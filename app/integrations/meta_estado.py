"""
¿LAS CREDENCIALES DE ESTE CLIENTE SIRVEN?
==========================================
Le pregunta a Meta por el token, el número y el tramo de envío de UN
negocio, y devuelve algo que se pueda pintar en el super-admin.

POR QUÉ EXISTE
--------------
Desde que cada cliente trae su propia App de Meta, el alta pasó de "dame
tu número" a pegar cuatro credenciales que saca de un panel que no
entiende. El fallo más probable ya no es un error del bot: es un token
mal copiado, uno temporal que caducó a las 24 h, o una App que no quedó
suscrita al webhook.

Y todos esos fallos tienen **el mismo síntoma**: "el bot no responde".
Indistinguible de la base caída, del despliegue roto o de un cliente
pausado. Sin esto, cada uno de esos casos es una sesión de diagnóstico
leyendo logs; con esto, es un botón que dice cuál de los cuatro es.

EL TRAMO DE ENVÍO, QUE ES EL QUE MUERDE CALLADO
-----------------------------------------------
Un negocio que todavía no completó su Business Verification puede mandar
**250 mensajes cada 24 h**. Al 251 Meta empieza a rechazar, el bot deja de
contestar de golpe y en el panel no se ve nada raro: es el mismo silencio
que un token revocado.

Por eso el tramo se lee y se enseña aunque todo lo demás esté bien. Es la
única forma de que se sepa ANTES de que el cliente llame.

NO LEE `config`
---------------
Las credenciales llegan por parámetro. Este módulo lo llama `/superadmin`,
que corre SIN inquilino fijado a propósito, así que aquí no hay ningún
`config.LO_QUE_SEA` que resolver — y no debe haberlo. Además así se puede
probar una credencial que todavía no está guardada en ninguna fila, que es
justo lo que hace falta al dar de alta.

NUNCA LEVANTA UNA EXCEPCIÓN
---------------------------
Meta se cae, la red falla y los tokens caducan. Un botón de diagnóstico
que revienta cuando lo que diagnostica está roto no sirve para nada.
"""

import requests

# La versión va aquí y no por parámetro: es contra qué API habla este
# código, no un dato de ningún negocio (ver `app/config.py`).
from app import config

TIMEOUT = 15

OK = "ok"
AVISO = "aviso"
MAL = "mal"


def _grafo() -> str:
    return f"https://graph.facebook.com/{config.GRAPH_API_VERSION}"


def _linea(estado: str, titulo: str, detalle: str = "") -> dict:
    return {"estado": estado, "titulo": titulo, "detalle": detalle}


def _error_de(respuesta) -> str:
    """El mensaje que manda Meta, que suele decir exactamente qué falta."""
    try:
        error = respuesta.json().get("error", {})
        texto = error.get("error_user_msg") or error.get("message") or ""
        codigo = error.get("code")
        return f"{texto} (code={codigo})" if codigo else texto
    except Exception:
        return f"HTTP {respuesta.status_code}"


def _tapar(linea: dict, *credenciales: str) -> dict:
    """
    Quita las credenciales de un texto que va a salir a pantalla.

    **META DEVUELVE EL TOKEN DENTRO DE SUS MENSAJES DE ERROR.** Un token
    mal copiado se contesta con *"Malformed access token EAAG..."*, con el
    token entero pegado. Ese texto acaba en la banda del super-admin, y de
    ahí en la URL de redirección — o sea en el historial del navegador y en
    los logs del servidor, que es exactamente donde una credencial de un
    cliente no puede estar.

    Se tapa aquí y no en quien pinta: este módulo es el único que conoce
    los secretos, así que es el único sitio donde no se puede olvidar. Lo
    descubrió una comprobación en el navegador; ninguna suite lo habría
    visto, porque el HTML servido era correcto.
    """
    for secreto in credenciales:
        # Menos de 8 caracteres no es una credencial de verdad, y taparlo
        # destrozaría textos normales que la contengan por casualidad.
        if not secreto or len(secreto) < 8:
            continue
        for campo in ("titulo", "detalle"):
            if secreto in linea[campo]:
                linea[campo] = linea[campo].replace(secreto, "«oculto»")
    return linea


def revisar(whatsapp_token: str, app_id: str = "", app_secret: str = "",
            phone_number_id: str = "", waba_id: str = "") -> dict:
    """
    Comprueba las credenciales de un cliente contra la Graph API.

    Devuelve `{"estado": "ok"|"aviso"|"mal", "lineas": [...]}`, donde cada
    línea es una comprobación con su propio estado. El estado general es
    el peor de los suyos.

    `aviso` y `mal` significan cosas distintas y no hay que mezclarlas:
    **mal** es "esto no funciona" (token inválido, número que no es suyo);
    **aviso** es "funciona, pero hay algo que saber" — el caso del tramo de
    250, que atiende perfectamente hasta que deja de hacerlo.
    """
    lineas = []

    if not whatsapp_token:
        return {"estado": MAL,
                "lineas": [_linea(MAL, "No hay token guardado",
                                  "Sin token no se puede ni preguntar.")]}

    lineas.append(_revisar_token(whatsapp_token, app_id, app_secret))
    lineas.append(_revisar_numero(whatsapp_token, phone_number_id, waba_id))

    if waba_id:
        lineas.append(_revisar_suscripcion(whatsapp_token, waba_id))

    lineas = [_tapar(x, whatsapp_token, app_secret)
              for x in lineas if x is not None]

    if any(x["estado"] == MAL for x in lineas):
        general = MAL
    elif any(x["estado"] == AVISO for x in lineas):
        general = AVISO
    else:
        general = OK

    return {"estado": general, "lineas": lineas}


def _revisar_token(token: str, app_id: str, app_secret: str) -> dict:
    """
    Si el token vale y si CADUCA, que es lo que más se equivoca.

    El token que Meta enseña de primeras en el panel de la App dura 24 h.
    El que hace falta lo genera un System User y no expira nunca. Los dos
    se ven igual, funcionan igual el primer día, y el segundo el bot está
    mudo. Distinguirlos pide `debug_token`, y eso pide App ID y App Secret.
    """
    if not (app_id and app_secret):
        # Sin App ID/Secret no se puede inspeccionar, pero el token se
        # prueba igual en la llamada siguiente. No es un fallo: es una
        # comprobación que no se puede hacer.
        return _linea(AVISO, "No se puede revisar si el token caduca",
                      "Falta el App ID o el App Secret de la App del "
                      "cliente. Un token temporal deja el bot mudo a las "
                      "24 h y así no hay forma de verlo venir.")

    try:
        r = requests.get(f"{_grafo()}/debug_token", timeout=TIMEOUT, params={
            "input_token": token,
            "access_token": f"{app_id}|{app_secret}",
        })
    except Exception as e:
        return _linea(MAL, "No se pudo hablar con Meta", str(e))

    if r.status_code >= 400:
        return _linea(MAL, "Meta rechazó la consulta del token", _error_de(r))

    datos = (r.json() or {}).get("data", {})

    if not datos.get("is_valid"):
        return _linea(MAL, "El token NO es válido",
                      "Caducado o revocado. Hay que pedirle al cliente uno "
                      "nuevo de su System User.")

    faltan = [p for p in ("whatsapp_business_messaging",
                          "whatsapp_business_management")
              if p not in (datos.get("scopes") or [])]
    if faltan:
        return _linea(MAL, "Al token le faltan permisos",
                      f"No trae {', '.join(faltan)}. Se marcan al generarlo "
                      f"en el System User.")

    if datos.get("expires_at"):
        from datetime import datetime
        cuando = datetime.fromtimestamp(datos["expires_at"]).strftime("%Y-%m-%d %H:%M")
        return _linea(MAL, f"El token CADUCA el {cuando}",
                      "Es un token temporal, no de System User. El bot va a "
                      "funcionar hasta esa fecha y después se queda mudo sin "
                      "avisar. Pídele uno permanente antes de cobrarle.")

    return _linea(OK, "Token permanente y con los permisos correctos")


def _revisar_numero(token: str, phone_number_id: str, waba_id: str) -> dict:
    """
    Que el número exista, sea de esa WABA, y EN QUÉ TRAMO DE ENVÍO está.

    Se pregunta por el número directamente y no por la lista de la WABA:
    así funciona aunque el `waba_id` no esté guardado, que es lo normal al
    dar de alta.
    """
    if not phone_number_id:
        return _linea(MAL, "No hay phone_number_id guardado",
                      "Es lo que dice por qué número sale cada respuesta. "
                      "Sin él no se le puede contestar a nadie.")

    try:
        r = requests.get(f"{_grafo()}/{phone_number_id}", timeout=TIMEOUT, params={
            "access_token": token,
            "fields": ("display_phone_number,verified_name,quality_rating,"
                       "code_verification_status,messaging_limit_tier"),
        })
    except Exception as e:
        return _linea(MAL, "No se pudo hablar con Meta", str(e))

    if r.status_code >= 400:
        return _linea(MAL, "El número no responde",
                      _error_de(r) + " — suele ser un phone_number_id que no "
                                     "es de este token.")

    n = r.json() or {}
    nombre = n.get("verified_name") or "(sin nombre)"
    numero = n.get("display_phone_number") or "(sin número)"
    tramo = n.get("messaging_limit_tier") or ""

    # EL TRAMO DE 250. Un negocio sin Business Verification puede mandar
    # 250 mensajes cada 24 h; al 251 Meta rechaza y el bot calla. Es un
    # aviso y no un fallo: hoy atiende bien, y por eso no se ve venir.
    if "250" in str(tramo) or str(tramo).upper().endswith("_250"):
        return _linea(AVISO, f"{numero} ({nombre}) — tope de 250 cada 24 h",
                      "Este negocio todavía no completó su Business "
                      "Verification. Funciona, pero pasados 250 mensajes en "
                      "un día deja de responder de golpe, sin más señal que "
                      "el silencio. Dile que haga la verificación antes de "
                      "que le pase.")

    detalle = f"tramo de envío: {tramo}" if tramo else ""
    return _linea(OK, f"{numero} ({nombre})", detalle)


def _revisar_suscripcion(token: str, waba_id: str) -> dict:
    """
    Si hay una App suscrita a la WABA. Sin esto, el cliente puede RECIBIR
    las respuestas del bot pero el bot no se entera de que le escribieron:
    los mensajes entrantes no llegan nunca al webhook.

    Es el fallo más desconcertante de todos, porque el envío de prueba sí
    funciona y todo parece bien configurado.
    """
    try:
        r = requests.get(f"{_grafo()}/{waba_id}/subscribed_apps",
                         timeout=TIMEOUT, params={"access_token": token})
    except Exception as e:
        return _linea(AVISO, "No se pudo comprobar la suscripción", str(e))

    if r.status_code >= 400:
        return _linea(AVISO, "No se pudo comprobar la suscripción", _error_de(r))

    suscritas = (r.json() or {}).get("data", [])
    if not suscritas:
        return _linea(MAL, "Ninguna App suscrita a esta cuenta",
                      "Los mensajes que le escriban al cliente NO van a "
                      "llegar al bot. Se arregla desde la App de Meta del "
                      "cliente, suscribiéndola a la WABA.")

    nombres = ", ".join(
        (a.get("whatsapp_business_api_data") or {}).get("name") or "?"
        for a in suscritas)
    return _linea(OK, f"App suscrita al webhook: {nombres}")
