"""
QUIÉN ES EL INQUILINO DE ESTA PETICIÓN
=======================================
Un solo proceso atiende a varios negocios. Este módulo responde, en
cualquier punto del código, a la pregunta "¿de qué cliente es lo que estoy
atendiendo ahora mismo?".

CÓMO SE AVERIGUA
----------------
Hay dos puertas de entrada y cada una lo resuelve a su manera:

  webhook  →  la URL: /webhook/{webhook_token} (`por_webhook_token`). El
              `phone_number_id` del mensaje ya solo CONFIRMA. La puerta
              vieja, /webhook a secas, todavía decide por él mientras se
              migra el bot de casa.
  panel    →  con `DOMINIO_BASE`, el subdominio del `Host`
              (panaderia.tudominio.com → "panaderia"); sin él, el pase
              firmado de la cookie de sesión (ver `app/main.py`).

Son caminos distintos hacia el mismo `client_id`, y está bien que lo sean:
el webhook lo dice Meta y el panel lo dice el navegador.

CÓMO VIAJA
----------
En un `ContextVar`, no en un parámetro. La alternativa era pasar el
inquilino por argumento a través de las 247 lecturas de configuración y
del millar de líneas de `bot_logic`, y eso es una reescritura del proyecto
entero con una oportunidad de equivocarse en cada firma.

Un ContextVar viaja solo por todo lo que cuelga de una petición, incluido
el salto a `run_in_threadpool` que hace el webhook (comprobado: anyio
copia el contexto al hilo).

    ⚠️  DOS SITIOS DONDE **NO** VIAJA SOLO.

    - `ThreadPoolExecutor.submit()` (el `_ejecutor` de gemini.py)
    - `threading.Thread(...)` a pelo (el hilo de push.py)

    En los dos hay que copiar el contexto a mano. Para eso está
    `envolver_para_hilo()`, que es lo que deben usar. Si algún día se
    agrega otro hilo y se olvida, el síntoma es `SinInquilino` — ruidoso,
    que es justo lo que se quiere. Lo que NUNCA debe pasar es que caiga en
    silencio sobre otro cliente.

POR QUÉ NO HAY UN VALOR POR DEFECTO
-----------------------------------
`actual()` levanta excepción si nadie fijó el inquilino, en vez de
devolver el cliente 1. Un valor por defecto convierte "se me olvidó
resolver el inquilino" en "le escribí al cliente equivocado", que es un
fallo que no se ve hasta que alguien se queja.

La única excepción es deliberada y explícita: sin sesión y sin
`DOMINIO_BASE`, el middleware atiende con el cliente por defecto, que es
de quien es la pantalla de entrada. Sin pase no se llega a ninguna
pantalla con datos. Ver `main._inquilino_del_pase`.
"""

import contextvars
import os
import time

from app.core.database import CLIENTE_POR_DEFECTO, Client, SessionLocal

# El inquilino de la petición en curso. Sin valor por defecto a propósito.
_inquilino = contextvars.ContextVar("inquilino")


class SinInquilino(Exception):
    """
    Se pidió el inquilino y nadie lo había fijado.

    Es un error de programación, no un estado posible: significa que hay
    un camino de entrada que no pasa por `usar()`, o un hilo nuevo que no
    copió el contexto.
    """


class InquilinoDesconocido(Exception):
    """El `phone_number_id` o el subdominio no corresponden a ningún cliente."""


# ── Fijar y leer ─────────────────────────────────────────────────────

class usar:
    """
    Marca de quién es todo lo que ocurra dentro del bloque.

        with tenencia.usar(cliente_id):
            bot_logic.handle_incoming_message(...)

    Es un gestor de contexto y no una función suelta porque el token de
    reposición hay que devolverlo sí o sí: sin eso, en un servidor que
    reutiliza hilos, el inquilino de una petición se quedaría puesto para
    la siguiente.
    """

    def __init__(self, client_id: int):
        self.client_id = client_id
        self._token = None

    def __enter__(self):
        self._token = _inquilino.set(self.client_id)
        return self.client_id

    def __exit__(self, *_):
        _inquilino.reset(self._token)
        return False


class sin_inquilino(usar):
    """
    Lo contrario de `usar`: dentro del bloque NO hay inquilino, aunque la
    petición traiga uno puesto.

        with tenencia.sin_inquilino():
            ... una consulta que tiene que mirar a TODOS los negocios

    Hace falta muy poco, y cuando hace falta no hay otra forma. El caso que
    lo trajo: entrar al panel con un nombre de usuario, que es único en
    toda la plataforma y no dice de qué negocio es. El middleware ya dejó
    puesto el cliente por defecto, así que buscarlo "en todos" con un
    `filter_by` volvía solo los del cliente 1 — y los de los demás negocios
    se quedaban fuera diciendo "clave incorrecta". Sin ningún error.

    ⚠️  Todo lo que se haga dentro ve a todos los clientes. Úsalo para
    LEER lo que tiene que ser global y sal en cuanto sepas de quién es; lo
    que se escriba después va con `usar(ese_id)`.
    """

    def __init__(self):
        super().__init__(None)


def actual() -> int:
    """El id del inquilino en curso. Levanta `SinInquilino` si no hay."""
    try:
        valor = _inquilino.get()
        if valor is None:        # dentro de `sin_inquilino()`
            raise LookupError
        return valor
    except LookupError as e:
        raise SinInquilino(
            "No hay inquilino fijado para esta operación. Toda entrada al "
            "sistema (webhook, panel, script) tiene que envolverse en "
            "`with tenencia.usar(client_id):`, y todo hilo nuevo tiene que "
            "copiar el contexto con `envolver_para_hilo()`.") from e


def actual_o_none() -> int | None:
    """Como `actual()`, pero devuelve None en vez de fallar."""
    try:
        return _inquilino.get()
    except LookupError:
        return None


def envolver_para_hilo(funcion):
    """
    Prepara una función para que se ejecute en OTRO hilo sin perder el
    inquilino.

    `ThreadPoolExecutor.submit` y `threading.Thread` arrancan con un
    contexto vacío: lo que se fijó en la petición no llega. Esto captura el
    contexto actual y lo reproduce dentro del hilo.

    Se llama desde el hilo que SÍ tiene el inquilino puesto (el que lanza),
    nunca desde dentro del hilo nuevo.
    """
    contexto = contextvars.copy_context()

    def dentro_del_hilo(*args, **kwargs):
        return contexto.run(funcion, *args, **kwargs)

    return dentro_del_hilo


# ── Resolución ───────────────────────────────────────────────────────
#
# El webhook consulta esto una vez por mensaje, así que va con caché. El
# plazo es corto a propósito: pausar a un cliente que no paga tiene que
# surtir efecto en un minuto, no cuando se reinicie el servicio. Las
# escrituras del panel invalidan la entrada a mano con `olvidar()`.

CACHE_SEGUNDOS = 60

_cache: dict = {}          # clave -> (momento, datos)


class DatosCliente:
    """
    Una foto de la fila de `clients`, desligada de la sesión que la leyó.

    Se copia a un objeto plano en vez de guardar la instancia del ORM: una
    instancia queda atada a su sesión, y al cerrarla cualquier atributo que
    no se hubiera leído explota con DetachedInstanceError — dentro del
    webhook y meses después de escribir el caché.
    """

    __slots__ = ("id", "slug", "nombre", "active", "phone_number_id",
                 "webhook_token", "fila")

    def __init__(self, fila: Client):
        self.id = fila.id
        self.slug = fila.slug
        self.nombre = fila.nombre
        self.active = fila.active
        self.phone_number_id = fila.phone_number_id
        self.webhook_token = fila.webhook_token
        # El resto de campos, para que `config` los use sin volver a la
        # base. Un dict y no el objeto, por lo mismo de arriba.
        self.fila = {c.name: getattr(fila, c.name)
                     for c in Client.__table__.columns}


def _del_cache(clave):
    guardado = _cache.get(clave)
    if not guardado:
        return None
    momento, datos = guardado
    if time.time() - momento > CACHE_SEGUNDOS:
        _cache.pop(clave, None)
        return None
    return datos


def _guardar(datos: DatosCliente):
    ahora = time.time()
    _cache[("id", datos.id)] = (ahora, datos)
    _cache[("slug", datos.slug)] = (ahora, datos)
    if datos.phone_number_id:
        _cache[("pnid", datos.phone_number_id)] = (ahora, datos)
    if datos.webhook_token:
        _cache[("webhook", datos.webhook_token)] = (ahora, datos)
    return datos


def olvidar(client_id: int = None):
    """
    Tira el caché. Sin argumento, entero.

    Hay que llamarlo tras cambiar algo de un cliente en el panel o al
    pausarlo, o el cambio tardaría hasta un minuto en verse.
    """
    if client_id is None:
        _cache.clear()
        return

    datos = _del_cache(("id", client_id))
    if datos:
        _cache.pop(("slug", datos.slug), None)
        _cache.pop(("pnid", datos.phone_number_id), None)
        _cache.pop(("webhook", datos.webhook_token), None)
    _cache.pop(("id", client_id), None)


def _buscar(clave, filtro) -> DatosCliente | None:
    guardado = _del_cache(clave)
    if guardado is not None:
        return guardado

    session = SessionLocal()
    try:
        fila = session.query(Client).filter_by(**filtro).first()
        return _guardar(DatosCliente(fila)) if fila else None
    finally:
        session.close()


def por_id(client_id: int) -> DatosCliente | None:
    return _buscar(("id", client_id), {"id": client_id})


def por_phone_number_id(phone_number_id: str) -> DatosCliente | None:
    """
    De qué negocio es el número por el que entró el mensaje.

    Es la resolución del webhook, y corre una vez por cada mensaje que
    llega, así que va por caché.
    """
    if not phone_number_id:
        return None
    return _buscar(("pnid", phone_number_id),
                   {"phone_number_id": phone_number_id})


def por_webhook_token(token: str) -> DatosCliente | None:
    """
    De qué negocio es la URL de webhook por la que entró este POST.

    ES LA PRIMERA RESOLUCIÓN DEL WEBHOOK, y va antes que
    `por_phone_number_id` a propósito.

    Cada cliente trae su propia App de Meta, así que la firma
    (`X-Hub-Signature-256`) se valida con SU App Secret. Para saber con
    cuál hay que saber primero de quién es el mensaje — y lo único que lo
    diría dentro del cuerpo es el `phone_number_id`, que es justo lo que
    todavía no se puede dar por auténtico. Leerlo para decidir con qué
    secreto comprobar la autenticidad es comprobar la autenticidad con un
    dato del propio sospechoso.

    Con el inquilino en la URL, el orden queda bien: se sabe de quién es
    antes de tocar el cuerpo, se valida la firma, y solo entonces se
    parsea. El `phone_number_id` del payload se sigue mirando después,
    pero ya como CONFIRMACIÓN (ver `app/main.py`).

    Corre una vez por mensaje entrante, así que va por caché igual que la
    otra.
    """
    if not token:
        return None
    return _buscar(("webhook", token), {"webhook_token": token})


def por_slug(slug: str) -> DatosCliente | None:
    if not slug:
        return None
    return _buscar(("slug", slug), {"slug": slug})


# ── Resolución por dominio (el panel) ────────────────────────────────

def dominio_base() -> str:
    """
    El dominio bajo el que cuelgan los subdominios de los clientes.

    Mientras esté vacío, el panel trabaja en modo de UN SOLO INQUILINO y
    todo se atribuye al cliente por defecto. Es la única puerta trasera del
    sistema, y es deliberada: permite que el bot siga funcionando como
    siempre mientras se termina la migración.

    En cuanto se define, la resolución pasa a ser estricta y un subdominio
    desconocido es un error, no un cliente 1 silencioso.
    """
    return (os.getenv("DOMINIO_BASE") or "").strip().lower()


def slug_de_host(host: str) -> str | None:
    """
    "panaderia.tudominio.com" → "panaderia". None si no cuelga del dominio
    base o si es el dominio pelado.
    """
    base = dominio_base()
    if not base or not host:
        return None

    host = host.split(":")[0].strip().lower()      # fuera el puerto
    if not host.endswith("." + base):
        return None

    subdominio = host[: -(len(base) + 1)]
    # "www.tudominio.com" no es un cliente, y un subdominio con puntos
    # (a.b.tudominio.com) tampoco: los slugs son de un solo nivel.
    if not subdominio or "." in subdominio or subdominio == "www":
        return None

    return subdominio


def resolver_por_host(host: str) -> DatosCliente:
    """
    El cliente al que le corresponde este `Host`.

    Levanta `InquilinoDesconocido` si el subdominio no existe o si el
    cliente está pausado — que desde fuera se ven igual a propósito: no
    hay por qué contarle a internet qué negocios son clientes nuestros ni
    cuáles dejaron de pagar.
    """
    if not dominio_base():
        # Modo de un solo inquilino. Ver `dominio_base`.
        datos = por_id(CLIENTE_POR_DEFECTO)
        if datos is None:
            raise InquilinoDesconocido(
                "No existe el cliente por defecto. ¿Corrió `init_db`?")
        return datos

    slug = slug_de_host(host)
    datos = por_slug(slug) if slug else None
    if datos is None or not datos.active:
        raise InquilinoDesconocido(f"Sin cliente activo para el host {host!r}.")
    return datos
