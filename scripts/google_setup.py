"""
DIAGNÓSTICO DE GOOGLE
======================
Comprueba que la cuenta de servicio pueda de verdad LEER y ESCRIBIR en el
calendario y en el Sheet del negocio.

Compartir el calendario y el Sheet con el email de la cuenta de servicio
es un paso aparte de crearla, y es el que más se olvida. Cuando falta,
Google responde 404 "no encontrado" en vez de un error de permisos, lo
cual despista bastante — de ahí que este script lo diga explícitamente.

Uso (desde la raíz del proyecto):
    python scripts/google_setup.py check
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

from googleapiclient.errors import HttpError

# Al correr "python scripts/google_setup.py", Python solo pone scripts/ en la
# ruta de búsqueda, así que el paquete app no se encontraría. Añadimos la
# raíz del proyecto antes de importarlo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config  # noqa: E402
from app.integrations import google_client  # noqa: E402

OK = "[OK]"
FAIL = "[X]"
WARN = "[!]"

# Nombre de la pestaña temporal que se crea y se borra para probar
# escritura sin tocar nada de lo que ya haya en el Sheet.
HOJA_PRUEBA = "_prueba_bot_borrar"


def _explicar_error(e: HttpError, recurso: str, email: str) -> str:
    estado = e.resp.status
    if estado == 404:
        return (f"No encontrado. Casi siempre significa que NO le compartiste "
                f"{recurso} a {email}, no que el ID esté mal.")
    if estado == 403:
        detalle = str(e)
        if "has not been used" in detalle or "is disabled" in detalle:
            return "La API no está habilitada en el proyecto de Google Cloud."
        return (f"Sin permiso. La cuenta de servicio ve {recurso} pero solo "
                f"puede leer: cámbiale el acceso a edición.")
    return f"HTTP {estado}: {e}"


def cmd_check(args):
    problemas = 0

    print("\n=== 1. Credenciales de la cuenta de servicio ===")
    try:
        email = google_client.email_cuenta_servicio()
        print(f"    {OK} JSON cargado correctamente.")
        print(f"    ... email: {email}")
    except Exception as e:
        print(f"    {FAIL} {e}")
        return 1

    print("\n=== 2. Configuración del negocio ===")
    print(f"    ... zona horaria: {config.BUSINESS_TIMEZONE}")
    print(f"    ... horario: {config.BUSINESS_HOURS_START} a {config.BUSINESS_HOURS_END}")
    print(f"    ... duración de cada cita: {config.APPOINTMENT_DURATION_MINUTES} min")
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    print(f"    ... días laborables: {', '.join(dias[d] for d in config.BUSINESS_DAYS)}")

    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(config.BUSINESS_TIMEZONE)
        print(f"    {OK} La zona horaria es válida.")
    except Exception:
        print(f"    {FAIL} Zona horaria '{config.BUSINESS_TIMEZONE}' desconocida. "
              f"Usa un nombre tipo 'America/Bogota'.")
        problemas += 1

    problemas += _check_calendar(email)
    problemas += _check_sheets(email)

    print()
    if problemas:
        print(f"{FAIL} {problemas} problema(s). Revisa arriba.")
    else:
        print(f"{OK} Google quedó listo: lectura y escritura confirmadas.")
    return 1 if problemas else 0


def _check_calendar(email):
    print("\n=== 3. Google Calendar ===")
    try:
        cal_id = google_client.id_calendario()
    except Exception as e:
        print(f"    {FAIL} {e}")
        return 1

    servicio = google_client.calendar()
    print(f"    ... calendario: {cal_id}")

    # Lectura
    try:
        info = servicio.calendars().get(calendarId=cal_id).execute()
        print(f"    {OK} Lectura OK — '{info.get('summary')}' "
              f"(zona del calendario: {info.get('timeZone')})")
    except HttpError as e:
        print(f"    {FAIL} No se puede leer el calendario.")
        print(f"        {_explicar_error(e, 'el calendario', email)}")
        return 1

    if info.get("timeZone") != config.BUSINESS_TIMEZONE:
        print(f"    {WARN} El calendario está en {info.get('timeZone')} y el bot "
              f"en {config.BUSINESS_TIMEZONE}.")
        print("        No es un error: el bot manda la zona en cada evento. "
              "Pero conviene que coincidan para no confundirte al mirar la agenda.")

    # Escritura: creamos un evento lejano y lo borramos enseguida.
    inicio = datetime.now() + timedelta(days=365)
    evento = {
        "summary": "PRUEBA del bot — se borra sola",
        "description": "Evento creado por google_setup.py para verificar permisos.",
        "start": {"dateTime": inicio.isoformat(), "timeZone": config.BUSINESS_TIMEZONE},
        "end": {"dateTime": (inicio + timedelta(minutes=15)).isoformat(),
                "timeZone": config.BUSINESS_TIMEZONE},
    }
    try:
        creado = servicio.events().insert(calendarId=cal_id, body=evento).execute()
    except HttpError as e:
        print(f"    {FAIL} Puede leer pero NO puede crear eventos.")
        print(f"        {_explicar_error(e, 'el calendario', email)}")
        print("        Compártelo con permiso 'Hacer cambios en los eventos'.")
        return 1

    try:
        servicio.events().delete(calendarId=cal_id, eventId=creado["id"]).execute()
        print(f"    {OK} Escritura OK — evento de prueba creado y borrado.")
    except HttpError:
        print(f"    {WARN} Se creó el evento de prueba pero no se pudo borrar. "
              f"Búscalo dentro de un año y bórralo a mano.")

    return 0


def _check_sheets(email):
    print("\n=== 4. Google Sheets ===")
    try:
        hoja_id = google_client.id_spreadsheet()
    except Exception as e:
        print(f"    {FAIL} {e}")
        return 1

    if config.GOOGLE_SHEETS_SPREADSHEET_ID.strip() != hoja_id:
        print(f"    {WARN} Pegaste la URL completa en el .env; se extrajo el ID solo.")
        print(f"        Funciona igual, pero queda más limpio dejar: {hoja_id}")

    servicio = google_client.sheets()
    print(f"    ... spreadsheet: {hoja_id}")

    try:
        info = servicio.spreadsheets().get(spreadsheetId=hoja_id).execute()
    except HttpError as e:
        print(f"    {FAIL} No se puede leer el Sheet.")
        print(f"        {_explicar_error(e, 'el Sheet', email)}")
        return 1

    pestanas = [h["properties"]["title"] for h in info.get("sheets", [])]
    print(f"    {OK} Lectura OK — '{info['properties']['title']}'")
    print(f"    ... pestañas actuales: {', '.join(pestanas)}")

    # Escritura: creamos una pestaña temporal y la borramos. Así no se
    # toca ninguna celda de lo que el dueño ya tenga escrito.
    try:
        respuesta = servicio.spreadsheets().batchUpdate(
            spreadsheetId=hoja_id,
            body={"requests": [{"addSheet": {"properties": {"title": HOJA_PRUEBA}}}]},
        ).execute()
        nueva_id = respuesta["replies"][0]["addSheet"]["properties"]["sheetId"]
    except HttpError as e:
        print(f"    {FAIL} Puede leer pero NO puede escribir.")
        print(f"        {_explicar_error(e, 'el Sheet', email)}")
        print("        Compártelo con permiso de 'Editor'.")
        return 1

    try:
        servicio.spreadsheets().batchUpdate(
            spreadsheetId=hoja_id,
            body={"requests": [{"deleteSheet": {"sheetId": nueva_id}}]},
        ).execute()
        print(f"    {OK} Escritura OK — pestaña de prueba creada y borrada.")
    except HttpError:
        print(f"    {WARN} Quedó una pestaña '{HOJA_PRUEBA}' sin borrar. "
              f"Elimínala a mano.")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Diagnóstico de Google Calendar y Sheets")
    parser.add_argument(
        "--cliente", default="",
        help="Id o nombre corto del negocio sobre el que trabajar. "
             "Sin esto se usan las credenciales del .env.")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("check", help="Verifica credenciales, calendario y Sheet")

    args = parser.parse_args()

    # Igual que en meta_setup: cada cliente tiene su calendario y su hoja,
    # así que revisarlos exige mirar SU configuración, no la del .env.
    if not args.cliente:
        return cmd_check(args)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scripts.meta_setup import _inquilino

    with _inquilino(args.cliente):
        return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
