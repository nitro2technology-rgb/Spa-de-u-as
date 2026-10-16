"""
LOS HUECOS ENTRE LLAVES
========================
Rellenar `{name}`, `{date}`, `{url}` y compañía en un texto que **escribió
el dueño del negocio**, sin que un texto raro pueda tumbar al bot.

    rellenar("Hola {name}, mira {url}", name="Ana", url="https://…")
    →  "Hola Ana, mira https://…"

POR QUÉ NO SE USA `str.format`
------------------------------
Porque `str.format` trata TODA llave como un hueco suyo, y estos textos
no los escribe un programador: los escribe el dueño en `/superadmin`,
donde nadie le dice —ni tiene por qué saber— que la llave es un carácter
especial.

Lo que pasaba, y costó un "el bot se quedó congelado":

    "Hola {name}, mira los ejemplos"   →  KeyError: 'name'
    "Abrimos de {9 a 6}"               →  KeyError: '9 a 6'
    "Un 50% de {descuento}"            →  KeyError: 'descuento'

Ese `KeyError` subía hasta `main`, donde lo recogía un `except (KeyError,
IndexError)` puesto para los payloads mal formados de Meta, y se anotaba
como "Payload inesperado, se ignora". O sea: **el cliente no recibía
absolutamente nada** y en el log ponía otra cosa. Visto desde el
teléfono, el bot se congelaba en esa opción.

Y era fácil de provocar sin hacer nada raro: el propio editor dice
"Puedes usar {name}" al lado de varios campos.

CÓMO SE COMPORTA
----------------
- Cambia los huecos que se le nombran.
- **Deja intacto lo que no reconoce.** Un `{descuento}` que nadie declaró
  se manda tal cual: se ve raro en el mensaje, y eso es una pista para
  quien lo escribió. Lo que no puede es dejar al cliente sin respuesta.
- Nunca levanta una excepción. Ni con llaves sin cerrar, ni con llaves
  dobles, ni con `None`.
- `None` cuenta como cadena vacía: "Hola {name}" sin nombre es "Hola ",
  no "Hola None".

Es la misma decisión —y por el mismo motivo— que `config_cliente._rellenar`
tomó para las variables del negocio. Ahí está dicho en corto; aquí, para
lo que rellena el bot en cada conversación.
"""


def rellenar(texto, **valores) -> str:
    """
    Los huecos nombrados, cambiados por su valor. Lo demás, como estaba.

    `texto` puede ser None: devuelve cadena vacía, que es lo que hace
    falta para no mandar la palabra "None" por WhatsApp.
    """
    if texto is None:
        return ""

    resultado = str(texto)
    for nombre, valor in valores.items():
        resultado = resultado.replace(
            "{" + nombre + "}", "" if valor is None else str(valor))
    return resultado
