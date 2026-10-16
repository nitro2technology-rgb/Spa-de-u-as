"""
ENTRAR AL PANEL DE LA BARBERÍA, Y TODO LO QUE CUELGA DE ESO
============================================================
La pantalla de entrada es UNA para todos los roles (6.1 del handoff): el
rol decide a dónde llega cada quien después (`permisos.destino_inicial`).

Se apoya en lo que ya hay y no lo duplica:

  · el ACCESO (usuario y clave) es una fila de `panel_users`, con el
    mismo hash que el panel del bot (`acceso.hash_clave`);
  · la SESIÓN es el mismo pase firmado y la misma cookie, así que el
    middleware de `app/main.py` resuelve el inquilino sin saber que esto
    existe.

Lo que añade este módulo:

  · se entra con el usuario, el CORREO o el CELULAR de `barb_personal`;
  · el freno cuenta por USUARIO + IP y dice cuántos intentos quedan (5, y
    15 minutos fuera). Encima sigue el freno por IP de la plataforma, que
    es el que para a quien prueba muchos usuarios distintos;
  · "Recordarme": un pase de 30 días (ver `pase_para`);
  · la clave temporal que se cambia al primer ingreso;
  · el enlace de "Olvidé mi contraseña": un solo uso y 30 minutos.

    ⚠️  LA BÚSQUEDA DEL USUARIO VA SIN INQUILINO.

Es la trampa de §3.20 de CONTINUAR_AQUI: quien todavía no entró llega con
el cliente por defecto puesto por el middleware, y con él el filtro del
ORM no encontraría nunca al personal de otra barbería. Se busca con
`tenencia.sin_inquilino()` y, en cuanto se sabe de quién es, todo lo que
se escribe va con `tenencia.usar(ese_id)`.
"""

import hashlib
import re
import secrets
import time
import unicodedata
from datetime import timedelta
from typing import NamedTuple

from sqlalchemy import func, or_

from app import config
from app.barberia import modelos as m
from app.barberia import permisos
from app.core import acceso, database, freno, planes, tenencia
from app.core.equipo import ROL_BARBERIA

MAX_INTENTOS = 5
MINUTOS_BLOQUEO = 15
DIAS_RECORDAR = 30
MINUTOS_ENLACE = 30
ENLACES_VIGENTES_MAX = 3      # por persona: que "Enviar enlace" no sea un cañón de correos
LARGO_MINIMO_CLAVE = 8

# Tope de candidatos contra los que se prueba una clave, como en acceso.py:
# cada intento cuesta un PBKDF2.
MAX_CANDIDATOS = 20


# ══════════════════════════════════════════════════════════════════════
#  NOMBRES DE USUARIO
# ══════════════════════════════════════════════════════════════════════

def sin_tildes(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in limpio if not unicodedata.combining(c))


def normalizar(identificador: str) -> str:
    """Lo que se escribió en "Usuario, correo o celular", listo para buscar."""
    return re.sub(r"\s+", "", (identificador or "").strip().lower())


def solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def telefono_normalizado(texto: str) -> str | None:
    """Un celular como se guarda: solo dígitos, o None si no parece uno."""
    digitos = solo_digitos(texto)
    return digitos if len(digitos) >= 7 else None


USUARIO_VALIDO = re.compile(r"^[a-z0-9._]+$")


def sugerir_usuario(nombre: str) -> str:
    """
    El usuario que se autocompleta en "Agregar usuario" (6.2.9): primer
    nombre + "." + inicial del apellido, sin tildes y en minúsculas.
    "Daniel Castro" → "daniel.c". El navegador hace lo mismo mientras se
    escribe (barberia.js); esta es la versión del servidor.
    """
    partes = [re.sub(r"[^a-z0-9]", "", sin_tildes(p).lower())
              for p in (nombre or "").split()]
    partes = [p for p in partes if p]
    if not partes:
        return ""
    return partes[0] + (f".{partes[-1][0]}" if len(partes) > 1 else "")


def clave_temporal_para(negocio: str) -> str:
    """"Filo Barbería" → "Filo-4827". El prefijo es la primera palabra."""
    palabra = re.sub(r"[^A-Za-z0-9]", "",
                     sin_tildes((negocio or "").split(" ")[0])) or "Clave"
    return f"{palabra[:12].capitalize()}-{secrets.randbelow(9000) + 1000}"


# ══════════════════════════════════════════════════════════════════════
#  EL FRENO
# ══════════════════════════════════════════════════════════════════════

class FrenoPorUsuario:
    """
    Fallos por (usuario, IP), con su ventana de olvido.

    En memoria, como `app/core/freno.py`, y por lo mismo: hay un solo
    proceso (ver §3.9). Se pierde al reiniciar.

    Por usuario + IP y no solo por usuario: si contara solo el usuario,
    cualquiera podría dejar fuera al dueño escribiendo su usuario cinco
    veces con una clave inventada.
    """

    TOPE_LLAVES = 5000

    def __init__(self):
        self._fallos: dict[tuple, list[float]] = {}

    def _vigentes(self, llave) -> list[float]:
        limite = time.time() - MINUTOS_BLOQUEO * 60
        fallos = [t for t in self._fallos.get(llave, []) if t > limite]
        if fallos:
            self._fallos[llave] = fallos
        else:
            self._fallos.pop(llave, None)
        return fallos

    def restantes(self, llave) -> int:
        return max(0, MAX_INTENTOS - len(self._vigentes(llave)))

    def bloqueado(self, llave) -> bool:
        return self.restantes(llave) == 0

    def anotar(self, llave):
        self._fallos.setdefault(llave, []).append(time.time())
        if len(self._fallos) > self.TOPE_LLAVES:
            for vieja in list(self._fallos):
                self._vigentes(vieja)

    def olvidar(self, llave):
        self._fallos.pop(llave, None)

    def clear(self):
        """Solo para las pruebas."""
        self._fallos.clear()


FRENO_USUARIO = FrenoPorUsuario()
FRENO_IP = freno.Freno("barberia")


# ══════════════════════════════════════════════════════════════════════
#  ENTRAR
# ══════════════════════════════════════════════════════════════════════

class Candidato(NamedTuple):
    user_id: int
    client_id: int
    personal_id: int
    rol: str
    password_hash: str
    activo: bool             # el acceso y la persona, los dos encendidos
    eliminado: bool
    cliente_activo: bool
    barberia: bool           # `clients.barberia_contratada`


def _candidatos(ident: str) -> list[Candidato]:
    """Todo el personal, de TODAS las barberías, que responde a ese nombre."""
    telefono = telefono_normalizado(ident)
    condiciones = [func.lower(database.PanelUser.email) == ident,
                   func.lower(m.Personal.correo) == ident]
    if telefono:
        condiciones.append(m.Personal.telefono == telefono)

    with tenencia.sin_inquilino():
        session = database.get_session()
        try:
            filas = (session.query(
                        database.PanelUser.id, database.PanelUser.client_id,
                        m.Personal.id, m.Personal.rol,
                        database.PanelUser.password_hash,
                        database.PanelUser.active, m.Personal.activo,
                        m.Personal.eliminado_en,
                        database.Client.active,
                        database.Client.barberia_contratada)
                     .join(m.Personal, m.Personal.panel_user_id == database.PanelUser.id)
                     .join(database.Client,
                           database.Client.id == database.PanelUser.client_id)
                     .filter(m.Personal.client_id == database.PanelUser.client_id,
                             or_(*condiciones))
                     .order_by(database.PanelUser.id)
                     .limit(MAX_CANDIDATOS).all())
        finally:
            session.close()

    return [Candidato(u, c, p, rol, h, bool(ua and pa), e is not None,
                      bool(ca), bool(b))
            for (u, c, p, rol, h, ua, pa, e, ca, b) in filas]


# Lo que puede salir de intentar entrar.
OK = "ok"
VACIO = "vacio"
INCORRECTO = "incorrecto"
BLOQUEADO = "bloqueado"
DESACTIVADO = "desactivado"
PAUSADO_DUENO = "pausado_dueno"     # el dueño ve la pantalla 4c
PAUSADO = "pausado"                 # el resto, un aviso genérico
SIN_MODULO = "sin_modulo"


class Resultado(NamedTuple):
    tipo: str
    pase: acceso.Pase | None = None
    rol: str | None = None
    client_id: int | None = None
    restantes: int | None = None


def entrar(usuario: str, clave: str, request) -> Resultado:
    """
    La decisión del formulario de entrada, entera.

    Lo que NO se distingue a propósito, porque le diría a cualquiera desde
    fuera qué usuarios existen: "ese usuario no existe" y "la clave no es
    esa". Lo que SÍ se distingue, y solo con la clave correcta: que el
    usuario esté desactivado o que la barbería esté pausada. Quien sabe la
    clave es quien tiene que enterarse de por qué no entra.
    """
    ident = normalizar(usuario)
    if not ident or not clave:
        return Resultado(VACIO)

    llave = (ident, freno.ip_de(request))
    if FRENO_IP.bloqueado(request) or FRENO_USUARIO.bloqueado(llave):
        return Resultado(BLOQUEADO)

    for c in _candidatos(ident):
        if c.eliminado or not acceso.clave_correcta(clave, c.password_hash):
            continue

        FRENO_USUARIO.olvidar(llave)
        FRENO_IP.olvidar(request)

        if not c.activo:
            return Resultado(DESACTIVADO, client_id=c.client_id)
        if not c.cliente_activo:
            return Resultado(PAUSADO_DUENO if c.rol == m.DUENO else PAUSADO,
                             rol=c.rol, client_id=c.client_id)
        if not c.barberia:
            return Resultado(SIN_MODULO, client_id=c.client_id)

        with tenencia.usar(c.client_id):
            acceso._anotar_acceso(c.user_id)
        return Resultado(OK, acceso.Pase(c.client_id, c.user_id, None),
                         rol=c.rol, client_id=c.client_id)

    FRENO_USUARIO.anotar(llave)
    FRENO_IP.anotar_fallo(request)
    restantes = FRENO_USUARIO.restantes(llave)
    if restantes == 0:
        return Resultado(BLOQUEADO)
    return Resultado(INCORRECTO, restantes=restantes)


# ── La sesión ────────────────────────────────────────────────────────

def pase_para(client_id: int, user_id: int, recordar: bool,
              vence_absoluto: float | None = None) -> tuple[str, int | None]:
    """
    El pase firmado y el `max_age` de su cookie.

    Sin "Recordarme": las horas de la plataforma y una cookie de sesión del
    navegador (se va al cerrarlo). Con él: 30 días de tope y de
    inactividad, y una cookie que sobrevive al cierre.

    Que un pase es "recordado" no se guarda aparte: se ve en su propio
    vencimiento absoluto, que va firmado (`es_recordado`). Así una
    renovación no puede convertir una sesión corta en una de 30 días.
    """
    if recordar:
        segundos = DIAS_RECORDAR * 24 * 3600
        vence = vence_absoluto or (time.time() + segundos)
        texto = acceso.crear_pase(client_id, user_id, vence,
                                  horas_inactividad=DIAS_RECORDAR * 24)
        return texto, max(60, int(vence - time.time()))
    return acceso.crear_pase(client_id, user_id, vence_absoluto), None


def es_recordado(pase: acceso.Pase) -> bool:
    """¿Se emitió con "Recordarme"? Su tope pasa del de una sesión normal."""
    return (pase.vence_absoluto - time.time()
            > config.PANEL_SESION_MAXIMA_HORAS * 3600 + 60)


# ── Quién es el del pase ─────────────────────────────────────────────

def persona_de(pase: acceso.Pase | None) -> permisos.Persona | None:
    """
    La persona de la barbería detrás de este pase, o None si ya no puede
    entrar.

    Se consulta en CADA petición, como `equipo.de_pase`: desactivar a
    alguien, quitarle una sede o pausar la barbería tiene que surtir
    efecto en la siguiente pantalla, no cuando caduque la sesión.

    Corre con el inquilino que puso el middleware, que sale del mismo pase.
    """
    if pase is None:
        return None

    negocio = tenencia.por_id(pase.client_id)
    if negocio is None or not negocio.active:
        return None
    fila = negocio.fila
    if not fila.get("barberia_contratada"):
        return None

    session = database.get_session()
    try:
        p = (session.query(m.Personal)
             .filter_by(client_id=pase.client_id, panel_user_id=pase.user_id)
             .first())
        u = session.get(database.PanelUser, pase.user_id)
        if (p is None or u is None or not p.activo or not u.active
                or p.eliminado_en is not None):
            return None

        if p.rol == m.DUENO:
            sedes = session.query(m.Sede.id, m.Sede.nombre).order_by(m.Sede.id)
        else:
            sedes = (session.query(m.Sede.id, m.Sede.nombre)
                     .join(m.PersonalSede, m.PersonalSede.sede_id == m.Sede.id)
                     .filter(m.PersonalSede.personal_id == p.id)
                     .order_by(m.Sede.id))
        sedes = tuple((i, n) for i, n in sedes.all())

        plan = planes.de(fila)
        return permisos.Persona(
            personal_id=p.id, user_id=u.id, client_id=pase.client_id,
            nombre=p.nombre, rol=p.rol, sedes=sedes,
            clave_temporal=bool(p.clave_temporal), negocio=negocio.nombre,
            plan_nombre=plan.nombre,
            con_bot=bool(fila.get("bot_contratado")) and plan.bot)
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
#  CONTRASEÑAS
# ══════════════════════════════════════════════════════════════════════

def _validar_nueva(nueva: str, repetida: str) -> str | None:
    if len(nueva or "") < LARGO_MINIMO_CLAVE:
        return (f"La contraseña nueva necesita al menos {LARGO_MINIMO_CLAVE} "
                f"caracteres.")
    if nueva != repetida:
        return "Las dos contraseñas no coinciden. Escríbelas otra vez."
    return None


def _poner_clave(personal_id: int, nueva: str) -> None:
    """Cambia la clave de alguien y le quita la marca de temporal."""
    session = database.get_session()
    try:
        p = session.get(m.Personal, personal_id)
        u = session.get(database.PanelUser, p.panel_user_id)
        u.password_hash = acceso.hash_clave(nueva)
        p.clave_temporal = False
        session.commit()
    finally:
        session.close()


def cambiar_clave(persona: permisos.Persona, actual: str, nueva: str,
                  repetida: str) -> str | None:
    """
    El cambio de contraseña desde el panel. Devuelve el error o None.

    Con clave TEMPORAL no se pide la actual: acaba de escribirla para
    entrar, y la pantalla es obligatoria. Con una clave propia sí: una
    sesión abierta en un computador ajeno no debe bastar para cambiarla.
    """
    if not persona.clave_temporal:
        session = database.get_session()
        try:
            u = session.get(database.PanelUser, persona.user_id)
            guardado = u.password_hash if u else ""
        finally:
            session.close()
        if not acceso.clave_correcta(actual, guardado):
            return "La contraseña actual no es esa."

    error = _validar_nueva(nueva, repetida)
    if error:
        return error

    _poner_clave(persona.personal_id, nueva)
    registrar("CLAVE", "cambió su contraseña", persona=persona)
    return None


# ── "Olvidé mi contraseña" ───────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def pedir_recuperacion(identificador: str) -> int:
    """
    Manda el enlace a quien responda a ese nombre y tenga correo.

    Devuelve cuántos enlaces salieron, SOLO para las pruebas: la pantalla
    dice lo mismo siempre ("si tiene un usuario, le llegó…"), porque
    contestar distinto le diría a cualquiera qué usuarios existen.

    El enlace apunta a `PANEL_URL` y no a la dirección de la petición: el
    `Host` lo escribe quien pide, y con él se podría mandar a la víctima
    un enlace legítimo que lleve a otro sitio.
    """
    from app.core import correo

    ident = normalizar(identificador)
    if not ident:
        return 0

    enviados = 0
    for c in _candidatos(ident):
        if c.eliminado or not c.activo or not c.cliente_activo or not c.barberia:
            continue

        with tenencia.usar(c.client_id):
            session = database.get_session()
            try:
                p = session.get(m.Personal, c.personal_id)
                if not p or not p.correo:
                    continue
                ahora = m.ahora()
                vigentes = (session.query(m.Recuperacion)
                            .filter(m.Recuperacion.personal_id == p.id,
                                    m.Recuperacion.usado_en.is_(None),
                                    m.Recuperacion.vence_en > ahora)
                            .count())
                if vigentes >= ENLACES_VIGENTES_MAX:
                    continue

                token = secrets.token_urlsafe(32)
                session.add(m.Recuperacion(
                    client_id=c.client_id, personal_id=p.id,
                    token_hash=_hash_token(token),
                    vence_en=ahora + timedelta(minutes=MINUTOS_ENLACE)))
                session.commit()
                destino, nombre = p.correo, p.nombre
            finally:
                session.close()

            enlace = f"{config.PANEL_URL}/restablecer/{token}"
            correo.avisar(
                [destino], "Crea tu contraseña nueva",
                f"Hola, {nombre.split(' ')[0]}.\n\n"
                f"Alguien pidió crear una contraseña nueva para tu usuario "
                f"del panel de la barbería. Si fuiste tú, entra aquí:\n\n"
                f"{enlace}\n\n"
                f"El enlace vence en {MINUTOS_ENLACE} minutos y sirve una "
                f"sola vez. Si no lo pediste, no hagas nada: tu contraseña "
                f"sigue igual.")
            enviados += 1
    return enviados


def enlace_valido(token: str) -> tuple[int, int] | None:
    """`(client_id, personal_id)` de un enlace vigente y sin usar, o None."""
    if not token:
        return None
    with tenencia.sin_inquilino():
        session = database.get_session()
        try:
            r = (session.query(m.Recuperacion)
                 .filter_by(token_hash=_hash_token(token)).first())
            if r is None or r.usado_en is not None:
                return None
            if m.en_utc(r.vence_en) <= m.ahora():
                return None
            return r.client_id, r.personal_id
        finally:
            session.close()


def restablecer(token: str, nueva: str, repetida: str) -> str | None:
    """La contraseña nueva desde el enlace del correo. Devuelve el error o None."""
    dueno = enlace_valido(token)
    if dueno is None:
        return "Este enlace ya no sirve. Pide uno nuevo desde la entrada."
    error = _validar_nueva(nueva, repetida)
    if error:
        return error

    client_id, personal_id = dueno
    with tenencia.usar(client_id):
        session = database.get_session()
        try:
            r = (session.query(m.Recuperacion)
                 .filter_by(token_hash=_hash_token(token)).first())
            # Se marca usado ANTES de cambiar la clave: dos pestañas con el
            # mismo enlace no pueden usarlo las dos.
            r.usado_en = m.ahora()
            session.commit()
            nombre = session.get(m.Personal, personal_id).nombre
        finally:
            session.close()
        _poner_clave(personal_id, nueva)
        registrar("CLAVE", "creó una contraseña nueva con el enlace del correo",
                  actor=nombre, personal_id=personal_id)
    return None


# ══════════════════════════════════════════════════════════════════════
#  ALTA DE PERSONAL Y SEDES
# ══════════════════════════════════════════════════════════════════════

class CupoLleno(ValueError):
    """El plan no admite otra sede u otro barbero."""


def _fila_cliente(client_id: int) -> dict:
    datos = tenencia.por_id(client_id)
    return datos.fila if datos else {}


def crear_sede(client_id: int, nombre: str, direccion: str = "",
               telefono: str = "") -> int:
    """Una sede nueva, dentro del cupo del plan. Con el inquilino puesto."""
    session = database.get_session()
    try:
        usadas = session.query(m.Sede).count()
        cupo = planes.cupo_de_sedes(_fila_cliente(client_id))
        if usadas >= cupo:
            cuantas = "la sede" if cupo == 1 else f"las {cupo} sedes"
            raise CupoLleno(f"Llegaste a {cuantas} de tu plan. Amplía el plan "
                            f"para agregar más.")
        sede = m.Sede(client_id=client_id, nombre=nombre.strip(),
                      direccion=direccion or None, telefono=telefono or None)
        session.add(sede)
        session.commit()
        sede_id = sede.id
    finally:
        session.close()

    # Una sede sin precios no puede cobrar nada. Import aquí: `operacion`
    # importa este módulo.
    from app.barberia import agenda, operacion
    operacion.sembrar_catalogo(sede_id)
    agenda.poner_horario_por_defecto(sede_id)
    return sede_id


def crear_persona(client_id: int, nombre: str, usuario: str, rol: str,
                  sedes: list[int], correo: str = "", telefono: str = "",
                  clave: str | None = None, actor: str | None = None,
                  exigir_cambio: bool | None = None, **pago) -> tuple[int, str]:
    """
    Alguien nuevo en la barbería, con su acceso. Devuelve `(id, clave)`.

    Sin `clave` se genera una temporal (`Filo-4827`) que se exige cambiar
    al primer ingreso. Con el inquilino de ESA barbería puesto: el usuario
    se busca en toda la plataforma (`acceso.crear_usuario`), pero lo que se
    escribe es de ella.

    Las validaciones van en el orden del handoff (6.2.9) y levantan
    `ValueError` con el texto que se enseña.
    """
    if tenencia.actual() != client_id:
        raise RuntimeError("crear_persona necesita el inquilino de esa barbería puesto.")

    nombre = (nombre or "").strip()
    usuario = acceso.normalizar_usuario(usuario)
    if not nombre:
        raise ValueError("Falta el nombre.")
    if not usuario:
        raise ValueError("Falta el usuario con el que va a entrar.")
    if not USUARIO_VALIDO.match(usuario):
        raise ValueError("El usuario solo puede llevar letras sin tilde, "
                         "números, punto y guion bajo.")
    if rol not in m.ROLES:
        raise ValueError("Ese rol no existe.")

    session = database.get_session()
    try:
        todas = [i for (i,) in session.query(m.Sede.id).all()]
        if rol == m.DUENO:
            sedes = todas            # "Elegir Dueño marca todas las sedes"
        sedes = [s for s in (sedes or []) if s in todas]
        if not sedes:
            raise ValueError("Elige al menos una sede.")

        if rol == m.BARBERO:
            barberos = (session.query(m.Personal)
                        .filter(m.Personal.rol == m.BARBERO,
                                m.Personal.eliminado_en.is_(None)).count())
            cupo = planes.cupo_de_barberos(_fila_cliente(client_id))
            if barberos >= cupo:
                raise CupoLleno(f"Llegaste a los {cupo} barberos de tu plan. "
                                f"Amplía el plan para agregar más.")
    finally:
        session.close()

    # Libre en TODA la plataforma, este negocio incluido. `crear_usuario`
    # no falla si el nombre ya es de este negocio: le cambia la clave y lo
    # reactiva. Aquí eso sería quedarse con la cuenta de otro —la del dueño
    # del bot, por ejemplo— sin que nadie lo note.
    if acceso.quien_usa(usuario) is not None:
        raise ValueError(f"Ya hay alguien con el usuario @{usuario}. "
                         f"Prueba con otro.")

    # Sin clave se genera una temporal. Con una clave dada, se exige
    # cambiarla solo si se pide (la que el dueño vio en el formulario de
    # "Agregar usuario" es temporal aunque venga escrita).
    temporal = clave is None if exigir_cambio is None else exigir_cambio
    if clave is None:
        clave = clave_temporal_para(tenencia.por_id(client_id).nombre)

    try:
        user_id = acceso.crear_usuario(
            client_id, usuario, clave,
            rol="dueno" if rol == m.DUENO else ROL_BARBERIA, area_id=None)
    except acceso.UsuarioOcupado:
        raise ValueError(f"Ya hay alguien con el usuario @{usuario}. "
                         f"Prueba con otro.") from None

    session = database.get_session()
    try:
        p = m.Personal(client_id=client_id, panel_user_id=user_id, nombre=nombre,
                       correo=(correo or "").strip().lower() or None,
                       telefono=telefono_normalizado(telefono), rol=rol,
                       clave_temporal=temporal, **pago)
        session.add(p)
        session.flush()
        for sede_id in sedes:
            session.add(m.PersonalSede(client_id=client_id, personal_id=p.id,
                                       sede_id=sede_id))
        session.commit()
        personal_id = p.id
    finally:
        session.close()

    registrar("USUARIO", f"creó el usuario @{usuario} ({permisos.ROLES[rol]})",
              actor=actor or "Nitro2Tech", tabla="barb_personal",
              registro_id=personal_id)
    return personal_id, clave


# ══════════════════════════════════════════════════════════════════════
#  ACTIVIDAD
# ══════════════════════════════════════════════════════════════════════

def registrar(accion: str, detalle: str, persona: permisos.Persona | None = None,
              actor: str | None = None, personal_id: int | None = None,
              sede_id: int | None = None, tabla: str | None = None,
              registro_id: int | None = None, motivo: str | None = None,
              antes=None, despues=None) -> None:
    """
    Una línea en Actividad. Con el inquilino puesto.

    No puede tumbar lo que la llamó: si no se pudo escribir, se anota en
    el log y se sigue. Lo contrario sería no dejar cerrar una caja porque
    falló la línea que dice que se cerró.
    """
    session = database.get_session()
    try:
        session.add(m.Actividad(
            personal_id=persona.personal_id if persona else personal_id,
            actor=(persona.nombre if persona else actor) or "Sistema",
            accion=accion, detalle=detalle, sede_id=sede_id, tabla=tabla,
            registro_id=registro_id, motivo=motivo, antes=antes, despues=despues))
        session.commit()
    except Exception as e:                                  # pragma: no cover
        session.rollback()
        print(f"[barberia] no se pudo anotar la actividad «{detalle}»: {e}")
    finally:
        session.close()
