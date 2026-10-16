"""
LOS PLANES QUE SE VENDEN
=========================
Qué incluye cada plan, en UN solo sitio. El panel del dueño lo enseña
("a qué tienes derecho"), el super-admin lo elige al dar de alta, y el bot
lo aplica: cuántas áreas caben y si la IA puede encenderse.

    Básico    1 administrador, sin áreas, sin IA
    Pro       el administrador + 3 áreas, con IA
    Premium   el administrador + 5 áreas, con IA

Cada ÁREA es una persona del equipo del negocio con su usuario y su clave:
recibe por correo los clientes de su área y en el panel solo ve esas
conversaciones (ver `app/core/equipo.py`).

POR QUÉ UN DICCIONARIO Y NO UNA TABLA
-------------------------------------
Son tres y cambian cuando cambia lo que se vende, que es una decisión de
producto y va con un despliegue. Lo que sí cambia de un cliente a otro —un
área de más pactada con él— tiene su columna (`max_destinos_avisos`), que
manda sobre el plan.
"""

from typing import NamedTuple


class Plan(NamedTuple):
    codigo: str
    nombre: str
    areas: int          # cuántas áreas con su propio usuario, además del dueño
    ia: bool            # si incluye que el bot entienda lo que escriben
    precio: int         # pesos colombianos al mes
    incluye: tuple      # lo que se le enseña al dueño, en sus palabras
    # Lo de abajo lo añadió el módulo de barberías (`app/barberia/`). Con
    # valores por defecto para que los tres planes del bot no cambien.
    bot: bool = True        # si incluye el bot de WhatsApp
    barberia: bool = False  # si incluye el panel de gestión de la barbería
    sedes: int = 0          # cupo de sedes (solo planes de barbería)
    barberos: int = 0       # cupo de barberos (solo planes de barbería)
    instalacion: int = 0    # pago único por montar el bot (App de Meta)


BASICO = "basico"
PRO = "pro"
PREMIUM = "premium"

# Los planes de barbería (ver `Instrucciones SAAS barberia.md`, §5). Son
# OTRA línea de producto: una barbería solo ve estos tres y un negocio del
# bot solo los suyos (`ORDEN` y `ORDEN_BARBERIA`). Viven en el mismo
# diccionario porque el cobro (`precio_de`) y el super-admin los leen de
# aquí sin saber de qué producto son.
#
#     ⚠️  PRECIOS DE EJEMPLO. La especificación los deja pendientes
#     (§11.1); son los del diseño, para poder probar el cobro.
BARBERIA = "barberia"
BARBERIA_BOT = "barberia_bot"
BARBERIA_BOT_IA = "barberia_bot_ia"

PLANES = {
    BASICO: Plan(BASICO, "Básico", 0, False, 70_000, (
        "Tu bot de WhatsApp con su menú, respondiendo día y noche",
        "Panel de conversaciones para responder tú",
        "Un usuario administrador",
        "Avisos por correo cuando entra un cliente",
    )),
    PRO: Plan(PRO, "Pro", 3, True, 100_000, (
        "Todo lo del plan Básico",
        "IA: el bot entiende lo que el cliente escribe con sus palabras",
        "Hasta 3 áreas de tu equipo, cada una con su usuario",
        "Cada área recibe y atiende solo sus clientes",
    )),
    PREMIUM: Plan(PREMIUM, "Premium", 5, True, 130_000, (
        "Todo lo del plan Pro",
        "Hasta 5 áreas de tu equipo, cada una con su usuario",
    )),
    BARBERIA: Plan(BARBERIA, "Barbería", 0, False, 89_000, (
        "Caja, agenda, pagos a barberos y gastos de tu barbería",
        "Hasta 1 sede y 5 barberos",
        "Recordatorios de cita por correo y notificación",
    ), bot=False, barberia=True, sedes=1, barberos=5),
    BARBERIA_BOT: Plan(BARBERIA_BOT, "Barbería + Bot", 0, False, 149_000, (
        "Todo lo del plan Barbería",
        "Bot de WhatsApp que agenda las citas por ti",
        "Recordatorios de cita por WhatsApp",
        "Hasta 2 sedes y 8 barberos",
    ), bot=True, barberia=True, sedes=2, barberos=8, instalacion=250_000),
    BARBERIA_BOT_IA: Plan(BARBERIA_BOT_IA, "Barbería + Bot IA", 0, True, 219_000, (
        "Todo lo del plan Barbería + Bot",
        "IA: el bot entiende lo que el cliente escribe con sus palabras",
        "Hasta 3 sedes y 10 barberos",
    ), bot=True, barberia=True, sedes=3, barberos=10, instalacion=250_000),
}

# Los que se le ofrecen a un negocio del bot. Una barbería nunca los ve.
ORDEN = (BASICO, PRO, PREMIUM)

# Los que se le ofrecen a una barbería.
ORDEN_BARBERIA = (BARBERIA, BARBERIA_BOT, BARBERIA_BOT_IA)

# Cómo nos pagan. Lo ve el dueño en "Mi plan" y en los correos de cobro.
# Es de la PLATAFORMA, no de ningún cliente: cambia con un despliegue.
MEDIOS_DE_PAGO = (
    ("Nequi", "317 886 2390"),
)

# El WhatsApp de Nitro, para mandar el comprobante. Sale del Nequi: es el
# mismo número.
WHATSAPP_COBROS = "573178862390"

# El calendario de cobro (decisión del 24-sep-2026):
DIAS_DE_AVISO = 7       # una semana antes empieza a avisar, un correo al día
DIAS_DE_GRACIA = 2      # vencido, el bot sigue dos días; al tercero se pausa


def pesos(valor: int) -> str:
    """70000 → "$70.000", como se escribe en Colombia."""
    return "$" + f"{int(valor or 0):,}".replace(",", ".")


def codigo_de(fila: dict | None) -> str:
    """
    El plan de un negocio, a partir de su fila de `clients`.

    `clients.plan` era una etiqueta libre ("mensual") hasta el
    23-sep-2026. Lo que no sea un plan conocido se deduce de lo que ya se
    había vendido: con la IA contratada era un Pro, sin ella un Básico.
    """
    fila = fila or {}
    guardado = str(fila.get("plan") or "").strip().lower()
    if guardado in PLANES:
        return guardado
    return PRO if fila.get("ia_contratada") else BASICO


def de(fila: dict | None) -> Plan:
    return PLANES[codigo_de(fila)]


def precio_de(fila: dict | None) -> int:
    """
    Lo que paga este negocio al mes: lo pactado con él
    (`clients.precio_mensual`) o, si no hay nada, el precio de su plan.
    """
    fila = fila or {}
    propio = fila.get("precio_mensual")
    if propio not in (None, "") and int(propio) >= 0:
        return int(propio)
    return de(fila).precio


def cupo_de_areas(fila: dict | None) -> int:
    """
    Cuántas áreas le caben a este negocio.

    Lo pactado con ÉL (`clients.max_destinos_avisos`) manda sobre el plan.
    Un negativo se acota a 0 —sin áreas, todo le llega al dueño—, y un 0 o
    vacío cuenta como "no dicho": lo que dé el plan.
    """
    fila = fila or {}
    propio = fila.get("max_destinos_avisos")
    try:
        propio = int(propio) if propio not in (None, "") else None
    except (TypeError, ValueError):
        propio = None
    if propio:
        return max(0, propio)
    return de(fila).areas


def _pactado(fila: dict, columna: str) -> int | None:
    """Lo que se pactó con este negocio en `columna`, o None si no hay."""
    try:
        valor = (fila or {}).get(columna)
        return int(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def cupo_de_sedes(fila: dict | None) -> int:
    """
    Cuántas sedes le caben a esta barbería: lo pactado con ella
    (`clients.max_sedes`) o, si no hay nada, lo que trae su plan.
    """
    propio = _pactado(fila, "max_sedes")
    return max(0, propio) if propio else de(fila).sedes


def cupo_de_barberos(fila: dict | None) -> int:
    """Igual que `cupo_de_sedes`, con `clients.max_barberos`."""
    propio = _pactado(fila, "max_barberos")
    return max(0, propio) if propio else de(fila).barberos
