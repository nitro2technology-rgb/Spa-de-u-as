"""
CLIENTE DE WHATSAPP (Meta Cloud API)
=====================================
Funciones para enviar mensajes. Es el ÚNICO sitio que habla con Meta, y
por eso aquí se aplican sus topes (ver LIMITE_*). No hace falta tocarlo
para adaptar el bot a un negocio: eso es su contenido, en `/superadmin`.

Los envíos con archivo (imagen, audio, documento) esperan un `media_id`
que ya esté subido: subirlo es trabajo de `app/core/media.py`, porque va
en multipart y no en JSON como todo lo de aquí. La división es a
propósito — este archivo habla de MENSAJES, aquel de ARCHIVOS.
"""

import requests

from app import config
from app.core import message_log

def _url() -> str:
    """
    El endpoint por el que sale un mensaje, para el negocio en curso.

    Es una función y no una constante de módulo porque el número
    (`PHONE_NUMBER_ID`) es de cada cliente: calculada al importar, se
    quedaría congelada con la del primer negocio y TODOS los mensajes
    saldrían por su número. El cliente final de un negocio recibiría la
    respuesta desde el WhatsApp de otro.
    """
    return (f"https://graph.facebook.com/{config.GRAPH_API_VERSION}"
            f"/{config.PHONE_NUMBER_ID}/messages")


def _headers():
    return {
        "Authorization": f"Bearer {config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }


# ⚠️  LOS TOPES DE META NO SE NEGOCIAN, Y PASARSE NO RECORTA: RECHAZA.
#
# Esta es la regla que gobierna todo este archivo. Si un payload se pasa
# de cualquiera de estos números, Meta **descarta el mensaje entero** y
# devuelve un 400. No manda una versión corta: no manda nada.
#
# Y el bot no se entera. No hay excepción, el código sigue como si todo
# hubiera ido bien, y en el chat del cliente no aparece nada. Visto desde
# el teléfono, un botón que no hace nada.
#
# Costó un "el bot se congela en Ver ejemplos": el dueño escribió un
# texto largo en una opción y su mensaje pasó de 1024 caracteres. En
# `/superadmin` el texto estaba perfectamente guardado.
#
# Por eso los topes se aplican AQUÍ, en el único sitio que habla con
# Meta, y no se confía en que quien llama se acuerde.
LIMITE_TEXTO = 4096          # cuerpo de un mensaje de texto normal
LIMITE_CUERPO_INTERACTIVO = 1024   # cuerpo de uno con botones o lista
LIMITE_TITULO_BOTON = 20     # lo que se lee DENTRO de un botón
LIMITE_TITULO_FILA = 24      # el de una fila de lista, que da para más
LIMITE_DESCRIPCION_FILA = 72
MAX_BOTONES = 3
MAX_FILAS = 10


def _trozos(texto: str, limite: int) -> list:
    """
    Parte un texto largo en trozos que Meta sí acepte.

    Se parte por párrafos, y si un párrafo solo ya se pasa, por líneas;
    lo que aún no quepa se corta a lo bruto. Se prefiere **partir a
    recortar**: lo escribió el dueño para que su cliente lo lea, y perder
    la mitad final sin avisar es lo mismo que perderlo entero, solo que
    más difícil de notar.
    """
    texto = texto or ""
    if len(texto) <= limite:
        return [texto]

    trozos, actual = [], ""
    for parrafo in texto.split("\n\n"):
        # Un párrafo que por sí solo no cabe: se parte por líneas.
        piezas = [parrafo] if len(parrafo) <= limite else parrafo.split("\n")
        for pieza in piezas:
            # Y si ni una línea cabe, se corta a lo bruto.
            while len(pieza) > limite:
                if actual:
                    trozos.append(actual)
                    actual = ""
                trozos.append(pieza[:limite])
                pieza = pieza[limite:]

            separador = "\n\n" if actual and pieza in parrafo.split("\n\n") else "\n"
            if not actual:
                actual = pieza
            elif len(actual) + len(separador) + len(pieza) <= limite:
                actual += separador + pieza
            else:
                trozos.append(actual)
                actual = pieza

    if actual:
        trozos.append(actual)
    return [t for t in trozos if t] or [""]


def send_text_message(to: str, text: str, autor: str = "bot"):
    """
    Envía un mensaje de texto simple.

    `autor` distingue en el historial lo que escribió el bot solo de lo
    que escribió una persona desde el panel.

    Si el texto se pasa de los 4096 caracteres se manda en varios: Meta
    rechazaría el mensaje entero y el cliente no recibiría NADA.
    """
    respuesta = None
    for trozo in _trozos(text, LIMITE_TEXTO):
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": trozo},
        }
        respuesta = _post(payload)

        if respuesta.status_code < 400:
            message_log.registrar(to, "saliente", autor, trozo)
        else:
            break

    return respuesta


def send_button_message(to: str, text: str, buttons: list):
    """
    Envía un mensaje con botones interactivos (máximo 3).

    buttons: lista de dicts [{"id": "opt_x", "title": "Texto botón"}, ...]

    Aquí se aplican los topes de Meta, que antes no se aplicaban en
    ninguna parte —`send_list_message` sí los aplicaba, este no— y por eso
    un botón con el título un poco largo tumbaba el mensaje ENTERO: el
    cliente pulsaba y no recibía nada. Ver el bloque de LIMITE_*.

    Un cuerpo que no cabe se manda como texto aparte ANTES de los
    botones, en vez de recortarlo: son los precios, la explicación, lo que
    el dueño escribió para que lo lean.
    """
    buttons = list(buttons or [])[:MAX_BOTONES]

    if not buttons:
        # Meta exige entre 1 y 3. Con cero rechaza el mensaje, así que se
        # manda el texto solo: peor sería que el cliente no leyera nada.
        print("[whatsapp_client] Un mensaje de botones sin ninguna opción; "
              "se manda como texto.")
        return send_text_message(to, text)

    respuesta = None
    cuerpo = text or ""
    if len(cuerpo) > LIMITE_CUERPO_INTERACTIVO:
        trozos = _trozos(cuerpo, LIMITE_CUERPO_INTERACTIVO)
        # Todo menos el último trozo va suelto; el último acompaña a los
        # botones, para que la pregunta quede pegada a las opciones.
        for trozo in trozos[:-1]:
            respuesta = send_text_message(to, trozo)
        cuerpo = trozos[-1]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": cuerpo},
            "action": {
                "buttons": [
                    {"type": "reply",
                     "reply": {"id": b["id"][:256],
                               "title": b["title"][:LIMITE_TITULO_BOTON]}}
                    for b in buttons
                ]
            },
        },
    }
    respuesta = _post(payload)

    if respuesta.status_code < 400:
        opciones = " / ".join(b["title"][:LIMITE_TITULO_BOTON] for b in buttons)
        message_log.registrar(to, "saliente", "bot", f"{cuerpo}\n[botones: {opciones}]")

    return respuesta


def send_list_message(to: str, text: str, boton: str, opciones: list, titulo_seccion: str = "Opciones"):
    """
    Envía una lista desplegable interactiva.

    Se usa cuando hay más de 3 opciones (los botones no dan para más).
    opciones: [{"id": "...", "title": "...", "description": "..."}, ...]

    Límites de la API de WhatsApp, que si se pasan hacen fallar el envío
    entero con un error poco descriptivo. Ver el bloque de LIMITE_*.

    El CUERPO también tiene el suyo (1024) y antes no se miraba: las
    filas se recortaban con cuidado y luego un texto largo del dueño
    tumbaba el mensaje igual.
    """
    if len(opciones) > MAX_FILAS:
        # WhatsApp no admite más, y lo que sobra no llega a verse. Se dice
        # en el log: un menú de doce opciones con dos invisibles no da
        # ningún otro síntoma.
        print(f"[whatsapp_client] Una lista de {len(opciones)} opciones: "
              f"solo caben {MAX_FILAS}; las últimas no se ven.")

    filas = []
    for o in opciones[:MAX_FILAS]:
        fila = {"id": o["id"][:200], "title": o["title"][:LIMITE_TITULO_FILA]}
        if o.get("description"):
            fila["description"] = o["description"][:LIMITE_DESCRIPCION_FILA]
        filas.append(fila)

    if not filas:
        print("[whatsapp_client] Una lista sin ninguna fila; se manda como texto.")
        return send_text_message(to, text)

    text = text or ""
    if len(text) > LIMITE_CUERPO_INTERACTIVO:
        trozos = _trozos(text, LIMITE_CUERPO_INTERACTIVO)
        for trozo in trozos[:-1]:
            send_text_message(to, trozo)
        text = trozos[-1]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": boton[:20],
                "sections": [{"title": titulo_seccion[:24], "rows": filas}],
            },
        },
    }
    respuesta = _post(payload)

    if respuesta.status_code < 400:
        titulos = " / ".join(f["title"] for f in filas)
        message_log.registrar(to, "saliente", "bot", f"{text}\n[lista: {titulos}]")

    return respuesta


def send_image_message(to: str, media_id: str, caption: str = "", autor: str = "humano"):
    """
    Envía una imagen ya subida a Meta (ver app/core/media.subir).

    Se manda por `id` y no por `link`: con un enlace, Meta tiene que poder
    alcanzar la URL desde fuera, y las imágenes del panel viven detrás de
    la sesión del dueño. Subirlas primero evita tener que publicar nada.

    El `autor` viene por defecto en "humano" porque el bot no manda
    imágenes solo: esto lo dispara siempre una persona desde el panel.
    """
    imagen = {"id": media_id}
    if caption:
        # Mismo tope que un texto normal, por si alguien pega un pie de
        # foto larguísimo: Meta rechaza el mensaje entero si se pasa.
        imagen["caption"] = caption[:1024]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": imagen,
    }
    respuesta = _post(payload)

    if respuesta.status_code < 400:
        message_log.registrar(to, "saliente", autor, caption or "",
                              media_id=media_id, media_tipo="image",
                              media_mime="image/jpeg")

    return respuesta


def send_audio_message(to: str, media_id: str, mime: str = "audio/ogg",
                       autor: str = "humano", voice: bool = True):
    """
    Envía un audio ya subido a Meta.

    Para que se vea como NOTA DE VOZ hacen falta DOS cosas, y las dos:

    1. Que el archivo sea OGG/Opus mono (de eso se encarga media.py).
    2. **`"voice": true` en este payload.**

    El segundo es el que no es evidente. Con el formato correcto pero sin
    la bandera, Meta acepta el envío, el cliente lo recibe y lo puede
    reproducir... como un archivo adjunto. Se ve perfecto en los logs y
    mal en el teléfono, que es la peor combinación.

    `voice=False` es para cuando la conversión no se pudo hacer: se manda
    igual, como adjunto, en vez de dejar al dueño sin poder responder.
    """
    audio = {"id": media_id}
    if voice:
        audio["voice"] = True

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": audio,
    }
    respuesta = _post(payload)

    if respuesta.status_code < 400:
        message_log.registrar(to, "saliente", autor, "",
                              media_id=media_id, media_tipo="audio",
                              media_mime=mime)

    return respuesta


def send_template_message(to: str, plantilla: str, idioma: str, variables: list):
    """
    Envía una plantilla aprobada por Meta.

    Es la única forma de escribirle a alguien que lleva más de 24 horas
    sin responder. Las variables sustituyen a {{1}}, {{2}}... en el orden
    en que se pasan.

    Meta rechaza la plantilla si algún valor lleva saltos de línea o
    tabulaciones, así que se limpian antes de enviarlos.
    """
    parametros = [
        {"type": "text", "text": " ".join(str(v).split())[:900] or "-"}
        for v in variables
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": plantilla,
            "language": {"code": idioma},
            "components": ([{"type": "body", "parameters": parametros}]
                           if parametros else []),
        },
    }
    respuesta = _post(payload)

    if respuesta.status_code < 400:
        resumen = " | ".join(p["text"] for p in parametros)
        message_log.registrar(to, "saliente", "bot", f"[plantilla {plantilla}] {resumen}")

    return respuesta


class SinRespuesta:
    """
    Lo que devuelve `_post` cuando Meta ni siquiera contestó.

    Tiene la misma forma que una respuesta de `requests` —`status_code`,
    `text`, `json()`— porque todo el que llama mira `status_code` para
    decidir. Antes un fallo de red subía como excepción, y un Meta lento
    al avisar a un área salía de `handle_incoming_message` ANTES del
    commit: el lead no se guardaba en la base, y el cliente, que sí había
    recibido su respuesta, no notaba nada.
    """

    status_code = 599

    def __init__(self, motivo: str):
        self.text = motivo

    def json(self):
        return {"error": {"message": self.text}}


def _post(payload: dict):
    try:
        response = requests.post(_url(), headers=_headers(), json=payload,
                                 timeout=15)
    except requests.RequestException as e:
        print(f"[whatsapp_client] SIN RESPUESTA DE META ({payload.get('type')}): "
              f"{type(e).__name__}: {e}. EL CLIENTE NO LO RECIBIÓ.")
        return SinRespuesta(f"{type(e).__name__}: {e}")

    if response.status_code >= 400:
        # Se dice con todas las letras que el cliente NO recibió nada. Un
        # "Error enviando mensaje" a secas se lee como un aviso; esto es
        # una entrega perdida, y el que lo lea tiene que saberlo sin
        # tener que ir a mirar qué hace el código de después.
        print(f"[whatsapp_client] META RECHAZÓ el mensaje "
              f"({payload.get('type')}): {response.status_code} {response.text}. "
              f"EL CLIENTE NO LO RECIBIÓ.")
    return response
