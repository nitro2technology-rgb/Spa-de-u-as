"""
CEREBRO DEL PLAN PRO (Gemini)
==============================
Traduce lo que el cliente escribe a mano en una intención del menú, o le
responde una pregunta suelta sobre el negocio.

**Este es el ÚNICO archivo del repo que sabe que Gemini existe.** Esa es
la regla que mantiene el plan Básico y el plan Pro en un solo código: un
arreglo en `bot_logic.py` sirve para los dos, porque es el mismo archivo.
Si algún día un cambio de Gemini pide tocar otro sitio, lo que hay que
arreglar es la interfaz de `base.py`, no esparcir la IA por el proyecto.

Dos cosas que este módulo NO hace, a propósito:

  - **No inventa textos de venta.** Elige QUÉ opción del menú corresponde;
    los precios, los enlaces y las confirmaciones salen de `negocio.toml`
    como siempre. Un modelo no puede equivocarse en un precio si nunca se
    le pide que lo escriba.
  - **No agenda.** Puede decidir que el cliente quiere una cita, pero la
    cita la crea el mismo código de siempre contra Google Calendar, con
    disponibilidad real.

Y la regla que manda sobre todo lo demás:

    SI GEMINI FALLA, EL BOT SIGUE VENDIENDO.

Cualquier fallo —sin clave, sin librería, timeout, cuota agotada, JSON
roto, id inventado— devuelve `NO_SE` y el bot responde lo que respondía
antes de que existiera la IA. Es el mismo trato que ya tienen Calendar y
Sheets (`CalendarNoDisponible`, `GoogleNoConfigurado`): una API de
terceros caída no puede costarte un cliente.
"""

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturoVencido

from app import config
from app.bot.cerebro.base import NO_SE, Decision
from app.core import consumo, tenencia
from app.core.database import ahora_utc

# El cliente se construye una vez POR NEGOCIO y se reutiliza, igual que
# los services de Google (app/integrations/google_client.py). Construirlo
# en cada mensaje añadiría cientos de milisegundos, y Meta reintenta el
# webhook si tardamos.
#
#     ⚠️  UNO POR INQUILINO, NO UNO Y YA.
#
# Cada negocio paga su propio consumo de IA. Con un solo cliente global,
# el PRIMERO que hablara dejaría su clave puesta para todo el proceso: los
# mensajes de los demás negocios se responderían con su clave y el consumo
# se le cargaría a él. Es el tipo de fallo que no da ningún error y se
# descubre leyendo una factura.
_clientes: dict = {}
_intento_fallido: dict = {}

# El último fallo, para poder verlo desde el panel. También por inquilino:
# si no, el panel de un negocio enseñaría el problema de otro.
#
# La degradación es silenciosa a propósito —el cliente nunca se entera de
# que la IA se cayó—, pero eso deja a quien administra el bot sin ninguna
# pista: "activé la IA y responde igual que antes" y a buscar en los logs.
# Guardando aquí el motivo, /admin/status y el panel pueden decirlo.
#
# Solo el último de cada uno: no es un registro, es "qué está pasando".
_ultimo_fallo: dict = {}


def _quien() -> int:
    """
    De quién es la IA que toca usar. 0 = sin inquilino (scripts, pruebas).
    """
    return tenencia.actual_o_none() or 0


def olvidar(client_id: int = None):
    """
    Tira el cliente de Gemini cacheado. Hay que llamarlo si cambian la
    clave o el modelo de un negocio, o seguiría usando los viejos.
    """
    if client_id is None:
        _clientes.clear(); _intento_fallido.clear(); _ultimo_fallo.clear()
        return
    for cache in (_clientes, _intento_fallido, _ultimo_fallo):
        cache.pop(client_id, None)


def _anotar_fallo(motivo: str):
    """Deja constancia del fallo para el panel, además del log."""
    _ultimo_fallo[_quien()] = {
        "motivo": motivo[:300],
        "cuando": ahora_utc().isoformat(timespec="seconds"),
    }
    print(f"[cerebro] {motivo}")


def ultimo_fallo():
    """El último fallo de la IA de este negocio, o None si va todo bien."""
    return _ultimo_fallo.get(_quien())


def olvidar_fallo():
    """Se llama al acertar: si vuelve a funcionar, el aviso desaparece."""
    _ultimo_fallo.pop(_quien(), None)

# Un solo hilo para el tope de tiempo. La librería trae su propio timeout,
# pero este es el que de verdad garantiza que no nos quedamos colgados:
# vale igual si el cuelgue pasa en un sitio que la librería no controla.
_ejecutor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gemini")


# ── Lo que el SDK hace por su cuenta, acotado ────────────────────────
#
# El SDK de Gemini REINTENTA solo cuando Google devuelve un 503, y lo hace
# con esperas que crecen. Medido contra el modelo de producción: entre
# llamadas de 0,8 s apareció una de **28,6 s**, que es esa cadena de
# reintentos.
#
# El cronómetro de `interpretar` corta a los 8 s, así que el cliente
# recibe su menú y eso no se ve desde fuera. El problema es lo que queda
# por dentro: `ThreadPoolExecutor` NO cancela nada, o sea que el hilo
# sigue reintentando después de que nos rindiéramos. Con cuatro hilos,
# unos cuantos tropiezos seguidos dejan a los mensajes siguientes
# esperando turno — un mal rato de Google convertido en un bot lento para
# todos, y sin ninguna señal que lo diga.
#
#     ⚠️  El tiempo por intento NO se puede bajar de 10 segundos.
#
# `HttpOptions.timeout` viaja a Google como plazo de la petición, y la API
# rechaza con un 400 cualquier valor menor: "Manually set deadline 4s is
# too short. Minimum allowed deadline is 10s". O sea que **no se puede
# hacer que la capa HTTP se rinda antes que nuestro cronómetro**: quien
# manda en lo que espera el cliente sigue siendo el tope de 8 s de
# `interpretar`. Lo que sí se acota aquí es el trabajo de fondo, que es lo
# que el cronómetro no alcanza.
INTENTOS_HTTP = 2
ESPERA_ENTRE_INTENTOS = 0.5

# El mínimo que Google acepta, en milisegundos. Ponerlo explícito y al
# mínimo no acelera ninguna respuesta: acota cuánto puede quedarse colgado
# un intento que nadie está ya esperando.
TIMEOUT_HTTP_MS = 10_000


class GeminiNoDisponible(Exception):
    """
    Falta configuración de Gemini, o es inválida.

    Dentro del bot nunca se ve: `interpretar` la atrapa y devuelve `NO_SE`.
    Existe para `scripts/gemini_setup.py`, que sí quiere el error completo
    para poder explicárselo a quien está configurando el cliente.
    """


def _construir_cliente():
    """
    El cliente de Gemini, construido una vez.

    El import va aquí dentro y no arriba a propósito: el plan Básico no
    tiene por qué llevar la librería instalada. Si falta, esto levanta
    `GeminiNoDisponible` como cualquier otro fallo de configuración y el
    bot se va al menú, en vez de caerse al arrancar.
    """
    quien = _quien()

    if quien in _clientes:
        return _clientes[quien]

    # Un negocio cuya clave ya falló no se reintenta en cada mensaje: no va
    # a arreglarse sola y cada intento cuesta tiempo dentro del webhook. Se
    # marca solo a ESE negocio: que a uno le falle la clave no puede dejar
    # sin IA a los demás.
    if _intento_fallido.get(quien):
        raise GeminiNoDisponible("Gemini ya falló al configurarse en este proceso.")

    if not config.GEMINI_API_KEY:
        _intento_fallido[quien] = True
        raise GeminiNoDisponible(
            "Falta GEMINI_API_KEY. Se saca en https://aistudio.google.com/apikey "
            "y se pega en las variables de entorno del servicio.")

    try:
        from google import genai
    except ImportError as e:
        _intento_fallido[quien] = True
        raise GeminiNoDisponible(
            "Falta la librería de Gemini. Instálala con: pip install google-genai") from e

    try:
        from google.genai import types

        _clientes[quien] = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(
                timeout=TIMEOUT_HTTP_MS,
                # Dos intentos y no los cinco de fábrica: el segundo salva
                # los 503 pasajeros, que es lo que suelen ser, y ahí se
                # acaba. Sin esto, un tropiezo de Google deja un hilo
                # reintentando un minuto largo.
                retry_options=types.HttpRetryOptions(
                    attempts=INTENTOS_HTTP,
                    initial_delay=ESPERA_ENTRE_INTENTOS,
                    max_delay=ESPERA_ENTRE_INTENTOS * 2,
                ),
            ),
        )
    except Exception as e:
        _intento_fallido[quien] = True
        raise GeminiNoDisponible(f"No se pudo crear el cliente de Gemini: {e}") from e

    return _clientes[quien]


def precalentar():
    """
    Paga el import de la librería de Gemini AL ARRANCAR, no en el primer
    mensaje.

    Importar `google.genai` cuesta entre uno y varios segundos —arrastra
    pydantic, httpx y el resto—, y hasta ahora eso pasaba dentro de
    `_construir_cliente()`, o sea **dentro del tope de 8 segundos** que
    `interpretar` le da a la IA. En una instancia pequeña recién
    desplegada, ese import solo puede comerse el presupuesto entero: el
    primer cliente que escribiera después de cada despliegue se llevaba el
    menú en vez de la IA, y el panel enseñaba "Gemini tardó más de 8s"
    como si el modelo fuera lento. No lo era.

    No construye ningún cliente ni llama al modelo: eso necesita la clave
    de UN negocio y aquí todavía no hay ninguno en curso. Lo caro es el
    import, y el import es del proceso entero, así que precalentarlo les
    sirve a todos los inquilinos.

    Nunca levanta: el plan Básico no tiene por qué llevar la librería, y
    quedarse sin IA no puede impedir arrancar.
    """
    try:
        from google import genai            # noqa: F401
        from google.genai import types      # noqa: F401
    except ImportError:
        # Plan Básico: no hay librería y no hace falta. `interpretar` ya
        # lo trata como un fallo de configuración y responde con el menú.
        pass
    except Exception as e:
        print(f"[cerebro] No se pudo precalentar Gemini: {e}")


# ── El prompt ────────────────────────────────────────────────────────

def _catalogo(opciones: list) -> str:
    """
    El menú del negocio como lista de intenciones válidas.

    Se arma en cada llamada y no una vez al arrancar porque el menú sale
    de `negocio.toml`, y en las pruebas se cambia en caliente. El coste es
    juntar unas pocas cadenas.
    """
    lineas = []
    for o in opciones:
        titulo = o.get("title", "")
        descripcion = o.get("description", "")
        detalle = f" — {descripcion}" if descripcion else ""
        lineas.append(f'- {o["id"]}: {titulo}{detalle}')
    return "\n".join(lineas)


def _instrucciones(opciones: list) -> str:
    """
    Lo que el modelo tiene que saber para decidir. Sale entero de la
    sección [ia] de negocio.toml, así que el cliente ajusta el carácter de
    su bot sin tocar Python, igual que ajusta sus textos.
    """
    partes = [
        f"Eres {config.IA_ROL or f'el asistente de {config.BUSINESS_NAME}'}.",
        f"Hablas por WhatsApp con clientes de {config.BUSINESS_NAME}.",
    ]

    if config.IA_TONO:
        partes.append(f"Tono: {config.IA_TONO}.")

    partes.append(
        "\nTu trabajo es UNA de estas dos cosas, nunca las dos:\n"
        "1. Si lo que pide encaja con una opción del menú, devuelve su id "
        "en `intencion` y deja `respuesta` en null.\n"
        "2. Si pregunta algo que no es ninguna opción, responde en "
        "`respuesta` y deja `intencion` en null.\n"
        "Si no lo tienes claro, deja las dos en null. Es preferible a "
        "acertar por casualidad."
    )

    partes.append(f"\nOpciones del menú (los únicos ids válidos):\n{_catalogo(opciones)}")

    if config.IA_NUNCA:
        prohibiciones = "\n".join(f"- {x}" for x in config.IA_NUNCA)
        partes.append(f"\nNUNCA hagas esto:\n{prohibiciones}")

    if config.IA_SIEMPRE_DERIVAR:
        temas = ", ".join(config.IA_SIEMPRE_DERIVAR)
        partes.append(
            f"\nSi el mensaje trata de: {temas} — no respondas tú. "
            "Deja las dos claves en null para que lo atienda una persona.")

    partes.append(
        f"\nSi respondes, hazlo en máximo {config.IA_MAX_PALABRAS} palabras. "
        "Es WhatsApp: un párrafo largo no se lee."
    )

    partes.append(
        '\nDevuelve SOLO un JSON con esta forma exacta, sin nada más:\n'
        '{"intencion": "id_o_null", "respuesta": "texto_o_null"}'
    )

    return "\n".join(partes)


# ── La llamada ───────────────────────────────────────────────────────

def _preguntar_al_modelo(texto: str, opciones: list) -> tuple:
    """
    La llamada cruda. Devuelve `(texto_de_la_respuesta, tokens)`.

    Los tokens vienen de `usage_metadata`, que es lo que Gemini responde
    junto al texto, y son los que se facturan. No se estiman por longitud
    del prompt: una estimación es una suposición, y aquí se cobra.
    """
    cliente = _construir_cliente()

    from google.genai import types

    respuesta = cliente.models.generate_content(
        model=config.GEMINI_MODELO,
        contents=texto,
        config=types.GenerateContentConfig(
            system_instruction=_instrucciones(opciones),
            response_mime_type="application/json",
            # Baja a propósito: esto es clasificar contra un catálogo
            # cerrado, no escribir. La creatividad aquí solo produce ids
            # que no existen.
            temperature=0.1,
        ),
    )
    return respuesta.text, _tokens_de(respuesta)


def _tokens_de(respuesta) -> tuple:
    """
    Los tokens de entrada y salida que reporta Gemini.

    Con `getattr` y no accediendo directo: el campo cambió de nombre entre
    versiones de la librería, y quedarse sin medir un mes es un problema de
    facturación; quedarse sin responderle a un cliente porque cambió un
    atributo es un problema mucho peor.
    """
    uso = getattr(respuesta, "usage_metadata", None)
    if uso is None:
        return 0, 0
    return (getattr(uso, "prompt_token_count", 0) or 0,
            getattr(uso, "candidates_token_count", 0) or 0)


def _leer_respuesta(crudo: str, opciones: list) -> Decision:
    """
    Convierte lo que devolvió el modelo en una Decision de la que uno se
    pueda fiar. Todo lo que no cuadre se descarta: más vale el menú de
    siempre que una acción inventada.
    """
    if not crudo:
        return NO_SE

    # Aunque se pide JSON puro, a veces llega envuelto en ```json ... ```
    limpio = crudo.strip()
    if limpio.startswith("```"):
        limpio = limpio.split("```")[1] if "```" in limpio[3:] else limpio[3:]
        if limpio.startswith("json"):
            limpio = limpio[4:]
        limpio = limpio.strip("` \n")

    try:
        datos = json.loads(limpio)
    except (ValueError, TypeError):
        _anotar_fallo(f"Gemini no devolvió JSON válido: {crudo[:120]!r}")
        return NO_SE

    if not isinstance(datos, dict):
        return NO_SE

    intencion = _valor(datos.get("intencion"))
    respuesta = _valor(datos.get("respuesta"))

    # Un id que no existe en el menú se tira. Es la barrera que impide que
    # el modelo invente acciones: solo puede elegir entre lo que el negocio
    # escribió en su negocio.toml.
    if intencion:
        ids_validos = {o["id"] for o in opciones}
        if intencion not in ids_validos:
            _anotar_fallo(f"Gemini eligió una opción que no está en el menú: "
                          f"{intencion!r}")
            return NO_SE
        return Decision(intencion=intencion, motivo="intencion de gemini")

    if respuesta:
        return Decision(respuesta=_recortar(str(respuesta)), motivo="respuesta de gemini")

    return NO_SE


def _valor(crudo):
    """
    Lo que el modelo puso en una clave, o None si no puso nada.

    Las instrucciones le enseñan la forma `{"intencion": "id_o_null"}`,
    con comillas, y a veces contesta la PALABRA en vez del valor:
    `"respuesta": "null"`. Con la intención vacía, esa palabra le llegaba
    al cliente como respuesta del bot.
    """
    if crudo is None:
        return None
    texto = str(crudo).strip()
    if texto.lower() in ("", "null", "none", "nulo", "id_o_null", "texto_o_null"):
        return None
    return texto


def _recortar(texto: str) -> str:
    """
    Aplica el tope de palabras de [ia].

    El modelo ya lo tiene en sus instrucciones, pero pedir no es garantizar
    y WhatsApp corta a los 4096 caracteres. Esto es el cinturón además del
    tirante.
    """
    palabras = texto.split()
    if len(palabras) <= config.IA_MAX_PALABRAS:
        return texto[:4000]
    return " ".join(palabras[:config.IA_MAX_PALABRAS]).rstrip(".,;:") + "…"


# ── El tope diario por contacto ──────────────────────────────────────

def _supera_el_tope(contact) -> bool:
    """
    Frena a un contacto que escribe en bucle.

    Sin esto, una persona (o un bot ajeno) escribiendo sin parar le vacía
    la cuota de Gemini al negocio en una tarde. Pasado el tope el bot no
    se calla: sigue con el menú de siempre, que es gratis.

    Se cuenta por intentos y no por aciertos: si la clave está mal, cada
    mensaje fallaría igual y no tiene sentido reintentar mil veces.
    """
    if config.IA_MAX_MENSAJES_DIA <= 0:
        return False  # 0 o menos = sin tope

    hoy = ahora_utc().strftime("%Y-%m-%d")

    if contact.ia_dia != hoy:
        contact.ia_dia = hoy
        contact.ia_mensajes_dia = 0

    if (contact.ia_mensajes_dia or 0) >= config.IA_MAX_MENSAJES_DIA:
        return True

    contact.ia_mensajes_dia = (contact.ia_mensajes_dia or 0) + 1
    return False


# ── La interfaz que usa bot_logic ────────────────────────────────────

def interpretar(contact, texto: str, opciones: list) -> Decision:
    """
    Qué hacer con un mensaje escrito a mano. Ver `base.interpretar`.

    **No levanta excepciones nunca.** Ese contrato es lo que permite que
    `bot_logic` la llame sin envolverla en un try, y lo que garantiza que
    un problema de Gemini no deje a un cliente sin respuesta.
    """
    if not texto or not texto.strip():
        return NO_SE

    if not opciones:
        return NO_SE

    # Dos topes que protegen cosas distintas y por eso conviven:
    #
    #   el diario POR CONTACTO   protege al negocio de una persona en bucle
    #   el mensual POR CLIENTE   protege TU margen del cliente entero
    #
    # Los dos degradan igual: al menú de siempre, que es gratis y vende.
    if consumo.supera_el_tope():
        print(f"[cerebro] el cliente gastó su cupo mensual de IA "
              f"({config.IA_LIMITE_MENSUAL}); sigue con el menú.")
        return NO_SE

    if _supera_el_tope(contact):
        print(f"[cerebro] {contact.phone} superó el tope diario de IA "
              f"({config.IA_MAX_MENSAJES_DIA}); sigue con el menú.")
        return NO_SE

    try:
        # El tope de tiempo es duro: Meta reintenta el webhook si tardamos,
        # y un reintento con el bot pensando es un mensaje duplicado para
        # el cliente. Antes que eso, el menú de siempre.
        # `envolver_para_hilo` no es opcional: ThreadPoolExecutor arranca
        # el hilo con un contexto VACÍO, así que sin esto
        # `_preguntar_al_modelo` no sabría de qué cliente es y leería la
        # configuración base — usando la clave de Gemini del dueño del bot
        # para responder al cliente de otro negocio, y cargándole a él el
        # consumo. Ver app/core/tenencia.py.
        futuro = _ejecutor.submit(
            tenencia.envolver_para_hilo(_preguntar_al_modelo), texto, opciones)
        crudo, (tokens_in, tokens_out) = futuro.result(
            timeout=config.IA_TIMEOUT_SEGUNDOS)
    except FuturoVencido:
        _anotar_fallo(f"Gemini tardó más de {config.IA_TIMEOUT_SEGUNDOS}s; "
                      f"se responde con el menú.")
        return NO_SE
    except GeminiNoDisponible as e:
        _anotar_fallo(f"Gemini no está disponible: {e}")
        return NO_SE
    except Exception as e:
        # Cuota agotada, red caída, la librería cambió de forma: da igual
        # cuál sea. El cliente recibe el menú y nadie se queda sin respuesta.
        _anotar_fallo(f"Gemini falló ({type(e).__name__}: {e}); se responde con el menú.")
        return NO_SE

    # El modelo contestó, o sea que hubo consumo de verdad: se anota aunque
    # lo que dijo no sirva. Los tokens se gastaron igual, y facturar solo
    # los aciertos sería facturar menos de lo que cuesta.
    consumo.anotar(tokens_in, tokens_out)

    decision = _leer_respuesta(crudo, opciones)

    # Si contestó algo utilizable, la IA está sana: se borra el aviso que
    # hubiera de antes para que el panel no siga enseñando un problema ya
    # resuelto.
    if decision.intencion or decision.respuesta:
        olvidar_fallo()

    return decision


def comprobar() -> str:
    """
    Verifica que la configuración sirve de verdad. Para
    `scripts/gemini_setup.py`, no para el bot.

    A diferencia de `interpretar`, esta SÍ levanta la excepción: quien está
    configurando un cliente nuevo necesita ver el error, no un silencio.
    """
    cliente = _construir_cliente()
    try:
        respuesta = cliente.models.generate_content(
            model=config.GEMINI_MODELO,
            contents="Responde exactamente: OK",
        )
        return (respuesta.text or "").strip()
    except Exception as e:
        raise GeminiNoDisponible(f"La clave no sirvió contra el modelo: {e}") from e
