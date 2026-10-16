"""
EL CUERPO DE CADA SECCIÓN
==========================
El HTML de lo que va dentro del armazón (`paginas.pagina_panel` y
`pagina_barbero`). Una función por pantalla del handoff, con su número.

Cada pantalla es la MISMA en computador y celular: la hoja de estilos la
acomoda (tablas → tarjetas por debajo de 768 px). Lo que en el celular se
ve distinto va con `solo-escritorio` / `solo-celular`.

Los formularios funcionan sin JavaScript: se envían y el servidor responde
con la pantalla. `barberia.js` solo añade comodidad (el total en vivo de
la hoja de cobro, el arqueo mientras se escribe, el usuario que se
autocompleta, cerrar con Esc).

Todo lo que escribe alguien pasa por `e()`.
"""

from datetime import date
from urllib.parse import quote

from app.barberia import formato, permisos
from app.barberia import modelos as m
from app.barberia.operacion import CATEGORIAS_GASTO, METODOS_COBRO, MOTIVOS_ANULACION
from app.barberia.paginas import e
from app.barberia.reportes import FILTROS_ACTIVIDAD
from app.core import planes

P = formato.pesos

# "Ampliar plan" abre el WhatsApp de Nitro2Tech con el mensaje escrito.
AMPLIAR_PLAN = (f"https://wa.me/{planes.WHATSAPP_COBROS}?text="
                + quote("Hola, quiero ampliar mi plan de barbería."))


def _error(mensaje: str | None) -> str:
    return f'<div class="caja-error" role="alert">{e(mensaje)}</div>' if mensaje else ""


def _estadistica(rotulo: str, cifra: str, tono: str = "") -> str:
    return (f'<div class="tarjeta estadistica"><span class="estadistica-rotulo">{e(rotulo)}</span>'
            f'<span class="estadistica-cifra {tono}">{e(cifra)}</span></div>')


def cajon(titulo: str, cuerpo: str, pie: str, cerrar: str, subtitulo: str = "",
          accion: str = "", metodo: str = "post", ancho: int = 480) -> str:
    """
    El panel lateral (§4.4). Si `accion` trae una ruta, el cajón entero es
    un formulario y el pie lleva sus botones. Se cierra con el enlace de
    `cerrar`, con Esc o tocando el velo (barberia.js).
    """
    abre = f'<form class="cajon-cuerpo-form" method="{metodo}" action="{e(accion)}" novalidate>' \
        if accion else '<div class="cajon-cuerpo-form">'
    cierra = "</form>" if accion else "</div>"
    sub = f'<p class="cajon-sub">{e(subtitulo)}</p>' if subtitulo else ""
    return f"""
<a class="velo" href="{e(cerrar)}" aria-label="Cerrar" data-cerrar></a>
<aside class="cajon" role="dialog" aria-modal="true" aria-labelledby="cajon-titulo"
       style="width:min({ancho}px,100%)" data-cerrar-en="{e(cerrar)}">
  {abre}
    <header class="cajon-cabeza">
      <div><h2 id="cajon-titulo">{e(titulo)}</h2>{sub}</div>
      <a class="boton boton-secundario" href="{e(cerrar)}">Cerrar</a>
    </header>
    <div class="cajon-cuerpo">{cuerpo}</div>
    <footer class="cajon-pie">{pie}</footer>
  {cierra}
</aside>"""


def dialogo(titulo: str, texto: str, accion: str, boton: str, cerrar: str,
            peligro: bool = True) -> str:
    clase = "boton-destructivo-fuerte" if peligro else "boton-primario"
    return f"""
<a class="velo" href="{e(cerrar)}" aria-label="Cerrar" data-cerrar></a>
<div class="dialogo" role="alertdialog" aria-modal="true" aria-labelledby="dialogo-titulo"
     data-cerrar-en="{e(cerrar)}">
  <h2 id="dialogo-titulo">{e(titulo)}</h2>
  <p>{e(texto)}</p>
  <form method="post" action="{e(accion)}" class="dialogo-pie">
    <a class="boton boton-secundario" href="{e(cerrar)}">Cancelar</a>
    <button class="boton {clase}" type="submit">{e(boton)}</button>
  </form>
</div>"""


def _q(base: str, **params) -> str:
    """Una dirección con sus filtros: los que valen algo, en orden."""
    partes = [f"{k}={v}" for k, v in params.items() if v not in (None, "", "hoy")]
    return base + ("?" + "&".join(partes) if partes else "")


# ══════════════════════════════════════════════════════════════════════
#  6.2.1 RESUMEN
# ══════════════════════════════════════════════════════════════════════

PERIODO_TEXTO = {"hoy": ("frente a ayer", "hoy"), "semana": ("frente a la semana pasada", "esta semana"),
                 "mes": ("frente al mes pasado", "este mes")}


def _margen(pct: int) -> str:
    if pct < 0:
        return f"Pierdes el {abs(pct)}%"
    return f"Te queda el {pct}%"


def resumen(r: dict, periodo: str, sede: int | None) -> str:
    frente, en = PERIODO_TEXTO[periodo]
    if r["cambio"] is None:
        nota_ingresos = ""
    else:
        signo = "+" if r["cambio"] > 0 else (formato.MENOS if r["cambio"] < 0 else "")
        tono = "ok" if r["cambio"] > 0 else ("mal" if r["cambio"] < 0 else "")
        nota_ingresos = f'<span class="kpi-nota {tono}">{signo}{abs(r["cambio"])}% {frente}</span>'
    nota_gastos = (f'<span class="kpi-nota">{e(formato.con_mayuscula(r["gasto_mayor"][0].lower()))} '
                   f'es el {r["gasto_mayor"][1]}%</span>' if r["gasto_mayor"] else "")

    def kpi(rotulo, valor, nota=""):
        return f"""
        <div class="tarjeta kpi">
          <span class="kpi-rotulo">{e(rotulo)}</span>
          <span class="kpi-cifra"><span class="solo-escritorio">{e(P(valor))}</span><span
            class="solo-celular">{e(formato.pesos_cortos(valor))}</span></span>
          {nota}
        </div>"""

    ocupacion = f"""
        <div class="tarjeta kpi">
          <span class="kpi-rotulo">Ocupación</span>
          <span class="kpi-cifra">{"—" if r["ocupacion"] is None else f'{r["ocupacion"]}%'}</span>
          <span class="kpi-nota solo-escritorio">Horas con cliente en silla</span>
        </div>"""

    # ── la gráfica ──
    maximo = max(r["barras"]) if any(r["barras"]) else 0
    columnas = []
    for etiqueta, valor in zip(r["etiquetas"], r["barras"]):
        alto = int(valor * 78 / maximo) if maximo else 0
        mayor = " mayor" if maximo and valor == maximo else ""
        columnas.append(f"""
          <div class="grafica-col">
            <span class="grafica-monto">{e(formato.pesos_cortos(valor)) if valor else ""}</span>
            <span class="grafica-barra{mayor}" style="height:{max(alto, 2 if valor else 0)}%"></span>
            <span class="grafica-etiqueta">{e(etiqueta)}</span>
          </div>""")
    titulo_grafica = {"hoy": "Ingresos por hora, hoy", "semana": "Ingresos por día, esta semana",
                      "mes": f"Ingresos por semana, {formato.MESES[r['desde'].month - 1]}"}[periodo]
    mejor = f'<span class="tarjeta-extra">Mejor momento: {e(r["mejor"])}</span>' if r["mejor"] else ""

    def apilada(titulo, partes, es_dinero):
        total = sum(v for _, v in partes)
        colores = ("violeta", "lila", "lila-claro")
        segmentos = "".join(
            f'<span class="apilada-seg {colores[i]}" style="width:{(v * 100 / total) if total else 0:.2f}%"></span>'
            for i, (_, v) in enumerate(partes) if v)
        leyenda = "".join(
            f'<li><span class="punto {colores[i]}"></span>{e(t)}'
            f'<span class="leyenda-valor">{e(P(v) if es_dinero else v)}'
            f'{f" · {int(round(v * 100 / total))}%" if total else ""}</span></li>'
            for i, (t, v) in enumerate(partes))
        return f"""
          <div class="apilada">
            <h3>{e(titulo)}</h3>
            <div class="apilada-barra">{segmentos or '<span class="apilada-seg vacia"></span>'}</div>
            <ul class="leyenda">{leyenda}</ul>
          </div>"""

    # ── ranking ──
    if r["ranking"]:
        mayor_rank = r["ranking"][0]["total"] or 1
        filas_rank = "".join(f"""
          <li class="ranking-fila">
            <span class="ranking-pos">{i + 1}</span>
            <span class="ranking-nombre">{e(b["nombre"])}<span class="celda-nota">{"" if b["ocupacion"] is None else f'Ocupación {b["ocupacion"]}%'}</span></span>
            <span class="ranking-barra"><span style="width:{b["total"] * 100 / mayor_rank:.1f}%"></span></span>
            <span class="ranking-n">{b["servicios"]} serv.</span>
            <span class="ranking-total">{e(P(b["total"]))}</span>
          </li>""" for i, b in enumerate(r["ranking"]))
    else:
        filas_rank = f'<li class="tenue">Todavía no hay servicios {e(en)}.</li>'

    # ── para revisar ──
    if r["revisar"]:
        revisar = "".join(
            f'<a class="revisar-item" href="{e(_q("/b/" + x["ir"], sede=sede))}">'
            f'<span class="punto {x["punto"]}"></span><span>{e(x["texto"])}</span></a>'
            for x in r["revisar"])
    else:
        revisar = '<p class="tenue">Nada pendiente. Todo cuadra.</p>'

    visitas = formato.plural(r["visitas"], "servicio")
    return f"""
      <div class="fila-kpi">
        <section class="hero">
          <span class="hero-rotulo">Ganancia neta<span class="solo-celular">, {e(en)}</span></span>
          <span class="hero-cifra">{e(P(r["neta"]))}</span>
          <span class="hero-nota">{e(_margen(r["margen"]))} de lo facturado en {e(visitas)}</span>
        </section>
        {kpi("Ingresos", r["ingresos"], nota_ingresos)}
        {kpi("Gastos", r["gastos"], nota_gastos)}
        {kpi("Ticket promedio", r["ticket"], '<span class="kpi-nota solo-escritorio">Por visita</span>')}
        {ocupacion}
      </div>

      <div class="fila-2 solo-escritorio-bloque">
        <section class="tarjeta">
          <header class="tarjeta-cabeza"><h2>{e(titulo_grafica)}</h2>{mejor}</header>
          <div class="grafica">{"".join(columnas)}</div>
        </section>
        <section class="tarjeta apiladas">
          {apilada("Cómo llegan los clientes", r["llegan"], False)}
          {apilada("Cómo pagan", r["pagan"], True)}
        </section>
      </div>

      <div class="fila-3">
        <section class="tarjeta solo-escritorio-bloque">
          <header class="tarjeta-cabeza"><h2>Barberos que más facturan</h2>
            <a class="enlace" href="{e(_q("/b/equipo", sede=sede))}">Ver liquidaciones</a></header>
          <ol class="ranking">{filas_rank}</ol>
        </section>
        <section class="tarjeta revisar">
          <header class="tarjeta-cabeza"><h2>Para revisar</h2>
            <a class="enlace solo-escritorio" href="{e(_q("/b/actividad", sede=sede))}">Ver actividad</a></header>
          <div class="revisar-lista">{revisar}</div>
        </section>
      </div>"""


# ══════════════════════════════════════════════════════════════════════
#  6.2.3 CAJA
# ══════════════════════════════════════════════════════════════════════

def _diferencia(dif) -> str:
    if dif is None:
        return ""
    if dif == 0:
        return '<p class="arqueo-resultado ok">Cuadra exacto</p>'
    if dif < 0:
        return f'<p class="arqueo-resultado mal">Falta {e(P(-dif))}</p>'
    return f'<p class="arqueo-resultado aviso">Sobra {e(P(dif))}</p>'


def caja(cajas: list[dict], errores: dict | None = None) -> str:
    errores = errores or {}
    tarjetas = []
    for c in cajas:
        error = _error(errores.get(c["sede_id"]))
        if c["caja"] is None:
            tarjetas.append(f"""
        <section class="tarjeta caja-tarjeta">
          <header class="caja-cabeza"><h2>{e(c["sede"])}</h2><span class="chip chip-pausado">Sin abrir</span></header>
          <p class="tenue">La caja de hoy no se ha abierto. Se abre sola con el primer
            cobro, o ábrela aquí con la base que dejaste.</p>
          <form method="post" action="/b/caja/abrir" class="caja-form" novalidate>
            <input type="hidden" name="sede_id" value="{c["sede_id"]}">
            <label class="campo"><span class="campo-etiqueta">Base al abrir</span>
              <input class="entrada-texto" name="base" inputmode="numeric" placeholder="$0"
                     data-dinero autocomplete="off"></label>
            {error}
            <button class="boton boton-primario" type="submit">Abrir caja</button>
          </form>
        </section>""")
            continue

        abierta = c["abierta"]
        estado = (f"Abierta desde las {formato.hora(c['abierta_en'])} por {c['abierta_por']}"
                  if abierta else
                  f"Cerrada a las {formato.hora(c['cerrada_en'])} por {c['cerrada_por']}")
        desglose = "".join(
            f'<div class="fila-dato"><span>{nombre}</span><span>{e(P(c["por_metodo"].get(k, 0)))}</span></div>'
            for k, nombre in ((m.TRANSFERENCIA, "Transferencia"), (m.TARJETA, "Tarjeta"),
                              (m.EFECTIVO, "Efectivo")))
        if abierta:
            conteo = f"""
            <form method="post" action="/b/caja/{c["caja"]}/cerrar" class="caja-form" novalidate
                  data-arqueo="{int(c["esperado"])}">
              <label class="campo"><span class="campo-etiqueta">Cuánto contaste</span>
                <input class="entrada-texto" name="contado" inputmode="numeric" placeholder="$0"
                       data-dinero autocomplete="off" required></label>
              <p class="arqueo-resultado" data-arqueo-resultado hidden></p>
              {error}
              <button class="boton boton-primario" type="submit" data-requiere-conteo>Cerrar caja</button>
            </form>"""
        else:
            conteo = f"""
            <div class="fila-dato"><span>Contaste</span><span>{e(P(c["contado"]))}</span></div>
            {_diferencia(c["diferencia"])}
            {error}"""

        tarjetas.append(f"""
        <section class="tarjeta caja-tarjeta">
          <header class="caja-cabeza"><h2>{e(c["sede"])}</h2>
            <span class="chip {"chip-ok" if abierta else "chip-pausado"}">{"Abierta" if abierta else "Cerrada"}</span></header>
          <div class="caja-total">
            <span class="tenue">Vendido hoy</span>
            <span class="caja-cifra">{e(P(c["vendido"]))}</span>
            <span class="tenue caja-estado">{e(estado)}</span>
          </div>
          <div class="caja-desglose">{desglose}</div>
          <div class="arqueo">
            <h3>Arqueo de efectivo</h3>
            <div class="fila-dato"><span>Base al abrir</span><span>{e(P(c["base"]))}</span></div>
            <div class="fila-dato"><span>Gastos pagados de la caja</span><span>{formato.MENOS if c["gastos"] else ""}{e(P(c["gastos"]))}</span></div>
            <div class="fila-dato fuerte"><span>Debería haber</span><span>{e(P(c["esperado"]))}</span></div>
            {conteo}
          </div>
        </section>""")

    return f"""
      <div class="cajas">{"".join(tarjetas) or '<p class="tenue">No tienes sedes asignadas.</p>'}</div>
      <p class="nota-pie">Una caja cerrada no se puede editar. Si hay que corregir algo,
        se anula con motivo y queda en Actividad.</p>"""


# ══════════════════════════════════════════════════════════════════════
#  6.2.4 BARBEROS Y PAGOS
# ══════════════════════════════════════════════════════════════════════

def equipo(d: dict, es_dueno: bool, sede: int | None) -> str:
    filas = []
    for f in d["filas"]:
        if f["estado"] == m.BORRADOR:
            accion = (f'<form method="post" action="/b/equipo/{f["personal_id"]}/aprobar">'
                      f'<button class="boton boton-oscuro boton-fila" type="submit">Aprobar</button></form>')
        elif f["estado"] == m.APROBADA:
            accion = (f'<form method="post" action="/b/equipo/liquidacion/{f["liquidacion_id"]}/pagar">'
                      f'<button class="boton boton-primario boton-fila" type="submit">Marcar pagada</button></form>')
        else:
            accion = '<span class="boton boton-fila pagada">Pagada</span>'

        notas = []
        if f["adelantos"]:
            fecha = f" del {formato.fecha_corta(f['fecha_adelanto'])}" if f.get("fecha_adelanto") else ""
            notas.append(f"Adelanto{fecha}")
        if f["alquiler"]:
            notas.append("Alquiler de silla")
        descuento = (f'<span class="mal">{formato.MENOS}{e(P(f["descuentos"]))}</span>'
                     f'<span class="celda-nota">{e(", ".join(notas))}</span>'
                     if f["descuentos"] else '<span class="tenue">—</span>')
        esquema = (f'<a class="esquema-enlace" href="{e(_q("/b/equipo", sede=sede, esquema=f["personal_id"]))}">'
                   f'{e(f["esquema"])}</a>' if es_dueno else f'<span class="esquema-texto">{e(f["esquema"])}</span>')
        filas.append(f"""
          <div class="tabla-fila equipo-fila{' apagada' if not f['activo'] else ''}">
            <div class="celda-persona"><span class="avatar">{e(f["iniciales"])}</span>
              <span><span class="celda-fuerte">{e(f["nombre"])}</span>
              <span class="celda-nota">{e(f["sedes"])}</span></span></div>
            <div data-rotulo="Esquema">{esquema}<span class="celda-nota">{e(f["nota_esquema"])}</span></div>
            <div data-rotulo="Comisiones" class="celda-detalle">{e(P(f["comisiones"]))}</div>
            <div data-rotulo="Propinas" class="celda-detalle">{e(P(f["propinas"]))}</div>
            <div data-rotulo="Productos" class="celda-detalle">{e(P(f["productos"]))}</div>
            <div data-rotulo="Descuentos" class="celda-detalle">{descuento}</div>
            <div data-rotulo="Le pagas" class="celda-fuerte le-pagas">{e(P(f["total"]))}</div>
            <div class="celda-accion">{accion}</div>
          </div>""")

    tabla = "".join(filas) or '<p class="tenue tabla-vacia">No hay barberos en esta sede.</p>'
    return f"""
      <div class="estadisticas">
        {_estadistica("Total de la quincena", P(d["total"]))}
        {_estadistica("Falta por pagar", P(d["falta"]), "violeta")}
        {_estadistica("Adelantos a descontar", P(d["adelantos"]), "mal")}
      </div>
      <section class="tarjeta tabla-tarjeta">
        <div class="tabla-cabeza equipo-fila">
          <span>Barbero</span><span>Esquema</span><span>Comisiones</span><span>Propinas</span>
          <span>Productos</span><span>Descuentos</span><span>Le pagas</span><span></span>
        </div>
        {tabla}
      </section>
      <p class="nota-pie">Se paga por quincena: del 1 al 15 y del 16 al fin de mes. Al aprobar,
        las cifras quedan congeladas y los adelantos se descuentan. Pagada es final.</p>"""


def cajon_adelanto(barberos: list[dict], cerrar: str, error: str = "", valores: dict | None = None) -> str:
    v = valores or {}
    opciones = "".join(
        f'<option value="{b["personal_id"]}"{" selected" if str(b["personal_id"]) == str(v.get("personal_id")) else ""}>'
        f'{e(b["nombre"])}</option>' for b in barberos)
    cuerpo = f"""
      <label class="campo"><span class="campo-etiqueta">¿A quién?</span>
        <select class="entrada-texto" name="personal_id">{opciones}</select></label>
      <label class="campo"><span class="campo-etiqueta">¿Cuánto?</span>
        <input class="entrada-texto" name="monto" inputmode="numeric" data-dinero
               value="{e(v.get("monto", ""))}" placeholder="$0" autocomplete="off"></label>
      <label class="campo"><span class="campo-etiqueta">Nota (opcional)</span>
        <input class="entrada-texto" name="nota" value="{e(v.get("nota", ""))}" maxlength="200"></label>
      <p class="tenue">Se descuenta en la liquidación de esta quincena.</p>
      {_error(error)}"""
    pie = (f'<a class="boton boton-secundario" href="{e(cerrar)}">Cancelar</a>'
           f'<button class="boton boton-primario" type="submit">Registrar adelanto</button>')
    return cajon("Registrar adelanto", cuerpo, pie, cerrar, accion="/b/equipo/adelanto")


def cajon_esquema(p: dict, cerrar: str, error: str = "") -> str:
    """Cómo se le paga a un barbero (solo el dueño). `p` son sus datos actuales."""
    def radio(valor, titulo, texto):
        marcado = " checked" if p["esquema_pago"] == valor else ""
        return (f'<label class="opcion-rol"><input type="radio" name="esquema" value="{valor}"{marcado}>'
                f'<span><strong>{e(titulo)}</strong><span class="tenue">{e(texto)}</span></span></label>')
    cuerpo = f"""
      <fieldset class="grupo"><legend class="campo-etiqueta">Esquema</legend>
        {radio(m.COMISION, "Comisión", "Se lleva un porcentaje de lo que factura (50/50, 60/40…).")}
        {radio(m.FIJO_MAS_COMISION, "Fijo + comisión", "Un sueldo fijo por quincena más un porcentaje.")}
        {radio(m.ALQUILER_SILLA, "Alquiler de silla", "Se queda con todo lo que factura y paga un alquiler.")}
      </fieldset>
      <div class="dos-columnas">
        <label class="campo"><span class="campo-etiqueta">Su porcentaje</span>
          <input class="entrada-texto" name="porcentaje" inputmode="numeric" value="{e(p["porcentaje"])}"></label>
        <label class="campo"><span class="campo-etiqueta">Sueldo fijo por quincena</span>
          <input class="entrada-texto" name="sueldo_fijo" inputmode="numeric" data-dinero value="{e(p["sueldo_fijo"])}"></label>
        <label class="campo"><span class="campo-etiqueta">Alquiler por quincena</span>
          <input class="entrada-texto" name="alquiler" inputmode="numeric" data-dinero value="{e(p["alquiler"])}"></label>
        <label class="campo"><span class="campo-etiqueta">Meta de la quincena</span>
          <input class="entrada-texto" name="meta" inputmode="numeric" data-dinero value="{e(p["meta"])}"></label>
      </div>
      <p class="tenue">El porcentaje solo aplica en Comisión y Fijo + comisión. Lo ya cobrado no cambia.</p>
      {_error(error)}"""
    pie = (f'<a class="boton boton-secundario" href="{e(cerrar)}">Cancelar</a>'
           f'<button class="boton boton-primario" type="submit">Guardar esquema</button>')
    return cajon(f"Cómo se le paga a {p['nombre']}", cuerpo, pie, cerrar,
                 accion=f"/b/equipo/{p['id']}/esquema")


# ══════════════════════════════════════════════════════════════════════
#  6.2.5 GASTOS
# ══════════════════════════════════════════════════════════════════════

def gastos(filas: list[dict], sedes: tuple, sede_sel: int | None, error: str = "",
           valores: dict | None = None) -> str:
    v = valores or {}
    total = sum((f["monto"] for f in filas), 0)
    cuerpo = "".join(f"""
          <div class="tabla-fila gastos-fila">
            <div><span class="celda-fuerte">{e(f["descripcion"])}</span>
              <span class="celda-nota">{"Pagado de la caja" if f["de_la_caja"] else "Transferencia"}</span></div>
            <div data-rotulo="Categoría">{e(f["categoria"] or "")}</div>
            <div data-rotulo="Tipo">{e(f["tipo"])}</div>
            <div data-rotulo="Sede">{e(f["sede"])}</div>
            <div data-rotulo="Fecha">{e(formato.fecha_corta(f["fecha"]))}</div>
            <div data-rotulo="Monto" class="celda-fuerte">{e(P(f["monto"]))}</div>
          </div>""" for f in filas) or '<p class="tenue tabla-vacia">No hay gastos este mes.</p>'

    def chips(nombre, opciones, actual):
        return "".join(
            f'<label class="chip-radio"><input type="radio" name="{nombre}" value="{e(val)}"'
            f'{" checked" if str(val) == str(actual) else ""}><span>{e(txt)}</span></label>'
            for val, txt in opciones)

    sede_def = v.get("sede_id") or sede_sel or (sedes[0][0] if sedes else "")
    return f"""
      <div class="gastos">
        <section class="tarjeta tabla-tarjeta">
          <div class="tabla-cabeza gastos-fila"><span>Concepto</span><span>Categoría</span>
            <span>Tipo</span><span>Sede</span><span>Fecha</span><span>Monto</span></div>
          {cuerpo}
          <div class="tabla-total gastos-fila"><span>Total</span><span></span><span></span>
            <span></span><span></span><span class="celda-fuerte">{e(P(total))}</span></div>
        </section>
        <section class="tarjeta">
          <form method="post" action="/b/gastos" class="formulario-panel" novalidate>
            <h2>Registrar gasto</h2>
            <label class="campo"><span class="campo-etiqueta">¿En qué se gastó?</span>
              <input class="entrada-texto" name="descripcion" placeholder="Ej. Recibo de la luz"
                     value="{e(v.get("descripcion", ""))}" maxlength="255" data-requerido></label>
            <label class="campo"><span class="campo-etiqueta">Monto</span>
              <input class="entrada-texto" name="monto" inputmode="numeric" placeholder="$0" data-dinero
                     value="{e(v.get("monto", ""))}" autocomplete="off" data-requerido></label>
            <fieldset class="grupo"><legend class="campo-etiqueta">Categoría</legend>
              <div class="chips">{chips("categoria", [(c, c) for c in CATEGORIAS_GASTO], v.get("categoria", "Insumos"))}</div></fieldset>
            <fieldset class="grupo"><legend class="campo-etiqueta">Tipo</legend>
              <div class="chips">{chips("tipo", [("FIJO", "Fijo, cada mes"), ("VARIABLE", "Variable")], v.get("tipo", "VARIABLE"))}</div></fieldset>
            <fieldset class="grupo"><legend class="campo-etiqueta">Sede</legend>
              <div class="chips">{chips("sede_id", list(sedes), sede_def)}</div></fieldset>
            <label class="casilla"><input type="checkbox" name="de_la_caja" value="1"
              {"checked" if v.get("de_la_caja") else ""}><span class="casilla-caja" aria-hidden="true"></span>
              Pagado de la caja (resta del arqueo)</label>
            {_error(error)}
            <button class="boton boton-primario boton-grande" type="submit" data-requiere-campos>Registrar gasto</button>
          </form>
        </section>
      </div>"""


# ══════════════════════════════════════════════════════════════════════
#  6.2.7 ACTIVIDAD
# ══════════════════════════════════════════════════════════════════════

def actividad(filas: list[dict], filtro: str, sede: int | None) -> str:
    chips = "".join(
        f'<a class="chip-sel{" activo" if c == filtro else ""}" href="{e(_q("/b/actividad", filtro=c if c != "todo" else "", sede=sede))}">{e(t)}</a>'
        for c, t, _ in FILTROS_ACTIVIDAD)
    lineas = "".join(f"""
        <li class="actividad-fila">
          <span class="actividad-cuando">{e(a["cuando"])}</span>
          <span class="punto {a["punto"]}"></span>
          <div class="actividad-que">
            <p><strong>{e(a["actor"])}</strong> {e(a["verbo"])}</p>
            {f'<p class="tenue">{e(a["detalle"])}</p>' if a["detalle"] else ""}
            {f'<p class="motivo">Motivo: {e(a["motivo"])}</p>' if a["motivo"] else ""}
          </div>
          <span class="actividad-sede">{e(a["sede"])}</span>
        </li>""" for a in filas) or '<li class="tenue tabla-vacia">No hay nada aquí todavía.</li>'
    return f"""
      <div class="chips">{chips}</div>
      <section class="tarjeta lista-actividad"><ol>{lineas}</ol></section>"""


# ══════════════════════════════════════════════════════════════════════
#  6.2.8 SEDES (y los precios)
# ══════════════════════════════════════════════════════════════════════

def sedes(datos: list[dict], precios: list[dict], sedes_ids: tuple, uso: tuple,
          cupos: tuple, error: str = "") -> str:
    tarjetas = "".join(f"""
        <section class="tarjeta sede-tarjeta{' apagada' if not s["activo"] else ''}">
          <header class="sede-cabeza">
            <div><h2>{e(s["nombre"])}</h2><p class="tenue">{e(s["direccion"])}</p></div>
            <form method="post" action="/b/sedes/{s["id"]}/estado">
              <input type="hidden" name="activo" value="{"0" if s["activo"] else "1"}">
              <button class="interruptor" type="submit" role="switch" aria-checked="{"true" if s["activo"] else "false"}"
                      aria-label="{"Pausar" if s["activo"] else "Abrir"} {e(s["nombre"])}"></button>
            </form>
          </header>
          <div class="fila-dato"><span>Barberos</span><span>{s["barberos"]}</span></div>
          <div class="fila-dato"><span>Facturó este mes</span><span>{e(P(s["facturado"]))}</span></div>
          <div class="fila-dato"><span>Horario</span><span class="texto-derecha">{e(s["horario"])}
            <a class="enlace" href="/b/sedes?horario={s["id"]}">Editar</a></span></div>
          <div class="fila-dato"><span>{e(precios[0]["nombre"]) if precios else "Corte"}</span>
            <span>{e(P(s["corte"])) if s["corte"] is not None else "—"}</span></div>
          <div class="fila-dato"><span>Estado</span>
            <span>{"Abierta al público" if s["activo"] else "Pausada"}</span></div>
        </section>""" for s in datos)

    cab = "".join(f"<span>{e(n)}</span>" for _, n in sedes_ids)
    columnas = f"minmax(0,1.6fr) repeat({len(sedes_ids)}, minmax(0,1fr))"
    filas = "".join(
        f'<div class="tabla-fila precios-fila" style="grid-template-columns:{columnas}">'
        f'<div class="celda-fuerte">{e(p["nombre"])}</div>'
        + "".join(
            f'<div data-rotulo="{e(n)}"><input class="entrada-texto entrada-chica" name="precio_{p["id"]}_{sid}" '
            f'inputmode="numeric" data-dinero value="{e(P(p["precios"].get(sid)) if p["precios"].get(sid) is not None else "")}" '
            f'aria-label="{e(p["nombre"])} en {e(n)}"></div>'
            for sid, n in sedes_ids)
        + "</div>" for p in precios)

    usa_sedes, usa_barberos = uso
    cupo_sedes, cupo_barberos = cupos
    agregar = ('<a class="boton boton-secundario" href="/b/sedes?nueva=1">Agregar sede</a>'
               if usa_sedes < cupo_sedes else "")
    return f"""
      <div class="sedes">{tarjetas}</div>
      <div class="plan-barra">
        <p>Usas <strong>{formato.plural(usa_sedes, "sede")} de {cupo_sedes}</strong> y
           <strong>{formato.plural(usa_barberos, "barbero")} de {cupo_barberos}</strong> que incluye tu plan.</p>
        <div class="plan-acciones">{agregar}
          <a class="boton boton-primario" href="{e(AMPLIAR_PLAN)}"
             target="_blank" rel="noopener">Ampliar plan</a></div>
      </div>
      <section class="tarjeta tabla-tarjeta">
        <header class="tarjeta-cabeza tarjeta-cabeza-pad"><h2>Servicios y precios</h2>
          <span class="tarjeta-extra">Lo ya cobrado no cambia</span></header>
        <form method="post" action="/b/sedes/precios" novalidate>
          <div class="tabla-cabeza precios-fila" style="grid-template-columns:{columnas}"><span>Servicio</span>{cab}</div>
          {filas}
          <div class="precios-pie">{_error(error)}
            <button class="boton boton-primario" type="submit">Guardar precios</button></div>
        </form>
        <form method="post" action="/b/sedes/servicio" class="precios-nuevo" novalidate>
          <label class="campo"><span class="campo-etiqueta">Servicio nuevo</span>
            <input class="entrada-texto" name="nombre" placeholder="Ej. Diseño de barba" maxlength="100"></label>
          <label class="campo"><span class="campo-etiqueta">Precio en todas las sedes</span>
            <input class="entrada-texto" name="precio" inputmode="numeric" data-dinero placeholder="$0"></label>
          <button class="boton boton-secundario" type="submit">Agregar servicio</button>
        </form>
      </section>"""


def cajon_sede_nueva(error: str = "", valores: dict | None = None) -> str:
    v = valores or {}
    cuerpo = f"""
      <label class="campo"><span class="campo-etiqueta">Nombre</span>
        <input class="entrada-texto" name="nombre" value="{e(v.get("nombre", ""))}" placeholder="Ej. Cedritos" maxlength="100"></label>
      <label class="campo"><span class="campo-etiqueta">Dirección</span>
        <input class="entrada-texto" name="direccion" value="{e(v.get("direccion", ""))}" maxlength="200"></label>
      <p class="tenue">Arranca con los mismos servicios y precios de tu primera sede.</p>
      {_error(error)}"""
    pie = ('<a class="boton boton-secundario" href="/b/sedes">Cancelar</a>'
           '<button class="boton boton-primario" type="submit">Agregar sede</button>')
    return cajon("Agregar sede", cuerpo, pie, "/b/sedes", accion="/b/sedes/nueva")


# ══════════════════════════════════════════════════════════════════════
#  6.2.9 USUARIOS
# ══════════════════════════════════════════════════════════════════════

TONO_ROL = {m.DUENO: "rol-dueno", m.ADMIN: "rol-admin", m.RECEPCION: "rol-recepcion",
            m.BARBERO: "rol-barbero"}


def usuarios(d: dict, sede: int | None) -> str:
    filas = []
    for u in d["filas"]:
        if u["es_yo"]:
            acceso, botones = '<span class="tenue">Tú</span>', '<span class="tenue">Tú</span>'
        else:
            acceso = f"""
              <form method="post" action="/b/usuarios/{u["id"]}/acceso">
                <input type="hidden" name="activo" value="{"0" if u["activo"] else "1"}">
                <button class="interruptor" type="submit" role="switch"
                        aria-checked="{"true" if u["activo"] else "false"}"
                        aria-label="Acceso de {e(u["nombre"])}"></button></form>"""
            botones = (f'<a class="boton boton-secundario boton-fila" href="{e(_q("/b/usuarios", sede=sede, editar=u["id"]))}">Editar</a>'
                       f'<a class="boton boton-destructivo boton-fila" href="{e(_q("/b/usuarios", sede=sede, quitar=u["id"]))}">Quitar</a>')
        filas.append(f"""
          <div class="tabla-fila usuarios-fila{' apagada' if not u['activo'] else ''}">
            <div class="celda-persona"><span class="avatar">{e(u["iniciales"])}</span>
              <span><span class="celda-fuerte">{e(u["nombre"])}</span>
              <span class="celda-nota">@{e(u["usuario"])}</span></span></div>
            <div data-rotulo="Rol"><span class="chip {TONO_ROL[u["rol"]]}">{e(u["rol_nombre"])}</span></div>
            <div data-rotulo="Sedes">{e(u["sedes"])}</div>
            <div data-rotulo="Contacto" class="celda-corta">{e(u["contacto"]) or '<span class="tenue">—</span>'}</div>
            <div data-rotulo="Último ingreso">{e(u["ultimo"])}</div>
            <div data-rotulo="Acceso">{acceso}</div>
            <div class="celda-accion">{botones}</div>
          </div>""")
    return f"""
      <div class="estadisticas">
        {_estadistica("Usuarios con acceso", str(d["con_acceso"]))}
        {_estadistica("Barberos de tu plan", f"{d['barberos']} de {d['cupo_barberos']}")}
        {_estadistica("Desactivados", str(d["desactivados"]))}
      </div>
      <section class="tarjeta tabla-tarjeta">
        <div class="tabla-cabeza usuarios-fila"><span>Persona</span><span>Rol</span><span>Sedes</span>
          <span>Contacto</span><span>Último ingreso</span><span>Acceso</span><span></span></div>
        {"".join(filas)}
      </section>"""


def cajon_usuario(persona: permisos.Persona, u: dict | None, cerrar: str, temporal: str = "",
                  error: str = "", valores: dict | None = None, restablecida: str = "") -> str:
    """Agregar (u=None) o editar. `valores` son los que se mandaron si hubo error."""
    v = valores or {}
    nombre = v.get("nombre", u["nombre"] if u else "")
    usuario = v.get("usuario", u["usuario"] if u else "")
    contacto = v.get("contacto", (u["correo"] or u["telefono"]) if u else "")
    rol = v.get("rol", u["rol"] if u else m.BARBERO)
    sedes_sel = [int(x) for x in v.get("sedes", u["sedes_ids"] if u else [])]

    roles = "".join(f"""
        <label class="opcion-rol"><input type="radio" name="rol" value="{r}"{" checked" if rol == r else ""}>
          <span><strong>{e(permisos.ROLES[r])}</strong><span class="tenue">{e(permisos.DESCRIPCION_ROL[r])}</span></span></label>"""
                    for r in m.ROLES)
    sedes = "".join(
        f'<label class="chip-radio"><input type="checkbox" name="sedes" value="{i}"'
        f'{" checked" if i in sedes_sel or rol == m.DUENO else ""}><span>{e(n)}</span></label>'
        for i, n in persona.sedes)

    if u is None:
        prefijo = temporal.split("-")[0] if temporal else "Clave"
        clave = f"""
        <div class="clave-temporal">
          <span class="campo-etiqueta">Contraseña temporal</span>
          <span class="clave-temporal-valor" data-temporal-texto>{e(temporal)}</span>
          <input type="hidden" name="temporal" value="{e(temporal)}" data-temporal>
          <button class="enlace" type="button" data-generar-temporal="{e(prefijo)}">Generar otra</button>
          <span class="tenue">Se la pedimos cambiar la primera vez que entre.</span>
        </div>"""
        accion, titulo, boton = "/b/usuarios", "Agregar usuario", "Guardar usuario"
    else:
        aviso = (f'<p class="caja-ok">Contraseña temporal: <strong>{e(restablecida)}</strong>. '
                 f'Compártela; se la pedimos cambiar al entrar.</p>' if restablecida else "")
        clave = f"""
        <div class="clave-temporal">
          {aviso}
          <button class="boton boton-secundario" type="submit" formaction="/b/usuarios/{u["id"]}/restablecer">Restablecer contraseña</button>
        </div>"""
        accion, titulo, boton = f"/b/usuarios/{u['id']}", "Editar usuario", "Guardar usuario"

    cuerpo = f"""
      <label class="campo"><span class="campo-etiqueta">Nombre completo</span>
        <input class="entrada-texto" name="nombre" value="{e(nombre)}" maxlength="100"
               {"data-autocompletar-usuario" if u is None else ""} autofocus></label>
      <label class="campo"><span class="campo-etiqueta">Usuario para entrar</span>
        <input class="entrada-texto" name="usuario" value="{e(usuario)}" maxlength="40"
               autocapitalize="none" autocorrect="off" spellcheck="false" pattern="[a-z0-9._]+"
               data-usuario></label>
      <label class="campo"><span class="campo-etiqueta">Correo o celular</span>
        <input class="entrada-texto" name="contacto" value="{e(contacto)}" placeholder="Para recuperar la clave"></label>
      <fieldset class="grupo"><legend class="campo-etiqueta">Rol</legend>{roles}</fieldset>
      <fieldset class="grupo"><legend class="campo-etiqueta">Sedes donde trabaja</legend>
        <div class="chips">{sedes}</div></fieldset>
      {clave}
      {_error(error)}"""
    pie = (f'<a class="boton boton-secundario" href="{e(cerrar)}">Cancelar</a>'
           f'<button class="boton boton-primario" type="submit">{boton}</button>')
    return cajon(titulo, cuerpo, pie, cerrar, accion=accion)


def dialogo_quitar(u: dict, cerrar: str) -> str:
    return dialogo(f"¿Quitar a {u['nombre']}?",
                   "Ya no podrá entrar al panel. Sus servicios, cajas y pagos se quedan en el "
                   "historial. Si solo quieres bloquearlo por un tiempo, apaga su acceso.",
                   f"/b/usuarios/{u['id']}/quitar", "Quitar usuario", cerrar)


# ══════════════════════════════════════════════════════════════════════
#  6.4 EL BARBERO
# ══════════════════════════════════════════════════════════════════════

def barbero_dia(hechos: list[dict], citas: str = "") -> str:
    filas = "".join(f"""
        <li class="yo-fila{' anulada' if h["anulada"] else ''}">
          <span class="yo-hora">{e(formato.hora(h["inicio"], con_ampm=False))}</span>
          <div class="yo-fila-texto">
            <p class="yo-fila-cliente">{e(h["cliente"])}</p>
            <p class="yo-tenue">{e(h["servicios"])}, {e(h["metodo"].lower())}</p>
            {f'<p class="yo-anulado">Anulado: {e(h["motivo"])}</p>' if h["anulada"] else ""}
          </div>
          <span class="yo-suyo">+{e(P(h["suyo"]))}</span>
          {'' if h["anulada"] else f'<a class="yo-anular" href="/yo/dia?anular={h["id"]}">Anular</a>'}
        </li>""" for h in hechos)
    ya = (f'<ul class="yo-lista">{filas}</ul>' if hechos
          else '<p class="yo-tenue">Todavía nada hoy.</p>')
    citas = citas or ('<div class="yo-vacio">No tienes más citas hoy. Si llega alguien, '
                      'regístralo abajo.</div>')
    return f"""
      {citas}
      <section class="yo-bloque">
        <h2>Ya hiciste</h2>
        {ya}
      </section>"""


def hoja(titulo: str, subtitulo: str, cuerpo: str, cerrar: str) -> str:
    return f"""
<a class="velo velo-oscuro" href="{e(cerrar)}" aria-label="Cerrar" data-cerrar></a>
<section class="hoja" role="dialog" aria-modal="true" aria-labelledby="hoja-titulo"
         data-cerrar-en="{e(cerrar)}">
  <h2 id="hoja-titulo" class="hoja-titulo">{e(titulo)}</h2>
  <p class="hoja-sub">{e(subtitulo)}</p>
  {cuerpo}
</section>"""


PROPINAS = ((0, "Nada"), (5000, "5 mil"), (10000, "10 mil"), (20000, "20 mil"))


def hoja_registrar(sedes: tuple, sede_id: int, catalogo: list[dict], porcentaje: int,
                   error: str = "", valores: dict | None = None, cita: dict | None = None) -> str:
    """
    "Cliente sin cita", o "Cobrar a {nombre}" si viene de una cita agendada
    (`cita`): entonces trae marcado lo que reservó, no pregunta la sede ni
    el cliente, y cierra ESA cita en vez de crear otra visita.
    """
    v = valores or {}
    elegidos = {int(x) for x in v.get("servicios", [])}
    if cita and not elegidos and cita.get("servicio_id"):
        elegidos = {cita["servicio_id"]}
    selector_sede = ""
    if len(sedes) > 1 and not cita:
        selector_sede = '<div class="hoja-grupo"><p class="hoja-rotulo">¿En qué sede?</p><div class="chips">' + "".join(
            f'<a class="chip-sede{" activo" if i == sede_id else ""}" href="/yo/dia?registrar=1&amp;sede={i}">{e(n)}</a>'
            for i, n in sedes) + "</div></div>"
    servicios = "".join(f"""
          <label class="opcion opcion-servicio">
            <input type="checkbox" name="servicios" value="{sv["id"]}" data-precio="{int(sv["precio"])}"
                   {"checked" if sv["id"] in elegidos else ""}>
            <span class="opcion-nombre">{e(sv["nombre"])}</span>
            <span class="opcion-precio">{e(P(sv["precio"]))}</span>
          </label>""" for sv in catalogo)
    metodo = v.get("metodo", "")
    metodos = "".join(
        f'<label class="opcion opcion-chica"><input type="radio" name="metodo" value="{k}"'
        f'{" checked" if metodo == k else ""}><span>{e("Transfer." if k == "transferencia" else t)}</span></label>'
        for k, t in METODOS_COBRO.items())
    propina = str(v.get("propina", "0"))
    propinas = "".join(
        f'<label class="opcion opcion-chica"><input type="radio" name="propina" value="{val}"'
        f'{" checked" if str(val) == propina else ""}><span>{e(t)}</span></label>'
        for val, t in PROPINAS)
    if cita:
        campo_cliente = f'<input type="hidden" name="cita_id" value="{cita["id"]}">'
    else:
        campo_cliente = f"""<label class="campo">
      <span class="campo-etiqueta">Celular o nombre del cliente (opcional)</span>
      <input class="entrada-texto" name="cliente" value="{e(v.get("cliente", ""))}" autocomplete="off">
    </label>"""
    cuerpo = f"""
  <form method="post" action="/yo/servicios" class="hoja-form" novalidate data-cobro data-porcentaje="{porcentaje}">
    <input type="hidden" name="sede_id" value="{sede_id}">
    {selector_sede}
    <div class="hoja-grupo">
      <p class="hoja-rotulo">¿Qué le hiciste? Puedes marcar varios</p>
      <div class="opciones-servicios">{servicios}</div>
    </div>
    <div class="hoja-grupo">
      <p class="hoja-rotulo">¿Cómo pagó?</p>
      <div class="opciones-cuatro">{metodos}</div>
      <label class="campo dividido" data-dividido {"" if metodo == "dividido" else "hidden"}>
        <span class="campo-etiqueta">Efectivo</span>
        <input class="entrada-texto" name="efectivo" inputmode="numeric" data-dinero
               value="{e(v.get("efectivo", ""))}" placeholder="$0" autocomplete="off">
        <span class="yo-tenue" data-resto></span>
      </label>
    </div>
    <div class="hoja-grupo">
      <p class="hoja-rotulo">Propina</p>
      <div class="opciones-cuatro">{propinas}</div>
    </div>
    {campo_cliente}
    <div class="hoja-pie">
      <span>Cobra <strong data-total>{e(P(0))}</strong></span>
      <span>Para ti <strong data-suyo>{e(P(0))}</strong></span>
    </div>
    {_error(error)}
    <button class="boton boton-claro boton-grande hoja-boton" type="submit" data-boton-cobro>Registrar</button>
  </form>"""
    if cita:
        return hoja(f"Cobrar a {cita['cliente']}", "Revisa lo que le hiciste y cómo pagó",
                    cuerpo, "/yo/dia")
    return hoja("Cliente sin cita", "Para quien llega sin reservar", cuerpo, "/yo/dia")


def hoja_anular(h: dict, error: str = "") -> str:
    motivos = "".join(
        f'<label class="opcion opcion-motivo"><input type="radio" name="motivo" value="{e(mo)}">'
        f'<span>{e(mo)}</span></label>' for mo in MOTIVOS_ANULACION)
    cuerpo = f"""
  <form method="post" action="/yo/servicios/{h["id"]}/anular" class="hoja-form" novalidate data-anular>
    <div class="opciones-motivos">{motivos}</div>
    {_error(error)}
    <div class="hoja-botones">
      <a class="boton boton-fantasma" href="/yo/dia">Volver</a>
      <button class="boton boton-anular" type="submit" data-boton-anular>Anular</button>
    </div>
  </form>"""
    sub = (f"{h['servicios']} de {h['cliente']}, {P(h['total'])}. No se borra: queda anulado "
           f"con el motivo y el dueño lo ve en Actividad.")
    return hoja("Anular servicio", sub, cuerpo, "/yo/dia")


def barbero_ganancias(g: dict, hoy: date) -> str:
    maximo = max((v for _, v in g["por_dia"]), default=0)
    barras = "".join(
        f'<span class="yo-dia{" hoy" if d == hoy else ""}" title="{e(formato.fecha_corta(d))}: {e(P(v))}" '
        f'style="height:{max(int(v * 100 / maximo) if maximo else 0, 3)}%"></span>'
        for d, v in g["por_dia"])
    meta = ""
    if g["meta"]:
        pct = min(100, int(g["bruto"] * 100 / g["meta"])) if g["meta"] else 0
        falta = max(g["meta"] - g["bruto"], 0)
        texto = (f"Te faltan {P(falta)} para llegar a {P(g['meta'])}" if falta
                 else f"Llegaste a tu meta de {P(g['meta'])}")
        meta = f"""
      <section class="yo-bloque">
        <div class="yo-meta-cabeza"><h2>Meta de la quincena</h2><span>{pct}%</span></div>
        <div class="yo-meta"><span style="width:{pct}%"></span></div>
        <p class="yo-tenue">{e(texto)}</p>
      </section>"""
    if g["esquema"] == m.ALQUILER_SILLA:
        rotulo_servicios = "Lo que facturaste (todo tuyo)"
    elif g["esquema"] == m.FIJO_MAS_COMISION:
        rotulo_servicios = f"Tu fijo y tu {g['porcentaje']}% de los servicios"
    else:
        rotulo_servicios = f"Tu {g['porcentaje']}% de los servicios"
    descuento = ""
    if g["adelantos"]:
        fecha = f" del {formato.fecha_corta(g['fecha_adelanto'])}" if g["fecha_adelanto"] else ""
        descuento += f'<div class="fila-dato"><span>Adelanto{e(fecha)}</span><span class="yo-menos">{formato.MENOS}{e(P(g["adelantos"]))}</span></div>'
    if g["alquiler"]:
        descuento += f'<div class="fila-dato"><span>Alquiler de la silla</span><span class="yo-menos">{formato.MENOS}{e(P(g["alquiler"]))}</span></div>'
    return f"""
      <section class="yo-bloque">
        <p class="yo-tenue">{e(formato.quincena(g["desde"]))}</p>
        <p class="yo-cifra">{e(P(g["total"]))}</p>
        <p class="yo-tenue">Lo que te pagan el {g["hasta"].day}, ya descontado{"s los adelantos" if g["adelantos"] else " todo"}.</p>
      </section>
      {meta}
      <section class="yo-bloque">
        <h2>Día por día</h2>
        <div class="yo-dias">{barras}</div>
      </section>
      <section class="yo-bloque yo-desglose">
        <div class="fila-dato"><span>{e(rotulo_servicios)}</span><span>{e(P(g["comisiones"]))}</span></div>
        <div class="fila-dato"><span>Propinas (son todas tuyas)</span><span>{e(P(g["propinas"]))}</span></div>
        <div class="fila-dato"><span>Productos vendidos</span><span>{e(P(g["productos"]))}</span></div>
        {descuento}
      </section>"""
