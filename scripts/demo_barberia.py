"""
DATOS DE DEMOSTRACIÓN DEL PANEL DE BARBERÍAS
============================================
Siembra "Filo Barbería" (tres sedes, siete personas y tres semanas de
trabajo) y "Navaja Club" (pausada), en la base que diga `DATABASE_URL`.

Lo usan dos caminos:

  · `scripts/servir_barberia.py`, que levanta el panel en local con un
    SQLite temporal (lo importa después de fijar su base).
  · A mano, contra la base de una DEMO en Render:

        DATABASE_URL="postgresql://…(External Database URL)…"             python scripts/demo_barberia.py --si

    ⚠️  NUNCA contra la base de producción del bot: escribe dos negocios
    enteros. Por eso pide `--si`, y se niega si ya hay una "Filo Barbería"
    o si la base no la creó Alembic todavía (ver §3.8 de CONTINUAR_AQUI:
    una base estrenada por `create_all` deja a Alembic sin constancia y el
    siguiente despliegue no arranca). Primero se despliega el servicio, que
    corre `alembic upgrade head`, y después se siembra.

Quién hay y con qué clave: ver la cabecera de `servir_barberia.py`.
"""

import os
import random
import sys
from datetime import date, timedelta
from decimal import Decimal

PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROYECTO)

from app.core import acceso, database, planes, tenencia    # noqa: E402
from app.barberia import cuentas, formato, nomina, operacion  # noqa: E402
from app.barberia import modelos as m                          # noqa: E402

CLAVE = "filo2026"


def _cliente(slug, nombre, plan, activo=True, **extra) -> int:
    session = database.SessionLocal()
    try:
        c = database.Client(slug=slug, nombre=nombre, active=activo, plan=plan,
                            barberia_contratada=True,
                            bot_contratado=planes.PLANES[plan].bot,
                            ia_contratada=planes.PLANES[plan].ia,
                            proveedor_agenda="barberia", **extra)
        session.add(c)
        session.commit()
        return c.id
    finally:
        session.close()


def _persona(client_id: int, personal_id: int):
    """La `Persona` de alguien, como la vería el panel si entrara."""
    session = database.get_session()
    try:
        user_id = session.get(m.Personal, personal_id).panel_user_id
    finally:
        session.close()
    return cuentas.persona_de(acceso.Pase(client_id, user_id, 0))


# Las combinaciones que se cobran, por posición en el catálogo inicial
# (0 corte, 1 corte + barba, 2 barba, 3 cejas, 4 tintura, 5 lavado).
COMBOS = ([0], [0], [0], [1], [1], [2], [0, 3], [4], [1, 5], [2, 3])
METODOS = (m.EFECTIVO, m.EFECTIVO, m.TRANSFERENCIA, m.TRANSFERENCIA, m.TARJETA)


def _historia(sedes: dict, barberos: list, dueno_id: int, dias: int = 24):
    """
    Tres semanas y pico de trabajo ANTES de hoy: servicios, pagos y una caja
    cerrada por sede y día. Se escribe directo en las tablas (no por
    `operacion.cobrar`) porque cobrar siempre usa la hora de ahora.
    """
    rng = random.Random(7)
    hoy = formato.hoy_en(formato.ZONA)
    catalogo = {sid: operacion.servicios_de_sede(sid) for sid in sedes}
    session = database.get_session()
    try:
        for k in range(dias, 0, -1):
            dia = hoy - timedelta(days=k)
            if dia.weekday() == 6 and rng.random() < .5:
                continue                        # algunos domingos no se abre
            base_dia = formato.inicio_utc(dia)
            for sid in sedes:
                # `base_dia` es la medianoche LOCAL (en UTC): las horas se
                # suman desde ahí, de 9 a. m. a 7 p. m.
                caja = m.Caja(sede_id=sid, abierta_por=dueno_id, base_inicial=Decimal(200000),
                              abierta_en=base_dia + timedelta(hours=8))
                session.add(caja)
                session.flush()
                efectivo = Decimal(0)
                for b in [b for b in barberos if sid in b["sedes"]]:
                    for _ in range(rng.randint(3, 7)):
                        inicio = base_dia + timedelta(hours=rng.randint(9, 19),
                                                      minutes=rng.choice((0, 15, 30, 45)))
                        elegidos = [catalogo[sid][i] for i in rng.choice(COMBOS)]
                        propina = Decimal(rng.choice((0, 0, 0, 5000, 5000, 10000)))
                        cita = m.Cita(sede_id=sid, barbero_id=b["id"], inicio=inicio,
                                      fin=inicio + timedelta(minutes=45), estado=m.COMPLETADA,
                                      origen=rng.choice((m.WALK_IN, m.WALK_IN, m.WHATSAPP,
                                                         m.WHATSAPP, m.PANEL)),
                                      propina=propina, registrada_por=b["id"])
                        session.add(cita)
                        session.flush()
                        total = propina
                        for sv in elegidos:
                            suyo = (sv["precio"] * b["pct"] / 100).quantize(Decimal(1))
                            session.add(m.CitaServicio(
                                cita_id=cita.id, servicio_id=sv["id"], nombre=sv["nombre"],
                                precio=sv["precio"], porcentaje_barbero=b["pct"],
                                monto_barbero=suyo, monto_barberia=sv["precio"] - suyo))
                            total += sv["precio"]
                        metodo = rng.choice(METODOS)
                        session.add(m.Pago(caja_id=caja.id, cita_id=cita.id, metodo=metodo,
                                           monto=total, created_at=inicio))
                        if metodo == m.EFECTIVO:
                            efectivo += total
                esperado = caja.base_inicial + efectivo
                faltante = Decimal(rng.choice((0, 0, 0, 0, 0, 0, -10000, 5000)))
                caja.efectivo_esperado = esperado
                caja.efectivo_contado = esperado + faltante
                caja.diferencia = faltante
                caja.cerrada_en = base_dia + timedelta(hours=21)
                caja.cerrada_por = dueno_id
        session.commit()
    finally:
        session.close()


def _cliente_con_nota(nombre: str, telefono: str, nota: str = "") -> int:
    session = database.get_session()
    try:
        c = m.ClienteBarberia(nombre=nombre, telefono=telefono, notas=nota or None)
        session.add(c)
        session.commit()
        return c.id
    finally:
        session.close()


def _agenda_de_ejemplo(dueno, chapinero, usaquen, andres, julian, daniel, hoy):
    """
    Citas de HOY a horas fijas (se escriben directo: reservar no deja
    agendar en el pasado, y la demo se puede sembrar a cualquier hora) y de
    MAÑANA por el camino de verdad (`agenda.reservar`). Una de hoy se queda
    sin cobro a propósito, para que salga en "Para revisar".
    """
    from datetime import time
    from app.barberia import agenda

    sebastian = _cliente_con_nota("Sebastián Rojas", "3104445566",
                                  "Viene cada 3 semanas. Degradado bajo.")
    daniel_o = _cliente_con_nota("Daniel Ortiz", "3157778899",
                                 "Barba en punta, máquina 1 a los lados")
    luis = _cliente_con_nota("Luis Herrera", "3001230000")
    oscar = _cliente_con_nota("Óscar Niño", "3009998877")
    corte, combo, barba = (operacion.servicios_de_sede(chapinero)[i] for i in (0, 1, 2))

    def cita(sede, barbero, cliente, hora, minutos_, estado, origen, servicio):
        inicio = agenda._local(hoy, hora)
        session = database.get_session()
        try:
            session.add(m.Cita(sede_id=sede, barbero_id=barbero, cliente_id=cliente,
                               inicio=inicio, fin=inicio + timedelta(minutes=minutos_),
                               estado=estado, origen=origen, servicio_id=servicio["id"]))
            session.commit()
        finally:
            session.close()

    cita(chapinero, andres, oscar, time(9, 30), 40, m.CONFIRMADA, m.WHATSAPP, corte)
    cita(chapinero, julian, luis, time(11, 0), 40, m.NO_ASISTIO, m.PANEL, corte)
    cita(chapinero, andres, daniel_o, time(15, 0), 25, m.CONFIRMADA, m.WHATSAPP, barba)
    cita(chapinero, andres, sebastian, time(17, 0), 60, m.CONFIRMADA, m.WHATSAPP, combo)
    cita(chapinero, andres, luis, time(18, 30), 40, m.PENDIENTE, m.PANEL, corte)
    cita(usaquen, daniel, sebastian, time(16, 0), 40, m.CONFIRMADA, m.WHATSAPP, corte)
    agenda.bloquear(dueno, chapinero, andres, hoy, time(13), time(14), "Almuerzo")

    manana = hoy + timedelta(days=1)
    for barbero, cliente, servicio, origen in ((andres, sebastian, combo, m.WHATSAPP),
                                               (julian, luis, corte, m.PANEL),
                                               (andres, daniel_o, barba, m.WHATSAPP),
                                               (None, oscar, corte, m.WHATSAPP)):
        huecos = agenda.huecos_de(chapinero, barbero, manana, servicio["minutos"])
        if huecos:
            inicio = list(huecos)[len(huecos) // 3]
            agenda.reservar(chapinero, barbero, servicio["id"], inicio, origen=origen,
                            cliente_id=cliente)


def sembrar():
    # En SQLite (local) la base se crea aquí; en PostgreSQL la crea Alembic
    # al desplegar, y `create_all` por este camino sería la trampa §3.8.
    if not database.ES_POSTGRES:
        database.init_db()

    filo = _cliente("filo", "Filo Barbería", planes.BARBERIA_BOT_IA,
                    vence_el=date.today() + timedelta(days=20))
    with tenencia.usar(filo):
        chapinero = cuentas.crear_sede(filo, "Chapinero", "Calle 57 # 9-21")
        usaquen = cuentas.crear_sede(filo, "Usaquén", "Carrera 6 # 119-10")
        cedritos = cuentas.crear_sede(filo, "Cedritos", "Calle 140 # 11-45")

        dueno, _ = cuentas.crear_persona(filo, "Ricardo Gómez", "ricardo", m.DUENO, [],
                                         correo="ricardo@filobarberia.co",
                                         telefono="300 111 2233", clave=CLAVE)
        cuentas.crear_persona(filo, "Sofía Restrepo", "sofia.r", m.ADMIN,
                              [chapinero, usaquen], correo="sofia@filobarberia.co", clave=CLAVE)
        cuentas.crear_persona(filo, "Laura Pardo", "laura.p", m.RECEPCION,
                              [chapinero], telefono="310 555 2201", clave=CLAVE)
        andres, _ = cuentas.crear_persona(filo, "Andrés Martínez", "andres.m", m.BARBERO,
                                          [chapinero, usaquen], clave=CLAVE,
                                          meta_quincena=Decimal(1_800_000))
        daniel, temporal = cuentas.crear_persona(filo, "Daniel Castro", "daniel.c",
                                                 m.BARBERO, [usaquen],
                                                 comision_defecto=Decimal(60))
        julian, _ = cuentas.crear_persona(filo, "Julián Pineda", "julian.p", m.BARBERO,
                                          [chapinero], clave=CLAVE,
                                          esquema_pago=m.FIJO_MAS_COMISION,
                                          comision_defecto=Decimal(20),
                                          sueldo_fijo=Decimal(650_000))
        kevin, _ = cuentas.crear_persona(filo, "Kevin Rojas", "kevin.r", m.BARBERO,
                                         [cedritos], clave=CLAVE,
                                         esquema_pago=m.ALQUILER_SILLA,
                                         alquiler_silla=Decimal(900_000))
        mateo, _ = cuentas.crear_persona(filo, "Mateo Vargas", "mateo.v", m.BARBERO,
                                         [cedritos], clave=CLAVE)
        camilo, _ = cuentas.crear_persona(filo, "Camilo Torres", "camilo.t",
                                          m.BARBERO, [chapinero], clave=CLAVE)
        session = database.get_session()
        try:
            p = session.get(m.Personal, camilo)
            p.activo = False
            session.get(database.PanelUser, p.panel_user_id).active = False
            session.commit()
        finally:
            session.close()

        # ── lo que pasó antes de hoy ──
        _historia({chapinero: "Chapinero", usaquen: "Usaquén", cedritos: "Cedritos"}, [
            {"id": andres, "sedes": (chapinero, usaquen), "pct": Decimal(50)},
            {"id": daniel, "sedes": (usaquen,), "pct": Decimal(60)},
            {"id": julian, "sedes": (chapinero,), "pct": Decimal(20)},
            {"id": kevin, "sedes": (cedritos,), "pct": Decimal(100)},
            {"id": mateo, "sedes": (cedritos,), "pct": Decimal(50)},
        ], dueno)

        # ── lo de hoy, por el camino de verdad ──
        hoy = formato.hoy_en(formato.ZONA)
        r = _persona(filo, dueno)
        primer_dia = hoy.replace(day=1)
        for sid, monto in ((chapinero, 4_200_000), (usaquen, 3_800_000), (cedritos, 2_600_000)):
            gid = operacion.registrar_gasto(r, sid, "Arriendo del local", monto, "Arriendo",
                                            "FIJO", False, hoy)
            session = database.get_session()
            session.get(m.Gasto, gid).fecha = primer_dia
            session.commit()
            session.close()
        for sid, texto, monto, cat, tipo, dia in (
                (chapinero, "Energía y agua", 610_000, "Servicios públicos", "FIJO", 12),
                (cedritos, "Arreglo de silla hidráulica", 340_000, "Mantenimiento", "VARIABLE", 19)):
            gid = operacion.registrar_gasto(r, sid, texto, monto, cat, tipo, False, hoy)
            session = database.get_session()
            session.get(m.Gasto, gid).fecha = hoy.replace(day=min(dia, hoy.day))
            session.commit()
            session.close()

        a = _persona(filo, andres)
        cat = operacion.servicios_de_sede(chapinero)
        operacion.cobrar(a, chapinero, [cat[0]["id"]], "efectivo", propina=5000)
        operacion.cobrar(a, chapinero, [cat[1]["id"]], "dividido", propina=10000,
                         efectivo_dividido=30000, cliente="Felipe Ruiz")
        repetido, _ = operacion.cobrar(a, chapinero, [cat[1]["id"]], "transferencia")
        operacion.anular(a, repetido, "Quedó repetido", hoy)
        operacion.cobrar(a, chapinero, [cat[0]["id"], cat[3]["id"]], "tarjeta",
                         cliente="Juan Castro")
        j = _persona(filo, julian)
        operacion.cobrar(j, chapinero, [cat[2]["id"]], "efectivo")
        operacion.registrar_gasto(r, chapinero, "Café y agua para clientes", 45_000,
                                  "Insumos", "VARIABLE", True, hoy)
        k = _persona(filo, kevin)
        cat_c = operacion.servicios_de_sede(cedritos)
        operacion.cobrar(k, cedritos, [cat_c[4]["id"]], "efectivo")
        operacion.cobrar(k, cedritos, [cat_c[0]["id"]], "efectivo", propina=5000)
        caja_c = next(c for c in operacion.cajas_de(r, cedritos, hoy) if c.get("abierta"))
        operacion.cerrar_caja(r, caja_c["caja"], caja_c["esperado"] - 18000)
        nomina.registrar_adelanto(r, andres, 100_000, "", hoy)
        nomina.aprobar(r, mateo, hoy)

        # ── la agenda: hoy (a horas fijas, directo) y mañana (reservando) ──
        _agenda_de_ejemplo(r, chapinero, usaquen, andres, julian, daniel, hoy)

    navaja = _cliente("navaja", "Navaja Club", planes.BARBERIA, activo=False,
                      pausado_por="impago",
                      vence_el=date.today() - timedelta(days=5))
    with tenencia.usar(navaja):
        sede = cuentas.crear_sede(navaja, "Centro", "Carrera 7 # 22-10")
        cuentas.crear_persona(navaja, "Hernán Ruiz", "navaja", m.DUENO, [],
                              clave="navaja2026")
        cuentas.crear_persona(navaja, "Felipe Nieto", "pipe.n", m.BARBERO, [sede],
                              clave="navaja2026")

    tenencia.olvidar()
    return temporal




def _alembic_al_dia() -> bool:
    from sqlalchemy import inspect
    return "alembic_version" in inspect(database.engine).get_table_names()


def _ya_sembrada() -> bool:
    with tenencia.sin_inquilino():
        s = database.SessionLocal()
        try:
            return s.query(database.Client).filter_by(slug="filo").first() is not None
        finally:
            s.close()


if __name__ == "__main__":
    if "--si" not in sys.argv:
        print("Esto escribe dos barberías de demostración en la base de DATABASE_URL. "
              "Si es la base de una DEMO, repite con --si. Nunca en producción.")
        sys.exit(1)
    if database.ES_POSTGRES and not _alembic_al_dia():
        print("La base todavía no tiene el esquema de Alembic. Despliega primero el "
              "servicio (corre `alembic upgrade head`) y vuelve a correr esto.")
        sys.exit(1)
    if not database.ES_POSTGRES:
        database.init_db()
    if _ya_sembrada():
        print("Ya hay una Filo Barbería en esta base: no se siembra dos veces.")
        sys.exit(1)
    temporal = sembrar()
    print("Listo. Entra con ricardo / filo2026 (dueño) o andres.m / filo2026 (barbero).")
    print(f"daniel.c tiene clave temporal: {temporal}")
