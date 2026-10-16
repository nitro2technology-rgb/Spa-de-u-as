"""
HERRAMIENTAS DE PUESTA EN MARCHA
================================
Se corren a mano, una vez, al montar el bot para un negocio. No forman
parte del servidor: nada de app/ importa esta carpeta.

    meta_setup.py    Revisa token, número, suscripción y plantillas de Meta
    google_setup.py  Verifica los permisos del Calendar y del Sheet
    web_button.py    Genera el botón de WhatsApp para la página web

Se ejecutan desde la raíz del proyecto, por ejemplo:

    python scripts/meta_setup.py check
"""
