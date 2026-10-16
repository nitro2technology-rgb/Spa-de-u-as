"""
EL HTML DEL PANEL DE LA BARBERÍA
=================================
HTML generado en Python, como el resto del panel (ver el docstring de
`app/web/admin_ui.py`): sin plantillas, sin build. El CSS y el JS viven en
`app/web/estaticos/barberia.css` y `barberia.js`, servidos con versión por
contenido (`app/web/activos.py`).

Todo texto que venga de la base o de quien escribe pasa por `e()`. Los
nombres de las barberías y de las personas los escribe gente.

Lo que se ve está en el handoff (`design_handoff_barbersaas/README.md`):
3a/3b la entrada, 2a/2b el panel del dueño, 2c el del barbero y 4c la
cuenta pausada. Las pantallas que todavía no tienen datos (Fase 1 y 2)
pintan su armazón completo y un estado vacío que lo dice.
"""

import html
from datetime import date

from app.barberia import formato
from app.barberia import permisos
from app.web import activos

PRODUCTO = "BarberSaaS"
TITULAR = "Cada corte registrado, cada peso en su lugar."


def e(texto) -> str:
    return html.escape(str(texto if texto is not None else ""), quote=True)


def _logo(clase: str) -> str:
    return (f'<img class="{clase}" src="{activos.url("barberia/nitro-wordmark.png")}" '
            f'alt="Nitro 2Tech">')


def documento(titulo: str, cuerpo: str, clase_body: str = "",
              color_tema: str = "#1A1823", aviso: str = "") -> str:
    """
    La página completa. `aviso` es el toast que sale al cargar (el que
    confirma lo que se acaba de hacer: "Contraseña guardada").
    """
    datos_aviso = f' data-aviso="{e(aviso)}"' if aviso else ""
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="{e(color_tema)}">
<meta name="robots" content="noindex">
<title>{e(titulo)} · {PRODUCTO}</title>
{activos.hoja("fuentes.css")}
{activos.hoja("barberia.css")}
{activos.guion("barberia.js")}
</head>
<body class="{e(clase_body)}"{datos_aviso}>
{cuerpo}
<div class="aviso" role="status" aria-live="polite" hidden></div>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════
#  ENTRAR (3a / 3b)
# ══════════════════════════════════════════════════════════════════════

def _error(mensaje: str) -> str:
    return (f'<div class="caja-error" role="alert">{e(mensaje)}</div>'
            if mensaje else "")


def _marco_entrada(formulario: str, titulo: str, aviso: str = "") -> str:
    """
    La columna de marca a la izquierda y el formulario a la derecha. En el
    celular, la marca se vuelve la cabecera del mismo degradado y el logo
    de Nitro baja al final (ver `.entrada` en barberia.css): es UNA página
    adaptable, no dos.
    """
    return documento(titulo, f"""
<div class="entrada">
  <section class="entrada-marca">
    <span class="entrada-circulo entrada-circulo-1" aria-hidden="true"></span>
    <span class="entrada-circulo entrada-circulo-2" aria-hidden="true"></span>
    <span class="entrada-producto">{PRODUCTO}</span>
    <div class="entrada-centro">
      <p class="entrada-titular">{TITULAR}</p>
      <p class="entrada-bajada">Caja, agenda y pagos de todas tus sedes en un solo panel.</p>
    </div>
    <div class="entrada-firma">
      <span>Un producto de</span>
      {_logo("entrada-logo")}
    </div>
  </section>
  <main class="entrada-formulario">
    <div class="entrada-caja">
{formulario}
    </div>
  </main>
</div>""", clase_body="cuerpo-entrada", aviso=aviso)


def pagina_entrar(error: str = "", usuario: str = "", recordar: bool = True,
                  vacio_usuario: bool = False, vacio_clave: bool = False,
                  aviso: str = "") -> str:
    return _marco_entrada(f"""
      <form class="formulario" method="post" action="/entrar" novalidate>
        <div class="formulario-cabeza solo-escritorio">
          <h1>Entra a tu barbería</h1>
          <p>Con el usuario y la contraseña que te dio el dueño.</p>
        </div>
        <label class="campo">
          <span class="campo-etiqueta">Usuario, correo o celular</span>
          <input name="usuario" value="{e(usuario)}" autocomplete="username"
                 autocapitalize="none" autocorrect="off" spellcheck="false"
                 placeholder="ej. andres.m"
                 class="entrada-texto{' con-error' if vacio_usuario else ''}"
                 {'autofocus' if not usuario else ''}>
        </label>
        <label class="campo">
          <span class="campo-etiqueta">Contraseña</span>
          <span class="clave{' con-error' if vacio_clave else ''}">
            <input name="clave" type="password" autocomplete="current-password"
                   placeholder="Tu contraseña" {'autofocus' if usuario else ''}>
            <button type="button" class="clave-ver" data-ver-clave
                    aria-pressed="false">Mostrar</button>
          </span>
        </label>
        <div class="entrada-fila">
          <label class="casilla">
            <input type="checkbox" name="recordar" value="1" {'checked' if recordar else ''}>
            <span class="casilla-caja" aria-hidden="true"></span>
            <span class="solo-escritorio">Recordarme en este equipo</span>
            <span class="solo-celular">Recordarme en este celular</span>
          </label>
          <a class="enlace solo-escritorio" href="/entrar/recuperar">Olvidé mi contraseña</a>
        </div>
        {_error(error)}
        <button class="boton boton-primario boton-grande" type="submit">Entrar</button>
        <a class="enlace enlace-centrado solo-celular" href="/entrar/recuperar">Olvidé mi contraseña</a>
        <p class="entrada-pie solo-escritorio">¿Tu barbería aún no tiene cuenta?
          Nitro 2Tech crea el acceso del dueño al contratar.</p>
      </form>""", "Entrar", aviso)


def pagina_recuperar(error: str = "", identificador: str = "") -> str:
    return _marco_entrada(f"""
      <form class="formulario" method="post" action="/recuperar" novalidate>
        <div class="formulario-cabeza">
          <h1>Recupera tu acceso</h1>
          <p>Te enviamos un enlace para crear una contraseña nueva.</p>
        </div>
        <label class="campo">
          <span class="campo-etiqueta">Usuario, correo o celular</span>
          <input name="identificador" value="{e(identificador)}" autocomplete="username"
                 autocapitalize="none" autocorrect="off" spellcheck="false"
                 placeholder="ej. ricardo@filobarberia.co" autofocus
                 class="entrada-texto{' con-error' if error else ''}">
        </label>
        {_error(error)}
        <button class="boton boton-primario boton-grande" type="submit">Enviar enlace</button>
        <p class="nota">Si eres barbero y no tienes correo, pídele al dueño que te
          ponga una contraseña nueva desde Usuarios.</p>
        <a class="enlace enlace-centrado" href="/entrar">Volver a entrar</a>
      </form>""", "Recupera tu acceso")


def pagina_enviado(identificador: str) -> str:
    return _marco_entrada(f"""
      <div class="formulario">
        <div class="formulario-cabeza">
          <h1>Revisa tu correo</h1>
          <p>Si <strong>{e(identificador)}</strong> tiene un usuario, le llegó un
            enlace para crear una contraseña nueva. El enlace vence en 30 minutos.</p>
        </div>
        <a class="boton boton-oscuro boton-grande" href="/entrar">Volver a entrar</a>
      </div>""", "Revisa tu correo")


def pagina_clave(error: str = "", pedir_actual: bool = False, token: str = "",
                 temporal: bool = False) -> str:
    """
    Crear una contraseña: la obligatoria tras una clave temporal, la del
    enlace del correo y la que se cambia por gusto desde el panel.
    """
    if token:
        titulo, texto, accion = ("Crea tu contraseña nueva",
                                 "Escríbela dos veces. Desde ahora entras con ella.",
                                 f"/restablecer/{e(token)}")
    elif temporal:
        titulo, texto, accion = ("Crea tu contraseña",
                                 "La que te dieron es temporal. Escribe una nueva "
                                 "que solo sepas tú.", "/cambiar-contrasena")
    else:
        titulo, texto, accion = ("Cambia tu contraseña",
                                 "Escribe la actual y luego la nueva dos veces.",
                                 "/cambiar-contrasena")

    actual = """
        <label class="campo">
          <span class="campo-etiqueta">Contraseña actual</span>
          <span class="clave">
            <input name="actual" type="password" autocomplete="current-password" autofocus>
            <button type="button" class="clave-ver" data-ver-clave aria-pressed="false">Mostrar</button>
          </span>
        </label>""" if pedir_actual else ""

    volver = ("" if (token or temporal)
              else '<a class="enlace enlace-centrado" href="/b">Volver al panel</a>')
    salir = ('<a class="enlace enlace-centrado" href="/salir">Salir</a>'
             if temporal else "")

    return _marco_entrada(f"""
      <form class="formulario" method="post" action="{accion}" novalidate>
        <div class="formulario-cabeza">
          <h1>{titulo}</h1>
          <p>{texto}</p>
        </div>
        {actual}
        <label class="campo">
          <span class="campo-etiqueta">Contraseña nueva</span>
          <span class="clave">
            <input name="nueva" type="password" autocomplete="new-password"
                   minlength="8" {'' if pedir_actual else 'autofocus'}>
            <button type="button" class="clave-ver" data-ver-clave aria-pressed="false">Mostrar</button>
          </span>
          <span class="campo-ayuda">Al menos 8 caracteres.</span>
        </label>
        <label class="campo">
          <span class="campo-etiqueta">Repítela</span>
          <span class="clave">
            <input name="repetida" type="password" autocomplete="new-password">
            <button type="button" class="clave-ver" data-ver-clave aria-pressed="false">Mostrar</button>
          </span>
        </label>
        {_error(error)}
        <button class="boton boton-primario boton-grande" type="submit">Guardar contraseña</button>
        {volver}{salir}
      </form>""", titulo)


def pagina_enlace_vencido() -> str:
    return _marco_entrada("""
      <div class="formulario">
        <div class="formulario-cabeza">
          <h1>Este enlace ya no sirve</h1>
          <p>Venció o ya se usó. Pide uno nuevo desde la entrada: dura 30 minutos.</p>
        </div>
        <a class="boton boton-primario boton-grande" href="/entrar/recuperar">Pedir otro enlace</a>
        <a class="enlace enlace-centrado" href="/entrar">Volver a entrar</a>
      </div>""", "Enlace vencido")


# ══════════════════════════════════════════════════════════════════════
#  CUENTA PAUSADA (4c)
# ══════════════════════════════════════════════════════════════════════

MOTIVOS_PAUSA = {
    "impago": "No hemos recibido el pago de la mensualidad.",
    "pedido": "Se pausó a pedido tuyo.",
    "revision": "Estamos revisando la cuenta.",
}


def pagina_pausada(negocio: str, plan: str, pendiente: int, motivo: str,
                   enlace_pago: str, enlace_soporte: str, medios: list) -> str:
    como = " · ".join(f"{e(n)} <strong>{e(d)}</strong>" for n, d in medios)
    return documento("Cuenta pausada", f"""
<main class="pausada">
  <div class="pausada-caja">
    <span class="chip chip-pausado">Cuenta pausada</span>
    <h1>{e(negocio)} está en pausa</h1>
    <p>{e(MOTIVOS_PAUSA.get(motivo, "Tu cuenta está en pausa."))}
       Tus citas, cajas y clientes están guardados; nada se borró.</p>
    <dl class="pausada-cuenta">
      <div><dt>Plan</dt><dd>{e(plan)}</dd></div>
      <div><dt>Valor pendiente</dt><dd>{e(formato.pesos(pendiente))}</dd></div>
    </dl>
    <p class="pausada-medios">Paga por {como} y envíanos el comprobante.</p>
    <a class="boton boton-claro boton-grande" href="{e(enlace_pago)}"
       target="_blank" rel="noopener">Pagar y reactivar</a>
    <a class="boton boton-fantasma boton-grande" href="{e(enlace_soporte)}"
       target="_blank" rel="noopener">Hablar con Nitro2Tech</a>
    <p class="pausada-nota">Solo el dueño ve esta pantalla. Los barberos ven un
      aviso de que el panel no está disponible.</p>
    <a class="enlace enlace-centrado enlace-oscuro" href="/entrar">Volver a la entrada</a>
  </div>
  {_logo("pausada-logo")}
</main>""", clase_body="cuerpo-pausada")


# ══════════════════════════════════════════════════════════════════════
#  PANEL DEL DUEÑO (2a / 2b)
# ══════════════════════════════════════════════════════════════════════

# Fuera de las f-strings: una barra invertida dentro de sus llaves no
# compila antes de Python 3.12.
ACTUAL = ' aria-current="true"'
PAGINA_ACTUAL = ' aria-current="page"'

PERIODOS = (("hoy", "Hoy", "hoy"), ("semana", "Semana", "esta semana"),
            ("mes", "Mes", None))


def _enlace(ruta: str, sede: int | None, periodo: str) -> str:
    """Los filtros son globales: viajan en cada enlace de la barra."""
    partes = []
    if sede:
        partes.append(f"sede={sede}")
    if periodo and periodo != "hoy":
        partes.append(f"periodo={periodo}")
    return ruta + ("?" + "&".join(partes) if partes else "")


def _segmentado(opciones: list, etiqueta: str, clase: str = "") -> str:
    """`opciones` = [(texto, href, activo)]. Un grupo de enlaces, no de botones."""
    items = "".join(
        f'<a class="segmento{" activo" if activo else ""}" href="{e(href)}"'
        f'{ACTUAL if activo else ""}>{e(texto)}</a>'
        for texto, href, activo in opciones)
    return (f'<nav class="segmentado {clase}" aria-label="{e(etiqueta)}">'
            f'{items}</nav>')


def _subtitulo(seccion: permisos.Seccion, periodo: str, hoy: date) -> str:
    textos = {
        "periodo": next((p[2] for p in PERIODOS if p[0] == periodo), None)
                   or f"en {formato.MESES[hoy.month - 1]}",
        "fecha": formato.con_mayuscula(formato.fecha_larga(hoy)),
        "quincena": formato.quincena(hoy),
        "mes": formato.mes(hoy),
    }
    return seccion.subtitulo.format(**textos)


# Las secciones que todavía no tienen pantalla: la agenda llega con el bot
# en la Fase 2, y el inventario en la Fase 3 (§10 de la especificación).
VACIOS = {
    "agenda": ("Aquí verás las citas de cada barbero, las que agenda el bot y los "
               "clientes que llegan sin cita.", "Llega con la agenda, en la Fase 2."),
    "inventario": ("Aquí verás el stock de cada producto por sede y cuándo pedir más.",
                   "Llega con el inventario, en la Fase 3."),
}


def vacio(clave: str) -> str:
    texto, cuando = VACIOS.get(clave, ("", ""))
    return f"""
      <section class="tarjeta vacio">
        <span class="chip chip-aviso">En construcción</span>
        <p>{e(texto)}</p>
        <p class="vacio-nota">{e(cuando)}</p>
      </section>"""


def _insignia(dato) -> str:
    if not dato:
        return ""
    texto, tono = dato
    return f'<span class="lateral-insignia {e(tono)}">{e(texto)}</span>'


def pagina_panel(persona: permisos.Persona, seccion: permisos.Seccion,
                 sede: int | None, periodo: str, hoy: date, aviso: str = "",
                 contenido: str = "", insignias: dict | None = None,
                 superpuesto: str = "", acciones: str = "") -> str:
    """
    El armazón del panel del dueño, de escritorio y de celular a la vez.

    `contenido` es el cuerpo de la sección (`pantallas.py`); `superpuesto`,
    un panel lateral o un diálogo abierto encima; `acciones`, los botones
    de la cabecera ("Agregar usuario"); `insignias`, {clave: (texto, tono)}
    para la barra lateral.
    """
    insignias = insignias or {}
    varias_sedes = len(persona.sedes) > 1

    # ── barra lateral (escritorio) ──
    nav = "".join(
        f'<a class="lateral-item{" activo" if s.clave == seccion.clave else ""}" '
        f'href="{e(_enlace("/b/" + s.clave, sede, periodo))}"'
        f'{PAGINA_ACTUAL if s.clave == seccion.clave else ""}>'
        f'<span class="lateral-ini" aria-hidden="true">{e(s.etiqueta[:2])}</span>'
        f'<span class="lateral-texto">{e(s.etiqueta)}</span>'
        f'{_insignia(insignias.get(s.clave))}</a>'
        for s in permisos.secciones_de(persona))

    # ── filtros ──
    filtros = ""
    if seccion.filtro_sede and varias_sedes:
        filtros += _segmentado(
            [("Todas", _enlace(f"/b/{seccion.clave}", None, periodo), sede is None)]
            + [(n, _enlace(f"/b/{seccion.clave}", i, periodo), sede == i)
               for i, n in persona.sedes], "Sede")
    if seccion.filtro_periodo:
        filtros += _segmentado(
            [(t, _enlace(f"/b/{seccion.clave}", sede, c), periodo == c)
             for c, t, _ in PERIODOS], "Periodo", "solo-escritorio")

    # ── celular ──
    chips = ""
    if varias_sedes:
        chips = '<nav class="movil-sedes" aria-label="Sede">' + "".join(
            f'<a class="chip-sede{" activo" if activo else ""}" href="{e(h)}">{e(t)}</a>'
            for t, h, activo in
            [("Todas", _enlace(f"/b/{seccion.clave}", None, periodo), sede is None)]
            + [(n, _enlace(f"/b/{seccion.clave}", i, periodo), sede == i)
               for i, n in persona.sedes]) + "</nav>"

    pestanas = permisos.pestanas_de(persona)
    barra_movil = ""
    if len(pestanas) > 1:
        barra_movil = '<nav class="pestanas" aria-label="Secciones">' + "".join(
            f'<a class="pestana{" activo" if c == seccion.clave else ""}" '
            f'href="{e(_enlace("/b/" + c, sede, periodo))}">{e(t)}</a>'
            for c, t in pestanas) + "</nav>"

    periodo_movil = ""
    if seccion.filtro_periodo:
        periodo_movil = _segmentado(
            [(t, _enlace(f"/b/{seccion.clave}", sede, c), periodo == c)
             for c, t, _ in PERIODOS], "Periodo", "segmentado-ancho solo-celular")

    return documento(seccion.titulo, f"""
<div class="panel">
  <aside class="lateral">
    <div class="lateral-marca">
      <span class="lateral-negocio">{e(persona.negocio)}</span>
      <span class="lateral-plan">Plan {e(persona.plan_nombre)}</span>
    </div>
    <nav class="lateral-nav" aria-label="Secciones">{nav}</nav>
    <div class="lateral-pie">
      <div class="lateral-usuario">
        <span class="avatar avatar-marca">{e(persona.iniciales)}</span>
        <span class="lateral-usuario-datos">
          <span class="lateral-usuario-nombre">{e(persona.nombre)}</span>
          <span class="lateral-usuario-rol">{e(persona.rol_nombre)}</span>
        </span>
      </div>
      <div class="lateral-cuenta">
        <a href="/cambiar-contrasena">Cambiar contraseña</a>
        <a href="/salir">Salir</a>
      </div>
      <div class="lateral-firma">
        <span>{PRODUCTO}, un producto de</span>
        {_logo("lateral-logo")}
      </div>
    </div>
  </aside>

  <header class="movil-cabecera">
    <div class="movil-fila">
      <div class="movil-marca">
        <span class="movil-negocio">{e(persona.negocio)}</span>
        <span class="lateral-plan">Plan {e(persona.plan_nombre)}</span>
      </div>
      <a class="movil-salir" href="/salir">Salir</a>
      <span class="avatar avatar-marca avatar-34">{e(persona.iniciales)}</span>
    </div>
    {chips}
  </header>

  <main class="principal">
    <header class="cabecera">
      <div class="cabecera-titulos">
        <h1>{e(seccion.titulo)}</h1>
        <p>{e(_subtitulo(seccion, periodo, hoy))}</p>
      </div>
      <div class="cabecera-filtros">{acciones}<span class="solo-escritorio cabecera-segmentos">{filtros}</span></div>
    </header>
    <div class="contenido">
      {periodo_movil}
      {contenido or vacio(seccion.clave)}
    </div>
  </main>
  {barra_movil}
</div>
{superpuesto}""", clase_body="cuerpo-panel" + (" con-pestanas" if barra_movil else ""),
                     color_tema="#1A1823", aviso=aviso)


# ══════════════════════════════════════════════════════════════════════
#  PANEL DEL BARBERO (2c)
# ══════════════════════════════════════════════════════════════════════

def pagina_barbero(persona: permisos.Persona, vista: str, hoy: date, llevas: dict,
                   cuerpo: str, superpuesto: str = "", aviso: str = "",
                   sede_nombre: str = "") -> str:
    """
    Tema oscuro fijo: menos brillo en el local y cifras claras de un
    vistazo. `llevas` es `nomina.hoy_llevas`; `cuerpo`, lo de "Mi día" o
    "Mis ganancias" (`pantallas.py`); `superpuesto`, la hoja abierta.
    """
    sede = sede_nombre or (persona.sedes[0][1] if persona.sedes else "")
    donde = f"{sede}, {formato.fecha_larga(hoy)}" if sede else formato.fecha_larga(hoy)

    segmentado = _segmentado([("Mi día", "/yo/dia", vista == "dia"),
                              ("Mis ganancias", "/yo/ganancias", vista == "ganancias")],
                             "Vista", "segmentado-oscuro segmentado-ancho")
    boton = ('<a class="yo-flotante" href="/yo/dia?registrar=1" data-abrir-hoja="registrar">'
             'Registrar cliente sin cita</a>') if vista == "dia" else ""

    return documento("Mi día", f"""
<div class="yo{' con-flotante' if boton else ''}">
  <header class="yo-cabecera">
    <div>
      <p class="yo-hola">Hola, {e(persona.primer_nombre)}</p>
      <p class="yo-donde">{e(donde)}</p>
    </div>
    <div class="yo-cuenta">
      <a class="movil-salir" href="/salir">Salir</a>
      <span class="avatar avatar-marca avatar-40">{e(persona.iniciales)}</span>
    </div>
  </header>
  <section class="yo-llevas">
    <div>
      <p class="yo-llevas-rotulo">Hoy llevas</p>
      <p class="yo-llevas-cifra">{e(formato.pesos(llevas["total"]))}</p>
    </div>
    <div class="yo-llevas-datos">
      <span>{e(formato.plural(llevas["servicios"], "servicio"))}</span>
      <span>{e(formato.pesos(llevas["propinas"]))} en propinas</span>
    </div>
  </section>
  {segmentado}
  <main class="yo-contenido">{cuerpo}
  </main>
  {boton}
</div>
{superpuesto}""", clase_body="cuerpo-yo", color_tema="#15131C", aviso=aviso)
