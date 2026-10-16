"""
CÓMO SE ESCRIBEN LAS CIFRAS Y LAS FECHAS (§4.5 del handoff)
============================================================
Pesos sin decimales y con punto de miles (`$48.600.000`), el menos
tipográfico (U+2212) en los negativos, y las fechas en español de
Colombia. Las horas de un instante las escribe el NAVEGADOR (§4.2 de
CONTINUAR_AQUI); aquí solo va lo que depende de la zona de la SEDE, que es
la misma para todos los que la miran.
"""

import calendar
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

MENOS = "−"

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def pesos(valor) -> str:
    """48600000 → "$48.600.000"; −100000 → "−$100.000". Redondea al mostrar."""
    cifra = Decimal(str(valor or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    signo = MENOS if cifra < 0 else ""
    return f"{signo}${abs(int(cifra)):,}".replace(",", ".")


def pesos_cortos(valor) -> str:
    """Para gráficas y celular: "$48,6 M", "$120 mil", "$900"."""
    cifra = Decimal(str(valor or 0))
    signo = MENOS if cifra < 0 else ""
    cifra = abs(cifra)
    if cifra >= 1_000_000:
        texto = f"{cifra / 1_000_000:.1f}".replace(".", ",").replace(",0", "")
        return f"{signo}${texto} M"
    if cifra >= 1_000:
        return f"{signo}${int(cifra / 1000)} mil"
    return pesos(-cifra if signo else cifra)


def hoy_en(zona: str) -> date:
    return datetime.now(ZoneInfo(zona or "America/Bogota")).date()


def fecha_larga(dia: date, con_dia_semana: bool = True) -> str:
    """"jueves 24 de septiembre"."""
    base = f"{dia.day} de {MESES[dia.month - 1]}"
    return f"{DIAS[dia.weekday()]} {base}" if con_dia_semana else base


def con_mayuscula(texto: str) -> str:
    return texto[:1].upper() + texto[1:]


def quincena(dia: date) -> str:
    """"Quincena del 15 al 30 de septiembre" (1–15 y 16–fin de mes)."""
    ultimo = calendar.monthrange(dia.year, dia.month)[1]
    desde, hasta = (1, 15) if dia.day <= 15 else (16, ultimo)
    return f"Quincena del {desde} al {hasta} de {MESES[dia.month - 1]}"


def mes(dia: date) -> str:
    return con_mayuscula(MESES[dia.month - 1])


def plural(n: int, singular: str, plural_: str | None = None) -> str:
    """"1 día" / "2 días"."""
    return f"{n} {singular if n == 1 else (plural_ or singular + 's')}"


# ══════════════════════════════════════════════════════════════════════
#  DÍAS Y PERIODOS EN LA ZONA DE LA BARBERÍA
# ══════════════════════════════════════════════════════════════════════
#
# Se guarda en UTC y se agrupa en la hora de la sede. "Hoy" en Bogotá
# empieza a las 5:00 UTC: sin esta conversión, un corte de las 8 p. m.
# caería en el día siguiente.

ZONA = "America/Bogota"


def zona() -> ZoneInfo:
    return ZoneInfo(ZONA)


def a_local(momento: datetime) -> datetime:
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(zona())


def inicio_utc(dia: date) -> datetime:
    """Las 00:00 de ese día en la zona de la barbería, en UTC."""
    return datetime.combine(dia, time(0), tzinfo=zona()).astimezone(timezone.utc)


def rango_utc(desde: date, hasta: date) -> tuple[datetime, datetime]:
    """[desde, hasta) en días locales, como instantes UTC."""
    return inicio_utc(desde), inicio_utc(hasta)


def periodo(clave: str, hoy: date) -> tuple[date, date]:
    """Hoy / Semana (de lunes a domingo) / Mes, como [desde, hasta)."""
    if clave == "semana":
        lunes = hoy - timedelta(days=hoy.weekday())
        return lunes, lunes + timedelta(days=7)
    if clave == "mes":
        primero = hoy.replace(day=1)
        return primero, primero + timedelta(days=calendar.monthrange(hoy.year, hoy.month)[1])
    return hoy, hoy + timedelta(days=1)


def periodo_anterior(clave: str, hoy: date) -> tuple[date, date]:
    """El periodo de antes, para el "+9% frente a…"."""
    desde, _ = periodo(clave, hoy)
    return periodo(clave, desde - timedelta(days=1))


def quincena_de(dia: date) -> tuple[date, date]:
    """[desde, hasta] de la quincena: del 1 al 15 y del 16 al fin de mes."""
    if dia.day <= 15:
        return dia.replace(day=1), dia.replace(day=15)
    return dia.replace(day=16), dia.replace(day=calendar.monthrange(dia.year, dia.month)[1])


def hora(momento: datetime, con_ampm: bool = True) -> str:
    """"8:02 a. m." en la hora de la barbería (§4.5)."""
    local = a_local(momento)
    h = local.hour % 12 or 12
    texto = f"{h}:{local.minute:02d}"
    if con_ampm:
        texto += " a. m." if local.hour < 12 else " p. m."
    return texto


def cuando(momento: datetime, hoy: date) -> str:
    """"Hoy 11:52 a. m.", "Ayer 7:05 p. m.", "18 sep"."""
    local = a_local(momento)
    if local.date() == hoy:
        return f"Hoy {hora(momento)}"
    if local.date() == hoy - timedelta(days=1):
        return f"Ayer {hora(momento)}"
    return fecha_corta(local.date())


def fecha_corta(dia: date) -> str:
    """"24 sep"."""
    return f"{dia.day} {MESES[dia.month - 1][:3]}"
