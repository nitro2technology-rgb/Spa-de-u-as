"""
AVISOS AL CELULAR (WEB PUSH)
=============================
Una notificación del sistema cada vez que escribe un cliente, aunque el
panel esté cerrado y el celular bloqueado. Es lo que faltaba para poder
atender sin tener la pestaña abierta todo el día.

Se apoya en el service worker que ya monta la PWA: el navegador recibe el
aviso aunque no haya nadie mirando, y al tocarlo abre el chat.

    Si no hay claves VAPID configuradas, esto no hace nada.

`config.VAPID_PUBLIC_KEY` y `config.VAPID_PRIVATE_KEY` se generan una vez
con `python scripts/push_setup.py`. Mientras falten, el panel funciona
igual y ni siquiera ofrece activar los avisos: es preferible a que el
dueño active un permiso que después no le va a llegar.

El envío va en un hilo aparte. Un servicio de push lento (o caído) no
puede quedarse colgando el webhook de WhatsApp: si el aviso no sale, el
mensaje ya está guardado y el panel lo muestra igual por el canal en
vivo.
"""

import json
import threading

from app import config
from app.core import database
from app.core import tenencia

try:
    from pywebpush import webpush, WebPushException
except ImportError:                                   # pragma: no cover
    webpush = None
    WebPushException = Exception


# Cuántos caracteres del mensaje se meten en la notificación. Lo justo
# para saber si hay que correr, sin volcar la conversación entera en la
# pantalla de bloqueo del celular.
RESUMEN = 120


def configurado() -> bool:
    """¿Se puede enviar? Hacen falta la librería y las dos claves."""
    return bool(webpush and config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY)


def avisar(titulo: str, cuerpo: str, url: str = "/admin/inbox",
           phone: str = None):
    """
    Manda el aviso a los dispositivos que les toca, sin bloquear.

    Con `phone`, solo a quien puede ver esa conversación: el dueño, y las
    áreas de las que es (ver `app/core/equipo.py`). Sin él, a todos.

    Vuelve enseguida: el trabajo real ocurre en un hilo. Quien llama a
    esto está atendiendo un webhook de Meta, que tiene prisa.
    """
    if not configurado():
        return

    # `envolver_para_hilo` no es opcional: un Thread nuevo arranca con el
    # contexto VACÍO, y sin él `_enviar_a_todos` no sabría de qué cliente
    # es. Leería la clave VAPID de la configuración base y —peor— mandaría
    # el aviso a los dispositivos equivocados en cuanto las suscripciones
    # se filtren por inquilino. Ver app/core/tenencia.py.
    hilo = threading.Thread(
        target=tenencia.envolver_para_hilo(_enviar_a_todos),
        args=(titulo, cuerpo, url, phone), daemon=True)
    hilo.start()


def _destinatarios(suscripciones: list, phone: str | None) -> list:
    """
    Las suscripciones que deben sonar por un mensaje de `phone`.

    Suena en los dispositivos del dueño (y en los de antes de las áreas,
    que no dicen de quién son) y en los de las áreas que ven esa
    conversación. En los de las demás áreas, no.
    """
    if not phone:
        return suscripciones

    from app.core import equipo

    session = database.get_session()
    try:
        contacto = session.query(database.Contact).filter_by(phone=phone).first()
        servicio, asignada = ((contacto.servicio, contacto.area)
                              if contacto else (None, None))
        de_area = {i for (i,) in session.query(database.PanelUser.id)
                   .filter(database.PanelUser.area_id.isnot(None)).all()}
    finally:
        session.close()

    permitidos = equipo.ids_de_usuarios_que_ven(servicio, asignada)
    return [s for s in suscripciones
            if s.get("user_id") not in de_area or s.get("user_id") in permitidos]


def _enviar_a_todos(titulo: str, cuerpo: str, url: str, phone: str = None):
    suscripciones = _destinatarios(database.suscripciones_push(), phone)
    if not suscripciones:
        return

    datos = json.dumps({"titulo": titulo, "cuerpo": cuerpo, "url": url})

    # El correo de contacto es opcional en la práctica, pero el estándar
    # pide un "mailto:" y algunos servicios rechazan el envío sin él.
    correo = config.VAPID_CONTACT_EMAIL or "no-reply@example.com"

    for suscripcion in suscripciones:
        try:
            webpush(
                subscription_info={"endpoint": suscripcion["endpoint"],
                                   "keys": suscripcion["keys"]},
                data=datos,
                vapid_private_key=config.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{correo}"},
                timeout=10,
            )
        except WebPushException as e:
            _limpiar_si_murio(suscripcion["endpoint"], e)
        except Exception as e:                        # pragma: no cover
            print(f"[push] no se pudo avisar: {e}")


def _limpiar_si_murio(endpoint: str, error):
    """
    Da de baja el buzón si el servicio de push dice que ya no existe.

    404 y 410 significan que ese dispositivo no va a recibir nada nunca
    más: permiso revocado, app desinstalada, navegador borrado. Sin esta
    limpieza la tabla se llena de buzones muertos y cada mensaje nuevo
    intenta escribirles uno por uno.

    Cualquier otro error (una caída pasajera del servicio) NO borra nada:
    ahí lo correcto es reintentar en el siguiente mensaje.
    """
    codigo = getattr(getattr(error, "response", None), "status_code", None)

    if codigo in (404, 410):
        database.borrar_suscripcion_push(endpoint)
        print(f"[push] buzón dado de baja ({codigo}).")
    else:
        print(f"[push] fallo al enviar ({codigo}): {error}")


def avisar_mensaje_entrante(phone: str, nombre: str, texto: str):
    """
    El aviso concreto de "te escribió un cliente".

    Lleva el nombre si lo sabemos, y si no el teléfono: en la pantalla de
    bloqueo hay que poder decidir en un vistazo si abrirlo o no.
    """
    resumen = (texto or "").strip()
    if len(resumen) > RESUMEN:
        resumen = resumen[:RESUMEN].rstrip() + "…"

    avisar(
        titulo=nombre or phone,
        cuerpo=resumen or "(mensaje sin texto)",
        url=f"/admin/chat/{phone}",
        phone=phone,
    )
