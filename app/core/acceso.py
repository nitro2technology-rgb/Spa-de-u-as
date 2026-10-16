"""
QUIÉN PUEDE ENTRAR AL PANEL
============================
Dos cosas, que antes eran una sola y no debían serlo:

  1. **Autenticar** — comprobar la clave contra `panel_users`, la tabla de
     usuarios de cada negocio.
  2. **Firmar el pase** — la cookie de sesión que dice "este navegador ya
     entró, y entró al panel del cliente 7".

    ⚠️  ANTES ESTO ERA UN SOLO SECRETO HACIENDO TRES TRABAJOS.

`ADMIN_API_KEY` era a la vez la contraseña del panel, la clave que firmaba
la cookie y la clave de la API de administración. Con un solo negocio era
un atajo. Con varios era una fuga: la cookie no decía de qué negocio era
—llevaba dos fechas y una firma, nada más— así que un pase emitido para el
cliente A valía, criptográficamente, para el panel del cliente B.

CÓMO QUEDÓ
----------
    pase = "p2:client_id:user_id:vence_absoluto:vence_inactividad:firma"

El pase lleva **de quién es**, y `leer_pase` exige que ese `client_id`
coincida con el inquilino de la petición. Una cookie del cliente A
presentada en el subdominio del cliente B se rechaza aunque la firma sea
buena y aunque los plazos estén vigentes.

Y la firma ya NO usa la contraseña de nadie: usa un secreto del servidor
(ver `secreto_de_firma`), que es de la instalación y no de un cliente.

LA RAMPA DE MIGRACIÓN
---------------------
Mientras un negocio no tenga usuarios en `panel_users`, el dueño del bot
—y **solo** él, el cliente por defecto— puede seguir entrando con
`ADMIN_API_KEY`, igual que siempre. Para cualquier otro cliente, sin
usuario no hay panel: si la rampa valiera para todos, la clave del dueño
abriría el panel de todos sus clientes.

Se crean con `python scripts/panel_usuario.py`.
"""

import hashlib
import hmac
import os
import secrets
import time
from typing import NamedTuple

from app import config
from app.core import database
from app.core.config_cliente import CLIENTE_POR_DEFECTO

# ── Cómo se guardan las contraseñas ──────────────────────────────────
#
# PBKDF2-HMAC-SHA256, de la biblioteca estándar. No se usa bcrypt ni argon2
# a propósito: son dependencias nuevas con rueda compilada, y aquí se
# verifica una contraseña al entrar al panel, no mil por segundo.
#
# El formato lleva el algoritmo y las vueltas por delante, así que subirlas
# dentro de unos años no invalida lo ya guardado: cada hash dice con qué
# parámetros se calculó.

ALGORITMO = "pbkdf2_sha256"
VUELTAS = 210_000          # recomendación de OWASP para PBKDF2-SHA256
BYTES_SAL = 16


def hash_clave(clave: str) -> str:
    """La contraseña lista para guardar en `panel_users.password_hash`."""
    if not clave:
        raise ValueError("La clave no puede estar vacía.")

    sal = secrets.token_bytes(BYTES_SAL)
    resumen = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, VUELTAS)
    return f"{ALGORITMO}${VUELTAS}${sal.hex()}${resumen.hex()}"


def clave_correcta(clave: str, guardado: str) -> bool:
    """
    ¿Es esta la contraseña que produjo ese hash?

    Nunca levanta: un hash con formato raro (una fila escrita a mano, una
    migración a medias) es una clave que no vale, no una caída del panel.
    """
    if not clave or not guardado:
        return False

    try:
        algoritmo, vueltas, sal, resumen = guardado.split("$")
        if algoritmo != ALGORITMO:
            return False
        calculado = hashlib.pbkdf2_hmac(
            "sha256", clave.encode("utf-8"), bytes.fromhex(sal), int(vueltas))
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(calculado.hex(), resumen)


# ── El secreto que firma los pases ───────────────────────────────────

_AVISADO = False


def secreto_de_firma() -> bytes:
    """
    Con qué se firma la cookie de sesión.

    En este orden:

      1. `SESSION_SECRET`, si está puesta. Es la vía limpia, y rotarla
         cierra de golpe las sesiones de todos los clientes.
      2. Derivado de `SECRETS_KEY` con HMAC. No es reutilizar el secreto:
         de un HMAC no se vuelve atrás, así que un pase filtrado no acerca
         a nadie a la clave maestra que descifra las credenciales. Ahorra
         una variable de entorno más que configurar.
      3. `ADMIN_API_KEY`, como último recurso y avisando. Es lo que había
         antes y solo sirve para que una instalación vieja no se quede sin
         panel al desplegar esto.

    Devuelve bytes porque es lo que come `hmac.new`.
    """
    global _AVISADO

    if propio := (os.getenv("SESSION_SECRET") or "").strip():
        return propio.encode("utf-8")

    if maestra := (os.getenv("SECRETS_KEY") or "").strip():
        # Etiqueta de separación: si mañana hiciera falta derivar otra
        # clave de lo mismo, sería con otra etiqueta y no la misma.
        return hmac.new(maestra.encode("utf-8"), b"panel-sesion-v1",
                        hashlib.sha256).digest()

    if not _AVISADO:
        _AVISADO = True
        print("[acceso] AVISO: no hay SESSION_SECRET ni SECRETS_KEY, así "
              "que las sesiones del panel se firman con ADMIN_API_KEY. "
              "Pon SESSION_SECRET antes de dar de alta al segundo cliente.")

    return (config.ADMIN_API_KEY or "sin-secreto").encode("utf-8")


# ── El pase (la cookie de sesión) ────────────────────────────────────

# Va delante del pase y entra en la firma. Sirve para dos cosas: que un
# pase del formato viejo —que no llevaba inquilino— no pueda colarse, y
# que el día que el formato cambie otra vez los pases en la calle caduquen
# solos en vez de interpretarse mal.
VERSION = "p2"


class Pase(NamedTuple):
    """Quién es el que está usando el panel, y hasta cuándo."""
    client_id: int
    user_id: int
    vence_absoluto: float


def crear_pase(client_id: int, user_id: int,
               vence_absoluto: float = None,
               horas_inactividad: float = None) -> str:
    """
    Un pase nuevo, firmado.

    Al renovar se conserva el vencimiento absoluto: la sesión se estira por
    uso, pero nunca más allá del tope.

    `horas_inactividad` es para el "Recordarme" del panel de barberías
    (`app/barberia/cuentas.py`): sin él, las horas de la plataforma.
    """
    ahora = time.time()
    if vence_absoluto is None:
        vence_absoluto = ahora + config.PANEL_SESION_MAXIMA_HORAS * 3600

    if horas_inactividad is None:
        horas_inactividad = config.PANEL_SESION_INACTIVIDAD_HORAS
    vence_inactividad = ahora + horas_inactividad * 3600
    cuerpo = (f"{VERSION}:{int(client_id)}:{int(user_id)}:"
              f"{vence_absoluto:.0f}:{vence_inactividad:.0f}")
    return f"{cuerpo}:{firmar(cuerpo)}"


def firmar(cuerpo: str) -> str:
    return hmac.new(secreto_de_firma(), cuerpo.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def leer_pase(texto: str, client_id: int | None) -> Pase | None:
    """
    El pase que trae la cookie, o None si no vale para ESTA petición.

    `client_id` es el inquilino que resolvió el middleware por el `Host`.
    Que el pase diga otro no es un caso raro de laboratorio: es lo que pasa
    si alguien copia su cookie al subdominio de otro negocio, y aquí es
    donde se corta.

    No consulta la base a propósito. Esto corre en cada petición del panel
    y en cada latido del canal en vivo; que el usuario siga existiendo se
    comprueba al entrar, no en cada consulta. El precio es que desactivar
    un usuario no cierra su sesión en curso, sino que la deja morir con el
    plazo de inactividad (`PANEL_SESION_INACTIVIDAD_HORAS`).
    """
    if not texto or client_id is None:
        return None

    partes = texto.split(":")
    if len(partes) != 6 or partes[0] != VERSION:
        return None

    _, cliente, usuario, absoluto, inactividad, firma = partes

    if not hmac.compare_digest(
            firma, firmar(":".join(partes[:5]))):
        return None

    try:
        cliente, usuario = int(cliente), int(usuario)
        absoluto, inactividad = float(absoluto), float(inactividad)
    except ValueError:
        return None

    # El corazón del asunto: un pase es de un negocio, no del servidor.
    if cliente != client_id:
        return None

    ahora = time.time()
    if ahora > inactividad or ahora > absoluto:
        return None

    return Pase(cliente, usuario, absoluto)


def leer_pase_sin_inquilino(texto: str) -> Pase | None:
    """
    Como `leer_pase`, pero es el pase el que DICE de qué negocio es.

    Se usa cuando todos los clientes comparten la misma dirección y por
    tanto no hay un inquilino con el que contrastar: el middleware lo lee
    de aquí (ver `app/main.py`).

    La firma sigue siendo lo que protege. Lo que se pierde respecto a los
    subdominios es la SEGUNDA comprobación —que la dirección dijera el
    mismo negocio que el pase—, no la primera.
    """
    if not texto:
        return None

    partes = texto.split(":")
    if len(partes) != 6 or partes[0] != VERSION:
        return None

    if not hmac.compare_digest(partes[5], firmar(":".join(partes[:5]))):
        return None

    try:
        return leer_pase(texto, int(partes[1]))
    except ValueError:
        return None


# ── Autenticación ────────────────────────────────────────────────────

# Id de usuario que se pone en el pase cuando se entró por la rampa, o sea
# con `ADMIN_API_KEY` y sin fila en `panel_users`. No es un id real de la
# tabla —empieza en 1— así que no puede confundirse con nadie.
USUARIO_HEREDADO = 0

# Tope de usuarios contra los que se prueba una clave. El formulario pide
# solo la contraseña (ver `autenticar`), así que hay que probarlas una a
# una, y cada intento cuesta un PBKDF2. Con un negocio pequeño sobra, y el
# tope evita que dar de alta a cien asesores convierta el login en una
# forma barata de tumbar el servidor.
MAX_USUARIOS_POR_INTENTO = 20


def _usuarios_activos(client_id: int) -> list:
    """
    Los usuarios de un negocio.

        ⚠️  Hay que llamarlo con ESE inquilino puesto.

    `filter_by(client_id=...)` no basta: el filtro automático de consultas
    (`database._filtrar_por_inquilino`) añade además el inquilino en curso,
    y si no es el mismo, las dos condiciones se contradicen y no devuelve
    ninguna fila. O sea: nadie podría entrar, y sin ningún error.

    Ya pasó. Al entrar sin subdominios, el middleware deja puesto el
    cliente por defecto porque todavía no hay pase que leer, y quien
    escribía el nombre de OTRO negocio se encontraba con "la clave no es
    correcta" siendo correcta. De eso se encarga `autenticar`, que envuelve
    todo esto en `tenencia.usar(client_id)`.
    """
    session = database.get_session()
    try:
        return (session.query(database.PanelUser)
                .filter_by(client_id=client_id, active=True)
                .order_by(database.PanelUser.id)
                .limit(MAX_USUARIOS_POR_INTENTO).all())
    finally:
        session.close()


def panel_habilitado(client_id: int | None) -> bool:
    """
    ¿Hay alguna forma de entrar al panel de este negocio?

    Se consulta al pintar el login para poder decir "este panel todavía no
    tiene clave" en vez de "clave incorrecta" para siempre.
    """
    if client_id is None:
        return False

    from app.core import tenencia
    with tenencia.usar(client_id):
        if _usuarios_activos(client_id):
            return True

    return bool(client_id == CLIENTE_POR_DEFECTO and config.ADMIN_API_KEY)


def autenticar(client_id: int, clave: str) -> Pase | None:
    """
    La clave que se escribió en el login, contra los usuarios del negocio.

    El formulario pide solo la contraseña y no un usuario, que es como
    funcionaba el panel y como lo espera quien ya lo usa. Así que se prueba
    contra cada usuario activo del negocio y gana el primero que case: el
    correo de `panel_users` sirve para saber QUIÉN entró y para poder
    quitarle el acceso a uno solo, no para escribirlo al entrar.

    Devuelve un `Pase` sin fecha (la pone `crear_pase`) o None.
    """
    if not clave or client_id is None:
        return None

    # Todo lo de dentro consulta y escribe filas de ESTE negocio, y puede
    # llamarse mientras está puesto otro —al entrar sin subdominios lo
    # normal es que el inquilino en curso sea el cliente por defecto—. Ver
    # el aviso de `_usuarios_activos`.
    from app.core import tenencia
    with tenencia.usar(client_id):
        for usuario in _usuarios_activos(client_id):
            if clave_correcta(clave, usuario.password_hash):
                _anotar_acceso(usuario.id)
                return Pase(client_id, usuario.id, None)

        return _rampa(client_id, clave)


def normalizar_usuario(texto: str) -> str:
    """
    Un nombre de usuario tal como se guarda y se compara.

    Sin mayúsculas ni espacios en los extremos: el móvil pone la primera en
    mayúscula sola, y "Nico" y "nico" no pueden ser dos personas. Por
    dentro no se toca nada —puede ser un correo, un nombre, "caja-2"—.
    """
    return (texto or "").strip().lower()


def autenticar_usuario(usuario: str, clave: str,
                       client_id: int | None = None) -> Pase | None:
    """
    Usuario y clave, como en cualquier sitio.

    El nombre de usuario es ÚNICO EN TODA LA PLATAFORMA (lo impone
    `crear_usuario`), así que dice por sí solo de qué negocio es: no hace
    falta escribir el negocio al entrar.

        ⚠️  Se busca con `tenencia.sin_inquilino()`, y no es opcional.

    El login corre con el cliente por defecto ya puesto por el middleware.
    Con él puesto, el filtro automático añade `client_id = 1` a la
    búsqueda, y el usuario de cualquier otro negocio no aparecería nunca:
    "usuario o clave incorrectos" siendo correctos, y sin ningún error.

    `client_id` restringe la búsqueda a un negocio; es para cuando se entra
    por subdominio y la dirección ya dijo de quién es el panel.

    Un negocio PAUSADO no entra, aunque la clave sea correcta.
    """
    nombre = normalizar_usuario(usuario)
    if not nombre or not clave:
        return None

    from app.core import tenencia
    from sqlalchemy import func

    with tenencia.sin_inquilino():
        session = database.get_session()
        try:
            consulta = (session.query(database.PanelUser.id,
                                      database.PanelUser.client_id,
                                      database.PanelUser.password_hash)
                        .join(database.Client,
                              database.Client.id == database.PanelUser.client_id)
                        .filter(func.lower(database.PanelUser.email) == nombre,
                                database.PanelUser.active.is_(True),
                                database.Client.active.is_(True)))
            if client_id is not None:
                consulta = consulta.filter(
                    database.PanelUser.client_id == client_id)
            # Varios solo si quedó algún nombre repetido de ANTES de que
            # fueran únicos; se prueban todos y gana el que case.
            candidatos = (consulta.order_by(database.PanelUser.id)
                          .limit(MAX_USUARIOS_POR_INTENTO).all())
        finally:
            session.close()

    for user_id, suyo, hash_guardado in candidatos:
        if clave_correcta(clave, hash_guardado):
            with tenencia.usar(suyo):
                _anotar_acceso(user_id)
            return Pase(suyo, user_id, None)
    return None


def pausado_por_impago(usuario: str, clave: str) -> int | None:
    """
    El negocio de este usuario si su clave es CORRECTA y lo pausó el cobro.

    Es para la pantalla de entrada: a quien no pagó, "usuario o clave
    incorrectos" lo manda a buscar el problema donde no está. Con la clave
    correcta se le dice que está pausado y cómo pagar. Solo con la clave
    correcta: a cualquiera de fuera no hay por qué contarle qué negocios
    tenemos ni cuáles deben.
    """
    nombre = normalizar_usuario(usuario)
    if not nombre or not clave:
        return None

    from app.core import tenencia
    from sqlalchemy import func

    with tenencia.sin_inquilino():
        session = database.get_session()
        try:
            filas = (session.query(database.PanelUser.client_id,
                                   database.PanelUser.password_hash)
                     .join(database.Client,
                           database.Client.id == database.PanelUser.client_id)
                     .filter(func.lower(database.PanelUser.email) == nombre,
                             database.PanelUser.active.is_(True),
                             database.PanelUser.area_id.is_(None),
                             database.Client.active.is_(False),
                             database.Client.pausado_por == "impago")
                     .limit(MAX_USUARIOS_POR_INTENTO).all())
        finally:
            session.close()

    for client_id, hash_guardado in filas:
        if clave_correcta(clave, hash_guardado):
            return client_id
    return None


def entrar(usuario: str, clave: str, client_id: int | None = None) -> Pase | None:
    """
    La decisión del formulario de entrada, entera.

    Primero, usuario y clave. Y si no, **las dos formas de entrar de antes**,
    para no dejar fuera a nadie a quien ya se le dio su acceso:

      - lo escrito es el nombre corto de un negocio → la clave contra los
        usuarios de ese negocio (era la casilla "Negocio").
      - la casilla vacía → la clave contra el cliente por defecto, incluida
        la rampa de `ADMIN_API_KEY`.

    Con subdominio (`client_id` puesto) no se busca en otros negocios, y la
    casilla vacía prueba la clave contra ese mismo negocio, como siempre.
    """
    pase = autenticar_usuario(usuario, clave, client_id)
    if pase is not None:
        return pase

    if client_id is not None:
        return autenticar(client_id, clave) if not normalizar_usuario(usuario) else None

    return autenticar_negocio(usuario, clave)


def normalizar_negocio(texto: str) -> str:
    """
    Lo que el cliente escribió en la casilla "Negocio", convertido al
    identificador que guarda la base.

    Perdona lo que se perdona sin ambigüedad: mayúsculas, espacios de más y
    tildes. Alguien que teclea `Panadería ` desde el celular —con el
    autocorrector poniéndole la tilde y la mayúscula— tiene que poder
    entrar; quedarse fuera por eso sería una llamada de soporte por cada
    cliente nuevo.

    Lo que NO hace es adivinar: no busca parecidos ni corrige erratas. Un
    nombre que no existe es un intento fallido, no una invitación a probar
    con el negocio más parecido.
    """
    import unicodedata

    limpio = unicodedata.normalize("NFKD", (texto or "").strip().lower())
    limpio = "".join(c for c in limpio if not unicodedata.combining(c))
    return limpio.replace(" ", "")


def autenticar_negocio(negocio: str, clave: str) -> Pase | None:
    """
    Entrar cuando todos los clientes comparten la misma dirección: el
    nombre del negocio hace el trabajo que hacía el subdominio.

    Con la casilla vacía se prueba con el cliente por defecto. Es
    deliberado: mientras el dueño del bot sea el único negocio, seguir
    entrando solo con la clave es lo que ya hacía, y obligarle a escribir
    su propio nombre cada vez no aporta nada.

    Un negocio PAUSADO no entra, aunque la clave sea correcta. Con
    subdominios eso lo cortaba `resolver_por_host` antes de llegar aquí.
    """
    slug = normalizar_negocio(negocio)

    if not slug:
        return autenticar(CLIENTE_POR_DEFECTO, clave)

    datos = tenencia_por_slug(slug)
    if datos is None or not datos.active:
        return None

    return autenticar(datos.id, clave)


def tenencia_por_slug(slug: str):
    """
    El import va dentro y no arriba: `tenencia` importa `database`, que
    acaba llegando a la configuración, y este módulo lo carga el panel.
    Arriba sería un círculo. Mismo motivo que en `database.tenencia_actual`.
    """
    from app.core import tenencia
    return tenencia.por_slug(slug)


def _rampa(client_id: int, clave: str) -> Pase | None:
    """
    La entrada con `ADMIN_API_KEY`, para quien todavía no tiene usuarios.

    Vale SOLO para el cliente por defecto —el dueño del bot— porque
    `ADMIN_API_KEY` es una variable de entorno, y una variable de entorno
    es del proceso, o sea de todos los inquilinos a la vez. Si la rampa
    valiera para cualquiera, la clave del dueño abriría el panel de todos
    sus clientes.
    """
    if client_id != CLIENTE_POR_DEFECTO or not config.ADMIN_API_KEY:
        return None

    if _usuarios_activos(client_id):
        # Ya tiene usuarios de verdad: la rampa se apaga sola. Si no, la
        # clave vieja seguiría abriendo el panel para siempre.
        return None

    if not _iguales(clave, config.ADMIN_API_KEY):
        return None

    return Pase(client_id, USUARIO_HEREDADO, None)


def _anotar_acceso(user_id: int):
    """Cuándo entró por última vez. Falla en silencio: no vale cerrarle el
    panel a alguien porque no se pudo escribir una fecha."""
    session = database.get_session()
    try:
        session.query(database.PanelUser).filter_by(id=user_id).update(
            {"ultimo_acceso": database.ahora_utc()})
        session.commit()
    except Exception as e:                                # pragma: no cover
        print(f"[acceso] no se pudo anotar el acceso: {e}")
        session.rollback()
    finally:
        session.close()


# ── Alta y mantenimiento (los usa scripts/panel_usuario.py) ──────────

def listar_usuarios(client_id: int) -> list[dict]:
    session = database.get_session()
    try:
        return [{"id": u.id, "email": u.email, "rol": u.rol,
                 "area_id": u.area_id,
                 "active": u.active, "ultimo_acceso": u.ultimo_acceso}
                for u in session.query(database.PanelUser)
                .filter_by(client_id=client_id)
                .order_by(database.PanelUser.id).all()]
    finally:
        session.close()


class UsuarioOcupado(ValueError):
    """Ese nombre de usuario ya lo tiene alguien, en este u otro negocio."""


def quien_usa(usuario: str, excepto_id: int | None = None):
    """
    `(client_id, nombre_del_negocio)` de quien ya tiene ese nombre, o None.

    Mira TODOS los negocios (`sin_inquilino`): un nombre de usuario es
    único en la plataforma, porque es lo único que se escribe al entrar.
    Los dados de baja cuentan también: si se reactivaran, habría dos.
    """
    from app.core import tenencia
    from sqlalchemy import func

    nombre = normalizar_usuario(usuario)
    with tenencia.sin_inquilino():
        session = database.get_session()
        try:
            consulta = (session.query(database.PanelUser.client_id,
                                      database.Client.nombre)
                        .join(database.Client,
                              database.Client.id == database.PanelUser.client_id)
                        .filter(func.lower(database.PanelUser.email) == nombre))
            if excepto_id is not None:
                consulta = consulta.filter(database.PanelUser.id != excepto_id)
            fila = consulta.first()
            return tuple(fila) if fila else None
        finally:
            session.close()


def _exigir_libre(client_id: int, usuario: str, excepto_id: int | None = None):
    ocupado = quien_usa(usuario, excepto_id)
    if ocupado is None:
        return
    suyo, negocio = ocupado
    donde = "este negocio" if suyo == client_id else f"«{negocio}»"
    raise UsuarioOcupado(
        f"El usuario «{normalizar_usuario(usuario)}» ya existe en {donde}. "
        f"Cada usuario es único en toda la plataforma, porque es lo que se "
        f"escribe al entrar: elige otro.")


# "No toques el área de este usuario". Es el defecto de `crear_usuario`:
# quien solo cambia una clave no tiene por qué saber de áreas.
MANTENER_AREA = object()


def crear_usuario(client_id: int, email: str, clave: str,
                  rol: str = "dueno", area_id=MANTENER_AREA) -> int:
    """
    Da de alta a quien puede entrar al panel de un negocio. Devuelve su id.

    Con `area_id` es el usuario de un ÁREA: solo verá las conversaciones de
    esa área (ver `app/core/equipo.py`). Sin él, es el dueño.

    `email` es el NOMBRE DE USUARIO: un correo, un nombre o lo que se
    quiera. La columna se sigue llamando `email` porque renombrarla era una
    migración sobre una tabla con cerradura (RLS) a cambio de nada.

    Si ese usuario ya existe en ese negocio, le cambia la clave y lo
    reactiva en vez de fallar. Si existe en OTRO negocio, levanta
    `UsuarioOcupado`: dos iguales harían imposible saber a quién deja
    entrar el formulario.
    """
    email = normalizar_usuario(email)
    if not email:
        raise ValueError("Hace falta un nombre de usuario.")

    session = database.get_session()
    try:
        propio = (session.query(database.PanelUser)
                  .filter_by(client_id=client_id, email=email).first())
    finally:
        session.close()
    if propio is None:
        _exigir_libre(client_id, email)

    session = database.get_session()
    try:
        usuario = (session.query(database.PanelUser)
                   .filter_by(client_id=client_id, email=email).first())
        if usuario is None:
            usuario = database.PanelUser(client_id=client_id, email=email,
                                         rol=rol)
            session.add(usuario)

        usuario.password_hash = hash_clave(clave)
        usuario.active = True
        # El área solo se toca si se pide. Cambiarle la clave a alguien
        # (que también pasa por aquí) no puede convertir en dueño —con
        # acceso a todo— a quien entraba por un área.
        if area_id is not MANTENER_AREA:
            usuario.area_id = area_id or None
            usuario.rol = "area" if area_id else rol
        session.commit()
        return usuario.id
    finally:
        session.close()


# ── El super-admin (tu herramienta, no la de los clientes) ───────────
#
# Autenticación aparte a propósito. El super-admin ve a TODOS los negocios,
# así que no puede entrar por la misma puerta que un cliente: si su acceso
# fuera una fila de `panel_users`, un error de rol convertiría al dueño de
# una panadería en administrador de la plataforma.
#
# Va con su propia clave en `SUPERADMIN_KEY` y su propia cookie. Mientras
# esa variable esté vacía, /superadmin responde 503 y no existe — que es lo
# correcto: una consola de administración sin clave, expuesta a internet,
# es peor que no tenerla.

VERSION_SUPER = "s1"

# Más corta que la de los clientes, y a propósito: esto no es la
# herramienta de trabajo de nadie, se entra a hacer algo y se sale.
HORAS_SUPER = 4


def super_habilitado() -> bool:
    return bool((os.getenv("SUPERADMIN_KEY") or "").strip())


def autenticar_super(clave: str) -> bool:
    esperada = (os.getenv("SUPERADMIN_KEY") or "").strip()
    if not esperada or not clave:
        return False
    return _iguales(clave, esperada)


def _iguales(a: str, b: str) -> bool:
    """
    Comparación en tiempo constante, y en bytes.

    `hmac.compare_digest` sobre `str` LEVANTA TypeError si alguno lleva un
    carácter que no sea ASCII. Una clave con una tilde daría un error del
    servidor en vez de un "clave incorrecta", que es de esos fallos que
    mandan a buscar el problema al sitio equivocado. En bytes no pasa.
    """
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def crear_pase_super() -> str:
    vence = time.time() + HORAS_SUPER * 3600
    cuerpo = f"{VERSION_SUPER}:{vence:.0f}"
    return f"{cuerpo}:{firmar(cuerpo)}"


def pase_super_valido(texto: str) -> bool:
    if not texto or not super_habilitado():
        return False

    partes = texto.split(":")
    if len(partes) != 3 or partes[0] != VERSION_SUPER:
        return False

    if not hmac.compare_digest(partes[2], firmar(":".join(partes[:2]))):
        return False

    try:
        return time.time() <= float(partes[1])
    except ValueError:
        return False


def desactivar_usuario(client_id: int, email: str) -> bool:
    """
    Le quita el acceso a alguien. No borra la fila: así queda constancia de
    que ese correo estuvo dentro.

    Ojo: su sesión en curso sigue viva hasta que caduque. Ver `leer_pase`.
    """
    session = database.get_session()
    try:
        filas = (session.query(database.PanelUser)
                 .filter_by(client_id=client_id,
                            email=(email or "").strip().lower())
                 .update({"active": False}))
        session.commit()
        return bool(filas)
    finally:
        session.close()


def renombrar_usuario(client_id: int, user_id: int, nuevo: str) -> str:
    """
    Le cambia el nombre de usuario a alguien. Devuelve el que quedó.

    Por id y no por nombre: el nombre es justo lo que cambia. La clave no
    se toca, y la sesión que tenga abierta sigue valiendo (el pase guarda
    el id, no el nombre).
    """
    nuevo = normalizar_usuario(nuevo)
    if not nuevo:
        raise ValueError("El nombre de usuario no puede quedar vacío.")
    _exigir_libre(client_id, nuevo, excepto_id=user_id)

    session = database.get_session()
    try:
        filas = (session.query(database.PanelUser)
                 .filter_by(client_id=client_id, id=user_id)
                 .update({"email": nuevo}))
        session.commit()
        if not filas:
            raise ValueError("Ese usuario no es de este negocio.")
        return nuevo
    finally:
        session.close()


def borrar_usuario(client_id: int, user_id: int) -> bool:
    """
    Borra a alguien de la lista para siempre. Solo si ya está de baja.

    Primero se da de baja y después se borra, a propósito: dar de baja se
    deshace (con una clave nueva) y borrar no. Dos pasos para lo que no
    tiene vuelta atrás. Con la fila se va también el nombre, que queda
    libre para otro.
    """
    session = database.get_session()
    try:
        filas = (session.query(database.PanelUser)
                 .filter_by(client_id=client_id, id=user_id, active=False)
                 .delete())
        session.commit()
        return bool(filas)
    finally:
        session.close()
