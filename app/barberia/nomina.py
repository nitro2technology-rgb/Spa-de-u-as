"""
LO QUE SE LE PAGA A CADA QUIEN
===============================
La liquidación quincenal (6.2.4 del handoff), los adelantos y lo que el
barbero ve de sí mismo en "Hoy llevas" y "Mis ganancias".

    Le pagas = comisiones + propinas + comisión por productos − descuentos

  · Comisiones: lo que le tocó de cada servicio, CONGELADO al cobrar en
    `barb_cita_servicios.monto_barbero`. En "fijo + comisión" se le suma
    el sueldo fijo de la quincena.
  · Propinas: 100% suyas.
  · Productos: la venta de productos llega en la Fase 3; hoy siempre $0.
  · Descuentos: los adelantos que no se han descontado, y en "alquiler de
    silla" el alquiler de la quincena.

Mientras la liquidación está en BORRADOR no hay fila: se calcula en vivo y
cambia con cada cobro. Al APROBAR se guardan las cifras y se ligan los
adelantos; desde ahí no cambia. PAGADA es final.
"""

from datetime import date, timedelta

from sqlalchemy import func

from app.barberia import cuentas, formato, permisos
from app.barberia import modelos as m
from app.barberia.operacion import CERO, Error, _al_peso, _session, _suma, dinero

ESQUEMAS = {
    m.COMISION: "Comisión",
    m.FIJO_MAS_COMISION: "Fijo + comisión",
    m.ALQUILER_SILLA: "Alquiler de silla",
}


def nombre_esquema(p: m.Personal) -> str:
    """Como se ve en la tabla: "50/50", "60/40", "Fijo + 20%", "Alquiler de silla"."""
    pct = int(_suma(p.comision_defecto))
    if p.esquema_pago == m.ALQUILER_SILLA:
        return "Alquiler de silla"
    if p.esquema_pago == m.FIJO_MAS_COMISION:
        return f"Fijo + {pct}%"
    return f"{pct}/{100 - pct}"


def nota_esquema(p: m.Personal) -> str:
    if p.esquema_pago == m.ALQUILER_SILLA:
        return f"Paga {formato.pesos(p.alquiler_silla)} por quincena"
    if p.esquema_pago == m.FIJO_MAS_COMISION:
        return f"{formato.pesos(p.sueldo_fijo)} por quincena"
    return "Sobre lo que factura"


def _servicios_del_periodo(s, personal_id: int, desde: date, hasta: date):
    """Citas COMPLETADAS (no anuladas) de alguien entre dos días, inclusive."""
    ini, fin = formato.rango_utc(desde, hasta + timedelta(days=1))
    return (s.query(m.Cita).filter(m.Cita.barbero_id == personal_id,
                                   m.Cita.estado == m.COMPLETADA,
                                   m.Cita.inicio >= ini, m.Cita.inicio < fin))


def calcular(s, p: m.Personal, desde: date, hasta: date) -> dict:
    """La liquidación de alguien en [desde, hasta], calculada en vivo."""
    citas = _servicios_del_periodo(s, p.id, desde, hasta).subquery()
    servicios, comisiones = (s.query(func.sum(m.CitaServicio.precio),
                                     func.sum(m.CitaServicio.monto_barbero))
                             .filter(m.CitaServicio.cita_id.in_(s.query(citas.c.id)))
                             .one())
    propinas = s.query(func.sum(citas.c.propina)).scalar()

    comisiones = _suma(comisiones)
    sueldo = _suma(p.sueldo_fijo) if p.esquema_pago == m.FIJO_MAS_COMISION else CERO
    adelantos = (s.query(m.Adelanto).filter(m.Adelanto.personal_id == p.id,
                                            m.Adelanto.liquidacion_id.is_(None),
                                            m.Adelanto.fecha <= hasta).all())
    total_adelantos = sum((_suma(a.monto) for a in adelantos), CERO)
    alquiler = _suma(p.alquiler_silla) if p.esquema_pago == m.ALQUILER_SILLA else CERO
    descuentos = total_adelantos + alquiler
    propinas = _suma(propinas)
    productos = CERO
    return {
        "servicios": _suma(servicios),
        "comisiones": comisiones + sueldo,
        "sueldo_fijo": sueldo,
        "propinas": propinas,
        "productos": productos,
        "adelantos": total_adelantos,
        "alquiler": alquiler,
        "descuentos": descuentos,
        "total": comisiones + sueldo + propinas + productos - descuentos,
        "adelantos_ids": [a.id for a in adelantos],
        "fecha_adelanto": max((a.fecha for a in adelantos), default=None),
    }


def _sedes_de(s, personal_id: int) -> list[int]:
    return [i for (i,) in s.query(m.PersonalSede.sede_id).filter_by(personal_id=personal_id)]


def filas(persona: permisos.Persona, sede_id: int | None, hoy: date) -> dict:
    """La tabla de Barberos y pagos de la quincena en curso, y sus totales."""
    desde, hasta = formato.quincena_de(hoy)
    visibles = {i for i, _ in persona.sedes if sede_id in (None, i)}
    nombres_sede = dict(persona.sedes)
    s = _session()
    try:
        gente = (s.query(m.Personal).filter(m.Personal.rol == m.BARBERO,
                                            m.Personal.eliminado_en.is_(None))
                 .order_by(m.Personal.nombre).all())
        salida = []
        for p in gente:
            sedes = _sedes_de(s, p.id)
            if not visibles & set(sedes):
                continue
            guardada = (s.query(m.Liquidacion)
                        .filter_by(personal_id=p.id, periodo_inicio=desde).first())
            if guardada is not None:
                datos = {"servicios": _suma(guardada.total_servicios),
                         "comisiones": _suma(guardada.total_comisiones),
                         "propinas": _suma(guardada.total_propinas),
                         "productos": _suma(guardada.total_productos),
                         "descuentos": _suma(guardada.descuentos),
                         "adelantos": CERO, "alquiler": CERO,
                         "total": _suma(guardada.total_a_pagar),
                         "fecha_adelanto": None}
                estado, liq_id = guardada.estado, guardada.id
            else:
                datos = calcular(s, p, desde, hasta)
                estado, liq_id = m.BORRADOR, None
                # Alguien desactivado que no trabajó en la quincena no
                # tiene nada que aprobar: sería una fila de ceros.
                if not p.activo and not datos["servicios"] and not datos["adelantos"]:
                    continue
            salida.append(dict(
                datos, personal_id=p.id, nombre=p.nombre, activo=p.activo,
                iniciales=permisos.iniciales(p.nombre),
                sedes=" y ".join(nombres_sede.get(i, "") for i in sedes
                                 if i in nombres_sede) or "",
                esquema=nombre_esquema(p), nota_esquema=nota_esquema(p),
                esquema_pago=p.esquema_pago, estado=estado, liquidacion_id=liq_id))
        total = sum((f["total"] for f in salida), CERO)
        falta = sum((f["total"] for f in salida if f["estado"] != m.PAGADA), CERO)
        adelantos = sum((f["adelantos"] for f in salida if f["estado"] == m.BORRADOR), CERO)
        return {"desde": desde, "hasta": hasta, "filas": salida, "total": total,
                "falta": falta, "adelantos": adelantos}
    finally:
        s.close()


def aprobar(persona: permisos.Persona, personal_id: int, hoy: date) -> int:
    """Congela la liquidación de la quincena en curso y le liga los adelantos."""
    desde, hasta = formato.quincena_de(hoy)
    s = _session()
    try:
        p = s.get(m.Personal, personal_id)
        if p is None or p.rol != m.BARBERO:
            raise Error("Esa persona no está en la liquidación.")
        if not set(_sedes_de(s, p.id)) & {i for i, _ in persona.sedes}:
            raise Error("Esa persona no es de tus sedes.")
        if s.query(m.Liquidacion).filter_by(personal_id=p.id, periodo_inicio=desde).first():
            raise Error("Esa liquidación ya estaba aprobada.")
        d = calcular(s, p, desde, hasta)
        liq = m.Liquidacion(personal_id=p.id, periodo_inicio=desde, periodo_fin=hasta,
                            total_servicios=d["servicios"], total_comisiones=d["comisiones"],
                            total_propinas=d["propinas"], total_productos=d["productos"],
                            sueldo_fijo=d["sueldo_fijo"], descuentos=d["descuentos"],
                            total_a_pagar=d["total"], estado=m.APROBADA,
                            aprobada_en=m.ahora())
        s.add(liq)
        s.flush()
        if d["adelantos_ids"]:
            (s.query(m.Adelanto).filter(m.Adelanto.id.in_(d["adelantos_ids"]))
             .update({"liquidacion_id": liq.id}, synchronize_session=False))
        s.commit()
        liq_id, nombre, total = liq.id, p.nombre, d["total"]
    finally:
        s.close()
    cuentas.registrar("PAGO", "aprobó una liquidación", persona=persona,
                      tabla="barb_liquidaciones", registro_id=liq_id,
                      despues={"detalle": f"{nombre}: {formato.pesos(total)} de la "
                                          f"{formato.quincena(desde).lower()}"})
    return liq_id


def marcar_pagada(persona: permisos.Persona, liquidacion_id: int) -> None:
    """APROBADA → PAGADA. Es final: revertirla exige anular con motivo (fuera de la Fase 1)."""
    s = _session()
    try:
        liq = s.get(m.Liquidacion, liquidacion_id)
        if liq is None or liq.estado != m.APROBADA:
            raise Error("Esa liquidación no está aprobada.")
        if not set(_sedes_de(s, liq.personal_id)) & {i for i, _ in persona.sedes}:
            raise Error("Esa persona no es de tus sedes.")
        liq.estado = m.PAGADA
        liq.pagada_en = m.ahora()
        s.commit()
        nombre = s.get(m.Personal, liq.personal_id).nombre
        total = _suma(liq.total_a_pagar)
    finally:
        s.close()
    cuentas.registrar("PAGO", "marcó una liquidación como pagada", persona=persona,
                      tabla="barb_liquidaciones", registro_id=liquidacion_id,
                      despues={"detalle": f"Le pagó {formato.pesos(total)} a {nombre}"})


def registrar_adelanto(persona: permisos.Persona, personal_id: int, monto, nota: str,
                       hoy: date) -> int:
    valor = _al_peso(dinero(monto))
    if valor <= 0:
        raise Error("Escribe cuánto le adelantaste.")
    s = _session()
    try:
        p = s.get(m.Personal, personal_id)
        if p is None or p.eliminado_en is not None or p.rol != m.BARBERO:
            raise Error("Elige a quién le adelantaste.")
        sedes = _sedes_de(s, p.id)
        if not set(sedes) & {i for i, _ in persona.sedes}:
            raise Error("Esa persona no es de tus sedes.")
        a = m.Adelanto(personal_id=p.id, monto=valor, fecha=hoy,
                       nota=(nota or "").strip()[:200] or None,
                       registrado_por=persona.personal_id)
        s.add(a)
        s.commit()
        a_id, nombre = a.id, p.nombre
    finally:
        s.close()
    cuentas.registrar("ADELANTO", "registró un adelanto", persona=persona,
                      sede_id=sedes[0] if sedes else None,
                      tabla="barb_adelantos", registro_id=a_id,
                      despues={"detalle": f"{formato.pesos(valor)} a {nombre}, se "
                                          f"descuenta en la quincena"})
    return a_id


def guardar_esquema(persona: permisos.Persona, personal_id: int, esquema: str,
                    porcentaje, sueldo_fijo, alquiler, meta) -> None:
    """Cómo se le paga a un barbero. Solo el dueño (es la nómina)."""
    if persona.rol != m.DUENO:
        raise Error("Solo el dueño cambia cómo se le paga a alguien.")
    if esquema not in ESQUEMAS:
        raise Error("Elige un esquema de pago.")
    pct = dinero(porcentaje)
    if esquema != m.ALQUILER_SILLA and not (0 < pct <= 100):
        raise Error("La comisión va de 1 a 100%.")
    s = _session()
    try:
        p = s.get(m.Personal, personal_id)
        if p is None or p.rol != m.BARBERO:
            raise Error("Esa persona no es barbero.")
        antes = nombre_esquema(p)
        p.esquema_pago = esquema
        if esquema != m.ALQUILER_SILLA:
            p.comision_defecto = pct
        p.sueldo_fijo = _al_peso(dinero(sueldo_fijo)) if esquema == m.FIJO_MAS_COMISION else 0
        p.alquiler_silla = _al_peso(dinero(alquiler)) if esquema == m.ALQUILER_SILLA else 0
        meta_valor = _al_peso(dinero(meta))
        p.meta_quincena = meta_valor if meta_valor > 0 else None
        s.commit()
        despues, nombre = nombre_esquema(p), p.nombre
    finally:
        s.close()
    cuentas.registrar("PAGO", "cambió cómo se le paga a alguien", persona=persona,
                      tabla="barb_personal", registro_id=personal_id,
                      despues={"detalle": f"{nombre}: de {antes} a {despues}. Lo ya "
                                          f"cobrado no cambia."})


# ══════════════════════════════════════════════════════════════════════
#  LO QUE VE EL BARBERO
# ══════════════════════════════════════════════════════════════════════

def hoy_llevas(personal_id: int, hoy: date) -> dict:
    """Hoy llevas = Σ(su parte de cada servicio) + propinas, sin anulados."""
    s = _session()
    try:
        citas = _servicios_del_periodo(s, personal_id, hoy, hoy).subquery()
        suyo = (s.query(func.sum(m.CitaServicio.monto_barbero))
                .filter(m.CitaServicio.cita_id.in_(s.query(citas.c.id))).scalar())
        propinas = s.query(func.sum(citas.c.propina)).scalar()
        n = s.query(func.count(citas.c.id)).scalar()
        return {"total": _suma(suyo) + _suma(propinas), "propinas": _suma(propinas),
                "servicios": n or 0}
    finally:
        s.close()


def ganancias(personal_id: int, hoy: date) -> dict:
    """"Mis ganancias": el neto de la quincena, la meta, los días y el desglose."""
    desde, hasta = formato.quincena_de(hoy)
    s = _session()
    try:
        p = s.get(m.Personal, personal_id)
        guardada = (s.query(m.Liquidacion)
                    .filter_by(personal_id=p.id, periodo_inicio=desde).first())
        d = calcular(s, p, desde, hasta)
        if guardada is not None:
            d["total"] = _suma(guardada.total_a_pagar)

        por_dia = []
        dia = desde
        while dia <= hasta:
            citas = _servicios_del_periodo(s, p.id, dia, dia).subquery()
            suyo = (s.query(func.sum(m.CitaServicio.monto_barbero))
                    .filter(m.CitaServicio.cita_id.in_(s.query(citas.c.id))).scalar())
            prop = s.query(func.sum(citas.c.propina)).scalar()
            por_dia.append((dia, _suma(suyo) + _suma(prop)))
            dia += timedelta(days=1)

        meta = _suma(p.meta_quincena) if p.meta_quincena else None
        bruto = d["comisiones"] + d["propinas"] + d["productos"]
        return dict(d, desde=desde, hasta=hasta, por_dia=por_dia, meta=meta, bruto=bruto,
                    porcentaje=int(_suma(p.comision_defecto)),
                    esquema=p.esquema_pago, estado=guardada.estado if guardada else m.BORRADOR)
    finally:
        s.close()


def datos_esquema(personal_id: int) -> dict | None:
    """Lo que se precarga en el panel "Cómo se le paga a…"."""
    s = _session()
    try:
        p = s.get(m.Personal, personal_id)
        if p is None or p.rol != m.BARBERO or p.eliminado_en is not None:
            return None
        return {"id": p.id, "nombre": p.nombre, "esquema_pago": p.esquema_pago,
                "porcentaje": int(_suma(p.comision_defecto)),
                "sueldo_fijo": formato.pesos(p.sueldo_fijo) if p.sueldo_fijo else "",
                "alquiler": formato.pesos(p.alquiler_silla) if p.alquiler_silla else "",
                "meta": formato.pesos(p.meta_quincena) if p.meta_quincena else ""}
    finally:
        s.close()


def porcentaje_de(personal_id: int) -> int:
    """El porcentaje con el que la hoja de cobro estima "Para ti" mientras se elige."""
    s = _session()
    try:
        p = s.get(m.Personal, personal_id)
        if p.esquema_pago == m.ALQUILER_SILLA:
            return 100
        return int(_suma(p.comision_defecto))
    finally:
        s.close()
