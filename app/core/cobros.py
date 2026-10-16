"""
LO QUE NOS PAGA CADA NEGOCIO
=============================
Cada negocio tiene una fecha hasta la que está pagado (`clients.vence_el`).
Con ella, esto decide en qué punto está su cuenta, le recuerda que pague y,
si no paga, le pausa el bot. Decisión del 24-sep-2026:

    7 días antes       empieza a avisar: banda en su panel y un correo al día
    el día que vence   último día pagado
    2 días después     el bot sigue funcionando (días de gracia), avisando
    al tercero         se pausa solo. El bot calla y el panel no abre.

El pago se registra A MANO en /superadmin (`registrar_pago`): nos pagan por
Nequi y alguien tiene que ver el comprobante. Registrarlo corre la fecha un
mes y, si lo había pausado el cobro, lo reactiva solo.

    ⚠️  Solo se reactiva solo lo que pausó el cobro (`pausado_por`).

Una pausa puesta a mano en /superadmin es una decisión tuya, y no la
deshace un pago: se reactiva también a mano.

SIN FECHA NO SE COBRA
---------------------
`vence_el` en NULL es "a este no se le cobra": el bot de casa, o un
cliente al que todavía no se le puso fecha. Nada de esto le toca.

LA REVISIÓN CORRE SOLA
----------------------
Cada hora, dentro del mismo proceso (`vigilar`, lo arranca `main`). Mandar
un correo al día y no uno por revisión lo resuelve
`recordatorio_enviado_el`. No hace falta un cron aparte: el servicio corre
siempre en un solo proceso (ver `app/core/eventos.py`).
"""

import asyncio
import html
from datetime import date, datetime, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from app.core import database, planes

# Las fechas de cobro son de Colombia: "vence el 5" es el 5 aquí, no en UTC
# (a las 7 de la tarde del 4 en Bogotá ya es 5 en UTC).
ZONA = ZoneInfo("America/Bogota")

SIN_COBRO = "sin_cobro"
AL_DIA = "al_dia"
POR_VENCER = "por_vencer"
VENCIDO = "vencido"
PAUSADO = "pausado"

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def hoy() -> date:
    return datetime.now(ZONA).date()


def fecha_en_palabras(d: date | None) -> str:
    """date(2026, 10, 5) → "5 de octubre"."""
    return f"{d.day} de {MESES[d.month - 1]}" if d else ""


def sumar_un_mes(d: date) -> date:
    """
    El mismo día del mes siguiente. Si no existe (31 de enero → febrero),
    el último del mes: así nadie pierde días de lo que pagó.
    """
    anio, mes = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for dia in (d.day, 30, 29, 28):
        try:
            return date(anio, mes, dia)
        except ValueError:
            continue
    return date(anio, mes, 28)


class Cuenta(NamedTuple):
    """En qué punto está lo que nos paga un negocio."""
    estado: str               # SIN_COBRO, AL_DIA, POR_VENCER, VENCIDO, PAUSADO
    vence_el: date | None
    dias: int | None          # hasta el vencimiento; negativo = vencido
    pausa_el: date | None     # el día en que se pausa si no paga
    precio: int
    plan: planes.Plan
    ultimo_pago_el: date | None
    ultimo_pago_monto: int | None


def cuenta(fila: dict, el_dia: date = None) -> Cuenta:
    """La cuenta de un negocio a partir de su fila de `clients`."""
    el_dia = el_dia or hoy()
    vence = fila.get("vence_el")
    plan = planes.de(fila)
    precio = planes.precio_de(fila)
    comun = dict(precio=precio, plan=plan,
                 ultimo_pago_el=fila.get("ultimo_pago_el"),
                 ultimo_pago_monto=fila.get("ultimo_pago_monto"))

    if not vence:
        return Cuenta(SIN_COBRO, None, None, None, **comun)

    dias = (vence - el_dia).days
    pausa_el = vence + timedelta(days=planes.DIAS_DE_GRACIA + 1)

    if fila.get("pausado_por") == "impago" and not fila.get("active", True):
        estado = PAUSADO
    elif dias < 0:
        estado = VENCIDO
    elif dias <= planes.DIAS_DE_AVISO:
        estado = POR_VENCER
    else:
        estado = AL_DIA
    return Cuenta(estado, vence, dias, pausa_el, **comun)


def _fila(cliente) -> dict:
    return {c.name: getattr(cliente, c.name)
            for c in database.Client.__table__.columns}


def cuenta_de(client_id: int, el_dia: date = None) -> Cuenta | None:
    session = database.get_session()
    try:
        cliente = session.query(database.Client).filter_by(id=client_id).first()
        return cuenta(_fila(cliente), el_dia) if cliente else None
    finally:
        session.close()


def registrar_pago(client_id: int, monto: int = None, el_dia: date = None) -> date:
    """
    Anota un pago y corre el vencimiento un mes. Devuelve la fecha nueva.

    El mes se suma desde el vencimiento si pagó a tiempo (pagar tres días
    antes no le quita esos tres días), y desde hoy si pagó tarde (no se le
    cobran los días que el bot estuvo pausado). Sin fecha de antes, desde
    hoy: es su primer mes.

    Si lo había pausado el cobro, lo reactiva.
    """
    el_dia = el_dia or hoy()
    session = database.get_session()
    try:
        cliente = session.query(database.Client).filter_by(id=client_id).first()
        if cliente is None:
            raise ValueError("Ese negocio no existe.")
        base = cliente.vence_el if cliente.vence_el and cliente.vence_el >= el_dia \
            else el_dia
        nuevo = sumar_un_mes(base)
        cliente.vence_el = nuevo
        cliente.ultimo_pago_el = el_dia
        cliente.ultimo_pago_monto = (int(monto) if monto not in (None, "")
                                     else planes.precio_de(_fila(cliente)))
        cliente.recordatorio_enviado_el = None
        if cliente.pausado_por == "impago":
            cliente.active = True
            cliente.paused_at = None
            cliente.pausado_por = None
        session.commit()
    finally:
        session.close()
    _olvidar(client_id)
    return nuevo


def _olvidar(client_id: int):
    from app import config
    config.olvidar(client_id)


# ── Lo que se le dice al dueño ───────────────────────────────────────

def _como_pagar_texto(c: Cuenta) -> str:
    medios = "\n".join(f"  · {nombre}: {dato}" for nombre, dato in planes.MEDIOS_DE_PAGO)
    return (f"Valor: {planes.pesos(c.precio)} (plan {c.plan.nombre}).\n"
            f"Cómo pagar:\n{medios}\n"
            f"Y mándanos el comprobante por WhatsApp: "
            f"https://wa.me/{planes.WHATSAPP_COBROS}")


def mensaje(c: Cuenta, negocio: str) -> tuple[str, str] | None:
    """
    `(asunto, cuerpo)` del correo que toca hoy, o None si no toca ninguno.

    Lo usa también el panel ("Mi plan") para decir lo mismo con las mismas
    palabras: dos textos distintos para la misma deuda confunden.
    """
    if c.estado in (SIN_COBRO, AL_DIA):
        return None
    if c.estado == PAUSADO:
        return (f"Tu bot de {negocio} está pausado por falta de pago",
                f"Hola. Tu bot de WhatsApp de {negocio} está pausado desde el "
                f"{fecha_en_palabras(c.pausa_el)}: no responde a tus clientes y "
                f"tu panel no abre. No se ha borrado nada.\n\n"
                f"En cuanto registremos tu pago vuelve a funcionar solo, con "
                f"todo tu historial.\n\n{_como_pagar_texto(c)}")
    if c.estado == VENCIDO:
        return (f"Tu plan venció: el bot de {negocio} se pausa el "
                f"{fecha_en_palabras(c.pausa_el)}",
                f"Hola. Tu plan de Nitro 2Tech venció el "
                f"{fecha_en_palabras(c.vence_el)}. Tu bot sigue funcionando "
                f"hasta el {fecha_en_palabras(c.pausa_el - timedelta(days=1))}; "
                f"si para entonces no hemos recibido el pago, se pausará y "
                f"dejará de responder a tus clientes.\n\n{_como_pagar_texto(c)}\n\n"
                f"Si ya pagaste, ignora este correo.")
    cuando = ("hoy" if c.dias == 0 else "mañana" if c.dias == 1
              else f"en {c.dias} días")
    return (f"Tu plan de Nitro 2Tech vence {cuando}",
            f"Hola. Tu plan {c.plan.nombre} de {negocio} vence {cuando}, el "
            f"{fecha_en_palabras(c.vence_el)}.\n\n{_como_pagar_texto(c)}\n\n"
            f"Si ya pagaste, ignora este correo.")


def correo_del_dueno(fila: dict) -> str:
    """A dónde se le escribe: su correo de avisos, o el del negocio."""
    negocio = fila.get("negocio_config") or {}
    propio = str((negocio.get("avisos") or {}).get("correo_dueno") or "").strip()
    if "@" in propio:
        return propio
    otro = str(fila.get("business_email") or "").strip()
    return otro if "@" in otro else ""


def _enviar(fila: dict, asunto: str, cuerpo: str) -> bool:
    from app.core import correo
    destino = correo_del_dueno(fila)
    if not destino:
        print(f"[cobros] {fila.get('slug')!r} no tiene correo: no se le puede "
              f"avisar del cobro.")
        return False
    html_ = (f'<div style="font-family:-apple-system,\'Segoe UI\',sans-serif;'
             f'max-width:560px;margin:0 auto;padding:24px;color:#171326;'
             f'white-space:pre-wrap;font-size:15px;line-height:1.6">'
             f'{html.escape(cuerpo)}</div>')
    ok, explica = correo.enviar_ahora([destino], asunto, cuerpo, html=html_,
                                      remitente="Nitro 2Tech")
    if not ok:
        print(f"[cobros] No salió el correo a {fila.get('slug')!r}: {explica}")
    return ok


# ── La revisión diaria ───────────────────────────────────────────────

def revisar_todos(el_dia: date = None) -> dict:
    """
    Pasa por todos los negocios con fecha: avisa y pausa lo que toque.

    Devuelve `{"avisados": [...], "pausados": [...]}` con los slugs, para
    el log y las pruebas. Corre SIN inquilino: mira a todos.
    """
    el_dia = el_dia or hoy()
    resumen = {"avisados": [], "pausados": []}

    session = database.get_session()
    try:
        filas = [_fila(c) for c in session.query(database.Client)
                 .filter(database.Client.vence_el.isnot(None)).all()]
    finally:
        session.close()

    for fila in filas:
        c = cuenta(fila, el_dia)

        if (c.estado == VENCIDO and fila.get("active")
                and el_dia >= c.pausa_el):
            _pausar_por_impago(fila["id"])
            fila.update(active=False, pausado_por="impago")
            resumen["pausados"].append(fila["slug"])
            print(f"[cobros] {fila['slug']!r} pausado por impago (venció el "
                  f"{c.vence_el}).")
            c = cuenta(fila, el_dia)
            texto = mensaje(c, fila.get("nombre") or "")
            if texto and _enviar(fila, *texto):
                _anotar_recordatorio(fila["id"], el_dia)
            continue

        if c.estado not in (POR_VENCER, VENCIDO) or not fila.get("active"):
            continue
        if fila.get("recordatorio_enviado_el") == el_dia:
            continue            # uno al día, no uno por revisión
        texto = mensaje(c, fila.get("nombre") or "")
        if texto and _enviar(fila, *texto):
            _anotar_recordatorio(fila["id"], el_dia)
            resumen["avisados"].append(fila["slug"])

    return resumen


def _pausar_por_impago(client_id: int):
    session = database.get_session()
    try:
        session.query(database.Client).filter_by(id=client_id).update({
            "active": False, "paused_at": database.ahora_utc(),
            "pausado_por": "impago"})
        session.commit()
    finally:
        session.close()
    _olvidar(client_id)


def _anotar_recordatorio(client_id: int, el_dia: date):
    session = database.get_session()
    try:
        session.query(database.Client).filter_by(id=client_id).update(
            {"recordatorio_enviado_el": el_dia})
        session.commit()
    finally:
        session.close()


SEGUNDOS_ENTRE_REVISIONES = 3600


async def vigilar():
    """
    La revisión de cobros, una vez por hora mientras el servicio viva.

    Nunca se cae: un fallo de una revisión se anota y se reintenta en la
    siguiente. Un cobro que falla no puede tumbar el bot.
    """
    from starlette.concurrency import run_in_threadpool

    while True:
        try:
            resumen = await run_in_threadpool(revisar_todos)
            if resumen["avisados"] or resumen["pausados"]:
                print(f"[cobros] Revisión: {resumen}")
        except Exception as e:
            print(f"[cobros] La revisión falló, se reintenta en una hora: {e}")
        await asyncio.sleep(SEGUNDOS_ENTRE_REVISIONES)
