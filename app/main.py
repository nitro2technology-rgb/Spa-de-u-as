"""
SERVIDOR WEBHOOK
================
Recibe los mensajes entrantes de la API de WhatsApp (Meta) y los pasa
a bot_logic. También expone el endpoint GET que Meta usa para verificar
el webhook al configurarlo.

Correr localmente (desde la raíz del proyecto):
    uvicorn app.main:app --reload --port 8000

Luego exponer con un túnel público (ngrok, por ejemplo) para que Meta
pueda alcanzar tu webhook durante pruebas:
    ngrok http 8000
"""

import asyncio
import hashlib
import hmac
import json
import threading
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Query
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import config
from app.core import eventos
from app.core import media
from app.core import tenencia
from app.core.database import CLIENTE_POR_DEFECTO, ahora_utc, init_db
from app.bot import bot_logic
from app.bot.cerebro import gemini
from app.web import activos
from app.web import guia
from app.web import admin_api
from app.web import admin_ui
from app.web import panel_equipo
from app.web import panel_plan
from app.web import panel_bot
from app.web import panel_estadisticas
from app.web import paginas_publicas
from app.web import pwa
from app.web import superadmin
from app.integrations import sheets_service
from app.barberia import consola as barberia_consola
from app.barberia import rutas as barberia_rutas


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Se ejecuta al arrancar el servidor, antes de atender peticiones."""
    init_db()
    ESTADISTICAS["arrancado"] = ahora_utc().isoformat(timespec="seconds")

    # El caché de imágenes y audios se limpia aquí y no dentro de
    # `init_db` a propósito: son archivos en disco, no filas, y la base no
    # tiene por qué saber que existe una carpeta de archivos.
    media.limpiar_cache()

    # El repartidor de avisos en vivo necesita saber cuál es el event loop
    # del servidor: los mensajes que salen del panel se publican desde un
    # hilo distinto y hay que devolverlos a este loop para repartirlos.
    eventos.capturar_loop()

    if config.VERIFY_WEBHOOK_SIGNATURE:
        _avisar_credenciales_incompletas()

    # Y por lo mismo, el import de la librería de Gemini se paga aquí y no
    # dentro del tope de tiempo de la IA. Va en un hilo aparte porque
    # tarda segundos y no hay razón para retrasar el arranque: si llega un
    # mensaje mientras tanto, esperará ese import igual que antes, nunca
    # más. Ver `gemini.precalentar`.
    threading.Thread(target=gemini.precalentar, daemon=True,
                     name="precalentar-gemini").start()

    # Los cobros: recordatorios diarios y pausa por impago. Una revisión
    # por hora dentro de este mismo proceso; ver `app/core/cobros.py`.
    from app.core import cobros
    revision_de_cobros = asyncio.create_task(cobros.vigilar())

    # Los recordatorios de las citas de barbería, 2 horas antes. Cada 10
    # minutos, en este mismo proceso; ver `app/barberia/recordatorios.py`.
    from app.barberia import recordatorios
    revision_de_recordatorios = asyncio.create_task(recordatorios.vigilar())

    # Crear las pestañas del Sheet aquí y no en el primer lead: así el
    # primer cliente del día no paga la espera, y si algo está mal
    # configurado nos enteramos al desplegar, no cuando llega una venta.
    try:
        sheets_service.asegurar_pestanas()
    except Exception as e:
        print(f"[main] AVISO: no se pudieron preparar las pestañas del Sheet: {e}")
        print("[main] El bot funciona igual; los leads no quedarán en el Sheet.")

    yield

    revision_de_cobros.cancel()
    revision_de_recordatorios.cancel()


# Contadores de esta ejecución, para saber si Meta está entregando los
# webhooks. Se reinician en cada despliegue, y eso también informa: si
# están a cero justo después de un despliegue, es que aún no ha llegado
# nada desde entonces.
ESTADISTICAS = {
    "arrancado": None,
    "webhooks_recibidos": 0,
    "webhooks_con_mensaje": 0,
    "rechazados_por_firma": 0,
    "ultimo_webhook": None,
    "ultimo_mensaje_de": None,
}

app = FastAPI(title="WhatsApp Bot Template", lifespan=lifespan)

# El CSS y el JavaScript del panel. Van fuera de /admin a proposito: son
# archivos sin nada de nadie, y pedirlos no deberia depender de tener
# sesion. La direccion lleva el hash del contenido, asi que se pueden
# cachear para siempre (ver `app/web/activos.py`).
app.mount(activos.BASE_URL, StaticFiles(directory=activos.CARPETA),
          name="estaticos")

# El panel HTML va primero: sus rutas son más específicas (/admin/chat/...)
# y así no las captura ninguna ruta genérica de la API JSON.
app.include_router(admin_ui.router)
app.include_router(panel_equipo.router)
app.include_router(panel_plan.router)
app.include_router(panel_bot.router)
app.include_router(panel_estadisticas.router)
app.include_router(admin_api.router)
app.include_router(paginas_publicas.router)

# El panel de gestión de barberías (/entrar, /b, /yo). Usa la misma sesión
# que el panel del bot, así que el middleware de abajo le resuelve el
# inquilino igual. La puerta de cada ruta está en `app/barberia/rutas.py`.
app.include_router(barberia_rutas.router)

# La guia que se le manda a un cliente nuevo para conectar su WhatsApp.
# Es de la PLATAFORMA, no de un negocio: ver el docstring de guia.py.
app.include_router(guia.router)

# La consola de la plataforma. No es el panel de ningún cliente: mira a
# todos, y por eso corre sin inquilino fijado (ver el middleware de abajo).
app.include_router(superadmin.router)
# Las barberías en la consola: /superadmin/barberias (misma sesión).
app.include_router(barberia_consola.router)

# Manifiesto, service worker e iconos: lo que hace que el panel se pueda
# instalar en el celular. Van en la raíz, no bajo /admin/, porque el
# alcance de un service worker es la carpeta desde la que se sirve.
app.include_router(pwa.router)


@app.middleware("http")
async def fijar_inquilino(request: Request, call_next):
    """
    Deja puesto de qué negocio es la petición, antes de atenderla.

    Va en un middleware y no en cada endpoint porque el panel tiene una
    veintena de rutas y bastaría olvidar una para que enseñara los datos
    de otro cliente. Aquí no se puede olvidar ninguna.

    HAY DOS FORMAS DE AVERIGUARLO, Y LA VARIABLE `DOMINIO_BASE` ELIGE.

    **Con `DOMINIO_BASE` puesta — por el subdominio.** panaderia.tudominio.com
    es el panel de "panaderia". Es lo más sólido: cada negocio tiene su
    propio origen, así que no comparten ni cookies, ni service worker, ni
    identidad de app instalable.

    **Sin `DOMINIO_BASE` — por la cookie de sesión.** Todos los clientes
    entran por la misma dirección, así que el `Host` ya no distingue a
    nadie y el inquilino sale del pase firmado que el navegador trae
    (`acceso.leer_pase`). Es lo que permite atender a varios negocios sin
    comprar un dominio ni configurar DNS por cliente.

    Quien no traiga pase válido —el que aún no ha entrado— se atiende con
    el cliente por defecto, que es de quien es la pantalla de entrada.

        La protección aquí es la FIRMA del pase, no la dirección.

    Con subdominios había dos comprobaciones y tenían que coincidir: la
    dirección decía un negocio y el pase decía el mismo. Sin subdominios
    queda una sola. Sigue siendo sólida —el pase va firmado con un secreto
    del servidor y sin él no se puede fabricar uno que diga otro negocio—
    pero conviene saber que es una capa y no dos. Ver `app/core/acceso.py`.

    TRES RUTAS QUEDAN FUERA, cada una por su motivo:

      /webhook     Lo manda Meta, no un navegador, y llega al dominio
                   pelado. Su inquilino sale de la URL
                   (/webhook/{webhook_token}), dentro del endpoint.

      /superadmin  La consola de la plataforma mira a TODOS los clientes.
                   Con un inquilino puesto, el filtro automático de
                   consultas le recortaría cada listado a un solo negocio
                   y enseñaría ceros para los demás, sin dar ningún error.
                   Cuando toca un cliente concreto lo hace con
                   `tenencia.usar(id)`, a mano y a la vista.

      /            Es el health check del hosting, que lo llama con un host
                   interno que no es de ningún cliente. Si respondiera 404,
                   Render daría el servicio por caído y lo reiniciaría en
                   bucle. Responde siempre, con la configuración base.

      /estaticos   El CSS y el JavaScript. Son archivos sin nada de nadie
                   —el mismo motivo por el que ya viven fuera de /admin— y
                   pedirlos no debería depender de resolver un inquilino.

                   No es una mejora teórica: `/superadmin` está exento de
                   este middleware pero SU CSS se sirve por aquí, así que
                   sin esta línea, el día que se active `DOMINIO_BASE` la
                   consola se serviría sin estilos. Aparecería al activar
                   una variable, meses después, y sin relación aparente.
                   Ver §7.6 de docs/CONTINUAR_AQUI.md.
    """
    ruta = request.url.path

    if (ruta.startswith("/webhook") or ruta.startswith("/superadmin")
            or ruta.startswith(activos.BASE_URL)):
        return await call_next(request)

    if not tenencia.dominio_base():
        with tenencia.usar(_inquilino_del_pase(request)):
            return await call_next(request)

    try:
        negocio = tenencia.resolver_por_host(request.headers.get("host", ""))
    except tenencia.InquilinoDesconocido:
        if ruta == "/":
            return await call_next(request)
        # Un subdominio que no es de nadie, o un cliente pausado. Los dos
        # dan lo mismo a propósito: no hay por qué contarle a internet
        # qué negocios son clientes nuestros ni cuáles dejaron de pagar.
        return JSONResponse(content={"detail": "No encontrado"}, status_code=404)
    except Exception as e:
        # La base caída no puede tumbar el health check, que es lo que el
        # hosting usa para decidir si reinicia el servicio.
        if ruta == "/":
            return await call_next(request)
        print(f"[main] No se pudo resolver el inquilino: {e}")
        return JSONResponse(content={"detail": "No disponible"}, status_code=503)

    with tenencia.usar(negocio.id):
        return await call_next(request)


def _inquilino_del_pase(request: Request) -> int:
    """
    De quién es la sesión que trae este navegador, cuando todos los
    negocios comparten la misma dirección.

    Sin pase válido devuelve el cliente por defecto, que es de quien es la
    pantalla de entrada y de quien tiene que ser la marca que se ve antes
    de que nadie diga quién es. No es un valor por defecto peligroso: sin
    pase no se llega a ninguna pantalla con datos dentro, porque cada una
    vuelve a comprobar la sesión.

    Un pase de un cliente PAUSADO tampoco pasa de aquí: se le trata como si
    no lo trajera, y su panel deja de abrir en cuanto se le pausa desde el
    super-admin. Con subdominios de eso se encargaba `resolver_por_host`.
    """
    from app.core import acceso
    from app.web.admin_ui import COOKIE

    pase = acceso.leer_pase_sin_inquilino(request.cookies.get(COOKIE, ""))
    if pase is None:
        return CLIENTE_POR_DEFECTO

    negocio = tenencia.por_id(pase.client_id)
    if negocio is None or not negocio.active:
        return CLIENTE_POR_DEFECTO

    return pase.client_id


@app.get("/")
def health():
    """
    Comprobación de salud. Los servicios de hosting la usan para saber si
    el proceso está vivo, y sirve para conectar un monitor de uptime.
    No expone nada sensible a propósito.
    """
    return {"status": "ok", "servicio": config.BUSINESS_NAME}


def _anotar_entregas_fallidas(estados: list, negocio_url, value: dict):
    """
    Deja constancia de los mensajes que Meta aceptó y luego NO entregó.

    Es la otra mitad de `notificaciones.anotar_no_entregado`: aquí llega la
    respuesta que la llamada de envío no daba.

    Hay que resolver el inquilino igual que para un mensaje entrante — por
    la URL si vino por la puerta nueva, y por `phone_number_id` si vino por
    la vieja—, porque el ajuste donde se anota es de un cliente concreto.
    """
    fallidos = [e for e in estados if (e or {}).get("status") == "failed"]
    if not fallidos:
        return

    if negocio_url is not None:
        negocio = negocio_url
    else:
        pnid = (value.get("metadata") or {}).get("phone_number_id")
        negocio = tenencia.por_phone_number_id(pnid)

    if negocio is None:
        return

    from app.bot import notificaciones

    with tenencia.usar(negocio.id):
        for estado in fallidos:
            errores = estado.get("errors") or [{}]
            error = errores[0] or {}
            detalle = (error.get("error_data") or {}).get("details")
            motivo = detalle or error.get("title") or error.get("message") or "sin detalle"

            try:
                notificaciones.anotar_no_entregado(
                    estado.get("recipient_id") or "?",
                    str(motivo)[:300],
                    cuando=ahora_utc().isoformat(timespec="minutes"),
                )
            except Exception as e:
                print(f"[main] No se pudo anotar la entrega fallida: {e}")


def _avisar_credenciales_incompletas():
    """
    Qué clientes activos no pueden recibir mensajes todavía, dicho al
    arrancar y por su nombre.

    Antes esto era una línea: "falta APP_SECRET". Valía cuando había una
    sola App de Meta y el aviso era sobre el despliegue entero. Ahora cada
    negocio trae la suya, así que la pregunta ya no es "¿está puesto el
    secreto?" sino **"¿a cuál de mis clientes le falta algo?"**.

    Importa que salga al desplegar y no cuando alguien se queje: a un
    cliente sin App Secret el webhook le rechaza TODO por firma inválida, y
    visto desde fuera eso es idéntico a un bot caído.

    No revienta el arranque. Un cliente a medio dar de alta es un estado
    normal del sistema —se le crea antes de tener sus credenciales— y no
    hay razón para que eso deje sin servicio a los que sí están listos.
    """
    from app.core.database import Client, SessionLocal

    session = SessionLocal()
    try:
        activos = session.query(Client).filter_by(active=True).all()
        for c in activos:
            faltan = [nombre for nombre, valor in (
                ("App Secret", c.app_secret),
                ("URL de webhook", c.webhook_token),
                ("verify token", c.verify_token),
                ("phone_number_id", c.phone_number_id),
                ("token de WhatsApp", c.whatsapp_token),
            ) if not valor]

            if not faltan:
                continue

            # El cliente 1 puede estar entero en el entorno: es el bot de
            # casa, que todavía entra por la puerta vieja. Eso no es un
            # aviso, es la rampa funcionando.
            if c.id == CLIENTE_POR_DEFECTO and not c.webhook_token:
                continue

            print(f"[main] AVISO: a {c.slug!r} le falta {', '.join(faltan)}. "
                  f"Hasta que lo tenga, sus mensajes se rechazan. "
                  f"Se completa en /superadmin.")
    except Exception as e:
        # La base puede no estar lista del todo en el primer arranque. Un
        # aviso que impide arrancar es peor que un aviso que no sale.
        print(f"[main] No se pudieron revisar las credenciales: {e}")
    finally:
        session.close()


def _firma_valida(request: Request, raw_body: bytes, app_secret: str) -> bool:
    """
    Valida la cabecera X-Hub-Signature-256 que Meta firma con el App Secret.
    Sin esto, cualquiera que conozca la URL pública puede hacer POST y
    hacerle creer al bot que llegó un mensaje.

    EL SECRETO LLEGA POR PARÁMETRO, y no se lee aquí dentro. Es de cada
    cliente —cada negocio trae su propia App de Meta— y quien llama es el
    único que sabe de qué cliente es este POST, porque lo dice su URL.
    Leerlo aquí obligaría a esta función a averiguar el inquilino, que es
    justo la decisión que no le toca.
    """
    if not config.VERIFY_WEBHOOK_SIGNATURE:
        return True

    if not app_secret:
        print("[main] Sin App Secret no se puede validar la firma: se rechaza. "
              "Pega el App Secret de la App de Meta de este cliente en "
              "/superadmin, o define APP_SECRET si es el bot de casa.")
        return False

    recibida = request.headers.get("X-Hub-Signature-256", "")
    if not recibida.startswith("sha256="):
        print("[main] Petición sin cabecera de firma, se rechaza.")
        return False

    esperada = hmac.new(
        app_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()

    # compare_digest evita filtrar información por tiempo de comparación
    if not hmac.compare_digest(esperada, recibida[len("sha256="):]):
        print("[main] Firma inválida, se rechaza la petición.")
        return False

    return True


# Los tipos que traen un archivo descargable. `location` y `contacts`
# también son "no texto", pero no tienen media_id: se registran igual
# para que quede el rastro, sin nada que bajar.
_TIPOS_CON_ARCHIVO = ("image", "audio", "video", "document", "sticker")


def _leer_adjunto(message: dict, msg_type: str) -> dict | None:
    """
    Saca la ficha del archivo del payload de Meta. None si el mensaje no
    trae ninguno.

    **No se descarga nada aquí.** El webhook espera a que todo esto
    termine antes de responderle 200 a Meta, y bajar una imagen de 5 MB
    en mitad de esa espera es pedir que Meta lo dé por fallido y lo
    reintente. Se anota el id y el archivo se baja cuando alguien abra la
    conversación en el panel — que además evita bajar las fotos que nadie
    va a mirar.
    """
    if msg_type not in _TIPOS_CON_ARCHIVO:
        # Una reacción no es un archivo ni una pregunta: es un 👍 a algo
        # que ya se dijo. Viaja con su emoji para que quede en el
        # historial, y el bot NO le contesta (ver `bot_logic`): antes le
        # respondía "¡Gracias! Ya lo recibí" con dos botones.
        if msg_type == "reaction":
            return {"tipo": "reaction",
                    "emoji": (message.get("reaction") or {}).get("emoji") or ""}
        # Ubicación, contacto... no hay archivo, pero sí hay mensaje: se
        # deja constancia para que no desaparezca.
        if msg_type in ("location", "contacts"):
            return {"tipo": msg_type}
        return None

    cuerpo = message.get(msg_type) or {}
    return {
        "tipo": msg_type,
        "media_id": cuerpo.get("id"),
        "mime": (cuerpo.get("mime_type") or "").split(";")[0].strip(),
        "nombre": cuerpo.get("filename"),
        "bytes": cuerpo.get("file_size"),
        "caption": cuerpo.get("caption"),
    }


# ══════════════════════════════════════════════════════════════════════
#  EL WEBHOOK
# ══════════════════════════════════════════════════════════════════════
#
#  CADA CLIENTE TIENE SU PROPIA URL:  /webhook/{webhook_token}
#
# No es celo de aislamiento: lo obliga el modelo. Cada negocio trae su
# propia App de Meta, así que la firma llega hecha con SU App Secret. Para
# saber con cuál validarla hay que saber primero de quién es el POST — y
# con una URL compartida lo único que lo diría está DENTRO del cuerpo
# (`phone_number_id`), que es justo lo que todavía no se puede dar por
# auténtico. Elegir con qué secreto comprobar la firma usando un dato del
# propio mensaje sin firmar es hacer la comprobación al revés.
#
# Con el inquilino en la URL el orden queda bien:
#
#     URL → cliente → su App Secret → firma → parsear → atender
#
# Y de paso resuelve el handshake de verificación (el GET), que no trae
# `phone_number_id` por ningún lado: con una sola URL no habría manera de
# saber qué cliente está configurando su webhook.
#
# El token es aleatorio e inadivinable, así que además es una capa previa
# gratis: quien no lo tenga no llega ni a la comprobación de firma. Pero
# es una capa, no LA protección — la protección sigue siendo la firma.


@app.get("/webhook/{webhook_token}")
def verify_webhook_cliente(
    webhook_token: str,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    El handshake que hace Meta cuando el CLIENTE configura su webhook.

    Meta lo llama una sola vez, desde el panel de la App del negocio, y
    compara el token que él escribió allí con el que tenemos guardado.
    """
    negocio = tenencia.por_webhook_token(webhook_token)
    if negocio is None:
        # Una URL que no es de nadie. 404 y no 403: a quien esté probando
        # URLs no hay por qué confirmarle que acertó el formato.
        return PlainTextResponse(content="No encontrado", status_code=404)

    with tenencia.usar(negocio.id):
        esperado = config.VERIFY_TOKEN

    if (hub_mode == "subscribe" and esperado
            and hmac.compare_digest((hub_verify_token or "").encode("utf-8"),
                                    esperado.encode("utf-8"))):
        print(f"[main] Webhook verificado para {negocio.slug!r}.")
        return PlainTextResponse(content=hub_challenge)

    print(f"[main] Verificación fallida para {negocio.slug!r}: el token que "
          f"mandó Meta no coincide con el que tiene guardado este cliente.")
    return PlainTextResponse(content="Token de verificación inválido",
                             status_code=403)


@app.post("/webhook/{webhook_token}")
async def receive_webhook_cliente(webhook_token: str, request: Request):
    """Cada mensaje que entra por el número de ESTE cliente."""
    negocio = tenencia.por_webhook_token(webhook_token)
    if negocio is None:
        _contar_webhook()
        return JSONResponse(content={"detail": "No encontrado"}, status_code=404)

    return await _atender(request, negocio)


# ── La ruta vieja, mientras se migra ─────────────────────────────────
#
# De cuando había UNA App de Meta —la nuestra— con los números de todos
# los clientes dentro. Resuelve el inquilino por `phone_number_id` y valida
# la firma con el `APP_SECRET` del entorno.
#
# Se mantiene para no dejar mudo al bot de casa mientras se le pasa a su
# URL propia. **Se retira en cuanto el último cliente esté migrado**: hasta
# entonces es la única puerta que valida con un secreto compartido.


@app.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """El handshake de la App vieja. Sin inquilino: lee del entorno."""
    esperado = config.VERIFY_TOKEN
    if (hub_mode == "subscribe" and esperado
            and hmac.compare_digest((hub_verify_token or "").encode("utf-8"),
                                    esperado.encode("utf-8"))):
        return PlainTextResponse(content=hub_challenge)
    return PlainTextResponse(content="Token de verificación inválido", status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    """Meta llama a este endpoint cada vez que llega un mensaje nuevo."""
    return await _atender(request, None)


def _contar_webhook():
    ESTADISTICAS["webhooks_recibidos"] += 1
    ESTADISTICAS["ultimo_webhook"] = ahora_utc().isoformat(timespec="seconds")


async def _atender(request: Request, negocio_url):
    """
    El cuerpo compartido por las dos puertas.

    `negocio_url` es el cliente que dijo la URL, o None si el POST entró
    por `/webhook` a secas. Esa diferencia decide **con qué secreto se
    valida la firma**, que es lo único que separa a los dos caminos: de
    ahí para abajo atienden idéntico, y por eso un arreglo aquí vale para
    los dos.
    """
    # Leemos el cuerpo crudo: la firma se calcula sobre los bytes exactos,
    # no sobre el JSON re-serializado.
    raw_body = await request.body()
    _contar_webhook()

    # El secreto con el que Meta firmó esto. Por la puerta nueva es el de
    # la App del cliente; por la vieja, sin inquilino fijado,
    # `config.APP_SECRET` cae en la configuración base, que lee del
    # ENTORNO — el secreto de la App de casa, como siempre.
    if negocio_url is not None:
        with tenencia.usar(negocio_url.id):
            secreto = config.APP_SECRET
    else:
        secreto = config.APP_SECRET

    if not _firma_valida(request, raw_body, secreto):
        ESTADISTICAS["rechazados_por_firma"] += 1
        return JSONResponse(content={"status": "firma invalida"}, status_code=403)

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        print("[main] Cuerpo no es JSON válido, se ignora.")
        return JSONResponse(content={"status": "ignored"})

    # UNA ENTREGA PUEDE TRAER VARIAS NOVEDADES, y hay que atenderlas todas.
    #
    # Meta junta en un solo POST lo que llega casi a la vez: varias
    # `entry`, varios `changes` y, dentro, varios `messages`. Antes se
    # atendía solo `entry[0].changes[0].messages[0]` y el resto se tiraba
    # sin rastro — dos clientes que escribían en el mismo segundo, y al
    # segundo no le contestaba nadie.
    #
    # Cada novedad va aparte, con su propio try: una mal formada no puede
    # llevarse por delante a las demás del mismo lote.
    entradas = body.get("entry") if isinstance(body, dict) else None
    for entry in entradas or []:
        for change in (entry or {}).get("changes") or []:
            try:
                await _atender_cambio((change or {}).get("value") or {},
                                      negocio_url)
            except (KeyError, IndexError, TypeError, AttributeError) as e:
                print(f"[main] Payload inesperado, se ignora: "
                      f"{type(e).__name__}: {e}")

    # Meta espera un 200 rápido; si no, reintenta el envío del webhook.
    return JSONResponse(content={"status": "ok"})


async def _atender_cambio(value: dict, negocio_url):
    """Una novedad de la entrega: avisos de entrega, mensajes, o nada."""

    # ── Los avisos de entrega ────────────────────────────────────────
    #
    # Meta manda aquí lo que pasó con CADA mensaje que enviamos: sent,
    # delivered, read... y **failed**.
    #
    # Esto se ignoraba entero, y era un agujero: la API responde 200
    # cuando ACEPTA un mensaje, no cuando lo entrega. Si luego no puede
    # entregarlo —el destinatario no le escribió al bot en 24 h, el número
    # no tiene WhatsApp— no vuelve como error de la llamada, vuelve por
    # aquí. Tirándolo, la única señal de que un lead no le llegó a nadie se
    # perdía, y desde fuera se veía igual que un día sin clientes.
    #
    # Solo se anotan los FALLIDOS. Los `delivered` y `read` llegan varios
    # por mensaje y no dicen nada que haya que guardar.
    if value.get("statuses"):
        _anotar_entregas_fallidas(value.get("statuses") or [],
                                  negocio_url, value)

    if not value.get("messages"):
        return

    # ── De qué negocio es este mensaje ───────────────────────────────
    # Meta manda el número por el que entró. Ese `phone_number_id` es lo
    # único del payload que dice a QUIÉN le escribieron, porque `from` es
    # el cliente final, no el negocio.
    phone_number_id = (value.get("metadata") or {}).get("phone_number_id")

    if negocio_url is not None:
        # Puerta nueva: de quién es ya lo dijo la URL, y la firma de ese
        # cliente ya cuadró. Aquí el `phone_number_id` no DECIDE nada —
        # CONFIRMA.
        #
        # Y hace falta que confirme: el error más probable del alta es un
        # cliente que pega la URL de webhook de otro. Con la firma sola no
        # se cazaría (cada uno firma bien lo suyo) y los mensajes de un
        # negocio entrarían en la bandeja del vecino.
        negocio = negocio_url

        if not negocio.phone_number_id:
            print(f"[main] {negocio.slug!r} no tiene phone_number_id "
                  f"guardado: no se le puede ni responder. Complétalo en "
                  f"/superadmin.")
            return

        if phone_number_id != negocio.phone_number_id:
            print(f"[main] La URL dice {negocio.slug!r} pero el mensaje "
                  f"entró por el número {phone_number_id!r}, que no es el "
                  f"suyo. Casi seguro: alguien pegó la URL de otro cliente "
                  f"en su App de Meta. Se ignora.")
            return
    else:
        # Puerta vieja: aquí sí decide, que es como funcionaba cuando había
        # una sola App para todos.
        negocio = tenencia.por_phone_number_id(phone_number_id)

        if negocio is None:
            # Un número que no es de ningún cliente. Se responde 200 igual:
            # con un error, Meta reintenta durante horas.
            print(f"[main] Mensaje para un phone_number_id desconocido "
                  f"({phone_number_id!r}), se ignora.")
            return

    if not negocio.active:
        # Cliente pausado (por impago, normalmente). El bot calla, pero no
        # se pierde nada: Meta ya le entregó el mensaje al negocio y sigue
        # en su WhatsApp. Al reactivarlo, todo vuelve solo.
        print(f"[main] Cliente {negocio.slug!r} pausado, no se responde.")
        return

    # El nombre que cada persona tiene puesto en su WhatsApp. Meta lo manda
    # al lado de los mensajes, no dentro de ellos. Sirve para no tener que
    # preguntárselo (ver `config.PEDIR_NOMBRE`); puede no venir, así que
    # nunca se da por hecho.
    perfiles = {}
    for contacto in (value.get("contacts") or []):
        nombre = ((contacto.get("profile") or {}).get("name") or "").strip()
        if contacto.get("wa_id") and nombre:
            perfiles[contacto["wa_id"]] = nombre
    # Con un solo contacto y un `wa_id` que no cuadra con el `from` (Meta
    # normaliza algunos números de país), ese nombre es de quien escribe.
    solo = next(iter(perfiles.values())) if len(perfiles) == 1 else ""

    for message in value.get("messages") or []:
        try:
            await _atender_mensaje(message, negocio,
                                   perfiles.get(message.get("from"), solo))
        except (KeyError, IndexError, TypeError) as e:
            print(f"[main] Mensaje con forma inesperada, se ignora: "
                  f"{type(e).__name__}: {e}")


async def _atender_mensaje(message: dict, negocio, perfil: str):
    """Un mensaje de un cliente, ya sabido de qué negocio es."""
    phone = message["from"]

    ESTADISTICAS["webhooks_con_mensaje"] += 1
    ESTADISTICAS["ultimo_mensaje_de"] = phone
    msg_type = message["type"]
    # ID único del mensaje: sirve para no procesar dos veces el mismo
    # webhook cuando Meta lo reintenta.
    message_id = message.get("id")

    text = None
    button_id = None
    list_id = None
    # `adjunto` y no `media`: ese nombre es el del módulo importado arriba,
    # y una variable local con el mismo nombre lo taparía dentro de toda la
    # función.
    adjunto = None

    if msg_type == "text":
        text = message["text"]["body"]
    elif msg_type == "interactive":
        interactive = message["interactive"]
        if interactive["type"] == "button_reply":
            button_id = interactive["button_reply"]["id"]
        elif interactive["type"] == "list_reply":
            # Respuesta a una lista desplegable (elección de día de cita)
            list_id = interactive["list_reply"]["id"]
    elif msg_type == "button":
        # El botón de respuesta rápida de una PLANTILLA. No trae el id de
        # ninguna opción del menú, sino el texto que pulsó: se trata como
        # si lo hubiera escrito, que es lo que el bot sabe interpretar.
        # Antes caía en "algo que no sabemos tratar" y llegaba vacío.
        text = (message.get("button") or {}).get("text") or None
    else:
        # Un archivo, o algo que no sabemos tratar. Antes esto se tiraba a
        # la basura y el mensaje entraba al flujo como si estuviera vacío:
        # la foto no quedaba en el historial, el dueño no recibía aviso, y
        # si el bot estaba pidiendo el nombre, el lead se quedaba llamándose
        # "Cliente".
        adjunto = _leer_adjunto(message, msg_type)
        # Una imagen puede traer pie de foto, y eso sí es texto del cliente:
        # se trata como tal para que la IA y la detección de origen lo vean.
        text = (adjunto or {}).get("caption")

    # ⚠️  El bot corre en su PROPIO try, y no dentro del de quien llama.
    #
    # Aquel caza `KeyError` e `IndexError` porque un payload de Meta al que
    # le falta una clave no es un fallo nuestro. El problema es que el bot
    # levanta esas MISMAS dos excepciones cuando algo va mal dentro: un
    # `.format` sobre un texto del dueño con una llave rara daba
    # `KeyError: 'name'`, subía hasta allí, y se anotaba como "Payload
    # inesperado". O sea que el cliente no recibía nada y el log culpaba a
    # Meta de un fallo nuestro. Costó encontrar por qué "el bot se
    # congelaba" en una opción.
    #
    # Separados, cada uno dice lo que es. Y el de aquí caza `Exception`
    # entera a propósito: un fallo procesando UN mensaje no puede tumbar el
    # webhook, porque Meta reintentaría y —peor— acabaría cortando las
    # entregas del cliente.
    #
    # En un hilo aparte, no aquí mismo: `handle_incoming_message` es una
    # función normal que habla con Meta y con Google por HTTP, y llamarla
    # directo desde un endpoint async bloquea el servidor entero mientras
    # espera. El `with` envuelve al `await`, no al revés: el inquilino
    # tiene que estar puesto MIENTRAS corre el bot, y `run_in_threadpool`
    # se lleva el contexto al hilo por su cuenta (anyio lo copia).
    try:
        with tenencia.usar(negocio.id):
            await run_in_threadpool(
                bot_logic.handle_incoming_message,
                phone=phone,
                perfil=perfil,
                message_type=msg_type,
                text=text,
                button_id=button_id,
                message_id=message_id,
                list_id=list_id,
                media=adjunto,
            )
    except Exception as e:
        # Con la traza entera: es un fallo del código, y sin ella hay que
        # adivinar en qué punto del recorrido se quedó.
        print(f"[main] EL BOT FALLÓ atendiendo a {phone} "
              f"({negocio.slug!r}): {type(e).__name__}: {e}. "
              f"Ese cliente se quedó SIN respuesta.")
        traceback.print_exc()
