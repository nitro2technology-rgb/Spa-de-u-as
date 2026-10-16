"""
EL EQUIPO DE UN NEGOCIO: QUIÉN VE QUÉ
======================================
Un negocio tiene un DUEÑO (el que nos paga) y, según su plan, varias ÁREAS
—Ventas, Soporte, Contratos—, cada una con su usuario y su clave.

    dueño   ve y atiende TODAS las conversaciones, y arma su equipo.
    área    ve y atiende SOLO las de su área. Nada más.

DE QUÉ ÁREA ES UNA CONVERSACIÓN
-------------------------------
En este orden:

  1. `Contact.area`: el dueño se la pasó a mano a un área.
  2. La opción del menú que eligió el cliente (`Contact.servicio`) y las
     áreas que dicen encargarse de ella (`avisos.destinos[].opciones`).
  3. Ninguna de las dos: es del DUEÑO. Lo que no tiene área no se le
     enseña a nadie más (decisión del 23-sep-2026).

    ⚠️  LA PUERTA ES ESTA, NO LA PANTALLA.

Esconder una conversación en el listado no impide abrirla escribiendo su
dirección. Por eso cada ruta del panel que toca una conversación pregunta
`puede_ver` antes de responder —el hilo, los archivos, el envío, el canal
en vivo—, y el listado se filtra en la consulta (`filtro_contactos`), no
después.
"""

from typing import NamedTuple

from sqlalchemy import and_, false, or_

from app import config
from app.core import database


class Quien(NamedTuple):
    """Quién está usando el panel."""
    user_id: int
    usuario: str          # lo que escribe al entrar
    area_id: str | None   # None = el dueño
    area_nombre: str
    opciones: tuple       # las opciones del menú de las que se encarga

    @property
    def es_dueno(self) -> bool:
        return self.area_id is None


DUENO_SIN_USUARIO = Quien(0, "administrador", None, "", ())

# `panel_users.rol` del personal de una barbería que no es el dueño. No
# entra a este panel: ver `de_pase` y `app/barberia/modelos.Personal`.
ROL_BARBERIA = "barberia"


def areas() -> list:
    """Las áreas del negocio en curso, con su `id`."""
    return list(config.AVISOS_DESTINOS or [])


def area(area_id: str) -> dict | None:
    return next((a for a in areas() if a.get("id") == area_id), None)


def de_pase(pase) -> Quien | None:
    """
    Quién es el dueño de este pase, o None si ya no puede entrar.

    Se consulta en CADA petición, y es a propósito. El pase de la cookie
    solo dice el id del usuario; lo que puede ver depende de su área, y el
    dueño puede cambiarla o quitarle el acceso en cualquier momento. Leído
    del pase, esos cambios no surtirían efecto hasta que la sesión
    caducara. Es una consulta por clave primaria: no cuesta nada.
    """
    if pase is None:
        return None

    from app.core import acceso
    if pase.user_id == acceso.USUARIO_HEREDADO:
        # Entró con la clave del servidor (la rampa del cliente por
        # defecto): es el dueño.
        return DUENO_SIN_USUARIO

    session = database.get_session()
    try:
        u = (session.query(database.PanelUser)
             .filter_by(id=pase.user_id, client_id=pase.client_id).first())
        if u is None or not u.active:
            return None
        usuario, area_id, rol = u.email, u.area_id, u.rol
    finally:
        session.close()

    if rol == ROL_BARBERIA:
        # Un barbero, recepción o administrador de sede de una barbería.
        # Su panel es /b o /yo (`app/barberia/`), no este: sin área, esta
        # función lo trataría como el DUEÑO y le abriría todas las
        # conversaciones del bot. Solo el dueño de la barbería entra aquí,
        # y ese va con rol "dueno".
        return None

    if not area_id:
        # Un usuario de ÁREA que se quedó sin área (se quitó su área) no
        # entra, aunque alguien le devuelva el acceso: sin esta línea
        # entraría sin área, o sea como dueño, y lo vería todo.
        if rol == "area":
            return None
        return Quien(pase.user_id, usuario, None, "", ())

    datos = area(area_id)
    if datos is None:
        # Su área ya no existe (el dueño la quitó). Sin área no hay nada
        # que enseñarle, y dejarle entrar a una bandeja vacía confunde más
        # que decirle que no tiene acceso.
        return None
    return Quien(pase.user_id, usuario, area_id, datos.get("nombre") or area_id,
                 tuple(datos.get("opciones") or ()))


def area_de_contacto(servicio: str | None, asignada: str | None) -> str | None:
    """
    De qué área es una conversación. None = del dueño. Ver el orden arriba.

    Si varias áreas reclaman la misma opción, se devuelve la primera; para
    VER, cuentan todas (ver `puede_ver`).
    """
    ids = {a["id"] for a in areas()}
    if asignada and asignada in ids:
        return asignada
    if servicio:
        for a in areas():
            if servicio in (a.get("opciones") or ()):
                return a["id"]
    return None


def _la_ve(quien: Quien, servicio: str | None, asignada: str | None) -> bool:
    if quien.es_dueno:
        return True
    if asignada:
        return asignada == quien.area_id
    return bool(servicio) and servicio in quien.opciones


def filtro_contactos(quien: Quien):
    """
    La condición SQL de las conversaciones que puede ver, o None si todas.

    Se aplica EN LA CONSULTA: filtrar la lista después de traerla dejaría
    las cuentas del panel ("Esperando respuesta tuya") contando las de las
    otras áreas.
    """
    if quien.es_dueno:
        return None
    C = database.Contact
    por_opcion = (and_(C.area.is_(None), C.servicio.in_(quien.opciones))
                  if quien.opciones else false())
    return or_(C.area == quien.area_id, por_opcion)


def puede_ver(quien: Quien | None, phone: str) -> bool:
    """¿Esta persona puede abrir la conversación con ese teléfono?"""
    if quien is None:
        return False
    if quien.es_dueno:
        return True
    session = database.get_session()
    try:
        c = session.query(database.Contact).filter_by(phone=phone).first()
        return c is not None and _la_ve(quien, c.servicio, c.area)
    finally:
        session.close()


def asignar(phone: str, area_id: str | None) -> bool:
    """
    El dueño le pasa una conversación a un área, o se la queda (None).

    Devuelve False si el contacto no existe o el área tampoco.
    """
    if area_id and area(area_id) is None:
        return False
    session = database.get_session()
    try:
        c = session.query(database.Contact).filter_by(phone=phone).first()
        if c is None:
            return False
        c.area = area_id or None
        session.commit()
        return True
    finally:
        session.close()


def ids_de_usuarios_que_ven(servicio: str | None, asignada: str | None) -> set | None:
    """
    Los `user_id` de área que ven esta conversación, además del dueño.

    Para los avisos al celular: el de un cliente de Ventas no le suena a
    Soporte. Devuelve el conjunto de ids de usuarios de área (el dueño
    siempre recibe, y no está aquí).
    """
    session = database.get_session()
    try:
        filas = (session.query(database.PanelUser.id, database.PanelUser.area_id)
                 .filter(database.PanelUser.area_id.isnot(None),
                         database.PanelUser.active.is_(True)).all())
    finally:
        session.close()

    quienes = set()
    for user_id, area_id in filas:
        datos = area(area_id)
        if datos is None:
            continue
        q = Quien(user_id, "", area_id, "", tuple(datos.get("opciones") or ()))
        if _la_ve(q, servicio, asignada):
            quienes.add(user_id)
    return quienes


def usuario_de_area(area_id: str) -> dict | None:
    """El usuario que entra por esa área, o None si todavía no tiene."""
    session = database.get_session()
    try:
        u = (session.query(database.PanelUser)
             .filter_by(area_id=area_id).order_by(database.PanelUser.id).first())
        if u is None:
            return None
        return {"id": u.id, "usuario": u.email, "activo": u.active,
                "ultimo_acceso": u.ultimo_acceso}
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
#  ARMAR EL EQUIPO (lo hace el dueño desde su panel)
# ══════════════════════════════════════════════════════════════════════
#
# Las áreas viven en `negocio_config.avisos.destinos`, junto al resto del
# contenido del negocio, y su usuario en `panel_users` con `area_id`. Aquí
# se escriben las dos cosas a la vez, para que no pueda quedar un área sin
# usuario por un lado y un usuario sin área por otro.

class NoSePudo(ValueError):
    """Lo que el dueño escribió no se puede guardar; el texto dice por qué."""


def _negocio_editable() -> dict:
    """
    El contenido del negocio en curso, listo para cambiarle algo.

    Si todavía no tiene el suyo (lee el negocio.toml del repositorio), se
    parte de ese archivo, igual que el editor de contenido. Guardar solo
    `{"avisos": …}` lo dejaría sin menú ni textos: con `negocio_config`
    puesto, el archivo deja de contar.
    """
    import copy
    from app.core.config_cliente import leer_negocio_toml
    from app.core import tenencia

    session = database.get_session()
    try:
        fila = session.query(database.Client).filter_by(id=tenencia.actual()).first()
        return copy.deepcopy((fila.negocio_config if fila else None)
                             or leer_negocio_toml())
    finally:
        session.close()


def _guardar_negocio(negocio: dict):
    from app.core import tenencia

    client_id = tenencia.actual()
    session = database.get_session()
    try:
        session.query(database.Client).filter_by(id=client_id).update(
            {"negocio_config": negocio})
        session.commit()
    finally:
        session.close()
    config.olvidar(client_id)


def guardar_correo_dueno(correo: str):
    """A dónde le llegan al dueño los avisos que no son de ningún área."""
    correo = (correo or "").strip()
    if correo and ("@" not in correo or " " in correo or len(correo) > 120):
        raise NoSePudo("Ese correo no parece bien escrito.")
    negocio = _negocio_editable()
    negocio.setdefault("avisos", {})["correo_dueno"] = correo
    _guardar_negocio(negocio)


def opciones_del_menu() -> list:
    """`[(id, título)]` del menú principal: lo que se le puede dar a un área."""
    return [(o["id"], o.get("title") or o["id"])
            for o in (config.NEED_OPTIONS or []) if o.get("id")]


def guardar_area(area_id: str | None, nombre: str, correo: str,
                 opciones: list, usuario: str, clave: str) -> str:
    """
    Crea un área con su usuario, o cambia una que ya existe. Devuelve su id.

    `area_id` vacío = área nueva. La clave vacía en un área que ya tiene
    usuario = no se toca. Levanta `NoSePudo` con el motivo, en palabras del
    dueño, si algo no cuadra — y en ese caso no se guarda NADA.
    """
    from app.core import acceso, tenencia
    from app.core.config_cliente import identificador_de_area

    nombre = " ".join((nombre or "").split())[:40]
    correo = (correo or "").strip()
    usuario = acceso.normalizar_usuario(usuario)
    validas = {i for i, _ in opciones_del_menu()}
    opciones = [o for o in (opciones or []) if o in validas]

    if not nombre:
        raise NoSePudo("Ponle un nombre al área: Ventas, Soporte…")
    if "@" not in correo or " " in correo:
        raise NoSePudo("El área necesita un correo: es por donde se entera "
                       "de que le llegó un cliente.")
    if not opciones:
        raise NoSePudo("Marca al menos una opción del menú: es lo que decide "
                       "qué conversaciones le llegan a esta área.")

    negocio = _negocio_editable()
    destinos = list((negocio.get("avisos") or {}).get("destinos") or [])
    # Las guardadas de antes no traen id: se les pone el mismo que les da
    # la configuración, para que el usuario siga encontrando su área.
    for i, d in enumerate(destinos):
        d["id"] = identificador_de_area(d.get("id"), d.get("nombre"), i)

    existente = next((d for d in destinos if d.get("id") == area_id), None)
    if area_id and existente is None:
        raise NoSePudo("Esa área ya no existe. Recarga la página.")

    if existente is None:
        if len(destinos) >= config.MAX_DESTINOS_AVISOS:
            raise NoSePudo(f"Tu plan incluye {config.MAX_DESTINOS_AVISOS} "
                           f"áreas y ya las tienes todas.")
        area_id = identificador_de_area(None, nombre, len(destinos))
        ocupados = {d["id"] for d in destinos}
        base, n = area_id, 2
        while area_id in ocupados:
            area_id, n = f"{base}-{n}", n + 1

    # El usuario primero: es lo único que puede chocar con otro negocio (el
    # nombre de usuario es único en toda la plataforma). Si choca, no se ha
    # tocado nada todavía.
    client_id = tenencia.actual()
    ya = usuario_de_area(area_id)
    try:
        if ya is None:
            if not usuario:
                raise NoSePudo("El área necesita un usuario para entrar al panel.")
            if len(clave or "") < 8:
                raise NoSePudo("La clave del área necesita 8 caracteres o más.")
            acceso.crear_usuario(client_id, usuario, clave, rol="area",
                                 area_id=area_id)
        else:
            if usuario and usuario != ya["usuario"]:
                acceso.renombrar_usuario(client_id, ya["id"], usuario)
            if clave:
                if len(clave) < 8:
                    raise NoSePudo("La clave nueva necesita 8 caracteres o más.")
                acceso.crear_usuario(client_id, usuario or ya["usuario"], clave,
                                     area_id=area_id)
    except acceso.UsuarioOcupado as e:
        raise NoSePudo(str(e)) from e

    nueva = {"id": area_id, "nombre": nombre, "correo": correo,
             "opciones": opciones}
    if existente is None:
        destinos.append(nueva)
    else:
        existente.clear()
        existente.update(nueva)

    negocio.setdefault("avisos", {})["destinos"] = destinos
    _guardar_negocio(negocio)
    return area_id


def quitar_area(area_id: str) -> bool:
    """
    Quita un área y le cierra el acceso a su usuario.

    El usuario se da de baja, no se borra: así su nombre no queda libre
    para otro por sorpresa, y el super-admin puede borrarlo si hace falta.
    Las conversaciones que eran de esa área vuelven al dueño solas: un
    `Contact.area` que no es de ningún área existente no cuenta.
    """
    negocio = _negocio_editable()
    destinos = list((negocio.get("avisos") or {}).get("destinos") or [])
    from app.core.config_cliente import identificador_de_area
    quedan = [d for i, d in enumerate(destinos)
              if identificador_de_area(d.get("id"), d.get("nombre"), i) != area_id]
    if len(quedan) == len(destinos):
        return False

    negocio.setdefault("avisos", {})["destinos"] = quedan
    _guardar_negocio(negocio)

    session = database.get_session()
    try:
        session.query(database.PanelUser).filter_by(area_id=area_id).update(
            {"active": False, "area_id": None, "rol": "area"})
        session.commit()
    finally:
        session.close()
    return True
