"""
LO QUE SE LEE: RESUMEN, ACTIVIDAD Y LAS CIFRAS DE CADA SEDE
============================================================
Solo lectura. Todo sale de los montos CONGELADOS al cobrar
(`barb_cita_servicios`), de los pagos y de los gastos, y nunca de los
precios actuales del catálogo.

    Ingresos      lo facturado en servicios (sin propinas: son del barbero)
    Ganancia neta lo que le queda a la barbería (su parte de cada servicio)
                  menos los gastos
    Margen        ganancia neta / ingresos
    Ticket        ingresos / visitas

La OCUPACIÓN ("horas con cliente en silla") necesita los horarios de cada
barbero, que llegan con la agenda en la Fase 2. Hasta entonces se muestra
"—" y no un número inventado.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func

from app.barberia import formato, permisos
from app.barberia import modelos as m
from app.barberia.operacion import CERO, NOMBRE_METODO, _session, _suma

DIAS_CORTOS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


def _ids(persona: permisos.Persona, sede_id: int | None) -> list[int]:
    return [i for i, _ in persona.sedes if sede_id in (None, i)]


def _citas(s, ids: list[int], desde: date, hasta: date):
    """Las visitas cobradas y no anuladas de esas sedes en [desde, hasta)."""
    ini, fin = formato.rango_utc(desde, hasta)
    return s.query(m.Cita).filter(m.Cita.sede_id.in_(ids), m.Cita.estado == m.COMPLETADA,
                                  m.Cita.inicio >= ini, m.Cita.inicio < fin)


def _ingresos(s, ids, desde, hasta) -> tuple[Decimal, Decimal, int]:
    citas = _citas(s, ids, desde, hasta).subquery()
    ingresos, barberia = (s.query(func.sum(m.CitaServicio.precio),
                                  func.sum(m.CitaServicio.monto_barberia))
                          .filter(m.CitaServicio.cita_id.in_(s.query(citas.c.id))).one())
    visitas = s.query(func.count(citas.c.id)).scalar() or 0
    return _suma(ingresos), _suma(barberia), visitas


def _gastos(s, ids, desde, hasta) -> tuple[Decimal, list]:
    filas = (s.query(m.Gasto.categoria, func.sum(m.Gasto.monto))
             .filter(m.Gasto.sede_id.in_(ids), m.Gasto.fecha >= desde, m.Gasto.fecha < hasta)
             .group_by(m.Gasto.categoria).all())
    por_categoria = sorted(((c or "Otros", _suma(v)) for c, v in filas),
                           key=lambda x: x[1], reverse=True)
    return sum((v for _, v in por_categoria), CERO), por_categoria


def _porcentaje(parte: Decimal, total: Decimal) -> int:
    return int(round(parte * 100 / total)) if total else 0


def resumen(persona: permisos.Persona, sede_id: int | None, periodo: str, hoy: date) -> dict:
    ids = _ids(persona, sede_id)
    desde, hasta = formato.periodo(periodo, hoy)
    antes_desde, antes_hasta = formato.periodo_anterior(periodo, hoy)

    s = _session()
    try:
        ingresos, barberia, visitas = _ingresos(s, ids, desde, hasta)
        gastos, por_categoria = _gastos(s, ids, desde, hasta)
        ingresos_antes, _, _ = _ingresos(s, ids, antes_desde, antes_hasta)
        neta = barberia - gastos

        # ── la gráfica ──
        citas = _citas(s, ids, desde, hasta).all()
        precio_de = dict(s.query(m.CitaServicio.cita_id, func.sum(m.CitaServicio.precio))
                         .filter(m.CitaServicio.cita_id.in_([c.id for c in citas] or [0]))
                         .group_by(m.CitaServicio.cita_id).all())
        if periodo == "hoy":
            etiquetas = [f"{h % 12 or 12}" for h in range(9, 21)]
            barras = [CERO] * 12
            for c in citas:
                h = min(max(formato.a_local(c.inicio).hour, 9), 20)
                barras[h - 9] += _suma(precio_de.get(c.id))
        elif periodo == "semana":
            etiquetas = list(DIAS_CORTOS)
            barras = [CERO] * 7
            for c in citas:
                barras[formato.a_local(c.inicio).weekday()] += _suma(precio_de.get(c.id))
        else:
            semanas = ((hasta - desde).days + 6) // 7
            etiquetas = [f"Sem {i + 1}" for i in range(semanas)]
            barras = [CERO] * semanas
            for c in citas:
                barras[(formato.a_local(c.inicio).day - 1) // 7] += _suma(precio_de.get(c.id))

        mejor = None
        if any(barras):
            i = max(range(len(barras)), key=lambda k: barras[k])
            if periodo == "hoy":
                h = 9 + i
                mejor = f"{h % 12 or 12} a {(h + 1) % 12 or 12} {'a. m.' if h < 11 else 'p. m.'}"
            elif periodo == "semana":
                mejor = formato.DIAS[i]
            else:
                mejor = f"Semana {i + 1}"

        # ── cómo llegan y cómo pagan ──
        origen = dict(s.query(m.Cita.origen, func.count(m.Cita.id))
                      .filter(m.Cita.id.in_([c.id for c in citas] or [0]))
                      .group_by(m.Cita.origen).all())
        llegan = [("Agendan por WhatsApp", origen.get(m.WHATSAPP, 0)),
                  ("Llegan sin cita", origen.get(m.WALK_IN, 0)),
                  ("Agendados en el local", origen.get(m.PANEL, 0) + origen.get(m.WEB, 0))]
        if not persona.con_bot:
            llegan = llegan[1:]

        pagos = dict(s.query(m.Pago.metodo, func.sum(m.Pago.monto))
                     .filter(m.Pago.cita_id.in_([c.id for c in citas] or [0]))
                     .group_by(m.Pago.metodo).all())
        pagan = [(NOMBRE_METODO[k], _suma(pagos.get(k)))
                 for k in (m.TRANSFERENCIA, m.EFECTIVO, m.TARJETA)]

        # ── barberos que más facturan ──
        top = (s.query(m.Cita.barbero_id, func.sum(m.CitaServicio.precio),
                       func.count(func.distinct(m.Cita.id)))
               .join(m.CitaServicio, m.CitaServicio.cita_id == m.Cita.id)
               .filter(m.Cita.id.in_([c.id for c in citas] or [0]))
               .group_by(m.Cita.barbero_id)
               .order_by(func.sum(m.CitaServicio.precio).desc()).limit(5).all())
        nombres = {p.id: p.nombre for p in s.query(m.Personal).all()}
        from app.barberia import agenda
        ranking = [{"nombre": nombres.get(b, ""), "total": _suma(t), "servicios": n,
                    "ocupacion": agenda.ocupacion(ids, desde, hasta, barbero_id=b)}
                   for b, t, n in top]
        ocupacion = agenda.ocupacion(ids, desde, hasta)

        revisar = _para_revisar(s, ids, hoy)
    finally:
        s.close()

    cambio = None
    if ingresos_antes:
        cambio = int(round((ingresos - ingresos_antes) * 100 / ingresos_antes))
    return {
        "desde": desde, "hasta": hasta,
        "ingresos": ingresos, "gastos": gastos, "neta": neta, "visitas": visitas,
        "margen": _porcentaje(neta, ingresos),
        "ticket": (ingresos / visitas) if visitas else CERO,
        "cambio": cambio,
        "gasto_mayor": (por_categoria[0][0], _porcentaje(por_categoria[0][1], gastos))
                       if por_categoria else None,
        "etiquetas": etiquetas, "barras": barras, "mejor": mejor,
        "llegan": llegan, "pagan": pagan, "ranking": ranking, "revisar": revisar,
        "ocupacion": ocupacion,
    }


def _para_revisar(s, ids: list[int], hoy: date) -> list[dict]:
    """
    "Para revisar", de datos reales (6.2.1). Hoy son dos: cajas cerradas con
    diferencia y servicios anulados hoy. Las citas sin cobro (Fase 2, con la
    agenda) y el stock bajo (Fase 3, con el inventario) llegan con sus
    módulos.
    """
    ini, fin = formato.rango_utc(hoy - timedelta(days=6), hoy + timedelta(days=1))
    nombres_sede = {x.id: x.nombre for x in s.query(m.Sede).all()}
    items = []

    caja = (s.query(m.Caja).filter(m.Caja.sede_id.in_(ids), m.Caja.cerrada_en >= ini,
                                   m.Caja.diferencia != 0)
            .order_by(m.Caja.cerrada_en.desc()).first())
    if caja is not None:
        dif = _suma(caja.diferencia)
        que = "faltaron" if dif < 0 else "sobraron"
        items.append({"punto": "rojo" if dif < 0 else "ambar", "ir": "actividad",
                      "texto": f"En {nombres_sede.get(caja.sede_id, '')} {que} "
                               f"{formato.pesos(abs(dif))} al cerrar la caja "
                               f"({formato.cuando(caja.cerrada_en, hoy).lower()})"})

    hoy_ini, hoy_fin = formato.rango_utc(hoy, hoy + timedelta(days=1))
    anulados = (s.query(m.Cita).filter(m.Cita.sede_id.in_(ids), m.Cita.estado == m.ANULADA,
                                       m.Cita.anulada_en >= hoy_ini,
                                       m.Cita.anulada_en < hoy_fin)
                .order_by(m.Cita.anulada_en.desc()).all())
    if anulados:
        n = len(anulados)
        items.append({"punto": "rojo", "ir": "actividad",
                      "texto": f"{formato.plural(n, 'servicio anulado', 'servicios anulados')} "
                               f"hoy. El último: «{anulados[0].motivo_anulacion}»"})
    from app.barberia import agenda
    pendientes = agenda.sin_cobro(ids, hoy)
    if pendientes:
        c = pendientes[0]
        barbero = s.get(m.Personal, c["barbero_id"]).nombre.split(" ")[0]
        extra = f" y {formato.plural(len(pendientes) - 1, 'otra')}" if len(pendientes) > 1 else ""
        items.insert(1, {"punto": "ambar", "ir": "agenda",
                         "texto": f"{c['cliente']} tenía cita con {barbero} "
                                  f"({formato.cuando(c['inicio'], hoy).lower()}) y no hay "
                                  f"cobro registrado{extra}"})
    return items[:4]


# ══════════════════════════════════════════════════════════════════════
#  ACTIVIDAD
# ══════════════════════════════════════════════════════════════════════

FILTROS_ACTIVIDAD = (
    ("todo", "Todo", None),
    ("anulaciones", "Anulaciones", ("ANULACION",)),
    ("caja", "Caja y adelantos", ("CAJA", "ADELANTO")),
    ("cruce", "Citas sin cobro", ("CRUCE",)),
    ("precios", "Precios", ("PRECIO",)),
)

# El color del punto de cada línea (6.2.7).
TIPO_PUNTO = {"ANULACION": "rojo", "CAJA": "violeta", "ADELANTO": "violeta",
              "PAGO": "violeta", "CRUCE": "ambar", "PRECIO": "lila"}


def actividad(persona: permisos.Persona, filtro: str, hoy: date, limite: int = 200) -> list[dict]:
    """
    Quién hizo qué, lo más reciente primero. El dueño lo ve todo; el
    administrador de sede solo lo de sus sedes (lo que no es de ninguna
    sede —usuarios, contraseñas, nómina— es del dueño).
    """
    acciones = next((a for c, _, a in FILTROS_ACTIVIDAD if c == filtro), None)
    s = _session()
    try:
        q = s.query(m.Actividad)
        if acciones:
            q = q.filter(m.Actividad.accion.in_(acciones))
        if persona.rol != m.DUENO:
            q = q.filter(m.Actividad.sede_id.in_([i for i, _ in persona.sedes]))
        filas = q.order_by(m.Actividad.created_at.desc(), m.Actividad.id.desc()).limit(limite).all()
        sedes = {x.id: x.nombre for x in s.query(m.Sede).all()}
        return [{"cuando": formato.cuando(f.created_at, hoy), "actor": f.actor,
                 "verbo": f.detalle or "", "detalle": (f.despues or {}).get("detalle", ""),
                 "motivo": f.motivo or "", "sede": sedes.get(f.sede_id, ""),
                 "punto": TIPO_PUNTO.get(f.accion, "gris")}
                for f in filas]
    finally:
        s.close()


def cuantas_hoy(persona: permisos.Persona, hoy: date) -> int:
    """La insignia de "Actividad" en la barra: lo que pasó hoy."""
    ini, fin = formato.rango_utc(hoy, hoy + timedelta(days=1))
    s = _session()
    try:
        q = s.query(func.count(m.Actividad.id)).filter(m.Actividad.created_at >= ini,
                                                       m.Actividad.created_at < fin)
        if persona.rol != m.DUENO:
            q = q.filter(m.Actividad.sede_id.in_([i for i, _ in persona.sedes]))
        return q.scalar() or 0
    finally:
        s.close()


# ══════════════════════════════════════════════════════════════════════
#  SEDES
# ══════════════════════════════════════════════════════════════════════

def sedes(hoy: date) -> list[dict]:
    """Una tarjeta por sede: barberos, lo facturado en el mes y el precio del corte."""
    desde, hasta = formato.periodo("mes", hoy)
    s = _session()
    try:
        salida = []
        for sede in s.query(m.Sede).order_by(m.Sede.id).all():
            barberos = (s.query(func.count(m.Personal.id))
                        .join(m.PersonalSede, m.PersonalSede.personal_id == m.Personal.id)
                        .filter(m.PersonalSede.sede_id == sede.id, m.Personal.rol == m.BARBERO,
                                m.Personal.activo.is_(True),
                                m.Personal.eliminado_en.is_(None)).scalar())
            ingresos, _, _ = _ingresos(s, [sede.id], desde, hasta)
            corte = (s.query(m.ServicioSede.precio)
                     .join(m.Servicio, m.Servicio.id == m.ServicioSede.servicio_id)
                     .filter(m.ServicioSede.sede_id == sede.id, m.Servicio.activo.is_(True))
                     .order_by(m.Servicio.orden, m.Servicio.id).first())
            from app.barberia import agenda
            salida.append({"id": sede.id, "nombre": sede.nombre,
                           "horario": agenda.texto_horario(agenda.horario_de_sede(sede.id)),
                           "direccion": sede.direccion or "", "activo": sede.activo,
                           "barberos": barberos or 0, "facturado": ingresos,
                           "corte": _suma(corte[0]) if corte else None})
        return salida
    finally:
        s.close()


def uso_del_plan() -> tuple[int, int]:
    """(sedes, barberos) en uso, para "Usas 3 de 3 sedes y 8 de 10 barberos"."""
    s = _session()
    try:
        return (s.query(func.count(m.Sede.id)).scalar() or 0,
                s.query(func.count(m.Personal.id))
                .filter(m.Personal.rol == m.BARBERO, m.Personal.eliminado_en.is_(None))
                .scalar() or 0)
    finally:
        s.close()
