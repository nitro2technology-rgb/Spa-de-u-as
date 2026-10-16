"""
LA FUENTE DEL LOGO, SIN CONTORNOS SOLAPADOS
============================================
Saca de Manrope una versión estática del peso 800 con **solo las letras
del logo**, y le quita los solapes internos de cada glifo.

    python scripts/fuente_del_logo.py

POR QUÉ HACE FALTA
------------------
El "2Tech" de la pantalla de entrada va hueco: se dibuja el contorno de
la letra y se ve el fondo por dentro. Con Manrope tal cual sale mal — el
2, la e y la h aparecen con rayas cruzadas por dentro.

No es culpa del navegador ni del grosor del trazo. Manrope es una fuente
variable, y como casi todas, cada letra está construida con **piezas que
se solapan** (el asta y el hombro de la h son dos formas superpuestas).
Rellenas se ven como una sola letra y nadie lo nota; vaciadas, el borde
de cada pieza se dibuja y esos bordes internos son las rayas.

Bajar el peso no lo arregla: las rayas se afinan, pero siguen ahí. Lo que
lo arregla es fundir las piezas de cada letra en una sola forma, que es
lo que hace este script.

QUÉ PRODUCE
-----------
`manrope-logo.woff2`, unos pocos kilobytes: el peso 800 congelado, con
los solapes fundidos y recortado a las letras de "Nitro 2Tech v.0-9".
Se declara aparte, como familia `Manrope Logo`, y se usa SOLO en el
titular de la entrada. El resto del panel sigue con la Manrope variable
de siempre, que va rellena y no tiene ningún problema.

Se corre una vez. Solo hay que repetirlo si cambia la tipografía o si el
logo estrena letras nuevas.
"""

import os

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.ttLib.removeOverlaps import removeOverlaps

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUENTES = os.path.join(RAIZ, "app", "web", "estaticos", "fuentes")

ORIGEN = os.path.join(FUENTES, "manrope-400-800-latin.woff2")
DESTINO = os.path.join(FUENTES, "manrope-logo.woff2")

PESO = 800

# Las letras del logo y poco más: el nombre, la versión y los dígitos por
# si algún día es v3. Todo lo demás sobra y son bytes que nadie pide.
LETRAS = "Nitro2Techv.0123456789 "


def main():
    fuente = TTFont(ORIGEN)

    # 1. Congelar el peso: de fuente variable a una sola instancia.
    instantiateVariableFont(fuente, {"wght": PESO}, inplace=True, updateFontNames=False)

    # 2. Recortar a las letras del logo. Va ANTES de fundir los solapes
    #    porque fundir es lo caro: sobre ocho letras es instantáneo.
    opciones = subset.Options()
    opciones.layout_features = ["*"]
    recortador = subset.Subsetter(options=opciones)
    recortador.populate(text=LETRAS)
    recortador.subset(fuente)

    # 3. Fundir las piezas de cada letra en una sola forma. Esto es lo
    #    que quita las rayas de dentro del 2, la e y la h.
    removeOverlaps(fuente)

    # 4. El nombre de familia propio, para poder pedirla solo en el logo
    #    sin tocar la Manrope de todo el panel.
    for registro in fuente["name"].names:
        if registro.nameID in (1, 3, 4, 6, 16):
            registro.string = "Manrope Logo"

    fuente.flavor = "woff2"
    fuente.save(DESTINO)

    print(f"{DESTINO}")
    print(f"{os.path.getsize(DESTINO)} bytes · peso {PESO} · letras: {LETRAS.strip()}")


if __name__ == "__main__":
    main()
