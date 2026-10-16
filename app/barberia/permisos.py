"""
QUIÉN VE QUÉ EN EL PANEL DE LA BARBERÍA
=========================================
La matriz de la §5 del handoff, en un solo sitio. Las rutas preguntan
aquí; la interfaz solo pinta lo que aquí se permite.

    ⚠️  LA PUERTA ES EL SERVIDOR.

Esconder "Usuarios" de la barra no impide escribir /b/usuarios en la
dirección. Por eso cada ruta llama a `puede_ver_seccion` antes de pintar
nada, igual que las del bot llaman a `equipo.puede_ver`.

Dos puertas más, que van antes del rol:

  · el MÓDULO: sin `clients.barberia_contratada`, nadie de ese negocio
    entra a /b ni a /yo, tenga el rol que tenga.
  · la SEDE: un administrador de sede, recepción o un barbero solo ven
    las sedes donde trabajan (`barb_personal_sede`). El dueño, todas.
"""

from typing import NamedTuple

from app.barberia import modelos as m

# Cómo se llama cada rol en pantalla.
ROLES = {
    m.DUENO: "Dueño",
    m.ADMIN: "Administrador de sede",
    m.RECEPCION: "Recepción",
    m.BARBERO: "Barbero",
}

# Lo que dice cada rol en la tarjeta de "Agregar usuario" (6.2.9).
DESCRIPCION_ROL = {
    m.DUENO: "Ve y cambia todo, incluida la nómina y los usuarios.",
    m.ADMIN: "Maneja caja, agenda, gastos y equipo de sus sedes. No ve la nómina.",
    m.RECEPCION: "Registra servicios, cobra y abre o cierra caja. No ve reportes.",
    m.BARBERO: "Solo su agenda, sus servicios y sus ganancias.",
}


class Seccion(NamedTuple):
    clave: str
    etiqueta: str       # en la barra lateral
    titulo: str         # el h2 de la cabecera
    subtitulo: str      # {periodo} se rellena en el resumen
    filtro_sede: bool
    filtro_periodo: bool


# En el orden de la barra lateral (6.2).
SECCIONES = (
    Seccion("resumen", "Resumen", "Resumen", "Cómo va el negocio {periodo}", True, True),
    Seccion("agenda", "Agenda", "Agenda de hoy", "{fecha}", True, False),
    Seccion("caja", "Caja", "Caja de hoy", "Lo que entró y el arqueo de efectivo", True, False),
    Seccion("equipo", "Barberos y pagos", "Barberos y pagos", "{quincena}", True, False),
    Seccion("gastos", "Gastos", "Gastos", "{mes}", True, False),
    Seccion("inventario", "Inventario", "Inventario",
            "Productos para vender y de uso interno", True, False),
    Seccion("actividad", "Actividad", "Actividad",
            "Quién hizo qué. Nada se borra, todo queda aquí.", False, False),
    Seccion("sedes", "Sedes", "Sedes", "Tus locales, horarios y precios", False, False),
    Seccion("usuarios", "Usuarios", "Usuarios",
            "Quién puede entrar al panel y qué puede ver", True, False),
)
POR_CLAVE = {s.clave: s for s in SECCIONES}

# Qué secciones de /b ve cada rol. El barbero no tiene ninguna: su panel
# es /yo.
#
# El ADMINISTRADOR DE SEDE no ve "Barberos y pagos": la §5 del handoff le
# quita "nómina/liquidaciones", y esa sección ES la liquidación quincenal.
# Tampoco Sedes (enseña el cupo del plan) ni Usuarios. Si el dueño del
# producto decide que "equipo de sus sedes" incluye esa pantalla, es
# añadir "equipo" aquí; no hay que tocar nada más.
SECCIONES_POR_ROL = {
    m.DUENO: tuple(s.clave for s in SECCIONES),
    m.ADMIN: ("resumen", "agenda", "caja", "gastos", "inventario", "actividad"),
    # Recepción agenda a quien llama o pasa por el local (Fase 2); el
    # handoff no se lo prohíbe, y sin agenda no podría hacerlo.
    m.RECEPCION: ("agenda", "caja"),
    m.BARBERO: (),
}

# Las cuatro pestañas del celular (6.3), en su orden. Cada rol ve las que
# le toquen de estas.
PESTANAS_CELULAR = (
    ("resumen", "Resumen"),
    ("caja", "Caja"),
    ("equipo", "Pagos"),
    ("actividad", "Actividad"),
)


class Persona(NamedTuple):
    """Quién está usando el panel de la barbería."""
    personal_id: int
    user_id: int
    client_id: int
    nombre: str
    rol: str
    # Las sedes que puede ver, como (id, nombre). Para el dueño, todas.
    sedes: tuple
    clave_temporal: bool
    negocio: str            # el nombre de la barbería
    plan_nombre: str
    con_bot: bool

    @property
    def rol_nombre(self) -> str:
        return ROLES.get(self.rol, self.rol)

    @property
    def es_barbero(self) -> bool:
        return self.rol == m.BARBERO

    @property
    def iniciales(self) -> str:
        return iniciales(self.nombre)

    @property
    def primer_nombre(self) -> str:
        return (self.nombre or "").split(" ")[0]


def iniciales(nombre: str) -> str:
    """"Ricardo Gómez" → "RG"; "Andrés" → "AN"."""
    partes = [p for p in (nombre or "").split() if p]
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[-1][0]).upper()


def secciones_de(persona: Persona) -> tuple:
    return tuple(POR_CLAVE[c] for c in SECCIONES_POR_ROL.get(persona.rol, ()))


def puede_ver_seccion(persona: Persona | None, clave: str) -> bool:
    return persona is not None and clave in SECCIONES_POR_ROL.get(persona.rol, ())


# Quien no ve el Resumen (recepción) no tendría con qué moverse en el
# celular: sus pestañas son las secciones que sí tiene.
PESTANAS_SIN_RESUMEN = (("agenda", "Agenda"), ("caja", "Caja"))


def pestanas_de(persona: Persona) -> tuple:
    lista = PESTANAS_CELULAR if puede_ver_seccion(persona, "resumen") else PESTANAS_SIN_RESUMEN
    return tuple((c, e) for c, e in lista if puede_ver_seccion(persona, c))


def destino_inicial(rol: str) -> str:
    """A dónde llega cada rol al entrar (§5 del handoff)."""
    if rol == m.BARBERO:
        return "/yo/dia"
    if rol == m.RECEPCION:
        return "/b/caja"
    return "/b/resumen"


def sede_permitida(persona: Persona, sede_id: int | None) -> int | None:
    """
    La sede pedida si esta persona la puede ver; si no, None ("Todas" de
    las suyas). Una sede ajena en la dirección no es un error que haya que
    explicar: se ignora.
    """
    if sede_id is None:
        return None
    return sede_id if any(s[0] == sede_id for s in persona.sedes) else None
