"""
EL RECORDATORIO DE 2 HORAS ANTES (§6.4 de la especificación)
=============================================================
Una revisión cada 10 minutos, dentro del mismo proceso (como `cobros.vigilar`):
cada cita confirmada o pendiente que empieza en las próximas 2 horas y
todavía no tiene recordatorio recibe UNO, con dos botones: "Confirmo" y
"Cancelar" (los atiende `bot.respuesta_recordatorio`).

SOLO SI EL PLAN TRAE EL BOT
---------------------------
Sin bot no hay número de WhatsApp desde el que escribir. Esos recordatorios
(por correo o notificación) quedan para después: casi ningún cliente de
barbería deja correo, y la notificación al celular es del barbero, no del
cliente.

LA VENTANA DE 24 HORAS
----------------------
WhatsApp solo deja mandar texto libre a quien escribió en las últimas 24 h
(`notificaciones.ventana_abierta`). Quien agendó ayer por la tarde ya la
tiene cerrada, y ahí solo vale una PLANTILLA aprobada por Meta. Si el
negocio la tiene puesta en su contenido
(`negocio_config["barberia"]["plantilla_recordatorio"]`, variables: nombre,
hora, barbero, sede) sale por plantilla, sin botones; si no, el recordatorio
no sale y se anota en el log. En los dos casos la cita queda marcada, para
no reintentar cada 10 minutos.

    ⚠️  Cada plantilla la cobra Meta. Es el costo que la especificación pide
    tener en cuenta al poner el precio del plan con bot.
"""

import asyncio
from datetime import timedelta

from app.barberia import formato
from app.barberia import modelos as m
from app.core import database, tenencia

SEGUNDOS_ENTRE_REVISIONES = 600
ANTICIPACION = timedelta(hours=2)


def _numero(s, cita: m.Cita) -> str | None:
    """El WhatsApp del cliente: el de su contacto del bot, o su celular con el 57."""
    if not cita.cliente_id:
        return None
    cli = s.get(m.ClienteBarberia, cita.cliente_id)
    if cli is None:
        return None
    if cli.contact_id:
        contacto = s.get(database.Contact, cli.contact_id)
        if contacto is not None:
            return contacto.phone
    if cli.telefono and len(cli.telefono) == 10:
        return "57" + cli.telefono
    return cli.telefono or None


def recordar_negocio(client_id: int) -> int:
    """Los recordatorios de una barbería. Con su inquilino. Devuelve cuántos salieron."""
    from app.bot import notificaciones
    from app.bot import whatsapp_client as wa

    ahora = m.ahora()
    enviados = 0
    datos = tenencia.por_id(client_id)
    negocio = (datos.fila.get("negocio_config") if datos else None) or {}
    plantilla = (negocio.get("barberia") or {}).get("plantilla_recordatorio")
    with tenencia.usar(client_id):
        s = database.get_session()
        try:
            citas = (s.query(m.Cita)
                     .filter(m.Cita.estado.in_((m.PENDIENTE, m.CONFIRMADA)),
                             m.Cita.recordatorio_en.is_(None),
                             m.Cita.inicio > ahora, m.Cita.inicio <= ahora + ANTICIPACION)
                     .all())
            for cita in citas:
                cita.recordatorio_en = ahora
                numero = _numero(s, cita)
                if not numero:
                    continue
                cli = s.get(m.ClienteBarberia, cita.cliente_id)
                barbero = s.get(m.Personal, cita.barbero_id).nombre.split(" ")[0]
                sede = s.get(m.Sede, cita.sede_id).nombre
                hora = formato.hora(cita.inicio)
                nombre = (cli.nombre or "").split(" ")[0]
                try:
                    if notificaciones.ventana_abierta(numero):
                        wa.send_button_message(
                            numero,
                            f"Hola, {nombre}. Te recuerdo tu cita de hoy a las {hora} con "
                            f"{barbero} en {sede}. ¿Nos confirmas?",
                            [{"id": f"brec_ok_{cita.id}", "title": "Confirmo"},
                             {"id": f"brec_no_{cita.id}", "title": "Cancelar"}])
                        enviados += 1
                        continue
                    if plantilla:
                        wa.send_template_message(numero, plantilla, "es",
                                                 [nombre, hora, barbero, sede])
                        enviados += 1
                    else:
                        print(f"[recordatorios] Cita {cita.id}: ventana cerrada y sin "
                              f"plantilla de recordatorio; no se le escribió.")
                except Exception as e:                        # pragma: no cover
                    print(f"[recordatorios] Cita {cita.id}: no salió el recordatorio: {e}")
            s.commit()
        finally:
            s.close()
    return enviados


def revisar_todos() -> int:
    """Las barberías que agendan en su panel y tienen el bot."""
    with tenencia.sin_inquilino():
        s = database.get_session()
        try:
            ids = [i for (i,) in s.query(database.Client.id).filter(
                database.Client.active.is_(True),
                database.Client.barberia_contratada.is_(True),
                database.Client.bot_contratado.is_(True),
                database.Client.proveedor_agenda == "barberia")]
        finally:
            s.close()
    total = 0
    for client_id in ids:
        try:
            total += recordar_negocio(client_id)
        except Exception as e:                                # pragma: no cover
            print(f"[recordatorios] {client_id}: la revisión falló: {e}")
    return total


async def vigilar():
    """Cada 10 minutos mientras el servicio viva. Nunca se cae."""
    from starlette.concurrency import run_in_threadpool

    while True:
        try:
            enviados = await run_in_threadpool(revisar_todos)
            if enviados:
                print(f"[recordatorios] {enviados} recordatorio(s) enviados.")
        except Exception as e:
            print(f"[recordatorios] La revisión falló, se reintenta: {e}")
        await asyncio.sleep(SEGUNDOS_ENTRE_REVISIONES)
