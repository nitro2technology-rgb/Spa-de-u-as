"""
SUITE DE LA IA (PLAN PRO)
==========================
Verifica que el bot con Gemini encendido hace lo que promete, y —lo que
más importa— que cuando Gemini falla el cliente NO se queda sin respuesta.

    python tests/test_ia.py

No llama a Gemini de verdad: reemplaza la función que habla con el modelo
por una que devuelve lo que cada prueba necesita. Así la suite corre sin
clave, sin red y sin gastar cuota, que es lo que permite pasarla en cada
cambio.

Lo que se prueba, en orden de importancia:

  1. Que un fallo de Gemini —cualquiera— acabe en el menú de siempre.
     Esta es LA garantía del producto: una API caída no puede costarle un
     cliente al negocio.
  2. Que el modelo no pueda inventar acciones: solo elige entre las
     opciones que el negocio escribió en su negocio.toml.
  3. Que el tope diario frene a quien escriba en bucle.

La suite del plan Básico (tests/test_regresion.py) sigue siendo la que
prueba que nada de esto se filtró al Básico: allí IA_ACTIVA está en false
y el recorrido tiene que ser idéntico al de siempre.
"""

import os
import sys
import tempfile

# El interruptor y la base van ANTES de importar config, que lee las
# variables de entorno al importarse. Sin IA_ACTIVA=true aquí, el paquete
# `cerebro` cargaría menu.py y esta suite no probaría nada.
_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test_ia.db')}"
os.environ["IA_ACTIVA"] = "true"
# El paquete de IA hay que haberlo COMPRADO. En un negocio de verdad
# es una columna (`clients.ia_contratada`) que solo toca /superadmin;
# el entorno solo lo ve un cliente sin configuracion propia, que es
# justo el caso de esta suite. La prueba de que la puerta CIERRA esta
# en test_regresion.
os.environ["IA_CONTRATADA"] = "true"
os.environ["GEMINI_API_KEY"] = "clave-de-mentira-para-las-pruebas"
os.environ["IA_MAX_MENSAJES_DIA"] = "3"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fallos = []
_contador_mensajes = 0
enviados = []


def check(nombre, condicion, extra=""):
    linea = f"  {'[OK]' if condicion else '[X] '} {nombre}{'  ' + extra if extra else ''}"
    try:
        print(linea)
    except UnicodeEncodeError:
        # La consola de Windows usa cp1252 y no sabe imprimir emojis, y los
        # textos del bot llevan varios.
        codificacion = sys.stdout.encoding or "ascii"
        print(linea.encode(codificacion, "replace").decode(codificacion))
    if not condicion:
        fallos.append(nombre)


from app import config                      # noqa: E402
from app.core import database               # noqa: E402
from app.bot import bot_logic               # noqa: E402
from app.bot import cerebro                 # noqa: E402
from app.bot.cerebro import gemini          # noqa: E402
from app.bot import whatsapp_client         # noqa: E402
from app.integrations import sheets_service # noqa: E402


class RespuestaFalsa:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.text = "{}"

    def json(self):
        return {}


def _enviar_texto(to, text, autor="bot"):
    enviados.append(("text", to, text))
    return RespuestaFalsa()


whatsapp_client.send_text_message = _enviar_texto
whatsapp_client.send_button_message = (
    lambda to, text, buttons: (enviados.append(("btn", to, text)), RespuestaFalsa())[-1])
whatsapp_client.send_list_message = (
    lambda to, text, boton, opciones, titulo="Opciones":
        (enviados.append(("list", to, text)), RespuestaFalsa())[-1])
whatsapp_client.send_template_message = (
    lambda to, p, i, v: (enviados.append(("plantilla", to, "")), RespuestaFalsa())[-1])
sheets_service.registrar_lead = lambda tipo, contacto, lead: True

database.init_db()

# Y la COLUMNA del cliente sembrado, además de la variable de arriba.
# No es redundante: son dos configuraciones distintas y la suite usa las
# dos. Sin inquilino fijado manda `config.base()`, que lee el entorno;
# dentro de un `tenencia.usar(...)` —como el bloque del medidor— manda la
# fila, y el entorno no se mira. Poner solo una deja la mitad de la suite
# corriendo en plan Básico sin decir por qué.
_s = database.get_session()
_s.query(database.Client).filter_by(id=config.CLIENTE_POR_DEFECTO).update(
    {"ia_contratada": True})
_s.commit()
_s.close()
config.olvidar()


# ── El Gemini de mentira ─────────────────────────────────────────────
# Se reemplaza `_preguntar_al_modelo`, que es la única función del módulo
# que toca la red. Todo lo demás —el parseo, la validación del id contra
# el menú, el recorte, el tope— se ejecuta de verdad, que es justo lo que
# se quiere probar.

_respuesta_del_modelo = None

# Cada llamada que llega al modelo queda anotada aquí. Es lo que permite
# distinguir "cayó al menú porque el modelo falló" de "cayó al menú porque
# ni se le preguntó" — dos cosas que se ven idénticas desde fuera y que en
# una prueba significan lo contrario.
_llamadas_al_modelo = []


# Devuelve lo mismo que el de verdad: el texto y los tokens que Gemini
# reporta en `usage_metadata`. Los números son los reales de este bot (ver
# `docs/CONTINUAR_AQUI.md`): prompt pequeno y sin historial.
TOKENS_POR_LLAMADA = (450, 40)


def _modelo_falso(texto, opciones):
    _llamadas_al_modelo.append(texto)
    if isinstance(_respuesta_del_modelo, Exception):
        raise _respuesta_del_modelo
    return _respuesta_del_modelo, TOKENS_POR_LLAMADA


gemini._preguntar_al_modelo = _modelo_falso


def responder(valor):
    """Lo que devolverá el 'modelo' en la siguiente llamada."""
    global _respuesta_del_modelo
    _respuesta_del_modelo = valor
    _llamadas_al_modelo.clear()


def estado(phone):
    s = database.get_session()
    try:
        return s.query(database.Contact).filter_by(phone=phone).first()
    finally:
        s.close()


def msg(text=None, button_id=None, phone="573009990001", list_id=None):
    """Simula un mensaje entrante ya parseado por el webhook."""
    global _contador_mensajes
    _contador_mensajes += 1
    enviados.clear()
    bot_logic.handle_incoming_message(
        phone, "text", text=text, button_id=button_id, list_id=list_id,
        message_id=f"wamid.ia.{_contador_mensajes}",
    )


def textos():
    """Lo que se le habría enviado al cliente, todo junto."""
    return " | ".join(t[2] or "" for t in enviados)


def llevar_hasta_el_menu(phone):
    """Deja al contacto en ASKED_NEED, que es donde vive la costura."""
    msg("hola", phone=phone)          # NEW -> ASKED_NAME
    msg("Nico", phone=phone)          # ASKED_NAME -> ASKED_NEED
    return estado(phone)


def resetear_tope(phone):
    """
    Pone a cero la cuenta diaria de la IA para ese contacto.

    Hace falta entre bloques de pruebas: el tope está en 3 a propósito
    (para poder probarlo rápido), así que sin esto el cuarto mensaje de
    una prueba ya no llegaría a la IA y la verificación pasaría por el
    tope en vez de por lo que dice comprobar. Una prueba que pasa por el
    motivo equivocado es peor que no tenerla.
    """
    s = database.get_session()
    try:
        c = s.query(database.Contact).filter_by(phone=phone).first()
        if c is not None:
            c.ia_mensajes_dia = 0
            s.commit()
    finally:
        s.close()


def llego_a_la_ia() -> bool:
    """True si el último mensaje llegó de verdad al modelo."""
    return len(_llamadas_al_modelo) > 0


# ═════════════════════════════════════════════════════════════════════
print("\n=== Qué plan quedó activo ===")

check("con IA_ACTIVA=true y clave puesta, el plan es Pro",
      cerebro.plan_activo() == cerebro.PRO, cerebro.plan_activo())
check("y el panel lo ve encendido", cerebro.estado()["ia_encendida"])
check("el estado NO filtra la clave",
      "clave-de-mentira" not in str(cerebro.estado()), str(cerebro.estado()))

# ═════════════════════════════════════════════════════════════════════
print("\n=== Lo que pasa cuando Gemini FALLA (la garantía del producto) ===")

TEL = "573009990001"
llevar_hasta_el_menu(TEL)
check("el contacto está en el menú", estado(TEL).state == "ASKED_NEED",
      estado(TEL).state)

# 1. El modelo revienta
resetear_tope(TEL)
responder(RuntimeError("cuota agotada"))
# Un texto que no es el título de ningún botón. Con uno que lo fuera
# ("una página web") ya no caería al "no entendí": ver la comprobación
# de justo debajo.
msg("tengo una duda con mi tienda de ropa", phone=TEL)
check("se le llegó a preguntar al modelo", llego_a_la_ia())
check("si el modelo revienta, responde igual", len(enviados) >= 1)
check("y lo que responde es el 'no entendí' de siempre",
      config.FALLBACK_MESSAGE[:25] in textos())
check("y lo deja en el menú, no en un estado raro",
      estado(TEL).state == "ASKED_NEED", estado(TEL).state)

# Con Gemini caído, lo que el plan Básico ya reconoce se sigue
# reconociendo: que el cliente con IA reciba "no entendí" ante el título
# de un botón sería vender la IA como un paso atrás.
resetear_tope(TEL)
responder(RuntimeError("cuota agotada"))
msg("cuanto vale una pagina web", phone=TEL)
check("con la IA caída, escribir un botón hace lo que hace el botón",
      estado(TEL).servicio == "opt_web"
      and config.FALLBACK_MESSAGE[:25] not in textos(), textos()[:60])
llevar_hasta_el_menu(TEL)

# 2. El modelo devuelve basura
resetear_tope(TEL)
responder("esto no es JSON ni de lejos")
msg("hola que tal", phone=TEL)
check("se le llegó a preguntar al modelo (JSON roto)", llego_a_la_ia())
check("si el modelo no devuelve JSON, responde igual", len(enviados) >= 1)
check("y también cae al menú de siempre", config.FALLBACK_MESSAGE[:25] in textos())

# 3. El modelo devuelve JSON válido pero vacío
resetear_tope(TEL)
responder('{"intencion": null, "respuesta": null}')
msg("mmm", phone=TEL)
check("se le llegó a preguntar al modelo (dice 'no sé')", llego_a_la_ia())
check("si el modelo dice 'no sé', cae al menú de siempre",
      config.FALLBACK_MESSAGE[:25] in textos())

# 4. Sin clave configurada. Ni se intenta: sin clave el plan cae a Básico
#    antes de tocar nada de Gemini, así que no se gasta ni una llamada ni
#    un milisegundo en algo que no puede funcionar.
resetear_tope(TEL)
_clave = config.GEMINI_API_KEY
config.GEMINI_API_KEY = ""
responder('{"intencion": "opt_web", "respuesta": null}')
msg("quiero una web", phone=TEL)
check("sin clave configurada, el bot responde igual",
      config.FALLBACK_MESSAGE[:25] in textos())
check("y ni siquiera se intenta llamar al modelo", not llego_a_la_ia(),
      f"{len(_llamadas_al_modelo)} llamadas")
config.GEMINI_API_KEY = _clave

# Con la clave puesta pero inválida, el fallo sí tiene que saltar al
# construir el cliente y quedar marcado, para no reintentarlo en cada
# mensaje: una clave rota no se arregla sola y cada intento cuesta tiempo
# dentro del webhook.
gemini.olvidar()      # tira el cliente cacheado de TODOS los inquilinos


def _cliente_roto(texto, opciones):
    _llamadas_al_modelo.append(texto)
    raise gemini.GeminiNoDisponible("clave rota de prueba")


responder(None)
gemini._preguntar_al_modelo = _cliente_roto
resetear_tope(TEL)
msg("otra web", phone=TEL)
check("con la clave puesta pero rota, responde igual",
      config.FALLBACK_MESSAGE[:25] in textos())
check("y esa sí se intentó", llego_a_la_ia())
gemini.olvidar()
gemini._preguntar_al_modelo = _modelo_falso

# 5. El timeout. Es el fallo que más caro sale: Meta reintenta el webhook
#    si tardamos, y el reintento le llega al cliente como un duplicado.
resetear_tope(TEL)
_timeout_real = config.IA_TIMEOUT_SEGUNDOS
config.IA_TIMEOUT_SEGUNDOS = 0.2


def _modelo_lento(texto, opciones):
    import time
    _llamadas_al_modelo.append(texto)
    time.sleep(3)
    return '{"intencion": null, "respuesta": "llego tarde"}', TOKENS_POR_LLAMADA


responder(None)
gemini._preguntar_al_modelo = _modelo_lento
msg("una pregunta lenta", phone=TEL)
check("si el modelo tarda demasiado, se corta y responde el menú",
      config.FALLBACK_MESSAGE[:25] in textos(), textos()[:50])
check("y NO se le manda al cliente la respuesta que llegó tarde",
      "llego tarde" not in textos())
config.IA_TIMEOUT_SEGUNDOS = _timeout_real
gemini._preguntar_al_modelo = _modelo_falso

# ═════════════════════════════════════════════════════════════════════
print("\n=== El modelo NO puede inventar acciones ===")

ids_reales = [o["id"] for o in bot_logic._todas_las_opciones()]

resetear_tope(TEL)
responder('{"intencion": "opt_que_no_existe", "respuesta": null}')
msg("algo raro", phone=TEL)
check("se le llegó a preguntar al modelo (id inventado)", llego_a_la_ia())
check("un id que no está en el menú se descarta",
      config.FALLBACK_MESSAGE[:25] in textos())

resetear_tope(TEL)
responder('{"intencion": "borrar_la_base_de_datos", "respuesta": null}')
msg("otra cosa", phone=TEL)
check("se le llegó a preguntar al modelo (acción peligrosa)", llego_a_la_ia())
check("tampoco puede inventarse una acción peligrosa",
      config.FALLBACK_MESSAGE[:25] in textos())

# ═════════════════════════════════════════════════════════════════════
print("\n=== Cuando Gemini SÍ acierta ===")

# Una opción de primer nivel que abra submenú: es la que más se usa.
_submenu = next((o for o in config.NEED_OPTIONS
                 if o.get("accion") == "submenu"), None)
check("el negocio tiene al menos un servicio con submenú", _submenu is not None,
      _submenu["id"] if _submenu else "ninguno")

if _submenu:
    T2 = "573009990002"
    llevar_hasta_el_menu(T2)
    resetear_tope(T2)
    responder('{"intencion": "%s", "respuesta": null}' % _submenu["id"])
    msg("cuanto vale eso", phone=T2)
    check(f"'{_submenu['title']}' se abre escribiéndolo, sin tocar el menú",
          len(enviados) >= 1 and config.FALLBACK_MESSAGE[:25] not in textos(),
          textos()[:60])
    check("y queda anotado en el recorrido, igual que si lo hubiera tocado",
          estado(T2).servicio == _submenu["id"] or bool(estado(T2).recorrido),
          f"servicio={estado(T2).servicio} recorrido={estado(T2).recorrido}")

# Una respuesta libre a una pregunta que no es del menú
T3 = "573009990003"
llevar_hasta_el_menu(T3)
resetear_tope(T3)
responder('{"intencion": null, "respuesta": "Sí, atendemos toda Colombia."}')
msg("hacen envios a otras ciudades", phone=T3)
check("responde una pregunta suelta con lo que dijo el modelo",
      "atendemos toda Colombia" in textos(), textos()[:70])
check("y le vuelve a ofrecer el menú para que pueda seguir",
      any(t[0] in ("list", "btn") for t in enviados),
      str([t[0] for t in enviados]))
check("sigue en el menú, listo para elegir", estado(T3).state == "ASKED_NEED",
      estado(T3).state)

# ═════════════════════════════════════════════════════════════════════
print("\n=== El tope de palabras ===")

_largo = " ".join(["palabra"] * 200)
T4 = "573009990004"
llevar_hasta_el_menu(T4)
resetear_tope(T4)
responder('{"intencion": null, "respuesta": "%s"}' % _largo)
msg("cuentame todo", phone=T4)
_enviado = next((t[2] for t in enviados if t[0] == "text"), "")
check(f"una respuesta larguísima se recorta a {config.IA_MAX_PALABRAS} palabras",
      len(_enviado.split()) <= config.IA_MAX_PALABRAS + 1,
      f"{len(_enviado.split())} palabras")
check("y cabe de sobra en el límite de WhatsApp", len(_enviado) <= 4096,
      f"{len(_enviado)} caracteres")

# ═════════════════════════════════════════════════════════════════════
print("\n=== El tope diario por contacto ===")

check("el tope de la prueba está en 3", config.IA_MAX_MENSAJES_DIA == 3,
      str(config.IA_MAX_MENSAJES_DIA))

T5 = "573009990005"
llevar_hasta_el_menu(T5)
resetear_tope(T5)
responder('{"intencion": null, "respuesta": "Respuesta de la IA."}')

for i in range(3):
    msg(f"pregunta {i}", phone=T5)
check("los primeros mensajes sí llegan a la IA", "Respuesta de la IA." in textos(),
      textos()[:50])
check("y la cuenta va subiendo", (estado(T5).ia_mensajes_dia or 0) == 3,
      f"lleva {estado(T5).ia_mensajes_dia}")

msg("una mas, pasado el tope", phone=T5)
check("pasado el tope, la IA ya no se llama",
      "Respuesta de la IA." not in textos(), textos()[:50])
check("pero el bot NO se calla: responde con el menú de siempre",
      config.FALLBACK_MESSAGE[:25] in textos())
check("la cuenta no sigue subiendo pasado el tope",
      (estado(T5).ia_mensajes_dia or 0) == 3, f"lleva {estado(T5).ia_mensajes_dia}")

# Al cambiar el día se reinicia sola
s = database.get_session()
try:
    c = s.query(database.Contact).filter_by(phone=T5).first()
    c.ia_dia = "2000-01-01"
    s.commit()
finally:
    s.close()

msg("al dia siguiente", phone=T5)
check("al cambiar el día, el contador se reinicia solo",
      "Respuesta de la IA." in textos(), textos()[:50])
check("y la cuenta vuelve a empezar en 1", (estado(T5).ia_mensajes_dia or 0) == 1,
      f"lleva {estado(T5).ia_mensajes_dia}")

# ═════════════════════════════════════════════════════════════════════
print("\n=== Lo que NUNCA llega a la IA ===")

T6 = "573009990006"
llevar_hasta_el_menu(T6)
resetear_tope(T6)
responder('{"intencion": null, "respuesta": "no debería llamarse"}')

# Tocar una opción del menú es el grueso del tráfico: si eso llamara a la
# IA, la factura del negocio se multiplicaría sin darle nada a cambio.
_primera = config.NEED_OPTIONS[0]
msg(list_id=_primera["id"], phone=T6)
check("tocar una opción del menú NO llama a la IA", not llego_a_la_ia(),
      f"{len(_llamadas_al_modelo)} llamadas")
check("y el cliente recibe lo que eligió, no una respuesta de la IA",
      "no debería llamarse" not in textos())

# Un mensaje vacío tampoco: no hay nada que interpretar y sería una
# llamada pagada a cambio de nada.
resetear_tope(T6)
_llamadas_al_modelo.clear()
d = gemini.interpretar(estado(T6), "   ", list(bot_logic._todas_las_opciones()))
check("un mensaje en blanco NO llama a la IA", not llego_a_la_ia(),
      f"{len(_llamadas_al_modelo)} llamadas")
check("y devuelve 'no sé'", d.intencion is None and d.respuesta is None)

# ═════════════════════════════════════════════════════════════════════
print("\n=== La lectura de lo que devuelve el modelo ===")

_ops = list(bot_logic._todas_las_opciones())

d = gemini._leer_respuesta('```json\n{"intencion": null, "respuesta": "hola"}\n```', _ops)
check("entiende un JSON envuelto en ```json", d.respuesta == "hola", str(d))

d = gemini._leer_respuesta("", _ops)
check("una respuesta vacía es 'no sé'", d.intencion is None and d.respuesta is None)

d = gemini._leer_respuesta("[1,2,3]", _ops)
check("un JSON que no es un objeto es 'no sé'",
      d.intencion is None and d.respuesta is None)

d = gemini._leer_respuesta('{"intencion": "%s"}' % ids_reales[0], _ops)
check("un id que sí existe se acepta", d.intencion == ids_reales[0], str(d))

# ═════════════════════════════════════════════════════════════════════
print("\n=== El panel avisa cuando la IA falla ===")
# La degradación es silenciosa para el cliente, pero NO para quien
# administra el bot: sin este aviso, "activé la IA y responde igual que
# antes" solo se puede diagnosticar entrando a los logs del hosting.

T8 = "573009990008"
llevar_hasta_el_menu(T8)

gemini.olvidar_fallo()
check("de partida no hay ningún fallo que enseñar",
      cerebro.estado()["ultimo_fallo"] is None)

resetear_tope(T8)
responder(RuntimeError("404 modelo inexistente"))
msg("algo", phone=T8)
_fallo = cerebro.estado()["ultimo_fallo"]
check("tras fallar, el panel lo sabe", _fallo is not None)
check("y dice el motivo", _fallo and "404" in _fallo["motivo"],
      str(_fallo)[:80] if _fallo else "None")
check("y cuándo pasó", bool(_fallo and _fallo.get("cuando")))
check("el cliente NO se enteró: recibió el menú de siempre",
      config.FALLBACK_MESSAGE[:25] in textos())

# Y en cuanto vuelve a funcionar, el aviso se va solo: si no, el panel
# seguiría enseñando un problema ya resuelto.
resetear_tope(T8)
responder('{"intencion": null, "respuesta": "Ya funciono."}')
msg("otra vez", phone=T8)
check("al volver a funcionar, el aviso desaparece solo",
      cerebro.estado()["ultimo_fallo"] is None,
      str(cerebro.estado()["ultimo_fallo"]))

# El aviso no puede filtrar la clave: esta salida se pega en chats.
gemini._anotar_fallo("fallo de prueba")
check("el estado sigue sin filtrar la clave",
      "clave-de-mentira" not in str(cerebro.estado()))
gemini.olvidar_fallo()

# ═════════════════════════════════════════════════════════════════════
print("\n=== El interruptor del panel (subir y bajar de plan) ===")

from app.core import ajustes  # noqa: E402

T7 = "573009990007"
llevar_hasta_el_menu(T7)
resetear_tope(T7)
responder('{"intencion": null, "respuesta": "Contesta la IA."}')

# Arranca en Pro (IA_ACTIVA=true) y la IA responde.
check("de partida está en Pro", cerebro.plan_activo() == cerebro.PRO)
msg("una pregunta", phone=T7)
check("y la IA contesta", "Contesta la IA." in textos(), textos()[:40])

# El dueño lo apaga desde el panel. Sin reiniciar nada.
cerebro.cambiar_plan(cerebro.BASICO)
check("tras apagarlo, el plan es Básico", cerebro.plan_activo() == cerebro.BASICO)

resetear_tope(T7)
_llamadas_al_modelo.clear()
msg("otra pregunta", phone=T7)
check("la IA ya no se llama", not llego_a_la_ia(), f"{len(_llamadas_al_modelo)}")
check("y el bot responde con el menú de siempre",
      config.FALLBACK_MESSAGE[:25] in textos())

# Y lo vuelve a encender.
cerebro.cambiar_plan(cerebro.PRO)
resetear_tope(T7)
msg("y otra mas", phone=T7)
check("al encenderlo otra vez, la IA vuelve a contestar",
      "Contesta la IA." in textos(), textos()[:40])

# Lo elegido en el panel manda sobre la variable de entorno: si no, un
# despliegue le devolvería al dueño el plan que él mismo apagó.
cerebro.cambiar_plan(cerebro.BASICO)
check("lo del panel gana sobre IA_ACTIVA",
      config.IA_ACTIVA and cerebro.plan_activo() == cerebro.BASICO,
      f"IA_ACTIVA={config.IA_ACTIVA}, plan={cerebro.plan_activo()}")

# Y sobrevive a un reinicio: el ajuste está en la base, no en memoria.
ajustes.vaciar_cache()
check("y sobrevive al reinicio del servicio",
      cerebro.plan_activo() == cerebro.BASICO, cerebro.plan_activo())

ajustes.olvidar(cerebro.AJUSTE_PLAN)
check("al olvidarlo, vuelve a mandar IA_ACTIVA",
      cerebro.plan_activo() == cerebro.PRO, cerebro.plan_activo())

# ═════════════════════════════════════════════════════════════════════
print("\n=== Sin clave, el plan Pro no se puede activar ===")

_clave_real = config.GEMINI_API_KEY
config.GEMINI_API_KEY = ""

check("sin clave, el plan es Básico aunque IA_ACTIVA sea true",
      cerebro.plan_activo() == cerebro.BASICO, cerebro.plan_activo())
check("y el panel lo sabe", not cerebro.estado()["clave_configurada"])

try:
    cerebro.cambiar_plan(cerebro.PRO)
    check("activar Pro sin clave se rechaza", False, "no levantó el error")
except ValueError as e:
    check("activar Pro sin clave se rechaza", True)
    # Lo lee el DUEÑO en su panel. Antes le decía dónde conseguir una
    # clave y que la pegara en las variables del servicio, que no son
    # suyas: la clave es de la plataforma (23-sep-2026).
    check("y el error le dice qué hacer sin mandarlo a Render",
          "Avísanos" in str(e) and "variables" not in str(e), str(e))

config.GEMINI_API_KEY = _clave_real
ajustes.olvidar(cerebro.AJUSTE_PLAN)

try:
    cerebro.cambiar_plan("plan_inventado")
    check("un plan que no existe se rechaza", False, "no levantó el error")
except ValueError:
    check("un plan que no existe se rechaza", True)

# ═════════════════════════════════════════════════════════════════════
print("\n=== El medidor de IA (lo que se factura) ===")

from app.core import consumo, tenencia   # noqa: E402

TEL_MEDIDOR = "573009990777"

with tenencia.usar(config.CLIENTE_POR_DEFECTO):
    _antes = consumo.del_mes()

    responder('{"intencion": null, "respuesta": "claro que si"}')
    llevar_hasta_el_menu(TEL_MEDIDOR)
    resetear_tope(TEL_MEDIDOR)
    msg("una pregunta cualquiera", phone=TEL_MEDIDOR)

    _despues = consumo.del_mes()

check("una respuesta de la IA suma un mensaje al medidor",
      _despues["mensajes"] == _antes["mensajes"] + 1,
      f'{_antes["mensajes"]} -> {_despues["mensajes"]}')
check("y suma los tokens REALES que reporto el modelo",
      _despues["tokens_in"] == _antes["tokens_in"] + TOKENS_POR_LLAMADA[0]
      and _despues["tokens_out"] == _antes["tokens_out"] + TOKENS_POR_LLAMADA[1],
      f'in={_despues["tokens_in"]} out={_despues["tokens_out"]}')

# Un fallo no se factura: los tokens no se gastaron, y contarlos
# convertiria una clave mal puesta en consumo del cliente.
with tenencia.usar(config.CLIENTE_POR_DEFECTO):
    _antes = consumo.del_mes()
    responder(RuntimeError("se cayo la red"))
    resetear_tope(TEL_MEDIDOR)
    msg("otra pregunta", phone=TEL_MEDIDOR)
    _despues = consumo.del_mes()

check("un intento que falla NO se le factura a nadie",
      _despues["mensajes"] == _antes["mensajes"],
      f'{_antes["mensajes"]} -> {_despues["mensajes"]}')
check("y el cliente recibe el menu de siempre",
      config.FALLBACK_MESSAGE[:25] in textos())

# ═════════════════════════════════════════════════════════════════════
print("\n=== El tope mensual protege el margen, sin romper el bot ===")

# El tope sale de `clients.ia_limite_mensual`. Se pone en lo ya gastado
# para que el siguiente mensaje ya no quepa.
_s = database.get_session()
_gastado = consumo.del_mes(config.CLIENTE_POR_DEFECTO)["mensajes"]
_s.query(database.Client).filter_by(id=config.CLIENTE_POR_DEFECTO).update(
    {"ia_limite_mensual": _gastado})
_s.commit(); _s.close()
config.olvidar()

with tenencia.usar(config.CLIENTE_POR_DEFECTO):
    check("con el cupo gastado, el cliente ya supera el tope",
          consumo.supera_el_tope(), f"gastado={_gastado}")
    check("y el panel dice que no le quedan mensajes",
          consumo.restantes() == 0, f"restantes={consumo.restantes()}")

    responder('{"intencion": null, "respuesta": "esto no deberia salir"}')
    resetear_tope(TEL_MEDIDOR)
    msg("pregunta pasada de cupo", phone=TEL_MEDIDOR)

check("pasado el tope ya ni se le pregunta al modelo", not llego_a_la_ia())
check("el bot NO se rompe: sigue vendiendo con el menu",
      config.FALLBACK_MESSAGE[:25] in textos(), textos()[:60])
check("y no se le cuela al cliente lo que iba a decir la IA",
      "esto no deberia salir" not in textos())

# Sin tope (0) se vuelve a preguntar, sin tocar nada mas.
_s = database.get_session()
_s.query(database.Client).filter_by(id=config.CLIENTE_POR_DEFECTO).update(
    {"ia_limite_mensual": 0})
_s.commit(); _s.close()
config.olvidar()

with tenencia.usar(config.CLIENTE_POR_DEFECTO):
    check("con el tope en 0 no hay cupo que gastar", not consumo.supera_el_tope())
    check("y el panel no promete un numero que no existe",
          consumo.restantes() is None)

    responder('{"intencion": null, "respuesta": "y aqui vuelvo"}')
    resetear_tope(TEL_MEDIDOR)
    msg("otra vez", phone=TEL_MEDIDOR)

check("al quitar el tope, la IA vuelve a contestar", "y aqui vuelvo" in textos())

# ═════════════════════════════════════════════════════════════════════
print("\n=== Lo que el SDK hace por su cuenta, acotado ===")
# El SDK reintenta solo ante un 503, con esperas que crecen: medido contra
# el modelo de producción, una llamada de 0,8 s se convirtió en una de
# 28,6 s. El cronómetro de `interpretar` corta a los 8 s y el cliente
# recibe su menú — pero ThreadPoolExecutor NO cancela nada, así que el
# hilo sigue reintentando. Con cuatro hilos, unos cuantos tropiezos
# seguidos dejan a los mensajes siguientes esperando turno.

_capturado = {}


def _cliente_espia(**kwargs):
    _capturado.update(kwargs)
    return object()


try:
    from google import genai as _genai
    _hay_genai = True
except ImportError:
    _hay_genai = False

if _hay_genai:
    _real = _genai.Client
    _genai.Client = _cliente_espia
    gemini.olvidar()
    try:
        gemini._construir_cliente()
    finally:
        _genai.Client = _real
        gemini.olvidar()

    _opciones = _capturado.get("http_options")
    _reintentos = getattr(_opciones, "retry_options", None)

    check("el cliente se construye con un tope de reintentos propio",
          _reintentos is not None and _reintentos.attempts == gemini.INTENTOS_HTTP,
          str(_reintentos)[:60])

    # Que no sean los cinco de fábrica es justamente el punto: dos salvan
    # el 503 pasajero y ahí se acaba.
    check("y son dos, no los de fábrica", gemini.INTENTOS_HTTP == 2)

    # El plazo NO puede bajar de 10 s: Google rechaza con un 400 cualquier
    # valor menor ("Minimum allowed deadline is 10s"). O sea que la capa
    # HTTP no puede rendirse antes que el cronómetro, y quien manda en lo
    # que espera el cliente sigue siendo IA_TIMEOUT_SEGUNDOS.
    check("y el plazo por intento respeta el mínimo que Google acepta",
          _opciones is not None and _opciones.timeout == gemini.TIMEOUT_HTTP_MS
          and gemini.TIMEOUT_HTTP_MS >= 10_000,
          f"{getattr(_opciones, 'timeout', None)} ms")
else:
    check("(sin librería de Gemini: no hay cliente que acotar)", True)

# ═════════════════════════════════════════════════════════════════════
print("\n=== El precalentado: que el primer mensaje no pague el import ===")
# Importar la librería de Gemini cuesta segundos, y hasta el 18-ago-2026
# eso ocurría DENTRO del tope de 8 segundos que `interpretar` le da a la
# IA. En una instancia pequeña recién desplegada, el primer cliente que
# escribía se llevaba el menú y el panel decía "Gemini tardó más de 8s",
# como si el modelo fuera lento. No lo era: era el import.

import time as _time                                        # noqa: E402

_t = _time.perf_counter()
gemini.precalentar()
_tardo = _time.perf_counter() - _t
check("precalentar no levanta aunque no haya librería ni clave", True,
      f"{_tardo:.2f}s")

# Lo que de verdad importa: después de precalentar, lo que le queda por
# importar al primer mensaje es nada. Se mide con el reloj, no mirando
# `sys.modules`, porque lo que se protege es el TIEMPO.
_t = _time.perf_counter()
try:
    from google.genai import types as _types                # noqa: E402,F401
    _hay_libreria = True
except ImportError:
    _hay_libreria = False
_despues = _time.perf_counter() - _t

check("tras precalentar, al primer mensaje ya no le cuesta importar",
      _despues < 0.05, f"{_despues:.4f}s"
      + ("" if _hay_libreria else "  (sin librería instalada: plan Básico)"))

# Y llamarlo dos veces no puede costar de nuevo ni romper nada: el
# arranque lo lanza en un hilo, y nada impide que alguien lo repita.
_t = _time.perf_counter()
gemini.precalentar()
check("y repetirlo no vuelve a costar", _time.perf_counter() - _t < 0.05)

# ═════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
if fallos:
    print(f"FALLARON {len(fallos)} verificaciones:")
    for f in fallos:
        print(f"  - {f}")
    sys.exit(1)
print("IA: todas las verificaciones pasaron.")
sys.exit(0)
