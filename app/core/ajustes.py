"""
AJUSTES QUE CAMBIA EL DUEÑO
============================
Lo que se puede cambiar desde el panel y sigue puesto después de un
reinicio o un despliegue.

Hoy solo hay uno: el plan (Básico o Pro). Está aquí y no en las variables
de entorno porque **el dueño del negocio tiene que poder activarlo él**,
sin entrar al panel de Render ni pedirle a nadie que despliegue. Es la
diferencia entre "contratas la IA y la enciendes" y "contratas la IA y
esperas a que alguien te la active".

Lo que SÍ sigue en variables de entorno: las credenciales, los límites
técnicos y todo lo que el cliente no debe tocar. Esto es solo para lo que
es suyo.

Se lee en cada mensaje entrante, así que va con caché en memoria. Vale
porque el servidor corre en UN solo proceso —lo exige el reparto de
mensajes en vivo (app/core/eventos.py) y lo impone el disco de Render—,
así que no hay una segunda copia que pueda quedarse desactualizada.
"""

from app.core import tenencia
from app.core.database import Ajuste, get_session

# Caché de lo leído. Se vacía al escribir, que es lo único que puede
# cambiarlo dentro de este proceso.
#
# La clave del caché lleva el INQUILINO, no solo el nombre del ajuste:
# "plan_ia" es un ajuste por negocio, y con la clave a secas el plan que
# activa un cliente se lo activaría a todos los demás.
_cache = {}


def _clave_cache(clave: str) -> tuple:
    return (tenencia.actual_o_none(), clave)


def leer(clave: str, por_defecto=None):
    """El valor guardado, o `por_defecto` si nadie lo ha puesto nunca."""
    en_cache = _clave_cache(clave)
    if en_cache in _cache:
        return _cache[en_cache]

    session = get_session()
    try:
        fila = session.query(Ajuste).filter_by(clave=clave).first()
        valor = fila.valor if fila is not None else por_defecto
    except Exception as e:
        # Si la tabla aún no existe (una base vieja que no ha pasado por
        # init_db), no se puede dejar mudo al bot por un ajuste: se usa el
        # valor por defecto y sigue.
        print(f"[ajustes] No se pudo leer '{clave}': {e}")
        return por_defecto
    finally:
        session.close()

    _cache[en_cache] = valor
    return valor


def escribir(clave: str, valor: str):
    """Guarda el valor y lo deja disponible al instante."""
    session = get_session()
    try:
        fila = session.query(Ajuste).filter_by(clave=clave).first()
        if fila is None:
            fila = Ajuste(clave=clave)
            session.add(fila)
        fila.valor = valor
        session.commit()
    finally:
        session.close()

    _cache[_clave_cache(clave)] = valor
    return valor


def olvidar(clave: str):
    """
    Borra el ajuste para que vuelva a mandar el valor por defecto (el de
    la variable de entorno). Es la forma de "devolver al estado de
    fábrica" sin tener que saber cuál era.
    """
    session = get_session()
    try:
        session.query(Ajuste).filter_by(clave=clave).delete()
        session.commit()
    finally:
        session.close()

    _cache.pop(_clave_cache(clave), None)


def vaciar_cache():
    """Para las pruebas, que cambian la base bajo los pies del módulo."""
    _cache.clear()
