"""
ESTADÍSTICAS, DESDE EL PANEL DEL DUEÑO
=======================================
Cuánta gente le escribió, qué pidió, de dónde llegó y qué dejó el bot
hecho (citas, consultas). Las cuentas están en `app/core/estadisticas.py`.

Las gráficas son HTML y CSS, sin librería: una barra es un `div` con su
altura. Son de UNA serie cada una, así que van en el color de acento y sin
leyenda —el título dice qué son—; cada barra dice su valor al pasar por
encima, y debajo hay una tabla con los mismos datos para quien no pueda
leer una gráfica.

Solo el dueño.
"""

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core import cobros, equipo, estadisticas
from app.web import admin_ui

router = APIRouter(prefix="/admin", tags=["panel"])


def _e(valor) -> str:
    return html.escape(str(valor if valor is not None else ""))


def _numero(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


def _columnas(serie: list) -> str:
    """Mensajes por día: una columna por día, de izquierda a derecha."""
    tope = max((d["mensajes"] for d in serie), default=0)
    if tope == 0:
        return ('<p class="est-vacio">Ningún mensaje en este periodo todavía.</p>')

    columnas = []
    for d in serie:
        n = d["mensajes"]
        alto = 0 if n == 0 else max(3, round(100 * n / tope))
        etiqueta = f"{d['fecha'].day} {cobros.MESES[d['fecha'].month - 1][:3]}"
        texto = f"{etiqueta}: {n} mensaje{'' if n == 1 else 's'}"
        # El valor encima solo en el pico: un número en cada columna no se
        # lee, y el pico es la referencia con la que se miden las demás.
        pico = (f'<span class="est-pico">{_numero(n)}</span>'
                if n == tope else "")
        columnas.append(
            f'<div class="est-col" title="{_e(texto)}" aria-label="{_e(texto)}">'
            f'{pico}<i style="height:{alto}%"></i></div>')

    primero, ultimo = serie[0]["fecha"], serie[-1]["fecha"]
    return f"""
      <div class="est-columnas" role="img"
           aria-label="Mensajes recibidos por día">{"".join(columnas)}</div>
      <div class="est-eje"><span>{primero.day} {cobros.MESES[primero.month - 1][:3]}</span>
        <span>{ultimo.day} {cobros.MESES[ultimo.month - 1][:3]}</span></div>"""


def _barras(filas: list, vacio: str) -> str:
    """Una lista ordenada de (nombre, cantidad) como barras horizontales."""
    if not filas:
        return f'<p class="est-vacio">{_e(vacio)}</p>'
    tope = max(n for _, n in filas) or 1
    return "".join(f"""
        <div class="est-fila" title="{_e(nombre)}: {n}">
          <span class="est-nombre">{_e(nombre)}</span>
          <span class="est-barra"><i style="width:{max(2, round(100 * n / tope))}%"></i></span>
          <span class="est-cuenta cifras">{_numero(n)}</span>
        </div>""" for nombre, n in filas)


def _tabla(serie: list) -> str:
    filas = "".join(
        f"<tr><td>{_e(d['fecha'].strftime('%d/%m'))}</td>"
        f"<td class='cifras'>{d['mensajes']}</td></tr>" for d in serie)
    return f"""
      <details class="est-tabla">
        <summary>Ver los datos en una tabla</summary>
        <table><thead><tr><th>Día</th><th>Mensajes</th></tr></thead>
        <tbody>{filas}</tbody></table>
      </details>"""


@router.get("/estadisticas", response_class=HTMLResponse)
def pantalla(request: Request, dias: int = 30):
    sesion = admin_ui._sesion_valida(request)
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return admin_ui._pedir_login(
            admin_ui.CADUCADA if admin_ui._sesion_caducada(request) else "")
    if not quien.es_dueno:
        return RedirectResponse("/admin/inbox", status_code=303)

    r = estadisticas.resumen(dias)

    periodos = "".join(
        f'<a class="filtro{" activo" if p == r["dias"] else ""}" '
        f'href="/admin/estadisticas?dias={p}">Últimos {p} días</a>'
        for p in estadisticas.PERIODOS)

    tarjetas = "".join(f"""
            <div class="metrica{clase}">
              <span>{_e(titulo)}</span>
              <strong class="cifras">{_numero(valor)}</strong>
            </div>""" for titulo, valor, clase in (
        ("Personas que escribieron", r["personas"], " acento"),
        ("Mensajes recibidos", r["mensajes"], ""),
        ("Citas agendadas", r["citas"], ""),
        ("Consultas y pedidos de asesor", r["consultas"], ""),
        ("Respuestas tuyas y de tu equipo", r["respuestas_humanas"], ""),
    ))

    area = "" if r["por_area"] is None else f"""
          <section class="ajuste est-caja">
            <h2>Conversaciones nuevas por área</h2>
            {_barras(r["por_area"], "Sin conversaciones nuevas.")}
          </section>"""

    return admin_ui._renovar(HTMLResponse(admin_ui._pagina("Estadísticas", f"""
      <div class="armazon">
        {admin_ui._rail("estadisticas", quien)}

        <main class="agenda">
          <header class="agenda-cabecera">
            <div class="agenda-titulo">
              <h1>Estadísticas</h1>
              <p class="apoyo">Del {r["desde"].day} de
                 {cobros.MESES[r["desde"].month - 1]} al {r["hasta"].day} de
                 {cobros.MESES[r["hasta"].month - 1]}.</p>
            </div>
            <nav class="lista-filtros" aria-label="Periodo">{periodos}</nav>
          </header>

          <div class="metricas est-metricas">{tarjetas}</div>

          <section class="ajuste est-caja est-ancha">
            <h2>Mensajes recibidos por día</h2>
            {_columnas(r["por_dia"])}
            {_tabla(r["por_dia"])}
          </section>

          <div class="est-rejilla">
            <section class="ajuste est-caja">
              <h2>Qué eligieron en el menú</h2>
              <p class="ajuste-apoyo">De las {_numero(r["nuevos"])} personas que
                 escribieron por primera vez.</p>
              {_barras(r["opciones"], "Nadie nuevo en este periodo.")}
            </section>
            <section class="ajuste est-caja">
              <h2>De dónde llegaron</h2>
              <p class="ajuste-apoyo">Según el mensaje con el que abrieron el
                 chat: tu web, un código QR, Instagram…</p>
              {_barras(r["origenes"], "Nadie nuevo en este periodo.")}
            </section>
            {area}
          </div>

          {admin_ui._credito()}
        </main>
      </div>""", guiones=("panel-base.js",), pantalla_completa=True)),
        request, sesion)
