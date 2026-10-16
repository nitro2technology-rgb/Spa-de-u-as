"""
LEVANTA EL PANEL CON UNA BASE DE MENTIRA, PARA MIRARLO EN EL NAVEGADOR
======================================================================

    python scripts/servir_de_prueba.py
    → http://127.0.0.1:8099/superadmin   ·   clave: prueba

POR QUÉ EXISTE ESTE ARCHIVO
---------------------------
Porque **nada visual se da por bueno sin abrirlo en el navegador** —las
cuatro suites han estado en verde con el panel roto en pantalla, ven
respuestas HTTP y no ven una pantalla— y para abrirlo hace falta una base
con cosas dentro.

Con la base vacía, media consola no se puede revisar: "Requiere atención"
no aparece nunca porque no hay ningún cliente con las credenciales rotas,
el mapa sale sin un solo paso, y los cuadros de texto no se ven crecer
porque no hay texto. O sea que justo lo que se acaba de cambiar es lo que
no se puede mirar.

Estas cuarenta líneas se escribieron ya tres veces en sesiones distintas,
cada una en un directorio temporal que se perdió al acabar. Por eso está
aquí y no ahí.

QUÉ SIEMBRA, Y POR QUÉ ESO
--------------------------
Cuatro clientes, uno por cada estado que la consola pinta distinto: el
que va bien, el de las credenciales rotas, el pausado y el recién dado de
alta sin probar. Y al primero, un menú de tres niveles con textos que
llevan saltos de línea y espacios de más, que es lo que hace falta para
ver de un vistazo si se conservan.

NO TOCA NADA DE VERDAD
----------------------
La base es un SQLite en un temporal y se borra al empezar. No manda
mensajes ni escribe en Google: nada de eso se llega a llamar, porque no
hay conversación. Los secretos son de pega.
"""

import os
import sys
import tempfile

PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROYECTO)
os.chdir(PROYECTO)

BASE = os.path.join(tempfile.gettempdir(), "panel_de_prueba.db").replace("\\", "/")
if os.path.exists(BASE):
    os.remove(BASE)

# Antes de importar nada de `app`: `config` lee el entorno al importarse.
os.environ["DATABASE_URL"] = "sqlite:///" + BASE
os.environ["ADMIN_API_KEY"] = "clave-de-prueba"
os.environ["SUPERADMIN_KEY"] = "prueba"
os.environ.setdefault("SECRETS_KEY", "T2FhOFBTS0RqM3ZzWmJ4TkxxWXc5Y0hHdFJtRXVfMD0=")

from app.core import database   # noqa: E402

PUERTO = 8099

# Un texto con saltos de línea, una línea en blanco y espacios de más:
# es lo que hace falta para ver si el editor los conserva (§4.10) y si el
# cuadro crece hasta caber (§4.11).
SALUDO = ("¡Hola! 👋 Soy el bot de prueba.\n"
          "\n"
          "Esto es lo que hacemos:\n"
          "  · Chatbots de WhatsApp\n"
          "  · Tableros de Power BI\n"
          "  · Páginas web\n"
          "\n"
          "Dime qué te interesa.")

MENU = [
    {"id": "servicios", "title": "Servicios", "accion": "submenu",
     "mensaje": "¿Qué te interesa?", "submenu": [
         {"id": "chatbots", "title": "Chatbots", "accion": "info",
          "mensaje": "Desde 900.000.\n\nIncluye el panel de atención."},
         {"id": "powerbi", "title": "Power BI", "accion": "submenu",
          "mensaje": "¿Qué necesitas?", "submenu": [
              {"id": "tableros", "title": "Tableros", "accion": "info",
               "mensaje": "Te armamos el tablero."},
              # Este de aquí es el que rompe el guardado a propósito:
              # abre más opciones y no tiene ninguna dentro. Sirve para
              # ver el error del mapa y que lleve hasta él (§4.12).
              {"id": "ver_ejemplo", "title": "Ver un ejemplo",
               "accion": "submenu", "mensaje": "Mira esto"},
          ]},
         {"id": "webs", "title": "Páginas web", "accion": "info",
          "mensaje": "Hacemos webs a medida."},
         {"id": "automatizacion", "title": "Automatización", "accion": "info",
          "mensaje": "Automatizamos lo repetitivo."},
     ]},
    {"id": "asesor", "title": "Hablar con alguien", "accion": "humano"},
]

# (slug, nombre, activo, token_estado) — uno por cada estado que la
# consola pinta distinto. Sin los cuatro, "Requiere atención" no sale.
CLIENTES = [
    ("panaderia", "Panadería La Espiga", True, "bien"),
    ("clinica", "Clínica Sonrisa", True, "mal"),
    ("gimnasio", "Gimnasio Hierro", False, "bien"),
    ("nuevo", "Negocio recién dado de alta", True, "sin_probar"),
]


def sembrar():
    database.init_db()
    sesion = database.get_session()
    try:
        primero = sesion.query(database.Client).first()
        config = dict(primero.negocio_config or {})
        config.setdefault("negocio", {})["nombre"] = primero.nombre
        config.setdefault("textos", {}).update({
            "bienvenida": SALUDO,
            "cierre": "¿Necesitas algo más?\nDime sin problema.",
        })
        config["menu"] = MENU
        sesion.query(database.Client).filter_by(id=primero.id).update(
            {"negocio_config": config, "token_estado": "bien"})

        for slug, nombre, activo, estado in CLIENTES:
            if sesion.query(database.Client).filter_by(slug=slug).first():
                continue
            sesion.add(database.Client(slug=slug, nombre=nombre, active=activo,
                                       token_estado=estado))
        sesion.commit()
        return primero.id, primero.nombre
    finally:
        sesion.close()


if __name__ == "__main__":
    cliente, nombre = sembrar()
    print(f"[prueba] Base sembrada en {BASE}")
    print(f"[prueba] Cliente {cliente} ({nombre}) con menú de tres niveles.")
    print(f"[prueba] http://127.0.0.1:{PUERTO}/superadmin   clave: prueba")
    print(f"[prueba] El mapa:  /superadmin/clientes/{cliente}/mapa")

    import uvicorn                                    # noqa: E402
    from app import main                              # noqa: E402

    # Un solo proceso, como en producción: el bus de avisos en vivo es una
    # cola en memoria y con `--workers` cada uno vería la suya (§3.9).
    uvicorn.run(main.app, host="127.0.0.1", port=PUERTO, log_level="warning")
