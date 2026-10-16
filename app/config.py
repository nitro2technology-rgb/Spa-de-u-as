"""
CONFIGURACIÓN
=============
La puerta de entrada a la configuración, para todo el proyecto.

Se sigue escribiendo `config.WELCOME_MESSAGE`, `config.PHONE_NUMBER_ID` o
`config.nombre_servicio(x)` exactamente igual que antes. Lo que cambió es
lo que hay detrás: ya no son constantes de un solo negocio, sino los
valores del INQUILINO de la petición en curso.

CÓMO FUNCIONA
-------------
Este módulo casi no define nada. Lo que hace es `__getattr__`: cuando
alguien pide un atributo que no existe aquí, Python llama a esa función,
que averigua de qué cliente es la petición (`app/core/tenencia.py`) y
devuelve el valor de su configuración (`app/core/config_cliente.py`).

Se eligió así en vez de pasar un objeto `cfg` por parámetro porque hay 247
lecturas de configuración repartidas por 18 archivos, incluidas 71 dentro
de `bot_logic.py`. Cambiarlas todas era una oportunidad de equivocarse por
cada una, y las pruebas que existen —que son la red de seguridad de esta
migración— dejarían de compilar antes de poder decir si algo se rompió.

QUÉ ES GLOBAL Y QUÉ ES DE CADA CLIENTE
--------------------------------------
Aquí abajo, como constantes de verdad, queda solo lo que es del SISTEMA:
la base de datos, la versión de la Graph API, los límites técnicos y los
plazos de sesión del panel.

    La App de Meta ESTUVO aquí y ya no está. Cada negocio trae la suya,
    así que `APP_ID`, `APP_SECRET` y `VERIFY_TOKEN` se resuelven por
    inquilino como todo lo demás. Ver el bloque de la API de Meta.

Todo lo que es de un NEGOCIO —sus textos, su menú, su horario, su marca,
sus credenciales— vive en `ConfiguracionCliente` y se resuelve por
inquilino.

    ⚠️  SIN INQUILINO FIJADO SE DEVUELVE LA CONFIGURACIÓN BASE.

Es decir: la que sale del entorno y del `negocio.toml` del repositorio,
que es exactamente como se comportaba el bot antes de existir los
inquilinos. Sirve para los scripts de `scripts/`, para las pruebas y para
cualquier camino que aún no se haya migrado.

Es una rampa, no un descuido, y tiene una propiedad que la hace segura:
**la configuración base NUNCA lee la base de datos**, así que jamás puede
devolver los datos de otro cliente de pago. Lo peor que puede pasar es que
un camino sin migrar use la configuración del dueño del bot.
"""

import os

from dotenv import load_dotenv

from app.core.config_cliente import (        # noqa: F401  (re-export)
    CLIENTE_POR_DEFECTO,
    ConfiguracionCliente,
    NEGOCIO_TOML,
    carpeta_media_base,
    color_legible_sobre,
    duracion_en_palabras,
    leer_negocio_toml,
    rgb_de,
)

# El nombre que tenía cuando era una función privada de este módulo. Se
# conserva porque las pruebas de regresión lo usan, y esas pruebas son la
# red de seguridad de toda esta migración: no se tocan para que sigan
# comprobando lo mismo que comprobaban antes.
_duracion_en_palabras = duracion_en_palabras

load_dotenv()  # carga el archivo .env si existe


# ══════════════════════════════════════════════════════════════════════
#  AJUSTES DEL SISTEMA — iguales para todos los clientes
# ══════════════════════════════════════════════════════════════════════

# ── Base de datos ────────────────────────────────────────────────────
# Una sola base para todos los inquilinos. Cada fila lleva `client_id`.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////var/data/bot.db")

# Días de conversación que se guardan. Lo más viejo se borra al arrancar.
#
# Es la política de la PLATAFORMA: la que aplica al negocio que no haya
# pedido otra cosa. El plazo de cada cliente vive en `clients.historial_dias`
# y manda sobre este (ver `database.limpiar_mensajes_antiguos`).
HISTORIAL_DIAS = int(os.getenv("HISTORIAL_DIAS", "180"))

# ── La API de Meta ───────────────────────────────────────────────────
# La VERSIÓN de la Graph API sí es del sistema: es contra qué API habla
# este código, no un dato de ningún negocio.
GRAPH_API_VERSION = "v21.0"

#   ⚠️  APP_ID, APP_SECRET y VERIFY_TOKEN YA NO ESTÁN AQUÍ.
#
# Estuvieron, y su comentario decía "UNA SOLA APP PARA TODOS LOS
# CLIENTES". Eso dejó de ser cierto: cada negocio trae ahora su propia
# App de Meta, creada desde su cuenta de developers, y por eso esos tres
# valores bajaron a `ConfiguracionCliente` como cualquier otro dato de un
# cliente.
#
# El cambio de modelo es comercial antes que técnico: con la App nuestra,
# conectar el número de un cliente dependía de que Meta nos aprobara el
# App Review a nosotros, y además nos hacía dueños de números ajenos.
#
# **Quitarlos de aquí no rompe nada**, y conviene entender por qué antes
# de volver a subir uno "para tenerlo a mano": al no estar definidos
# arriba, `config.APP_SECRET` pasa por el `__getattr__` de abajo, que
# resuelve el inquilino en curso; y si no hay ninguno fijado cae en
# `base()`, que lee del ENTORNO. O sea que un script suelto o un camino
# sin migrar siguen viendo la variable de Render de siempre, igual que
# antes. Subirlos otra vez aquí es lo que rompería: se convertirían en el
# valor de todos y el App Secret del dueño validaría la firma de otro.

# Si está en False, el webhook acepta cualquier POST sin validar firma.
# Útil solo para pruebas locales. En producción debe quedar en True.
VERIFY_WEBHOOK_SIGNATURE = os.getenv("VERIFY_WEBHOOK_SIGNATURE", "true").lower() == "true"

# ── Correo de avisos ─────────────────────────────────────────────────
# Con qué cuenta se le avisa por correo a las áreas de un negocio cuando
# entra un lead (ver `app/core/correo.py`).
#
# ES DEL SISTEMA Y NO DE CADA CLIENTE, a propósito. Pedirle a cada negocio
# las credenciales de su correo sería otra credencial que custodiar y otro
# paso donde atascarse en el alta, para algo que el destinatario no ve: el
# aviso dice de qué negocio es en el asunto.
#
# Sin `SMTP_HOST` y `SMTP_DESDE` esto no hace nada y el bot funciona
# igual, como con las claves de push.
#
# Con `or` y no con el segundo argumento de `getenv`: una variable que
# existe pero vacía (Render la crea así si se deja en blanco) no puede
# ganarle al valor por defecto.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PUERTO = os.getenv("SMTP_PUERTO") or "587"
SMTP_USUARIO = os.getenv("SMTP_USUARIO", "")
SMTP_CLAVE = os.getenv("SMTP_CLAVE", "")
SMTP_DESDE = os.getenv("SMTP_DESDE", "")
SMTP_NOMBRE = os.getenv("SMTP_NOMBRE") or "Nitro 2Tech"

# La dirección del panel, para poner el enlace a la conversación dentro
# del correo. Sin esto el aviso dice qué pasó pero no lleva a ningún
# sitio, que es la mitad de su utilidad.
PANEL_URL = (os.getenv("PANEL_URL") or "https://bot.nitro2tech.com").rstrip("/")

# ── Archivos del chat ────────────────────────────────────────────────
# El disco es solo un CACHÉ: Meta guarda una copia 7 días de todo lo que
# entra por el webhook, así que aquí basta con tener a mano lo de las
# últimas horas. La CARPETA sí es por cliente (config_cliente.MEDIA_DIR).
MEDIA_CACHE_DIAS = int(os.getenv("MEDIA_CACHE_DIAS", "1"))
MEDIA_CACHE_MB = int(os.getenv("MEDIA_CACHE_MB", "200"))

# Límites de Meta, que no se pueden subir aunque se quiera:
#   imagen 5 MB y solo JPEG/PNG · audio 16 MB · documento 100 MB
MEDIA_MAX_MB_IMAGEN = 5
MEDIA_MAX_MB_AUDIO = 16

# ── Sesión del panel ─────────────────────────────────────────────────
# Plazos, no credenciales: son política del producto, iguales para todos.
PANEL_SESION_INACTIVIDAD_HORAS = float(os.getenv("PANEL_SESION_INACTIVIDAD_HORAS", "5"))
PANEL_SESION_MAXIMA_HORAS = float(os.getenv("PANEL_SESION_MAXIMA_HORAS", "12"))
PANEL_MAX_INTENTOS_LOGIN = int(os.getenv("PANEL_MAX_INTENTOS_LOGIN", "8"))
PANEL_BLOQUEO_LOGIN_MINUTOS = int(os.getenv("PANEL_BLOQUEO_LOGIN_MINUTOS", "15"))

# ── IA: lo que es técnico, no comercial ──────────────────────────────
# Segundos que se espera a Gemini antes de rendirse y responder con el
# menú. Corto a propósito: Meta REINTENTA el webhook si tardamos, y un
# reintento con el bot pensando le llega al cliente como un duplicado.
IA_TIMEOUT_SEGUNDOS = float(os.getenv("IA_TIMEOUT_SEGUNDOS", "8"))


# ══════════════════════════════════════════════════════════════════════
#  LA CONFIGURACIÓN DE CADA CLIENTE
# ══════════════════════════════════════════════════════════════════════

# Armar una configuración implica leer el TOML entero y resolver los
# enlaces y precios de cada opción del menú. Hacerlo en cada mensaje sería
# tirar ese trabajo a la basura dentro del camino caliente del webhook.
_configs: dict = {}
_config_base = None


def base() -> ConfiguracionCliente:
    """
    La configuración que sale del entorno y del negocio.toml.

    Es la de antes de que existieran los inquilinos. Se usa cuando nadie
    fijó uno: scripts, pruebas y caminos sin migrar.
    """
    global _config_base
    if _config_base is None:
        _config_base = ConfiguracionCliente()
    return _config_base


def para(client_id: int) -> ConfiguracionCliente:
    """La configuración de un cliente concreto, por su id."""
    if client_id in _configs:
        return _configs[client_id]

    from app.core import tenencia

    datos = tenencia.por_id(client_id)
    if datos is None:
        # Un id que no existe no puede resolverse a la configuración de
        # otro: eso sería atender a un cliente con los datos de un tercero.
        raise tenencia.InquilinoDesconocido(
            f"No existe el cliente {client_id!r}.")

    _configs[client_id] = ConfiguracionCliente(
        fila=datos.fila, negocio=datos.fila.get("negocio_config"))
    return _configs[client_id]


def actual() -> ConfiguracionCliente:
    """
    La configuración del inquilino de esta petición, o la base si no hay.

    Es lo que resuelve cada `config.LO_QUE_SEA` del proyecto.
    """
    from app.core import tenencia

    client_id = tenencia.actual_o_none()
    if client_id is None:
        return base()
    return para(client_id)


def olvidar(client_id: int = None):
    """
    Tira la configuración cacheada. Hay que llamarlo tras cambiar los
    datos de un cliente, o el cambio no se vería hasta reiniciar.
    """
    global _config_base
    from app.core import tenencia

    if client_id is None:
        _configs.clear()
        _config_base = None
        tenencia.olvidar()
        return

    _configs.pop(client_id, None)
    tenencia.olvidar(client_id)


def __getattr__(nombre: str):
    """
    Lo que hace que `config.WELCOME_MESSAGE` siga funcionando.

    Python solo llama a esto cuando el atributo NO está definido arriba,
    así que los ajustes del sistema se resuelven directo y sin pasar por
    aquí. Todo lo demás es del cliente en curso.
    """
    # Sin esto, un `from app import config` dentro de un módulo a medio
    # importar puede pedir dunders (__path__, __all__…) y acabaría
    # buscándolos en la configuración de un negocio.
    if nombre.startswith("__"):
        raise AttributeError(nombre)

    # Resolver la configuración va FUERA del try. Si envolviéramos las dos
    # cosas, cualquier AttributeError de dentro —un import circular, por
    # ejemplo— se disfrazaría de "esa clave no existe" y mandaría a buscar
    # el problema al sitio equivocado. Ya pasó una vez.
    cfg = actual()

    try:
        return getattr(cfg, nombre)
    except AttributeError as e:
        raise AttributeError(
            f"'{nombre}' no es ni un ajuste del sistema ni un valor de la "
            f"configuración del cliente.") from e


# ══════════════════════════════════════════════════════════════════════
#  VALIDACIÓN AL ARRANCAR
# ══════════════════════════════════════════════════════════════════════
#
# La configuración base se construye AQUÍ, al importar el módulo, y no la
# primera vez que alguien lea un valor.
#
# Es a propósito y es importante: armarla es lo que detecta un
# `negocio.toml` mal escrito —una opción del menú que nombra un enlace o
# unos precios que no existen en el archivo—, y eso tiene que reventar el
# DESPLIEGUE, cuando aún se puede volver a la versión anterior.
#
# Si se dejara para el primer acceso, un TOML roto arrancaría el servicio
# tan campante y el error aparecería en mitad de la primera conversación
# con un cliente, que recibiría un mensaje en blanco o ninguno. Hay una
# prueba de regresión que lo cubre.
#
# La configuración de CADA cliente se valida cuando se le da de alta, no
# aquí: sus datos están en la base, no en este archivo.
base()
