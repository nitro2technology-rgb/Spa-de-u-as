"""
PRUEBAS DEL PANEL DE ATENCIÓN MANUAL
=====================================
Levanta el servidor de verdad en un puerto suelto y ejercita el panel por
HTTP, igual que lo haría un navegador: login, bandeja, hilo de la
conversación, respuesta manual y devolución al bot.

Va aparte de test_regresion.py porque necesita un servidor corriendo. No
envía nada a WhatsApp ni escribe en Google: esas funciones se sustituyen
antes de arrancar, y la base es temporal.

    python tests/test_panel.py
"""
import json, os, sys, tempfile, threading, time

# La raíz del proyecto es la carpeta que contiene tests/, no tests/ misma:
# desde ahí se importa el paquete app y ahí espera el .env la configuración.
PROY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROY)
os.chdir(PROY)
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "panel.db").replace("\\", "/")
os.environ["ADMIN_API_KEY"] = "clave-panel-prueba"

import requests, uvicorn
from app import config
from app.core import database, message_log, push, tenencia
from app.bot import whatsapp_client, bot_logic
from app.integrations import sheets_service

# Nada sale a Meta ni a Google
class FalsaResp:
    status_code = 200
    def json(self): return {"ok": True}

enviados = []
def _fake_text(to, text, autor="bot"):
    enviados.append((to, text, autor))
    message_log.registrar(to, "saliente", autor, text)
    return FalsaResp()

whatsapp_client.send_text_message = _fake_text
whatsapp_client.send_button_message = lambda to, t, b: (enviados.append((to, t, "bot")),
    message_log.registrar(to, "saliente", "bot", t), FalsaResp())[-1]
whatsapp_client.send_list_message = lambda to, t, b, o, ti="x": (
    enviados.append((to, t, "bot")),
    message_log.registrar(to, "saliente", "bot", t), FalsaResp())[-1]
sheets_service.registrar_lead = lambda *a, **k: True
sheets_service.asegurar_pestanas = lambda *a, **k: True

from app import main


def pide_clave(texto: str) -> bool:
    """
    Si esa respuesta es la pantalla de entrada.

    Se mira el formulario, no el rotulo: los textos de la pantalla
    cambian con cada rediseno y no vale la pena que eso rompa nueve
    pruebas que hablan de sesiones caducadas.
    """
    return 'name="clave"' in texto and 'action="/admin/login"' in texto


threading.Thread(target=lambda: uvicorn.run(main.app, port=8321, log_level="error"),
                 daemon=True).start()

BASE = "http://127.0.0.1:8321"
for _ in range(80):
    try:
        requests.get(BASE + "/", timeout=1); break
    except Exception: time.sleep(0.25)

fallos = []
def check(n, c, extra=""):
    linea = f"  {'[OK]' if c else '[X] '} {n}{'  ' + extra if extra else ''}"
    try:
        print(linea)
    except UnicodeEncodeError:
        # La consola de Windows usa cp1252 y no sabe imprimir emojis. Los
        # textos del bot llevan varios, así que si aparecen en el detalle
        # de una verificación reventaría la suite entera por un print.
        # (Mismo apaño que en test_regresion.py.)
        codificacion = sys.stdout.encoding or "ascii"
        print(linea.encode(codificacion, "replace").decode(codificacion))
    if not c: fallos.append(n)

TEL = "573001112233"

# El listado lo pinta el navegador, desde un JSON que el servidor deja
# embebido en la página. Estas pruebas no ejecutan JavaScript, así que
# comprueban ese JSON: es el contrato entre las dos partes.
import re  # noqa: E402


def listado_de(texto_html):
    """Las conversaciones que la página le entrega al navegador."""
    trozo = re.search(r'id="listado-inicial"[^>]*>(.*?)</script>',
                      texto_html, re.S)
    return json.loads(trozo.group(1)) if trozo else None


def fila_de(texto_html, phone):
    return next((c for c in (listado_de(texto_html) or []) if c["phone"] == phone), None)

print("\n=== Sin sesión ===")
r = requests.get(f"{BASE}/admin/inbox")
check("la bandeja pide la clave si no hay sesión",
      pide_clave(r.text) or "password" in r.text)
check("no filtra ninguna conversación", TEL not in r.text)

print("\n=== Login ===")
# Esta suite corre SIN DOMINIO_BASE, o sea con todos los negocios en la
# misma dirección. Ahí el formulario pide también el negocio — salvo que se
# deje vacío, que es el atajo del cliente por defecto (el dueño del bot),
# para que su forma de entrar no cambie por ser el único.
s = requests.Session()
r = s.post(f"{BASE}/admin/login", data={"clave": "incorrecta"})
check("rechaza la clave incorrecta", "no son correctos" in r.text)
check("no deja cookie de sesión con clave mala", "panel_nitro" not in s.cookies)

# Y no dice CUÁL de las dos cosas falló: distinguirlo permitiría averiguar
# qué negocios son clientes nuestros probando nombres uno a uno.
r = s.post(f"{BASE}/admin/login",
           data={"negocio": "no-existe-este", "clave": "clave-panel-prueba"})
check("un negocio que no existe da el mismo error que una clave mala",
      "no son correctos" in r.text and "panel_nitro" not in s.cookies)

r = s.post(f"{BASE}/admin/login", data={"clave": "clave-panel-prueba"})
check("acepta la clave correcta y entra a la bandeja",
      r.status_code == 200 and "Conversaciones" in r.text)
check("deja la cookie de sesión", "panel_nitro" in s.cookies)

# El HTML del formulario, no solo su respuesta. Estas pruebas envían por
# HTTP y se saltan la validación del navegador, así que un `required` de
# más no se nota aquí pero deja al dueño sin poder pulsar Entrar. Pasó.
_entrada = requests.get(f"{BASE}/admin/login").text
_fuentes = requests.get(f"{BASE}/estaticos/fuentes.css").text
_casilla = [l for l in _entrada.splitlines() if 'name="usuario"' in l]
check("el formulario pide el usuario", bool(_casilla))
check("y esa casilla NO es obligatoria: vacía entra el cliente por defecto",
      _casilla and "required" not in _casilla[0], str(_casilla)[:90])
check("y ya no pide el negocio", 'name="negocio"' not in _entrada)

# Escribiendo el nombre del negocio se llega al mismo sitio, y se perdona
# lo que se perdona sin ambigüedad: mayúsculas, tildes y espacios.
for _escrito in ("principal", "PRINCIPAL", " Principál "):
    _otra = requests.Session()
    _r = _otra.post(f"{BASE}/admin/login",
                    data={"negocio": _escrito, "clave": "clave-panel-prueba"})
    check(f"entra escribiendo el negocio como {_escrito!r}",
          "panel_nitro" in _otra.cookies, f"status={_r.status_code}")

print("\n=== Caducidad de la sesión ===")
from app.web import admin_ui   # noqa: E402  (para el freno de intentos)
from app.core import acceso    # noqa: E402  (para forjar pases a mano)

check("la cookie NO guarda la clave de administración",
      "clave-panel-prueba" not in s.cookies["panel_nitro"])
check("y sí dice de qué negocio es",
      s.cookies["panel_nitro"].startswith(f"{acceso.VERSION}:{config.CLIENTE_POR_DEFECTO}:"))


def con_pase(pase):
    """Una sesión limpia que lleva el pase indicado."""
    otra = requests.Session()
    otra.cookies.set("panel_nitro", pase, domain="127.0.0.1")
    return otra


def pase_a_mano(absoluto_en, inactividad_en, client_id=None, user_id=0):
    """Pase firmado de verdad, pero con los plazos (y el dueño) que digamos."""
    ahora = time.time()
    cuerpo = (f"{acceso.VERSION}:{client_id or config.CLIENTE_POR_DEFECTO}:{user_id}:"
              f"{ahora + absoluto_en:.0f}:{ahora + inactividad_en:.0f}")
    return f"{cuerpo}:{acceso.firmar(cuerpo)}"


r = con_pase(pase_a_mano(3600, -10)).get(f"{BASE}/admin/inbox")
check("un pase pasado de inactividad no entra", pide_clave(r.text))
check("y explica que caducó", "caducó" in r.text)

r = con_pase(pase_a_mano(-10, 3600)).get(f"{BASE}/admin/inbox")
check("el tope absoluto manda aunque haya actividad reciente",
      pide_clave(r.text))

# Un pase de otro negocio, firmado con el MISMO secreto del servidor: es
# válido criptográficamente y aun así no puede abrir este panel.
r = con_pase(pase_a_mano(3600, 3600, client_id=99)).get(f"{BASE}/admin/inbox")
check("un pase de otro inquilino no abre este panel",
      pide_clave(r.text))

# Estirar el plazo desde el navegador tiene que romper la firma.
_v, _cli, _usr, _abs, _inact, _firma = s.cookies["panel_nitro"].split(":")
r = con_pase(f"{_v}:{_cli}:{_usr}:{_abs}:{float(_inact) + 99999:.0f}:{_firma}"
             ).get(f"{BASE}/admin/inbox")
check("no se puede estirar el plazo manipulando la cookie",
      pide_clave(r.text))

# El formato viejo no llevaba inquilino. Que no se cuele es lo que evita
# que una cookie emitida antes de la Fase 3 siga valiendo.
r = con_pase(f"{_abs}:{_inact}:{_firma}").get(f"{BASE}/admin/inbox")
check("un pase del formato anterior ya no vale",
      pide_clave(r.text))

r = con_pase("basura").get(f"{BASE}/admin/inbox")
check("un pase con formato inválido no entra", pide_clave(r.text))

# Lo que haces tú renueva; lo que el panel consulta de fondo, no. Si las
# consultas de fondo renovaran, una pestaña olvidada no caducaría nunca.
check("abrir la bandeja renueva la sesión",
      "panel_nitro" in s.get(f"{BASE}/admin/inbox").headers.get("set-cookie", ""))
check("las consultas de fondo NO renuevan la sesión",
      "panel_nitro" not in
      s.get(f"{BASE}/admin/api/conversaciones").headers.get("set-cookie", ""))

print("\n=== Freno a los intentos de clave ===")
bruta = requests.Session()
for _ in range(config.PANEL_MAX_INTENTOS_LOGIN):
    bruta.post(f"{BASE}/admin/login", data={"clave": "a-ver-si-acierto"})
r = bruta.post(f"{BASE}/admin/login", data={"clave": "a-ver-si-acierto"})
check("bloquea tras demasiados intentos fallidos", "Demasiados intentos" in r.text)
r = bruta.post(f"{BASE}/admin/login", data={"clave": "clave-panel-prueba"})
check("y el bloqueo también aplica a la clave correcta",
      "Demasiados intentos" in r.text)

# Se limpia el contador: si no, el resto de la suite entra desde la misma
# IP y se quedaría bloqueada.
admin_ui._FRENO.clear()
check("tras limpiar el bloqueo se puede volver a entrar",
      "Conversaciones" in bruta.post(f"{BASE}/admin/login",
                                     data={"clave": "clave-panel-prueba"}).text)

print("\n=== Con una conversación real del bot ===")
n = 0
def msg(text=None, phone=TEL, button_id=None, list_id=None):
    """
    Un mensaje entrante, saltándose el webhook.

    El `with` no es decoración: en producción el inquilino lo fija el
    webhook antes de llamar al bot, y aquí se entra por debajo. Sin él, el
    aviso en vivo se descarta —no hay a qué panel entregarlo— y la prueba
    del canal SSE falla sin decir por qué. Ver app/core/eventos.py.
    """
    global n; n += 1
    with tenencia.usar(config.CLIENTE_POR_DEFECTO):
        bot_logic.handle_incoming_message(phone, "text", text=text, button_id=button_id,
                                          list_id=list_id, message_id=f"p.{n}")

msg("hola"); msg("Camila")
r = s.get(f"{BASE}/admin/inbox")
_fila = fila_de(r.text, TEL)
check("la conversación aparece en la bandeja",
      _fila is not None and _fila["name"] == "Camila", str(_fila)[:80])

r = s.get(f"{BASE}/admin/chat/{TEL}")
check("se ve lo que escribió el cliente", "hola" in r.text)
check("se ve lo que respondió el bot", "Bienvenido" in r.text)
check("la ventana de 24h aparece abierta", "Puedes responder libremente" in r.text)
check("el bot figura como activo en ese chat", "El bot está respondiendo aquí" in r.text)

print("\n=== Contexto: de qué servicio viene y por dónde pasó ===")
# Sin esto hay que leerse el hilo entero para saber de qué venía hablando
# quien te escribe.
check("si aún no eligió servicio, lo dice en vez de dejarlo en blanco",
      "Todavía no ha elegido" in r.text)

msg(button_id="opt_powerbi"); msg(button_id="powerbi_precios")
r = s.get(f"{BASE}/admin/chat/{TEL}")
check("el hilo muestra el servicio que eligió", "Tablero en Power BI" in r.text)
check("y el recorrido que lleva", "Vio precios" in r.text)

r = s.get(f"{BASE}/admin/inbox")
check("la bandeja etiqueta la conversación con su servicio",
      fila_de(r.text, TEL)["servicio"] == "Tablero en Power BI")

r = s.get(f"{BASE}/admin/api/conversaciones")
_conv = next(c for c in r.json()["conversaciones"] if c["phone"] == TEL)
check("el listado que se refresca solo también trae el servicio",
      _conv["servicio"] == "Tablero en Power BI", str(_conv["servicio"]))

print("\n=== Responder a mano ===")
antes = len(enviados)
r = s.post(f"{BASE}/admin/chat/{TEL}", data={"texto": "Hola Camila, te ayudo yo."})
check("el envío responde bien", r.status_code == 200)
check("se envió por WhatsApp", len(enviados) == antes + 1)
check("se envió marcado como escrito por un humano",
      enviados[-1][2] == "humano" and enviados[-1][0] == TEL)

contacto = bot_logic.listar_contactos(solo_humanos=True)
check("al responder, la conversación queda atendida por humano",
      any(c["phone"] == TEL for c in contacto))

r = s.get(f"{BASE}/admin/chat/{TEL}")
check("la respuesta manual se ve en el hilo", "te ayudo yo" in r.text)
check("el panel avisa que el bot está callado", "El bot no responde aquí" in r.text)

print("\n=== El bot ya no contesta ahí ===")
antes = len(enviados)
msg("gracias!")
check("un mensaje del cliente ya no dispara al bot", len(enviados) == antes)
r = s.get(f"{BASE}/admin/chat/{TEL}")
check("pero el mensaje sí queda en el hilo", "gracias!" in r.text)

print("\n=== Devolver al bot ===")
r = s.post(f"{BASE}/admin/chat/{TEL}/devolver")
check("el panel confirma la devolución", "vuelve a responder" in r.text)
check("el contacto deja de estar atendido por humano",
      not any(c["phone"] == TEL for c in bot_logic.listar_contactos(solo_humanos=True)))
antes = len(enviados)
msg("hola otra vez")
check("el bot vuelve a responder", len(enviados) > antes)

print("\n=== Validaciones ===")
r = s.post(f"{BASE}/admin/chat/{TEL}", data={"texto": "   "})
check("no deja enviar un mensaje vacío", "Escribe un mensaje" in r.text)

from app.web import admin_ui  # noqa: E402
antes = len(enviados)
r = s.post(f"{BASE}/admin/chat/{TEL}", data={"texto": "x" * (admin_ui.LIMITE_WHATSAPP + 1)})
check("rechaza un mensaje más largo que el máximo de WhatsApp",
      "máximo de WhatsApp" in r.text and len(enviados) == antes,
      f"enviados: {antes} -> {len(enviados)}")

largo = "Hola, te explico con detalle. " * 100          # ~3.000 caracteres
antes = len(enviados)
r = s.post(f"{BASE}/admin/chat/{TEL}", data={"texto": largo})
check("sí deja enviar un mensaje largo dentro del límite",
      len(enviados) == antes + 1 and enviados[-1][1] == largo.strip(),
      f"{len(largo)} caracteres")

print("\n=== Enviar sin recargar la página ===")
# El arreglo de la cajita que no se vaciaba: el panel manda por aquí y
# limpia el campo en el acto, sin esperar a que Meta conteste.
antes = len(enviados)
r = s.post(f"{BASE}/admin/api/chat/{TEL}/enviar", json={"texto": "sin recargar"})
check("el envío de fondo manda el mensaje",
      r.status_code == 200 and r.json().get("ok") is True
      and len(enviados) == antes + 1 and enviados[-1][1] == "sin recargar",
      f"{r.status_code} {r.text[:80]}")

antes = len(enviados)
r = s.post(f"{BASE}/admin/api/chat/{TEL}/enviar", json={"texto": "   "})
check("y rechaza el mensaje vacío en JSON, sin redirigir",
      r.status_code == 400 and r.json().get("ok") is False
      and "Escribe un mensaje" in r.json().get("error", "")
      and len(enviados) == antes,
      f"{r.status_code} {r.text[:80]}")

antes = len(enviados)
r = s.post(f"{BASE}/admin/api/chat/{TEL}/enviar",
           json={"texto": "x" * (admin_ui.LIMITE_WHATSAPP + 1)})
check("y el pasado de largo también, con el motivo explicado",
      r.status_code == 400 and "máximo de WhatsApp" in r.json().get("error", "")
      and len(enviados) == antes,
      f"{r.status_code} {r.text[:80]}")

# Es un endpoint de escritura abierto a internet: sin sesión, nada.
r = requests.post(f"{BASE}/admin/api/chat/{TEL}/enviar", json={"texto": "cuela"})
check("sin sesión no deja enviar", r.status_code == 401, f"{r.status_code}")

# Lo que de verdad pedía el arreglo: vaciar ANTES de salir a la red.
def guion_de(url):
    """
    El JavaScript que ejecuta una pantalla del panel.

    Ya no viene dentro del HTML: son archivos (`/estaticos/panel-*.js`).
    Se piden todos y se juntan, que es como se ejecutan en el navegador —
    comparten ambito y corren en orden.
    """
    pagina = s.get(url).text
    partes = [requests.get(BASE + u, timeout=10).text
              for u in re.findall(r'src="(/estaticos/panel-[^"]*)"', pagina)]
    return chr(10).join(partes)


guion = guion_de(f"{BASE}/admin/chat/{TEL}")
check("la cajita se vacía antes de mandar, no al confirmarse",
      "area.value = ''" in guion
      and guion.index("area.value = ''") < guion.index("enviar(texto)"))
check("y si falla, el texto vuelve a la cajita", "devolverTexto" in guion)

print("\n=== Estado de atención ===")
ESTADO_TEL = "573009998877"
msg("hola", phone=ESTADO_TEL)

r = s.post(f"{BASE}/admin/api/chat/{ESTADO_TEL}/estado", json={"estado": "urgente"})
check("marca la conversación como urgente",
      r.status_code == 200 and r.json().get("ok") is True,
      f"{r.status_code} {r.text[:80]}")

# Lo que de verdad se pidió: que se vea en el HISTORIAL, no en el chat.
check("y el listado lo lleva, que es donde sirve",
      fila_de(s.get(f"{BASE}/admin/inbox").text, ESTADO_TEL)["estado_atencion"] == "urgente")
check("el refresco del listado también",
      [c["estado_atencion"] for c in
       s.get(f"{BASE}/admin/api/conversaciones").json()["conversaciones"]
       if c["phone"] == ESTADO_TEL] == ["urgente"])

for estado in ("esperando", "terminado"):
    r = s.post(f"{BASE}/admin/api/chat/{ESTADO_TEL}/estado", json={"estado": estado})
    check(f"se puede cambiar a {estado}", r.status_code == 200
          and fila_de(s.get(f"{BASE}/admin/inbox").text,
                      ESTADO_TEL)["estado_atencion"] == estado)

r = s.post(f"{BASE}/admin/api/chat/{ESTADO_TEL}/estado", json={"estado": ""})
check("y se puede quitar la marca",
      r.status_code == 200
      and fila_de(s.get(f"{BASE}/admin/inbox").text, ESTADO_TEL)["estado_atencion"] == "")

# Un estado inventado no puede entrar en la base: el menú se pinta desde
# la misma lista que valida el servidor, pero el endpoint está abierto.
r = s.post(f"{BASE}/admin/api/chat/{ESTADO_TEL}/estado", json={"estado": "inventado"})
check("un estado que no existe se rechaza", r.status_code == 400, f"{r.status_code}")

r = requests.post(f"{BASE}/admin/api/chat/{ESTADO_TEL}/estado", json={"estado": "urgente"})
check("sin sesión no deja marcar", r.status_code == 401, f"{r.status_code}")

# La cabecera del hilo: flecha sola para volver, sin la palabra.
_hilo = s.get(f"{BASE}/admin/chat/{ESTADO_TEL}").text
check("el botón de volver es solo la flecha",
      'class="volver solo-movil"' in _hilo and "← Conversaciones" not in _hilo)
check("y el menú ofrece los tres estados",
      all(f'data-estado="{e}"' in _hilo for e in ("urgente", "esperando", "terminado")))

# ── La ficha, desde un teléfono ──────────────────────────────────────
#
# Por debajo de 1200px la ficha deja de caber como cuarta columna. Hasta
# el 20-ago-2026 ahí desaparecía y punto: las etiquetas y la nota interna
# se veían en la lista y en la agenda, y no había ninguna forma de
# añadirlas si no era desde un computador. Ahora el botón de la cabecera
# la trae como panel encima, con el MISMO HTML — por eso lo que se
# comprueba es que las tres piezas viajan y que la hoja las conoce.
check("la cabecera trae el botón que abre la ficha",
      'id="ver-ficha"' in _hilo and 'aria-controls="ficha-contacto"' in _hilo)
check("y el panel tiene con qué cerrarse",
      "data-cerrar-ficha" in _hilo and "data-velo-ficha" in _hilo)
check("la ficha sigue siendo UNA, no una copia para el teléfono",
      _hilo.count('id="ficha-contacto"') == 1 and _hilo.count("data-nota") == 1)

print("\n=== Eliminar un chat ===")
BORRAR_TEL = "573009991122"
msg("hola", phone=BORRAR_TEL)
msg("soy Pasajero", phone=BORRAR_TEL)

r = requests.post(f"{BASE}/admin/api/chat/{BORRAR_TEL}/borrar")
check("sin sesión no deja borrar", r.status_code == 401, f"{r.status_code}")

r = s.post(f"{BASE}/admin/api/chat/{BORRAR_TEL}/borrar")
borrado = r.json()
check("borra el chat y dice cuánto se llevó",
      r.status_code == 200 and borrado.get("ok") is True
      and borrado.get("mensajes", 0) > 0,
      f"{r.status_code} {r.text[:100]}")

_ses = database.get_session()
check("el contacto ya no está en la base",
      _ses.query(database.Contact).filter_by(phone=BORRAR_TEL).first() is None)
check("ni le queda un solo mensaje",
      _ses.query(database.Message).filter_by(phone=BORRAR_TEL).count() == 0)
_ses.close()

check("y desaparece de la bandeja",
      not any(c["phone"] == BORRAR_TEL for c in
              s.get(f"{BASE}/admin/api/conversaciones").json()["conversaciones"]))

r = s.post(f"{BASE}/admin/api/chat/{BORRAR_TEL}/borrar")
check("borrarlo dos veces avisa en vez de reventar", r.status_code == 404,
      f"{r.status_code}")

print("\n=== Avisos al celular (push) ===")
from app.core import push as _push  # noqa: E402

# Sin claves VAPID el panel no debe ofrecer nada: pedir el permiso y no
# poder entregar el aviso es peor que no ofrecerlo.
_pub_original = config.VAPID_PUBLIC_KEY
config.VAPID_PUBLIC_KEY = ""
check("sin claves configuradas no se ofrece el botón",
      s.get(f"{BASE}/admin/api/push/clave").json()["clave"] == ""
      and not _push.configurado())

config.VAPID_PUBLIC_KEY = "clave-publica-de-prueba"
config.VAPID_PRIVATE_KEY = "clave-privada-de-prueba"
check("con claves, el panel recibe la pública",
      s.get(f"{BASE}/admin/api/push/clave").json()["clave"] == "clave-publica-de-prueba")

BUZON = "https://push.example.com/buzon/abc123"
r = s.post(f"{BASE}/admin/api/push/suscribir",
           json={"endpoint": BUZON, "keys": {"p256dh": "llave1", "auth": "llave2"}})
check("apunta el dispositivo", r.status_code == 200 and r.json().get("ok") is True,
      f"{r.status_code} {r.text[:80]}")
check("y queda uno solo en la lista",
      [x["endpoint"] for x in database.suscripciones_push()] == [BUZON])

# El navegador rota las claves y vuelve a suscribirse con el mismo buzón:
# eso tiene que refrescar, no duplicar.
s.post(f"{BASE}/admin/api/push/suscribir",
       json={"endpoint": BUZON, "keys": {"p256dh": "nueva1", "auth": "nueva2"}})
_subs = database.suscripciones_push()
check("resuscribirse refresca las claves en vez de duplicar",
      len(_subs) == 1 and _subs[0]["keys"]["p256dh"] == "nueva1",
      f"{len(_subs)} suscripciones")

r = requests.post(f"{BASE}/admin/api/push/suscribir",
                  json={"endpoint": "x", "keys": {"p256dh": "a", "auth": "b"}})
check("sin sesión no deja apuntarse", r.status_code == 401, f"{r.status_code}")

r = s.post(f"{BASE}/admin/api/push/baja", json={"endpoint": BUZON})
check("se puede dar de baja",
      r.json().get("ok") is True and database.suscripciones_push() == [])

# Un buzón muerto (410) se limpia solo; una caída pasajera no borra nada.
database.guardar_suscripcion_push(BUZON, "a", "b")


class _Respuesta:
    def __init__(self, codigo):
        self.status_code = codigo


_error_muerto = _push.WebPushException("se fue")
_error_muerto.response = _Respuesta(410)
_push._limpiar_si_murio(BUZON, _error_muerto)
check("un buzón muerto se da de baja solo", database.suscripciones_push() == [])

database.guardar_suscripcion_push(BUZON, "a", "b")
_error_pasajero = _push.WebPushException("vuelve luego")
_error_pasajero.response = _Respuesta(503)
_push._limpiar_si_murio(BUZON, _error_pasajero)
check("pero una caída pasajera no lo borra",
      len(database.suscripciones_push()) == 1)
database.borrar_suscripcion_push(BUZON)

config.VAPID_PUBLIC_KEY = _pub_original
config.VAPID_PRIVATE_KEY = ""

print("\n=== Los dos paneles ===")
msg("hola", phone="573001112255"); msg("Otro Cliente", phone="573001112255")
r = s.get(f"{BASE}/admin/chat/{TEL}")
check("la conversación trae el listado al lado", 'class="col-lista"' in r.text)
check("y el hilo en su propio panel", 'class="panel-chat"' in r.text)

# En el telefono no caben las cuatro columnas y hay que elegir cual se
# queda. Se eligio mal una vez: la bandeja escondia el rail Y la lista, y
# en un telefono solo quedaba el cartel de "elige una conversacion" sin
# ninguna forma de elegirla. Las cuatro suites en verde y el panel
# inservible en un movil, que es desde donde se responde casi siempre.
check("la conversacion se marca en el cuerpo, y la bandeja no",
      'class="completa hay-hilo"' in r.text
      and "hay-hilo" not in s.get(f"{BASE}/admin/inbox").text)
_otra = fila_de(r.text, "573001112255")
check("desde el hilo se ven las otras conversaciones",
      _otra is not None and _otra["name"] == "Otro Cliente", str(_otra)[:70])
_guion_hilo = guion_de(f"{BASE}/admin/chat/{TEL}")
check("la conversación abierta queda marcada",
      "c.phone === telefono ? ' activa'" in _guion_hilo
      and fila_de(r.text, TEL) is not None)
check("el hilo tiene su propia caja con scroll", 'id="chat"' in r.text)
check("el scroll es el de la caja, no el de la página",
      "caja.scrollTop = caja.scrollHeight" in _guion_hilo
      and "window.scrollTo" not in _guion_hilo)
# Solo la flecha, sin la palabra: en el celular la cabecera tiene que
# dejarle el ancho al nombre y al recorrido.
check("en el celular hay flecha para volver al listado",
      'class="volver solo-movil" href="/admin/inbox"' in r.text
      and "← Conversaciones" not in r.text)
check("la bandeja suelta sigue existiendo (vista de celular)",
      s.get(f"{BASE}/admin/inbox").status_code == 200)

print("\n=== El hilo no se recarga encima de lo que escribes ===")
r = s.get(f"{BASE}/admin/chat/{TEL}")
check("el hilo NO usa la recarga automática del navegador",
      'http-equiv="refresh"' not in r.text)
check("Enter envía el mensaje", "requestSubmit" in _guion_hilo)
check("Shift+Enter hace salto de línea", "shiftKey" in _guion_hilo)
check("guarda un borrador por si acaso", "sessionStorage" in _guion_hilo)
check("no recarga la página nunca", "location.reload" not in _guion_hilo)

print("\n=== Canal en vivo (el servidor empuja los mensajes) ===")
check("el hilo abre el canal en vivo",
      "EventSource" in _guion_hilo and "/admin/api/stream" in _guion_hilo)
check("arranca desde el id del último mensaje ya pintado",
      "data-ultimo-id=" in r.text)
check("no te mueve la vista si estás leyendo hacia arriba",
      "pegadoAlFondo" in _guion_hilo)
check("reacciona si la sesión caduca con la pestaña abierta",
      "caducada" in _guion_hilo)

r_inbox = s.get(f"{BASE}/admin/inbox")
_guion_bandeja = guion_de(f"{BASE}/admin/inbox")
check("la bandeja también escucha el canal", "EventSource" in _guion_bandeja)
check("y ya no recarga la página entera",
      'http-equiv="refresh"' not in r_inbox.text)

# Plan B: si el canal en vivo falla, se vuelve a preguntar por turnos.
check("queda el respaldo por si el canal no funciona",
      "buscarNuevos" in _guion_hilo and "/admin/api/chat/" in _guion_hilo
      and "arrancarRespaldo" in _guion_hilo)

check("el canal exige sesión",
      requests.get(f"{BASE}/admin/api/stream").status_code == 401)


def buscar_evento(respuesta, texto, segundos=8):
    """
    Espera hasta encontrar en el canal un mensaje con ese texto.

    El canal lleva los mensajes de TODAS las conversaciones (el listado
    lateral también tiene que enterarse), así que hay que buscar el
    nuestro entre lo que llegue, no quedarse con el primero.
    """
    limite = time.time() + segundos
    try:
        for linea in respuesta.iter_lines(decode_unicode=True):
            if time.time() > limite:
                return None
            if linea and linea.startswith("data:"):
                evento = json.loads(linea[len("data:"):].strip())
                if evento.get("texto") == texto:
                    return evento
    except Exception:
        return None
    return None


# a) Lo que se perdió entre que la página se pintó y el canal conectó.
#    Se manda ANTES de conectar, así que no hay carrera posible.
_ultimo_antes = max(m["id"] for m in
                    s.get(f"{BASE}/admin/api/chat/{TEL}?desde=0").json()["mensajes"])
msg("mensaje que cae en el hueco")
flujo = s.get(f"{BASE}/admin/api/stream?desde={_ultimo_antes}", stream=True, timeout=10)
evento = buscar_evento(flujo, "mensaje que cae en el hueco")
flujo.close()
check("al conectar recupera lo que se perdió en el hueco",
      evento is not None, str(evento)[:70])

# b) Empuje en vivo: el canal ya está abierto cuando llega el mensaje.
flujo = s.get(f"{BASE}/admin/api/stream?desde=0", stream=True, timeout=10)
time.sleep(0.4)   # que al servidor le dé tiempo a suscribir este canal
threading.Timer(0.2, lambda: msg("mensaje empujado en vivo")).start()
evento = buscar_evento(flujo, "mensaje empujado en vivo")
flujo.close()
check("empuja el mensaje en cuanto llega, sin que el panel pregunte",
      evento is not None, str(evento)[:70])
check("y dice de qué conversación es y quién habló",
      evento is not None and evento["phone"] == TEL and evento["quien"] == "cliente")

print("\n=== El listado ya no consulta una vez por contacto ===")
from sqlalchemy import event as _ev   # noqa: E402

# Con dos contactos cualquier implementación da un número parecido. Hacen
# falta unos cuantos para que se note la diferencia entre "unas pocas
# consultas" y "dos por cada contacto".
for _i in range(10):
    msg("hola", phone=f"5730077700{_i:02d}")

_consultas = []
_ev.listen(database.engine, "before_cursor_execute",
           lambda *a: _consultas.append(1))

_consultas.clear(); message_log.conversaciones(limite=1)
_con_uno = len(_consultas)
_consultas.clear(); message_log.conversaciones(limite=50)
_con_todos = len(_consultas)
_cuantos = len(message_log.conversaciones(limite=50))

check("el número de consultas no crece con los contactos",
      _con_uno == _con_todos,
      f"1 contacto: {_con_uno} consultas / {_cuantos} contactos: {_con_todos}")
check("y son unas pocas, no dos por contacto", _con_todos <= 5,
      f"{_con_todos} consultas")

_consultas.clear(); message_log.conversacion_info(TEL)
check("los datos de una sola conversación no piden el listado entero",
      len(_consultas) <= 3, f"{len(_consultas)} consultas")

# Los endpoints de datos
r = s.get(f"{BASE}/admin/api/chat/{TEL}?desde=0")
datos = r.json()
check("el endpoint de mensajes responde", r.status_code == 200)
check("devuelve los mensajes del hilo", len(datos["mensajes"]) > 0)
check("cada mensaje trae id, quién lo dijo, texto y hora",
      all({"id", "quien", "texto", "hora"} <= set(m) for m in datos["mensajes"]))
check("distingue cliente / bot / humano",
      {"cliente", "bot", "humano"} >= {m["quien"] for m in datos["mensajes"]})
check("informa del estado de la ventana y del takeover",
      "ventana_abierta" in datos and "atendido_por_humano" in datos)

ultimo = max(m["id"] for m in datos["mensajes"])
r = s.get(f"{BASE}/admin/api/chat/{TEL}?desde={ultimo}")
check("con 'desde' del último id no devuelve nada",
      r.json()["mensajes"] == [], str(r.json()["mensajes"])[:60])

antes = len(enviados)
s.post(f"{BASE}/admin/chat/{TEL}", data={"texto": "mensaje nuevo de prueba"})
r = s.get(f"{BASE}/admin/api/chat/{TEL}?desde={ultimo}")
nuevos = r.json()["mensajes"]
check("tras enviar, aparece solo el mensaje nuevo",
      len(nuevos) == 1 and nuevos[0]["texto"] == "mensaje nuevo de prueba"
      and nuevos[0]["quien"] == "humano", str(nuevos)[:90])

r = s.get(f"{BASE}/admin/api/conversaciones")
check("el endpoint del listado responde",
      r.status_code == 200 and len(r.json()["conversaciones"]) > 0)

sin_sesion = requests.Session()
check("los endpoints en vivo exigen sesión",
      sin_sesion.get(f"{BASE}/admin/api/chat/{TEL}").status_code == 401
      and sin_sesion.get(f"{BASE}/admin/api/conversaciones").status_code == 401)

print("\n=== Escapado de HTML (mensaje malicioso del cliente) ===")
msg("<script>alert('xss')</script>", phone="573001112244")
r = s.get(f"{BASE}/admin/chat/573001112244")
check("el HTML del cliente se muestra escapado, no se ejecuta",
      "<script>alert" not in r.text and "&lt;script&gt;" in r.text)

print("\n=== Ventana de 24 horas cerrada ===")
from datetime import timedelta
ses = database.get_session()
for m in ses.query(database.Message).filter_by(phone=TEL, direccion="entrante").all():
    m.created_at = database.ahora_utc() - timedelta(hours=30)
ses.commit(); ses.close()
r = s.get(f"{BASE}/admin/chat/{TEL}")
check("avisa que la ventana se cerró", "más de 24 horas" in r.text)
# Se busca la clase del formulario y no '<textarea' a secas: el campo de
# notas internas vive en la cabecera y está siempre, se pueda responder o
# no. Tampoco vale 'name="texto"', que aparece dentro del JavaScript.
check("y esconde el formulario de respuesta", 'class="responder"' not in r.text)
check("pero el estado se puede seguir marcando", 'data-estado="urgente"' in r.text)
r = s.get(f"{BASE}/admin/inbox")
check("la bandeja marca la ventana cerrada",
      fila_de(r.text, TEL)["ventana_abierta"] is False)

print("\n=== Política de privacidad (pública) ===")
sin_clave = requests.Session()
r = sin_clave.get(f"{BASE}/privacidad")
check("se ve sin iniciar sesión", r.status_code == 200)
check("lleva el nombre del negocio", config.BUSINESS_NAME in r.text)
check("dice qué datos se recogen y con quién se comparten",
      "número de teléfono" in r.text and "Meta" in r.text and "Google" in r.text)
check("da un correo de contacto para ejercer derechos",
      config.BUSINESS_EMAIL in r.text)
check("no filtra nada del panel", "ADMIN" not in r.text and "clave" not in r.text.lower())

# La IA no estaba declarada, y el texto del mensaje del cliente SÍ se le
# manda a Google (`gemini.py`). Se detectó preparando el App Review el
# 20-ago-2026: la seccion "con quien se comparten" listaba Meta, Calendar
# y el hosting, y se dejaba fuera al que lee los mensajes.
check("declara que el mensaje se envía a la IA de Google",
      "Gemini" in r.text)
check("y dice quién responde por los datos de quien escribe",
      "encargo" in r.text and "responsable" not in r.text.split("<h1>")[0])

# Las otras dos URLs que pide el panel de la App de Meta. Sin ellas, el
# formulario del App Review no se puede completar.
print("")
print("=== Términos y eliminación de datos (públicos) ===")
for _ruta, _senal in (("/terminos", "Términos del servicio"),
                      ("/eliminar-datos", "Cómo pedir que se eliminen tus datos")):
    _r = sin_clave.get(f"{BASE}{_ruta}")
    check(f"{_ruta} se ve sin iniciar sesión", _r.status_code == 200,
          str(_r.status_code))
    check(f"{_ruta} lleva su título", _senal in _r.text)
    check(f"{_ruta} lleva el nombre del negocio",
          config.BUSINESS_NAME in _r.text)
    # El fallo de las plantillas con hueco, otra vez: una pagina legal con
    # un {email} crudo delante de un revisor de Meta es de las que cuesta
    # explicar.
    import re as _re2
    check(f"{_ruta} no deja huecos de plantilla sin rellenar",
          not _re2.findall(r"\{[a-z_]+\}", _r.text),
          str(_re2.findall(r"\{[a-z_]+\}", _r.text)[:3]))

# Las tres se enlazan entre sí: el revisor entra por una y tiene que poder
# llegar a las otras dos sin adivinar la URL.
for _ruta in ("/privacidad", "/terminos", "/eliminar-datos"):
    _r = sin_clave.get(f"{BASE}{_ruta}")
    check(f"{_ruta} enlaza a las otras dos",
          all(u in _r.text for u in ("/privacidad", "/terminos", "/eliminar-datos")))

print("\n=== Un solo generador del listado ===")
# Antes había dos: uno en Python para la primera carga y otro en JS para
# los refrescos. Ya habían divergido — una conversación sin mensajes
# decía "sin mensajes" al cargar y se quedaba en blanco al refrescarse.
r_inbox = s.get(f"{BASE}/admin/inbox")
r_hilo = s.get(f"{BASE}/admin/chat/{TEL}")

check("la bandeja ya no trae el listado pintado en HTML",
      '<a class="conversacion' not in r_inbox.text)
check("el hilo tampoco", '<a class="conversacion' not in r_hilo.text)
check("las dos pantallas llevan el listado de partida embebido",
      listado_de(r_inbox.text) is not None and listado_de(r_hilo.text) is not None)
check("y no hace falta pedirlo por red para pintarlo",
      "pintarListado(JSON.parse" in r_inbox.text
      or "pintarListado(JSON.parse" in guion_de(f"{BASE}/admin/inbox"))

# La prueba de que ya no pueden divergir: lo embebido y lo que devuelve
# el endpoint que refresca tienen que ser lo MISMO.
_embebido = {c["phone"]: c for c in listado_de(r_inbox.text)}
_del_api = {c["phone"]: c
            for c in s.get(f"{BASE}/admin/api/conversaciones").json()["conversaciones"]}
check("la primera carga y el refresco entregan lo mismo",
      _embebido == _del_api,
      f"{len(_embebido)} vs {len(_del_api)} conversaciones")

# El caso concreto que divergía: un contacto sin ningún mensaje.
TEL_VACIO = "573001110000"
_ses = database.get_session()
_ses.add(database.Contact(phone=TEL_VACIO))
_ses.commit(); _ses.close()

_vacia = fila_de(s.get(f"{BASE}/admin/inbox").text, TEL_VACIO)
check("una conversación sin mensajes aparece igualmente",
      _vacia is not None, str(_vacia))
check("y el texto que falta lo resuelve un solo sitio, el que pinta",
      _vacia["resumen"] == "" and _vacia["name"] == ""
      and "c.resumen || 'sin mensajes'" in guion_de(f"{BASE}/admin/inbox")
      and "c.name || c.phone" in guion_de(f"{BASE}/admin/inbox"))

# Un nombre malicioso no puede cerrar el bloque JSON y colar código.
TEL_MALO = "573001110001"
msg("hola", phone=TEL_MALO); msg("</script><script>alert(1)</script>", phone=TEL_MALO)
_texto = s.get(f"{BASE}/admin/inbox").text
check("un nombre con etiquetas no rompe el JSON embebido",
      "</script><script>alert(1)" not in _texto
      and fila_de(_texto, TEL_MALO) is not None)

print("\n=== App instalable en el celular (PWA) ===")

# Las tres rutas van SIN sesión a propósito: el navegador pide el
# manifiesto y el icono desde la pantalla de login, que es donde alguien
# abre esto por primera vez en el celular.
r = sin_clave.get(f"{BASE}/manifest.webmanifest")
ficha = r.json()
check("el manifiesto responde sin haber entrado", r.status_code == 200)
check("lleva el nombre del negocio",
      config.BUSINESS_NAME in ficha["name"], ficha["name"])
check("al abrir desde el icono entra directo a la bandeja",
      ficha["start_url"] == "/admin/inbox", ficha["start_url"])
check("se abre como app, sin barra de direcciones",
      ficha["display"] == "standalone")
check("su alcance es todo el sitio, no solo /admin",
      ficha["scope"] == "/", ficha["scope"])
check("lleva el color de marca del negocio",
      ficha["theme_color"] == config.MARCA_COLOR)
check("trae los iconos que pide Android",
      {"192x192", "512x512"} <= {i["sizes"] for i in ficha["icons"]})
check("y uno recortable, para que Android no lo meta en un cuadro blanco",
      any(i.get("purpose") == "maskable" for i in ficha["icons"]))

r_sw = sin_clave.get(f"{BASE}/sw.js")
check("el service worker responde desde la raíz", r_sw.status_code == 200)
check("y se sirve como JavaScript",
      "javascript" in r_sw.headers.get("content-type", ""),
      r_sw.headers.get("content-type", ""))
check("no se queda pegado en una versión vieja",
      "no-cache" in r_sw.headers.get("cache-control", ""))

# LO IMPORTANTE DE TODO ESTO: guardar el HTML del panel dejaría la
# pantalla de un cliente cacheada en el celular, y podría reaparecer
# después de cerrar sesión. Se comprueba de dos formas, porque es la
# regla que no se puede romper.
check("corta explícitamente todo lo que empiece por /admin",
      "url.pathname.startsWith('/admin')" in r_sw.text)
check("no precarga nada del panel",
      "/admin" not in r_sw.text.split("PRECARGA")[1].split("]")[0])

# La lista blanca del service worker, probada contra rutas reales del
# panel: se saca del propio archivo servido, no de una copia.
_patron = re.search(r"const CACHEABLE = /(.+)/;", r_sw.text).group(1)
_cacheable = re.compile(_patron)
_privadas = ["/admin/inbox", f"/admin/chat/{TEL}", "/admin/api/conversaciones",
             f"/admin/api/chat/{TEL}", "/admin/api/stream", "/admin/login"]
check("ninguna ruta del panel entra en la caché",
      not any(_cacheable.search(p) for p in _privadas),
      f"regla: {_patron}")
check("y sí entran el manifiesto y los iconos",
      all(_cacheable.search(p) for p in ["/manifest.webmanifest",
                                         "/icono-192.png", "/icono-512.png"]))

r = sin_clave.get(f"{BASE}/icono-192.png")
check("el icono se genera", r.status_code == 200)
check("y es un PNG de verdad",
      r.content[:4] == b"\x89PNG" and r.headers["content-type"] == "image/png")
check("existe el de 180, que es el único que acepta iOS",
      sin_clave.get(f"{BASE}/icono-180.png").content[:4] == b"\x89PNG")
check("un tamaño que nadie pide no pone al servidor a dibujar",
      sin_clave.get(f"{BASE}/icono-30000.png").status_code == 404)

# Los dos tipos de logo. Tratarlos igual deja el icono feo en uno de los
# dos casos: un logo que ya trae su fondo, pegado al 60 %, queda como una
# calcomanía flotando sobre el color de marca.
import io as _io  # noqa: E402
from PIL import Image as _Img  # noqa: E402
from app.web import pwa as _pwa  # noqa: E402


def _icono_con(logo):
    """El icono de 512 que saldría con ese logo, sin tocar el de verdad."""
    original = _pwa._cargar_logo
    _pwa._cargar_logo = lambda: logo
    _pwa._CACHE_ICONOS.clear()
    try:
        return _Img.open(_io.BytesIO(_pwa._dibujar_icono(512))).convert("RGB")
    finally:
        _pwa._cargar_logo = original
        _pwa._CACHE_ICONOS.clear()


_marca = _pwa._a_rgb(config.MARCA_COLOR, (22, 163, 74))

_macizo = _Img.new("RGBA", (400, 400), (80, 20, 120, 255))
check("un logo que ya trae su fondo ocupa el icono entero",
      _icono_con(_macizo).getpixel((4, 4)) == (80, 20, 120),
      f"esquina: {_icono_con(_macizo).getpixel((4, 4))}")

_recortado = _Img.new("RGBA", (400, 400), (255, 255, 255, 0))
_recortado.paste((255, 255, 255, 255), (150, 150, 250, 250))
_esquina = _icono_con(_recortado).getpixel((4, 4))
check("un logo recortado va centrado sobre el color de marca",
      _esquina == _marca, f"esquina: {_esquina} / marca: {_marca}")
check("y no se le come los bordes el recorte de Android",
      _icono_con(_recortado).getpixel((256, 256)) == (255, 255, 255))

check("sin logo, el icono son las iniciales sobre el color de marca",
      _icono_con(None).getpixel((4, 4)) == _marca)

# En las páginas del panel. El login entra en la lista a propósito: es la
# primera pantalla que ve alguien en el celular, y si ahí no se ofrece
# instalar, no se instala nunca.
for pantalla, texto in [("la bandeja", s.get(f"{BASE}/admin/inbox").text),
                        ("el hilo", s.get(f"{BASE}/admin/chat/{TEL}").text),
                        ("el login", requests.get(f"{BASE}/admin/inbox").text)]:
    check(f"{pantalla} ofrece instalarse",
          'rel="manifest"' in texto and "pwa-registro.js" in texto)

texto = s.get(f"{BASE}/admin/inbox").text
check("iOS encuentra su icono de 180",
      'rel="apple-touch-icon" href="/icono-180.png"' in texto)
check("iOS la abre a pantalla completa",
      'name="apple-mobile-web-app-capable" content="yes"' in texto)
check("y con el nombre del negocio debajo del icono",
      f'name="apple-mobile-web-app-title" content="{config.APP_NOMBRE_CORTO}"'
      in texto)
check("la barra de estado toma el color de marca",
      f'name="theme-color" content="{config.MARCA_COLOR}"' in texto)

print("\n=== Vuelve sola al bot cuando la conversación se enfría ===")
TEL_ABANDONO = "573001119999"
msg("hola", phone=TEL_ABANDONO); msg("Olvidado", phone=TEL_ABANDONO)
s.post(f"{BASE}/admin/chat/{TEL_ABANDONO}", data={"texto": "Ahora te reviso"})
check("al responder queda atendida por ti",
      any(c["phone"] == TEL_ABANDONO
          for c in bot_logic.listar_contactos(solo_humanos=True)))


def envejecer(phone, minutos, solo_asesor=False):
    """
    Empuja hacia atrás la actividad de un chat.

    Con `solo_asesor` envejece únicamente el lado del asesor y deja
    recientes los mensajes del cliente: así se simula al asesor que tardó
    de más mientras el cliente sigue escribiendo.
    """
    viejo = database.ahora_utc() - timedelta(minutes=minutos)
    sesion = database.get_session()
    consulta = sesion.query(database.Message).filter_by(phone=phone)
    if solo_asesor:
        consulta = consulta.filter_by(autor="humano")
    for m in consulta.all():
        m.created_at = viejo
    contacto = sesion.query(database.Contact).filter_by(phone=phone).first()
    if contacto and contacto.takeover_at:
        contacto.takeover_at = viejo
    sesion.commit(); sesion.close()


# El asesor ya tardó más del plazo, pero el cliente acaba de escribir: la
# conversación está viva y el bot NO debe meterse. Antes se despertaba
# justo aquí y saludaba desde cero por encima del asesor.
msg("sigues ahi?", phone=TEL_ABANDONO)
envejecer(TEL_ABANDONO, config.HUMAN_TAKEOVER_TIMEOUT_MINUTES + 5, solo_asesor=True)
s.get(f"{BASE}/admin/api/conversaciones")
check("no la suelta mientras el cliente siga escribiendo",
      any(c["phone"] == TEL_ABANDONO
          for c in bot_logic.listar_contactos(solo_humanos=True)))

# Ahora sí: silencio por los dos lados durante más del plazo.
envejecer(TEL_ABANDONO, config.HUMAN_TAKEOVER_TIMEOUT_MINUTES + 5)
r = s.get(f"{BASE}/admin/api/conversaciones")
check("el panel la devuelve sola al bot al refrescarse",
      not any(c["phone"] == TEL_ABANDONO
              for c in bot_logic.listar_contactos(solo_humanos=True)))
_fila = next(c for c in r.json()["conversaciones"] if c["phone"] == TEL_ABANDONO)
check("y deja de mostrarla como atendida por ti",
      _fila["atendido_por_humano"] is False)

antes = len(enviados)
msg("hola?", phone=TEL_ABANDONO)
check("el bot vuelve a responderle", len(enviados) > antes)
check("y lo reconoce en vez de pedirle el nombre otra vez",
      any("Olvidado" in t[1] for t in enviados[antes:]),
      f"envió: {[t[1][:40] for t in enviados[antes:]]}")

# ── Imágenes y notas de voz ──────────────────────────────────────────

print("\n=== Ver un archivo del chat ===")
from app.core import media   # noqa: E402

TEL_MEDIA = "573001119911"
msg("hola", phone=TEL_MEDIA)
msg("Rocío", phone=TEL_MEDIA)

# Una imagen entrante, como la que dejaría el webhook
message_log.registrar(TEL_MEDIA, "entrante", "cliente", None,
                      media_id="MID-PANEL-1", media_tipo="image",
                      media_mime="image/jpeg", media_bytes=2048)
id_imagen = message_log.ultimo_saliente(TEL_MEDIA)
_s = database.get_session()
id_imagen = (_s.query(database.Message).filter_by(phone=TEL_MEDIA, direccion="entrante")
             .order_by(database.Message.id.desc()).first().id)
_s.close()

# Lo que devolvería Meta, sin salir a la red
PIXEL = (b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 40 + b"\xff\xd9")
bajadas = []
media.descargar = lambda mid: (bajadas.append(mid), (PIXEL, "image/jpeg"))[-1]

r = requests.get(f"{BASE}/admin/media/{id_imagen}")
check("sin sesión no se puede ver la imagen de un cliente",
      r.status_code == 401, f"status={r.status_code}")

r = s.get(f"{BASE}/admin/media/{id_imagen}")
check("con sesión sí se sirve", r.status_code == 200, f"status={r.status_code}")
check("y llega como imagen", r.headers.get("content-type", "").startswith("image/"),
      r.headers.get("content-type"))
check("no se cachea en público: es la conversación de alguien",
      "private" in r.headers.get("cache-control", ""),
      r.headers.get("cache-control"))
check("se bajó de Meta la primera vez", bajadas == ["MID-PANEL-1"], str(bajadas))

r = s.get(f"{BASE}/admin/media/{id_imagen}")
check("la segunda vez sale del caché, sin volver a pedírsela a Meta",
      bajadas == ["MID-PANEL-1"], str(bajadas))

r = s.get(f"{BASE}/admin/media/{id_imagen}?descargar=1")
check("con ?descargar=1 se guarda en vez de abrirse",
      "attachment" in r.headers.get("content-disposition", ""),
      r.headers.get("content-disposition"))

# Un documento con acentos y espacios en el nombre. Sin la forma
# `filename*`, el navegador lo guardaba como "cotizaci%C3%B3n+final.pdf".
message_log.registrar(TEL_MEDIA, "entrante", "cliente", None,
                      media_id="MID-PDF-1", media_tipo="document",
                      media_mime="application/pdf",
                      media_nombre="cotización final.pdf")
_s = database.get_session()
id_pdf = (_s.query(database.Message).filter_by(phone=TEL_MEDIA)
          .order_by(database.Message.id.desc()).first().id)
_s.close()

media.descargar = lambda mid: (b"%PDF-1.4 falso", "application/pdf")
r = s.get(f"{BASE}/admin/media/{id_pdf}?descargar=1")
_cd = r.headers.get("content-disposition", "")
check("un nombre con acentos y espacios se descarga bien",
      "filename*=UTF-8''cotizaci%C3%B3n%20final.pdf" in _cd, _cd)

print("\n=== Un archivo que ya caducó en Meta ===")
# Meta borra a los 7 días lo que entró por webhook. La burbuja tiene que
# seguir ahí: perder la imagen es una cosa, perder el rastro es otra.
def _caducado(mid):
    raise media.MediaError("Meta no encuentra el archivo (404).")

media.descargar = _caducado

# Se borra el archivo a mano y no con limpiar_cache(dias=0): un 0 ahí
# significa "guardar para siempre", no "borrar todo". Confundir las dos
# cosas es justo el fallo del que protege esa guarda.
_cacheada = media.ruta_cache(id_imagen, "image/jpeg")
if os.path.exists(_cacheada):
    os.remove(_cacheada)

r = s.get(f"{BASE}/admin/media/{id_imagen}")
check("el servidor responde 410 (se fue), no 404 (nunca estuvo)",
      r.status_code == 410, f"status={r.status_code}")

r = s.get(f"{BASE}/admin/chat/{TEL_MEDIA}")
check("y el hilo sigue mostrando que hubo una imagen",
      "adjunto" in r.text and f"/admin/media/{id_imagen}" in r.text)

print("\n=== El hilo pinta los adjuntos ===")
media.descargar = lambda mid: (PIXEL, "image/jpeg")
r = s.get(f"{BASE}/admin/chat/{TEL_MEDIA}")
check("la imagen se pinta con una etiqueta img", "<img src=\"/admin/media/" in r.text)
check("y con su enlace para guardarla", "?descargar=1" in r.text)
check("el panel ofrece adjuntar", 'id="btn-adjuntar"' in r.text)
check("y grabar una nota de voz", 'id="btn-grabar"' in r.text)
check("el micrófono se mantiene pulsado, no se toca",
      "Mantén pulsado para grabar" in r.text)
check("la caja de texto no explica atajos de teclado",
      'placeholder="Escribe un mensaje"' in r.text)

# La foto se enseña antes de mandarla: equivocarse de imagen con un
# cliente no se puede deshacer.
# El JavaScript tampoco viaja ya dentro de la pagina: son archivos
# (`/estaticos/panel-*.js`). Se piden todos y se juntan, que es como se
# ejecutan en el navegador: comparten ambito y corren en orden.
_archivos_js = re.findall(r'src="(/estaticos/panel-[^"]*)"', r.text)
_js = chr(10).join(requests.get(BASE + u, timeout=10).text for u in _archivos_js)
check("los guiones del panel se sirven como archivos",
      len(_archivos_js) >= 4 and len(_js) > 20000,
      f"{len(_archivos_js)} archivos, {len(_js)} caracteres")
check("y la pagina ya no los lleva dentro",
      "function subirAdjunto" not in r.text and "function subirAdjunto" in _js)
check("pero si lleva lo que cambia con el negocio",
      "const PANEL = {" in r.text and "origenPorDefecto" in r.text)

# Al sacar el JavaScript de las f-strings, un hueco de Python que se
# escape queda como `{LO_QUE_SEA}` dentro del archivo: el navegador se
# come el guion entero con un SyntaxError y el panel deja de responder,
# sin que ninguna prueba de HTTP se entere. Paso una vez, con
# {SEGUNDOS_PLAN_B * 1000}.
_huecos = re.findall(r"\{[A-Z_][A-Z_0-9]*[ }*]", _js)
check("no queda ningun hueco de Python dentro de los guiones",
      not _huecos, str(_huecos)[:70])

# El CSS del panel ya no viaja dentro de la pagina: es un archivo aparte
# (`/estaticos/panel.css`, ver app/web/activos.py). Se pide una vez, y de
# paso esto comprueba que el archivo se sirve de verdad.
_css_url = re.search(r'href="(/estaticos/panel\.css[^"]*)"', r.text).group(1)
_css = requests.get(BASE + _css_url, timeout=10).text
check("la hoja de estilos se sirve como archivo, cacheable",
      "?v=" in _css_url and len(_css) > 5000,
      f"{_css_url} · {len(_css)} caracteres")
check("y ya no viaja dentro de cada pagina",
      "--surf:" not in r.text and "--surf:" in _css)
check("pero el color del negocio SI va en la pagina",
      "--marca-cliente:" in r.text)
check("la imagen se previsualiza antes de enviarla",
      "function previsualizar" in _js and "previa-fondo" in _js)
check("y no se sube hasta darle a Enviar",
      "subirAdjunto(archivo, 'imagen', comentario)" in _js)
check("deslizar arriba fija la grabación sin mantener el dedo",
      "PIXELES_PARA_BLOQUEAR" in _js and "fijarGrabacion" in _js)
check("y el botón no hace scroll al deslizar sobre él",
      "touch-action: none" in _css)

print("\n=== La barra de escribir: un solo botón a la derecha ===")
# Con la caja vacía se ve el micrófono; al escribir, el avión. Es una
# clase del CSS y no un display puesto a mano, para que el estado no
# acabe repartido entre dos sitios.
check("por defecto el botón de enviar está oculto",
      ".fila-envio.js .enviar { display: none; }" in _css)
check("y al escribir se cambia el micrófono por el avión",
      ".fila-envio.js.escribiendo .grabar { display: none; }" in _css
      and ".fila-envio.js.escribiendo .enviar { display: grid; }" in _css)
check("el cambio lo dispara el teclear", "actualizarBotonDerecha" in _js)
# Sin JavaScript el micrófono no sirve, pero el formulario de respaldo
# tiene que poder enviarse: por eso todo cuelga de la clase `js`.
check("sin JavaScript el botón de enviar NO se esconde",
      "filaEnvio.classList.add('js')" in _js)

print("\n=== Mientras se graba, la barra cambia ===")
check("aparece un micrófono rojo palpitando",
      'class="mic-rojo"' in r.text and ".mic-rojo" in _css
      and "animation: latido" in _css)
check("y un contador en formato m:ss",
      'id="cronometro"' in r.text and "function comoReloj" in _js
      and "String(total % 60).padStart(2, '0')" in _js)
check("con el aviso de que se puede cancelar",
      "Desliza para cancelar" in _js)
check("se esconden el clip y la caja de texto, no el micrófono pulsado",
      ".fila-envio.grabando .adjuntar," in _css
      and ".fila-envio.grabando textarea { display: none; }" in _css
      and ".fila-envio.grabando .grabar" not in _css)
check("arrastrar a la izquierda cancela la nota de voz",
      "PIXELES_PARA_CANCELAR" in _js and "cancelarGrabacion(); return;" in _js)
check("una grabación olvidada se corta sola", "MAXIMO_GRABANDO_MS" in _js)
# El micrófono rojo tiene que medir lo mismo que el botón del clip al que
# sustituye, y la caja del contador lo mismo que la caja de texto. Si no,
# la barra pega un salto de tamaño justo al empezar a grabar.
check("el micrófono rojo mide igual que los botones (42 px)",
      ".mic-rojo { width: 42px; height: 42px;" in _css)
# Las dos cajas tienen que compartir el redondeo, y se comprueba que
# usen el MISMO token en vez de el mismo número: así cambiar el token no
# las descuadra ni hace fallar la prueba por nada.
_radio_caja = re.search(r"\.fila-envio textarea \{[^}]*border-radius: ([^;]+);", _css)
_radio_grab = re.search(r"\.grabando-info \{[^}]*border-radius: ([^;]+);", _css)
check("y la caja del contador igual que la de escribir",
      "min-height: 42px;" in _css and _radio_caja and _radio_grab
      and _radio_caja.group(1) == _radio_grab.group(1),
      f"{_radio_caja.group(1) if _radio_caja else '?'} vs "
      f"{_radio_grab.group(1) if _radio_grab else '?'}")

print("\n=== El chat se abre en el último mensaje ===")
# Eran DOS causas sumadas:
#
# 1. Una imagen sin cargar y sin tamaño declarado ocupa CERO de alto. Con
#    varias fotos en el hilo, el alto al pintar era mucho menor que el
#    real, se bajaba a ese falso final, y luego cada foto que cargaba
#    empujaba el último mensaje fuera de la vista.
# 2. `pegadoAlFondo` se recalculaba en cada `scroll`, así que cualquier
#    movimiento del navegador durante ese acomodo lo dejaba en false y ya
#    nada volvía a bajar el hilo.
check("las imágenes reservan su hueco antes de cargar",
      "aspect-ratio: 4 / 3;" in _css)
check("y sueltan ese hueco al cargar, para no recortar la foto",
      ".adjunto img.cargada { aspect-ratio: auto;" in _css
      and "classList.add('cargada')" in _js)
check("se vuelve a bajar cuando carga una imagen del hilo",
      "caja.addEventListener('load'" in _js and "}, true);" in _js)
# La regla que arregla la segunda causa: un `scroll` solo puede volver a
# anclar, nunca desanclar. Desanclar es cosa de un gesto del usuario.
check("un scroll automático NO desancla el hilo",
      "if (distanciaAlFondo() < MARGEN_FONDO) pegadoAlFondo = true;" in _js)
check("solo lo desanclan la rueda, el dedo o arrastrar la barra",
      "'wheel', 'touchmove'" in _js and "gestoEnCurso" in _js)
check("y hay una red de seguridad mientras el hilo se acomoda",
      "[50, 150, 400, 800, 1500, 2500]" in _js)

print("\n=== Botón para volver al último mensaje ===")
check("existe y es una flecha hacia abajo",
      'id="bajar-al-final"' in r.text and "<svg" in r.text)
check("arranca oculto: con el chat al día no tapa nada",
      'id="bajar-al-final"' in r.text and "hidden>" in r.text)
check("flota sobre el hilo, encima del micrófono",
      ".bajar-al-final { position: absolute; right: 16px; top: -52px;" in _css)
check("aparece solo cuando te alejas del final",
      "btnBajar.hidden = distanciaAlFondo() < 120;" in _js)
check("al pulsarlo baja y vuelve a anclar el hilo",
      "pegadoAlFondo = true;" in _js and "behavior: 'smooth'" in _js)
check("si entra un mensaje mientras lees arriba, el botón sale",
      "else actualizarBotonBajar();" in _js)
# El atributo `capture` es lo que hace que el celular abra la cámara en
# vez de la galería. Se mira la etiqueta en sí, no la página entera: los
# comentarios del guion nombran la palabra al explicar por qué no está.
_input = re.search(r'<input type="file"[^>]*>', r.text)
check("el selector de archivo NO abre la cámara (sin 'capture')",
      _input and "capture" not in _input.group(0),
      _input.group(0) if _input else "no se encontró el input")
check("solo ofrece los formatos que acepta Meta",
      'accept="image/jpeg,image/png"' in r.text)

print("\n=== Mandar una imagen desde el panel ===")
subidas = []
media.subir = lambda contenido, mime, nombre: (
    subidas.append((len(contenido), mime, nombre)), "MID-SUBIDO")[-1]

imagenes_enviadas = []
whatsapp_client.send_image_message = lambda to, mid, caption="", autor="humano": (
    imagenes_enviadas.append((to, mid, caption)),
    message_log.registrar(to, "saliente", autor, caption or "", media_id=mid,
                          media_tipo="image", media_mime="image/jpeg"),
    FalsaResp())[-1]

# Un PNG de verdad, para que Pillow tenga algo que validar
from PIL import Image as _Image  # noqa: E402
_buf = _io.BytesIO()
_Image.new("RGB", (40, 40), (200, 30, 30)).save(_buf, format="PNG")
PNG = _buf.getvalue()

r = s.post(f"{BASE}/admin/api/chat/{TEL_MEDIA}/adjunto",
           files={"archivo": ("foto.png", PNG, "image/png")},
           data={"clase": "imagen", "texto": "mira esto"})
check("el panel puede mandar una imagen", r.status_code == 200 and r.json().get("ok"),
      r.text[:120])
check("se subió a Meta antes de enviarla", len(subidas) == 1, str(subidas))
check("y se mandó con su pie de foto",
      imagenes_enviadas and imagenes_enviadas[-1][2] == "mira esto",
      str(imagenes_enviadas[-1] if imagenes_enviadas else None))
check("mandar una imagen también toma el control de la conversación",
      message_log.conversacion_info(TEL_MEDIA)["atendido_por_humano"] is True)

r = requests.post(f"{BASE}/admin/api/chat/{TEL_MEDIA}/adjunto",
                  files={"archivo": ("foto.png", PNG, "image/png")},
                  data={"clase": "imagen"})
check("sin sesión no se puede mandar nada", r.status_code == 401)

r = s.post(f"{BASE}/admin/api/chat/{TEL_MEDIA}/adjunto",
           files={"archivo": ("cosa.txt", b"esto no es una imagen", "text/plain")},
           data={"clase": "imagen"})
check("un archivo que no es imagen se rechaza con un motivo claro",
      r.status_code == 400 and "imagen" in r.json().get("error", "").lower(),
      r.text[:120])

print("\n=== Mandar una nota de voz desde el panel ===")
audios_enviados = []
whatsapp_client.send_audio_message = (
    lambda to, mid, mime="audio/ogg", autor="humano", voice=True: (
        audios_enviados.append((to, mid, mime, voice)),
        message_log.registrar(to, "saliente", autor, "", media_id=mid,
                              media_tipo="audio", media_mime=mime),
        FalsaResp())[-1])

# Un WebM/Opus como el que graba Chrome, hecho con la misma librería que
# lo va a convertir. Es la prueba de que el camino real funciona.
def _grabacion_de_navegador():
    import array, math
    import av
    buzon = _io.BytesIO()
    salida = av.open(buzon, mode="w", format="webm")
    pista = salida.add_stream("libopus", rate=48000)
    pista.layout = "stereo"
    for i in range(40):
        f = av.AudioFrame(format="s16", layout="stereo", samples=960)
        f.rate = 48000
        datos = array.array("h")
        for n in range(960):
            v = int(math.sin(2 * math.pi * 440 * (i * 960 + n) / 48000) * 8000)
            datos.extend([v, v])
        f.planes[0].update(datos.tobytes())
        for p in pista.encode(f):
            salida.mux(p)
    for p in pista.encode(None):
        salida.mux(p)
    salida.close()
    return buzon.getvalue()


try:
    WEBM = _grabacion_de_navegador()
except Exception as e:      # sin PyAV la conversión no se puede probar
    WEBM = None
    print(f"  (aviso) no se pudo fabricar la grabación de prueba: {e}")

if WEBM:
    subidas.clear()
    r = s.post(f"{BASE}/admin/api/chat/{TEL_MEDIA}/adjunto",
               files={"archivo": ("voz.webm", WEBM, "audio/webm")},
               data={"clase": "audio"})
    check("el panel puede mandar una nota de voz",
          r.status_code == 200 and r.json().get("ok"), r.text[:150])
    # Para que WhatsApp la pinte como NOTA DE VOZ hacen falta DOS cosas y
    # las dos: el formato OGG/Opus, y la bandera `voice` en el payload.
    # Faltó la segunda y el resultado fue un audio que se envía sin error
    # y llega al cliente como archivo adjunto. Perfecto en los logs.
    check("se convirtió a OGG antes de subirla",
          subidas and subidas[-1][1] == "audio/ogg", str(subidas))
    check("y se envió con la bandera de nota de voz",
          audios_enviados and audios_enviados[-1][3] is True,
          str(audios_enviados[-1] if audios_enviados else None))
    check("sin aviso de degradación", not r.json().get("aviso"),
          str(r.json().get("aviso")))

    # 16 kbps mono no es un capricho: Meta solo dibuja el botón de
    # reproducir hasta 512 KB. Por encima pone uno de descarga y deja de
    # parecer una nota de voz aunque lo sea.
    _ogg, _mime, _es = media.a_nota_de_voz(WEBM, "audio/webm")
    check("la grabación queda pequeña (tope de 512 KB de Meta)",
          len(_ogg) <= 512 * 1024, f"{len(_ogg)/1024:.0f} KB")

    print("\n=== Si la conversión falla, se dice ===")
    # Antes esto se degradaba en silencio: se mandaba el original, Meta lo
    # aceptaba, y el cliente recibía un adjunto sin que nadie se enterara.
    _convertir_real = media._transcodificar_a_opus
    media._transcodificar_a_opus = lambda datos: (_ for _ in ()).throw(
        RuntimeError("PyAV simulado como ausente"))

    audios_enviados.clear()
    r = s.post(f"{BASE}/admin/api/chat/{TEL_MEDIA}/adjunto",
               files={"archivo": ("voz.m4a", b"\x00\x00\x00\x20ftypM4A ", "audio/mp4")},
               data={"clase": "audio"})
    check("sin conversor se envía igual, no se pierde el mensaje",
          r.status_code == 200 and r.json().get("ok"), r.text[:150])
    check("pero SIN pedir nota de voz, que sería mentirle a Meta",
          audios_enviados and audios_enviados[-1][3] is False,
          str(audios_enviados[-1] if audios_enviados else None))
    check("y el panel avisa de que salió como archivo, no como nota de voz",
          "nota de voz" in (r.json().get("aviso") or ""), str(r.json().get("aviso")))

    media._transcodificar_a_opus = _convertir_real

print("\n=== La limpieza del caché no borra el rastro ===")
os.makedirs(config.MEDIA_DIR, exist_ok=True)
_viejo = os.path.join(config.MEDIA_DIR, "999999.jpg")
with open(_viejo, "wb") as f:
    f.write(b"x" * 1000)
os.utime(_viejo, (time.time() - 86400 * 5, time.time() - 86400 * 5))

borrados = media.limpiar_cache(dias=1, tope_mb=200)
check("borra los archivos que pasaron del plazo", borrados >= 1, f"borrados={borrados}")
check("y el archivo ya no está", not os.path.exists(_viejo))

_s = database.get_session()
quedan = _s.query(database.Message).filter_by(phone=TEL_MEDIA).filter(
    database.Message.media_tipo.isnot(None)).count()
_s.close()
check("pero los mensajes con adjunto siguen en el historial", quedan >= 2,
      f"mensajes con adjunto={quedan}")

# Un 0 mal puesto en la configuración no puede vaciar el caché entero al
# arrancar, igual que con HISTORIAL_DIAS.
with open(os.path.join(config.MEDIA_DIR, "888888.jpg"), "wb") as f:
    f.write(b"y" * 500)
check("con el plazo en 0 no borra nada por antigüedad",
      media.limpiar_cache(dias=0, tope_mb=200) == 0)

print("\n=== El diagnóstico avisa si falta el conversor de audio ===")
# Sin PyAV el servicio arranca igual y las imágenes funcionan: lo único
# que se rompe son las notas de voz, y solo al intentar mandar una. Por
# eso /admin/status tiene que decirlo antes de que pase.
r = requests.get(f"{BASE}/admin/status",
                 headers={"X-Admin-Key": "clave-panel-prueba"})
_diag = r.json().get("archivos", {})
check("el diagnóstico dice si se pueden mandar notas de voz",
      "notas_de_voz" in _diag, str(_diag)[:150])
check("y aquí PyAV está, así que dice que sí",
      _diag.get("notas_de_voz") is True, str(_diag.get("conversor")))
check("también dice cuánto ocupa el caché",
      "cache_mb" in _diag and "en_cache" in _diag, str(_diag)[:150])

print("\n=== Diseño: tokens y color de marca ===")
# Todo el color sale de variables en :root. El modo oscuro solo las
# redefine, en vez de la lista de parches regla a regla que había antes
# —y que siempre iba un paso por detrás de los colores nuevos—.
_entrada = requests.get(f"{BASE}/admin/login").text
# Los tokens viven en la hoja compartida; el color del negocio, en la
# pagina. Esa division es justo lo que se comprueba.
check("hay un sistema de tokens en :root", ":root {" in _css
      and "--surf:" in _css and "--txt2:" in _css)
check("el acento es el morado de Nitro, no el color del cliente",
      "--acc:#6D28D9" in _css and f"--acc: {config.MARCA_COLOR}" not in _css)
check("y del cliente solo viaja el color de su cuadrito",
      f"--marca-cliente: {config.MARCA_COLOR};" in _entrada)
check("el modo oscuro redefine tokens, no reglas sueltas",
      ".tema-oscuro {" in _css and "--bg:#0A0812;" in _css)
# El sistema decide la PRIMERA vez; a partir de ahi manda lo que eligio
# quien usa el panel, que es lo que persiste en el navegador.
check("y el sistema solo decide la primera visita",
      "@media (prefers-color-scheme: dark) {" in _css
      and ":root:not(.tema-claro):not(.tema-oscuro)" in _css)

# ── La ficha como panel, por debajo de 1200px ────────────────────────
#
# El fallo que costó la vuelta al implementarlo: `.ver-ficha` a secas
# pierde por especificidad contra `.acciones-chat button`, que fija un
# `display`, y el botón salía TAMBIÉN en el escritorio, donde la ficha ya
# está a la vista y el botón no significa nada. Es la misma trampa que
# obliga a `!important` en `[hidden]`, y no da ningún error: solo un
# botón de más que nadie mira dos veces.
check("el botón de la ficha se apaga con un selector que gana al de los botones",
      ".acciones-chat .ver-ficha" in _css
      and ".ver-ficha, .cerrar-ficha, .velo-ficha" not in _css)
check("y solo se enciende por debajo de 1200px",
      "@media (max-width: 1200px)" in _css)

# El aspa vive dentro de la ficha, que tiene su propio scroll. En
# `absolute` se iba hacia arriba con el contenido, y al llegar a la nota
# interna —el final, y lo que más se viene a escribir— no quedaba ningún
# botón de cerrar en pantalla. En `fixed` pasa lo mismo: la ficha lleva
# un `transform`, y eso convierte a sus hijos fijos en absolutos.
check("el aspa de cerrar se queda a la vista al bajar por la ficha",
      "position: sticky" in _css and "float: right" in _css)

# El velo tiene que tapar también la barra de navegación del móvil
# (z-index 30) y quedarse por debajo de la vista previa de imagen (50),
# que se abre desde el hilo y manda sobre esto.
check("el velo tapa la barra de navegación pero no la vista previa",
      "z-index: 38" in _css and "z-index: 39" in _css)

for _clase in ("ver-ficha", "cerrar-ficha", "velo-ficha"):
    check(f"la hoja conoce .{_clase}", f".{_clase}" in _css)

# ── La bandeja no se sale de la pantalla ─────────────────────────────
#
# Salió en producción el 20-ago-2026, dicho por el dueño: en el teléfono
# "se ve cortado hacia la derecha" — el buscador, el último filtro, la
# hora de cada conversación y el botón del pie.
#
# La columna es un flex item, y un flex item trae `min-width: auto`: no
# encoge por debajo de su contenido mínimo. Y su contenido mínimo es el
# NOMBRE MÁS LARGO de la lista, porque va en `nowrap` para poder cortarlo
# con puntos suspensivos. Un solo contacto con nombre largo estiraba la
# columna a 452px dentro de una pantalla de 390. Con nombres cortos no se
# reproduce, que es por lo que llegó a producción.
# No se busca "el bloque de móvil" porque hay varios y están anidados
# (900px lleva dentro uno de 820px). Se buscan todas las reglas de
# `.col-lista` y se mira la que la convierte en columna elástica: es esa,
# y solo esa, la que necesita poder encoger.
_reglas_col = [b.split("}")[0] for b in _css.split(".col-lista {")[1:]]
_elastica = [r for r in _reglas_col if "width: auto" in r]
check("la hoja convierte la lista en columna elástica en pantalla estrecha",
      len(_elastica) == 1, f"{len(_elastica)} reglas")
check("y esa columna puede encoger por debajo de su contenido",
      bool(_elastica) and "min-width: 0" in _elastica[0],
      " ".join(_elastica[0].split()) if _elastica else "(no está la regla)")

# ── Los controles de la cabecera del hilo ────────────────────────────
#
# El de estado es un `<summary>` y no un `<button>`, así que se había
# quedado fuera de la regla que iguala a los demás: una pastilla de 94x23
# entre tres cuadrados de 34x34, y 6px más abajo. Ahora entra en la misma
# regla, con su icono, y en el teléfono se queda en icono como los otros.
check("el control de estado se dimensiona con los demás",
      ".acciones-chat .estados > summary" in _css)
check("y lleva icono para poder quedarse sin texto en el teléfono",
      "<svg" in _hilo.split('class="estados"')[1].split("</summary>")[0])

# Y el que salió buscando lo anterior, que YA estaba en producción: las
# opciones del menú desplegable son `<button>` y viven dentro de
# `.acciones-chat`, así que se llevaban el tamaño de los controles de la
# cabecera. En el teléfono eso las dejaba en 34px de ancho: "Esperando al
# cliente" recortado a nada, en un menú de 48px. Se acota con `>`.
check("la regla de los controles no alcanza a las opciones del menú",
      ".acciones-chat > button" in _css
      and ".acciones-chat button {" not in _css
      and ".acciones-chat button," not in _css)
check("el tema se pone antes de pintar, para que no haya destello",
      "n2t-tema" in _entrada and _entrada.index("n2t-tema") < _entrada.index("panel.css"))
# Un color de marca claro dejaría los botones ilegibles con texto blanco.
check("sobre una marca clara el texto se vuelve oscuro",
      config.color_legible_sobre((250, 240, 10)) == "#111827")
check("y sobre una oscura, blanco",
      config.color_legible_sobre((30, 20, 90)) == "#ffffff")

# La otra mitad de la comprobación del móvil: en el teléfono la lista
# solo se esconde con una conversación abierta. Sin esa condición, la
# bandeja en un móvil quedaba sin nada que pulsar.
check("y en el teléfono solo se esconde la lista con una abierta",
      "body.hay-hilo .rail, body.hay-hilo .col-lista { display: none; }" in _css)
# El icono del rail es el único <button> de los cuatro, y hereda el
# padding de los botones del panel: sin ponerlo a cero, la luna se salía
# de su cuadro y aparecía descentrada.
# En el telefono la navegacion baja al borde inferior: 56px de ancho son
# el 14% de la pantalla robados a lo que se viene a leer, y la esquina de
# arriba a la izquierda es la mas incomoda de alcanzar con el pulgar.
check("en el teléfono la navegación baja al borde inferior",
      ".rail { position: fixed; inset: auto 0 0 0;" in _css)
# Y lo que quede debajo tiene que poder verse: sin esto la barra tapa la
# ultima conversacion de la lista.
check("y deja sitio para que nada quede debajo de ella",
      "padding-bottom: calc(56px + env(safe-area-inset-bottom, 0px))" in _css)
# Con las palabras, los botones y el control de estado no caben al lado
# del nombre y la cabecera se parte en dos filas: 44px menos de
# conversacion en cada telefono, para siempre. El selector lleva `>`
# desde el 20-ago-2026 para no alcanzar a las opciones del desplegable,
# que tambien son <button> y viven dentro de la misma fila.
check("los botones del hilo se quedan en icono en el móvil",
      ".acciones-chat > button span," in _css
      and ".acciones-chat .estados > summary span { display: none; }" in _css)

check("y el icono del rail no hereda el relleno de los botones",
      ".rail-icono { width: 42px; height: 42px; border-radius: 13px; padding: 0;"
      in _css)

print("\n=== Diseño: pantalla de entrada ===")
check("la entrada tiene su propio cuerpo, no la caja genérica",
      'class="entrada"' in _entrada and "entrada-pantalla" in _entrada)
# El logo, el nombre y "Panel de atencion" se quitaron de la columna
# derecha (dueno, 19-ago-2026): la de al lado ya dice las tres cosas.
check("no repite la marca en las dos columnas",
      "login-negocio" not in _entrada)
# La decision de producto del 19-ago-2026: la plataforma es Nitro tambien
# dentro del panel de un cliente. Del negocio se ve su cuadrito y su
# nombre; la columna de marca es de Nitro siempre. Sin esta prueba, el
# primer cliente que pida "ponme mi logo grande" lo deshace sin querer.
check("pero la columna de marca sigue siendo la de Nitro",
      "login-marca" in _entrada and "Nitro" in _entrada)
# La palabra hueca necesita la Manrope sin solapes; con la normal, el 2,
# la e y la h salen con rayas cruzadas por dentro. Si el @font-face
# desaparece de la hoja, la letra sigue viendose -fea, pero se ve-.
check("el titular hueco pide la fuente sin solapes",
      "'Manrope Logo'" in _css and "manrope-logo.woff2" in _fuentes)
check("y la clave se puede mirar antes de mandarla",
      "data-ver-clave" in _entrada and "panel-login.js" in _entrada)

# El HTML y el CSS viven en archivos distintos desde el rediseno, y nada
# obliga a que hablen del mismo. Ya paso una vez: se renombro una clase
# en Python, la hoja se quedo con la vieja, las cuatro suites en verde y
# la pantalla descuadrada. Esto lo mira de una vez para toda la entrada.
_clases = set()
for _trozo in re.findall(r'class="([^"]+)"', _entrada):
    _clases.update(_trozo.split())
_sin_estilo = sorted(c for c in _clases if f".{c}" not in _css)
check("toda clase de la entrada existe en la hoja", not _sin_estilo,
      str(_sin_estilo))
check("y el nombre del negocio", config.BUSINESS_NAME in _entrada)
check("el campo de clave deja que el gestor de contraseñas lo rellene",
      'autocomplete="current-password"' in _entrada)

print("\n=== Etiquetas libres y nota interna ===")
# Las etiquetas libres y la nota interna. Las dos son SOLO del panel: el
# bot no las lee y el cliente no las ve nunca.

_r = s.post(f"{BASE}/admin/api/chat/{TEL}/etiquetas",
            json={"etiquetas": ["  cliente   viejo ", "CLIENTE VIEJO",
                                "", "x" * 40]})
check("guarda las etiquetas y devuelve las que quedaron",
      _r.status_code == 200 and _r.json()["ok"], _r.text[:80])
_quedaron = _r.json()["etiquetas"]
# El servidor recorta y descarta; el panel repinta con ESTO y no con lo
# que mando, o se veria una etiqueta que en la base esta cortada.
check("normaliza los espacios", _quedaron[0] == "cliente viejo", str(_quedaron))
check("descarta la repetida sin mirar mayusculas", len(_quedaron) == 2,
      str(_quedaron))
check("y recorta la larga al tope",
      len(_quedaron[1]) == database.LARGO_ETIQUETA, str(len(_quedaron[1])))

check("las etiquetas se ven en la bandeja",
      (fila_de(s.get(f"{BASE}/admin/inbox").text, TEL) or {}).get("etiquetas")
      == _quedaron)

_r = s.post(f"{BASE}/admin/api/chat/{TEL}/nota",
            json={"nota": "  Llamar el lunes.  "})
check("guarda la nota interna", _r.status_code == 200 and _r.json()["ok"])
check("y se vuelve a ver al abrir el hilo",
      "Llamar el lunes." in s.get(f"{BASE}/admin/chat/{TEL}").text)

# El bot NO puede acabar mandandole la nota al cliente. Es una columna
# que solo lee el panel, y quien escribe ahi cuenta con eso.
check("la nota no sale por ningun texto del bot",
      "Llamar el lunes." not in " ".join(
          str(t) for t in enviados[-20:]), str(enviados[-1])[:60])

_r = s.post(f"{BASE}/admin/api/chat/573000000000/etiquetas",
            json={"etiquetas": ["x"]})
check("etiquetar a alguien que ya no existe no revienta",
      _r.status_code == 400 and not _r.json()["ok"], _r.text[:60])
check("sin sesion no se puede etiquetar a nadie",
      requests.post(f"{BASE}/admin/api/chat/{TEL}/etiquetas",
                    json={"etiquetas": ["cuela"]}).status_code == 401)


print("\n=== La agenda de contactos ===")
_agenda = s.get(f"{BASE}/admin/contactos").text
check("la agenda existe y trae su tabla",
      "tabla-contactos" in _agenda and "Contactos totales" in _agenda)
check("y el rail marca en qué pantalla estás",
      'href="/admin/contactos"' in _agenda
      and "rail-icono activo" in _agenda)

# Los contactos van embebidos como JSON, igual que el listado: una sola
# pintada, sin el parpadeo de esperar a la red.
_trozo = re.search(r'id="contactos-inicial"[^>]*>(.*?)</script>', _agenda, re.S)
check("los contactos viajan embebidos", _trozo is not None)
if _trozo:
    _gente = json.loads(_trozo.group(1))
    check("y trae a quien escribió", any(g["phone"] == TEL for g in _gente),
          f"{len(_gente)} contactos")
    # "Esperando respuesta tuya" NO es el estado que se marca a mano: es
    # que el ultimo mensaje sea del cliente. Es la diferencia entre lo
    # que alguien se acordo de marcar y lo que de verdad esta sin
    # contestar, y la segunda es la que importa por la manana.
    check("sabe quién quedó sin respuesta",
          all("esperando" in g for g in _gente))

_csv = s.get(f"{BASE}/admin/contactos.csv")
check("se puede exportar la lista",
      _csv.status_code == 200
      and "attachment" in _csv.headers.get("content-disposition", ""))
# El BOM y el punto y coma no son manias: son lo que hace que Excel en
# espanol abra el archivo en columnas y respete las tildes.
check("y el archivo lo abre Excel sin romper las tildes",
      _csv.content.startswith(bytes([0xEF, 0xBB, 0xBF])) and b";" in _csv.content)
check("sin sesión, la exportación no entrega nada",
      pide_clave(requests.get(f"{BASE}/admin/contactos.csv").text))

print("\n=== La configuración ===")
_ajustes = s.get(f"{BASE}/admin/configuracion").text
check("la configuración existe",
      "Avisos del navegador" in _ajustes and "Apariencia" in _ajustes)
check("y el rail lleva a ella", 'href="/admin/configuracion"' in _ajustes)

# Sin claves VAPID no se ofrece un interruptor que no podria funcionar:
# se explica que falta. Pedirle un permiso al navegador para nada es
# peor que no ofrecer nada.
check("sin claves de aviso, no ofrece un botón que no serviría",
      ("data-avisos" in _ajustes) == push.configurado(),
      f"configurado={push.configurado()}")

# El boton de los avisos se esconde con `hidden` cuando el navegador los
# tiene bloqueados. `display` de la hoja le gana al `hidden` del
# navegador, asi que hace falta decirlo a lo bruto: sin esto, el boton
# seguia ahi invitando a pulsar algo que no podia funcionar.
check("y `hidden` gana sobre cualquier display",
      "[hidden] { display: none !important; }" in _css)

check("dice quién tiene la sesión abierta",
      "Tu sesión" in _ajustes and "Cerrar sesión" in _ajustes)
check("sin sesión, la configuración pide la clave",
      pide_clave(requests.get(f"{BASE}/admin/configuracion").text))

print("\n=== Crédito de quien hizo el bot ===")
check("aparece en la pantalla de entrada",
      "Creado por" in _entrada and config.CREADO_POR in _entrada)
_bandeja = s.get(f"{BASE}/admin/inbox").text
check("y en la bandeja de conversaciones",
      "Creado por" in _bandeja and config.CREADO_POR in _bandeja)
_hilo = s.get(f"{BASE}/admin/chat/{TEL_MEDIA}").text
check("y al pie del listado dentro de un chat",
      'class="credito-lista"' in _hilo)
# Quien revenda el bot con su nombre tiene que poder quitarlo sin tocar
# Python: sale de negocio.toml.
_antes = config.CREADO_POR
config.CREADO_POR = ""
check("se puede quitar dejándolo vacío en el TOML",
      admin_ui._credito() == "")
config.CREADO_POR = _antes

print("\n=== Reiniciar una conversacion (poder probar un cambio) ===")
# Costó una tarde de diagnóstico: el dueño cambiaba el saludo en el panel,
# le escribía a su bot y el bot seguía por donde iba. No era el guardado
# ni la caché — el saludo SOLO se manda a quien empieza de cero, y él ya
# tenía una conversación a medias. Sin esto, la única forma de probar un
# cambio era esperar 24 horas o escribir desde otro número.

TEL_R = "573009991234"
msg("hola", phone=TEL_R)
msg("Nico", phone=TEL_R)      # ya no está en NEW: dio su nombre

_s = database.get_session()
_estado_antes = _s.query(database.Contact).filter_by(phone=TEL_R).first().state
_s.close()
check("tras dar su nombre, la conversacion ya no esta al principio",
      _estado_antes != "NEW", _estado_antes)

_saludo_nuevo = "SALUDO CAMBIADO PARA LA PRUEBA"
# OJO con cual se toca: sin inquilino puesto, `config.actual()` devuelve
# la configuracion BASE, y el bot usa la del cliente. Son dos objetos
# distintos, y parchear el equivocado hace que la prueba mienta.
with tenencia.usar(config.CLIENTE_POR_DEFECTO):
    _cfg_del_bot = config.actual()
_original = _cfg_del_bot.WELCOME_MESSAGE
_cfg_del_bot.WELCOME_MESSAGE = _saludo_nuevo

_desde = len(enviados)
msg("otra cosa", phone=TEL_R)
check("con la conversacion a medias, el saludo nuevo NO se ve",
      not any(_saludo_nuevo in (e[1] or "") for e in enviados[_desde:]),
      "esto es lo que parecia 'no se guardo'")

r = s.post(f"{BASE}/admin/api/chat/{TEL_R}/reiniciar")
check("el panel deja reiniciar la conversacion",
      r.json().get("ok"), r.text[:60])

_desde = len(enviados)
msg("hola de nuevo", phone=TEL_R)
check("y entonces si: el proximo mensaje empieza por el saludo",
      any(_saludo_nuevo in (e[1] or "") for e in enviados[_desde:]),
      str([e[1][:25] for e in enviados[_desde:]]))

# Reiniciar NO borra: el historial y el nombre siguen ahi.
_s = database.get_session()
_c = _s.query(database.Contact).filter_by(phone=TEL_R).first()
_cuantos = _s.query(database.Message).filter_by(phone=TEL_R).count()
_nombre = _c.name
_s.close()
check("y no borra el historial ni el nombre",
      _cuantos > 2 and _nombre == "Nico",
      f"{_cuantos} mensajes, nombre={_nombre!r}")

_cfg_del_bot.WELCOME_MESSAGE = _original

r = s.post(f"{BASE}/admin/api/chat/573000000000/reiniciar")
check("reiniciar un contacto que no existe no revienta",
      r.status_code == 400 and not r.json().get("ok"), r.text[:50])

print("\n=== El equipo: cada área ve solo lo suyo ===")
# 23-sep-2026. El dueño arma sus áreas en su panel; cada una entra con su
# usuario y SOLO ve las conversaciones de las opciones del menú de las que
# se encarga. Lo que se prueba aquí es la puerta, no la pantalla: una
# conversación de otra área no se abre ni escribiendo su dirección.
_s = database.get_session()
_s.query(database.Client).filter_by(id=config.CLIENTE_POR_DEFECTO).update(
    {"plan": "pro"})
_s.commit()
_s.close()
config.olvidar()

with tenencia.usar(config.CLIENTE_POR_DEFECTO):
    _menu = [o["id"] for o in config.NEED_OPTIONS]
_de_ventas, _de_otra = _menu[0], _menu[1]

r = s.get(f"{BASE}/admin/equipo")
check("el dueño ve su equipo y su plan",
      r.status_code == 200 and "Tu equipo" in r.text and "Plan Pro" in r.text)

r = s.post(f"{BASE}/admin/equipo/area", data={
    "nombre": "Ventas", "correo": "ventas@negocio.test",
    "opciones": [_de_ventas], "usuario": "ventas-prueba",
    "clave": "clave-de-ventas"})
check("el dueño crea un área con su usuario", "guardada" in r.text, r.url)

r = s.post(f"{BASE}/admin/equipo/area", data={
    "nombre": "Sin opciones", "correo": "x@negocio.test",
    "usuario": "otra-prueba", "clave": "clave-de-otra"})
check("un área sin ninguna opción del menú no se guarda",
      "Marca al menos una opción" in r.text)

TEL_VENTAS, TEL_OTRA = "573007700001", "573007700002"
for _tel, _opcion in ((TEL_VENTAS, _de_ventas), (TEL_OTRA, _de_otra)):
    msg("hola", phone=_tel); msg("Cliente", phone=_tel)
    msg(list_id=_opcion, phone=_tel)

_area = requests.Session()
r = _area.post(f"{BASE}/admin/login",
               data={"usuario": "ventas-prueba", "clave": "clave-de-ventas"})
check("el área entra con su usuario", "Conversaciones" in r.text)
check("y su bandeja dice de qué área es", "Ventas" in r.text)
_suyas = {c["phone"] for c in listado_de(r.text)}
check("ve la conversación de su área", TEL_VENTAS in _suyas, str(_suyas))
check("y NO la de otra opción del menú", TEL_OTRA not in _suyas, str(_suyas))
check("ni las que no son de ningún área", TEL not in _suyas)

r = _area.get(f"{BASE}/admin/api/chat/{TEL_OTRA}")
check("abrir una conversación ajena por su dirección da 404",
      r.status_code == 404, str(r.status_code))
r = _area.get(f"{BASE}/admin/chat/{TEL_OTRA}")
check("y la pantalla del hilo lo devuelve a su bandeja",
      r.url.endswith("/admin/inbox") and TEL_OTRA not in r.text, r.url)
r = _area.post(f"{BASE}/admin/api/chat/{TEL_OTRA}/enviar", json={"texto": "hola"})
check("no puede escribirle a un cliente de otra área", r.status_code == 404)
r = _area.get(f"{BASE}/admin/api/chat/{TEL_VENTAS}")
check("la suya sí se abre", r.status_code == 200)
r = _area.post(f"{BASE}/admin/api/chat/{TEL_VENTAS}/borrar")
check("un área no puede borrar conversaciones", r.status_code == 403)
r = _area.post(f"{BASE}/admin/api/chat/{TEL_OTRA}/area", json={"area": "ventas"})
check("ni quedarse con las de otras", r.status_code == 403)
r = _area.get(f"{BASE}/admin/equipo")
check("ni arma el equipo", r.url.endswith("/admin/inbox"), r.url)
r = _area.get(f"{BASE}/admin/mi-plan")
check("ni ve el plan ni los pagos: eso es del dueño",
      r.url.endswith("/admin/inbox"), r.url)

from datetime import timedelta as _td  # noqa: E402
from app.core import cobros as _cobros  # noqa: E402
_s = database.get_session()
_s.query(database.Client).filter_by(id=config.CLIENTE_POR_DEFECTO).update(
    {"vence_el": _cobros.hoy() + _td(days=3)})
_s.commit()
_s.close()
r = s.get(f"{BASE}/admin/mi-plan")
check("el dueño ve su plan, su precio y cómo pagar",
      r.status_code == 200 and "Pro" in r.text and "$100.000" in r.text
      and "317 886 2390" in r.text)
check("y cuándo vence", "Vence en 3 días" in r.text)
r = s.get(f"{BASE}/admin/inbox")
check("la bandeja del dueño avisa del pago cercano", "cobro-banda" in r.text)
r = _area.get(f"{BASE}/admin/inbox")
check("la del área, no", "cobro-banda" not in r.text)

print("\n=== El dueño edita su bot y ve sus estadísticas ===")
r = _area.get(f"{BASE}/admin/mi-bot")
check("un área no edita el bot", r.url.endswith("/admin/inbox"), r.url)
r = _area.post(f"{BASE}/admin/mi-bot/guardar", json={"textos": {}})
check("ni por la puerta de atrás", r.status_code == 403)
r = _area.get(f"{BASE}/admin/estadisticas")
check("ni ve las estadísticas del negocio", r.url.endswith("/admin/inbox"))

r = s.get(f"{BASE}/admin/mi-bot")
check("el dueño abre el mapa de su bot",
      r.status_code == 200 and '"/admin/mi-bot/guardar"' in r.text
      and "superadmin" not in r.text.split("<body")[0].lower().replace(
          "superadmin.css", "").replace("superadmin-", ""))
with tenencia.usar(config.CLIENTE_POR_DEFECTO):
    _mapa_menu = list(config.NEED_OPTIONS)
_saludo = "Hola, soy el bot nuevo.\n\nEscríbeme."
r = s.post(f"{BASE}/admin/mi-bot/guardar", json={
    "textos": {"bienvenida": _saludo}, "menu": _mapa_menu})
check("guarda un cambio del dueño", r.json().get("ok") is True, r.text[:120])
with tenencia.usar(config.CLIENTE_POR_DEFECTO):
    check("y el bot lo dice desde ya, saltos de línea incluidos",
          config.WELCOME_MESSAGE == _saludo, repr(config.WELCOME_MESSAGE))
_roto = [dict(_mapa_menu[0], title="")] + _mapa_menu[1:]
r = s.post(f"{BASE}/admin/mi-bot/guardar", json={"menu": _roto})
check("pero no deja guardar un botón en blanco, y dice dónde está",
      r.json().get("ok") is False and r.json().get("donde"), r.text[:120])

r = s.get(f"{BASE}/admin/estadisticas?dias=7")
check("el dueño ve sus estadísticas",
      r.status_code == 200 and "Personas que escribieron" in r.text
      and "Mensajes recibidos por día" in r.text)
check("con las áreas, si las tiene", "por área" in r.text)

r = _area.get(f"{BASE}/admin/api/conversaciones")
check("el listado de fondo también viene filtrado",
      {c["phone"] for c in r.json()["conversaciones"]} == {TEL_VENTAS},
      str([c["phone"] for c in r.json()["conversaciones"]]))

r = s.post(f"{BASE}/admin/api/chat/{TEL_OTRA}/area", json={"area": "ventas"})
check("el dueño le pasa una conversación a un área", r.status_code == 200)
r = _area.get(f"{BASE}/admin/api/chat/{TEL_OTRA}")
check("y desde ese momento el área la ve", r.status_code == 200)

r = s.post(f"{BASE}/admin/equipo/area/quitar", data={"id": "ventas"})
check("el dueño quita el área", "quitada" in r.text)
r = _area.get(f"{BASE}/admin/inbox")
check("y su usuario deja de poder entrar al momento", pide_clave(r.text))
r = s.get(f"{BASE}/admin/chat/{TEL_OTRA}")
check("sus conversaciones vuelven al dueño",
      r.status_code == 200 and TEL_OTRA in r.text)

_s = database.get_session()
_s.query(database.Client).filter_by(id=config.CLIENTE_POR_DEFECTO).update(
    {"plan": None, "negocio_config": None, "vence_el": None})
_s.commit()
_s.close()
config.olvidar()

print("\n=== Cerrar sesión ===")
s.get(f"{BASE}/admin/logout")
r = s.get(f"{BASE}/admin/inbox")
check("tras salir vuelve a pedir la clave", pide_clave(r.text))

print("\n" + "=" * 55)
if fallos:
    print(f"FALLARON {len(fallos)}:")
    for f in fallos: print("  -", f)
    sys.exit(1)
print("Panel: todas las verificaciones pasaron.")
