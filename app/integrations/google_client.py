"""
CLIENTE DE GOOGLE (Calendar + Sheets)
======================================
Carga las credenciales de la cuenta de servicio y entrega los objetos
"service" de la API. No sabe nada del negocio: la lógica de horarios y
de filas vive en calendar_service.py y sheets_service.py.

Las credenciales son de cada negocio (se pegan en su ficha de
`/superadmin`), así que hay un juego de clientes por inquilino.
"""

import json
import os
import re

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app import config

# Permisos que pedimos. Son los mínimos para lo que hace el bot: crear y
# leer eventos, y escribir filas en el Sheet. No pedimos acceso a todo
# Drive a propósito — si el JSON se filtrara, el daño posible es menor.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]

# Se construyen una vez POR CLIENTE y se reutilizan: crear el service en
# cada mensaje agregaría cientos de milisegundos y Meta reintenta el
# webhook si tardamos.
#
# Antes eran tres variables sueltas, una sola copia para todo el proceso.
# Con varios negocios eso significaba que el PRIMERO en agendar dejaba
# puestas sus credenciales para todos: las citas de un cliente acabarían
# en el Google Calendar de otro y sus leads en el Sheet de otro. Por eso
# ahora hay un juego por inquilino.
_credenciales: dict = {}
_calendar: dict = {}
_sheets: dict = {}


def _quien() -> int:
    """
    De quién son las credenciales que toca usar.

    El 0 es "sin inquilino": los scripts de `scripts/` y las pruebas, que
    trabajan con lo que haya en el entorno.
    """
    from app.core import tenencia
    return tenencia.actual_o_none() or 0


def olvidar(client_id: int = None):
    """
    Tira los clientes de Google cacheados. Hay que llamarlo si cambian las
    credenciales de un negocio, o seguiría hablando con la cuenta vieja.
    """
    if client_id is None:
        _credenciales.clear(); _calendar.clear(); _sheets.clear()
        return
    for cache in (_credenciales, _calendar, _sheets):
        cache.pop(client_id, None)


class GoogleNoConfigurado(Exception):
    """Falta configuración de Google, o es inválida."""


def _cargar_credenciales():
    """
    Acepta las dos formas de entregar el JSON de la cuenta de servicio:

    - Una RUTA a un archivo (cómodo en local).
    - El CONTENIDO del JSON (necesario en el hosting, donde no se pueden
      subir archivos pero sí definir variables de entorno).

    Se distinguen por la primera letra: un JSON siempre empieza con "{".
    """
    quien = _quien()
    if quien in _credenciales:
        return _credenciales[quien]

    valor = (config.GOOGLE_SERVICE_ACCOUNT_JSON or "").strip()
    if not valor:
        raise GoogleNoConfigurado(
            "Falta GOOGLE_SERVICE_ACCOUNT_JSON: la ruta al archivo .json de la "
            "cuenta de servicio, o su contenido completo."
        )

    if valor.startswith("{"):
        try:
            datos = json.loads(valor)
        except json.JSONDecodeError as e:
            raise GoogleNoConfigurado(
                f"GOOGLE_SERVICE_ACCOUNT_JSON parece un JSON pero no se puede leer: {e}"
            ) from e
    else:
        if not os.path.exists(valor):
            raise GoogleNoConfigurado(
                f"No existe el archivo de credenciales '{valor}'. Descárgalo de "
                f"Google Cloud > Credenciales > tu cuenta de servicio > Claves."
            )
        with open(valor, encoding="utf-8") as f:
            datos = json.load(f)

    if datos.get("type") != "service_account":
        raise GoogleNoConfigurado(
            "El JSON no es de una cuenta de servicio (le falta \"type\": "
            "\"service_account\"). Puede que hayas descargado credenciales de "
            "OAuth de usuario, que sirven para otra cosa."
        )

    _credenciales[quien] = service_account.Credentials.from_service_account_info(
        datos, scopes=SCOPES
    )
    return _credenciales[quien]


def email_cuenta_servicio() -> str:
    """El email al que hay que compartirle el calendario y el Sheet."""
    return _cargar_credenciales().service_account_email


# Segundos que se espera a Google por llamada. El de fábrica de
# `googleapiclient` es 60, y un mensaje hace varias seguidas —la
# disponibilidad, crear el evento, dos filas del Sheet—: con Google lento,
# el webhook podía quedarse minutos esperando, Meta reintentaba y cada
# reintento ocupaba otro hilo. Con 20 se rinde antes, el bot va por la ruta
# manual y el cliente recibe su respuesta.
TIMEOUT = 20


def _http(credenciales):
    """El transporte HTTP de Google, con credenciales y con nuestro plazo."""
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.http import build_http

    # `build_http` y no un `httplib2.Http` a pelo: trae los ajustes que la
    # librería necesita (las redirecciones 308). Solo se cambia el plazo.
    http = build_http()
    http.timeout = TIMEOUT
    return AuthorizedHttp(credenciales, http=http)


def calendar():
    """Servicio de Google Calendar del negocio en curso."""
    quien = _quien()
    if quien not in _calendar:
        # cache_discovery=False evita un aviso ruidoso en cada arranque:
        # la caché en disco no funciona sin oauth2client, que ya no se usa.
        _calendar[quien] = build("calendar", "v3",
                                 http=_http(_cargar_credenciales()),
                                 cache_discovery=False)
    return _calendar[quien]


def sheets():
    """Servicio de Google Sheets del negocio en curso."""
    quien = _quien()
    if quien not in _sheets:
        _sheets[quien] = build("sheets", "v4",
                               http=_http(_cargar_credenciales()),
                               cache_discovery=False)
    return _sheets[quien]


def id_calendario() -> str:
    valor = (config.GOOGLE_CALENDAR_ID or "").strip()
    if not valor:
        raise GoogleNoConfigurado("Falta GOOGLE_CALENDAR_ID en el .env.")
    return valor


def id_spreadsheet() -> str:
    """
    Devuelve el ID del Sheet.

    Acepta que hayas pegado la URL completa en vez del ID: es lo que uno
    tiene en el portapapeles al venir del navegador, y equivocarse ahí
    produce un error de Google que no explica nada.
    """
    valor = (config.GOOGLE_SHEETS_SPREADSHEET_ID or "").strip()
    if not valor:
        raise GoogleNoConfigurado("Falta GOOGLE_SHEETS_SPREADSHEET_ID en el .env.")

    encontrado = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", valor)
    if encontrado:
        return encontrado.group(1)

    return valor

