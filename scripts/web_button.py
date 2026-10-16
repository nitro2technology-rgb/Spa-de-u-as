"""
BOTÓN DE WHATSAPP PARA LA PÁGINA WEB (click-to-chat)
=====================================================
Genera el HTML listo para pegar en la web del negocio, con el número y el
mensaje inicial ya puestos desde config.py — así no hay que acordarse del
número ni arriesgarse a escribirlo mal en cada sitio.

El enlace es el oficial de WhatsApp (https://wa.me/...): abre la app con la
conversación empezada, y de ahí en adelante responde el mismo bot. No hace
falta ningún widget ni JavaScript de terceros.

Cada botón lleva un mensaje precargado distinto según el canal, y esa frase
es la que después permite saber de dónde llegó cada cliente (Contact.origen).

Uso (desde la raíz del proyecto):
    python scripts/web_button.py                     # muestra los dos snippets
    python scripts/web_button.py --flotante          # solo el botón flotante
    python scripts/web_button.py --enlace            # solo la URL wa.me
    python scripts/web_button.py --origen instagram  # botón para otro canal
    python scripts/web_button.py -o boton.html       # guarda una página de ejemplo
"""

import argparse
import os
import sys
from urllib.parse import quote

# Al correr "python scripts/web_button.py", Python solo pone scripts/ en la
# ruta de búsqueda, así que el paquete app no se encontraría. Añadimos la
# raíz del proyecto antes de importarlo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config  # noqa: E402

# Logo de WhatsApp embebido como SVG: sin esto habría que cargar una imagen
# desde un servidor externo, que puede caerse o rastrear a los visitantes.
_LOGO_SVG = (
    '<svg viewBox="0 0 32 32" width="24" height="24" fill="currentColor" '
    'aria-hidden="true" focusable="false">'
    '<path d="M16 0C7.2 0 0 7.2 0 16c0 2.8.7 5.5 2.1 7.9L0 32l8.3-2.2c2.3 1.3 '
    '4.9 1.9 7.7 1.9 8.8 0 16-7.2 16-16S24.8 0 16 0zm0 29.1c-2.5 0-4.9-.7-7-1.9'
    'l-.5-.3-5 1.3 1.3-4.8-.3-.5c-1.3-2.1-2-4.6-2-7.1C2.5 8.6 8.6 2.5 16 2.5'
    'S29.5 8.6 29.5 16 23.4 29.1 16 29.1zm7.4-9.8c-.4-.2-2.4-1.2-2.8-1.3-.4-.1'
    '-.6-.2-.9.2-.3.4-1 1.3-1.2 1.5-.2.2-.4.3-.8.1-.4-.2-1.7-.6-3.3-2-1.2-1.1'
    '-2-2.4-2.3-2.8-.2-.4 0-.6.2-.8.2-.2.4-.4.6-.7.2-.2.3-.4.4-.7.1-.3 0-.5-.1'
    '-.7-.1-.2-.9-2.1-1.2-2.9-.3-.8-.6-.7-.9-.7h-.7c-.3 0-.7.1-1 .5-.4.4-1.3 '
    '1.3-1.3 3.2s1.4 3.7 1.6 3.9c.2.2 2.7 4.2 6.6 5.8.9.4 1.6.6 2.2.8.9.3 1.8.2 '
    '2.4.2.7-.1 2.4-1 2.7-1.9.3-.9.3-1.8.2-1.9-.1-.2-.3-.3-.7-.5z"/></svg>'
)

_ESTILOS_BASE = """\
  background:#25D366; color:#fff; text-decoration:none; font-weight:600;
  font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
  display:inline-flex; align-items:center; gap:10px;"""


def url_chat(origen: str = None) -> str:
    """
    Arma la URL de click-to-chat con el mensaje inicial ya codificado.

    El mensaje cambia según el origen: esa frase es la que después permite
    saber por qué canal llegó el cliente (ver config.ORIGENES).
    """
    if not config.BUSINESS_WHATSAPP_NUMBER:
        raise ValueError(
            "Falta BUSINESS_WHATSAPP_NUMBER en .env — es el número visible del "
            "negocio en formato internacional sin '+', ej: 573178862390"
        )

    origen = origen or config.ORIGEN_BOTON_WEB
    if origen not in config.ORIGENES:
        raise ValueError(
            f"Origen '{origen}' no existe. Definidos en config.ORIGENES: "
            f"{', '.join(config.ORIGENES)}"
        )

    numero = "".join(c for c in config.BUSINESS_WHATSAPP_NUMBER if c.isdigit())
    mensaje = config.ORIGENES[origen]["mensaje"]
    return f"https://wa.me/{numero}?text={quote(mensaje)}"


def snippet_flotante(origen: str = None) -> str:
    """Botón fijo en la esquina inferior derecha, visible en toda la página."""
    return f"""<!-- Botón flotante de WhatsApp — {config.BUSINESS_NAME} -->
<a href="{url_chat(origen)}"
   target="_blank" rel="noopener"
   aria-label="{config.WEB_BUTTON_LABEL} por WhatsApp"
   style="position:fixed; bottom:24px; right:24px; z-index:9999;
  padding:14px; border-radius:50%; box-shadow:0 4px 12px rgba(0,0,0,.25);
{_ESTILOS_BASE}">
  {_LOGO_SVG}
</a>"""


def snippet_en_linea(origen: str = None) -> str:
    """Botón normal, para poner dentro de una sección de la página."""
    return f"""<!-- Botón de WhatsApp — {config.BUSINESS_NAME} -->
<a href="{url_chat(origen)}"
   target="_blank" rel="noopener"
   style="padding:12px 22px; border-radius:999px;
{_ESTILOS_BASE}">
  {_LOGO_SVG}
  <span>{config.WEB_BUTTON_LABEL}</span>
</a>"""


def pagina_ejemplo(origen: str = None) -> str:
    """Página completa para ver cómo quedan los dos botones antes de pegarlos."""
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Botón de WhatsApp — {config.BUSINESS_NAME}</title>
</head>
<body style="font-family:system-ui,sans-serif; max-width:640px; margin:60px auto; padding:0 20px;">
  <h1>{config.BUSINESS_NAME}</h1>
  <p>Vista previa de los botones. El flotante está abajo a la derecha.</p>
  {snippet_en_linea(origen)}
  {snippet_flotante(origen)}
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Genera el botón de WhatsApp para la web")
    parser.add_argument("--flotante", action="store_true", help="Solo el botón flotante")
    parser.add_argument("--en-linea", action="store_true", help="Solo el botón en línea")
    parser.add_argument("--enlace", action="store_true", help="Solo la URL wa.me")
    parser.add_argument(
        "--origen",
        default=config.ORIGEN_BOTON_WEB,
        help=f"Canal del botón: {', '.join(config.ORIGENES)} (por defecto: {config.ORIGEN_BOTON_WEB})",
    )
    parser.add_argument("-o", "--output", help="Guarda una página de ejemplo en un archivo")
    args = parser.parse_args()

    try:
        enlace = url_chat(args.origen)
    except ValueError as e:
        print(f"[X] {e}")
        return 1

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(pagina_ejemplo(args.origen))
        print(f"[OK] Página de ejemplo guardada en {args.output}")
        return 0

    if args.enlace:
        print(enlace)
        return 0
    if args.flotante:
        print(snippet_flotante(args.origen))
        return 0
    if args.en_linea:
        print(snippet_en_linea(args.origen))
        return 0

    print(f"\nOrigen: '{args.origen}' — los leads que entren por aquí quedan marcados así.")
    print(f"\nEnlace directo (sirve para el botón, para la bio de Instagram, para un QR):\n\n{enlace}")
    print("\n\n--- Botón dentro de una sección de la página ---\n")
    print(snippet_en_linea(args.origen))
    print("\n\n--- Botón flotante (pegar justo antes de </body>) ---\n")
    print(snippet_flotante(args.origen))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
