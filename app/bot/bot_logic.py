"""
LÓGICA DEL BOT
==============
Máquina de estados genérica: capta nombre → pregunta necesidad →
según la respuesta, recolecta datos de venta, agenda una cita, o deriva
a un humano. Al final, avisa al negocio (`notificaciones.avisar_dueno`,
que reparte entre sus áreas).

Esto es lo que se reutiliza tal cual entre negocios. Los TEXTOS que se
envían son de cada negocio y se leen de `config`, no de aquí.
"""

import unicodedata
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.integrations import calendar_service
from app import config
from app.core import message_log
# ⚠️  Los textos del bot los escribe el DUEÑO, así que sus huecos se
# rellenan con esto y NUNCA con `str.format`: una llave que format no
# reconozca —`{9 a 6}`, un `{name}` donde no tocaba— levanta un KeyError
# que deja al cliente sin ninguna respuesta. Ver `app/core/huecos.py`.
from app.core.huecos import rellenar
from app.bot import cerebro
# Solo sus utilidades de texto (normalizar, palabras con peso), para que
# "volver al menú" se compare igual que el título de un botón escrito.
from app.bot.cerebro import menu as entender
from app.bot import notificaciones
from app.core import tenencia
from app.integrations import sheets_service
from app.integrations.calendar_service import CalendarNoDisponible
from app.core.database import get_session, ahora_utc, Contact, Lead, ProcessedMessage
from app.bot import whatsapp_client as wa
# La agenda de las barberías (§6 de su especificación). Solo desvía a los
# negocios con `proveedor_agenda = "barberia"`; los demás no pasan por ahí.
from app.barberia import bot as barberia_bot


def handle_incoming_message(
    phone: str,
    message_type: str,
    text: str = None,
    button_id: str = None,
    message_id: str = None,
    list_id: str = None,
    media: dict = None,
    perfil: str = None,
):
    """
    Punto de entrada: se llama por cada mensaje entrante ya parseado
    desde el webhook (main.py). Decide qué responder según el estado
    actual del contacto.

    `media` es la ficha de un archivo adjunto (ver main._leer_adjunto), o
    None. Puede venir acompañada de `text` si la imagen traía pie de foto.
    """
    session = get_session()
    try:
        # 1. ¿Ya procesamos este mensaje? (Meta reintenta los webhooks)
        if message_id and _mensaje_duplicado(session, message_id):
            print(f"[bot_logic] Mensaje {message_id} ya procesado, se ignora.")
            return

        contact = _get_or_create_contact(session, phone)

        # Una reacción (👍 a un mensaje del bot) no es una pregunta ni un
        # archivo: se guarda en el historial para que el panel la vea, y
        # nada más. Ni se contesta —antes recibía "¡Gracias! Ya lo
        # recibí" con dos botones, un mensaje absurdo y, desde el 1-oct,
        # cobrado— ni cuenta como actividad que mueva la conversación.
        if (media or {}).get("tipo") == "reaction":
            if media.get("emoji"):
                message_log.registrar(phone, "entrante", "cliente",
                                      media["emoji"])
            session.commit()
            return

        _detectar_origen(contact, text)

        # ¿Estaba ya fría la conversación ANTES de este mensaje? Hay que
        # preguntarlo aquí, antes de registrar lo que acaba de llegar: si
        # no, el mensaje que estamos procesando contaría como actividad
        # reciente y una conversación abandonada hace días nunca volvería
        # al bot.
        venia_fria = _conversacion_manual_fria(contact)

        # Guardamos lo que dijo el cliente para poder verlo en el panel.
        # Si tocó un botón o una lista, anotamos cuál: si no, la
        # conversación se vería con huecos.
        entrante = text or (f"[tocó: {button_id}]" if button_id else None) \
            or (f"[eligió: {list_id}]" if list_id else None)
        message_log.registrar(
            phone, "entrante", "cliente", entrante,
            media_id=(media or {}).get("media_id"),
            media_tipo=(media or {}).get("tipo"),
            media_mime=(media or {}).get("mime"),
            media_nombre=(media or {}).get("nombre"),
            media_bytes=(media or {}).get("bytes"),
        )

        # Cuánto llevaba callado el cliente. Se calcula ANTES de tocar
        # last_interaction, porque ese campo aún tiene la hora del mensaje
        # anterior.
        inactivo = ahora_utc() - (contact.last_interaction or ahora_utc())

        # 2. ¿Lo está atendiendo un humano? Entonces el bot no dice nada.
        if contact.atendido_por_humano:
            if venia_fria:
                _devolver_al_bot(contact, motivo="conversación fría")
            else:
                contact.last_interaction = ahora_utc()
                session.commit()
                print(f"[bot_logic] {phone} atendido por humano, el bot no responde.")
                return

        contact.last_interaction = ahora_utc()

        # 3. ¿Pide hablar con una persona? Vale en cualquier punto del flujo.
        if _pide_atencion_humana(text):
            _escalar_a_humano(contact, session, text)
            session.commit()
            return

        # 3a. ¿Pide volver al menú? También vale en cualquier punto: a
        # mitad de agendar, después de leer unos precios, o cuando el bot
        # le acaba de pedir que cuente su consulta. Quien escribe "quiero
        # volver al menú" no está contestando a lo que se le preguntó, y
        # tratarlo como respuesta —el detalle de la consulta, un día que
        # no existe— es no escucharle.
        #
        # Menos al principio: a quien aún no dijo su nombre no hay menú
        # que devolverle, y el saludo ya se lo va a ofrecer.
        if (contact.state not in ("NEW", "ASKED_NAME")
                and _pide_volver_al_menu(text)):
            _volver_al_menu(contact, session)
            session.commit()
            return

        # 3b. Respuesta a los botones que se ofrecen tras un adjunto. Se
        # atienden aquí y no en el despacho por estado porque un archivo
        # puede llegar en cualquier punto del flujo, y el estado del
        # contacto sigue siendo el que era antes de mandarlo.
        if button_id in (BOTON_MEDIA_MENU, BOTON_MEDIA_ASESOR):
            _responder_tras_media(contact, session, button_id)
            session.commit()
            return

        # 3b-bis. Los botones del recordatorio de una cita de barbería
        # ("Confirmo" / "Cancelar"). Como los de arriba, pueden llegar en
        # cualquier punto del flujo: el recordatorio sale solo, horas después.
        if (button_id or "").startswith((barberia_bot.BOTON_CONFIRMO,
                                         barberia_bot.BOTON_CANCELO)):
            barberia_bot.respuesta_recordatorio(contact, session, button_id)
            session.commit()
            return

        # 3c. Llegó un archivo. El bot no lo interpreta: acusa recibo,
        # avisa de que lo mirará una persona y deja al cliente elegir si
        # sigue con el menú o prefiere que lo atiendan.
        if media:
            _handle_media(contact, session, media)
            session.commit()
            return

        # 4. ¿Retomó una conversación que dejó a medias hace mucho?
        # Se reinicia el flujo: los botones de aquel mensaje ya quedaron
        # enterrados en su chat y no puede responder a lo que se le pidió.
        if (contact.state not in ("NEW", "DONE")
                and inactivo > timedelta(hours=config.CONVERSATION_TIMEOUT_HOURS)):
            print(f"[bot_logic] {phone} vuelve tras {inactivo.days} día(s); "
                  f"se reinicia el flujo.")
            contact.state = "NEW"

        state = contact.state

        if state == "NEW":
            _handle_new(contact, session, perfil)

        elif state == "ASKED_NAME":
            _handle_name_response(contact, session, text)

        elif state == "ASKED_NEED":
            # El menú es una lista, así que la respuesta llega en list_id.
            # Se acepta button_id también por si Meta reenvía un webhook
            # viejo de cuando el menú eran botones.
            _handle_need_response(contact, session, button_id, list_id, text)

        elif state == "ASKING_DATE":
            _handle_appointment_date(contact, session, list_id, text)

        elif state == "ASKING_TIME":
            # Los horarios llegan como botón si eran 3 o menos, y como
            # fila de lista si eran más.
            _handle_appointment_time(contact, session, button_id or list_id, text)

        elif state == "ASKING_OTHER_DETAIL":
            _handle_other_detail(contact, session, text)

        elif state in barberia_bot.ESTADOS:
            # Agendando en una barbería: sede, servicio, barbero, día, hora.
            barberia_bot.manejar(contact, session, button_id or list_id, text)

        else:
            # Conversación ya cerrada (DONE) y el cliente vuelve a escribir.
            _handle_returning(contact, session, text)

        session.commit()
    finally:
        session.close()


# ── Toma de control manual (atendido por humano) ─────────────────────

def _mensaje_duplicado(session, message_id: str) -> bool:
    """
    Marca el mensaje como procesado. Devuelve True si YA estaba.

    Se apoya en el índice único de processed_messages en vez de un
    "SELECT y luego INSERT": así dos webhooks simultáneos con el mismo
    mensaje no se cuelan los dos por la rendija entre consulta e inserción.
    """
    session.add(ProcessedMessage(message_id=message_id))
    try:
        session.commit()
        return False
    except IntegrityError:
        session.rollback()
        return True


def _detectar_origen(contact: Contact, text: str):
    """
    Deduce de dónde llegó el cliente por el mensaje precargado del botón.

    Solo lo escribe si el contacto sigue en el origen por defecto: así el
    primer canal por el que llegó no se pisa si más adelante vuelve a
    escribir desde otro botón. Si el cliente borró el mensaje precargado
    antes de enviarlo, no hay nada que detectar y queda como "directo".
    """
    if not text or contact.origen not in (None, config.ORIGEN_POR_DEFECTO):
        return

    normalizado = _normalizar(text)
    for clave, datos in config.ORIGENES.items():
        if _normalizar(datos["marcador"]) in normalizado:
            contact.origen = clave
            print(f"[bot_logic] {contact.phone} llegó por '{clave}'.")
            return


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar contra las palabras clave."""
    sin_tildes = unicodedata.normalize("NFD", texto)
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    return sin_tildes.lower().strip()


def _pide_atencion_humana(text: str) -> bool:
    if not text:
        return False
    normalizado = _normalizar(text)
    return any(_normalizar(clave) in normalizado for clave in config.HUMAN_TAKEOVER_KEYWORDS)


def _pide_volver_al_menu(text: str) -> bool:
    """
    ¿Escribió una de las frases que lo devuelven al menú principal?

    NO se compara como `_pide_atencion_humana`, que busca la frase en
    cualquier sitio del mensaje. Aquí eso sería una trampa cara: "menú" está
    dentro de "quiero cambiar el menú de mi restaurante", que es una
    consulta de venta, y dentro de "menudo". Por eso:

      - una frase de varias palabras cuenta si aparece ENTERA y con sus
        palabras completas: "volver al menú" en "¿puedo volver al menú?".
      - una palabra sola cuenta solo si es lo único con peso que escribió:
        "Menú", "menú porfa", "Inicio 🙏". No en "el menú de mi local".
    """
    if not text or not text.strip():
        return False

    escrito = entender.normalizar(text)
    peso = entender.palabras(text)

    for frase in config.PALABRAS_MENU:
        frase = entender.normalizar(frase)
        if not frase:
            continue
        if " " in frase:
            if f" {frase} " in f" {escrito} ":
                return True
        elif peso and peso == entender.palabras(frase):
            return True
    return False


def _marcar_atendido_por_humano(contact: Contact):
    """
    Silencia al bot para este contacto. No envía nada: quien llama decide
    qué mensajes mandar, porque el escalamiento por palabra clave y el
    final de la rama "Otra consulta" avisan cosas distintas.
    """
    contact.atendido_por_humano = True
    contact.takeover_at = ahora_utc()
    contact.state = "HUMANO"


def _conversacion_manual_fria(contact: Contact) -> bool:
    """
    ¿Lleva la conversación parada por los DOS lados el tiempo suficiente
    como para que el bot la retome?

    Se mide desde lo último que ocurrió, venga de quien venga: el último
    mensaje del cliente, la última respuesta manual, o el momento en que
    se tomó la conversación. Mientras cualquiera de los dos siga vivo, el
    bot no interrumpe.

    Es la parte delicada de todo el takeover. Medirlo solo desde la
    respuesta manual hacía que un asesor que tardaba media hora perdiera
    la conversación: el bot se despertaba justo cuando el cliente por fin
    contestaba, y lo saludaba desde cero. Medirlo solo desde el cliente
    tenía el problema opuesto: quien insistía cada pocos minutos dejaba
    al bot mudo para siempre.
    """
    if not contact.atendido_por_humano:
        return False

    momentos = [
        m for m in (
            contact.takeover_at,
            message_log.ultima_respuesta_manual(contact.phone),
            message_log.ultimo_mensaje_del_cliente(contact.phone),
        )
        if m is not None
    ]
    if not momentos:
        # Marcada como atendida pero sin ninguna fecha: no se puede medir,
        # así que se deja como está en vez de soltarla por sorpresa.
        return False

    limite = timedelta(minutes=config.HUMAN_TAKEOVER_TIMEOUT_MINUTES)
    return (ahora_utc() - max(momentos)) > limite


def liberar_conversaciones_vencidas() -> int:
    """
    Devuelve al bot las conversaciones que llevan demasiado tiempo tomadas
    sin respuesta. Devuelve cuántas liberó.

    Hace falta además de la comprobación al recibir un mensaje: si el
    cliente no vuelve a escribir, aquella nunca se ejecuta y la
    conversación se quedaría marcada para siempre. El panel llama a esto
    al pintarse, así que se ve al día sin tareas en segundo plano.
    """
    session = get_session()
    try:
        pendientes = session.query(Contact).filter(
            Contact.atendido_por_humano.is_(True)
        ).all()

        liberadas = 0
        for contact in pendientes:
            if _conversacion_manual_fria(contact):
                _devolver_al_bot(
                    contact,
                    motivo=f"{config.HUMAN_TAKEOVER_TIMEOUT_MINUTES} min sin "
                           f"actividad por ninguna de las dos partes")
                liberadas += 1

        if liberadas:
            session.commit()
        return liberadas
    finally:
        session.close()


def _devolver_al_bot(contact: Contact, motivo: str):
    """
    Devuelve la conversación al bot.

    Queda en DONE, no en NEW. La diferencia se nota cuando el cliente
    vuelve a escribir: NEW lo saludaba desde cero ("¡Hola! ¿cómo te
    llamas?") a alguien con quien un asesor acababa de hablar y cuyo
    nombre ya sabíamos. DONE lo lleva a `_handle_returning`, que lo
    reconoce, le ofrece el menú directamente y, si tenía una cita, lo
    pasa otra vez a un asesor.
    """
    contact.atendido_por_humano = False
    contact.takeover_at = None
    contact.state = "DONE"
    print(f"[bot_logic] {contact.phone} devuelto al bot por {motivo}.")


def _escalar_a_humano(contact: Contact, session, text: str):
    """El cliente pidió hablar con una persona en medio del flujo."""
    lead = Lead(contact_id=contact.id, type="otro", detail=text, status="pendiente")
    session.add(lead)

    _marcar_atendido_por_humano(contact)

    wa.send_text_message(contact.phone, config.HUMAN_TAKEOVER_MESSAGE)
    nombre = contact.name or "(sin nombre aún)"
    notificaciones.avisar_dueno(
        rellenar(config.OWNER_NOTIFICATION_TAKEOVER,
            name=nombre,
            phone=contact.phone,
            detail=text,
            origen=contact.origen or config.ORIGEN_POR_DEFECTO,
        ),
        ["cliente esperando respuesta", nombre, contact.phone, text or "-"],
        servicio=contact.servicio,
    )
    lead.status = "notificado"
    _registrar_en_sheet(contact, lead)


# ── API para el panel de administración (admin_api.py) ───────────────

def tomar_control_manual(phone: str) -> bool:
    """Marca un contacto como atendido por humano. False si no existe."""
    session = get_session()
    try:
        contact = session.query(Contact).filter_by(phone=phone).first()
        if not contact:
            return False
        _marcar_atendido_por_humano(contact)
        session.commit()
        print(f"[bot_logic] {phone} marcado como atendido por humano (manual).")
        return True
    finally:
        session.close()


def devolver_control_al_bot(phone: str) -> bool:
    """Desmarca un contacto para que el bot vuelva a responderle."""
    session = get_session()
    try:
        contact = session.query(Contact).filter_by(phone=phone).first()
        if not contact:
            return False
        _devolver_al_bot(contact, motivo="acción manual")
        session.commit()
        return True
    finally:
        session.close()


def listar_contactos(solo_humanos: bool = False) -> list:
    """Devuelve los contactos y su estado, para el panel del dueño."""
    session = get_session()
    try:
        consulta = session.query(Contact)
        if solo_humanos:
            consulta = consulta.filter(Contact.atendido_por_humano.is_(True))

        return [
            {
                "phone": c.phone,
                "name": c.name,
                "state": c.state,
                "origen": c.origen,
                "atendido_por_humano": c.atendido_por_humano,
                "takeover_at": c.takeover_at.isoformat() if c.takeover_at else None,
                "last_interaction": (
                    c.last_interaction.isoformat() if c.last_interaction else None
                ),
            }
            for c in consulta.order_by(Contact.last_interaction.desc()).all()
        ]
    finally:
        session.close()


# ── Pasos de la máquina de estados ───────────────────────────────────

def _get_or_create_contact(session, phone: str) -> Contact:
    contact = session.query(Contact).filter_by(phone=phone).first()
    if not contact:
        contact = Contact(phone=phone, state="NEW")
        session.add(contact)
        try:
            session.commit()
        except IntegrityError:
            # Dos mensajes del mismo número nuevo, casi a la vez: el otro
            # hilo lo creó primero. Es el mismo contacto, no un error — sin
            # esto, el segundo mensaje se quedaba sin respuesta.
            session.rollback()
            contact = session.query(Contact).filter_by(phone=phone).one()
    return contact


def _en_una_linea(texto: str, largo: int = 80) -> str:
    """
    Un nombre como se guarda: en una línea y con tope.

    Lo escribe el cliente (o viene de su perfil de WhatsApp) y acaba en el
    asunto del correo de aviso, en el Sheet y en la cabecera del panel. Un
    salto de línea en el asunto hacía que el aviso por correo no saliera.
    """
    return " ".join((texto or "").split())[:largo]


def _handle_new(contact: Contact, session, perfil: str = None):
    """
    El primer mensaje de alguien que nunca ha escrito.

    Preguntarle el nombre es un mensaje más antes de poder venderle, y casi
    todo el mundo lo tiene puesto en su WhatsApp. Si el negocio prefiere no
    preguntarlo (`config.PEDIR_NOMBRE`), se usa ese y se va directo al
    menú.

    El perfil puede no venir —Meta no lo garantiza, y hay quien no tiene
    nombre puesto—, así que en ese caso se pregunta igual: quedarse sin
    nombre estropea todos los textos que lo usan y el registro del lead.
    """
    nombre = _en_una_linea(perfil)

    if not config.PEDIR_NOMBRE and nombre:
        contact.name = nombre
        contact.state = "ASKED_NEED"
        _enviar_menu(contact, rellenar(config.WELCOME_MESSAGE, name=contact.name),
                     session)
        return

    wa.send_text_message(contact.phone, config.WELCOME_MESSAGE)
    contact.state = "ASKED_NAME"


# ── Archivos que manda el cliente ────────────────────────────────────
#
# El bot NO interpreta lo que le mandan: no mira las imágenes ni escucha
# los audios. Su trabajo aquí es que no se pierda nada y que el cliente no
# se quede esperando en silencio.

BOTON_MEDIA_MENU = "media_menu"
BOTON_MEDIA_ASESOR = "media_asesor"


def _handle_media(contact: Contact, session, media: dict):
    """
    Llegó una imagen, una nota de voz o un documento.

    Se acusa recibo y se le dan dos salidas: seguir con el menú o que lo
    atienda una persona. **No se marca como atendido por humano aquí**: si
    el cliente solo mandaba una foto de referencia y quiere seguir viendo
    precios, silenciar al bot lo dejaría tirado. Que lo decida él.

    El archivo ya quedó registrado antes de llegar aquí, así que el aviso
    al celular del dueño ya salió aunque el cliente no toque ningún botón.
    """
    texto = {
        "image": config.MEDIA_RECIBIDA_IMAGEN,
        "audio": config.MEDIA_RECIBIDA_AUDIO,
        "document": config.MEDIA_RECIBIDA_DOCUMENTO,
    }.get(media.get("tipo"), config.MEDIA_RECIBIDA_OTRO)

    wa.send_button_message(contact.phone, texto, [
        {"id": BOTON_MEDIA_MENU, "title": config.MEDIA_BOTON_MENU},
        {"id": BOTON_MEDIA_ASESOR, "title": config.MEDIA_BOTON_ASESOR},
    ])

    # El estado no se toca: si el cliente ignora los botones y sigue
    # escribiendo, la conversación continúa donde la había dejado.


def _responder_tras_media(contact: Contact, session, button_id: str):
    """Lo que eligió el cliente después de mandarnos un archivo."""
    if button_id == BOTON_MEDIA_ASESOR:
        _escalar_a_humano(contact, session, config.MEDIA_DETALLE_ASESOR)
        return

    # Quiere seguir con el menú. Si es la primera vez que escribe y su
    # primer mensaje fue la foto, todavía no sabemos ni cómo se llama:
    # se empieza por el principio en vez de soltarle el menú a un
    # desconocido.
    if not contact.name:
        contact.state = "NEW"
        _handle_new(contact, session)
        return

    _enviar_menu(contact, rellenar(config.ASK_NEED_MESSAGE, name=contact.name), session)


def _handle_returning(contact: Contact, session, text: str):
    """
    El cliente vuelve a escribir con la conversación ya cerrada.

    Antes se reiniciaba el flujo entero, así que a quien preguntaba algo
    después de agendar le respondía "cuéntame tu nombre" — sabiendo ya
    cómo se llama. Ahora:

    - Si su última gestión fue una cita, pasa a un asesor: quien vuelve
      tras agendar pregunta por la dirección, el enlace o un cambio de
      hora, y nada de eso lo sabe el bot.
    - Si no, se le ofrece el menú directamente, sin volver a pedirle el
      nombre.

    Y en los dos casos, si lo que escribe ES una opción —"quiero una
    página web"—, se hace eso en vez de enseñarle el menú para que la
    busque. Ya dijo lo que quería.
    """
    if not contact.name:
        # Nunca llegó a decirnos su nombre: empezamos de cero.
        contact.state = "NEW"
        _handle_new(contact, session)
        return

    tras_cita = _viene_de_una_cita(session, contact)

    # Tras una cita solo se acepta que elija una opción, no una respuesta
    # libre de la IA: quien vuelve después de agendar pregunta por SU
    # reunión, y el modelo no sabe nada de ella. Contestaría inventando.
    if _entender_texto(contact, session, text, con_respuesta=not tras_cita):
        return

    if tras_cita:
        _escalar_a_humano(contact, session, text)
        return

    _enviar_menu(contact, rellenar(config.WELCOME_BACK_MESSAGE, name=contact.name), session)


def _viene_de_una_cita(session, contact: Contact) -> bool:
    """
    ¿Su última gestión fue una cita, y el negocio pasa esos a una persona?

    Quien escribe después de agendar casi siempre pregunta por su reunión
    —el enlace, la dirección, cambiarla— y nada de eso lo sabe el bot.
    """
    if not config.TAKEOVER_AFTER_APPOINTMENT:
        return False
    ultimo = (session.query(Lead)
              .filter_by(contact_id=contact.id)
              .order_by(Lead.id.desc())
              .first())
    return ultimo is not None and ultimo.type == "cita"


def _handle_name_response(contact: Contact, session, text: str):
    name = _en_una_linea(text).title()

    # Sin texto no hay nombre que guardar. Antes se caía en "Cliente", y
    # bastaba con que el cliente mandara un sticker o una ubicación justo
    # en este paso para perder su nombre real de por vida: el bot ya no lo
    # vuelve a preguntar, y el lead llegaba al dueño y al Sheet llamándose
    # "Cliente". Se le pregunta otra vez, que es lo que haría una persona.
    if not name:
        wa.send_text_message(contact.phone, config.WELCOME_MESSAGE)
        return

    contact.name = name
    _enviar_menu(contact, rellenar(config.ASK_NEED_MESSAGE, name=contact.name), session)


# A quién ya se le avisó de que su bot está sin armar. En memoria y por
# (negocio, teléfono): se pierde al reiniciar, y eso está bien — lo que se
# evita es avisar en CADA mensaje de la misma persona, no llevar un
# registro. Un negocio sin contenido es una situación de horas, no de
# meses.
_AVISADOS_SIN_CONTENIDO = set()


def _sin_contenido(contact: Contact):
    """
    Qué hace el bot de un negocio al que todavía no le armaron el menú.

    Nace en blanco a propósito (ver `superadmin.alta`), así que entre la
    creación y el primer menú hay una ventana en la que puede escribir un
    cliente real. Se le responde con cortesía —nunca silencio, que es lo
    que hace que alguien se vaya a la competencia— y se avisa al dueño,
    porque para él eso es un lead que se está perdiendo.
    """
    wa.send_text_message(contact.phone, config.SIN_CONTENIDO_MESSAGE)

    quien = (tenencia.actual_o_none(), contact.phone)
    if quien in _AVISADOS_SIN_CONTENIDO:
        return
    _AVISADOS_SIN_CONTENIDO.add(quien)

    print(f"[bot_logic] {contact.phone} escribió a un negocio SIN MENÚ "
          f"configurado. Se respondió con el texto de cortesía.")
    try:
        # Sin `servicio` a propósito, y no por olvido: esto no es un lead
        # de un área, es un aviso de que el bot está a medio configurar.
        # Mandárselo a Ventas porque el cliente venía de Ventas sería
        # avisarle al que no puede arreglarlo. Va al área general.
        notificaciones.avisar_dueno(
            f"📭 Te escribió {contact.phone} y tu bot todavía no tiene menú. "
            f"Se le respondió con el mensaje de cortesía. "
            f"Ármalo en el panel para que atienda de verdad.", [])
    except Exception as e:
        # Que no se pueda avisar al dueño no puede impedir responderle al
        # cliente, que es lo único que él nota.
        print(f"[bot_logic] No se pudo avisar al dueño: {e}")


def _enviar_menu(contact: Contact, texto: str, session=None):
    """
    Manda el menú principal de servicios.

    Necesita la sesión para saber si el cliente tiene una reunión pendiente
    y decidir si le ofrece gestionarla.
    """
    if not config.NEED_OPTIONS:
        _sin_contenido(contact)
        return

    cita = _cita_activa(session, contact) if session is not None else None
    _enviar_opciones(contact, texto,
                     _opciones_para_mostrar(config.NEED_OPTIONS, cita=cita))


def _cita_activa(session, contact: Contact):
    """
    La reunión vigente del cliente, o None si no tiene.

    Vigente = la última cita que creó y que no ha cancelado. No se filtra
    por fecha a propósito: quien acaba de perderse una reunión de esta
    mañana también necesita poder gestionarla.
    """
    return (session.query(Lead)
            .filter_by(contact_id=contact.id, type="cita")
            .filter(Lead.status != "cancelada")
            .order_by(Lead.id.desc())
            .first())


def _opciones_para_mostrar(opciones: list, incluir_ocultas: bool = False,
                           cita=None) -> list:
    """
    Descarta las opciones que ahora mismo no se deben ofrecer.

    - "oculta": solo se llega a ellas desde el "luego" de otra opción, no
      desde el menú donde están declaradas. Sirve para no gastar uno de
      los tres botones en algo que encaja mejor más adelante.
    - Sin la URL o sin el texto configurados: se esconde en vez de mandar
      la portada como si fuera lo que se le prometió al cliente, o un
      mensaje en blanco. Así se puede dejar la opción escrita en config y
      que aparezca sola el día que se llene su contenido.
    """
    visibles = []
    for opcion in opciones:
        if opcion.get("oculta") and not incluir_ocultas:
            continue
        # "Mi cita agendada" solo tiene sentido si de verdad hay una: a
        # quien nunca agendó le ensuciaría el menú con una opción que solo
        # puede llevarle a "no encontramos ninguna reunión".
        if opcion.get("solo_con_cita") and cita is None:
            continue
        if opcion.get("accion") in ("enlace", "info"):
            # El "True" por defecto es para no esconder las opciones que
            # ni siquiera declaran esa clave: solo se juzga lo declarado.
            if not opcion.get("url", True) or not opcion.get("mensaje", True):
                continue
        visibles.append(opcion)
    return visibles


def _enviar_opciones(contact: Contact, texto: str, opciones: list):
    """
    Manda un grupo de opciones, eligiendo el formato según cuántas sean.

    Hasta 3 van como BOTONES: se ven directo en el chat y el cliente
    responde de un toque. WhatsApp no admite un cuarto botón, así que de
    ahí en adelante hay que usar la LISTA, que llega a 10 pero obliga a
    abrirla primero.
    """
    # Sin ninguna opción no se manda un interactivo: Meta exige al menos
    # una y rechazaría el mensaje ENTERO, así que el cliente se quedaría
    # sin el texto también. Pasa cuando todas las opciones de un grupo se
    # esconden por no tener contenido (ver `_opciones_para_mostrar`), y
    # antes era una de las formas de que un botón no hiciera nada.
    if not opciones:
        print(f"[bot_logic] {contact.phone}: no quedó ninguna opción que "
              f"ofrecer; se manda solo el texto.")
        wa.send_text_message(contact.phone, texto)
    elif len(opciones) <= 3:
        wa.send_button_message(contact.phone, texto, opciones)
    else:
        wa.send_list_message(
            contact.phone,
            texto,
            config.NEED_LIST_BUTTON,
            opciones,
            config.NEED_LIST_SECTION,
        )
    contact.state = "ASKED_NEED"


def _decir_y_ofrecer(contact: Contact, texto: str, pregunta: str,
                     opciones: list):
    """
    Manda un texto y unas opciones **en un solo mensaje** cuando caben.

    Es el patrón más repetido del bot: dice algo (los precios, la cita
    confirmada) y acto seguido pregunta cómo seguir. Salían dos mensajes,
    y desde el **1-oct-2026** Meta cobra cada uno: ese segundo envío era
    una línea del recibo de cada cliente, todos los días, sin aportar
    nada que no cupiera en el primero. El cuerpo de un mensaje con
    botones ES texto.

    LO QUE NO SE PUEDE HACER es juntarlo siempre. El cuerpo interactivo
    admite 1024 caracteres y un texto suelto 4096; pasarse no recorta,
    Meta **rechaza el mensaje entero** y el cliente se queda sin nada,
    que es peor que el mensaje que se quería ahorrar. Por eso, cuando no
    cabe, se vuelve a partir en dos.

    Esta función es el único sitio que conoce esa regla. Si aparece otra
    rama con el mismo patrón, que la use en vez de repetirla.
    """
    junto = f"{texto}\n\n{pregunta}" if pregunta else texto

    if len(junto) <= wa.LIMITE_CUERPO_INTERACTIVO:
        _enviar_opciones(contact, junto, opciones)
    else:
        wa.send_text_message(contact.phone, texto)
        _enviar_opciones(contact, pregunta, opciones)


def _ofrecer_cierre(contact: Contact, texto: str = ""):
    """
    Cierra un recorrido ofreciendo volver al menú o terminar.

    Se llama al final de las ramas que acaban en algo concreto (agendar,
    cancelar, reagendar). Sin esto el cliente se queda mirando el último
    mensaje sin saber si puede seguir pidiendo cosas.

    `texto` es lo que se dice ANTES —la cita confirmada, la cancelación—.
    Va aquí y no en un envío aparte para que las dos cosas viajen en un
    solo mensaje siempre que quepan.
    """
    if texto:
        _decir_y_ofrecer(contact, texto, config.CIERRE_MESSAGE,
                         config.CIERRE_OPTIONS)
    else:
        _enviar_opciones(contact, config.CIERRE_MESSAGE, config.CIERRE_OPTIONS)


# ── Las dos salidas que existen SIEMPRE ──────────────────────────────
#
# "Volver al menú principal" y "Atrás" se pueden ofrecer después de
# cualquier respuesta ("y le vuelve a ofrecer…"), y **no dependen de que
# el negocio las tenga escritas**. Antes solo se podían ofrecer las
# opciones HERMANAS —las del mismo grupo—, así que una rama honda podía
# dejar al cliente sin ninguna forma de volver: leía la respuesta y se
# quedaba ahí, con el menú principal a dos mensajes de distancia y sin
# ningún botón que llevara. Escribir a mano una opción "volver" en cada
# grupo era la única salida, y nadie se acuerda de hacerlo en todos.
#
# Empiezan por "__" para que no puedan chocar con un id de verdad: los
# que genera el editor salen de `idLibre`, que solo deja letras, números
# y guión bajo, y nunca empieza por guión bajo.
ID_VOLVER_MENU = "__menu__"
ID_ATRAS = "__atras__"

# "Atrás" lleva al grupo donde estaba el cliente, y ese dato viaja EN EL
# PROPIO BOTÓN (`__atras__:web_precios`) en vez de guardarse en el
# contacto. Así no hace falta una columna nueva ni recordar nada entre
# mensajes: el botón que se pulsa ya dice de dónde venía. Los ids de
# botón de Meta admiten 256 caracteres, de sobra.
SEPARADOR_ATRAS = ":"


def _opcion_fija(clave: str, desde_id: str = ""):
    """
    Una de las dos salidas fijas, ya lista para mandar, o None.

    `desde_id` es la opción cuyo "y le vuelve a ofrecer…" la está
    enseñando: es lo que le permite a "Atrás" saber a dónde volver.
    """
    if clave == ID_VOLVER_MENU:
        return {"id": ID_VOLVER_MENU, "title": config.BOTON_VOLVER_MENU,
                "accion": "menu"}
    if clave == ID_ATRAS:
        return {"id": ID_ATRAS + SEPARADOR_ATRAS + (desde_id or ""),
                "title": config.BOTON_ATRAS, "accion": "atras"}
    return None


def _grupo_de(opcion_id: str):
    """
    El grupo al que pertenece una opción: `(la opción padre, sus hermanas)`.

    El padre es None cuando la opción cuelga del menú principal, que es
    justo lo que hace falta saber para que "Atrás" ofrezca el menú de
    arriba en vez de un submenú que no existe.
    """
    def buscar(lista, padre):
        for opcion in lista or []:
            if opcion.get("id") == opcion_id:
                return padre, lista
            encontrado = buscar(opcion.get("submenu"), opcion)
            if encontrado is not None:
                return encontrado
        return None

    return buscar(config.NEED_OPTIONS, None) or (None, [])


def _todas_las_opciones():
    """
    Recorre el menú entero, a la profundidad que tenga.

    Como los ids son únicos, con esto basta para saber qué tocó el cliente
    sin recordar en qué submenú estaba.

    Antes bajaba **exactamente dos niveles**, que era lo que el editor de
    contenido dejaba armar. Un tercer nivel se dibujaba y se enviaba, pero
    al pulsarlo no se encontraba la opción: el cliente recibía el mensaje
    de "no entendí" y en el log quedaba "acción desconocida". Ahora baja
    hasta el fondo, que es lo que permite armar el mapa por pasos.
    """
    def recorrer(opciones):
        for opcion in opciones or []:
            yield opcion
            yield from recorrer(opcion.get("submenu"))

    yield from recorrer(config.NEED_OPTIONS)
    yield from recorrer(config.CIERRE_OPTIONS)


def _opcion_elegida(opcion_id: str):
    """Busca en config la opción que tocó el cliente. None si no existe."""
    if not opcion_id:
        return None

    # Las dos salidas fijas no están en el menú de nadie: se reconocen
    # por su id. "Atrás" llega con el sitio del que viene pegado detrás
    # (`__atras__:web_precios`), así que se parte por el separador.
    if opcion_id == ID_VOLVER_MENU:
        return _opcion_fija(ID_VOLVER_MENU)
    if opcion_id.startswith(ID_ATRAS):
        desde = opcion_id[len(ID_ATRAS) + len(SEPARADOR_ATRAS):] \
            if SEPARADOR_ATRAS in opcion_id else ""
        return {"id": opcion_id, "title": config.BOTON_ATRAS,
                "accion": "atras", "desde": desde}

    for opcion in _todas_las_opciones():
        if opcion["id"] == opcion_id:
            return opcion
    return None


def _servicio_del_contacto(contact: Contact):
    """La opción de primer nivel que eligió, o None si aún no eligió."""
    if not contact.servicio:
        return None
    for opcion in config.NEED_OPTIONS:
        if opcion["id"] == contact.servicio:
            return opcion
    # El id ya no existe en config (se renombró la opción). No es un error:
    # el contacto simplemente pierde la pista de su servicio.
    return None


def _anotar_recorrido(contact: Contact, elegida: dict):
    """
    Deja constancia de por dónde va el cliente, para la columna
    "Recorrido" del Sheet.

    Al elegir un servicio del menú principal el recorrido empieza de cero:
    si alguien mira chatbots y luego se pasa a Power BI, mezclar los pasos
    de los dos daría una fila que no describe a nadie.
    """
    # Una opción del MENÚ PRINCIPAL es un servicio, lleve o no `sheet`.
    #
    # Antes solo contaba si traía `sheet`, que es una clave del
    # negocio.toml que el mapa no escribe nunca. En cualquier negocio con
    # el menú armado en el mapa el bot no sabía qué había elegido el
    # cliente: los avisos no se repartían por área y los leads caían en la
    # pestaña "otros" del Sheet. Y ahora de esto depende qué área ve la
    # conversación (`app/core/equipo.py`).
    es_servicio = elegida.get("sheet") or any(
        o.get("id") == elegida.get("id") for o in config.NEED_OPTIONS)
    if es_servicio:
        contact.servicio = elegida["id"]
        contact.recorrido = None
        return

    paso = elegida.get("paso")
    if not paso:
        return

    pasos = [p for p in (contact.recorrido or "").split(" > ") if p]
    # Sin esto, quien toca dos veces el mismo botón lo ve repetido.
    if not pasos or pasos[-1] != paso:
        pasos.append(paso)
    contact.recorrido = " > ".join(pasos)[:500]


def _handle_need_response(contact: Contact, session, button_id: str,
                          list_id: str = None, text: str = None):
    elegida = _opcion_elegida(list_id or button_id)

    if elegida is not None:
        _ejecutar_opcion(contact, session, elegida)
        return

    # Escribió texto libre en vez de elegir del menú, o eligió una opción
    # que ya no existe (un menú viejo que tenía a la vista).
    #
    # Si su última gestión fue una cita, casi siempre está preguntando por
    # ella —el enlace, la hora, cambiarla— y nada de eso lo sabe el bot.
    # Responderle "no entendí" ahí es lo peor que puede hacer. Pero si lo
    # que escribió ES una opción ("quiero ver los precios"), se hace eso:
    # pasarle a una persona a quien ya dijo lo que quería es hacerle
    # esperar para nada.
    tras_cita = _viene_de_una_cita(session, contact)

    if _entender_texto(contact, session, text, con_respuesta=not tras_cita):
        return

    if tras_cita:
        _escalar_a_humano(contact, session, text)
        return

    _no_entendi(contact, session)


def _entender_texto(contact: Contact, session, text: str,
                    con_respuesta: bool = True) -> bool:
    """
    Intenta hacer lo que el cliente pidió ESCRIBIENDO. True si lo atendió.

    Antes esto solo se intentaba con el menú a la vista (`ASKED_NEED`).
    Escribir "quiero una página web" después de haber agendado, a mitad
    de elegir un día, o al volver al día siguiente, recibía el menú o el
    "no entendí" sin mirar lo que decía. Ahora se pregunta en todos esos
    sitios, porque lo que el cliente espera es que se le haga caso esté
    donde esté.

    Quién entiende, según el plan (ver `cerebro.interpretar`):

      Básico   los títulos de los botones escritos a mano
               ("Página web" en "quiero una pagina web"). Sin red.
      Pro      Gemini, y si no sabe, lo mismo que el Básico.

    Además del menú entero se le ofrece "Menú principal", que no es
    opción de nadie: sin ella la IA no tendría cómo decir "quiere volver
    al principio" con otras palabras que las de `palabras_menu`.

    `con_respuesta=False` descarta lo que la IA conteste de su cosecha y
    solo acepta que elija una opción. Es para cuando lo que pregunta el
    cliente es algo que el modelo no puede saber (su cita).
    """
    if not text or not text.strip():
        return False

    opciones = list(_todas_las_opciones()) + [_opcion_fija(ID_VOLVER_MENU)]
    decision = cerebro.interpretar(contact, text, opciones)

    if decision.intencion:
        elegida = _opcion_elegida(decision.intencion)
        if elegida is None:
            return False
        print(f"[bot_logic] {contact.phone} escribió {text[:60]!r} → "
              f"'{elegida.get('id')}' ({decision.motivo}).")
        # Si estaba a mitad de agendar, eso se abandona: pidió otra cosa.
        contact.temp_data = None
        contact.state = "ASKED_NEED"
        _ejecutar_opcion(contact, session, elegida)
        return True

    if decision.respuesta and con_respuesta:
        # Preguntó algo que no es ninguna opción del menú. Se le responde
        # y se le vuelven a ofrecer las opciones, para que pueda seguir sin
        # tener que adivinar qué escribir.
        contact.temp_data = None
        wa.send_text_message(contact.phone, decision.respuesta)
        _enviar_menu(contact, rellenar(config.ASK_NEED_MESSAGE,
            name=contact.name or ""), session)
        return True

    return False


def _no_entendi(contact: Contact, session):
    """
    El "no entendí", y debajo el menú para que pueda seguir.

    Solo decía la frase. Quien no acertaba a escribir algo reconocible la
    recibía una vez, y otra, y otra, sin ningún botón a la vista —el menú
    se había quedado varios mensajes más arriba—. Desde el teléfono eso es
    un bot trabado.

    Va en UN solo mensaje siempre que quepa: la frase, "¿con qué quieres
    continuar?" y los botones. Son la misma respuesta, y desde el
    1-oct-2026 Meta cobra cada mensaje. `_decir_y_ofrecer` sabe partirlo
    si se pasa del tope del cuerpo interactivo.

    El negocio puede apagarlo (`menu_tras_no_entendi`) y cambiar los dos
    textos desde el mapa.
    """
    if not (config.MENU_TRAS_NO_ENTENDI and config.NEED_OPTIONS):
        wa.send_text_message(contact.phone, config.FALLBACK_MESSAGE)
        return

    opciones = _opciones_para_mostrar(config.NEED_OPTIONS,
                                      cita=_cita_activa(session, contact))
    _decir_y_ofrecer(
        contact, config.FALLBACK_MESSAGE,
        rellenar(config.NO_ENTENDI_MENU_MESSAGE, name=contact.name or ""),
        opciones)


def _volver_al_menu(contact: Contact, session):
    """
    Vuelve a empezar: el menú entero otra vez, sin pedirle el nombre.

    Lo usan el botón "Menú principal", la acción "Volver al menú" y las
    frases de `palabras_menu`, que valen en cualquier punto de la
    conversación.
    """
    contact.servicio = None
    contact.recorrido = None
    contact.temp_data = None

    if not contact.name:
        contact.state = "NEW"
        _handle_new(contact, session)
        return

    _enviar_menu(contact, rellenar(config.WELCOME_BACK_MESSAGE, name=contact.name), session)


def _ejecutar_opcion(contact: Contact, session, elegida: dict):
    """
    Hace lo que dice una opción del menú, la haya pulsado o escrito.

    Es el mismo camino para las dos cosas a propósito: lo que el cliente
    pide escribiendo tiene que salir igual —y anotarse igual en la columna
    "Recorrido" del Sheet— que lo que pide tocando.
    """
    _anotar_recorrido(contact, elegida)

    accion = elegida.get("accion")

    if accion == "submenu":
        # `{name}` se rellena también aquí. El editor dice "puedes usar
        # {name}" al lado de varios campos, y hasta ahora el mensaje de un
        # submenú era el único que lo mandaba literal: el cliente leía
        # "Hola {name}".
        mensaje = rellenar(elegida.get("mensaje") or config.ASK_NEED_MESSAGE,
                           name=contact.name)

        # El submenú de la cita nombra el día y la hora que tiene puestos,
        # para que confirme que va a tocar la reunión correcta.
        if elegida.get("solo_con_cita"):
            cita = _cita_activa(session, contact)
            if cita is None:
                wa.send_text_message(contact.phone, config.CITA_NO_ENCONTRADA_MESSAGE)
                _enviar_menu(contact, rellenar(config.WELCOME_BACK_MESSAGE,
                    name=contact.name), session)
                return
            mensaje = rellenar(
                mensaje,
                date=cita.appointment_date or "(por confirmar)",
                time=cita.appointment_time or "(por confirmar)",
            )

        _enviar_opciones(contact, mensaje, _opciones_para_mostrar(elegida["submenu"]))
        return

    if accion in ("cancelar", "reagendar"):
        _gestionar_cita(contact, session, accion)
        return

    if accion in ("enlace", "info"):
        # ⚠️  AQUÍ ESTABA EL "BOTÓN QUE NO RESPONDE".
        #
        # Esto era un `.format(url=…)` sobre el texto que escribió el
        # dueño. Cualquier otra llave —un `{name}`, que el propio editor
        # invita a usar, o un `{9 a 6}` al escribir un horario— levantaba
        # un KeyError, y ese KeyError lo recogía en `main` el `except
        # (KeyError, IndexError)` de los payloads mal formados. Resultado:
        # el cliente pulsaba y no recibía NADA, y el log culpaba a Meta.
        #
        # `rellenar` cambia lo que conoce y deja lo demás como está: un
        # hueco que nadie declaró se ve raro en el mensaje —que es una
        # pista para quien lo escribió— pero el cliente recibe respuesta.
        texto = rellenar(
            elegida.get("mensaje") or config.WEBSITE_MESSAGE,
            url=elegida.get("url") or config.BUSINESS_WEBSITE,
            name=contact.name,
        )

        # "info" además vuelve a ofrecer opciones, para que quien acaba de
        # leer los precios pueda avanzar sin tener que escribir nada.
        #
        # Entre ellas pueden ir las dos salidas fijas —"Menú principal" y
        # "Atrás"—, que no son opciones del menú de nadie: se arman aquí.
        # "Atrás" se lleva dentro el id de ESTA opción, que es lo que le
        # dice a dónde volver. Ver `OPCIONES_FIJAS` más arriba.
        siguientes = [_opcion_fija(i, elegida.get("id", "")) or _opcion_elegida(i)
                      for i in elegida.get("luego", [])]
        siguientes = _opciones_para_mostrar(
            [o for o in siguientes if o is not None], incluir_ocultas=True
        )

        if not siguientes:
            # Sin opciones que ofrecer, el texto va solo. Se queda en
            # ASKED_NEED a propósito: quien mira el enlace puede elegir
            # otra cosa del menú que ya tiene a la vista, sin reiniciar.
            wa.send_text_message(contact.phone, texto)
            return

        # ⚠️  Si no escribió pregunta, NO se dice nada. Antes caía en
        # `FALLBACK_MESSAGE`, que es el "Disculpa, no entendí bien 🤔",
        # así que a un cliente que acababa de pulsar un botón y recibir
        # justo lo que pidió se le contestaba que no se le había
        # entendido. Aquí no ha fallado nada: se le enseña su texto y
        # debajo los botones, y ya está.
        #
        # Salía en cuanto una opción tenía a quién ofrecer después, así
        # que se destapó al aparecer "Atrás" y "Menú principal" (§3.17):
        # de golpe, opciones que nunca habían tenido `luego` lo tenían.
        pregunta = rellenar(elegida.get("pregunta") or "", name=contact.name)

        # Los precios y el "¿cómo quieres seguir?" viajan juntos siempre
        # que quepan. Preguntar precios es lo más común que hace un
        # cliente, así que este es el ahorro que más se nota.
        _decir_y_ofrecer(contact, texto, pregunta, siguientes)
        return

    if accion == "cita":
        if not _ofrecer_dias(contact, session):
            # Google no respondió: registramos la solicitud igual, para
            # que el cliente no se quede sin respuesta.
            _registrar_cita_manual(contact, session, motivo="Calendar caído")
        return

    if accion == "humano":
        # Dos formas, y la elige el negocio en el mapa:
        #
        #   pide detalle   "cuéntame tu duda" → espera → avisa. Lo de
        #                  siempre, y el valor por defecto.
        #   directo        avisa YA y le dice que en un momento le
        #                  escriben. Quien llega a este botón ya recorrió
        #                  el menú hasta aquí: se sabe qué quiere, y
        #                  pedírselo otra vez es un mensaje que sobra.
        if not config.ASESOR_PIDE_DETALLE:
            _pasar_directo_a_asesor(contact, session, elegida)
            return
        wa.send_text_message(contact.phone,
                             rellenar(config.OTHER_QUERY_MESSAGE, name=contact.name))
        contact.state = "ASKING_OTHER_DETAIL"
        return

    if accion == "menu":
        _volver_al_menu(contact, session)
        return

    if accion == "atras":
        # Al grupo del que venía: las opciones HERMANAS de aquella por
        # la que llegó. Si esa opción colgaba del menú principal, atrás ES
        # el menú principal.
        padre, hermanas = _grupo_de(elegida.get("desde", ""))

        if padre is None:
            _enviar_menu(contact, rellenar(config.ASK_NEED_MESSAGE,
                                           name=contact.name), session)
            return

        # El mismo texto con el que se ofreció ese grupo la primera vez:
        # volver atrás tiene que devolver a un sitio reconocible, no a
        # una pantalla que el cliente no ha visto nunca.
        _enviar_opciones(
            contact,
            rellenar(padre.get("mensaje") or config.ASK_NEED_MESSAGE,
                     name=contact.name),
            _opciones_para_mostrar(hermanas, cita=_cita_activa(session, contact)),
        )
        return

    if accion == "terminar":
        wa.send_text_message(contact.phone, config.DESPEDIDA_MESSAGE)
        # DONE y no HUMANO: el bot se calla, pero vuelve solo en cuanto el
        # cliente escriba de nuevo. Con HUMANO haría falta desbloquearlo a
        # mano desde el panel.
        contact.state = "DONE"
        return

    # Una opción con una acción que no existe. Es un error de config, no
    # del cliente: se le responde algo sensato y queda avisado en el log
    # para que se vea al revisar, en vez de dejarlo mudo.
    print(f"[bot_logic] La opción '{elegida['id']}' tiene una acción "
          f"desconocida: {accion!r}. Revisa NEED_OPTIONS en config.")
    _no_entendi(contact, session)


def _borrar_cita_del_sheet(contact: Contact, cita: Lead):
    """
    Quita del Sheet las filas de una cita que se acaba de deshacer.

    Son dos: la de "Citas agendadas" y la que se escribió en la pestaña
    del servicio. Si se quedaran, el Sheet mostraría una reunión que ya no
    existe en el calendario y las cuentas del mes saldrían infladas.

    En "Citas agendadas" se busca por el ID del evento, que es único. En la
    del servicio no hay columna de ID, así que se busca por teléfono y se
    borra la fila más reciente, que es justamente la de esta cita.
    """
    if cita.google_event_id:
        sheets_service.eliminar_fila("citas", "ID del evento", cita.google_event_id)

    servicio = _servicio_del_contacto(contact)
    destino = (servicio or {}).get("sheet") or "otros"
    sheets_service.eliminar_fila(destino, "Teléfono", contact.phone)


def _gestionar_cita(contact: Contact, session, accion: str):
    """
    Cancela o reagenda la reunión que ya tenía el cliente.

    En los dos casos se libera primero el hueco del calendario: si no, al
    reagendar quedarían dos eventos suyos y el horario viejo seguiría
    apareciendo ocupado para todo el mundo.
    """
    cita = _cita_activa(session, contact)
    if cita is None:
        wa.send_text_message(contact.phone, config.CITA_NO_ENCONTRADA_MESSAGE)
        _enviar_menu(contact, rellenar(config.WELCOME_BACK_MESSAGE, name=contact.name), session)
        return

    fecha = cita.appointment_date or "(por confirmar)"
    hora = cita.appointment_time or "(por confirmar)"
    servicio = config.nombre_servicio(contact.servicio) or "(sin servicio)"

    # Si Google falla, el lead se marca igual y se avisa al dueño: para el
    # cliente la cita queda cancelada, y que el evento siga en el
    # calendario es un problema que se arregla a mano, no suyo.
    es_de_barberia = (cita.google_event_id or "").startswith(barberia_bot.PREFIJO_LEAD)
    if es_de_barberia:
        # La cita vive en la agenda de la barbería, no en Google.
        barberia_bot.cancelar_por_lead(cita.google_event_id)
    elif cita.google_event_id:
        if not calendar_service.eliminar_evento(cita.google_event_id):
            print(f"[bot_logic] El evento {cita.google_event_id} no se pudo borrar; "
                  f"queda por limpiar a mano en el calendario.")

    cita.status = "cancelada"
    if not es_de_barberia:
        _borrar_cita_del_sheet(contact, cita)

    if accion == "cancelar":
        notificaciones.avisar_dueno(
            rellenar(config.OWNER_NOTIFICATION_CANCELACION,
                name=contact.name or "(sin nombre)", phone=contact.phone,
                date=fecha, time=hora, servicio=servicio),
            ["cita cancelada", contact.name or "-", contact.phone, f"{fecha} {hora}"],
            servicio=contact.servicio,
        )
        # La cancelación y el "¿algo más?" en un solo mensaje al cliente.
        _ofrecer_cierre(
            contact,
            rellenar(config.CITA_CANCELADA_MESSAGE, date=fecha, time=hora),
        )
        return

    # Reagendar: se avisa al dueño de que el hueco viejo quedó libre y se
    # le vuelve a ofrecer el calendario desde cero.
    wa.send_text_message(
        contact.phone,
        rellenar(config.CITA_REAGENDAR_MESSAGE, date=fecha, time=hora),
    )
    notificaciones.avisar_dueno(
        rellenar(config.OWNER_NOTIFICATION_REAGENDA,
            name=contact.name or "(sin nombre)", phone=contact.phone,
            date=fecha, time=hora, servicio=servicio),
        ["cita reagendada", contact.name or "-", contact.phone, f"{fecha} {hora}"],
        servicio=contact.servicio,
    )

    if not _ofrecer_dias(contact, session):
        _registrar_cita_manual(contact, session, motivo="Calendar caído al reagendar")


def _ofrecer_dias(contact: Contact, session, texto: str = None) -> bool:
    """
    Manda la lista de días que tienen algún horario libre.

    Devuelve False si Google no responde, para que quien llama derive a
    la ruta manual en vez de dejar al cliente sin respuesta.

    Una BARBERÍA no agenda en Google: pregunta sede, servicio y barbero
    antes del día (`app/barberia/bot.py`). Todo lo que llega aquí —la
    opción "cita" del menú y "Reagendar"— entra por este desvío.
    """
    if barberia_bot.es_barberia():
        return barberia_bot.iniciar(contact, session, texto)

    try:
        dias = calendar_service.dias_con_disponibilidad()
    except CalendarNoDisponible as e:
        print(f"[bot_logic] Calendar no disponible: {e}")
        return False

    if not dias:
        wa.send_text_message(contact.phone, config.APPOINTMENT_NO_AVAILABILITY_MESSAGE)
        _registrar_cita_manual(contact, session, motivo="sin disponibilidad")
        return True

    opciones = [
        {
            "id": f"dia_{fecha.isoformat()}",
            "title": calendar_service.formatear_dia_corto(fecha),
            "description": rellenar(config.APPOINTMENT_DAY_DESCRIPTION, n=libres),
        }
        for fecha, libres in dias
    ]

    wa.send_list_message(
        contact.phone,
        texto or config.ASK_APPOINTMENT_DATE_MESSAGE,
        config.APPOINTMENT_DAYS_BUTTON,
        opciones,
        config.APPOINTMENT_DAYS_SECTION,
    )
    contact.state = "ASKING_DATE"
    return True


def _handle_appointment_date(contact: Contact, session, list_id: str,
                             text: str = None):
    """El cliente eligió un día de la lista: le mostramos las horas libres."""
    if not list_id or not list_id.startswith("dia_"):
        # Escribió texto libre en vez de tocar la lista. Si lo que escribió
        # es otra opción del menú, se hace eso: cambió de idea. Solo se
        # acepta que ELIJA una opción, no una respuesta libre de la IA, que
        # dejaría el agendado a medias sin volver a enseñarle los días.
        if _entender_texto(contact, session, text, con_respuesta=False):
            return
        _ofrecer_dias(contact, session, config.FALLBACK_MESSAGE)
        return

    fecha = date.fromisoformat(list_id[len("dia_"):])
    _ofrecer_horarios(contact, session, fecha)


def _ofrecer_horarios(contact: Contact, session, fecha, texto: str = None):
    """
    Muestra los horarios libres del día elegido.

    Hasta 3 van como botones y el resto como lista, igual que el menú: son
    los mismos topes de WhatsApp. Antes se mandaban siempre como botones,
    así que de un día entero libre solo se veían los tres primeros de la
    mañana y parecía que no había nada más.
    """
    try:
        libres = calendar_service.horarios_libres(fecha)
    except CalendarNoDisponible as e:
        print(f"[bot_logic] Calendar no disponible: {e}")
        _registrar_cita_manual(contact, session, motivo="Calendar caído")
        return

    if not libres:
        # Se llenó entre que vio la lista y eligió
        if not _ofrecer_dias(contact, session, config.APPOINTMENT_NO_SLOTS_MESSAGE):
            _registrar_cita_manual(contact, session, motivo="Calendar caído")
        return

    opciones = [
        {"id": f"hora_{slot.isoformat()}", "title": calendar_service.formatear_hora(slot)}
        for slot in libres[:config.APPOINTMENT_SLOTS_OFFERED]
    ]

    mensaje = texto or rellenar(config.ASK_APPOINTMENT_TIME_MESSAGE,
        date=calendar_service.formatear_dia(fecha)
    )

    if len(opciones) <= 3:
        wa.send_button_message(contact.phone, mensaje, opciones)
    else:
        wa.send_list_message(
            contact.phone,
            mensaje,
            config.APPOINTMENT_TIMES_BUTTON,
            opciones,
            config.APPOINTMENT_TIMES_SECTION,
        )

    contact.temp_data = fecha.isoformat()
    contact.state = "ASKING_TIME"


def _handle_appointment_time(contact: Contact, session, button_id: str,
                             text: str = None):
    """El cliente eligió una hora: creamos el evento real en el calendario."""
    if not button_id or not button_id.startswith("hora_"):
        # Igual que con los días: si escribió otra opción, cambió de idea.
        if _entender_texto(contact, session, text, con_respuesta=False):
            return
        fecha = date.fromisoformat(contact.temp_data) if contact.temp_data else None
        if fecha:
            _ofrecer_horarios(contact, session, fecha, config.FALLBACK_MESSAGE)
        else:
            _ofrecer_dias(contact, session, config.FALLBACK_MESSAGE)
        return

    inicio = datetime.fromisoformat(button_id[len("hora_"):])

    try:
        # Última comprobación antes de reservar: entre que vio los botones
        # y tocó uno pudo entrar otra cita en ese hueco.
        if not calendar_service.sigue_libre(inicio):
            _ofrecer_horarios(contact, session, inicio.date(),
                              config.APPOINTMENT_SLOT_TAKEN_MESSAGE)
            return

        event_id = calendar_service.crear_evento(
            nombre=contact.name or "Cliente",
            telefono=contact.phone,
            inicio=inicio,
        )
    except CalendarNoDisponible as e:
        print(f"[bot_logic] No se pudo agendar en Calendar: {e}")
        _registrar_cita_manual(contact, session, motivo="Calendar caído")
        return

    fecha_texto = calendar_service.formatear_dia(inicio.date())
    hora_texto = calendar_service.formatear_hora(inicio)

    lead = Lead(
        contact_id=contact.id,
        type="cita",
        appointment_date=fecha_texto,
        appointment_time=hora_texto,
        google_event_id=event_id,
        status="pendiente",
    )
    session.add(lead)

    _notify_owner_appointment(contact, fecha_texto, hora_texto)

    contact.temp_data = None
    lead.status = "notificado"
    _registrar_en_sheet(contact, lead)

    # El recorrido termina aquí, así que se le ofrece salida en vez de
    # dejarlo mirando la confirmación sin saber si puede pedir algo más.
    # La confirmación va DENTRO de ese mismo mensaje: eran dos envíos
    # seguidos al cliente y desde el 1-oct-2026 Meta cobra los dos.
    _ofrecer_cierre(
        contact,
        rellenar(config.APPOINTMENT_CONFIRMATION_MESSAGE,
            name=contact.name, date=fecha_texto, time=hora_texto
        ),
    )


def _registrar_cita_manual(contact: Contact, session, motivo: str):
    """
    Ruta de emergencia: si Google no responde, la cita NO se pierde.

    Se guarda como lead pendiente y se avisa al dueño para que la
    confirme a mano. Vale más una cita por confirmar que un cliente sin
    respuesta porque se cayó una API que no es la nuestra.
    """
    print(f"[bot_logic] Cita de {contact.phone} registrada a mano ({motivo}).")

    lead = Lead(
        contact_id=contact.id,
        type="cita",
        detail=f"Pendiente de agendar a mano ({motivo})",
        status="pendiente",
    )
    session.add(lead)

    wa.send_text_message(
        contact.phone,
        rellenar(config.APPOINTMENT_FALLBACK_MESSAGE, name=contact.name or "Cliente"),
    )
    _notify_owner_appointment(contact, "por confirmar", "por confirmar")

    contact.state = "DONE"
    contact.temp_data = None
    _registrar_en_sheet(contact, lead)


def _pasar_directo_a_asesor(contact: Contact, session, elegida: dict):
    """
    "Pasar a una persona" sin pedirle antes que cuente su consulta.

    Lo que el cliente no escribe lo dice su recorrido: el botón que pulsó
    y por dónde llegó hasta él ("Página web > Hablar con un asesor"). Eso
    es lo que va en el aviso y en el Sheet, para que quien atiende sepa de
    qué va antes de escribirle.

    El resto es exactamente la rama de siempre (`_handle_other_detail`):
    mismo lead, mismo aviso, mismo takeover. Solo cambia que no se espera
    un mensaje del cliente.
    """
    titulo = elegida.get("title") or "Pasar a una persona"
    detalle = f"Pulsó «{titulo}»"
    servicio = _servicio_del_contacto(contact)
    if servicio is not None:
        detalle += f" en {servicio.get('title')}"
    if contact.recorrido:
        detalle += f" · recorrido: {contact.recorrido}"

    _handle_other_detail(contact, session, detalle,
                         confirmacion=config.ASESOR_DIRECTO_MESSAGE)


def _handle_other_detail(contact: Contact, session, text: str,
                         confirmacion: str = None):
    lead = Lead(contact_id=contact.id, type="otro", detail=text, status="pendiente")
    session.add(lead)

    wa.send_text_message(
        contact.phone,
        rellenar(confirmacion or config.HUMAN_HANDOFF_CONFIRMATION,
                 name=contact.name),
    )
    _notify_owner_other(contact, text)

    # Esta rama termina en que una persona responde. Si dejáramos el
    # contacto en DONE, el siguiente mensaje del cliente reiniciaría el
    # saludo justo encima del asesor: por eso se fusiona con el flag.
    if config.TAKEOVER_ON_OTHER_QUERY:
        _marcar_atendido_por_humano(contact)
    else:
        contact.state = "DONE"

    lead.status = "notificado"
    _registrar_en_sheet(contact, lead)


# ── Seguimiento en Google Sheets ─────────────────────────────────────

def _registrar_en_sheet(contact: Contact, lead: Lead):
    """
    Agrega el lead como fila del Sheet del dueño.

    Se llama al final de cada rama, después de guardar en la base y de
    avisar por WhatsApp: si el Sheet falla, el lead ya está a salvo por
    los otros dos caminos. sheets_service nunca lanza excepción.
    """
    servicio = _servicio_del_contacto(contact)

    datos_contacto = {
        "name": contact.name,
        "phone": contact.phone,
        "origen": contact.origen,
        # Nombre legible del servicio, no el id: esto va a una celda que
        # lee una persona.
        "servicio": servicio["title"] if servicio else "",
        "recorrido": contact.recorrido or "",
    }
    datos_lead = {
        "detail": lead.detail,
        "appointment_date": lead.appointment_date,
        "appointment_time": lead.appointment_time,
        "google_event_id": lead.google_event_id,
    }

    # A la pestaña del servicio que eligió. Quien nunca eligió ninguno
    # —por ejemplo el que pide un asesor nada más entrar— va a "otros".
    destinos = [(servicio or {}).get("sheet") or "otros"]

    # Y las citas, además, a su propia pestaña, para verlas todas juntas
    # sin ir servicio por servicio.
    if lead.type == "cita":
        destinos.insert(0, "citas")

    for destino in destinos:
        sheets_service.registrar_lead(destino, datos_contacto, datos_lead)


# ── Notificaciones al dueño ──────────────────────────────────────────

def _notify_owner_appointment(contact: Contact, date: str, time: str):
    nombre = contact.name or "(sin nombre)"
    msg = rellenar(config.OWNER_NOTIFICATION_APPOINTMENT,
        name=nombre,
        phone=contact.phone,
        date=date,
        time=time,
        origen=contact.origen or config.ORIGEN_POR_DEFECTO,
    )
    notificaciones.avisar_dueno(
        msg, ["cita", nombre, contact.phone, f"{date} a las {time}"],
        servicio=contact.servicio)


def _notify_owner_other(contact: Contact, detail: str):
    nombre = contact.name or "(sin nombre)"
    msg = rellenar(config.OWNER_NOTIFICATION_OTHER,
        name=nombre,
        phone=contact.phone,
        detail=detail,
        origen=contact.origen or config.ORIGEN_POR_DEFECTO,
    )
    notificaciones.avisar_dueno(msg, ["consulta", nombre, contact.phone, detail or "-"],
                                servicio=contact.servicio)
