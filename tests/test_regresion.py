"""
SUITE DE REGRESIÓN
==================
Verifica el comportamiento del bot sin tocar Meta ni la base real: usa una
base SQLite temporal y reemplaza las funciones de envío de WhatsApp por
unas que solo anotan lo que se habría enviado.

Correr antes de desplegar cualquier cambio:

    python tests/test_regresion.py

Devuelve código de salida 0 si todo pasa, 1 si algo falla (así sirve
también para un pipeline de CI más adelante).

No usa pytest a propósito: así no agrega dependencias al proyecto y la
salida se lee en español, como el resto del código.
"""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

# La base y la clave de admin se definen ANTES de importar config, porque
# config lee las variables de entorno al importarse.
_TMP = tempfile.mkdtemp()
DB_PATH = os.path.join(_TMP, "test_regresion.db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["ADMIN_API_KEY"] = "clave-de-prueba"
# El número del dueño, fijado aquí y no heredado del .env de quien corre
# la suite. Antes lo ponía un defecto de la configuración —un número real
# con formato válido—, y ese defecto ya no existe: sin esto, la suite solo
# pasaba en una máquina con .env. Los envíos están interceptados, así que
# este número no llega nunca a Meta.
if not os.environ.get("OWNER_PHONE_NUMBER"):
    os.environ["OWNER_PHONE_NUMBER"] = "573001234567"

# La raíz del proyecto es la carpeta que contiene tests/, no tests/ misma:
# desde ahí se importan los paquetes app y scripts.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fallos = []
_contador_mensajes = 0
enviados = []


def check(nombre, condicion, extra=""):
    linea = f"  {'[OK]' if condicion else '[X] '} {nombre}{'  ' + extra if extra else ''}"
    try:
        print(linea)
    except UnicodeEncodeError:
        # La consola de Windows usa cp1252 y no sabe imprimir emojis. Los
        # textos del bot llevan varios, así que si aparecen en el detalle
        # de una verificación reventaría la suite entera por un print.
        codificacion = sys.stdout.encoding or "ascii"
        print(linea.encode(codificacion, "replace").decode(codificacion))
    if not condicion:
        fallos.append(nombre)


# Aquí había una prueba que creaba una base con el ESQUEMA VIEJO y
# comprobaba que `init_db` le agregaba las columnas nuevas con ALTER TABLE.
# Se retiró junto con `_migrar_columnas_nuevas`, que es lo que hacía ese
# trabajo: ahora el esquema lo gobierna Alembic (ver migrations/) y ya no
# existe el caso de "actualizar en sitio una base vieja" — la base de
# producción se estrena limpia sobre PostgreSQL.
#
# Lo que sustituye a aquella comprobación está en la sección 1: que el
# esquema nazca ya multi-inquilino y con su cliente inicial sembrado.

from app import config           # noqa: E402
from app.core import database         # noqa: E402
from app.integrations import calendar_service # noqa: E402
from app.integrations import sheets_service   # noqa: E402
from app.bot import bot_logic        # noqa: E402
from app.bot import whatsapp_client  # noqa: E402
from scripts import web_button       # noqa: E402
from app.web import admin_api        # noqa: E402
from fastapi import HTTPException  # noqa: E402

# Interceptamos los envíos: ninguna prueba debe llamar a la API de Meta.
# Se devuelve una respuesta falsa porque el código mira el status_code
# para saber si hace falta reintentar con una plantilla.
class RespuestaFalsa:
    def __init__(self, status_code=200, cuerpo=None):
        self.status_code = status_code
        self._cuerpo = cuerpo or {}
        self.text = str(self._cuerpo)

    def json(self):
        return self._cuerpo


# Los envíos DE VERDAD, guardados antes de sustituirlos por los de
# mentira. Los necesita la comprobación de los topes de Meta: ahí lo que
# se prueba es justamente el código de `whatsapp_client` que los aplica,
# así que hay que hacerlo correr en vez de sustituirlo. Ver más abajo.
ENVIOS_REALES = {
    "texto": whatsapp_client.send_text_message,
    "botones": whatsapp_client.send_button_message,
    "lista": whatsapp_client.send_list_message,
}


def _enviar_texto(to, text, autor="bot"):
    enviados.append(("text", to, text))
    return RespuestaFalsa()


whatsapp_client.send_text_message = _enviar_texto
# Los botones van en la cuarta posición: hay comprobaciones que necesitan
# saber QUÉ opciones se ofrecieron, no solo que hubo botones. Las que ya
# existían indexan [0], [1] y [2], así que añadir un cuarto no las toca.
whatsapp_client.send_button_message = (
    lambda to, text, buttons:
        (enviados.append(("btn", to, text, buttons)), RespuestaFalsa())[-1])
whatsapp_client.send_template_message = (
    lambda to, p, i, v: (enviados.append(("plantilla", to, f"{p}:{v}")), RespuestaFalsa())[-1])
whatsapp_client.send_list_message = (
    lambda to, text, boton, opciones, titulo="Opciones":
        (enviados.append(("list", to, text)), RespuestaFalsa())[-1])

# Tampoco se escribe en el Sheet real: anotamos las filas que se habrían
# agregado para poder verificarlas.
filas_sheet = []
_registrar_real = sheets_service.registrar_lead  # se prueba aparte, más abajo
sheets_service.registrar_lead = (
    lambda tipo, contacto, lead: filas_sheet.append((tipo, contacto, lead)) or True)


def estado(phone):
    s = database.get_session()
    try:
        return s.query(database.Contact).filter_by(phone=phone).first()
    finally:
        s.close()


def msg(text=None, button_id=None, phone="573002222222", mid=None, list_id=None,
        media=None):
    """Simula un mensaje entrante ya parseado por el webhook."""
    global _contador_mensajes
    _contador_mensajes += 1
    bot_logic.handle_incoming_message(
        phone, media["tipo"] if media else "text",
        text=text, button_id=button_id, list_id=list_id, media=media,
        message_id=mid or f"wamid.{_contador_mensajes}",
    )


def historial(phone):
    """Los mensajes guardados de un contacto, del más viejo al más nuevo."""
    s = database.get_session()
    try:
        return (s.query(database.Message).filter_by(phone=phone)
                .order_by(database.Message.id.asc()).all())
    finally:
        s.close()


# ── 1. Esquema multi-inquilino ───────────────────────────────────────

print("\n=== El esquema nace multi-inquilino ===")
database.init_db()

con = sqlite3.connect(DB_PATH)
cols = {r[1] for r in con.execute("PRAGMA table_info(contacts)")}
cols_mensajes = {r[1] for r in con.execute("PRAGMA table_info(messages)")}
tablas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
cliente = con.execute(
    "SELECT id, slug, active FROM clients ORDER BY id").fetchall()
con.close()

for tabla in ("clients", "panel_users", "ia_uso", "processed_messages"):
    check(f"tabla '{tabla}' creada", tabla in tablas)

# `client_id` en todas las tablas del inquilino. Sin esto no se puede
# separar a un negocio de otro, y es lo único que la Fase 1 tenía que
# dejar puesto.
for columna in ("atendido_por_humano", "takeover_at", "origen",
                "servicio", "recorrido", "client_id"):
    check(f"columna '{columna}' en contacts", columna in cols)

for columna in ("media_id", "media_tipo", "media_mime",
                "media_nombre", "media_bytes", "client_id"):
    check(f"columna '{columna}' en messages", columna in cols_mensajes)

# El cliente inicial: sin él, el FK a `clients` deja la base inservible en
# PostgreSQL (en SQLite no se aplica, así que este fallo solo se vería al
# desplegar — que es justo por lo que se comprueba aquí).
check("se siembra exactamente un cliente inicial", len(cliente) == 1,
      f"clientes={cliente!r}")
check("y es el cliente por defecto",
      cliente and cliente[0][0] == database.CLIENTE_POR_DEFECTO)
check("con su slug", cliente and cliente[0][1] == "principal")
check("y activo", cliente and cliente[0][2] == 1)

# Un contacto nuevo tiene que caer sobre ese cliente sin que nadie se lo
# diga: el código todavía no pasa `client_id` en ningún INSERT y es el
# `server_default` el que lo resuelve. Cuando se quite (fin de la Fase 2)
# esta comprobación debe seguir pasando, pero por otra razón.
_s = database.get_session()
try:
    _s.add(database.Contact(phone="573009999999", name="Prueba tenencia"))
    _s.commit()
    _nuevo = _s.query(database.Contact).filter_by(phone="573009999999").first()
    check("un contacto nuevo hereda el cliente por defecto",
          _nuevo.client_id == database.CLIENTE_POR_DEFECTO,
          f"client_id={_nuevo.client_id!r}")
    _s.delete(_nuevo)
    _s.commit()
finally:
    _s.close()

# El mismo teléfono en DOS negocios distintos tiene que poder existir. Es
# LA restricción que rompía el multi-inquilino: `phone` era único global.
_s = database.get_session()
try:
    _s.add(database.Client(id=99, slug="otro-negocio", nombre="Otro negocio"))
    _s.commit()
    _s.add(database.Contact(client_id=database.CLIENTE_POR_DEFECTO,
                            phone="573008888888", name="Cliente de A"))
    _s.add(database.Contact(client_id=99, phone="573008888888",
                            name="Cliente de B"))
    _s.commit()
    _repetidos = _s.query(database.Contact).filter_by(phone="573008888888").count()
    check("el mismo teléfono puede existir en dos negocios", _repetidos == 2,
          f"encontrados={_repetidos}")
except Exception as _e:
    check("el mismo teléfono puede existir en dos negocios", False, str(_e)[:120])
finally:
    _s.rollback()
    _s.query(database.Contact).filter_by(phone="573008888888").delete()
    _s.query(database.Client).filter_by(id=99).delete()
    _s.commit()
    _s.close()

# ── 2. Flujo normal ──────────────────────────────────────────────────

TEL = "573002222222"

print("\n=== Flujo de captación ===")
enviados.clear(); msg("hola")
check("saluda a un contacto nuevo", len(enviados) == 1 and "Bienvenido" in enviados[0][2])
enviados.clear(); msg("Nico")
check("guarda el nombre", estado(TEL).name == "Nico")
check("pregunta la necesidad con una lista", len(enviados) == 1 and enviados[0][0] == "list")

print("\n=== El menú cabe en los límites de WhatsApp ===")
# Si un título se pasa de 24 caracteres WhatsApp lo corta a media palabra,
# y si la lista pasa de 10 filas el envío falla entero.
check("el menú no pasa de 10 opciones", len(config.NEED_OPTIONS) <= 10,
      f"{len(config.NEED_OPTIONS)} opciones")
for _o in config.NEED_OPTIONS:
    check(f"'{_o['title']}' cabe en 24 caracteres", len(_o["title"]) <= 24,
          f"{len(_o['title'])} car")
    check(f"la descripción de '{_o['title']}' cabe en 72",
          len(_o.get("description", "")) <= 72)
check("el botón de la lista cabe en 20 caracteres",
      len(config.NEED_LIST_BUTTON) <= 20, f"{len(config.NEED_LIST_BUTTON)} car")
check("el título de la sección cabe en 24",
      len(config.NEED_LIST_SECTION) <= 24)
check("no hay dos opciones con el mismo id",
      len({_o["id"] for _o in config.NEED_OPTIONS}) == len(config.NEED_OPTIONS))

print("\n=== Los submenús caben en los límites de los BOTONES ===")
# Un botón admite 20 caracteres, no 24 como la lista, y no tiene
# descripción donde meter la frase larga. Además no caben más de 3.
for _padre in config.NEED_OPTIONS:
    _sub = _padre.get("submenu")
    if not _sub:
        continue
    if len(_sub) <= 3:
        for _o in _sub:
            check(f"botón '{_o['title']}' cabe en 20 caracteres",
                  len(_o["title"]) <= 20, f"{len(_o['title'])} car")
    else:
        check(f"el submenú de '{_padre['title']}' no pasa de 10", len(_sub) <= 10)
        for _o in _sub:
            check(f"fila '{_o['title']}' cabe en 24 caracteres", len(_o["title"]) <= 24)

_ids = [o["id"] for o in bot_logic._todas_las_opciones()]
check("no hay ids repetidos en todo el menú", len(_ids) == len(set(_ids)),
      f"{len(_ids)} opciones en total")

print("\n=== Una opción con una acción que no existe ===")
# Es un error de configuración, no del cliente: no puede dejarlo mudo.
config.NEED_OPTIONS.append({
    "id": "opt_rota", "title": "Opción rota",
    "description": "Con una acción que no existe", "accion": "no_existe",
})
enviados.clear(); msg(list_id="opt_rota")
check("le responde algo en vez de dejarlo sin respuesta", len(enviados) >= 1)
check("y lo deja en el menú, no en un estado raro",
      estado(TEL).state == "ASKED_NEED", estado(TEL).state)
config.NEED_OPTIONS.pop()

print("\n=== Una llave rara en un texto NO puede dejar mudo al bot ===")
#
# El dueño escribió algo con llaves en "Ver ejemplos" y el bot dejó de
# responder en esa opción. Parecía que se congelaba.
#
# Era `str.format` sobre un texto que escribe él: format trata TODA
# llave como un hueco suyo, así que "{name}" —que el propio editor
# invita a usar— o un "{9 a 6}" al escribir un horario levantaban un
# KeyError. Y ese KeyError lo recogía en `main` el `except (KeyError,
# IndexError)` puesto para los payloads mal formados de Meta: el
# cliente no recibía NADA y el log culpaba a Meta.
#
# Ahora se rellena con `huecos.rellenar`, que cambia lo que conoce y
# deja lo demás como está. Ver `app/core/huecos.py`.

config.NEED_OPTIONS.append({
    "id": "opt_llaves", "title": "Ver ejemplos", "accion": "info",
    "mensaje": "Hola {name}, abrimos de {9 a 6} con {descuento} de rebaja.",
})

enviados.clear(); msg(list_id="opt_llaves")
_dicho = enviados[-1][2] if enviados else ""
check("responde aunque el texto lleve llaves que nadie declaró",
      len(enviados) >= 1, f"{len(enviados)} mensajes")
check("y rellena el {name}, que es lo que el editor promete",
      "Hola " in _dicho and "{name}" not in _dicho, _dicho[:60])
check("lo que no reconoce lo manda tal cual, sin reventar",
      "{9 a 6}" in _dicho and "{descuento}" in _dicho, _dicho[:80])

# El mismo texto, por el camino de un submenú: antes ni siquiera se
# intentaba rellenar y el cliente leía "Hola {name}".
config.NEED_OPTIONS.append({
    "id": "opt_sub_llaves", "title": "Con submenú", "accion": "submenu",
    "mensaje": "Hola {name}, ¿qué te enseño?", "submenu": [
        {"id": "sub_uno", "title": "Uno", "accion": "info", "mensaje": "Uno."}]})

enviados.clear(); msg(list_id="opt_sub_llaves")
check("el mensaje de un submenú también rellena {name}",
      enviados and "{name}" not in enviados[-1][2],
      enviados[-1][2][:50] if enviados else "(nada)")

config.NEED_OPTIONS.pop(); config.NEED_OPTIONS.pop()

# Y la pieza suelta, que es donde se ve la regla entera.
from app.core.huecos import rellenar as _rellenar               # noqa: E402

check("rellenar nunca revienta, pase lo que pase",
      _rellenar("{a} {sin cerrar {b}", a="1", b="2") == "1 {sin cerrar 2"
      and _rellenar(None) == ""
      and _rellenar("Hola {name}", name=None) == "Hola ",
      repr(_rellenar("{a} {sin cerrar {b}", a="1", b="2")))
check("y no toca lo que no se le nombra",
      _rellenar("{url} y {otro}", url="X") == "X y {otro}")


print("\n=== Una respuesta correcta NO lleva pegado el 'no entendí' ===")
#
# El dueño escribió su texto, marcó "Atrás" y "Menú principal" en "y le
# vuelve a ofrecer…", y al cliente le llegaba:
#
#     Página web creada por nosotros: 👇
#     https://www.neo-redes.com/
#     La tuya se diseña con la identidad de tu negocio.
#
#     Disculpa, no entendí bien 🤔 ¿Puedes elegir una de las opciones…?
#
# O sea: se le contestaba que no se le había entendido a alguien que
# acababa de pulsar un botón y recibir exactamente lo que pidió.
#
# El campo "qué pregunta después" caía en `FALLBACK_MESSAGE` cuando
# estaba vacío. Salía en cuanto una opción tenía a quién ofrecer
# después, así que se destapó al aparecer las salidas fijas: de golpe,
# opciones que nunca habían tenido `luego` lo tenían.

config.NEED_OPTIONS.append({
    "id": "sin_pregunta", "title": "Ver ejemplos", "accion": "info",
    "mensaje": "Página web creada por nosotros.",
    "luego": [bot_logic.ID_VOLVER_MENU]})

enviados.clear(); msg(list_id="sin_pregunta")
_cuerpo = enviados[-1][2]
check("sin pregunta escrita, solo va el texto del dueño",
      _cuerpo == "Página web creada por nosotros.", repr(_cuerpo))
check("y NO se le cuela el 'no entendí'",
      config.FALLBACK_MESSAGE not in _cuerpo)
check("pero los botones siguen saliendo",
      enviados[-1][0] == "btn" and len(enviados[-1][3]) == 1)

config.NEED_OPTIONS[-1]["pregunta"] = "¿Cómo quieres seguir?"
enviados.clear(); msg(list_id="sin_pregunta")
check("con pregunta escrita, esa sí se manda pegada al texto",
      enviados[-1][2].endswith("¿Cómo quieres seguir?"), repr(enviados[-1][2]))

config.NEED_OPTIONS.pop()


print("\n=== 'Menú principal' y 'Atrás' se pueden ofrecer siempre ===")
#
# Antes, en "y le vuelve a ofrecer…" solo se podían marcar las opciones
# HERMANAS. En una rama honda eso deja al cliente sin ninguna forma de
# volver: lee la respuesta y se queda ahí, con el menú principal a dos
# mensajes de distancia y sin ningún botón que lleve. La única salida era
# escribir a mano una opción "volver" en cada grupo, y nadie se acuerda
# de hacerlo en todos.
#
# Las dos salidas fijas no son opciones de ningún menú: las arma el bot,
# así que existen aunque el negocio no tenga nada escrito. "Atrás" lleva
# el sitio del que viene dentro del propio botón
# (`__atras__:web_precios`), y por eso no hace falta guardar nada entre
# mensajes ni una columna nueva.

config.NEED_OPTIONS.append({
    "id": "nav_web", "title": "Páginas web", "accion": "submenu",
    "mensaje": "¿Por dónde empezamos?", "submenu": [
        {"id": "nav_precios", "title": "Ver precios", "accion": "info",
         "mensaje": "Desde 900.000.", "pregunta": "¿Cómo sigues?",
         "luego": [bot_logic.ID_ATRAS, bot_logic.ID_VOLVER_MENU]},
        {"id": "nav_asesor", "title": "Hablar", "accion": "humano"},
    ]})

enviados.clear(); msg(list_id="nav_precios")
_ofrecidos = [b["title"] for b in enviados[-1][3]] if enviados[-1][0] == "btn" else []
check("después de una respuesta se pueden ofrecer las dos salidas fijas",
      config.BOTON_VOLVER_MENU in _ofrecidos and config.BOTON_ATRAS in _ofrecidos,
      str(_ofrecidos))

# El id que se le manda a Meta lleva pegado de dónde viene: eso es lo
# que hace que "Atrás" sepa a qué grupo volver sin recordar nada.
_id_atras = next(b["id"] for b in enviados[-1][3]
                 if b["title"] == config.BOTON_ATRAS)
check("el botón Atrás se lleva dentro el sitio del que viene",
      _id_atras == bot_logic.ID_ATRAS + ":" + "nav_precios", _id_atras)

enviados.clear(); msg(button_id=_id_atras)
check("y al pulsarlo vuelve al grupo del que venía, con su mismo texto",
      enviados and "¿Por dónde empezamos?" in enviados[-1][2],
      enviados[-1][2][:40] if enviados else "(nada)")
check("con las opciones de ese grupo, no con otras",
      sorted(b["title"] for b in enviados[-1][3]) == ["Hablar", "Ver precios"],
      str([b["title"] for b in enviados[-1][3]]))

enviados.clear(); msg(button_id=bot_logic.ID_VOLVER_MENU)
check("'Menú principal' devuelve al menú de arriba",
      enviados and any(b["title"] == "Páginas web"
                       for b in (enviados[-1][3] if enviados[-1][0] == "btn" else [])
                       ) or enviados[-1][0] == "list",
      str(enviados[-1][:3])[:70])

# Desde una opción de PRIMER nivel no hay grupo encima: atrás es el menú.
config.NEED_OPTIONS.append({
    "id": "nav_suelta", "title": "Suelta", "accion": "info",
    "mensaje": "Algo.", "luego": [bot_logic.ID_ATRAS]})
enviados.clear(); msg(list_id="nav_suelta")
_id_atras2 = next(b["id"] for b in enviados[-1][3]
                  if b["title"] == config.BOTON_ATRAS)
enviados.clear(); msg(button_id=_id_atras2)
check("desde el primer nivel, 'Atrás' lleva al menú principal",
      len(enviados) >= 1, str(enviados[-1][:3])[:70])

# Y lo que sostiene todo: existen aunque el negocio no tenga nada escrito.
check("las dos salidas existen sin que el negocio las declare",
      bot_logic._opcion_fija(bot_logic.ID_VOLVER_MENU)["accion"] == "menu"
      and bot_logic._opcion_fija(bot_logic.ID_ATRAS, "x")["accion"] == "atras"
      and bot_logic._opcion_fija("otra_cosa") is None)

config.NEED_OPTIONS.pop(); config.NEED_OPTIONS.pop()


print("\n=== Lo que el cliente ESCRIBE se entiende, esté donde esté ===")
#
# 13-sep-2026, dicho por el dueño: el bot contestaba "no entendí", el
# cliente escribía "Quiero una página web" —casi letra por letra el botón
# que tenía delante— y el bot repetía "no entendí". Sin IA no se miraba el
# texto en absoluto, y "no entendí" salía sin ningún botón debajo, así que
# no había forma de salir de ahí más que adivinando.

from app.bot.cerebro import menu as _entender  # noqa: E402

_opts = [{"id": "w", "title": "Crear mi página web"},
         {"id": "wp", "title": "Precios página web"},
         {"id": "e1", "title": "Ver ejemplos"},
         {"id": "e2", "title": "Ver ejemplos"},
         {"id": "fin", "title": "No, gracias"}]
check("reconoce el título de un botón escrito con otras palabras alrededor",
      _entender.interpretar(None, "Quiero una pagina web", _opts).intencion == "w")
check("sin tildes, en plural y sin el verbo del botón también",
      _entender.interpretar(None, "PÁGINAS WEB", _opts).intencion == "w")
check("entre dos que encajan, gana la más concreta",
      _entender.interpretar(None, "precios de pagina web", _opts).intencion == "wp")
check("si dos se llaman igual NO adivina",
      _entender.interpretar(None, "ver ejemplos", _opts).intencion is None)
check("un 'no' suelto no elige el botón que despide al cliente",
      _entender.interpretar(None, "no entiendo nada", _opts).intencion is None)
check("un saludo no elige nada",
      _entender.interpretar(None, "hola buenas", _opts).intencion is None)

T_ESCRIBE = "573007770001"
msg("hola", phone=T_ESCRIBE); msg("Lucia", phone=T_ESCRIBE)

enviados.clear(); msg("asdf qwerty", phone=T_ESCRIBE)
check("el 'no entendí' va con el menú debajo, en UN solo mensaje",
      len(enviados) == 1 and enviados[0][0] in ("list", "btn"),
      str([e[:1] for e in enviados]))
check("y lleva la frase y la pregunta de continuar",
      enviados and config.FALLBACK_MESSAGE in enviados[-1][2]
      and config.NO_ENTENDI_MENU_MESSAGE in enviados[-1][2],
      repr(enviados[-1][2][:80]) if enviados else "(nada)")

enviados.clear(); msg("Quiero una página web", phone=T_ESCRIBE)
check("después, escribir el botón hace lo que hace el botón",
      enviados and "empezar" in enviados[-1][2],
      repr(enviados[-1][2][:60]) if enviados else "(nada)")
check("y queda anotado como si lo hubiera pulsado",
      estado(T_ESCRIBE).servicio == "opt_web")

# Volver al menú desde un sitio donde el texto se tomaba como otra cosa: el
# bot le acaba de pedir que cuente su consulta.
enviados.clear(); msg(button_id="web_asesor", phone=T_ESCRIBE)
check("'Hablar con un asesor' pide la consulta, como siempre",
      estado(T_ESCRIBE).state == "ASKING_OTHER_DETAIL")
enviados.clear(); msg("mejor quiero volver al menú", phone=T_ESCRIBE)
_c = estado(T_ESCRIBE)
check("'volver al menú' vale ahí también, y NO se toma como la consulta",
      _c.state == "ASKED_NEED" and not _c.atendido_por_humano,
      f"state={_c.state}")

# Pero "menú" dentro de una frase de negocio es una consulta, no una orden.
msg(button_id="web_asesor", phone=T_ESCRIBE)
msg("quiero cambiar el menú de mi restaurante", phone=T_ESCRIBE)
check("'el menú de mi restaurante' es una consulta, no volver al menú",
      estado(T_ESCRIBE).atendido_por_humano is True)
bot_logic.devolver_control_al_bot(T_ESCRIBE)

enviados.clear(); msg("Menú", phone=T_ESCRIBE)
check("'Menú' a secas lo devuelve al menú aunque la conversación esté cerrada",
      enviados and enviados[-1][0] in ("list", "btn")
      and estado(T_ESCRIBE).state == "ASKED_NEED")

# El negocio puede quitar el menú de debajo del "no entendí".
_base = config.base()
_base.MENU_TRAS_NO_ENTENDI = False
enviados.clear(); msg("asdf qwerty", phone=T_ESCRIBE)
check("sin el ajuste, solo la frase",
      len(enviados) == 1 and enviados[0][0] == "text")
_base.MENU_TRAS_NO_ENTENDI = True

print("\n=== 'Pasar a una persona' puede no pedir la consulta otra vez ===")
#
# "Si alguien hizo clic para hablar con un humano ya siguió un paso a paso:
# ya sabemos qué quiere". Pedirle que lo cuente otra vez era un mensaje de
# más —y desde el 1-oct-2026, uno que Meta cobra—.

T_DIRECTO = "573007770002"
msg("hola", phone=T_DIRECTO); msg("Mateo", phone=T_DIRECTO)
msg(list_id="opt_web", phone=T_DIRECTO)
_base.ASESOR_PIDE_DETALLE = False
enviados.clear(); msg(button_id="web_asesor", phone=T_DIRECTO)
_c = estado(T_DIRECTO)
check("sin pedir detalle, avisa y calla al bot al primer toque",
      _c.atendido_por_humano is True, f"state={_c.state}")
check("y le dice al cliente el texto de 'directo', con su nombre",
      any(e[1] == T_DIRECTO and "Mateo" in e[2]
          and "unos momentos" in e[2] for e in enviados),
      str([e[2][:40] for e in enviados if e[1] == T_DIRECTO]))
check("NO le pide que cuente su consulta",
      not any(config.OTHER_QUERY_MESSAGE in e[2] for e in enviados))

_s = database.get_session()
try:
    _lead = (_s.query(database.Lead).join(database.Contact,
             database.Lead.contact_id == database.Contact.id)
             .filter(database.Contact.phone == T_DIRECTO)
             .order_by(database.Lead.id.desc()).first())
finally:
    _s.close()
check("el aviso dice qué botón pulsó y en qué servicio",
      _lead is not None and "Hablar con un asesor" in (_lead.detail or "")
      and "página web" in (_lead.detail or "").lower(),
      repr(_lead.detail if _lead else None))
_base.ASESOR_PIDE_DETALLE = True
bot_logic.devolver_control_al_bot(T_DIRECTO)


print("\n=== Pasarse de los topes de Meta NO puede dejar mudo al bot ===")
#
# "Página web → Ver ejemplos: en superadmin hay texto y en el chat no
# llega nada". El texto estaba bien guardado; lo que fallaba era el
# ENVÍO.
#
# Si un payload se pasa de los topes de la Cloud API, Meta **descarta el
# mensaje entero** y devuelve un 400. No manda una versión corta: no
# manda nada. Y el bot no se entera —no hay excepción— así que el
# cliente pulsa un botón y no pasa absolutamente nada.
#
# Había cuatro formas de caer ahí, todas al alcance de quien escribe
# textos en /superadmin sin saber que existen topes:
#
#   · el mensaje de un submenú de más de 1024 caracteres
#   · un título de botón de más de 20 (¡el editor decía 24!)
#   · un texto suelto de más de 4096
#   · un grupo cuyas opciones se esconden todas → 0 botones
#
# Los topes se aplican ahora en `whatsapp_client`, que es el único sitio
# que habla con Meta. Se prefiere PARTIR a recortar: lo escribió el dueño
# para que su cliente lo lea.

_enviados_wa = []


def _post_falso(payload):
    """Valida como valida Meta: si algo se pasa, 400 y no llega nada."""
    class _R:
        def __init__(self, code): self.status_code = code; self.text = "límite"
    tipo = payload.get("type")
    if tipo == "text":
        if len(payload["text"]["body"]) > 4096:
            return _R(400)
        _enviados_wa.append(("texto", payload["text"]["body"]))
        return _R(200)

    inter = payload["interactive"]
    if len(inter["body"]["text"]) > 1024:
        return _R(400)
    if inter["type"] == "button":
        botones = inter["action"]["buttons"]
        if not 1 <= len(botones) <= 3:
            return _R(400)
        if any(len(b["reply"]["title"]) > 20 for b in botones):
            return _R(400)
        _enviados_wa.append(("botones", inter["body"]["text"]))
        return _R(200)

    filas = inter["action"]["sections"][0]["rows"]
    if not 1 <= len(filas) <= 10 or any(len(f["title"]) > 24 for f in filas):
        return _R(400)
    _enviados_wa.append(("lista", inter["body"]["text"]))
    return _R(200)


_post_real = whatsapp_client._post
_texto_real = ENVIOS_REALES["texto"]
_boton_real = ENVIOS_REALES["botones"]
_lista_real = ENVIOS_REALES["lista"]
from app.core import message_log as _mlog                       # noqa: E402
_registrar_real_log = _mlog.registrar

# Se restauran los envíos DE VERDAD y se sustituye solo el `_post`: lo
# que se prueba es justo el código de `whatsapp_client` que aplica los
# topes, así que sustituirlo entero —como hace el resto de la suite— no
# probaría nada.
whatsapp_client._post = _post_falso
whatsapp_client.send_text_message = _texto_real
whatsapp_client.send_button_message = _boton_real
whatsapp_client.send_list_message = _lista_real
_mlog.registrar = lambda *a, **k: None


def _entrega(fn, *args, **kwargs):
    _enviados_wa.clear()
    fn(*args, **kwargs)
    return list(_enviados_wa)


check("un texto de más de 4096 se parte y llega entero",
      len(_entrega(whatsapp_client.send_text_message, TEL, "Ejemplos. " * 500)) >= 2)
check("un botón con el título largo se manda igual, recortado",
      len(_entrega(whatsapp_client.send_button_message, TEL, "Mira:",
                   [{"id": "a", "title": "Ver la tienda de ropa completa"}])) == 1)
check("un cuerpo de más de 1024 con botones se parte en vez de perderse",
      len(_entrega(whatsapp_client.send_button_message, TEL, "Hola. " * 300,
                   [{"id": "a", "title": "Uno"}])) >= 2)
check("más de 3 botones no tumban el mensaje",
      len(_entrega(whatsapp_client.send_button_message, TEL, "Mira:",
                   [{"id": str(i), "title": f"B{i}"} for i in range(6)])) == 1)
check("sin ninguna opción se manda el texto en vez de nada",
      _entrega(whatsapp_client.send_button_message, TEL, "Mira:", []) ==
      [("texto", "Mira:")])
check("una lista con el cuerpo largo también se parte",
      len(_entrega(whatsapp_client.send_list_message, TEL, "Hola. " * 300, "Ver",
                   [{"id": "a", "title": "Uno"}])) >= 2)

# Y el recorrido de verdad: la opción que el dueño describió.
config.NEED_OPTIONS.append({
    "id": "opt_ejemplos", "title": "Ver ejemplos", "accion": "submenu",
    "mensaje": "Estos son los sitios que hemos hecho. " * 40,   # > 1024
    "submenu": [{"id": "ej_uno", "title": "Ver la tienda de ropa completa",
                 "accion": "info", "mensaje": "Aquí la tienes."}],
})
_enviados_wa.clear()
msg(list_id="opt_ejemplos")
check("'Ver ejemplos' con un texto largo y un botón largo SÍ entrega",
      len(_enviados_wa) >= 1, f"{len(_enviados_wa)} mensajes entregados")
config.NEED_OPTIONS.pop()

whatsapp_client._post = _post_real
whatsapp_client.send_text_message = _enviar_texto
whatsapp_client.send_button_message = (
    lambda to, text, buttons:
        (enviados.append(("btn", to, text, buttons)), RespuestaFalsa())[-1])
whatsapp_client.send_list_message = (
    lambda to, text, boton, opciones, titulo="Opciones":
        (enviados.append(("list", to, text)), RespuestaFalsa())[-1])
_mlog.registrar = _registrar_real_log


print("\n=== Opciones que se esconden mientras no tienen contenido ===")
_pbi = next(o for o in config.NEED_OPTIONS if o["id"] == "opt_powerbi")
_demo = next(o for o in _pbi["submenu"] if o["id"] == "powerbi_demo")
_precios_pbi = next(o for o in _pbi["submenu"] if o["id"] == "powerbi_precios")

_demo_url = _demo["url"]

_demo["url"] = ""
check("sin URL de ejemplo, ese botón no se ofrece en ningún sitio",
      _demo not in bot_logic._opciones_para_mostrar([_demo], incluir_ocultas=True))

_demo["url"] = _demo_url
check("con la URL puesta, el botón sí se ofrece",
      _demo in bot_logic._opciones_para_mostrar([_demo], incluir_ocultas=True),
      _demo_url)
check("aun con URL, el ejemplo no sale en el menú de arriba de Power BI",
      _demo not in bot_logic._opciones_para_mostrar(_pbi["submenu"]))
_demo["url"] = _demo_url

_txt_pbi = _precios_pbi["mensaje"]
_precios_pbi["mensaje"] = ""
check("sin precios escritos, 'ver planes' no se ofrece",
      _precios_pbi not in bot_logic._opciones_para_mostrar(_pbi["submenu"]))
_precios_pbi["mensaje"] = "• *Plan* $1\n{url}"
check("al escribir los precios la opción aparece sola",
      _precios_pbi in bot_logic._opciones_para_mostrar(_pbi["submenu"]))

T_PBI = "573005554433"
msg("hola", phone=T_PBI); msg("Ruben", phone=T_PBI)
enviados.clear(); msg(list_id="opt_powerbi", phone=T_PBI)
check("Power BI abre su submenú en botones", any(t[0] == "btn" for t in enviados))
enviados.clear(); msg(button_id="powerbi_precios", phone=T_PBI)
check("los precios de Power BI llegan al cliente",
      any("Plan" in t[2] for t in enviados))
check("y después ofrece el ejemplo, agendar y asesor",
      any(t[0] == "btn" for t in enviados))
_precios_pbi["mensaje"] = _txt_pbi

# Nunca más de 3 en un grupo que se manda como botones: con 4 WhatsApp
# rechaza el envío entero.
for _padre in bot_logic._todas_las_opciones():
    _visibles = bot_logic._opciones_para_mostrar(_padre.get("submenu", []))
    if _visibles:
        check(f"el submenú visible de '{_padre['title']}' es mandable",
              len(_visibles) <= 10, f"{len(_visibles)} opciones")
    _luego = bot_logic._opciones_para_mostrar(
        [bot_logic._opcion_elegida(i) for i in _padre.get("luego", []) or []
         if bot_logic._opcion_elegida(i)], incluir_ocultas=True)
    if _luego:
        check(f"lo que ofrece '{_padre['title']}' tras su mensaje es mandable",
              len(_luego) <= 10, f"{len(_luego)} opciones")

print("\n=== Recorrido del cliente y pestaña del Sheet ===")
T_REC = "573006665544"
msg("hola", phone=T_REC); msg("Marcela", phone=T_REC)

msg(list_id="opt_powerbi", phone=T_REC)
check("al elegir servicio se recuerda cuál fue",
      estado(T_REC).servicio == "opt_powerbi")
check("y el recorrido empieza limpio", not estado(T_REC).recorrido)

msg(button_id="powerbi_precios", phone=T_REC)
check("ver precios queda anotado en el recorrido",
      estado(T_REC).recorrido == "Vio precios", str(estado(T_REC).recorrido))

msg(button_id="powerbi_precios", phone=T_REC)
check("tocar dos veces lo mismo no lo repite",
      estado(T_REC).recorrido == "Vio precios", str(estado(T_REC).recorrido))

filas_sheet.clear()
msg(button_id="powerbi_asesor", phone=T_REC)
msg("necesito ver ventas por mes", phone=T_REC)
check("el recorrido acumula los pasos en orden",
      estado(T_REC).recorrido == "Vio precios > Pidió asesor",
      str(estado(T_REC).recorrido))
check("la fila va a la pestaña de Power BI, no a una genérica",
      [t for t, _, _ in filas_sheet] == ["powerbi"],
      str([t for t, _, _ in filas_sheet]))
_c_sheet = filas_sheet[0][1]
check("la fila lleva el nombre del servicio, legible",
      _c_sheet["servicio"] == "Tablero en Power BI", str(_c_sheet["servicio"]))
check("y el recorrido completo",
      _c_sheet["recorrido"] == "Vio precios > Pidió asesor")
check("el mensaje del cliente viaja en el lead",
      "ventas por mes" in (filas_sheet[0][2].get("detail") or ""))
bot_logic.devolver_control_al_bot(T_REC)

# Cambiar de servicio no puede arrastrar el recorrido del anterior: la
# fila describiría a alguien que no existe.
T_CAMBIA = "573006665533"
msg("hola", phone=T_CAMBIA); msg("Julián", phone=T_CAMBIA)
msg(list_id="opt_powerbi", phone=T_CAMBIA)
msg(button_id="powerbi_precios", phone=T_CAMBIA)
check("va acumulando en el primer servicio",
      estado(T_CAMBIA).recorrido == "Vio precios")

msg(list_id="opt_chatbot", phone=T_CAMBIA)
check("al cambiar de servicio, el recorrido empieza de cero",
      estado(T_CAMBIA).servicio == "opt_chatbot" and not estado(T_CAMBIA).recorrido,
      f"{estado(T_CAMBIA).servicio} / {estado(T_CAMBIA).recorrido}")

print("\n=== Quien nunca elige un servicio ===")
T_SIN_SERV = "573006665500"
filas_sheet.clear()
msg("hola", phone=T_SIN_SERV); msg("Pedro", phone=T_SIN_SERV)
msg("quiero hablar con un asesor", phone=T_SIN_SERV)
check("cae en la pestaña de otras consultas",
      [t for t, _, _ in filas_sheet] == ["otros"],
      str([t for t, _, _ in filas_sheet]))
check("y su fila no inventa un servicio",
      filas_sheet[0][1]["servicio"] == "")
bot_logic.devolver_control_al_bot(T_SIN_SERV)

print("\n=== Submenú del chatbot ===")
T_SUB = "573007776655"
msg("hola", phone=T_SUB); msg("Laura", phone=T_SUB)
enviados.clear(); msg(list_id="opt_chatbot", phone=T_SUB)
check("el chatbot abre un submenú de botones, no pide detalle",
      any(t[0] == "btn" for t in enviados))
check("sigue esperando que elija", estado(T_SUB).state == "ASKED_NEED")

enviados.clear(); msg(button_id="chatbot_precios", phone=T_SUB)
_textos = [t[2] for t in enviados]
check("'ver planes y precios' manda los tres planes",
      all(p in " ".join(_textos)
          for p in ("ChatBot Básico", "Chatbot Pro", "Agente IA Pro")))
check("manda los precios de instalación y mensualidad",
      all(v in " ".join(_textos)
          for v in ("$300.000", "$100.000", "$600.000", "$150.000",
                    "$800.000", "$200.000")))
check("dice que se personalizan según la necesidad",
      any("personalizan" in t for t in _textos))
check("incluye el enlace al detalle de costos",
      any(config.PRICING_URL in t for t in _textos))
check("y después ofrece cómo seguir, en botones",
      any(t[0] == "btn" for t in enviados))
check("sigue esperando que elija", estado(T_SUB).state == "ASKED_NEED")

# EN UN SOLO MENSAJE. Antes salian dos —el texto y luego los botones—, y
# preguntar precios es lo mas comun que hace un cliente. Desde el
# 1-oct-2026 Meta cobra por mensaje: ese segundo envio era una linea del
# recibo de cada cliente, todos los dias.
check("y todo eso va en UN mensaje, no en dos",
      len(enviados) == 1 and enviados[0][0] == "btn",
      f"{len(enviados)} mensajes: {[e[0] for e in enviados]}")

# El otro lado del mismo trato. El cuerpo de un mensaje interactivo
# admite 1024 caracteres y un texto suelto 4096: pasarse NO recorta, Meta
# rechaza el mensaje entero y el cliente se queda sin nada. Con un texto
# largo el bot tiene que volver a partir en dos.
# Se toca la OPCION, no `config`: el texto ya esta resuelto dentro de
# ella cuando se arma el menu, asi que cambiar `config.CHATBOT_PRICING_
# MESSAGE` a estas alturas no cambia lo que manda el bot. Es la trampa
# que el CLAUDE.md advierte, y aqui muerde.
_opcion_precios = bot_logic._opcion_elegida("chatbot_precios")
_precio_original = _opcion_precios["mensaje"]
_opcion_precios["mensaje"] = "Precios muy detallados. " * 60   # ~1440

T_LARGO = "573007770001"
msg("hola", phone=T_LARGO); msg("Tere", phone=T_LARGO)
msg(list_id="opt_chatbot", phone=T_LARGO)
enviados.clear(); msg(button_id="chatbot_precios", phone=T_LARGO)

check("con un texto que no cabe en el cuerpo, vuelve a partir en dos",
      len(enviados) == 2, f"{len(enviados)} mensajes")
check("y el cliente recibe el texto entero igualmente",
      any("Precios muy detallados" in (t[2] or "") for t in enviados))
check("ningun envio se pasa del tope de un mensaje interactivo",
      all(len(t[2] or "") <= 1024
          for t in enviados if t[0] in ("btn", "list")),
      str([len(t[2] or "") for t in enviados]))

_opcion_precios["mensaje"] = _precio_original

# Las viñetas no pueden ser "*": WhatsApp emparejaría unos asteriscos con
# otros y pondría en negrita medio mensaje.
_precios = config.CHATBOT_PRICING_MESSAGE
check("ninguna línea de precios empieza con un asterisco suelto",
      not any(l.lstrip().startswith("* ") for l in _precios.split("\n")))
check("los asteriscos de negrita están emparejados",
      _precios.count("*") % 2 == 0, f"{_precios.count('*')} asteriscos")
check("el mensaje cabe en un solo envío de WhatsApp",
      len(_precios) <= 4096, f"{len(_precios)} de 4096 car")

# Los botones de "luego" se referencian por id: si alguien renombra un id
# en config sin actualizar la referencia, el cliente se queda sin salida.
for _padre in bot_logic._todas_las_opciones():
    for _ref in _padre.get("luego", []):
        check(f"'{_padre['title']}' apunta a un id que existe: {_ref}",
              bot_logic._opcion_elegida(_ref) is not None)

enviados.clear(); msg(button_id="chatbot_asesor", phone=T_SUB)
enviados.clear(); msg("quiero saber si sirve para mi negocio", phone=T_SUB)
_c = estado(T_SUB)
check("'hablar con un asesor' calla al bot y avisa al dueño",
      _c.atendido_por_humano is True, f"state={_c.state}")
enviados.clear(); msg("hola?", phone=T_SUB)
check("y el bot ya no responde ahí", len(enviados) == 0)
bot_logic.devolver_control_al_bot(T_SUB)

print("\n=== Opción de enlace a la web ===")
T_WEB = "573009998877"
msg("hola", phone=T_WEB); msg("Sofia", phone=T_WEB)
enviados.clear(); msg(list_id="opt_web_nitro", phone=T_WEB)
check("responde con la dirección de la web",
      any(config.BUSINESS_WEBSITE in t[2] for t in enviados))
check("deja el menú abierto para elegir otra cosa",
      estado(T_WEB).state == "ASKED_NEED")
enviados.clear(); msg(list_id="opt_powerbi", phone=T_WEB)
check("y de hecho puede elegir otra opción sin reiniciar",
      estado(T_WEB).servicio == "opt_powerbi" and any(t[0] == "btn" for t in enviados))

print("\n=== Elegir algo que no está en el menú ===")
T_RARO = "573009998866"
msg("hola", phone=T_RARO); msg("Diego", phone=T_RARO)
enviados.clear(); msg(list_id="opt_que_ya_no_existe", phone=T_RARO)
check("responde el mensaje de 'no entendí'",
      any("no entendí" in t[2] for t in enviados))
check("y no lo saca del menú", estado(T_RARO).state == "ASKED_NEED")

print("\n=== Cálculo de horarios libres (sin llamar a Google) ===")
from datetime import date as _date, time as _time  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

ZONA = ZoneInfo(config.BUSINESS_TIMEZONE)
LUNES = _date(2026, 8, 10)      # lunes, laborable
DOMINGO = _date(2026, 8, 9)     # domingo, no laborable
MADRUGADA = datetime.combine(LUNES, _time(0, 0), tzinfo=ZONA)   # nada ha pasado aún


def dt(fecha, h, m=0):
    return datetime.combine(fecha, _time(h, m), tzinfo=ZONA)


libres = calendar_service._slots_del_dia(LUNES, [], MADRUGADA)
check("un día vacío ofrece toda la jornada",
      len(libres) == 9 and libres[0] == dt(LUNES, 9) and libres[-1] == dt(LUNES, 17),
      f"{len(libres)} slots, de {libres[0].strftime('%H:%M')} a {libres[-1].strftime('%H:%M')}")

check("no ofrece nada en día no laborable",
      calendar_service._slots_del_dia(DOMINGO, [], MADRUGADA) == [])

ocupado = [(dt(LUNES, 10), dt(LUNES, 11))]
libres = calendar_service._slots_del_dia(LUNES, ocupado, MADRUGADA)
check("excluye los horarios ya ocupados",
      dt(LUNES, 10) not in libres
      and dt(LUNES, 9) in libres and dt(LUNES, 11) in libres)

solapado = [(dt(LUNES, 10, 15), dt(LUNES, 10, 20))]
libres = calendar_service._slots_del_dia(LUNES, solapado, MADRUGADA)
check("un evento corto bloquea el slot que lo contiene",
      dt(LUNES, 10) not in libres and dt(LUNES, 11) in libres)

pegado = [(dt(LUNES, 9), dt(LUNES, 10))]
libres = calendar_service._slots_del_dia(LUNES, pegado, MADRUGADA)
check("un evento que termina justo cuando empieza otro slot no lo bloquea",
      dt(LUNES, 10) in libres and dt(LUNES, 9) not in libres)

libres = calendar_service._slots_del_dia(LUNES, [], dt(LUNES, 14))
check("no ofrece horarios que ya pasaron",
      all(s > dt(LUNES, 14) for s in libres) and dt(LUNES, 9) not in libres)

libres = calendar_service._slots_del_dia(LUNES, [], dt(LUNES, 14))
minimo = dt(LUNES, 14) + timedelta(minutes=config.APPOINTMENT_MIN_NOTICE_MINUTES)
check("respeta la anticipación mínima", all(s >= minimo for s in libres),
      f"primero={libres[0].strftime('%H:%M')} minimo={minimo.strftime('%H:%M')}")

check("formatea la hora en 12h", calendar_service.formatear_hora(dt(LUNES, 15, 30)) == "3:30 pm"
      and calendar_service.formatear_hora(dt(LUNES, 9, 0)) == "9:00 am")
check("formatea el día en español",
      calendar_service.formatear_dia(LUNES) == "Lunes 10 de agosto",
      calendar_service.formatear_dia(LUNES))
check("el día corto cabe en 24 caracteres (límite de las listas)",
      all(len(calendar_service.formatear_dia_corto(_date(2026, m, 28))) <= 24
          for m in range(1, 13)))

print("\n=== Rama de cita con Google simulado ===")

# Sustituimos las llamadas a Google por respuestas fijas: la suite no
# debe depender de la red ni crear eventos reales en el calendario.
DIA = _date(2026, 8, 10)
eventos_creados = []
_google = {"dias": [(DIA, 3)], "horarios": [dt(DIA, 9), dt(DIA, 11), dt(DIA, 15)],
           "libre": True, "falla": False}


def _falso_dias():
    if _google["falla"]: raise calendar_service.CalendarNoDisponible("simulado")
    return _google["dias"]


def _falsos_horarios(fecha):
    if _google["falla"]: raise calendar_service.CalendarNoDisponible("simulado")
    return _google["horarios"]


def _falso_sigue_libre(inicio):
    if _google["falla"]: raise calendar_service.CalendarNoDisponible("simulado")
    return _google["libre"]


def _falso_crear(nombre, telefono, inicio, detalle=None):
    if _google["falla"]: raise calendar_service.CalendarNoDisponible("simulado")
    eventos_creados.append((nombre, telefono, inicio))
    return f"evt_{inicio.isoformat()}"


calendar_service.dias_con_disponibilidad = _falso_dias
calendar_service.horarios_libres = _falsos_horarios
calendar_service.sigue_libre = _falso_sigue_libre
calendar_service.crear_evento = _falso_crear

# El agendamiento se llega desde el submenú del chatbot ("Agendar una
# reunión"). Como los ids son únicos en todo el menú, se puede tocar esa
# opción directamente sin pasar antes por el submenú.
T_CITA = "573004444444"
msg("hola", phone=T_CITA); msg("Ana", phone=T_CITA)
enviados.clear(); msg(button_id="chatbot_reunion", phone=T_CITA)
check("ofrece los días como lista", any(t[0] == "list" for t in enviados))
check("queda esperando el día", estado(T_CITA).state == "ASKING_DATE")

enviados.clear(); msg(list_id=f"dia_{DIA.isoformat()}", phone=T_CITA)
check("ofrece los horarios como botones", any(t[0] == "btn" for t in enviados))
check("guarda el día elegido",
      estado(T_CITA).state == "ASKING_TIME" and estado(T_CITA).temp_data == DIA.isoformat())

enviados.clear(); msg(button_id=f"hora_{dt(DIA, 11).isoformat()}", phone=T_CITA)
check("crea el evento en el calendario",
      len(eventos_creados) == 1 and eventos_creados[0][2] == dt(DIA, 11))
check("limpia temp_data al terminar", estado(T_CITA).temp_data is None)
check("y ofrece volver al menú o terminar",
      any(t[0] == "btn" for t in enviados) and estado(T_CITA).state == "ASKED_NEED")
check("confirma al cliente con día y hora",
      any("11:00 am" in t[2] and "Lunes 10 de agosto" in t[2]
          for t in enviados if t[1] == T_CITA))
check("avisa al dueño", any(t[1] == config.OWNER_PHONE_NUMBER for t in enviados))

s = database.get_session()
cita = s.query(database.Lead).filter_by(type="cita").first()
check("el lead guarda el ID del evento de Google",
      cita is not None and cita.google_event_id == f"evt_{dt(DIA, 11).isoformat()}",
      f"event_id={cita.google_event_id if cita else None!r}")
check("el lead guarda fecha y hora legibles",
      cita.appointment_date == "Lunes 10 de agosto" and cita.appointment_time == "11:00 am")
s.close()

print("\n=== Un día con muchos horarios libres ===")
# Antes iban siempre como botones y WhatsApp solo admite 3: de un día
# entero libre el cliente solo veía los tres primeros de la mañana.
_horarios_pocos = _google["horarios"]
_google["horarios"] = [dt(DIA, h, m) for h in range(9, 18) for m in (0, 30)]  # 18 huecos

T_MUCHOS = "573004446000"
msg("hola", phone=T_MUCHOS); msg("Tomás", phone=T_MUCHOS)
msg(list_id="opt_chatbot", phone=T_MUCHOS)
msg(button_id="chatbot_reunion", phone=T_MUCHOS)
enviados.clear(); msg(list_id=f"dia_{DIA.isoformat()}", phone=T_MUCHOS)
check("con más de 3 huecos los manda como lista, no como botones",
      any(t[0] == "list" for t in enviados) and not any(t[0] == "btn" for t in enviados))
check("nunca pasa del tope de filas de WhatsApp",
      config.APPOINTMENT_SLOTS_OFFERED <= 10, str(config.APPOINTMENT_SLOTS_OFFERED))

# Con la duración configurada, ¿cabe un día entero en una sola lista? Si
# alguien acorta las citas y deja de caber, esto avisa antes de desplegar.
_ini = _time(*[int(x) for x in config.BUSINESS_HOURS_START.split(":")])
_fin = _time(*[int(x) for x in config.BUSINESS_HOURS_END.split(":")])
_minutos_dia = (_fin.hour * 60 + _fin.minute) - (_ini.hour * 60 + _ini.minute)
_huecos_dia = _minutos_dia // config.APPOINTMENT_DURATION_MINUTES
check("un día entero libre cabe en la lista de horarios",
      _huecos_dia <= config.APPOINTMENT_SLOTS_OFFERED,
      f"{_huecos_dia} huecos vs {config.APPOINTMENT_SLOTS_OFFERED} que se muestran")

check("la duración se le dice al cliente en palabras",
      config._duracion_en_palabras(60) == "1 hora"
      and config._duracion_en_palabras(120) == "2 horas"
      and config._duracion_en_palabras(30) == "30 minutos")

# La respuesta de una lista llega en list_id, no en button_id: si el
# código solo mirase button_id, elegir la hora no haría nada.
enviados.clear()
msg(list_id=f"hora_{dt(DIA, 14).isoformat()}", phone=T_MUCHOS)
check("elegir la hora desde la lista sí agenda",
      any("2:00 pm" in t[2] for t in enviados if t[1] == T_MUCHOS),
      str([t[2][:40] for t in enviados if t[1] == T_MUCHOS]))

# Y con 3 o menos se siguen viendo directo en el chat, sin toque extra.
_google["horarios"] = [dt(DIA, 9), dt(DIA, 10)]
T_POCOS = "573004446001"
msg("hola", phone=T_POCOS); msg("Lucía", phone=T_POCOS)
msg(list_id="opt_chatbot", phone=T_POCOS)
msg(button_id="chatbot_reunion", phone=T_POCOS)
enviados.clear(); msg(list_id=f"dia_{DIA.isoformat()}", phone=T_POCOS)
check("con 3 o menos se siguen mandando como botones",
      any(t[0] == "btn" for t in enviados))
_google["horarios"] = _horarios_pocos

print("\n=== Doble-booking: el horario se ocupó mientras el cliente decidía ===")
T_RACE = "573004444445"
msg("hola", phone=T_RACE); msg("Beto", phone=T_RACE)
msg(button_id="chatbot_reunion", phone=T_RACE)
msg(list_id=f"dia_{DIA.isoformat()}", phone=T_RACE)

_google["libre"] = False
antes_de_eventos = len(eventos_creados)
enviados.clear(); msg(button_id=f"hora_{dt(DIA, 11).isoformat()}", phone=T_RACE)
check("NO crea el evento si el horario ya se ocupó",
      len(eventos_creados) == antes_de_eventos)
check("avisa y vuelve a ofrecer horarios",
      any("acaban de tomar" in t[2] for t in enviados) and estado(T_RACE).state == "ASKING_TIME")
_google["libre"] = True

print("\n=== El día se llenó entero ===")
T_LLENO = "573004444446"
msg("hola", phone=T_LLENO); msg("Caro", phone=T_LLENO)
msg(button_id="chatbot_reunion", phone=T_LLENO)
_google["horarios"] = []
enviados.clear(); msg(list_id=f"dia_{DIA.isoformat()}", phone=T_LLENO)
check("vuelve a ofrecer la lista de días",
      any(t[0] == "list" for t in enviados) and estado(T_LLENO).state == "ASKING_DATE")
_google["horarios"] = [dt(DIA, 9), dt(DIA, 11), dt(DIA, 15)]

print("\n=== Sin disponibilidad en todo el rango ===")
T_SIN = "573004444447"
msg("hola", phone=T_SIN); msg("Dani", phone=T_SIN)
_google["dias"] = []
enviados.clear(); msg(button_id="chatbot_reunion", phone=T_SIN)
check("avisa que no hay horarios y registra el lead igual",
      any("no tenemos horarios libres" in t[2] for t in enviados))
s = database.get_session()
check("queda un lead de cita pendiente de agendar a mano",
      s.query(database.Lead).filter_by(type="cita").filter(
          database.Lead.detail.isnot(None)).count() >= 1)
s.close()
_google["dias"] = [(DIA, 3)]

print("\n=== Google caído: la cita no se pierde ===")
T_CAIDO = "573004444448"
msg("hola", phone=T_CAIDO); msg("Eva", phone=T_CAIDO)
_google["falla"] = True
enviados.clear(); msg(button_id="chatbot_reunion", phone=T_CAIDO)
check("responde al cliente igual", len(enviados) > 0)
check("no lo deja a medias", estado(T_CAIDO).state == "DONE")
s = database.get_session()
lead_caido = (s.query(database.Lead).join(database.Contact)
              .filter(database.Contact.phone == T_CAIDO).first())
check("registra la cita para confirmar a mano",
      lead_caido is not None and lead_caido.type == "cita"
      and lead_caido.google_event_id is None)
s.close()
check("avisa al dueño para que la confirme",
      any(t[1] == config.OWNER_PHONE_NUMBER for t in enviados))
_google["falla"] = False

print("\n=== Cierre del recorrido: volver al menú o terminar ===")
T_CIERRE = "573007771100"
msg("hola", phone=T_CIERRE); msg("Elena", phone=T_CIERRE)
msg(button_id="chatbot_reunion", phone=T_CIERRE)
msg(list_id=f"dia_{DIA.isoformat()}", phone=T_CIERRE)
enviados.clear(); msg(button_id=f"hora_{dt(DIA, 12).isoformat()}", phone=T_CIERRE)
_txt = " ".join(t[2] for t in enviados if t[1] == T_CIERRE)
check("la confirmación avisa de que un asesor manda el enlace",
      "asesor" in _txt and "Meet" in _txt, _txt[:80])
check("y ofrece volver al menú o terminar", any(t[0] == "btn" for t in enviados))

enviados.clear(); msg(button_id="cierre_menu", phone=T_CIERRE)
check("'volver al menú' muestra el menú otra vez",
      any(t[0] == "list" for t in enviados))
check("y suelta el servicio anterior", estado(T_CIERRE).servicio is None)

msg(list_id="opt_chatbot", phone=T_CIERRE)
msg(button_id="chatbot_precios", phone=T_CIERRE)
enviados.clear(); msg(button_id="cierre_terminar", phone=T_CIERRE)
check("'terminar' se despide", any("Gracias" in t[2] for t in enviados))
check("y deja la conversación cerrada", estado(T_CIERRE).state == "DONE")
check("sin marcarla como atendida por un humano",
      estado(T_CIERRE).atendido_por_humano is False)
enviados.clear(); msg("hola otra vez", phone=T_CIERRE)
check("el bot vuelve solo cuando el cliente escribe", len(enviados) > 0)

print("\n=== Reagendar y cancelar ===")
# Sin cita, la opción no aparece en el menú: solo llevaría a un callejón.
T_SINCITA = "573007772200"
msg("hola", phone=T_SINCITA); msg("Pablo", phone=T_SINCITA)
_visibles = bot_logic._opciones_para_mostrar(config.NEED_OPTIONS, cita=None)
check("sin cita, 'Mi cita agendada' no se ofrece",
      not any(o["id"] == "opt_gestionar_cita" for o in _visibles))
_visibles = bot_logic._opciones_para_mostrar(config.NEED_OPTIONS, cita=object())
check("con cita, sí se ofrece",
      any(o["id"] == "opt_gestionar_cita" for o in _visibles))

T_GEST = "573007773300"
msg("hola", phone=T_GEST); msg("Rosa", phone=T_GEST)
msg(list_id="opt_chatbot", phone=T_GEST)
msg(button_id="chatbot_reunion", phone=T_GEST)
msg(list_id=f"dia_{DIA.isoformat()}", phone=T_GEST)
msg(button_id=f"hora_{dt(DIA, 16).isoformat()}", phone=T_GEST)
_s = database.get_session()
_cita = (_s.query(database.Lead).join(database.Contact)
         .filter(database.Contact.phone == T_GEST).order_by(database.Lead.id.desc()).first())
_evento_id = _cita.google_event_id
_s.close()
check("la cita quedó con su evento de calendario", bool(_evento_id))

# Cancelar: se borra el evento y el lead queda marcado.
borrados = []
calendar_service.eliminar_evento = lambda eid: (borrados.append(eid), True)[-1]
filas_borradas = []
_eliminar_fila_real = sheets_service.eliminar_fila   # se prueba aparte, más abajo
sheets_service.eliminar_fila = (
    lambda destino, col, val: filas_borradas.append((destino, col, val)) or True)
enviados.clear(); msg(button_id="cita_cancelar", phone=T_GEST)
check("cancelar borra el evento del calendario", borrados == [_evento_id], str(borrados))
check("se lo confirma al cliente",
      any("cancelamos" in t[2] for t in enviados if t[1] == T_GEST))
check("y avisa al dueño",
      any("CANCELADA" in t[2] for t in enviados if t[1] == config.OWNER_PHONE_NUMBER))
_s = database.get_session()
_cita = (_s.query(database.Lead).join(database.Contact)
         .filter(database.Contact.phone == T_GEST).order_by(database.Lead.id.desc()).first())
check("el lead queda como cancelada", _cita.status == "cancelada", _cita.status)
_s.close()
check("tras cancelar ofrece menú o terminar", any(t[0] == "btn" for t in enviados))

check("borra la fila de la pestaña de citas, por el ID del evento",
      ("citas", "ID del evento", _evento_id) in filas_borradas, str(filas_borradas))
check("y también la de la pestaña del servicio, por teléfono",
      ("chatbot", "Teléfono", T_GEST) in filas_borradas, str(filas_borradas))

# Ya sin cita activa, la opción desaparece del menú.
_s = database.get_session()
_c = _s.query(database.Contact).filter_by(phone=T_GEST).first()
check("cancelada, ya no cuenta como cita activa",
      bot_logic._cita_activa(_s, _c) is None)
_s.close()

# Reagendar: libera el hueco viejo y vuelve a ofrecer días.
T_REAG = "573007774400"
msg("hola", phone=T_REAG); msg("Iván", phone=T_REAG)
msg(button_id="chatbot_reunion", phone=T_REAG)
msg(list_id=f"dia_{DIA.isoformat()}", phone=T_REAG)
msg(button_id=f"hora_{dt(DIA, 17).isoformat()}", phone=T_REAG)
borrados.clear(); enviados.clear(); filas_borradas.clear()
msg(button_id="cita_reagendar", phone=T_REAG)
check("reagendar libera el hueco viejo", len(borrados) == 1, str(borrados))
check("y quita del Sheet la fila de la cita vieja",
      any(d == "citas" for d, _, _ in filas_borradas), str(filas_borradas))
check("avisa al dueño de que quedó libre",
      any("REAGENDADA" in t[2] for t in enviados if t[1] == config.OWNER_PHONE_NUMBER))
check("y vuelve a ofrecer los días", any(t[0] == "list" for t in enviados))
check("queda esperando que elija día", estado(T_REAG).state == "ASKING_DATE")

# Si Google no puede borrar, el cliente igual queda atendido.
calendar_service.eliminar_evento = lambda eid: False
T_FALLO = "573007775500"
msg("hola", phone=T_FALLO); msg("Nadia", phone=T_FALLO)
msg(button_id="chatbot_reunion", phone=T_FALLO)
msg(list_id=f"dia_{DIA.isoformat()}", phone=T_FALLO)
msg(button_id=f"hora_{dt(DIA, 9).isoformat()}", phone=T_FALLO)
enviados.clear(); msg(button_id="cita_cancelar", phone=T_FALLO)
check("si Google no borra el evento, la cita se cancela igual",
      any("cancelamos" in t[2] for t in enviados if t[1] == T_FALLO))
calendar_service.eliminar_evento = lambda eid: (borrados.append(eid), True)[-1]

print("\n=== Conversación abandonada a medias ===")
T_VIEJO = "573005555511"
msg("hola", phone=T_VIEJO); msg("Sofi", phone=T_VIEJO)
check("queda esperando que toque un botón", estado(T_VIEJO).state == "ASKED_NEED")

# La dejamos "envejecer" más allá del tiempo de caducidad
s = database.get_session()
c = s.query(database.Contact).filter_by(phone=T_VIEJO).first()
c.last_interaction = database.ahora_utc() - timedelta(
    hours=config.CONVERSATION_TIMEOUT_HOURS + 1)
s.commit(); s.close()

enviados.clear(); msg("hola de nuevo", phone=T_VIEJO)
check("al volver días después reinicia el flujo en vez de decir 'no entendí'",
      any("Bienvenido" in t[2] for t in enviados) and estado(T_VIEJO).state == "ASKED_NAME",
      str([t[2][:40] for t in enviados]))

# Dentro de la ventana NO debe reiniciar: el cliente sigue viendo los botones
T_RECIENTE = "573005555512"
msg("hola", phone=T_RECIENTE); msg("Iván", phone=T_RECIENTE)
s = database.get_session()
c = s.query(database.Contact).filter_by(phone=T_RECIENTE).first()
c.last_interaction = database.ahora_utc() - timedelta(
    hours=config.CONVERSATION_TIMEOUT_HOURS - 1)
s.commit(); s.close()
enviados.clear(); msg("cual era la opcion?", phone=T_RECIENTE)
check("dentro de la ventana no reinicia, solo aclara",
      any("no entendí" in t[2] for t in enviados)
      and estado(T_RECIENTE).state == "ASKED_NEED")

print("\n=== Respuesta inesperada ===")
T_RARO = "573005555555"
msg("hola", phone=T_RARO); msg("Luis", phone=T_RARO)
enviados.clear(); msg("blablabla sin tocar botón", phone=T_RARO)
check("responde el mensaje de fallback",
      any("no entendí" in t[2] for t in enviados))

# ── 2b. Archivos que manda el cliente ────────────────────────────────
# Antes de esto, una foto no dejaba NADA: ni fila en el historial, ni
# burbuja en el panel, ni aviso al celular. Y si llegaba justo cuando el
# bot pedía el nombre, el lead se quedaba llamándose "Cliente".

print("\n=== El cliente manda una imagen ===")

FOTO = {"tipo": "image", "media_id": "MID-FOTO-1", "mime": "image/jpeg",
        "nombre": None, "bytes": 45231, "caption": None}

T_FOTO = "573007000001"
msg("hola", phone=T_FOTO); msg("Marcela", phone=T_FOTO)
enviados.clear()
msg(phone=T_FOTO, media=dict(FOTO))

guardados = historial(T_FOTO)
entrante = [m for m in guardados if m.direccion == "entrante"][-1]
check("la imagen queda guardada en el historial",
      entrante.media_tipo == "image", f"media_tipo={entrante.media_tipo!r}")
check("con el id de Meta para poder bajarla luego",
      entrante.media_id == "MID-FOTO-1")
check("y con su tipo y tamaño",
      entrante.media_mime == "image/jpeg" and entrante.media_bytes == 45231)

check("el bot acusa recibo", any("Recibimos tu imagen" in t[2] for t in enviados))
botones = [t[3] for t in enviados if t[0] == "btn"]
ids = [b["id"] for b in botones[0]] if botones else []
check("y ofrece las dos salidas", ids == ["media_menu", "media_asesor"], str(ids))

check("NO lo pasa a un humano por su cuenta",
      estado(T_FOTO).atendido_por_humano is False)

# El resumen del listado y el aviso al celular no pueden quedar en blanco
from app.core import message_log as _log  # noqa: E402
check("en la bandeja se resume como imagen, no en blanco",
      _log.conversacion_info(T_FOTO)["ultimo_texto"] == "📷 Imagen",
      repr(_log.conversacion_info(T_FOTO)["ultimo_texto"]))

# Y el panel tiene que poder pintarla
ficha = [m for m in _log.conversacion(T_FOTO) if m.get("media_tipo")][-1]
check("el panel recibe la URL del archivo",
      ficha["media_url"] == f"/admin/media/{entrante.id}", ficha.get("media_url"))
check("y sabe que todavía se puede bajar", ficha["media_disponible"] is True)

print("\n=== Elegir 'ver el menú' después de mandar la imagen ===")
enviados.clear()
msg(button_id="media_menu", phone=T_FOTO)
check("vuelve al menú de servicios",
      any(t[0] in ("list", "btn") for t in enviados)
      and estado(T_FOTO).state == "ASKED_NEED")

print("\n=== Elegir 'hablar con asesor' después de mandar la imagen ===")
T_FOTO2 = "573007000002"
msg("hola", phone=T_FOTO2); msg("Andrés", phone=T_FOTO2)
msg(phone=T_FOTO2, media=dict(FOTO, media_id="MID-FOTO-2"))
enviados.clear()
msg(button_id="media_asesor", phone=T_FOTO2)
check("el bot se calla y lo pasa a una persona",
      estado(T_FOTO2).atendido_por_humano is True)
check("y avisa al dueño",
      any(t[1] == config.OWNER_PHONE_NUMBER for t in enviados))

print("\n=== Notas de voz y documentos ===")
T_VOZ = "573007000003"
msg("hola", phone=T_VOZ); msg("Sara", phone=T_VOZ)
enviados.clear()
msg(phone=T_VOZ, media={"tipo": "audio", "media_id": "MID-VOZ", "mime": "audio/ogg",
                        "nombre": None, "bytes": 8100, "caption": None})
check("una nota de voz se registra y se acusa distinto",
      any("nota de voz" in t[2] for t in enviados),
      str([t[2][:45] for t in enviados]))

T_DOC = "573007000004"
msg("hola", phone=T_DOC); msg("Pedro", phone=T_DOC)
enviados.clear()
msg(phone=T_DOC, media={"tipo": "document", "media_id": "MID-PDF",
                        "mime": "application/pdf", "nombre": "cotizacion.pdf",
                        "bytes": 120000, "caption": None})
check("un documento se acusa como documento",
      any("documento" in t[2].lower() for t in enviados))
check("y en la bandeja se resume con su nombre",
      _log.conversacion_info(T_DOC)["ultimo_texto"] == "📎 cotizacion.pdf",
      repr(_log.conversacion_info(T_DOC)["ultimo_texto"]))

print("\n=== Una imagen con pie de foto ===")
T_PIE = "573007000005"
msg("hola", phone=T_PIE); msg("Lucía", phone=T_PIE)
enviados.clear()
msg("esto es lo que tengo montado", phone=T_PIE,
    media=dict(FOTO, media_id="MID-PIE", caption="esto es lo que tengo montado"))
con_pie = [m for m in historial(T_PIE) if m.media_tipo][-1]
check("el pie de foto se guarda como texto del cliente",
      con_pie.texto == "esto es lo que tengo montado", repr(con_pie.texto))
check("y la imagen sigue adjunta al mismo mensaje", con_pie.media_id == "MID-PIE")

print("\n=== Una foto no puede costarle el nombre al lead ===")
# El fallo real: `name = (text or "").strip().title()` dejaba el contacto
# llamándose "Cliente", y el bot ya no vuelve a preguntar. Ese nombre
# llegaba al aviso del dueño y al Sheet.
T_NOMBRE = "573007000006"
msg("hola", phone=T_NOMBRE)
enviados.clear()
msg(phone=T_NOMBRE, media=dict(FOTO, media_id="MID-NOMBRE"))
check("mandar una foto al pedirle el nombre no lo bautiza 'Cliente'",
      estado(T_NOMBRE).name is None, f"name={estado(T_NOMBRE).name!r}")
check("y el bot le sigue preguntando el nombre",
      estado(T_NOMBRE).state == "ASKED_NAME")

enviados.clear(); msg("Valentina", phone=T_NOMBRE)
check("cuando por fin lo escribe, se guarda bien",
      estado(T_NOMBRE).name == "Valentina", f"name={estado(T_NOMBRE).name!r}")

# El otro camino al mismo fallo: un tipo que ni siquiera trae archivo
# (sticker, ubicación, una reacción) y llega con todo en None.
T_VACIO = "573007000007"
msg("hola", phone=T_VACIO)
msg(phone=T_VACIO)  # ni texto, ni botón, ni adjunto
check("un mensaje sin nada tampoco bautiza al lead",
      estado(T_VACIO).name is None, f"name={estado(T_VACIO).name!r}")

print("\n=== Una ubicación deja rastro aunque no haya archivo ===")
T_UBIC = "573007000008"
msg("hola", phone=T_UBIC); msg("Camilo", phone=T_UBIC)
enviados.clear()
msg(phone=T_UBIC, media={"tipo": "location"})
ubicacion = [m for m in historial(T_UBIC) if m.media_tipo][-1]
check("la ubicación queda registrada", ubicacion.media_tipo == "location")
check("sin id de archivo, porque no hay nada que bajar",
      ubicacion.media_id is None)
ficha_ubic = [m for m in _log.conversacion(T_UBIC) if m.get("media_tipo")][-1]
check("y el panel sabe que no hay archivo disponible",
      ficha_ubic["media_disponible"] is False)

# ── 3. Deduplicación ─────────────────────────────────────────────────

print("\n=== Deduplicación (Meta reintenta el webhook) ===")
enviados.clear()
msg("hola", phone="573006666666", mid="wamid.REPETIDO")
primera = len(enviados)
msg("hola", phone="573006666666", mid="wamid.REPETIDO")
check("un mensaje repetido no genera respuesta nueva", len(enviados) == primera,
      f"envíos: {primera} -> {len(enviados)}")

# ── 4. Origen del contacto ───────────────────────────────────────────

print("\n=== Origen del contacto ===")
T_WEB = "573007777777"
msg(config.ORIGENES["web"]["mensaje"], phone=T_WEB)
check("detecta el origen 'web' por el mensaje del botón",
      estado(T_WEB).origen == "web", f"origen={estado(T_WEB).origen!r}")

T_IG = "573007777778"
msg(config.ORIGENES["instagram"]["mensaje"], phone=T_IG)
check("detecta el origen 'instagram'", estado(T_IG).origen == "instagram")

T_DIR = "573007777779"
msg("buenas, tienen repuestos?", phone=T_DIR)
check("un cliente que escribe por su cuenta queda como 'directo'",
      estado(T_DIR).origen == config.ORIGEN_POR_DEFECTO)

msg(config.ORIGENES["qr"]["mensaje"], phone=T_WEB)
check("un origen ya conocido no se pisa con otro posterior",
      estado(T_WEB).origen == "web", f"origen={estado(T_WEB).origen!r}")

msg(config.ORIGENES["web"]["mensaje"].upper(), phone="57300777780")
check("detecta el origen sin importar mayúsculas ni tildes",
      estado("57300777780").origen == "web")

enviados.clear()
msg("Ana", phone=T_WEB) if estado(T_WEB).state == "ASKED_NAME" else None
s = database.get_session()
c_web = s.query(database.Contact).filter_by(phone=T_WEB).first()
c_web.name = "Web Cliente"; c_web.state = "ASKING_OTHER_DETAIL"; s.commit(); s.close()
enviados.clear(); msg("quiero cotizar", phone=T_WEB)
check("la notificación al dueño incluye el origen",
      any("Origen: web" in t[2] for t in enviados if t[1] == config.OWNER_PHONE_NUMBER))

# ── 5. Toma de control manual ────────────────────────────────────────

print("\n=== Escalamiento por palabra clave ===")
T_ESC = "573008888888"
msg("hola", phone=T_ESC); msg("Pedro", phone=T_ESC)
enviados.clear(); msg("necesito HABLAR CON UN ASESOR por favor", phone=T_ESC)
c = estado(T_ESC)
check("marca el contacto como atendido por humano", c.atendido_por_humano is True)
check("el estado pasa a HUMANO", c.state == "HUMANO", f"state={c.state}")
check("registra cuándo empezó", c.takeover_at is not None)
check("avisa al cliente", any(t[1] == T_ESC for t in enviados))
check("avisa al dueño", any(t[1] == config.OWNER_PHONE_NUMBER for t in enviados))

s = database.get_session()
check("crea un lead tipo 'otro'",
      s.query(database.Lead).filter_by(type="otro").count() >= 1)
s.close()

enviados.clear(); msg("hola? sigues ahi?", phone=T_ESC)
check("el bot no responde mientras lo atiende un humano", len(enviados) == 0,
      f"envió {len(enviados)} mensajes")

print("\n=== Devolver el control ===")
check("release devuelve True", bot_logic.devolver_control_al_bot(T_ESC) is True)
check("release de un número inexistente devuelve False",
      bot_logic.devolver_control_al_bot("570000000000") is False)
enviados.clear(); msg("hola de nuevo", phone=T_ESC)
check("el bot vuelve a responder", len(enviados) > 0)

check("takeover manual devuelve True", bot_logic.tomar_control_manual(T_ESC) is True)
enviados.clear(); msg("otra cosa", phone=T_ESC)
check("el bot se calla tras el takeover manual", len(enviados) == 0)

print("\n=== Liberación automática por inactividad ===")


def envejecer(phone, minutos, mensajes=True):
    """
    Mueve hacia atrás lo que cuenta como actividad de ese chat.

    Con `mensajes=False` envejece solo el lado del asesor (cuándo se tomó
    la conversación), y deja recientes los mensajes del cliente: así se
    simula al asesor que tardó mucho mientras el cliente sigue escribiendo.
    """
    desfase = timedelta(minutes=minutos)
    s = database.get_session()
    c = s.query(database.Contact).filter_by(phone=phone).first()
    if c.takeover_at:
        c.takeover_at -= desfase
    if c.last_interaction:
        c.last_interaction -= desfase
    if mensajes:
        for m in s.query(database.Message).filter_by(phone=phone).all():
            if m.created_at:
                m.created_at -= desfase
    s.commit(); s.close()


# El caso que antes se hacía mal: el asesor tardó más del plazo, pero el
# cliente acaba de escribir. La conversación está viva y el bot NO debe
# meterse. Antes se despertaba justo aquí y saludaba desde cero.
bot_logic.tomar_control_manual(T_ESC)
msg("tengo una duda mas", phone=T_ESC)      # el cliente deja rastro reciente
envejecer(T_ESC, config.HUMAN_TAKEOVER_TIMEOUT_MINUTES + 30, mensajes=False)
enviados.clear(); msg("sigues ahi?", phone=T_ESC)
check("no interrumpe una conversación viva aunque el asesor tarde",
      len(enviados) == 0, f"envió {len(enviados)} mensajes")
check("y la deja en manos del humano", estado(T_ESC).atendido_por_humano is True)

# Ahora sí: los dos lados llevan callados más del plazo.
envejecer(T_ESC, config.HUMAN_TAKEOVER_TIMEOUT_MINUTES + 30)
enviados.clear(); msg("hola, vuelvo despues de dias", phone=T_ESC)
check("el bot retoma cuando los dos lados llevan callados", len(enviados) > 0)
check("el flag queda desmarcado", estado(T_ESC).atendido_por_humano is False)
# Al soltarla queda en DONE, no en NEW: quien vuelve tras hablar con un
# asesor no puede recibir "¿cómo te llamas?" si ya sabemos su nombre.
check("no reinicia el saludo al soltarla",
      not any(t[2] == config.WELCOME_MESSAGE for t in enviados),
      f"envió: {[t[2][:40] for t in enviados]}")
check("y reconoce al cliente por su nombre",
      any("Pedro" in t[2] for t in enviados))

bot_logic.devolver_control_al_bot(T_ESC)

print("\n=== Rama de asesor fusionada con el flag ===")
# "Hablar con un asesor" (accion "humano") pasa por el mismo camino que la
# vieja rama "Otra consulta", así que aquí se verifica ese flag.
T_OTRO = "573003333333"
msg("hola", phone=T_OTRO); msg("Ana", phone=T_OTRO)
msg(button_id="chatbot_asesor", phone=T_OTRO)
enviados.clear(); msg("tengo una duda sobre la garantia", phone=T_OTRO)
c = estado(T_OTRO)
check("'otra consulta' deja la conversación en manos del humano",
      c.atendido_por_humano is True and c.state == "HUMANO", f"state={c.state}")
enviados.clear(); msg("sigue ahi?", phone=T_OTRO)
check("no reinicia el saludo encima del asesor", len(enviados) == 0)

# ── 6. Endpoints de administración ───────────────────────────────────

print("\n=== Google Sheets ===")

CONTACTO = {"name": "Nico", "phone": "573001234567", "origen": "web",
            "servicio": "Tablero en Power BI", "recorrido": "Vio precios > Agendó reunión"}

check("cada pestaña declara su formato de fila",
      all(d.get("formato") in ("servicio", "cita")
          for d in config.SHEETS_TABS.values()))
check("no hay dos pestañas con el mismo nombre",
      len({d["nombre"] for d in config.SHEETS_TABS.values()})
      == len(config.SHEETS_TABS))

fila = sheets_service._fila("citas", CONTACTO, {
    "appointment_date": "Lunes 10 de agosto", "appointment_time": "11:00 am",
    "google_event_id": "evt_123"})
check("la fila de cita tiene tantas celdas como columnas",
      len(fila) == len(config.SHEETS_TABS["citas"]["columnas"]),
      f"{len(fila)} vs {len(config.SHEETS_TABS['citas']['columnas'])}")
check("la cita dice de qué servicio es y por dónde pasó",
      fila[3] == "Tablero en Power BI"
      and fila[4] == "Vio precios > Agendó reunión", str(fila))
check("la fila de cita lleva día, hora, origen y el ID del evento",
      fila[5] == "Lunes 10 de agosto" and fila[6] == "11:00 am"
      and fila[7] == "web" and fila[9] == "evt_123", str(fila))

import re as _re  # noqa: E402
check("la fecha va en ISO, para que ordenar la columna dé el orden real",
      bool(_re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", fila[0])), fila[0])
check("el teléfono va como texto y conserva sus dígitos",
      fila[2] == "573001234567" and isinstance(fila[2], str))

for _clave, _datos in config.SHEETS_TABS.items():
    _f = sheets_service._fila(_clave, CONTACTO, {"detail": "algo"})
    check(f"la fila de '{_datos['nombre']}' cuadra con sus columnas",
          len(_f) == len(_datos["columnas"]),
          f"{len(_f)} vs {len(_datos['columnas'])}")

fila = sheets_service._fila("powerbi", CONTACTO, {"detail": "ver ventas por mes"})
check("la pestaña del servicio lleva el recorrido",
      fila[3] == "Vio precios > Agendó reunión")
check("y el mensaje que escribió el cliente", fila[4] == "ver ventas por mes")

fila = sheets_service._fila("citas", {"phone": "573000000000"}, {})
check("una cita sin datos no deja celdas en blanco confusas",
      fila[1] == "(sin nombre)" and fila[3] == "(sin servicio)"
      and fila[5] == "por confirmar"
      and fila[7] == config.ORIGEN_POR_DEFECTO, str(fila))

check("una pestaña que no existe no se escribe, y no revienta",
      _registrar_real("inventada", CONTACTO, {}) is False)

print("\n=== Borrar la fila de una cita cancelada ===")
# Sheet simulado con tres citas: hay que borrar la del medio, y solo esa.
_COLS = config.SHEETS_TABS["citas"]["columnas"]
_ID = _COLS.index("ID del evento")


def _fila_falsa(evento):
    fila = [""] * len(_COLS)
    fila[_ID] = evento
    return fila


_hoja = {"values": [_COLS, _fila_falsa("evt_A"), _fila_falsa("evt_B"),
                    _fila_falsa("evt_C")]}
_peticiones = []


class _Valores:
    def get(self, **kw): return self
    def execute(self): return _hoja


class _Spreadsheets:
    def values(self): return _Valores()
    def get(self, **kw): return self
    def batchUpdate(self, spreadsheetId=None, body=None):
        _peticiones.append(body); return self
    def execute(self):
        return {"sheets": [{"properties": {
            "title": config.SHEETS_TABS["citas"]["nombre"], "sheetId": 77}}]}


class _Sheets:
    def spreadsheets(self): return _Spreadsheets()


_sheets_original_2 = sheets_service.google_client.sheets
_id_original = sheets_service.google_client.id_spreadsheet
sheets_service.google_client.sheets = lambda: _Sheets()
sheets_service.google_client.id_spreadsheet = lambda: "hoja-de-prueba"

check("borrar una cita devuelve True",
      _eliminar_fila_real("citas", "ID del evento", "evt_B") is True)
_rango_borrado = _peticiones[0]["requests"][0]["deleteDimension"]["range"]
check("borra exactamente la fila de esa cita",
      _rango_borrado["startIndex"] == 2 and _rango_borrado["endIndex"] == 3,
      str(_rango_borrado))
check("y sobre la pestaña correcta", _rango_borrado["sheetId"] == 77)

_peticiones.clear()
check("si el ID no está, no borra nada",
      _eliminar_fila_real("citas", "ID del evento", "evt_Z") is False
      and not _peticiones)
check("una columna que no existe tampoco borra nada",
      _eliminar_fila_real("citas", "Columna inventada", "x") is False
      and not _peticiones)
check("nunca borra la fila de encabezados",
      _eliminar_fila_real("citas", "ID del evento", "ID del evento") is False
      and not _peticiones)
sheets_service.google_client.sheets = _sheets_original_2
sheets_service.google_client.id_spreadsheet = _id_original

destinos_usados = {t for t, _, _ in filas_sheet}
check("las citas se escriben en su pestaña y en la del servicio",
      {"citas", "chatbot"} <= destinos_usados, str(sorted(destinos_usados)))
check("todo destino usado existe en config",
      destinos_usados <= set(config.SHEETS_TABS), str(sorted(destinos_usados)))
check("las filas incluyen teléfono y origen del contacto",
      all(c.get("phone") and "origen" in c for _, c, _ in filas_sheet))
check("y llevan el servicio y el recorrido del contacto",
      all("servicio" in c and "recorrido" in c for _, c, _ in filas_sheet))

cita_con_evento = [l for t, _, l in filas_sheet
                   if t == "citas" and l.get("google_event_id")]
check("la cita agendada llega al Sheet con su ID de evento", len(cita_con_evento) >= 1)

cita_manual = [l for t, _, l in filas_sheet if t == "citas" and not l.get("google_event_id")]
check("la cita que hay que confirmar a mano también llega al Sheet",
      len(cita_manual) >= 1)

# Resiliencia: si Google falla, registrar_lead devuelve False sin lanzar.
_sheets_original = sheets_service.google_client.sheets


def _sheets_rotos():
    raise RuntimeError("Google caído (simulado)")


sheets_service.google_client.sheets = _sheets_rotos
sheets_service._pestanas_verificadas = True
check("si el Sheet falla, devuelve False sin lanzar excepción",
      _registrar_real("venta", CONTACTO, {"detail": "x"}) is False)
check("un tipo desconocido no rompe nada",
      _registrar_real("inventado", CONTACTO, {}) is False)
sheets_service.google_client.sheets = _sheets_original

# Y lo más importante: que un Sheet roto no corte la conversación.
sheets_service.registrar_lead = _registrar_real
sheets_service.google_client.sheets = _sheets_rotos
T_SHEET = "573009999001"
msg("hola", phone=T_SHEET); msg("Fran", phone=T_SHEET)
msg(list_id="opt_powerbi", phone=T_SHEET)
msg(button_id="powerbi_asesor", phone=T_SHEET)
enviados.clear(); msg("quiero un tablero de ventas", phone=T_SHEET)
check("con el Sheet caído el cliente igual recibe su confirmación",
      any(t[1] == T_SHEET for t in enviados))
check("con el Sheet caído el dueño igual recibe el aviso",
      any(t[1] == config.OWNER_PHONE_NUMBER for t in enviados))
s = database.get_session()
check("con el Sheet caído el lead igual queda en la base",
      s.query(database.Lead).join(database.Contact)
       .filter(database.Contact.phone == T_SHEET).count() == 1)
s.close()
sheets_service.google_client.sheets = _sheets_original
sheets_service.registrar_lead = (
    lambda tipo, contacto, lead: filas_sheet.append((tipo, contacto, lead)) or True)

print("\n=== Vuelve a escribir con la conversación ya cerrada ===")

# Tras una consulta atendida: se le ofrece el menú, sin volver a pedirle
# el nombre. Se le devuelve el control al bot primero, que si no sigue
# callado por el flag de atención humana.
T_VUELVE = "573006660001"
msg("hola", phone=T_VUELVE); msg("Marta", phone=T_VUELVE)
msg(list_id="opt_powerbi", phone=T_VUELVE)
msg(button_id="powerbi_asesor", phone=T_VUELVE)
msg("un teclado", phone=T_VUELVE)
bot_logic.devolver_control_al_bot(T_VUELVE)
s = database.get_session()
_cv = s.query(database.Contact).filter_by(phone=T_VUELVE).first()
_cv.state = "DONE"; s.commit(); s.close()

enviados.clear(); msg("una pregunta mas", phone=T_VUELVE)
textos = [t[2] for t in enviados if t[1] == T_VUELVE]
check("no le vuelve a pedir el nombre",
      not any("cuéntame tu nombre" in t for t in textos), str(textos)[:70])
check("le saluda por su nombre y le ofrece el menú",
      any("Marta" in t for t in textos) and any(t[0] == "list" for t in enviados))
check("queda esperando que elija opción", estado(T_VUELVE).state == "ASKED_NEED")

# Tras una CITA: pasa a un asesor, porque suele preguntar por la cita.
T_TRAS_CITA = "573006660002"
msg("hola", phone=T_TRAS_CITA); msg("Jorge", phone=T_TRAS_CITA)
msg(button_id="chatbot_reunion", phone=T_TRAS_CITA)
msg(list_id=f"dia_{DIA.isoformat()}", phone=T_TRAS_CITA)
enviados.clear()
msg(button_id=f"hora_{dt(DIA, 15).isoformat()}", phone=T_TRAS_CITA)
check("la cita queda agendada",
      any("Cita agendada" in t[2] for t in enviados if t[1] == T_TRAS_CITA))

# EL GUARDIAN. La confirmacion y el "¿te ayudo con algo mas?" eran dos
# envios seguidos AL CLIENTE, y desde el 1-oct-2026 Meta cobra los dos.
# Ahora van juntos. Se cuenta solo lo del cliente: el aviso al dueno sale
# por el mismo sitio, no se le cobra a el y no se puede quitar.
#
# Si alguien vuelve a partir esto en dos, aqui se entera. Sin una prueba
# que cuente, "el bot habla de mas" vuelve a ser una opinion y el numero
# sube sin que nadie lo note: `python scripts/medir_verbosidad.py`.
_al_cliente = [t for t in enviados if t[1] == T_TRAS_CITA]
check("y la confirmacion va en UN mensaje, con las opciones dentro",
      len(_al_cliente) == 1 and _al_cliente[0][0] == "btn",
      f"{len(_al_cliente)} mensajes: {[t[0] for t in _al_cliente]}")

enviados.clear(); msg("me pasan el link de la reunion?", phone=T_TRAS_CITA)
check("tras agendar, una pregunta pasa a un asesor",
      estado(T_TRAS_CITA).atendido_por_humano is True)
check("y no reinicia el saludo",
      not any("Bienvenido" in t[2] for t in enviados if t[1] == T_TRAS_CITA))
check("avisa al dueño de que hay alguien esperando",
      any(t[1] == config.OWNER_PHONE_NUMBER for t in enviados))

print("\n=== Avisos al dueño fuera de la ventana de 24h ===")
from app.bot import notificaciones  # noqa: E402

FUERA_DE_VENTANA = RespuestaFalsa(400, {"error": {
    "code": 131047,
    "message": "Re-engagement message"}})

_texto_original = whatsapp_client.send_text_message
enviados.clear()
whatsapp_client.send_text_message = lambda to, text, autor="bot": FUERA_DE_VENTANA
config.OWNER_TEMPLATE_NAME = "aviso_lead"

check("si la ventana está cerrada, reintenta con la plantilla",
      notificaciones.avisar_dueno("texto bonito", ["venta", "Ana", "573001", "un pc"]) is True)
check("la plantilla lleva las 4 variables en orden",
      any(t[0] == "plantilla" and "'venta', 'Ana', '573001', 'un pc'" in t[2]
          for t in enviados), str(enviados)[:120])

enviados.clear()
config.OWNER_TEMPLATE_NAME = ""
check("sin plantilla configurada, avisa del problema y no revienta",
      notificaciones.avisar_dueno("texto", ["a", "b", "c", "d"]) is False)
check("y no intenta enviar ninguna plantilla",
      not any(t[0] == "plantilla" for t in enviados))

enviados.clear()
config.OWNER_TEMPLATE_NAME = "aviso_lead"

# La ventana tiene que estar ABIERTA para que este caso exista siquiera.
# Desde que el aviso se decide ANTES de enviar, con la ventana cerrada ni
# se intenta el texto libre: se va derecho a la plantilla. Así que "el
# texto libre falló con un error que no es de ventana" solo puede pasarle
# a alguien que sí le escribió al bot hace poco.
_log.registrar(config.OWNER_PHONE_NUMBER, "entrante", "cliente", "hola")

OTRO_ERROR = RespuestaFalsa(400, {"error": {"code": 131026, "message": "Undeliverable"}})
whatsapp_client.send_text_message = lambda to, text, autor="bot": OTRO_ERROR
check("un error que NO es de ventana no dispara la plantilla",
      notificaciones.avisar_dueno("texto", ["a", "b", "c", "d"]) is False
      and not any(t[0] == "plantilla" for t in enviados))

whatsapp_client.send_text_message = _texto_original
config.OWNER_TEMPLATE_NAME = ""

# ── De dónde sale la plantilla ───────────────────────────────────────
#
# Lo de arriba prueba que `notificaciones` la USA bien; esto prueba que
# haya forma de DÁRSELA. Salió el 20-ago-2026, al apagar la rampa del
# cliente 1: en cuanto un negocio tiene `negocio_config` deja de leer el
# entorno, y la plantilla solo existía como variable de entorno. O sea que
# ningún cliente podía tenerla, y sus leads se perdían pasadas 24 h sin que
# nadie se enterara — el fallo silencioso que este módulo viene a evitar.
# Ahora sale también de `[avisos]`, que sí se edita desde el panel.
from app.core.config_cliente import ConfiguracionCliente  # noqa: E402
from app.web import contenido as _contenido  # noqa: E402


def _con_avisos(avisos):
    return ConfiguracionCliente(
        fila={"id": 7, "nombre": "N"},
        negocio={"negocio": {"nombre": "N"}, "textos": {}, "menu": [],
                 "avisos": avisos})


check("la plantilla sale del contenido del negocio",
      _con_avisos({"plantilla": "aviso_lead"}).OWNER_TEMPLATE_NAME == "aviso_lead")
check("y su idioma también",
      _con_avisos({"plantilla": "x",
                   "plantilla_idioma": "es_ES"}).OWNER_TEMPLATE_LANG == "es_ES")
check("un idioma en blanco cae al defecto 'es', no a cadena vacía",
      _con_avisos({"plantilla": "x",
                   "plantilla_idioma": ""}).OWNER_TEMPLATE_LANG == "es")
check("sin plantilla escrita queda vacía, y notificaciones ya avisa de eso",
      _con_avisos({}).OWNER_TEMPLATE_NAME == "")

# La razón de ser de todo lo anterior, dicha en una verificación.
os.environ["OWNER_TEMPLATE_NAME"] = "la-del-entorno"
check("un negocio con contenido propio NO lee el entorno: por eso hace falta [avisos]",
      _con_avisos({"plantilla": "aviso_lead"}).OWNER_TEMPLATE_NAME == "aviso_lead"
      and _con_avisos({}).OWNER_TEMPLATE_NAME == "")
del os.environ["OWNER_TEMPLATE_NAME"]

# Y que el editor la escriba justo donde la configuración la busca: son dos
# módulos distintos y no hay nada más que los ate.
_guardado = _contenido.leer(
    {"aviso-plantilla": "  aviso_lead  ", "aviso-plantilla_idioma": "es"},
    {"negocio": {"nombre": "N"}, "textos": {}, "menu": [], "avisos": {}})
check("el editor la guarda donde la configuración la busca",
      ConfiguracionCliente(fila={"id": 7, "nombre": "N"},
                           negocio=_guardado).OWNER_TEMPLATE_NAME == "aviso_lead",
      f"guardado={_guardado.get('avisos', {}).get('plantilla')!r}")

print("\n=== Endpoints /admin ===")
for descripcion, clave, esperado in (
    ("rechaza una clave incorrecta", "clave-mala", 401),
    ("rechaza una petición sin clave", None, 401),
):
    try:
        admin_api._validar_clave(clave)
        check(descripcion, False, "no lanzó excepción")
    except HTTPException as e:
        check(descripcion, e.status_code == esperado, f"status={e.status_code}")

try:
    admin_api._validar_clave("clave-de-prueba")
    check("acepta la clave correcta", True)
except HTTPException as e:
    check("acepta la clave correcta", False, f"status={e.status_code}")

_original = config.ADMIN_API_KEY
config.ADMIN_API_KEY = ""
try:
    admin_api._validar_clave("lo-que-sea")
    check("sin ADMIN_API_KEY los endpoints quedan deshabilitados", False)
except HTTPException as e:
    check("sin ADMIN_API_KEY los endpoints quedan deshabilitados", e.status_code == 503)
config.ADMIN_API_KEY = _original

bot_logic.tomar_control_manual(T_OTRO)
todos = bot_logic.listar_contactos()
humanos = bot_logic.listar_contactos(solo_humanos=True)
check("listar_contactos devuelve todos los contactos", len(todos) >= 8, f"total={len(todos)}")
check("el filtro solo_humanos funciona",
      len(humanos) < len(todos) and all(c["atendido_por_humano"] for c in humanos),
      f"humanos={len(humanos)}/{len(todos)}")
check("la lista incluye el origen", all("origen" in c for c in todos))

# ── 7. Botón de la web ───────────────────────────────────────────────

print("\n=== Botón de WhatsApp para la web ===")
config.BUSINESS_WHATSAPP_NUMBER = "+57 317 886 2390"
enlace = web_button.url_chat()
check("limpia el número al armar el enlace", enlace.startswith("https://wa.me/573178862390?"))
check("el mensaje va codificado para URL", " " not in enlace)
check("el enlace de instagram usa su propio mensaje",
      web_button.url_chat("instagram") != enlace)

try:
    web_button.url_chat("canal-que-no-existe")
    check("rechaza un origen inexistente", False, "no lanzó excepción")
except ValueError:
    check("rechaza un origen inexistente", True)

config.BUSINESS_WHATSAPP_NUMBER = ""
try:
    web_button.url_chat()
    check("avisa si falta BUSINESS_WHATSAPP_NUMBER", False, "no lanzó excepción")
except ValueError:
    check("avisa si falta BUSINESS_WHATSAPP_NUMBER", True)
config.BUSINESS_WHATSAPP_NUMBER = "573178862390"

html = web_button.snippet_flotante()
check("el botón flotante lleva aria-label", 'aria-label=' in html)
check("el logo va embebido, sin pedir imágenes externas",
      "<svg" in html and "http://" not in html.replace("https://wa.me", ""))

# ── 8. Firma del webhook ─────────────────────────────────────────────

print("\n=== Firma del webhook (X-Hub-Signature-256) ===")
import hashlib, hmac  # noqa: E402
from app import main           # noqa: E402


class _PeticionFalsa:
    def __init__(self, headers):
        self.headers = headers


# El secreto va por PARÁMETRO desde que cada cliente trae su propia App
# de Meta: quien llama es el único que sabe de qué negocio es el POST,
# porque lo dice su URL. Antes se leía de `config.APP_SECRET`, que era uno
# solo para todos.
#
# Ojo con "arreglar" esto poniendo `config.APP_SECRET = ...`: al asignarlo
# se crea el atributo en el módulo y deja de pasar por el `__getattr__`
# que resuelve por inquilino, así que el resto de la suite se quedaría
# viendo ese valor para TODOS los clientes.
config.VERIFY_WEBHOOK_SIGNATURE = True
SECRETO = "secreto-de-prueba"
cuerpo = b'{"entry":[]}'
firma_ok = "sha256=" + hmac.new(SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()

check("acepta un cuerpo bien firmado",
      main._firma_valida(_PeticionFalsa({"X-Hub-Signature-256": firma_ok}),
                         cuerpo, SECRETO) is True)
check("rechaza si no hay firma",
      main._firma_valida(_PeticionFalsa({}), cuerpo, SECRETO) is False)
check("rechaza una firma inválida",
      main._firma_valida(_PeticionFalsa({"X-Hub-Signature-256": "sha256=abc"}),
                         cuerpo, SECRETO) is False)
check("rechaza si el cuerpo fue alterado",
      main._firma_valida(_PeticionFalsa({"X-Hub-Signature-256": firma_ok}),
                         cuerpo + b" ", SECRETO) is False)

check("sin App Secret no acepta nada (falla cerrado)",
      main._firma_valida(_PeticionFalsa({"X-Hub-Signature-256": firma_ok}),
                         cuerpo, "") is False)

# LA COMPROBACIÓN QUE JUSTIFICA TODO EL CAMBIO DE MODELO: un mensaje
# firmado por la App de un cliente NO puede colarse como si fuera de otro.
#
# Con una sola App esto no se podía ni preguntar: el secreto era el mismo
# para todos, así que cualquier firma válida valía para cualquier negocio.
# Ahora cada uno firma con lo suyo y esa es la separación.
check("la firma de un cliente no vale para otro",
      main._firma_valida(_PeticionFalsa({"X-Hub-Signature-256": firma_ok}),
                         cuerpo, "el-secreto-de-otro-negocio") is False)

# ── 8b. Las credenciales no salen en los mensajes de error ───────────
#
# META DEVUELVE EL TOKEN DENTRO DE SUS ERRORES: a un token mal copiado le
# contesta "Malformed access token EAAG...", con el token entero pegado.
# Ese texto se pinta en el super-admin y viaja en la URL de redirección,
# o sea al historial del navegador y a los logs.
#
# Salió comprobando el botón "Probar credenciales" en el navegador; la
# suite no lo habría visto, porque el HTML servido era correcto.

print("\n=== Las credenciales no se filtran a pantalla ===")
from app.integrations import meta_estado                      # noqa: E402

TOKEN_FALSO = "EAAG-token-larguisimo-de-un-cliente"
SECRETO_FALSO = "app-secret-de-un-cliente"

_linea = meta_estado._tapar(
    {"estado": "mal",
     "titulo": f"Malformed access token {TOKEN_FALSO}",
     "detalle": f"y el secreto {SECRETO_FALSO} tambien"},
    TOKEN_FALSO, SECRETO_FALSO)

check("el token no aparece en el titulo", TOKEN_FALSO not in _linea["titulo"],
      _linea["titulo"])
check("el app secret no aparece en el detalle",
      SECRETO_FALSO not in _linea["detalle"], _linea["detalle"])
check("y se ve que hay algo tapado, no un hueco",
      "«oculto»" in _linea["titulo"], _linea["titulo"])

# Una cadena corta NO se tapa: no es una credencial, y taparla destrozaría
# textos normales que la contengan por casualidad.
_corta = meta_estado._tapar(
    {"estado": "ok", "titulo": "el numero 123 responde", "detalle": ""}, "123")
check("una cadena corta no se confunde con una credencial",
      _corta["titulo"] == "el numero 123 responde", _corta["titulo"])

# ── 8c. A quién le llega cada aviso ──────────────────────────────────
#
# Un negocio con áreas —Ventas, Soporte, Contratos— no quiere que las tres
# reciban todo. Lo que NO puede pasar bajo ninguna configuración es que un
# aviso no le llegue a nadie: eso es una venta que nadie atiende, y no da
# ningún error — se ve igual que un día sin clientes.

print("\n=== Los avisos se reparten por área ===")
from app.bot import notificaciones as _avisos                 # noqa: E402

_cfg = config.base()
_cfg.OWNER_PHONE_NUMBER = "573000000000"
# La configuración base no tiene plan, así que es Básico, y el Básico no
# trae áreas (23-sep-2026). Estas pruebas son del reparto por áreas: se
# les da el cupo del Pro.
from app.core import planes as _planes                        # noqa: E402
_cfg.MAX_DESTINOS_AVISOS = _planes.PLANES[_planes.PRO].areas


def _destinos(lista):
    _cfg.AVISOS_DESTINOS = _cfg._leer_destinos(lista)


def _quien(servicio=None):
    return [n for n, _ in _avisos.a_quien(servicio)]


_destinos(None)
check("sin áreas configuradas, todo va al dueño como siempre",
      _quien("opt_ventas") == ["573000000000"], str(_quien("opt_ventas")))

# ── El país y el número van en dos cuadros y se juntan aquí ──────────
#
# Sin el país, Meta rechaza el envío con un error que no dice que el
# problema era el formato del número — así que el aviso no llega y no hay
# ninguna señal de por qué.

print("\n=== El indicativo del país se une al número ===")


def _numero_de(fila):
    r = _cfg._leer_destinos([dict(fila, opciones=[])])
    return r[0]["numero"] if r else None


check("España: 34 + 612345678",
      _numero_de({"indicativo": "34", "numero": "612345678"}) == "34612345678",
      str(_numero_de({"indicativo": "34", "numero": "612345678"})))
check("EE.UU., con indicativo de un solo dígito",
      _numero_de({"indicativo": "1", "numero": "2125551234"}) == "12125551234")
check("los signos y espacios se limpian solos",
      _numero_de({"indicativo": "+34", "numero": "612 34 56 78"}) == "34612345678")

# Las dos formas de acabar con el país repetido, que darían un número que
# parece bien y no existe.
check("un número guardado ANTES de los dos cuadros no se rompe",
      _numero_de({"numero": "573001112233"}) == "573001112233")
check("pegar el número entero en el cuadro del número no duplica el país",
      _numero_de({"indicativo": "57", "numero": "573001112233"}) == "573001112233",
      str(_numero_de({"indicativo": "57", "numero": "573001112233"})))

_destinos([
    {"nombre": "Ventas", "numero": "+57 300 111 2233", "opciones": ["opt_ventas"]},
    {"nombre": "Soporte", "numero": "573004445566", "opciones": ["opt_soporte"]},
    {"nombre": "General", "numero": "573007778899", "opciones": []},
])
check("el número se limpia de signos y espacios",
      _quien("opt_ventas") == ["573001112233"], str(_quien("opt_ventas")))
check("a Soporte solo le llega lo suyo",
      _quien("opt_soporte") == ["573004445566"], str(_quien("opt_soporte")))
check("y NO le llega lo de Ventas",
      "573004445566" not in _quien("opt_ventas"), str(_quien("opt_ventas")))
check("lo que nadie reclama va al área general",
      _quien("opt_lo_que_sea") == ["573007778899"], str(_quien("opt_lo_que_sea")))
check("y lo que pasa antes de elegir nada, también",
      _quien(None) == ["573007778899"], str(_quien(None)))

# Sin área general: antes que perder el aviso, va a todas.
_destinos([
    {"nombre": "Ventas", "numero": "573001112233", "opciones": ["opt_ventas"]},
    {"nombre": "Soporte", "numero": "573004445566", "opciones": ["opt_soporte"]},
])
check("sin área general, lo huérfano va a todas antes que perderse",
      sorted(_quien("opt_huerfana")) == ["573001112233", "573004445566"],
      str(_quien("opt_huerfana")))
check("un aviso NUNCA se queda sin destinatario",
      all(_quien(s) for s in ("opt_ventas", "opt_x", None)))

# Higiene de los datos, que los escribe gente en un formulario.
_destinos([
    {"nombre": "Sin número", "numero": "", "opciones": ["opt_a"]},
    {"nombre": "Uno", "numero": "573001111111", "opciones": []},
    {"nombre": "Dos", "numero": "573002222222", "opciones": ["opt_b"]},
    {"nombre": "Tres", "numero": "573003333333", "opciones": ["opt_c"]},
    {"nombre": "Cuatro", "numero": "573004444444", "opciones": ["opt_d"]},
])
check("un área sin número se descarta entera",
      "" not in [d["numero"] for d in _cfg.AVISOS_DESTINOS])
check("el tope son 3 áreas", len(_cfg.AVISOS_DESTINOS) == 3,
      f"quedaron {len(_cfg.AVISOS_DESTINOS)}")
check("y el área sin número NO gasta un cupo de las buenas",
      [d["nombre"] for d in _cfg.AVISOS_DESTINOS] == ["Uno", "Dos", "Tres"],
      str([d["nombre"] for d in _cfg.AVISOS_DESTINOS]))

_cfg.AVISOS_DESTINOS = []


# ── 8c-bis. El cupo de áreas lo decide el plan ───────────────────────
#
# Básico 0, Pro 3, Premium 5 (23-sep-2026), y una columna para el caso
# pactado. El número lo decide la VENTA, así que no puede ser una
# constante escrita en cada sitio: vive en `app/core/planes.py`.

print("\n=== El cupo de áreas lo decide el plan ===")
from app.core.config_cliente import cupo_de_destinos             # noqa: E402

check("Básico: un solo administrador, sin áreas",
      cupo_de_destinos({"plan": "basico"}) == 0)
check("Pro: 3 áreas", cupo_de_destinos({"plan": "pro"}) == 3)
check("Premium: 5 áreas", cupo_de_destinos({"plan": "premium"}) == 5)
check("un negocio de antes, con la IA contratada, es un Pro",
      cupo_de_destinos({"plan": "mensual", "ia_contratada": True}) == 3)
check("y sin ella, un Básico", cupo_de_destinos({"plan": "mensual"}) == 0)
check("lo pactado con ESE negocio manda sobre el plan",
      cupo_de_destinos({"plan": "pro", "max_destinos_avisos": 2}) == 2)
check("un cero cuenta como 'no dicho' y cae al plan",
      cupo_de_destinos({"plan": "premium", "max_destinos_avisos": 0}) == 5)
check("la IA viene con el plan: Pro sí, Básico no",
      _planes.de({"plan": "pro"}).ia and not _planes.de({"plan": "basico"}).ia)

_seis = [{"nombre": f"A{i}", "correo": f"a{i}@negocio.test", "opciones": []}
         for i in range(6)]
_cfg.MAX_DESTINOS_AVISOS = cupo_de_destinos({"plan": "premium"})
_cfg.AVISOS_DESTINOS = _cfg._leer_destinos(_seis)
check("en Premium caben 5 áreas y la sexta se queda fuera",
      len(_cfg.AVISOS_DESTINOS) == 5, f"quedaron {len(_cfg.AVISOS_DESTINOS)}")
check("y cada área tiene su id, distinto de las demás",
      len({d["id"] for d in _cfg.AVISOS_DESTINOS}) == 5,
      str([d["id"] for d in _cfg.AVISOS_DESTINOS]))

_cfg.MAX_DESTINOS_AVISOS = cupo_de_destinos({"plan": "basico"})
_cfg.AVISOS_DESTINOS = _cfg._leer_destinos(_seis)
check("en Básico no queda ninguna", _cfg.AVISOS_DESTINOS == [])

_cfg.MAX_DESTINOS_AVISOS = _planes.PLANES[_planes.PRO].areas
_cfg.AVISOS_DESTINOS = []


# ── 8c-ter. Guardar el contenido NO puede borrar las áreas ───────────
#
# Las áreas se editan en la ficha del cliente, no en el editor de
# contenido — pero VIVEN en `negocio_config`, que es lo que el editor de
# contenido reescribe entero.
#
# Si alguien vuelve a poner ahí una línea del tipo
# `avisos["destinos"] = leer_destinos(formulario)`, el formulario ya no
# trae esos campos, así que guardaría una lista vacía y **borraría todas
# las áreas del negocio**. Sin error, sin aviso, y el dueño solo lo
# notaría cuando dejaran de llegarle los leads.

print("\n=== Guardar el contenido no borra las áreas de aviso ===")
from app.web import contenido as _cont                        # noqa: E402


class _FormularioSinAreas(dict):
    """Un envío del editor de contenido: no trae ningún campo `destino-*`."""

    def getlist(self, clave):
        return []


_antes = {
    "avisos": {
        "cita": "texto viejo",
        "destinos": [
            {"nombre": "Ventas", "numero": "573001112233", "opciones": ["opt_a"]},
            {"nombre": "Soporte", "numero": "573004445566", "opciones": []},
        ],
    },
    "menu": [{"id": "opt_a", "title": "A", "accion": "humano"}],
}

_despues = _cont.leer(_FormularioSinAreas({"aviso-cita": "texto nuevo"}), _antes)
_quedaron = (_despues.get("avisos") or {}).get("destinos")

check("las áreas sobreviven a guardar el contenido",
      _quedaron == _antes["avisos"]["destinos"],
      f"quedaron {_quedaron}")
check("y lo que sí edita esa pantalla sigue guardándose",
      (_despues.get("avisos") or {}).get("cita") == "texto nuevo")


# ── 8c-ter-bis. Los saltos de línea de un mensaje sobreviven ─────────
#
# Lo que se escribe en el editor tiene que llegarle al cliente TAL CUAL:
# con sus saltos de línea, sus líneas en blanco y sus espacios. WhatsApp
# los respeta, así que el editor no puede comérselos por el camino.
#
# La trampa que esto vigila, que no daba ningún error y borraba trabajo:
#
#   · **Un `<input>` no admite saltos de línea.** El navegador se los
#     quita al PINTAR el campo, así que un texto guardado con saltos los
#     perdía solo con abrir la pantalla, y el siguiente guardado escribía
#     la versión aplastada. Con el editor de contenido bastaba entrar y
#     pulsar Guardar sin tocar nada: manda el formulario entero. Por eso
#     todo lo que sea el CUERPO de un mensaje va en `<textarea>`, y solo
#     los rótulos de WhatsApp —etiquetas de botón, títulos de lista— van
#     en renglón. Lo decide `mapa.cabe_en_una_linea`, para los dos
#     editores a la vez.
#
#   · **Un formulario manda los saltos en `\r\n`.** Ese `\r` se guardaba
#     dentro del mensaje: no se ve, no da error y se acumula.
#
#   · **El HTML se come el salto pegado a `<textarea>`.** Un texto que
#     empiece por una línea en blanco la perdía en cada carga.

print("\n=== Un mensaje se guarda con los saltos y los espacios que tiene ===")
from app.web import mapa as _mapa                              # noqa: E402

_CON_FORMA = "Hola      Ana\n\n  · uno\n  · dos\n\nGracias."

_form = _FormularioSinAreas({
    # Como lo manda un navegador de verdad: con retornos de carro.
    "texto-bienvenida": _CON_FORMA.replace("\n", "\r\n"),
    "menu-0-id": "opt_a",
    "menu-0-accion": "info",
    "menu-0-title": "A",
    "menu-0-mensaje": _CON_FORMA.replace("\n", "\r\n"),
})
_guardado = _cont.leer(_form, {"menu": [], "textos": {}})

check("el texto conserva saltos, líneas en blanco y espacios",
      _guardado["textos"]["bienvenida"] == _CON_FORMA,
      repr(_guardado["textos"]["bienvenida"])[:70])
check("y el mensaje de una opción del menú, también",
      _guardado["menu"][0].get("mensaje") == _CON_FORMA)
check("no queda ningún retorno de carro guardado",
      "\r" not in _guardado["textos"]["bienvenida"]
      and "\r" not in _guardado["menu"][0].get("mensaje", ""))
check("un campo con solo espacios cuenta como vacío",
      _cont.leer(_FormularioSinAreas({"texto-despedida": "   \r\n  "}),
                 {"textos": {}})["textos"]["despedida"] == "")

# Y que el HTML los pinte donde caben: cuadro para los mensajes, renglón
# solo para los rótulos que WhatsApp manda en una línea.
_html = _cont.pintar({"textos": {"bienvenida": _CON_FORMA},
                      "menu": [{"id": "opt_a", "title": "A",
                                "accion": "info", "mensaje": _CON_FORMA}]})

check("el saludo se edita en un cuadro, no en un renglón",
      '<textarea name="texto-bienvenida"' in _html)
check("y el mensaje de la opción, también",
      '<textarea name="menu-0-mensaje"' in _html)
check("la etiqueta del botón de WhatsApp sigue en un renglón",
      '<input type="text" name="texto-menu_boton"' in _html
      and not _mapa.cabe_en_una_linea("bienvenida")
      and _mapa.cabe_en_una_linea("menu_boton"))
check("el <textarea> lleva el salto que el HTML se come",
      '<textarea name="texto-bienvenida" rows="3">\n' in _html)

# El mapa no guarda por formulario sino por JSON, pero un texto PEGADO
# desde Word llega igual con `\r\n`.
from app.web import superadmin as _super                       # noqa: E402

check("el mapa también deja los saltos en \\n",
      _super._sin_retornos({"textos": {"x": "a\r\nb"}, "m": ["c\r\nd"]})
      == {"textos": {"x": "a\nb"}, "m": ["c\nd"]})


# ── 8c-ter-ter. Un error del mapa dice DÓNDE está ────────────────────
#
# El editor no guarda si algo rompería una conversación, y eso está bien.
# Lo que no valía era el aviso: decía qué pasaba —"'Ver un ejemplo' abre
# más opciones pero está vacía"— y no dónde. Con un menú de tres niveles
# eso deja abriendo pasos uno por uno buscando cuál es, y dos botones
# pueden llamarse igual en ramas distintas.
#
# Ahora `_revisar_mapa` devuelve además:
#
#   donde   el recorrido tal y como se lee en la pantalla
#   ruta    los índices del paso, para que el editor lo ABRA solo
#
# Lo que se vigila aquí es que `donde` hable el idioma de la pantalla
# ("Botón 2 · Ver un ejemplo") y que `ruta` apunte de verdad a ese paso.
# Si un día el árbol cambia cómo titula sus tarjetas y esto no se entera,
# el error mandaría a buscar un botón que en pantalla se llama de otra
# forma — peor que no decir nada.

print("\n=== Un error del mapa dice en qué paso está ===")

_ARBOL = {"menu": [
    {"id": "servicios", "title": "Servicios", "accion": "submenu", "submenu": [
        {"id": "chatbots", "title": "Chatbots", "accion": "info", "mensaje": "x"},
        {"id": "powerbi", "title": "Power BI", "accion": "submenu", "submenu": [
            {"id": "tableros", "title": "Tableros", "accion": "info", "mensaje": "x"},
            {"id": "ver_ejemplo", "title": "Ver un ejemplo", "accion": "submenu"},
        ]},
    ]},
    {"id": "asesor", "title": "Hablar con alguien", "accion": "humano"},
]}

_motivo, _donde, _ruta = _super._revisar_mapa(_ARBOL)

check("caza el submenú vacío, por hondo que esté", bool(_motivo), _motivo[:50])
check("y dice el recorrido entero hasta él",
      _donde == "El menú → Botón 1 · Servicios → Botón 2 · Power BI "
                "→ Botón 2 · Ver un ejemplo", _donde)
check("con la ruta que el editor necesita para abrirlo",
      _ruta == [0, 1, 1], str(_ruta))


def _paso_en(negocio, ruta):
    """El paso al que apunta una ruta, como hace `opcionEn` en el editor."""
    lista, opcion = negocio["menu"], None
    for i in ruta:
        opcion = lista[i]
        lista = opcion.get("submenu") or []
    return opcion


check("y la ruta lleva al paso que el mensaje nombra",
      _paso_en(_ARBOL, _ruta)["title"] == "Ver un ejemplo")

# "Fila" y no "Botón" cuando el grupo pasa de 3: es lo que dice la
# tarjeta del árbol, porque es lo que WhatsApp le manda al cliente.
_CUATRO = {"menu": [{"id": "r", "title": "R", "accion": "submenu", "submenu": [
    {"id": "a", "title": "A", "accion": "info", "mensaje": "x"},
    {"id": "b", "title": "B", "accion": "info", "mensaje": "x"},
    {"id": "c", "title": "C", "accion": "info", "mensaje": "x"},
    {"id": "d", "title": "D", "accion": "submenu"},
]}]}
check("llama 'Fila' a lo que sale en lista y 'Botón' a lo que sale suelto",
      _super._revisar_mapa(_CUATRO)[1].endswith("Fila 4 · D"),
      _super._revisar_mapa(_CUATRO)[1])

# Un paso sin texto tiene que poder nombrarse igual: es justo el que no
# se distingue de los demás mirando el árbol.
_SIN_TEXTO = {"menu": [{"id": "a", "title": "", "accion": "info"}]}
check("un paso sin texto también se sabe cuál es",
      _super._revisar_mapa(_SIN_TEXTO)[1] == "El menú → Botón 1 · (sin texto)",
      _super._revisar_mapa(_SIN_TEXTO)[1])

# Los dos que se llaman igual: el mensaje tiene que nombrar los DOS
# sitios, o se cambia el que no era.
_REPES = {"menu": [
    {"id": "asesor", "title": "Hablar", "accion": "humano"},
    {"id": "otro", "title": "Servicios", "accion": "submenu", "submenu": [
        {"id": "asesor", "title": "Con alguien", "accion": "humano"}]},
]}
_m, _d, _r = _super._revisar_mapa(_REPES)
check("con dos identificadores iguales, nombra los dos sitios",
      "Botón 1 · Hablar" in _m and _d.endswith("Botón 1 · Con alguien"),
      f"{_m[:60]} | {_d}")

check("un mapa sano no señala ningún paso",
      _super._revisar_mapa({"menu": [
          {"id": "a", "title": "A", "accion": "info", "mensaje": "x"}]})
      == ("", "", []))

# El respaldo: un error que solo sabe el identificador (los de
# `ConfiguracionCliente`) también tiene que poder llevar hasta el paso.
_donde2, _ruta2 = _super._donde_esta(
    _ARBOL, "negocio.toml: la opción 'tableros' pide el enlace 'x'.")
check("un error que solo nombra el id se localiza igual",
      _ruta2 == [0, 1, 0] and _donde2.endswith("Botón 1 · Tableros"),
      f"{_donde2} {_ruta2}")
check("y si no reconoce ningún paso, no se inventa uno",
      _super._donde_esta(_ARBOL, "algo que no nombra nada") == ("", []))


# ── 8c-quater. Un aviso ACEPTADO no es un aviso ENTREGADO ────────────
#
# Meta responde 200 cuando ACEPTA un mensaje, no cuando lo entrega. Si
# luego no puede entregarlo —el destinatario no le escribió al bot en 24 h,
# el número no tiene WhatsApp— eso NO vuelve como error de la llamada:
# llega después, en un webhook de estado.
#
# Ese webhook se estaba ignorando entero, así que la única señal de que un
# lead no le llegó a nadie se perdía. Desde fuera se veía idéntico a un
# día sin clientes.

print("\n=== Un aviso aceptado no es un aviso entregado ===")

from app.core import tenencia                                 # noqa: E402

_FALLIDO = {
    "status": "failed",
    "recipient_id": "34612345678",
    "errors": [{"code": 131047, "title": "Re-engagement message",
                "error_data": {"details": "more than 24 hours have passed"}}],
}

class _NegocioDeLaURL:
    """
    El cliente que dijo la URL del webhook, como lo pasa `_atender`.

    Se usa este camino y no el viejo porque es el que va a quedar: con la
    App de Meta de cada cliente, el inquilino sale de la URL y no del
    `phone_number_id` del cuerpo.
    """
    id = database.CLIENTE_POR_DEFECTO


with tenencia.usar(database.CLIENTE_POR_DEFECTO):
    main._anotar_entregas_fallidas([_FALLIDO], _NegocioDeLaURL(), {})
    _u = _avisos.ultimo_no_entregado()

check("un webhook de entrega fallida queda anotado",
      _u is not None and _u["numero"] == "34612345678", str(_u))
check("y con el motivo que dio Meta",
      _u and "24 hours" in _u["motivo"], str(_u and _u["motivo"])[:60])

# Los `delivered` y `read` llegan varios por mensaje: anotarlos seria ruido.
with tenencia.usar(database.CLIENTE_POR_DEFECTO):
    _antes = _avisos.ultimo_no_entregado()
    main._anotar_entregas_fallidas(
        [{"status": "delivered", "recipient_id": "573001112233"}],
        _NegocioDeLaURL(), {})
    _despues = _avisos.ultimo_no_entregado()

check("una entrega correcta no pisa el último fallo",
      _antes == _despues, f"{_antes} -> {_despues}")

# La causa n.º 1 de que un aviso aceptado no llegue, y se puede saber
# ANTES de mandar nada: mirando si esa persona le escribió al bot.
with tenencia.usar(database.CLIENTE_POR_DEFECTO):
    check("un número que nunca escribió al bot tiene la ventana cerrada",
          _avisos.ventana_abierta("34999888777") is False)
    check("y uno vacío tampoco la tiene abierta",
          _avisos.ventana_abierta("") is False)


# ── 8c-quinquies. Con la ventana cerrada se va DIRECTO a la plantilla ─
#
# Antes se intentaba el texto libre y solo se reintentaba con plantilla si
# el envío devolvía error. Como Meta devuelve 200 aunque no vaya a
# entregarlo, ese reintento NO SE DISPARÓ NUNCA. La red de seguridad
# llevaba puesta desde el principio y no se activó jamás.
#
# Era exactamente el síntoma que reportó el dueño: a él le llegaban los
# avisos —le escribe al bot, su ventana está abierta— y a los números de
# las áreas no les llegaba nada, sin error en ningún sitio.

print("\n=== Con la ventana cerrada, el aviso sale por plantilla ===")

_enviado = {"texto": 0, "plantilla": 0}
_wa_texto, _wa_plantilla = whatsapp_client.send_text_message, whatsapp_client.send_template_message


class _Ok:
    status_code = 200
    text = "{}"

    def json(self):
        return {}


whatsapp_client.send_text_message = (
    lambda to, texto, autor="bot": (_enviado.__setitem__("texto", _enviado["texto"] + 1), _Ok())[-1])
whatsapp_client.send_template_message = (
    lambda to, p, i, v: (_enviado.__setitem__("plantilla", _enviado["plantilla"] + 1), _Ok())[-1])

config.OWNER_TEMPLATE_NAME = "aviso_lead"
config.AVISOS_DESTINOS = []

# Un número que NUNCA le escribió al bot: su ventana está cerrada, que es
# la situación de cualquier área recién configurada.
#
# El número tiene que ser EXCLUSIVO de este bloque. La primera versión usó
# 573009998877, que otra prueba de más arriba ya usaba como cliente — y
# ese cliente sí le había escrito al bot, así que su ventana estaba
# abierta y la comprobación fallaba diciendo la verdad.
SIN_VENTANA = "573001234599"
config.OWNER_PHONE_NUMBER = SIN_VENTANA
_enviado.update(texto=0, plantilla=0)
_avisos.avisar_dueno("hola", ["cita", "Ana", "573001", "mañana"])

check("con la ventana cerrada NO se manda texto libre",
      _enviado["texto"] == 0, f"textos={_enviado['texto']}")
check("y sale por plantilla, que es lo que sí atraviesa la ventana",
      _enviado["plantilla"] == 1, f"plantillas={_enviado['plantilla']}")

# Un aviso SIN variables no cabe en una plantilla de cuatro huecos: Meta
# lo rechazaría. Ese sigue por texto libre.
_enviado.update(texto=0, plantilla=0)
_avisos.avisar_dueno("tu bot no tiene menú", [])

check("un aviso sin variables no intenta la plantilla",
      _enviado["plantilla"] == 0 and _enviado["texto"] == 1,
      f"texto={_enviado['texto']} plantilla={_enviado['plantilla']}")

# Con la ventana ABIERTA se manda el texto bonito, no la plantilla: es
# más legible y no gasta una plantilla.
_log.registrar(SIN_VENTANA, "entrante", "cliente", "hola")
_enviado.update(texto=0, plantilla=0)
_avisos.avisar_dueno("hola", ["cita", "Ana", "573001", "mañana"])

check("con la ventana abierta se manda el texto normal",
      _enviado["texto"] == 1 and _enviado["plantilla"] == 0,
      f"texto={_enviado['texto']} plantilla={_enviado['plantilla']}")

whatsapp_client.send_text_message = _wa_texto
whatsapp_client.send_template_message = _wa_plantilla
config.OWNER_PHONE_NUMBER = "573000000000"


# ── 8c-sexies. El aviso por correo ───────────────────────────────────
#
# WhatsApp NO sirve para avisar a un equipo, y costó tres rondas
# descubrirlo: la ventana de 24 h, la plantilla aprobada y la facturación
# de la cuenta son tres puertas capaces de bloquear el aviso por su
# cuenta, y las tres fallan en silencio.
#
# El correo no tiene ninguna. Es la vía principal desde ahora.

print("\n=== El aviso por correo ===")
import time                                                   # noqa: E402
from app.core import correo as _correo                        # noqa: E402

check("sin SMTP configurado no se intenta enviar",
      _correo.configurado() is False)
_ok_sin, _exp_sin = _correo.enviar_ahora(["a@b.com"], "x", "y")
check("y se explica por qué, en vez de fallar en silencio",
      _ok_sin is False and "servidor de correo" in _exp_sin, _exp_sin)
check("una dirección sin arroba se descarta",
      _correo.enviar_ahora(["esto-no-es-un-correo"], "x", "y")[0] is False)

# Un área vale con SOLO correo. Antes hacía falta el número sí o sí, y eso
# dejaba fuera al caso que ahora es el normal.
_solo_correo = _cfg._leer_destinos(
    [{"nombre": "Ventas", "correo": "ventas@x.com", "opciones": []}])
check("un área con solo correo es válida",
      len(_solo_correo) == 1 and _solo_correo[0]["correo"] == "ventas@x.com",
      str(_solo_correo))
check("y queda sin número, sin inventarse ninguno",
      _solo_correo[0]["numero"] == "")
check("un área sin correo NI número se descarta",
      _cfg._leer_destinos([{"nombre": "Vacía", "opciones": []}]) == [])

# El correo que sale de verdad: lo que importa es que se pueda ACTUAR
# desde él sin tener que buscar nada.
config.SMTP_HOST = "smtp.ejemplo.com"
config.SMTP_DESDE = "avisos@nitro2tech.com"

_capturado = {}


class _SMTPFalso:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, *a, **k): pass
    def login(self, *a): pass
    def send_message(self, m): _capturado["m"] = m


import smtplib as _smtplib                                    # noqa: E402
_smtp_real = _smtplib.SMTP
_smtplib.SMTP = _SMTPFalso

_avisos._avisar_por_correo(
    "ventas@panaderia.com", "Ventas",
    "NUEVA CITA\nNombre: Ana",
    ["cita", "Ana", "573001112233", "mañana"])
time.sleep(1.2)

_m = _capturado.get("m")
check("el correo sale con el negocio y el área en el asunto",
      _m is not None and "cita" in _m["Subject"] and "Ventas" in _m["Subject"],
      str(_m["Subject"]) if _m else "no salió")
# A LA CUENTA QUE ENVIA NO LE LLEGA COPIA. Estuvo con `To` a la direccion
# remitente y los destinos en copia oculta, y el efecto era que el dueno de
# la plataforma recibia un correo por cada aviso de cada cliente.
check("el correo va al area, y solo al area",
      _m and _m["To"] == "ventas@panaderia.com" and not _m["Bcc"],
      f"To={_m['To']!r} Bcc={_m['Bcc']!r}" if _m else "no salio")
check("la cuenta que envia NO recibe copia",
      _m and config.SMTP_DESDE not in (_m["To"] or ""),
      f"To={_m['To']!r}" if _m else "")
# Y el nombre que se ve es el del NEGOCIO: quien lo recibe trabaja en la
# panaderia, no en Nitro.
check("el remitente se ve con el nombre del negocio",
      _m and _m["From"].startswith(config.BUSINESS_NAME),
      str(_m["From"]) if _m else "")

_texto = _m.get_body(("plain",)).get_content() if _m else ""
_html = _m.get_body(("html",)).get_content() if _m else ""

# Los dos enlaces son la mitad de la utilidad del aviso: quien lo recibe
# puede no tener usuario del panel, y aun así tiene que poder contactar al
# cliente.
check("lleva el enlace para escribirle al cliente por WhatsApp",
      "wa.me/573001112233" in _texto and "wa.me/573001112233" in _html)
check("y el enlace a la conversación en el panel",
      "/admin/chat/573001112233" in _texto and "/admin/chat/573001112233" in _html)
check("va en texto y en HTML, para que se lea en cualquier cliente",
      bool(_texto) and bool(_html))

_smtplib.SMTP = _smtp_real
config.SMTP_HOST = ""
config.SMTP_DESDE = ""


# ── 8d. El paquete de IA se contrata ─────────────────────────────────
#
# Antes la única puerta era "¿hay clave de Gemini?". Esa no es la
# pregunta: la clave la ponemos NOSOTROS y es la misma para todos, así que
# cualquier cliente podía encender la IA desde su panel y cargarnos el
# consumo sin haberla pagado.

print("\n=== La IA hay que haberla contratado ===")
from app.bot import cerebro as _cerebro                       # noqa: E402

_ia_antes = getattr(_cfg, "IA_CONTRATADA", False)
_clave_antes = _cfg.GEMINI_API_KEY

_cfg.GEMINI_API_KEY = "clave-de-prueba"
_cfg.IA_CONTRATADA = False
check("sin contratar, el plan es Básico aunque HAYA clave",
      _cerebro.plan_activo() == _cerebro.BASICO, _cerebro.plan_activo())
check("y el panel del cliente no dice que esté contratada",
      _cerebro.estado()["contratada"] is False)

try:
    _cerebro.cambiar_plan("pro")
    check("y el endpoint tampoco deja encenderla", False, "no lanzó excepción")
except ValueError:
    # La puerta tiene que estar en el camino que decide, no solo en el
    # HTML: esconder un botón mientras el endpoint sigue aceptando la
    # petición no es una puerta, es un adorno.
    check("y el endpoint tampoco deja encenderla", True)

_cfg.IA_CONTRATADA = True
check("contratada y con clave, ya se puede",
      _cerebro.estado()["contratada"] is True)

_cfg.IA_CONTRATADA = _ia_antes
_cfg.GEMINI_API_KEY = _clave_antes


# ── 9. Limpieza de mensajes procesados ───────────────────────────────

print("\n=== Limpieza de IDs de mensajes ===")
s = database.get_session()
s.add(database.ProcessedMessage(message_id="wamid.VIEJO",
                                received_at=database.ahora_utc() - timedelta(days=30)))
s.commit()
antes = s.query(database.ProcessedMessage).count()
s.close()

database.limpiar_mensajes_procesados(dias=7)

s = database.get_session()
despues = s.query(database.ProcessedMessage).count()
s.close()
check("borra los IDs de más de 7 días", despues == antes - 1, f"{antes} -> {despues}")

print("\n=== Limpieza del historial de conversaciones ===")
TEL_VIEJO = "573004445566"   # un número propio: si comparte con otra
                             # prueba, arrastra los mensajes de aquella
s = database.get_session()
s.add(database.Message(phone=TEL_VIEJO, direccion="entrante", autor="cliente",
                       texto="mensaje de hace un año",
                       created_at=database.ahora_utc() - timedelta(days=365)))
s.add(database.Message(phone=TEL_VIEJO, direccion="entrante", autor="cliente",
                       texto="mensaje de ayer",
                       created_at=database.ahora_utc() - timedelta(days=1)))
s.commit()
s.close()

borrados = database.limpiar_mensajes_antiguos(dias=180)

s = database.get_session()
quedan = [m.texto for m in s.query(database.Message).filter_by(phone=TEL_VIEJO).all()]
leads_vivos = s.query(database.Lead).count()
s.close()

check("borra la conversación de más de 180 días",
      "mensaje de hace un año" not in quedan and borrados >= 1, f"borró {borrados}")
check("y respeta la reciente", "mensaje de ayer" in quedan, str(quedan))
check("no toca los leads ni las citas, que son el registro comercial",
      leads_vivos > 0, f"{leads_vivos} leads")

# Un 0 mal puesto en las variables de entorno borraría el historial
# ENTERO en el primer arranque, y eso no se deshace.
check("con 0 días no borra nada, en vez de borrarlo todo",
      database.limpiar_mensajes_antiguos(dias=0) == 0)
s = database.get_session()
check("y el mensaje reciente sigue ahí",
      s.query(database.Message).filter_by(phone=TEL_VIEJO).count() == 1)
s.close()

# El plazo es de cada negocio (`clients.historial_dias`): son datos de
# terceros y no puede decidirlo una variable de entorno del despliegue.
s = database.get_session()
s.add(database.Message(phone=TEL_VIEJO, direccion="entrante", autor="cliente",
                       texto="mensaje de hace un mes",
                       created_at=database.ahora_utc() - timedelta(days=30)))
s.query(database.Client).filter_by(id=config.CLIENTE_POR_DEFECTO).update(
    {"historial_dias": 7})
s.commit()
s.close()

_borrados = database.limpiar_mensajes_antiguos()      # sin forzar plazo

s = database.get_session()
_quedan = [m.texto for m in s.query(database.Message).filter_by(phone=TEL_VIEJO).all()]
s.close()

check("manda el plazo del cliente, no el de la plataforma",
      "mensaje de hace un mes" not in _quedan and _borrados >= 1,
      f"borró {_borrados}, quedan {_quedan}")
check("y lo de dentro del plazo se queda", "mensaje de ayer" in _quedan)

s = database.get_session()
s.query(database.Client).filter_by(id=config.CLIENTE_POR_DEFECTO).update(
    {"historial_dias": None})
s.commit(); s.close()

print("\n=== El contenido vive en negocio.toml ===")
import json as _json  # noqa: E402
import subprocess as _sub  # noqa: E402
import inspect as _insp  # noqa: E402

PROY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

check("config lee negocio.toml y no lo lleva escrito dentro",
      os.path.exists(config.NEGOCIO_TOML), config.NEGOCIO_TOML)

# LA prueba que habría cazado el fallo de la migración: el generador
# sustituyó "{negocio}" hasta dentro de la propia definición del nombre,
# así que BUSINESS_NAME valía literalmente "{negocio}" y todo texto que
# lo interpola salía mal.
_expuestos = {n: getattr(config, n) for n in dir(config)
              if n.isupper() and not n.startswith("_")
              and not callable(getattr(config, n))
              and not _insp.ismodule(getattr(config, n))}


def _cadenas(valor):
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for v in valor.values():
            yield from _cadenas(v)
    elif isinstance(valor, (list, tuple)):
        for v in valor:
            yield from _cadenas(v)


_sin_rellenar = sorted(
    n for n, v in _expuestos.items()
    for t in _cadenas(v) if "{negocio}" in t or "{duracion}" in t)
check("no queda ningún hueco de la plantilla sin rellenar",
      not _sin_rellenar, str(_sin_rellenar)[:120])
check("y el nombre del negocio es un nombre de verdad",
      config.BUSINESS_NAME and "{" not in config.BUSINESS_NAME,
      repr(config.BUSINESS_NAME))

# El menú tiene que quedar RESUELTO: las referencias por nombre del TOML
# convertidas en los valores que el resto del código ya leía.
_todas = []
for _o in config.NEED_OPTIONS + config.CIERRE_OPTIONS:
    _todas.append(_o)
    _todas.extend(_o.get("submenu", []))
check("las opciones con precios traen su texto ya puesto",
      all("mensaje" in o for o in _todas if o["id"].endswith("_precios")))
check("y ninguna se queda con la referencia sin resolver",
      not any("enlace" in o or "precios" in o for o in _todas))

# El otro fallo del generador: como hoy los cuatro enlaces apuntan a la
# misma URL, un mapeo por valor los colapsaba y TODAS las opciones
# acababan con el mismo. Con las cuatro distintas se nota.
_entorno = dict(os.environ)
_entorno.update({
    "PRICING_URL": "https://ej.test/precios",
    "POWERBI_DEMO_URL": "https://ej.test/powerbi",
    "WEB_DEMO_URL": "https://ej.test/web",
    "AUTOMATIZACION_DEMO_URL": "https://ej.test/autos",
    "PYTHONIOENCODING": "utf-8",
})
_guion = (
    "import json;from app import config as c;"
    "o=[x for m in c.NEED_OPTIONS for x in [m]+m.get('submenu',[])];"
    "print(json.dumps({x['id']: x.get('url') for x in o if x.get('url')}))"
)
_salida = _sub.run([sys.executable, "-c", _guion], capture_output=True,
                   text=True, encoding="utf-8", env=_entorno, cwd=PROY)
_urls = _json.loads(_salida.stdout.strip().splitlines()[-1])
check("cada opción resuelve SU enlace, no el de otra",
      _urls.get("powerbi_demo") == "https://ej.test/powerbi"
      and _urls.get("web_ejemplos") == "https://ej.test/web"
      and _urls.get("auto_ejemplos") == "https://ej.test/autos"
      and _urls.get("chatbot_precios") == "https://ej.test/precios",
      str(_urls))
check("las variables de entorno siguen ganando sobre el TOML",
      all(u.startswith("https://ej.test/") for u in _urls.values()))

# Un TOML que nombra un enlace inexistente tiene que fallar AL ARRANCAR,
# no mandarle un mensaje en blanco a un cliente.
_roto = os.path.join(tempfile.mkdtemp(), "roto.toml")
_texto_toml = open(os.path.join(PROY, "negocio.toml"), encoding="utf-8").read()
# Se ancla en un valor que aparece UNA sola vez. Con uno repetido se
# corre el riesgo de tocar el ejemplo de un comentario y creer que la
# prueba pasa cuando en realidad no rompió nada.
assert _texto_toml.count('enlace = "powerbi_demo"') == 1
open(_roto, "w", encoding="utf-8").write(
    _texto_toml.replace('enlace = "powerbi_demo"', 'enlace = "no_existe"', 1))
_falla = _sub.run([sys.executable, "-c", "from app import config"],
                  capture_output=True, text=True, encoding="utf-8", cwd=PROY,
                  env={**_entorno, "NEGOCIO_TOML": _roto})
check("un enlace que no existe no arranca en silencio",
      _falla.returncode != 0 and "no_existe" in _falla.stderr,
      _falla.stderr.strip().splitlines()[-1][:90] if _falla.stderr else "(sin error)")

# Y la prueba de que esto sirve para lo que se hizo: otro negocio, otros
# textos, sin tocar una línea de Python.
_otro = os.path.join(tempfile.mkdtemp(), "otro.toml")
open(_otro, "w", encoding="utf-8").write(
    _texto_toml.replace('nombre = "Nitro 2Tech"', 'nombre = "Panadería Doña Eva"', 1))
_res = _sub.run(
    [sys.executable, "-c",
     "from app import config as c;print(c.BUSINESS_NAME);print(c.WELCOME_MESSAGE)"],
    capture_output=True, text=True, encoding="utf-8", cwd=PROY,
    env={**_entorno, "NEGOCIO_TOML": _otro})
check("otro negocio solo cambia el TOML, no el código",
      "Panadería Doña Eva" in _res.stdout and "Nitro" not in _res.stdout,
      _res.stdout.strip().replace("\n", " | ")[:100])

print("\n=== La plantilla se puede correr en local recién clonada ===")
# El valor por defecto del codigo apunta al disco del servidor
# (/var/data/bot.db), que en produccion es lo correcto pero en una
# maquina de trabajo no existe. Quien clone el repo y copie .env.example
# tiene que poder arrancar sin averiguar esto por su cuenta.
_ejemplo = {}
for _linea in open(os.path.join(PROY, ".env.example"), encoding="utf-8"):
    _linea = _linea.strip()
    if _linea and not _linea.startswith("#") and "=" in _linea:
        _c, _, _v = _linea.partition("=")
        _ejemplo[_c.strip()] = _v.strip()

_db_ejemplo = _ejemplo.get("DATABASE_URL", "")
check("`.env.example` trae una base que funciona en cualquier máquina",
      _db_ejemplo.startswith("sqlite:///") and not _db_ejemplo.startswith("sqlite:////"),
      _db_ejemplo or "(no define DATABASE_URL)")

# Y el defecto del codigo, el que se usa cuando NO hay .env, tiene que
# seguir apuntando al disco: es lo que salva produccion si render.yaml no
# se aplicara.
_defecto = _sub.run(
    [sys.executable, "-c",
     "import os;os.environ.pop('DATABASE_URL',None);"
     "from dotenv import load_dotenv;"
     "import app.config as c;print(c.DATABASE_URL)"],
    capture_output=True, text=True, encoding="utf-8",
    cwd=tempfile.mkdtemp(),
    env={**{k: v for k, v in os.environ.items() if k != "DATABASE_URL"},
         "PYTHONPATH": PROY,
         "NEGOCIO_TOML": os.path.join(PROY, "negocio.toml")})
check("y sin .env el defecto sigue siendo el disco del servidor",
      "/var/data/" in _defecto.stdout, _defecto.stdout.strip()[:60])

print("\n=== SQLite listo para producción (base en disco) ===")
from sqlalchemy import text  # noqa: E402
# En producción la base es un archivo, y lo tocan a la vez el webhook (en
# su propio hilo), el panel abierto y el canal en vivo. Sin esto, el
# segundo en llegar se lleva un "database is locked".
if database.DATABASE_URL.startswith("sqlite"):
    s = database.get_session()
    modo = s.execute(text("PRAGMA journal_mode")).scalar()
    espera = s.execute(text("PRAGMA busy_timeout")).scalar()
    s.close()
    check("leer y escribir a la vez no se bloquean (WAL)",
          str(modo).lower() == "wal", f"journal_mode = {modo}")
    check("ante un choque espera en vez de fallar al instante",
          int(espera) >= 5000, f"busy_timeout = {espera} ms")
else:
    check("(base Postgres: no aplica)", True)

print("\n=== El diagnóstico avisa si la base se va a borrar sola ===")
# Una base dentro de la carpeta del código desaparece en cada despliegue
# SIN dar ningún error: desde fuera se ve igual que si todo fuera bien.
# Esto es lo único que lo delata antes de perder las conversaciones.
from sqlalchemy import create_engine as _crear  # noqa: E402
from sqlalchemy.orm import sessionmaker as _sesionero  # noqa: E402


def _diagnostico_de(url):
    motor = _crear(url, connect_args={"check_same_thread": False})
    sesion = _sesionero(bind=motor)()
    try:
        return admin_api._donde_vive_la_base(sesion)
    finally:
        sesion.close()
        motor.dispose()


_efimera = _diagnostico_de("sqlite:///" + os.path.join(os.getcwd(), "efimera.db")
                           .replace("\\", "/"))
check("detecta una base que se borra en cada despliegue",
      _efimera["sobrevive_al_despliegue"] is False, str(_efimera.get("archivo")))
check("y explica qué revisar", "DATABASE_URL" in _efimera.get("aviso", ""))

_en_disco = _diagnostico_de(
    "sqlite:///" + os.path.join(tempfile.mkdtemp(), "bot.db").replace("\\", "/"))
check("da por buena una base fuera de la carpeta del código",
      _en_disco["sobrevive_al_despliegue"] is True, str(_en_disco.get("archivo")))
check("y no incluye aviso cuando está bien", "aviso" not in _en_disco)
check("dice en qué modo quedó SQLite",
      _en_disco.get("modo_concurrencia") is not None,
      str(_en_disco.get("modo_concurrencia")))

for _sobrante in ("efimera.db", "efimera.db-wal", "efimera.db-shm"):
    if os.path.exists(_sobrante):
        os.remove(_sobrante)


# ── Revisión del 23-sep-2026 ─────────────────────────────────────────
#
# Cada bloque de aquí es un fallo que existía y que ninguna suite veía.
# Casi todos tenían la forma de siempre en este proyecto: no daban error,
# solo dejaban a alguien sin recibir algo.

print("\n=== Un negocio sin número del dueño no avisa a un desconocido ===")
# El defecto era "573001234567": un número colombiano con formato válido.
# Un negocio sin áreas y sin número del dueño le mandaba a ese número el
# nombre, el teléfono y la consulta de cada uno de sus clientes.
from app.core.config_cliente import ConfiguracionCliente as _CC  # noqa: E402

_sin_dueno = _CC(fila={"id": 99, "nombre": "Sin dueño"},
                 negocio={"negocio": {"nombre": "Sin dueño"}})
check("sin número del dueño, el número del dueño queda vacío",
      _sin_dueno.OWNER_PHONE_NUMBER == "", repr(_sin_dueno.OWNER_PHONE_NUMBER))
check("y el verify token tampoco es uno adivinable",
      _sin_dueno.VERIFY_TOKEN == "", repr(_sin_dueno.VERIFY_TOKEN))

_dueno_antes = config.OWNER_PHONE_NUMBER
_areas_antes = config.AVISOS_DESTINOS
config.OWNER_PHONE_NUMBER = ""
config.AVISOS_DESTINOS = []
enviados.clear()
_avisos.avisar_dueno("un lead", ["cita", "Ana", "573001", "mañana"])
check("sin nadie configurado no se le escribe a ningún número",
      not enviados, str(enviados[:1]))
config.OWNER_PHONE_NUMBER = _dueno_antes
config.AVISOS_DESTINOS = _areas_antes


print("\n=== Un área solo con correo, sin correo en la plataforma ===")
# Contaba como entregado aunque la plataforma no tuviera SMTP: el aviso no
# salía por ningún lado y `avisar_dueno` decía que sí.
config.AVISOS_DESTINOS = [{"nombre": "Ventas", "numero": "",
                           "correo": "ventas@negocio.test", "opciones": []}]
_smtp_antes = config.SMTP_HOST
config.SMTP_HOST = ""
enviados.clear()
_llego = _avisos.avisar_dueno("un lead", ["cita", "Ana", "573001", "mañana"])
check("el aviso cae al número del dueño en vez de perderse",
      any(t[1] == config.OWNER_PHONE_NUMBER for t in enviados),
      f"enviados={len(enviados)}")
check("y dice que llegó porque de verdad salió por algún sitio", _llego is True)
config.SMTP_HOST = _smtp_antes
config.AVISOS_DESTINOS = _areas_antes


print("\n=== Un correo que falla en su hilo deja rastro ===")
from app.core import correo as _correo  # noqa: E402

_enviar_antes = _correo._enviar


def _smtp_roto(*_a, **_k):
    raise OSError("el servidor de correo no contesta")


_correo._enviar = _smtp_roto
_correo._enviar_o_anotar(["ventas@negocio.test"], "asunto", "cuerpo")
_correo._enviar = _enviar_antes
_ultimo = _avisos.ultimo_no_entregado() or {}
check("el fallo del correo queda anotado donde lo ve el super-admin",
      "ventas@negocio.test" in _ultimo.get("numero", ""), str(_ultimo))


print("\n=== El asunto del correo no acepta saltos de línea ===")
# El nombre del cliente va en el asunto y lo escribe él. Con un salto de
# línea, `EmailMessage` levanta ValueError dentro del hilo y el aviso no
# sale — sin más rastro que una traza en el log.
try:
    _msj = _correo.armar(["a@b.test"], "[N] cita · Ana\nBcc: otro@x.test", "c")
    check("un asunto con salto de línea se arma igual",
          "\n" not in _msj["Subject"], repr(_msj["Subject"]))
except Exception as _e:
    check("un asunto con salto de línea se arma igual", False, repr(_e))


print("\n=== El nombre que escribe el cliente queda en una línea ===")
_TEL_NOMBRE = "573008880001"
msg("hola", phone=_TEL_NOMBRE)
msg("Ana\nPérez\n\n  otra cosa", phone=_TEL_NOMBRE)
_c = estado(_TEL_NOMBRE)
check("sin saltos de línea en el nombre", _c and "\n" not in (_c.name or ""),
      repr(_c.name if _c else None))


print("\n=== Una reacción con emoji no es un archivo ===")
# Reaccionar 👍 a un mensaje del bot le contestaba "¡Gracias! Ya lo
# recibí" con dos botones: un mensaje absurdo y, desde el 1-oct, cobrado.
_TEL_REACCION = "573008880002"
msg("hola", phone=_TEL_REACCION)
msg("Luis", phone=_TEL_REACCION)
enviados.clear()
msg(media={"tipo": "reaction", "emoji": "👍"}, phone=_TEL_REACCION)
check("a una reacción no se le contesta", not enviados, str(enviados[:1]))
check("pero queda en el historial",
      any((m.texto or "") == "👍" for m in historial(_TEL_REACCION)))


print("\n=== Sin red, enviar no revienta ===")
# `_post` no cazaba los errores de red. Un Meta lento al avisar a un área
# subía como excepción hasta `handle_incoming_message`, antes del commit:
# el lead no se guardaba y nadie se enteraba.
import requests as _requests  # noqa: E402

_post_antes = _requests.post


def _sin_red(*_a, **_k):
    raise _requests.ConnectionError("red caída")


_requests.post = _sin_red
try:
    _r = ENVIOS_REALES["texto"]("573001", "hola")
    check("un fallo de red vuelve como respuesta fallida, no como excepción",
          _r.status_code >= 500, f"status={_r.status_code}")
except Exception as _e:
    check("un fallo de red vuelve como respuesta fallida, no como excepción",
          False, repr(_e))
finally:
    _requests.post = _post_antes


print("\n=== El calendario con datos imposibles no cuelga al bot ===")
import threading as _hilos  # noqa: E402
from datetime import date as _fecha  # noqa: E402

_cc_cero = _CC(fila={"id": 98, "nombre": "X"}, negocio={
    "negocio": {"nombre": "X"},
    "horario": {"duracion_cita_min": 0, "dias_a_buscar": "30",
                "horarios_ofrecidos": "15"},
    "ia": {"max_palabras": ""},
})
check("una duración de 0 minutos no llega al calendario",
      _cc_cero.APPOINTMENT_DURATION_MINUTES > 0,
      str(_cc_cero.APPOINTMENT_DURATION_MINUTES))
check("los números escritos como texto se leen como números",
      _cc_cero.APPOINTMENT_SEARCH_DAYS == 30, repr(_cc_cero.APPOINTMENT_SEARCH_DAYS))
check("y nunca se ofrecen más horarios de los que caben en una lista",
      _cc_cero.APPOINTMENT_SLOTS_OFFERED <= 10,
      str(_cc_cero.APPOINTMENT_SLOTS_OFFERED))
check("un largo de respuesta vacío cae a su defecto",
      _cc_cero.IA_MAX_PALABRAS > 0, str(_cc_cero.IA_MAX_PALABRAS))
check("sin nombres de días escritos, usa los de siempre",
      len(_cc_cero.DIAS_SEMANA) == 7 and len(_cc_cero.MESES) == 12)

_duracion_antes = config.APPOINTMENT_DURATION_MINUTES
config.APPOINTMENT_DURATION_MINUTES = 0
_hilo = _hilos.Thread(target=lambda: calendar_service._slots_del_dia(
    _fecha.today(), [], calendar_service.ahora_local()), daemon=True)
_hilo.start()
_hilo.join(3)
check("con duración 0 el cálculo de horarios termina", not _hilo.is_alive())
config.APPOINTMENT_DURATION_MINUTES = _duracion_antes

_zona_antes = config.BUSINESS_TIMEZONE
config.BUSINESS_TIMEZONE = ""
try:
    # `ahora_local` y no `dias_con_disponibilidad`, que esta suite
    # sustituye más arriba para no hablar con Google. Es lo primero que
    # esa función llama.
    calendar_service.ahora_local()
    check("sin zona horaria, el calendario se da por no disponible", False,
          "no levantó nada")
except calendar_service.CalendarNoDisponible:
    check("sin zona horaria, el calendario se da por no disponible", True)
except Exception as _e:
    check("sin zona horaria, el calendario se da por no disponible", False,
          repr(_e))
finally:
    config.BUSINESS_TIMEZONE = _zona_antes


print("\n=== Google lento no retiene el webhook minutos ===")
from app.integrations import google_client as _google  # noqa: E402

try:
    _http = _google._http(object())
    check("las llamadas a Google llevan nuestro plazo, no el de 60 s",
          getattr(_http.http, "timeout", None) == _google.TIMEOUT,
          str(getattr(_http.http, "timeout", None)))
except Exception as _e:
    check("las llamadas a Google llevan nuestro plazo, no el de 60 s", False,
          repr(_e))


print("\n=== El caché de archivos se limpia en TODOS los negocios ===")
from app.core import media as _media  # noqa: E402
import time as _tiempo  # noqa: E402

_raiz_media = tempfile.mkdtemp()
_media_antes = os.environ.get("MEDIA_DIR")
os.environ["MEDIA_DIR"] = _raiz_media
_viejos = []
for _cid in ("1", "7"):
    os.makedirs(os.path.join(_raiz_media, _cid))
    _ruta = os.path.join(_raiz_media, _cid, "10.jpg")
    with open(_ruta, "wb") as _f:
        _f.write(b"x")
    _hace = _tiempo.time() - 5 * 86400
    os.utime(_ruta, (_hace, _hace))
    _viejos.append(_ruta)
_media.limpiar_cache(dias=1, tope_mb=200)
check("se borra lo viejo del cliente 1", not os.path.exists(_viejos[0]))
check("y también lo del cliente 7", not os.path.exists(_viejos[1]))
if _media_antes is None:
    os.environ.pop("MEDIA_DIR", None)
else:
    os.environ["MEDIA_DIR"] = _media_antes


print("\n=== Un archivo que Meta no entrega no tumba el panel ===")
_get_antes = _requests.get


def _sin_red_get(*_a, **_k):
    raise _requests.ConnectionError("red caída")


_requests.get = _sin_red_get
try:
    _media.descargar("123")
    check("sin red, bajar un archivo da MediaError", False, "no levantó")
except _media.MediaError:
    check("sin red, bajar un archivo da MediaError", True)
except Exception as _e:
    check("sin red, bajar un archivo da MediaError", False, repr(_e))
finally:
    _requests.get = _get_antes


print("\n=== La IA no manda la palabra 'null' ===")
from app.bot.cerebro import gemini as _gem  # noqa: E402

# El prompt le enseña la forma `{"intencion": "id_o_null", ...}`, con
# comillas, así que a veces devuelve la palabra y no el valor. Con la
# intención vacía, esa palabra le llegaba al cliente como respuesta.
_dec = _gem._leer_respuesta('{"intencion": null, "respuesta": "null"}',
                            [{"id": "opt_a", "title": "A"}])
check("'null' escrito como texto cuenta como vacío",
      not _dec.intencion and not _dec.respuesta, repr(_dec))
_dec = _gem._leer_respuesta('{"intencion": "None", "respuesta": null}',
                            [{"id": "opt_a", "title": "A"}])
check("y 'None' tampoco es una opción inventada",
      not _dec.intencion and _gem.ultimo_fallo() is None, repr(_dec))


print("\n=== El editor de contenido no borra lo que no enseña ===")
# El formulario tiene dos niveles de menú y diez campos por opción. El mapa
# tiene más: un tercer nivel, la URL propia, `oculta` y `solo_con_cita`.
# Guardar una vez desde el editor de contenido borraba todo eso.
from html.parser import HTMLParser  # noqa: E402
from starlette.datastructures import FormData  # noqa: E402
from app.web import contenido as _contenido  # noqa: E402


class _Formulario(HTMLParser):
    """Lo que mandaría el navegador al pulsar Guardar sin tocar nada."""

    def __init__(self):
        super().__init__()
        self.campos, self._area, self._select = [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("name"):
            if a.get("type") == "checkbox":
                if "checked" in a:
                    self.campos.append((a["name"], a.get("value", "on")))
            else:
                self.campos.append((a["name"], a.get("value", "")))
        elif tag == "textarea" and a.get("name"):
            self._area = [a["name"], ""]
        elif tag == "select" and a.get("name"):
            self._select = [a["name"], None]
        elif tag == "option" and self._select is not None:
            if self._select[1] is None or "selected" in a:
                self._select[1] = a.get("value", "")

    def handle_data(self, data):
        if self._area is not None:
            self._area[1] += data

    def handle_endtag(self, tag):
        if tag == "textarea" and self._area is not None:
            # El salto que se come el HTML tras <textarea>.
            valor = self._area[1][1:] if self._area[1].startswith("\n") else self._area[1]
            self.campos.append((self._area[0], valor))
            self._area = None
        elif tag == "select" and self._select is not None:
            self.campos.append((self._select[0], self._select[1] or ""))
            self._select = None


_negocio_rico = {
    "negocio": {"nombre": "Rico"},
    "enlaces": {"web": "https://rico.test"},
    "menu": [
        {"id": "o1", "title": "Servicios", "accion": "submenu", "submenu": [
            {"id": "o1a", "title": "Uno", "accion": "submenu", "submenu": [
                {"id": "o1a1", "title": "Hondo", "accion": "info",
                 "mensaje": "Tercer nivel"}]},
            {"id": "o1b", "title": "Propia", "accion": "info",
             "mensaje": "Mira", "url": "https://propia.test"}]},
        {"id": "o2", "title": "Mi cita", "accion": "submenu",
         "solo_con_cita": True, "submenu": [
             {"id": "o2a", "title": "Cancelar", "accion": "cancelar"}]},
        {"id": "o3", "title": "Escondida", "accion": "info", "oculta": True,
         "mensaje": "Solo desde luego"},
    ],
}
_lector = _Formulario()
_lector.feed(_contenido.pintar(_negocio_rico))
_guardado = _contenido.leer(FormData(_lector.campos), _negocio_rico)
_por_id = {}


def _indexar(opciones):
    for _o in opciones or []:
        _por_id[_o["id"]] = _o
        _indexar(_o.get("submenu"))


_indexar(_guardado.get("menu"))
check("el tercer nivel del menú sigue ahí", "o1a1" in _por_id,
      str(sorted(_por_id)))
check("la URL propia de una opción sigue ahí",
      _por_id.get("o1b", {}).get("url") == "https://propia.test")
check("'solo con cita' sigue marcado",
      _por_id.get("o2", {}).get("solo_con_cita") is True)
check("y la opción oculta sigue oculta",
      _por_id.get("o3", {}).get("oculta") is True)
check("lo que sí edita el formulario se guarda",
      _por_id.get("o1b", {}).get("mensaje") == "Mira")

print("\n=== El bot sabe qué eligió el cliente aunque la opción no tenga Sheet ===")
# El mapa no escribe `sheet` en las opciones, y el bot solo anotaba el
# servicio si la opción lo traía: en cualquier negocio armado en el mapa,
# el reparto por áreas no funcionaba y los leads caían en "otros".
_menu_antes = config.NEED_OPTIONS
config.NEED_OPTIONS = [{"id": "opt_sin_sheet", "title": "Sin sheet",
                        "accion": "info", "mensaje": "Hola"},
                       {"id": "opt_dos", "title": "Dos", "accion": "info",
                        "mensaje": "Dos"}]
_TEL_SERV = "573008880003"
msg("hola", phone=_TEL_SERV)
msg("Rosa", phone=_TEL_SERV)
msg(list_id="opt_sin_sheet", phone=_TEL_SERV)
check("el servicio queda anotado", estado(_TEL_SERV).servicio == "opt_sin_sheet",
      repr(estado(_TEL_SERV).servicio))
config.NEED_OPTIONS = _menu_antes


print("\n=== A las áreas se les avisa solo por correo ===")
# Decisión del 23-sep-2026: un aviso por WhatsApp a un área lo cobra Meta.
config.AVISOS_DESTINOS = [{"id": "ventas", "nombre": "Ventas",
                           "numero": "573001110000",
                           "correo": "ventas@negocio.test",
                           "opciones": ["opt_x"]}]
_smtp_antes = config.SMTP_HOST
config.SMTP_HOST, config.SMTP_DESDE = "smtp.prueba", "bot@prueba"
_avisar_antes = _correo.avisar
_correos = []
_correo.avisar = lambda dest, *a, **k: _correos.append(dest)
enviados.clear()
_avisos.avisar_dueno("un lead", ["cita", "Ana", "573001", "mañana"],
                     servicio="opt_x")
check("el área recibe su correo", _correos == [["ventas@negocio.test"]],
      str(_correos))
check("y ningún WhatsApp, aunque tenga número guardado", not enviados,
      str(enviados[:1]))

config.AVISOS_CORREO_DUENO = "dueno@negocio.test"
_correos.clear()
_avisos.avisar_dueno("otro lead", ["consulta", "Ana", "573001", "-"],
                     servicio="opt_de_nadie")
check("lo que no es de ningún área le llega al dueño por correo",
      _correos == [["dueno@negocio.test"]], str(_correos))
config.AVISOS_CORREO_DUENO = ""
_correo.avisar = _avisar_antes
config.SMTP_HOST, config.SMTP_DESDE = _smtp_antes, ""
config.AVISOS_DESTINOS = _areas_antes

print("\n=== Los cobros: avisar, pausar y reactivar ===")
# 24-sep-2026: una semana antes, un correo al día; dos días de gracia; al
# tercero se pausa solo; registrar el pago lo reactiva.
from datetime import date as _d, timedelta as _td  # noqa: E402
from app.core import cobros as _cobros  # noqa: E402

check("un mes después del 31 de enero es el último de febrero",
      _cobros.sumar_un_mes(_d(2026, 1, 31)) == _d(2026, 2, 28))
check("y del 15 de diciembre, el 15 de enero",
      _cobros.sumar_un_mes(_d(2026, 12, 15)) == _d(2027, 1, 15))

_HOY = _d(2026, 10, 10)
_fila_cobro = {"plan": "pro", "active": True}
for _dias, _estado in ((20, _cobros.AL_DIA), (7, _cobros.POR_VENCER),
                       (0, _cobros.POR_VENCER), (-2, _cobros.VENCIDO)):
    _fila_cobro["vence_el"] = _HOY + _td(days=_dias)
    check(f"a {_dias} días del vencimiento está {_estado}",
          _cobros.cuenta(_fila_cobro, _HOY).estado == _estado)
check("sin fecha no se le cobra",
      _cobros.cuenta({"plan": "pro"}, _HOY).estado == _cobros.SIN_COBRO)
check("el precio es el de su plan",
      _cobros.cuenta(_fila_cobro, _HOY).precio == 100_000)
check("salvo que tenga uno pactado",
      _cobros.cuenta(dict(_fila_cobro, precio_mensual=80_000), _HOY).precio == 80_000)

_s = database.get_session()
_s.add(database.Client(id=50, slug="cobro-prueba", nombre="Cobro Prueba",
                       active=True, plan="pro", vence_el=_HOY + _td(days=3),
                       negocio_config={"avisos": {"correo_dueno": "dueno@cobro.test"}}))
_s.commit()
_s.close()

_cobrados = []
_enviar_ahora_antes = _correo.enviar_ahora
_correo.enviar_ahora = lambda dest, asunto, *a, **k: (_cobrados.append((dest, asunto)),
                                                      (True, "enviado"))[-1]

_r = _cobros.revisar_todos(_HOY)
check("a 3 días del vencimiento se le avisa", "cobro-prueba" in _r["avisados"])
check("por correo, al correo del dueño",
      _cobrados and _cobrados[0][0] == ["dueno@cobro.test"], str(_cobrados))
_r = _cobros.revisar_todos(_HOY)
check("y una sola vez al día, aunque la revisión corra cada hora",
      "cobro-prueba" not in _r["avisados"] and len(_cobrados) == 1)
_r = _cobros.revisar_todos(_HOY + _td(days=1))
check("al día siguiente, otro", "cobro-prueba" in _r["avisados"])

_vence = _HOY + _td(days=3)
_r = _cobros.revisar_todos(_vence + _td(days=2))
check("en el segundo día de gracia sigue activo",
      "cobro-prueba" not in _r["pausados"] and _cobros.cuenta_de(50, _vence + _td(days=2)).estado == _cobros.VENCIDO)
_r = _cobros.revisar_todos(_vence + _td(days=3))
check("al tercero se pausa solo", "cobro-prueba" in _r["pausados"])
check("y queda pausado por impago",
      _cobros.cuenta_de(50, _vence + _td(days=3)).estado == _cobros.PAUSADO)
check("y se le avisa de la pausa", "pausado" in _cobrados[-1][1], _cobrados[-1][1])

_nuevo = _cobros.registrar_pago(50, el_dia=_vence + _td(days=4))
_s = database.get_session()
_c = _s.query(database.Client).filter_by(id=50).first()
check("registrar el pago lo reactiva", _c.active and _c.pausado_por is None)
check("y lo deja pagado un mes desde el día del pago (pagó tarde)",
      _nuevo == _cobros.sumar_un_mes(_vence + _td(days=4)), str(_nuevo))
check("con el monto del plan si no se dice otro", _c.ultimo_pago_monto == 100_000)
_s.close()

_antes = _cobros.registrar_pago(50, el_dia=_nuevo - _td(days=3))
check("pagar antes de tiempo no le quita días",
      _antes == _cobros.sumar_un_mes(_nuevo), str(_antes))

_s = database.get_session()
_s.query(database.Client).filter_by(id=50).update(
    {"active": False, "pausado_por": None})
_s.commit()
_s.close()
_cobros.registrar_pago(50)
check("una pausa puesta a mano no la deshace un pago",
      _cobros.cuenta_de(50).estado != _cobros.PAUSADO
      and not database.get_session().query(database.Client).get(50).active)

_correo.enviar_ahora = _enviar_ahora_antes
_s = database.get_session()
_s.query(database.Client).filter_by(id=50).delete()
_s.commit()
_s.close()

# ── Resultado ────────────────────────────────────────────────────────

print("\n" + "=" * 60)
if fallos:
    print(f"FALLARON {len(fallos)} verificaciones:")
    for f in fallos:
        print(f"  - {f}")
    sys.exit(1)

print("Todas las verificaciones pasaron.")
sys.exit(0)
