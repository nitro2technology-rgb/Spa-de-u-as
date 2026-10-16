"""
LAS PANTALLAS DE LA AGENDA (Fase 2)
====================================
6.2.2 la Agenda del dueño, administrador y recepción; el detalle de una
cita; "Nueva cita" y "Bloquear horario"; el horario de una sede; y lo que
la agenda le añade a "Mi día" del barbero (6.4).

Mismo criterio que `pantallas.py`: los formularios funcionan sin
JavaScript, y todo lo que escribe alguien pasa por `e()`.
"""

from datetime import date, timedelta

from app.barberia import formato
from app.barberia import modelos as m
from app.barberia.paginas import e
from app.barberia.pantallas import _error, cajon

PX_HORA = 52          # alto de una hora en la agenda (6.2.2)

# Estilo de cada bloque según su estado (la tabla de 6.2.2).
CLASE_ESTADO = {
    m.COMPLETADA: "cita-completada", m.EN_CURSO: "cita-en-curso",
    m.CONFIRMADA: "cita-confirmada", m.PENDIENTE: "cita-pendiente",
    m.NO_ASISTIO: "cita-no-vino", m.ANULADA: "cita-no-vino",
}
ORIGEN = {m.WHATSAPP: "WhatsApp", m.WALK_IN: "Sin cita", m.PANEL: "Local", m.WEB: "Web"}


def _q(base: str, **params) -> str:
    partes = [f"{k}={v}" for k, v in params.items() if v not in (None, "")]
    return base + ("?" + "&".join(partes) if partes else "")


def _hora_decimal(momento) -> float:
    local = formato.a_local(momento)
    return local.hour + local.minute / 60


# ══════════════════════════════════════════════════════════════════════
#  6.2.2 LA AGENDA
# ══════════════════════════════════════════════════════════════════════

def agenda(d: dict, sede_id: int, sede_nombre: str, varias_sedes: bool, sin_filtro: bool,
           hoy: date) -> str:
    dia = d["dia"]
    alto = (d["hasta"] - d["desde"]) * PX_HORA
    horas = "".join(
        f'<span class="agenda-hora" style="top:{(h - d["desde"]) * PX_HORA}px">'
        f'{h % 12 or 12}{"" if h % 12 else ""}</span>'
        for h in range(d["desde"], d["hasta"]))
    lineas = "".join(f'<span class="agenda-linea" style="top:{(h - d["desde"]) * PX_HORA}px"></span>'
                     for h in range(d["desde"], d["hasta"] + 1))

    ahora_px = None
    if dia == hoy:
        ahora = _hora_decimal(m.ahora())
        if d["desde"] <= ahora <= d["hasta"]:
            ahora_px = (ahora - d["desde"]) * PX_HORA

    columnas = []
    for b in d["barberos"]:
        bloques = []
        for c in [c for c in d["citas"] if c["barbero_id"] == b["id"]]:
            top = (_hora_decimal(c["inicio"]) - d["desde"]) * PX_HORA + 2
            alto_b = max(c["minutos"] / 60 * PX_HORA - 4, 22)
            clase = "cita-sin-cobro" if c["sin_cobro"] else CLASE_ESTADO.get(c["estado"], "")
            servicios = c["servicios"] + (" (anulado)" if c["estado"] == m.ANULADA else "")
            origen = '<span class="bloque-origen">WhatsApp</span>' if c["origen"] == m.WHATSAPP else ""
            bloques.append(
                f'<a class="bloque {clase}" style="top:{top:.0f}px;height:{alto_b:.0f}px" '
                f'href="{e(_q("/b/agenda", sede=sede_id, fecha=dia.isoformat(), cita=c["id"]))}" '
                f'title="{e(c["estado_nombre"])}">'
                f'<span class="bloque-linea"><strong>{e(formato.hora(c["inicio"], False))} '
                f'{e(c["cliente"])}</strong>{origen}</span>'
                f'<span class="bloque-servicio">{e(servicios)}</span></a>')
        for bl in [x for x in d["bloqueos"] if x["personal_id"] in (None, b["id"])]:
            top = (_hora_decimal(bl["inicio"]) - d["desde"]) * PX_HORA + 2
            alto_b = max((bl["fin"] - bl["inicio"]).total_seconds() / 3600 * PX_HORA - 4, 22)
            bloques.append(
                f'<a class="bloque cita-bloqueo" style="top:{top:.0f}px;height:{alto_b:.0f}px" '
                f'href="{e(_q("/b/agenda", sede=sede_id, fecha=dia.isoformat(), bloqueo=bl["id"]))}">'
                f'<span class="bloque-linea"><strong>{e(bl["motivo"])}</strong></span></a>')
        ahora_linea = (f'<span class="agenda-ahora" style="top:{ahora_px:.0f}px"></span>'
                       if ahora_px is not None else "")
        columnas.append(f"""
          <div class="agenda-col">
            <header class="agenda-col-cabeza"><span class="avatar avatar-30">{e(b["iniciales"])}</span>
              <span><span class="celda-fuerte">{e(b["nombre"])}</span>
              <span class="celda-nota">{e(b["sub"])}</span></span></header>
            <div class="agenda-cuerpo" style="height:{alto}px">{lineas}{"".join(bloques)}{ahora_linea}</div>
          </div>""")

    leyenda = "".join(f'<span class="leyenda-cita"><span class="cuadrito {c}"></span>{t}</span>'
                      for c, t in (("cita-completada", "Completada"), ("cita-en-curso", "En curso"),
                                   ("cita-confirmada", "Confirmada"), ("cita-pendiente", "Sin confirmar"),
                                   ("cita-no-vino", "No vino"), ("cita-sin-cobro", "Sin cobro")))
    nota = (f"Mostrando {sede_nombre}. Elige otra sede arriba." if sin_filtro and varias_sedes
            else ("La línea roja es la hora actual" if dia == hoy else ""))
    anterior, siguiente = dia - timedelta(days=1), dia + timedelta(days=1)
    navegar = f"""
        <nav class="agenda-nav" aria-label="Día">
          <a class="boton boton-secundario boton-fila" href="{e(_q("/b/agenda", sede=sede_id, fecha=anterior.isoformat()))}" aria-label="Día anterior">‹</a>
          <a class="boton boton-secundario boton-fila" href="{e(_q("/b/agenda", sede=sede_id))}">Hoy</a>
          <a class="boton boton-secundario boton-fila" href="{e(_q("/b/agenda", sede=sede_id, fecha=siguiente.isoformat()))}" aria-label="Día siguiente">›</a>
          <span class="agenda-fecha">{e(formato.con_mayuscula(formato.fecha_larga(dia)))}</span>
        </nav>"""
    acciones = f"""
        <div class="agenda-acciones">
          <a class="boton boton-secundario" href="{e(_q("/b/agenda", sede=sede_id, fecha=dia.isoformat(), bloquear=1))}">Bloquear horario</a>
          <a class="boton boton-primario" href="{e(_q("/b/agenda", sede=sede_id, fecha=dia.isoformat(), nueva=1))}">Nueva cita</a>
        </div>"""
    cuerpo = ("".join(columnas) if d["barberos"] else
              '<p class="tenue tabla-vacia">Esta sede no tiene barberos con acceso.</p>')
    cerrada = ('<p class="tenue agenda-cerrada">La sede no atiende este día.</p>'
               if not d["horario"] else "")
    return f"""
      <div class="agenda-barra">{navegar}{acciones}</div>
      <div class="agenda-leyenda">{leyenda}<span class="tenue">{e(nota)}</span></div>
      {cerrada}
      <section class="tarjeta agenda">
        <div class="agenda-horas"><div class="agenda-col-cabeza"></div>
          <div class="agenda-cuerpo" style="height:{alto}px">{horas}</div></div>
        <div class="agenda-cols">{cuerpo}</div>
      </section>"""


def cajon_cita(c: dict, cerrar: str, puede_gestionar: bool, error: str = "") -> str:
    telefono = c["telefono"]
    if telefono and len(telefono) == 10:
        telefono = f"{telefono[:3]} {telefono[3:6]} {telefono[6:]}"
    cuando = (f'{formato.con_mayuscula(formato.fecha_larga(formato.a_local(c["inicio"]).date()))}, '
              f'{formato.hora(c["inicio"])} a {formato.hora(c["fin"])}')
    acciones = ""
    if puede_gestionar and c["estado"] in (m.PENDIENTE, m.CONFIRMADA, m.EN_CURSO):
        confirmar = (f'<form method="post" action="/b/agenda/cita/{c["id"]}/estado">'
                     f'<input type="hidden" name="estado" value="{m.CONFIRMADA}">'
                     f'<button class="boton boton-primario" type="submit">Confirmar</button></form>'
                     if c["estado"] == m.PENDIENTE else "")
        acciones = f"""
        <div class="consola-acciones">
          {confirmar}
          <form method="post" action="/b/agenda/cita/{c["id"]}/estado">
            <input type="hidden" name="estado" value="{m.NO_ASISTIO}">
            <button class="boton boton-secundario" type="submit">No vino</button></form>
        </div>
        <form class="consola-bloque" method="post" action="/b/agenda/cita/{c["id"]}/cancelar">
          <h3>Cancelar la cita</h3>
          <label class="campo"><span class="campo-etiqueta">Motivo (opcional)</span>
            <input class="entrada-texto" name="motivo" maxlength="200" placeholder="Ej. El cliente llamó a cancelar"></label>
          <button class="boton boton-destructivo" type="submit">Cancelar cita</button>
        </form>"""
    nota = ""
    if c["cliente_id"]:
        nota = f"""
        <form class="consola-bloque" method="post" action="/b/clientes/{c["cliente_id"]}/nota">
          <input type="hidden" name="volver" value="{e(cerrar)}">
          <h3>Ficha del cliente</h3>
          <label class="campo"><span class="campo-etiqueta">Nota (la ve el barbero al atenderlo)</span>
            <textarea class="entrada-texto" name="nota" rows="3" maxlength="500"
              placeholder="Ej. Barba en punta, máquina 1 a los lados">{e(c["nota"])}</textarea></label>
          <button class="boton boton-secundario" type="submit">Guardar nota</button>
        </form>"""
    cuerpo = f"""
      <p><span class="chip {CLASE_ESTADO.get(c["estado"], "chip-pausado")} chip-cita">{e(c["estado_nombre"])}</span>
         <span class="tenue">{e(ORIGEN.get(c["origen"], ""))}</span></p>
      <div class="fila-dato"><span>Cuándo</span><span>{e(cuando)}</span></div>
      <div class="fila-dato"><span>Servicio</span><span>{e(c["servicios"] or "—")}</span></div>
      <div class="fila-dato"><span>Celular</span><span>{e(telefono or "—")}</span></div>
      {'<p class="caja-error">Esta cita ya pasó y no tiene cobro. Si vino, que el barbero la cobre; si no, márcala como "no vino".</p>' if c["sin_cobro"] else ""}
      {_error(error)}
      {acciones}
      {nota}"""
    return cajon(c["cliente"], cuerpo, f'<a class="boton boton-secundario" href="{e(cerrar)}">Cerrar</a><span></span>',
                 cerrar)


def cajon_nueva_cita(sede_id: int, dia: date, barberos: list, servicios: list, barbero: str,
                     servicio: str, huecos: dict, cerrar: str, error: str = "",
                     cliente: str = "") -> str:
    """
    Dos formularios en el mismo panel: arriba se elige barbero, servicio y
    día (GET: vuelve a pintar las horas libres); abajo, la hora y el
    cliente (POST: reserva). Con JavaScript, el de arriba se envía solo al
    cambiar algo.
    """
    op_barbero = '<option value="">El que esté libre</option>' + "".join(
        f'<option value="{i}"{" selected" if str(i) == barbero else ""}>{e(n)}</option>'
        for i, n in barberos)
    op_servicio = "".join(
        f'<option value="{sv["id"]}"{" selected" if str(sv["id"]) == servicio else ""}>'
        f'{e(sv["nombre"])} · {e(formato.pesos(sv["precio"]))} · {sv["minutos"]} min</option>'
        for sv in servicios)
    horas = "".join(f'<option value="{t.isoformat()}">{e(formato.hora(t))}'
                    f'{" · " + e(n) if not barbero else ""}</option>'
                    for t, n in huecos.items())
    reservar = (f"""
      <form method="post" action="/b/agenda/cita" class="consola-bloque" novalidate>
        <input type="hidden" name="sede_id" value="{sede_id}">
        <input type="hidden" name="barbero" value="{e(barbero)}">
        <input type="hidden" name="servicio" value="{e(servicio)}">
        <label class="campo"><span class="campo-etiqueta">Hora</span>
          <select class="entrada-texto" name="inicio">{horas}</select></label>
        <label class="campo"><span class="campo-etiqueta">Celular o nombre del cliente</span>
          <input class="entrada-texto" name="cliente" value="{e(cliente)}" autocomplete="off"></label>
        {_error(error)}
        <button class="boton boton-primario boton-grande" type="submit">Agendar cita</button>
      </form>""" if huecos else
                f'<p class="tenue">No hay horas libres ese día con esa elección.</p>{_error(error)}')
    cuerpo = f"""
      <form method="get" action="/b/agenda" class="formulario-panel" data-auto-enviar>
        <input type="hidden" name="sede" value="{sede_id}">
        <input type="hidden" name="nueva" value="1">
        <label class="campo"><span class="campo-etiqueta">Barbero</span>
          <select class="entrada-texto" name="barbero">{op_barbero}</select></label>
        <label class="campo"><span class="campo-etiqueta">Servicio</span>
          <select class="entrada-texto" name="servicio">{op_servicio}</select></label>
        <label class="campo"><span class="campo-etiqueta">Día</span>
          <input class="entrada-texto" type="date" name="fecha" value="{dia.isoformat()}"></label>
        <button class="boton boton-secundario" type="submit" data-solo-sin-js>Ver horas libres</button>
      </form>
      {reservar}"""
    return cajon("Nueva cita", cuerpo, f'<a class="boton boton-secundario" href="{e(cerrar)}">Cancelar</a><span></span>',
                 cerrar)


def cajon_bloquear(sede_id: int, dia: date, barberos: list, cerrar: str, error: str = "",
                   v: dict | None = None) -> str:
    v = v or {}
    opciones = '<option value="">Toda la sede</option>' + "".join(
        f'<option value="{i}"{" selected" if str(i) == v.get("personal_id") else ""}>{e(n)}</option>'
        for i, n in barberos)
    cuerpo = f"""
      <label class="campo"><span class="campo-etiqueta">¿A quién?</span>
        <select class="entrada-texto" name="personal_id">{opciones}</select></label>
      <label class="campo"><span class="campo-etiqueta">Día</span>
        <input class="entrada-texto" type="date" name="fecha" value="{e(v.get("fecha", dia.isoformat()))}"></label>
      <div class="dos-columnas">
        <label class="campo"><span class="campo-etiqueta">Desde</span>
          <input class="entrada-texto" type="time" name="desde" value="{e(v.get("desde", "12:00"))}"></label>
        <label class="campo"><span class="campo-etiqueta">Hasta</span>
          <input class="entrada-texto" type="time" name="hasta" value="{e(v.get("hasta", "13:00"))}"></label>
      </div>
      <label class="campo"><span class="campo-etiqueta">Motivo</span>
        <input class="entrada-texto" name="motivo" value="{e(v.get("motivo", "Almuerzo"))}" maxlength="100"></label>
      <p class="tenue">Mientras esté bloqueado, ni el bot ni el panel agendan en ese rato.</p>
      <input type="hidden" name="sede_id" value="{sede_id}">
      {_error(error)}"""
    pie = (f'<a class="boton boton-secundario" href="{e(cerrar)}">Cancelar</a>'
           '<button class="boton boton-primario" type="submit">Bloquear</button>')
    return cajon("Bloquear horario", cuerpo, pie, cerrar, accion="/b/agenda/bloqueo")


def cajon_bloqueo(bl: dict, cerrar: str) -> str:
    cuerpo = f"""
      <div class="fila-dato"><span>Motivo</span><span>{e(bl["motivo"])}</span></div>
      <div class="fila-dato"><span>Desde</span><span>{e(formato.hora(bl["inicio"]))}</span></div>
      <div class="fila-dato"><span>Hasta</span><span>{e(formato.hora(bl["fin"]))}</span></div>
      <form method="post" action="/b/agenda/bloqueo/{bl["id"]}/quitar">
        <button class="boton boton-destructivo" type="submit">Quitar bloqueo</button></form>"""
    return cajon("Horario bloqueado", cuerpo,
                 f'<a class="boton boton-secundario" href="{e(cerrar)}">Cerrar</a><span></span>', cerrar)


# ══════════════════════════════════════════════════════════════════════
#  EL HORARIO DE UNA SEDE
# ══════════════════════════════════════════════════════════════════════

def cajon_horario(sede: dict, horario: dict, error: str = "") -> str:
    filas = []
    for dia in range(7):
        tramos = horario.get(dia) or []
        abierto = bool(tramos)
        desde = tramos[0][0].strftime("%H:%M") if tramos else "08:00"
        hasta = tramos[-1][1].strftime("%H:%M") if tramos else "20:00"
        filas.append(f"""
        <div class="horario-fila">
          <label class="casilla"><input type="checkbox" name="abierto_{dia}" value="1"{" checked" if abierto else ""}>
            <span class="casilla-caja" aria-hidden="true"></span>{e(formato.con_mayuscula(formato.DIAS[dia]))}</label>
          <input class="entrada-texto entrada-chica" type="time" name="desde_{dia}" value="{desde}" aria-label="Abre el {formato.DIAS[dia]}">
          <input class="entrada-texto entrada-chica" type="time" name="hasta_{dia}" value="{hasta}" aria-label="Cierra el {formato.DIAS[dia]}">
        </div>""")
    cuerpo = f"""
      <p class="tenue">Los barberos de la sede trabajan este horario. El bot solo ofrece horas dentro de él.</p>
      <div class="horario">{"".join(filas)}</div>
      {_error(error)}"""
    pie = ('<a class="boton boton-secundario" href="/b/sedes">Cancelar</a>'
           '<button class="boton boton-primario" type="submit">Guardar horario</button>')
    return cajon(f"Horario de {sede['nombre']}", cuerpo, pie, "/b/sedes",
                 accion=f"/b/sedes/{sede['id']}/horario")


# ══════════════════════════════════════════════════════════════════════
#  "MI DÍA" CON CITAS (6.4)
# ══════════════════════════════════════════════════════════════════════

def barbero_citas(dia: dict) -> str:
    """La tarjeta de la siguiente cita y la lista de "Después"."""
    actual, resto = dia["actual"], dia["resto"]
    if actual is None:
        return '<div class="yo-vacio">No tienes más citas hoy. Si llega alguien, regístralo abajo.</div>'
    rotulo = "Atendiendo ahora" if actual["estado"] == m.EN_CURSO else "Tu siguiente cita"
    origen = "Agendó por WhatsApp" if actual["origen"] == m.WHATSAPP else "Agendado en el local"
    nota = f'<p class="yo-nota">{e(actual["nota"])}</p>' if actual["nota"] else ""
    if actual["estado"] == m.EN_CURSO:
        principal = (f'<a class="boton boton-claro yo-cita-boton" '
                     f'href="/yo/dia?registrar=1&amp;cita={actual["id"]}">Cobrar</a>')
    else:
        principal = (f'<form method="post" action="/yo/citas/{actual["id"]}/empezar">'
                     f'<button class="boton boton-claro yo-cita-boton" type="submit">Empezar</button></form>')
    tarjeta = f"""
      <section class="yo-cita">
        <div class="yo-cita-cabeza"><span class="yo-cita-rotulo">{rotulo}</span>
          <span class="yo-tenue">{origen}</span></div>
        <p class="yo-cita-hora">{e(formato.hora(actual["inicio"]))}</p>
        <p class="yo-cita-cliente">{e(actual["cliente"])}</p>
        <p class="yo-tenue">{e(actual["servicios"])}, {actual["minutos"]} min</p>
        {nota}
        <div class="yo-cita-botones">
          <form method="post" action="/yo/citas/{actual["id"]}/no-vino">
            <button class="boton boton-fantasma yo-cita-boton" type="submit">No vino</button></form>
          {principal}
        </div>
      </section>"""
    despues = ""
    if resto:
        filas = "".join(f"""
          <li class="yo-fila yo-despues">
            <span class="yo-hora">{e(formato.hora(c["inicio"], False))}</span>
            <div class="yo-fila-texto"><p class="yo-fila-cliente">{e(c["cliente"])}</p>
              <p class="yo-tenue">{e(c["servicios"])}, {c["minutos"]} min</p></div>
            <span class="yo-estado {"ok" if c["estado"] == m.CONFIRMADA else ""}">{e(c["estado_nombre"])}<br>
              <span class="yo-tenue">{"WhatsApp" if c["origen"] == m.WHATSAPP else "Local"}</span></span>
          </li>""" for c in resto)
        despues = f'<section class="yo-bloque"><h2>Después</h2><ul class="yo-lista">{filas}</ul></section>'
    return tarjeta + despues
