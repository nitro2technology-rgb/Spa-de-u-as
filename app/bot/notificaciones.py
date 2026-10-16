"""
AVISOS AL NEGOCIO
==================
Todo lo que el bot le manda al negocio cuando entra un lead pasa por aquí.

A QUIÉN LE LLEGA
----------------
Ya no es "el dueño": un negocio reparte sus avisos entre áreas —Ventas,
Soporte, Contratos; cuántas, lo decide su plan— y dice de qué opciones del
menú se encarga cada una. Lo configura el negocio desde `/superadmin`, y se
resuelve en `a_quien()`, que es donde está explicado el orden.

Sin áreas configuradas, todo va al número del dueño.

POR DÓNDE
---------
Por CORREO (`app/core/correo.py`). A las áreas, solo por correo: un aviso
por WhatsApp lo cobra Meta, y además tiene tres puertas que lo bloquean en
silencio —la ventana de 24 h, la plantilla aprobada y la facturación de la
cuenta—. El WhatsApp del dueño queda como último recurso (ver
`avisar_dueno`); cuando se usa, la ventana se pregunta ANTES de enviar
(`ventana_abierta`) y, cerrada, el aviso sale directo por plantilla.
"""

from app import config
from app.bot import whatsapp_client as wa

# Meta devuelve este código cuando hace falta una plantilla porque la
# ventana de 24 horas ya se cerró.
ERROR_FUERA_DE_VENTANA = 131047


def a_quien(servicio: str = None) -> list:
    """
    `(numero, nombre)` de cada destino de este servicio. Es la vista de
    `_destinos_para` con solo números, para quien no necesita el resto.
    """
    return [(d.get("numero") or "", d.get("nombre") or "")
            for d in _destinos_para(servicio)]


def avisar_dueno(texto: str, variables: list, servicio: str = None) -> bool:
    """
    Manda un aviso a quien le toque. Devuelve True si llegó a alguien.

    `servicio` es la opción del menú que eligió el cliente, y es lo que
    decide a qué área va (ver `_destinos_para`).

    POR CORREO, Y SOLO POR CORREO, a las áreas (decisión del 23-sep-2026).
    Un aviso por WhatsApp a un área es un mensaje que Meta cobra, y además
    tiene tres puertas que lo bloquean en silencio: la ventana de 24 h, la
    plantilla aprobada y la facturación de la cuenta. El correo no cuesta
    nada y llega siempre. Los números de WhatsApp que tengan las áreas
    guardadas de antes se ignoran.

    El WhatsApp del DUEÑO se usa en un solo caso: cuando el aviso no salió
    por ninguna otra vía. Es la regla que gobierna todo esto —un aviso
    nunca se queda sin destinatario—, y ahí sí compensa pagar el mensaje:
    lo otro es una venta que nadie atiende.
    """
    llegó_a_alguien = False
    correos_probados = set()
    dueno_probado = False

    for destino in _destinos_para(servicio):
        correo_de = destino.get("correo")
        area = destino.get("nombre") or ""

        if correo_de:
            correos_probados.add(correo_de)
            if _avisar_por_correo(correo_de, area, texto, variables):
                llegó_a_alguien = True
        elif destino.get("es_dueno") and destino.get("numero"):
            # El dueño sin correo configurado: su WhatsApp es la única vía.
            dueno_probado = True
            if _avisar_a(destino["numero"], texto, variables, "dueño"):
                llegó_a_alguien = True

    if not llegó_a_alguien:
        correo_dueno = config.AVISOS_CORREO_DUENO
        if correo_dueno and correo_dueno not in correos_probados:
            print("[notificaciones] El aviso no salió por sus áreas: va al "
                  "correo del dueño.")
            llegó_a_alguien = _avisar_por_correo(correo_dueno, "", texto, variables)

    dueno = config.OWNER_PHONE_NUMBER
    if not llegó_a_alguien and dueno and not dueno_probado:
        print("[notificaciones] El aviso no salió por correo: va al WhatsApp "
              "del dueño para que no se pierda.")
        llegó_a_alguien = _avisar_a(dueno, texto, variables, "dueño")

    if not llegó_a_alguien:
        print("[notificaciones] ESTE AVISO NO LE LLEGÓ A NADIE: el negocio no "
              "tiene áreas con correo, ni correo ni número del dueño. Se "
              "configura en su panel > Equipo, o en /superadmin.")

    return llegó_a_alguien


def _destinos_para(servicio: str = None) -> list:
    """
    A quién le toca un aviso de este servicio. En orden:

      1. Las áreas que dicen encargarse de esa opción del menú.
      2. Si ninguna, el DUEÑO, por su correo. Lo que no es de ningún área
         es suyo, que es también quien lo ve en el panel
         (`app/core/equipo.py`).
      3. Sin correo del dueño —los negocios de antes de las áreas con
         usuario—, lo de siempre: las áreas sin opciones marcadas, y si no
         hay, todas. Mejor que tres personas lean algo que no les toca a
         que un cliente se quede sin atender.
      4. Sin áreas, el número del dueño.

    **Un lead no se puede perder por estar mal configurado.** Un aviso que
    no se entrega a nadie es una venta que nadie atiende, y no da ningún
    error: se ve exactamente igual que un día sin clientes.
    """
    destinos = config.AVISOS_DESTINOS or []

    if destinos and servicio:
        propios = [d for d in destinos if servicio in (d.get("opciones") or [])]
        if propios:
            return propios

    if config.AVISOS_CORREO_DUENO:
        return [{"nombre": "", "numero": "", "es_dueno": True,
                 "correo": config.AVISOS_CORREO_DUENO}]

    comodines = [d for d in destinos if not (d.get("opciones") or [])]
    if comodines:
        return comodines

    if destinos:
        print(f"[notificaciones] Ningún área cubre {servicio!r} y el dueño no "
              f"tiene correo de avisos: el aviso va a todas las áreas.")
        return destinos

    # Sin áreas, el dueño. Y sin dueño, nadie: antes aquí había un número
    # inventado por defecto, y los leads le llegaban a un desconocido.
    if config.OWNER_PHONE_NUMBER:
        return [{"nombre": "", "numero": config.OWNER_PHONE_NUMBER,
                 "correo": "", "es_dueno": True}]
    return []


def _avisar_por_correo(direccion: str, area: str, texto: str,
                       variables: list) -> bool:
    """
    El aviso por correo, con lo justo para poder actuar. True si se pudo
    poner en camino — False si la plataforma no tiene con qué enviarlo.

    Lleva DOS enlaces y los dos importan: el del panel para responderle
    desde ahí, y el de WhatsApp para escribirle directo desde el teléfono.
    Quien recibe esto en el área de Ventas puede no tener usuario del
    panel, y aun así tiene que poder contactar al cliente.
    """
    from app.core import correo

    if not correo.configurado():
        return False

    # `variables` viene en el orden de la plantilla de Meta: tipo, nombre,
    # teléfono, detalle. Se reutiliza en vez de inventar otro formato para
    # que los dos avisos digan lo mismo.
    tipo = variables[0] if len(variables) > 0 else "aviso"
    nombre = variables[1] if len(variables) > 1 else ""
    telefono = variables[2] if len(variables) > 2 else ""

    negocio = config.BUSINESS_NAME
    encabezado = f"[{negocio}] {tipo}" + (f" · {nombre}" if nombre else "")
    if area:
        encabezado = f"{encabezado} → {area}"

    enlaces = []
    if telefono:
        enlaces.append(f"Escribirle por WhatsApp: https://wa.me/{telefono}")
        enlaces.append(f"Abrir en el panel: {config.PANEL_URL}/admin/chat/{telefono}")

    cuerpo = texto + ("\n\n" + "\n".join(enlaces) if enlaces else "")

    correo.avisar([direccion], encabezado[:150], cuerpo,
                  html=_html_del_aviso(negocio, area, texto, telefono),
                  remitente=negocio)
    return True


def _html_del_aviso(negocio: str, area: str, texto: str, telefono: str) -> str:
    """
    La versión con formato. Sobria a propósito: esto se lee en el móvil,
    de camino a atender a alguien.
    """
    import html as _h

    botones = ""
    if telefono:
        botones = f"""
        <p style="margin:24px 0 0">
          <a href="https://wa.me/{_h.escape(telefono)}"
             style="background:#6D28D9;color:#fff;text-decoration:none;
                    padding:11px 18px;border-radius:8px;display:inline-block;
                    font-weight:600">Escribirle por WhatsApp</a>
        </p>
        <p style="margin:12px 0 0;font-size:14px">
          <a href="{_h.escape(config.PANEL_URL)}/admin/chat/{_h.escape(telefono)}"
             style="color:#6D28D9">Abrir la conversación en el panel</a>
        </p>"""

    etiqueta = f" · {_h.escape(area)}" if area else ""

    return f"""<div style="font-family:-apple-system,'Segoe UI',sans-serif;
                max-width:560px;margin:0 auto;padding:24px;color:#171326">
      <p style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;
                color:#6D28D9;margin:0 0 10px">{_h.escape(negocio)}{etiqueta}</p>
      <div style="white-space:pre-wrap;font-size:16px;line-height:1.6;
                  background:#F6F5FA;border-radius:12px;padding:18px">{_h.escape(texto)}</div>
      {botones}
      <p style="margin:28px 0 0;font-size:12px;color:#8B85A1">
        Te lo manda tu bot de WhatsApp. Si ya no quieres estos avisos,
        pídele a quien administra el bot que quite tu correo del área.
      </p>
    </div>"""


def _avisar_a(numero: str, texto: str, variables: list, area: str = "") -> bool:
    """
    Un aviso a UN número, por el camino que de verdad se lo entregue.

    SE PREGUNTA POR LA VENTANA **ANTES** DE ENVIAR, Y ESO ES EL ARREGLO.

    Antes se intentaba el texto libre y solo se reintentaba con plantilla
    si el envío devolvía error. Parecía razonable y estaba roto: **Meta
    devuelve 200 cuando ACEPTA el mensaje, no cuando lo entrega.** Con la
    ventana cerrada acepta igual y lo descarta después, avisando por un
    webhook de estado. Así que la condición `status_code >= 400` no se
    cumplía nunca y el reintento por plantilla —que llevaba ahí desde el
    principio— no se disparó jamás.

    El síntoma era exactamente este: al dueño le llegaban los avisos
    (porque él le escribe al bot y su ventana está abierta) y a los números
    de las áreas no les llegaba nada, sin ningún error en ningún sitio.

    Preguntando antes, la decisión es nuestra y no depende de que Meta nos
    diga que falló. Un número de área recién configurado nunca le ha
    escrito al bot, así que va directo por plantilla, que es la vía que sí
    funciona fuera de la ventana.
    """
    quien = f"{area} ({numero})" if area else numero

    # Con la ventana cerrada, el texto libre no se va a entregar por mucho
    # que Meta lo acepte. Se va derecho a la plantilla.
    #
    # `variables` vacío descarta ese camino: la plantilla espera un número
    # fijo de huecos y Meta rechaza el envío si no cuadran. Le pasa al
    # aviso de "tu bot no tiene menú", que no es un lead y va sin datos.
    # Ese sigue intentando el texto libre — si el dueño lleva un día sin
    # escribirle al bot no le llegará, y es asumible: no es una venta.
    if variables and config.OWNER_TEMPLATE_NAME and not ventana_abierta(numero):
        print(f"[notificaciones] {quien} lleva más de 24h sin escribirle al "
              f"bot: el aviso sale por plantilla.")
        return _por_plantilla(numero, variables, quien)

    respuesta = wa.send_text_message(numero, texto)

    if respuesta.status_code < 400:
        return True

    if not _es_fuera_de_ventana(respuesta):
        print(f"[notificaciones] El aviso a {quien} falló: {respuesta.text[:200]}")
        return False

    if not config.OWNER_TEMPLATE_NAME:
        # Las flechas van como ">" y no como "→" a propósito: la consola
        # de Windows usa cp1252, que no sabe escribir esa flecha, y un
        # `print` que revienta se lleva por delante a quien lo llamó. Aquí
        # tumbaba la suite de regresión entera y escondía el fallo de
        # verdad que venía debajo.
        print("[notificaciones] Pasaron más de 24h desde tu último mensaje al bot y "
              "no hay plantilla configurada: este aviso NO te va a llegar. "
              "Ponla en /superadmin > el contenido completo > Avisos al dueño. "
              "Las que tienes aprobadas: python scripts/meta_setup.py plantillas")
        return False

    return _por_plantilla(numero, variables, quien)


def _por_plantilla(numero: str, variables: list, quien: str) -> bool:
    """
    El envío por plantilla, que es lo único que atraviesa la ventana.

    Está aparte porque ahora se llega aquí por dos caminos: sabiendo de
    antemano que la ventana está cerrada (lo normal), y como reintento si
    Meta rechaza el texto libre (el camino viejo, que sigue valiendo).
    """
    if not config.OWNER_TEMPLATE_NAME:
        return False

    respuesta = wa.send_template_message(
        numero,
        config.OWNER_TEMPLATE_NAME,
        config.OWNER_TEMPLATE_LANG,
        variables,
    )

    if respuesta.status_code >= 400:
        print(f"[notificaciones] La plantilla falló con {quien}: "
              f"{respuesta.text[:300]}")
        print("[notificaciones] Revisa que exista y esté aprobada, y que "
              "espere el mismo número de variables: "
              "python scripts/meta_setup.py plantillas")
        return False

    return True


# Dónde se guarda el último aviso que Meta no pudo entregar. Es un ajuste
# del cliente y no una tabla nueva a propósito: una tabla con `client_id`
# cuesta su política de RLS, y el día que se olvide queda sin cerradura
# sin que nadie se entere (ver CLAUDE.md). Aquí solo hace falta recordar
# el último, que es lo que se enseña.
AJUSTE_ULTIMO_FALLO = "ultimo_fallo_aviso"


def anotar_no_entregado(numero: str, motivo: str, cuando: str = ""):
    """
    Guarda que un aviso NO llegó, para que se pueda ver en el panel.

    ES LA PIEZA QUE FALTABA, Y EXPLICA UN SÍNTOMA ENTERO.

    Meta responde **200 cuando ACEPTA** un mensaje, no cuando lo entrega.
    Si luego no puede entregarlo —el destinatario no le ha escrito al bot
    en 24 h, el número no tiene WhatsApp, el que sea— eso NO vuelve como
    error de la llamada: llega después, en un webhook de estado.

    Ese webhook se estaba tirando a la basura (`main.py`, "ignoramos
    eventos de estado de entrega"). Con lo cual la única señal de que un
    lead no le llegó a nadie se perdía, y desde fuera se veía idéntico a
    que no hubiera clientes ese día.
    """
    from app.core import ajustes

    texto = f"{cuando or ''}|{numero}|{motivo}".strip("|")
    try:
        ajustes.escribir(AJUSTE_ULTIMO_FALLO, texto[:500])
    except Exception as e:
        # Anotar el fallo no puede provocar otro fallo.
        print(f"[notificaciones] No se pudo anotar el aviso no entregado: {e}")

    print(f"[notificaciones] NO ENTREGADO a {numero}: {motivo}")


def ultimo_no_entregado() -> dict | None:
    """El último aviso que no llegó, para pintarlo en `/superadmin`."""
    from app.core import ajustes

    guardado = ajustes.leer(AJUSTE_ULTIMO_FALLO, None)
    if not guardado:
        return None

    partes = str(guardado).split("|")
    if len(partes) < 3:
        return {"cuando": "", "numero": "", "motivo": str(guardado)}
    return {"cuando": partes[0], "numero": partes[1], "motivo": "|".join(partes[2:])}


def ventana_abierta(numero: str) -> bool:
    """
    Si ese número le escribió al bot en las últimas 24 h.

    WhatsApp solo deja mandar texto libre a quien te haya escrito en ese
    plazo. Un número de Ventas recién configurado **nunca** le ha escrito
    al bot, así que su ventana está cerrada desde el primer minuto — y ese
    es el caso que hace que los avisos no lleguen aunque todo esté bien
    puesto.

    Se mira en NUESTRA base y no preguntándole a Meta, porque Meta no
    tiene un endpoint para esto: lo único que sabe de la ventana lo dice
    al rechazar un envío, y aquí hace falta saberlo ANTES de mandar nada.
    """
    from datetime import timedelta
    from app.core.database import Message, ahora_utc, get_session

    if not numero:
        return False

    session = get_session()
    try:
        limite = ahora_utc() - timedelta(hours=24)
        return session.query(Message).filter(
            Message.phone == numero,
            Message.direccion == "entrante",
            Message.created_at >= limite,
        ).first() is not None
    except Exception:
        # Sin poder comprobarlo, no se afirma nada: quien llama lo trata
        # como "no se sabe" y lo dice.
        return False
    finally:
        session.close()


def probar_destinos(destinos: list = None) -> list:
    """
    Manda un aviso de prueba a cada área y cuenta qué pasó con cada una.

    Devuelve `[(nombre, numero, ok, explicacion)]`.

    `destinos` en crudo, tal como vienen del formulario, para poder probar
    un número ANTES de guardarlo. Se pasan por la misma limpieza que usa el
    bot —`ConfiguracionCliente._leer_destinos`— y no por otra escrita
    aparte: si la prueba normalizara el número de una forma y el bot de
    otra, la prueba diría que va bien y el aviso seguiría sin llegar, que
    es peor que no tener prueba.

    Sin argumento, prueba los que ya están configurados.

    POR QUÉ EXISTE
    --------------
    Un aviso que no llega **no da ninguna señal**: el cliente final recibe
    su respuesta con normalidad y el único rastro queda en los logs del
    hosting, que es justo donde no va a mirar quien administra el bot.
    Entre "el número está mal escrito", "hace más de 24 h que esa persona
    no le escribe al bot y no hay plantilla" y "el token no tiene permiso",
    desde fuera no se distingue nada: en los tres casos no pasa nada.

    Esto convierte los tres en una frase en pantalla.

    Va por `_post` y no por `send_text_message` a propósito: una prueba no
    debe quedar registrada en el historial de conversaciones. Si lo
    hiciera, cada comprobación crearía una conversación falsa con el
    número de Ventas en la bandeja del panel.
    """
    if destinos is None:
        limpios = config.AVISOS_DESTINOS or []
    else:
        limpios = config.actual()._leer_destinos(destinos)

    if not limpios:
        limpios = [{"nombre": "Dueño", "numero": config.OWNER_PHONE_NUMBER,
                    "correo": ""}]

    resultados = []
    from app.core import correo as _correo

    # EL CORREO PRIMERO, porque es la vía que se recomienda. Se envía
    # esperando el resultado (`enviar_ahora`) y no en un hilo: el objetivo
    # de este botón es justamente saber si salió.
    for d in limpios:
        direccion = d.get("correo")
        if not direccion:
            continue
        area = d.get("nombre") or ""
        ok, explica = _correo.enviar_ahora(
            [direccion],
            f"Prueba de avisos · {config.BUSINESS_NAME}",
            "Prueba de avisos. Si lees esto, el bot ya puede escribirte "
            "cuando entre un cliente.",
            remitente=config.BUSINESS_NAME)
        resultados.append((f"{area} (correo)".strip(), direccion, ok, explica))

    # WhatsApp solo al que no tiene correo, que es el caso del dueño sin
    # correo de avisos: a las áreas ya no se les avisa por ahí (ver
    # `avisar_dueno`), y probarles un WhatsApp sería probar una vía que
    # no se usa — y pagarla.
    a_probar = [(d.get("numero"), d.get("nombre") or "") for d in limpios
                if not d.get("correo")]

    for numero, area in a_probar:
        if not numero:
            continue

        respuesta = wa._post({
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "text",
            "text": {"body": "Prueba de avisos. Si lees esto, el bot ya "
                             "puede escribirte cuando entre un lead."},
        })

        if respuesta.status_code < 400:
            # ⚠️ 200 SIGNIFICA "LO ACEPTO", NO "LO ENTREGUÉ".
            #
            # Decir aquí "le llegó" es lo que hizo que esta prueba diera un
            # falso OK mientras los avisos no llegaban a nadie. Meta acepta
            # el mensaje y solo después, en un webhook de estado, dice si
            # pudo entregarlo.
            #
            # Lo único que sí se puede afirmar antes de mandarlo es si esa
            # persona le escribió al bot en 24 h, que es la causa nº 1 de
            # que un aviso aceptado no se entregue.
            if ventana_abierta(numero):
                resultados.append((area, numero, True,
                                   "aceptado, y le escribió al bot hace poco: "
                                   "debería llegarle"))
            elif config.OWNER_TEMPLATE_NAME:
                resultados.append((area, numero, True,
                                   "aceptado. OJO: esta persona no le ha "
                                   "escrito al bot en 24 h, así que WhatsApp "
                                   "puede no entregarle este mensaje suelto. "
                                   "Los avisos de verdad sí le llegarán, por "
                                   "plantilla."))
            else:
                resultados.append((area, numero, False,
                                   "aceptado por Meta PERO probablemente no "
                                   "le llegue: no le ha escrito al bot en "
                                   "24 h y este negocio no tiene plantilla "
                                   "de avisos. Que le escriba una vez al "
                                   "bot, o configura la plantilla."))
            continue

        if _es_fuera_de_ventana(respuesta):
            if config.OWNER_TEMPLATE_NAME:
                explica = ("hace más de 24 h que no le escribe al bot, así "
                           "que el aviso saldrá por plantilla. Que le "
                           "escriba una vez al bot y esto se arregla solo.")
            else:
                explica = ("hace más de 24 h que no le escribe al bot y NO "
                           "hay plantilla configurada: sus avisos no van a "
                           "llegar. Que le escriba una vez al bot, o pon la "
                           "plantilla en el contenido del negocio.")
            resultados.append((area, numero, False, explica))
            continue

        resultados.append((area, numero, False, _motivo_de(respuesta)))

    return resultados


def _motivo_de(respuesta) -> str:
    """Lo que dijo Meta, en algo que se pueda leer sin ser programador."""
    try:
        error = respuesta.json().get("error", {})
    except ValueError:
        return f"Meta respondió {respuesta.status_code}"

    codigo = error.get("code")
    texto = (error.get("error_user_msg") or error.get("message") or "").strip()

    # Cada código dice una cosa distinta y mandan a mirar a sitios
    # distintos. Meterlos todos en "revisa el número" haría que dos de los
    # tres casos se buscaran donde no está el problema — que es exactamente
    # lo que este botón existe para evitar.
    #
    # Los que faltan salen tal como los manda Meta: es mejor un mensaje en
    # inglés y exacto que uno en español e inventado.
    explicaciones = {
        # El número no tiene WhatsApp, o no existe. Aquí sí, casi siempre
        # es el país: mal indicativo, o el cero inicial que sobra.
        131026: ("Ese número no recibe WhatsApp. Casi siempre es el país: "
                 "revisa el indicativo y que el número vaya sin el cero "
                 "inicial."),
        # La App del cliente sigue en modo desarrollo: solo puede escribir
        # a los números que estén dados de alta como probadores.
        131030: ("La App de Meta de este cliente todavía solo puede "
                 "escribirle a los números registrados como prueba. Es lo "
                 "que se levanta al conectar su número de verdad."),
        # Token sin permiso, o de otra App.
        190: ("El token de este cliente no vale para enviar. Pídele uno "
              "nuevo de su Usuario del sistema."),
    }

    if codigo in explicaciones:
        return f"{explicaciones[codigo]} (Meta: {texto})" if texto else explicaciones[codigo]

    return texto or f"Meta respondió {respuesta.status_code}"


def _es_fuera_de_ventana(respuesta) -> bool:
    """¿El envío falló por la ventana de 24 horas, o por otra cosa?"""
    try:
        error = respuesta.json().get("error", {})
    except ValueError:
        return False

    if error.get("code") == ERROR_FUERA_DE_VENTANA:
        return True

    # Meta no siempre usa el mismo código para lo mismo; el subcódigo y
    # el texto son la red de seguridad.
    detalle = f"{error.get('message', '')} {error.get('error_data', {})}".lower()
    return "re-engagement" in detalle or "24 hour" in detalle or "24-hour" in detalle
