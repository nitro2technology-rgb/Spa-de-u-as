"""
LAS TABLAS DE LA BARBERÍA
==========================
Todas llevan `client_id` y entran en `database.MODELOS_DEL_INQUILINO`, así
que tienen las DOS cerraduras del proyecto: el filtro del ORM y su
política de Row-Level Security (migración `e1b5c3a7d902`). Si agregas una
tabla aquí, agrégala también a `MODELOS` de abajo y a la migración, o
quedará sin la segunda cerradura sin que nada lo diga.

POR QUÉ `barb_` Y NO UN ESQUEMA DE POSTGRES
-------------------------------------------
La especificación proponía un esquema `barberia`. Se usa un prefijo en su
lugar porque las pruebas corren sobre SQLite, que no tiene esquemas, y
porque `database.tablas_sin_cerradura()` solo revisa `current_schema()`:
en otro esquema, una tabla sin política pasaría la comprobación.

FASE 0
------
Solo las tablas que necesitan la entrada y los roles: sedes, personal,
en qué sedes trabaja cada quien, la actividad y los enlaces de
recuperación. Las de citas, caja, pagos, gastos e inventario llegan con
sus pantallas (Fase 1 y 2 de la especificación).

LAS FECHAS
----------
`DateTime(timezone=True)`, como pide la especificación, y siempre en UTC
(`ahora()`). SQLite las devuelve sin zona; `en_utc()` las normaliza
antes de comparar, o `aware < naive` revienta con TypeError.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, Time, UniqueConstraint,
)

from app.core import database
from app.core.database import Base, JSONPortable, columna_cliente


def ahora() -> datetime:
    """El instante actual en UTC, con zona."""
    return datetime.now(timezone.utc)


def en_utc(momento: datetime | None) -> datetime | None:
    """Una fecha leída de la base, con zona UTC aunque SQLite se la quite."""
    if momento is None or momento.tzinfo is not None:
        return momento
    return momento.replace(tzinfo=timezone.utc)


# ── Roles ────────────────────────────────────────────────────────────
# Lo que se guarda en `barb_personal.rol`. Los nombres en pantalla están
# en `permisos.ROLES`.
DUENO = "DUENO"
ADMIN = "ADMIN"            # administrador de sede (lo agregó el diseño)
RECEPCION = "RECEPCION"
BARBERO = "BARBERO"
ROLES = (DUENO, ADMIN, RECEPCION, BARBERO)

# Cómo se le paga a un barbero.
COMISION = "COMISION"
FIJO_MAS_COMISION = "FIJO_MAS_COMISION"
ALQUILER_SILLA = "ALQUILER_SILLA"
ESQUEMAS_DE_PAGO = (COMISION, FIJO_MAS_COMISION, ALQUILER_SILLA)

# Dinero: DECIMAL, nunca FLOAT (§7 de la especificación). Numeric de
# SQLAlchemy devuelve `Decimal`.
Dinero = Numeric(12, 2)
Porcentaje = Numeric(5, 2)


class Sede(Base):
    """Un local de la barbería."""
    __tablename__ = "barb_sedes"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    nombre = Column(String(100), nullable=False)
    direccion = Column(Text, nullable=True)
    telefono = Column(String(20), nullable=True)
    # Las horas se muestran en la zona de la sede; se guardan en UTC.
    zona_horaria = Column(String(50), nullable=False, default="America/Bogota",
                          server_default="America/Bogota")
    # "abierta al público / pausada" en la pantalla de Sedes. Pausar una
    # sede no borra nada.
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=ahora)


class Personal(Base):
    """
    Una persona de la barbería: dueño, administrador de sede, recepción o
    barbero.

    Su ACCESO (usuario y clave) es una fila de `panel_users`, la misma
    tabla del panel del bot (decisión §11.4 de la especificación). Aquí va
    lo que es de la barbería: el rol, el esquema de pago, sus sedes.

        ⚠️  `panel_users.rol` NO es este rol.

    Allí dice qué puede hacer en el panel del BOT: "dueno" lo ve todo.
    Solo el DUEÑO de la barbería va con "dueno" (si su plan trae el bot,
    atiende las conversaciones); el resto va con "barberia", que
    `equipo.de_pase` deja fuera de /admin. Sin eso, cualquier barbero
    entraría a las conversaciones del bot como si fuera el dueño.
    """
    __tablename__ = "barb_personal"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    panel_user_id = Column(Integer, ForeignKey("panel_users.id"), nullable=True)

    nombre = Column(String(100), nullable=False)
    # Para recuperar la clave y para entrar sin acordarse del usuario.
    correo = Column(String(120), nullable=True)
    telefono = Column(String(20), nullable=True)     # solo dígitos

    rol = Column(String(20), nullable=False, default=BARBERO)

    esquema_pago = Column(String(20), nullable=False, default=COMISION)
    comision_defecto = Column(Porcentaje, nullable=False, default=50)
    sueldo_fijo = Column(Dinero, nullable=False, default=0)
    alquiler_silla = Column(Dinero, nullable=False, default=0)
    # La meta de la quincena que ve el barbero en "Mis ganancias".
    meta_quincena = Column(Dinero, nullable=True)

    # La puso el dueño o el super-admin: al primer ingreso se exige
    # cambiarla, y hasta entonces no se abre ninguna otra pantalla.
    clave_temporal = Column(Boolean, nullable=False, default=False)

    # El interruptor de "Acceso" en Usuarios. Apagado no puede entrar,
    # pero sigue en la lista.
    activo = Column(Boolean, nullable=False, default=True)
    # "Quitar" es un borrado LÓGICO: la actividad y los cobros apuntan a
    # esta fila, así que no se puede borrar.
    eliminado_en = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ahora)

    __table_args__ = (
        CheckConstraint("rol IN ('DUENO','ADMIN','RECEPCION','BARBERO')",
                        name="ck_barb_personal_rol"),
        CheckConstraint(
            "esquema_pago IN ('COMISION','FIJO_MAS_COMISION','ALQUILER_SILLA')",
            name="ck_barb_personal_esquema"),
    )


class PersonalSede(Base):
    """En qué sedes trabaja cada quien. Un barbero puede rotar entre varias."""
    __tablename__ = "barb_personal_sede"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    personal_id = Column(Integer, ForeignKey("barb_personal.id"), nullable=False)
    sede_id = Column(Integer, ForeignKey("barb_sedes.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("personal_id", "sede_id", name="uq_barb_personal_sede"),
    )


class Actividad(Base):
    """
    Quién hizo qué. Nada se borra ni se edita aquí: es la pantalla
    Actividad del dueño (`barberia.auditoria` en la especificación).

    `actor` es el nombre tal como se enseña, y se guarda aparte del
    `personal_id` a propósito: "Nitro2Tech (soporte)" no es una persona de
    la barbería, y el nombre de alguien que se quitó tiene que seguir
    leyéndose igual.
    """
    __tablename__ = "barb_actividad"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    personal_id = Column(Integer, ForeignKey("barb_personal.id"), nullable=True)
    actor = Column(String(120), nullable=False)
    accion = Column(String(40), nullable=False)      # ver ACCIONES en cuentas.py
    tabla = Column(String(50), nullable=True)
    registro_id = Column(Integer, nullable=True)
    sede_id = Column(Integer, ForeignKey("barb_sedes.id"), nullable=True)
    detalle = Column(Text, nullable=True)
    motivo = Column(Text, nullable=True)
    antes = Column(JSONPortable, nullable=True)
    despues = Column(JSONPortable, nullable=True)
    created_at = Column(DateTime(timezone=True), default=ahora, index=True)


class Recuperacion(Base):
    """
    Un enlace de "Olvidé mi contraseña".

    Se guarda el HASH del token, no el token: quien lea la base no puede
    usar los enlaces vigentes. Un solo uso y 30 minutos.
    """
    __tablename__ = "barb_recuperaciones"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    personal_id = Column(Integer, ForeignKey("barb_personal.id"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    vence_en = Column(DateTime(timezone=True), nullable=False)
    usado_en = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ahora)


# ══════════════════════════════════════════════════════════════════════
#  FASE 1: catálogo, clientes, cobros, caja, gastos y nómina
#  (migración `f2c6d4b8e013`)
# ══════════════════════════════════════════════════════════════════════

class Servicio(Base):
    """Lo que se hace en la silla: "Corte clásico", "Barba"… El precio va por sede."""
    __tablename__ = "barb_servicios"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    nombre = Column(String(100), nullable=False)
    # El orden en la hoja de cobro del barbero: los más usados primero.
    orden = Column(Integer, nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True)


class ServicioSede(Base):
    """Precio y duración de un servicio en UNA sede. Sin fila, no se ofrece ahí."""
    __tablename__ = "barb_servicio_sede"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    servicio_id = Column(Integer, ForeignKey("barb_servicios.id"), nullable=False)
    sede_id = Column(Integer, ForeignKey("barb_sedes.id"), nullable=False)
    precio = Column(Dinero, nullable=False)
    duracion_minutos = Column(Integer, nullable=False, default=30)

    __table_args__ = (
        UniqueConstraint("servicio_id", "sede_id", name="uq_barb_servicio_sede"),
    )


class ComisionServicio(Base):
    """La excepción a `Personal.comision_defecto` para un servicio. Manda sobre ella."""
    __tablename__ = "barb_comision_servicio"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    personal_id = Column(Integer, ForeignKey("barb_personal.id"), nullable=False)
    servicio_id = Column(Integer, ForeignKey("barb_servicios.id"), nullable=False)
    porcentaje = Column(Porcentaje, nullable=False)

    __table_args__ = (
        UniqueConstraint("personal_id", "servicio_id", name="uq_barb_comision_servicio"),
    )


class ClienteBarberia(Base):
    """
    Quien se sienta en la silla. Se vincula al contacto del bot por el
    celular, para que el historial de conversación y el de cortes sean de
    la misma persona (§6.5 de la especificación).
    """
    __tablename__ = "barb_clientes"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    nombre = Column(String(100), nullable=False)
    telefono = Column(String(20), nullable=True)     # solo dígitos
    correo = Column(String(120), nullable=True)
    barbero_preferido_id = Column(Integer, ForeignKey("barb_personal.id"), nullable=True)
    notas = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=ahora)

    __table_args__ = (
        UniqueConstraint("client_id", "telefono", name="uq_barb_clientes_telefono"),
    )


# Estados de una cita. Los nombres de pantalla están en `operacion.py`.
PENDIENTE = "PENDIENTE"
CONFIRMADA = "CONFIRMADA"
EN_CURSO = "EN_CURSO"
COMPLETADA = "COMPLETADA"
CANCELADA = "CANCELADA"
NO_ASISTIO = "NO_ASISTIO"
ANULADA = "ANULADA"
ESTADOS_CITA = (PENDIENTE, CONFIRMADA, EN_CURSO, COMPLETADA, CANCELADA,
                NO_ASISTIO, ANULADA)

WALK_IN = "WALK_IN"
PANEL = "PANEL"
WHATSAPP = "WHATSAPP"
WEB = "WEB"
ORIGENES = (WALK_IN, PANEL, WHATSAPP, WEB)


class Cita(Base):
    """
    Una visita: agendada o de alguien que llegó sin cita. Es la ÚNICA
    agenda de la barbería (§6.1): aquí caen las del bot, las del panel y
    los clientes sin cita que registra el barbero.

    La propina va en la cita y no en el pago: un pago dividido la contaría
    dos veces. Va 100% al barbero.
    """
    __tablename__ = "barb_citas"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    sede_id = Column(Integer, ForeignKey("barb_sedes.id"), nullable=False)
    barbero_id = Column(Integer, ForeignKey("barb_personal.id"), nullable=False)
    cliente_id = Column(Integer, ForeignKey("barb_clientes.id"), nullable=True)
    inicio = Column(DateTime(timezone=True), nullable=False, index=True)
    fin = Column(DateTime(timezone=True), nullable=False)
    estado = Column(String(20), nullable=False, default=PENDIENTE)
    origen = Column(String(20), nullable=False, default=WALK_IN)
    propina = Column(Dinero, nullable=False, default=0)
    # Quién la registró, que no tiene por qué ser el barbero: recepción.
    registrada_por = Column(Integer, ForeignKey("barb_personal.id"), nullable=True)
    motivo_anulacion = Column(Text, nullable=True)
    anulada_en = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ahora)

    # ── Fase 2: la agenda ──
    # Lo que se reservó (una cita del bot o del panel). Al cobrar, la hoja
    # lo trae marcado; lo que de verdad se hizo queda en `barb_cita_servicios`.
    servicio_id = Column(Integer, ForeignKey("barb_servicios.id"), nullable=True)
    # Cuándo salió el recordatorio: uno por cita, no uno por revisión.
    recordatorio_en = Column(DateTime(timezone=True), nullable=True)
    # Por qué se canceló ("El cliente canceló por WhatsApp").
    motivo_cancelacion = Column(String(200), nullable=True)

    __table_args__ = (
        CheckConstraint("estado IN ('PENDIENTE','CONFIRMADA','EN_CURSO','COMPLETADA',"
                        "'CANCELADA','NO_ASISTIO','ANULADA')", name="ck_barb_citas_estado"),
        CheckConstraint("origen IN ('WALK_IN','PANEL','WHATSAPP','WEB')",
                        name="ck_barb_citas_origen"),
    )


class CitaServicio(Base):
    """
    Lo que se le hizo en esa visita, con el precio y el porcentaje
    CONGELADOS al cobrar: cambiar el precio del catálogo o la comisión del
    barbero no toca lo ya cobrado ni las liquidaciones.
    """
    __tablename__ = "barb_cita_servicios"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    cita_id = Column(Integer, ForeignKey("barb_citas.id"), nullable=False, index=True)
    servicio_id = Column(Integer, ForeignKey("barb_servicios.id"), nullable=False)
    nombre = Column(String(100), nullable=False)     # también congelado
    precio = Column(Dinero, nullable=False)
    porcentaje_barbero = Column(Porcentaje, nullable=False)
    monto_barbero = Column(Dinero, nullable=False)
    monto_barberia = Column(Dinero, nullable=False)


class Caja(Base):
    """
    La caja de una sede en un día. Se cierra con el arqueo: lo que debería
    haber en efectivo contra lo que se contó. Cerrada no se edita.
    """
    __tablename__ = "barb_cajas"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    sede_id = Column(Integer, ForeignKey("barb_sedes.id"), nullable=False)
    abierta_por = Column(Integer, ForeignKey("barb_personal.id"), nullable=False)
    abierta_en = Column(DateTime(timezone=True), nullable=False, default=ahora)
    base_inicial = Column(Dinero, nullable=False, default=0)
    cerrada_por = Column(Integer, ForeignKey("barb_personal.id"), nullable=True)
    cerrada_en = Column(DateTime(timezone=True), nullable=True)
    efectivo_esperado = Column(Dinero, nullable=True)
    efectivo_contado = Column(Dinero, nullable=True)
    diferencia = Column(Dinero, nullable=True)
    observaciones = Column(Text, nullable=True)


EFECTIVO = "EFECTIVO"
TRANSFERENCIA = "TRANSFERENCIA"
TARJETA = "TARJETA"
OTRO = "OTRO"
METODOS = (EFECTIVO, TRANSFERENCIA, TARJETA, OTRO)


class Pago(Base):
    """
    Una parte de lo que se cobró. Un pago dividido son dos filas: cada parte
    suma a su método, y el arqueo solo cuenta la de efectivo. El monto
    incluye la propina (es lo que entró a la caja).
    """
    __tablename__ = "barb_pagos"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    caja_id = Column(Integer, ForeignKey("barb_cajas.id"), nullable=False, index=True)
    cita_id = Column(Integer, ForeignKey("barb_citas.id"), nullable=True, index=True)
    metodo = Column(String(20), nullable=False)
    monto = Column(Dinero, nullable=False)
    created_at = Column(DateTime(timezone=True), default=ahora)

    __table_args__ = (
        CheckConstraint("metodo IN ('EFECTIVO','TRANSFERENCIA','TARJETA','OTRO')",
                        name="ck_barb_pagos_metodo"),
    )


class Gasto(Base):
    """Arriendo, servicios, insumos… Si salió de la caja, resta del arqueo."""
    __tablename__ = "barb_gastos"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    sede_id = Column(Integer, ForeignKey("barb_sedes.id"), nullable=False)
    caja_id = Column(Integer, ForeignKey("barb_cajas.id"), nullable=True)
    descripcion = Column(String(255), nullable=False)
    categoria = Column(String(50), nullable=True)
    tipo = Column(String(10), nullable=False, default="VARIABLE")
    monto = Column(Dinero, nullable=False)
    fecha = Column(Date, nullable=False)
    registrado_por = Column(Integer, ForeignKey("barb_personal.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ahora)

    __table_args__ = (
        CheckConstraint("tipo IN ('FIJO','VARIABLE')", name="ck_barb_gastos_tipo"),
    )


class Adelanto(Base):
    """Plata que se le adelantó a alguien y se descuenta de su liquidación."""
    __tablename__ = "barb_adelantos"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    personal_id = Column(Integer, ForeignKey("barb_personal.id"), nullable=False)
    monto = Column(Dinero, nullable=False)
    fecha = Column(Date, nullable=False)
    nota = Column(String(200), nullable=True)
    # Se llena al APROBAR la liquidación que lo descuenta.
    liquidacion_id = Column(Integer, ForeignKey("barb_liquidaciones.id"), nullable=True)
    registrado_por = Column(Integer, ForeignKey("barb_personal.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ahora)


BORRADOR = "BORRADOR"
APROBADA = "APROBADA"
PAGADA = "PAGADA"


class Liquidacion(Base):
    """
    Lo que se le paga a alguien en una quincena. Mientras está en borrador
    no hay fila: se calcula en vivo. Al APROBARLA se guardan las cifras
    (quedan congeladas) y se le ligan los adelantos. PAGADA es final.
    """
    __tablename__ = "barb_liquidaciones"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    personal_id = Column(Integer, ForeignKey("barb_personal.id"), nullable=False)
    periodo_inicio = Column(Date, nullable=False)
    periodo_fin = Column(Date, nullable=False)
    total_servicios = Column(Dinero, nullable=False)
    total_comisiones = Column(Dinero, nullable=False)
    total_propinas = Column(Dinero, nullable=False)
    total_productos = Column(Dinero, nullable=False, default=0)
    sueldo_fijo = Column(Dinero, nullable=False, default=0)
    descuentos = Column(Dinero, nullable=False, default=0)
    total_a_pagar = Column(Dinero, nullable=False)
    estado = Column(String(20), nullable=False, default=APROBADA)
    aprobada_en = Column(DateTime(timezone=True), nullable=True)
    pagada_en = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ahora)

    __table_args__ = (
        UniqueConstraint("personal_id", "periodo_inicio", name="uq_barb_liquidacion_periodo"),
        CheckConstraint("estado IN ('BORRADOR','APROBADA','PAGADA')",
                        name="ck_barb_liquidaciones_estado"),
    )


# ══════════════════════════════════════════════════════════════════════
#  FASE 2: la agenda (migración `a4d7e9b2c015`)
# ══════════════════════════════════════════════════════════════════════

class Horario(Base):
    """
    Cuándo se atiende, por día de la semana, en la hora LOCAL de la sede.

    Con `personal_id` vacío es el horario de la SEDE; con él, el de ese
    barbero en esa sede. Un barbero sin filas propias trabaja el horario de
    la sede. Varias filas el mismo día son varios tramos (mañana y tarde).
    """
    __tablename__ = "barb_horarios"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    sede_id = Column(Integer, ForeignKey("barb_sedes.id"), nullable=False)
    personal_id = Column(Integer, ForeignKey("barb_personal.id"), nullable=True)
    dia_semana = Column(Integer, nullable=False)        # 0 lunes … 6 domingo
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)

    __table_args__ = (
        CheckConstraint("dia_semana BETWEEN 0 AND 6", name="ck_barb_horarios_dia"),
    )


class Bloqueo(Base):
    """
    Un rato en que no se agenda: almuerzo, vacaciones, un festivo.

    Con `personal_id` es de ese barbero; sin él, de toda la `sede_id`.
    """
    __tablename__ = "barb_bloqueos"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    sede_id = Column(Integer, ForeignKey("barb_sedes.id"), nullable=True)
    personal_id = Column(Integer, ForeignKey("barb_personal.id"), nullable=True)
    inicio = Column(DateTime(timezone=True), nullable=False, index=True)
    fin = Column(DateTime(timezone=True), nullable=False)
    motivo = Column(String(100), nullable=True)
    creado_por = Column(Integer, ForeignKey("barb_personal.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=ahora)


# Las que entran en `database.MODELOS_DEL_INQUILINO` y en las migraciones
# de RLS. Mantener las listas iguales: `tests/test_barberia.py` lo vigila.
MODELOS_FASE_0 = (Sede, Personal, PersonalSede, Actividad, Recuperacion)
MODELOS_FASE_1 = (Servicio, ServicioSede, ComisionServicio, ClienteBarberia, Cita,
                  CitaServicio, Caja, Pago, Gasto, Adelanto, Liquidacion)
MODELOS_FASE_2 = (Horario, Bloqueo)
MODELOS = MODELOS_FASE_0 + MODELOS_FASE_1 + MODELOS_FASE_2


def _registrar():
    """
    Suma estas tablas a `database.MODELOS_DEL_INQUILINO`: el filtro del ORM
    y la comprobación de RLS leen esa tupla en cada uso, no al importar.
    Una sola vez aunque el módulo se cargue por los dos caminos.
    """
    if Sede not in database.MODELOS_DEL_INQUILINO:
        database.MODELOS_DEL_INQUILINO = database.MODELOS_DEL_INQUILINO + MODELOS


_registrar()
