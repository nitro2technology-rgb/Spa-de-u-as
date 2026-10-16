"""
LAS CIFRAS DE UN NEGOCIO
=========================
Lo que ve el dueño en "Estadísticas": cuánta gente le escribió, qué pidió,
de dónde llegó y cuántas citas y consultas dejó el bot.

Todo sale de lo que ya se guarda —`contacts`, `messages`, `leads`— y va
filtrado por el negocio en curso como cualquier consulta del panel (el
filtro del ORM y RLS). No hay tabla de estadísticas: con los volúmenes de
un negocio pequeño, contar al vuelo cuesta milisegundos y nunca se
desincroniza.

Los días se cuentan en hora de Colombia, igual que los cobros: un mensaje
de las 9 de la noche del lunes es del lunes, no del martes en UTC.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app import config
from app.core import database

ZONA = ZoneInfo("America/Bogota")

PERIODOS = (7, 30, 90)


def _dia_local(momento) -> str:
    """Un `created_at` (UTC sin zona) → "2026-09-24" en Colombia."""
    return (momento.replace(tzinfo=timezone.utc).astimezone(ZONA)
            .date().isoformat())


def resumen(dias: int = 30) -> dict:
    """Las cifras de los últimos `dias` días, listas para pintar."""
    dias = dias if dias in PERIODOS else 30
    hoy = datetime.now(ZONA).date()
    primero = hoy - timedelta(days=dias - 1)
    # El corte en UTC que corresponde a la medianoche de Colombia del
    # primer día: así el primer día cuenta entero.
    desde = (datetime.combine(primero, datetime.min.time(), tzinfo=ZONA)
             .astimezone(timezone.utc).replace(tzinfo=None))

    M, C, L = database.Message, database.Contact, database.Lead
    session = database.get_session()
    try:
        entrantes = (session.query(M.created_at, M.phone)
                     .filter(M.direccion == "entrante", M.created_at >= desde)
                     .all())
        respuestas_humanas = (session.query(func.count(M.id))
                              .filter(M.direccion == "saliente",
                                      M.autor == "humano",
                                      M.created_at >= desde).scalar()) or 0
        nuevos = (session.query(C.servicio, C.origen, C.area)
                  .filter(C.created_at >= desde).all())
        leads = (session.query(L.type, L.status)
                 .filter(L.created_at >= desde).all())
    finally:
        session.close()

    por_dia = Counter(_dia_local(m) for m, _ in entrantes)
    serie = []
    for i in range(dias):
        d = primero + timedelta(days=i)
        serie.append({"dia": d.isoformat(), "fecha": d,
                      "mensajes": por_dia.get(d.isoformat(), 0)})

    titulos = {o["id"]: o.get("title") or o["id"]
               for o in (config.NEED_OPTIONS or []) if o.get("id")}
    opciones = Counter(titulos.get(s, "Otra opción") if s else "No eligió ninguna"
                       for s, _, _ in nuevos)
    origenes = Counter((o or config.ORIGEN_POR_DEFECTO) for _, o, _ in nuevos)

    por_area = None
    from app.core import equipo
    if equipo.areas():
        nombres = {a["id"]: a.get("nombre") or a["id"] for a in equipo.areas()}
        por_area = Counter(nombres.get(equipo.area_de_contacto(s, a), "Tú (sin área)")
                           for s, _, a in nuevos)

    return {
        "dias": dias,
        "desde": primero,
        "hasta": hoy,
        "personas": len({p for _, p in entrantes}),
        "mensajes": len(entrantes),
        "nuevos": len(nuevos),
        "citas": sum(1 for t, s in leads if t == "cita" and s != "cancelada"),
        "consultas": sum(1 for t, _ in leads if t == "otro"),
        "respuestas_humanas": respuestas_humanas,
        "por_dia": serie,
        "opciones": opciones.most_common(),
        "origenes": origenes.most_common(),
        "por_area": por_area.most_common() if por_area is not None else None,
    }
