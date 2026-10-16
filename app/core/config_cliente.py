"""
LA CONFIGURACIÓN DE UN NEGOCIO
===============================
Todo lo que distingue al bot de un cliente del de otro: sus textos, su
menú, sus precios, su horario, su marca y sus credenciales.

Antes esto eran ~120 constantes calculadas al importar `app/config.py`,
lo que ataba el proceso a UN negocio: el primero que se cargara. Aquí es
un objeto, y hay uno por inquilino.

    `app/config.py` sigue siendo la puerta de entrada.

Nadie importa este módulo para leer configuración. Se sigue escribiendo
`config.WELCOME_MESSAGE`, igual que siempre, y `config.py` averigua de qué
inquilino es la petición en curso y pregunta aquí. Esas 247 lecturas
repartidas por el proyecto no se tocaron: reescribirlas era una
oportunidad de equivocarse por cada una.

DE DÓNDE SALE CADA VALOR
------------------------
En este orden, y el primero que tenga algo gana:

  1. Una columna de la fila del cliente en `clients` (lo que se edita
     desde el panel de administración).
  2. Su `negocio_config`, que es el `negocio.toml` guardado como JSON.
  3. Una variable de entorno — **solo si el cliente todavía no tiene
     `negocio_config`**. Ver más abajo.
  4. El valor por defecto.

EL PASO 3 SE RETIRA SOLO
------------------------
Antes las variables de entorno ganaban sobre el TOML: eran la vía para un
arreglo urgente sin desplegar. Con un solo negocio eso tenía sentido.

Con varios NO puede tenerlo: una variable de entorno es del proceso, y el
proceso es de todos. Si `BUSINESS_TIMEZONE=America/Bogota` ganara sobre el
TOML, un cliente en México heredaría el horario de otro.

Por eso el entorno solo se consulta para el cliente que aún no tiene su
configuración en la base — que hoy es el dueño del bot, y mañana ninguno.
Es una rampa de migración que se apaga sola: en cuanto un cliente tiene
`negocio_config`, su configuración es suya y solo suya.
"""

import os
import tomllib

from app.core import secretos

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# El inquilino al que pertenece todo lo que existía antes de que hubiera
# inquilinos: el dueño del bot, que pasa a ser el primer cliente.
#
# Vive aquí y no en `database.py` porque este módulo no importa nada del
# proyecto, y así puede usarlo tanto la base de datos como la
# configuración sin que se importen en círculo.
CLIENTE_POR_DEFECTO = 1

def identificador_de_area(guardado, nombre, posicion: int) -> str:
    """
    El id de un área: el que tenga guardado, o uno sacado de su nombre.

    Las áreas guardadas antes del 23-sep-2026 no traen id; se les deduce
    del nombre ("Admin 1" → "admin-1") para que sigan siendo las mismas al
    guardarlas con uno.
    """
    import re
    import unicodedata

    ident = str(guardado or "").strip().lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", ident):
        return ident
    base = unicodedata.normalize("NFKD", str(nombre or "").lower())
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:30]
    return base or f"area-{posicion + 1}"


def cupo_de_destinos(fila: dict | None) -> int:
    """
    Cuántas áreas le tocan a este negocio: lo que diga su PLAN comercial
    (`app/core/planes.py`), o lo pactado con él si tiene algo.

    Sale del plan COMERCIAL —lo que compró— y nunca de `plan_activo()`,
    que es lo que el dueño tiene encendido ahora: apagar la IA un rato no
    puede recortarle las áreas.

    Vive aquí, y no en el formulario, porque el formulario no es la única
    puerta: una pestaña vieja del navegador o el editor en crudo pueden
    mandar más filas. Se recorta al construir la configuración, que es por
    donde pasa todo el mundo.
    """
    from app.core import planes
    return planes.cupo_de_areas(fila)

# El negocio.toml del repositorio. Es el del dueño del bot mientras no se
# haya pasado a la base, y la plantilla desde la que se da de alta a un
# cliente nuevo.
NEGOCIO_TOML = os.getenv("NEGOCIO_TOML", os.path.join(_RAIZ, "negocio.toml"))

_toml_cache = None


def leer_negocio_toml() -> dict:
    """El negocio.toml del repositorio, leído una sola vez."""
    global _toml_cache
    if _toml_cache is None:
        with open(NEGOCIO_TOML, "rb") as f:
            _toml_cache = tomllib.load(f)
    return _toml_cache


# ── Utilidades de color, que no dependen de ningún negocio ───────────

def rgb_de(color: str, respaldo: tuple = (22, 163, 74)) -> tuple:
    """'#7c3aed' → (124, 58, 237). Si viene mal escrito, el color de casa."""
    texto = (color or "").strip().lstrip("#")
    if len(texto) == 3:
        texto = "".join(c * 2 for c in texto)
    if len(texto) != 6:
        return respaldo
    try:
        return tuple(int(texto[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return respaldo


def color_legible_sobre(fondo: tuple) -> str:
    """
    Negro o blanco, el que se lea sobre ese fondo. Devuelve el hex listo
    para CSS.

    Hace falta porque el color de marca lo elige cada cliente: con uno
    amarillo, las letras blancas de los botones desaparecen.
    """
    r, g, b = fondo
    brillo = (r * 299 + g * 587 + b * 114) / 1000
    return "#111827" if brillo > 150 else "#ffffff"


def duracion_en_palabras(minutos: int) -> str:
    """"60" se le dice al cliente como "1 hora", no como "60 minutos"."""
    if minutos % 60:
        return f"{minutos} minutos"
    horas = minutos // 60
    return "1 hora" if horas == 1 else f"{horas} horas"


def carpeta_media_base() -> str:
    """
    La carpeta raíz del caché de imágenes y notas de voz.

    Con SQLite se pone al lado del archivo de la base, que es el único
    sitio que sobrevivía al despliegue. Con PostgreSQL no hay "carpeta de
    la base", así que se usa una del proyecto — efímera, y da igual: esto
    es un CACHÉ y Meta conserva 7 días lo que entra por webhook.
    """
    if ruta := os.getenv("MEDIA_DIR", ""):
        return ruta

    url = os.getenv("DATABASE_URL", "")
    if url.startswith("sqlite"):
        archivo = url.split("///")[-1]
        return os.path.join(os.path.dirname(os.path.abspath(archivo)), "media")

    return os.path.join(_RAIZ, "media")


class ConfiguracionCliente:
    """
    La configuración de UN negocio, ya resuelta y lista para leer.

    Se construye una vez por cliente y se guarda en caché (ver
    `app/config.py`), porque armarla implica leer el TOML entero y resolver
    los enlaces y precios del menú. Hacerlo en cada mensaje sería tirar
    trabajo a la basura en el camino caliente del webhook.
    """

    def __init__(self, fila: dict | None = None, negocio: dict | None = None):
        # `fila` son las columnas de `clients`. `negocio` es el contenido
        # del TOML. Los dos pueden faltar en las pruebas, que construyen
        # esto sin base de datos.
        self._fila = fila or {}
        self._negocio_de_la_base = negocio is not None
        self._n = negocio if negocio is not None else leer_negocio_toml()

        # El entorno solo cuenta para quien aún no tiene su configuración
        # en la base. Ver el docstring del módulo.
        self._usar_entorno = not self._negocio_de_la_base

        self._construir()

    # ── Resolución de un valor suelto ────────────────────────────────

    def _col(self, nombre: str):
        """El valor de una columna de `clients`, o None si está vacía."""
        valor = self._fila.get(nombre)
        return valor if valor not in (None, "") else None

    def _env(self, nombre: str):
        """Una variable de entorno, solo si a este cliente le aplican."""
        if not self._usar_entorno:
            return None
        valor = os.getenv(nombre)
        return valor if valor not in (None, "") else None

    def _texto(self, seccion: str, clave: str, defecto=""):
        return self._n.get(seccion, {}).get(clave, defecto)

    def _entero(self, valor, defecto: int, minimo: int = None,
                maximo: int = None) -> int:
        """
        Un número de la configuración, dentro de lo que tiene sentido.

        Lo escribe alguien desde una pantalla, así que llega como texto,
        vacío o fuera de rango. Un `int()` a pelo convertía un campo en
        blanco en un ValueError que dejaba sin configuración —o sea, sin
        bot— al negocio entero. Y un 0 en la duración de la cita colgaba
        el cálculo de horarios en un bucle sin fin.
        """
        try:
            numero = int(str(valor).strip())
        except (ValueError, TypeError):
            numero = defecto
        if minimo is not None:
            numero = max(minimo, numero)
        if maximo is not None:
            numero = min(maximo, numero)
        return numero

    def _texto_del_bot(self, clave: str) -> str:
        """
        Un texto de la conversación, con el defecto del producto detrás.

        Antes, lo que no estuviera escrito quedaba en cadena vacía. Con un
        negocio que traía el `negocio.toml` entero eso no se notaba: venían
        todos. Desde que **un negocio nace en blanco** (ver
        `mapa.negocio_en_blanco`) sí se nota, y de la peor manera — el bot
        mandaría mensajes VACÍOS, y una lista de WhatsApp con la etiqueta
        del botón vacía Meta la rechaza entera.

        Estos defectos no son la plantilla de ningún negocio: no hablan de
        servicios, ni de precios, ni de horarios. Son el vocabulario del
        propio bot, lo que tiene que saber decir cualquiera. Todos se
        pueden cambiar desde el editor.
        """
        return self._texto("textos", clave) or TEXTOS_POR_DEFECTO.get(clave, "")

    def _valor(self, columna=None, entorno=None, seccion=None, clave=None,
               defecto=""):
        """La cascada completa: columna → entorno → TOML → defecto."""
        if columna and (v := self._col(columna)) is not None:
            return v
        if entorno and (v := self._env(entorno)) is not None:
            return v
        if seccion and clave:
            # Vacío cuenta como "no dicho", igual que en `_col` y `_env`.
            # Es lo que hace el editor cuando alguien deja un campo en
            # blanco, y sin esto un `duracion_cita_min = ""` no caería al
            # defecto: reventaría en el `int()` de quien llama.
            v = self._texto(seccion, clave, None)
            if v not in (None, ""):
                return v
        return defecto

    # Huecos que rellena el BOT en cada conversación, mucho después de
    # esto: el nombre de quien escribe, la fecha que eligió, el enlace de
    # la opción. Un negocio no puede definir una variable que se llame
    # igual — la suya ganaría aquí y el bot se quedaría sin poder poner el
    # dato de verdad, que es lo que hace personal a la respuesta.
    NOMBRES_RESERVADOS = frozenset({
        "name", "nombre", "url", "date", "time", "detail", "origen",
        "servicio", "phone", "n", "horas", "minutos", "negocio", "duracion",
    })

    def _leer_variables(self, crudas) -> dict:
        """
        Las variables del negocio, limpias.

        Se descarta en silencio lo que no sirve —nombres reservados, claves
        raras, valores que no son texto— en vez de levantar: esto lo
        escribe alguien desde una pantalla, y una variable de más no puede
        dejar al bot sin arrancar. Lo que sí avisa es el editor, que es
        donde se puede corregir.
        """
        if not isinstance(crudas, dict):
            return {}

        limpias = {}
        for nombre, valor in crudas.items():
            nombre = str(nombre).strip()
            if (not nombre or nombre in self.NOMBRES_RESERVADOS
                    or not nombre.replace("_", "").isalnum()):
                continue
            limpias[nombre] = "" if valor is None else str(valor)
        return limpias

    def _leer_destinos(self, crudos) -> list:
        """
        Las áreas que reciben avisos, limpias y con tope.

        Cada una es `{"nombre", "numero", "correo", "opciones"}`: a qué
        opciones del menú se dedica. Sin opciones = recoge todo lo que
        nadie reclame.

        **Esto lo edita gente desde un formulario**, así que se limpia
        aquí y no se confía en lo guardado: un número con espacios o un
        `+` delante hace que Meta rechace el envío con un error que no
        dice que el problema era el formato del número.

        Se descarta el área que no tenga ni correo ni número —no hay por
        dónde avisarle— en vez de guardarla a medias: un destino silencioso
        en la lista parece configurado y no lo está.
        """
        if not isinstance(crudos, list):
            return []

        cupo = getattr(self, "MAX_DESTINOS_AVISOS", 0)

        limpios = []
        for fila in crudos:
            if not isinstance(fila, dict):
                continue

            # Meta quiere el número en formato internacional sin "+" ni
            # separadores: "573001112233". El país y el número se guardan
            # aparte —así se pueden volver a pintar en dos cuadros— y se
            # juntan aquí, que es el único sitio por el que pasa todo el
            # mundo.
            solo_digitos = lambda v: "".join(c for c in str(v or "") if c.isdigit())

            indicativo = solo_digitos(fila.get("indicativo"))
            local = solo_digitos(fila.get("numero"))

            # El correo es la vía principal desde que se vio que WhatsApp no
            # sirve para avisar a un equipo (tres puertas que lo bloquean:
            # la ventana de 24 h, la plantilla y la facturación de Meta).
            # Ver `app/core/correo.py`.
            correo = str(fila.get("correo") or "").strip()[:120]

            # Un área vale si tiene POR DONDE avisarle: correo, WhatsApp, o
            # los dos. Antes hacía falta el número sí o sí, y eso dejaba
            # fuera al área que solo quiere correo — que ahora es el caso
            # normal.
            if not local and not correo:
                continue

            # SI EL NÚMERO YA VIENE COMPLETO, NO SE LE PEGA EL PAÍS OTRA VEZ.
            #
            # Pasa en dos casos y los dos son normales: lo guardado antes de
            # que existieran los dos cuadros (todo junto en `numero`), y
            # quien pega el número entero en el cuadro de la derecha sin
            # darse cuenta.
            #
            # Se distingue por longitud y no por el prefijo: `57` es un
            # comienzo perfectamente válido de un número local, así que
            # "empieza por el indicativo" no prueba nada. Un número local no
            # llega a 11 dígitos en ningún país que nos importe —Colombia
            # 10, España 9, México 10, EE.UU. 10— y uno internacional
            # siempre los pasa.
            if not local:
                numero = ""
            elif indicativo and len(local) < 11:
                numero = indicativo + local
            else:
                numero = local

            opciones = fila.get("opciones")
            if not isinstance(opciones, list):
                opciones = []

            limpios.append({
                # Lo que une el área con el usuario que entra por ella
                # (`panel_users.area_id`). No sale del nombre: renombrar
                # "Ventas" a "Ventas y cotizaciones" no puede dejar a esa
                # persona sin sus conversaciones.
                "id": identificador_de_area(fila.get("id"), fila.get("nombre"),
                                            len(limpios)),
                "nombre": str(fila.get("nombre") or "").strip()[:40],
                "numero": numero,
                "correo": correo,
                "opciones": [str(o).strip() for o in opciones if str(o).strip()],
            })

        # Dos áreas con el mismo nombre darían el mismo id, y entonces un
        # usuario vería las conversaciones de las dos.
        vistos = set()
        for d in limpios:
            base, n = d["id"], 2
            while d["id"] in vistos:
                d["id"] = f"{base}-{n}"
                n += 1
            vistos.add(d["id"])

        # El tope se aplica DESPUÉS de descartar las inválidas, no antes.
        # Al revés, un área a medio llenar gastaba un cupo y dejaba fuera a
        # una buena que venía detrás — sin decir nada, que es lo peor.
        return limpios[:cupo]

    def _secreto(self, columna: str, entorno: str) -> str:
        """
        Una credencial. En la base va cifrada; en el entorno, en claro.

        Si el descifrado falla no se puede seguir como si nada: devolver
        cadena vacía dejaría al bot intentando hablar con Meta sin token y
        el error aparecería tres capas más abajo, sin decir que el problema
        era la clave maestra.
        """
        guardado = self._col(columna)
        if guardado is not None:
            return secretos.descifrar(guardado)
        return self._env(entorno) or ""

    def _rellenar(self, valor):
        """
        Sustituye los huecos que dependen de otra parte de la configuración.

        En el contenido se escribe "{negocio}" o "{duracion}" y aquí se
        cambian por su valor. NO se usa str.format: los textos llevan
        además huecos como "{name}" o "{url}" que tiene que rellenar el bot
        mucho después, y format se los comería aquí.

        Desde el 18-ago-2026 cada negocio puede definir **las suyas** en
        `[variables]`, y se sustituyen igual. Sirven para lo que se repite
        en veinte textos y cambia una vez al año: el celular, la dirección,
        el horario de atención escrito en prosa.
        """
        if isinstance(valor, str):
            texto = (valor.replace("{negocio}", self.BUSINESS_NAME)
                          .replace("{duracion}", self._duracion_palabras))
            for nombre, contenido in self.VARIABLES.items():
                texto = texto.replace("{" + nombre + "}", contenido)
            return texto
        if isinstance(valor, list):
            return [self._rellenar(v) for v in valor]
        if isinstance(valor, dict):
            return {k: self._rellenar(v) for k, v in valor.items()}
        return valor

    # ── Construcción ─────────────────────────────────────────────────

    def _construir(self):
        n = self._n

        # El nombre va primero: `_rellenar` lo necesita para "{negocio}".
        self.BUSINESS_NAME = self._valor(
            columna="nombre", seccion="negocio", clave="nombre")

        # Y las variables del negocio justo después, porque a partir de
        # aquí todo lo que pase por `_rellenar` puede usarlas.
        self.VARIABLES = self._leer_variables(n.get("variables"))

        # ── Credenciales de Meta ─────────────────────────────────────
        self.WHATSAPP_TOKEN = self._secreto("whatsapp_token", "WHATSAPP_TOKEN")
        self.PHONE_NUMBER_ID = self._valor(
            columna="phone_number_id", entorno="PHONE_NUMBER_ID")
        self.WABA_ID = self._valor(columna="waba_id", entorno="WABA_ID")

        # ── La App de Meta, que es la DEL CLIENTE ────────────────────
        # Antes eran constantes del sistema en `app/config.py`: una sola
        # App para todos, con su secreto en el entorno del servicio. Ahora
        # cada negocio trae la suya, así que bajan a la cascada como
        # cualquier otro dato de un cliente.
        #
        # La cascada columna → entorno es justo lo que hace que esto no
        # rompa nada al desplegarse: el cliente que todavía no tenga sus
        # columnas puestas sigue leyendo las variables de Render de
        # siempre y atiende igual que ayer. Es la misma rampa que se usó
        # con `gemini_modelo`, y se apaga sola cuando el último cliente
        # tiene lo suyo.
        self.APP_ID = self._valor(columna="app_id", entorno="APP_ID")
        self.APP_SECRET = self._secreto("app_secret", "APP_SECRET")
        # Sin defecto a propósito. Era "mi_token_de_verificacion", o sea
        # uno que cualquiera puede adivinar: un negocio sin el suyo
        # aceptaba el handshake de quien lo escribiera. Vacío, el webhook
        # no verifica a nadie hasta que se le ponga uno (`main`).
        self.VERIFY_TOKEN = self._valor(
            columna="verify_token", entorno="VERIFY_TOKEN")

        # El trozo aleatorio de su URL de webhook. No tiene variable de
        # entorno: no es un ajuste que se pueda poner "para todos", es la
        # identidad de UNA fila. Sin él, ese cliente no tiene URL propia
        # todavía y entra por `/webhook` a secas, como siempre.
        self.WEBHOOK_TOKEN = self._col("webhook_token") or ""

        # ── Google ───────────────────────────────────────────────────
        self.GOOGLE_SERVICE_ACCOUNT_JSON = self._secreto(
            "google_service_account_json", "GOOGLE_SERVICE_ACCOUNT_JSON")
        self.GOOGLE_CALENDAR_ID = self._valor(
            columna="google_calendar_id", entorno="GOOGLE_CALENDAR_ID")
        self.GOOGLE_SHEETS_SPREADSHEET_ID = self._valor(
            columna="google_sheets_spreadsheet_id",
            entorno="GOOGLE_SHEETS_SPREADSHEET_ID")

        # ── Avisos al celular ────────────────────────────────────────
        self.VAPID_PUBLIC_KEY = self._valor(
            columna="vapid_public_key", entorno="VAPID_PUBLIC_KEY")
        self.VAPID_PRIVATE_KEY = self._secreto(
            "vapid_private_key", "VAPID_PRIVATE_KEY")
        self.VAPID_CONTACT_EMAIL = self._valor(
            columna="vapid_contact_email", entorno="VAPID_CONTACT_EMAIL")

        # ── Panel ────────────────────────────────────────────────────
        # La clave del SERVIDOR, no de este negocio: los usuarios de cada
        # panel viven en `panel_users`. Esta solo abre la API de
        # `/admin/status` y la rampa del cliente por defecto mientras no
        # tenga usuarios (ver `acceso._rampa`).
        self.ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

        # ── Horario ──────────────────────────────────────────────────
        self.BUSINESS_TIMEZONE = self._valor(
            entorno="BUSINESS_TIMEZONE", seccion="horario", clave="zona")
        self.BUSINESS_HOURS_START = self._valor(
            entorno="BUSINESS_HOURS_START", seccion="horario", clave="inicio")
        self.BUSINESS_HOURS_END = self._valor(
            entorno="BUSINESS_HOURS_END", seccion="horario", clave="fin")
        self.BUSINESS_DAYS = self._texto("horario", "dias", [])

        # Con un mínimo: una duración de 0 hacía que el cálculo de horarios
        # (`calendar_service._slots_del_dia`) avanzara de cero en cero y no
        # terminara nunca, con un hilo al 100 % por cada "agendar".
        self.APPOINTMENT_DURATION_MINUTES = self._entero(self._valor(
            entorno="APPOINTMENT_DURATION_MINUTES",
            seccion="horario", clave="duracion_cita_min", defecto=60),
            60, minimo=5)
        self.APPOINTMENT_MIN_NOTICE_MINUTES = self._entero(self._valor(
            entorno="APPOINTMENT_MIN_NOTICE_MINUTES",
            seccion="horario", clave="anticipacion_min", defecto=60),
            60, minimo=0)
        self.APPOINTMENT_SEARCH_DAYS = self._entero(
            self._texto("horario", "dias_a_buscar", 21), 21, minimo=1, maximo=90)
        # Diez como techo: los horarios salen en una lista de WhatsApp, que
        # no admite más filas. Del undécimo en adelante no se verían.
        self.APPOINTMENT_SLOTS_OFFERED = self._entero(
            self._texto("horario", "horarios_ofrecidos", 10), 10,
            minimo=1, maximo=10)

        # Nombres en español: no dependemos del locale del sistema, que en
        # Windows y en los contenedores Linux no es el mismo. Con los de
        # siempre detrás: un negocio que nace en blanco no los trae, y sin
        # ellos formatear la fecha de una cita daba IndexError.
        self.DIAS_SEMANA = (self._texto("horario", "dias_semana", None)
                            or list(DIAS_POR_DEFECTO))
        self.MESES = self._texto("horario", "meses", None) or list(MESES_POR_DEFECTO)
        self.CALENDAR_EVENT_TITLE = self._texto("horario", "titulo_evento")

        # Lo calcula una vez para que `_rellenar` pueda usarlo.
        self._duracion_palabras = duracion_en_palabras(
            self.APPOINTMENT_DURATION_MINUTES)

        # ── Sheets ───────────────────────────────────────────────────
        self.SHEETS_TABS = n.get("sheets", {}).get("pestanas", {})
        self.SHEETS_DEFAULT_TABS = self._texto("sheets", "pestanas_por_defecto", [])

        # ── Conversación ─────────────────────────────────────────────
        self.CONVERSATION_TIMEOUT_HOURS = self._entero(self._valor(
            entorno="CONVERSATION_TIMEOUT_HOURS",
            seccion="conversacion", clave="caduca_horas", defecto=24),
            24, minimo=1)
        self.HUMAN_TAKEOVER_TIMEOUT_MINUTES = self._entero(self._valor(
            entorno="HUMAN_TAKEOVER_TIMEOUT_MINUTES",
            seccion="conversacion", clave="takeover_minutos", defecto=180),
            180, minimo=1)
        # ¿Le pregunta el nombre, o usa el que trae su WhatsApp?
        #
        # Preguntarlo es un mensaje más antes de vender, y la gente ya lo
        # tiene puesto en su perfil: Meta lo manda en cada webhook
        # (`contacts[0].profile.name`). Por defecto se pregunta, que es lo
        # que hacía siempre — cambiarlo en silencio le movería el primer
        # paso de la conversación a todos los negocios que ya funcionan.
        self.PEDIR_NOMBRE = self._texto("conversacion", "pedir_nombre", True)

        self.HUMAN_TAKEOVER_KEYWORDS = self._texto(
            "conversacion", "palabras_asesor", [])
        self.TAKEOVER_ON_OTHER_QUERY = self._texto(
            "conversacion", "takeover_en_otra_consulta", True)
        self.TAKEOVER_AFTER_APPOINTMENT = self._texto(
            "conversacion", "takeover_tras_cita", True)

        # Al pulsar "Pasar a una persona", ¿le pide que cuente su consulta
        # antes de avisar? Quien llega ahí ya recorrió el menú, así que
        # casi siempre se sabe lo que quiere y preguntárselo otra vez es
        # un mensaje redundante. En True por defecto porque es lo que hizo
        # siempre: cambiarlo en silencio le movería ese paso a todos los
        # negocios que ya funcionan.
        self.ASESOR_PIDE_DETALLE = self._texto(
            "conversacion", "asesor_pide_detalle", True) is not False

        # ¿Vuelve a enseñar el menú después del "no entendí"? Sin él, quien
        # no acertaba a escribir algo reconocible recibía la misma frase una
        # y otra vez, sin ningún botón que pulsar: parecía un bot trabado.
        self.MENU_TRAS_NO_ENTENDI = self._texto(
            "conversacion", "menu_tras_no_entendi", True) is not False

        # Lo que lo devuelve al menú principal en cualquier punto de la
        # conversación. Vacío = las de fábrica, igual que un texto vacío
        # dice el suyo en gris: un negocio nuevo nace en blanco y tiene
        # que poder salir de un callejón igual. Ver
        # `bot_logic._pide_volver_al_menu` para cómo se comparan.
        self.PALABRAS_MENU = (self._texto("conversacion", "palabras_menu", None)
                              or list(PALABRAS_MENU_POR_DEFECTO))

        # ── Datos de contacto ────────────────────────────────────────
        #
        # ⚠️  SIN DEFECTO, y es lo más importante de este bloque. Era
        # "573001234567": parece un marcador, pero es un número colombiano
        # con formato válido. Un negocio sin áreas y sin número del dueño le
        # mandaba ahí el nombre, el teléfono y la consulta de cada cliente.
        # Solo dígitos: "+57 300…" lo rechaza Meta sin decir por qué.
        self.OWNER_PHONE_NUMBER = "".join(
            c for c in str(self._valor(columna="owner_phone_number",
                                       entorno="OWNER_PHONE_NUMBER"))
            if c.isdigit())
        self.BUSINESS_EMAIL = self._valor(
            columna="business_email", entorno="BUSINESS_EMAIL",
            seccion="negocio", clave="email")
        self.BUSINESS_WEBSITE = self._valor(
            columna="business_website", entorno="BUSINESS_WEBSITE",
            seccion="negocio", clave="web")
        self.BUSINESS_WHATSAPP_NUMBER = self._valor(
            columna="business_whatsapp_number", entorno="BUSINESS_WHATSAPP_NUMBER",
            seccion="negocio", clave="whatsapp")
        self.WEB_BUTTON_LABEL = self._texto("negocio", "boton_web")

        # ── Marca ────────────────────────────────────────────────────
        self.APP_NOMBRE = self._valor(
            columna="app_nombre", entorno="APP_NOMBRE",
            seccion="marca", clave="app_nombre")
        self.APP_NOMBRE_CORTO = self._valor(
            columna="app_nombre_corto", entorno="APP_NOMBRE_CORTO",
            seccion="marca", clave="app_nombre_corto")
        self.MARCA_COLOR = self._valor(
            columna="marca_color", entorno="MARCA_COLOR",
            seccion="marca", clave="color")
        self.MARCA_COLOR_FONDO = self._valor(
            columna="marca_color_fondo", entorno="MARCA_COLOR_FONDO",
            seccion="marca", clave="color_fondo")

        # Quién hizo el bot. Es lo único que NO cambia de un cliente a
        # otro: la marca del panel es la del negocio, esto es la firma de
        # quien se lo montó.
        self.CREADO_POR = self._texto("marca", "creado_por", "Nitro 2Tech")

        # La imagen del negocio, guardada en la base (base64 o data URI).
        # Vive en la columna y no en un archivo del repositorio porque un
        # archivo del repositorio es del despliegue, o sea de todos: con dos
        # clientes, los dos tendrían el mismo icono. Ver `pwa._cargar_logo`.
        self.LOGO = self._valor(columna="logo")

        self.MARCA_RGB = ", ".join(str(v) for v in rgb_de(self.MARCA_COLOR))
        self.MARCA_TEXTO = color_legible_sobre(rgb_de(self.MARCA_COLOR))

        # Los nombres de app llevan "{negocio}" en el TOML.
        self.APP_NOMBRE = self._rellenar(self.APP_NOMBRE)
        self.APP_NOMBRE_CORTO = self._rellenar(self.APP_NOMBRE_CORTO)

        # ── Enlaces ──────────────────────────────────────────────────
        self.PRICING_URL = self._valor(
            entorno="PRICING_URL", seccion="enlaces", clave="precios")
        self.POWERBI_DEMO_URL = self._valor(
            entorno="POWERBI_DEMO_URL", seccion="enlaces", clave="powerbi_demo")
        self.WEB_DEMO_URL = self._valor(
            entorno="WEB_DEMO_URL", seccion="enlaces", clave="web_demo")
        self.AUTOMATIZACION_DEMO_URL = self._valor(
            entorno="AUTOMATIZACION_DEMO_URL",
            seccion="enlaces", clave="automatizacion_demo")

        # Los enlaces a los que una opción puede apuntar por nombre.
        #
        # Antes eran ESTOS CUATRO Y NINGUNO MÁS, escritos aquí a mano. Con
        # un negocio.toml que traía justo esos cuatro no se notaba; desde
        # que el contenido se edita desde el panel sí, y de la peor forma:
        # crear un enlace nuevo se aceptaba en la pantalla y luego el
        # guardado lo rechazaba con "pide el enlace X, que no está en
        # [enlaces]" — señalando la sección donde el enlace SÍ estaba.
        #
        # Ahora vale cualquiera que el negocio declare. Los cuatro de
        # siempre se mantienen encima porque además pueden venir por
        # variable de entorno, que gana sobre el contenido.
        self._enlaces = {
            nombre: self._rellenar(valor)
            for nombre, valor in (self._n.get("enlaces") or {}).items()
            if isinstance(valor, str)
        }
        self._enlaces.update({
            nombre: url for nombre, url in (
                ("precios", self.PRICING_URL),
                ("powerbi_demo", self.POWERBI_DEMO_URL),
                ("web_demo", self.WEB_DEMO_URL),
                ("automatizacion_demo", self.AUTOMATIZACION_DEMO_URL),
            ) if url
        })

        # ── Precios ──────────────────────────────────────────────────
        self.CHATBOT_PRICING_MESSAGE = self._rellenar(self._texto("precios", "chatbot"))
        self.POWERBI_PRICING_MESSAGE = self._rellenar(self._texto("precios", "powerbi"))
        self.WEB_PRICING_MESSAGE = self._rellenar(self._texto("precios", "web"))
        self.AUTOMATIZACION_PRICING_MESSAGE = self._rellenar(
            self._texto("precios", "automatizacion"))

        # Los bloques de precios a los que una opcion puede apuntar por
        # nombre. Mismo caso que `_enlaces`: eran CUATRO NOMBRES FIJOS
        # escritos aqui, asi que un negocio no podia crear el suyo desde
        # el panel — se aceptaba en la pantalla y lo rechazaba el
        # guardado. Ahora vale cualquiera que el negocio declare.
        self._precios = {
            nombre: self._rellenar(valor)
            for nombre, valor in (self._n.get("precios") or {}).items()
            if isinstance(valor, str)
        }
        self._precios.update({
            nombre: texto for nombre, texto in (
                ("chatbot", self.CHATBOT_PRICING_MESSAGE),
                ("powerbi", self.POWERBI_PRICING_MESSAGE),
                ("web", self.WEB_PRICING_MESSAGE),
                ("automatizacion", self.AUTOMATIZACION_PRICING_MESSAGE),
            ) if texto
        })

        # ── Orígenes ─────────────────────────────────────────────────
        self.ORIGENES = {clave: self._rellenar(datos)
                         for clave, datos in n.get("origenes", {}).items()}
        self.ORIGEN_POR_DEFECTO = self._texto(
            "origenes_ajustes", "por_defecto", "directo")
        self.ORIGEN_BOTON_WEB = self._texto("origenes_ajustes", "boton_web", "web")

        # ── Menú ─────────────────────────────────────────────────────
        self.NEED_OPTIONS = [self._opcion(o) for o in n.get("menu", [])]

        # Lo que contesta un negocio al que todavía no le armaron el menú.
        # Un negocio nuevo nace en blanco (ver `superadmin.alta`), y entre
        # que se crea y se termina de armar puede escribirle un cliente
        # real. Antes que el silencio o un error, esto.
        self.SIN_CONTENIDO_MESSAGE = self._rellenar(
            self._texto_del_bot("sin_configurar"))
        self.NEED_LIST_BUTTON = self._texto_del_bot("menu_boton")
        self.NEED_LIST_SECTION = self._texto_del_bot("menu_seccion")
        self.BOTON_VOLVER_MENU = self._texto_del_bot("boton_volver_menu")
        self.BOTON_ATRAS = self._texto_del_bot("boton_atras")
        self.CIERRE_OPTIONS = [self._opcion(o) for o in n.get("cierre", [])]

        # ── Textos ───────────────────────────────────────────────────
        for atributo, clave in (
            ("WELCOME_MESSAGE", "bienvenida"),
            ("WELCOME_BACK_MESSAGE", "bienvenida_de_vuelta"),
            ("ASK_NEED_MESSAGE", "preguntar_necesidad"),
            ("CIERRE_MESSAGE", "cierre"),
            ("DESPEDIDA_MESSAGE", "despedida"),
            ("WEBSITE_MESSAGE", "enlace_web"),
            ("OTHER_QUERY_MESSAGE", "otra_consulta"),
            ("HUMAN_HANDOFF_CONFIRMATION", "paso_a_asesor"),
            ("FALLBACK_MESSAGE", "no_entendi"),
            ("NO_ENTENDI_MENU_MESSAGE", "no_entendi_menu"),
            ("HUMAN_TAKEOVER_MESSAGE", "aviso_asesor"),
            ("ASESOR_DIRECTO_MESSAGE", "asesor_directo"),
            ("MEDIA_RECIBIDA_IMAGEN", "media_imagen"),
            ("MEDIA_RECIBIDA_AUDIO", "media_audio"),
            ("MEDIA_RECIBIDA_DOCUMENTO", "media_documento"),
            ("MEDIA_RECIBIDA_OTRO", "media_otro"),
            ("ASK_APPOINTMENT_DATE_MESSAGE", "cita_preguntar_dia"),
            ("ASK_APPOINTMENT_TIME_MESSAGE", "cita_preguntar_hora"),
            ("APPOINTMENT_CONFIRMATION_MESSAGE", "cita_confirmada"),
            ("APPOINTMENT_SLOT_TAKEN_MESSAGE", "cita_horario_tomado"),
            ("APPOINTMENT_NO_SLOTS_MESSAGE", "cita_dia_lleno"),
            ("APPOINTMENT_NO_AVAILABILITY_MESSAGE", "cita_sin_disponibilidad"),
            ("APPOINTMENT_FALLBACK_MESSAGE", "cita_respaldo"),
            ("CITA_CANCELADA_MESSAGE", "cita_cancelada"),
            ("CITA_REAGENDAR_MESSAGE", "cita_reagendar"),
            ("CITA_NO_ENCONTRADA_MESSAGE", "cita_no_encontrada"),
        ):
            setattr(self, atributo, self._rellenar(self._texto_del_bot(clave)))

        # Los que NO llevan relleno: son etiquetas de botón con tope de
        # caracteres, no frases.
        self.APPOINTMENT_DAYS_BUTTON = self._texto_del_bot("cita_boton_dias")
        self.APPOINTMENT_DAYS_SECTION = self._texto_del_bot("cita_seccion_dias")
        self.APPOINTMENT_DAY_DESCRIPTION = self._texto_del_bot("cita_dia_descripcion")
        self.APPOINTMENT_TIMES_BUTTON = self._texto_del_bot("cita_boton_horarios")
        self.APPOINTMENT_TIMES_SECTION = self._texto_del_bot("cita_seccion_horarios")

        # WhatsApp corta el título a 20 caracteres sin avisar, así que se
        # recorta aquí para que al menos se vea entero lo que quepa.
        self.MEDIA_BOTON_MENU = self._texto_del_bot("media_boton_menu")[:20]
        self.MEDIA_BOTON_ASESOR = self._texto_del_bot("media_boton_asesor")[:20]
        self.MEDIA_DETALLE_ASESOR = self._texto_del_bot("media_detalle_asesor")

        # ── Avisos al dueño ──────────────────────────────────────────
        #
        # La plantilla con la que se avisa al dueño fuera de la ventana de
        # 24 h. Tiene que poder salir del contenido del negocio: en cuanto
        # un cliente tiene `negocio_config` deja de leer el entorno (ver
        # `_env`), y hasta que esto estuvo en `[avisos]` no había ninguna
        # forma de dársela — sus leads se perdían en silencio pasado un
        # día, que es justo lo que `notificaciones.py` viene a evitar.
        self.OWNER_TEMPLATE_NAME = self._valor(
            entorno="OWNER_TEMPLATE_NAME", seccion="avisos", clave="plantilla")
        self.OWNER_TEMPLATE_LANG = self._valor(
            entorno="OWNER_TEMPLATE_LANG", seccion="avisos",
            clave="plantilla_idioma", defecto="es")

        for atributo, clave in (
            ("OWNER_NOTIFICATION_APPOINTMENT", "cita"),
            ("OWNER_NOTIFICATION_OTHER", "consulta"),
            ("OWNER_NOTIFICATION_TAKEOVER", "pide_asesor"),
            ("OWNER_NOTIFICATION_CANCELACION", "cancelacion"),
            ("OWNER_NOTIFICATION_REAGENDA", "reagenda"),
        ):
            setattr(self, atributo, self._rellenar(self._texto("avisos", clave)))

        # El plan comercial: qué compró. Ver `app/core/planes.py`.
        from app.core import planes
        self.PLAN = planes.codigo_de(self._fila)

        # El cupo antes que la lista, porque la lista se recorta con él.
        self.MAX_DESTINOS_AVISOS = cupo_de_destinos(self._fila)
        self.AVISOS_DESTINOS = self._leer_destinos(
            (n.get("avisos") or {}).get("destinos"))

        # A dónde le llegan al DUEÑO los avisos por correo: lo que no es de
        # ningún área, y todo en el plan Básico, que no tiene áreas.
        correo_dueno = str((n.get("avisos") or {}).get("correo_dueno") or "").strip()
        self.AVISOS_CORREO_DUENO = correo_dueno if "@" in correo_dueno else ""

        # ── IA ───────────────────────────────────────────────────────
        #
        # ¿COMPRÓ el paquete? Es lo comercial, y va antes que todo lo
        # demás: en False, `cerebro.plan_activo()` devuelve siempre Básico
        # y el dueño no ve el interruptor en su panel.
        #
        # Hasta ahora la única puerta era "¿hay clave de Gemini?", y esa no
        # es la pregunta: la clave la ponemos NOSOTROS y es la misma para
        # todos, así que cualquier cliente podía encenderla desde su panel
        # y cargarnos el consumo sin haberla pagado.
        #
        # Mismo patrón que `ia_activa`, y por la misma razón: la variable
        # de entorno solo la ve un cliente SIN configuración propia — o
        # sea, la configuración base de los scripts y las pruebas. En
        # cuanto un negocio tiene la suya, esto es su columna y nada más.
        # Con el entorno mandando sobre la columna, poner IA_CONTRATADA en
        # Render se la regalaría a todos.
        # Desde el 23-sep-2026 lo decide el PLAN: Pro y Premium la traen,
        # Básico no (`app/core/planes.py`). Un negocio sin fila —la
        # configuración base de los scripts y las pruebas— sigue leyendo
        # la variable de entorno.
        if self._fila:
            contratada = planes.de(self._fila).ia
        else:
            contratada = (os.getenv("IA_CONTRATADA", "false").lower() == "true"
                          if self._usar_entorno else False)
        self.IA_CONTRATADA = bool(contratada)

        ia_activa = self._fila.get("ia_activa")
        if ia_activa is None:
            ia_activa = (os.getenv("IA_ACTIVA", "false").lower() == "true"
                         if self._usar_entorno else False)
        self.IA_ACTIVA = bool(ia_activa)

        self.GEMINI_API_KEY = self._secreto("gemini_api_key", "GEMINI_API_KEY")
        self.GEMINI_MODELO = self._valor(
            columna="gemini_modelo", entorno="GEMINI_MODELO",
            defecto="gemini-3.1-flash-lite")

        self.IA_MAX_MENSAJES_DIA = self._entero(self._valor(
            entorno="IA_MAX_MENSAJES_DIA", defecto=40), 40)

        # Tope MENSUAL por cliente: lo que hace seguro vender un plan de
        # precio fijo. 0 = sin tope.
        self.IA_LIMITE_MENSUAL = self._entero(
            self._fila.get("ia_limite_mensual") or 0, 0, minimo=0)

        self.IA_ROL = self._rellenar(self._texto("ia", "rol"))
        self.IA_TONO = self._texto("ia", "tono")
        self.IA_NUNCA = self._texto("ia", "nunca", [])
        self.IA_SIEMPRE_DERIVAR = self._texto("ia", "siempre_derivar", [])
        self.IA_MAX_PALABRAS = self._entero(
            self._texto("ia", "max_palabras", 60), 60, minimo=5)

        # ── Identidad del inquilino ──────────────────────────────────
        self.CLIENT_ID = self._fila.get("id")
        self.CLIENT_SLUG = self._fila.get("slug")
        self.CLIENT_ACTIVE = bool(self._fila.get("active", True))

        # ── Caché de archivos, separado por cliente ──────────────────
        # Una carpeta por inquilino y no una común: los nombres de archivo
        # salen del media_id de Meta, que es único, así que no habría
        # choques — pero el tope de MB del caché sí es común, y con una
        # sola carpeta el cliente que más archivos recibe le borraría el
        # caché a los demás.
        #
        # Sin `CLIENT_ID` se usa el del cliente por defecto, NO la carpeta
        # raíz. Es importante: si no, el mismo archivo caería en dos rutas
        # distintas según si hay inquilino fijado o no, y el caché que
        # escribe una petición del panel no lo encontraría un script.
        self.MEDIA_DIR = os.path.join(
            carpeta_media_base(), str(self.CLIENT_ID or CLIENTE_POR_DEFECTO))

    # ── Menú: resolución de referencias por nombre ───────────────────

    def _opcion(self, fila: dict) -> dict:
        """
        Una fila del menú, tal y como la espera bot_logic.

        Traduce las dos referencias por nombre que usa el TOML —para no
        repetir una URL o un texto de precios largo en cada opción— a los
        valores que el resto del código ya leía:

            enlace  = "precios"   →  "url":     PRICING_URL
            precios = "chatbot"   →  "mensaje": CHATBOT_PRICING_MESSAGE
        """
        o = {k: self._rellenar(v) for k, v in fila.items()
             if k not in ("enlace", "precios", "submenu")}

        # ── Los punteros a lo compartido ─────────────────────────────
        #
        # `enlace` y `precios` no son datos de la opción: son el nombre de
        # algo que vive en otra sección y que varias opciones pueden
        # compartir. Están bien para escribir un TOML a mano.
        #
        #     ⚠️  Y LO PROPIO DE LA OPCIÓN GANA SOBRE ELLOS.
        #
        # Eso último es lo que costó una tarde. Antes el puntero
        # sobrescribía siempre, así que una opción que tuviera su propio
        # `mensaje` Y un `precios` heredado mandaba el bloque compartido:
        # el dueño cambió sus precios desde el panel, se guardaron, y el
        # bot siguió diciendo los viejos. El cambio estaba en la base y no
        # se usaba.
        #
        # Ahora el puntero solo rellena lo que la opción no diga por sí
        # misma, que es lo que cualquiera espera al escribir un texto
        # encima. Los TOML de siempre no cambian: sus opciones con
        # `precios` no traen `mensaje` propio.
        if "enlace" in fila:
            nombre = fila["enlace"]
            if nombre not in self._enlaces:
                raise ValueError(
                    f"negocio.toml: la opción '{fila.get('id')}' pide el enlace "
                    f"'{nombre}', que no está en [enlaces].")
            if not o.get("url"):
                o["url"] = self._enlaces[nombre]

        if "precios" in fila:
            nombre = fila["precios"]
            if nombre not in self._precios:
                raise ValueError(
                    f"negocio.toml: la opción '{fila.get('id')}' pide los precios "
                    f"'{nombre}', que no están en [precios].")
            if not o.get("mensaje"):
                o["mensaje"] = self._precios[nombre]

        if "submenu" in fila:
            o["submenu"] = [self._opcion(s) for s in fila["submenu"]]

        return o

    # ── Derivados que el resto del código pide como función ──────────

    def enlace(self, url: str) -> str:
        """Devuelve el enlace, o la web principal si está vacío."""
        return url or self.BUSINESS_WEBSITE

    def nombre_servicio(self, opcion_id: str) -> str:
        """
        El nombre legible de un servicio a partir del id que se guarda en
        el contacto ("opt_powerbi" → "Tablero en Power BI").

        Cadena vacía si el contacto no eligió servicio, o si el id ya no
        existe porque se renombró la opción.
        """
        if not opcion_id:
            return ""
        for opcion in self.NEED_OPTIONS:
            if opcion["id"] == opcion_id:
                return opcion["title"]
        return ""

    def plazo_takeover(self) -> str:
        """
        El plazo en palabras, para los textos del panel: "3 horas" en vez
        de "180 minutos", que nadie divide mentalmente.
        """
        minutos = self.HUMAN_TAKEOVER_TIMEOUT_MINUTES
        if minutos < 60:
            return f"{minutos} minutos"

        horas = minutos / 60
        if horas != int(horas):
            return f"{horas:.1f} horas".replace(".", ",")

        horas = int(horas)
        return "1 hora" if horas == 1 else f"{horas} horas"

    def iniciales_marca(self) -> str:
        """
        Las iniciales que se dibujan en el icono cuando el negocio no puso
        su logo. "Nitro 2Tech" → "N2".
        """
        palabras = [p for p in self.BUSINESS_NAME.split() if p]
        if not palabras:
            return "?"
        if len(palabras) == 1:
            return palabras[0][:2].upper()
        return (palabras[0][0] + palabras[1][0]).upper()


# ══════════════════════════════════════════════════════════════════════
#  EL VOCABULARIO DEL BOT
# ══════════════════════════════════════════════════════════════════════
#
# Lo que dice cualquier bot, diga lo que diga el negocio: cómo saluda, qué
# contesta cuando no entiende, cómo se despide, qué pone en la etiqueta de
# una lista. Un negocio nace en blanco y no tiene por qué escribir esto
# antes de poder atender a nadie.
#
#     No es una plantilla de negocio. Aquí no hay servicios, ni precios,
#     ni horarios: de eso trata el mapa, y de eso el negocio empieza vacío.
#
# Se sobrescriben desde el editor, uno a uno. Los huecos entre llaves los
# rellena el bot en cada conversación ({name}, {url}) o la configuración
# ({negocio}); ver `ConfiguracionCliente._rellenar`.
#
# Las etiquetas de botón se quedan cortas a propósito: WhatsApp corta a 20
# caracteres el botón y a 24 el título de una lista, sin avisar.
# Frases que devuelven al menú principal en cualquier momento. Son frases
# y no la palabra "menú" suelta a propósito: Nitro vende chatbots, y "quiero
# cambiar el menú de mi restaurante" es una consulta de venta, no una orden
# de volver. Una palabra sola SÍ vale cuando es todo lo que escribe
# ("menú", "inicio"). Ver `bot_logic._pide_volver_al_menu`.
DIAS_POR_DEFECTO = ("lunes", "martes", "miércoles", "jueves", "viernes",
                    "sábado", "domingo")
MESES_POR_DEFECTO = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
                     "julio", "agosto", "septiembre", "octubre", "noviembre",
                     "diciembre")

PALABRAS_MENU_POR_DEFECTO = (
    "menú", "inicio", "volver al menú", "menú principal", "ver el menú",
    "ir al menú", "mostrar el menú", "muéstrame el menú", "volver al inicio",
    "empezar de nuevo", "volver a empezar", "regresar al menú",
)

TEXTOS_POR_DEFECTO = {
    "bienvenida": "¡Hola! 👋 Bienvenido/a a {negocio}.\n"
                  "Para atenderte mejor, cuéntame tu nombre:",
    "bienvenida_de_vuelta": "¡Hola de nuevo, {name}! ¿En qué te ayudo?",
    "preguntar_necesidad": "Cuéntame, {name}: ¿qué necesitas?",
    "cierre": "¿Necesitas algo más?",
    "despedida": "¡Gracias por escribir a {negocio}! Aquí estamos cuando "
                 "nos necesites. 👋",
    "no_entendi": "No estoy seguro de haber entendido. ¿Me lo dices de "
                  "otra forma, o eliges una opción del menú?",
    # Va pegado al "no entendí", encima del menú que se le vuelve a
    # enseñar. Ver `bot_logic._no_entendi`.
    "no_entendi_menu": "¿Con qué quieres continuar?",
    "otra_consulta": "Claro, cuéntame con tus palabras qué necesitas y "
                     "se lo paso a una persona del equipo.",
    "paso_a_asesor": "Listo, {name}: ya avisé a una persona del equipo. "
                     "Te escriben en breve.",
    # Lo que dice al pulsar "Pasar a una persona" cuando el negocio NO
    # quiere que le pida contar su consulta otra vez.
    "asesor_directo": "Listo, {name} 🙌 En unos momentos un asesor se "
                      "contactará contigo por aquí mismo.",
    "aviso_asesor": "Te estoy conectando con una persona del equipo.",
    "enlace_web": "Aquí lo tienes: {url}",

    # Etiquetas: cortas por obligación, no por estilo.
    "menu_boton": "Ver opciones",
    "menu_seccion": "¿Qué necesitas?",

    # Las dos salidas que se pueden ofrecer DESPUÉS de cualquier
    # respuesta ("y le vuelve a ofrecer…"). Existen siempre, las tenga
    # el negocio escritas o no: son la forma de que un cliente no se
    # quede en un callejón sin salida. Ver `bot_logic.OPCIONES_FIJAS`.
    "boton_volver_menu": "Menú principal",
    "boton_atras": "Atrás",

    # Archivos que manda el cliente. El bot no los entiende, pero tiene
    # que decir algo: el silencio ante una foto parece una caída.
    "media_imagen": "¡Gracias por la foto! Ya la tengo. 📸",
    "media_audio": "¡Gracias por la nota de voz! Ya la escuchamos. 🎤",
    "media_documento": "¡Gracias por el archivo! Ya lo tengo. 📄",
    "media_otro": "¡Gracias! Ya lo recibí.",
    "media_boton_menu": "Ver el menú",
    "media_boton_asesor": "Hablar con alguien",
    "media_detalle_asesor": "Mandó un archivo y pidió hablar con una persona.",

    # Citas. Solo se usan si el negocio ofrece agendar, pero si lo ofrece
    # sin escribir esto, mandaría mensajes vacíos en mitad del agendado.
    "cita_preguntar_dia": "¿Qué día te viene bien?",
    "cita_boton_dias": "Ver días",
    "cita_seccion_dias": "Días disponibles",
    "cita_dia_descripcion": "Toca para ver los horarios",
    "cita_preguntar_hora": "¿A qué hora?",
    "cita_boton_horarios": "Ver horarios",
    "cita_seccion_horarios": "Horarios libres",
    "cita_confirmada": "¡Listo, {name}! Quedaste para el {date} a las "
                       "{time}. Te esperamos. 📅",
    "cita_horario_tomado": "Justo se ocupó ese horario. ¿Elegimos otro?",
    "cita_dia_lleno": "Ese día se llenó. ¿Probamos con otro?",
    "cita_sin_disponibilidad": "No me quedan horarios libres por ahora. "
                               "Te contacta una persona del equipo.",
    "cita_respaldo": "Anoté tu solicitud, {name}. Te confirmamos el "
                     "horario en un momento.",
    "cita_cancelada": "Listo, cancelé tu cita. Cuando quieras agendamos otra.",
    "cita_reagendar": "Vale, busquemos otro día.",
    "cita_no_encontrada": "No encuentro una cita tuya activa. "
                          "¿Agendamos una?",

    # Y el que aparece cuando todavía no hay menú que ofrecer.
    "sin_configurar": "¡Hola! Gracias por escribir a {negocio}. "
                      "En un momento te atendemos.",
}
