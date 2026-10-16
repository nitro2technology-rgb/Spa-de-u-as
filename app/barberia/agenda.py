"""
LA AGENDA DE LA BARBERÍA
=========================
La única fuente de verdad de las citas (§6.1 de la especificación): aquí
caen las que agenda el bot, las del panel y los clientes sin cita que
registra el barbero.

    horario   cuándo se atiende (`barb_horarios`, en la hora LOCAL de la sede)
    bloqueo   un rato en que no (`barb_bloqueos`: almuerzo, vacaciones)
    cita      lo que ocupa a un barbero (`barb_citas`)

Un HUECO es un inicio en el que cabe el servicio entero: dentro del
horario, fuera de todo bloqueo y sin pisar ninguna cita que ocupe.

    ⚠️  RESERVAR VA CON CANDADO.

Entre que el cliente ve los horarios y toca uno pueden pasar minutos, y en
ese tiempo el panel o el bot de otro cliente pueden tomar el mismo. Por
eso `reservar` vuelve a mirar el hueco DENTRO de `_CANDADO`. Basta un
candado del proceso porque hay un solo proceso (§3.9 de CONTINUAR_AQUI);
el día que haya varios, esto tiene que pasar a una restricción EXCLUDE de
PostgreSQL (btree_gist) sobre (barbero, rango de la cita).

Qué citas ocupan: las pendientes, confirmadas, en curso y completadas. Una
cancelada, anulada o "no vino" libera el hueco.
"""

import threading
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import or_

from app.barberia import cuentas, formato, permisos
from app.barberia import modelos as m
from app.barberia.operacion import Error, _session, servicios_de_sede

# (día, desde, hasta) — lunes a sábado de 8 a. m. a 8 p. m., domingo de 10 a 4.
HORARIO_POR_DEFECTO = tuple((d, time(8), time(20)) for d in range(6)) + ((6, time(10), time(16)),)

PASO_MINUTOS = 30          # los huecos se ofrecen cada media hora
ANTICIPACION_MINUTOS = 30  # no se ofrece un hueco que empieza en menos de esto
DIAS_A_MIRAR = 21          # hasta dónde se buscan días con huecos

OCUPAN = (m.PENDIENTE, m.CONFIRMADA, m.EN_CURSO, m.COMPLETADA)
ACTIVAS = (m.PENDIENTE, m.CONFIRMADA, m.EN_CURSO)

NOMBRE_ESTADO = {
    m.COMPLETADA: "Completada", m.EN_CURSO: "En curso", m.CONFIRMADA: "Confirmada",
    m.PENDIENTE: "Sin confirmar", m.NO_ASISTIO: "No vino", m.ANULADA: "Anulada",
    m.CANCELADA: "Cancelada",
}
DIAS_CORTOS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")

_CANDADO = threading.Lock()


class Ocupado(Error):
    """El hueco ya no está libre."""


def _utc(momento: datetime) -> datetime:
    return m.en_utc(momento)


def _local(dia: date, hora: time) -> datetime:
    """Un día y una hora de la sede, como instante UTC."""
    return datetime.combine(dia, hora, tzinfo=formato.zona()).astimezone(timezone.utc)


# ══════════════════════════════════════════════════════════════════════
#  HORARIOS
# ══════════════════════════════════════════════════════════════════════

def poner_horario_por_defecto(sede_id: int) -> None:
    """El horario con el que nace una sede. Con el inquilino puesto."""
    s = _session()
    try:
        if s.query(m.Horario).filter_by(sede_id=sede_id, personal_id=None).count():
            return
        for dia, desde, hasta in HORARIO_POR_DEFECTO:
            s.add(m.Horario(sede_id=sede_id, dia_semana=dia, hora_inicio=desde, hora_fin=hasta))
        s.commit()
    finally:
        s.close()


def horario_de_sede(sede_id: int) -> dict[int, list[tuple[time, time]]]:
    """{día: [(desde, hasta), …]}. Un día sin tramos está cerrado."""
    s = _session()
    try:
        filas = (s.query(m.Horario).filter_by(sede_id=sede_id, personal_id=None)
                 .order_by(m.Horario.dia_semana, m.Horario.hora_inicio).all())
        salida = {d: [] for d in range(7)}
        for f in filas:
            salida[f.dia_semana].append((f.hora_inicio, f.hora_fin))
        return salida
    finally:
        s.close()


def _hora_corta(t: time) -> str:
    """8:00 → "8 a. m.", 16:30 → "4:30 p. m."."""
    h = t.hour % 12 or 12
    minutos = f":{t.minute:02d}" if t.minute else ""
    return f"{h}{minutos} {'a. m.' if t.hour < 12 else 'p. m.'}"


def texto_horario(horario: dict) -> str:
    """"Lun a sáb 8 a. m. a 8 p. m., dom 10 a. m. a 4 p. m."."""
    grupos = []                                   # [(desde_dia, hasta_dia, tramos)]
    for dia in range(7):
        tramos = tuple(horario.get(dia) or ())
        if grupos and grupos[-1][2] == tramos and grupos[-1][1] == dia - 1:
            grupos[-1] = (grupos[-1][0], dia, tramos)
        else:
            grupos.append((dia, dia, tramos))
    partes = []
    for desde, hasta, tramos in grupos:
        if not tramos:
            continue
        dias = DIAS_CORTOS[desde] if desde == hasta else f"{DIAS_CORTOS[desde]} a {DIAS_CORTOS[hasta]}"
        horas = " y ".join(f"{_hora_corta(a)} a {_hora_corta(b)}" for a, b in tramos)
        partes.append(f"{dias} {horas}")
    return formato.con_mayuscula(", ".join(partes)) if partes else "Cerrada todos los días"


def guardar_horario(persona: permisos.Persona, sede_id: int,
                    dias: dict[int, tuple[time, time] | None]) -> None:
    """Reemplaza el horario de una sede: un tramo por día, o None si cierra."""
    if not permisos.sede_permitida(persona, sede_id):
        raise Error("Esa sede no es tuya.")
    for dia, tramo in dias.items():
        if tramo and tramo[0] >= tramo[1]:
            raise Error(f"El {formato.DIAS[dia]} cierra antes de abrir. Revisa las horas.")
    s = _session()
    try:
        s.query(m.Horario).filter_by(sede_id=sede_id, personal_id=None).delete()
        for dia, tramo in dias.items():
            if tramo:
                s.add(m.Horario(sede_id=sede_id, dia_semana=dia, hora_inicio=tramo[0],
                                hora_fin=tramo[1]))
        s.commit()
        nombre = s.get(m.Sede, sede_id).nombre
    finally:
        s.close()
    cuentas.registrar("SEDE", f"cambió el horario de {nombre}", persona=persona,
                      sede_id=sede_id, tabla="barb_horarios", registro_id=sede_id,
                      despues={"detalle": texto_horario(horario_de_sede(sede_id))})


# ══════════════════════════════════════════════════════════════════════
#  HUECOS
# ══════════════════════════════════════════════════════════════════════

def _tramos(s, sede_id: int, personal_id: int | None, dia: date) -> list[tuple[datetime, datetime]]:
    """Cuándo trabaja ese barbero en esa sede ese día (su horario, o el de la sede)."""
    q = s.query(m.Horario).filter_by(sede_id=sede_id, dia_semana=dia.weekday())
    propios = q.filter_by(personal_id=personal_id).all() if personal_id else []
    filas = propios or q.filter_by(personal_id=None).all()
    return sorted((_local(dia, f.hora_inicio), _local(dia, f.hora_fin)) for f in filas)


def _ocupados(s, sede_id: int, personal_id: int, desde: datetime,
              hasta: datetime) -> list[tuple[datetime, datetime]]:
    citas = (s.query(m.Cita.inicio, m.Cita.fin)
             .filter(m.Cita.barbero_id == personal_id, m.Cita.estado.in_(OCUPAN),
                     m.Cita.inicio < hasta, m.Cita.fin > desde).all())
    bloqueos = (s.query(m.Bloqueo.inicio, m.Bloqueo.fin)
                .filter(or_(m.Bloqueo.personal_id == personal_id,
                            (m.Bloqueo.personal_id.is_(None)) & (m.Bloqueo.sede_id == sede_id)),
                        m.Bloqueo.inicio < hasta, m.Bloqueo.fin > desde).all())
    return sorted((_utc(a), _utc(b)) for a, b in list(citas) + list(bloqueos))


def _libres(tramos, ocupados):
    salida = []
    for ini, fin in tramos:
        cursor = ini
        for a, b in ocupados:
            if b <= cursor or a >= fin:
                continue
            if a > cursor:
                salida.append((cursor, a))
            cursor = max(cursor, b)
        if cursor < fin:
            salida.append((cursor, fin))
    return salida


def _en_la_rejilla(momento: datetime) -> datetime:
    """El primer múltiplo de PASO_MINUTOS (en hora local) desde `momento`."""
    local = momento.astimezone(formato.zona())
    base = local.replace(minute=0, second=0, microsecond=0)
    while base < local:
        base += timedelta(minutes=PASO_MINUTOS)
    return base.astimezone(timezone.utc)


def huecos(s, sede_id: int, personal_id: int, dia: date, minutos: int,
           ahora: datetime | None = None) -> list[datetime]:
    """Los inicios libres de un barbero en una sede un día, en UTC."""
    ahora = ahora or m.ahora()
    tramos = _tramos(s, sede_id, personal_id, dia)
    if not tramos:
        return []
    ocupados = _ocupados(s, sede_id, personal_id, tramos[0][0], tramos[-1][1])
    minimo = ahora + timedelta(minutes=ANTICIPACION_MINUTOS)
    salida = []
    for a, b in _libres(tramos, ocupados):
        t = _en_la_rejilla(max(a, minimo))
        while t + timedelta(minutes=minutos) <= b:
            salida.append(t)
            t += timedelta(minutes=PASO_MINUTOS)
    return salida


def barberos_de(sede_id: int) -> list[tuple[int, str]]:
    """Los barberos con acceso que trabajan en esa sede."""
    s = _session()
    try:
        return [(i, n) for i, n in
                s.query(m.Personal.id, m.Personal.nombre)
                .join(m.PersonalSede, m.PersonalSede.personal_id == m.Personal.id)
                .filter(m.PersonalSede.sede_id == sede_id, m.Personal.rol == m.BARBERO,
                        m.Personal.activo.is_(True), m.Personal.eliminado_en.is_(None))
                .order_by(m.Personal.nombre).all()]
    finally:
        s.close()


def _citas_del_dia(s, personal_id: int, dia: date) -> int:
    ini, fin = formato.rango_utc(dia, dia + timedelta(days=1))
    return (s.query(m.Cita).filter(m.Cita.barbero_id == personal_id, m.Cita.estado.in_(OCUPAN),
                                   m.Cita.inicio >= ini, m.Cita.inicio < fin).count())


def huecos_de(sede_id: int, barbero_id: int | None, dia: date, minutos: int,
              ahora: datetime | None = None) -> dict[datetime, int]:
    """
    {inicio: barbero}. Con `barbero_id` vacío ("el que esté libre"), a cada
    hora le toca el barbero con MENOS citas ese día (decisión §11.6,
    provisional: reparte el trabajo).
    """
    s = _session()
    try:
        candidatos = [barbero_id] if barbero_id else [i for i, _ in barberos_de(sede_id)]
        carga = {b: _citas_del_dia(s, b, dia) for b in candidatos}
        salida: dict[datetime, int] = {}
        for b in sorted(candidatos, key=lambda x: carga[x]):
            for t in huecos(s, sede_id, b, dia, minutos, ahora):
                salida.setdefault(t, b)
        return dict(sorted(salida.items()))
    finally:
        s.close()


def dias_con_huecos(sede_id: int, barbero_id: int | None, minutos: int, desde: date,
                    cuantos: int = 10) -> list[tuple[date, int]]:
    """Los próximos días con al menos un hueco, y cuántos tiene cada uno."""
    salida = []
    for k in range(DIAS_A_MIRAR):
        dia = desde + timedelta(days=k)
        n = len(huecos_de(sede_id, barbero_id, dia, minutos))
        if n:
            salida.append((dia, n))
        if len(salida) >= cuantos:
            break
    return salida


def duracion(sede_id: int, servicio_id: int) -> int:
    sv = next((x for x in servicios_de_sede(sede_id) if x["id"] == servicio_id), None)
    if sv is None:
        raise Error("Ese servicio no se ofrece en esa sede.")
    return sv["minutos"]


# ══════════════════════════════════════════════════════════════════════
#  RESERVAR Y CAMBIAR UNA CITA
# ══════════════════════════════════════════════════════════════════════

def reservar(sede_id: int, barbero_id: int | None, servicio_id: int, inicio: datetime, *,
             origen: str, cliente_id: int | None = None, persona: permisos.Persona | None = None,
             actor: str = "") -> tuple[int, int]:
    """
    Agenda una cita. Devuelve `(cita_id, barbero_id)`. Levanta `Ocupado`
    si el hueco ya no está (se vuelve a mirar dentro del candado).

    Entra CONFIRMADA: quien la pide por WhatsApp o la agenda en el local la
    acaba de confirmar (así lo pide el handoff, §9).
    """
    inicio = _utc(inicio)
    minutos = duracion(sede_id, servicio_id)
    dia = inicio.astimezone(formato.zona()).date()
    with _CANDADO:
        libres = huecos_de(sede_id, barbero_id, dia, minutos, ahora=m.ahora() - timedelta(
            minutes=ANTICIPACION_MINUTOS))
        if inicio not in libres:
            raise Ocupado("Ese horario ya se ocupó. Elige otro.")
        barbero_id = libres[inicio]
        s = _session()
        try:
            cita = m.Cita(sede_id=sede_id, barbero_id=barbero_id, cliente_id=cliente_id,
                          inicio=inicio, fin=inicio + timedelta(minutes=minutos),
                          estado=m.CONFIRMADA, origen=origen, servicio_id=servicio_id,
                          registrada_por=persona.personal_id if persona else None)
            s.add(cita)
            s.commit()
            cita_id = cita.id
            barbero = s.get(m.Personal, barbero_id).nombre
            cliente = s.get(m.ClienteBarberia, cliente_id).nombre if cliente_id else "Sin nombre"
        finally:
            s.close()
    cuentas.registrar("CITA", "agendó una cita", persona=persona,
                      actor=actor or ("Bot de WhatsApp" if origen == m.WHATSAPP else "Sistema"),
                      sede_id=sede_id, tabla="barb_citas", registro_id=cita_id,
                      despues={"detalle": f"{cliente} con {barbero}, "
                                          f"{formato.fecha_larga(dia)} a las {formato.hora(inicio)}"})
    return cita_id, barbero_id


def _puede_tocar(persona: permisos.Persona, cita: m.Cita) -> bool:
    if not permisos.sede_permitida(persona, cita.sede_id):
        return False
    return persona.rol != m.BARBERO or cita.barbero_id == persona.personal_id


def cambiar_estado(persona: permisos.Persona, cita_id: int, estado: str) -> str:
    """Empezar, "no vino" o confirmar. Devuelve el nombre del cliente."""
    permitidos = {m.EN_CURSO: ACTIVAS, m.NO_ASISTIO: ACTIVAS,
                  m.CONFIRMADA: (m.PENDIENTE,)}
    if estado not in permitidos:
        raise Error("Ese cambio no se puede hacer.")
    s = _session()
    try:
        cita = s.get(m.Cita, cita_id)
        if cita is None or not _puede_tocar(persona, cita):
            raise Error("Esa cita no existe.")
        if cita.estado not in permitidos[estado]:
            raise Error("Esa cita ya no se puede cambiar.")
        cita.estado = estado
        s.commit()
        cliente = s.get(m.ClienteBarberia, cita.cliente_id).nombre if cita.cliente_id else "El cliente"
        sede_id = cita.sede_id
    finally:
        s.close()
    if estado == m.NO_ASISTIO:
        cuentas.registrar("CITA", "marcó que un cliente no vino", persona=persona,
                          sede_id=sede_id, tabla="barb_citas", registro_id=cita_id,
                          despues={"detalle": cliente})
    return cliente


def cancelar(cita_id: int, motivo: str, persona: permisos.Persona | None = None,
             actor: str = "") -> None:
    """Cancela una cita que todavía no se atendió. Libera el hueco."""
    s = _session()
    try:
        cita = s.get(m.Cita, cita_id)
        if cita is None or (persona is not None and not _puede_tocar(persona, cita)):
            raise Error("Esa cita no existe.")
        if cita.estado not in ACTIVAS:
            raise Error("Esa cita ya no se puede cancelar.")
        cita.estado = m.CANCELADA
        cita.motivo_cancelacion = (motivo or "")[:200] or None
        s.commit()
        sede_id = cita.sede_id
        cliente = s.get(m.ClienteBarberia, cita.cliente_id).nombre if cita.cliente_id else "Sin nombre"
        cuando = f"{formato.fecha_larga(formato.a_local(cita.inicio).date())} a las {formato.hora(cita.inicio)}"
    finally:
        s.close()
    cuentas.registrar("CITA", "canceló una cita", persona=persona,
                      actor=actor or "Sistema", sede_id=sede_id, tabla="barb_citas",
                      registro_id=cita_id, motivo=motivo or None,
                      despues={"detalle": f"{cliente}, {cuando}"})


def bloquear(persona: permisos.Persona, sede_id: int, personal_id: int | None, dia: date,
             desde: time, hasta: time, motivo: str) -> int:
    """Un rato sin agenda para un barbero o para toda la sede."""
    if not permisos.sede_permitida(persona, sede_id):
        raise Error("Esa sede no es tuya.")
    if desde >= hasta:
        raise Error("El bloqueo termina antes de empezar.")
    if personal_id and personal_id not in [i for i, _ in barberos_de(sede_id)]:
        raise Error("Ese barbero no trabaja en esa sede.")
    s = _session()
    try:
        b = m.Bloqueo(sede_id=sede_id, personal_id=personal_id, inicio=_local(dia, desde),
                      fin=_local(dia, hasta), motivo=(motivo or "").strip()[:100] or None,
                      creado_por=persona.personal_id)
        s.add(b)
        s.commit()
        return b.id
    finally:
        s.close()


def quitar_bloqueo(persona: permisos.Persona, bloqueo_id: int) -> None:
    s = _session()
    try:
        b = s.get(m.Bloqueo, bloqueo_id)
        if b is None or (b.sede_id and not permisos.sede_permitida(persona, b.sede_id)):
            raise Error("Ese bloqueo no existe.")
        s.delete(b)
        s.commit()
    finally:
        s.close()


# ══════════════════════════════════════════════════════════════════════
#  LO QUE SE LEE
# ══════════════════════════════════════════════════════════════════════

def _nombres_servicios(s, cita: m.Cita) -> str:
    hechos = [cs.nombre for cs in s.query(m.CitaServicio).filter_by(cita_id=cita.id)]
    if hechos:
        return ", ".join(hechos)
    if cita.servicio_id:
        sv = s.get(m.Servicio, cita.servicio_id)
        return sv.nombre if sv else ""
    return ""


def _dato_cita(s, cita: m.Cita, ahora: datetime) -> dict:
    cliente = s.get(m.ClienteBarberia, cita.cliente_id) if cita.cliente_id else None
    minutos = int((_utc(cita.fin) - _utc(cita.inicio)).total_seconds() // 60)
    sin_cobro = (cita.estado in ACTIVAS
                 and _utc(cita.fin) + timedelta(minutes=30) < ahora)
    return {
        "id": cita.id, "inicio": _utc(cita.inicio), "fin": _utc(cita.fin), "minutos": minutos,
        "barbero_id": cita.barbero_id, "sede_id": cita.sede_id, "estado": cita.estado,
        "estado_nombre": NOMBRE_ESTADO.get(cita.estado, cita.estado),
        "origen": cita.origen, "servicio_id": cita.servicio_id,
        "servicios": _nombres_servicios(s, cita),
        "cliente": cliente.nombre if cliente else "Cliente de paso",
        "telefono": cliente.telefono if cliente else "",
        "nota": (cliente.notas or "") if cliente else "",
        "cliente_id": cliente.id if cliente else None,
        "sin_cobro": sin_cobro,
    }


def agenda_dia(sede_id: int, dia: date) -> dict:
    """Lo que pinta la Agenda (6.2.2): barberos, citas y bloqueos de un día."""
    ini, fin = formato.rango_utc(dia, dia + timedelta(days=1))
    ahora = m.ahora()
    horario = horario_de_sede(sede_id).get(dia.weekday()) or []
    desde = min((a.hour for a, _ in horario), default=8)
    hasta = max(((b.hour + (1 if b.minute else 0)) for _, b in horario), default=20)
    s = _session()
    try:
        barberos = []
        for b_id, nombre in barberos_de(sede_id):
            sedes = s.query(m.PersonalSede).filter_by(personal_id=b_id).count()
            p = s.get(m.Personal, b_id)
            barberos.append({"id": b_id, "nombre": nombre, "iniciales": permisos.iniciales(nombre),
                             "sub": "Rota entre sedes" if sedes > 1 else
                             ("Alquiler de silla" if p.esquema_pago == m.ALQUILER_SILLA else
                              f"{int(p.comision_defecto)}% de comisión")})
        ids = [b["id"] for b in barberos]
        citas = (s.query(m.Cita).filter(m.Cita.sede_id == sede_id, m.Cita.barbero_id.in_(ids or [0]),
                                        m.Cita.inicio >= ini, m.Cita.inicio < fin,
                                        m.Cita.estado != m.CANCELADA)
                 .order_by(m.Cita.inicio).all())
        bloqueos = (s.query(m.Bloqueo).filter(m.Bloqueo.inicio < fin, m.Bloqueo.fin > ini,
                                              or_(m.Bloqueo.sede_id == sede_id,
                                                  m.Bloqueo.personal_id.in_(ids or [0])))
                    .order_by(m.Bloqueo.inicio).all())
        return {
            "dia": dia, "desde": desde, "hasta": max(hasta, desde + 1),
            "barberos": barberos, "horario": horario,
            "citas": [_dato_cita(s, c, ahora) for c in citas],
            "bloqueos": [{"id": b.id, "personal_id": b.personal_id, "inicio": _utc(b.inicio),
                          "fin": _utc(b.fin), "motivo": b.motivo or "Bloqueado"} for b in bloqueos],
        }
    finally:
        s.close()


def cita(cita_id: int) -> dict | None:
    s = _session()
    try:
        c = s.get(m.Cita, cita_id)
        return _dato_cita(s, c, m.ahora()) if c else None
    finally:
        s.close()


def dia_del_barbero(personal_id: int, hoy: date) -> dict:
    """"Mi día": la cita en curso o la siguiente, y las que vienen después."""
    ini, fin = formato.rango_utc(hoy, hoy + timedelta(days=1))
    ahora = m.ahora()
    s = _session()
    try:
        citas = (s.query(m.Cita).filter(m.Cita.barbero_id == personal_id,
                                        m.Cita.inicio >= ini, m.Cita.inicio < fin,
                                        m.Cita.estado.in_(ACTIVAS))
                 .order_by(m.Cita.inicio).all())
        datos = [_dato_cita(s, c, ahora) for c in citas]
    finally:
        s.close()
    en_curso = next((c for c in datos if c["estado"] == m.EN_CURSO), None)
    actual = en_curso or (datos[0] if datos else None)
    resto = [c for c in datos if actual is None or c["id"] != actual["id"]]
    return {"actual": actual, "resto": resto}


def sin_cobro(sede_ids: list[int], hoy: date) -> list[dict]:
    """
    Citas que ya pasaron y siguen sin cobro ni "no vino": el cruce agenda
    contra cobros de "Para revisar" (6.2.1). Media hora de gracia tras el
    fin, para no marcar a quien está cobrando ahora mismo.
    """
    ini, _ = formato.rango_utc(hoy - timedelta(days=6), hoy)
    ahora = m.ahora()
    s = _session()
    try:
        citas = (s.query(m.Cita).filter(m.Cita.sede_id.in_(sede_ids or [0]),
                                        m.Cita.estado.in_(ACTIVAS), m.Cita.inicio >= ini,
                                        m.Cita.fin < ahora - timedelta(minutes=30))
                 .order_by(m.Cita.inicio.desc()).all())
        return [_dato_cita(s, c, ahora) for c in citas]
    finally:
        s.close()


def ocupacion(sede_ids: list[int], desde: date, hasta: date,
              barbero_id: int | None = None) -> int | None:
    """
    Horas con cliente en la silla / horas de horario, en %. None si en ese
    periodo no había horario (no hay contra qué medir).
    """
    s = _session()
    try:
        disponibles = timedelta()
        ocupadas = timedelta()
        for sid in sede_ids:
            ids = [b for b, _ in barberos_de(sid) if barbero_id in (None, b)]
            dia = desde
            while dia < hasta:
                for b in ids:
                    for a, z in _tramos(s, sid, b, dia):
                        disponibles += z - a
                dia += timedelta(days=1)
            ini, fin = formato.rango_utc(desde, hasta)
            for a, z in (s.query(m.Cita.inicio, m.Cita.fin)
                         .filter(m.Cita.sede_id == sid, m.Cita.estado == m.COMPLETADA,
                                 m.Cita.barbero_id.in_(ids or [0]),
                                 m.Cita.inicio >= ini, m.Cita.inicio < fin)):
                ocupadas += _utc(z) - _utc(a)
        if not disponibles:
            return None
        return min(100, int(round(ocupadas / disponibles * 100)))
    finally:
        s.close()
