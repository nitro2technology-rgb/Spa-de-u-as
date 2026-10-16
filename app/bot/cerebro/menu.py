"""
CEREBRO DEL PLAN BÁSICO
========================
No usa IA. Reconoce lo que el cliente ESCRIBE comparándolo con los títulos
de las opciones del menú, y nada más.

Hasta el 13-sep-2026 devolvía `NO_SE` siempre, y eso tenía un coste que
se veía en el teléfono: el bot contestaba "no entendí" y el cliente, muy
razonablemente, escribía **"Quiero una página web"** — que es casi letra
por letra el botón "Página web" que tenía delante. Otro "no entendí". Y
otro. Un bot que no reconoce sus propios botones escritos a mano parece
trabado, no básico.

Lo que hace, y por qué es tan poco:

  - Una opción coincide si **todas** las palabras con peso de su título
    están en el mensaje. "Página web" ⊂ "quiero una pagina web".
  - Si coinciden varias, gana la que tiene MÁS palabras en común: "precios
    de página web" elige "Precios página web" antes que "Página web".
  - Si aun así hay empate —"Ver ejemplos" existe en tres ramas—, no elige
    ninguna. Adivinar entre dos es peor que decir "no entendí" y enseñar
    el menú.

No entiende sinónimos ni frases ("algo para vender por internet"): eso es
lo que se vende con la IA. Pero sí lo evidente, que es lo que un cliente
espera de cualquier bot.

Coste: cero llamadas de red, cero dependencias, microsegundos.

El plan Pro también pasa por aquí: si Gemini no sabe, falla o se agotó el
cupo, `cerebro.interpretar` prueba esto antes de rendirse. Es la regla de
siempre —un arreglo en el Básico llega solo al Pro—.
"""

import re
import unicodedata

from app.bot.cerebro.base import NO_SE, Decision

# Palabras que no distinguen una opción de otra. Sin quitarlas, "Hablar
# con un asesor" exigiría que el cliente escribiera "con" y "un".
PALABRAS_VACIAS = frozenset("""
    a al algo alguna alguno como con de del el en es esa ese eso esta este
    esto la las lo los me mi mis necesito para pero por porfa porfavor
    puede puedo que quiero quisiera se ser si sobre su sus te tu tus un una
    uno unos unas y ya yo favor hola buenas buenos dias tardes noches gracias
    ver no
    crear hacer tener saber conocer agendar pedir solicitar obtener mas
    info informacion
""".split())
# Los verbos de la última línea son los que un botón lleva y el cliente se
# come al escribir: el botón dice "Crear mi página web" y el cliente
# escribe "quiero una página web"; dice "Agendar una reunión" y escribe
# "quiero una reunión". Exigirlos era no reconocer justo lo evidente.
# "no" está ahí aunque cambie el sentido: con peso, el botón "No, gracias"
# se elegiría con cualquier "no entiendo nada", y ese botón DESPIDE al
# cliente. Un botón así se pulsa; no se adivina.


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y solo letras y números separados por espacio."""
    sin_tildes = unicodedata.normalize("NFD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9ñ]+", sin_tildes.lower()))


def _raiz(palabra: str) -> str:
    """
    El plural fuera: "páginas" y "página", "ejemplos" y "ejemplo".

    No es un lematizador ni pretende serlo. Solo quita la "s" final de las
    palabras largas, que en español resuelve casi todos los plurales que un
    cliente escribe contra un botón en singular (y al revés).
    """
    if len(palabra) > 4 and palabra.endswith("es") and palabra[-3] in "rlndz":
        return palabra[:-2]
    if len(palabra) > 3 and palabra.endswith("s"):
        return palabra[:-1]
    return palabra


def palabras(texto: str) -> set:
    """Las palabras con peso de un texto, ya normalizadas."""
    return {_raiz(p) for p in normalizar(texto).split()
            if p not in PALABRAS_VACIAS and len(p) > 1}


def interpretar(contact, texto: str, opciones: list) -> Decision:
    """La opción cuyo título escribió el cliente, o `NO_SE`."""
    escritas = palabras(texto)
    if not escritas:
        return NO_SE

    candidatas = []
    for opcion in opciones or []:
        claves = palabras(opcion.get("title", ""))
        if claves and claves <= escritas:
            candidatas.append((len(claves), opcion))

    if not candidatas:
        return NO_SE

    mejor = max(n for n, _ in candidatas)
    ganadoras = [o for n, o in candidatas if n == mejor]
    if len(ganadoras) != 1:
        return NO_SE

    return Decision(intencion=ganadoras[0]["id"],
                    motivo="coincide con el título de la opción")
