"""
EL BOT AGENDA EN LA BARBERÍA (§6 de la especificación, guion 2d del handoff)
=============================================================================
Cuando un negocio tiene `proveedor_agenda = "barberia"`, la opción "cita" del
menú no va a Google Calendar: pregunta sede → servicio → barbero → día →
hora y reserva en la agenda de la barbería (`agenda.reservar`), que es la
única fuente de verdad.

Los negocios de siempre (Google Calendar) no pasan por aquí: `bot_logic`
solo desvía cuando `es_barberia()` lo dice. Por eso este módulo no toca el
camino de Google, y lo que no es de barbería sigue igual que ayer.

EL ESTADO
---------
    BARB_SEDE → BARB_SERVICIO → BARB_BARBERO → BARB_DIA → BARB_HORA

Lo elegido viaja en `contact.temp_data` como JSON ({"sede", "servicio",
"barbero", "dia"}). Un paso que solo tiene una opción (una sede, un
barbero) se salta solo.

LA CITA QUEDA TAMBIÉN COMO LEAD
-------------------------------
Además de la cita, se guarda un `Lead` de tipo "cita" con
`google_event_id = "barb:{id}"`. Así "Cancelar" y "Reagendar", el aviso al
dueño y todo lo que el bot ya sabe hacer con una cita siguen funcionando;
`bot_logic._gestionar_cita` mira ese prefijo para cancelar en la agenda de
la barbería y no en Google.

LOS TOPES DE META
-----------------
Filas de lista: 24 caracteres de título y 72 de descripción, 10 filas.
Botones: 20 caracteres y 3 como mucho. Los aplica `whatsapp_client`, pero
aquí se recortan ANTES para que lo recortado siga teniendo sentido.
"""

import json
from datetime import date, datetime

from app.barberia import agenda, formato
from app.barberia import modelos as m
from app.barberia.operacion import Error, _session, servicios_de_sede
from app.core import database, tenencia

PREFIJO_LEAD = "barb:"
ESTADOS = ("BARB_SEDE", "BARB_SERVICIO", "BARB_BARBERO", "BARB_DIA", "BARB_HORA")

# Los botones del recordatorio (`recordatorios.py`). Llevan el id de la cita.
BOTON_CONFIRMO = "brec_ok_"
BOTON_CANCELO = "brec_no_"


def es_barberia() -> bool:
    """
    ¿Este negocio agenda en la barbería y no en Google Calendar?

    Sin inquilino (las pruebas del bot y el camino de un solo negocio usan
    la configuración base) no es una barbería: se contesta que no en vez de
    levantar `SinInquilino`, que dejaría mudo al bot de siempre.
    """
    client_id = tenencia.actual_o_none()
    if client_id is None:
        return False
    datos = tenencia.por_id(client_id)
    fila = datos.fila if datos else {}
    return bool(fila.get("barberia_contratada")) and fila.get("proveedor_agenda") == "barberia"


def _wa():
    from app.bot import whatsapp_client
    return whatsapp_client


def _cortar(texto: str, largo: int) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= largo else texto[:largo - 1].rstrip() + "…"


def _datos(contact) -> dict:
    try:
        return json.loads(contact.temp_data or "{}") or {}
    except (TypeError, ValueError):
        return {}


def _guardar(contact, **cambios) -> dict:
    datos = dict(_datos(contact), **cambios)
    contact.temp_data = json.dumps(datos)
    return datos


def _lista(contact, texto: str, boton: str, filas: list, estado: str):
    _wa().send_list_message(contact.phone, texto, _cortar(boton, 20),
                            [{"id": f["id"], "title": _cortar(f["title"], 24),
                              **({"description": _cortar(f["description"], 72)}
                                 if f.get("description") else {})}
                             for f in filas[:10]], "Opciones")
    contact.state = estado


# ══════════════════════════════════════════════════════════════════════
#  EL RECORRIDO
# ══════════════════════════════════════════════════════════════════════

def _sedes() -> list:
    s = _session()
    try:
        return [(x.id, x.nombre, x.direccion or "") for x in
                s.query(m.Sede).filter_by(activo=True).order_by(m.Sede.id)]
    finally:
        s.close()


def iniciar(contact, session, texto: str | None = None) -> bool:
    """Empieza (o reempieza) a agendar. Devuelve True: siempre responde algo."""
    contact.temp_data = None
    sedes = _sedes()
    if not sedes:
        _sin_agenda(contact, session, "sin sedes")
        return True
    if len(sedes) == 1:
        _guardar(contact, sede=sedes[0][0])
        _pedir_servicio(contact, session)
        return True
    _lista(contact, texto or "¿En qué sede te atendemos?", "Ver sedes",
           [{"id": f"bsede_{i}", "title": n, "description": d} for i, n, d in sedes],
           "BARB_SEDE")
    return True


def _ultima_visita(contact) -> str:
    """"La última vez fue Corte clásico con Andrés." (usa el historial del contacto)."""
    s = _session()
    try:
        cli = s.query(m.ClienteBarberia).filter_by(contact_id=contact.id).first()
        if cli is None:
            return ""
        c = (s.query(m.Cita).filter_by(cliente_id=cli.id, estado=m.COMPLETADA)
             .order_by(m.Cita.inicio.desc()).first())
        if c is None:
            return ""
        servicios = [cs.nombre for cs in s.query(m.CitaServicio).filter_by(cita_id=c.id)]
        barbero = s.get(m.Personal, c.barbero_id).nombre.split(" ")[0]
        return f"La última vez fue {', '.join(servicios)} con {barbero}." if servicios else ""
    finally:
        s.close()


def _pedir_servicio(contact, session, texto: str | None = None):
    datos = _datos(contact)
    servicios = servicios_de_sede(datos["sede"])
    if not servicios:
        _sin_agenda(contact, session, "sede sin servicios")
        return
    nombre = f"¡Hola, {contact.name.split(' ')[0]}! " if contact.name else ""
    ultima = _ultima_visita(contact)
    pregunta = texto or f"{nombre}¿Qué te vas a hacer?{(' ' + ultima) if ultima else ''}"
    _lista(contact, pregunta, "Ver servicios",
           [{"id": f"bserv_{sv['id']}", "title": sv["nombre"],
             "description": f"{formato.pesos(sv['precio'])} · {sv['minutos']} min"}
            for sv in servicios], "BARB_SERVICIO")


def _pedir_barbero(contact, session, texto: str | None = None):
    datos = _datos(contact)
    barberos = agenda.barberos_de(datos["sede"])
    if not barberos:
        _sin_agenda(contact, session, "sede sin barberos")
        return
    if len(barberos) == 1:
        _guardar(contact, barbero=barberos[0][0])
        _pedir_dia(contact, session)
        return
    filas = [{"id": "bbarb_0", "title": "El que esté libre",
              "description": "Te damos la hora más cercana"}]
    filas += [{"id": f"bbarb_{i}", "title": n} for i, n in barberos]
    _lista(contact, texto or "¿Con quién te quieres atender?", "Ver barberos", filas,
           "BARB_BARBERO")


def _dia_corto(dia: date, hoy: date) -> str:
    base = f"{formato.DIAS[dia.weekday()][:3].capitalize()} {dia.day} de {formato.MESES[dia.month - 1][:3]}"
    if dia == hoy:
        return f"Hoy, {base.lower()}"
    if (dia - hoy).days == 1:
        return f"Mañana, {base.lower()}"
    return base


def _pedir_dia(contact, session, texto: str | None = None):
    datos = _datos(contact)
    minutos = agenda.duracion(datos["sede"], datos["servicio"])
    hoy = formato.hoy_en(formato.ZONA)
    dias = agenda.dias_con_huecos(datos["sede"], datos.get("barbero") or None, minutos, hoy)
    if not dias:
        _sin_agenda(contact, session, "sin horarios libres")
        return
    _lista(contact, texto or "¿Qué día te queda bien?", "Ver días",
           [{"id": f"bdia_{d.isoformat()}", "title": _dia_corto(d, hoy),
             "description": formato.plural(n, "horario libre", "horarios libres")}
            for d, n in dias], "BARB_DIA")


def _pedir_hora(contact, session, texto: str | None = None):
    datos = _datos(contact)
    dia = date.fromisoformat(datos["dia"])
    minutos = agenda.duracion(datos["sede"], datos["servicio"])
    huecos = list(agenda.huecos_de(datos["sede"], datos.get("barbero") or None, dia, minutos))
    if not huecos:
        _pedir_dia(contact, session, "Ese día se llenó. ¿Qué otro día te queda bien?")
        return
    # Hasta 10 filas: si hay más, repartidas a lo largo del día y no solo
    # las de la mañana (el mismo tropiezo que ya tuvo el camino de Google).
    if len(huecos) > 10:
        paso = len(huecos) / 10
        huecos = [huecos[int(i * paso)] for i in range(10)]
    hoy = formato.hoy_en(formato.ZONA)
    quien = ""
    if datos.get("barbero"):
        s = _session()
        try:
            quien = s.get(m.Personal, datos["barbero"]).nombre.split(" ")[0]
        finally:
            s.close()
    mensaje = texto or (f"{quien} tiene libre el {_dia_corto(dia, hoy).lower()}:" if quien
                        else f"Horas libres el {_dia_corto(dia, hoy).lower()}:")
    opciones = [{"id": f"bhora_{t.isoformat()}", "title": formato.hora(t)} for t in huecos]
    if len(opciones) <= 3:
        _wa().send_button_message(contact.phone, mensaje, opciones)
        contact.state = "BARB_HORA"
    else:
        _lista(contact, mensaje, "Ver horas", opciones, "BARB_HORA")


def _cliente_de(contact) -> int:
    """La ficha del cliente de este contacto (por su WhatsApp), o una nueva."""
    telefono = "".join(c for c in contact.phone if c.isdigit())
    local = telefono[-10:]
    s = _session()
    try:
        cli = (s.query(m.ClienteBarberia).filter(
            (m.ClienteBarberia.contact_id == contact.id) | (m.ClienteBarberia.telefono == local))
            .first())
        if cli is None:
            cli = m.ClienteBarberia(nombre=contact.name or f"WhatsApp {local[-4:]}",
                                    telefono=local, contact_id=contact.id)
            s.add(cli)
        else:
            cli.contact_id = cli.contact_id or contact.id
            if contact.name and cli.nombre.startswith(("WhatsApp", "3")):
                cli.nombre = contact.name
        s.commit()
        return cli.id
    finally:
        s.close()


def _reservar(contact, session, inicio: datetime):
    from app.bot import bot_logic

    datos = _datos(contact)
    try:
        cita_id, barbero_id = agenda.reservar(
            datos["sede"], datos.get("barbero") or None, datos["servicio"], inicio,
            origen=m.WHATSAPP, cliente_id=_cliente_de(contact), actor="Bot de WhatsApp")
    except agenda.Ocupado:
        _pedir_hora(contact, session, "Esa hora se acaba de ocupar. Estas siguen libres:")
        return
    except Error as ex:
        print(f"[barberia.bot] No se pudo reservar para {contact.phone}: {ex}")
        _sin_agenda(contact, session, "error al reservar")
        return

    s = _session()
    try:
        cita = s.get(m.Cita, cita_id)
        sede = s.get(m.Sede, cita.sede_id)
        barbero = s.get(m.Personal, barbero_id).nombre.split(" ")[0]
        servicio = next(sv for sv in servicios_de_sede(cita.sede_id)
                        if sv["id"] == cita.servicio_id)
    finally:
        s.close()

    hoy = formato.hoy_en(formato.ZONA)
    dia = formato.a_local(inicio).date()
    fecha_texto = _dia_corto(dia, hoy)
    hora_texto = formato.hora(inicio)
    session.add(database.Lead(contact_id=contact.id, type="cita", appointment_date=fecha_texto,
                              appointment_time=hora_texto,
                              google_event_id=f"{PREFIJO_LEAD}{cita_id}", status="notificado"))
    bot_logic._notify_owner_appointment(contact, fecha_texto, hora_texto)
    contact.temp_data = None

    lugar = f"{sede.nombre}, {sede.direccion}" if sede.direccion else sede.nombre
    bot_logic._ofrecer_cierre(
        contact,
        f"Listo, quedó tu cita ✂️\n\n{servicio['nombre']} con {barbero}\n"
        f"{fecha_texto}, {hora_texto}\n{lugar}\n{formato.pesos(servicio['precio'])}\n\n"
        f"Te escribo 2 horas antes para que confirmes.")


def _sin_agenda(contact, session, motivo: str):
    """Nada que ofrecer: la cita no se pierde, la confirma una persona."""
    from app.bot import bot_logic
    contact.temp_data = None
    bot_logic._registrar_cita_manual(contact, session, motivo=motivo)


def manejar(contact, session, eleccion: str | None, texto: str | None) -> None:
    """Lo que contestó el cliente en un paso del recorrido."""
    from app.bot import bot_logic
    from app import config

    estado = contact.state
    eleccion = eleccion or ""
    pasos = {"BARB_SEDE": ("bsede_", "sede"), "BARB_SERVICIO": ("bserv_", "servicio"),
             "BARB_BARBERO": ("bbarb_", "barbero"), "BARB_DIA": ("bdia_", "dia"),
             "BARB_HORA": ("bhora_", "hora")}
    prefijo, campo = pasos[estado]

    if not eleccion.startswith(prefijo):
        # Escribió en vez de tocar la lista. Si es otra opción del menú,
        # cambió de idea (como en el camino de Google); si no, se le vuelve
        # a preguntar lo mismo.
        if bot_logic._entender_texto(contact, session, texto, con_respuesta=False):
            return
        _repreguntar(contact, session, estado, config.FALLBACK_MESSAGE)
        return

    valor = eleccion[len(prefijo):]
    try:
        if campo == "sede":
            _guardar(contact, sede=int(valor))
            _pedir_servicio(contact, session)
        elif campo == "servicio":
            _guardar(contact, servicio=int(valor))
            _pedir_barbero(contact, session)
        elif campo == "barbero":
            _guardar(contact, barbero=int(valor) or None)
            _pedir_dia(contact, session)
        elif campo == "dia":
            _guardar(contact, dia=date.fromisoformat(valor).isoformat())
            _pedir_hora(contact, session)
        else:
            _reservar(contact, session, datetime.fromisoformat(valor))
    except (ValueError, KeyError, Error) as ex:
        # Un botón viejo, o datos que ya no cuadran (se quitó el servicio):
        # se vuelve a empezar en vez de quedarse mudo.
        print(f"[barberia.bot] Paso {estado} con {eleccion!r}: {ex}. Se reinicia.")
        iniciar(contact, session, "Empecemos otra vez. ¿En qué sede te atendemos?")


def _repreguntar(contact, session, estado: str, texto: str):
    datos = _datos(contact)
    if estado == "BARB_SEDE" or "sede" not in datos:
        iniciar(contact, session, texto)
    elif estado == "BARB_SERVICIO":
        _pedir_servicio(contact, session, texto)
    elif estado == "BARB_BARBERO":
        _pedir_barbero(contact, session, texto)
    elif estado == "BARB_DIA":
        _pedir_dia(contact, session, texto)
    else:
        _pedir_hora(contact, session, texto)


# ══════════════════════════════════════════════════════════════════════
#  CANCELAR DESDE EL BOT Y LOS BOTONES DEL RECORDATORIO
# ══════════════════════════════════════════════════════════════════════

def cancelar_por_lead(google_event_id: str) -> bool:
    """La cita de barbería detrás de un Lead ("barb:{id}"). True si se canceló."""
    try:
        cita_id = int(google_event_id[len(PREFIJO_LEAD):])
        agenda.cancelar(cita_id, "El cliente la canceló por WhatsApp", actor="Bot de WhatsApp")
        return True
    except (ValueError, Error) as ex:
        print(f"[barberia.bot] No se pudo cancelar {google_event_id}: {ex}")
        return False


def _cita_del_contacto(contact, cita_id: int):
    """La cita, solo si es de ESTE contacto (el id viaja en un botón)."""
    s = _session()
    try:
        c = s.get(m.Cita, cita_id)
        if c is None or not c.cliente_id:
            return None
        cli = s.get(m.ClienteBarberia, c.cliente_id)
        telefono = "".join(x for x in contact.phone if x.isdigit())
        if cli.contact_id != contact.id and not telefono.endswith(cli.telefono or "-"):
            return None
        return {"id": c.id, "estado": c.estado, "inicio": m.en_utc(c.inicio)}
    finally:
        s.close()


def respuesta_recordatorio(contact, session, boton: str) -> None:
    """"Confirmo" o "Cancelar" del recordatorio de 2 horas antes."""
    from app.bot import bot_logic
    confirma = boton.startswith(BOTON_CONFIRMO)
    try:
        cita_id = int(boton[len(BOTON_CONFIRMO if confirma else BOTON_CANCELO):])
    except ValueError:
        return
    cita = _cita_del_contacto(contact, cita_id)
    if cita is None or cita["estado"] not in agenda.ACTIVAS:
        bot_logic._ofrecer_cierre(contact, "Esa cita ya no está activa.")
        return
    hora = formato.hora(cita["inicio"])
    if confirma:
        s = _session()
        try:
            c = s.get(m.Cita, cita_id)
            if c.estado == m.PENDIENTE:
                c.estado = m.CONFIRMADA
            s.commit()
        finally:
            s.close()
        bot_logic._ofrecer_cierre(contact, f"¡Perfecto! Te esperamos a las {hora}.")
        return
    agenda.cancelar(cita_id, "El cliente la canceló desde el recordatorio",
                    actor="Bot de WhatsApp")
    lead = (session.query(database.Lead)
            .filter_by(contact_id=contact.id, google_event_id=f"{PREFIJO_LEAD}{cita_id}").first())
    if lead is not None:
        lead.status = "cancelada"
    bot_logic._ofrecer_cierre(contact, f"Listo, cancelé tu cita de las {hora}. "
                                       f"Cuando quieras, agenda otra desde el menú.")
