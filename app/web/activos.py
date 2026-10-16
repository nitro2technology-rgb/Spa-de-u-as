"""
LOS ARCHIVOS DE LA INTERFAZ
============================
El CSS y el JavaScript del panel, servidos como archivos en vez de vivir
dentro de cadenas de Python.

POR QUÉ SE SACARON DE PYTHON
----------------------------
Estaban dentro de f-strings, y eso costaba dos cosas todos los días:

  · **Las llaves había que doblarlas.** En una f-string, `{` abre un hueco
    a rellenar, así que todo el CSS y todo el JavaScript se escribían con
    `{{` y `}}`. Olvidar una no da un error de estilos: da un error de
    Python **al arrancar el servidor**, y a veces en la línea equivocada.

  · **Se reenviaban en cada carga.** Medio megabyte de la misma hoja de
    estilos viajando otra vez en cada pantalla, sin que el navegador
    pudiera guardarla. En un celular con datos, eso se nota.

QUÉ NO SE PUEDE SACAR
---------------------
Lo que cambia con cada negocio: su color de marca. Eso se queda como unas
pocas variables dentro de la página, encima de la hoja compartida. Si se
metiera en el archivo cacheado, el primer negocio que lo pidiera le
pondría su color a todos los demás.

EL VERSIONADO
-------------
La dirección lleva un trozo del hash del contenido
(`/estaticos/panel.css?v=a1b2c3d4`). Así el navegador puede guardarlo para
siempre y, al desplegar un cambio, la dirección cambia sola y lo vuelve a
pedir. Sin esto tocaría elegir entre "no cachear nunca" y "explicarle a
cada cliente cómo se vacía la caché".
"""

import hashlib
import os

CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estaticos")

# La ruta pública. Va fuera de /admin a propósito: son archivos sin nada
# de nadie, y pedirlos no debería depender de tener sesión.
BASE_URL = "/estaticos"

_versiones: dict[str, str] = {}


def version(nombre: str) -> str:
    """
    Ocho caracteres del hash del archivo. Se calcula una vez por proceso:
    en producción el archivo no cambia mientras el servidor vive, y en
    desarrollo se reinicia al guardar.
    """
    if nombre in _versiones:
        return _versiones[nombre]

    ruta = os.path.join(CARPETA, nombre)
    try:
        with open(ruta, "rb") as f:
            _versiones[nombre] = hashlib.md5(f.read()).hexdigest()[:8]
    except OSError:
        # Un archivo que falta no puede impedir que la página se pinte:
        # se sirve sin versión y el navegador pedirá lo que haya.
        _versiones[nombre] = "0"
    return _versiones[nombre]


def url(nombre: str) -> str:
    return f"{BASE_URL}/{nombre}?v={version(nombre)}"


def hoja(nombre: str) -> str:
    """La etiqueta <link> lista para meter en una plantilla."""
    return f'<link rel="stylesheet" href="{url(nombre)}">'


def guion(nombre: str) -> str:
    """La etiqueta <script> lista para meter en una plantilla."""
    return f'<script src="{url(nombre)}" defer></script>'
