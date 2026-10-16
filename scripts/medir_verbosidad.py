"""
CUÁNTOS MENSAJES MANDA EL BOT
==============================
Recorre unas cuantas conversaciones típicas y cuenta los mensajes que
salen hacia WhatsApp, uno por uno.

    python scripts/medir_verbosidad.py            # el resumen
    python scripts/medir_verbosidad.py --detalle  # y qué manda en cada paso

POR QUÉ EXISTE
--------------
Hasta el 30 de septiembre de 2026, los mensajes dentro de la ventana de
24 horas son **gratis**. Desde el **1 de octubre** Meta cobra cada
mensaje de servicio, y entonces:

    una respuesta partida en tres burbujas  =  tres cobros

Eso es una línea del recibo de cada cliente, y crece con cada
conversación. Pero "el bot habla de más" es una opinión hasta que hay un
número: esto lo da, antes y después de tocar nada.

No manda nada a Meta ni escribe en Google: usa una base temporal y
sustituye los envíos por una lista en memoria, igual que la suite de
regresión.

QUÉ NO MIDE
-----------
El coste real, que depende de la tarifa por país que Meta publica el
1-sep-2026 y del tipo de conversación. Aquí se cuentan **mensajes**, que
es lo único que depende de nosotros.
"""

import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(tempfile.mkdtemp(), "medir.db").replace("\\", "/"))
os.environ.setdefault("ADMIN_API_KEY", "clave-de-medida")

from datetime import date, datetime, time, timedelta   # noqa: E402

from app.core import database                      # noqa: E402
from app.bot import bot_logic, whatsapp_client     # noqa: E402
from app.integrations import calendar_service      # noqa: E402
from app.integrations import sheets_service        # noqa: E402

enviados = []


class _Respuesta:
    status_code = 200
    text = "{}"

    def json(self):
        return {}


def _texto(to, text, autor="bot"):
    enviados.append((to, "texto", text))
    return _Respuesta()


def _botones(to, text, buttons):
    enviados.append((to, "botones", text))
    return _Respuesta()


def _lista(to, text, boton, opciones, titulo="Opciones"):
    enviados.append((to, "lista", text))
    return _Respuesta()


def _plantilla(to, plantilla, idioma, variables):
    enviados.append((to, "plantilla", plantilla))
    return _Respuesta()


whatsapp_client.send_text_message = _texto
whatsapp_client.send_button_message = _botones
whatsapp_client.send_list_message = _lista
whatsapp_client.send_template_message = _plantilla
sheets_service.registrar_lead = lambda *a, **k: True

# ── Google, simulado ─────────────────────────────────────────────────
# El agendamiento es de los recorridos que más mensajes encadenan, así
# que tiene que entrar en la medida. No se llama al calendario de verdad:
# ni se depende de la red ni se crean eventos.
DIA = date.today() + timedelta(days=3)
_HORAS = [datetime.combine(DIA, time(9)), datetime.combine(DIA, time(11)),
          datetime.combine(DIA, time(15))]

calendar_service.dias_con_disponibilidad = lambda: [(DIA, 3)]
calendar_service.horarios_libres = lambda fecha: _HORAS
calendar_service.sigue_libre = lambda inicio: True
calendar_service.crear_evento = (
    lambda nombre, telefono, inicio, detalle=None: "evt_medida")


def imprimir(linea: str):
    """
    Un print que no revienta con los emojis del bot.

    La consola de Windows usa cp1252 y los textos del bot llevan varios.
    Sin esto, la medida entera se cae por un print. Es el mismo apaño que
    ya tenía `tests/test_regresion.py`.
    """
    try:
        print(linea)
    except UnicodeEncodeError:
        codificacion = sys.stdout.encoding or "ascii"
        print(linea.encode(codificacion, "replace").decode(codificacion))


_n = 0


def entra(phone, **como):
    """Un mensaje del cliente, y devuelve lo que el bot contestó."""
    global _n
    _n += 1
    antes = len(enviados)
    bot_logic.handle_incoming_message(
        phone, "text", message_id=f"wamid.medir.{_n}", **como)
    return enviados[antes:]


# ── Las conversaciones que se miden ──────────────────────────────────
# Son las que de verdad ocurren: preguntar precios, pedir una reunión,
# hablar con una persona. Cada paso es lo que HACE el cliente; lo que
# cuenta es lo que el bot contesta a cada uno.
GUIONES = {
    "Pregunta precios y se va": [
        ("escribe 'hola'", {"text": "hola"}),
        ("dice su nombre", {"text": "Ana"}),
        ("elige un servicio", {"list_id": "opt_chatbot"}),
        ("pide precios", {"button_id": "chatbot_precios"}),
    ],
    "Compara dos servicios": [
        ("escribe 'hola'", {"text": "hola"}),
        ("dice su nombre", {"text": "Luis"}),
        ("elige un servicio", {"list_id": "opt_chatbot"}),
        ("pide precios", {"button_id": "chatbot_precios"}),
        ("vuelve al menú", {"text": "menu"}),
        ("elige otro servicio", {"list_id": "opt_powerbi"}),
        ("pide precios", {"button_id": "powerbi_precios"}),
    ],
    "Agenda una reunión": [
        ("escribe 'hola'", {"text": "hola"}),
        ("dice su nombre", {"text": "Jorge"}),
        ("elige un servicio", {"list_id": "opt_chatbot"}),
        ("pide reunión", {"button_id": "chatbot_reunion"}),
        ("elige el día", {"list_id": "dia_" + DIA.isoformat()}),
        ("elige la hora", {"button_id": "hora_" + _HORAS[1].isoformat()}),
    ],
    "Pide hablar con una persona": [
        ("escribe 'hola'", {"text": "hola"}),
        ("dice su nombre", {"text": "Marta"}),
        ("elige un servicio", {"list_id": "opt_chatbot"}),
        ("pide asesor", {"button_id": "chatbot_asesor"}),
        ("cuenta lo suyo", {"text": "quiero saber si sirve para mi negocio"}),
    ],
}


def medir(nombre, pasos, detalle=False):
    phone = "5730099" + str(abs(hash(nombre)) % 100000).zfill(5)
    enviados.clear()

    total = 0
    filas = []
    for etiqueta, como in pasos:
        salida = entra(phone, **como)
        # Solo cuenta lo que va AL CLIENTE. El aviso al dueno sale por
        # el mismo sitio y contarlo aqui llevaba a la conclusion
        # equivocada: que el traspaso a un asesor manda dos mensajes de
        # mas. Manda uno al cliente y uno al dueno, y el del dueno ni se
        # le cobra a el ni se puede quitar.
        suyos = [e for e in salida if e[0] == phone]
        total += len(suyos)
        filas.append((etiqueta, len(suyos), salida))

    imprimir(f"\n  {nombre}")
    imprimir(f"  {'-' * len(nombre)}")
    for etiqueta, cuantos, salida in filas:
        aviso = "  <-- de mas" if cuantos > 1 else ""
        imprimir(f"    {cuantos}  {etiqueta}{aviso}")
        if detalle:
            for destino, clase, texto in salida:
                limpio = " ".join((texto or "").split())[:60]
                quien = "cliente" if destino == phone else "DUENO"
                imprimir(f"          [{quien}/{clase}] {limpio}")
    imprimir(f"    {total} mensajes en total, "
             f"{len(pasos)} del cliente "
             f"({total / len(pasos):.1f} por cada uno)")
    return total, len(pasos)


def main():
    detalle = "--detalle" in sys.argv
    database.init_db()

    print("=" * 62)
    print("  CUANTOS MENSAJES MANDA EL BOT")
    print("=" * 62)

    mensajes = pasos = 0
    for nombre, guion in GUIONES.items():
        m, p = medir(nombre, guion, detalle)
        mensajes += m
        pasos += p

    print("\n" + "=" * 62)
    print(f"  {mensajes} mensajes del bot para {pasos} del cliente "
          f"({mensajes / pasos:.2f} por cada uno)")
    print("=" * 62)
    print("\n  Lo que se busca es 1.00: una respuesta por cada cosa que")
    print("  hace el cliente. Cada decima por encima son mensajes que")
    print("  desde el 1-oct-2026 se le cobran al cliente.\n")


if __name__ == "__main__":
    main()
