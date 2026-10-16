"""
AGENDAMIENTO CON GOOGLE CALENDAR
=================================
Calcula qué días y horarios están realmente libres, y crea el evento.

La disponibilidad NUNCA se inventa ni se guarda en caché: se consulta a
Google en el momento. Es la única forma de que dos clientes que escriben
a la vez no reserven el mismo hueco.

El horario laboral (días, horas, duración) vive en config.py.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from app import config
from app.core.huecos import rellenar
from app.integrations import google_client


class CalendarNoDisponible(Exception):
    """Google no respondió o no está configurado. El bot debe seguir igual."""


def _zona():
    """
    La zona horaria del negocio.

    Una zona vacía o mal escrita es CONFIGURACIÓN, no un fallo del
    cliente: se trata como Google caído, que lleva al bot a la ruta manual
    (la cita se anota y se avisa al dueño). Antes levantaba un error
    cualquiera y el cliente que pulsaba "Agendar" no recibía nada.
    """
    try:
        return ZoneInfo(config.BUSINESS_TIMEZONE)
    except (ValueError, KeyError, TypeError) as e:     # ZoneInfoNotFoundError es KeyError
        raise CalendarNoDisponible(
            f"La zona horaria {config.BUSINESS_TIMEZONE!r} no vale. Se pone "
            f"en el contenido del negocio, en Horario (p. ej. "
            f"America/Bogota).") from e


def ahora_local() -> datetime:
    return datetime.now(_zona())


def _hora_config(valor: str) -> tuple:
    """Convierte '09:00' en (9, 0). Mal escrita, calendario no disponible."""
    try:
        horas, _, minutos = str(valor or "").partition(":")
        horas, minutos = int(horas), int(minutos or 0)
        if not (0 <= horas <= 24 and 0 <= minutos < 60):
            raise ValueError
        return horas, minutos
    except ValueError as e:
        raise CalendarNoDisponible(
            f"La hora {valor!r} del horario no se entiende. Se escribe como "
            f"09:00.") from e


def formatear_hora(momento: datetime) -> str:
    """9:00 am / 3:30 pm — sin depender del locale del sistema operativo."""
    hora = momento.hour % 12 or 12
    sufijo = "am" if momento.hour < 12 else "pm"
    return f"{hora}:{momento.minute:02d} {sufijo}"


def formatear_dia(fecha) -> str:
    """'Jueves 7 de agosto' — para el texto de confirmación."""
    return (f"{config.DIAS_SEMANA[fecha.weekday()].capitalize()} {fecha.day} "
            f"de {config.MESES[fecha.month - 1]}")


def formatear_dia_corto(fecha) -> str:
    """'Jueves 7 ago' — cabe en los 24 caracteres que permite una lista."""
    return (f"{config.DIAS_SEMANA[fecha.weekday()].capitalize()} {fecha.day} "
            f"{config.MESES[fecha.month - 1][:3]}")


def _ocupados(desde: datetime, hasta: datetime) -> list:
    """
    Pide a Google los bloques ocupados del calendario en ese rango.

    Una sola llamada para todo el rango: consultar día por día sería
    lento y Meta reintenta el webhook si tardamos en responder.
    """
    try:
        id_calendario = google_client.id_calendario()
        respuesta = google_client.calendar().freebusy().query(
            body={
                "timeMin": desde.isoformat(),
                "timeMax": hasta.isoformat(),
                "timeZone": config.BUSINESS_TIMEZONE,
                "items": [{"id": id_calendario}],
            }
        ).execute()
    except Exception as e:
        raise CalendarNoDisponible(f"No se pudo consultar el calendario: {e}") from e

    calendarios = respuesta.get("calendars", {})
    bloques = calendarios.get(id_calendario, {}).get("busy", [])

    return [
        (datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
        for b in bloques
    ]


def _slots_del_dia(fecha, ocupados: list, desde_momento: datetime) -> list:
    """
    Genera los horarios libres de un día concreto.

    Descarta los que ya pasaron, los que empiezan demasiado pronto (nadie
    quiere una cita dentro de 5 minutos) y los que chocan con algo ya
    agendado.
    """
    if fecha.weekday() not in config.BUSINESS_DAYS:
        return []

    zona = _zona()
    h_ini, m_ini = _hora_config(config.BUSINESS_HOURS_START)
    h_fin, m_fin = _hora_config(config.BUSINESS_HOURS_END)

    medianoche = datetime.combine(fecha, datetime.min.time(), tzinfo=zona)
    # Con `+ timedelta` y no con `.replace(hour=…)`: "24:00" es un cierre
    # válido y `replace` no admite la hora 24.
    inicio_jornada = medianoche + timedelta(hours=h_ini, minutes=m_ini)
    fin_jornada = medianoche + timedelta(hours=h_fin, minutes=m_fin)

    # Nunca menos de un minuto. La configuración ya lo impide, pero este
    # bucle avanza de `duracion` en `duracion`, y con 0 no terminaba jamás:
    # un hilo al 100 % por cada cliente que pulsaba "Agendar".
    duracion = timedelta(minutes=max(1, config.APPOINTMENT_DURATION_MINUTES))
    minimo = desde_momento + timedelta(minutes=config.APPOINTMENT_MIN_NOTICE_MINUTES)

    libres = []
    slot = inicio_jornada
    while slot + duracion <= fin_jornada:
        fin_slot = slot + duracion

        if slot >= minimo and not any(ini < fin_slot and slot < fin
                                      for ini, fin in ocupados):
            libres.append(slot)

        slot += duracion

    return libres


def dias_con_disponibilidad(cantidad: int = 10) -> list:
    """
    Devuelve los próximos días laborables que tengan al menos un hueco.

    [(date, cantidad_de_horarios_libres), ...]
    """
    ahora = ahora_local()
    hasta = ahora + timedelta(days=config.APPOINTMENT_SEARCH_DAYS)
    ocupados = _ocupados(ahora, hasta)

    dias = []
    fecha = ahora.date()
    for _ in range(config.APPOINTMENT_SEARCH_DAYS):
        libres = _slots_del_dia(fecha, ocupados, ahora)
        if libres:
            dias.append((fecha, len(libres)))
            if len(dias) >= cantidad:
                break
        fecha += timedelta(days=1)

    return dias


def horarios_libres(fecha) -> list:
    """
    Horarios libres de un día concreto, consultados de nuevo a Google.

    Se vuelve a preguntar a propósito, aunque ya se hubiera preguntado al
    armar la lista de días: entre un mensaje y el siguiente pueden pasar
    minutos, y en ese rato alguien pudo agendar.
    """
    zona = _zona()
    inicio = datetime.combine(fecha, datetime.min.time(), tzinfo=zona)
    fin = inicio + timedelta(days=1)

    ocupados = _ocupados(inicio, fin)
    return _slots_del_dia(fecha, ocupados, ahora_local())


def sigue_libre(inicio: datetime) -> bool:
    """
    Confirma que ese horario exacto siga libre.

    Se llama justo antes de crear el evento. Entre que el cliente ve los
    botones y toca uno pueden pasar minutos: sin esta comprobación, dos
    clientes que eligen a la vez terminan con la misma hora.
    """
    fin = inicio + timedelta(minutes=config.APPOINTMENT_DURATION_MINUTES)
    return not any(ini < fin and inicio < f for ini, f in _ocupados(inicio, fin))


def eliminar_evento(event_id: str) -> bool:
    """
    Borra la cita del calendario. Devuelve True si el hueco quedó libre.

    Un evento que ya no está se toma como éxito: si Google responde 404 o
    410 es que alguien lo borró a mano desde el calendario, y el resultado
    para el cliente es el mismo que buscábamos.
    """
    if not event_id:
        return False

    try:
        google_client.calendar().events().delete(
            calendarId=google_client.id_calendario(), eventId=event_id
        ).execute()
        return True
    except HttpError as e:
        if getattr(e, "status_code", None) in (404, 410) or "404" in str(e) or "410" in str(e):
            print(f"[calendar] El evento {event_id} ya no existía.")
            return True
        print(f"[calendar] No se pudo borrar el evento {event_id}: {e}")
        return False
    except Exception as e:
        print(f"[calendar] No se pudo borrar el evento {event_id}: {e}")
        return False


def crear_evento(nombre: str, telefono: str, inicio: datetime, detalle: str = None) -> str:
    """
    Crea la cita en el calendario y devuelve su ID.

    El ID se guarda en la tabla Lead para poder mover o cancelar la cita
    más adelante sin buscarla a mano en el calendario.
    """
    fin = inicio + timedelta(minutes=config.APPOINTMENT_DURATION_MINUTES)

    descripcion = f"Cita agendada por el bot de WhatsApp.\n\nTeléfono: {telefono}"
    if detalle:
        descripcion += f"\nMotivo: {detalle}"

    evento = {
        # `rellenar` y no `.format`: el título del evento lo escribe el
        # dueño, y una llave que format no reconozca reventaría el
        # agendado entero — la cita no se crearía y el cliente se
        # quedaría esperando. Ver `app/core/huecos.py`.
        "summary": rellenar(config.CALENDAR_EVENT_TITLE, name=nombre),
        "description": descripcion,
        "start": {"dateTime": inicio.isoformat(), "timeZone": config.BUSINESS_TIMEZONE},
        "end": {"dateTime": fin.isoformat(), "timeZone": config.BUSINESS_TIMEZONE},
    }

    try:
        creado = google_client.calendar().events().insert(
            calendarId=google_client.id_calendario(), body=evento
        ).execute()
    except Exception as e:
        raise CalendarNoDisponible(f"No se pudo crear el evento: {e}") from e

    return creado["id"]
