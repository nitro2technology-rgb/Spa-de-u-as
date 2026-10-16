"""
EL EQUIPO, DESDE EL PANEL DEL DUEÑO
====================================
Donde el dueño arma sus áreas: Ventas, Soporte, Contratos… Cada una con
su correo (por donde se entera de que le llegó un cliente), las opciones
del menú de las que se encarga, y su usuario y clave para entrar al panel,
donde solo verá sus conversaciones.

Cuántas caben lo dice su plan (`app/core/planes.py`). La lógica —qué se
guarda, qué se valida, quién ve qué— está en `app/core/equipo.py`; aquí
solo hay pantalla.

Formularios de toda la vida, sin JavaScript: cada área es un formulario
con su botón de guardar. Es la pantalla que se usa una vez al empezar y de
vez en cuando después, y tiene que funcionar a la primera.
"""

import html
from urllib.parse import quote_plus

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import config
from app.core import equipo, planes
from app.web import admin_ui

router = APIRouter(prefix="/admin", tags=["panel"])


def _e(valor) -> str:
    return html.escape(str(valor if valor is not None else ""))


def _volver(ok: str = "", mal: str = "", ancla: str = "") -> RedirectResponse:
    cola = f"?ok={quote_plus(ok)}" if ok else f"?mal={quote_plus(mal)}"
    return RedirectResponse(f"/admin/equipo{cola}{ancla}", status_code=303)


def _dueno_o_fuera(request: Request):
    """(sesión, quién) si es el dueño; si no, la respuesta que toca."""
    sesion = admin_ui._sesion_valida(request)
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return None, admin_ui._pedir_login(
            admin_ui.CADUCADA if admin_ui._sesion_caducada(request) else "")
    if not quien.es_dueno:
        # Un área no arma el equipo: de vuelta a sus conversaciones.
        return None, RedirectResponse("/admin/inbox", status_code=303)
    return (sesion, quien), None


def _casillas(nombre: str, marcadas, opciones: list) -> str:
    if not opciones:
        return ('<p class="equipo-vacio">Tu bot todavía no tiene menú. Las '
                'áreas se reparten por sus opciones: pídenos armarlo y vuelve '
                'aquí.</p>')
    return "".join(f"""
          <label class="equipo-casilla">
            <input type="checkbox" name="{nombre}" value="{_e(ident)}"
                   {"checked" if ident in marcadas else ""}>
            <span>{_e(titulo)}</span>
          </label>""" for ident, titulo in opciones)


def _tarjeta_area(area: dict | None, opciones: list) -> str:
    """Un área: sus datos, su usuario y sus botones. None = una nueva."""
    nueva = area is None
    area = area or {}
    usuario = None if nueva else equipo.usuario_de_area(area["id"])
    ultimo = ""
    if usuario and usuario.get("ultimo_acceso"):
        ultimo = f'Entró por última vez el {usuario["ultimo_acceso"]:%d/%m/%Y}.'
    elif usuario:
        ultimo = "Todavía no ha entrado."

    titulo = "Nueva área" if nueva else _e(area.get("nombre") or area["id"])
    ancla = "nueva" if nueva else _e(area["id"])

    quitar = "" if nueva else f"""
        <details class="equipo-quitar">
          <summary>Quitar esta área</summary>
          <form method="post" action="/admin/equipo/area/quitar">
            <input type="hidden" name="id" value="{_e(area["id"])}">
            <p>Su usuario deja de poder entrar, y sus conversaciones vuelven a
               ti. No se borra ningún mensaje.</p>
            <button type="submit" class="equipo-peligro">Sí, quitar
              {_e(area.get("nombre") or "el área")}</button>
          </form>
        </details>"""

    return f"""
      <section class="ajuste equipo-area" id="area-{ancla}">
        <div class="equipo-area-cabecera">
          <h2>{titulo}</h2>
          {"" if nueva else '<span class="equipo-pastilla">Área</span>'}
        </div>
        <form method="post" action="/admin/equipo/area" class="equipo-form">
          <input type="hidden" name="id" value="{_e(area.get("id"))}">

          <div class="equipo-rejilla">
            <label class="equipo-campo">
              <span>Nombre del área</span>
              <input name="nombre" required maxlength="40"
                     value="{_e(area.get("nombre"))}"
                     placeholder="Ventas, Soporte, Contratos…">
            </label>
            <label class="equipo-campo">
              <span>Su correo</span>
              <input name="correo" type="email" required maxlength="120"
                     value="{_e(area.get("correo"))}"
                     placeholder="ventas@tunegocio.com">
              <small>Aquí le avisamos cuando le llega un cliente.</small>
            </label>
          </div>

          <fieldset class="equipo-opciones">
            <legend>De qué se encarga</legend>
            <p class="equipo-ayuda">Las opciones de tu menú. Cuando un cliente
               elige una de estas, la conversación es de esta área.</p>
            <div class="equipo-casillas">
              {_casillas("opciones", set(area.get("opciones") or ()), opciones)}
            </div>
          </fieldset>

          <div class="equipo-rejilla">
            <label class="equipo-campo">
              <span>Usuario para entrar</span>
              <input name="usuario" maxlength="60" autocomplete="off"
                     autocapitalize="none" spellcheck="false"
                     value="{_e((usuario or {}).get("usuario"))}"
                     placeholder="ventas-tunegocio" {"required" if nueva else ""}>
              <small>Único: nadie más puede tenerlo.</small>
            </label>
            <label class="equipo-campo">
              <span>{"Su clave" if nueva else "Clave nueva"}</span>
              <input name="clave" type="password" minlength="8"
                     autocomplete="new-password" {"required" if nueva else ""}
                     placeholder="{"8 caracteres o más" if nueva else "Vacía = no cambiarla"}">
              <small>{_e(ultimo) or "Se la das tú a esa persona."}</small>
            </label>
          </div>

          <div class="equipo-pie">
            <button type="submit" class="boton-solido">
              {"Crear el área" if nueva else "Guardar cambios"}</button>
          </div>
        </form>
        {quitar}
      </section>"""


@router.get("/equipo", response_class=HTMLResponse)
def pantalla_equipo(request: Request, ok: str = "", mal: str = ""):
    """El equipo del negocio: sus áreas y a dónde le llegan los avisos."""
    quienes, fuera = _dueno_o_fuera(request)
    if fuera is not None:
        return fuera
    sesion, quien = quienes

    plan = planes.PLANES[config.PLAN]
    cupo = config.MAX_DESTINOS_AVISOS
    areas = equipo.areas()
    opciones = equipo.opciones_del_menu()

    banda = ""
    if ok:
        banda = f'<div class="banda ok">{_e(ok)}</div>'
    elif mal:
        banda = f'<div class="banda alerta">{_e(mal)}</div>'

    if cupo <= 0:
        cuerpo_areas = f"""
      <section class="ajuste equipo-plan">
        <h2>Tu plan {_e(plan.nombre)} es para un solo administrador</h2>
        <p class="ajuste-apoyo">Todos los clientes te llegan a ti. Con el plan
           <strong>Pro</strong> puedes tener hasta
           {planes.PLANES[planes.PRO].areas} áreas —Ventas, Soporte…—, cada una
           con su usuario, recibiendo y atendiendo solo lo suyo. Con el
           <strong>Premium</strong>, hasta {planes.PLANES[planes.PREMIUM].areas}.</p>
        <p class="ajuste-nota">Para cambiar de plan, escríbenos.</p>
      </section>"""
    else:
        tarjetas = "".join(_tarjeta_area(a, opciones) for a in areas)
        if len(areas) < cupo:
            nueva = f"""
      <details class="equipo-anadir"{" open" if not areas else ""}>
        <summary>+ Añadir un área <span>({len(areas)} de {cupo} en tu plan)</span></summary>
        {_tarjeta_area(None, opciones)}
      </details>"""
        else:
            nueva = (f'<p class="ajuste-nota">Tienes las {cupo} áreas de tu plan '
                     f'{_e(plan.nombre)}. Si necesitas más, escríbenos.</p>')
        cuerpo_areas = tarjetas + nueva

    usadas = f"{len(areas)} de {cupo} áreas" if cupo > 0 else "sin áreas"

    return admin_ui._renovar(HTMLResponse(admin_ui._pagina("Equipo", f"""
      <div class="armazon">
        {admin_ui._rail("equipo", quien)}

        <main class="agenda">
          <header class="agenda-cabecera">
            <div class="agenda-titulo">
              <h1>Tu equipo</h1>
              <p class="apoyo">Cada área recibe por correo los clientes de lo
                 que le toca y, en el panel, solo ve esas conversaciones. Lo
                 que no es de ningún área te llega a ti.</p>
            </div>
            <span class="equipo-plan-pastilla">Plan {_e(plan.nombre)} ·
              {usadas}</span>
          </header>

          {banda}

          <section class="ajuste" id="tus-avisos">
            <h2>Tus avisos</h2>
            <p class="ajuste-apoyo">El correo donde te avisamos de los clientes
               que no son de ningún área{" —en tu plan, todos—" if cupo <= 0 else ""}.</p>
            <form method="post" action="/admin/equipo/correo" class="equipo-fila">
              <input name="correo" type="email" maxlength="120"
                     value="{_e(config.AVISOS_CORREO_DUENO)}"
                     placeholder="tu@correo.com" aria-label="Tu correo de avisos">
              <button type="submit" class="boton-solido">Guardar</button>
            </form>
          </section>

          {cuerpo_areas}

          {admin_ui._credito()}
        </main>
      </div>""", guiones=("panel-base.js",), pantalla_completa=True)),
        request, sesion)


@router.post("/equipo/correo")
async def guardar_correo(request: Request):
    quienes, fuera = _dueno_o_fuera(request)
    if fuera is not None:
        return fuera
    formulario = await request.form()
    try:
        equipo.guardar_correo_dueno(formulario.get("correo") or "")
    except equipo.NoSePudo as e:
        return _volver(mal=str(e), ancla="#tus-avisos")
    return _volver(ok="Listo: los avisos que son para ti te llegan a ese correo.",
                   ancla="#tus-avisos")


@router.post("/equipo/area")
async def guardar_area(request: Request):
    quienes, fuera = _dueno_o_fuera(request)
    if fuera is not None:
        return fuera
    formulario = await request.form()
    try:
        area_id = equipo.guardar_area(
            (formulario.get("id") or "").strip() or None,
            formulario.get("nombre") or "",
            formulario.get("correo") or "",
            formulario.getlist("opciones"),
            formulario.get("usuario") or "",
            formulario.get("clave") or "")
    except equipo.NoSePudo as e:
        return _volver(mal=str(e))
    nombre = " ".join((formulario.get("nombre") or "").split())
    return _volver(ok=f"Área «{nombre}» guardada.", ancla=f"#area-{area_id}")


@router.post("/equipo/area/quitar")
async def quitar_area(request: Request):
    quienes, fuera = _dueno_o_fuera(request)
    if fuera is not None:
        return fuera
    formulario = await request.form()
    if not equipo.quitar_area((formulario.get("id") or "").strip()):
        return _volver(mal="Esa área ya no existía.")
    return _volver(ok="Área quitada. Sus conversaciones vuelven a ti.")
