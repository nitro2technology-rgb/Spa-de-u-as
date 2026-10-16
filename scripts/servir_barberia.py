"""
LEVANTA EL PANEL DE BARBERÍAS CON UNA BASE DE MENTIRA
======================================================

    python scripts/servir_barberia.py
    → http://127.0.0.1:8098/entrar

Lo mismo que `servir_de_prueba.py`, para el panel de barberías: nada
visual se da por bueno sin abrirlo en el navegador, y para abrirlo hace
falta una base con gente dentro. La base es un SQLite en un temporal que
se borra al empezar; no manda correos (sin SMTP no sale ninguno).

QUIÉN HAY (contraseña entre paréntesis)
---------------------------------------
Filo Barbería — plan Barbería + Bot IA, tres sedes:

    ricardo     Dueño                      (filo2026)
    sofia.r     Administradora de Chapinero y Usaquén   (filo2026)
    laura.p     Recepción de Chapinero     (filo2026)
    andres.m    Barbero, rota entre Chapinero y Usaquén  (filo2026)
    daniel.c    Barbero con clave TEMPORAL (se imprime al arrancar)
    camilo.t    Barbero DESACTIVADO        (filo2026)

Navaja Club — PAUSADA por impago, para ver la pantalla 4c:

    navaja      Dueño                      (navaja2026)
    pipe.n      Barbero                    (navaja2026)

También se entra con el correo (ricardo@filobarberia.co) o el celular
(300 111 2233) del dueño de Filo.
"""

import os
import sys
import tempfile

PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROYECTO)
os.chdir(PROYECTO)

BASE = os.path.join(tempfile.gettempdir(), "barberia_de_prueba.db").replace("\\", "/")
if os.path.exists(BASE):
    os.remove(BASE)

PUERTO = 8098
os.environ["DATABASE_URL"] = "sqlite:///" + BASE
os.environ["ADMIN_API_KEY"] = "clave-de-prueba"
os.environ["SUPERADMIN_KEY"] = "prueba"
os.environ["PANEL_URL"] = f"http://127.0.0.1:{PUERTO}"
os.environ.setdefault("SECRETS_KEY", "T2FhOFBTS0RqM3ZzWmJ4TkxxWXc5Y0hHdFJtRXVfMD0=")

# La siembra vive en `demo_barberia.py`, que también sirve para la demo de
# Render. Se importa DESPUÉS de fijar la base de arriba.
sys.path.insert(0, os.path.join(PROYECTO, "scripts"))
from demo_barberia import CLAVE, sembrar   # noqa: E402

if __name__ == "__main__":
    temporal = sembrar()
    print(f"\n  http://127.0.0.1:{PUERTO}/entrar")
    print(f"  ricardo / sofia.r / laura.p / andres.m / julian.p / kevin.r / camilo.t  ·  clave: {CLAVE}")
    print(f"  daniel.c (clave temporal): {temporal}")
    print("  navaja / pipe.n  ·  clave: navaja2026  (barbería pausada)\n")

    import uvicorn
    from app.main import app
    uvicorn.run(app, host="127.0.0.1", port=PUERTO, log_level="warning")
