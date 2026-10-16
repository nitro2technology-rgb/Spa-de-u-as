"""
SECRETOS DE CADA CLIENTE
=========================
Cifra y descifra lo que se guarda en la tabla `clients` y que no puede
quedar en claro: el token de WhatsApp, el JSON de la cuenta de servicio de
Google, la clave de Gemini y la clave privada de los avisos push.

    Antes estos valores eran variables de entorno de un servicio por
    cliente. Ahí solo los veía quien entraba al panel del hosting. Ahora
    viven en una base compartida, y una base se respalda, se copia a un
    portátil para depurar y se abre con un cliente de SQL. Cifrarlos es la
    diferencia entre "se filtró un respaldo" y "se filtraron las
    credenciales de todos mis clientes".

Son credenciales de TERCEROS, además: quien pueda leer el token de un
cliente puede escribirles a los clientes de ese negocio haciéndose pasar
por él.

LA CLAVE MAESTRA
----------------
Sale de la variable de entorno `SECRETS_KEY` y NO se guarda en la base —
si estuviera junto a lo que protege, no protegería nada. Se genera una
sola vez con:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

y se pega en las variables de entorno del servicio.

    ⚠️  Si se pierde la clave maestra, lo cifrado no se recupera. Hay que
        volver a pedirle sus credenciales a cada cliente. Guárdala también
        fuera del hosting.

Fernet (AES-128 en modo CBC con HMAC) viene de `cryptography`, que ya
estaba instalado como dependencia de google-auth y pywebpush. No agrega
nada al despliegue.
"""

import os

from cryptography.fernet import Fernet, InvalidToken

# Marca lo que ya está cifrado. Sin ella no se puede distinguir un valor
# cifrado de uno que se guardó en claro antes de que esto existiera, y
# `descifrar` no sabría si tiene que trabajar o devolver tal cual.
PREFIJO = "enc:"


class SecretoNoDisponible(Exception):
    """No hay clave maestra, o no sirve para lo que se intenta descifrar."""


def _clave():
    """La clave maestra, o None si no está configurada."""
    return (os.getenv("SECRETS_KEY") or "").strip() or None


def hay_clave() -> bool:
    """
    Si se pueden cifrar secretos ahora mismo.

    Lo consultan el arranque y el alta de un cliente para no escribir
    credenciales en claro por descuido.
    """
    return _clave() is not None


def cifrar(valor: str) -> str:
    """
    Devuelve el valor cifrado y con prefijo, listo para guardar.

    Levanta `SecretoNoDisponible` si falta la clave maestra. Es a
    propósito: guardar en claro cuando se pidió cifrar sería un fallo
    silencioso, y de los caros.
    """
    if not valor:
        return valor

    clave = _clave()
    if clave is None:
        raise SecretoNoDisponible(
            "Falta SECRETS_KEY: no se puede cifrar. Genérala con "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` y ponla en las "
            "variables de entorno.")

    try:
        motor = Fernet(clave.encode("utf-8"))
    except (ValueError, TypeError) as e:
        raise SecretoNoDisponible(
            f"SECRETS_KEY no tiene el formato que espera Fernet: {e}") from e

    return PREFIJO + motor.encrypt(valor.encode("utf-8")).decode("utf-8")


def descifrar(valor: str) -> str:
    """
    El valor en claro.

    Lo que no lleva el prefijo se devuelve tal cual: así conviven las filas
    escritas antes de que existiera el cifrado con las nuevas, y migrar es
    volver a guardar, no un paso aparte.
    """
    if not valor or not valor.startswith(PREFIJO):
        return valor

    clave = _clave()
    if clave is None:
        raise SecretoNoDisponible(
            "Este valor está cifrado y falta SECRETS_KEY para leerlo.")

    try:
        motor = Fernet(clave.encode("utf-8"))
        return motor.decrypt(valor[len(PREFIJO):].encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        # Casi siempre es la clave equivocada: se rotó SECRETS_KEY sin
        # volver a cifrar lo que había, o se copió la base de otro entorno.
        raise SecretoNoDisponible(
            "No se pudo descifrar: SECRETS_KEY no es la que cifró este "
            "valor.") from e
    except (ValueError, TypeError) as e:
        raise SecretoNoDisponible(f"SECRETS_KEY inválida: {e}") from e

