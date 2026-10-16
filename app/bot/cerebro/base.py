"""
LA INTERFAZ DEL CEREBRO
========================
Lo único que `bot_logic` conoce de la IA. Aquí no hay lógica: hay una
forma de preguntar y una forma de responder, y nada más.

Esa pobreza es a propósito. Es la costura que permite que el plan Básico
y el plan Pro sean EL MISMO CÓDIGO con una variable de entorno de
diferencia, y la que permitirá mañana sacar el motor a un paquete
instalable sin volver a tocar `bot_logic`.

**La regla del proyecto**: nada de IA fuera de `cerebro/gemini.py`. Si un
cambio de Gemini pide tocar otro archivo, es que esta interfaz se quedó
corta — se arregla aquí, no se esparce el código de IA por el repo.
"""

from dataclasses import dataclass


@dataclass
class Decision:
    """
    Lo que el cerebro entendió de un mensaje escrito a mano.

    Las tres formas posibles, y solo estas tres:

    - `intencion`: el id de una opción del menú. El bot la ejecuta como si
      el cliente la hubiera tocado, con los textos del TOML. La IA elige
      QUÉ hacer; CÓMO se hace no cambia.
    - `respuesta`: texto para enviarle tal cual, cuando preguntó algo que
      no es ninguna opción del menú ("¿hacen envíos?").
    - las dos en None: el cerebro no supo. El bot responde lo que
      respondía antes de que existiera la IA.

    `motivo` no se le manda a nadie: queda en los logs para poder mirar
    después por qué el bot hizo lo que hizo.
    """

    intencion: str = None
    respuesta: str = None
    motivo: str = ""


# La respuesta "no sé", que es la que devuelve el plan Básico siempre y el
# plan Pro cada vez que algo falla. Se define una vez aquí para que quede
# claro que es un valor esperado del sistema, no un caso de error.
NO_SE = Decision(None, None, "sin decision")


def interpretar(contact, texto: str, opciones: list) -> Decision:
    """
    Qué hacer con un mensaje que el cliente escribió a mano.

    - `contact`: el contacto, por si hace falta su nombre o su historia.
    - `texto`: lo que escribió, tal cual.
    - `opciones`: el menú vigente del negocio (ya resuelto desde
      `negocio.toml`), que es el catálogo cerrado de intenciones válidas.

    Devuelve siempre una `Decision`. **Nunca levanta una excepción**: si
    algo va mal, devuelve `NO_SE` y el bot sigue por el camino de siempre.
    Esta firma es la que implementan `menu.py` y `gemini.py`.
    """
    raise NotImplementedError
