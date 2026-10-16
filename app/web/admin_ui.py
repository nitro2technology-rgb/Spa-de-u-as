"""
PANEL DE ATENCIÓN MANUAL
=========================
Una bandeja de entrada mínima para leer las conversaciones y responder a
mano, sin depender de WhatsApp Manager ni de un servicio de pago.

Al enviar una respuesta desde aquí, la conversación queda marcada como
"atendida por humano" automáticamente: el bot deja de responder ahí para
no escribir encima del asesor. Se devuelve al bot con un botón, o sola
tras el tiempo de inactividad configurado.

Es HTML plano generado en Python a propósito: sin plantillas, sin build,
sin dependencias nuevas. Para una bandeja de un negocio pequeño sobra, y
mantiene el proyecto de una sola pieza.
"""

import asyncio
import html
import json
import re
from urllib.parse import quote, quote_plus

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse,
)
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.bot import bot_logic
from app import config
from app.core import acceso
from app.core import database
from app.core import equipo
from app.core import eventos
from app.core import freno
from app.core import media
from app.core import message_log
from app.core import push
from app.core import tenencia
from app.web import activos
from app.web import pwa
from app.bot import whatsapp_client as wa

router = APIRouter(prefix="/admin", tags=["panel"])

COOKIE = "panel_nitro"

# Máximo de un mensaje de texto en la API de WhatsApp.
LIMITE_WHATSAPP = 4096

# Cada cuánto se preguntan mensajes nuevos, en segundos, CUANDO HAY QUE
# CAER AL PLAN B. Lo normal es que el servidor empuje los mensajes por el
# canal en vivo y esto no se use nunca; solo entra si ese canal falla.
SEGUNDOS_PLAN_B = 3

# Cómo se nombra a cada quien en el hilo. Lo usan el pintado del servidor
# y el del navegador, así que vive en un solo sitio.
ETIQUETA_AUTOR = {"cliente": "Cliente", "humano": "Tú", "bot": "Bot"}

# Cómo se llama cada estado de atención en pantalla. La clave es lo que
# se guarda en la base (ver database.ESTADOS_ATENCION); el texto se puede
# reescribir cuando se quiera sin tocar lo ya guardado.
#
# Un solo sitio para las tres pantallas que lo pintan: la cabecera del
# hilo, el menú para marcarlo y el listado de conversaciones.
ETIQUETA_ESTADO = {
    "urgente": "Urgente",
    "esperando": "Esperando al cliente",
    "terminado": "Terminado",
}


# Los guiones del panel viven en `app/web/estaticos/panel-*.js`: el
# listado (`panel-listado.js`, el ÚNICO que pinta una conversación en la
# lista), el canal en vivo (`panel-vivo.js`) y el hilo (`panel-chat.js`).
# Aquí solo queda el HTML de partida y los datos que necesitan.

# ── Sesión ───────────────────────────────────────────────────────────
# La cookie NO guarda ninguna clave. Guarda un pase firmado que caduca
# solo, por inactividad y por antigüedad. Antes la cookie era la clave tal
# cual y duraba 30 días, así que un celular perdido era acceso permanente
# al panel, y no había forma de que una sesión expirara sin cambiar la
# clave para todo el mundo.
#
# Cómo se arma, cómo se firma y por qué lleva el `client_id` dentro está
# en `app/core/acceso.py`. Aquí queda solo lo que es del panel: cuándo se
# valida y cuándo se renueva.

def _sesion_valida(request: Request):
    """
    El pase de esta petición, o None si no vale.

    Lo importante está en `acceso.leer_pase`: el pase tiene que ser de
    ESTE inquilino, no de cualquiera. Se le pasa el que resolvió el
    middleware por el `Host`.

    Devuelve un `acceso.Pase`, que siempre es verdadero, así que los
    llamadores pueden seguir haciendo `if not _sesion_valida(request)`.
    """
    return acceso.leer_pase(request.cookies.get(COOKIE, ""),
                            tenencia.actual_o_none())


def _renovar(respuesta, request: Request, sesion: acceso.Pase):
    """
    Estampa la cookie de sesión en una respuesta ya construida.

    Solo se llama desde lo que haces tú a mano (abrir la bandeja, abrir un
    chat, enviar un mensaje). Las consultas que el panel hace solo de
    fondo NO renuevan: si lo hicieran, una pestaña olvidada mantendría la
    sesión viva para siempre y la caducidad no serviría de nada.
    """
    respuesta.set_cookie(
        COOKIE,
        acceso.crear_pase(sesion.client_id, sesion.user_id,
                          sesion.vence_absoluto),
        httponly=True,          # inalcanzable desde JavaScript
        samesite="lax",         # no se manda en peticiones de otros sitios
        secure=_exige_https(request),
        max_age=int(config.PANEL_SESION_INACTIVIDAD_HORAS * 3600),
    )
    return respuesta


def _sesion_caducada(request: Request) -> bool:
    """¿Traía cookie pero ya no vale? Entonces la sesión expiró."""
    return bool(request.cookies.get(COOKIE)) and not _sesion_valida(request)


def _quien(request: Request):
    """
    Quién está usando el panel —el dueño o un área—, o None.

    Es lo que TODA ruta del panel pregunta antes de responder. La sesión
    sola ya no basta: con áreas, estar dentro no quiere decir poder verlo
    todo. Ver `app/core/equipo.py`.
    """
    return equipo.de_pase(_sesion_valida(request))


def _conversacion_ajena(request: Request, phone: str):
    """
    None si quien pide puede ver esa conversación; si no, la respuesta.

    404 y no 403 a propósito: a un área no hay por qué confirmarle que ese
    cliente existe y es de otra.
    """
    quien = _quien(request)
    if quien is None:
        return JSONResponse({"error": "no autorizado"}, status_code=401)
    if not equipo.puede_ver(quien, phone):
        return JSONResponse({"error": "No encontrado"}, status_code=404)
    return None


def _solo_dueno(request: Request):
    """None si es el dueño; si no, la respuesta."""
    quien = _quien(request)
    if quien is None:
        return JSONResponse({"error": "no autorizado"}, status_code=401)
    if not quien.es_dueno:
        return JSONResponse({"error": "Solo el administrador puede hacer esto."},
                            status_code=403)
    return None


# ── Freno a los intentos de clave ────────────────────────────────────
# El mecanismo está en `app/core/freno.py`, porque /superadmin usa el
# mismo. Aquí solo queda el contador de esta puerta.

_FRENO = freno.Freno("panel")


def _credito(clase: str = "credito") -> str:
    """
    La firma de quien montó el bot. Vacía si el TOML la deja en blanco,
    para quien revenda el panel con su propio nombre.
    """
    if not config.CREADO_POR:
        return ""
    return (f'<p class="{clase}">Creado por '
            f'<strong>{html.escape(config.CREADO_POR)}</strong></p>')


# Los servicios que se anuncian en la pantalla de entrada. Son los de
# Nitro, no los del negocio que usa el panel: la plataforma es Nitro
# también dentro del panel de un cliente (decisión del dueño, 19-ago-2026).
SERVICIOS_NITRO = ("Chatbots", "Automatizaciones", "Páginas web", "Power BI")


def _pedir_login(mensaje: str = "", usuario: str = "",
                 aviso_html: str = "") -> HTMLResponse:
    """
    La pantalla de entrada: la marca a la izquierda, el formulario a la
    derecha.

    La columna de marca es SIEMPRE Nitro y siempre oscura, en los dos
    temas. Del negocio que entra aparece su cuadrito encima del
    formulario — lo justo para saber que es su panel, sin convertir la
    herramienta en suya.
    """
    aviso = aviso_html or (f'<div class="banda alerta">{html.escape(mensaje)}</div>'
                           if mensaje else "")

    # USUARIO Y CLAVE. Antes era "Negocio" y clave, y el negocio no decía
    # con QUÉ usuario se entraba: el dueño añadió uno en /superadmin, la
    # clave de siempre dejó de servir, y no había forma de saber cuál era
    # la nueva ni dónde se había cambiado (13-sep-2026).
    #
    # El usuario es único en toda la plataforma, así que dice solo de qué
    # negocio es. Se conserva lo que escribió al fallar.
    #
    # SIN `required`, y es importante: quien entraba con el nombre de su
    # negocio, o solo con la clave, sigue pudiendo (ver `acceso.entrar`).
    # Con `required` el navegador no deja ni enviar el formulario.
    casilla = f"""
              <div class="login-campo">
                <label for="usuario">Usuario</label>
                <input id="usuario" type="text" name="usuario"
                       value="{html.escape(usuario)}"
                       placeholder="tu usuario o tu correo"
                       autocomplete="username" autocapitalize="none"
                       autocorrect="off" spellcheck="false" autofocus>
              </div>"""

    chips = "".join(f'<span class="chip-marca">{s}</span>'
                    for s in SERVICIOS_NITRO)

    return HTMLResponse(_pagina("Entrar", f"""
      <div class="entrada-pantalla">

        <section class="login-marca">
          <span class="login-orbe" aria-hidden="true"></span>
          <span class="login-barrido" aria-hidden="true"></span>

          <div class="login-fila-marca">
            <span class="marca-texto">
              <span>Nitro</span><span class="marca-texto-acento">2Tech</span>
            </span>
            <span class="login-separador" aria-hidden="true"></span>
            <span class="login-rotulo mono">Panel de atención</span>
          </div>

          <div class="login-centro">
            <p class="login-antetitulo">
              <span class="mono">Tecnología que atiende por ti</span></p>
            <h1 class="login-titular">
              <span class="lleno">Nitro</span>
              <span class="contorno">2Tech</span><span
                class="login-version mono">v2.0</span>
            </h1>
            <p class="login-bajada">Tu WhatsApp atendido de día y de noche.
               El bot responde solo; tú entras cuando quieras y él se calla
               automáticamente.</p>
            <div class="login-chips">{chips}</div>
          </div>

          <div class="login-pie">
            <span class="login-pie-estado mono">
              <span class="punto-vivo" aria-hidden="true"></span>
              Bot activo · atendiendo ahora</span>
            <!-- El dominio de la PLATAFORMA, no el del cliente: esta
                 pantalla es de Nitro aunque se entre al panel de otro
                 negocio (ver la decision de marca en CONTINUAR_AQUI, §1).
                 Por eso va literal y no sale de `config`. -->
            <span class="login-pie-web mono">nitro2tech.com</span>
          </div>
        </section>

        <main class="login-formulario">
          <div class="login-caja">
            <h1>Entra a tu panel</h1>
            <p class="apoyo">Usa el usuario y la clave que te
               entregamos.</p>

            <form method="post" action="/admin/login" class="login-tarjeta">
              {aviso}
              {casilla}
              <div class="login-campo">
                <label for="clave">Clave de acceso</label>
                <div class="login-clave">
                  <input id="clave" type="password" name="clave"
                         autocomplete="current-password" required>
                  <button type="button" class="login-ver"
                          data-ver-clave>Ver</button>
                </div>
              </div>
              <button type="submit" class="login-entrar">Entrar al panel</button>
              <p class="login-cifrado">
                <span>Sesión cifrada</span>
              </p>
            </form>

            {_credito("login-firma")}
          </div>
        </main>
      </div>""", guiones=("panel-login.js",), clase_body="entrada"))


CADUCADA = "Tu sesión caducó por inactividad. Entra de nuevo."


SIN_CLAVE = """
          <div class="tarjeta centrada">
            <h1>Panel deshabilitado</h1>
            <p>Este negocio todavía no tiene ninguna clave de acceso.</p>
            <p class="tenue">Se crea con <code>python scripts/panel_usuario.py</code>.</p>
          </div>"""


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    # Con subdominios, un negocio sin clave no tiene panel que ofrecer y se
    # dice. Sin subdominios no se puede saber a quién quiere entrar quien
    # todavía no ha escrito nada, así que la pantalla se pinta igual.
    if tenencia.dominio_base() and not acceso.panel_habilitado(
            tenencia.actual_o_none()):
        return HTMLResponse(_pagina("Sin configurar", SIN_CLAVE),
                            status_code=503)

    if _sesion_valida(request):
        return RedirectResponse("/admin/inbox", status_code=303)
    return _pedir_login(CADUCADA if _sesion_caducada(request) else "")


@router.post("/login")
def login(request: Request, clave: str = Form(...), usuario: str = Form(""),
          negocio: str = Form("")):
    """
    Entrar al panel de un negocio.

    De qué negocio se trata sale de uno de dos sitios, según cómo esté
    desplegado (ver el middleware de `app/main.py`):

      con subdominios  del `Host`, que el middleware ya resolvió.
      sin subdominios  de la casilla "Negocio" de este formulario, que es
                       la que hace el trabajo que hacía el subdominio.

    En los dos casos la clave se compara contra los usuarios de ESE
    inquilino y de ningún otro (`app/core/acceso.py`). Antes se comparaba
    contra `ADMIN_API_KEY`, que es una variable de entorno y por tanto la
    misma para todos los clientes del despliegue.
    """
    por_subdominio = bool(tenencia.dominio_base())

    # `negocio` es el nombre de la casilla de antes. Se sigue aceptando por
    # una pestaña abierta con el formulario viejo, o un gestor de claves
    # que lo rellene solo.
    usuario = usuario or negocio

    if por_subdominio and not acceso.panel_habilitado(tenencia.actual_o_none()):
        return _pedir_login("Este panel todavía no tiene clave de acceso.")

    if _FRENO.bloqueado(request):
        return _pedir_login(_FRENO.aviso(), usuario)

    sesion = acceso.entrar(
        usuario, clave,
        client_id=tenencia.actual_o_none() if por_subdominio else None)

    if sesion is None:
        # Clave correcta pero el negocio lo pausó el cobro: se le dice eso y
        # cómo pagar, no "clave incorrecta". Ver `acceso.pausado_por_impago`.
        pausado = acceso.pausado_por_impago(usuario, clave)
        if pausado is not None:
            return _pedir_login(usuario=usuario, aviso_html=_aviso_de_pausa(pausado))
        _FRENO.anotar_fallo(request)
        # El mismo mensaje para "ese usuario no existe" y para "la clave no
        # es esa": distinguirlos le diría a cualquiera desde fuera qué
        # usuarios existen, probando nombres uno a uno.
        return _pedir_login("El usuario o la clave no son correctos.", usuario)

    _FRENO.olvidar(request)   # entró bien: se olvidan los fallos

    # La respuesta se estampa con el inquilino de QUIEN ENTRÓ, que no tiene
    # por qué ser el que traía la petición: sin subdominios, el middleware
    # puso el cliente por defecto porque todavía no había pase que leer.
    with tenencia.usar(sesion.client_id):
        return _renovar(RedirectResponse("/admin/inbox", status_code=303),
                        request, sesion)


def _aviso_de_pausa(client_id: int) -> str:
    """Lo que ve en la entrada el dueño de un negocio pausado por no pagar."""
    from app.core import cobros, planes
    from app.web.panel_plan import enlace_comprobante

    c = cobros.cuenta_de(client_id)
    datos = tenencia.por_id(client_id)
    negocio = datos.nombre if datos else ""
    medios = " · ".join(f"{html.escape(n)}: <strong>{html.escape(d)}</strong>"
                        for n, d in planes.MEDIOS_DE_PAGO)
    precio = planes.pesos(c.precio) if c else ""
    return f"""
      <div class="banda alerta pausa-cobro">
        <strong>Tu servicio está pausado por falta de pago.</strong>
        Tu bot no está respondiendo, pero no se ha borrado nada.<br>
        Paga {precio} por {medios} y
        <a href="{html.escape(enlace_comprobante(negocio))}" target="_blank"
           rel="noopener">envíanos el comprobante por WhatsApp</a>. En cuanto
        lo registremos, todo vuelve a funcionar.
      </div>"""


def _exige_https(request: Request) -> bool:
    """
    Marca la cookie como "solo HTTPS" salvo en pruebas locales.

    Sin esta excepción no se podría entrar al panel en localhost, porque
    el navegador descarta las cookies `secure` que llegan por HTTP. En el
    servidor real siempre hay HTTPS, así que allí sí se exige.
    """
    return request.url.hostname not in ("localhost", "127.0.0.1", "::1")


@router.get("/logout")
def logout(request: Request):
    respuesta = RedirectResponse("/admin/login", status_code=303)
    # Los mismos atributos que al crearla: si no coinciden, el navegador
    # borra "otra" cookie y la sesión sigue viva.
    respuesta.delete_cookie(COOKIE, httponly=True, samesite="lax",
                            secure=_exige_https(request))
    return respuesta


# ── Bandeja de entrada ───────────────────────────────────────────────

def _fila_listado(c: dict) -> dict:
    """
    Los datos de una conversación tal y como los espera el listado.

    Punto único: lo usan el endpoint que refresca la barra lateral y el
    JSON que se embebe en la primera carga, así que las dos vías entregan
    exactamente lo mismo. Aquí NO se decide cómo se ve nada — de eso se
    encarga `pintarListado`, que también es único.
    """
    return {
        "phone": c["phone"],
        "name": c["name"] or "",
        "resumen": (c["ultimo_texto"] or "").split("\n")[0][:70],
        "atendido_por_humano": c["atendido_por_humano"],
        "servicio": c.get("servicio"),
        "estado_atencion": c.get("estado_atencion") or "",
        "es_dueno": c["es_dueno"],
        "origen": c["origen"],
        "ventana_abierta": c["ventana_abierta"],
        # Las que puso el negocio a mano. Se ven aqui y no solo en la
        # ficha porque su razon de ser es barrer el listado: una etiqueta
        # que hay que abrir la conversacion para leer no sirve de nada.
        "etiquetas": c.get("etiquetas") or [],
        # En UTC y en ISO: quien pinta la tarjeta es el navegador, que sí
        # sabe en qué huso está quien mira. El servidor no lo sabe.
        "cuando": (c["last_interaction"].isoformat() + "Z"
                   if c.get("last_interaction") else ""),
    }


def _listado_inicial(conversaciones: list) -> str:
    """
    El listado de partida, embebido en la página.

    Va como JSON y no como HTML ya pintado para que exista **un solo**
    generador (`pintarListado`). Embebido y no pedido por fetch para que
    la lista aparezca de una vez, sin el parpadeo de esperar a la red.

    `<` se escapa: sin eso, un nombre que contenga "</script>" cerraría el
    bloque antes de tiempo y el resto del JSON se ejecutaría como código.
    """
    crudo = json.dumps([_fila_listado(c) for c in conversaciones],
                       ensure_ascii=False)
    seguro = crudo.replace("<", "\\u003c")
    return f'<script type="application/json" id="listado-inicial">{seguro}</script>'


def _iniciales(nombre: str) -> str:
    """
    Las dos primeras iniciales de un nombre, para el cuadrito.

    Avatar de verdad no hay —Meta no lo entrega— y una silueta gris
    repetida cuarenta veces no distingue una conversación de otra. Las
    iniciales sí, y no cuestan una petición.
    """
    partes = [p for p in (nombre or "").split() if p]
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[1][0]).upper()


# Los iconos del rail. Van como SVG en el HTML y no como archivo ni como
# fuente de iconos: son cuatro trazos, pesan menos que la petición que
# harían falta para traerlos, y siguen el color del texto.
_ICONO_CHATS = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="1.9" stroke-linecap="round" '
                'stroke-linejoin="round" aria-hidden="true">'
                '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.9 8.9 0 0 1-3.8-.8'
                'L3 21l1.9-4.9A8.4 8.4 0 0 1 12 3.1a8.4 8.4 0 0 1 9 8.4z"/>'
                '</svg>')
_ICONO_TEMA = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
               'stroke-width="1.9" stroke-linecap="round" '
               'stroke-linejoin="round" aria-hidden="true">'
               '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'
               '</svg>')
_ICONO_SALIR = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="1.9" stroke-linecap="round" '
                'stroke-linejoin="round" aria-hidden="true">'
                '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
                '<path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></svg>')
_ICONO_LUPA = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
               'stroke-width="2" stroke-linecap="round" aria-hidden="true">'
               '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'
               '</svg>')


_ICONO_CONTACTOS = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                    'stroke-width="1.9" stroke-linecap="round" '
                    'stroke-linejoin="round" aria-hidden="true">'
                    '<path d="M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20"/>'
                    '<circle cx="10" cy="8" r="3.5"/>'
                    '<path d="M19.5 20v-1.4a3.4 3.4 0 0 0-2.6-3.3"/>'
                    '<path d="M15.2 4.6a3.4 3.4 0 0 1 0 6.6"/></svg>')


_ICONO_AJUSTES = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                  'stroke-width="1.9" stroke-linecap="round" '
                  'stroke-linejoin="round" aria-hidden="true">'
                  '<circle cx="12" cy="12" r="3.2"/>'
                  '<path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8'
                  'l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0'
                  'v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8'
                  'l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1'
                  'A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8'
                  'l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1'
                  'a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8'
                  'l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1'
                  'a1.6 1.6 0 0 0-1.5 1z"/></svg>')


_ICONO_EQUIPO = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                 'stroke-width="1.9" stroke-linecap="round" '
                 'stroke-linejoin="round" aria-hidden="true">'
                 '<rect x="9" y="3" width="6" height="5" rx="1.2"/>'
                 '<rect x="2.5" y="16" width="6" height="5" rx="1.2"/>'
                 '<rect x="15.5" y="16" width="6" height="5" rx="1.2"/>'
                 '<path d="M12 8v4M5.5 16v-2h13v2"/></svg>')


_ICONO_PLAN = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
               'stroke-width="1.9" stroke-linecap="round" '
               'stroke-linejoin="round" aria-hidden="true">'
               '<rect x="2.5" y="5" width="19" height="14" rx="2.5"/>'
               '<path d="M2.5 10h19M6.5 15h4"/></svg>')


_ICONO_BOT = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
              'stroke-width="1.9" stroke-linecap="round" '
              'stroke-linejoin="round" aria-hidden="true">'
              '<rect x="4" y="7" width="16" height="12" rx="3"/>'
              '<path d="M12 7V4M9 12h.01M15 12h.01M9.5 16h5"/></svg>')
_ICONO_ESTADISTICAS = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                       'stroke-width="1.9" stroke-linecap="round" '
                       'stroke-linejoin="round" aria-hidden="true">'
                       '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>')


def _rail(activo: str = "chats", quien=None) -> str:
    """
    La columna de iconos de la izquierda: quién es la plataforma, a dónde
    se puede ir, y de quién es este panel.

    La marca de arriba es la de **Nitro**, y la de abajo las iniciales
    del negocio. Ese reparto es la decisión de producto de siempre: la
    herramienta es Nitro también dentro del panel de un cliente.

    "Equipo" solo lo ve el dueño: es donde se arman las áreas, y quien
    entra por un área no tiene nada que hacer ahí.
    """
    equipo_enlace = ""
    if quien is not None and quien.es_dueno:
        equipo_enlace = f"""
        <a class="rail-icono{" activo" if activo == "equipo" else ""}"
           href="/admin/equipo"
           aria-label="Equipo" title="Equipo y áreas">{_ICONO_EQUIPO}</a>
        <a class="rail-icono{" activo" if activo == "plan" else ""}"
           href="/admin/mi-plan"
           aria-label="Mi plan" title="Mi plan y pagos">{_ICONO_PLAN}</a>
        <a class="rail-icono{" activo" if activo == "bot" else ""}"
           href="/admin/mi-bot"
           aria-label="Mi bot" title="Lo que dice mi bot">{_ICONO_BOT}</a>
        <a class="rail-icono{" activo" if activo == "estadisticas" else ""}"
           href="/admin/estadisticas"
           aria-label="Estadísticas" title="Estadísticas">{_ICONO_ESTADISTICAS}</a>"""
    return f"""
      <nav class="rail" aria-label="Secciones">
        <span class="lettermark" title="Nitro 2Tech">N2</span>
        <a class="rail-icono{" activo" if activo == "chats" else ""}"
           href="/admin/inbox"
           aria-label="Conversaciones" title="Conversaciones">{_ICONO_CHATS}</a>
        <a class="rail-icono{" activo" if activo == "contactos" else ""}"
           href="/admin/contactos"
           aria-label="Contactos" title="Contactos">{_ICONO_CONTACTOS}</a>{equipo_enlace}
        <a class="rail-icono{" activo" if activo == "configuracion" else ""}"
           href="/admin/configuracion"
           aria-label="Configuración" title="Configuración">{_ICONO_AJUSTES}</a>
        <span class="rail-hueco"></span>
        <button type="button" class="rail-icono" data-tema-boton
                title="Cambiar de tema">{_ICONO_TEMA}</button>
        <a class="rail-icono solo-ancho" href="/admin/logout"
           aria-label="Salir" title="Salir">{_ICONO_SALIR}</a>
        <span class="rail-negocio" title="{html.escape(config.BUSINESS_NAME)}"
              >{html.escape(_iniciales(config.BUSINESS_NAME))}</span>
      </nav>"""


# Los filtros del listado. Cada uno es una condición sobre lo que YA
# tiene la fila: nada de ir al servidor a preguntar otra vez.
#
# No hay "sin leer" a propósito. Haría falta guardar qué se ha visto y
# cuándo, que es una columna nueva y su migración; está apuntado como
# `docs/CONTINUAR_AQUI.md` §2. Un filtro que no filtre de verdad
# es peor que no tenerlo.
FILTROS = (
    ("todas", "Todas"),
    ("urgente", "Urgentes"),
    ("esperando", "Esperan respuesta"),
    ("mias", "Atendidas por mí"),
)


def _columna_lista(conversaciones: list, quien=None) -> str:
    """
    La columna del medio: cabecera, buscador, filtros, lista y pie.

    Quien entra por un área ve el nombre de su área en el título —así sabe
    por qué no están todas— y no ve el interruptor de la IA, que es del
    negocio entero y lo decide el dueño.
    """
    de_area = quien is not None and not quien.es_dueno
    titulo = (f'Conversaciones <span class="lista-area">'
              f'{html.escape(quien.area_nombre)}</span>' if de_area
              else "Conversaciones")
    pie_plan = "" if de_area else _control_plan()
    # El aviso de un pago cercano o atrasado, donde el dueño lo ve cada vez
    # que abre el panel. El import va aquí: `panel_plan` importa este módulo.
    from app.web.panel_plan import banda_de_cobro
    cobro = banda_de_cobro(quien)
    filtros = "".join(
        f'<button type="button" class="filtro{" activo" if clave == "todas" else ""}"'
        f' data-filtro="{clave}">{etiqueta}</button>'
        for clave, etiqueta in FILTROS)

    return f"""
      <aside class="col-lista">
        <div class="lista-cabecera">
          <div class="lista-titulo">
            <h1>{titulo}</h1>
            <span class="lista-cuenta" data-cuenta></span>
          </div>
          <div class="lista-buscar">
            {_ICONO_LUPA}
            <input type="search" id="buscar-conversacion"
                   placeholder="Buscar por nombre o número"
                   autocomplete="off" aria-label="Buscar una conversación">
          </div>
          <div class="lista-filtros">{filtros}</div>
          {cobro}
        </div>

        <div class="lista-scroll"></div>
        {_listado_inicial(conversaciones)}

        <div class="pie-lista">
          {pie_plan}
          {_credito("credito-lista")}
        </div>
      </aside>"""


def _control_plan() -> str:
    """
    El estado del bot, al pie de la lista.

    Antes era una tarjeta arriba del todo, del ancho de la pantalla. Pero
    no es una acción que se haga a diario —se enciende una vez y se
    olvida—, así que ocupaba el mejor sitio de la pantalla para no decir
    casi nada. Aquí abajo se ve siempre y no le quita espacio a las
    conversaciones, que es a lo que se viene.

    Cuatro estados, y los cuatro tienen que decir la verdad:

    - **Sin el paquete contratado**: ni botón ni instrucciones para
      conseguir una clave. Ofrecerle a alguien cómo activar algo que no
      compró es enseñarle una puerta cerrada — y antes de que existiera
      `ia_contratada`, esa puerta además se abría.
    - **Sin clave de Gemini**: no se ofrece un botón que no haría nada. Se
      le dice que nos avise: la clave es de la plataforma, no suya, así que
      explicarle cómo conseguirla era mandarlo a un sitio que no le toca.
    - **Plan Básico con clave puesta**: ya lo tiene todo, solo falta
      encenderlo. Un botón.
    - **Plan Pro**: se ve que está encendido y se puede apagar, que es lo
      que permite enseñarle a un cliente los dos bots en la misma
      conversación.
    """
    from app.bot import cerebro

    estado = cerebro.estado()

    if not estado["contratada"]:
        # Sin desplegable de ayuda: no hay nada que el dueño pueda hacer
        # por su cuenta, y un "cómo activarlo" que termina en "llámanos"
        # es peor que no decir nada. Si pregunta, se le vende.
        return """
          <div class="pie-estado">
            <span>Plan Básico · el bot responde con su menú</span>
          </div>"""

    if not estado["clave_configurada"]:
        return """
          <div class="pie-estado">
            <span>Plan Básico · el bot responde con su menú</span>
          </div>
          <details class="plan-ayuda">
            <summary>Activar la IA</summary>
            <p>Tu plan incluye la IA, pero todavía no está lista en tu
            cuenta. Avísanos y la dejamos preparada: al volver aquí
            aparecerá el botón para encenderla.</p>
          </details>"""

    if estado["ia_encendida"]:
        # Si la IA está encendida pero falla, el cliente no lo nota (se le
        # responde con el menú) y aquí sí tiene que notarse: si no, el
        # dueño ve "IA encendida" y un bot que responde como antes, sin
        # ninguna pista de por qué.
        fallo = estado.get("ultimo_fallo")
        aviso = ""
        if fallo:
            aviso = f"""
          <div class="plan-fallo">
            <strong>La IA no está respondiendo.</strong> Mientras tanto el bot
            contesta con su menú, así que ningún cliente se queda sin respuesta.
            <br>{html.escape(fallo["motivo"])} ({html.escape(fallo["cuando"])})
          </div>"""

        return f"""
          <div class="pie-estado">
            <span class="punto-vivo" aria-hidden="true"></span>
            <span>Bot con IA encendido</span>
            <button type="button" class="plan-btn" data-plan="basico">Apagar</button>
          </div>{aviso}"""

    return """
          <div class="pie-estado">
            <span>Plan Básico · tu clave de IA ya está puesta</span>
            <button type="button" class="plan-btn encender"
                    data-plan="pro">Encender IA</button>
          </div>"""


@router.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request, aviso: str = ""):
    sesion = _sesion_valida(request)
    # Sin quién (se le quitó el acceso, o su área ya no existe) es
    # como no tener sesión: la cookie sola no abre nada.
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        # Un negocio sin ninguna clave de acceso no puede ver un formulario
        # que nunca va a aceptar nada: se le dice qué le falta. Solo aplica
        # con subdominios, que es cuando la dirección ya dice de qué
        # negocio se trata; si no, aquí todavía no se sabe quién llama.
        if tenencia.dominio_base() and not acceso.panel_habilitado(
                tenencia.actual_o_none()):
            return HTMLResponse(_pagina("Sin configurar", SIN_CLAVE),
                                status_code=503)
        return _pedir_login(CADUCADA if _sesion_caducada(request) else "")

    bot_logic.liberar_conversaciones_vencidas()

    # Aquí se aterriza tras borrar un chat: el hilo ya no existe, así que
    # el resultado hay que contarlo aquí.
    banda = (f'<div class="banda ok">{html.escape(aviso)}</div>'
             if aviso else "")

    # La bandeja es el mismo armazón que el hilo, con la tercera columna
    # vacía. Antes eran dos páginas distintas —una lista centrada y una
    # de dos paneles— y al abrir una conversación se recargaba todo.
    return _renovar(HTMLResponse(_pagina("Bandeja", f"""
      <div class="armazon">
        {_rail(quien=quien)}
        {_columna_lista(message_log.conversaciones(
            filtro=equipo.filtro_contactos(quien)), quien)}
        <section class="panel-vacio">
          <div>
            {banda}
            <strong>Elige una conversación</strong>
            El bot atiende solo mientras tanto. Cuando escribas tú, se calla.
          </div>
        </section>
      </div>""",
        guiones=("panel-base.js", "panel-plan.js",
                 "panel-listado.js", "panel-vivo.js"),
        pantalla_completa=True)),
        request, sesion)


# ── La agenda: todas las personas que han escrito ────────────────────

# Cuántos contactos trae la agenda. La bandeja se queda en los 50 más
# recientes porque es una cola de trabajo; esto es un directorio, y un
# directorio que se corta por la mitad no sirve para buscar a nadie.
TOPE_AGENDA = 500


def _semana_atras():
    from datetime import timedelta
    return database.ahora_utc() - timedelta(days=7)


def _metricas(gente: list) -> tuple:
    """
    Las tres cifras de arriba.

    "Esperando respuesta tuya" NO es el estado que marcas a mano: es que
    **el último mensaje sea del cliente**. Es la diferencia entre lo que
    alguien se acordó de marcar y lo que de verdad está sin contestar, y
    la segunda es la que importa cuando abres esto por la mañana.
    """
    desde = _semana_atras()

    recientes = sum(1 for c in gente
                    if c["last_interaction"] and c["last_interaction"] >= desde)
    esperando = sum(1 for c in gente if c.get("ultimo_autor") == "cliente")

    return len(gente), recientes, esperando


def _fila_contacto(c: dict) -> dict:
    """Un contacto tal y como lo espera la tabla."""
    return {
        "phone": c["phone"],
        "name": c["name"] or "",
        "origen": c["origen"] or "",
        "servicio": c.get("servicio") or "",
        "estado_atencion": c.get("estado_atencion") or "",
        "etiquetas": c.get("etiquetas") or [],
        "esperando": c.get("ultimo_autor") == "cliente",
        "resumen": (c["ultimo_texto"] or "").split("\n")[0][:60],
        # En UTC y en ISO, como en el resto del panel: la fecha la escribe
        # el navegador, que sabe en qué huso está quien mira.
        "cuando": (c["last_interaction"].isoformat() + "Z"
                   if c.get("last_interaction") else ""),
    }


@router.get("/contactos", response_class=HTMLResponse)
def contactos(request: Request):
    """
    La agenda: la misma gente que la bandeja, pero como directorio.

    La bandeja responde a "¿a quién atiendo ahora?" y esta a "¿quién me
    ha escrito?". Por eso aquí caben 500 y allí 50, y por eso aquí hay
    teléfono y fecha en columnas y allí un resumen del último mensaje.
    """
    sesion = _sesion_valida(request)
    # Sin quién (se le quitó el acceso, o su área ya no existe) es
    # como no tener sesión: la cookie sola no abre nada.
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return _pedir_login(CADUCADA if _sesion_caducada(request) else "")

    gente = message_log.conversaciones(
        TOPE_AGENDA, filtro=equipo.filtro_contactos(quien))
    total, recientes, esperando = _metricas(gente)

    filas = json.dumps([_fila_contacto(c) for c in gente], ensure_ascii=False)
    # `<` escapado: sin eso, un nombre con "</script>" cerraría el bloque
    # antes de tiempo y el resto del JSON se ejecutaría como código.
    filas = filas.replace("<", "\\u003c")

    return _renovar(HTMLResponse(_pagina("Contactos", f"""
      <div class="armazon">
        {_rail("contactos", quien)}

        <main class="agenda">
          <header class="agenda-cabecera">
            <div class="agenda-titulo">
              <h1>Contactos</h1>
              <p class="apoyo">Todas las personas que han escrito a tu
                 WhatsApp.</p>
            </div>
            <div class="agenda-acciones">
              <div class="lista-buscar">
                {_ICONO_LUPA}
                <input type="search" id="buscar-contacto"
                       placeholder="Buscar por nombre o número"
                       autocomplete="off" aria-label="Buscar un contacto">
              </div>
              <a class="boton-solido" href="/admin/contactos.csv"
                 download>Exportar lista</a>
            </div>
          </header>

          <div class="metricas">
            <div class="metrica">
              <span>Contactos totales</span>
              <strong class="cifras">{total}</strong>
            </div>
            <div class="metrica acento">
              <span>Escribieron esta semana</span>
              <strong class="cifras">{recientes}</strong>
            </div>
            <div class="metrica aviso">
              <span>Esperando respuesta tuya</span>
              <strong class="cifras">{esperando}</strong>
            </div>
          </div>

          <div class="tabla-contactos">
            <div class="tabla-cabecera" role="row">
              <span>Contacto</span>
              <span>Teléfono</span>
              <span>Etiquetas</span>
              <span>Último mensaje</span>
              <span class="col-accion"></span>
            </div>
            <div class="tabla-cuerpo"></div>
          </div>

          <script type="application/json" id="contactos-inicial">{filas}</script>
          {_credito()}
        </main>
      </div>""",
        guiones=("panel-base.js", "panel-contactos.js"),
        pantalla_completa=True)),
        request, sesion)


def _quien_entro(sesion) -> str:
    """
    El correo de quien tiene la sesion abierta.

    El pase solo guarda el id, que no le dice nada a nadie. Si el
    usuario ya no está —se le dio de baja con la sesión abierta— se dice
    eso y no un id suelto.
    """
    for u in acceso.listar_usuarios(sesion.client_id):
        if u["id"] == sesion.user_id:
            return u["email"]
    return "sesión activa"


@router.get("/configuracion", response_class=HTMLResponse)
def configuracion(request: Request):
    """
    Los ajustes de quien atiende, no los del negocio.

    Lo del negocio —textos, precios, horarios— se toca en `/superadmin`,
    porque cambia lo que ven sus clientes. Aquí solo hay cosas que
    afectan a quien está mirando esta pantalla: si el navegador le avisa
    y de qué color ve el panel.

    Los avisos son **por dispositivo**. Activarlos en el computador de la
    oficina no los activa en el celular, y al revés: cada navegador se
    suscribe por su cuenta. Se dice en la pantalla porque si no, parece
    una avería.
    """
    sesion = _sesion_valida(request)
    # Sin quién (se le quitó el acceso, o su área ya no existe) es
    # como no tener sesión: la cookie sola no abre nada.
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return _pedir_login(CADUCADA if _sesion_caducada(request) else "")

    # Si el servidor no tiene claves VAPID, no se ofrece un interruptor
    # que no podría funcionar: se explica qué falta. Es mejor eso que
    # pedirle un permiso al navegador para nada.
    if not push.configurado():
        avisos = """
            <p class="ajuste-apoyo">Este servicio todavía no puede mandar
               avisos: le faltan sus claves de notificación. Se generan una
               sola vez y se ponen en la configuración del negocio.</p>
            <p class="ajuste-nota">Mientras tanto, el panel te sigue
               enseñando los mensajes nuevos en vivo si lo tienes abierto.</p>"""
    else:
        avisos = """
            <p class="ajuste-apoyo">Recibe un aviso del navegador cuando
               alguien te escriba, aunque tengas el panel cerrado.</p>

            <div class="ajuste-fila">
              <div class="ajuste-estado" data-estado-avisos>
                <span class="punto-vivo" aria-hidden="true"></span>
                <span data-texto-avisos>Comprobando…</span>
              </div>
              <button type="button" class="boton-solido" data-avisos hidden
                      >Activar</button>
            </div>

            <p class="ajuste-nota">Los avisos son <strong>de este
               dispositivo</strong>. Si entras desde el celular y desde el
               computador, tienes que activarlos en cada uno.</p>"""

    return _renovar(HTMLResponse(_pagina("Configuración", f"""
      <div class="armazon">
        {_rail("configuracion", quien)}

        <main class="agenda">
          <header class="agenda-cabecera">
            <div class="agenda-titulo">
              <h1>Configuración</h1>
              <p class="apoyo">Cómo te avisa y cómo se ve el panel. Solo
                 cambia para ti, no para tus clientes.</p>
            </div>
          </header>

          <section class="ajuste">
            <h2>Avisos del navegador</h2>
            {avisos}
          </section>

          <section class="ajuste">
            <h2>Apariencia</h2>
            <p class="ajuste-apoyo">Claro u oscuro. Se recuerda en este
               navegador; la primera vez lo decide tu sistema.</p>
            <div class="ajuste-fila">
              <div class="ajuste-estado">
                <span data-tema-actual>—</span>
              </div>
              <button type="button" class="boton-contorno"
                      data-tema-boton>Modo oscuro</button>
            </div>
          </section>

          <section class="ajuste">
            <h2>Tu sesión</h2>
            <p class="ajuste-apoyo">Se cierra sola tras un rato sin usarla.
               También puedes cerrarla ahora, por ejemplo si estás en un
               computador que no es tuyo.</p>
            <div class="ajuste-fila">
              <div class="ajuste-estado">
                <span>{html.escape(_quien_entro(sesion))}</span>
              </div>
              <a class="boton-contorno" href="/admin/logout">Cerrar sesión</a>
            </div>
          </section>

          {_credito()}
        </main>
      </div>""",
        guiones=("panel-base.js", "panel-ajustes.js"),
        pantalla_completa=True)),
        request, sesion)


@router.get("/contactos.csv")
def exportar_contactos(request: Request):
    """
    La agenda como archivo, para abrirla en Excel o subirla a otro sitio.

    Es de las pocas cosas del panel que salen de aquí, así que se sirve
    con el nombre del negocio y la fecha: un "contactos.csv" suelto en la
    carpeta de descargas no le dice nada a nadie dentro de dos semanas.
    """
    import csv
    import io as _io

    sesion = _sesion_valida(request)
    # Sin quién (se le quitó el acceso, o su área ya no existe) es
    # como no tener sesión: la cookie sola no abre nada.
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return _pedir_login(CADUCADA if _sesion_caducada(request) else "")

    buffer = _io.StringIO()
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow(["Nombre", "Telefono", "Origen", "Servicio",
                       "Estado", "Etiquetas", "Ultimo mensaje (UTC)",
                       "Esperando respuesta"])

    for c in message_log.conversaciones(
            TOPE_AGENDA, filtro=equipo.filtro_contactos(quien)):
        escritor.writerow([
            c["name"] or "",
            c["phone"],
            c["origen"] or "",
            c.get("servicio") or "",
            ETIQUETA_ESTADO.get(c.get("estado_atencion") or "", ""),
            ", ".join(c.get("etiquetas") or []),
            c["last_interaction"].strftime("%Y-%m-%d %H:%M")
            if c.get("last_interaction") else "",
            "si" if c.get("ultimo_autor") == "cliente" else "no",
        ])

    # `;` como separador y BOM al principio: es lo que hace que Excel en
    # español abra el archivo en columnas y respete las tildes. Con coma y
    # sin BOM, se ve todo en una columna y con la ñ rota.
    hoy = database.ahora_utc().strftime("%Y-%m-%d")
    # El nombre del negocio, reducido a lo que un sistema de archivos
    # acepta sin quejarse en Windows, en Mac y en Linux.
    apodo = "".join(ch if ch.isalnum() else "-"
                    for ch in (config.BUSINESS_NAME or "negocio").lower())
    nombre = f"contactos-{apodo.strip('-') or 'negocio'}-{hoy}.csv"

    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get("/api/chat/{phone}")
def api_chat(request: Request, phone: str, desde: int = 0):
    """Mensajes nuevos de una conversación, a partir de un id."""
    # Ojo: aquí NO se renueva la sesión. Es una consulta de fondo, y si
    # renovara, una pestaña abierta y olvidada no caducaría nunca.
    if (negado := _conversacion_ajena(request, phone)) is not None:
        return negado

    datos = message_log.conversacion_info(phone)
    mensajes = message_log.conversacion(phone, desde_id=desde or None)

    return {
        "mensajes": [
            {
                "id": m["id"],
                "quien": message_log.quien(m["direccion"], m["autor"]),
                "texto": m["texto"] or "",
                "hora": m["created_at"].strftime("%d/%m %H:%M") if m["created_at"] else "",
                # Los campos del adjunto tienen que ser LOS MISMOS que
                # publica el canal en vivo: los dos caminos terminan en la
                # misma función crearBurbuja() del navegador.
                **{k: v for k, v in m.items() if k.startswith("media_")},
            }
            for m in mensajes
        ],
        "atendido_por_humano": bool(datos and datos["atendido_por_humano"]),
        "ventana_abierta": bool(datos and datos["ventana_abierta"]),
        "horas_restantes": round(datos["horas_restantes"]) if datos else 0,
    }


# Cada cuánto se manda un latido por el canal en vivo. Sirve para que
# ningún intermediario dé la conexión por muerta y la corte, y para
# comprobar de paso que la sesión sigue valiendo.
SEGUNDOS_ENTRE_LATIDOS = 20


@router.get("/api/stream")
async def stream(request: Request, desde: int = 0):
    """
    Canal de avisos en vivo: el servidor empuja cada mensaje al panel.

    Sustituye al sondeo cada 3 segundos. Es más rápido (el mensaje sale en
    cuanto se guarda, no hasta 3 segundos después) y más barato (mientras
    no pasa nada, no se consulta la base para nada).
    """
    sesion = _sesion_valida(request)
    # Sin quién (se le quitó el acceso, o su área ya no existe) es
    # como no tener sesión: la cookie sola no abre nada.
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return JSONResponse({"error": "no autorizado"}, status_code=401)

    # La cola queda apuntada a ESTE negocio y solo recibe lo suyo (ver
    # app/core/eventos.py). Se suscribe aquí, dentro de la petición, que es
    # donde el inquilino está puesto.
    cola = eventos.suscribir()

    # Y se guarda a mano para lo que ocurre DESPUÉS: el cuerpo de una
    # respuesta en streaming se sirve fuera del ciclo normal de la
    # petición, y no hay que confiar en que el contexto siga puesto allí.
    # Sin esto, la recuperación de abajo consultaría sin filtro de
    # inquilino y le entregaría a este panel los mensajes de todos.
    inquilino = sesion.client_id

    # EL REPARTO ES POR NEGOCIO; EL FILTRO POR ÁREA VA AQUÍ.
    #
    # `eventos` entrega a este canal todo lo del negocio. Quien entra por un
    # área solo puede recibir lo de su área, así que cada aviso se mira
    # antes de mandarlo. La respuesta se guarda un rato por teléfono: una
    # conversación activa manda muchos mensajes seguidos y no hace falta
    # preguntar a la base por cada uno. Poco rato, porque el dueño puede
    # pasarle la conversación a otra área en cualquier momento.
    vistos: dict = {}
    filtro = equipo.filtro_contactos(quien)

    async def _la_ve(phone: str) -> bool:
        if quien.es_dueno:
            return True
        ahora = asyncio.get_running_loop().time()
        guardado = vistos.get(phone)
        if guardado and ahora - guardado[1] < 30:
            return guardado[0]
        with tenencia.usar(inquilino):
            ve = await run_in_threadpool(equipo.puede_ver, quien, phone)
        vistos[phone] = (ve, ahora)
        return ve

    async def emitir():
        try:
            # Lo que se haya perdido entre que la página se pintó y este
            # canal llegó a conectarse. Sin esto, un mensaje que caiga
            # justo en ese hueco no aparecería hasta recargar.
            if desde:
                with tenencia.usar(inquilino):
                    perdidos = await run_in_threadpool(
                        message_log.mensajes_desde, desde, 200, filtro)
                for m in perdidos:
                    yield f"data: {json.dumps(m)}\n\n"

            while True:
                try:
                    aviso = await asyncio.wait_for(
                        cola.get(), timeout=SEGUNDOS_ENTRE_LATIDOS)
                except asyncio.TimeoutError:
                    # La cookie que llegó con esta petición es la de
                    # cuando se abrió el canal, así que este control acaba
                    # cerrando el canal al vencer el plazo aunque sigas
                    # trabajando. No pasa nada: el navegador reconecta
                    # solo con la cookie fresca y se pone al día.
                    if not acceso.leer_pase(request.cookies.get(COOKIE, ""),
                                            inquilino):
                        yield "event: caducada\ndata: {}\n\n"
                        return
                    yield ": latido\n\n"
                    continue

                if not await _la_ve(aviso.get("phone", "")):
                    continue
                yield f"data: {json.dumps(aviso)}\n\n"
        finally:
            eventos.desuscribir(cola)

    return StreamingResponse(
        emitir(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Le dice a los proxys que no acumulen la respuesta antes de
            # entregarla; si lo hicieran, los mensajes llegarían a
            # bloques en vez de al instante.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/conversaciones")
def api_conversaciones(request: Request):
    """Listado para refrescar la barra lateral sin recargar la página."""
    # Consulta de fondo: valida pero no renueva (ver api_chat).
    quien = _quien(request)
    if quien is None:
        return JSONResponse({"error": "no autorizado"}, status_code=401)

    # El panel consulta esto cada pocos segundos, así que aquí es donde se
    # nota que una conversación abandonada vuelve sola al bot: sin esto
    # habría que esperar a que el cliente escribiera, o no pasaría nunca.
    bot_logic.liberar_conversaciones_vencidas()

    return {
        "conversaciones": [_fila_listado(c) for c in message_log.conversaciones(
            filtro=equipo.filtro_contactos(quien))]
    }


# ── Conversación ─────────────────────────────────────────────────────

@router.get("/chat/{phone}", response_class=HTMLResponse)
def chat(request: Request, phone: str, error: str = "", ok: str = ""):
    sesion = _sesion_valida(request)
    # Sin quién (se le quitó el acceso, o su área ya no existe) es
    # como no tener sesión: la cookie sola no abre nada.
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return _pedir_login(CADUCADA if _sesion_caducada(request) else "")

    # Una conversación de otra área se trata como una que no existe: de
    # vuelta a la bandeja, sin confirmar que ese cliente está.
    if not equipo.puede_ver(quien, phone):
        return RedirectResponse("/admin/inbox", status_code=303)

    return _renovar(HTMLResponse(_pintar_chat(phone, quien, error=error, ok=ok)),
                    request, sesion)


class _MensajeRequest(BaseModel):
    # El tope real lo pone _enviar_a_mano, que da un error explicando
    # cuánto se pasó. Este solo evita tragarse un cuerpo enorme.
    texto: str = Field(max_length=LIMITE_WHATSAPP * 2)


def _enviar_a_mano(phone: str, texto: str) -> str | None:
    """
    Manda la respuesta escrita por el asesor. Devuelve el motivo del
    fallo, o None si salió bien.

    Lo usan las dos puertas de entrada — el envío de fondo del panel y el
    POST de formulario de respaldo — para que no puedan divergir.

    El orden importa: primero se marca como atendido por humano y luego
    se envía. Si se hiciera al revés y el cliente contestara rapidísimo,
    el bot podría colarse con una respuesta automática en medio.
    """
    if not texto:
        return "Escribe un mensaje."

    # El maxlength del navegador se puede saltar; comprobamos aquí también
    # para dar un error claro en vez de que Meta rechace el envío.
    if len(texto) > LIMITE_WHATSAPP:
        return (f"El mensaje tiene {len(texto)} caracteres y el máximo de "
                f"WhatsApp es {LIMITE_WHATSAPP}. Divídelo en dos.")

    bot_logic.tomar_control_manual(phone)

    envio = wa.send_text_message(phone, texto, autor="humano")
    if envio.status_code >= 400:
        return _motivo_fallo(envio)

    return None


@router.post("/api/chat/{phone}/enviar")
def api_enviar(request: Request, phone: str, datos: _MensajeRequest):
    """
    Envía la respuesta y contesta en JSON, sin recargar la página.

    Existe para que la cajita de texto se vacíe en el instante en que das
    Enter. Con el POST de formulario había que esperar a que Meta
    contestara para que la página se volviera a pintar, y durante ese
    segundo largo el texto seguía a la vista: parecía que no se había
    enviado y se acababa mandando dos veces.

    Consulta de fondo: valida pero no renueva la sesión (ver api_chat).
    """
    if (negado := _conversacion_ajena(request, phone)) is not None:
        return negado

    fallo = _enviar_a_mano(phone, (datos.texto or "").strip())
    if fallo:
        return JSONResponse({"ok": False, "error": fallo}, status_code=400)

    return {"ok": True}


# ── Archivos: verlos y mandarlos ─────────────────────────────────────

@router.get("/media/{message_id}")
async def ver_media(request: Request, message_id: int, descargar: int = 0):
    """
    Sirve el archivo de un mensaje: la imagen, la nota de voz, el PDF.

    Va bajo /admin y detrás de la sesión a propósito. Estas son fotos que
    manda un cliente por privado —una factura, una cédula, el interior de
    su casa— y no pueden quedar en una URL abierta que solo hay que
    adivinar. Con `?descargar=1` se guarda en vez de abrirse.

    Si no está en el caché de disco se baja de Meta al vuelo. Por eso el
    caché puede durar un día sin que se note: mientras el archivo siga
    vivo allí (7 días desde que entró), se recupera solo.
    """
    quien = _quien(request)
    if quien is None:
        return JSONResponse({"error": "no autorizado"}, status_code=401)

    ficha = await run_in_threadpool(message_log.adjunto_de, message_id)
    # La misma respuesta si no existe que si es de otra área: probando
    # números de mensaje no se puede saber qué hay en las demás.
    if not ficha or not await run_in_threadpool(
            equipo.puede_ver, quien, ficha["phone"]):
        return JSONResponse({"error": "ese mensaje no tiene archivo"},
                            status_code=404)

    try:
        contenido, mime = await run_in_threadpool(
            media.obtener, message_id, ficha["media_id"], ficha["media_mime"])
    except media.MediaError as e:
        # Lo normal aquí es que hayan pasado los 7 días de Meta. Se
        # responde 410 (se fue) y no 404 (nunca estuvo), que es lo que de
        # verdad pasó.
        return JSONResponse({"error": str(e)}, status_code=410)

    cabeceras = {
        # PRIVATE, no public: es el archivo de la conversación de alguien.
        # Una hora basta para que el hilo no vuelva a pedir la misma
        # imagen cada vez que se hace scroll.
        "Cache-Control": "private, max-age=3600",
    }
    if descargar:
        nombre = ficha["media_nombre"] or f"{message_id}{media.extension_de(mime)}"
        # Dos formas del nombre a propósito. `filename` con los acentos y
        # los espacios quitados, para navegadores viejos; `filename*` con
        # el nombre real codificado, que es el que usan los de hoy. Con
        # solo el primero, "cotización final.pdf" se guardaba como
        # "cotizaci%C3%B3n+final.pdf".
        simple = re.sub(r'[^A-Za-z0-9._-]', "_", nombre) or "archivo"
        cabeceras["Content-Disposition"] = (
            f'attachment; filename="{simple}"; '
            f"filename*=UTF-8''{quote(nombre)}")

    return Response(content=contenido, media_type=mime or "application/octet-stream",
                    headers=cabeceras)


# Lo que el panel puede mandar. Los documentos no entran de momento: el
# caso real es la foto y la nota de voz, y cada tipo nuevo son más
# formatos que probar contra Meta.
_ADJUNTOS_ACEPTADOS = ("imagen", "audio")


@router.post("/api/chat/{phone}/adjunto")
async def api_adjunto(request: Request, phone: str):
    """
    Manda una imagen o una nota de voz al cliente, desde el panel.

    Se lee el multipart a mano en vez de con UploadFile porque el campo
    `clase` decide cómo se trata el archivo, y así los dos van juntos en
    un solo sitio.

    Igual que el texto: primero se toma el control de la conversación y
    luego se envía, para que el bot no se cuele con una respuesta
    automática mientras Meta procesa la subida.
    """
    if (negado := _conversacion_ajena(request, phone)) is not None:
        return negado

    formulario = await request.form()
    subido = formulario.get("archivo")
    clase = (formulario.get("clase") or "imagen").strip().lower()
    pie = (formulario.get("texto") or "").strip()

    if subido is None or not hasattr(subido, "read"):
        return JSONResponse({"ok": False, "error": "No llegó ningún archivo."},
                            status_code=400)
    if clase not in _ADJUNTOS_ACEPTADOS:
        return JSONResponse({"ok": False, "error": "Tipo de archivo no admitido."},
                            status_code=400)

    contenido = await subido.read()
    if not contenido:
        return JSONResponse({"ok": False, "error": "El archivo llegó vacío."},
                            status_code=400)

    try:
        fallo, aviso = await run_in_threadpool(
            _mandar_adjunto, phone, clase, contenido,
            subido.content_type or "", pie)
    except media.MediaError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    if fallo:
        return JSONResponse({"ok": False, "error": fallo}, status_code=400)

    # `aviso` es para lo que se envió PERO no como se esperaba. El caso
    # real: la grabación salió como archivo de audio y no como nota de
    # voz. Se manda igual, pero el dueño tiene que enterarse.
    return {"ok": True, "aviso": aviso} if aviso else {"ok": True}


def _mandar_adjunto(phone: str, clase: str, contenido: bytes,
                    mime: str, pie: str) -> tuple[str | None, str | None]:
    """
    Prepara el archivo, lo sube y lo envía. Devuelve (fallo, aviso): el
    motivo del error si no se pudo, y una advertencia si se envió pero
    con alguna pega.

    Aparte del endpoint porque todo esto es bloqueante (Pillow, PyAV y dos
    llamadas HTTP a Meta) y corre en el threadpool.
    """
    es_nota_de_voz = True
    if clase == "imagen":
        listo, mime_final = media.preparar_imagen(contenido)
        nombre = "imagen" + media.extension_de(mime_final)
    else:
        listo, mime_final, es_nota_de_voz = media.a_nota_de_voz(contenido, mime)
        nombre = "nota-de-voz" + media.extension_de(mime_final)

    tope = (config.MEDIA_MAX_MB_IMAGEN if clase == "imagen"
            else config.MEDIA_MAX_MB_AUDIO) * 1024 * 1024
    if len(listo) > tope:
        return (f"El archivo pesa más de lo que admite WhatsApp "
                f"({tope // (1024*1024)} MB).", None)

    aviso = None
    if not es_nota_de_voz:
        aviso = ("Se envió como archivo de audio, no como nota de voz: no se "
                 "pudo convertir la grabación. Revisa /admin/status.")
    elif len(listo) > 512 * 1024:
        # Meta solo dibuja el botón de reproducir hasta 512 KB; por encima
        # lo cambia por uno de descarga y deja de parecer una nota de voz.
        aviso = ("La grabación es larga y pesa más de 512 KB: al cliente le "
                 "saldrá un icono de descarga en vez del de reproducir.")

    media_id = media.subir(listo, mime_final, nombre)

    bot_logic.tomar_control_manual(phone)

    if clase == "imagen":
        envio = wa.send_image_message(phone, media_id, pie, autor="humano")
    else:
        # `voice` es lo que hace que se vea como nota de voz y no como un
        # archivo. Si la conversión falló va en False, porque pedir una
        # nota de voz con un archivo que no es OGG/Opus es mentirle a Meta.
        envio = wa.send_audio_message(phone, media_id, mime_final,
                                      autor="humano", voice=es_nota_de_voz)

    if envio.status_code >= 400:
        return _motivo_fallo(envio), None

    # La copia se guarda con el id del MENSAJE que acabó de crear
    # send_*_message, para que el hilo la pinte sin volver a bajarla de
    # Meta. Si no se encuentra, no pasa nada: se bajará cuando se mire.
    ultimo = message_log.ultimo_saliente(phone)
    if ultimo:
        media.escribir_cache(ultimo, mime_final, listo)

    return None, aviso


class _PlanRequest(BaseModel):
    plan: str = Field(default="", max_length=10)


@router.post("/api/plan")
def api_plan(request: Request, datos: _PlanRequest):
    """
    Enciende o apaga la IA desde el panel, sin reiniciar el servicio.

    Es la segunda mitad de subir a plan Pro: el dueño pega su clave de
    Gemini en las variables del servicio y lo activa aquí. Tiene efecto en
    el siguiente mensaje que le escriban.

    Esto SÍ renueva la sesión: es una acción del dueño, no una consulta de
    fondo del panel.
    """
    sesion = _sesion_valida(request)
    # Sin quién (se le quitó el acceso, o su área ya no existe) es
    # como no tener sesión: la cookie sola no abre nada.
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return JSONResponse({"error": "no autorizado"}, status_code=401)
    # La IA es del negocio entero: la enciende o la apaga el dueño.
    if not quien.es_dueno:
        return JSONResponse({"ok": False, "error": "Solo el administrador "
                             "puede encender o apagar la IA."}, status_code=403)

    from app.bot import cerebro

    try:
        cerebro.cambiar_plan((datos.plan or "").strip().lower())
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    return _renovar(JSONResponse({"ok": True, **cerebro.estado()}), request, sesion)


class _EstadoRequest(BaseModel):
    estado: str = Field(default="", max_length=20)


@router.post("/api/chat/{phone}/estado")
def api_estado(request: Request, phone: str, datos: _EstadoRequest):
    """
    Marca en qué punto de atención está esta conversación.

    Consulta de fondo: valida pero no renueva la sesión (ver api_chat).
    """
    if (negado := _conversacion_ajena(request, phone)) is not None:
        return negado

    if not database.guardar_estado_atencion(phone, (datos.estado or "").strip()):
        return JSONResponse(
            {"ok": False, "error": "Ese contacto ya no existe, o el estado no vale."},
            status_code=400)

    return {"ok": True}


class _EtiquetasRequest(BaseModel):
    # El tope real lo pone `database._limpiar_etiquetas`, que recorta y
    # descarta. Esto solo evita tragarse un cuerpo enorme.
    etiquetas: list[str] = Field(default_factory=list, max_length=50)


class _NotaRequest(BaseModel):
    nota: str = Field(default="", max_length=database.LARGO_NOTA * 2)


@router.post("/api/chat/{phone}/etiquetas")
def api_etiquetas(request: Request, phone: str, datos: _EtiquetasRequest):
    """
    Guarda las etiquetas libres de un contacto.

    Devuelve las que QUEDARON, no las que se mandaron: el servidor
    recorta, quita repetidas y aplica el tope, así que el panel tiene que
    repintar con lo que respondió y no con lo que envió. Si no, se vería
    una etiqueta de 60 caracteres que en la base está cortada a 24.
    """
    if (negado := _conversacion_ajena(request, phone)) is not None:
        return negado

    quedaron = database.guardar_etiquetas(phone, datos.etiquetas)
    if quedaron is None:
        return JSONResponse({"ok": False, "error": "Ese contacto ya no existe."},
                            status_code=400)

    return {"ok": True, "etiquetas": quedaron}


@router.post("/api/chat/{phone}/nota")
def api_nota(request: Request, phone: str, datos: _NotaRequest):
    """
    Guarda la nota interna de un contacto.

    NO se le manda nunca al cliente: el bot no lee esta columna. Quien
    escribe una nota cuenta con eso.
    """
    if (negado := _conversacion_ajena(request, phone)) is not None:
        return negado

    if not database.guardar_nota(phone, datos.nota):
        return JSONResponse({"ok": False, "error": "Ese contacto ya no existe."},
                            status_code=400)

    return {"ok": True}


class _AreaRequest(BaseModel):
    area: str = Field(default="", max_length=60)


@router.post("/api/chat/{phone}/area")
def api_area(request: Request, phone: str, datos: _AreaRequest):
    """
    El dueño le pasa esta conversación a un área, o se la queda ("").

    Solo el dueño: un área no puede quedarse con conversaciones ajenas ni
    soltar las suyas. La decisión manda sobre la opción del menú que
    eligió el cliente (ver `app/core/equipo.py`).
    """
    if (negado := _solo_dueno(request)) is not None:
        return negado

    if not equipo.asignar(phone, (datos.area or "").strip() or None):
        return JSONResponse({"ok": False, "error": "Esa conversación o esa área "
                             "ya no existen."}, status_code=400)
    return {"ok": True}


@router.post("/api/chat/{phone}/reiniciar")
def api_reiniciar(request: Request, phone: str):
    """
    Devuelve esta conversación a su principio.

    Es lo que hacía falta para poder PROBAR un cambio: lo que se edita en
    el panel —el saludo, el menú— solo se ve al empezar de cero, y quien
    prueba su propio bot ya tiene una conversación a medias.
    """
    if (negado := _conversacion_ajena(request, phone)) is not None:
        return negado

    if not database.reiniciar_conversacion(phone):
        return JSONResponse({"ok": False, "error": "Ese contacto ya no existe."},
                            status_code=400)

    print(f"[panel] Conversación de {phone} reiniciada desde el panel.")
    return {"ok": True}


@router.post("/api/chat/{phone}/borrar")
def api_borrar(request: Request, phone: str):
    """
    Borra el contacto y todo su historial. No tiene vuelta atrás.

    No toca Google Calendar a propósito: si el contacto tenía citas, sus
    ids de evento vuelven en la respuesta para que el panel pueda avisar
    de que siguen en el calendario.
    """
    if (negado := _solo_dueno(request)) is not None:
        return negado

    borrado = database.borrar_contacto(phone)
    if borrado is None:
        return JSONResponse({"ok": False, "error": "Ese contacto ya no existe."},
                            status_code=404)

    return {"ok": True, **borrado}


# ── Avisos al celular ────────────────────────────────────────────────

class _LlavesPush(BaseModel):
    p256dh: str
    auth: str


class _SuscripcionPush(BaseModel):
    endpoint: str
    keys: _LlavesPush


class _BajaPush(BaseModel):
    endpoint: str


@router.get("/api/push/clave")
def api_push_clave(request: Request):
    """
    La clave pública con la que el navegador se suscribe.

    Devuelve cadena vacía si no hay claves configuradas. El panel lo usa
    para decidir si ofrece o no el botón: es mejor no ofrecerlo que
    pedirle al dueño un permiso que después no le va a servir de nada.
    """
    if _quien(request) is None:
        return JSONResponse({"error": "no autorizado"}, status_code=401)

    return {"clave": config.VAPID_PUBLIC_KEY if push.configurado() else ""}


@router.post("/api/push/suscribir")
def api_push_suscribir(request: Request, datos: _SuscripcionPush):
    """Apunta este dispositivo para recibir los avisos."""
    quien = _quien(request)
    if quien is None:
        return JSONResponse({"error": "no autorizado"}, status_code=401)

    # Con el usuario: el aviso de un cliente de Ventas no le suena a Soporte.
    database.guardar_suscripcion_push(
        datos.endpoint, datos.keys.p256dh, datos.keys.auth,
        user_id=quien.user_id or None)
    return {"ok": True}


@router.post("/api/push/baja")
def api_push_baja(request: Request, datos: _BajaPush):
    """Deja de avisar a este dispositivo."""
    if _quien(request) is None:
        return JSONResponse({"error": "no autorizado"}, status_code=401)

    return {"ok": database.borrar_suscripcion_push(datos.endpoint)}


@router.post("/chat/{phone}")
def responder(request: Request, phone: str, texto: str = Form(...)):
    """
    Respaldo sin JavaScript: envía y recarga la página.

    Lo normal es que el panel mande por `api_enviar` y no pase por aquí.
    Esto queda para un navegador con JS desactivado, igual que el sondeo
    es el plan B del canal en vivo.
    """
    sesion = _sesion_valida(request)
    # Sin quién (se le quitó el acceso, o su área ya no existe) es
    # como no tener sesión: la cookie sola no abre nada.
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return _pedir_login(CADUCADA if _sesion_caducada(request) else "")

    # Una conversación de otra área se trata como una que no existe: de
    # vuelta a la bandeja, sin confirmar que ese cliente está.
    if not equipo.puede_ver(quien, phone):
        return RedirectResponse("/admin/inbox", status_code=303)

    fallo = _enviar_a_mano(phone, (texto or "").strip())
    cola = f"?error={quote_plus(fallo)}" if fallo else ""

    return _renovar(
        RedirectResponse(f"/admin/chat/{phone}{cola}", status_code=303),
        request, sesion)


@router.post("/chat/{phone}/devolver")
def devolver(request: Request, phone: str):
    sesion = _sesion_valida(request)
    # Sin quién (se le quitó el acceso, o su área ya no existe) es
    # como no tener sesión: la cookie sola no abre nada.
    quien = equipo.de_pase(sesion)
    if not sesion or quien is None:
        return _pedir_login(CADUCADA if _sesion_caducada(request) else "")

    # Una conversación de otra área se trata como una que no existe: de
    # vuelta a la bandeja, sin confirmar que ese cliente está.
    if not equipo.puede_ver(quien, phone):
        return RedirectResponse("/admin/inbox", status_code=303)

    bot_logic.devolver_control_al_bot(phone)
    return _renovar(
        RedirectResponse(f"/admin/chat/{phone}?ok=El+bot+vuelve+a+responder",
                         status_code=303),
        request, sesion)


def _motivo_fallo(respuesta) -> str:
    """Traduce el error de Meta a algo accionable, en texto normal."""
    try:
        error = respuesta.json().get("error", {})
        codigo = error.get("code")
    except ValueError:
        codigo = None

    if codigo == 131047:
        return ("Pasaron más de 24h desde su último mensaje. WhatsApp no permite "
                "escribir libremente: hace falta una plantilla aprobada.")
    return "No se pudo enviar. Revisa los logs del servidor."




def _pintar_adjunto(m: dict) -> str:
    """
    El adjunto de un mensaje, en HTML. Cadena vacía si era solo texto.

    Es el gemelo en servidor de `crearAdjunto()` del guion del navegador:
    la primera carga la pinta este, y todo lo que llegue después lo pinta
    aquel. **Si cambias uno, cambia el otro** — el hilo ya divergió una vez
    por tener dos generadores y costó encontrarlo.
    """
    tipo = m.get("media_tipo")
    if not tipo:
        return ""

    etiqueta = html.escape(m.get("media_etiqueta") or "Archivo")

    if not m.get("media_disponible"):
        return (f'<div class="adjunto"><div class="adjunto-ido">'
                f'{etiqueta} — ya no disponible</div></div>')

    url = html.escape(m.get("media_url") or "")

    if tipo == "image":
        cuerpo = (f'<a href="{url}" target="_blank" rel="noopener">'
                  f'<img src="{url}" alt="{etiqueta}" loading="lazy"></a>')
    elif tipo == "audio":
        cuerpo = f'<audio controls preload="none" src="{url}"></audio>'
    else:
        cuerpo = (f'<a class="adjunto-archivo" href="{url}" target="_blank" '
                  f'rel="noopener">{etiqueta}</a>')

    return (f'<div class="adjunto">{cuerpo}'
            f'<a class="adjunto-bajar" href="{url}?descargar=1">Guardar</a></div>')


def _bloque_area(datos: dict, es_dueno: bool) -> str:
    """
    De qué área es esta conversación y, para el dueño, a cuál pasarla.

    El área sale de la opción del menú que eligió el cliente; el dueño
    puede pasársela a otra a mano, y esa decisión manda (ver
    `app/core/equipo.py`). Sin áreas en el negocio no se pinta: en el plan
    Básico no hay nada que repartir.
    """
    areas = equipo.areas()
    if not areas:
        return ""

    actual = equipo.area_de_contacto(datos.get("servicio_id"),
                                     datos.get("area_asignada"))
    nombre = next((a.get("nombre") or a["id"] for a in areas
                   if a["id"] == actual), "Tú (administrador)")

    if not es_dueno:
        return f"""
          <section class="ficha-bloque">
            <h2>Área</h2>
            <p class="ficha-area">{html.escape(nombre)}</p>
          </section>"""

    opciones = "".join(
        f'<option value="{html.escape(a["id"])}"'
        f'{" selected" if a["id"] == actual else ""}>'
        f'{html.escape(a.get("nombre") or a["id"])}</option>'
        for a in areas)
    return f"""
          <section class="ficha-bloque">
            <h2>Área que la atiende</h2>
            <select class="ficha-area-elegir" data-asignar-area
                    aria-label="Área que atiende esta conversación">
              <option value=""{" selected" if actual is None else ""}>Tú (administrador)</option>
              {opciones}
            </select>
            <p class="ficha-nota-pie">Al cambiarla, esa área la ve en su panel
               y las demás dejan de verla.</p>
          </section>"""


def _ficha_contacto(phone: str, datos: dict, mensajes: list,
                    es_dueno: bool = True) -> str:
    """
    La columna de la derecha: quién es y por dónde ha pasado.

    Todo lo que enseña sale de lo que ya está en la base, incluidas las
    etiquetas libres y la nota interna, que se editan aquí mismo
    (`panel-ficha.js`).

    Se esconde por CSS por debajo de 1200px: en un portátil pequeño el
    hilo importa más que la ficha. Ahí no desaparece — el botón de la
    cabecera del hilo la trae como panel encima. Es el MISMO HTML movido
    de sitio, no una copia: dos fichas que mantener acabarían
    diferenciándose.
    """
    if not datos:
        return ""

    nombre = datos.get("name") or "(sin nombre)"

    # La presencia, en una frase. Es la misma información que el chip del
    # listado, dicha para quien ya está dentro de la conversación.
    if datos.get("atendido_por_humano"):
        presencia, clase = "La atiendes tú", "mia"
    elif not datos.get("ventana_abierta"):
        presencia, clase = "Ventana cerrada", "cerrada"
    else:
        presencia, clase = "La atiende el bot", "bot"

    # El recorrido viene como "Vio precios > Pidió asesor". Se parte para
    # pintarlo como pasos: leído en vertical se ve de un vistazo por
    # dónde va, que es justo lo que hay que saber antes de escribirle.
    pasos = [p.strip() for p in (datos.get("recorrido") or "").split(">") if p.strip()]
    if pasos:
        lista = "".join(f'<li>{html.escape(p)}</li>' for p in pasos)
        recorrido = f"""
          <section class="ficha-bloque">
            <h2>Recorrido en el bot</h2>
            <ol class="ficha-pasos">{lista}</ol>
          </section>"""
    else:
        recorrido = ""

    servicio = datos.get("servicio")
    chip_servicio = (f'<span class="chip servicio">{html.escape(servicio)}</span>'
                     if servicio else "")

    # Las etiquetas libres se pintan aquí y se editan en el navegador
    # (`panel-ficha.js`). El servicio va en la misma caja porque para
    # quien mira son lo mismo —cosas que describen a este contacto—,
    # aunque una la ponga el bot y las otras una persona; por eso el
    # servicio no lleva el aspa de quitar.
    sueltas = "".join(
        f'<span class="chip etiqueta" data-etiqueta="{html.escape(e)}">'
        f'{html.escape(e)}'
        f'<button type="button" class="quitar-etiqueta" aria-label="Quitar la '
        f'etiqueta {html.escape(e)}">&times;</button></span>'
        for e in datos.get("etiquetas") or [])

    etiquetas = f"""
          <section class="ficha-bloque">
            <h2>Etiquetas</h2>
            <div class="ficha-etiquetas" data-etiquetas>
              {chip_servicio}
              {sueltas}
              <button type="button" class="anadir-etiqueta"
                      data-anadir-etiqueta>+ Añadir</button>
              <input type="text" class="nueva-etiqueta" data-nueva-etiqueta
                     maxlength="{database.LARGO_ETIQUETA}" hidden
                     placeholder="cliente viejo" aria-label="Etiqueta nueva">
            </div>
          </section>"""

    # "Primer mensaje" sale del hilo que ya se cargó: no cuesta una
    # consulta más. El total sí es el de los mensajes traídos, así que se
    # dice "en este hilo" y no "en total" — el hilo tiene tope.
    primero = mensajes[0]["created_at"] if mensajes else None
    desde = (f'<time datetime="{primero.isoformat()}Z" data-fecha></time>'
             if primero else "—")

    return f"""
      <aside class="ficha" id="ficha-contacto">
        <button type="button" class="cerrar-ficha" data-cerrar-ficha
                aria-label="Cerrar la ficha">&times;</button>
        <div class="ficha-arriba">
          <span class="ficha-inicial" aria-hidden="true"
                >{html.escape(_iniciales(nombre))}</span>
          <strong>{html.escape(nombre)}</strong>
          <span class="ficha-telefono telefono">{html.escape(phone)}</span>
          <span class="ficha-presencia {clase}">
            <span class="punto-vivo" aria-hidden="true"></span>
            {presencia}</span>
        </div>

        {_bloque_area(datos, es_dueno)}
        {etiquetas}
        {recorrido}

        <section class="ficha-bloque">
          <h2>Datos</h2>
          <div class="ficha-dato"><span>Primer mensaje</span><span>{desde}</span></div>
          <div class="ficha-dato"><span>Mensajes en este hilo</span>
            <span>{len(mensajes)}</span></div>
          <div class="ficha-dato"><span>Origen</span>
            <span>{html.escape(datos.get("origen") or "—")}</span></div>
        </section>

        <section class="ficha-bloque">
          <h2>Nota interna</h2>
          <textarea class="ficha-nota" data-nota rows="3"
                    maxlength="{database.LARGO_NOTA}"
                    placeholder="Solo la ves tú. El cliente nunca la recibe."
                    >{html.escape(datos.get("nota_interna") or "")}</textarea>
          <span class="ficha-guardado" data-guardado hidden>Guardado</span>
        </section>
      </aside>"""


def _pintar_chat(phone: str, quien=None, error: str = "", ok: str = "") -> str:
    mensajes = message_log.conversacion(phone)

    # El listado de al lado sí hace falta entero; los datos de ESTA
    # conversación se piden aparte, en vez de buscarlos dentro del listado.
    conversaciones = message_log.conversaciones(
        200, filtro=equipo.filtro_contactos(quien) if quien else None)
    datos = message_log.conversacion_info(phone)
    es_dueno = quien is None or quien.es_dueno
    abierta = bool(datos and datos["ventana_abierta"])
    horas = datos["horas_restantes"] if datos else 0
    nombre = html.escape((datos or {}).get("name") or "(sin nombre)")
    atendido = (datos or {}).get("atendido_por_humano")

    # El estado se marca desde aquí y se ve en el listado. Las opciones se
    # pintan en el servidor a partir de la misma lista que valida el
    # endpoint, así que no puede aparecer en pantalla un estado que la
    # base vaya a rechazar.
    estado_actual = (datos or {}).get("estado_atencion") or ""

    # En el teléfono este control se queda en icono, como Reiniciar y
    # Eliminar. El color dice cuál es el estado, pero un color no lo lee
    # un lector de pantalla: el nombre va aquí.
    _ETIQUETA_ESTADO_LARGA = (
        f"Estado: {ETIQUETA_ESTADO[estado_actual]}. Cambiarlo"
        if estado_actual in ETIQUETA_ESTADO else "Marcar un estado")
    opciones_estado = "".join(
        f'<button type="button" class="chip estado {clave}" data-estado="{clave}">'
        f'{ETIQUETA_ESTADO[clave]}</button>'
        for clave in database.ESTADOS_ATENCION
    ) + ('<button type="button" class="chip estado sin-estado" data-estado="">'
         'Quitar la marca</button>')

    # Contexto de la conversación: qué servicio eligió y por dónde pasó.
    # Va en la cabecera y no dentro del hilo para que siga a la vista
    # aunque hagas scroll: es lo que necesitas mientras escribes.
    servicio = (datos or {}).get("servicio") or ""
    recorrido = (datos or {}).get("recorrido") or ""
    if servicio or recorrido:
        partes = []
        if servicio:
            partes.append(f'<strong>{html.escape(servicio)}</strong>')
        if recorrido:
            partes.append(html.escape(recorrido))
        contexto = f'<div class="contexto">{" · ".join(partes)}</div>'
    else:
        contexto = ('<div class="contexto tenue">Todavía no ha elegido '
                    'ningún servicio.</div>')

    burbujas = []
    for m in mensajes:
        clase = message_log.quien(m["direccion"], m["autor"])
        # El instante en UTC, y la hora en blanco: la escribe el navegador
        # (`ponerSeparadores` en panel-chat.js), que es el único de los dos
        # que sabe en qué huso está sentado quien atiende. Antes salía
        # "15:31 UTC" para un mensaje que en Medellín llegó a las 10:31.
        iso = m["created_at"].isoformat() + "Z" if m["created_at"] else ""
        # Una imagen puede venir sin pie de foto: entonces no se pinta la
        # caja del texto, que solo dejaría un hueco debajo.
        cuerpo = (f'<div class="texto">{html.escape(m["texto"])}</div>'
                  if m.get("texto") else "")
        burbujas.append(f"""
          <div class="burbuja {clase}" data-iso="{iso}">
            <div class="meta">{ETIQUETA_AUTOR[clase]} · <time data-hora
                 datetime="{iso}"></time></div>
            {_pintar_adjunto(m)}
            {cuerpo}
          </div>""")

    if not burbujas:
        burbujas = ['<p class="tenue">Sin mensajes todavía.</p>']

    if abierta:
        estado_ventana = (f'<div class="banda ok">Puedes responder libremente. '
                          f'Quedan {horas:.0f} h de la ventana de 24 horas.</div>')
        # maxlength 4096: es el máximo que admite un mensaje de texto de
        # WhatsApp. Mejor que el navegador lo corte a que Meta rechace el
        # envío entero cuando ya lo diste por enviado.
        # La caja y el botón van en la misma fila, como en WhatsApp: el
        # botón es un círculo con el avión, no una barra con texto. Ocupa
        # menos y deja la caja crecer hacia arriba al escribir.
        # El input de archivo NO lleva el atributo `capture`: con él, el
        # celular abre la cámara directamente. Sin él, ofrece la galería y
        # el explorador, que es lo que se quiere — las fotos que se mandan
        # a un cliente ya están hechas, no se toman en el momento.
        #
        # accept en JPEG y PNG porque son los dos únicos formatos que
        # acepta Meta. Un HEIC de iPhone se descarta antes de subirlo, y
        # lo que se cuele lo convierte Pillow en el servidor.
        # El orden en el HTML es el orden en pantalla: adjuntar, la caja
        # de texto, y a la derecha UN solo botón. Cuál de los dos se ve lo
        # decide el CSS según haya texto escrito o no — el micrófono
        # cuando está vacía, el avión en cuanto escribes.
        #
        # La vista de grabación va DENTRO de la misma fila y no en una
        # banda aparte: mientras se graba ocupa el sitio que dejan el
        # botón de adjuntar y la caja de texto, y el micrófono de la
        # derecha se queda donde está. Eso último no es estético — es el
        # botón que tienes pulsado, y si desapareciera el navegador
        # perdería la captura del puntero y "soltar para enviar" dejaría
        # de funcionar.
        formulario = f"""
          <form method="post" class="responder">
            <div class="fila-envio" id="fila-envio">
              <input type="file" id="archivo" accept="image/jpeg,image/png" hidden>
              <button type="button" class="adjuntar" id="btn-adjuntar"
                      aria-label="Adjuntar una imagen" title="Adjuntar una imagen">
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                  <path fill="currentColor" d="M16.5 6.5v9a4.5 4.5 0 1 1-9 0V5.75a3 3 0 1 1 6 0v9a1.5 1.5 0 1 1-3 0V6.5H9v8.25a3 3 0 1 0 6 0v-9a4.5 4.5 0 1 0-9 0v9.75a6 6 0 0 0 12 0V6.5z"/>
                </svg>
              </button>

              <div class="grabando-vista" id="grabando-vista" aria-live="polite">
                <span class="mic-rojo" aria-hidden="true">
                  <svg viewBox="0 0 24 24" width="20" height="20">
                    <path fill="currentColor" d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z"/>
                  </svg>
                </span>
                <div class="grabando-info">
                  <span class="cronometro" id="cronometro">0:00</span>
                  <span class="pista-cancelar" id="pista-cancelar">&lsaquo; Desliza para cancelar</span>
                  <button type="button" class="descartar-audio" id="descartar-audio"
                          hidden>Descartar</button>
                </div>
              </div>

              <textarea name="texto" rows="1" maxlength="{LIMITE_WHATSAPP}"
                        placeholder="Escribe un mensaje"
                        autofocus required></textarea>
              <button type="button" class="grabar" id="btn-grabar"
                      aria-label="Mantén pulsado para grabar una nota de voz"
                      title="Mantén pulsado para grabar">
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                  <path fill="currentColor" d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z"/>
                </svg>
              </button>
              <button type="submit" class="enviar" aria-label="Enviar por WhatsApp"
                      title="Enviar por WhatsApp">
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                  <path fill="currentColor" d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2z"/>
                </svg>
              </button>
            </div>
            <span class="tenue" id="contador"></span>
          </form>"""
    else:
        estado_ventana = ('<div class="banda alerta">Pasaron más de 24 horas desde su '
                          'último mensaje. WhatsApp no permite escribir libremente: '
                          'haría falta una plantilla aprobada por Meta.</div>')
        formulario = ""

    aviso = ""
    if error:
        aviso += f'<div class="banda alerta">{html.escape(error)}</div>'
    if ok:
        aviso += f'<div class="banda ok">{html.escape(ok)}</div>'

    if atendido:
        control = f"""
          <form method="post" action="/admin/chat/{html.escape(phone)}/devolver">
            <button class="secundario" type="submit">Devolver la conversación al bot</button>
          </form>
          <p class="tenue">El bot no responde aquí. Vuelve solo si la conversación
             se queda quieta {config.plazo_takeover()} — ni tú ni el cliente.
             Mientras alguno de los dos escriba, no interrumpe.</p>"""
    else:
        control = ('<p class="tenue">El bot está respondiendo aquí. Si envías un '
                   'mensaje, se calla automáticamente.</p>')

    # Por debajo de 1200px la ficha no cabe como cuarta columna y se
    # esconde (ver la hoja). Sin esto, las etiquetas y la nota interna
    # solo se podían editar desde un computador: en el teléfono se veían
    # en la lista y en la agenda, y no había forma de añadirlas. El botón
    # la trae como panel encima del hilo — el mismo HTML y el mismo JS,
    # solo colocado de otra manera, así que no hay dos fichas que
    # mantener. Si no hay contacto no hay ficha, y entonces tampoco botón.
    if datos:
        boton_ficha = """
              <button type="button" class="ver-ficha" id="ver-ficha"
                      aria-expanded="false" aria-controls="ficha-contacto"
                      aria-label="Ver la ficha del contacto"
                      title="Etiquetas, nota interna y recorrido">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round"
                     stroke-linejoin="round" aria-hidden="true">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                  <circle cx="12" cy="7" r="4"/>
                </svg><span>Ficha</span></button>"""
        velo_ficha = '<div class="velo-ficha" data-velo-ficha></div>'
    else:
        boton_ficha = velo_ficha = ""

    # Dos paneles: el listado de conversaciones a la izquierda y el hilo
    # a la derecha. Cada uno con su propio scroll, para poder saltar de
    # una conversación a otra sin volver atrás.
    #
    # En pantallas estrechas el listado se oculta por CSS y queda solo el
    # hilo, con el enlace "Conversaciones" de la cabecera para volver.
    return _pagina(nombre, f"""
      <div class="armazon">
        {_rail(quien=quien)}
        {_columna_lista(conversaciones, quien)}

        <section class="panel-chat">
          <header class="chat-cabecera">
            <a class="volver solo-movil" href="/admin/inbox"
               aria-label="Volver a las conversaciones" title="Conversaciones">←</a>
            <span class="chat-inicial" aria-hidden="true"
                  >{html.escape(_iniciales((datos or {}).get("name") or phone))}</span>
            <div class="titulo">
              <strong>{nombre}</strong>
              <span class="tenue telefono">{html.escape(phone)}</span>
            </div>
            <div class="acciones-chat">
              {boton_ficha}
              <details class="estados">
                <summary class="chip estado {estado_actual or 'sin-estado'}"
                         aria-label="{_ETIQUETA_ESTADO_LARGA}"
                         title="{_ETIQUETA_ESTADO_LARGA}">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       stroke-width="2" stroke-linecap="round"
                       stroke-linejoin="round" aria-hidden="true">
                    <path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z"/>
                    <path d="M7 7h.01"/>
                  </svg><span>{ETIQUETA_ESTADO.get(estado_actual, 'Marcar estado')}</span></summary>
                <div class="menu-estados">
                  {opciones_estado}
                </div>
              </details>
              <button type="button" id="reiniciar-chat"
                      aria-label="Reiniciar la conversación"
                      title="El próximo mensaje se atiende como si escribiera por primera vez">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round"
                     stroke-linejoin="round" aria-hidden="true">
                  <path d="M3 12a9 9 0 1 0 2.6-6.4"/><path d="M3 4v5h5"/>
                </svg><span>Reiniciar</span></button>
              {"" if not es_dueno else """<button type="button" class="peligro" id="borrar-chat"
                      aria-label="Eliminar chat" title="Eliminar chat">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round"
                     stroke-linejoin="round" aria-hidden="true">
                  <path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/>
                  <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/>
                  <path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>
                </svg><span>Eliminar</span></button>"""}
            </div>
            {contexto}
          </header>

          <div class="chat" id="chat">
            {aviso}
            {estado_ventana}
            {''.join(burbujas)}
          </div>

          <div class="zona-envio">
            <button type="button" class="bajar-al-final" id="bajar-al-final"
                    aria-label="Ir al último mensaje" title="Ir al último mensaje"
                    hidden>
              <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                <path fill="currentColor" d="M12 16.5 5.5 10l1.4-1.4 5.1 5.1 5.1-5.1L18.5 10z"/>
              </svg>
            </button>
            {formulario}
            {control}
          </div>
        </section>

        {velo_ficha}
        {_ficha_contacto(phone, datos, mensajes, es_dueno)}
      </div>""",
        guiones=("panel-base.js", "panel-chat.js", "panel-ficha.js",
                 "panel-listado.js", "panel-vivo.js"),
        pantalla_completa=True,
        # `hay-hilo` es lo que distingue esta pantalla de la bandeja, que
        # usa el MISMO armazon. En el telefono no caben las cuatro
        # columnas y hay que elegir: sin conversacion abierta manda la
        # lista, con una abierta manda el hilo. Sin esta clase, la
        # bandeja en un telefono ensenaba el cartel de "elige una
        # conversacion" y ninguna forma de elegirla.
        clase_body="hay-hilo",
        # El JS arranca desde este id y solo pide lo posterior.
        atributos_body=f' data-ultimo-id="{mensajes[-1]["id"] if mensajes else 0}"')


# ── Plantilla HTML ───────────────────────────────────────────────────

def _color_seguro(color: str) -> str:
    """
    El color de marca, y solo si ES un color.

    Va dentro de un `<style>` y lo escribe una persona en un formulario.
    Cualquier cosa que no sea un hexadecimal —`red; } </style><script>…`—
    se convertía en marcado de la página. Uno válido se deja tal cual se
    escribió; lo demás pasa por `rgb_de`, que cae en el color de casa.
    """
    color = (color or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", color):
        return color
    return "#{:02x}{:02x}{:02x}".format(*config.rgb_de(color))


def _pagina(titulo: str, cuerpo: str, guiones: tuple = (),
            pantalla_completa: bool = False, atributos_body: str = "",
            clase_body: str = "") -> str:
    """
    Envuelve el contenido en una página completa.

    El CSS y el JS son archivos servidos por este mismo servidor
    (`app/web/activos.py`): **nada de CDN**, así el panel funciona igual
    detrás de cualquier proxy y no filtra visitas a terceros. Lo que sí
    viaja en la página es lo que cambia con cada negocio: su color de
    marca y el objeto `PANEL`. Y se ve bien en el celular, que es desde
    donde se va a responder la mayoría de las veces.

    Ya no existe la recarga del navegador (`<meta refresh>`): todas las
    pantallas se actualizan solas por el canal en vivo, sin pisar lo que
    estés escribiendo.

    El registro del service worker (`pwa-registro.js`) va SIEMPRE, también
    en el login: es ahí donde alguien abre el panel por primera vez en el
    celular, y es cuando tiene que aparecerle la opción de instalar.
    """
    # Lo que el guion necesita de Python. Va inline y ANTES que los
    # archivos —un <script> sin `defer` se ejecuta al encontrarlo, y los
    # que llevan `defer` esperan a que la página esté leída—, así que
    # cuando `panel-base.js` arranca, `PANEL` ya existe.
    #
    # Aquí solo entra lo que cambia con el negocio o con la versión. Todo
    # lo demás vive en los archivos, que el navegador ya tiene guardados.
    # `<` escapado, como en el listado embebido: `origenPorDefecto` lo
    # escribe el negocio, y un "</script>" ahí cerraría el bloque.
    ajustes = json.dumps({
        "etiquetasEstado": ETIQUETA_ESTADO,
        "etiquetasAutor": ETIQUETA_AUTOR,
        "limiteWhatsapp": LIMITE_WHATSAPP,
        "origenPorDefecto": config.ORIGEN_POR_DEFECTO,
        "segundosPlanB": SEGUNDOS_PLAN_B,
    }, ensure_ascii=False).replace("<", "\\u003c")

    archivos = list(guiones) + ["panel-tema.js", "pwa-registro.js"]
    bloque_script = (f"<script>const PANEL = {ajustes};</script>\n"
                     + "\n".join(activos.guion(a) for a in archivos))

    clases = [c for c in (("completa" if pantalla_completa else ""),
                          clase_body) if c]
    clase_body = f' class="{" ".join(clases)}"' if clases else ""

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titulo)} · {html.escape(config.BUSINESS_NAME)}</title>
{pwa.cabecera_html()}
<script>
  /* El tema, ANTES de pintar nada. Con `defer` la pagina aparecería un
     instante en claro antes de volverse oscura, y ese destello blanco a
     oscuras molesta de verdad. Son seis lineas: caben aqui. */
  (function () {{
    var t;
    try {{ t = localStorage.getItem('n2t-tema'); }} catch (e) {{}}
    if (!t) t = matchMedia('(prefers-color-scheme: dark)').matches
                 ? 'oscuro' : 'claro';
    document.documentElement.classList.add('tema-' + t);
  }})();
</script>
{activos.hoja("fuentes.css")}
{activos.hoja("panel.css")}
<style>
  /* Lo unico del CLIENTE en toda la interfaz: el color de su cuadrito.
     La plataforma es Nitro tambien dentro del panel de un negocio, asi
     que su color ya no tiñe la herramienta — solo lo que es suyo. */
  :root {{ --marca-cliente: {_color_seguro(config.MARCA_COLOR)}; }}
</style>
</head>
<body{clase_body}{atributos_body}>{cuerpo}{bloque_script}</body>
</html>"""
