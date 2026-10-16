"""
QUIÉN ENTRA AL PANEL DE UN NEGOCIO
===================================
Da de alta, lista y da de baja a las personas que pueden entrar al panel
de un cliente. Se corre a mano contra la base del despliegue.

    Desde el 18-ago-2026 esto mismo se hace desde el navegador, en la
    ficha del negocio en `/superadmin`. Este script se queda para cuando
    no hay super-admin a mano: sin `SUPERADMIN_KEY` puesta esa consola no
    existe, y entonces la terminal es la única puerta.

    python scripts/panel_usuario.py listar 2
    python scripts/panel_usuario.py crear 2 rosa@panaderia.com
    python scripts/panel_usuario.py baja  2 rosa@panaderia.com

La clave se escribe en el momento y NO se pasa por argumento: lo que se
teclea en la terminal queda en el historial del shell y en los registros
del hosting.

    Cada negocio tiene sus propios usuarios.

Antes la contraseña del panel era `ADMIN_API_KEY`, una variable de entorno
del proceso — o sea, la misma para todos los clientes del despliegue. Hoy
`ADMIN_API_KEY` solo sirve, y solo para el cliente por defecto, mientras
ese cliente no tenga ningún usuario aquí. En cuanto se le crea uno, la
rampa se apaga y esa clave deja de abrirle el panel.
"""

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import acceso, database        # noqa: E402


def _cliente(argumento: str):
    """La fila de `clients`, buscada por id o por slug."""
    session = database.get_session()
    try:
        consulta = session.query(database.Client)
        fila = (consulta.filter_by(id=int(argumento)).first()
                if argumento.isdigit() else
                consulta.filter_by(slug=argumento).first())
        if fila is None:
            sys.exit(f"No hay ningún cliente '{argumento}'. "
                     f"Prueba con su id o con su slug.")
        return fila.id, fila.nombre
    finally:
        session.close()


def _pedir_clave() -> str:
    clave = getpass.getpass("Clave nueva: ")
    if len(clave) < 8:
        sys.exit("Demasiado corta: mínimo 8 caracteres.")
    if clave != getpass.getpass("Repítela: "):
        sys.exit("No coinciden.")
    return clave


def listar(client_id: int, nombre: str):
    usuarios = acceso.listar_usuarios(client_id)
    print(f"\nPanel de {nombre} (cliente {client_id})")

    if not usuarios:
        print("  (sin usuarios)")
        if not acceso.panel_habilitado(client_id):
            print("  ⚠  Y sin ADMIN_API_KEY aplicable: nadie puede entrar.")
        else:
            print("  Se entra con ADMIN_API_KEY. Crea un usuario para "
                  "apagar esa rampa.")
        return

    for u in usuarios:
        estado = "activo" if u["active"] else "dado de baja"
        visto = u["ultimo_acceso"].strftime("%d/%m/%Y %H:%M") if u["ultimo_acceso"] else "nunca"
        print(f"  [{u['id']}] {u['email']}  ({u['rol']}, {estado})  "
              f"último acceso: {visto}")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__.strip())

    accion, cliente = sys.argv[1], sys.argv[2]
    client_id, nombre = _cliente(cliente)

    if accion == "listar":
        return listar(client_id, nombre)

    if len(sys.argv) < 4:
        sys.exit(f"Falta el correo:  python scripts/panel_usuario.py "
                 f"{accion} {cliente} correo@ejemplo.com")
    email = sys.argv[3]

    if accion == "crear":
        try:
            acceso.crear_usuario(client_id, email, _pedir_clave())
        except ValueError as e:        # incluye acceso.UsuarioOcupado
            sys.exit(f"\n{e}")
        print(f"\nListo: entra al panel de {nombre} con el usuario "
              f"«{acceso.normalizar_usuario(email)}».")
        print("Si este cliente entraba con ADMIN_API_KEY, esa clave ya no "
              "le sirve.")
        return

    if accion == "baja":
        if acceso.desactivar_usuario(client_id, email):
            print(f"\n{email} ya no entra al panel de {nombre}.")
            print("Su sesión abierta, si la tiene, se cierra sola al vencer "
                  "el plazo de inactividad.")
        else:
            print(f"\n{email} no estaba dado de alta en {nombre}.")
        return

    sys.exit(f"Acción desconocida: {accion!r}. Usa listar, crear o baja.")


if __name__ == "__main__":
    main()
