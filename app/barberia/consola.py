"""
LA CONSOLA NITRO2TECH PARA BARBERÍAS (6.5 del handoff, lo de la Fase 1)
========================================================================
    /superadmin/barberias

Dar de alta una barbería, cambiarle el plan y los límites, pausarla,
reactivarla, registrar su pago y restablecer la contraseña del dueño.

Entra con la MISMA sesión del super-admin del bot (`superadmin._entrada_valida`)
y, como todo /superadmin, corre SIN inquilino (lo excluye el middleware de
`app/main.py`): mira a todas las barberías. Cuando toca las filas de una
en concreto lo hace con `tenencia.usar(ese_id)`, a mano y a la vista.

El cobro es el de siempre (`app/core/cobros.py`): "Registrar pago" corre la
fecha un mes y reactiva lo que pausó el cobro; una pausa puesta a mano no la
deshace un pago.

LO QUE QUEDA PARA DESPUÉS (no está en esta entrega)
---------------------------------------------------
El Resumen con los KPIs de la plataforma, la pantalla de Cobros propia de
barberías, las reglas de cobro editables, el consumo del bot y "Entrar a su
panel como soporte". Los cobros de todos los clientes siguen en
/superadmin/cobros.
"""

import re
import secrets
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import config
from app.barberia import cuentas, formato
from app.barberia import modelos as m
from app.barberia.paginas import _logo, documento, e
from app.barberia.pantallas import _error, cajon
from app.core import acceso, cobros, database, planes, tenencia

router = APIRouter(prefix="/superadmin/barberias", tags=["consola-barberias"])

DIAS_DE_PRUEBA = 14

MOTIVOS_PAUSA = (("impago", "Falta de pago"), ("pedido", "El cliente lo pidió"),
                 ("revision", "Revisión de la cuenta"))
TEXTO_MOTIVO = dict(MOTIVOS_PAUSA)

FILTROS = (("todas", "Todas"), ("al_dia", "Al día"), ("vence", "Vence pronto"),
           ("gracia", "En gracia"), ("pausadas", "Pausadas"), ("nuevas", "Nuevas"))


# ══════════════════════════════════════════════════════════════════════
#  LOS DATOS
# ══════════════════════════════════════════════════════════════════════

def _estado(fila: dict, hoy) -> tuple[str, str, str, str]:
    """(clave, etiqueta, clase del chip, detalle) de una barbería (tabla de 6.5)."""
    c = cobros.cuenta(fila, hoy)
    if not fila.get("active"):
        dias = (hoy - fila["paused_at"].date()).days if fila.get("paused_at") else 0
        motivo = TEXTO_MOTIVO.get(fila.get("pausado_por") or "", "pausa a mano").lower()
        return ("pausadas", "Pausada", "chip-pausado",
                f"Pausada hace {formato.plural(dias, 'día')}, {motivo}")
    if planes.de(fila).bot and not fila.get("phone_number_id"):
        return ("nuevas", "Instalando bot", "chip-info", "Falta conectar su WhatsApp")
    if c.estado == cobros.SIN_COBRO:
        return ("al_dia", "Sin cobro", "chip-pausado", "No tiene fecha de cobro")
    if not fila.get("ultimo_pago_el") and c.dias is not None and c.dias >= 0:
        return ("nuevas", "En prueba", "chip-marca",
                f"La prueba termina en {formato.plural(c.dias, 'día')}")
    if c.estado == cobros.VENCIDO:
        dias = -c.dias
        return ("gracia", "En gracia", "chip-error",
                f"Vencida hace {formato.plural(dias, 'día')}, se pausa el "
                f"{c.pausa_el.day} de {formato.MESES[c.pausa_el.month - 1]}")
    if c.estado == cobros.POR_VENCER:
        return ("vence", "Vence pronto", "chip-aviso",
                f"Vence en {formato.plural(c.dias, 'día')}")
    return ("al_dia", "Al día", "chip-ok",
            f"Próximo cobro el {c.vence_el.day} de {formato.MESES[c.vence_el.month - 1]}")


def _uso(client_id: int) -> tuple[int, int]:
    """(sedes, barberos) en uso. Con el inquilino de ESA barbería."""
    with tenencia.usar(client_id):
        s = database.get_session()
        try:
            sedes = s.query(m.Sede).count()
            barberos = (s.query(m.Personal).filter(m.Personal.rol == m.BARBERO,
                                                   m.Personal.eliminado_en.is_(None)).count())
            return sedes, barberos
        finally:
            s.close()


def _dueno(client_id: int) -> dict | None:
    with tenencia.usar(client_id):
        s = database.get_session()
        try:
            p = (s.query(m.Personal).filter_by(rol=m.DUENO)
                 .filter(m.Personal.eliminado_en.is_(None)).order_by(m.Personal.id).first())
            if p is None:
                return None
            u = s.get(database.PanelUser, p.panel_user_id)
            return {"id": p.id, "nombre": p.nombre, "usuario": u.email if u else "",
                    "correo": p.correo or "", "telefono": p.telefono or "",
                    "ultimo": u.ultimo_acceso if u else None}
        finally:
            s.close()


def barberias(filtro: str = "todas", q: str = "") -> list[dict]:
    hoy = cobros.hoy()
    q = cuentas.sin_tildes(q or "").lower().strip()
    with tenencia.sin_inquilino():
        s = database.get_session()
        try:
            filas = (s.query(database.Client).filter(database.Client.barberia_contratada.is_(True))
                     .order_by(database.Client.nombre).all())
            filas = [{c.name: getattr(f, c.name) for c in database.Client.__table__.columns}
                     for f in filas]
        finally:
            s.close()

    salida = []
    for f in filas:
        clave, etiqueta, chip, detalle = _estado(f, hoy)
        if filtro != "todas" and filtro != clave:
            continue
        dueno = _dueno(f["id"])
        texto = cuentas.sin_tildes(f"{f['nombre']} {dueno['nombre'] if dueno else ''}").lower()
        if q and q not in texto:
            continue
        sedes, barberos = _uso(f["id"])
        salida.append({
            "id": f["id"], "nombre": f["nombre"], "fila": f, "plan": planes.de(f),
            "precio": planes.precio_de(f), "dueno": dueno,
            "sedes": sedes, "cupo_sedes": planes.cupo_de_sedes(f),
            "barberos": barberos, "cupo_barberos": planes.cupo_de_barberos(f),
            "estado": clave, "etiqueta": etiqueta, "chip": chip, "detalle": detalle,
        })
    return salida


def _slug(nombre: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", cuentas.sin_tildes(nombre).lower()).strip("-") or "barberia"
    base = base[:40]
    with tenencia.sin_inquilino():
        s = database.get_session()
        try:
            slug, n = base, 2
            while s.query(database.Client).filter_by(slug=slug).first():
                slug, n = f"{base}-{n}", n + 1
            return slug
        finally:
            s.close()


def _usuario_libre(nombre: str) -> str:
    base = cuentas.sugerir_usuario(nombre) or "dueno"
    usuario, n = base, 2
    while acceso.quien_usa(usuario) is not None:
        usuario, n = f"{base}{n}", n + 1
    return usuario


def _temporal() -> str:
    return f"Nitro-{secrets.randbelow(9000) + 1000}"


def dar_de_alta(nombre: str, sede: str, dueno: str, correo: str, celular: str,
                plan: str, prueba: bool) -> tuple[int, str, str]:
    """
    Una barbería nueva con su primera sede y el acceso del dueño. Devuelve
    `(client_id, usuario, contraseña temporal)`. Levanta ValueError con el
    texto que se enseña, en el orden del handoff.
    """
    nombre, dueno = " ".join((nombre or "").split()), " ".join((dueno or "").split())
    correo = (correo or "").strip().lower()
    if not nombre:
        raise ValueError("Falta el nombre de la barbería.")
    if not dueno:
        raise ValueError("Falta el nombre del dueño.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", correo):
        raise ValueError("Escribe un correo válido para enviarle el acceso.")
    if plan not in planes.ORDEN_BARBERIA:
        raise ValueError("Elige un plan.")
    with tenencia.sin_inquilino():
        s = database.get_session()
        try:
            ya = (s.query(m.Personal.id).filter(m.Personal.rol == m.DUENO,
                                                m.Personal.correo == correo,
                                                m.Personal.eliminado_en.is_(None)).first())
        finally:
            s.close()
    if ya:
        raise ValueError("Ese correo ya es el dueño de otra barbería.")

    p = planes.PLANES[plan]
    hoy = cobros.hoy()
    s = database.SessionLocal()
    try:
        cliente = database.Client(
            slug=_slug(nombre), nombre=nombre, active=True, plan=plan,
            barberia_contratada=True, bot_contratado=p.bot, ia_contratada=p.ia,
            proveedor_agenda="barberia", business_email=correo,
            vence_el=hoy + timedelta(days=DIAS_DE_PRUEBA) if prueba else hoy)
        s.add(cliente)
        s.commit()
        client_id = cliente.id
    finally:
        s.close()

    usuario, temporal = _usuario_libre(dueno), _temporal()
    with tenencia.usar(client_id):
        cuentas.crear_sede(client_id, (sede or "").strip() or "Principal")
        cuentas.crear_persona(client_id, dueno, usuario, m.DUENO, [], correo=correo,
                              telefono=celular or "", clave=temporal,
                              actor="Nitro2Tech", exigir_cambio=True)
        from app.core import correo as correo_mod
        correo_mod.avisar(
            [correo], f"Tu acceso a {nombre}",
            f"Hola, {dueno.split(' ')[0]}.\n\nYa está listo el panel de {nombre}.\n\n"
            f"Entra en {config.PANEL_URL}/entrar\nUsuario: {usuario}\n"
            f"Contraseña temporal: {temporal}\n\n"
            f"Al entrar te pediremos crear una contraseña propia.")
    tenencia.olvidar(client_id)
    return client_id, usuario, temporal


def _actualizar(client_id: int, **campos) -> None:
    with tenencia.sin_inquilino():
        s = database.get_session()
        try:
            c = s.get(database.Client, client_id)
            for k, v in campos.items():
                setattr(c, k, v)
            s.commit()
        finally:
            s.close()
    config.olvidar(client_id)          # incluye tenencia.olvidar()


def pausar(client_id: int, motivo: str) -> None:
    if motivo not in TEXTO_MOTIVO:
        raise ValueError("Elige por qué la pausas.")
    _actualizar(client_id, active=False, paused_at=database.ahora_utc(), pausado_por=motivo)


def reactivar(client_id: int) -> None:
    _actualizar(client_id, active=True, paused_at=None, pausado_por=None)


def cambiar_plan(client_id: int, plan: str) -> None:
    if plan not in planes.ORDEN_BARBERIA:
        raise ValueError("Ese plan no es de barberías.")
    p = planes.PLANES[plan]
    _actualizar(client_id, plan=plan, bot_contratado=p.bot, ia_contratada=p.ia)


def cambiar_limites(client_id: int, sedes: int, barberos: int) -> None:
    """Lo pactado con ELLA. Nunca por debajo de lo que ya usa."""
    usa_sedes, usa_barberos = _uso(client_id)
    if sedes < usa_sedes or barberos < usa_barberos:
        raise ValueError(f"No puede quedar por debajo de lo que usa: {usa_sedes} sedes "
                         f"y {usa_barberos} barberos.")
    _actualizar(client_id, max_sedes=sedes, max_barberos=barberos)


def restablecer_dueno(client_id: int) -> str:
    dueno = _dueno(client_id)
    if dueno is None:
        raise ValueError("Esa barbería no tiene dueño.")
    temporal = _temporal()
    with tenencia.usar(client_id):
        s = database.get_session()
        try:
            p = s.get(m.Personal, dueno["id"])
            s.get(database.PanelUser, p.panel_user_id).password_hash = acceso.hash_clave(temporal)
            p.clave_temporal = True
            s.commit()
        finally:
            s.close()
        cuentas.registrar("CLAVE", "le puso una contraseña temporal al dueño",
                          actor="Nitro2Tech (soporte)", tabla="barb_personal",
                          registro_id=dueno["id"])
    return temporal


# ══════════════════════════════════════════════════════════════════════
#  LAS PANTALLAS
# ══════════════════════════════════════════════════════════════════════

AVISO_COOKIE = "consola_aviso"


def _pagina(cuerpo: str, superpuesto: str = "", aviso: str = "") -> str:
    return documento("Barberías", f"""
<div class="panel">
  <aside class="lateral lateral-consola">
    <div class="lateral-marca">{_logo("consola-logo")}
      <span class="lateral-plan">Consola de la plataforma</span></div>
    <nav class="lateral-nav" aria-label="Secciones">
      <a class="lateral-item activo" href="/superadmin/barberias" aria-current="page">
        <span class="lateral-ini" aria-hidden="true">Ba</span><span class="lateral-texto">Barberías</span></a>
      <a class="lateral-item" href="/superadmin/barberias?nueva=1">
        <span class="lateral-ini" aria-hidden="true">Nu</span><span class="lateral-texto">Nueva barbería</span></a>
      <a class="lateral-item" href="/superadmin">
        <span class="lateral-ini" aria-hidden="true">Bo</span><span class="lateral-texto">Consola del bot</span></a>
    </nav>
    <div class="lateral-pie"><div class="lateral-cuenta"><a href="/superadmin/logout">Salir</a></div></div>
  </aside>
  <header class="movil-cabecera movil-consola">
    <div class="movil-fila"><div class="movil-marca">{_logo("consola-logo")}
      <span class="lateral-plan">Consola de la plataforma</span></div>
      <a class="movil-salir" href="/superadmin/barberias?nueva=1">Nueva</a>
      <a class="movil-salir" href="/superadmin/logout">Salir</a></div>
  </header>
  <main class="principal">
    <header class="cabecera">
      <div class="cabecera-titulos"><h1>Barberías</h1>
        <p>Alta, plan, límites, pausa y cobro de cada barbería</p></div>
      <div class="cabecera-filtros"><a class="boton boton-primario" href="/superadmin/barberias?nueva=1">Nueva barbería</a></div>
    </header>
    <div class="contenido">{cuerpo}</div>
  </main>
</div>
{superpuesto}""", clase_body="cuerpo-panel", aviso=aviso)


def _listado(filas: list[dict], filtro: str, q: str, todas: list[dict]) -> str:
    cuenta = {c: sum(1 for f in todas if f["estado"] == c) for c, _ in FILTROS}
    cuenta["todas"] = len(todas)
    chips = "".join(
        f'<a class="chip-sel{" activo" if c == filtro else ""}" '
        f'href="/superadmin/barberias?filtro={c}{"&amp;q=" + quote(q) if q else ""}">{e(t)} · {cuenta[c]}</a>'
        for c, t in FILTROS)
    filas_html = "".join(f"""
      <a class="tabla-fila consola-fila{' apagada' if f['estado'] == 'pausadas' else ''}"
         href="/superadmin/barberias?ficha={f['id']}&amp;filtro={e(filtro)}">
        <div class="celda-persona"><span class="avatar avatar-cuadrado">{e(cuentas_iniciales(f['nombre']))}</span>
          <span><span class="celda-fuerte">{e(f['nombre'])}</span>
          <span class="celda-nota">{e(f['dueno']['nombre'] if f['dueno'] else 'Sin dueño')}</span></span></div>
        <div data-rotulo="Plan">{e(f['plan'].nombre)}</div>
        <div data-rotulo="Sedes">{f['sedes']} de {f['cupo_sedes']}</div>
        <div data-rotulo="Barberos"{' class="aviso-texto"' if f['barberos'] >= f['cupo_barberos'] else ''}>{f['barberos']} de {f['cupo_barberos']}</div>
        <div data-rotulo="Mensualidad">{e(formato.pesos(f['precio']))}</div>
        <div data-rotulo="Estado" class="celda-estado"><span class="chip {f['chip']}">{e(f['etiqueta'])}</span>
          <span class="celda-nota celda-corta">{e(f['detalle'])}</span></div>
      </a>""" for f in filas) or '<p class="tenue tabla-vacia">Ninguna barbería coincide con la búsqueda.</p>'
    return f"""
      <form class="consola-buscar" method="get" action="/superadmin/barberias">
        <input type="hidden" name="filtro" value="{e(filtro)}">
        <input class="entrada-texto" name="q" value="{e(q)}" placeholder="Buscar por barbería o dueño"
               aria-label="Buscar">
      </form>
      <div class="chips">{chips}</div>
      <section class="tarjeta tabla-tarjeta">
        <div class="tabla-cabeza consola-fila"><span>Barbería</span><span>Plan</span><span>Sedes</span>
          <span>Barberos</span><span>Mensualidad</span><span>Estado</span></div>
        {filas_html}
      </section>"""


def cuentas_iniciales(nombre: str) -> str:
    from app.barberia.permisos import iniciales
    return iniciales(nombre)


def _ficha(f: dict, cerrar: str, extra: str = "", error: str = "") -> str:
    fila, dueno = f["fila"], f["dueno"]
    activa = fila.get("active")
    acciones = f"""
      <div class="consola-acciones">
        <form method="post" action="/superadmin/barberias/{f['id']}/pago">
          <button class="boton boton-oscuro" type="submit">Registrar pago</button></form>
        {f'<a class="boton boton-destructivo" href="{cerrar}&amp;pausar={f["id"]}">Pausar cuenta</a>' if activa else
         f'<form method="post" action="/superadmin/barberias/{f["id"]}/reactivar"><button class="boton boton-primario" type="submit">Reactivar cuenta</button></form>'}
        <form method="post" action="/superadmin/barberias/{f['id']}/restablecer-dueno">
          <button class="boton boton-secundario" type="submit">Restablecer contraseña del dueño</button></form>
      </div>"""
    planes_html = "".join(
        f'<label class="opcion-rol"><input type="radio" name="plan" value="{c}"'
        f'{" checked" if f["plan"].codigo == c else ""}><span><strong>{e(planes.PLANES[c].nombre)}</strong>'
        f'<span class="tenue">{e(formato.pesos(planes.PLANES[c].precio))} al mes · '
        f'{formato.plural(planes.PLANES[c].sedes, 'sede')}, {formato.plural(planes.PLANES[c].barberos, 'barbero')}</span></span></label>'
        for c in planes.ORDEN_BARBERIA)
    modulos = (f'Gestión: incluida · Bot de WhatsApp: {"sí" if f["plan"].bot else "no incluido"} · '
               f'IA: {"sí" if f["plan"].ia else "no incluida"}')
    ultimo = (f'{formato.pesos(fila.get("ultimo_pago_monto") or 0)} el '
              f'{formato.fecha_corta(fila["ultimo_pago_el"])}' if fila.get("ultimo_pago_el") else "Ninguno todavía")
    datos_dueno = (f"""
        <div class="fila-dato"><span>Nombre</span><span>{e(dueno['nombre'])}</span></div>
        <div class="fila-dato"><span>Usuario</span><span>@{e(dueno['usuario'])}</span></div>
        <div class="fila-dato"><span>Correo</span><span>{e(dueno['correo'] or '—')}</span></div>
        <div class="fila-dato"><span>Último ingreso</span><span>{e(formato.cuando(m.en_utc(dueno['ultimo']), cobros.hoy()) if dueno['ultimo'] else 'Nunca')}</span></div>"""
                   if dueno else '<p class="tenue">Sin dueño.</p>')
    cuerpo = f"""
      <p><span class="chip {f['chip']}">{e(f['etiqueta'])}</span> <span class="tenue">{e(f['detalle'])}</span></p>
      {extra}
      {_error(error)}
      {acciones}
      <section class="consola-bloque"><h3>Dueño</h3>{datos_dueno}</section>
      <form class="consola-bloque" method="post" action="/superadmin/barberias/{f['id']}/plan">
        <h3>Plan</h3>
        <fieldset class="grupo">{planes_html}</fieldset>
        <p class="tenue">{e(modulos)}</p>
        <button class="boton boton-secundario" type="submit">Cambiar plan</button>
      </form>
      <form class="consola-bloque" method="post" action="/superadmin/barberias/{f['id']}/limites">
        <h3>Límites</h3>
        <div class="dos-columnas">
          <label class="campo"><span class="campo-etiqueta">Sedes (usa {f['sedes']})</span>
            <input class="entrada-texto" name="sedes" type="number" min="{f['sedes']}" value="{f['cupo_sedes']}"></label>
          <label class="campo"><span class="campo-etiqueta">Barberos (usa {f['barberos']})</span>
            <input class="entrada-texto" name="barberos" type="number" min="{f['barberos']}" value="{f['cupo_barberos']}"></label>
        </div>
        <button class="boton boton-secundario" type="submit">Guardar límites</button>
      </form>
      <section class="consola-bloque"><h3>Cobro</h3>
        <div class="fila-dato"><span>Mensualidad</span><span>{e(formato.pesos(f['precio']))}</span></div>
        <div class="fila-dato"><span>Pagado hasta</span><span>{e(formato.fecha_corta(fila['vence_el'])) if fila.get('vence_el') else 'Sin fecha'}</span></div>
        <div class="fila-dato"><span>Último pago</span><span>{e(ultimo)}</span></div>
      </section>"""
    pie = f'<a class="boton boton-secundario" href="{e(cerrar)}">Cerrar</a><span></span>'
    return cajon(f["nombre"], cuerpo, pie, cerrar,
                 subtitulo=f"Cliente desde {formato.MESES[fila['created_at'].month - 1]} "
                           f"{fila['created_at'].year}" if fila.get("created_at") else "",
                 ancho=540)


def _cajon_nueva(error: str = "", v: dict | None = None) -> str:
    v = v or {}
    plan = v.get("plan", planes.BARBERIA)
    planes_html = "".join(
        f'<label class="opcion-rol"><input type="radio" name="plan" value="{c}"{" checked" if plan == c else ""}>'
        f'<span><strong>{e(planes.PLANES[c].nombre)}</strong><span class="tenue">'
        f'{e(formato.pesos(planes.PLANES[c].precio))} al mes · {formato.plural(planes.PLANES[c].sedes, "sede")}, '
        f'{formato.plural(planes.PLANES[c].barberos, "barbero")}'
        f'{" · instalación " + formato.pesos(planes.PLANES[c].instalacion) if planes.PLANES[c].instalacion else ""}'
        f'</span></span></label>' for c in planes.ORDEN_BARBERIA)
    cuerpo = f"""
      <label class="campo"><span class="campo-etiqueta">Nombre de la barbería</span>
        <input class="entrada-texto" name="nombre" value="{e(v.get('nombre', ''))}" maxlength="100" autofocus></label>
      <label class="campo"><span class="campo-etiqueta">Primera sede</span>
        <input class="entrada-texto" name="sede" value="{e(v.get('sede', ''))}" placeholder="Ej. Chapinero" maxlength="100"></label>
      <h3 class="consola-subtitulo">Dueño (será el primer usuario)</h3>
      <label class="campo"><span class="campo-etiqueta">Nombre</span>
        <input class="entrada-texto" name="dueno" value="{e(v.get('dueno', ''))}" maxlength="100"></label>
      <div class="dos-columnas">
        <label class="campo"><span class="campo-etiqueta">Correo</span>
          <input class="entrada-texto" name="correo" type="email" value="{e(v.get('correo', ''))}"></label>
        <label class="campo"><span class="campo-etiqueta">Celular</span>
          <input class="entrada-texto" name="celular" inputmode="tel" value="{e(v.get('celular', ''))}"></label>
      </div>
      <fieldset class="grupo"><legend class="campo-etiqueta">Plan</legend>{planes_html}</fieldset>
      <label class="casilla"><input type="checkbox" name="prueba" value="1" {'checked' if v.get('prueba', '1') else ''}>
        <span class="casilla-caja" aria-hidden="true"></span>Empieza con {DIAS_DE_PRUEBA} días gratis</label>
      <p class="tenue">El usuario del dueño sale de su nombre. Le enviamos el acceso por correo
        con una contraseña temporal. Precios de ejemplo, por definir.</p>
      {_error(error)}"""
    pie = ('<a class="boton boton-secundario" href="/superadmin/barberias">Cancelar</a>'
           '<button class="boton boton-primario" type="submit">Crear barbería y acceso</button>')
    return cajon("Nueva barbería", cuerpo, pie, "/superadmin/barberias",
                 accion="/superadmin/barberias", ancho=520)


# ══════════════════════════════════════════════════════════════════════
#  LAS RUTAS
# ══════════════════════════════════════════════════════════════════════

def _fuera(request: Request):
    """La respuesta si no hay sesión del super-admin; None si la hay."""
    from app.web import superadmin
    if not acceso.super_habilitado() or not superadmin._entrada_valida(request):
        return RedirectResponse("/superadmin/login", status_code=303)
    return None


def _hecho(ruta: str, request: Request, texto: str):
    r = RedirectResponse(ruta, status_code=303)
    from app.web.superadmin import _exige_https
    r.set_cookie(AVISO_COOKIE, quote(texto), max_age=60, httponly=True, samesite="lax",
                 secure=_exige_https(request))
    return r


def _responder(request: Request, html: str, status_code: int = 200):
    r = HTMLResponse(html, status_code=status_code)
    if request.cookies.get(AVISO_COOKIE):
        r.delete_cookie(AVISO_COOKIE, httponly=True, samesite="lax")
    return r


def _aviso(request: Request) -> str:
    from urllib.parse import unquote
    guardado = request.cookies.get(AVISO_COOKIE)
    return unquote(guardado) if guardado else ""


def _pintar(request, filtro="todas", q="", superpuesto="", status_code=200):
    todas = barberias()
    filas = [f for f in todas if filtro in ("todas", f["estado"])]
    if q:
        filas = barberias(filtro, q)
    return _responder(request, _pagina(_listado(filas, filtro, q, todas), superpuesto,
                                       _aviso(request)), status_code)


def _una(client_id: int) -> dict | None:
    return next((f for f in barberias() if f["id"] == client_id), None)


@router.get("", response_class=HTMLResponse)
def listado(request: Request, filtro: str = "todas", q: str = "", ficha: str = "",
            nueva: str = "", pausar: str = ""):
    fuera = _fuera(request)
    if fuera:
        return fuera
    filtro = filtro if filtro in dict(FILTROS) else "todas"
    superpuesto = ""
    cerrar = f"/superadmin/barberias?filtro={filtro}"
    if nueva:
        superpuesto = _cajon_nueva()
    elif pausar.isdigit() and (f := _una(int(pausar))):
        opciones = "".join(
            f'<label class="opcion-rol"><input type="radio" name="motivo" value="{c}"><span><strong>{e(t)}</strong></span></label>'
            for c, t in MOTIVOS_PAUSA)
        superpuesto = f"""
<a class="velo" href="{e(cerrar)}" aria-label="Cerrar" data-cerrar></a>
<div class="dialogo" role="alertdialog" aria-modal="true" aria-labelledby="dialogo-titulo" data-cerrar-en="{e(cerrar)}">
  <h2 id="dialogo-titulo">¿Pausar {e(f['nombre'])}?</h2>
  <p>El dueño y su equipo no podrán entrar al panel y el bot deja de responder. No se borra
     nada: al reactivar, todo sigue donde estaba.</p>
  <form method="post" action="/superadmin/barberias/{f['id']}/pausa">
    <fieldset class="grupo consola-motivos">{opciones}</fieldset>
    <div class="dialogo-pie">
      <a class="boton boton-secundario" href="{e(cerrar)}">Cancelar</a>
      <button class="boton boton-destructivo-fuerte" type="submit">Pausar cuenta</button>
    </div>
  </form>
</div>"""
    elif ficha.isdigit() and (f := _una(int(ficha))):
        superpuesto = _ficha(f, cerrar)
    return _pintar(request, filtro, q, superpuesto)


@router.post("")
def alta(request: Request, nombre: str = Form(""), sede: str = Form(""), dueno: str = Form(""),
         correo: str = Form(""), celular: str = Form(""), plan: str = Form(planes.BARBERIA),
         prueba: str = Form("")):
    fuera = _fuera(request)
    if fuera:
        return fuera
    try:
        client_id, usuario, temporal = dar_de_alta(nombre, sede, dueno, correo, celular,
                                                   plan, bool(prueba))
    except (ValueError, cuentas.CupoLleno) as ex:
        v = {"nombre": nombre, "sede": sede, "dueno": dueno, "correo": correo,
             "celular": celular, "plan": plan, "prueba": prueba}
        return _pintar(request, superpuesto=_cajon_nueva(str(ex), v), status_code=400)
    f = _una(client_id)
    extra = (f'<p class="caja-ok">Listo. Le enviamos a {e(dueno.split(" ")[0])} el usuario '
             f'<strong>@{e(usuario)}</strong> y la contraseña <strong>{e(temporal)}</strong>.</p>')
    return _pintar(request, superpuesto=_ficha(f, "/superadmin/barberias", extra))


def _accion(request: Request, client_id: int, hacer, texto: str):
    fuera = _fuera(request)
    if fuera:
        return fuera
    f = _una(client_id)
    if f is None:
        return _hecho("/superadmin/barberias", request, "Esa barbería no existe.")
    try:
        resultado = hacer()
    except ValueError as ex:
        return _pintar(request, superpuesto=_ficha(f, "/superadmin/barberias", error=str(ex)),
                       status_code=400)
    return _hecho(f"/superadmin/barberias?ficha={client_id}", request,
                  texto.format(nombre=f["nombre"], resultado=resultado))


@router.post("/{client_id}/pago")
def pago(request: Request, client_id: int):
    return _accion(request, client_id, lambda: cobros.registrar_pago(client_id),
                   "Pago registrado. {nombre} queda al día hasta el {resultado:%d/%m/%Y}.")


@router.post("/{client_id}/pausa")
def pausa(request: Request, client_id: int, motivo: str = Form("")):
    return _accion(request, client_id, lambda: pausar(client_id, motivo),
                   "{nombre} quedó pausada. Nadie de la barbería puede entrar y el bot dejó de responder.")


@router.post("/{client_id}/reactivar")
def activar(request: Request, client_id: int):
    return _accion(request, client_id, lambda: reactivar(client_id),
                   "{nombre} está activa otra vez. Ya pueden entrar.")


@router.post("/{client_id}/plan")
def plan(request: Request, client_id: int, plan: str = Form("")):
    return _accion(request, client_id, lambda: cambiar_plan(client_id, plan),
                   "{nombre} cambió de plan. Se cobra el nuevo precio desde el próximo mes.")


@router.post("/{client_id}/limites")
def limites(request: Request, client_id: int, sedes: str = Form("0"), barberos: str = Form("0")):
    def hacer():
        if not (sedes.isdigit() and barberos.isdigit()):
            raise ValueError("Escribe números enteros.")
        cambiar_limites(client_id, int(sedes), int(barberos))
    return _accion(request, client_id, hacer, "Límites guardados.")


@router.post("/{client_id}/restablecer-dueno")
def restablecer(request: Request, client_id: int):
    fuera = _fuera(request)
    if fuera:
        return fuera
    try:
        temporal = restablecer_dueno(client_id)
    except ValueError as ex:
        return _hecho("/superadmin/barberias", request, str(ex))
    f = _una(client_id)
    extra = f'<p class="caja-ok">Contraseña temporal del dueño: <strong>{e(temporal)}</strong></p>'
    return _pintar(request, superpuesto=_ficha(f, "/superadmin/barberias", extra))
