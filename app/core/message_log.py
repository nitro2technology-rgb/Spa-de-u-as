"""
HISTORIAL DE CONVERSACIONES
============================
Guarda cada mensaje que entra y cada uno que sale, para poder ver la
charla completa en el panel y responder a mano con contexto.

Nunca lanza excepción: si falla el registro del historial, el mensaje ya
se envió o ya se procesó, y perder una línea del historial no puede
tumbar una conversación con un cliente.
"""

from datetime import timedelta

from sqlalchemy import func

from app import config
from app.core import eventos
from app.core import push
from app.core.database import (get_session, ahora_utc, etiquetas_de,
                               Contact, Message)


def quien(direccion: str, autor: str) -> str:
    """
    Quién habló, en los términos que usa el panel.

    Vive aquí y no en el panel porque lo necesitan tres sitios: el hilo
    pintado en el servidor, la respuesta del endpoint y el aviso en vivo.
    """
    if direccion == "entrante":
        return "cliente"
    return "humano" if autor == "humano" else "bot"


def etiqueta_media(media_tipo: str, media_nombre: str = None) -> str:
    """
    Cómo se nombra un adjunto cuando hay que resumirlo en una línea: en el
    listado de la bandeja, en el aviso al celular y en la burbuja cuando
    el archivo ya caducó.

    Vive aquí, y no en el panel, porque lo necesitan esos tres sitios y ya
    hubo una divergencia parecida con el hilo de la conversación.
    """
    if media_tipo == "document" and media_nombre:
        return f"📎 {media_nombre}"

    return {
        "image": "📷 Imagen",
        "audio": "🎤 Nota de voz",
        "document": "📎 Documento",
        "video": "🎬 Video",
        "sticker": "🙂 Sticker",
        "location": "📍 Ubicación",
        "contacts": "👤 Contacto",
    }.get(media_tipo, "📎 Archivo")


def registrar(phone: str, direccion: str, autor: str, texto: str,
              media_id: str = None, media_tipo: str = None,
              media_mime: str = None, media_nombre: str = None,
              media_bytes: int = None):
    """
    Anota un mensaje en el historial y avisa a los paneles abiertos.

    Es el punto por el que pasa TODO mensaje, entrante y saliente, así que
    es el sitio natural para disparar el aviso en vivo.

    Un mensaje puede traer texto, un adjunto, o las dos cosas (una imagen
    con pie de foto). Lo que no puede es venir vacío del todo: eso sería
    una llamada perdida, no un mensaje.
    """
    # Antes esta guarda era `if not texto`, y por eso una foto o una nota
    # de voz desaparecían sin dejar rastro: ni en el historial, ni en el
    # panel, ni en el aviso al celular. El dueño no se enteraba.
    if not texto and not media_tipo:
        return

    session = get_session()
    try:
        mensaje = Message(phone=phone, direccion=direccion, autor=autor,
                          texto=texto, media_id=media_id, media_tipo=media_tipo,
                          media_mime=media_mime, media_nombre=media_nombre,
                          media_bytes=media_bytes)
        session.add(mensaje)
        session.commit()

        aviso = {
            "id": mensaje.id,
            "phone": phone,
            "quien": quien(direccion, autor),
            "texto": texto or "",
            "hora": mensaje.created_at.strftime("%d/%m %H:%M") if mensaje.created_at else "",
            **_ficha_media(mensaje),
        }
        resumen = texto or etiqueta_media(media_tipo, media_nombre)
    except Exception as e:
        print(f"[message_log] No se pudo guardar el mensaje: {e}")
        session.rollback()
        return
    finally:
        session.close()

    # Fuera del try: si algo fallara al avisar, el mensaje ya está
    # guardado y no queremos que un problema del panel tumbe el envío.
    eventos.publicar(aviso)

    # Y el aviso al celular, que es el que sirve con el panel cerrado.
    # Solo para lo que escribe el cliente: notificar también lo que
    # mandamos nosotros haría sonar el teléfono con nuestras propias
    # respuestas. Sale en un hilo aparte y no puede frenar el webhook.
    #
    # Se pregunta por `configurado()` ANTES de buscar el nombre: sin
    # claves VAPID esa consulta se haría en cada mensaje entrante para
    # nada, y esto está en el camino caliente del webhook.
    if direccion == "entrante" and push.configurado():
        push.avisar_mensaje_entrante(phone, _nombre_de(phone), resumen)


def _ficha_media(m) -> dict:
    """
    Los datos del adjunto en el formato que espera el panel, o un dict
    vacío si el mensaje era solo texto.

    Se saca a una función porque los TRES formatos de mensaje que sirve
    este módulo tienen que llevar exactamente los mismos campos, y ya se
    perdió tiempo una vez por mantenerlos a mano cada uno por su lado.
    """
    if not m.media_tipo:
        return {}

    return {
        "media_tipo": m.media_tipo,
        "media_mime": m.media_mime or "",
        "media_nombre": m.media_nombre or "",
        "media_bytes": m.media_bytes or 0,
        # El archivo se pide por el id del MENSAJE, no por el de Meta: así
        # la URL no expone el id de Meta y el panel no necesita saber de
        # dónde sale el archivo.
        "media_url": f"/admin/media/{m.id}",
        "media_etiqueta": etiqueta_media(m.media_tipo, m.media_nombre),
        # Sin media_id no hay de dónde bajarlo: es un adjunto que ya
        # caducó, o uno que nunca se llegó a subir.
        "media_disponible": bool(m.media_id),
    }


def _nombre_de(phone: str) -> str:
    """El nombre del contacto para el aviso, o el teléfono si no lo sabemos."""
    session = get_session()
    try:
        contacto = session.query(Contact).filter_by(phone=phone).first()
        return (contacto.name if contacto and contacto.name else phone)
    except Exception:
        return phone
    finally:
        session.close()


def conversacion(phone: str, limite: int = 100, desde_id: int = None) -> list:
    """
    Los últimos mensajes de un contacto, del más viejo al más nuevo.

    Con `desde_id` devuelve solo los posteriores a ese id. Lo usa el panel
    para traer únicamente lo nuevo cada pocos segundos, en vez de recargar
    la conversación entera.
    """
    session = get_session()
    try:
        consulta = session.query(Message).filter_by(phone=phone)

        if desde_id:
            mensajes = (consulta.filter(Message.id > desde_id)
                        .order_by(Message.id.asc()).all())
        else:
            mensajes = list(reversed(
                consulta.order_by(Message.id.desc()).limit(limite).all()))

        return [
            {
                "id": m.id,
                "direccion": m.direccion,
                "autor": m.autor,
                "texto": m.texto,
                "created_at": m.created_at,
                **_ficha_media(m),
            }
            for m in mensajes
        ]
    finally:
        session.close()


def adjunto_de(message_id: int) -> dict | None:
    """
    La ficha del archivo de un mensaje, o None si no tiene ninguno (o si
    ya caducó y no queda de dónde bajarlo).

    Lo usa el panel para servir la imagen: pide por el id del MENSAJE, y
    aquí se traduce al id de Meta. Así la URL del panel no expone nunca
    los ids de Meta.
    """
    session = get_session()
    try:
        m = session.query(Message).filter_by(id=message_id).first()
        if not m or not m.media_id:
            return None
        return {
            # De qué conversación es: el panel comprueba que quien lo pide
            # pueda verla. Un área no puede abrir la foto de un cliente de
            # otra área probando números de mensaje.
            "phone": m.phone,
            "media_id": m.media_id,
            "media_mime": m.media_mime or "",
            "media_nombre": m.media_nombre or "",
            "media_tipo": m.media_tipo or "",
        }
    finally:
        session.close()


def ultimo_saliente(phone: str) -> int | None:
    """
    El id del último mensaje que le mandamos. Sirve para guardar en caché
    lo que acabamos de enviar, que ya tenemos en memoria y sería absurdo
    volver a bajar de Meta para pintarlo en el hilo.
    """
    session = get_session()
    try:
        m = (session.query(Message)
             .filter_by(phone=phone, direccion="saliente")
             .order_by(Message.id.desc()).first())
        return m.id if m else None
    finally:
        session.close()


def ultimo_mensaje_del_cliente(phone: str):
    """Cuándo escribió por última vez. None si nunca lo hizo."""
    session = get_session()
    try:
        # Por id y no por fecha: dan el mismo orden (el id crece con cada
        # mensaje), pero el id está en el índice (client_id, phone, id) y
        # la fecha no. Esto corre en cada mensaje de una conversación
        # atendida a mano y en cada refresco del panel.
        ultimo = (
            session.query(Message)
            .filter_by(phone=phone, direccion="entrante")
            .order_by(Message.id.desc())
            .first()
        )
        return ultimo.created_at if ultimo else None
    finally:
        session.close()


def ultima_respuesta_manual(phone: str):
    """Cuándo respondió una persona por última vez. None si nunca."""
    session = get_session()
    try:
        ultimo = (
            session.query(Message)
            .filter_by(phone=phone, direccion="saliente", autor="humano")
            .order_by(Message.id.desc())
            .first()
        )
        return ultimo.created_at if ultimo else None
    finally:
        session.close()


def _ventana(momento) -> tuple:
    """
    ¿Queda ventana de 24 horas, contando desde `momento`?

    WhatsApp solo permite responder libremente dentro de las 24 horas
    siguientes al último mensaje del cliente. Pasado ese plazo hay que
    usar una plantilla aprobada por Meta, y un envío normal falla con el
    error 131047.

    Devuelve (abierta, horas_restantes).
    """
    if not momento:
        return False, 0

    restante = timedelta(hours=24) - (ahora_utc() - momento)
    if restante.total_seconds() <= 0:
        return False, 0

    return True, restante.total_seconds() / 3600


def ventana_abierta(phone: str) -> tuple:
    """La ventana de 24 h de un contacto. Devuelve (abierta, horas)."""
    return _ventana(ultimo_mensaje_del_cliente(phone))


def mensajes_desde(desde_id: int, limite: int = 200, filtro=None) -> list:
    """
    Mensajes posteriores a un id, de TODAS las conversaciones que se ven.

    Lo usa el panel al abrir el canal de avisos en vivo, para recuperar lo
    que haya entrado entre que la página se pintó y el canal se conectó.
    Sin esto, un mensaje que cayera justo en ese hueco no aparecería hasta
    recargar.

    `filtro` es la condición de `equipo.filtro_contactos`: quien entra por
    un área solo recupera los de su área.
    """
    session = get_session()
    try:
        consulta = session.query(Message).filter(Message.id > desde_id)
        if filtro is not None:
            visibles = session.query(Contact.phone).filter(filtro)
            consulta = consulta.filter(Message.phone.in_(visibles))
        mensajes = (consulta.order_by(Message.id.asc())
                    .limit(limite)
                    .all())
        return [
            {
                "id": m.id,
                "phone": m.phone,
                "quien": quien(m.direccion, m.autor),
                "texto": m.texto or "",
                # En UTC y en ISO: la hora la escribe el navegador, que
                # es el único de los dos que sabe en qué huso está
                # sentado quien atiende. Antes se mandaba ya formateada y
                # el panel enseñaba UTC, cinco horas corridas en Colombia.
                "iso": (m.created_at.isoformat() + "Z") if m.created_at else "",
                **_ficha_media(m),
            }
            for m in mensajes
        ]
    finally:
        session.close()


def _ultimos_por_telefono(session, telefonos: list, solo_entrantes: bool = False) -> dict:
    """
    El mensaje más reciente de cada teléfono, en UNA consulta.

    Antes el panel pedía esto contacto por contacto: con 200 conversaciones
    eran 400 consultas cada vez que se refrescaba la bandeja, varias veces
    por minuto y por pestaña abierta. Era, con diferencia, lo más caro que
    hacía el panel.

    Se agrupa por id y no por fecha porque el id es autoincremental: da el
    mismo orden y no empata cuando dos mensajes caen en el mismo segundo.
    """
    consulta = session.query(func.max(Message.id)).filter(Message.phone.in_(telefonos))
    if solo_entrantes:
        consulta = consulta.filter(Message.direccion == "entrante")

    ids = [fila[0] for fila in consulta.group_by(Message.phone).all()]
    if not ids:
        return {}

    return {m.phone: m
            for m in session.query(Message).filter(Message.id.in_(ids)).all()}


def _resumen(mensaje) -> str | None:
    """El último mensaje en una línea, para el listado de la bandeja."""
    if not mensaje:
        return None
    if mensaje.texto:
        return mensaje.texto
    if mensaje.media_tipo:
        return etiqueta_media(mensaje.media_tipo, mensaje.media_nombre)
    return None


def _fila(contacto: Contact, ultimo, ultimo_entrante) -> dict:
    """Un contacto en el formato que espera el panel."""
    abierta, horas = _ventana(ultimo_entrante.created_at if ultimo_entrante else None)

    return {
        "phone": contacto.phone,
        "name": contacto.name,
        "state": contacto.state,
        "origen": contacto.origen,
        "atendido_por_humano": contacto.atendido_por_humano,
        # Qué servicio eligió y por dónde pasó. Es el contexto que
        # necesita quien va a responderle a mano: sin esto hay que
        # leerse el hilo entero para saber de qué venía hablando.
        "servicio": config.nombre_servicio(contacto.servicio),
        # El id del servicio y el área a mano: con los dos se sabe de qué
        # área es (`equipo.area_de_contacto`), que el dueño ve en la ficha.
        "servicio_id": contacto.servicio or "",
        "area_asignada": contacto.area or "",
        "recorrido": contacto.recorrido or "",
        # En qué punto de atención lo dejaste. Va aquí y no solo en el
        # hilo porque su razón de ser es verse en el listado: saber a
        # quién atender ya sin abrir conversación por conversación.
        "estado_atencion": contacto.estado_atencion or "",
        # Las etiquetas que se pone el negocio a su manera, y la nota que
        # deja quien atiende. Las dos son SOLO del panel: el bot no las
        # lee y el cliente no las ve nunca.
        "etiquetas": etiquetas_de(contacto),
        "nota_interna": contacto.nota_interna or "",
        "es_dueno": contacto.phone == config.OWNER_PHONE_NUMBER,
        # Una foto sin pie de foto no tiene texto que enseñar, y dejar la
        # fila en blanco haría parecer que no pasó nada.
        "ultimo_texto": _resumen(ultimo),
        "ultimo_autor": ultimo.autor if ultimo else None,
        "last_interaction": contacto.last_interaction,
        "ventana_abierta": abierta,
        "horas_restantes": horas,
    }


def conversaciones(limite: int = 50, filtro=None) -> list:
    """
    Lista de contactos para el panel, el más reciente primero.

    Incluye el último mensaje de cada uno para poder ojear la bandeja sin
    entrar a cada conversación.

    Son tres consultas fijas, no dos por contacto: los contactos, el
    último mensaje de cada uno y el último mensaje *entrante* de cada uno
    (que es el que decide la ventana de 24 h).

    `filtro` es la condición de `equipo.filtro_contactos`: quien entra por
    un área solo ve las de su área, y se filtra en la consulta —no
    después— para que el tope de `limite` y las cuentas sean las suyas.
    """
    session = get_session()
    try:
        consulta = session.query(Contact)
        if filtro is not None:
            consulta = consulta.filter(filtro)
        contactos = (
            consulta
            .order_by(Contact.last_interaction.desc())
            .limit(limite)
            .all()
        )
        if not contactos:
            return []

        telefonos = [c.phone for c in contactos]
        ultimos = _ultimos_por_telefono(session, telefonos)
        entrantes = _ultimos_por_telefono(session, telefonos, solo_entrantes=True)

        return [_fila(c, ultimos.get(c.phone), entrantes.get(c.phone))
                for c in contactos]
    finally:
        session.close()


def conversacion_info(phone: str):
    """
    Los datos de UNA conversación, o None si ese contacto no existe.

    El panel pedía antes las 200 conversaciones para buscar la suya
    dentro, lo que disparaba el recuento completo cada pocos segundos.
    """
    session = get_session()
    try:
        contacto = session.query(Contact).filter_by(phone=phone).first()
        if not contacto:
            return None

        # Para UN teléfono no se agrupa: agrupar cuesta dos consultas
        # (los ids y luego las filas) y aquí basta con pedir la última
        # directamente. La agrupación solo compensa con la lista entera.
        ultimo = (session.query(Message).filter_by(phone=phone)
                  .order_by(Message.id.desc()).first())
        entrante = (session.query(Message)
                    .filter_by(phone=phone, direccion="entrante")
                    .order_by(Message.id.desc()).first())

        return _fila(contacto, ultimo, entrante)
    finally:
        session.close()
