"""
LA OPERACIÓN DEL DÍA: CATÁLOGO, CLIENTES, CAJA, COBROS, ANULACIONES Y GASTOS
=============================================================================
Todo lo que mueve plata en la barbería pasa por aquí, y las pantallas
(`rutas.py`) no escriben en la base por su cuenta.

Las reglas que no se pueden romper (§7 de la especificación):

  · **Montos congelados.** El precio y el porcentaje del barbero se copian a
    `barb_cita_servicios` al cobrar. Cambiar el catálogo o la comisión no
    toca lo ya cobrado.
  · **Nada se borra.** Un servicio se ANULA con motivo, y queda en
    Actividad. Una caja cerrada no se edita.
  · **Dinero en Decimal**, redondeado al peso solo al guardar la parte de
    cada quien y al mostrar.

Todo corre con el inquilino ya puesto por el middleware: las consultas no
filtran por `client_id` a mano, lo hace el ORM (y RLS en PostgreSQL).
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func

from app.barberia import cuentas, formato, permisos
from app.barberia import modelos as m
from app.core import database

CERO = Decimal("0")

# El catálogo con el que nace una barbería (los del diseño). El dueño
# cambia los precios en Sedes.
CATALOGO_INICIAL = (
    ("Corte clásico", 35_000, 40),
    ("Corte + barba", 50_000, 60),
    ("Barba", 20_000, 25),
    ("Cejas", 10_000, 15),
    ("Tintura", 60_000, 75),
    ("Lavado", 8_000, 10),
)

METODOS_COBRO = {
    "efectivo": "Efectivo",
    "transferencia": "Transferencia",
    "tarjeta": "Tarjeta",
    "dividido": "Dividido",
}
NOMBRE_METODO = {m.EFECTIVO: "Efectivo", m.TRANSFERENCIA: "Transferencia",
                 m.TARJETA: "Tarjeta", m.OTRO: "Otro"}

MOTIVOS_ANULACION = (
    "Lo registré por error",
    "Quedó repetido",
    "El cliente no pagó",
    "Cambió de servicio",
)

CATEGORIAS_GASTO = ("Arriendo", "Servicios públicos", "Insumos", "Mantenimiento")

TOPE_MONTO = Decimal("100000000")     # $100 millones: más que eso es un dedo de más


class Error(ValueError):
    """Un error que se le enseña a quien usa el panel, tal cual."""


def dinero(valor) -> Decimal:
    """Lo que escribió alguien ("$394.000", "394000") como Decimal, o 0."""
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))
    digitos = "".join(c for c in str(valor or "") if c.isdigit())
    return Decimal(digitos) if digitos else CERO


def _suma(valor) -> Decimal:
    return Decimal(str(valor)) if valor is not None else CERO


def _al_peso(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _session():
    return database.get_session()


# ══════════════════════════════════════════════════════════════════════
#  CATÁLOGO Y PRECIOS
# ══════════════════════════════════════════════════════════════════════

def sembrar_catalogo(sede_id: int) -> None:
    """
    Le da precios a una sede nueva. La primera sede crea además el
    catálogo; las siguientes copian los precios de la primera.
    """
    s = _session()
    try:
        servicios = s.query(m.Servicio).order_by(m.Servicio.orden).all()
        if not servicios:
            for orden, (nombre, precio, minutos) in enumerate(CATALOGO_INICIAL):
                sv = m.Servicio(nombre=nombre, orden=orden)
                s.add(sv)
                s.flush()
                s.add(m.ServicioSede(servicio_id=sv.id, sede_id=sede_id,
                                     precio=Decimal(precio), duracion_minutos=minutos))
            s.commit()
            return

        for sv in servicios:
            ya = s.query(m.ServicioSede).filter_by(servicio_id=sv.id, sede_id=sede_id).first()
            if ya:
                continue
            modelo = (s.query(m.ServicioSede).filter_by(servicio_id=sv.id)
                      .order_by(m.ServicioSede.id).first())
            if modelo is None:
                continue
            s.add(m.ServicioSede(servicio_id=sv.id, sede_id=sede_id,
                                 precio=modelo.precio,
                                 duracion_minutos=modelo.duracion_minutos))
        s.commit()
    finally:
        s.close()


def servicios_de_sede(sede_id: int) -> list[dict]:
    """Lo que se ofrece en una sede, con su precio ahí, en el orden de la hoja."""
    s = _session()
    try:
        filas = (s.query(m.Servicio.id, m.Servicio.nombre, m.ServicioSede.precio,
                         m.ServicioSede.duracion_minutos)
                 .join(m.ServicioSede, m.ServicioSede.servicio_id == m.Servicio.id)
                 .filter(m.ServicioSede.sede_id == sede_id, m.Servicio.activo.is_(True))
                 .order_by(m.Servicio.orden, m.Servicio.id).all())
        return [{"id": i, "nombre": n, "precio": _suma(p), "minutos": d}
                for i, n, p, d in filas]
    finally:
        s.close()


def tabla_de_precios(sedes: list[tuple]) -> list[dict]:
    """[{id, nombre, precios: {sede_id: Decimal|None}}] para la pantalla Sedes."""
    s = _session()
    try:
        servicios = (s.query(m.Servicio).filter(m.Servicio.activo.is_(True))
                     .order_by(m.Servicio.orden, m.Servicio.id).all())
        precios = {(ss.servicio_id, ss.sede_id): _suma(ss.precio)
                   for ss in s.query(m.ServicioSede).all()}
        return [{"id": sv.id, "nombre": sv.nombre,
                 "precios": {sid: precios.get((sv.id, sid)) for sid, _ in sedes}}
                for sv in servicios]
    finally:
        s.close()


def cambiar_precio(persona: permisos.Persona, servicio_id: int, sede_id: int,
                   precio) -> bool:
    """
    El precio de un servicio en una sede. Devuelve si cambió algo. Queda en
    Actividad ("cambió un precio"): lo ya cobrado no cambia.
    """
    nuevo = _al_peso(dinero(precio))
    if nuevo <= 0 or nuevo > TOPE_MONTO:
        raise Error("Escribe un precio mayor que cero.")
    if not permisos.sede_permitida(persona, sede_id):
        raise Error("Esa sede no es tuya.")

    s = _session()
    try:
        sv = s.get(m.Servicio, servicio_id)
        sede = s.get(m.Sede, sede_id)
        if sv is None or sede is None:
            raise Error("Ese servicio ya no existe.")
        fila = s.query(m.ServicioSede).filter_by(servicio_id=servicio_id,
                                                 sede_id=sede_id).first()
        antes = _suma(fila.precio) if fila else None
        if antes == nuevo:
            return False
        if fila is None:
            fila = m.ServicioSede(servicio_id=servicio_id, sede_id=sede_id,
                                  precio=nuevo, duracion_minutos=30)
            s.add(fila)
        else:
            fila.precio = nuevo
        s.commit()
        nombre_sv, nombre_sede = sv.nombre, sede.nombre
    finally:
        s.close()

    detalle = (f"{nombre_sv} en {nombre_sede} pasó de {formato.pesos(antes)} a "
               f"{formato.pesos(nuevo)}. Lo ya cobrado no cambia." if antes is not None
               else f"{nombre_sv} en {nombre_sede} ahora cuesta {formato.pesos(nuevo)}.")
    cuentas.registrar("PRECIO", "cambió un precio", persona=persona, sede_id=sede_id,
                      tabla="barb_servicio_sede", registro_id=servicio_id,
                      antes={"precio": str(antes) if antes is not None else None},
                      despues={"precio": str(nuevo), "detalle": detalle})
    return True


def crear_servicio(persona: permisos.Persona, nombre: str, precio, minutos: int = 30) -> int:
    """Un servicio nuevo, con el mismo precio en todas las sedes."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise Error("Escribe el nombre del servicio.")
    valor = _al_peso(dinero(precio))
    if valor <= 0:
        raise Error("Escribe un precio mayor que cero.")
    s = _session()
    try:
        if s.query(m.Servicio).filter(func.lower(m.Servicio.nombre) == nombre.lower(),
                                      m.Servicio.activo.is_(True)).first():
            raise Error(f"Ya hay un servicio que se llama «{nombre}».")
        orden = (s.query(func.max(m.Servicio.orden)).scalar() or 0) + 1
        sv = m.Servicio(nombre=nombre[:100], orden=orden)
        s.add(sv)
        s.flush()
        for (sede_id,) in s.query(m.Sede.id).all():
            s.add(m.ServicioSede(servicio_id=sv.id, sede_id=sede_id, precio=valor,
                                 duracion_minutos=max(5, int(minutos or 30))))
        s.commit()
        nuevo_id = sv.id
    finally:
        s.close()
    cuentas.registrar("PRECIO", "agregó un servicio", persona=persona,
                      tabla="barb_servicios", registro_id=nuevo_id,
                      despues={"detalle": f"{nombre}, a {formato.pesos(valor)} en todas las sedes"})
    return nuevo_id


# ══════════════════════════════════════════════════════════════════════
#  CLIENTES
# ══════════════════════════════════════════════════════════════════════

def _contacto_por_telefono(s, telefono: str) -> int | None:
    """
    El contacto del bot con ese celular. El bot guarda el número de
    WhatsApp con el indicativo (573001112233); aquí llega como lo escribe
    alguien en el local (300 111 2233). Se casan por los últimos 10.
    """
    cola = telefono[-10:]
    fila = (s.query(database.Contact.id)
            .filter(database.Contact.phone.like(f"%{cola}")).first())
    return fila[0] if fila else None


def cliente_para(texto: str) -> int | None:
    """
    "Celular o nombre del cliente (opcional)". Con un celular que ya
    existe, su ficha; si no, una ficha nueva. Vacío = cliente de paso
    (decisión §11.5, provisional: se permite).
    """
    texto = (texto or "").strip()
    if not texto:
        return None
    s = _session()
    try:
        telefono = cuentas.telefono_normalizado(texto)
        if telefono:
            cli = s.query(m.ClienteBarberia).filter_by(telefono=telefono).first()
            if cli is None:
                legible = (f"{telefono[:3]} {telefono[3:6]} {telefono[6:]}"
                           if len(telefono) == 10 else telefono)
                cli = m.ClienteBarberia(nombre=legible, telefono=telefono,
                                        contact_id=_contacto_por_telefono(s, telefono))
                s.add(cli)
                s.commit()
            return cli.id

        nombre = " ".join(texto.split())[:100]
        cli = (s.query(m.ClienteBarberia)
               .filter(func.lower(m.ClienteBarberia.nombre) == nombre.lower()).first())
        if cli is None:
            cli = m.ClienteBarberia(nombre=nombre)
            s.add(cli)
            s.commit()
        return cli.id
    finally:
        s.close()


def guardar_nota_cliente(cliente_id: int, nota: str) -> None:
    """La nota de la ficha del cliente (la ve el barbero al atenderlo)."""
    s = _session()
    try:
        cli = s.get(m.ClienteBarberia, cliente_id)
        if cli is None:
            raise Error("Ese cliente no existe.")
        cli.notas = (nota or "").strip()[:500] or None
        s.commit()
    finally:
        s.close()


# ══════════════════════════════════════════════════════════════════════
#  CAJA
# ══════════════════════════════════════════════════════════════════════

def caja_abierta(s, sede_id: int):
    return (s.query(m.Caja).filter(m.Caja.sede_id == sede_id,
                                   m.Caja.cerrada_en.is_(None))
            .order_by(m.Caja.id.desc()).first())


def abrir_caja(persona: permisos.Persona, sede_id: int, base, automatica: bool = False) -> int:
    """Abre la caja de una sede. Una sola abierta por sede."""
    if not permisos.sede_permitida(persona, sede_id):
        raise Error("Esa sede no es tuya.")
    base = _al_peso(dinero(base))
    s = _session()
    try:
        if caja_abierta(s, sede_id):
            raise Error("La caja de esa sede ya está abierta.")
        caja = m.Caja(sede_id=sede_id, abierta_por=persona.personal_id, base_inicial=base)
        s.add(caja)
        s.commit()
        caja_id = caja.id
        sede = s.get(m.Sede, sede_id).nombre
    finally:
        s.close()
    detalle = (f"abrió la caja de {sede} al registrar un cobro (base {formato.pesos(0)})"
               if automatica else f"abrió la caja de {sede} con base {formato.pesos(base)}")
    cuentas.registrar("CAJA", detalle, persona=persona, sede_id=sede_id,
                      tabla="barb_cajas", registro_id=caja_id)
    return caja_id


def cuentas_de_caja(s, caja: m.Caja) -> dict:
    """
    Lo que entró y el arqueo de una caja. Los pagos de un servicio ANULADO
    no cuentan: ese dinero se devolvió o nunca entró.
    """
    filas = (s.query(m.Pago.metodo, func.sum(m.Pago.monto))
             .outerjoin(m.Cita, m.Cita.id == m.Pago.cita_id)
             .filter(m.Pago.caja_id == caja.id,
                     (m.Cita.id.is_(None)) | (m.Cita.estado != m.ANULADA))
             .group_by(m.Pago.metodo).all())
    por_metodo = {metodo: _suma(total) for metodo, total in filas}
    gastos = _suma(s.query(func.sum(m.Gasto.monto)).filter(m.Gasto.caja_id == caja.id).scalar())
    base = _suma(caja.base_inicial)
    efectivo = por_metodo.get(m.EFECTIVO, CERO)
    return {
        "vendido": sum(por_metodo.values(), CERO),
        "por_metodo": por_metodo,
        "base": base,
        "gastos": gastos,
        "esperado": base + efectivo - gastos,
    }


def cajas_de(persona: permisos.Persona, sede_id: int | None, hoy: date) -> list[dict]:
    """Una tarjeta por sede: la caja abierta, o la última cerrada hoy, o sin abrir."""
    desde, _ = formato.rango_utc(hoy, hoy + timedelta(days=1))
    sedes = [s for s in persona.sedes if sede_id in (None, s[0])]
    s = _session()
    try:
        salida = []
        nombres = {p.id: p.nombre for p in s.query(m.Personal).all()}
        for sid, nombre in sedes:
            caja = caja_abierta(s, sid) or (
                s.query(m.Caja).filter(m.Caja.sede_id == sid, m.Caja.abierta_en >= desde)
                .order_by(m.Caja.id.desc()).first())
            dato = {"sede_id": sid, "sede": nombre, "caja": None}
            if caja is not None:
                dato.update(caja=caja.id, abierta=caja.cerrada_en is None,
                            abierta_en=caja.abierta_en, cerrada_en=caja.cerrada_en,
                            abierta_por=nombres.get(caja.abierta_por, ""),
                            cerrada_por=nombres.get(caja.cerrada_por, ""),
                            contado=caja.efectivo_contado, diferencia=caja.diferencia,
                            **cuentas_de_caja(s, caja))
                if caja.cerrada_en is not None:
                    # Cerrada no se recalcula: lo que se guardó al cerrar.
                    dato["esperado"] = _suma(caja.efectivo_esperado)
            salida.append(dato)
        return salida
    finally:
        s.close()


def cerrar_caja(persona: permisos.Persona, caja_id: int, contado) -> Decimal:
    """
    Cierra con el arqueo. Guarda lo esperado, lo contado y la diferencia
    (contado − esperado: negativa es faltante). Devuelve la diferencia.
    """
    # Lo que escribe alguien llega como texto ("$394.000", con punto de
    # miles); lo que pasa el código, como número. Al texto solo se le
    # toman los dígitos; a un número no, o "241000.00" serían 24 millones.
    if isinstance(contado, (int, Decimal)):
        contado = _al_peso(Decimal(contado))
    else:
        texto = str(contado or "").strip()
        if not any(c.isdigit() for c in texto):
            raise Error("Escribe cuánto contaste.")
        contado = _al_peso(dinero(texto))
    s = _session()
    try:
        caja = s.get(m.Caja, caja_id)
        if caja is None or not permisos.sede_permitida(persona, caja.sede_id):
            raise Error("Esa caja no es de tus sedes.")
        if caja.cerrada_en is not None:
            raise Error("Esa caja ya está cerrada.")
        esperado = cuentas_de_caja(s, caja)["esperado"]
        caja.efectivo_esperado = esperado
        caja.efectivo_contado = contado
        caja.diferencia = contado - esperado
        caja.cerrada_en = m.ahora()
        caja.cerrada_por = persona.personal_id
        s.commit()
        diferencia, sede_id = contado - esperado, caja.sede_id
        sede = s.get(m.Sede, sede_id).nombre
    finally:
        s.close()

    if diferencia == 0:
        verbo = "cerró la caja"
    elif diferencia < 0:
        verbo = "cerró la caja con faltante"
    else:
        verbo = "cerró la caja con sobrante"
    cuentas.registrar("CAJA", verbo, persona=persona, sede_id=sede_id,
                      tabla="barb_cajas", registro_id=caja_id,
                      despues={"detalle": f"Debía haber {formato.pesos(esperado)} en "
                                          f"efectivo y contó {formato.pesos(contado)}",
                               "sede": sede})
    return diferencia


# ══════════════════════════════════════════════════════════════════════
#  COBRAR Y ANULAR
# ══════════════════════════════════════════════════════════════════════

def _porcentaje(s, barbero: m.Personal, servicio_id: int) -> Decimal:
    """Lo del barbero en ese servicio: su excepción, su esquema o su comisión."""
    if barbero.esquema_pago == m.ALQUILER_SILLA:
        return Decimal("100")
    propio = (s.query(m.ComisionServicio.porcentaje)
              .filter_by(personal_id=barbero.id, servicio_id=servicio_id).scalar())
    return _suma(propio if propio is not None else barbero.comision_defecto)


def cobrar(persona: permisos.Persona, sede_id: int, servicio_ids: list[int],
           metodo: str, propina=0, efectivo_dividido=None,
           cliente: str = "", cita_id: int | None = None) -> tuple[int, Decimal]:
    """
    Registra un servicio ya hecho. Devuelve `(cita_id, lo que le toca al
    barbero)`.

    Sin `cita_id` es un cliente sin cita: se crea la visita, como si hubiera
    TERMINADO ahora (empezó hace lo que dura el servicio), para no ocupar en
    la agenda un rato que todavía no ha pasado. Con `cita_id` se cobra esa
    cita agendada (Fase 2): pasa a completada con lo que de verdad se hizo.

    El barbero es quien registra (Fase 1: el barbero registra lo suyo).

    Si la caja de la sede está cerrada, SE ABRE SOLA con base $0 a nombre de
    quien cobra y queda en Actividad. Es la opción que el handoff pone
    primero (6.4); la decisión sigue abierta.
    """
    if not servicio_ids:
        raise Error("Elige qué le hiciste.")
    if metodo not in METODOS_COBRO:
        raise Error("Elige cómo pagó.")
    if not permisos.sede_permitida(persona, sede_id):
        raise Error("No trabajas en esa sede.")
    propina = _al_peso(dinero(propina))
    if propina < 0 or propina > TOPE_MONTO:
        raise Error("La propina no es válida.")

    catalogo = {sv["id"]: sv for sv in servicios_de_sede(sede_id)}
    elegidos = [catalogo[i] for i in dict.fromkeys(servicio_ids) if i in catalogo]
    if len(elegidos) != len(set(servicio_ids)):
        raise Error("Uno de los servicios ya no se ofrece en esa sede.")

    subtotal = sum((sv["precio"] for sv in elegidos), CERO)
    total = subtotal + propina

    if metodo == "dividido":
        efectivo = _al_peso(dinero(efectivo_dividido))
        if efectivo <= 0 or efectivo >= total:
            raise Error(f"En un pago dividido, el efectivo va entre $1 y "
                        f"{formato.pesos(total - 1)}.")
        partes = [(m.EFECTIVO, efectivo), (m.TRANSFERENCIA, total - efectivo)]
    else:
        partes = [({"efectivo": m.EFECTIVO, "transferencia": m.TRANSFERENCIA,
                    "tarjeta": m.TARJETA}[metodo], total)]

    cliente_id = cliente_para(cliente)
    if cita_id is not None:
        s = _session()
        try:
            agendada = s.get(m.Cita, cita_id)
            if (agendada is None or agendada.barbero_id != persona.personal_id
                    or agendada.sede_id != sede_id):
                raise Error("Esa cita no es tuya.")
            if agendada.estado not in (m.PENDIENTE, m.CONFIRMADA, m.EN_CURSO):
                raise Error("Esa cita ya se cobró o se canceló.")
            cliente_id = agendada.cliente_id or cliente_id
        finally:
            s.close()

    s = _session()
    try:
        caja = caja_abierta(s, sede_id)
    finally:
        s.close()
    if caja is None:
        abrir_caja(persona, sede_id, 0, automatica=True)

    s = _session()
    try:
        caja = caja_abierta(s, sede_id)
        barbero = s.get(m.Personal, persona.personal_id)
        ahora = m.ahora()
        minutos = sum(sv["minutos"] for sv in elegidos)
        if cita_id is not None:
            cita = s.get(m.Cita, cita_id)
            cita.estado = m.COMPLETADA
            cita.propina = propina
            cita.cliente_id = cliente_id
        else:
            cita = m.Cita(sede_id=sede_id, barbero_id=barbero.id, cliente_id=cliente_id,
                          inicio=ahora - timedelta(minutes=minutos), fin=ahora,
                          estado=m.COMPLETADA, origen=m.WALK_IN, propina=propina,
                          registrada_por=persona.personal_id)
            s.add(cita)
        s.flush()

        parte = propina
        for sv in elegidos:
            pct = _porcentaje(s, barbero, sv["id"])
            suyo = _al_peso(sv["precio"] * pct / 100)
            s.add(m.CitaServicio(cita_id=cita.id, servicio_id=sv["id"], nombre=sv["nombre"],
                                 precio=sv["precio"], porcentaje_barbero=pct,
                                 monto_barbero=suyo, monto_barberia=sv["precio"] - suyo))
            parte += suyo
        for metodo_bd, monto in partes:
            s.add(m.Pago(caja_id=caja.id, cita_id=cita.id, metodo=metodo_bd, monto=monto))
        s.commit()
        cita_id = cita.id
    finally:
        s.close()

    nombres = ", ".join(sv["nombre"] for sv in elegidos)
    cuentas.registrar("SERVICIO", "registró un servicio", persona=persona, sede_id=sede_id,
                      tabla="barb_citas", registro_id=cita_id,
                      despues={"detalle": f"{nombres} por {formato.pesos(total)}"})
    return cita_id, parte


def anular(persona: permisos.Persona, cita_id: int, motivo: str, hoy: date) -> None:
    """
    Anula un servicio cobrado. No se borra: queda con el motivo y en
    Actividad. Un barbero solo anula los suyos del día; después, solo el
    dueño o el administrador de esa sede.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise Error("Elige por qué lo anulas.")
    s = _session()
    try:
        cita = s.get(m.Cita, cita_id)
        if cita is None or not permisos.sede_permitida(persona, cita.sede_id):
            raise Error("Ese servicio no existe.")
        if persona.rol == m.BARBERO:
            if cita.barbero_id != persona.personal_id:
                raise Error("Ese servicio no existe.")
            if formato.a_local(cita.inicio).date() != hoy:
                raise Error("Solo puedes anular los servicios de hoy. Pídeselo al dueño.")
        elif persona.rol == m.RECEPCION:
            raise Error("Pídele al dueño o al administrador que lo anule.")
        if cita.estado == m.ANULADA:
            raise Error("Ese servicio ya estaba anulado.")
        cita.estado = m.ANULADA
        cita.motivo_anulacion = motivo[:300]
        cita.anulada_en = m.ahora()
        s.commit()
        servicios = [cs.nombre for cs in s.query(m.CitaServicio).filter_by(cita_id=cita_id)]
        total = _suma(s.query(func.sum(m.Pago.monto)).filter_by(cita_id=cita_id).scalar())
        registrada = formato.hora(cita.inicio)
        sede_id = cita.sede_id
    finally:
        s.close()
    cuentas.registrar("ANULACION", "anuló un servicio", persona=persona, sede_id=sede_id,
                      tabla="barb_citas", registro_id=cita_id, motivo=motivo[:300],
                      despues={"detalle": f"{', '.join(servicios)} de {formato.pesos(total)}, "
                                          f"registrado a las {registrada}"})


def servicios_del_dia(personal_id: int, hoy: date) -> list[dict]:
    """"Ya hiciste": lo de hoy de un barbero, del más reciente al más antiguo."""
    desde, hasta = formato.rango_utc(hoy, hoy + timedelta(days=1))
    s = _session()
    try:
        citas = (s.query(m.Cita).filter(m.Cita.barbero_id == personal_id,
                                        m.Cita.inicio >= desde, m.Cita.inicio < hasta,
                                        m.Cita.estado.in_((m.COMPLETADA, m.ANULADA)))
                 .order_by(m.Cita.inicio.desc(), m.Cita.id.desc()).all())
        salida = []
        for c in citas:
            servicios = s.query(m.CitaServicio).filter_by(cita_id=c.id).all()
            pagos = s.query(m.Pago).filter_by(cita_id=c.id).all()
            cliente = s.get(m.ClienteBarberia, c.cliente_id) if c.cliente_id else None
            metodos = {p.metodo for p in pagos}
            salida.append({
                "id": c.id,
                "inicio": c.inicio,
                "cliente": cliente.nombre if cliente else "Cliente de paso",
                "servicios": ", ".join(cs.nombre for cs in servicios),
                "metodo": "Dividido" if len(metodos) > 1 else
                          NOMBRE_METODO.get(next(iter(metodos), ""), ""),
                "total": sum((_suma(p.monto) for p in pagos), CERO),
                "suyo": sum((_suma(cs.monto_barbero) for cs in servicios), CERO)
                        + _suma(c.propina),
                "propina": _suma(c.propina),
                "anulada": c.estado == m.ANULADA,
                "motivo": c.motivo_anulacion or "",
            })
        return salida
    finally:
        s.close()


# ══════════════════════════════════════════════════════════════════════
#  GASTOS
# ══════════════════════════════════════════════════════════════════════

def registrar_gasto(persona: permisos.Persona, sede_id: int, descripcion: str, monto,
                    categoria: str, tipo: str, de_la_caja: bool, hoy: date) -> int:
    descripcion = " ".join((descripcion or "").split())
    valor = _al_peso(dinero(monto))
    if not descripcion:
        raise Error("Escribe en qué se gastó.")
    if valor <= 0 or valor > TOPE_MONTO:
        raise Error("Escribe un monto mayor que cero.")
    if not permisos.sede_permitida(persona, sede_id):
        raise Error("Elige una de tus sedes.")
    if categoria not in CATEGORIAS_GASTO:
        categoria = "Insumos"
    tipo = "FIJO" if tipo == "FIJO" else "VARIABLE"

    s = _session()
    try:
        caja_id = None
        if de_la_caja:
            caja = caja_abierta(s, sede_id)
            if caja is None:
                raise Error("La caja de esa sede está cerrada. Ábrela o registra el "
                            "gasto sin marcar «Pagado de la caja».")
            caja_id = caja.id
        gasto = m.Gasto(sede_id=sede_id, caja_id=caja_id, descripcion=descripcion[:255],
                        categoria=categoria, tipo=tipo, monto=valor, fecha=hoy,
                        registrado_por=persona.personal_id)
        s.add(gasto)
        s.commit()
        return gasto.id
    finally:
        s.close()


def gastos_de(sede_id: int | None, sedes: tuple, desde: date, hasta: date) -> list[dict]:
    """Los gastos de [desde, hasta), los más recientes primero."""
    ids = [s[0] for s in sedes if sede_id in (None, s[0])]
    nombres = dict(sedes)
    s = _session()
    try:
        filas = (s.query(m.Gasto).filter(m.Gasto.sede_id.in_(ids), m.Gasto.fecha >= desde,
                                         m.Gasto.fecha < hasta)
                 .order_by(m.Gasto.fecha.desc(), m.Gasto.id.desc()).all())
        return [{"id": g.id, "descripcion": g.descripcion, "categoria": g.categoria,
                 "tipo": "Fijo" if g.tipo == "FIJO" else "Variable",
                 "sede": nombres.get(g.sede_id, ""), "fecha": g.fecha,
                 "monto": _suma(g.monto), "de_la_caja": g.caja_id is not None}
                for g in filas]
    finally:
        s.close()
