"""
LA PANTALLA "USUARIOS" (6.2.9 del handoff)
==========================================
Quién puede entrar al panel y qué ve. Solo el dueño la usa
(`permisos.SECCIONES_POR_ROL`), y aquí se vuelve a comprobar: la puerta es
el servidor, no la barra lateral.

El alta está en `cuentas.crear_persona` (la usa también el super-admin).
Aquí va lo demás:

  · editar: nombre, usuario, contacto, rol y sedes;
  · el interruptor de Acceso (desactiva sin tocar nada más);
  · "Quitar": borrado LÓGICO (`eliminado_en`). La fila se queda porque la
    actividad y los cobros la referencian;
  · restablecer la contraseña: una temporal nueva, que se exige cambiar.

El dueño no se puede desactivar ni quitar a sí mismo: se quedaría fuera
de su propia barbería sin nadie que lo pudiera arreglar.
"""

from sqlalchemy import func

from app.barberia import cuentas, formato, permisos
from app.barberia import modelos as m
from app.barberia.operacion import Error, _session
from app.core import acceso, database, planes, tenencia
from app.core.equipo import ROL_BARBERIA


def _solo_dueno(persona: permisos.Persona):
    if persona.rol != m.DUENO:
        raise Error("Solo el dueño administra los usuarios.")


def listar(persona: permisos.Persona, sede_id: int | None, hoy) -> dict:
    _solo_dueno(persona)
    nombres_sede = dict(persona.sedes)
    s = _session()
    try:
        gente = (s.query(m.Personal, database.PanelUser)
                 .outerjoin(database.PanelUser,
                            database.PanelUser.id == m.Personal.panel_user_id)
                 .filter(m.Personal.eliminado_en.is_(None))
                 .order_by(m.Personal.id).all())
        sedes_de = {}
        for pid, sid in s.query(m.PersonalSede.personal_id, m.PersonalSede.sede_id):
            sedes_de.setdefault(pid, []).append(sid)
        filas = []
        for p, u in gente:
            suyas = sedes_de.get(p.id, [])
            if sede_id is not None and sede_id not in suyas and p.rol != m.DUENO:
                continue
            todas = set(suyas) >= set(nombres_sede) or p.rol == m.DUENO
            filas.append({
                "id": p.id, "nombre": p.nombre, "usuario": u.email if u else "",
                "rol": p.rol, "rol_nombre": permisos.ROLES[p.rol],
                "sedes_ids": suyas,
                "sedes": "Todas" if todas else ", ".join(nombres_sede.get(i, "") for i in suyas),
                "contacto": p.correo or (p.telefono and _telefono_legible(p.telefono)) or "",
                "correo": p.correo or "", "telefono": p.telefono or "",
                "ultimo": formato.cuando(m.en_utc(u.ultimo_acceso), hoy)
                          if u and u.ultimo_acceso else "Nunca",
                "activo": bool(p.activo and u and u.active),
                "es_yo": p.id == persona.personal_id,
                "iniciales": permisos.iniciales(p.nombre),
            })
        barberos = sum(1 for p, _ in gente if p.rol == m.BARBERO)
        desactivados = sum(1 for f in filas if not f["activo"])
    finally:
        s.close()
    cupo = planes.cupo_de_barberos(tenencia.por_id(persona.client_id).fila)
    return {"filas": filas, "con_acceso": sum(1 for f in filas if f["activo"]),
            "barberos": barberos, "cupo_barberos": cupo, "desactivados": desactivados}


def _telefono_legible(digitos: str) -> str:
    """3001112233 → "300 111 2233"."""
    if len(digitos) == 10:
        return f"{digitos[:3]} {digitos[3:6]} {digitos[6:]}"
    return digitos


def editar(persona: permisos.Persona, personal_id: int, nombre: str, usuario: str,
           contacto: str, rol: str, sedes: list[int]) -> None:
    """Guarda los cambios de alguien. Mismas validaciones y orden que el alta."""
    _solo_dueno(persona)
    nombre = (nombre or "").strip()
    usuario = acceso.normalizar_usuario(usuario)
    if not nombre:
        raise Error("Falta el nombre.")
    if not usuario:
        raise Error("Falta el usuario con el que va a entrar.")
    if not cuentas.USUARIO_VALIDO.match(usuario):
        raise Error("El usuario solo puede llevar letras sin tilde, números, punto y "
                    "guion bajo.")
    if rol not in m.ROLES:
        raise Error("Elige un rol.")

    s = _session()
    try:
        p = s.get(m.Personal, personal_id)
        if p is None or p.eliminado_en is not None:
            raise Error("Esa persona ya no está.")
        if p.id == persona.personal_id and rol != m.DUENO:
            raise Error("No puedes quitarte el rol de dueño a ti mismo.")
        u = s.get(database.PanelUser, p.panel_user_id)
        ocupado = acceso.quien_usa(usuario, excepto_id=u.id if u else None)
        if ocupado is not None:
            raise Error(f"Ya hay alguien con el usuario @{usuario}. Prueba con otro.")

        todas = [i for (i,) in s.query(m.Sede.id)]
        sedes = todas if rol == m.DUENO else [i for i in (sedes or []) if i in todas]
        if not sedes:
            raise Error("Elige al menos una sede.")
        if rol == m.BARBERO and p.rol != m.BARBERO:
            barberos = (s.query(func.count(m.Personal.id))
                        .filter(m.Personal.rol == m.BARBERO,
                                m.Personal.eliminado_en.is_(None)).scalar())
            cupo = planes.cupo_de_barberos(tenencia.por_id(persona.client_id).fila)
            if barberos >= cupo:
                raise Error(f"Llegaste a los {cupo} barberos de tu plan. Amplía el plan "
                            f"para agregar más.")

        p.nombre = nombre[:100]
        p.rol = rol
        correo, telefono = _contacto(contacto)
        p.correo, p.telefono = correo, telefono
        if u is not None:
            u.email = usuario
            u.rol = "dueno" if rol == m.DUENO else ROL_BARBERIA
        s.query(m.PersonalSede).filter_by(personal_id=p.id).delete()
        for sid in sedes:
            s.add(m.PersonalSede(personal_id=p.id, sede_id=sid))
        s.commit()
    finally:
        s.close()
    cuentas.registrar("USUARIO", f"editó el usuario @{usuario}", persona=persona,
                      tabla="barb_personal", registro_id=personal_id)


def _contacto(texto: str) -> tuple[str | None, str | None]:
    """"Correo o celular": un solo campo que se guarda donde toca."""
    texto = (texto or "").strip()
    if "@" in texto:
        return texto.lower()[:120], None
    return None, cuentas.telefono_normalizado(texto)


def cambiar_acceso(persona: permisos.Persona, personal_id: int, activo: bool) -> str:
    """El interruptor. Devuelve el aviso: "{nombre} ya no puede entrar." / "…otra vez."."""
    _solo_dueno(persona)
    if personal_id == persona.personal_id:
        raise Error("No puedes apagarte el acceso a ti mismo.")
    s = _session()
    try:
        p = s.get(m.Personal, personal_id)
        if p is None or p.eliminado_en is not None:
            raise Error("Esa persona ya no está.")
        # El cupo del plan lo ocupa quien no se ha QUITADO, esté activo o no
        # (ver `cuentas.crear_persona`): apagar el acceso no libera un
        # puesto, y por eso encenderlo tampoco lo gasta.
        p.activo = activo
        u = s.get(database.PanelUser, p.panel_user_id)
        if u is not None:
            u.active = activo
        s.commit()
        nombre = p.nombre
    finally:
        s.close()
    verbo = "le devolvió el acceso a" if activo else "le quitó el acceso a"
    cuentas.registrar("USUARIO", f"{verbo} {nombre}", persona=persona,
                      tabla="barb_personal", registro_id=personal_id)
    return f"{nombre} puede entrar otra vez." if activo else f"{nombre} ya no puede entrar."


def quitar(persona: permisos.Persona, personal_id: int) -> str:
    """Borrado lógico. El nombre de usuario queda libre para otro."""
    _solo_dueno(persona)
    if personal_id == persona.personal_id:
        raise Error("No puedes quitarte a ti mismo.")
    s = _session()
    try:
        p = s.get(m.Personal, personal_id)
        if p is None or p.eliminado_en is not None:
            raise Error("Esa persona ya no está.")
        p.eliminado_en = m.ahora()
        p.activo = False
        u = s.get(database.PanelUser, p.panel_user_id)
        if u is not None:
            u.active = False
            # Se libera el nombre: el siguiente "daniel.c" tiene que poder
            # usarlo. El original queda en Actividad.
            u.email = f"{u.email}~quitado~{p.id}"
        s.commit()
        nombre = p.nombre
    finally:
        s.close()
    cuentas.registrar("USUARIO", f"quitó a {nombre}", persona=persona,
                      tabla="barb_personal", registro_id=personal_id)
    return f"{nombre} ya no tiene usuario."


def restablecer(persona: permisos.Persona, personal_id: int) -> str:
    """Una contraseña temporal nueva. Se la exige cambiar al entrar."""
    _solo_dueno(persona)
    temporal = cuentas.clave_temporal_para(persona.negocio)
    s = _session()
    try:
        p = s.get(m.Personal, personal_id)
        if p is None or p.eliminado_en is not None:
            raise Error("Esa persona ya no está.")
        u = s.get(database.PanelUser, p.panel_user_id)
        u.password_hash = acceso.hash_clave(temporal)
        p.clave_temporal = True
        s.commit()
        nombre = p.nombre
    finally:
        s.close()
    cuentas.registrar("CLAVE", f"le puso una contraseña temporal a {nombre}",
                      persona=persona, tabla="barb_personal", registro_id=personal_id)
    return temporal
