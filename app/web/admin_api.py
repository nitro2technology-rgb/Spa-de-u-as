"""
ENDPOINTS DE ADMINISTRACIÓN
============================
Diagnóstico (`/admin/status`) y operaciones sueltas por terminal: tomar el
control de una conversación, devolverla, cambiar el plan.

Protegidos con una clave fija en la cabecera `X-Admin-Key`, que sale de
ADMIN_API_KEY en .env. Si esa variable está vacía, los endpoints quedan
deshabilitados: es preferible a dejarlos abiertos a internet por olvido.

    ⚠️  Es una clave del SERVIDOR, no de un negocio. Sin cookie de sesión,
    el middleware resuelve el cliente por defecto: esto opera sobre el bot
    de casa. El panel de cada negocio va por su sesión (`admin_ui`).

Ejemplos:
    curl -X POST https://tu-dominio/admin/takeover \
         -H "X-Admin-Key: TU_CLAVE" \
         -H "Content-Type: application/json" \
         -d '{"phone": "573001234567"}'

    curl https://tu-dominio/admin/contacts?solo_humanos=true \
         -H "X-Admin-Key: TU_CLAVE"
"""

import hmac
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text as _text

from app import config
from app.bot import bot_logic

router = APIRouter(prefix="/admin", tags=["admin"])


class ContactoRequest(BaseModel):
    # Formato internacional sin "+", igual que OWNER_PHONE_NUMBER
    phone: str = Field(min_length=8, max_length=20)


class PlanRequest(BaseModel):
    # "basico" o "pro". Se valida en cerebro.cambiar_plan.
    plan: str = Field(min_length=3, max_length=10)


def _validar_clave(clave_recibida: str | None):
    if not config.ADMIN_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Endpoints de admin deshabilitados: define ADMIN_API_KEY en .env",
        )

    # compare_digest evita que se pueda adivinar la clave carácter a
    # carácter midiendo cuánto tarda la comparación en fallar. En bytes:
    # sobre `str` levanta TypeError con cualquier carácter no ASCII, y una
    # cabecera con una tilde daba un 500 en vez de un 401.
    if not clave_recibida or not hmac.compare_digest(
            clave_recibida.encode("utf-8"), config.ADMIN_API_KEY.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Clave de administración inválida")


@router.post("/takeover")
def tomar_control(datos: ContactoRequest, x_admin_key: str | None = Header(default=None)):
    """Marca un contacto como atendido por humano: el bot deja de responderle."""
    _validar_clave(x_admin_key)

    if not bot_logic.tomar_control_manual(datos.phone):
        raise HTTPException(status_code=404, detail="Ese contacto no existe todavía")

    return {
        "status": "ok",
        "phone": datos.phone,
        "atendido_por_humano": True,
        "nota": (
            f"El bot volverá solo si la conversación se queda quieta "
            f"{config.plazo_takeover()}, sin mensajes del cliente ni "
            f"respuestas manuales. Mientras alguno de los dos escriba, no "
            f"interrumpe."
        ),
    }


@router.post("/release")
def devolver_control(datos: ContactoRequest, x_admin_key: str | None = Header(default=None)):
    """Devuelve la conversación al bot."""
    _validar_clave(x_admin_key)

    if not bot_logic.devolver_control_al_bot(datos.phone):
        raise HTTPException(status_code=404, detail="Ese contacto no existe todavía")

    return {"status": "ok", "phone": datos.phone, "atendido_por_humano": False}


@router.get("/plan")
def ver_plan(x_admin_key: str | None = Header(default=None)):
    """
    En qué plan está el bot ahora mismo: Básico o Pro (con IA).

    No devuelve la clave de Gemini ni un trozo de ella, solo si está
    puesta o no.
    """
    _validar_clave(x_admin_key)

    from app.bot import cerebro
    return cerebro.estado()


@router.post("/plan")
def cambiar_plan(datos: PlanRequest, x_admin_key: str | None = Header(default=None)):
    """
    Cambia entre el plan Básico y el Pro. Tiene efecto en el siguiente
    mensaje: no hace falta reiniciar ni volver a desplegar.

    Es la segunda mitad de "subir a Pro": el dueño pega su clave de Gemini
    en las variables del servicio y activa el plan desde aquí. Sin clave,
    esto responde 400 explicando dónde conseguirla — es preferible a
    dejarle activar algo que no va a funcionar.

    Queda guardado en la base, así que sobrevive a los despliegues.
    """
    _validar_clave(x_admin_key)

    from app.bot import cerebro

    try:
        quedo = cerebro.cambiar_plan(datos.plan.strip().lower())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {"status": "ok", **cerebro.estado(), "plan": quedo}


def _donde_vive_la_base(session) -> dict:
    """
    Si la base sobrevive al próximo despliegue, o no.

    Es LA pregunta cuando se estrena un servicio: un archivo SQLite dentro
    de la carpeta del código se borra en cada deploy y las conversaciones
    desaparecen **sin dar ningún error**, así que desde fuera se ve igual
    que si todo estuviera bien. Esto lo dice antes de perder nada.

    Nunca devuelve la URL entera: con Postgres llevaría la contraseña.
    """
    if session.bind.dialect.name != "sqlite":
        # Una base administrada vive fuera del servicio por definición.
        return {"sobrevive_al_despliegue": True}

    ruta = session.bind.url.database or ""
    if not ruta or ruta == ":memory:":
        return {"archivo": ruta or "(en memoria)",
                "sobrevive_al_despliegue": False}

    completa = os.path.abspath(ruta)

    # Si el archivo cae dentro de la carpeta desde la que corre el código,
    # el hosting lo reemplaza entero en cada despliegue. Fuera de ahí
    # (/var/data en Render) está sobre el disco, que sí se conserva.
    dentro_del_codigo = completa.startswith(os.getcwd() + os.sep)

    datos = {"archivo": completa, "sobrevive_al_despliegue": not dentro_del_codigo}
    if dentro_del_codigo:
        datos["aviso"] = ("La base está dentro de la carpeta del código: se "
                          "borra en cada despliegue. Revisa DATABASE_URL y "
                          "que el disco esté montado.")

    # Con la base en disco esto tiene que decir "wal": sin él, el webhook y
    # el panel chocan y el segundo se lleva un "database is locked".
    try:
        datos["modo_concurrencia"] = session.execute(
            _text("PRAGMA journal_mode")).scalar()
    except Exception:
        pass

    return datos


def _estado_media() -> dict:
    """
    Si el servicio puede de verdad recibir y mandar archivos.

    `notas_de_voz` es el dato que importa: sin PyAV el panel sigue
    funcionando y las imágenes también, pero las grabaciones no se pueden
    convertir a OGG/Opus y WhatsApp las rechaza. Como la importación es
    perezosa, el fallo no aparece al arrancar.
    """
    info = {"carpeta": config.MEDIA_DIR, "cache_dias": config.MEDIA_CACHE_DIAS}

    try:
        import av  # noqa: F401
        info["notas_de_voz"] = True
        info["conversor"] = f"PyAV {av.__version__}"
    except Exception as e:
        info["notas_de_voz"] = False
        info["conversor"] = f"falta PyAV ({str(e)[:80]}): pon 'av' en requirements.txt"

    try:
        from PIL import Image  # noqa: F401
        info["imagenes"] = True
    except Exception:
        info["imagenes"] = False

    try:
        os.makedirs(config.MEDIA_DIR, exist_ok=True)
        archivos = [f for f in os.listdir(config.MEDIA_DIR)
                    if os.path.isfile(os.path.join(config.MEDIA_DIR, f))]
        info["en_cache"] = len(archivos)
        info["cache_mb"] = round(sum(
            os.path.getsize(os.path.join(config.MEDIA_DIR, f))
            for f in archivos) / (1024 * 1024), 2)
    except OSError as e:
        info["cache_ok"] = False
        info["error"] = str(e)[:200]

    return info


@router.get("/status")
def estado(x_admin_key: str | None = Header(default=None)):
    """
    Diagnóstico del servicio ya desplegado.

    Comprueba lo que no se ve desde fuera: que la base responda y que las
    credenciales de Google sigan sirviendo. Sin esto, un JSON mal pegado
    en las variables de entorno no se nota hasta que un cliente intenta
    agendar y falla.

    Solo lectura: no crea eventos ni filas. No devuelve ningún secreto.
    """
    _validar_clave(x_admin_key)

    from app.integrations import calendar_service
    from app.integrations import google_client
    from app.core.database import get_session, Contact, Lead, Message

    from app import main

    resultado = {"servicio": config.BUSINESS_NAME}

    # Si un cliente escribe y no aparece por ningún lado, esto dice si
    # Meta llegó a entregar el webhook o si el mensaje nunca llegó.
    resultado["webhooks"] = dict(main.ESTADISTICAS)

    # Ajustes que se definen por variable de entorno. Sirve para
    # confirmar que lo que pusiste en el panel del hosting llegó de
    # verdad al proceso. Aquí solo van valores que no son secretos.
    resultado["configuracion"] = {
        "plantilla_avisos": config.OWNER_TEMPLATE_NAME or "(sin configurar)",
        "plantilla_idioma": config.OWNER_TEMPLATE_LANG,
        "zona_horaria": config.BUSINESS_TIMEZONE,
        "horario": f"{config.BUSINESS_HOURS_START}-{config.BUSINESS_HOURS_END}",
        "duracion_cita_min": config.APPOINTMENT_DURATION_MINUTES,
        "minutos_takeover": config.HUMAN_TAKEOVER_TIMEOUT_MINUTES,
        "horas_caducidad_conversacion": config.CONVERSATION_TIMEOUT_HOURS,
        "asesor_tras_cita": config.TAKEOVER_AFTER_APPOINTMENT,
        "firma_webhook_activa": config.VERIFY_WEBHOOK_SIGNATURE,
    }

    # ── De dónde sale lo que el bot contesta ─────────────────────────
    #
    # Es la primera pregunta cuando alguien dice "cambié un texto en el
    # panel y el bot sigue igual", y hasta ahora no había forma de
    # responderla sin entrar a la base. Un negocio lee su propio contenido
    # (`clients.negocio_config`) o, si no lo tiene, el `negocio.toml` del
    # repositorio.
    from app.core import tenencia as _tenencia
    from app.core.database import get_session as _sesion, Client as _Client

    contenido = {"cliente": _tenencia.actual_o_none()}
    try:
        s_ = _sesion()
        try:
            fila = s_.query(_Client).filter_by(id=contenido["cliente"]).first()
            propio = (fila.negocio_config if fila else None) or {}
        finally:
            s_.close()

        contenido["origen"] = ("su contenido en la base" if propio
                               else "el negocio.toml del repositorio")
        contenido["opciones_en_la_base"] = len(propio.get("menu") or [])
        contenido["textos_en_la_base"] = len(propio.get("textos") or {})
        contenido["opciones_que_usa_el_bot"] = len(config.NEED_OPTIONS)
        # Lo que de verdad zanja la duda: el primer mensaje, tal cual.
        contenido["saludo_en_uso"] = (config.WELCOME_MESSAGE or "")[:120]

        # Qué guarda CADA opción y qué acaba usando el bot. Es lo que hace
        # falta cuando alguien dice "lo cambié y sigue igual": una opción
        # puede tener su texto propio y además un puntero a un bloque
        # compartido (`precios`, `enlace`). Lo propio gana; el puntero solo
        # rellena lo que la opción no diga (ver `config_cliente._opcion`).
        def _resumen(guardado, resuelto):
            claves = [k for k in ("mensaje", "precios", "enlace", "url")
                      if k in guardado]
            return {
                "id": guardado.get("id"),
                "guarda": claves,
                "texto_que_manda": ((resuelto or {}).get("mensaje") or "")[:60],
            }

        resueltas = {o.get("id"): o for o in config.NEED_OPTIONS}
        for o in config.NEED_OPTIONS:
            for sub in o.get("submenu") or []:
                resueltas[sub.get("id")] = sub

        opciones = []
        def _recorrer(lista):
            for g in lista or []:
                opciones.append(_resumen(g, resueltas.get(g.get("id"))))
                _recorrer(g.get("submenu"))
        _recorrer(propio.get("menu") or [])
        contenido["opciones"] = opciones
    except Exception as e:
        contenido["error"] = f"{type(e).__name__}: {e}"

    resultado["contenido"] = contenido

    # En qué plan está y si la IA puede funcionar. Es lo primero que hay
    # que mirar cuando alguien dice "contraté el Pro y responde igual que
    # antes": casi siempre es la clave sin poner o el plan sin activar.
    from app.bot import cerebro
    resultado["ia"] = cerebro.estado()

    # Base de datos
    try:
        session = get_session()
        resultado["base_de_datos"] = {
            "ok": True,
            "motor": session.bind.dialect.name,
            "contactos": session.query(Contact).count(),
            "leads": session.query(Lead).count(),
            "mensajes": session.query(Message).count(),
        }
        resultado["base_de_datos"].update(_donde_vive_la_base(session))
        session.close()
    except Exception as e:
        resultado["base_de_datos"] = {"ok": False, "error": str(e)[:200]}

    # Archivos del chat. Interesa sobre todo la conversión de audio: `av`
    # se importa solo cuando se manda una nota de voz, así que si la
    # dependencia no llegó a instalarse el servicio arranca igual de bien
    # y no se sabe hasta que alguien graba una y falla.
    resultado["archivos"] = _estado_media()

    # Credenciales de Google
    try:
        resultado["google"] = {"ok": True, "cuenta": google_client.email_cuenta_servicio()}
    except Exception as e:
        resultado["google"] = {"ok": False, "error": str(e)[:200]}
        return resultado

    # Calendario: solo lectura
    try:
        info = google_client.calendar().calendars().get(
            calendarId=google_client.id_calendario()).execute()
        dias = calendar_service.dias_con_disponibilidad()
        resultado["calendario"] = {
            "ok": True,
            "nombre": info.get("summary"),
            "zona": info.get("timeZone"),
            "dias_con_hueco": len(dias),
            "proximo": dias[0][0].isoformat() if dias else None,
        }
    except Exception as e:
        resultado["calendario"] = {"ok": False, "error": str(e)[:200]}

    # Sheet: solo lectura
    try:
        info = google_client.sheets().spreadsheets().get(
            spreadsheetId=google_client.id_spreadsheet()).execute()
        resultado["sheet"] = {
            "ok": True,
            "nombre": info["properties"]["title"],
            "pestanas": [h["properties"]["title"] for h in info["sheets"]],
        }
    except Exception as e:
        resultado["sheet"] = {"ok": False, "error": str(e)[:200]}

    return resultado


@router.get("/contacts")
def listar_contactos(solo_humanos: bool = False, x_admin_key: str | None = Header(default=None)):
    """Lista los contactos y su estado. Con ?solo_humanos=true filtra los tomados."""
    _validar_clave(x_admin_key)

    contactos = bot_logic.listar_contactos(solo_humanos=solo_humanos)
    return {"total": len(contactos), "contactos": contactos}
