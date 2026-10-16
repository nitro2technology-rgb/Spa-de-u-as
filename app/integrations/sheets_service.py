"""
SEGUIMIENTO EN GOOGLE SHEETS
=============================
Cada lead que genera el bot se agrega como una fila del Sheet del negocio,
en la pestaña de su servicio. Las citas van además a su propia pestaña.

Es solo de ida: el dueño puede marcar filas como "confirmada" o poner
notas y el bot no lo toca ni lo lee. El Sheet es su tablero, no una
segunda base de datos.

Ninguna función de aquí puede romper una conversación: si Google falla,
se registra el error y el bot sigue como si nada. El lead ya está guardado
en la base y ya se notificó por WhatsApp — el Sheet es un extra.
"""

from googleapiclient.errors import HttpError

from app import config
from app.integrations import google_client
from app.integrations.calendar_service import ahora_local

# Las pestañas se comprueban una vez por arranque, no en cada lead: sería
# una llamada extra a Google en cada mensaje.
#
# Es un conjunto de inquilinos ya comprobados y no un booleano: cada
# negocio tiene su propio Sheet, y con una sola bandera el primero en
# arrancar daba por buenos los Sheets de todos los demás — que podían no
# tener ni las pestañas creadas.
_pestanas_verificadas: set = set()


def _rango(nombre_pestana: str) -> str:
    """Las comillas simples permiten nombres de pestaña con espacios."""
    return f"'{nombre_pestana}'!A:Z"


def asegurar_pestanas(forzar: bool = False) -> bool:
    """
    Crea las pestañas que falten y les escribe la fila de encabezados.

    Si el Sheet está recién creado y solo tiene la pestaña por defecto
    vacía ("Hoja 1"), la renombra en vez de dejarla ahí sin usar.

    Devuelve True si el Sheet quedó listo.
    """
    from app.core import tenencia
    quien = tenencia.actual_o_none() or 0

    if quien in _pestanas_verificadas and not forzar:
        return True

    servicio = google_client.sheets()
    hoja_id = google_client.id_spreadsheet()

    info = servicio.spreadsheets().get(spreadsheetId=hoja_id).execute()
    existentes = {h["properties"]["title"]: h["properties"] for h in info["sheets"]}

    faltantes = [
        datos["nombre"] for datos in config.SHEETS_TABS.values()
        if datos["nombre"] not in existentes
    ]
    if not faltantes:
        _pestanas_verificadas.add(quien)
        return True

    peticiones = []

    # ¿Hay una pestaña por defecto vacía que podamos reaprovechar?
    vacia_por_defecto = None
    for nombre in config.SHEETS_DEFAULT_TABS:
        props = existentes.get(nombre)
        if props and _esta_vacia(servicio, hoja_id, nombre):
            vacia_por_defecto = props
            break

    if vacia_por_defecto:
        peticiones.append({
            "updateSheetProperties": {
                "properties": {"sheetId": vacia_por_defecto["sheetId"],
                               "title": faltantes[0]},
                "fields": "title",
            }
        })
        print(f"[sheets] Pestaña '{vacia_por_defecto['title']}' renombrada "
              f"a '{faltantes[0]}'.")
        faltantes = faltantes[1:]

    for nombre in faltantes:
        peticiones.append({"addSheet": {"properties": {"title": nombre}}})
        print(f"[sheets] Pestaña '{nombre}' creada.")

    if peticiones:
        servicio.spreadsheets().batchUpdate(
            spreadsheetId=hoja_id, body={"requests": peticiones}
        ).execute()

    _escribir_encabezados(servicio, hoja_id)
    _pestanas_verificadas.add(quien)
    return True


def _esta_vacia(servicio, hoja_id: str, nombre: str) -> bool:
    """True si la pestaña no tiene ni una celda escrita."""
    try:
        valores = servicio.spreadsheets().values().get(
            spreadsheetId=hoja_id, range=_rango(nombre)
        ).execute()
        return not valores.get("values")
    except HttpError:
        return False


def _escribir_encabezados(servicio, hoja_id: str):
    """
    Pone la fila de títulos en las pestañas que estén vacías.

    Solo escribe si la pestaña no tiene nada: si ya tiene datos, no
    tocamos la primera fila para no pisar encabezados que el dueño haya
    ajustado a mano.
    """
    for datos in config.SHEETS_TABS.values():
        if not _esta_vacia(servicio, hoja_id, datos["nombre"]):
            continue

        servicio.spreadsheets().values().update(
            spreadsheetId=hoja_id,
            range=f"'{datos['nombre']}'!A1",
            valueInputOption="RAW",
            body={"values": [datos["columnas"]]},
        ).execute()


def _fila(destino: str, contacto: dict, lead: dict) -> list:
    """
    Arma la fila según el formato de la pestaña, en el mismo orden que sus
    columnas.

    La fecha va en formato ISO (año-mes-día) a propósito: como se escribe
    como texto, ordenar la columna en el Sheet sigue dando el orden
    cronológico correcto. Con "06/08/2026" no pasaría.
    """
    fecha = ahora_local().strftime("%Y-%m-%d %H:%M")
    nombre = contacto.get("name") or "(sin nombre)"
    telefono = contacto.get("phone", "")
    origen = contacto.get("origen") or config.ORIGEN_POR_DEFECTO
    recorrido = contacto.get("recorrido") or ""

    if config.SHEETS_TABS[destino].get("formato") == "cita":
        return [fecha, nombre, telefono,
                contacto.get("servicio") or "(sin servicio)",
                recorrido,
                lead.get("appointment_date") or "por confirmar",
                lead.get("appointment_time") or "por confirmar",
                origen, "pendiente", lead.get("google_event_id") or ""]

    # Pestaña de servicio: el recorrido dice por dónde pasó y el mensaje
    # es lo que escribió el cliente, si escribió algo.
    return [fecha, nombre, telefono, recorrido,
            lead.get("detail") or "", origen, "pendiente"]


def _id_de_pestana(servicio, hoja_id: str, nombre: str):
    """El id numérico de la pestaña, que es lo que pide borrar filas."""
    info = servicio.spreadsheets().get(spreadsheetId=hoja_id).execute()
    for hoja in info["sheets"]:
        if hoja["properties"]["title"] == nombre:
            return hoja["properties"]["sheetId"]
    return None


def eliminar_fila(destino: str, columna: str, valor: str) -> bool:
    """
    Borra la ÚLTIMA fila de esa pestaña cuya `columna` valga `valor`.

    Se usa al cancelar o reagendar una cita: si la fila se quedara, el
    Sheet mostraría una reunión que ya no existe en el calendario.

    Se borra la última y no todas las que coincidan a propósito: si el
    mismo cliente agendó, canceló y volvió a agendar, cada gestión tiene
    su fila y solo sobra la de la cita que se acaba de deshacer.

    Nunca lanza excepción: dejar una fila de más es un problema de orden,
    no una razón para romperle la conversación a un cliente.
    """
    datos = config.SHEETS_TABS.get(destino)
    if not datos or not valor:
        return False

    if columna not in datos["columnas"]:
        print(f"[sheets] La pestaña '{datos['nombre']}' no tiene columna '{columna}'.")
        return False

    indice_col = datos["columnas"].index(columna)

    try:
        servicio = google_client.sheets()
        hoja_id = google_client.id_spreadsheet()

        filas = servicio.spreadsheets().values().get(
            spreadsheetId=hoja_id, range=_rango(datos["nombre"])
        ).execute().get("values", [])

        # De abajo arriba: nos interesa la más reciente. La fila 0 es la de
        # encabezados y no se toca nunca.
        objetivo = None
        for numero in range(len(filas) - 1, 0, -1):
            fila = filas[numero]
            if len(fila) > indice_col and fila[indice_col] == valor:
                objetivo = numero
                break

        if objetivo is None:
            print(f"[sheets] No había fila con {columna}={valor} en "
                  f"'{datos['nombre']}'.")
            return False

        pestana_id = _id_de_pestana(servicio, hoja_id, datos["nombre"])
        if pestana_id is None:
            return False

        servicio.spreadsheets().batchUpdate(
            spreadsheetId=hoja_id,
            body={"requests": [{"deleteDimension": {"range": {
                "sheetId": pestana_id,
                "dimension": "ROWS",
                "startIndex": objetivo,
                "endIndex": objetivo + 1,
            }}}]},
        ).execute()

        print(f"[sheets] Fila borrada de '{datos['nombre']}' ({columna}={valor}).")
        return True

    except Exception as e:
        print(f"[sheets] No se pudo borrar la fila de '{datos['nombre']}': {e}")
        return False


def registrar_lead(destino: str, contacto: dict, lead: dict) -> bool:
    """
    Agrega la fila al Sheet. Devuelve True si se escribió.

    Recibe diccionarios y no objetos de SQLAlchemy a propósito: así quien
    llama decide qué datos se comparten y esta función no depende de que
    la sesión de base de datos siga abierta.

    Nunca lanza excepción: un fallo del Sheet no puede tumbar una
    conversación con un cliente.
    """
    if destino not in config.SHEETS_TABS:
        print(f"[sheets] Pestaña desconocida '{destino}', no se registra.")
        return False

    try:
        asegurar_pestanas()

        google_client.sheets().spreadsheets().values().append(
            spreadsheetId=google_client.id_spreadsheet(),
            range=_rango(config.SHEETS_TABS[destino]["nombre"]),
            # RAW y no USER_ENTERED: con USER_ENTERED, Sheets "interpreta"
            # cada celda. La fecha se convertía en su número de serie
            # (46240.0125 en vez de la fecha) y los teléfonos en números,
            # perdiendo el cero inicial en los países que lo usan.
            # En RAW todo queda como texto, tal cual se escribió.
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [_fila(destino, contacto, lead)]},
        ).execute()

        print(f"[sheets] {contacto.get('phone')} agregado a la pestaña "
              f"'{config.SHEETS_TABS[destino]['nombre']}'.")
        return True

    except Exception as e:
        # A propósito atrapamos todo: credenciales mal, sin red, cuota
        # agotada, permiso revocado... nada de eso debe cortar el flujo.
        print(f"[sheets] No se pudo escribir en el Sheet: {e}")
        return False
