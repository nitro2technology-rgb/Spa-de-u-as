"""
LAS FUENTES, SERVIDAS DESDE AQUÍ
=================================
Descarga Manrope e IBM Plex Mono de Google y las deja en
`app/web/estaticos/fuentes/`, con su hoja `fuentes.css` apuntando a los
archivos locales.

    python scripts/traer_fuentes.py

POR QUÉ NO SE ENLAZAN DE GOOGLE
-------------------------------
El diseño las pedía con un `<link>` a `fonts.googleapis.com`. Funciona,
pero tiene tres costes que aquí importan:

  · **Cada apertura del panel de cada cliente se le cuenta a Google.** El
    panel es una herramienta de trabajo de negocios ajenos; quién lo abre
    y cuándo no tiene por qué salir de este servidor.
  · **Deja de funcionar detrás de un proxy** que bloquee dominios de
    fuera, que es justo donde acaban muchas oficinas.
  · **Depende de que Google conteste** para que el panel se vea bien.

Servirlas desde aquí cuesta unos cientos de kilobytes en el repositorio y
los quita los tres. Se corre una vez; solo hay que repetirlo si se cambia
de tipografía.

SOLO LATINO
-----------
Google sirve el mismo tipo partido en alfabetos (cirílico, griego,
vietnamita…). Aquí se guarda únicamente `latin` y `latin-ext`, que es lo
que necesita el español: lo demás serían megas que nadie va a pedir.
"""

import os
import re
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, "app", "web", "estaticos", "fuentes")
HOJA = os.path.join(RAIZ, "app", "web", "estaticos", "fuentes.css")

# Con este User-Agent, Google devuelve woff2 (el formato moderno y el más
# pequeño). Con otro devuelve formatos viejos y mucho más pesados.
NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

PEDIDO = ("https://fonts.googleapis.com/css2"
          "?family=Manrope:wght@400..800"
          "&family=IBM+Plex+Mono:wght@400;500;600"
          # Los títulos y las cifras del panel de barbería (ver
          # app/web/estaticos/barberia.css).
          "&family=Unbounded:wght@400..700"
          "&display=swap")

ALFABETOS = ("latin", "latin-ext")

# La familia del logo no se baja de Google: la fabrica
# `scripts/fuente_del_logo.py` a partir de la Manrope variable. Se
# reescribe aquí para que volver a correr este script no la borre de la
# hoja; el archivo .woff2 lo genera el otro.
LOGO = """
/* Manrope Logo — SOLO el titular de la pantalla de entrada.
   Lo genera `scripts/fuente_del_logo.py`: el peso 800 congelado,
   recortado a las letras del logo y con los solapes internos de cada
   glifo fundidos. Ese titular va HUECO, y con la Manrope normal el 2, la
   e y la h salen con rayas cruzadas por dentro. */
@font-face {
  font-family: 'Manrope Logo';
  font-style: normal;
  font-weight: 800;
  font-display: swap;
  src: url(fuentes/manrope-logo.woff2) format('woff2');
}
"""


def bajar(url: str) -> bytes:
    peticion = urllib.request.Request(url, headers={"User-Agent": NAVEGADOR})
    with urllib.request.urlopen(peticion, timeout=60) as r:
        return r.read()


def main():
    os.makedirs(DESTINO, exist_ok=True)
    css = bajar(PEDIDO).decode("utf-8")

    # Cada @font-face viene precedido de un comentario con su alfabeto.
    bloques = re.split(r"/\*\s*([a-z-]+)\s*\*/", css)
    salida, guardados = [], 0

    for i in range(1, len(bloques), 2):
        alfabeto, bloque = bloques[i], bloques[i + 1]
        if alfabeto not in ALFABETOS:
            continue

        url = re.search(r"url\((https://[^)]+\.woff2)\)", bloque)
        familia = re.search(r"font-family:\s*'([^']+)'", bloque)
        peso = re.search(r"font-weight:\s*([\d ]+)", bloque)
        if not (url and familia):
            continue

        nombre = (f"{familia.group(1).replace(' ', '-').lower()}"
                  f"-{(peso.group(1) if peso else 'x').replace(' ', '-')}"
                  f"-{alfabeto}.woff2")
        with open(os.path.join(DESTINO, nombre), "wb") as f:
            f.write(bajar(url.group(1)))
        guardados += 1

        salida.append(f"/* {familia.group(1)} · {alfabeto} */"
                      + bloque.replace(url.group(1), f"fuentes/{nombre}").rstrip())

    cabecera = """/* ══════════════════════════════════════════════════════════════════
   LAS FUENTES DEL PANEL
   ══════════════════════════════════════════════════════════════════
   Generado por `scripts/traer_fuentes.py`. No se edita a mano.

   Se sirven desde este servidor y no desde Google: el panel es una
   herramienta de negocios ajenos, y quién lo abre no tiene por qué salir
   de aquí. Además funciona detrás de un proxy que bloquee dominios de
   fuera, y no depende de que Google conteste para verse bien.

   Solo alfabeto latino: lo demás serían megas que nadie va a pedir.
   ══════════════════════════════════════════════════════════════════ */

"""
    with open(HOJA, "w", encoding="utf-8", newline="\n") as f:
        f.write(cabecera + "\n".join(salida) + "\n" + LOGO)

    peso_total = sum(os.path.getsize(os.path.join(DESTINO, n))
                     for n in os.listdir(DESTINO))
    print(f"{guardados} archivos de fuente · {peso_total // 1024} KB en total")
    print(f"hoja: {HOJA}")


if __name__ == "__main__":
    main()
