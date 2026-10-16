"""
"MI BOT": EL DUEÑO EDITA LO QUE DICE SU BOT
============================================
El mismo mapa de la conversación que usa el super-admin —el recorrido paso
a paso, con el teléfono al lado pintando lo que va a ver el cliente—, pero
desde el panel del negocio y guardando por su propia sesión.

Es el MISMO editor y la MISMA puerta de guardado (`superadmin.guardar_mapa`)
a propósito. Las reglas que impiden dejar al bot diciendo algo roto —los
topes de Meta, los ids repetidos, un submenú vacío, los saltos de línea—
costaron cada una un fallo en producción; tenerlas dos veces sería volver a
pagarlos.

Solo el dueño. Un área no toca lo que dice el bot de todo el negocio.
"""

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import config
from app.core import equipo, tenencia
from app.web import activos, admin_ui, mapa, superadmin

router = APIRouter(prefix="/admin", tags=["panel"])


def _dueno(request: Request):
    """El `Quien` si es el dueño; None si no hay sesión; False si es un área."""
    quien = equipo.de_pase(admin_ui._sesion_valida(request))
    if quien is None:
        return None
    return quien if quien.es_dueno else False


# El tema del panel se guarda en `n2t-tema` y el del editor en
# `superadmin:tema`. Los valores son los mismos ("claro", "oscuro"): se lee
# el del panel para que el dueño no pase de oscuro a claro al entrar aquí.
_TEMA_DEL_PANEL = ("<script>try{var t=localStorage.getItem('n2t-tema');"
                   "if(t)document.documentElement.dataset.tema=t;}catch(e){}"
                   "</script>")


@router.get("/mi-bot", response_class=HTMLResponse)
def mi_bot(request: Request):
    quien = _dueno(request)
    if quien is None:
        return admin_ui._pedir_login(
            admin_ui.CADUCADA if admin_ui._sesion_caducada(request) else "")
    if quien is False:
        return RedirectResponse("/admin/inbox", status_code=303)

    client_id = tenencia.actual()
    nombre, negocio = superadmin._contenido_de(client_id)
    cuerpo = mapa.pintar(negocio, client_id, nombre, tiene_propio=True,
                         guardar_en="/admin/mi-bot/guardar",
                         con_ia=config.IA_CONTRATADA,
                         aviso_del_archivo=False)

    return admin_ui._renovar(HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mi bot · {html.escape(config.BUSINESS_NAME)}</title>
{_TEMA_DEL_PANEL}
<link rel="stylesheet" href="{activos.url('fuentes.css')}">
<link rel="stylesheet" href="{activos.url('superadmin.css')}">
</head><body class="mi-bot">
<div class="lienzo">
  <header class="cabecera">
    <div class="cabecera-izq">
      <h1>Mi bot</h1>
      <p class="resumen">Lo que dice tu bot, paso a paso. A la derecha ves
         cómo le llega a tu cliente. Nada cambia hasta que pulses
         <strong>Guardar</strong>.</p>
    </div>
    <div class="cabecera-acciones">
      <a class="boton suave" href="/admin/inbox">← Volver a mi panel</a>
    </div>
  </header>
  <div class="cuerpo">{cuerpo}</div>
</div>
<script src="{activos.url('superadmin-campos.js')}" defer></script>
</body></html>"""), request, admin_ui._sesion_valida(request))


@router.post("/mi-bot/guardar")
async def guardar(request: Request):
    quien = _dueno(request)
    if quien is None:
        return JSONResponse({"ok": False, "error": "Tu sesión caducó. Entra de "
                             "nuevo; lo que no guardaste se pierde."},
                            status_code=401)
    if quien is False:
        return JSONResponse({"ok": False, "error": "Solo el administrador "
                             "cambia lo que dice el bot."}, status_code=403)

    try:
        enviado = await request.json()
    except Exception:
        enviado = None
    if not isinstance(enviado, dict):
        return JSONResponse({"ok": False, "error": "El mapa llegó ilegible."},
                            status_code=400)

    client_id = tenencia.actual()
    nombre, actual = superadmin._contenido_de(client_id)

    # La IA solo se toma si su plan la trae: la caja no se le enseña, y
    # tampoco se acepta por la puerta de atrás.
    secciones = tuple(x for x in superadmin.SECCIONES_DEL_MAPA
                      if x != "ia" or config.IA_CONTRATADA)
    return JSONResponse(superadmin.guardar_mapa(client_id, nombre, actual,
                                                enviado, secciones))
