"""
PASAR EL CONTENIDO DE UN NEGOCIO A LA BASE
===========================================
Copia un `negocio.toml` —textos, menú, precios, horarios— a la columna
`clients.negocio_config` del cliente que se diga.

    python scripts/negocio_a_la_base.py 1              # el negocio.toml del repo
    python scripts/negocio_a_la_base.py panaderia otro.toml
    python scripts/negocio_a_la_base.py 1 --ver        # solo mirar, sin escribir

POR QUÉ HAY QUE HACERLO
-----------------------
Mientras un cliente tenga `negocio_config` en NULL, su configuración sale
del `negocio.toml` del repositorio **y de las variables de entorno del
proceso**. Es la rampa de migración documentada en
`app/core/config_cliente.py`, y tiene fecha de caducidad por un motivo
concreto:

    Una variable de entorno es del proceso, y el proceso es de todos.

Con un solo negocio eso daba igual. Con varios, cada valor que un cliente
sigue leyendo del entorno es un valor que en realidad es del despliegue —
y el día que se cambie por otro cliente, se le cambia a él también.

En cuanto este script escribe la columna, ese cliente deja de mirar el
entorno para siempre: su configuración es suya y solo suya.

    El TOML se VALIDA antes de guardarse.

Armar la configuración es lo que detecta una opción del menú que nombra un
enlace o unos precios que no existen en el archivo. Si el TOML está roto,
esto falla aquí — no en la primera conversación del cliente.
"""

import json
import os
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config                                    # noqa: E402
from app.core import database                             # noqa: E402
from app.core.config_cliente import (                     # noqa: E402
    NEGOCIO_TOML, ConfiguracionCliente,
)


def _cliente(argumento: str):
    session = database.get_session()
    try:
        consulta = session.query(database.Client)
        fila = (consulta.filter_by(id=int(argumento)).first()
                if argumento.isdigit() else
                consulta.filter_by(slug=argumento).first())
        if fila is None:
            sys.exit(f"No hay ningún cliente '{argumento}'. Usa su id o su slug.")
        return fila.id, fila.nombre, fila.negocio_config is not None
    finally:
        session.close()


def _leer(ruta: str) -> dict:
    if not os.path.exists(ruta):
        sys.exit(f"No existe el archivo {ruta}.")
    with open(ruta, "rb") as f:
        return tomllib.load(f)


def _resumen(negocio: dict) -> str:
    return (f'  negocio:  {negocio.get("negocio", {}).get("nombre", "(sin nombre)")}\n'
            f'  menú:     {len(negocio.get("menu", []))} opciones\n'
            f'  textos:   {len(negocio.get("textos", {}))} mensajes\n'
            f'  precios:  {len(negocio.get("precios", {}))} bloques\n'
            f'  enlaces:  {len(negocio.get("enlaces", {}))}')


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip())

    client_id, nombre, ya_tenia = _cliente(sys.argv[1])
    argumentos = [a for a in sys.argv[2:] if not a.startswith("--")]
    ruta = argumentos[0] if argumentos else NEGOCIO_TOML
    solo_ver = "--ver" in sys.argv

    negocio = _leer(ruta)

    print(f"\nCliente {client_id} — {nombre}")
    print(f"Archivo: {ruta}")
    print(_resumen(negocio))

    # La validación de verdad: si el menú nombra un enlace que no está en
    # [enlaces], esto levanta ValueError con el id de la opción culpable.
    try:
        ConfiguracionCliente(fila={"id": client_id, "nombre": nombre},
                             negocio=negocio)
    except Exception as e:
        sys.exit(f"\nEse TOML no es válido y NO se guardó:\n  {e}")

    print("\nEl TOML es válido.")

    if solo_ver:
        print("(--ver: no se escribió nada)")
        return

    if ya_tenia:
        respuesta = input("Este cliente YA tenía contenido propio en la base. "
                          "¿Reemplazarlo? [s/N] ")
        if respuesta.strip().lower() not in ("s", "si", "sí"):
            sys.exit("Cancelado.")

    session = database.get_session()
    try:
        session.query(database.Client).filter_by(id=client_id).update(
            {"negocio_config": negocio})
        session.commit()
    finally:
        session.close()

    config.olvidar(client_id)

    print(f"\nGuardado. El cliente {client_id} ya no lee variables de entorno: "
          f"su configuración sale de la base.")
    print("Comprueba el panel y una conversación antes de dar por hecho que "
          "quedó bien.")

    # Útil para llevarlo a otro entorno sin volver a correr esto.
    if "--json" in sys.argv:
        print("\n" + json.dumps(negocio, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
