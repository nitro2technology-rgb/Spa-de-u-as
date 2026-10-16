"""
BASE DE DATOS
=============
Guarda cada contacto, en qué paso del flujo va, y los leads/citas
generados.

MULTI-INQUILINO
---------------
Una sola base atiende a VARIOS negocios. Cada fila lleva `client_id`, que
dice de quién es, y la tabla `clients` guarda todo lo que distingue a un
negocio de otro: sus credenciales de Meta, su calendario, su marca y sus
textos.

Dos cerraduras, y hacen falta las dos (ver CLAUDE.md):

  1. El filtro del ORM (`_filtrar_por_inquilino`): toda consulta a una
     tabla de `MODELOS_DEL_INQUILINO` lleva `WHERE client_id = …` solo.
     `_sellar_inquilino` rellena el `client_id` de lo que se inserta.
  2. Row-Level Security en PostgreSQL, con sus políticas en una migración
     (`c3f1a7d2b904`). `_anunciar_inquilino` le dice a la base de quién es
     cada transacción.

La columna conserva `server_default="1"` de la migración de agosto. Ya no
lo usa nadie —`_sellar_inquilino` pone el inquilino en cada INSERT—, pero
quitarlo es una migración sobre seis tablas con cerradura.

EL ESQUEMA LO GOBIERNA ALEMBIC
------------------------------
Las migraciones viven en `migrations/`. `alembic upgrade head` corre antes
de arrancar el servidor (ver el startCommand de render.yaml). `init_db()`
sigue existiendo para las pruebas, que crean su propia base temporal.

Para producción se usa PostgreSQL: SQLite no soporta Row-Level Security,
que es la segunda capa que impide que una consulta sin filtrar devuelva
datos de otro inquilino. Las pruebas siguen corriendo sobre SQLite.
"""

import json

from sqlalchemy import (
    create_engine, event, func,
    Column, Integer, String, Text, Date, DateTime, Boolean, ForeignKey,
    JSON, UniqueConstraint, Index,
    false as sa_false, true as sa_true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    declarative_base, sessionmaker, relationship, with_loader_criteria,
)
from datetime import datetime, timedelta, timezone

from app import config
from app.core.config_cliente import CLIENTE_POR_DEFECTO  # noqa: F401 (re-export)

# JSON en las dos bases: JSONB en PostgreSQL (indexable, binario) y JSON
# normal en SQLite, que es lo que usan las pruebas.
JSONPortable = JSON().with_variant(JSONB(), "postgresql")


def ahora_utc() -> datetime:
    """
    Hora UTC actual, sin zona horaria.

    `datetime.utcnow()` quedó deprecado en Python 3.12 y se va a eliminar.
    Devolvemos un datetime *naive* (sin tzinfo) a propósito: es el formato
    que ya tienen las fechas guardadas, y comparar uno naive con uno
    "aware" lanza TypeError. Toda la app debe usar esta función.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

def _normalizar_url(url: str) -> str:
    """
    Ajusta la URL de la base para que SQLAlchemy la entienda.

    Dos tropiezos clásicos al desplegar, los dos por cómo entregan la URL
    los servicios de hosting:

    1. Render y Railway a veces la dan como "postgres://". SQLAlchemy no
       reconoce ese esquema y falla al arrancar con NoSuchModuleError.
    2. "postgresql://" a secas hace que SQLAlchemy busque psycopg2, que no
       tiene versión precompilada para Python 3.13+. Usamos psycopg 3, que
       se pide explícitamente con "postgresql+psycopg://".
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]

    return url


DATABASE_URL = _normalizar_url(config.DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    # Postgres administrado corta las conexiones inactivas sin avisar; sin
    # esto el primer mensaje tras un rato de silencio falla con
    # "server closed the connection unexpectedly".
    pool_pre_ping=not DATABASE_URL.startswith("sqlite"),
)

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _preparar_sqlite(conexion, _registro):
        """
        Deja SQLite listo para que lo usen varias cosas a la vez.

        Hace falta desde que la base de producción es un archivo en disco.
        Aquí hay tres cosas tocando la base al mismo tiempo: el webhook
        (que corre en un hilo aparte), el panel abierto y el canal en
        vivo. Con la configuración de fábrica de SQLite, mientras uno
        escribe los demás no pueden ni leer, y el segundo en llegar
        recibe "database is locked".

        - journal_mode=WAL: quien lee no bloquea a quien escribe ni al
          revés. Es LA diferencia entre funcionar y no. Se guarda en el
          archivo, así que basta con ponerlo una vez, pero no molesta.
        - busy_timeout: ante un choque, espera 5 segundos en vez de
          fallar al instante.
        - synchronous=NORMAL: con WAL es seguro y evita esperar al disco
          en cada mensaje. En un disco de red como el de Render, eso se
          nota.
        """
        cursor = conexion.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


# Row-Level Security solo existe en PostgreSQL. En la máquina de
# desarrollo hay SQLite, así que todo lo de las cerraduras tiene que
# poder no estar sin que nada cambie.
ES_POSTGRES = DATABASE_URL.startswith("postgresql")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def columna_cliente(**extra):
    """
    La columna `client_id` que llevan todas las tablas del inquilino.

    Está en una función porque se repite en ocho tablas y tiene que ser
    idéntica en todas: el día que se quite el `server_default` hay un solo
    sitio que tocar (y una migración que escribir).
    """
    return Column(Integer, ForeignKey("clients.id"), nullable=False,
                  server_default=str(CLIENTE_POR_DEFECTO), index=True, **extra)


class Client(Base):
    """
    Un negocio al que le vendimos el bot. Es el inquilino.

    Aquí vive TODO lo que cambia de un cliente a otro y que antes eran
    variables de entorno del servicio: sus credenciales de Meta, su
    calendario, su marca y el contenido de su negocio.toml. Esa es la
    diferencia entre "un despliegue por cliente" y "un despliegue".

    `active` es la palanca comercial: en False el webhook de ese negocio
    deja de procesarse y su panel no deja entrar. Se pausa a quien no paga
    sin borrarle nada, para que al volver tenga su historial intacto.
    """
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)

    # Identifica al cliente en su subdominio: "panaderia" →
    # panaderia.tudominio.com. Por eso es único.
    slug = Column(String, unique=True, index=True, nullable=False)
    nombre = Column(String, nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    # ── Meta ─────────────────────────────────────────────────────────
    # El número del negocio dentro de la API de Meta. ES LA CLAVE DE
    # ENRUTAMIENTO: llega en cada webhook
    # (entry[].changes[].value.metadata.phone_number_id) y es lo que dice
    # de qué cliente es el mensaje. Único e indexado porque se busca por
    # él en el camino caliente, una vez por mensaje entrante.
    phone_number_id = Column(String, unique=True, index=True, nullable=True)
    waba_id = Column(String, nullable=True)

    # Cifrado. Ver app/core/secretos.py.
    whatsapp_token = Column(String, nullable=True)

    # ── La App de Meta, que es DEL CLIENTE ───────────────────────────
    # Antes estos tres eran variables de entorno globales: había UNA App
    # de Meta para todos, la nuestra, y por eso el webhook tenía una sola
    # URL y un solo secreto de firma.
    #
    # Ya no. Cada negocio trae su propia App, creada desde SU cuenta de
    # developers, y nosotros no aparecemos en ella. El motivo es
    # comercial antes que técnico: con la App nuestra, conectar el número
    # de un cliente dependía de que Meta nos aprobara el App Review, y
    # además nos hacía dueños de números ajenos. Así el negocio sigue
    # siendo dueño de su número y nosotros ponemos hosting, base y panel.
    #
    # La consecuencia en el código está en `app/main.py`: la firma del
    # webhook ya no se puede validar con un secreto global, así que cada
    # cliente tiene su propia URL de webhook (ver `webhook_token`).
    app_id = Column(String, nullable=True)
    app_secret = Column(String, nullable=True)                    # cifrado

    # El que el cliente escribe en su App al configurar el webhook. Meta
    # lo devuelve en el GET de verificación y tiene que coincidir.
    verify_token = Column(String, nullable=True)

    # EL TROZO ALEATORIO DE SU URL DE WEBHOOK: /webhook/{webhook_token}.
    #
    # Es lo que dice de quién es el POST **antes** de tocar el cuerpo, que
    # es lo que hace falta para poder validar la firma con el App Secret
    # correcto. Con una URL compartida habría que parsear JSON sin firmar
    # para saber a quién preguntarle el secreto, que es justo el orden que
    # no debe tener una comprobación de autenticidad.
    #
    # Único e indexado por lo mismo que `phone_number_id`: se busca por él
    # una vez por mensaje entrante.
    #
    # De paso, al ser inadivinable, es una capa más: quien no lo tenga no
    # llega ni a la comprobación de firma.
    webhook_token = Column(String, unique=True, index=True, nullable=True)

    # Si el token de WhatsApp respondía la última vez que se probó.
    # "ok", "revocado", "sin_probar". Lo escribe el botón "Probar
    # credenciales" del super-admin y la revisión periódica.
    #
    # Existe porque el fallo más probable de este modelo es un token
    # revocado o mal copiado, y su síntoma —"el bot no responde"— es
    # idéntico al de otras diez cosas. Sin este campo, cada uno de esos
    # casos es una sesión de diagnóstico.
    token_estado = Column(String, nullable=True)
    token_revisado = Column(DateTime, nullable=True)

    # ── Google (Calendar + Sheets) ───────────────────────────────────
    google_service_account_json = Column(String, nullable=True)   # cifrado
    google_calendar_id = Column(String, nullable=True)
    google_sheets_spreadsheet_id = Column(String, nullable=True)

    # ── IA (paquete opcional) ────────────────────────────────────────
    # La clave la ponemos nosotros y facturamos el consumo, así que el
    # cliente no tiene que abrir cuenta en Google Cloud. Si un cliente
    # prefiere traer la suya, se guarda aquí y a ese no se le factura uso.
    gemini_api_key = Column(String, nullable=True)                # cifrado

    # Por cliente, no global: los modelos caducan (ver config.GEMINI_MODELO)
    # y además permite vender un paquete de IA con mejor modelo. Cambiarlo
    # es un UPDATE, no un despliegue.
    gemini_modelo = Column(String, nullable=True)

    # ¿ESTE NEGOCIO COMPRÓ EL PAQUETE DE IA?
    #
    # Es distinto de `ia_activa`, y confundirlos es fácil:
    #
    #   ia_contratada  comercial — lo vendimos. Solo se toca desde
    #                  /superadmin, y en False el dueño no ve ni el botón.
    #   ia_activa      operativo — cómo nace encendido si lo contrató.
    #   ajuste plan_ia lo que el dueño eligió en su panel.
    #
    # Hasta ahora la puerta era "¿hay clave de Gemini?", que no es la
    # pregunta: la clave la ponemos nosotros y es la misma para todos, así
    # que cualquier cliente podía encender la IA desde su panel y
    # cargarnos el consumo sin haberla pagado.
    # `sa.false()` y no "0": es lo mismo en los dos motores sin depender de
    # la conversión implícita de PostgreSQL. Ver la migración f7c3a9e21b48.
    ia_contratada = Column(Boolean, default=False, nullable=False,
                           server_default=sa_false())

    ia_activa = Column(Boolean, default=False, nullable=False)

    # Cuántas áreas puede tener este negocio recibiendo avisos.
    #
    # En NULL lo decide el plan: 3 sin IA, 6 con IA. Esta columna es para
    # el caso suelto — el cliente que negocia una más, o el que necesita
    # menos. Manda sobre el plan, igual que `gemini_modelo` manda sobre la
    # variable de entorno (ver §3.10 de CONTINUAR_AQUI).
    #
    # Es una columna y no una constante porque el número lo decide la
    # venta, y una venta no puede depender de un despliegue.
    max_destinos_avisos = Column(Integer, nullable=True)

    # Tope MENSUAL de mensajes que pueden llegar a la IA, por cliente.
    # Es lo que hace seguro vender un plan de precio fijo: el peor caso es
    # un número conocido. Al superarlo el bot NO se rompe: `interpretar`
    # devuelve NO_SE y sigue vendiendo con el menú, igual que cuando
    # Gemini da timeout. Conviene ser generoso — el tope cuesta centavos y
    # uno apretado genera llamadas de soporte. En 0, sin tope.
    ia_limite_mensual = Column(Integer, default=0, nullable=False)

    # ── Avisos al celular (Web Push) ─────────────────────────────────
    vapid_public_key = Column(String, nullable=True)
    vapid_private_key = Column(String, nullable=True)             # cifrado
    vapid_contact_email = Column(String, nullable=True)

    # ── Negocio y marca ──────────────────────────────────────────────
    owner_phone_number = Column(String, nullable=True)
    business_whatsapp_number = Column(String, nullable=True)
    business_email = Column(String, nullable=True)
    business_website = Column(String, nullable=True)

    marca_color = Column(String, nullable=True)
    marca_color_fondo = Column(String, nullable=True)
    app_nombre = Column(String, nullable=True)
    app_nombre_corto = Column(String, nullable=True)
    logo = Column(String, nullable=True)          # URL o ruta al archivo

    # El negocio.toml entero. Textos, menú, precios, horarios y orígenes.
    # Va como JSON y no como archivo porque con varios inquilinos no puede
    # haber "el" negocio.toml del despliegue.
    negocio_config = Column(JSONPortable, nullable=True)

    # Días de conversación que se le guardan. En NULL manda
    # `config.HISTORIAL_DIAS`, que es la política de la plataforma.
    #
    # Es por cliente y no global porque es dato de terceros: un negocio
    # puede necesitar guardar un año y otro querer que no quede nada
    # pasados 30 días. Con una sola variable de entorno, el plazo de todos
    # lo decide el despliegue.
    historial_dias = Column(Integer, nullable=True)

    # ── Comercial ────────────────────────────────────────────────────
    plan = Column(String, nullable=True)
    created_at = Column(DateTime, default=ahora_utc)
    paused_at = Column(DateTime, nullable=True)

    # ── Cobro (ver `app/core/cobros.py`) ─────────────────────────────
    # Hasta cuándo está pagado. NULL = no se le cobra: el bot de casa, o
    # un cliente al que todavía no se le puso fecha.
    vence_el = Column(Date, nullable=True)
    # Lo pactado con ÉL; NULL = el precio de su plan (`planes.precio_de`).
    precio_mensual = Column(Integer, nullable=True)
    ultimo_pago_el = Column(Date, nullable=True)
    ultimo_pago_monto = Column(Integer, nullable=True)
    # El día del último correo de cobro: uno al día, no uno por revisión.
    recordatorio_enviado_el = Column(Date, nullable=True)
    # "impago" si lo pausó el cobro automático. Solo esos se reactivan
    # solos al registrar el pago: una pausa puesta a mano no la deshace.
    pausado_por = Column(String, nullable=True)

    # ── Módulos contratados (ver `app/barberia/`) ────────────────────
    # Qué productos compró este negocio. Es COMERCIAL, igual que
    # `ia_contratada`: solo se toca desde /superadmin, y la puerta está en
    # el servidor (`app/barberia/permisos.py`), no en esconder un botón.
    #
    #   barberia_contratada  el panel de gestión de la barbería (/b, /yo).
    #   bot_contratado       el bot de WhatsApp. Nace en true porque todos
    #                        los clientes de antes de las barberías lo
    #                        tienen; una barbería del plan de entrada va
    #                        en false.
    barberia_contratada = Column(Boolean, default=False, nullable=False,
                                 server_default=sa_false())
    bot_contratado = Column(Boolean, default=True, nullable=False,
                            server_default=sa_true())

    # Dónde agenda el bot: "google" (el Google Calendar del negocio, lo de
    # siempre) o "barberia" (la agenda del panel de la barbería, que es la
    # única fuente de verdad de sus citas). Ver la §6 de la especificación.
    proveedor_agenda = Column(String, default="google", nullable=False,
                              server_default="google")

    # Cupos pactados con ESTE negocio. NULL = lo que traiga su plan
    # (`planes.cupo_de_sedes` / `cupo_de_barberos`). Mismo patrón que
    # `max_destinos_avisos`.
    max_sedes = Column(Integer, nullable=True)
    max_barberos = Column(Integer, nullable=True)


class PanelUser(Base):
    """
    Quién puede entrar al panel de un cliente. La usa `app/core/acceso.py`.

    `email` es el NOMBRE DE USUARIO —un correo, un nombre, "caja-2"—, único
    en toda la plataforma. La unicidad la impone el código
    (`acceso.crear_usuario`) y no un índice: uno global rompería el
    despliegue si ya hubiera repetidos de antes.
    """
    __tablename__ = "panel_users"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()

    email = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)

    # "dueno" (todo dentro de su negocio) o "area" (solo atender).
    rol = Column(String, default="dueno", nullable=False)

    # El área por la que entra: el `id` de uno de sus
    # `negocio_config.avisos.destinos`. NULL es el dueño, que lo ve todo.
    # Quien entra por un área SOLO ve las conversaciones de esa área (ver
    # `app/core/equipo.py`).
    area_id = Column(String, nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=ahora_utc)
    ultimo_acceso = Column(DateTime, nullable=True)

    # El mismo correo puede administrar dos negocios distintos, pero no
    # puede estar dos veces en el mismo.
    __table_args__ = (
        UniqueConstraint("client_id", "email", name="uq_panel_users_cliente_email"),
    )


class IAUso(Base):
    """
    Cuánta IA consumió cada cliente cada mes. Es el medidor de facturación.

    Una fila por cliente y mes, que se va sumando. Barato: un UPDATE por
    mensaje interpretado, no una fila por llamada.

    Los tokens son los REALES que devuelve Gemini en `usage_metadata`, no
    una estimación. Facturar sobre una estimación es facturar sobre una
    suposición.

    `mensajes` es lo que se compara contra `Client.ia_limite_mensual`.
    """
    __tablename__ = "ia_uso"

    client_id = Column(Integer, ForeignKey("clients.id"), primary_key=True)

    # "2026-08". En UTC, igual que el tope diario por contacto.
    periodo = Column(String, primary_key=True)

    mensajes = Column(Integer, default=0, nullable=False)
    tokens_in = Column(Integer, default=0, nullable=False)
    tokens_out = Column(Integer, default=0, nullable=False)
    actualizado = Column(DateTime, default=ahora_utc, onupdate=ahora_utc)


class Contact(Base):
    """Un contacto/cliente que ha escrito por WhatsApp."""
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()

    # NO es único por sí solo: dos negocios distintos pueden tener al
    # mismo cliente final escribiéndoles, y con un único global el segundo
    # negocio chocaría contra la fila del primero. La unicidad es por
    # pareja (client_id, phone) — ver __table_args__ al final de la clase.
    phone = Column(String, index=True, nullable=False)
    name = Column(String, nullable=True)

    # Estado dentro de la conversación (máquina de estados simple)
    # Valores: NEW, ASKED_NAME, ASKED_NEED, ASKING_DATE, ASKING_TIME,
    #          ASKING_OTHER_DETAIL, HUMANO, DONE
    state = Column(String, default="NEW")

    # Guarda temporalmente datos que se están recolectando (ej: la fecha
    # de la cita mientras se pregunta la hora)
    temp_data = Column(String, nullable=True)

    # Toma de control manual: mientras esté en True, el bot NO responde
    # a este contacto (lo atiende una persona desde WhatsApp Manager).
    atendido_por_humano = Column(Boolean, default=False, nullable=False)
    takeover_at = Column(DateTime, nullable=True)

    # De dónde llegó el cliente: "web", "instagram", "qr", "directo"...
    # Se deduce del mensaje precargado del botón (ver config.ORIGENES).
    #
    # El defecto es un CALLABLE, no un valor. Dos motivos, y los dos
    # importan:
    #
    #  - Es de cada negocio: sale de su negocio.toml. Evaluado al definir
    #    la clase, todos los contactos nuevos heredarían el origen por
    #    defecto del primer cliente que se cargara.
    #  - Leer configuración al importar este módulo cierra un círculo:
    #    config → tenencia → database → config. Aplazarlo a la inserción
    #    lo rompe.
    origen = Column(String, default=lambda: config.ORIGEN_POR_DEFECTO)

    # Qué servicio eligió en el menú principal: el id de la opción
    # ("opt_powerbi"). Se guarda el id y no el nombre para que, si algún
    # día se reescribe el texto en config, las conversaciones abiertas
    # sigan sabiendo a qué pestaña del Sheet van.
    servicio = Column(String, nullable=True)

    # El área a la que el DUEÑO le pasó esta conversación a mano. Manda
    # sobre la que diría `servicio`. NULL = la que diga la opción elegida,
    # y si ninguna área la reclama, el dueño. Ver `app/core/equipo.py`.
    area = Column(String, nullable=True)

    # Por dónde ha pasado dentro de ese servicio, en orden y separado por
    # " > ": "Vio precios > Pidió asesor". Es lo que se escribe en la
    # columna "Recorrido" del Sheet.
    recorrido = Column(String, nullable=True)

    # En qué punto de atención está esta conversación, puesto a mano por
    # el asesor desde el panel. Vacío = sin marcar.
    #
    # Valores: "urgente", "esperando", "terminado". Se guarda el id y no
    # el texto para poder cambiar mañana cómo se llaman en pantalla sin
    # tocar lo que ya está guardado.
    #
    # No lo ve el cliente: es para poder barrer el listado de un vistazo
    # y saber a quién hay que atender ya.
    estado_atencion = Column(String, nullable=True)

    # ETIQUETAS LIBRES, las que se pone el negocio a su manera: "cliente
    # viejo", "pidio descuento", "no contesta". Se guardan como una lista
    # JSON en una sola columna.
    #
    # Lo relacionalmente correcto seria una tabla aparte, y se descarto a
    # sabiendas: son dos o tres etiquetas por contacto y unos cientos de
    # contactos por negocio, asi que no hay nada que optimizar. Una tabla
    # nueva costaria su politica de RLS y un modelo mas en
    # MODELOS_DEL_INQUILINO, y el dia que a alguien se le olvide la
    # segunda, esa tabla se queda sin cerradura sin que nadie se entere.
    # Ademas encaja con como ya esta hecha esta tabla: `servicio`,
    # `recorrido` y `estado_atencion` tambien viven aqui.
    #
    # Se lee y se escribe con `etiquetas_de()` y `guardar_etiquetas()`,
    # que son los que saben del JSON. Nadie mas deberia tocar la columna.
    etiquetas = Column(Text, nullable=True)

    # La nota que se deja quien atiende, para si mismo o para el
    # companero del turno siguiente. NO se le manda nunca al cliente:
    # esta columna no la lee el bot, solo el panel.
    nota_interna = Column(Text, nullable=True)

    # ── Tope diario de la IA (solo plan Pro) ─────────────────────────
    # Cuántos mensajes de este contacto han llegado hoy a Gemini, y de qué
    # día es esa cuenta ("2026-08-08", en UTC). Al cambiar el día se
    # reinicia sola, así que no hace falta ninguna tarea que las limpie.
    #
    # Están para frenar a quien escriba en bucle: sin esto, una sola
    # persona puede vaciarle la cuota al negocio en una tarde. Pasado el
    # tope el bot no se calla, sigue con el menú, que es gratis.
    #
    # En el plan Básico quedan siempre en NULL: nada las toca.
    ia_mensajes_dia = Column(Integer, nullable=True)
    ia_dia = Column(String, nullable=True)

    created_at = Column(DateTime, default=ahora_utc)
    last_interaction = Column(DateTime, default=ahora_utc)

    leads = relationship("Lead", back_populates="contact")

    __table_args__ = (
        # LA restricción que hace posible el multi-inquilino. Antes `phone`
        # era único a secas, lo que significaba "este teléfono existe una
        # vez en todo el sistema" — cierto con un solo negocio, falso con
        # varios.
        UniqueConstraint("client_id", "phone", name="uq_contacts_cliente_phone"),
    )


class Ajuste(Base):
    """
    Un ajuste que se cambia desde el panel y sobrevive al reinicio.

    Existe porque hay cosas que el dueño del negocio tiene que poder
    cambiar SIN que nadie despliegue nada ni entre al panel del hosting.
    Hoy solo se usa para el plan (Básico / Pro), que es lo que se activa
    al contratar la IA.

    Lo que se define por variable de entorno NO vive aquí: las variables
    siguen siendo la vía para un cambio urgente y para lo que no debe
    tocar el cliente. Esta tabla es para lo que es suyo.
    """
    __tablename__ = "ajustes"

    # La clave sola ya no basta: "plan_ia" es un ajuste POR NEGOCIO, y con
    # `clave` como única PK el plan que activa un cliente se lo cambiaría a
    # todos. La PK es la pareja.
    client_id = columna_cliente(primary_key=True)
    clave = Column(String, primary_key=True)
    valor = Column(String, nullable=True)
    actualizado = Column(DateTime, default=ahora_utc, onupdate=ahora_utc)


class Lead(Base):
    """Un resultado de la conversación: una cita u otra consulta."""
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True)
    # Redundante con contact.client_id, y a propósito: permite filtrar y
    # contar leads por inquilino sin unir con `contacts`, y deja que
    # Row-Level Security proteja esta tabla por sí sola en la Fase 2.
    client_id = columna_cliente()
    contact_id = Column(Integer, ForeignKey("contacts.id"))

    # Tipo: "cita" u "otro"
    type = Column(String, nullable=False)
    detail = Column(String, nullable=True)
    appointment_date = Column(String, nullable=True)
    appointment_time = Column(String, nullable=True)

    # ID del evento en Google Calendar, para poder moverlo o cancelarlo
    # después sin buscarlo a mano. Vacío si la cita no llegó a crearse
    # (Google caído) o si el lead no es una cita.
    google_event_id = Column(String, nullable=True)

    # Estado del lead: "pendiente", "notificado"
    status = Column(String, default="pendiente")
    created_at = Column(DateTime, default=ahora_utc)

    contact = relationship("Contact", back_populates="leads")


class Message(Base):
    """
    Historial de la conversación, en los dos sentidos.

    Hasta ahora solo se guardaba el resultado (el Lead), no la charla. Sin
    esto no se puede responder a mano: no habría forma de ver qué dijo el
    cliente antes de contestarle.

    Un mensaje puede llevar texto, un archivo, o las dos cosas (una imagen
    con pie de foto). Del archivo se guarda la FICHA, nunca los bytes: el
    archivo en sí vive en el caché de disco (app/core/media.py) y se puede
    borrar sin perder el rastro de que existió.
    """
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()
    phone = Column(String, index=True, nullable=False)

    # "entrante" (lo escribió el cliente) o "saliente" (se lo enviamos)
    direccion = Column(String, nullable=False)

    # Quién lo escribió: "cliente", "bot" o "humano"
    autor = Column(String, nullable=False)

    texto = Column(String, nullable=True)
    created_at = Column(DateTime, default=ahora_utc, index=True)

    # --- Adjunto, si lo hay -------------------------------------------
    # El id que le dio Meta. Es con lo que se descarga el archivo, y es lo
    # que caduca: Meta borra los archivos recibidos por webhook a los 7
    # días. Pasado ese plazo el resto de la ficha sigue aquí, así que la
    # conversación no queda con un hueco silencioso.
    media_id = Column(String, nullable=True)

    # "image", "audio", "document", "sticker", "video", "location"...
    media_tipo = Column(String, nullable=True)

    media_mime = Column(String, nullable=True)

    # Solo lo traen los documentos. Es el nombre que el cliente ve.
    media_nombre = Column(String, nullable=True)

    # Tamaño en bytes. Sirve para pintar "PDF · 1,2 MB" en el panel sin
    # tener que bajarse el archivo para averiguarlo.
    media_bytes = Column(Integer, nullable=True)

    __table_args__ = (
        # El orden importa: es el de las consultas del panel, que siempre
        # piden "los mensajes de ESTE teléfono de ESTE cliente, por id".
        # Es la tabla que más crece, así que es donde un índice mal puesto
        # se nota antes.
        Index("ix_messages_cliente_phone_id", "client_id", "phone", "id"),
    )


class ProcessedMessage(Base):
    """
    Registro de IDs de mensajes ya procesados.

    Meta reintenta el webhook si no respondemos rápido o si algo falla, y
    reenvía el MISMO mensaje. Sin este control el bot contestaría dos veces
    al cliente y duplicaría leads. El índice único hace la comprobación
    atómica: si el INSERT choca, es que ya lo procesamos.
    """
    __tablename__ = "processed_messages"

    id = Column(Integer, primary_key=True)
    # Único GLOBAL y no por cliente, a diferencia del resto de tablas: los
    # ids de mensaje de Meta (wamid) ya son únicos en todo WhatsApp, así
    # que la pareja no agregaría nada y el índice sería más grande. El
    # `client_id` va igual, para poder limpiar y auditar por inquilino.
    message_id = Column(String, unique=True, index=True, nullable=False)
    client_id = columna_cliente()
    received_at = Column(DateTime, default=ahora_utc)


class PushSubscription(Base):
    """
    Un dispositivo suscrito a los avisos del panel.

    Cada celular o navegador donde se abre el panel y se aceptan las
    notificaciones deja aquí su buzón: una URL del servicio de push
    (Google, Mozilla, Apple) y dos claves con las que se cifra el aviso.
    No guarda nada personal, y sin esas claves el aviso no se entrega.

    Se borran solas cuando el servicio de push responde que ese buzón ya
    no existe: permiso revocado, app desinstalada o navegador borrado.
    """
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True)
    client_id = columna_cliente()

    # Único por cliente y no global: si mañana atiendes a dos negocios
    # desde el mismo celular, es el mismo endpoint del navegador para los
    # dos, y con un único global el segundo no podría suscribirse.
    endpoint = Column(String, index=True, nullable=False)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    created_at = Column(DateTime, default=ahora_utc)

    # De quién es el dispositivo: el aviso de un cliente de Ventas no le
    # suena a Soporte. NULL = de antes de las áreas; se trata como del dueño.
    user_id = Column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("client_id", "endpoint",
                         name="uq_push_cliente_endpoint"),
    )


# ══════════════════════════════════════════════════════════════════════
#  EL FILTRO POR INQUILINO
# ══════════════════════════════════════════════════════════════════════
#
# Estas tablas llevan `client_id` y NUNCA deben devolver ni tocar filas de
# otro negocio. `clients` no está: es la tabla que dice quién es quién, y
# filtrarla sería morderse la cola.
MODELOS_DEL_INQUILINO = (Contact, Message, Lead, Ajuste, PushSubscription,
                         ProcessedMessage, PanelUser, IAUso)

# Las tablas del panel de barberías viven en su módulo y se suman a esta
# tupla ELLAS MISMAS al terminar de cargarse (`modelos._registrar`). Así
# funciona en los dos órdenes de import: si alguien importa primero
# `app.barberia.modelos`, este import de aquí devuelve el módulo a medio
# cargar, y sumar `_barberia.MODELOS` desde aquí reventaba. El import va a
# esta altura y no arriba: `modelos` necesita `Base` y `columna_cliente`.
from app.barberia import modelos as _barberia  # noqa: E402,F401


@event.listens_for(SessionLocal, "do_orm_execute")
def _filtrar_por_inquilino(estado):
    """
    Le añade `WHERE client_id = ...` a toda consulta que toque una tabla
    del inquilino.

    Va aquí y no en cada consulta a propósito. Hay unas cuarenta repartidas
    por cinco archivos, y con el filtro a mano bastaba olvidar UNA para
    enseñarle a un negocio las conversaciones de otro — un fallo que no da
    error, no aparece en las pruebas de un solo cliente y solo se descubre
    cuando alguien se queja. Aquí no se puede olvidar ninguna.

    Sin inquilino fijado no filtra nada: es lo que necesitan los scripts de
    mantenimiento, las pruebas y las tareas de limpieza que barren la base
    entera al arrancar.
    """
    if estado.is_column_load or estado.is_relationship_load:
        return          # ya se resolvió el permiso al cargar el objeto padre

    client_id = tenencia_actual()
    if client_id is None:
        return

    # Si el inquilino cambió con la transacción ya abierta, la base se
    # quedó con el de antes y devolvería cero filas. Pasa poco —una sesión
    # suele vivir dentro de un solo `tenencia.usar`— pero cuando pasara, el
    # síntoma sería una bandeja vacía sin ningún error. Se vuelve a
    # anunciar, y solo entonces: en el camino normal esto no cuesta nada.
    if ES_POSTGRES and estado.session.info.get("inquilino_anunciado") != client_id:
        _fijar_inquilino_en_la_base(estado.session.connection(), client_id)
        estado.session.info["inquilino_anunciado"] = client_id

    for modelo in MODELOS_DEL_INQUILINO:
        estado.statement = estado.statement.options(
            with_loader_criteria(modelo, modelo.client_id == client_id,
                                 include_aliases=True))


# ── La segunda cerradura: Row-Level Security ─────────────────────────
#
# El filtro de arriba vive en el ORM: es una regla que este código se
# aplica a sí mismo. RLS pone la MISMA regla dentro de PostgreSQL, de modo
# que una consulta en SQL crudo —o una que se olvide del filtro— tampoco
# pueda devolver filas de otro negocio.
#
# Para que la base sepa de quién es cada transacción hay que decírselo, y
# eso es lo que hace `_anunciar_inquilino`. Va con `set_config(..., true)`,
# o sea LOCAL A LA TRANSACCIÓN: al terminar se olvida sola. Es lo que hace
# que sea seguro con un pool de conexiones — una conexión reutilizada
# nunca llega con el negocio del anterior puesto.
#
#     ⚠️  SIN INQUILINO NO SE ANUNCIA NADA, y las políticas dejan pasar.
#
# Es deliberado y es la misma regla que el filtro del ORM: los scripts de
# mantenimiento, las migraciones, las limpiezas del arranque y /superadmin
# tienen que poder mirar a todos los negocios. La consecuencia hay que
# decirla clara: esto protege las consultas que SÍ tienen inquilino
# puesto, que son todas las de una petición real. No es una cerradura
# contra alguien que ya pueda ejecutar el SQL que quiera en la base.
#
# Endurecerlo (que sin inquilino no se vea nada) es cambiar la política de
# la migración y darle a la app un rol propio que no sea el dueño de las
# tablas. Se puede hacer el día que haga falta; hoy sería más ceremonia
# que protección, y un camino olvidado dejaría al bot sin responder.

def _fijar_inquilino_en_la_base(conexion, client_id):
    """Le dice a PostgreSQL de qué negocio es esta transacción."""
    conexion.exec_driver_sql(
        "SELECT set_config('app.client_id', %s, true)", (str(client_id),))


@event.listens_for(SessionLocal, "after_begin")
def _anunciar_inquilino(session, transaccion, conexion):
    """
    Al abrir la transacción, decirle a la base a quién atiende.

    `after_begin` salta cuando la transacción empieza de verdad (con la
    primera consulta), no al crear la sesión, así que aquí el inquilino ya
    está puesto en todos los caminos reales: el webhook lo resuelve del
    `phone_number_id` y el panel del pase de sesión, los dos antes de
    tocar la base.
    """
    if not ES_POSTGRES:
        return

    client_id = tenencia_actual()
    if client_id is None:
        return

    _fijar_inquilino_en_la_base(conexion, client_id)
    session.info["inquilino_anunciado"] = client_id


@event.listens_for(SessionLocal, "before_flush")
def _sellar_inquilino(session, contexto, instancias):
    """
    Le pone el `client_id` a lo que se va a insertar.

    Sin esto, una fila nueva caería sobre el cliente 1 por el
    `server_default` — o sea, el negocio B guardaría sus conversaciones
    dentro de las del negocio A. Y como la fila SÍ se escribiría, el fallo
    sería silencioso.

    Solo rellena lo que viene vacío: si quien inserta ya dijo de quién es
    (las pruebas lo hacen), se respeta.
    """
    client_id = tenencia_actual()
    if client_id is None:
        return

    for obj in session.new:
        if isinstance(obj, MODELOS_DEL_INQUILINO) and obj.client_id is None:
            obj.client_id = client_id


def tenencia_actual():
    """
    El inquilino en curso, o None.

    El import va dentro y no arriba porque `tenencia` importa este módulo:
    arriba serían dos módulos importándose en círculo.
    """
    from app.core import tenencia
    return tenencia.actual_o_none()


def init_db():
    """
    Deja la base lista para arrancar.

    `create_all` solo crea las tablas que FALTAN; nunca modifica una que ya
    existe. Eso alcanza para las pruebas y para un arranque en limpio, que
    es para lo que está.

        En producción el esquema lo gobierna Alembic.

    `alembic upgrade head` corre antes que esto (ver el startCommand de
    render.yaml), así que cuando se llega aquí las tablas ya están al día y
    `create_all` no hace nada. Antes vivía aquí una migración a mano
    (`_migrar_columnas_nuevas`) que agregaba columnas con ALTER TABLE; se
    retiró al entrar Alembic, porque dos cosas gobernando el mismo esquema
    es peor que cualquiera de las dos sola.
    """
    Base.metadata.create_all(bind=engine)
    _avisar_si_faltan_las_cerraduras()
    _sembrar_cliente_inicial()
    limpiar_mensajes_procesados()
    limpiar_mensajes_antiguos()


def tablas_sin_cerradura() -> list[str]:
    """
    Las tablas del inquilino a las que les falta Row-Level Security.

    Se comprueban las tres cosas, porque cada una sola no vale: que la
    política exista, que RLS esté encendido y que esté FORZADO — sin lo
    último, la aplicación (que es la dueña de las tablas en Render) se
    salta sus propias cerraduras y todo esto sería decoración.

    Vacía = todo en orden. En SQLite devuelve vacía siempre: allí no hay
    RLS que comprobar.
    """
    if not ES_POSTGRES:
        return []

    esperadas = {m.__tablename__ for m in MODELOS_DEL_INQUILINO}
    with engine.connect() as conexion:
        filas = conexion.exec_driver_sql("""
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = current_schema()
               AND c.relrowsecurity
               AND c.relforcerowsecurity
               AND EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid)
        """).fetchall()

    return sorted(esperadas - {f[0] for f in filas})


def _avisar_si_faltan_las_cerraduras():
    """
    Un aviso a gritos si el esquema quedó sin RLS.

    El caso real: una base estrenada por `create_all` en vez de por
    Alembic (ver docs/CONTINUAR_AQUI.md §3.8). Las tablas quedan bien,
    pero sin políticas — y como nada falla, se creería protegida cuando no
    lo está. Avisar es lo único que se puede hacer aquí: crear las
    políticas por este camino sería volver a tener dos cosas gobernando el
    esquema, que es justo lo que se quitó.
    """
    try:
        faltan = tablas_sin_cerradura()
    except Exception as e:
        # Un aviso no puede ser lo que impida arrancar. Si la base no
        # contesta, ya reventó `create_all` unas líneas más arriba con un
        # error que dice bastante más que este.
        print(f"[base] No se pudo comprobar Row-Level Security: {e}")
        return

    if faltan:
        print(f"[base] AVISO: sin Row-Level Security en {', '.join(faltan)}. "
              f"El aislamiento entre clientes depende solo del filtro del "
              f"ORM. Corre 'alembic upgrade head'.")


def _sembrar_cliente_inicial():
    """
    Crea el cliente 1 si la tabla `clients` está vacía.

    Hace falta por dos motivos, y el segundo es el que muerde:

    1. El dueño del bot pasa a ser el primer inquilino sin ningún paso
       manual: lo que hasta ahora eran las variables de entorno del
       servicio se copian a su fila.

    2. Todas las tablas tienen `client_id` con FK a `clients`, y ese FK SÍ
       se aplica en PostgreSQL. En SQLite no —hace falta
       `PRAGMA foreign_keys=ON`, que no activamos—, así que sin esta
       siembra las pruebas pasarían y producción fallaría en el primer
       mensaje. Es justo el tipo de fallo que no se ve hasta desplegar.

    Los secretos (token de WhatsApp, JSON de Google, clave de Gemini) solo
    se copian si hay clave maestra para cifrarlos. Sin `SECRETS_KEY` se
    dejan en NULL y se avisa: guardar credenciales de terceros en claro
    dentro de una base compartida no es un atajo aceptable. El bot sigue
    funcionando porque la configuración de un cliente sin columna cae en
    la variable de entorno (ver `config_cliente`).
    """
    from app.core import secretos

    session = SessionLocal()
    try:
        if session.query(Client).first() is not None:
            return

        cifrables = {}
        if secretos.hay_clave():
            for campo, valor in (
                ("whatsapp_token", config.WHATSAPP_TOKEN),
                ("google_service_account_json", config.GOOGLE_SERVICE_ACCOUNT_JSON),
                ("gemini_api_key", config.GEMINI_API_KEY),
                ("vapid_private_key", config.VAPID_PRIVATE_KEY),
            ):
                if valor:
                    cifrables[campo] = secretos.cifrar(valor)
        else:
            print("[database] AVISO: falta SECRETS_KEY, así que las "
                  "credenciales del cliente inicial quedan sin copiar a la "
                  "base. El bot funciona igual: sigue leyéndolas del "
                  "entorno. Genera la clave antes de dar de alta al "
                  "segundo cliente.")

        session.add(Client(
            id=CLIENTE_POR_DEFECTO,
            slug="principal",
            nombre=config.BUSINESS_NAME or "Mi negocio",
            active=True,

            phone_number_id=config.PHONE_NUMBER_ID or None,
            waba_id=config.WABA_ID or None,

            google_calendar_id=config.GOOGLE_CALENDAR_ID or None,
            google_sheets_spreadsheet_id=config.GOOGLE_SHEETS_SPREADSHEET_ID or None,

            gemini_modelo=config.GEMINI_MODELO,
            ia_activa=config.IA_ACTIVA,
            # 0 = sin tope. El dueño no se factura a sí mismo; los topes
            # se ponen al dar de alta a cada cliente según su plan.
            ia_limite_mensual=0,

            vapid_public_key=config.VAPID_PUBLIC_KEY or None,
            vapid_contact_email=config.VAPID_CONTACT_EMAIL or None,

            owner_phone_number=config.OWNER_PHONE_NUMBER or None,
            business_whatsapp_number=config.BUSINESS_WHATSAPP_NUMBER or None,
            business_email=config.BUSINESS_EMAIL or None,
            business_website=config.BUSINESS_WEBSITE or None,

            marca_color=config.MARCA_COLOR or None,
            marca_color_fondo=config.MARCA_COLOR_FONDO or None,
            app_nombre=config.APP_NOMBRE or None,
            app_nombre_corto=config.APP_NOMBRE_CORTO or None,

            # `negocio_config` se queda en NULL a propósito: mientras lo
            # esté, el contenido sale del negocio.toml del repositorio. Pasa
            # a la base la primera vez que se guarda desde el editor o el
            # mapa. Llenarlo aquí dejaría dos fuentes de verdad.
            **cifrables,
        ))
        session.commit()
        print(f"[database] Cliente inicial creado (id={CLIENTE_POR_DEFECTO}, "
              f"slug='principal').")
    except Exception as e:
        # No puede tumbar el arranque: si la siembra falla, es mejor un
        # servicio arriba con un aviso que un servicio caído.
        print(f"[database] AVISO: no se pudo sembrar el cliente inicial: {e}")
        session.rollback()
    finally:
        session.close()


def limpiar_mensajes_procesados(dias: int = 7):
    """
    Borra IDs de mensajes viejos. Meta no reintenta un webhook días después,
    así que guardarlos para siempre solo haría crecer la tabla sin motivo.
    """
    limite = ahora_utc() - timedelta(days=dias)
    session = SessionLocal()
    try:
        borrados = (
            session.query(ProcessedMessage)
            .filter(ProcessedMessage.received_at < limite)
            .delete(synchronize_session=False)
        )
        session.commit()
        if borrados:
            print(f"[database] Limpieza: {borrados} IDs de mensajes antiguos borrados.")
    finally:
        session.close()


def limpiar_mensajes_antiguos(dias: int = None):
    """
    Borra del historial los mensajes viejos, **el plazo de cada cliente**.

    Sin esto la tabla `messages` crece para siempre, y el disco es
    justamente lo que se paga en el hosting. El panel no necesita
    conversaciones de hace medio año: para eso está el registro de leads
    en el Sheet, que no se toca nunca.

    Cada negocio puede tener su plazo (`clients.historial_dias`); quien no
    lo tenga usa `config.HISTORIAL_DIAS`, la política de la plataforma. Con
    `dias` se fuerza uno para todos, que es lo que hacen las pruebas.

    Devuelve cuántos borró en total, para poder comprobarlo.
    """
    session = SessionLocal()
    try:
        plazos = {c.id: c.historial_dias for c in session.query(Client).all()}
    finally:
        session.close()

    # Sin clientes en la tabla no hay a quién consultarle el plazo, pero sí
    # puede haber mensajes (una base a medio sembrar, o las pruebas).
    if not plazos:
        plazos = {None: None}

    total = 0
    for client_id, propio in plazos.items():
        total += _borrar_mensajes_de(client_id, dias or propio or config.HISTORIAL_DIAS)
    return total


def _borrar_mensajes_de(client_id, dias: int) -> int:
    # Un 0 mal puesto en las variables de entorno borraría el historial
    # ENTERO en el primer arranque, y eso no se deshace. Se trata como
    # "guardar para siempre", que es lo que hacía antes de existir esto.
    if dias <= 0:
        print(f"[database] plazo de historial <= 0 (cliente {client_id}): "
              f"no se borra nada.")
        return 0

    limite = ahora_utc() - timedelta(days=dias)
    session = SessionLocal()
    try:
        consulta = session.query(Message).filter(Message.created_at < limite)
        # `client_id is None` = no hay tabla de clientes todavía: se barre
        # todo lo viejo, que es lo que hacía esto antes de la tenencia.
        if client_id is not None:
            consulta = consulta.filter(Message.client_id == client_id)

        borrados = consulta.delete(synchronize_session=False)
        session.commit()
        if borrados:
            print(f"[database] Limpieza: {borrados} mensajes de más de "
                  f"{dias} días borrados del historial"
                  + (f" del cliente {client_id}." if client_id else "."))
        return borrados
    finally:
        session.close()


# ── Etiquetas libres y nota interna ──────────────────────────────────
# Las dos viven en `contacts` y las dos son SOLO del panel: ni el bot las
# lee ni el cliente las ve nunca.

# Cuántas etiquetas caben por contacto y cuánto mide cada una. No es
# capricho: sin tope, una etiqueta pegada de un correo entero rompe la
# fila del listado y la de la tabla de contactos, y nadie se entera hasta
# que la ve.
MAX_ETIQUETAS = 8
LARGO_ETIQUETA = 24
LARGO_NOTA = 2000


def etiquetas_de(contacto) -> list:
    """
    Las etiquetas de un contacto, siempre como lista.

    Tolera que la columna esté vacía, con JSON roto o con algo que no sea
    una lista: son datos que edita gente, y una excepción aquí dejaría el
    panel entero sin pintar por una etiqueta mal guardada.
    """
    if not contacto or not contacto.etiquetas:
        return []
    try:
        valor = json.loads(contacto.etiquetas)
    except (ValueError, TypeError):
        return []
    return [str(e) for e in valor] if isinstance(valor, list) else []


def _limpiar_etiquetas(etiquetas: list) -> list:
    """
    Deja la lista como se va a guardar: sin espacios sobrantes, sin
    vacías, sin repetidas y dentro de los topes.

    Las repetidas se detectan sin distinguir mayúsculas: "Cliente viejo"
    y "cliente viejo" son la misma, y tener las dos en la ficha no ayuda
    a nadie. Se conserva la primera tal y como se escribió.
    """
    limpias, vistas = [], set()

    for cruda in etiquetas or []:
        etiqueta = " ".join(str(cruda).split())[:LARGO_ETIQUETA]
        if not etiqueta:
            continue
        clave = etiqueta.lower()
        if clave in vistas:
            continue
        vistas.add(clave)
        limpias.append(etiqueta)
        if len(limpias) >= MAX_ETIQUETAS:
            break

    return limpias


def guardar_etiquetas(phone: str, etiquetas: list) -> list | None:
    """
    Guarda las etiquetas de un contacto. Devuelve las que quedaron, o
    None si ese contacto ya no existe.
    """
    session = get_session()
    try:
        contacto = session.query(Contact).filter_by(phone=phone).first()
        if not contacto:
            return None

        limpias = _limpiar_etiquetas(etiquetas)
        # Vacío se guarda como NULL y no como "[]": así la columna dice
        # "no tiene" de una sola manera y no de dos.
        contacto.etiquetas = json.dumps(limpias, ensure_ascii=False) if limpias else None
        session.commit()
        return limpias
    finally:
        session.close()


def guardar_nota(phone: str, nota: str) -> bool:
    """
    Guarda la nota interna de un contacto. False si ya no existe.

    La nota NO se le manda nunca al cliente: esta columna no la lee el
    bot. Si algún día alguien la usa para componer un mensaje, que sepa
    que quien la escribió no contaba con eso.
    """
    session = get_session()
    try:
        contacto = session.query(Contact).filter_by(phone=phone).first()
        if not contacto:
            return False

        limpia = (nota or "").strip()[:LARGO_NOTA]
        contacto.nota_interna = limpia or None
        session.commit()
        return True
    finally:
        session.close()


def guardar_suscripcion_push(endpoint: str, p256dh: str, auth: str,
                             user_id: int = None) -> bool:
    """
    Apunta un dispositivo para recibir avisos. Idempotente: si ese buzón
    ya estaba, refresca sus claves en vez de duplicarlo.

    El mismo celular puede reinscribirse con el mismo endpoint cuando el
    navegador rota las claves; sin este refresco, los avisos empezarían a
    fallar en silencio.
    """
    session = get_session()
    try:
        fila = session.query(PushSubscription).filter_by(endpoint=endpoint).first()
        if fila:
            # También el usuario: si en ese celular entra ahora otra
            # persona, los avisos tienen que ser los de ella.
            fila.p256dh, fila.auth, fila.user_id = p256dh, auth, user_id
        else:
            session.add(PushSubscription(endpoint=endpoint, p256dh=p256dh,
                                         auth=auth, user_id=user_id))

        session.commit()
        return True
    finally:
        session.close()


def borrar_suscripcion_push(endpoint: str) -> bool:
    """Da de baja un dispositivo. False si no estaba apuntado."""
    session = get_session()
    try:
        borradas = (session.query(PushSubscription)
                    .filter_by(endpoint=endpoint).delete(synchronize_session=False))
        session.commit()
        return bool(borradas)
    finally:
        session.close()


def suscripciones_push() -> list[dict]:
    """Todos los dispositivos apuntados, en el formato que espera pywebpush."""
    session = get_session()
    try:
        return [{"endpoint": s.endpoint,
                 "keys": {"p256dh": s.p256dh, "auth": s.auth},
                 "user_id": s.user_id}
                for s in session.query(PushSubscription).all()]
    finally:
        session.close()


# Los tres estados que se pueden marcar, más el vacío para quitar la
# marca. Vive aquí y no en el panel porque lo validan el endpoint y las
# pruebas: un estado inventado no debe poder entrar en la base.
ESTADOS_ATENCION = ("urgente", "esperando", "terminado")


def reiniciar_conversacion(phone: str) -> bool:
    """
    Devuelve una conversación a su principio: el próximo mensaje de esa
    persona se responde como si escribiera por primera vez.

    Hace falta por dos motivos, y el segundo costó una tarde:

      **Para probar.** El saludo, el menú y todo lo que se cambie desde el
      panel solo se ven al empezar una conversación. Quien está probando
      su propio bot ya tiene una a medias, así que cambiaba un texto,
      escribía, y el bot seguía por donde iba — pareciendo que el cambio
      no se había guardado. La única alternativa era esperar las
      `CONVERSATION_TIMEOUT_HOURS` (24 h) o usar otro número.

      **Para atender.** Un cliente que se quedó atascado a mitad de un
      formulario tenía que esperar un día para poder empezar de nuevo.

    No borra nada: ni el historial, ni el nombre, ni sus leads. Solo mueve
    el punto del recorrido. Devuelve False si no existe ese contacto.
    """
    session = get_session()
    try:
        contacto = session.query(Contact).filter_by(phone=phone).first()
        if contacto is None:
            return False

        contacto.state = "NEW"
        contacto.servicio = None
        contacto.recorrido = None
        session.commit()
        return True
    finally:
        session.close()


def guardar_estado_atencion(phone: str, estado: str) -> bool:
    """
    Marca en qué punto está la conversación. Cadena vacía quita la marca.

    Devuelve False si el contacto no existe o si el estado no es uno de
    los conocidos.
    """
    if estado and estado not in ESTADOS_ATENCION:
        return False

    session = get_session()
    try:
        contacto = session.query(Contact).filter_by(phone=phone).first()
        if not contacto:
            return False

        contacto.estado_atencion = estado or None
        session.commit()
        return True
    finally:
        session.close()


def borrar_contacto(phone: str) -> dict | None:
    """
    Borra un contacto y todo su rastro en la base: sus mensajes y sus
    leads. Devuelve un resumen de lo borrado, o None si no existía.

    NO toca Google Calendar ni el Sheet. Es a propósito: borrar una
    conversación del panel no puede hacerte perder una cita reservada de
    verdad sin que te enteres. Si el contacto tenía citas, sus ids de
    evento vuelven en el resumen para que el panel pueda avisarte.

    Es irreversible. Si el cliente vuelve a escribir después, el bot lo
    trata como nuevo y le pregunta el nombre otra vez.
    """
    session = get_session()
    try:
        contacto = session.query(Contact).filter_by(phone=phone).first()
        if not contacto:
            return None

        citas = [l.google_event_id
                 for l in session.query(Lead).filter_by(contact_id=contacto.id)
                 if l.google_event_id]

        mensajes = session.query(Message).filter_by(phone=phone).delete(
            synchronize_session=False)
        leads = session.query(Lead).filter_by(contact_id=contacto.id).delete(
            synchronize_session=False)
        session.delete(contacto)
        session.commit()

        print(f"[database] {phone} borrado: {mensajes} mensajes, {leads} leads.")
        return {"phone": phone, "mensajes": mensajes, "leads": leads,
                "citas_en_calendar": citas}
    finally:
        session.close()


def actividad_por_cliente() -> dict:
    """
    Cuánto se movió cada negocio: contactos, mensajes y cuándo fue el
    último. Para el listado del super-admin.

        ⚠️  Tiene que correr SIN inquilino fijado.

    Si hubiera uno, `_filtrar_por_inquilino` recortaría el recuento a ese
    negocio y el listado enseñaría ceros para todos los demás — sin dar
    ningún error. Por eso /superadmin queda fuera del middleware que fija
    el inquilino (ver `app/main.py`).

    Devuelve {client_id: {contactos, mensajes, ultimo}}.
    """
    session = SessionLocal()
    try:
        contactos = dict(session.query(Contact.client_id, func.count(Contact.id))
                         .group_by(Contact.client_id).all())

        mensajes = {fila[0]: (fila[1], fila[2]) for fila in
                    session.query(Message.client_id, func.count(Message.id),
                                  func.max(Message.created_at))
                    .group_by(Message.client_id).all()}

        return {cid: {
            "contactos": contactos.get(cid, 0),
            "mensajes": mensajes.get(cid, (0, None))[0],
            "ultimo": mensajes.get(cid, (0, None))[1],
        } for cid in set(contactos) | set(mensajes)}
    finally:
        session.close()


def get_session():
    return SessionLocal()
