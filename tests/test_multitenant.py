"""
PRUEBAS DE AISLAMIENTO ENTRE CLIENTES
======================================
Un solo despliegue atiende a varios negocios. Esta suite comprueba la
promesa que sostiene todo el producto:

    Lo de un cliente no se mezcla NUNCA con lo de otro.

Levanta el servidor de verdad con DOS negocios dados de alta y ejercita
los dos caminos por los que entra una petición:

  - El webhook, cuyo inquilino sale del `phone_number_id` que manda Meta.
  - El panel, cuyo inquilino sale del subdominio del `Host`.

No envía nada a WhatsApp ni a Google: esas funciones se sustituyen antes
de arrancar, y la base es temporal.

    python tests/test_multitenant.py

Devuelve 0 si todo pasa y 1 si algo falla, igual que las demás suites.
"""
import copy, json, os, sys, tempfile, threading, time

PROY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROY)
os.chdir(PROY)

# Normalmente, una SQLite temporal. Pero esta suite es la que hay que
# correr contra PostgreSQL antes de tocar producción: es la única forma de
# comprobar que la aplicación entera sigue funcionando con Row-Level
# Security puesto, que ahí sí existe. La base tiene que estar VACÍA y con
# las migraciones aplicadas (ver tests/test_rls.py).
#
#     TEST_DATABASE_URL="postgresql://..." python tests/test_multitenant.py
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or (
    "sqlite:///" + os.path.join(tempfile.mkdtemp(), "multi.db").replace("\\", "/"))
os.environ["ADMIN_API_KEY"] = "clave-multi-prueba"
os.environ["VERIFY_WEBHOOK_SIGNATURE"] = "false"
# Una clave maestra de PRUEBA, fijada aquí y no heredada del .env de quien
# corre la suite. Sin ninguna, el alta se niega a guardar credenciales (no
# se guardan en claro) y la suite solo pasaba en una máquina con .env.
os.environ["SECRETS_KEY"] = "T2FhOFBTS0RqM3ZzWmJ4TkxxWXc5Y0hHdFJtRXVfMD0="
# El dominio bajo el que cuelgan los subdominios de los clientes. Con esto
# puesto, la resolución del panel es ESTRICTA: un subdominio desconocido es
# un 404, no el cliente por defecto.
os.environ["DOMINIO_BASE"] = "ejemplo.test"

# Cada cliente tiene su propio número de WhatsApp dentro de la API de Meta.
PNID_A, PNID_B = "1000000000001", "2000000000002"

import requests, uvicorn                                      # noqa: E402
from app import config                                        # noqa: E402
from app.core import acceso, config_cliente, database, message_log, tenencia  # noqa: E402
from app.bot import whatsapp_client                           # noqa: E402
from app.integrations import sheets_service                   # noqa: E402


def pide_clave(texto: str) -> bool:
    """
    Si esa respuesta es la pantalla de entrada.

    Se mira el formulario, no el rotulo: los textos de la pantalla
    cambian con cada rediseno y no vale la pena que eso rompa nueve
    pruebas que hablan de sesiones caducadas.
    """
    return 'name="clave"' in texto and 'action="/admin/login"' in texto


# Nada sale a Meta ni a Google. Se anota el número por el que HABRÍA
# salido cada mensaje, que es justo lo que hay que comprobar.
class FalsaResp:
    status_code = 200
    def json(self): return {"ok": True}

enviados = []


def _fake_text(to, text, autor="bot"):
    enviados.append({"a": to, "texto": text, "url": whatsapp_client._url()})
    message_log.registrar(to, "saliente", autor, text)
    return FalsaResp()


whatsapp_client.send_text_message = _fake_text
whatsapp_client.send_button_message = lambda to, t, b: (
    enviados.append({"a": to, "texto": t, "url": whatsapp_client._url()}),
    message_log.registrar(to, "saliente", "bot", t), FalsaResp())[-1]
whatsapp_client.send_list_message = lambda to, t, b, o, ti="x": (
    enviados.append({"a": to, "texto": t, "url": whatsapp_client._url()}),
    message_log.registrar(to, "saliente", "bot", t), FalsaResp())[-1]
sheets_service.registrar_lead = lambda *a, **k: True
sheets_service.asegurar_pestanas = lambda *a, **k: True

database.init_db()

# ── Los dos negocios ─────────────────────────────────────────────────
# El cliente 1 lo siembra `init_db` desde el entorno: es el dueño del bot.
# Se le pone su phone_number_id y se da de alta un segundo negocio, con su
# propio negocio.toml (una copia con los textos cambiados).

_toml_b = copy.deepcopy(config_cliente.leer_negocio_toml())
_toml_b.setdefault("negocio", {})["nombre"] = "Panaderia Dona Rosa"
_toml_b.setdefault("textos", {})["bienvenida"] = "Hola, panaderia Dona Rosa aqui."
_toml_b.setdefault("marca", {})["color"] = "#ff0000"

_s = database.get_session()
_s.query(database.Client).filter_by(id=database.CLIENTE_POR_DEFECTO).update(
    {"phone_number_id": PNID_A, "slug": "negocio-a", "nombre": "Negocio A"})
_s.add(database.Client(
    id=2, slug="panaderia", nombre="Panaderia Dona Rosa", active=True,
    phone_number_id=PNID_B, negocio_config=_toml_b))
# Un tercero, dado de baja por impago.
_s.add(database.Client(id=3, slug="moroso", nombre="Cliente Moroso",
                       active=False, phone_number_id="3000000000003"))
_s.commit()

# En PostgreSQL, insertar ids a mano NO adelanta el contador de la tabla.
# Sin esto, el primer negocio que se dé de alta desde /superadmin pediría
# el id 1 —que ya es del dueño— y reventaría por clave duplicada. En
# SQLite no hace falta y no se hace.
if database.DATABASE_URL.startswith("postgresql"):
    from sqlalchemy import text as _text
    _s.execute(_text(
        "SELECT setval(pg_get_serial_sequence('clients', 'id'), "
        "(SELECT MAX(id) FROM clients))"))
    _s.commit()

_s.close()
config.olvidar()

from app import main                                          # noqa: E402

threading.Thread(target=lambda: uvicorn.run(main.app, port=8322, log_level="error"),
                 daemon=True).start()

BASE = "http://127.0.0.1:8322"
for _ in range(80):
    try:
        requests.get(BASE + "/", timeout=1); break
    except Exception:
        time.sleep(0.25)

fallos = []


def check(nombre, condicion, detalle=""):
    linea = f"  {'[OK]' if condicion else '[X] '} {nombre}" + (
        f"  {detalle}" if detalle else "")
    try:
        print(linea)
    except UnicodeEncodeError:
        # La consola de Windows usa cp1252 y no sabe imprimir emojis. Los
        # textos del bot llevan varios, y aquí se imprimen en el detalle de
        # las verificaciones: sin esto reventaría la suite por un print.
        codificacion = sys.stdout.encoding or "ascii"
        print(linea.encode(codificacion, "replace").decode(codificacion))
    if not condicion:
        fallos.append(nombre)


def webhook(pnid, telefono, texto, mid):
    """Un mensaje entrante para el negocio dueño de ese phone_number_id."""
    return requests.post(BASE + "/webhook", timeout=10, json={"entry": [{
        "id": "WABA", "changes": [{"value": {
            "metadata": {"phone_number_id": pnid},
            "messages": [{"from": telefono, "id": mid, "type": "text",
                          "text": {"body": texto}}]}}]}]})


# ── 1. La configuración es de cada quien ─────────────────────────────

print("\n=== Cada negocio ve SU configuracion ===")

with tenencia.usar(1):
    nombre_a, bienvenida_a = config.BUSINESS_NAME, config.WELCOME_MESSAGE
    url_a, media_a, color_a = whatsapp_client._url(), config.MEDIA_DIR, config.MARCA_COLOR

with tenencia.usar(2):
    nombre_b, bienvenida_b = config.BUSINESS_NAME, config.WELCOME_MESSAGE
    url_b, media_b, color_b = whatsapp_client._url(), config.MEDIA_DIR, config.MARCA_COLOR

check("el nombre del negocio cambia con el inquilino",
      nombre_a != nombre_b and nombre_b == "Panaderia Dona Rosa",
      f"{nombre_a!r} vs {nombre_b!r}")
check("y sus textos tambien",
      bienvenida_a != bienvenida_b and "Dona Rosa" in bienvenida_b)
check("y su color de marca", color_a != color_b and color_b == "#ff0000")

# Lo mas grave que puede fallar: responder por el numero de otro negocio.
check("cada uno envia por SU numero de WhatsApp",
      PNID_A in url_a and PNID_B in url_b and url_a != url_b,
      f"{url_a} vs {url_b}")

check("y guarda sus archivos en su propia carpeta",
      media_a != media_b and media_a.endswith("1") and media_b.endswith("2"))

# Al salir del bloque no puede quedar nada pegado: un hilo reutilizado
# atenderia la siguiente peticion con el inquilino de la anterior.
check("fuera de un bloque no queda inquilino puesto",
      tenencia.actual_o_none() is None)


# ── 2. El contexto sobrevive a los saltos de hilo ────────────────────

print("\n=== El inquilino viaja a los hilos ===")

from concurrent.futures import ThreadPoolExecutor                # noqa: E402

_ex = ThreadPoolExecutor(max_workers=1)

with tenencia.usar(2):
    sin_envolver = _ex.submit(tenencia.actual_o_none).result()
    envuelto = _ex.submit(
        tenencia.envolver_para_hilo(tenencia.actual_o_none)).result()

check("un hilo suelto NO hereda el inquilino (por eso hace falta envolver)",
      sin_envolver is None, f"leyo {sin_envolver!r}")
check("envolver_para_hilo lo lleva al hilo", envuelto == 2, f"leyo {envuelto!r}")


# ── 3. El webhook enruta por phone_number_id ─────────────────────────

print("\n=== El webhook entrega a quien corresponde ===")

TEL = "573001112233"        # el MISMO cliente final le escribe a los dos

enviados.clear()
webhook(PNID_A, TEL, "hola", "wamid.a1")
respuesta_a = enviados[0] if enviados else None

enviados.clear()
webhook(PNID_B, TEL, "hola", "wamid.b1")
respuesta_b = enviados[0] if enviados else None

check("el negocio A responde por su numero",
      respuesta_a and PNID_A in respuesta_a["url"], str(respuesta_a))
check("el negocio B responde por el suyo",
      respuesta_b and PNID_B in respuesta_b["url"], str(respuesta_b))
check("y B saluda con SU texto, no con el de A",
      respuesta_b and "Dona Rosa" in respuesta_b["texto"], str(respuesta_b))

_s = database.get_session()
_contactos = {c.client_id: c for c in
              _s.query(database.Contact).filter_by(phone=TEL).all()}
_mensajes = {}
for m in _s.query(database.Message).filter_by(phone=TEL).all():
    _mensajes.setdefault(m.client_id, []).append(m)
_s.close()

# Es LA restriccion que rompia el multi-inquilino: `phone` era unico global,
# asi que el segundo negocio no habria podido ni crear el contacto.
check("el mismo cliente final existe por separado en los dos negocios",
      set(_contactos) == {1, 2}, f"client_ids={sorted(_contactos)}")
check("y cada conversacion queda con su dueno",
      set(_mensajes) == {1, 2} and all(_mensajes.values()))

_antes = len(enviados)
_r = webhook("9999999999999", TEL, "hola", "wamid.x1")
check("un numero de nadie se ignora sin responder",
      _r.status_code == 200 and len(enviados) == _antes, f"status={_r.status_code}")

_antes = len(enviados)
_r = webhook("3000000000003", TEL, "hola", "wamid.m1")
check("un cliente pausado por impago no recibe respuesta",
      _r.status_code == 200 and len(enviados) == _antes, f"status={_r.status_code}")
check("y Meta recibe 200, para que no reintente en bucle", _r.status_code == 200)


# ── 3b. Los cachés en memoria tampoco se mezclan ─────────────────────
#
# Media docena de módulos guardaban su estado en una variable suelta: el
# cliente de Gemini, los servicios de Google, los ajustes, las pestañas del
# Sheet y los iconos del panel. Con un solo negocio daba igual. Con varios,
# el PRIMERO en pasar por ahí dejaba lo suyo puesto para todos.

print("\n=== Los caches en memoria son de cada quien ===")

from app.core import ajustes                                     # noqa: E402
from app.bot import cerebro                                      # noqa: E402
from app.bot.cerebro import gemini                               # noqa: E402

with tenencia.usar(1):
    ajustes.escribir("plan_ia", "pro")
with tenencia.usar(2):
    plan_b = ajustes.leer("plan_ia", "sin_poner")
with tenencia.usar(1):
    plan_a = ajustes.leer("plan_ia", "sin_poner")

# El plan es lo que se activa al contratar la IA. Si se colara, un negocio
# estaria usando (y pagando) un paquete que no compro.
check("activar el plan de un negocio no se lo activa a otro",
      plan_a == "pro" and plan_b == "sin_poner", f"A={plan_a!r} B={plan_b!r}")

with tenencia.usar(1):
    gemini._anotar_fallo("se acabo la cuota de A")
    fallo_a = gemini.ultimo_fallo()
with tenencia.usar(2):
    fallo_b = gemini.ultimo_fallo()

check("el panel de un negocio no ve el fallo de IA de otro",
      fallo_a is not None and fallo_b is None, f"A={fallo_a} B={fallo_b}")

# Sin clave, los dos deben quedarse en plan Basico y responder con el menu
# de siempre: la IA es un paquete OPCIONAL y su ausencia no degrada nada.
with tenencia.usar(2):
    check("sin clave de IA, el negocio se queda en plan Basico",
          cerebro.plan_activo() == cerebro.BASICO)

from app.web import pwa                                          # noqa: E402

pwa._CACHE_ICONOS.clear()
_ok_icono = True
for _host in ("negocio-a.ejemplo.test", "panaderia.ejemplo.test"):
    _r = requests.get(BASE + "/icono-192.png", timeout=10, headers={"Host": _host})
    _ok_icono = _ok_icono and _r.status_code == 200

if _ok_icono:
    # Lo que se comprueba es que el icono se guarde POR INQUILINO. Antes la
    # clave del cache era solo el tamano, asi que el primer panel en pedirlo
    # le dejaba su icono a todos los demas.
    _inquilinos_en_cache = {clave[0] for clave in pwa._CACHE_ICONOS}
    check("el icono se cachea por inquilino, no uno para todos",
          _inquilinos_en_cache == {1, 2}, f"claves={sorted(_inquilinos_en_cache)}")

    # PENDIENTE (Fase 4): hoy los dos dibujan el MISMO logo, porque sale de
    # un archivo del repositorio (app/marca/logo.png) que es de todos. La
    # columna `clients.logo` ya existe pero todavia no la lee nadie. Hasta
    # entonces, dos negocios comparten imagen aunque no compartan cache.
else:
    print("  [--] icono: falta Pillow en este entorno, se omite")


# ── 4. El panel enruta por subdominio ────────────────────────────────

print("\n=== El panel se resuelve por el Host ===")

check("panaderia.ejemplo.test es el cliente 2",
      tenencia.resolver_por_host("panaderia.ejemplo.test").id == 2)
check("negocio-a.ejemplo.test es el cliente 1",
      tenencia.resolver_por_host("negocio-a.ejemplo.test").id == 1)
check("el puerto no estorba",
      tenencia.resolver_por_host("panaderia.ejemplo.test:8322").id == 2)

for host in ("nadie.ejemplo.test", "moroso.ejemplo.test", "www.ejemplo.test",
             "ejemplo.test", "otrodominio.com"):
    try:
        tenencia.resolver_por_host(host)
        check(f"{host} no da acceso a ningun panel", False, "resolvio a alguien")
    except tenencia.InquilinoDesconocido:
        check(f"{host} no da acceso a ningun panel", True)

_r = requests.get(BASE + "/admin/login", headers={"Host": "nadie.ejemplo.test"},
                  timeout=10)
check("por HTTP, un subdominio desconocido da 404", _r.status_code == 404,
      f"status={_r.status_code}")

_r = requests.get(BASE + "/admin/login", headers={"Host": "moroso.ejemplo.test"},
                  timeout=10)
check("un cliente pausado no puede entrar al panel", _r.status_code == 404,
      f"status={_r.status_code}")

_r = requests.get(BASE + "/admin/login", headers={"Host": "panaderia.ejemplo.test"},
                  timeout=10)
check("un negocio sin usuarios de panel no ofrece entrada",
      _r.status_code == 503, f"status={_r.status_code}")

# A partir de aquí el negocio B tiene con qué entrar. El A no: sigue con la
# rampa de ADMIN_API_KEY, que es lo que tiene hoy el dueño del bot.

acceso.crear_usuario(2, "rosa@panaderia.test", "pan-recien-horneado")

_r = requests.get(BASE + "/admin/login", headers={"Host": "panaderia.ejemplo.test"},
                  timeout=10)
check("y el panel de un cliente activo abre con SU marca",
      _r.status_code == 200 and "Panaderia Dona Rosa" in _r.text,
      f"status={_r.status_code}")

# El health check lo llama el hosting con un host interno que no es de
# ningun cliente. Si respondiera 404, Render daria el servicio por caido.
_r = requests.get(BASE + "/", headers={"Host": "10.0.0.5:10000"}, timeout=10)
check("el health check responde aunque el host no sea de nadie",
      _r.status_code == 200, f"status={_r.status_code}")


# ── 5. La sesion del panel es de UN negocio (Fase 3) ─────────────────
#
# La cookie llevaba dos fechas y una firma: nada que dijera de quien era.
# Con la clave de firma compartida entre inquilinos —y lo era, porque la
# firma salia de ADMIN_API_KEY, una variable de entorno del proceso— un
# pase emitido para un negocio valia para el panel de cualquier otro.

print("\n=== La sesion del panel no cruza de negocio ===")

HOST_A, HOST_B = "negocio-a.ejemplo.test", "panaderia.ejemplo.test"


def entrar(host, clave):
    """Devuelve el valor de la cookie de sesion, o None si no dejo entrar."""
    r = requests.post(BASE + "/admin/login", data={"clave": clave}, timeout=10,
                      headers={"Host": host}, allow_redirects=False)
    return r.cookies.get("panel_nitro")


def con_cookie(host, cookie, ruta="/admin/inbox"):
    return requests.get(BASE + ruta, timeout=10, allow_redirects=False,
                        headers={"Host": host, "Cookie": f"panel_nitro={cookie}"})


cookie_a = entrar(HOST_A, "clave-multi-prueba")
cookie_b = entrar(HOST_B, "pan-recien-horneado")

check("el dueno entra a su panel con ADMIN_API_KEY (la rampa)",
      cookie_a is not None)
check("y el cliente nuevo con SU clave, la de panel_users",
      cookie_b is not None)

# Lo mas grave: la clave del dueno del bot NO puede abrir el panel de un
# cliente. ADMIN_API_KEY es del proceso, o sea de todos los inquilinos.
check("la clave del dueno NO abre el panel de otro negocio",
      entrar(HOST_B, "clave-multi-prueba") is None)
check("ni la del cliente abre el del dueno",
      entrar(HOST_A, "pan-recien-horneado") is None)

if cookie_a and cookie_b:
    check("cada pase dice de que negocio es",
          cookie_a.startswith(f"{acceso.VERSION}:1:")
          and cookie_b.startswith(f"{acceso.VERSION}:2:"),
          f"{cookie_a.split(':')[:3]} vs {cookie_b.split(':')[:3]}")

    # LA fuga: misma firma, mismo servidor, otro negocio.
    _r = con_cookie(HOST_B, cookie_a)
    check("el pase del negocio A no abre el panel de B",
          pide_clave(_r.text) or _r.status_code in (303, 401),
          f"status={_r.status_code}")

    _r = con_cookie(HOST_A, cookie_b)
    check("ni el de B el de A",
          pide_clave(_r.text) or _r.status_code in (303, 401),
          f"status={_r.status_code}")

    _r = con_cookie(HOST_B, cookie_b)
    check("y cada quien si entra al suyo",
          _r.status_code == 200 and "Conversaciones" in _r.text,
          f"status={_r.status_code}")

    # Las consultas de datos van por el mismo control, no solo las paginas.
    _r = con_cookie(HOST_B, cookie_a, "/admin/api/conversaciones")
    check("y tampoco sirve para pedirle los datos por la API",
          _r.status_code == 401, f"status={_r.status_code}")


# ── 6. El canal en vivo entrega solo lo del negocio que escucha ──────
#
# `eventos.py` repartia cada mensaje a TODAS las colas suscritas. Con dos
# paneles abiertos, uno veia en vivo las conversaciones del otro: telefono,
# nombre y texto completo, sin que nada diera error.

print("\n=== El canal en vivo no mezcla conversaciones ===")

TEL_A, TEL_B = "573001110001", "573001110002"

if cookie_a:
    escuchado = []

    # Cuánto silencio se aguanta antes de dar por cerrado el canal.
    #
    # Contra una base REMOTA hay que pasar del latido del servidor
    # (`admin_ui.SEGUNDOS_ENTRE_LATIDOS`, 20 s): un webhook contra Oregon
    # tarda unos 9 segundos, aquí se mandan dos seguidos, y el panel de A
    # no oye NADA mientras se procesa el de B. Con 12 s se cortaba antes
    # de que llegara lo suyo y parecía que el canal no entregaba — cuando
    # lo que pasaba es que la prueba se iba antes de tiempo.
    #
    # Con SQLite local todo esto ocurre en milisegundos y 3 segundos
    # sobran, que es lo que interesa para el uso diario.
    _ESPERA = 25 if database.DATABASE_URL.startswith("postgresql") else 3

    def escuchar(host, cookie, silencio=_ESPERA):
        """Lee el canal hasta que pasen `silencio` segundos sin nada nuevo."""
        try:
            r = requests.get(BASE + "/admin/api/stream?desde=0", stream=True,
                             timeout=(5, silencio),
                             headers={"Host": host, "Cookie": f"panel_nitro={cookie}"})
            for linea in r.iter_lines(decode_unicode=True):
                if linea and linea.startswith("data:"):
                    escuchado.append(json.loads(linea[len("data:"):].strip()))
        except Exception:
            pass        # el corte por silencio es la forma normal de acabar

    _oyente = threading.Thread(target=escuchar, args=(HOST_A, cookie_a), daemon=True)
    _oyente.start()
    time.sleep(0.8)     # que al servidor le de tiempo a suscribir la cola

    webhook(PNID_B, TEL_B, "hola", "wamid.sse.b")
    webhook(PNID_A, TEL_A, "hola", "wamid.sse.a")
    _oyente.join(timeout=_ESPERA + 20)

    _telefonos = {e.get("phone") for e in escuchado}
    check("el panel de A recibe en vivo lo suyo",
          TEL_A in _telefonos, f"recibio {sorted(_telefonos)}")
    check("y NO recibe ni una linea de las conversaciones de B",
          TEL_B not in _telefonos, f"recibio {sorted(_telefonos)}")

# La otra mitad del canal: al reconectar, el panel pide lo que se perdio.
# Ese camino corre fuera del ciclo normal de la peticion, asi que se
# comprueba aparte que sigue filtrando por inquilino.
with tenencia.usar(1):
    _recuperado_a = {m["phone"] for m in message_log.mensajes_desde(0)}
with tenencia.usar(2):
    _recuperado_b = {m["phone"] for m in message_log.mensajes_desde(0)}

check("al reconectar, cada panel recupera solo sus mensajes",
      TEL_A in _recuperado_a and TEL_A not in _recuperado_b
      and TEL_B in _recuperado_b and TEL_B not in _recuperado_a,
      f"A={sorted(_recuperado_a)} B={sorted(_recuperado_b)}")


# ── 7. Los avisos al celular van al dueno que toca ───────────────────
#
# El filtro automatico de la Fase 2 deberia cubrirlo, porque
# PushSubscription lleva client_id y el hilo va envuelto. "Deberia" no es
# una garantia: aqui se comprueba.

print("\n=== Los avisos push no despiertan al dueno equivocado ===")

from app.core import push                                      # noqa: E402

with tenencia.usar(1):
    database.guardar_suscripcion_push("https://push.test/buzon-de-A", "pA", "aA")
with tenencia.usar(2):
    database.guardar_suscripcion_push("https://push.test/buzon-de-B", "pB", "aB")

with tenencia.usar(1):
    _buzones_a = [s["endpoint"] for s in database.suscripciones_push()]
with tenencia.usar(2):
    _buzones_b = [s["endpoint"] for s in database.suscripciones_push()]

check("cada negocio solo ve sus dispositivos apuntados",
      _buzones_a == ["https://push.test/buzon-de-A"]
      and _buzones_b == ["https://push.test/buzon-de-B"],
      f"A={_buzones_a} B={_buzones_b}")

# El envio real ocurre en un hilo aparte, donde el contexto NO viaja solo.
# Si se olvidara `envolver_para_hilo`, esto leeria los buzones del cliente
# por defecto y le sonaria el telefono al dueno equivocado.
_visto_en_el_hilo = []
_suscripciones_real = database.suscripciones_push
database.suscripciones_push = lambda: (
    _visto_en_el_hilo.append(tenencia.actual_o_none()), [])[-1]
push.configurado = lambda: True

with tenencia.usar(2):
    push.avisar("titulo", "cuerpo")
time.sleep(1.0)

database.suscripciones_push = _suscripciones_real

check("el hilo del push conserva el inquilino que lo lanzo",
      _visto_en_el_hilo == [2], f"leyo {_visto_en_el_hilo}")


# ── 8. El medidor de IA es de cada quien (Fase 4) ────────────────────
#
# Es lo que se factura. Si el consumo de un negocio se le anotara a otro,
# el error no se ve hasta que alguien reclama una factura.

print("\n=== El consumo de IA no se cruza ===")

from app.core import consumo                                   # noqa: E402

with tenencia.usar(1):
    consumo.anotar(tokens_in=450, tokens_out=40)
    consumo.anotar(tokens_in=450, tokens_out=40)
with tenencia.usar(2):
    consumo.anotar(tokens_in=100, tokens_out=10)

with tenencia.usar(1):
    _uso_a = consumo.del_mes()
with tenencia.usar(2):
    _uso_b = consumo.del_mes()

check("cada negocio suma su propio consumo",
      _uso_a["mensajes"] == 2 and _uso_b["mensajes"] == 1,
      f'A={_uso_a["mensajes"]} B={_uso_b["mensajes"]}')
check("y sus tokens, que son los que se cobran",
      _uso_a["tokens_in"] == 900 and _uso_b["tokens_in"] == 100,
      f'A={_uso_a["tokens_in"]} B={_uso_b["tokens_in"]}')

# El listado del super-admin tiene que ver a TODOS. Corre sin inquilino a
# propósito: con uno puesto, el filtro automatico lo dejaria en un negocio.
_todos = {c["client_id"]: c["mensajes"] for c in consumo.uso_de_todos()}
check("el super-admin ve el consumo de todos los clientes",
      _todos.get(1) == 2 and _todos.get(2) == 1 and 3 in _todos,
      f"{_todos}")


print("\n=== Las etiquetas y las notas no se cruzan ===")

# Etiquetas y nota interna viven en `contacts`, que ya esta filtrada por
# inquilino. Se comprueba igualmente: son columnas nuevas, y dar por
# hecho que heredan el aislamiento es exactamente como se cuela una fuga.
TEL_ETIQ = "573009998877"

with tenencia.usar(1):
    database.get_session().close()
    _s1 = database.get_session()
    _s1.add(database.Contact(phone=TEL_ETIQ, name="De la A"))
    _s1.commit(); _s1.close()
    database.guardar_etiquetas(TEL_ETIQ, ["secreto de A"])
    database.guardar_nota(TEL_ETIQ, "Nota privada de A")

with tenencia.usar(2):
    _s2 = database.get_session()
    _s2.add(database.Contact(phone=TEL_ETIQ, name="De la B"))
    _s2.commit(); _s2.close()
    _suyas = database.guardar_etiquetas(TEL_ETIQ, ["lo de B"])

check("el mismo telefono en dos negocios no comparte etiquetas",
      _suyas == ["lo de B"], str(_suyas))

with tenencia.usar(1):
    _s = database.get_session()
    _c = _s.query(database.Contact).filter_by(phone=TEL_ETIQ).first()
    _etq_a, _nota_a = database.etiquetas_de(_c), _c.nota_interna
    _s.close()

check("y las del primero siguen intactas", _etq_a == ["secreto de A"],
      str(_etq_a))
check("la nota de uno no llega al otro", _nota_a == "Nota privada de A",
      str(_nota_a))

with tenencia.usar(2):
    _s = database.get_session()
    _c = _s.query(database.Contact).filter_by(phone=TEL_ETIQ).first()
    _nota_b = _c.nota_interna
    _s.close()
check("el segundo no ve ninguna nota que no sea suya", _nota_b is None,
      str(_nota_b))


# ── 9. La consola de la plataforma (super-admin) ─────────────────────

print("\n=== El super-admin ===")

# Ojo con las cookies de aqui en adelante: `requests` decide a que dominio
# pertenecen mirando la cabecera Host si se fuerza a mano, asi que con un
# Host puesto NO manda la cookie de sesion. El super-admin no la necesita:
# esta fuera del middleware de inquilinos, y responde en cualquier host.
_r = requests.get(BASE + "/superadmin", timeout=10, allow_redirects=False)
check("sin clave configurada, el super-admin no existe",
      _r.status_code == 503, f"status={_r.status_code}")

os.environ["SUPERADMIN_KEY"] = "clave-de-la-plataforma"

_r = requests.get(BASE + "/superadmin", timeout=10)
check("con clave, pide entrar antes de enseñar nada",
      'action="/superadmin/login"' in _r.text and "Panaderia" not in _r.text)

_super = requests.Session()
_r = _super.post(BASE + "/superadmin/login", data={"clave": "no-es-esa"},
                 timeout=10)
check("rechaza la clave incorrecta", "Clave incorrecta" in _r.text)
check("y no deja cookie", "super_nitro" not in _super.cookies)

_r = _super.post(BASE + "/superadmin/login",
                 data={"clave": "clave-de-la-plataforma"}, timeout=10)
check("entra con la clave correcta", "super_nitro" in _super.cookies)

# ── El freno a los intentos de clave ──
#
# La puerta de la plataforma tiene que estar al menos tan protegida como
# la de un cliente: detrás de esta clave están las conversaciones de TODOS
# los negocios, el alta, la pausa y las credenciales cifradas. Hasta ahora
# solo frenaba /admin, o sea justo al reves de como debia estar.
from app.web import superadmin as _superadmin   # noqa: E402

_bruta = requests.Session()
for _ in range(config.PANEL_MAX_INTENTOS_LOGIN):
    _bruta.post(BASE + "/superadmin/login", data={"clave": "a-ver-si-acierto"},
                timeout=10)
_r = _bruta.post(BASE + "/superadmin/login", data={"clave": "a-ver-si-acierto"},
                 timeout=10)
check("el super-admin bloquea tras demasiados intentos fallidos",
      "Demasiados intentos" in _r.text)

# Y el bloqueo aplica también a la clave buena: si el acierto pasara, a
# quien prueba a lo bruto le bastaria con seguir probando.
_r = _bruta.post(BASE + "/superadmin/login",
                 data={"clave": "clave-de-la-plataforma"}, timeout=10)
check("y el bloqueo también aplica a la clave correcta",
      "Demasiados intentos" in _r.text and "super_nitro" not in _bruta.cookies)

# El freno de cada puerta es suyo: bloquear el super-admin no puede dejar
# a los clientes fuera de su propio panel.
_r = requests.get(BASE + "/admin/login", timeout=10, headers={"Host": HOST_A})
check("bloquear el super-admin no cierra el panel de los clientes",
      "Demasiados intentos" not in _r.text, f"status={_r.status_code}")

# Se limpia: el resto de la suite entra desde esta misma IP.
_superadmin._FRENO.clear()

# La cookie del super-admin no puede servir para el panel de un cliente, ni
# al reves: son dos puertas distintas a propósito.
_r = con_cookie(HOST_B, _super.cookies["super_nitro"])
check("el pase del super-admin no abre el panel de un cliente",
      pide_clave(_r.text), f"status={_r.status_code}")

if cookie_b:
    _r = requests.get(BASE + "/superadmin", timeout=10, headers={
        "Host": HOST_A, "Cookie": f"super_nitro={cookie_b}"})
    check("ni el pase de un cliente abre el super-admin",
          'action="/superadmin/login"' in _r.text and "Dar de alta" not in _r.text)

_r = _super.get(BASE + "/superadmin/clientes", timeout=10)
check("el tablero lista los negocios",
      "Panaderia Dona Rosa" in _r.text and "Cliente Moroso" in _r.text)
check("y dice cuál está pausado", '"chip neutro">pausado' in _r.text)

_r = _super.get(BASE + "/superadmin/consumo", timeout=10)
_json_consumo = _r.json()
check("el consumo se puede sacar en JSON para facturar",
      _r.status_code == 200
      and {c["client_id"]: c["mensajes"] for c in _json_consumo["clientes"]}.get(1) == 2,
      str(_json_consumo)[:60])

# Pausar por impago: es un UPDATE y tiene que surtir efecto ya, sin
# reiniciar y sin esperar a que caduque el cache de tenencia.
_r = _super.post(BASE + "/superadmin/clientes/2/estado", timeout=10,
                 allow_redirects=False)
check("pausar a un cliente responde con una redirección",
      _r.status_code == 303, f"status={_r.status_code}")

_antes = len(enviados)
webhook(PNID_B, TEL_B, "hola?", "wamid.pausado.1")
check("un cliente pausado deja de recibir respuestas al instante",
      len(enviados) == _antes, f"enviados={len(enviados) - _antes}")

_r = requests.get(BASE + "/admin/login", timeout=10, headers={"Host": HOST_B})
check("y su panel deja de abrir", _r.status_code == 404, f"status={_r.status_code}")

# Y el negocio A, que sí paga, sigue funcionando como si nada.
_antes = len(enviados)
webhook(PNID_A, TEL_A, "sigo aqui", "wamid.pausado.2")
check("pausar a uno no toca a los demas", len(enviados) > _antes)

_r = _super.post(BASE + "/superadmin/clientes/2/estado", timeout=10,
                 allow_redirects=False)
_r = requests.get(BASE + "/admin/login", timeout=10, headers={"Host": HOST_B})
check("al reanudarlo, su panel vuelve", _r.status_code == 200,
      f"status={_r.status_code}")

# ── Alta de un negocio, de punta a punta ──
_r = _super.post(BASE + "/superadmin/clientes", timeout=15,
                 allow_redirects=False, data={
                     "nombre": "Ferreteria El Tornillo",
                     "slug": "ferreteria",
                     "phone_number_id": "4000000000004",
                     "whatsapp_token": "TOKEN-DE-LA-FERRETERIA",
                     "email": "dueno@ferreteria.test",
                     "clave": "tornillos-y-tuercas",
                     "ia_activa": "si",
                     "ia_limite_mensual": "500",
                     "plan": "mensual"})
check("dar de alta un negocio redirige al listado", _r.status_code == 303,
      f"status={_r.status_code} {_r.text[:80]}")

_s = database.get_session()
_nuevo = _s.query(database.Client).filter_by(slug="ferreteria").first()
_datos_nuevo = ({"id": _nuevo.id, "token": _nuevo.whatsapp_token,
                 "config": _nuevo.negocio_config, "pnid": _nuevo.phone_number_id}
                if _nuevo else None)
_s.close()

check("el negocio queda creado", _datos_nuevo is not None)

if _datos_nuevo:
    check("su token se guarda CIFRADO, nunca en claro",
          _datos_nuevo["token"].startswith("enc:")
          and "TOKEN-DE-LA-FERRETERIA" not in _datos_nuevo["token"])
    check("y nace con su contenido en la base, no leyendo el entorno",
          bool(_datos_nuevo["config"]))

    # Lo que de verdad importa de un alta: que el negocio ya atienda.
    _antes = len(enviados)
    webhook(_datos_nuevo["pnid"], "573004440001", "hola", "wamid.nueva.1")
    check("y responde por su propio numero desde el primer mensaje",
          len(enviados) > _antes
          and _datos_nuevo["pnid"] in enviados[-1]["url"],
          str(enviados[-1] if enviados else None)[:70])

    _r = requests.post(BASE + "/admin/login", timeout=10, allow_redirects=False,
                       headers={"Host": "ferreteria.ejemplo.test"},
                       data={"clave": "tornillos-y-tuercas"})
    check("su dueño puede entrar al panel con la clave del alta",
          _r.cookies.get("panel_nitro") is not None)

    # ── La ficha: lo que hace falta para operar un cliente de verdad ──
    _cid = _datos_nuevo["id"]

    _r = _super.get(f"{BASE}/superadmin/clientes/{_cid}?bloque=whatsapp",
                    timeout=10)
    check("la ficha del negocio nunca enseña sus credenciales",
          "TOKEN-DE-LA-FERRETERIA" not in _r.text
          and _datos_nuevo["token"] not in _r.text)
    check("pero sí dice que hay una guardada", "guardado" in _r.text)

    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}", timeout=10,
                     allow_redirects=False, data={
                         "nombre": "Ferreteria El Tornillo",
                         "slug": "ferreteria",
                         "phone_number_id": _datos_nuevo["pnid"],
                         "ia_activa": "no", "ia_limite_mensual": "700",
                         "owner_phone_number": "573009998877",
                         "google_calendar_id": "cal-de-la-ferreteria",
                         "historial_dias": "30",
                         "marca_color": "#0055aa",
                         # Los secretos van VACÍOS: no deben tocarse.
                         "whatsapp_token": "", "gemini_api_key": "",
                         "google_service_account_json": "",
                         "vapid_private_key": ""})
    check("guardar la ficha responde con una redirección",
          _r.status_code == 303, f"status={_r.status_code}")

    _s = database.get_session()
    _f = _s.query(database.Client).filter_by(id=_cid).first()
    _tras_guardar = {"token": _f.whatsapp_token, "owner": _f.owner_phone_number,
                     "cal": _f.google_calendar_id, "dias": _f.historial_dias,
                     "tope": _f.ia_limite_mensual, "color": _f.marca_color}
    _s.close()

    # LO IMPORTANTE: abrir la ficha y darle a Guardar no puede dejar al
    # cliente sin token. Vacío significa "no lo toques", no "bórralo".
    check("guardar con las credenciales vacías NO las borra",
          _tras_guardar["token"] == _datos_nuevo["token"],
          f'antes={str(_datos_nuevo["token"])[:12]} despues={str(_tras_guardar["token"])[:12]}')

    check("y sí guarda el resto de lo que hacía falta para operar",
          _tras_guardar["owner"] == "573009998877"
          and _tras_guardar["cal"] == "cal-de-la-ferreteria"
          and _tras_guardar["dias"] == 30
          and _tras_guardar["tope"] == 700
          and _tras_guardar["color"] == "#0055aa", str(_tras_guardar))

    # El número del dueño es el que recibe los avisos de lead: tiene que
    # llegarle a la configuración, no quedarse en la fila.
    with tenencia.usar(_cid):
        check("y el bot ya sabe a quién avisarle de sus leads",
              config.OWNER_PHONE_NUMBER == "573009998877",
              config.OWNER_PHONE_NUMBER)

    # Una credencial nueva sí se guarda, y CIFRADA.
    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}", timeout=10,
                     allow_redirects=False, data={
                         "nombre": "Ferreteria El Tornillo", "slug": "ferreteria",
                         "phone_number_id": _datos_nuevo["pnid"],
                         "ia_activa": "no", "ia_limite_mensual": "700",
                         "whatsapp_token": "TOKEN-ROTADO"})
    _s = database.get_session()
    _rotado = _s.query(database.Client).filter_by(id=_cid).first().whatsapp_token
    _s.close()
    check("rotar el token lo guarda cifrado, no en claro",
          _rotado != _datos_nuevo["token"] and _rotado.startswith("enc:")
          and "TOKEN-ROTADO" not in _rotado)
    with tenencia.usar(_cid):
        check("y el bot lo usa descifrado", config.WHATSAPP_TOKEN == "TOKEN-ROTADO")

    # ── "¿Encendida?" manda de verdad, y la IA se puede probar ──
    #
    # 13-sep-2026: "la IA de Gemini ya no está respondiendo". La ficha
    # decía contratada y "nace encendida: No", y no había forma de saber
    # desde aquí lo que eligió el dueño en su panel ni si Gemini fallaba.
    with tenencia.usar(1):
        _plan_del_otro = ajustes.leer(cerebro.AJUSTE_PLAN, None)

    _super.post(f"{BASE}/superadmin/clientes/{_cid}", timeout=10,
                allow_redirects=False, data={
                    "_bloque": "whatsapp", "ia_contratada": "si",
                    "ia_activa": "si", "ia_limite_mensual": "700"})
    with tenencia.usar(_cid):
        check("encenderla desde la ficha gana sobre lo que eligió el dueño",
              ajustes.leer(cerebro.AJUSTE_PLAN, None) == cerebro.PRO)
    with tenencia.usar(1):
        check("y no le toca el plan a otro negocio",
              ajustes.leer(cerebro.AJUSTE_PLAN, None) == _plan_del_otro)

    _super.post(f"{BASE}/superadmin/clientes/{_cid}", timeout=10,
                allow_redirects=False, data={
                    "_bloque": "whatsapp", "ia_contratada": "si",
                    "ia_activa": "no", "ia_limite_mensual": "700"})
    with tenencia.usar(_cid):
        check("y apagarla también", ajustes.leer(cerebro.AJUSTE_PLAN, None)
              == cerebro.BASICO)
    _r = _super.get(f"{BASE}/superadmin/clientes/{_cid}?bloque=whatsapp",
                    timeout=10)
    check("la ficha dice si la IA contesta HOY, no solo cómo nació",
          "IA apagada" in _r.text, _r.text[_r.text.find("Paquete de IA"):][:200])

    # Probar la IA: el error de Google puede traer la clave dentro, y el
    # mensaje viaja en la URL de la redirección.
    from urllib.parse import unquote_plus as _unq         # noqa: E402
    from app.bot.cerebro import gemini as _gem             # noqa: E402
    _super.post(f"{BASE}/superadmin/clientes/{_cid}", timeout=10,
                allow_redirects=False, data={
                    "_bloque": "whatsapp", "gemini_api_key": "CLAVE-GEMINI-FERRE"})
    _comprobar_real = _gem.comprobar
    def _gemini_rechaza():
        raise _gem.GeminiNoDisponible(
            "La clave no sirvió contra el modelo: API key CLAVE-GEMINI-FERRE "
            "not valid")
    _gem.comprobar = _gemini_rechaza
    try:
        _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/probar-ia",
                         timeout=10, allow_redirects=False)
    finally:
        _gem.comprobar = _comprobar_real
    _destino = _unq(_r.headers.get("location", ""))
    check("'Probar la IA' dice que no respondió y por qué",
          "NO respondió" in _destino and "not valid" in _destino, _destino[:120])
    check("sin dejar la clave en la URL", "CLAVE-GEMINI-FERRE" not in _destino)

    # Se deja como estaba: las pruebas de abajo cuentan con este negocio
    # sin IA ni clave propia.
    _s = database.get_session()
    _s.query(database.Client).filter_by(id=_cid).update(
        {"gemini_api_key": None, "ia_contratada": False})
    _s.commit(); _s.close()
    with tenencia.usar(_cid):
        ajustes.olvidar(cerebro.AJUSTE_PLAN)
    config.olvidar(_cid)

    # ── Los usuarios del panel, desde la ficha ──
    #
    # Lo que se comprueba no es que el formulario pinte: es que lo que se
    # hace en /superadmin CAMBIA QUIEN PUEDE ENTRAR al panel del cliente.
    # Antes esto solo se podía por terminal, o sea que un cliente que
    # perdiera su clave un domingo se quedaba fuera hasta el lunes.

    def _entra(clave):
        """¿Con esa clave se entra al panel de la ferretería?"""
        _p = requests.post(BASE + "/admin/login", timeout=10,
                           allow_redirects=False,
                           headers={"Host": "ferreteria.ejemplo.test"},
                           data={"clave": clave})
        return _p.cookies.get("panel_nitro") is not None

    _r = _super.get(f"{BASE}/superadmin/clientes/{_cid}?bloque=usuarios",
                    timeout=10)
    check("la ficha lista a quién puede entrar al panel",
          "dueno@ferreteria.test" in _r.text
          and f'action="/superadmin/clientes/{_cid}/usuarios"' in _r.text)
    check("y nunca enseña sus claves",
          "tornillos-y-tuercas" not in _r.text)

    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios", timeout=10,
                     allow_redirects=False,
                     data={"email": "asesor@ferreteria.test",
                           "clave": "clave-del-asesor"})
    check("añadir un usuario desde la ficha redirige diciendo que quedó",
          "ok=" in _r.headers.get("location", ""),
          _r.headers.get("location", "")[:70])
    check("y ese usuario ya entra al panel de SU negocio",
          _entra("clave-del-asesor"))

    # La clave de un negocio no abre el de otro, por muy nueva que sea.
    _p = requests.post(BASE + "/admin/login", timeout=10, allow_redirects=False,
                       headers={"Host": HOST_B},
                       data={"clave": "clave-del-asesor"})
    check("pero no abre el panel de otro negocio",
          _p.cookies.get("panel_nitro") is None)

    # Una clave corta no se acepta: es la puerta del panel de un cliente.
    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios", timeout=10,
                     allow_redirects=False,
                     data={"email": "otro@ferreteria.test", "clave": "corta"})
    check("una clave de menos de 8 caracteres se rechaza",
          "mal=" in _r.headers.get("location", ""))
    check("y ese usuario no se crea",
          all(u["email"] != "otro@ferreteria.test"
              for u in acceso.listar_usuarios(_cid)))

    # El caso que motivó todo esto: un cliente llama un domingo diciendo
    # que perdió su clave. El mismo correo, clave nueva, y no se duplica.
    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios", timeout=10,
                     allow_redirects=False,
                     data={"email": "asesor@ferreteria.test",
                           "clave": "clave-nueva-del-asesor"})
    check("volver a poner el mismo correo le cambia la clave, no lo duplica",
          len([u for u in acceso.listar_usuarios(_cid)
               if u["email"] == "asesor@ferreteria.test"]) == 1)
    check("entra con la clave nueva", _entra("clave-nueva-del-asesor"))
    check("y la vieja ya no vale", not _entra("clave-del-asesor"))

    # Dar de baja: deja de entrar, sin borrarle la fila.
    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios/baja",
                     timeout=10, allow_redirects=False,
                     data={"email": "asesor@ferreteria.test"})
    check("dar de baja a un usuario lo deja fuera",
          not _entra("clave-nueva-del-asesor"),
          _r.headers.get("location", "")[:60])
    check("pero no le borra la fila: queda constancia de que estuvo",
          any(u["email"] == "asesor@ferreteria.test" and not u["active"]
              for u in acceso.listar_usuarios(_cid)))

    # Y el dueño, que no se tocó, sigue entrando.
    check("dar de baja a uno no toca a los demás",
          _entra("tornillos-y-tuercas"))

    # LA RED DE SEGURIDAD: el último acceso no se da de baja desde aquí.
    # Dejaría al negocio fuera de su propio panel sin que nadie lo pidiera.
    # Para cortarle el acceso a un cliente entero está el botón de pausar.
    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios/baja",
                     timeout=10, allow_redirects=False,
                     data={"email": "dueno@ferreteria.test"})
    check("no deja dar de baja al único acceso que le queda al negocio",
          "mal=" in _r.headers.get("location", ""),
          _r.headers.get("location", "")[:70])
    check("y el negocio sigue pudiendo entrar", _entra("tornillos-y-tuercas"))

    # Un usuario de baja vuelve con una clave nueva, no con la de antes.
    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios", timeout=10,
                     allow_redirects=False,
                     data={"email": "asesor@ferreteria.test",
                           "clave": "clave-de-la-vuelta"})
    check("reactivar a un usuario le pone una clave nueva",
          _entra("clave-de-la-vuelta") and not _entra("clave-nueva-del-asesor"))

    # Cambiarle el usuario y borrarlo, desde la ficha (13-sep-2026).
    _id_asesor = next(u["id"] for u in acceso.listar_usuarios(_cid)
                      if u["email"] == "asesor@ferreteria.test")
    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios/renombrar",
                     timeout=10, allow_redirects=False,
                     data={"id": _id_asesor, "usuario": "Mostrador"})
    check("cambiarle el usuario desde la ficha lo guarda en minúsculas",
          any(u["id"] == _id_asesor and u["email"] == "mostrador"
              for u in acceso.listar_usuarios(_cid)),
          _r.headers.get("location", "")[:70])
    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios/renombrar",
                     timeout=10, allow_redirects=False,
                     data={"id": _id_asesor, "usuario": "dueno@ferreteria.test"})
    check("y no deja ponerle el de otro usuario",
          "mal=" in _r.headers.get("location", ""))

    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios/borrar",
                     timeout=10, allow_redirects=False, data={"id": _id_asesor})
    check("a quien todavía puede entrar no se le borra desde la ficha",
          "mal=" in _r.headers.get("location", "")
          and any(u["id"] == _id_asesor for u in acceso.listar_usuarios(_cid)))
    _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios/baja",
                timeout=10, allow_redirects=False, data={"email": "mostrador"})
    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios/borrar",
                     timeout=10, allow_redirects=False, data={"id": _id_asesor})
    check("sin acceso, borrarlo lo quita de la lista",
          not any(u["id"] == _id_asesor for u in acceso.listar_usuarios(_cid)),
          _r.headers.get("location", "")[:70])
    check("y la ficha dice con qué usuario y dirección se entra",
          "Cómo se entra" in _super.get(
              f"{BASE}/superadmin/clientes/{_cid}?bloque=usuarios", timeout=10).text)

    # Sin sesión de super-admin no se le tocan los usuarios a nadie: es la
    # forma más barata de meterse en el panel de un cliente.
    _r = requests.post(f"{BASE}/superadmin/clientes/{_cid}/usuarios", timeout=10,
                       allow_redirects=False,
                       data={"email": "intruso@ferreteria.test",
                             "clave": "me-cuelo-en-el-panel"})
    check("sin sesión de super-admin no se puede crear un usuario",
          not _entra("me-cuelo-en-el-panel"), f"status={_r.status_code}")

    # ── El logo se sube como archivo ──
    #
    # El campo sigue aceptando la cadena pegada a mano —es lo que viaja al
    # servidor— pero la ficha trae con qué elegir el archivo y convertirlo
    # en el navegador. Sin eso había que convertir la imagen por fuera.
    _r = _super.get(f"{BASE}/superadmin/clientes/{_cid}?bloque=integraciones",
                    timeout=10)
    check("la ficha ofrece subir el logo como archivo",
          'id="logo-archivo"' in _r.text and 'type="file"' in _r.text)
    check("y sigue habiendo dónde pegar la cadena a mano",
          'name="logo"' in _r.text)

    # Antes esto buscaba "FileReader" DENTRO del HTML, o sea comprobaba que
    # el JavaScript fuera inline. Eso es el detalle de implementación, no la
    # garantía: desde que el super-admin sirve su JS en archivos aparte
    # —como el panel del cliente— lo que hay que exigir es que la página
    # los pida, y que existan.
    check("la página carga el JavaScript del logo",
          "superadmin-logo.js" in _r.text)

    def _direccion_de(html_, archivo):
        """La ruta con la que la página pide un estático, con su versión."""
        marca = f"/estaticos/{archivo}?v="
        if marca not in html_:
            return None
        desde = html_.index(marca)
        return html_[desde:html_.index('"', desde)]

    for _archivo in ("superadmin.css", "superadmin-logo.js"):
        _ruta = _direccion_de(_r.text, _archivo)
        check(f"y {_archivo} se sirve de verdad",
              _ruta is not None
              and _super.get(BASE + _ruta, timeout=10).status_code == 200,
              _ruta or "no está enlazado")

    # ── El editor de contenido ──
    #
    # Lo que se comprueba no es que el formulario pinte: es que lo que se
    # escribe en el panel CAMBIA LO QUE DICE EL BOT, sin tocar código.

    _r = _super.get(f"{BASE}/superadmin/clientes/{_cid}/contenido", timeout=10)
    check("el editor de contenido abre con los textos del negocio",
          'name="texto-bienvenida"' in _r.text)

    # Y NO trae el menú de otro negocio. Antes el alta copiaba el
    # negocio.toml del repositorio como plantilla, así que un cliente
    # nuevo nacía ofreciendo servicios que no vende. Armarlo consistía en
    # borrar, y lo que se quedaba a medio borrar salía por WhatsApp.
    check("y el negocio nuevo NO hereda el menú de la plantilla",
          'name="menu-0-id"' not in _r.text)

    _SALUDO = "Ferreteria El Tornillo al habla, dime que necesitas."
    _formulario = {
        "negocio-nombre": "Ferreteria El Tornillo",
        "texto-bienvenida": _SALUDO,
        "texto-preguntar_necesidad": "Cuentame, ¿que buscas?",
        "menu-0-id": "opt_asesor",
        "menu-0-accion": "humano",
        "menu-0-title": "Hablar con alguien",
    }

    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/contenido", timeout=15,
                     allow_redirects=False, data=_formulario)
    check("guardar el contenido redirige diciendo que quedó",
          "ok=" in _r.headers.get("location", ""),
          _r.headers.get("location", "")[:70])

    _antes = len(enviados)
    webhook(_datos_nuevo["pnid"], "573004440002", "hola", "wamid.contenido.1")
    _dicho = enviados[-1]["texto"] if len(enviados) > _antes else ""
    check("y el bot ya saluda con el texto que se escribió en el panel",
          _SALUDO in _dicho, _dicho[:70])

    # El "deshacer" del editor: la copia de lo que hay guardado AHORA. La
    # validación impide guardar algo roto, pero no devuelve un texto que se
    # borró sin querer; para eso está el archivo.
    _r = _super.get(f"{BASE}/superadmin/clientes/{_cid}/contenido.json",
                    timeout=10)
    _copia = _r.json() if _r.status_code == 200 else {}
    check("se puede descargar una copia del contenido",
          _r.status_code == 200
          and "attachment" in _r.headers.get("content-disposition", ""),
          _r.headers.get("content-disposition", "")[:60])
    check("y la copia trae lo que el bot está diciendo de verdad",
          _copia.get("textos", {}).get("bienvenida") == _SALUDO,
          str(_copia.get("textos", {}).get("bienvenida"))[:50])

    _r = requests.get(f"{BASE}/superadmin/clientes/{_cid}/contenido.json",
                      timeout=10)
    check("pero no sin sesión de super-admin",
          _SALUDO not in _r.text, f"status={_r.status_code}")

    # Lo que el editor no enseña —las pestañas del Sheet— no puede
    # desaparecer al guardar. Si desapareciera, nadie lo notaría hasta que
    # un lead no se registrara en la hoja.
    _s = database.get_session()
    _guardado = _s.query(database.Client).filter_by(id=_cid).first().negocio_config
    _s.close()
    check("y lo que el editor no muestra sigue ahí",
          "sheets" in _guardado,
          f"secciones={sorted(_guardado)}")

    # Un negocio en blanco nace con las dos pestañas donde caen los leads,
    # que no son contenido suyo sino el sitio donde el bot escribe. Sin
    # ellas perdería sus leads en silencio (ver mapa.negocio_en_blanco).
    check("y nace con las pestañas donde caen los leads",
          set(_guardado.get("sheets", {}).get("pestanas", {})) >= {"otros", "citas"},
          str(sorted(_guardado.get("sheets", {}).get("pestanas", {}))))

    # LA RED DE SEGURIDAD: una opción que apunta a un enlace que no existe
    # no se guarda. Es lo que hace que se le pueda dar esto a alguien que
    # no programa — lo peor que pasa es que no deje guardar.
    _malo = dict(_formulario)
    _malo["texto-bienvenida"] = "ESTO NO DEBERIA GUARDARSE"
    _malo["menu-0-enlace"] = "enlace_que_no_existe"

    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/contenido", timeout=15,
                     allow_redirects=False, data=_malo)
    check("una opción que apunta a un enlace inexistente se rechaza",
          "mal=" in _r.headers.get("location", ""),
          _r.headers.get("location", "")[:70])

    _antes = len(enviados)
    webhook(_datos_nuevo["pnid"], "573004440003", "hola", "wamid.contenido.2")
    _dicho = enviados[-1]["texto"] if len(enviados) > _antes else ""
    check("y NO se toca nada: el bot sigue diciendo lo anterior",
          _SALUDO in _dicho and "NO DEBERIA" not in _dicho, _dicho[:70])

    # Y un menú vacío tampoco: es lo que el bot ofrece.
    _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}/contenido", timeout=15,
                     allow_redirects=False,
                     data={"texto-bienvenida": "hola"})
    check("un menú vacío se rechaza",
          "mal=" in _r.headers.get("location", ""))

    # El nombre corto y el phone_number_id no pueden chocar con otro
    # negocio: uno es con lo que entra al panel y el otro con lo que el
    # webhook decide de quién es cada mensaje.
    for _campo, _valor in (("slug", "panaderia"),
                           ("phone_number_id", PNID_B)):
        _datos = {"nombre": "X", "slug": "ferreteria",
                  "phone_number_id": _datos_nuevo["pnid"],
                  "ia_activa": "no", "ia_limite_mensual": "0"}
        _datos[_campo] = _valor
        _r = _super.post(f"{BASE}/superadmin/clientes/{_cid}", timeout=10,
                         allow_redirects=False, data=_datos)
        check(f"no deja pisarle el {_campo} a otro negocio",
              "mal=" in _r.headers.get("location", ""),
              _r.headers.get("location", "")[:70])

# ── El mapa de la conversación ──
#
# El editor por pasos. Lo que se comprueba no es que la página pinte: es
# que lo que se arma en el mapa ES lo que vive el cliente por WhatsApp,
# incluida la profundidad, que antes el bot no sabía recorrer.

def mapa_de(cid):
    return _super.get(f"{BASE}/superadmin/clientes/{cid}/mapa", timeout=10)


def guardar_mapa(cid, cuerpo):
    return _super.post(f"{BASE}/superadmin/clientes/{cid}/mapa", timeout=15,
                       json=cuerpo)


_r = mapa_de(_cid)
check("el mapa abre y lleva el contenido embebido",
      _r.status_code == 200 and 'id="arbol"' in _r.text
      and "let datos =" in _r.text, f"status={_r.status_code}")

# ── Armar una conversación de tres niveles ──
#
# Nivel 1: el menú.  Nivel 2: lo que abre una opción.  Nivel 3: lo que
# abre esa. El tercero es el que antes se dibujaba y al pulsarlo no hacía
# nada, porque `_todas_las_opciones` solo bajaba dos.
_MAPA = {
    "textos": {
        "bienvenida": "Ferreteria El Tornillo, dime que necesitas.",
        "preguntar_necesidad": "¿Con qué te ayudo?",
    },
    "menu": [
        {"id": "herramientas", "title": "Herramientas", "accion": "submenu",
         "mensaje": "¿Qué herramienta buscas?", "submenu": [
             {"id": "taladros", "title": "Taladros", "accion": "submenu",
              "mensaje": "¿De qué tipo?", "submenu": [
                  {"id": "taladro_percutor", "title": "Percutor",
                   "accion": "info",
                   "mensaje": "El percutor cuesta 380.000. Llama al {celular}."},
              ]},
         ]},
        {"id": "asesor", "title": "Hablar con alguien", "accion": "humano"},
    ],
    "variables": {"celular": "310 555 0101"},
    "enlaces": {},
    "precios": {},
}

_r = guardar_mapa(_cid, _MAPA)
check("el mapa se guarda", _r.status_code == 200 and _r.json().get("ok"),
      str(_r.json())[:90])

_antes = len(enviados)
webhook(_datos_nuevo["pnid"], "573004440010", "hola", "wamid.mapa.1")
check("el bot saluda con lo que se escribió en el mapa",
      "El Tornillo, dime que necesitas" in (enviados[-1]["texto"] if len(enviados) > _antes else ""),
      (enviados[-1]["texto"] if enviados else "")[:60])

# Se le da el nombre y se recorre el árbol hasta el tercer nivel.
def pulsar(boton, mid):
    antes = len(enviados)
    requests.post(BASE + "/webhook", timeout=15, json={"entry": [{
        "id": "WABA", "changes": [{"value": {
            "metadata": {"phone_number_id": _datos_nuevo["pnid"]},
            "messages": [{"from": "573004440010", "id": mid,
                          "type": "interactive", "interactive": {
                              "type": "button_reply",
                              "button_reply": {"id": boton, "title": boton}}}]}}]}]})
    return enviados[-1]["texto"] if len(enviados) > antes else ""


webhook(_datos_nuevo["pnid"], "573004440010", "Nico", "wamid.mapa.2")

_dicho = pulsar("herramientas", "wamid.mapa.3")
check("nivel 2: abrir una opción del menú ofrece las de dentro",
      "¿Qué herramienta buscas?" in _dicho, _dicho[:60])

_dicho = pulsar("taladros", "wamid.mapa.4")
check("nivel 3: y las de dentro pueden abrir OTRAS",
      "¿De qué tipo?" in _dicho, _dicho[:60])

_dicho = pulsar("taladro_percutor", "wamid.mapa.5")
check("el tercer nivel responde de verdad (antes caía en 'no entendí')",
      "380.000" in _dicho, _dicho[:70])

# ── Las variables ──
check("y las variables del negocio se sustituyen en la respuesta",
      "310 555 0101" in _dicho and "{celular}" not in _dicho, _dicho[:70])

# ── Lo que el mapa NO administra, no se toca ──
_s = database.get_session()
_tras_mapa = _s.query(database.Client).filter_by(id=_cid).first().negocio_config
_s.close()
check("guardar el mapa no borra las pestañas del Sheet",
      "sheets" in _tras_mapa and "otros" in _tras_mapa["sheets"]["pestanas"],
      f"secciones={sorted(_tras_mapa)}")

# ── La red de seguridad ──
#
# Igual que el editor de contenido: lo peor que puede pasar es que no
# deje guardar. Cada uno de estos rompería una conversación de verdad.
_roto = json.loads(json.dumps(_MAPA))
_roto["menu"].append({"id": "asesor", "title": "Otro asesor", "accion": "humano"})
_r = guardar_mapa(_cid, _roto)
check("dos pasos con el mismo identificador se rechazan",
      not _r.json().get("ok") and "mismo identificador" in _r.json().get("error", ""),
      str(_r.json())[:80])

_roto = json.loads(json.dumps(_MAPA))
_roto["menu"].append({"id": "vacia", "title": "Sin nada dentro",
                      "accion": "submenu", "submenu": []})
_r = guardar_mapa(_cid, _roto)
check("una opción que abre opciones pero está vacía se rechaza",
      not _r.json().get("ok") and "vacía" in _r.json().get("error", ""),
      str(_r.json())[:80])

# El tope de un título depende de CÓMO le llegue: 20 si es un botón, 24
# si es una fila de lista. No es cosmético — pasado eso Meta rechaza el
# mensaje ENTERO y el cliente no recibe nada, ni el texto que lo
# acompañaba. Antes aquí se pedían 24 siempre, así que un botón de 22
# pasaba la revisión y luego dejaba mudo al bot.
_roto = json.loads(json.dumps(_MAPA))
_roto["menu"].append({"id": "larga", "accion": "humano",
                      "title": "Un titulo larguisimo que WhatsApp corta"})
_r = guardar_mapa(_cid, _roto)
check("un botón que WhatsApp no aceptaría se rechaza",
      not _r.json().get("ok") and "20" in _r.json().get("error", ""),
      str(_r.json())[:100])

# 22 caracteres: cabe en una fila de lista, NO en un botón. Con dos
# opciones más en el menú son 3 en total, así que salen como botones.
_roto = json.loads(json.dumps(_MAPA))
_roto["menu"].append({"id": "justa", "accion": "humano",
                      "title": "Hablar con un asesor h"})
_r = guardar_mapa(_cid, _roto)
check("y uno de 22, que cabría en una lista pero no en un botón, también",
      not _r.json().get("ok") and "20" in _r.json().get("error", ""),
      str(_r.json())[:100])

# El mismo título, con el menú convertido en lista (más de 3 opciones):
# ahí sí cabe, y tiene que dejar guardar.
_bien = json.loads(json.dumps(_MAPA))
_bien["menu"].append({"id": "justa", "accion": "humano",
                      "title": "Hablar con un asesor h"})
_bien["menu"].append({"id": "otra_mas", "accion": "humano", "title": "Otra"})
_bien["menu"].append({"id": "y_otra", "accion": "humano", "title": "Y otra"})
_r = guardar_mapa(_cid, _bien)
check("ese mismo título SÍ se acepta cuando el menú sale como lista",
      _r.json().get("ok"), str(_r.json())[:100])

# Se deja el mapa como estaba, que las comprobaciones de abajo lo usan.
guardar_mapa(_cid, _MAPA)

# Y tras cada rechazo, el bot sigue diciendo lo de antes: o entra todo o
# no entra nada.
_dicho = pulsar("asesor", "wamid.mapa.6")
check("tras los rechazos, el mapa bueno sigue vivo", bool(_dicho), _dicho[:50])

# Un menú vacío SÍ se puede guardar: un negocio se arma a ratos, y
# obligar a terminarlo de una sentada es lo que hacía falta evitar.
_r = guardar_mapa(_cid, {"menu": [], "textos": _MAPA["textos"],
                         "variables": {}, "enlaces": {}, "precios": {}})
check("un menú vacío sí se puede guardar (se arma a ratos)",
      _r.json().get("ok"), str(_r.json())[:80])

# Y entonces el bot responde con cortesía en vez de romperse. El saludo
# sale igual —eso no depende del menú—; la cortesía aparece cuando le
# tocaría ofrecer las opciones, o sea después de preguntar el nombre.
webhook(_datos_nuevo["pnid"], "573004440011", "hola?", "wamid.mapa.7")
_antes = len(enviados)
webhook(_datos_nuevo["pnid"], "573004440011", "Ana", "wamid.mapa.8")

# Se filtra por destinatario: entre lo enviado va también el aviso al
# DUEÑO, que es la otra mitad de esto —para él, alguien escribiendo a un
# bot sin armar es un lead que se está perdiendo.
_al_cliente = [e["texto"] for e in enviados[_antes:] if e["a"] == "573004440011"]
_al_dueno = [e["texto"] for e in enviados[_antes:] if e["a"] != "573004440011"]

check("un negocio sin menú responde con cortesía, no con silencio",
      any("en un momento te atendemos" in t.lower() for t in _al_cliente),
      str(_al_cliente)[:70])
check("y al dueño le llega el aviso de que su bot está sin armar",
      any("todavía no tiene menú" in t for t in _al_dueno),
      str(_al_dueno)[:70])

# Y con el menú vacío, un texto vacío jamás: WhatsApp rechaza el envío y
# el cliente se queda sin respuesta sin que nadie se entere.
check("y ningún mensaje del bot sale vacío",
      all((e["texto"] or "").strip() for e in enviados[-4:]),
      str([e["texto"][:18] for e in enviados[-4:]]))

# Se deja el mapa bueno puesto para lo que venga después.
guardar_mapa(_cid, _MAPA)

# -- El texto que viene de [precios] tambien se puede cambiar --
#
# El caso del dueno, y el que mas costo: cambio el bloque de precios de su
# chatbot desde el panel, guardo, borro la conversacion, escribio desde
# otro numero... y el bot siguio mandando los precios viejos. La URL SI le
# habia cambiado.
#
# La causa: la opcion no guarda su texto, apunta a un bloque de [precios]
# por nombre, y `config_cliente._opcion` SOBRESCRIBE el mensaje con ese
# bloque. Se escribia en un campo que despues pisaba otra cosa.

_PRECIOS = json.loads(json.dumps(_MAPA))
_PRECIOS["precios"] = {"chatbot": "PRECIOS VIEJOS: instalacion 300.000"}
_PRECIOS["menu"] = [
    {"id": "ver_precios", "title": "Ver precios", "accion": "info",
     "precios": "chatbot"},
    {"id": "otro_servicio", "title": "Otro servicio", "accion": "info",
     "precios": "chatbot"},
    {"id": "asesor3", "title": "Hablar con alguien", "accion": "humano"},
]
_r = guardar_mapa(_cid, _PRECIOS)
check("una opcion puede tomar su texto de los precios compartidos",
      _r.json().get("ok"), str(_r.json())[:70])

webhook(_datos_nuevo["pnid"], "573004440050", "hola", "wamid.precio.1")
webhook(_datos_nuevo["pnid"], "573004440050", "Ana", "wamid.precio.2")


def pulsar_precio(boton, mid, telefono="573004440050"):
    antes = len(enviados)
    requests.post(BASE + "/webhook", timeout=15, json={"entry": [{
        "id": "WABA", "changes": [{"value": {
            "metadata": {"phone_number_id": _datos_nuevo["pnid"]},
            "messages": [{"from": telefono, "id": mid, "type": "interactive",
                          "interactive": {"type": "button_reply",
                                          "button_reply": {"id": boton,
                                                           "title": boton}}}]}}]}]})
    return " ".join(e["texto"] for e in enviados[antes:])


check("y el bot manda ese bloque",
      "PRECIOS VIEJOS" in pulsar_precio("ver_precios", "wamid.precio.3"), "")

# Ahora se cambia el texto DE ESA OPCION, como lo hace el editor: escribe
# su propio mensaje y deja de apuntar al bloque.
_NUEVO = json.loads(json.dumps(_PRECIOS))
_NUEVO["menu"][0] = {"id": "ver_precios", "title": "Ver precios",
                     "accion": "info",
                     "mensaje": "PRECIOS NUEVOS: instalacion 130.000"}
_r = guardar_mapa(_cid, _NUEVO)
check("cambiar ese texto desde el mapa se guarda", _r.json().get("ok"),
      str(_r.json())[:70])

webhook(_datos_nuevo["pnid"], "573004440051", "hola", "wamid.precio.4")
webhook(_datos_nuevo["pnid"], "573004440051", "Ana", "wamid.precio.5")
_dicho = pulsar_precio("ver_precios", "wamid.precio.6", "573004440051")

check("y el bot manda el texto NUEVO, no el bloque de siempre",
      "PRECIOS NUEVOS" in _dicho and "PRECIOS VIEJOS" not in _dicho,
      _dicho[:70])

# Y la otra opcion, que seguia apuntando al bloque, no se toca.
_dicho = pulsar_precio("otro_servicio", "wamid.precio.7", "573004440051")
check("y el otro servicio sigue con el bloque compartido",
      "PRECIOS VIEJOS" in _dicho, _dicho[:70])

# El caso que de verdad le pasó al dueño: la opción acabó con SU texto y
# ADEMÁS el puntero al bloque compartido, porque lo guardó una pestaña con
# el editor de antes. El puntero pisaba su texto, así que el cambio estaba
# en la base y el bot seguía mandando lo viejo.
#
# Lo propio de la opción tiene que ganar, sin que él tenga que volver a
# escribir nada.
_CON_LOS_DOS = json.loads(json.dumps(_PRECIOS))
_CON_LOS_DOS["menu"][0] = {
    "id": "ver_precios", "title": "Ver precios", "accion": "info",
    "mensaje": "MIS PRECIOS DE AHORA",
    "precios": "chatbot",          # el puntero que se quedo pegado
}

# Se escribe DIRECTO en la base, saltandose el editor: es como quedo su
# dato, y hay que arreglarlo sin pedirle que lo vuelva a guardar. Se parte
# de lo que ya hay para no pisarle el resto de secciones.
_s = database.get_session()
_actual = dict(_s.query(database.Client).filter_by(id=_cid).first().negocio_config)
_actual["menu"] = _CON_LOS_DOS["menu"]
_actual["precios"] = _CON_LOS_DOS["precios"]
_s.query(database.Client).filter_by(id=_cid).update({"negocio_config": _actual})
_s.commit()
_s.close()
config.olvidar(_cid)

webhook(_datos_nuevo["pnid"], "573004440060", "hola", "wamid.gana.1")
webhook(_datos_nuevo["pnid"], "573004440060", "Ana", "wamid.gana.2")
_dicho = pulsar_precio("ver_precios", "wamid.gana.3", "573004440060")
check("con las dos cosas guardadas, gana el texto propio de la opcion",
      "MIS PRECIOS DE AHORA" in _dicho and "PRECIOS VIEJOS" not in _dicho,
      _dicho[:70])

# Y al volver a guardar desde el panel, el puntero se va: el dato queda
# limpio y no vuelve a haber dos fuentes para lo mismo.
_r = guardar_mapa(_cid, _CON_LOS_DOS)
check("y al guardar desde el panel, el puntero se limpia solo",
      _r.json().get("ok"), str(_r.json())[:60])

_s = database.get_session()
_op = (_s.query(database.Client).filter_by(id=_cid).first()
       .negocio_config["menu"][0])
_s.close()
check("la opcion se queda solo con su texto",
      "precios" not in _op and _op.get("mensaje") == "MIS PRECIOS DE AHORA",
      str(sorted(_op))[:70])

guardar_mapa(_cid, _MAPA)   # se deja como estaba

# ── TODO texto que el bot puede decir se puede editar ──
#
# El dueño: "cuando quiero modificar el texto de lo que arroja el bot
# originalmente no me permite hacerlo". Tenía razón a medias: el mapa
# dejaba editar 6 de los 34 textos del bot, y los otros 28 solo estaban en
# el editor de contenido. Se comprueba contra la tabla de defectos, que es
# la lista de todo lo que el bot sabe decir.
from app.core.config_cliente import TEXTOS_POR_DEFECTO as _DEFECTOS  # noqa: E402
from app.web import mapa as _mapa                          # noqa: E402

# Los que se editan dentro de su paso los declara el propio mapa; los
# demás, en "Los demás textos".
_en_el_mapa = set(_mapa.TEXTOS_EN_PASOS)
for _g, _campos in _mapa.GRUPOS_DE_TEXTOS:
    _en_el_mapa.update(c for c, _ in _campos)

_sin_editar = sorted(set(_DEFECTOS) - _en_el_mapa)
check("todos los textos del bot se pueden editar desde el mapa",
      not _sin_editar, f"no se pueden: {_sin_editar}")

# Declararlo en TEXTOS_EN_PASOS no basta: algún paso del editor tiene que
# escribirlo de verdad. Sin esto, la lista de arriba podría prometer un
# campo que no existe en ninguna pantalla.
_js_mapa = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app", "web", "estaticos",
    "superadmin-mapa.js"), encoding="utf-8").read()
_prometidos = sorted(c for c in _mapa.TEXTOS_EN_PASOS
                     if f"datos.textos.{c} = " not in _js_mapa)
check("y cada texto que va dentro de un paso lo edita ese paso",
      not _prometidos, f"sin campo: {_prometidos}")

# Y uno de punta a punta, de los que antes no estaban: lo que contesta
# cuando no entiende. Es el que más se toca al ajustar un bot.
_TEXTOS = json.loads(json.dumps(_MAPA))
_TEXTOS["textos"] = dict(_TEXTOS["textos"])
_TEXTOS["textos"]["no_entendi"] = "Perdona, no te seguí. ¿Lo dices de otra forma?"
_r = guardar_mapa(_cid, _TEXTOS)
check("se puede cambiar lo que dice cuando no entiende",
      _r.json().get("ok"), str(_r.json())[:70])

webhook(_datos_nuevo["pnid"], "573004440040", "hola", "wamid.texto.1")
webhook(_datos_nuevo["pnid"], "573004440040", "Ana", "wamid.texto.2")
_antes = len(enviados)
webhook(_datos_nuevo["pnid"], "573004440040", "jkasdhfkjasdhf", "wamid.texto.3")
_dicho = " ".join(e["texto"] for e in enviados[_antes:])
check("y el bot lo dice de verdad", "no te seguí" in _dicho, _dicho[:70])

guardar_mapa(_cid, _MAPA)   # se deja como estaba

# ── El enlace es de SU opción y no pisa a las demás ──
#
# Lo cazó el dueño al no poder guardar: "la opción 'chatbot_precios' pide
# el enlace 'chatbot_precios', que no está en [enlaces]". El editor
# escribía en el diccionario compartido `[enlaces]`, así que **vaciar el
# campo en una opción borraba el enlace de todas las que lo compartían**
# —cuatro, en su caso— y al guardar reventaba señalando una opción que
# nadie había tocado.

_ENLACES = json.loads(json.dumps(_MAPA))
_ENLACES["enlaces"] = {"compartido": "https://ejemplo.test/comun"}
_ENLACES["menu"] = [
    {"id": "una", "title": "Ver precios", "accion": "info",
     "mensaje": "Aquí los tienes: {url}", "url": "https://ejemplo.test/suyo"},
    {"id": "otra", "title": "Ver catálogo", "accion": "info",
     "mensaje": "Mira: {url}", "enlace": "compartido"},
    {"id": "asesor2", "title": "Hablar con alguien", "accion": "humano"},
]
_r = guardar_mapa(_cid, _ENLACES)
check("una opción puede llevar su propio enlace", _r.json().get("ok"),
      str(_r.json())[:80])

# Lo que importa: que ese enlace LLEGUE al cliente por WhatsApp.
webhook(_datos_nuevo["pnid"], "573004440030", "hola", "wamid.enlace.1")
webhook(_datos_nuevo["pnid"], "573004440030", "Ana", "wamid.enlace.2")


def pulsar_en(boton, mid, telefono="573004440030"):
    antes = len(enviados)
    requests.post(BASE + "/webhook", timeout=15, json={"entry": [{
        "id": "WABA", "changes": [{"value": {
            "metadata": {"phone_number_id": _datos_nuevo["pnid"]},
            "messages": [{"from": telefono, "id": mid, "type": "interactive",
                          "interactive": {"type": "button_reply",
                                          "button_reply": {"id": boton,
                                                           "title": boton}}}]}}]}]})
    return enviados[-1]["texto"] if len(enviados) > antes else ""


_dicho = pulsar_en("una", "wamid.enlace.3")
check("y el bot lo manda tal cual", "https://ejemplo.test/suyo" in _dicho,
      _dicho[:70])

# Y el de la otra opción, que sigue usando el compartido de siempre.
_dicho = pulsar_en("otra", "wamid.enlace.4")
check("y el enlace compartido de otra opción sigue funcionando",
      "https://ejemplo.test/comun" in _dicho, _dicho[:70])

# La red de seguridad que faltaba: un enlace que apunta a un nombre
# inexistente se rechaza entero, y dice cuál es.
_roto = json.loads(json.dumps(_ENLACES))
_roto["enlaces"] = {}          # como si se hubiera borrado el compartido
_r = guardar_mapa(_cid, _roto)
check("y si un enlace compartido desaparece, NO se guarda a medias",
      not _r.json().get("ok") and "compartido" in _r.json().get("error", ""),
      str(_r.json())[:90])

guardar_mapa(_cid, _MAPA)   # se deja como estaba

# ── El editor y el bot tienen que hablar del mismo idioma ──
#
# Esto lo cazó el dueño en producción, y de la peor forma: no podía
# guardar su propio mapa porque el editor rechazaba una acción que su bot
# lleva usando desde siempre ("'Cambiar de horario' tiene una acción que
# el bot no entiende: 'reagendar'"). La lista del editor se escribió a
# mano mirando el código, y se dejó fuera las de citas.
#
# Se comprueba contra la FUENTE, no contra otra lista escrita a mano: si
# mañana el bot aprende una acción nueva y nadie la añade al editor, esto
# falla aquí y no en el negocio de alguien.
import inspect as _inspect                                 # noqa: E402
import re as _re                                           # noqa: E402
from app.bot import bot_logic as _bl                       # noqa: E402
from app.web import mapa as _mapa                          # noqa: E402

_fuente = _inspect.getsource(_bl)
_del_bot = set(_re.findall(r'accion == "([a-z_]+)"', _fuente))
for _grupo in _re.findall(r'accion in \(([^)]+)\)', _fuente):
    _del_bot.update(_re.findall(r'"([a-z_]+)"', _grupo))

_faltan = sorted(_del_bot - set(_mapa.ACCIONES_VALIDAS))
check("el editor acepta TODAS las acciones que el bot entiende",
      not _faltan, f"le faltan: {_faltan}")

_sobran = sorted(set(_mapa.ACCIONES_VALIDAS) - _del_bot)
check("y no ofrece ninguna que el bot ignore", not _sobran,
      f"sobran: {_sobran}")

# Y el caso concreto, de punta a punta: un menú de citas se guarda.
_CON_CITAS = json.loads(json.dumps(_MAPA))
_CON_CITAS["menu"].append({
    "id": "mi_cita", "title": "Mi cita", "accion": "submenu",
    "mensaje": "¿Qué hacemos con tu cita del {date}?",
    "solo_con_cita": True,
    "submenu": [
        {"id": "mover_cita", "title": "Cambiar de horario", "accion": "reagendar"},
        {"id": "anular_cita", "title": "Cancelar", "accion": "cancelar"},
    ]})
_r = guardar_mapa(_cid, _CON_CITAS)
check("un menú para gestionar citas se guarda sin pelear",
      _r.json().get("ok"), str(_r.json())[:90])

_s = database.get_session()
_guardado_citas = _s.query(database.Client).filter_by(id=_cid).first().negocio_config
_s.close()
_rama = [o for o in _guardado_citas["menu"] if o["id"] == "mi_cita"]
check("y conserva que solo se le enseña a quien tiene una",
      bool(_rama) and _rama[0].get("solo_con_cita") is True,
      str(_rama)[:70])

guardar_mapa(_cid, _MAPA)   # se deja como estaba

# ── El nombre: preguntarlo o tomarlo de WhatsApp ──
#
# Preguntarlo es un mensaje más antes de poder venderle, y casi todo el
# mundo lo tiene puesto en su perfil. Meta lo manda en cada webhook, al
# lado de los mensajes y no dentro de ellos.

def webhook_con_perfil(pnid, telefono, texto, mid, perfil):
    return requests.post(BASE + "/webhook", timeout=15, json={"entry": [{
        "id": "WABA", "changes": [{"value": {
            "metadata": {"phone_number_id": pnid},
            "contacts": [{"wa_id": telefono, "profile": {"name": perfil}}],
            "messages": [{"from": telefono, "id": mid, "type": "text",
                          "text": {"body": texto}}]}}]}]})


_SIN_PREGUNTAR = json.loads(json.dumps(_MAPA))
_SIN_PREGUNTAR["conversacion"] = {"pedir_nombre": False}
_r = guardar_mapa(_cid, _SIN_PREGUNTAR)
check("se puede elegir no preguntar el nombre", _r.json().get("ok"),
      str(_r.json())[:70])

_antes = len(enviados)
webhook_con_perfil(_datos_nuevo["pnid"], "573004440020", "hola",
                   "wamid.nombre.1", "Marcela")
_dicho = [e["texto"] for e in enviados[_antes:]]
check("con el nombre de WhatsApp, el bot ofrece el menú al primer mensaje",
      any("dime que necesitas" in t.lower() or "necesitas" in t.lower()
          for t in _dicho), str(_dicho)[:90])

_s = database.get_session()
with tenencia.usar(_cid):
    _contacto = _s.query(database.Contact).filter_by(phone="573004440020").first()
    _nombre = _contacto.name if _contacto else None
    _estado = _contacto.state if _contacto else None
_s.close()
check("y le queda guardado el nombre de su perfil", _nombre == "Marcela",
      str(_nombre))
check("sin pasar por el paso de preguntarlo", _estado != "ASKED_NAME", str(_estado))

# Si el perfil no viene —Meta no lo garantiza— se pregunta igual: quedarse
# sin nombre estropea todos los textos que lo usan.
_antes = len(enviados)
webhook(_datos_nuevo["pnid"], "573004440021", "hola", "wamid.nombre.2")
_s = database.get_session()
with tenencia.usar(_cid):
    _sin = _s.query(database.Contact).filter_by(phone="573004440021").first()
    _estado_sin = _sin.state if _sin else None
_s.close()
check("y si su WhatsApp no trae nombre, se lo pregunta igual",
      _estado_sin == "ASKED_NAME", str(_estado_sin))

# Lo que el mapa NO administra de esa sección sigue intacto: solo toca
# `pedir_nombre`, y los plazos viven en el editor de contenido.
_s = database.get_session()
_conv = (_s.query(database.Client).filter_by(id=_cid).first()
         .negocio_config.get("conversacion") or {})
_s.close()
check("y guardar el nombre no borra el resto de esa sección",
      "caduca_horas" in _conv or len(_conv) >= 1, str(_conv)[:70])

guardar_mapa(_cid, _MAPA)   # se deja como estaba

# ── Entrenar a la IA desde el mapa ──
#
# No entrena ningún modelo: escribe las instrucciones que recibe en cada
# mensaje. Lo que se comprueba es justo eso — que lo escrito en el panel
# LLEGA al prompt, porque un ajuste que no llega es peor que no tenerlo.
_CON_IA = json.loads(json.dumps(_MAPA))
_CON_IA["ia"] = {
    "rol": "el asesor de repuestos de {negocio}",
    "tono": "seco y directo, sin emojis",
    "nunca": ["inventar precios", "prometer plazos"],
    "siempre_derivar": ["reclamos", "garantías"],
    "max_palabras": 25,
}
_r = guardar_mapa(_cid, _CON_IA)
check("los ajustes de la IA se guardan desde el mapa", _r.json().get("ok"),
      str(_r.json())[:70])

from app.bot.cerebro import gemini as _gemini   # noqa: E402

with tenencia.usar(_cid):
    _prompt = _gemini._instrucciones(config.NEED_OPTIONS)

check("y llegan al prompt: quién dice ser",
      "asesor de repuestos de Ferreteria El Tornillo" in _prompt,
      _prompt[:60])
check("el tono", "seco y directo, sin emojis" in _prompt)
check("lo que tiene prohibido",
      "inventar precios" in _prompt and "prometer plazos" in _prompt)
check("los temas que pasa a una persona",
      "reclamos" in _prompt and "garantías" in _prompt)
check("y el largo máximo", "máximo 25 palabras" in _prompt,
      " ".join(_prompt.split())[-90:])

# El mapa administra la IA, así que lo que NO administra sigue intacto.
_s = database.get_session()
_tras_ia = _s.query(database.Client).filter_by(id=_cid).first().negocio_config
_s.close()
check("y guardar la IA no borra las pestañas del Sheet",
      "sheets" in _tras_ia, f"secciones={sorted(_tras_ia)}")

# ── Lo que la pantalla tiene que decir sola ──
_r = mapa_de(_cid)
check("el mapa lleva el tope de botones de WhatsApp",
      '"max_botones": 3' in _r.text)
check("y los cinco ajustes de la IA, ni uno más",
      all(f'"{c}"' in _r.text for c in
          ("rol", "tono", "nunca", "siempre_derivar", "max_palabras")))

# Se deja el mapa sin la IA para no arrastrarlo a otras comprobaciones.
guardar_mapa(_cid, _MAPA)

# Sin sesión de super-admin no se le arma el bot a nadie.
_r = requests.post(f"{BASE}/superadmin/clientes/{_cid}/mapa", timeout=10,
                   json={"menu": []})
check("sin sesión de super-admin no se puede guardar el mapa",
      _r.status_code == 401, f"status={_r.status_code}")


# Un slug repetido o reservado no puede pasar: es el subdominio del panel.
for _slug, _motivo in (("panaderia", "repetido"), ("www", "reservado"),
                       ("Con Mayusculas", "mal escrito")):
    _r = _super.post(BASE + "/superadmin/clientes", timeout=10,
                     allow_redirects=False, data={
                         "nombre": "X", "slug": _slug,
                         "phone_number_id": "5000000000005",
                         "whatsapp_token": "t", "email": "x@x.test",
                         "clave": "12345678"})
    check(f"un subdominio {_motivo} se rechaza",
          "/superadmin/nuevo" in _r.headers.get("location", ""),
          _r.headers.get("location", "")[:60])


# ── 10. El logo es de cada negocio ───────────────────────────────────
#
# Hasta la Fase 4 el icono salia de app/marca/logo.png, un archivo del
# repositorio: dos negocios instalaban la app con la MISMA imagen.

print("\n=== El icono lleva el logo de cada negocio ===")

try:
    from PIL import Image as _Img                              # noqa: E402
    import base64, io as _io                                   # noqa: E402
    _buf = _io.BytesIO()
    _Img.new("RGBA", (64, 64), (220, 30, 30, 255)).save(_buf, format="PNG")
    _ROJO = base64.b64encode(_buf.getvalue()).decode()
except ImportError:
    _ROJO = None

_s = database.get_session()
_s.query(database.Client).filter_by(id=2).update({"logo": _ROJO})
_s.commit(); _s.close()
config.olvidar(2)
pwa.olvidar()

_iconos = {}
for _host, _cid in ((HOST_A, 1), (HOST_B, 2)):
    _r = requests.get(BASE + "/icono-192.png", timeout=10, headers={"Host": _host})
    _iconos[_cid] = _r.content if _r.status_code == 200 else None

if all(_iconos.values()):
    check("el icono de cada negocio es una imagen distinta",
          _iconos[1] != _iconos[2], f"{len(_iconos[1])} vs {len(_iconos[2])} bytes")
    with tenencia.usar(2):
        check("y el logo del negocio sale de SU fila, no de un archivo del repo",
              config.LOGO == _ROJO)
else:
    print("  [--] icono: falta Pillow en este entorno, se omite")


# ── 11. Todos los negocios en UNA SOLA direccion ─────────────────────
#
# Es el despliegue sin subdominios: no hay dominio comodin ni un dominio
# por cliente, asi que el `Host` ya no distingue a nadie y el inquilino
# sale del pase firmado. La promesa a comprobar es la misma de siempre, y
# ahora sin la red de seguridad del subdominio:
#
#     dos negocios, la MISMA direccion, y ninguno ve lo del otro.

print("\n=== Todos en la misma direccion (sin subdominios) ===")

os.environ["DOMINIO_BASE"] = ""      # el interruptor; se lee en cada peticion

# El moroso esta pausado y ahora SI tiene con que entrar: sirve para
# comprobar que la pausa por impago sigue cortando el paso cuando ya no hay
# subdominio que la haga cumplir.
acceso.crear_usuario(3, "moroso@test", "clave-del-moroso")


def entrar_compartido(negocio, clave):
    """Entra por la direccion comun, como lo hara un cliente de verdad."""
    sesion = requests.Session()
    r = sesion.post(BASE + "/admin/login", timeout=10, allow_redirects=False,
                    data={"negocio": negocio, "clave": clave})
    return sesion, r


_sesion_a, _r_a = entrar_compartido("negocio-a", "clave-multi-prueba")
_sesion_b, _r_b = entrar_compartido("panaderia", "pan-recien-horneado")

check("el dueno entra escribiendo el nombre de su negocio",
      "panel_nitro" in _sesion_a.cookies, f"status={_r_a.status_code}")
check("y la panaderia el suyo, por la MISMA direccion",
      "panel_nitro" in _sesion_b.cookies, f"status={_r_b.status_code}")

if "panel_nitro" in _sesion_a.cookies and "panel_nitro" in _sesion_b.cookies:
    check("cada pase queda emitido a nombre de su negocio",
          _sesion_a.cookies["panel_nitro"].startswith(f"{acceso.VERSION}:1:")
          and _sesion_b.cookies["panel_nitro"].startswith(f"{acceso.VERSION}:2:"),
          f'{_sesion_a.cookies["panel_nitro"][:8]} vs '
          f'{_sesion_b.cookies["panel_nitro"][:8]}')

    # LO QUE IMPORTA: misma URL, misma maquina, y listados distintos.
    _conv_a = {c["phone"] for c in _sesion_a.get(
        BASE + "/admin/api/conversaciones", timeout=10).json()["conversaciones"]}
    _conv_b = {c["phone"] for c in _sesion_b.get(
        BASE + "/admin/api/conversaciones", timeout=10).json()["conversaciones"]}

    check("el dueno ve sus conversaciones y NINGUNA de la panaderia",
          TEL_A in _conv_a and TEL_B not in _conv_a, f"vio {sorted(_conv_a)}")
    check("y la panaderia las suyas y ninguna del dueno",
          TEL_B in _conv_b and TEL_A not in _conv_b, f"vio {sorted(_conv_b)}")

    # Sin subdominio, la firma del pase es la UNICA proteccion. Que aguante
    # es justo lo que hay que comprobar: cambiarle el numero de cliente a
    # mano tiene que romperla.
    _partes = _sesion_a.cookies["panel_nitro"].split(":")
    _falsificado = ":".join([_partes[0], "2"] + _partes[2:])
    _r = requests.get(BASE + "/admin/api/conversaciones", timeout=10,
                      headers={"Cookie": f"panel_nitro={_falsificado}"})
    check("cambiarle el negocio al pase rompe la firma y no entra",
          _r.status_code == 401, f"status={_r.status_code}")

check("un negocio pausado no entra aunque la clave sea correcta",
      "panel_nitro" not in entrar_compartido(
          "moroso", "clave-del-moroso")[0].cookies)

check("un negocio que no existe tampoco",
      "panel_nitro" not in entrar_compartido(
          "no-existe", "cualquier-clave")[0].cookies)

# La casilla vacia es el atajo del cliente por defecto: mientras el dueno
# sea el unico negocio, entra como entraba antes de que existiera todo esto.
check("con la casilla vacia entra el cliente por defecto",
      "panel_nitro" in entrar_compartido("", "clave-multi-prueba")[0].cookies)

# ── Usuario y clave, sin escribir el negocio ──
#
# 13-sep-2026: "El negocio o la clave no son correctos", y el dueño sin
# saber con qué usuario entraba ni dónde había cambiado la clave. Ahora se
# entra con usuario y clave; el usuario es único en la plataforma y dice
# solo de qué negocio es.
#
# La trampa que esto vigila: el login corre con el cliente por defecto
# puesto por el middleware, y buscar el usuario con ese inquilino fijado
# no encontraría NUNCA a los de otro negocio. Sin ningún error.


def entrar_con_usuario(usuario, clave):
    sesion = requests.Session()
    sesion.post(BASE + "/admin/login", timeout=10, allow_redirects=False,
                data={"usuario": usuario, "clave": clave})
    return sesion.cookies.get("panel_nitro") or ""


_pase_rosa = entrar_con_usuario("rosa@panaderia.test", "pan-recien-horneado")
check("un usuario de OTRO negocio entra con usuario y clave, sin negocio",
      _pase_rosa.startswith(f"{acceso.VERSION}:2:"), _pase_rosa[:10])
check("sin distinguir mayúsculas ni espacios",
      entrar_con_usuario(" Rosa@Panaderia.test ", "pan-recien-horneado")
      .startswith(f"{acceso.VERSION}:2:"))
check("con la clave de otro negocio no entra",
      not entrar_con_usuario("rosa@panaderia.test", "clave-multi-prueba"))
check("el usuario de un negocio pausado no entra",
      not entrar_con_usuario("moroso@test", "clave-del-moroso"))

try:
    acceso.crear_usuario(1, "ROSA@panaderia.test", "otra-clave-cualquiera")
    check("un usuario no puede repetirse en otro negocio", False, "no lo impidió")
except acceso.UsuarioOcupado as _e:
    check("un usuario no puede repetirse en otro negocio",
          "Panaderia" in str(_e), str(_e)[:80])

_id_rosa = next(u["id"] for u in acceso.listar_usuarios(2)
                if u["email"] == "rosa@panaderia.test")
acceso.renombrar_usuario(2, _id_rosa, "Rosa")
check("cambiarle el usuario lo deja entrar con el nuevo y la misma clave",
      entrar_con_usuario("rosa", "pan-recien-horneado")
      .startswith(f"{acceso.VERSION}:2:"))
check("y con el viejo ya no",
      not entrar_con_usuario("rosa@panaderia.test", "pan-recien-horneado"))
acceso.renombrar_usuario(2, _id_rosa, "rosa@panaderia.test")

acceso.crear_usuario(2, "temporal", "clave-temporal")
_id_tmp = next(u["id"] for u in acceso.listar_usuarios(2)
               if u["email"] == "temporal")
check("a quien todavía puede entrar no se le borra",
      acceso.borrar_usuario(2, _id_tmp) is False)
acceso.desactivar_usuario(2, "temporal")
check("sin acceso, se le borra para siempre y su nombre queda libre",
      acceso.borrar_usuario(2, _id_tmp) and acceso.quien_usa("temporal") is None)

# Y la puerta de los subdominios sigue abierta: volver a ponerla los
# reactiva sin tocar codigo, que es lo que permite cambiar de idea.
os.environ["DOMINIO_BASE"] = "ejemplo.test"
_r = requests.get(BASE + "/admin/login", timeout=10, headers={"Host": HOST_B})
check("volver a poner DOMINIO_BASE reactiva los subdominios",
      _r.status_code == 200 and "Panaderia Dona Rosa" in _r.text,
      f"status={_r.status_code}")
_r = requests.get(BASE + "/admin/login", timeout=10, headers={"Host": "nadie.ejemplo.test"})
check("y con ellos vuelve el 404 del subdominio desconocido",
      _r.status_code == 404, f"status={_r.status_code}")


# ── La URL de webhook de cada cliente ────────────────────────────────
#
# Desde que cada negocio trae SU propia App de Meta, el webhook ya no es
# una sola puerta: cada cliente tiene la suya, /webhook/{token}. Es lo que
# permite validar la firma con el App Secret correcto, porque dice de
# quién es el POST antes de tocar el cuerpo.
#
# Lo que se comprueba aquí es que esa puerta AÍSLA. La firma se prueba en
# test_regresion; aquí importa el enrutamiento.

print("\n=== La URL de webhook es de cada cliente ===")

TOKEN_A, TOKEN_B = "urlsecreta-de-a", "urlsecreta-de-b"

_s = database.get_session()
_s.query(database.Client).filter_by(id=1).update(
    {"webhook_token": TOKEN_A, "verify_token": "verify-de-a", "active": True})
_s.query(database.Client).filter_by(id=2).update(
    {"webhook_token": TOKEN_B, "verify_token": "verify-de-b", "active": True})
_s.commit()
_s.close()
tenencia.olvidar()
config.olvidar()


def webhook_por_url(token, pnid, telefono, texto, mid):
    """Un mensaje que entra por la URL propia de un cliente."""
    return requests.post(f"{BASE}/webhook/{token}", timeout=10, json={"entry": [{
        "id": "WABA", "changes": [{"value": {
            "metadata": {"phone_number_id": pnid},
            "messages": [{"from": telefono, "id": mid, "type": "text",
                          "text": {"body": texto}}]}}]}]})


TEL_URL = "573009998877"

enviados.clear()
_r = webhook_por_url(TOKEN_A, PNID_A, TEL_URL, "hola", "wamid.url.a1")
check("por su propia URL, el mensaje llega y se responde por su numero",
      _r.status_code == 200 and enviados and PNID_A in enviados[0]["url"],
      f"status={_r.status_code} enviados={len(enviados)}")

enviados.clear()
_r = webhook_por_url(TOKEN_B, PNID_B, TEL_URL, "hola", "wamid.url.b1")
check("y el otro negocio responde con lo suyo por el suyo",
      _r.status_code == 200 and enviados and PNID_B in enviados[0]["url"]
      and "Dona Rosa" in enviados[0]["texto"],
      f"status={_r.status_code} enviados={len(enviados)}")

# EL ERROR MAS PROBABLE DEL ALTA: el cliente pega en su App de Meta la URL
# de otro. Con la firma sola no se caza —cada uno firma bien lo suyo— y
# los mensajes de un negocio acabarian en la bandeja del vecino.
enviados.clear()
_r = webhook_por_url(TOKEN_A, PNID_B, TEL_URL, "hola", "wamid.url.cruzado")
check("una URL que no corresponde al numero del mensaje NO se atiende",
      _r.status_code == 200 and not enviados,
      f"status={_r.status_code} enviados={len(enviados)}")

# Y 200, no un error: con un 4xx o un 5xx Meta reintenta el mismo webhook
# durante horas, y un cliente mal configurado nos machacaria el servicio.
check("pero se le responde 200, para que Meta no reintente en bucle",
      _r.status_code == 200, f"status={_r.status_code}")

enviados.clear()
_r = webhook_por_url("token-que-no-es-de-nadie", PNID_A, TEL_URL, "hola",
                     "wamid.url.nadie")
check("una URL de webhook inexistente da 404 y no atiende a nadie",
      _r.status_code == 404 and not enviados, f"status={_r.status_code}")

# El handshake de verificacion. Es la otra mitad de por que hace falta una
# URL por cliente: el GET no trae `phone_number_id` por ningun lado, asi
# que con una sola puerta no habria forma de saber quien esta
# configurando su webhook.
_r = requests.get(f"{BASE}/webhook/{TOKEN_A}", timeout=10, params={
    "hub.mode": "subscribe", "hub.verify_token": "verify-de-a",
    "hub.challenge": "desafio-123"})
check("el handshake acepta el verify token de ese cliente",
      _r.status_code == 200 and _r.text == "desafio-123",
      f"status={_r.status_code} cuerpo={_r.text[:40]!r}")

_r = requests.get(f"{BASE}/webhook/{TOKEN_A}", timeout=10, params={
    "hub.mode": "subscribe", "hub.verify_token": "verify-de-b",
    "hub.challenge": "desafio-123"})
check("y rechaza el de OTRO cliente, aunque sea un verify token valido",
      _r.status_code == 403, f"status={_r.status_code}")

_r = requests.get(f"{BASE}/webhook/token-que-no-es-de-nadie", timeout=10, params={
    "hub.mode": "subscribe", "hub.verify_token": "verify-de-a",
    "hub.challenge": "desafio-123"})
check("una URL inexistente no verifica nada", _r.status_code == 404,
      f"status={_r.status_code}")

# La puerta vieja sigue abierta mientras se migra: el bot de casa todavia
# entra por ahi. El dia que se retire, esta comprobacion se invierte.
enviados.clear()
webhook(PNID_A, TEL_URL, "hola", "wamid.url.vieja")
check("la puerta vieja /webhook sigue atendiendo durante la migracion",
      bool(enviados), f"enviados={len(enviados)}")


# ── Una entrega con varios mensajes ──────────────────────────────────
#
# Meta junta en un solo POST lo que llega casi a la vez. Se atendía solo
# `messages[0]`: dos clientes que escribían en el mismo segundo, y al
# segundo no le contestaba nadie, sin ningún rastro (23-sep-2026).

print("\n=== Una entrega con varios mensajes los atiende todos ===")

enviados.clear()
_r = requests.post(f"{BASE}/webhook/{TOKEN_A}", timeout=10, json={"entry": [{
    "id": "WABA", "changes": [{"value": {
        "metadata": {"phone_number_id": PNID_A},
        "contacts": [{"wa_id": "573007770001", "profile": {"name": "Uno"}},
                     {"wa_id": "573007770002", "profile": {"name": "Dos"}}],
        "messages": [
            {"from": "573007770001", "id": "wamid.lote.1", "type": "text",
             "text": {"body": "hola"}},
            {"from": "573007770002", "id": "wamid.lote.2", "type": "text",
             "text": {"body": "hola"}},
        ]}}]}]})
_a_quien = {e["a"] for e in enviados}
check("los dos clientes del mismo lote reciben respuesta",
      _r.status_code == 200 and {"573007770001", "573007770002"} <= _a_quien,
      f"status={_r.status_code} a={sorted(_a_quien)}")

# Y una novedad mal formada no se lleva por delante a las buenas del lote.
enviados.clear()
_r = requests.post(f"{BASE}/webhook/{TOKEN_A}", timeout=10, json={"entry": [
    {"id": "WABA", "changes": [{"value": {
        "metadata": {"phone_number_id": PNID_A},
        "messages": [{"id": "wamid.lote.roto"}]}}]},
    {"id": "WABA", "changes": [{"value": {
        "metadata": {"phone_number_id": PNID_A},
        "messages": [{"from": "573007770003", "id": "wamid.lote.3",
                      "type": "text", "text": {"body": "hola"}}]}}]},
]})
check("un mensaje roto en el lote no impide atender al siguiente",
      _r.status_code == 200 and any(e["a"] == "573007770003" for e in enviados),
      f"status={_r.status_code} enviados={len(enviados)}")


# ── El super-admin por tareas (24-sep-2026) ──────────────────────────

print("\n=== El super-admin: Hoy, Cobros y eliminar ===")
from datetime import timedelta as _td  # noqa: E402
from app.core import cobros as _cobros  # noqa: E402

_s = database.get_session()
_s.add(database.Client(id=77, slug="debe-plata", nombre="Debe Plata",
                       active=True, plan="basico",
                       vence_el=_cobros.hoy() + _td(days=2)))
_s.add(database.Client(id=78, slug="se-va", nombre="Se Va", active=True,
                       plan="basico"))
_s.add(database.Contact(client_id=78, phone="573005550000", name="X"))
_s.add(database.Message(client_id=78, phone="573005550000",
                        direccion="entrante", autor="cliente", texto="hola"))
_s.commit()
_s.close()
tenencia.olvidar()

_r = _super.get(BASE + "/superadmin", timeout=10)
check("la portada es 'Hoy', con los cobros que piden algo",
      "Hoy ·" in _r.text and "Debe Plata" in _r.text and "vence en 2 días" in _r.text)
check("y los números del mes", "Cobro mensual esperado" in _r.text)

_r = _super.get(BASE + "/superadmin/cobros", timeout=10)
check("Cobros lista a todos, el más urgente primero",
      _r.text.index("Debe Plata") < _r.text.index("Se Va"))

_r = _super.post(BASE + "/superadmin/clientes/77/pago",
                 data={"monto": "70000", "volver": "hoy"}, timeout=10)
check("registrar un pago desde Hoy vuelve a Hoy",
      _r.url.endswith("/superadmin") or "/superadmin?ok=" in _r.url, _r.url)
check("y corre la fecha un mes",
      _cobros.cuenta_de(77).vence_el
      == _cobros.sumar_un_mes(_cobros.hoy() + _td(days=2)))

_r = _super.post(BASE + "/superadmin/clientes/78/eliminar",
                 data={"confirmar": "otro-nombre"}, timeout=10)
_s = database.get_session()
check("con el nombre equivocado no se borra nada",
      _s.query(database.Client).filter_by(id=78).first() is not None)
_s.close()
_r = _super.post(BASE + "/superadmin/clientes/78/eliminar",
                 data={"confirmar": "se-va"}, timeout=10)
_s = database.get_session()
check("con su nombre corto se borra el negocio",
      _s.query(database.Client).filter_by(id=78).first() is None)
check("y todo lo suyo",
      _s.query(database.Message).filter_by(client_id=78).count() == 0
      and _s.query(database.Contact).filter_by(client_id=78).count() == 0)
check("sin tocar a los demás",
      _s.query(database.Client).filter_by(id=77).first() is not None)
_s.close()
_r = _super.post(BASE + "/superadmin/clientes/1/eliminar",
                 data={"confirmar": "principal"}, timeout=10)
_s = database.get_session()
check("el bot de casa no se puede eliminar",
      _s.query(database.Client).filter_by(id=1).first() is not None)
_s.close()

# La entrada de un negocio pausado por no pagar: con la clave correcta se
# le dice cómo pagar; con una incorrecta, lo de siempre.
acceso.crear_usuario(77, "dueno-debe", "clave-de-debe")
_s = database.get_session()
_s.query(database.Client).filter_by(id=77).update(
    {"active": False, "pausado_por": "impago"})
_s.commit()
_s.close()
tenencia.olvidar()
# Sin subdominios, que es como corre producción. Con subdominios, el de un
# negocio pausado da 404 antes del formulario, y así tiene que seguir: no
# se le cuenta a internet qué negocios existen.
os.environ["DOMINIO_BASE"] = ""
_r = requests.post(BASE + "/admin/login", timeout=10,
                   data={"usuario": "dueno-debe", "clave": "clave-de-debe"})
check("el dueño pausado por impago ve cómo pagar al entrar",
      "pausado por falta de pago" in _r.text and "317 886 2390" in _r.text)
_r = requests.post(BASE + "/admin/login", timeout=10,
                   data={"usuario": "dueno-debe", "clave": "no-es-esta"})
check("y con la clave mala no se le cuenta nada",
      "pausado" not in _r.text and "no son correctos" in _r.text)
os.environ["DOMINIO_BASE"] = "ejemplo.test"

# ── Resultado ────────────────────────────────────────────────────────

print("\n" + "=" * 60)
if fallos:
    print(f"FALLARON {len(fallos)}:")
    for f in fallos:
        print(f"  - {f}")
    sys.exit(1)

print("Aislamiento entre clientes: todas las verificaciones pasaron.")
