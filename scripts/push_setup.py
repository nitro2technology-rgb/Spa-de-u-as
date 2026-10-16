"""
CLAVES PARA LOS AVISOS AL CELULAR (VAPID)
==========================================
Se corre UNA vez, a mano, y ya. Genera el par de claves con el que el
servidor firma cada notificación, las imprime, y tú las pegas en las
variables de entorno del hosting.

    python scripts/push_setup.py

Sin estas claves el panel funciona igual: simplemente no ofrece el botón
de activar avisos. Con ellas, cada mensaje de un cliente llega como
notificación del celular aunque el panel esté cerrado.

    La clave PRIVADA no se comparte ni se sube al repositorio.

Si algún día se regeneran, todos los dispositivos apuntados dejan de
recibir: hay que volver a darle a "Activar avisos" en cada uno.
"""

import base64
import sys

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
except ImportError:
    sys.exit("Falta cryptography. Instálalo con:  pip install -r requirements.txt")


def _b64(crudo: bytes) -> str:
    """base64url SIN relleno, que es la única forma que acepta el navegador."""
    return base64.urlsafe_b64encode(crudo).decode("ascii").rstrip("=")


def generar() -> tuple[str, str]:
    """
    Devuelve (clave_publica, clave_privada) en el formato que esperan el
    navegador y pywebpush.

    La curva es P-256: el estándar de Web Push no admite otra. La pública
    va como punto sin comprimir (65 bytes) y la privada como su valor de
    32 bytes. Cualquier otro formato falla al suscribirse, y el error que
    devuelve el navegador no explica por qué.
    """
    clave = ec.generate_private_key(ec.SECP256R1())

    publica = clave.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)

    privada = clave.private_numbers().private_value.to_bytes(32, "big")

    return _b64(publica), _b64(privada)


def main():
    publica, privada = generar()

    print()
    print("=" * 66)
    print("  CLAVES GENERADAS — pégalas en las variables de entorno")
    print("=" * 66)
    print()
    print(f"VAPID_PUBLIC_KEY={publica}")
    print(f"VAPID_PRIVATE_KEY={privada}")
    print("VAPID_CONTACT_EMAIL=tu-correo@ejemplo.com")
    print()
    print("En Render: Dashboard → tu servicio → Environment → Add.")
    print("Ojo: lo que pongas ahí a mano le gana a render.yaml.")
    print()
    print("La clave PRIVADA no se sube al repositorio ni se comparte.")
    print("Si la cambias, hay que volver a activar los avisos en cada")
    print("celular donde estuvieran andando.")
    print()


if __name__ == "__main__":
    main()
