"""
LA PANTALLA "SEDES" (6.2.8 del handoff)
========================================
Abrir o pausar una sede al público y agregar una nueva dentro del cupo del
plan. Los precios por sede están en `operacion.py` (catálogo).

Pausar una sede no borra nada: sus cajas, cobros y precios se quedan. Los
horarios y bloqueos llegan con la agenda en la Fase 2.
"""

from app.barberia import cuentas, permisos
from app.barberia import modelos as m
from app.barberia.operacion import Error, _session


def cambiar_estado(persona: permisos.Persona, sede_id: int, activo: bool) -> str:
    """Abre o pausa una sede. Devuelve su nombre."""
    if not permisos.sede_permitida(persona, sede_id):
        raise Error("Esa sede no es tuya.")
    s = _session()
    try:
        sede = s.get(m.Sede, sede_id)
        sede.activo = activo
        s.commit()
        nombre = sede.nombre
    finally:
        s.close()
    cuentas.registrar("SEDE", f"{'abrió' if activo else 'pausó'} la sede {nombre}",
                      persona=persona, sede_id=sede_id, tabla="barb_sedes",
                      registro_id=sede_id)
    return nombre


def crear(persona: permisos.Persona, nombre: str, direccion: str) -> int:
    """Una sede nueva, dentro del cupo (`cuentas.crear_sede` lo comprueba)."""
    if persona.rol != m.DUENO:
        raise Error("Solo el dueño agrega sedes.")
    nombre = " ".join((nombre or "").split())
    if not nombre:
        raise Error("Escribe el nombre de la sede.")
    sede_id = cuentas.crear_sede(persona.client_id, nombre[:100], (direccion or "").strip()[:200])
    cuentas.registrar("SEDE", f"agregó la sede {nombre}", persona=persona, sede_id=sede_id,
                      tabla="barb_sedes", registro_id=sede_id)
    return sede_id
