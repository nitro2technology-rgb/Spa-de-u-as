"""
LAS RUTAS DEL PANEL DE LA BARBERÍA
===================================
    /entrar, /recuperar, /restablecer/{token}, /cambiar-contrasena, /salir
    /b/{sección}     el panel del dueño, del administrador y de recepción
    /yo/dia, /yo/ganancias     el del barbero

La sesión es la del panel del bot —el mismo pase y la misma cookie—, así
que el middleware de `app/main.py` resuelve el inquilino de estas rutas
como el de cualquier otra. Lo propio de aquí es la puerta:

    ⚠️  CADA RUTA DE /b Y /yo PASA POR `_exigir`.

Que comprueba, en cada petición y en este orden: que la persona sigue
existiendo y activa, que su barbería tiene el módulo y no está pausada
(`cuentas.persona_de`), que no le toca cambiar una clave temporal, y que
su rol puede ver esa pantalla (`permisos`). Una ruta nueva que se salte
`_exigir` le enseña a un barbero la caja de todas las sedes, sin error.
"""

import re
from urllib.parse import quote, unquote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from datetime import date, datetime, time

from app.barberia import (agenda, cuentas, formato, nomina, operacion, paginas, pantallas,
                          pantallas_agenda, permisos, reportes)
from app.barberia import modelos as m
from app.barberia import sedes as sedes_mod
from app.barberia import usuarios as usuarios_mod
from app.core import acceso, planes, tenencia
from app.web.admin_ui import COOKIE, _exige_https

router = APIRouter(tags=["barberia"])


# ── La sesión ────────────────────────────────────────────────────────

def _pase(request: Request):
    return acceso.leer_pase(request.cookies.get(COOKIE, ""),
                            tenencia.actual_o_none())


def _poner_sesion(respuesta, request: Request, client_id: int, user_id: int,
                  recordar: bool, vence_absoluto: float | None = None):
    texto, max_age = cuentas.pase_para(client_id, user_id, recordar, vence_absoluto)
    respuesta.set_cookie(COOKIE, texto, httponly=True, samesite="lax",
                         secure=_exige_https(request), max_age=max_age)
    return respuesta


def _renovar(respuesta, request: Request, pase: acceso.Pase):
    """Estira la sesión por uso, sin pasar del tope ni cambiar si es recordada."""
    return _poner_sesion(respuesta, request, pase.client_id, pase.user_id,
                         cuentas.es_recordado(pase), pase.vence_absoluto)


def _cerrar_sesion(respuesta, request: Request):
    # Los mismos atributos que al crearla, o el navegador borra "otra".
    respuesta.delete_cookie(COOKIE, httponly=True, samesite="lax",
                            secure=_exige_https(request))
    return respuesta


def _ir(ruta: str):
    return RedirectResponse(ruta, status_code=303)


def _exigir(request: Request, seccion: str | None = None, barbero: bool = False):
    """
    `(persona, pase, None)` si puede ver la pantalla; si no,
    `(None, None, respuesta)` con la redirección que toque.
    """
    pase = _pase(request)
    persona = cuentas.persona_de(pase)
    if persona is None:
        respuesta = _ir("/entrar?aviso=sesion" if request.cookies.get(COOKIE)
                        else "/entrar")
        return None, None, _cerrar_sesion(respuesta, request)

    if persona.clave_temporal:
        return None, None, _ir("/cambiar-contrasena")

    if barbero != persona.es_barbero:
        return None, None, _ir(permisos.destino_inicial(persona.rol))

    if seccion is not None and not permisos.puede_ver_seccion(persona, seccion):
        return None, None, _ir(permisos.destino_inicial(persona.rol))

    return persona, pase, None


def _hoy():
    """
    El día de hoy en la zona de la barbería. Todas las sedes de hoy son de
    Colombia; cuando una sede traiga otra zona (`barb_sedes.zona_horaria`),
    este es el sitio que la tiene que leer.
    """
    return formato.hoy_en("America/Bogota")


# ══════════════════════════════════════════════════════════════════════
#  ENTRAR
# ══════════════════════════════════════════════════════════════════════

AVISOS_ENTRADA = {
    "clave": "Contraseña guardada. Entra con ella.",
    "salir": "Saliste del panel.",
}
SESION_TERMINADA = "Tu sesión terminó. Entra de nuevo."


@router.get("/entrar", response_class=HTMLResponse)
def entrar_form(request: Request, aviso: str = ""):
    persona = cuentas.persona_de(_pase(request))
    if persona is not None:
        return _ir("/cambiar-contrasena" if persona.clave_temporal
                   else permisos.destino_inicial(persona.rol))
    if aviso == "sesion":
        return HTMLResponse(paginas.pagina_entrar(error=SESION_TERMINADA))
    return HTMLResponse(paginas.pagina_entrar(aviso=AVISOS_ENTRADA.get(aviso, "")))


def _intentos(n: int) -> str:
    return f"Te queda {n} intento." if n == 1 else f"Te quedan {n} intentos."


@router.post("/entrar")
def entrar(request: Request, usuario: str = Form(""), clave: str = Form(""),
           recordar: str = Form("")):
    recordado = bool(recordar)
    r = cuentas.entrar(usuario, clave, request)

    def de_nuevo(error: str, **extra):
        return HTMLResponse(paginas.pagina_entrar(
            error=error, usuario=usuario, recordar=recordado, **extra))

    if r.tipo == cuentas.VACIO:
        return de_nuevo("Escribe tu usuario y tu contraseña.",
                        vacio_usuario=not cuentas.normalizar(usuario),
                        vacio_clave=not clave)
    if r.tipo == cuentas.INCORRECTO:
        return de_nuevo(f"Usuario o contraseña incorrectos. {_intentos(r.restantes)}")
    if r.tipo == cuentas.BLOQUEADO:
        return de_nuevo(f"Bloqueamos el acceso por {cuentas.MINUTOS_BLOQUEO} "
                        f"minutos. El dueño puede restablecer tu contraseña "
                        f"desde Usuarios.")
    if r.tipo == cuentas.DESACTIVADO:
        return de_nuevo("Este usuario está desactivado. Pídele al dueño que lo "
                        "vuelva a activar.")
    if r.tipo == cuentas.PAUSADO:
        return de_nuevo("El panel no está disponible por ahora. Habla con el dueño.")
    if r.tipo == cuentas.SIN_MODULO:
        return de_nuevo("Tu plan no incluye el panel de la barbería. Habla con "
                        "Nitro2Tech para agregarlo.")
    if r.tipo == cuentas.PAUSADO_DUENO:
        return HTMLResponse(_pagina_pausada(r.client_id))

    # Entró. La cookie se estampa con el inquilino de QUIEN ENTRÓ: sin
    # subdominios, el middleware puso el cliente por defecto porque todavía
    # no había pase que leer (igual que en `admin_ui.login`).
    with tenencia.usar(r.client_id):
        persona = cuentas.persona_de(r.pase)
        destino = ("/cambiar-contrasena" if persona and persona.clave_temporal
                   else permisos.destino_inicial(r.rol))
        return _poner_sesion(_ir(destino), request, r.client_id,
                             r.pase.user_id, recordado)


def _pagina_pausada(client_id: int) -> str:
    from app.core import cobros, planes
    from app.web.panel_plan import enlace_comprobante

    datos = tenencia.por_id(client_id)
    negocio = datos.nombre if datos else ""
    c = cobros.cuenta_de(client_id)
    soporte = (f"https://wa.me/{planes.WHATSAPP_COBROS}?text="
               + quote(f"Hola, necesito ayuda con la cuenta de {negocio}."))
    return paginas.pagina_pausada(
        negocio=negocio,
        plan=c.plan.nombre if c else "",
        pendiente=c.precio if c else 0,
        motivo=(datos.fila.get("pausado_por") if datos else "") or "",
        enlace_pago=enlace_comprobante(negocio),
        enlace_soporte=soporte,
        medios=list(planes.MEDIOS_DE_PAGO))


@router.api_route("/salir", methods=["GET", "POST"])
def salir(request: Request):
    return _cerrar_sesion(_ir("/entrar?aviso=salir"), request)


# ── Olvidé mi contraseña ─────────────────────────────────────────────

@router.get("/entrar/recuperar", response_class=HTMLResponse)
def recuperar_form():
    return HTMLResponse(paginas.pagina_recuperar())


@router.post("/recuperar", response_class=HTMLResponse)
def recuperar(request: Request, identificador: str = Form("")):
    if not cuentas.normalizar(identificador):
        return HTMLResponse(paginas.pagina_recuperar(
            error="Escribe tu usuario, correo o celular."))
    # Quien está bloqueado por intentos no manda correos: sería una forma
    # de seguir probando nombres. La pantalla dice lo mismo igual.
    if not cuentas.FRENO_IP.bloqueado(request):
        cuentas.pedir_recuperacion(identificador)
    return HTMLResponse(paginas.pagina_enviado(identificador.strip()))


@router.get("/restablecer/{token}", response_class=HTMLResponse)
def restablecer_form(token: str):
    if cuentas.enlace_valido(token) is None:
        return HTMLResponse(paginas.pagina_enlace_vencido(), status_code=410)
    return HTMLResponse(paginas.pagina_clave(token=token))


@router.post("/restablecer/{token}", response_class=HTMLResponse)
def restablecer(token: str, nueva: str = Form(""), repetida: str = Form("")):
    if cuentas.enlace_valido(token) is None:
        return HTMLResponse(paginas.pagina_enlace_vencido(), status_code=410)
    error = cuentas.restablecer(token, nueva, repetida)
    if error:
        return HTMLResponse(paginas.pagina_clave(error=error, token=token))
    return _ir("/entrar?aviso=clave")


# ── Cambiar la contraseña ────────────────────────────────────────────

@router.get("/cambiar-contrasena", response_class=HTMLResponse)
def cambiar_form(request: Request):
    persona = cuentas.persona_de(_pase(request))
    if persona is None:
        return _ir("/entrar")
    return HTMLResponse(paginas.pagina_clave(
        pedir_actual=not persona.clave_temporal, temporal=persona.clave_temporal))


@router.post("/cambiar-contrasena", response_class=HTMLResponse)
def cambiar(request: Request, actual: str = Form(""), nueva: str = Form(""),
            repetida: str = Form("")):
    pase = _pase(request)
    persona = cuentas.persona_de(pase)
    if persona is None:
        return _ir("/entrar")
    error = cuentas.cambiar_clave(persona, actual, nueva, repetida)
    if error:
        return HTMLResponse(paginas.pagina_clave(
            error=error, pedir_actual=not persona.clave_temporal,
            temporal=persona.clave_temporal))
    destino = permisos.destino_inicial(persona.rol) + "?aviso=clave"
    return _renovar(_ir(destino), request, pase)


# ══════════════════════════════════════════════════════════════════════
#  EL PANEL
# ══════════════════════════════════════════════════════════════════════

AVISOS_PANEL = {"clave": "Contraseña guardada."}

# El aviso de "hecho" viaja en una cookie de un solo uso y no en la
# dirección: con `?aviso=texto` cualquiera podría armar un enlace que le
# enseñe a un dueño un aviso falso dentro de su propio panel.
AVISO_COOKIE = "barb_aviso"


def _hecho(ruta: str, request: Request, texto: str):
    respuesta = _ir(ruta)
    respuesta.set_cookie(AVISO_COOKIE, quote(texto), max_age=60, httponly=True,
                         samesite="lax", secure=_exige_https(request))
    return respuesta


def _aviso(request: Request, clave: str = "") -> str:
    guardado = request.cookies.get(AVISO_COOKIE)
    return unquote(guardado) if guardado else AVISOS_PANEL.get(clave, "")


def _responder(html: str, request: Request, pase, status_code: int = 200):
    respuesta = _renovar(HTMLResponse(html, status_code=status_code), request, pase)
    if request.cookies.get(AVISO_COOKIE):
        respuesta.delete_cookie(AVISO_COOKIE, httponly=True, samesite="lax",
                                secure=_exige_https(request))
    return respuesta


def _sede_de(persona, valor) -> int | None:
    texto = str(valor or "")
    return permisos.sede_permitida(persona, int(texto) if texto.isdigit() else None)


def _volver(seccion: str, sede_id=None, **extra) -> str:
    partes = [f"{k}={v}" for k, v in (("sede", sede_id), *extra.items()) if v]
    return f"/b/{seccion}" + ("?" + "&".join(partes) if partes else "")


@router.get("/b")
def panel_inicio(request: Request):
    persona = cuentas.persona_de(_pase(request))
    if persona is None:
        return _ir("/entrar")
    return _ir(permisos.destino_inicial(persona.rol))


def _fecha(texto: str, hoy: date) -> date:
    try:
        return date.fromisoformat(texto) if texto else hoy
    except ValueError:
        return hoy


def _sede_agenda(persona, sede_id):
    """La agenda es de UNA sede: con "Todas", la primera de las suyas."""
    if sede_id:
        return sede_id, dict(persona.sedes)[sede_id]
    return persona.sedes[0] if persona.sedes else (None, "")


def _contenido(persona, clave: str, sede_id, periodo: str, hoy, filtro: str = "",
               errores: dict | None = None, fecha: str = "") -> str:
    """El cuerpo de una sección, con sus datos."""
    errores = errores or {}
    if clave == "agenda":
        sid, nombre = _sede_agenda(persona, sede_id)
        if sid is None:
            return '<p class="tenue">No tienes sedes asignadas.</p>'
        return pantallas_agenda.agenda(agenda.agenda_dia(sid, _fecha(fecha, hoy)), sid, nombre,
                                       len(persona.sedes) > 1, sede_id is None, hoy)
    if clave == "resumen":
        return pantallas.resumen(reportes.resumen(persona, sede_id, periodo, hoy),
                                 periodo, sede_id)
    if clave == "caja":
        return pantallas.caja(operacion.cajas_de(persona, sede_id, hoy), errores.get("caja"))
    if clave == "equipo":
        return pantallas.equipo(nomina.filas(persona, sede_id, hoy),
                                persona.rol == m.DUENO, sede_id)
    if clave == "gastos":
        desde, hasta = formato.periodo("mes", hoy)
        return pantallas.gastos(operacion.gastos_de(sede_id, persona.sedes, desde, hasta),
                                persona.sedes, sede_id, errores.get("gasto", ""),
                                errores.get("valores"))
    if clave == "actividad":
        return pantallas.actividad(reportes.actividad(persona, filtro or "todo", hoy),
                                   filtro or "todo", sede_id)
    if clave == "sedes":
        fila = tenencia.por_id(persona.client_id).fila
        return pantallas.sedes(reportes.sedes(hoy), operacion.tabla_de_precios(persona.sedes),
                               persona.sedes, reportes.uso_del_plan(),
                               (planes.cupo_de_sedes(fila), planes.cupo_de_barberos(fila)),
                               errores.get("precios", ""))
    if clave == "usuarios":
        return pantallas.usuarios(usuarios_mod.listar(persona, sede_id, hoy), sede_id)
    return ""


def _insignias(persona, hoy) -> dict:
    insignias = {}
    if permisos.puede_ver_seccion(persona, "caja"):
        abiertas = sum(1 for c in operacion.cajas_de(persona, None, hoy) if c.get("abierta"))
        if abiertas:
            insignias["caja"] = (formato.plural(abiertas, "abierta"), "lila")
    if permisos.puede_ver_seccion(persona, "actividad"):
        n = reportes.cuantas_hoy(persona, hoy)
        if n:
            insignias["actividad"] = (f"{n} hoy", "rojo")
    return insignias


def _acciones(persona, clave: str, sede_id) -> str:
    if clave == "usuarios":
        return (f'<a class="boton boton-primario" href="{paginas.e(_volver("usuarios", sede_id, nuevo=1))}">'
                f'Agregar usuario</a>')
    if clave == "equipo":
        return (f'<a class="boton boton-secundario" href="{paginas.e(_volver("equipo", sede_id, adelanto=1))}">'
                f'Registrar adelanto</a>')
    return ""


def _pintar(request, persona, pase, clave: str, sede_id=None, periodo: str = "hoy",
            filtro: str = "", superpuesto: str = "", errores: dict | None = None,
            aviso: str = "", status_code: int = 200, fecha: str = ""):
    hoy = _hoy()
    # La Agenda enseña en su subtítulo el día que se está mirando.
    dia_titulo = _fecha(fecha, hoy) if clave == "agenda" else hoy
    pagina = paginas.pagina_panel(
        persona, permisos.POR_CLAVE[clave], sede_id, periodo, dia_titulo, aviso=aviso,
        contenido=_contenido(persona, clave, sede_id, periodo, hoy, filtro, errores, fecha),
        insignias=_insignias(persona, hoy), superpuesto=superpuesto,
        acciones=_acciones(persona, clave, sede_id))
    return _responder(pagina, request, pase, status_code)


@router.get("/b/{seccion}", response_class=HTMLResponse)
def panel(request: Request, seccion: str, sede: str = "", periodo: str = "hoy",
          aviso: str = "", filtro: str = "", nuevo: str = "", editar: str = "",
          quitar: str = "", adelanto: str = "", esquema: str = "", nueva: str = "",
          fecha: str = "", cita: str = "", bloquear: str = "", bloqueo: str = "",
          barbero: str = "", servicio: str = "", horario: str = ""):
    if seccion not in permisos.POR_CLAVE:
        return HTMLResponse("No encontrado", status_code=404)

    persona, pase, desvio = _exigir(request, seccion)
    if desvio:
        return desvio

    sede_id = _sede_de(persona, sede)
    periodo = periodo if periodo in ("hoy", "semana", "mes") else "hoy"
    cerrar = _volver(seccion, sede_id)
    superpuesto = ""

    if seccion == "usuarios":
        if nuevo:
            superpuesto = pantallas.cajon_usuario(
                persona, None, cerrar, temporal=cuentas.clave_temporal_para(persona.negocio))
        elif editar.isdigit() or quitar.isdigit():
            fila = next((u for u in usuarios_mod.listar(persona, None, _hoy())["filas"]
                         if u["id"] == int(editar or quitar) and not u["es_yo"]), None)
            if fila is not None:
                superpuesto = (pantallas.cajon_usuario(persona, fila, cerrar) if editar
                               else pantallas.dialogo_quitar(fila, cerrar))
    elif seccion == "equipo":
        if adelanto:
            superpuesto = pantallas.cajon_adelanto(
                nomina.filas(persona, sede_id, _hoy())["filas"], cerrar)
        elif esquema.isdigit() and persona.rol == m.DUENO:
            datos = nomina.datos_esquema(int(esquema))
            if datos:
                superpuesto = pantallas.cajon_esquema(datos, cerrar)
    elif seccion == "sedes" and nueva:
        superpuesto = pantallas.cajon_sede_nueva()
    elif seccion == "sedes" and horario.isdigit():
        sid = _sede_de(persona, horario)
        if sid:
            superpuesto = pantallas_agenda.cajon_horario(
                {"id": sid, "nombre": dict(persona.sedes)[sid]}, agenda.horario_de_sede(sid))
    elif seccion == "agenda":
        superpuesto = _superpuesto_agenda(persona, sede_id, fecha, cita, nueva, bloquear,
                                          bloqueo, barbero, servicio)

    return _pintar(request, persona, pase, seccion, sede_id, periodo, filtro,
                   superpuesto, aviso=_aviso(request, aviso), fecha=fecha)


def _superpuesto_agenda(persona, sede_id, fecha: str, cita: str = "", nueva: str = "",
                        bloquear: str = "", bloqueo: str = "", barbero: str = "",
                        servicio: str = "", error: str = "", cliente: str = "",
                        valores: dict | None = None) -> str:
    sid, _ = _sede_agenda(persona, sede_id)
    if sid is None:
        return ""
    dia = _fecha(fecha, _hoy())
    cerrar = _volver("agenda", sede_id, fecha=fecha)
    if cita.isdigit():
        c = agenda.cita(int(cita))
        if c and permisos.sede_permitida(persona, c["sede_id"]):
            return pantallas_agenda.cajon_cita(c, cerrar, True, error)
    if bloqueo.isdigit():
        bl = next((b for b in agenda.agenda_dia(sid, dia)["bloqueos"] if b["id"] == int(bloqueo)),
                  None)
        if bl:
            return pantallas_agenda.cajon_bloqueo(bl, cerrar)
    if bloquear:
        return pantallas_agenda.cajon_bloquear(sid, dia, agenda.barberos_de(sid), cerrar, error,
                                               valores)
    if nueva:
        servicios = operacion.servicios_de_sede(sid)
        servicio = servicio or (str(servicios[0]["id"]) if servicios else "")
        barberos = agenda.barberos_de(sid)
        barbero = barbero if barbero in {str(i) for i, _ in barberos} else ""
        huecos = {}
        if servicio.isdigit():
            try:
                minutos = agenda.duracion(sid, int(servicio))
                nombres = dict(barberos)
                huecos = {t: nombres.get(b, "")
                          for t, b in agenda.huecos_de(sid, int(barbero) if barbero else None,
                                                       dia, minutos).items()}
            except operacion.Error:
                huecos = {}
        return pantallas_agenda.cajon_nueva_cita(sid, dia, barberos, servicios, barbero,
                                                 servicio, huecos, cerrar, error, cliente)
    return ""


# ── Agenda ───────────────────────────────────────────────────────────

def _volver_a_la_cita(cita_id: int) -> str:
    c = agenda.cita(cita_id)
    if c is None:
        return "/b/agenda"
    return _volver("agenda", c["sede_id"], fecha=formato.a_local(c["inicio"]).date().isoformat())


@router.post("/b/agenda/cita")
def cita_nueva(request: Request, sede_id: str = Form(""), barbero: str = Form(""),
               servicio: str = Form(""), inicio: str = Form(""), cliente: str = Form("")):
    persona, pase, desvio = _exigir(request, "agenda")
    if desvio:
        return desvio
    sid = _sede_de(persona, sede_id)
    fecha = ""
    try:
        try:
            momento = datetime.fromisoformat(inicio)
        except ValueError:
            raise operacion.Error("Elige una hora de la lista.") from None
        fecha = momento.astimezone(formato.zona()).date().isoformat()
        if sid is None or not servicio.isdigit():
            raise operacion.Error("Elige el servicio y la hora.")
        agenda.reservar(sid, int(barbero) if barbero.isdigit() else None, int(servicio), momento,
                        origen=m.PANEL, cliente_id=operacion.cliente_para(cliente),
                        persona=persona)
    except operacion.Error as ex:
        superpuesto = _superpuesto_agenda(persona, sid, fecha, nueva="1", barbero=barbero,
                                          servicio=servicio, error=str(ex), cliente=cliente)
        return _pintar(request, persona, pase, "agenda", sid, superpuesto=superpuesto,
                       status_code=400, fecha=fecha)
    return _hecho(_volver("agenda", sid, fecha=fecha), request, "Cita agendada.")


@router.post("/b/agenda/cita/{cita_id}/estado")
def cita_estado(request: Request, cita_id: int, estado: str = Form("")):
    persona, pase, desvio = _exigir(request, "agenda")
    if desvio:
        return desvio
    volver = _volver_a_la_cita(cita_id)
    try:
        cliente = agenda.cambiar_estado(persona, cita_id, estado)
    except operacion.Error as ex:
        return _hecho(volver, request, str(ex))
    texto = {m.CONFIRMADA: f"Cita de {cliente} confirmada.",
             m.NO_ASISTIO: f"{cliente} quedó como “no vino”.",
             m.EN_CURSO: f"Empezaste con {cliente}."}.get(estado, "Listo.")
    return _hecho(volver, request, texto)


@router.post("/b/agenda/cita/{cita_id}/cancelar")
def cita_cancelar(request: Request, cita_id: int, motivo: str = Form("")):
    persona, pase, desvio = _exigir(request, "agenda")
    if desvio:
        return desvio
    volver = _volver_a_la_cita(cita_id)
    try:
        agenda.cancelar(cita_id, motivo.strip(), persona)
    except operacion.Error as ex:
        return _hecho(volver, request, str(ex))
    return _hecho(volver, request, "Cita cancelada. El horario quedó libre.")


def _hora(texto: str) -> time:
    try:
        return time.fromisoformat(texto)
    except ValueError:
        raise operacion.Error("Escribe las horas como 12:00.") from None


@router.post("/b/agenda/bloqueo")
def bloqueo_nuevo(request: Request, sede_id: str = Form(""), personal_id: str = Form(""),
                  fecha: str = Form(""), desde: str = Form(""), hasta: str = Form(""),
                  motivo: str = Form("")):
    persona, pase, desvio = _exigir(request, "agenda")
    if desvio:
        return desvio
    sid = _sede_de(persona, sede_id)
    try:
        if sid is None:
            raise operacion.Error("Elige una de tus sedes.")
        agenda.bloquear(persona, sid, int(personal_id) if personal_id.isdigit() else None,
                        _fecha(fecha, _hoy()), _hora(desde), _hora(hasta), motivo)
    except operacion.Error as ex:
        valores = {"personal_id": personal_id, "fecha": fecha, "desde": desde, "hasta": hasta,
                   "motivo": motivo}
        superpuesto = _superpuesto_agenda(persona, sid, fecha, bloquear="1", error=str(ex),
                                          valores=valores)
        return _pintar(request, persona, pase, "agenda", sid, superpuesto=superpuesto,
                       status_code=400, fecha=fecha)
    return _hecho(_volver("agenda", sid, fecha=fecha), request, "Horario bloqueado.")


@router.post("/b/agenda/bloqueo/{bloqueo_id}/quitar")
def bloqueo_quitar(request: Request, bloqueo_id: int):
    persona, pase, desvio = _exigir(request, "agenda")
    if desvio:
        return desvio
    try:
        agenda.quitar_bloqueo(persona, bloqueo_id)
    except operacion.Error as ex:
        return _hecho("/b/agenda", request, str(ex))
    return _hecho("/b/agenda", request, "Bloqueo quitado.")


@router.post("/b/clientes/{cliente_id}/nota")
def cliente_nota(request: Request, cliente_id: int, nota: str = Form(""),
                 volver: str = Form("/b/agenda")):
    persona, pase, desvio = _exigir(request, "agenda")
    if desvio:
        return desvio
    # Solo a la agenda: `volver` lo manda el navegador, y una dirección de
    # fuera convertiría esto en un redireccionador abierto.
    volver = volver if volver.startswith("/b/agenda") else "/b/agenda"
    try:
        operacion.guardar_nota_cliente(cliente_id, nota)
    except operacion.Error as ex:
        return _hecho(volver, request, str(ex))
    return _hecho(volver, request, "Nota guardada.")


@router.post("/b/sedes/{sede_id}/horario")
async def sede_horario(request: Request, sede_id: int):
    persona, pase, desvio = _exigir(request, "sedes")
    if desvio:
        return desvio
    formulario = await request.form()
    try:
        dias = {}
        for dia in range(7):
            if formulario.get(f"abierto_{dia}"):
                dias[dia] = (_hora(str(formulario.get(f"desde_{dia}", ""))),
                             _hora(str(formulario.get(f"hasta_{dia}", ""))))
            else:
                dias[dia] = None
        agenda.guardar_horario(persona, sede_id, dias)
    except operacion.Error as ex:
        sid = _sede_de(persona, sede_id)
        superpuesto = (pantallas_agenda.cajon_horario(
            {"id": sid, "nombre": dict(persona.sedes)[sid]}, agenda.horario_de_sede(sid), str(ex))
            if sid else "")
        return _pintar(request, persona, pase, "sedes", superpuesto=superpuesto, status_code=400)
    return _hecho("/b/sedes", request, "Horario guardado.")


# ── Caja ─────────────────────────────────────────────────────────────

@router.post("/b/caja/abrir")
def caja_abrir(request: Request, sede_id: str = Form(""), base: str = Form("")):
    persona, pase, desvio = _exigir(request, "caja")
    if desvio:
        return desvio
    sid = _sede_de(persona, sede_id)
    try:
        operacion.abrir_caja(persona, sid, base)
    except operacion.Error as ex:
        return _pintar(request, persona, pase, "caja", errores={"caja": {sid: str(ex)}},
                       status_code=400)
    return _hecho("/b/caja", request, "Caja abierta.")


@router.post("/b/caja/{caja_id}/cerrar")
def caja_cerrar(request: Request, caja_id: int, contado: str = Form("")):
    persona, pase, desvio = _exigir(request, "caja")
    if desvio:
        return desvio
    try:
        dif = operacion.cerrar_caja(persona, caja_id, contado)
    except operacion.Error as ex:
        errores = {c["sede_id"]: str(ex) for c in operacion.cajas_de(persona, None, _hoy())
                   if c.get("caja") == caja_id}
        return _pintar(request, persona, pase, "caja", errores={"caja": errores},
                       status_code=400)
    if dif == 0:
        texto = "Caja cerrada. Cuadra exacto."
    elif dif < 0:
        texto = f"Caja cerrada. Falta {formato.pesos(-dif)}."
    else:
        texto = f"Caja cerrada. Sobra {formato.pesos(dif)}."
    return _hecho("/b/caja", request, texto)


# ── Gastos ───────────────────────────────────────────────────────────

@router.post("/b/gastos")
def gasto_nuevo(request: Request, descripcion: str = Form(""), monto: str = Form(""),
                categoria: str = Form("Insumos"), tipo: str = Form("VARIABLE"),
                sede_id: str = Form(""), de_la_caja: str = Form("")):
    persona, pase, desvio = _exigir(request, "gastos")
    if desvio:
        return desvio
    try:
        operacion.registrar_gasto(persona, _sede_de(persona, sede_id), descripcion, monto,
                                  categoria, tipo, bool(de_la_caja), _hoy())
    except operacion.Error as ex:
        valores = {"descripcion": descripcion, "monto": monto, "categoria": categoria,
                   "tipo": tipo, "sede_id": sede_id, "de_la_caja": de_la_caja}
        return _pintar(request, persona, pase, "gastos",
                       errores={"gasto": str(ex), "valores": valores}, status_code=400)
    return _hecho("/b/gastos", request, "Gasto registrado.")


# ── Barberos y pagos ─────────────────────────────────────────────────

@router.post("/b/equipo/{personal_id}/aprobar")
def liquidacion_aprobar(request: Request, personal_id: int):
    persona, pase, desvio = _exigir(request, "equipo")
    if desvio:
        return desvio
    try:
        nomina.aprobar(persona, personal_id, _hoy())
    except operacion.Error as ex:
        return _hecho("/b/equipo", request, str(ex))
    return _hecho("/b/equipo", request, "Liquidación aprobada.")


@router.post("/b/equipo/liquidacion/{liquidacion_id}/pagar")
def liquidacion_pagar(request: Request, liquidacion_id: int):
    persona, pase, desvio = _exigir(request, "equipo")
    if desvio:
        return desvio
    try:
        nomina.marcar_pagada(persona, liquidacion_id)
    except operacion.Error as ex:
        return _hecho("/b/equipo", request, str(ex))
    return _hecho("/b/equipo", request, "Marcada como pagada.")


@router.post("/b/equipo/adelanto")
def adelanto_nuevo(request: Request, personal_id: str = Form(""), monto: str = Form(""),
                   nota: str = Form("")):
    persona, pase, desvio = _exigir(request, "equipo")
    if desvio:
        return desvio
    try:
        nomina.registrar_adelanto(persona, int(personal_id or 0), monto, nota, _hoy())
    except (operacion.Error, ValueError) as ex:
        cajon = pantallas.cajon_adelanto(
            nomina.filas(persona, None, _hoy())["filas"], "/b/equipo", str(ex),
            {"personal_id": personal_id, "monto": monto, "nota": nota})
        return _pintar(request, persona, pase, "equipo", superpuesto=cajon, status_code=400)
    return _hecho("/b/equipo", request, "Adelanto registrado.")


@router.post("/b/equipo/{personal_id}/esquema")
def esquema_guardar(request: Request, personal_id: int, esquema: str = Form(""),
                    porcentaje: str = Form(""), sueldo_fijo: str = Form(""),
                    alquiler: str = Form(""), meta: str = Form("")):
    persona, pase, desvio = _exigir(request, "equipo")
    if desvio:
        return desvio
    try:
        nomina.guardar_esquema(persona, personal_id, esquema, porcentaje, sueldo_fijo,
                               alquiler, meta)
    except operacion.Error as ex:
        datos = nomina.datos_esquema(personal_id)
        if datos is None:
            return _hecho("/b/equipo", request, str(ex))
        datos.update(esquema_pago=esquema or datos["esquema_pago"], porcentaje=porcentaje,
                     sueldo_fijo=sueldo_fijo, alquiler=alquiler, meta=meta)
        return _pintar(request, persona, pase, "equipo",
                       superpuesto=pantallas.cajon_esquema(datos, "/b/equipo", str(ex)),
                       status_code=400)
    return _hecho("/b/equipo", request, "Esquema guardado.")


# ── Sedes y precios ──────────────────────────────────────────────────

@router.post("/b/sedes/{sede_id}/estado")
def sede_estado(request: Request, sede_id: int, activo: str = Form("")):
    persona, pase, desvio = _exigir(request, "sedes")
    if desvio:
        return desvio
    try:
        nombre = sedes_mod.cambiar_estado(persona, sede_id, activo == "1")
    except operacion.Error as ex:
        return _hecho("/b/sedes", request, str(ex))
    texto = (f"{nombre} está abierta al público." if activo == "1"
             else f"{nombre} quedó pausada.")
    return _hecho("/b/sedes", request, texto)


@router.post("/b/sedes/precios")
async def precios_guardar(request: Request):
    persona, pase, desvio = _exigir(request, "sedes")
    if desvio:
        return desvio
    formulario = await request.form()
    cambios = 0
    try:
        for clave, valor in formulario.items():
            partes = clave.split("_")
            if (len(partes) != 3 or partes[0] != "precio" or not str(valor).strip()
                    or not (partes[1].isdigit() and partes[2].isdigit())):
                continue
            if operacion.cambiar_precio(persona, int(partes[1]), int(partes[2]), valor):
                cambios += 1
    except operacion.Error as ex:
        return _pintar(request, persona, pase, "sedes", errores={"precios": str(ex)},
                       status_code=400)
    return _hecho("/b/sedes", request,
                  "Precios guardados." if cambios else "No cambió ningún precio.")


@router.post("/b/sedes/servicio")
def servicio_nuevo(request: Request, nombre: str = Form(""), precio: str = Form("")):
    persona, pase, desvio = _exigir(request, "sedes")
    if desvio:
        return desvio
    try:
        operacion.crear_servicio(persona, nombre, precio)
    except operacion.Error as ex:
        return _pintar(request, persona, pase, "sedes", errores={"precios": str(ex)},
                       status_code=400)
    return _hecho("/b/sedes", request, "Servicio agregado.")


@router.post("/b/sedes/nueva")
def sede_nueva(request: Request, nombre: str = Form(""), direccion: str = Form("")):
    persona, pase, desvio = _exigir(request, "sedes")
    if desvio:
        return desvio
    try:
        sedes_mod.crear(persona, nombre, direccion)
    except (operacion.Error, cuentas.CupoLleno) as ex:
        cajon = pantallas.cajon_sede_nueva(str(ex), {"nombre": nombre, "direccion": direccion})
        return _pintar(request, persona, pase, "sedes", superpuesto=cajon, status_code=400)
    return _hecho("/b/sedes", request, "Sede agregada.")


# ── Usuarios ─────────────────────────────────────────────────────────

# La temporal que se enseñó en el formulario, si tiene la forma de una
# ("Filo-4827"). Si no, se genera otra: nunca se guarda sin mirar lo que
# mande el navegador.
TEMPORAL_VALIDA = re.compile(r"^[A-Za-z0-9]{1,12}-\d{4}$")


def _valores_usuario(nombre, usuario, contacto, rol, sedes) -> dict:
    return {"nombre": nombre, "usuario": usuario, "contacto": contacto, "rol": rol,
            "sedes": [x for x in sedes if x.isdigit()]}


@router.post("/b/usuarios")
def usuario_nuevo(request: Request, nombre: str = Form(""), usuario: str = Form(""),
                  contacto: str = Form(""), rol: str = Form(m.BARBERO),
                  sedes: list[str] = Form([]), temporal: str = Form("")):
    persona, pase, desvio = _exigir(request, "usuarios")
    if desvio:
        return desvio
    temporal = temporal if TEMPORAL_VALIDA.match(temporal or "") else \
        cuentas.clave_temporal_para(persona.negocio)
    correo, telefono = usuarios_mod._contacto(contacto)
    try:
        cuentas.crear_persona(persona.client_id, nombre, usuario, rol,
                              [int(x) for x in sedes if x.isdigit()],
                              correo=correo or "", telefono=telefono or "",
                              clave=temporal, actor=persona.nombre, exigir_cambio=True)
    except (ValueError, cuentas.CupoLleno) as ex:
        cajon = pantallas.cajon_usuario(persona, None, "/b/usuarios", temporal=temporal,
                                        error=str(ex),
                                        valores=_valores_usuario(nombre, usuario, contacto,
                                                                 rol, sedes))
        return _pintar(request, persona, pase, "usuarios", superpuesto=cajon, status_code=400)
    return _hecho("/b/usuarios", request,
                  f"Usuario creado. Compártele @{acceso.normalizar_usuario(usuario)} "
                  f"y la contraseña temporal.")


@router.post("/b/usuarios/{personal_id}")
def usuario_editar(request: Request, personal_id: int, nombre: str = Form(""),
                   usuario: str = Form(""), contacto: str = Form(""),
                   rol: str = Form(m.BARBERO), sedes: list[str] = Form([])):
    persona, pase, desvio = _exigir(request, "usuarios")
    if desvio:
        return desvio
    try:
        usuarios_mod.editar(persona, personal_id, nombre, usuario, contacto, rol,
                            [int(x) for x in sedes if x.isdigit()])
    except operacion.Error as ex:
        fila = next((u for u in usuarios_mod.listar(persona, None, _hoy())["filas"]
                     if u["id"] == personal_id), None)
        cajon = pantallas.cajon_usuario(persona, fila, "/b/usuarios", error=str(ex),
                                        valores=_valores_usuario(nombre, usuario, contacto,
                                                                 rol, sedes))
        return _pintar(request, persona, pase, "usuarios", superpuesto=cajon, status_code=400)
    return _hecho("/b/usuarios", request, "Cambios guardados.")


@router.post("/b/usuarios/{personal_id}/acceso")
def usuario_acceso(request: Request, personal_id: int, activo: str = Form("")):
    persona, pase, desvio = _exigir(request, "usuarios")
    if desvio:
        return desvio
    try:
        texto = usuarios_mod.cambiar_acceso(persona, personal_id, activo == "1")
    except operacion.Error as ex:
        texto = str(ex)
    return _hecho("/b/usuarios", request, texto)


@router.post("/b/usuarios/{personal_id}/quitar")
def usuario_quitar(request: Request, personal_id: int):
    persona, pase, desvio = _exigir(request, "usuarios")
    if desvio:
        return desvio
    try:
        texto = usuarios_mod.quitar(persona, personal_id)
    except operacion.Error as ex:
        texto = str(ex)
    return _hecho("/b/usuarios", request, texto)


@router.post("/b/usuarios/{personal_id}/restablecer")
def usuario_restablecer(request: Request, personal_id: int):
    persona, pase, desvio = _exigir(request, "usuarios")
    if desvio:
        return desvio
    try:
        temporal = usuarios_mod.restablecer(persona, personal_id)
    except operacion.Error as ex:
        return _hecho("/b/usuarios", request, str(ex))
    fila = next((u for u in usuarios_mod.listar(persona, None, _hoy())["filas"]
                 if u["id"] == personal_id), None)
    return _pintar(request, persona, pase, "usuarios",
                   superpuesto=pantallas.cajon_usuario(persona, fila, "/b/usuarios",
                                                       restablecida=temporal))


# ══════════════════════════════════════════════════════════════════════
#  EL BARBERO
# ══════════════════════════════════════════════════════════════════════

@router.get("/yo")
def yo_inicio():
    return _ir("/yo/dia")


def _pintar_yo(request, persona, pase, vista: str, superpuesto: str = "",
               aviso: str = "", status_code: int = 200):
    hoy = _hoy()
    if vista == "dia":
        cuerpo = pantallas.barbero_dia(
            operacion.servicios_del_dia(persona.personal_id, hoy),
            pantallas_agenda.barbero_citas(agenda.dia_del_barbero(persona.personal_id, hoy)))
    else:
        cuerpo = pantallas.barbero_ganancias(nomina.ganancias(persona.personal_id, hoy), hoy)
    pagina = paginas.pagina_barbero(persona, vista, hoy,
                                    nomina.hoy_llevas(persona.personal_id, hoy), cuerpo,
                                    superpuesto=superpuesto, aviso=aviso)
    return _responder(pagina, request, pase, status_code)


def _hoja_registrar(persona, sede_id=None, error: str = "", valores: dict | None = None,
                    cita_id: int | None = None) -> str:
    cita = agenda.cita(cita_id) if cita_id else None
    if cita and (cita["barbero_id"] != persona.personal_id
                 or cita["estado"] not in agenda.ACTIVAS):
        cita = None
    if cita:
        sede_id = cita["sede_id"]
    sede_id = sede_id or (persona.sedes[0][0] if persona.sedes else None)
    return pantallas.hoja_registrar(persona.sedes, sede_id,
                                    operacion.servicios_de_sede(sede_id) if sede_id else [],
                                    nomina.porcentaje_de(persona.personal_id), error, valores,
                                    cita)


@router.get("/yo/{vista}", response_class=HTMLResponse)
def yo(request: Request, vista: str, aviso: str = "", registrar: str = "",
       anular: str = "", sede: str = "", cita: str = ""):
    if vista not in ("dia", "ganancias"):
        return HTMLResponse("No encontrado", status_code=404)

    persona, pase, desvio = _exigir(request, barbero=True)
    if desvio:
        return desvio

    superpuesto = ""
    if vista == "dia" and registrar:
        superpuesto = _hoja_registrar(persona, _sede_de(persona, sede),
                                      cita_id=int(cita) if cita.isdigit() else None)
    elif vista == "dia" and anular.isdigit():
        hecho = next((h for h in operacion.servicios_del_dia(persona.personal_id, _hoy())
                      if h["id"] == int(anular) and not h["anulada"]), None)
        if hecho:
            superpuesto = pantallas.hoja_anular(hecho)
    return _pintar_yo(request, persona, pase, vista, superpuesto, _aviso(request, aviso))


@router.post("/yo/servicios")
def yo_registrar(request: Request, sede_id: str = Form(""), servicios: list[str] = Form([]),
                 metodo: str = Form(""), efectivo: str = Form(""), propina: str = Form("0"),
                 cliente: str = Form(""), cita_id: str = Form("")):
    persona, pase, desvio = _exigir(request, barbero=True)
    if desvio:
        return desvio
    sid = _sede_de(persona, sede_id)
    try:
        cita = int(cita_id) if cita_id.isdigit() else None
        if cita is not None:
            datos = agenda.cita(cita)
            sid = datos["sede_id"] if datos else sid
        _, parte = operacion.cobrar(persona, sid, [int(x) for x in servicios if x.isdigit()],
                                    metodo, propina, efectivo, cliente, cita_id=cita)
    except operacion.Error as ex:
        valores = {"servicios": [x for x in servicios if x.isdigit()], "metodo": metodo,
                   "efectivo": efectivo, "propina": propina, "cliente": cliente}
        return _pintar_yo(request, persona, pase, "dia",
                          _hoja_registrar(persona, sid, str(ex), valores,
                                          int(cita_id) if cita_id.isdigit() else None),
                          status_code=400)
    return _hecho("/yo/dia", request, f"Servicio registrado. Ganaste {formato.pesos(parte)}.")


@router.post("/yo/servicios/{cita_id}/anular")
def yo_anular(request: Request, cita_id: int, motivo: str = Form("")):
    persona, pase, desvio = _exigir(request, barbero=True)
    if desvio:
        return desvio
    try:
        operacion.anular(persona, cita_id, motivo, _hoy())
    except operacion.Error as ex:
        hecho = next((h for h in operacion.servicios_del_dia(persona.personal_id, _hoy())
                      if h["id"] == cita_id), None)
        if hecho is None:
            return _hecho("/yo/dia", request, str(ex))
        return _pintar_yo(request, persona, pase, "dia",
                          pantallas.hoja_anular(hecho, str(ex)), status_code=400)
    return _hecho("/yo/dia", request, "Servicio anulado. El dueño lo verá en Actividad.")


@router.post("/yo/citas/{cita_id}/{accion}")
def yo_cita(request: Request, cita_id: int, accion: str):
    """Empezar o "no vino", desde la tarjeta de su siguiente cita."""
    persona, pase, desvio = _exigir(request, barbero=True)
    if desvio:
        return desvio
    estado = {"empezar": m.EN_CURSO, "no-vino": m.NO_ASISTIO}.get(accion)
    if estado is None:
        return HTMLResponse("No encontrado", status_code=404)
    try:
        cliente = agenda.cambiar_estado(persona, cita_id, estado)
    except operacion.Error as ex:
        return _hecho("/yo/dia", request, str(ex))
    texto = (f"Empezaste con {cliente}." if estado == m.EN_CURSO
             else f"{cliente} quedó como “no vino”.")
    return _hecho("/yo/dia", request, texto)
