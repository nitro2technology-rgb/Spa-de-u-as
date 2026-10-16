"""
SUPER-ADMIN — LA CONSOLA DEL NEGOCIO
=====================================
No es el panel de un cliente: es la herramienta con la que se opera la
plataforma. Tres cosas, que son las tres que hacen falta para vender esto:

    dar de alta      un negocio nuevo, con su clave de panel, en un paso
    pausar           a quien no paga, sin borrarle nada
    ver el consumo   de IA por cliente, que es el único costo que escala

    ⚠️  ESTO CORRE SIN INQUILINO FIJADO, Y ES A PROPÓSITO.

`/superadmin` está exento del middleware que resuelve el negocio por el
`Host` (ver `app/main.py`). Tiene que ser así: esta consola mira a TODOS
los clientes, y con un inquilino puesto el filtro automático de consultas
(`database._filtrar_por_inquilino`) recortaría cada listado a un solo
negocio — enseñando ceros para los demás y sin dar ningún error.

Cuando hay que leer o escribir algo de un cliente concreto se envuelve
explícitamente en `tenencia.usar(id)`.

QUIÉN ENTRA
-----------
`SUPERADMIN_KEY`, y una cookie aparte de la de los clientes
(`app/core/acceso.py`). Mientras esa variable esté vacía, todo esto
responde 503 y no existe: una consola de administración sin clave,
colgada de internet, es peor que no tenerla.

POR QUÉ ES HTML A MANO
----------------------
Igual que el panel: sin plantillas, sin build, sin dependencias nuevas.
Son cuatro pantallas que se usan desde el celular y que tienen que
funcionar el día que haga falta pausar a alguien un domingo.
"""

import copy
import html
import json
import re
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import config
from app.core import acceso, consumo, database, freno, secretos, tenencia
from app.core import planes
from app.core.config_cliente import (ConfiguracionCliente, cupo_de_destinos,
                                     leer_negocio_toml)
from app.web import activos
from app.web import contenido
from app.web import mapa
from app.web import pwa

router = APIRouter(prefix="/superadmin", tags=["superadmin"])

COOKIE = "super_nitro"

# Un slug es un subdominio: panaderia.tudominio.com. Lo que no sea esto no
# puede ser un cliente, porque su panel no tendría dónde vivir.
SLUG_VALIDO = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])$")

# Reservados: no son negocios y colisionarían con el propio despliegue.
SLUGS_PROHIBIDOS = {"www", "admin", "api", "superadmin", "app", "mail",
                    "webhook", "static", "assets"}


def _caja_avisos(client_id: int, datos: dict) -> str:
    """
    Todo lo de "a quién le llega un lead", en UNA pestaña.

    Estuvo repartido en dos —el cupo en el bloque de IA, los números al
    final del editor de contenido— y el dueño no los encontró. Ese es el
    síntoma que lo justifica: **si hay que explicar dónde está, está mal
    puesto.**

    Y estaba mal por una razón de fondo, no solo de sitio: los números de
    aviso no son CONTENIDO. El editor de contenido es lo que el bot dice —
    textos, menú, precios—; a quién se le avisa es configuración del
    negocio, y vive al lado del número del dueño, que es exactamente lo
    mismo con otro nombre.

    Es larga, así que lleva barra fija abajo: se recorre entera antes de
    guardar, y perder los cambios por no encontrar el botón sería absurdo.
    """
    from app.web import contenido

    negocio = datos.get("negocio_config") or {}
    cupo = _cupo_avisos(client_id)
    destinos = ((negocio.get("avisos") or {}).get("destinos") or [])
    usadas = sum(1 for d in destinos[:cupo]
                 if (d.get("correo") or "").strip()
                 or (d.get("numero") or "").strip())

    ancho = int(round(100 * min(usadas, cupo) / max(cupo, 1)))
    medidor = f"""
        <div class="medidor"><i style="width:{ancho}%"></i></div>
        <p class="medidor-texto">Usando {usadas} de {cupo} áreas</p>"""

    return f"""
      <form method="post" action="/superadmin/clientes/{client_id}"
            data-cuenta-cambios="avisos">
        <input type="hidden" name="_bloque" value="avisos">

        <div class="caja">
          <h2>A quién le llega un lead</h2>
          <p class="tenue">Cuando alguien agenda, pregunta o pide un asesor,
             el negocio tiene que enterarse. Aquí se dice quién.
             <strong>Un aviso que no llega no da ninguna señal</strong>: el
             cliente recibe su respuesta con normalidad y el negocio se ve
             igual que en un día flojo.</p>

          <div class="rejilla">
            <div>
              <label for="owner">Número del dueño</label>
              <input id="owner" name="owner_phone_number" class="mono"
                     value="{html.escape(str(datos.get("owner_phone_number") or ""))}"
                     placeholder="573001234567">
              <p class="tenue">Formato internacional, sin "+" ni espacios.
                 <strong>Es la red de seguridad</strong>: si abajo no hay
                 áreas, todo llega aquí.</p>
            </div>
            <div>
              <label for="areas">Áreas incluidas en su plan</label>
              <input id="areas" name="max_destinos_avisos" type="number"
                     min="1" max="20" class="cifra"
                     value="{html.escape(str(datos.get("max_destinos_avisos") or ""))}"
                     placeholder="{_cupo_por_plan(datos)} (lo que da su plan)">
              <p class="tenue">Vacío = lo que da su plan:
                 <strong>{_resumen_cupos()}</strong>. Escribe un número solo para un caso
                 pactado — entonces deja de seguir al plan.</p>
              {medidor}
            </div>
          </div>
        </div>

        <div class="caja">
          <h2>Las áreas</h2>
          {contenido.bloque_destinos(negocio, cupo, _rechazos_de_meta(client_id))}
        </div>

        <div class="guardar-fijo">
          <span class="contador" data-contador-de="avisos">Sin cambios</span>
          <button type="submit" class="suave"
                  formaction="/superadmin/clientes/{client_id}/probar-avisos"
                  formnovalidate>Mandar un aviso de prueba</button>
          <button type="submit">Guardar avisos</button>
          <p class="aviso"><strong>El aviso de prueba es una acción
             inmediata</strong>: le escribe a cada área con lo que hay
             escrito en pantalla, ahora mismo, sin guardar primero. Si
             alguno no llega, te dice por qué.</p>
        </div>
      </form>"""


def _rechazos_de_meta(client_id: int) -> dict:
    """
    `{numero: motivo}` con lo último que Meta no pudo entregar.

    Hoy se guarda un solo fallo por cliente (`notificaciones`), así que
    el diccionario trae como mucho una entrada. Se devuelve así y no como
    un par suelto porque quien lo pinta busca POR NÚMERO: lo que hace
    falta es señalar el área concreta, no repetir el error en una banda
    donde no se sabe a quién le pasó.
    """
    from app.bot import notificaciones

    try:
        with tenencia.usar(client_id):
            ultimo = notificaciones.ultimo_no_entregado()
    except Exception:
        return {}

    if not ultimo or not ultimo.get("numero"):
        return {}
    return {ultimo["numero"]: ultimo["motivo"]}


def _cupo_por_plan(datos: dict) -> int:
    """
    Lo que le daría su plan, ignorando el ajuste suelto.

    Es lo que se enseña de marcador en el campo vacío: dice qué va a pasar
    si no se escribe nada, que es justo la pregunta de quien lo mira.
    """
    return planes.de(datos).areas


def _resumen_cupos() -> str:
    """"Básico 0, Pro 3, Premium 5": lo que da cada plan, sin repetirlo a mano."""
    return ", ".join(f"{p.nombre} {p.areas}" for p in
                     (planes.PLANES[c] for c in planes.ORDEN))


def _selector_plan(actual: str, nombre: str = "plan") -> str:
    """
    El plan comercial, como desplegable: Básico, Pro o Premium.

    Era una etiqueta libre ("mensual") más un "¿compró la IA?" aparte. Ahora
    el plan decide las dos cosas —cuántas áreas caben y si trae IA—, y una
    etiqueta libre no puede decidir nada.
    """
    opciones = "".join(
        f'<option value="{p.codigo}"{" selected" if p.codigo == actual else ""}>'
        f'{p.nombre} — {"con IA" if p.ia else "sin IA"}, '
        f'{p.areas} área{"" if p.areas == 1 else "s"}</option>'
        for p in (planes.PLANES[c] for c in planes.ORDEN))
    return f'<select id="{nombre}" name="{nombre}">{opciones}</select>'


def _cupo_avisos(client_id: int) -> int:
    """
    Cuántas áreas de aviso le tocan a este cliente.

    Se lee de su fila cada vez, sin caché: es un número que se cambia
    justo antes de venir a esta pantalla —se le sube el plan y se entra a
    repartir— y verlo desfasado sería exactamente el momento equivocado.
    """
    session = database.get_session()
    try:
        cliente = session.query(database.Client).filter_by(id=client_id).first()
        if cliente is None:
            return 3
        return cupo_de_destinos({
            "max_destinos_avisos": cliente.max_destinos_avisos,
            "ia_contratada": cliente.ia_contratada,
            "plan": cliente.plan,
        })
    finally:
        session.close()


def _solo_digitos(texto) -> str:
    """Un número de teléfono como lo quiere Meta: sin "+", espacios ni guiones."""
    return "".join(c for c in str(texto or "") if c.isdigit())


def _token_de_webhook() -> str:
    """
    Un trozo aleatorio para la URL de webhook de un cliente, y para su
    verify token.

    `token_urlsafe(24)` son 192 bits: no se adivina probando. Importa
    porque esta cadena es lo primero que separa a un cliente de otro en el
    webhook — quien no la tenga no llega ni a la comprobación de firma.

    NO se deriva del slug ni del id. Un `webhook_token` predecible sería
    una URL que cualquiera puede construir sabiendo el nombre del negocio,
    y entonces no aportaría nada sobre no tenerlo.
    """
    import secrets as _aleatorio
    return _aleatorio.token_urlsafe(24)

# El freno a quien prueba claves a lo bruto, el mismo que el del panel de
# los clientes (`app/core/freno.py`). Aquí importa MÁS que allí: detrás de
# esta clave están las conversaciones de todos los negocios, el alta, la
# pausa y las credenciales cifradas.
_FRENO = freno.Freno("superadmin")


# ── Página ───────────────────────────────────────────────────────────
# Neutra a propósito: esto NO lleva la marca de ningún cliente. Que se
# parezca al panel de un negocio sería la mejor forma de equivocarse de
# pestaña y pausar al cliente que sí paga.

# El CSS y el JavaScript viven en `app/web/estaticos/`, no aquí.
#
# Salieron por lo mismo que salieron los del panel del cliente: dentro de
# una cadena de Python no hay resaltado ni autocompletado, y un error de
# CSS no da un error de CSS — da un error de Python al arrancar el
# servidor. Ahora se editan como lo que son.
#
# `activos.url()` les pone el hash del contenido en la dirección, así que
# el navegador los cachea para siempre y aun así ve los cambios en cuanto
# se despliegan.


# El logo se sube como archivo y se convierte a base64 AQUÍ, en el
# navegador. Antes había que pegar la cadena a mano, o sea convertir la
# imagen con una herramienta de fuera: nadie tiene eso a mano el día que un
# cliente manda su logo por WhatsApp.
#
# No toca el servidor a propósito. Subir un archivo de verdad querría decir
# multipart, un límite de tamaño en el endpoint y un sitio donde dejarlo
# mientras tanto — y el destino final es igualmente una cadena en una
# columna. Con FileReader el formulario sigue siendo el mismo.


# ══════════════════════════════════════════════════════════════════════
#  EL ARMAZON DE LA PANTALLA
# ══════════════════════════════════════════════════════════════════════
#
# Barra lateral oscura de operacion + contenido. Lo que distingue esta
# consola del panel del cliente NO es otra paleta —las dos son Nitro, el
# mismo morado— es la ESTRUCTURA: la barra, la densidad de tabla y el
# mono en cada identificador.
#
# La barra la pinta `_nav_cuerpo()` una sola vez y se coloca en dos
# sitios: el <aside> de escritorio y el <details> del celular. Duplicar
# el marcado es feo; duplicar la LISTA de enlaces seria peor, porque el
# dia que se anada uno se anadiria en un solo sitio y en el telefono no
# existiria.

# El nombre del tema en `localStorage`, y el guion de dos lineas que lo
# aplica ANTES del CSS. Si esto se hiciera desde el archivo con `defer`,
# la pagina apareceria un instante en claro antes de volverse oscura —
# ese fogonazo blanco a oscuras molesta de verdad.
# Con try: en una ventana privada o con el almacenamiento bloqueado,
# `localStorage` LEVANTA en vez de devolver null, y sin el try la página
# se quedaba sin su tema.
_SIN_DESTELLO = ("<script>try{var t=localStorage.getItem('superadmin:tema');"
                 "if(t&&t!=='auto')document.documentElement.dataset.tema=t;"
                 "}catch(e){}</script>")


def _tema_grupo() -> str:
    """`Sistema · Claro · Oscuro`. Tres estados, no dos: ver el guion."""
    botones = "".join(
        f'<button type="button" class="tema-boton" data-tema-valor="{valor}"'
        f' aria-pressed="false">{etiqueta}</button>'
        for valor, etiqueta in (("auto", "Sistema"), ("claro", "Claro"),
                                ("oscuro", "Oscuro")))
    return f'<div class="tema-grupo" role="group" aria-label="Tema">{botones}</div>'


def _logo(px: int = 24) -> str:
    """
    El logo de Nitro, servido desde ESTE dominio.

    Como el CSS y las fuentes: el panel es una herramienta de negocios
    ajenos y quien lo abre no tiene por que salir de aqui. Con la version
    en la direccion, el navegador lo cachea para siempre y aun asi ve el
    cambio el dia que se cambie.
    """
    return (f'<img class="n-marca-logo" src="{activos.url("nitro-logo.svg")}"'
            f' alt="Nitro" width="{px}" height="{px}">')


def _n_marca(px: int = 24) -> str:
    return f"""<a class="n-marca" href="/superadmin">
        {_logo(px)}
        <span class="n-marca-texto">Nitro <span>superadmin</span></span>
      </a>"""


def _requieren_atencion(uso: list | None = None) -> list[dict]:
    """
    Los clientes que hay que mirar HOY, para la barra lateral.

    Es el corazon del rediseno, y responde a un fallo que no da ninguna
    senal: un cliente con el token roto o sin cupo de IA esta tan mudo
    como uno pausado, y en la ficha de otro negocio no hay forma de
    enterarse. Aqui aparece en TODAS las pantallas.

    Dos consultas en total —`uso_de_todos` ya cruza con `clients`—, asi
    que se puede permitir el lujo de correr en cada carga. Con datos
    cacheados diria "todo en orden" justo despues de que algo se rompa,
    que es cuando esto tiene que servir.

    Corre SIN inquilino, como todo `/superadmin` (ver la cabecera del
    modulo).
    """
    avisos = []
    try:
        credenciales = _estado_credenciales()
        for c in (uso if uso is not None else consumo.uso_de_todos()):
            # UNA tarjeta por cliente, aunque tenga dos problemas. Con una
            # por motivo, el mismo negocio salia dos veces seguidas y la
            # lista parecia mas larga de lo que era: lo que hay que contar
            # de un vistazo es a cuantos hay que ir a ver.
            motivos, grave = [], False
            estado = credenciales.get(c["client_id"], "")
            if estado == "mal":
                motivos.append("credenciales rotas")
                grave = True
            elif estado == "aviso":
                motivos.append("revisar credenciales")
            if c["limite"] and c["mensajes"] >= c["limite"]:
                motivos.append("sin cupo de IA este mes")
            if motivos:
                avisos.append({"id": c["client_id"], "nombre": c["nombre"],
                               "motivo": " · ".join(motivos), "grave": grave})
    except Exception:
        # La barra lateral no puede tumbar una pantalla. Si la base no
        # contesta, lo que hace falta es poder entrar a mirar por que.
        return []
    # Lo roto primero: es lo que deja a un negocio mudo ahora mismo.
    avisos.sort(key=lambda a: not a["grave"])
    return avisos


def _nav_cuerpo(activo: str, cuantos_clientes: int | None = None) -> str:
    """Los enlaces de la barra, el bloque de atencion y el pie."""
    # Una sola consulta para las dos cosas: la cuenta de clientes y quién
    # requiere atención. Se hacían dos iguales en cada pantalla.
    try:
        uso = consumo.uso_de_todos()
    except Exception:
        uso = None
    if cuantos_clientes is None:
        cuantos_clientes = len(uso or [])

    def item(clave, href, texto, cuenta=""):
        marca = " activo" if activo == clave else ""
        cuenta = f'<span class="cuenta">{cuenta}</span>' if cuenta != "" else ""
        return (f'<a class="nav-item{marca}" href="{href}">{texto}{cuenta}</a>')

    # Por TAREAS, no por cómo está guardado (24-sep-2026): lo de hoy, los
    # negocios, el dinero y dar de alta. La cuenta de Cobros es lo que pide
    # una acción —vencidos, pausados y lo que vence esta semana—; un número
    # que no pide nada se deja de mirar.
    try:
        por_cobrar = sum(1 for _f, c in _cuentas_de_cobro()
                         if c.estado in _ESTADOS_QUE_PIDEN_ALGO)
    except Exception:
        por_cobrar = 0
    enlaces = (item("hoy", "/superadmin", "Hoy")
               + item("clientes", "/superadmin/clientes", "Clientes",
                      cuantos_clientes)
               + item("cobros", "/superadmin/cobros", "Cobros",
                      por_cobrar or "")
               + item("nuevo", "/superadmin/nuevo", "Dar de alta")
               # El panel de barberías tiene su propia consola.
               + item("barberias", "/superadmin/barberias", "Barberías"))

    # Si no hay ninguno, el bloque NO se pinta. Un hueco fijo que dice
    # "todo bien" se deja de mirar a la semana, y entonces tampoco se ve
    # el dia que diga otra cosa.
    pendientes = _requieren_atencion(uso) if uso is not None else []
    atencion = ""
    if pendientes:
        tarjetas = "".join(
            f'<a class="alerta-cliente{"" if p["grave"] else " avisa"}"'
            f' href="/superadmin/clientes/{p["id"]}">'
            f'<strong>{html.escape(p["nombre"])}</strong>'
            f'<span>{html.escape(p["motivo"])}</span></a>'
            for p in pendientes[:6])
        mas = ("" if len(pendientes) <= 6 else
               f'<p class="rotulo">y {len(pendientes) - 6} mas</p>')
        atencion = f"""
      <div class="atencion">
        <p class="rotulo">Requiere atención</p>
        {tarjetas}{mas}
      </div>"""

    return f"""
      <nav class="nav">{enlaces}</nav>
      {atencion}
      <div class="barra-pie">
        <a class="barra-enlace" href="/admin">Panel de atención ↗</a>
        <a class="barra-enlace" href="/superadmin/logout">Salir</a>
        {_tema_grupo()}
      </div>"""


def _barra_lateral(activo: str) -> tuple[str, str]:
    """
    (la barra de escritorio, la cabecera del celular).

    Las dos con el MISMO cuerpo: se pinta una vez y se coloca dos veces.
    """
    cuerpo = _nav_cuerpo(activo)
    aside = f'<aside class="barra">{_n_marca()}{cuerpo}</aside>'
    movil = f"""
    <header class="cabecera-movil">
      <details class="menu-movil">
        <summary>
          {_logo(22)}
          <span class="n-marca-texto">Nitro <span>superadmin</span></span>
          <span class="abrir">Menú</span>
        </summary>
        <div class="menu-cuerpo">{cuerpo}</div>
      </details>
    </header>"""
    return aside, movil


def _documento(titulo: str, cuerpo: str, clase_body: str = "",
               guiones: tuple = ()) -> str:
    """El <html> completo. Todo lo que se sirve pasa por aqui."""
    extra = "".join(f'<script src="{activos.url(g)}" defer></script>'
                    for g in guiones)
    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(titulo)} · Nitro superadmin</title>
<link rel="icon" href="{activos.url("nitro-logo.svg")}" type="image/svg+xml">
{_SIN_DESTELLO}
<link rel="stylesheet" href="{activos.url('fuentes.css')}">
<link rel="stylesheet" href="{activos.url('superadmin.css')}">
</head><body{f' class="{clase_body}"' if clase_body else ""}>{cuerpo}
<script src="{activos.url('superadmin-tema.js')}" defer></script>
<script src="{activos.url('superadmin-campos.js')}" defer></script>{extra}
</body></html>"""


def _cabecera(titulo: str, resumen: str = "", chips: str = "",
              acciones: str = "") -> str:
    resumen = f'<p class="resumen">{resumen}</p>' if resumen else ""
    return f"""
    <header class="cabecera">
      <div class="cabecera-izq">
        <h1>{titulo}{chips}</h1>
        {resumen}
      </div>
      <div class="cabecera-acciones">{acciones}</div>
    </header>"""


# ══════════════════════════════════════════════════════════════════════
#  LA COLUMNA DE AYUDA
# ══════════════════════════════════════════════════════════════════════
#
# A la derecha sobraba pantalla y a los campos les faltaba explicación.
# Esta consola pide "clave pública VAPID" y "phone_number_id" sin decir en
# ninguna parte qué son; quien la usa no siempre es quien la programó, y
# un campo que no se entiende se rellena mal o se deja vacío por miedo.
#
# ── CÓMO SE ESCRIBE ESTO ──────────────────────────────────────────────
# En PUNTOS, no en párrafos. Cada punto es un titular corto en negrita y
# una frase debajo. Nadie lee un muro de texto al lado de un formulario:
# se ojea, se busca la palabra que uno no entiende, y se sigue.
#
# Las reglas al escribir un punto nuevo:
#
#   · Menos de veinte palabras. Si no cabe, es que son dos puntos.
#   · Nada de jerga. Esto lo lee alguien que no sabe qué es un endpoint.
#   · Di **qué pasa si lo dejas vacío**, que es la pregunta real de quien
#     mira un campo que no conoce.
#
# `ojo` es lo único que puede romper algo sin dar error. Va aparte y en
# ámbar porque si va mezclado con lo demás, se lee como lo demás.

AYUDA = {

    "hoy": {
        "titulo": "Lo de hoy",
        "entradilla": "Lo que pide tu atención, primero.",
        "puntos": [
            ("Cobros que piden algo",
             "Los que vencen esta semana, los vencidos y los pausados. "
             "Registra el pago desde la misma fila."),
            ("Negocios con algo roto",
             "Credenciales de Meta que fallan o sin cupo de IA."),
            ("Los números",
             "Cuánto deberías cobrar al mes y cuánto entró."),
        ],
        "ojo": "Un vencido se pausa solo al tercer día. El pago lo reactiva.",
    },

    "cobros": {
        "titulo": "Lo que te pagan",
        "entradilla": "Todos los negocios, del más urgente al que menos.",
        "puntos": [
            ("Registrar pago",
             "Corre la fecha un mes. Si estaba pausado por no pagar, lo "
             "reactiva."),
            ("Sin cobro",
             "No tiene fecha: no se le avisa ni se le pausa nunca."),
            ("El precio",
             "El de su plan, salvo que le pongas uno pactado en su ficha."),
        ],
        "ojo": "Una pausa que pusiste tú a mano no la deshace un pago.",
    },

    "clientes": {
        "titulo": "La lista de todos los negocios",
        "entradilla": "De un vistazo: quién funciona y quién no.",
        "puntos": [
            ("La barra de color",
             "Verde, su WhatsApp va. Rojo, está roto y no le entra ni un "
             "mensaje."),
            ("Pausar",
             "Apaga el bot de quien no paga. No le borra nada."),
            ("Reanudar",
             "Lo devuelve tal cual estaba, con todo su historial."),
        ],
        "ojo": "Borrar un negocio no existe, y es a propósito.",
    },

    "nuevo": {
        "titulo": "Dar de alta un negocio",
        "entradilla": "Se crea todo de una vez: el negocio, su clave de "
                      "panel y su contenido.",
        "puntos": [
            ("Antes de empezar",
             "Necesitas 4 datos que te da el cliente desde su cuenta de "
             "Meta. Pídeselos ya."),
            ("Al terminar",
             "Te damos 2 datos nuestros. Él los pega en Meta, o no le entra "
             "nada."),
            ("Y por último",
             "Ármale la conversación en el Mapa."),
        ],
        "ojo": "Nace en blanco: sin menú y sin textos. Todo se lo pones tú.",
    },

    "resumen": {
        "titulo": "Cómo le va a este negocio",
        "entradilla": "Lo que gastó de IA, cuánta gente le escribe y su plan.",
        "puntos": [
            ("Los dos datos de Meta",
             "Se copian con el botón. No se escriben a mano."),
            ("¿Y por qué no se editan?",
             "Si cambian, su bot deja de recibir mensajes y no avisa nadie."),
        ],
        "ojo": "¿Banda roja arriba? Un aviso no le llegó a nadie. Eso es un "
               "cliente que preguntó y nadie atendió.",
    },

    "avisos": {
        "titulo": "¿Quién se entera de un lead?",
        "entradilla": "Alguien pide una cita o un asesor. Aquí decides a "
                      "quién le suena.",
        "puntos": [
            ("El número del dueño",
             "La red de seguridad: mientras no haya áreas, todo le llega a "
             "él."),
            ("Un área es un correo",
             "Ventas, Soporte, Contratos. Le marcas de qué se encarga y solo "
             "le llega eso."),
            ("Con el correo basta",
             "El WhatsApp del área es opcional y falla más: solo deja "
             "escribirle a quien te escribió en 24 h."),
            ("Un área sin casillas marcadas",
             "Recoge todo lo que las demás no pidan. Conviene tener una."),
        ],
        "ojo": "Las casillas salen del Mapa de conversación. Si no aparece "
               "ninguna, es que este negocio todavía no tiene menú.",
    },

    "whatsapp": {
        "titulo": "Las llaves de su WhatsApp",
        "entradilla": "Se las da el cliente, desde su propia cuenta de Meta.",
        "puntos": [
            ("¿Los campos salen vacíos?",
             "No se perdió nada. Lo que está guardado no se enseña nunca."),
            ("Vacío quiere decir «déjalo»",
             "Escribe algo solo si quieres cambiarlo."),
            ("¿Compró el paquete de IA?",
             "En No, el bot responde solo con su menú y el dueño ni ve el "
             "interruptor."),
        ],
        "ojo": "Si Meta rechaza sus llaves, el bot se queda mudo y por fuera "
               "se ve igual que un día flojo. Para eso está Probar "
               "credenciales.",
    },

    "usuarios": {
        "titulo": "Quién entra a su panel",
        "entradilla": "Los usuarios y las claves del equipo del negocio.",
        "puntos": [
            ("Se entra con usuario y clave",
             "El usuario es único en toda la plataforma. La clave no se ve "
             "nunca: si se olvida, se pone una nueva aquí."),
            ("Aquí no hay Guardar",
             "Todo pasa al momento, en cuanto pulsas."),
            ("Quitar acceso, y después borrar",
             "Al último que puede entrar no se le quita: dejaría al negocio "
             "fuera de su propio panel."),
        ],
        "ojo": "¿Quieres cortarle todo a quien no paga? Pausa el negocio: "
               "eso además le apaga el bot.",
    },

    "integraciones": {
        "titulo": "Si no sabes qué es, déjalo vacío",
        "entradilla": "El bot funciona igual sin nada de esta pantalla.",
        "puntos": [
            ("Datos públicos",
             "El WhatsApp, el correo y la web que el bot le da a SUS "
             "clientes."),
            ("Google",
             "Solo si quiere que el bot le agende las citas y le apunte los "
             "clientes en una hoja."),
            ("VAPID",
             "Dos claves para que al dueño le suene el celular. Se generan "
             "con <code>python scripts/push_setup.py</code>."),
            ("Marca",
             "Su color y su logo, para que reconozca su panel."),
        ],
    },

    "contenido": {
        "titulo": "Todo lo que el bot dice",
        "entradilla": "Sus textos, sus precios, sus enlaces y su horario.",
        "puntos": [
            ("El índice de la izquierda",
             "Para saltar de un bloque a otro. La página es larga a "
             "propósito."),
            ("Los huecos entre llaves",
             "<code>{name}</code> y <code>{negocio}</code> se rellenan "
             "solos. Déjalos tal cual."),
            ("Se revisa todo al guardar",
             "Si algo no cuadra te lo dice y no cambia nada."),
        ],
        "ojo": "Descarga una copia antes de tocar mucho. Es el único "
               "deshacer que hay.",
    },

    "mapa": {
        "titulo": "El recorrido del cliente",
        "entradilla": "El saludo, el menú y qué pasa al tocar cada opción.",
        "puntos": [
            ("El teléfono de la derecha",
             "Es lo que va a ver el cliente. Cambia algo y se pinta ahí "
             "mismo."),
            ("Nace en blanco",
             "Ni una opción. Todo lo que tenga se lo pones aquí."),
        ],
        "ojo": "Lo que armes aquí es lo que luego puedes repartir en Avisos "
               "y áreas.",
    },
}


def _ayuda(clave: str) -> str:
    """
    La columna de la derecha, o cadena vacía si esa pantalla no tiene.

    Es un `<details>` y sale ABIERTO del servidor. En escritorio el
    `<summary>` se esconde y queda como una columna más; en pantalla
    estrecha se pliega en un botón al principio de la sección, y quien lo
    pliega es el guion (ver superadmin-tema.js). Sin JavaScript se queda
    abierta: mal colocada, pero nunca escondida.
    """
    if clave not in AYUDA:
        return ""

    a = AYUDA[clave]

    puntos = "".join(f"""
          <li>
            <p class="punto-titulo">{fuerte}</p>
            <p class="punto-texto">{texto}</p>
          </li>""" for fuerte, texto in a["puntos"])

    ojo = "" if not a.get("ojo") else f"""
          <p class="ayuda-ojo"><span aria-hidden="true">!</span>{a["ojo"]}</p>"""

    # El título va DOS veces, y no es un descuido: en el <summary> lo lee
    # quien la tiene plegada en un teléfono, y en la cabecera de dentro
    # quien la tiene abierta como columna. Cada uno se esconde donde manda
    # el otro, así el marcado no depende de JavaScript para tener título.
    return f"""
      <details class="ayuda-lateral" open>
        <summary>
          <span class="ayuda-signo" aria-hidden="true">?</span>
          <span class="ayuda-summary-texto">{a["titulo"]}</span>
        </summary>
        <div class="ayuda-cuerpo">
          <div class="ayuda-cabecera">
            <span class="rotulo">Qué es esta pantalla</span>
            <p class="ayuda-titulo">{a["titulo"]}</p>
            <p class="ayuda-entradilla">{a["entradilla"]}</p>
          </div>
          <ul class="ayuda-puntos">{puntos}</ul>
          {ojo}
        </div>
      </details>"""


def _pantalla(titulo: str, cabecera: str, cuerpo: str, activo: str = "",
              pestanas: str = "", estrecho: bool = False,
              ayuda: str = "", guiones: tuple = ()) -> str:
    """
    Una pantalla de la consola: barra lateral + cabecera + contenido, y a
    la derecha la ayuda de esa pantalla si la tiene.

    `ayuda` es la CLAVE del texto (ver AYUDA), no el texto. Así una
    pantalla nueva que se olvide de pasarla se queda sin columna en vez
    de con una columna vacía, y la lista de textos vive en un solo sitio.
    """
    aside, movil = _barra_lateral(activo)
    panel = _ayuda(ayuda)

    zona = cuerpo if not panel else f"""
        <div class="dos-zonas">
          <div class="zona-principal">{cuerpo}</div>
          {panel}
        </div>"""

    clases = "cuerpo"
    if estrecho:
        clases += " estrecho"
    if panel:
        clases += " con-ayuda"

    return _documento(titulo, f"""{movil}
    <div class="armazon">
      {aside}
      <div class="lienzo">
        {cabecera}
        {pestanas}
        <div class="{clases}">{zona}</div>
      </div>
    </div>""", guiones=guiones)


# Se conserva el nombre viejo porque lo usan las pantallas que no llevan
# barra lateral (sin clave, y la de entrada): son las dos que se ven
# ANTES de estar dentro, y una barra de navegacion ahi no navega a nada.
def _pagina(titulo: str, cuerpo: str) -> str:
    return _documento(titulo, f'<div class="cuerpo estrecho">{cuerpo}</div>')


def _sin_clave() -> HTMLResponse:
    return HTMLResponse(_pagina("Deshabilitado", """
      <div class="caja">
        <h1>Super-admin deshabilitado</h1>
        <p class="tenue">Falta <code>SUPERADMIN_KEY</code> en las variables
           de entorno. Una consola de administración sin clave, colgada de
           internet, es peor que no tenerla.</p>
        <p class="tenue">Genérala con
          <code>python -c "import secrets; print(secrets.token_urlsafe(32))"</code>.</p>
      </div>"""), status_code=503)


def _login(aviso: str = "") -> HTMLResponse:
    """
    La puerta. Fondo oscuro en los DOS temas y una sola caja.

    No es una pantalla de trabajo: sin nada que leer alrededor, el unico
    sitio donde mirar es el campo de la clave. El interruptor de tema va
    igualmente arriba a la derecha, porque lo que se elija aqui es lo que
    se va a encontrar dentro.
    """
    banda = f'<div class="banda mal">{html.escape(aviso)}</div>' if aviso else ""
    return HTMLResponse(_documento("Entrar", f"""
    <header class="entrada-cabecera">
      {_logo(26)}
      <span class="n-marca-texto">Nitro <span>superadmin</span></span>
      {_tema_grupo()}
    </header>

    <div class="entrada-centro">
      <div class="entrada-caja">
        <h1>Entrar</h1>
        <p class="tenue">La consola de la plataforma. Mira a todos los
           negocios.</p>
        {banda}
        <form method="post" action="/superadmin/login">
          <label for="clave">Clave</label>
          <input id="clave" type="password" name="clave" autofocus required
                 autocomplete="current-password">
          <button type="submit">Entrar</button>
        </form>
      </div>
    </div>

    <p class="entrada-pie">HTTPS verificado · sin usuario, sin recuperación</p>
    """, clase_body="entrada"))


def _entrada_valida(request: Request) -> bool:
    return acceso.pase_super_valido(request.cookies.get(COOKIE, ""))


def _exige_https(request: Request) -> bool:
    return request.url.hostname not in ("localhost", "127.0.0.1", "::1")


# ── Entrar y salir ───────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if not acceso.super_habilitado():
        return _sin_clave()
    if _entrada_valida(request):
        return RedirectResponse("/superadmin", status_code=303)
    return _login()


@router.post("/login")
def login(request: Request, clave: str = Form(...)):
    if not acceso.super_habilitado():
        return _sin_clave()

    # El freno va ANTES de comprobar la clave, y bloquea también a quien la
    # acierta: si el acierto pasara, quien prueba a lo bruto solo tendría
    # que seguir probando hasta dar con ella.
    if _FRENO.bloqueado(request):
        return _login(_FRENO.aviso())

    if not acceso.autenticar_super(clave):
        _FRENO.anotar_fallo(request)
        return _login("Clave incorrecta.")

    _FRENO.olvidar(request)   # entró bien: se olvidan los fallos

    respuesta = RedirectResponse("/superadmin", status_code=303)
    respuesta.set_cookie(COOKIE, acceso.crear_pase_super(), httponly=True,
                         samesite="lax", secure=_exige_https(request),
                         max_age=acceso.HORAS_SUPER * 3600)
    return respuesta


@router.get("/logout")
def logout(request: Request):
    respuesta = RedirectResponse("/superadmin/login", status_code=303)
    respuesta.delete_cookie(COOKIE, httponly=True, samesite="lax",
                            secure=_exige_https(request))
    return respuesta


# ── El listado ───────────────────────────────────────────────────────

@router.get("/clientes", response_class=HTMLResponse)
def tablero(request: Request, ok: str = "", mal: str = "", periodo: str = ""):
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    periodo = periodo or consumo.periodo_actual()
    uso = consumo.uso_de_todos(periodo)
    actividad = database.actividad_por_cliente()

    banda = ""
    if ok:
        banda = f'<div class="banda ok">{html.escape(ok)}</div>'
    elif mal:
        banda = f'<div class="banda mal">{html.escape(mal)}</div>'

    # El estado de las credenciales de cada cliente, en UNA consulta y no
    # una por fila. Con veinte clientes lo que hace falta es barrer el
    # listado y ver quién está roto, no entrar a comprobar de uno en uno.
    credenciales = _estado_credenciales()

    filas = "".join(_fila_cliente(c, actividad.get(c["client_id"], {}),
                                  credenciales.get(c["client_id"], ""))
                    for c in uso)

    meses = consumo.periodos_con_uso() or [periodo]
    if periodo not in meses:
        meses.insert(0, periodo)
    opciones = "".join(
        f'<option value="{m}"{" selected" if m == periodo else ""}>{m}</option>'
        for m in meses)

    total_mensajes = sum(c["mensajes"] for c in uso)
    activos = sum(1 for c in uso if c["active"])

    acciones = f"""
      <form method="get" action="/superadmin/clientes" class="filtro-mes">
        <select name="periodo" aria-label="Mes">{opciones}</select>
        <button class="suave" type="submit">Ver</button>
      </form>
      <a class="boton" href="/superadmin/nuevo">Dar de alta</a>"""

    cabecera = _cabecera(
        "Clientes",
        resumen=(f'{activos} de {len(uso)} activos · '
                 f'<span class="cifra">{total_mensajes:,}</span> mensajes de '
                 f'IA en <span class="cifra">{periodo}</span>'),
        acciones=acciones)

    tabla = f"""
      <div class="tabla">
        <div class="tabla-cab">
          <div>Negocio</div><div>Estado</div><div>IA {periodo}</div>
          <div>Conversación</div><div>Acciones</div>
        </div>
        {filas}
        <p class="pie-tabla">Los clientes no se borran: pausar conserva el
           historial, los contactos y el contenido.</p>
      </div>"""

    cuerpo = banda + _banda_orientadora(uso, credenciales) + (
        tabla if uso else "")

    return HTMLResponse(_pantalla("Clientes", cabecera, cuerpo,
                                  activo="clientes", ayuda="clientes"))


def _banda_orientadora(uso: list, credenciales: dict) -> str:
    """
    Qué hacer a continuación, dicho arriba de la tabla.

    No es un "estado vacío": con tres clientes, una tabla sin nada
    encima no orienta a nadie. Y con cero, la banda OCUPA el sitio de la
    tabla — una cabecera de columnas sobre la nada es peor que un texto
    que invita a empezar.
    """
    if not uso:
        return """
      <div class="orienta vacia">
        <h2>Todavía no hay ningún negocio</h2>
        <p>Dar de alta uno crea su clave de panel, su URL de webhook y su
           contenido en un solo paso. Después se le arma la conversación.</p>
        <a class="boton" href="/superadmin/nuevo">Dar de alta el primero</a>
      </div>"""

    rotos = [c for c in uso if credenciales.get(c["client_id"]) == "mal"]
    sin_cupo = [c for c in uso
                if c["limite"] and c["mensajes"] >= c["limite"]]

    if rotos:
        primero = rotos[0]
        cuantos = ("un cliente" if len(rotos) == 1
                   else f"{len(rotos)} clientes")
        detalle = (f'<strong>{html.escape(primero["nombre"])}</strong> tiene '
                   f'las credenciales rotas' if len(rotos) == 1 else
                   f'<strong>{len(rotos)} clientes</strong> tienen las '
                   f'credenciales rotas')
        return f"""
      <div class="orienta">
        <p>Todo en orden salvo {cuantos}: {detalle}. Mientras tanto no le
           entra ni un mensaje, y por fuera se ve igual que un día flojo.</p>
        <a class="boton" href="/superadmin/clientes/{primero["client_id"]}">
          Abrir {html.escape(primero["nombre"])}</a>
      </div>"""

    if sin_cupo:
        primero = sin_cupo[0]
        return f"""
      <div class="orienta">
        <p><strong>{html.escape(primero["nombre"])}</strong> se quedó sin
           cupo de IA este mes. El bot sigue vendiendo con su menú, pero
           deja de responder lo que no encaje en él.</p>
        <a class="boton" href="/superadmin/clientes/{primero["client_id"]}">
          Ver su plan</a>
      </div>"""

    if len(uso) < 5:
        return """
      <div class="orienta">
        <p>Todo en orden. Cuando entre un negocio nuevo, darlo de alta le
           deja lista la clave del panel y su URL de webhook; lo siguiente
           es armarle la conversación.</p>
        <a class="boton suave" href="/superadmin/nuevo">Dar de alta otro</a>
      </div>"""

    return ""


def _estado_credenciales() -> dict:
    """
    `{client_id: token_estado}` para todos los clientes, de una vez.

    Corre sin inquilino, como todo `/superadmin`: `clients` no lleva
    `client_id` y está fuera del filtro automático, así que esta consulta
    ve a todos — que es justo lo que tiene que hacer.
    """
    session = database.get_session()
    try:
        return {fila.id: (fila.token_estado or "")
                for fila in session.query(database.Client).all()}
    finally:
        session.close()


# El semáforo de credenciales, en palabras. El color solo no es una
# lectura accesible, y "rojo" no dice si hay que rotar un token o
# esperar: el texto sí.
_CHIPS_CREDENCIALES = {
    "ok":         ("bien",   "credenciales ok"),
    "aviso":      ("avisa",  "revisar credenciales"),
    "mal":        ("mal",    "credenciales rotas"),
    "sin_probar": ("neutro", "sin comprobar"),
}


def _chip_credenciales(estado: str) -> str:
    clase, texto = _CHIPS_CREDENCIALES.get(estado or "",
                                           ("neutro", "sin comprobar"))
    return f'<span class="chip {clase}"><i class="punto"></i>{texto}</span>'


def _fila_cliente(c: dict, act: dict, credenciales: str = "") -> str:
    """
    Una fila del listado.

    El semáforo de las credenciales va DOS veces: como barra de 3px en el
    borde izquierdo —que es lo que deja barrer veinte filas de un
    vistazo— y como chip con texto. Un cliente activo con el token roto
    está tan mudo como uno pausado, y sin esto se ven igual.
    """
    cid = c["client_id"]
    sem = credenciales if credenciales in _CHIPS_CREDENCIALES else ""

    estado = ('<span class="chip morado">activo</span>' if c["active"]
              else '<span class="chip neutro">pausado</span>')

    plan = f'<span class="tenue">{html.escape(planes.de(c).nombre)}</span>'

    if c["limite"]:
        agotado = c["mensajes"] >= c["limite"]
        clase = ' class="sin-cupo cifra"' if agotado else ' class="cifra"'
        cupo = f'<span{clase}>{c["mensajes"]:,} / {c["limite"]:,}</span>'
        if agotado:
            cupo += '<br><span class="tenue">sin cupo este mes</span>'
    else:
        cupo = (f'<span class="cifra">{c["mensajes"]:,}</span>'
                f'<br><span class="tenue">sin tope</span>')

    tokens = c["tokens_in"] + c["tokens_out"]
    if not c["limite"] or c["mensajes"] < c["limite"]:
        cupo += f'<br><span class="tenue cifra">{tokens:,} tokens</span>'

    ultimo = act.get("ultimo")
    ultimo = ultimo.strftime("%d/%m/%Y") if ultimo else "nunca"

    accion = "Reanudar" if not c["active"] else "Pausar"

    return f"""<div class="fila" data-sem="{sem}">
      <div>
        <a class="fila-nombre" href="/superadmin/clientes/{cid}">{html.escape(c["nombre"])}</a>
        <span class="fila-id">{html.escape(c["slug"])} · id {cid}</span>
      </div>
      <div class="pila">{estado}{_chip_credenciales(credenciales)}{plan}</div>
      <div class="fila-dato">{cupo}</div>
      <div class="fila-dato">
        <span class="cifra">{act.get("contactos", 0)}</span> contactos<br>
        <span class="tenue"><span class="cifra">{act.get("mensajes", 0)}</span>
        mensajes · {ultimo}</span>
      </div>
      <div class="fila-acciones">
        <form method="post" action="/superadmin/clientes/{cid}/estado">
          <button class="suave" type="submit">{accion}</button>
        </form>
        <a class="boton suave" href="/superadmin/clientes/{cid}">Abrir</a>
      </div>
    </div>"""


# ── Alta ─────────────────────────────────────────────────────────────

@router.get("/nuevo", response_class=HTMLResponse)
def alta_form(request: Request, mal: str = "", campo: str = ""):
    """
    Dar de alta un negocio: una columna, cuatro tarjetas numeradas.

    Una columna y no dos: es un formulario que se rellena de arriba
    abajo, una sola vez por cliente, con datos que llegan por WhatsApp
    mientras se escriben. Dos columnas obligarían a decidir por dónde
    seguir en cada paso.

    `campo` dice cuál es el culpable del error. La banda roja arriba
    dice QUÉ pasó; el borde rojo dice DÓNDE, que es lo que no se puede
    adivinar en un formulario de quince campos.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    banda = f'<div class="banda mal">{html.escape(mal)}</div>' if mal else ""
    aviso_cifrado = "" if secretos.hay_clave() else (
        '<div class="banda mal">Falta <code>SECRETS_KEY</code>: sin ella no se '
        'pueden guardar cifradas las credenciales del cliente, y no se guardan '
        'en claro.</div>')

    def malo(nombre: str) -> str:
        return " malo" if campo == nombre else ""

    cabecera = _cabecera(
        "Dar de alta un negocio",
        resumen='Crea el negocio, su clave de panel y su contenido en un paso.',
        acciones='<a class="volver" href="/superadmin/clientes">← volver al listado</a>')

    cuerpo = f"""
      {banda}{aviso_cifrado}
      <form method="post" action="/superadmin/clientes" data-cuenta-cambios="alta">

        <div class="caja">
          <h2>1 · Identidad</h2>
          <div class="rejilla">
            <div>
              <label for="nombre">Nombre del negocio</label>
              <input id="nombre" name="nombre" required maxlength="80"
                     class="{malo("nombre").strip()}">
            </div>
            <div>
              <label for="slug">Subdominio</label>
              <input id="slug" name="slug" required maxlength="32"
                     pattern="[a-z0-9-]+" placeholder="panaderia"
                     class="mono{malo("slug")}">
              <p class="tenue">Su panel será
                 <code>slug.tudominio.com</code>. Solo minúsculas, números
                 y guiones.</p>
            </div>
          </div>
        </div>

        <div class="caja">
          <h2>2 · WhatsApp</h2>
          <p class="tenue">La App de Meta, la cuenta y el número son
             <strong>del cliente</strong>: los saca de su propio
             developers.facebook.com y nosotros no aparecemos ahí. Estas
             cuatro credenciales te las tiene que dar él.</p>
          <div class="rejilla">
            <div>
              <label for="pnid">phone_number_id</label>
              <input id="pnid" name="phone_number_id" required
                     inputmode="numeric" maxlength="40"
                     class="mono{malo("phone_number_id")}">
              <p class="tenue">Dice por qué número sale cada respuesta, y
                 confirma que los mensajes que entran son suyos.</p>
            </div>
            <div>
              <label for="waba">waba_id <span class="nota">(opcional)</span></label>
              <input id="waba" name="waba_id" maxlength="40" class="mono">
              <p class="tenue">Sin esto no se puede comprobar si su App
                 quedó suscrita al webhook.</p>
            </div>
          </div>
          <div class="rejilla">
            <div>
              <label for="app_id">App ID</label>
              <input id="app_id" name="app_id" inputmode="numeric"
                     maxlength="40" class="mono">
            </div>
            <div>
              <label for="app_secret">App Secret</label>
              <input id="app_secret" name="app_secret" autocomplete="off"
                     spellcheck="false" class="mono secreto">
              <p class="tenue">Con esto se valida la firma de sus webhooks.
                 Sin esto, sus mensajes se rechazan todos.</p>
            </div>
          </div>
          <label for="token">Token permanente de WhatsApp</label>
          <input id="token" name="whatsapp_token" required autocomplete="off"
                 spellcheck="false" class="mono secreto{malo("whatsapp_token")}">
          <p class="tenue">Tiene que ser de un <strong>System User</strong>.
             El que Meta enseña de primeras en el panel de la App dura 24 h
             y deja el bot mudo al día siguiente, sin avisar. Se comprueba
             solo: después de crear el negocio hay un botón que lo dice.</p>

          <label for="owner">Número del dueño del negocio</label>
          <input id="owner" name="owner_phone_number" required
                 inputmode="numeric" placeholder="573001234567" class="mono">
          <p class="tenue">Es la red de seguridad de los avisos: mientras no
             haya áreas, todo lo que entre le llega aquí. Sin él, el dueño
             no se entera de sus propios clientes.</p>
        </div>

        <div class="caja">
          <h2>3 · Paquete de IA</h2>
          <div class="rejilla">
            <div>
              <label for="plan">Plan</label>
              {_selector_plan(planes.PRO)}
              <p class="tenue">Decide si trae IA y cuántas áreas con su
                 usuario puede tener: {_resumen_cupos()}.</p>
              <label for="vence_el">Pagado hasta</label>
              <input id="vence_el" name="vence_el" type="date"
                     value="{_un_mes_desde_hoy()}">
              <p class="tenue">Desde el día siguiente se le cobra. Vacío = no
                 se le cobra.</p>
            </div>
            <div>
              <label for="ia_activa">¿Nace encendida?</label>
              <select id="ia_activa" name="ia_activa">
                <option value="no">No</option>
                <option value="si">Sí</option>
              </select>
            </div>
            <div>
              <label for="limite">Tope mensual de mensajes con IA</label>
              <input id="limite" name="ia_limite_mensual" type="number"
                     min="0" value="2000" class="cifra">
              <p class="tenue">0 = sin tope. Al pasarse, el bot sigue
                 vendiendo con el menú.</p>
            </div>
          </div>
          <label for="gemini">Clave de Gemini
            <span class="nota">(opcional)</span></label>
          <input id="gemini" name="gemini_api_key" autocomplete="off"
                 spellcheck="false" class="mono secreto">
          <p class="tenue">Si se deja vacía se usa la del despliegue y el
             consumo se le factura a este cliente. Si el cliente trae la
             suya, paga él directo a Google.</p>
        </div>

        <div class="caja">
          <h2>4 · Acceso al panel</h2>
          <div class="rejilla">
            <div>
              <label for="email">Usuario de quien administra</label>
              <input id="email" name="email" required class="mono"
                     autocomplete="off" autocapitalize="none" spellcheck="false"
                     placeholder="un nombre o un correo">
              <p class="tenue">Lo que escribirá al entrar a su panel. Único en
                 toda la plataforma.</p>
            </div>
            <div>
              <label for="clave">Clave del panel</label>
              <input id="clave" name="clave" required minlength="8"
                     class="{malo("clave").strip()}">
              <p class="tenue">8 caracteres o más. Es la que le pasas al
                 cliente.</p>
            </div>
          </div>
        </div>

        <div class="guardar-fijo">
          <span class="contador" data-contador-de="alta">Sin cambios</span>
          <button type="submit">Crear negocio</button>
          <p class="aviso">Se crea el negocio, su usuario de panel y su
             contenido en blanco. Lo primero que hay que hacer después es
             pasarle su URL de webhook: hasta que la pegue en Meta no le
             entra ni un mensaje.</p>
        </div>
      </form>"""

    return HTMLResponse(_pantalla("Alta", cabecera, cuerpo, activo="nuevo",
                                  estrecho=True, ayuda="nuevo"))


@router.post("/clientes")
def alta(request: Request,
         nombre: str = Form(...), slug: str = Form(...),
         phone_number_id: str = Form(...), whatsapp_token: str = Form(...),
         email: str = Form(...), clave: str = Form(...),
         owner_phone_number: str = Form(""),
         waba_id: str = Form(""), gemini_api_key: str = Form(""),
         app_id: str = Form(""), app_secret: str = Form(""),

         ia_activa: str = Form("no"), ia_limite_mensual: int = Form(0),
         plan: str = Form(""), vence_el: str = Form("")):
    """
    Crea el negocio, su clave de panel y su contenido, en un solo paso.

    Los tres van juntos a propósito: un cliente sin usuario de panel no
    puede entrar, y uno sin `negocio_config` leería variables de entorno
    del proceso, que son del despliegue y no suyas. Dejar cualquiera de las
    dos cosas "para después" es dejar un cliente a medio dar de alta.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    plan_elegido = (plan or "").strip().lower()
    if plan_elegido not in planes.PLANES:
        plan_elegido = planes.BASICO

    slug = (slug or "").strip().lower()
    if not SLUG_VALIDO.match(slug) or slug in SLUGS_PROHIBIDOS:
        return _redirigir_error(
            f"El subdominio {slug!r} no vale: solo minúsculas, números y "
            f"guiones, entre 3 y 32 caracteres, y no puede ser uno "
            f"reservado.", "slug")

    if len(clave) < 8:
        return _redirigir_error("La clave del panel necesita 8 caracteres o más.",
                                "clave")

    # Antes de crear nada: si el usuario ya existe en otro negocio, el
    # negocio quedaría creado y sin nadie que pudiera entrar.
    if not acceso.normalizar_usuario(email):
        return _redirigir_error("Hace falta un usuario para entrar al panel.",
                                "email")
    if acceso.quien_usa(email):
        return _redirigir_error(
            f"El usuario «{acceso.normalizar_usuario(email)}» ya existe. Cada "
            f"usuario es único en toda la plataforma: elige otro.", "email")

    if not secretos.hay_clave():
        return _redirigir_error(
            "Falta SECRETS_KEY: no se puede guardar cifrado el token del "
            "cliente, y en claro no se guarda.", "whatsapp_token")

    # ── El negocio nace EN BLANCO ────────────────────────────────────
    #
    # Antes se le copiaba el `negocio.toml` del repositorio como plantilla.
    # Sonaba cómodo y no lo era: cada cliente empezaba con el menú de OTRO
    # negocio —servicios que no vende, precios que no son suyos, textos con
    # el nombre cambiado a medias— y armarlo consistía en borrar. Borrar lo
    # que no entiendes es peor que escribir desde cero, porque lo que se
    # queda a medio borrar sale por WhatsApp.
    #
    # Ahora se crea con lo mínimo y el menú se arma en el mapa
    # (/superadmin/clientes/{id}/mapa). Mientras no tenga ninguna opción,
    # el bot responde el texto de cortesía y avisa al dueño; ver
    # `bot_logic._sin_contenido`.
    negocio = mapa.negocio_en_blanco(nombre.strip())
    try:
        ConfiguracionCliente(fila={"nombre": nombre.strip()}, negocio=negocio)
    except Exception as e:
        return _redirigir_error(f"No se pudo crear la configuración: {e}")

    session = database.get_session()
    try:
        if session.query(database.Client).filter_by(slug=slug).first():
            return _redirigir_error(
                f"Ya hay un negocio con el subdominio {slug!r}.", "slug")
        if session.query(database.Client).filter_by(
                phone_number_id=phone_number_id.strip()).first():
            return _redirigir_error(
                "Ese phone_number_id ya está en uso. Es la clave de "
                "enrutamiento del webhook: no puede repetirse.",
                "phone_number_id")

        cliente = database.Client(
            slug=slug,
            nombre=nombre.strip(),
            active=True,
            phone_number_id=phone_number_id.strip(),
            waba_id=waba_id.strip() or None,
            whatsapp_token=secretos.cifrar(whatsapp_token.strip()),
            app_id=app_id.strip() or None,
            app_secret=(secretos.cifrar(app_secret.strip())
                        if app_secret.strip() else None),
            # Los dos se generan aquí y no se piden: son NUESTROS, no del
            # cliente. Él los copia a su App de Meta, y por eso tienen que
            # existir desde el primer momento — si se dejaran para
            # "cuando haga falta", el alta terminaría sin que nadie tenga
            # qué pegar y el negocio quedaría sin recibir mensajes.
            webhook_token=_token_de_webhook(),
            verify_token=_token_de_webhook(),
            token_estado="sin_probar",
            gemini_api_key=(secretos.cifrar(gemini_api_key.strip())
                            if gemini_api_key.strip() else None),
            ia_contratada=planes.PLANES[plan_elegido].ia,
            ia_activa=(ia_activa == "si"),
            ia_limite_mensual=max(0, ia_limite_mensual),
            plan=plan_elegido,
            vence_el=_fecha_o_nada(vence_el),
            owner_phone_number=_solo_digitos(owner_phone_number) or None,
            negocio_config=negocio,
        )
        session.add(cliente)
        session.commit()
        client_id = cliente.id
    finally:
        session.close()

    acceso.crear_usuario(client_id, email, clave)
    config.olvidar(client_id)

    print(f"[superadmin] Cliente {client_id} ({slug}) dado de alta.")
    from urllib.parse import quote_plus
    # A la ficha y no al mapa, a diferencia de antes: lo primero que hay
    # que hacer ahora es darle al cliente su URL de webhook, porque hasta
    # que la pegue en su App de Meta no le entra ni un mensaje. Armar la
    # conversación puede esperar a que eso esté; al revés, no.
    return RedirectResponse(
        f"/superadmin/clientes/{client_id}?ok=" + quote_plus(
            f"Negocio creado: {slug} (id {client_id}). Pásale ahora los dos "
            f"datos de 'Lo que el cliente pega en su App de Meta', y después "
            f"ármale la conversación."),
        status_code=303)


def _un_mes_desde_hoy() -> str:
    from app.core import cobros
    return cobros.sumar_un_mes(cobros.hoy()).isoformat()


def _fecha_o_nada(texto: str):
    from datetime import date as _date
    try:
        return _date.fromisoformat((texto or "").strip()) if texto else None
    except ValueError:
        return None


def _redirigir_error(mensaje: str, campo: str = ""):
    """
    Vuelve al alta con el error, y con el NOMBRE del campo culpable.

    Las dos cosas hacen falta: la banda roja dice qué pasó y el borde
    rojo dice dónde. En un formulario de quince campos, un mensaje sin
    señal obliga a releerlo entero buscando cuál era.
    """
    from urllib.parse import quote_plus
    extra = f"&campo={quote_plus(campo)}" if campo else ""
    return RedirectResponse(
        f"/superadmin/nuevo?mal={quote_plus(mensaje)}{extra}", status_code=303)


# ══════════════════════════════════════════════════════════════════════
#  HOY Y COBROS: LA CONSOLA POR TAREAS (24-sep-2026)
# ══════════════════════════════════════════════════════════════════════
#
# La portada ya no es la tabla de todos los negocios: es lo que hay que
# hacer HOY. Primero lo que pide una acción —un cobro, algo roto—, después
# los números. La tabla sigue en "Clientes", y el dinero tiene su sección.

# Lo que pide que hagas algo. "Al día" y "sin cobro" no piden nada.
_ESTADOS_QUE_PIDEN_ALGO = ("pausado", "vencido", "por_vencer")

# El orden de urgencia en las listas de cobro.
_URGENCIA = {"pausado": 0, "vencido": 1, "por_vencer": 2, "al_dia": 3,
             "sin_cobro": 4}


def _cuentas_de_cobro() -> list:
    """`[(fila, Cuenta)]` de todos los negocios, del más urgente al que menos."""
    from app.core import cobros

    session = database.get_session()
    try:
        filas = [{c.name: getattr(cliente, c.name)
                  for c in database.Client.__table__.columns}
                 for cliente in session.query(database.Client).all()]
    finally:
        session.close()
    pares = [(f, cobros.cuenta(f)) for f in filas]
    pares.sort(key=lambda p: (_URGENCIA[p[1].estado],
                              p[1].vence_el or cobros.date.max))
    return pares


def _chip_cobro(c) -> str:
    from app.core import cobros
    if c.estado == cobros.PAUSADO:
        return '<span class="chip mal"><i class="punto"></i>pausado por impago</span>'
    if c.estado == cobros.VENCIDO:
        return (f'<span class="chip mal"><i class="punto"></i>vencido · se pausa '
                f'el {cobros.fecha_en_palabras(c.pausa_el)}</span>')
    if c.estado == cobros.POR_VENCER:
        cuando = "hoy" if c.dias == 0 else f"en {c.dias} días"
        return f'<span class="chip avisa"><i class="punto"></i>vence {cuando}</span>'
    if c.estado == cobros.AL_DIA:
        return '<span class="chip bien"><i class="punto"></i>al día</span>'
    return '<span class="chip neutro">sin cobro</span>'


def _boton_pago(client_id: int, precio: int, volver: str) -> str:
    """"Registrar pago" en una línea, para las listas de Hoy y de Cobros."""
    return f"""
          <form method="post" action="/superadmin/clientes/{client_id}/pago"
                class="pago-rapido">
            <input type="hidden" name="volver" value="{volver}">
            <input name="monto" type="number" min="0" value="{precio}"
                   class="cifra" aria-label="Monto recibido">
            <button type="submit" class="mini">Registrar pago</button>
          </form>"""


def _fila_tarea(fila: dict, c, volver: str) -> str:
    from app.core import cobros
    vence = (f"pagado hasta el {cobros.fecha_en_palabras(c.vence_el)}"
             if c.vence_el else "")
    return f"""
        <div class="tarea">
          <div class="tarea-que">
            <a href="/superadmin/clientes/{fila["id"]}">{html.escape(fila["nombre"])}</a>
            <span class="tenue">{html.escape(c.plan.nombre)} ·
              {planes.pesos(c.precio)} · {html.escape(vence)}</span>
          </div>
          {_chip_cobro(c)}
          {_boton_pago(fila["id"], c.precio, volver)}
        </div>"""


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def hoy(request: Request, ok: str = "", mal: str = ""):
    """
    La portada: lo que hay que hacer hoy, y los números del mes.

    Arriba, lo que pide una acción: cobros que vencen o vencieron y
    negocios con algo roto. Si no hay nada, se dice con una frase y no con
    cajas vacías. Abajo, cuánto se espera cobrar y cuánto entró este mes.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    from app.core import cobros

    banda = ""
    if ok:
        banda = f'<div class="banda ok">{html.escape(ok)}</div>'
    elif mal:
        banda = f'<div class="banda mal">{html.escape(mal)}</div>'

    pares = _cuentas_de_cobro()
    por_cobrar = [(f, c) for f, c in pares if c.estado in _ESTADOS_QUE_PIDEN_ALGO]
    problemas = _requieren_atencion()

    if por_cobrar:
        caja_cobros = f"""
      <div class="caja">
        <div class="etiqueta-fila"><h2>Cobros que piden algo</h2>
          <a class="volver" href="/superadmin/cobros">ver todos los cobros →</a></div>
        {"".join(_fila_tarea(f, c, "hoy") for f, c in por_cobrar)}
      </div>"""
    else:
        caja_cobros = """
      <div class="caja">
        <h2>Cobros</h2>
        <p class="tenue">Todo al día: nada vence esta semana.</p>
      </div>"""

    if problemas:
        filas_problema = "".join(f"""
        <div class="tarea">
          <div class="tarea-que">
            <a href="/superadmin/clientes/{p["id"]}">{html.escape(p["nombre"])}</a>
          </div>
          <span class="chip {"mal" if p["grave"] else "avisa"}"><i class="punto"></i>{html.escape(p["motivo"])}</span>
          <a class="boton suave mini" href="/superadmin/clientes/{p["id"]}?bloque=whatsapp">Revisar</a>
        </div>""" for p in problemas)
        caja_problemas = f"""
      <div class="caja">
        <h2>Negocios con algo roto</h2>
        <p class="tenue">Un negocio con las credenciales rotas está mudo, y por
           fuera se ve igual que un día flojo.</p>
        {filas_problema}
      </div>"""
    else:
        caja_problemas = """
      <div class="caja">
        <h2>Problemas</h2>
        <p class="tenue">Ningún negocio con credenciales rotas ni sin cupo.</p>
      </div>"""

    este_mes = cobros.hoy().replace(day=1)
    activos_con_cobro = [(f, c) for f, c in pares
                         if f["active"] and c.estado != cobros.SIN_COBRO]
    esperado = sum(c.precio for _f, c in activos_con_cobro)
    recibido = sum((c.ultimo_pago_monto or 0) for _f, c in pares
                   if c.ultimo_pago_el and c.ultimo_pago_el >= este_mes)
    activos = sum(1 for f, _c in pares if f["active"])
    pausados = len(pares) - activos

    metricas = f"""
      <div class="metricas">
        <div class="metrica"><p class="rotulo">Cobro mensual esperado</p>
          <p class="valor">{planes.pesos(esperado)}</p>
          <p class="pie">{len(activos_con_cobro)} negocios con fecha de pago</p></div>
        <div class="metrica"><p class="rotulo">Recibido este mes</p>
          <p class="valor">{planes.pesos(recibido)}</p>
          <p class="pie">pagos registrados desde el 1 de
             {cobros.MESES[este_mes.month - 1]}</p></div>
        <div class="metrica"><p class="rotulo">Negocios</p>
          <p class="valor">{activos}</p>
          <p class="pie">activos · {pausados} pausados</p></div>
      </div>"""

    cabecera = _cabecera(
        f"Hoy · {cobros.hoy().day} de {cobros.MESES[cobros.hoy().month - 1]}",
        resumen="Lo que pide tu atención primero; los números, después.",
        acciones='<a class="boton" href="/superadmin/nuevo">Dar de alta</a>')

    return HTMLResponse(_pantalla(
        "Hoy", cabecera, banda + caja_cobros + caja_problemas + metricas,
        activo="hoy", ayuda="hoy"))


@router.get("/cobros", response_class=HTMLResponse)
def cobros_pantalla(request: Request, ok: str = "", mal: str = ""):
    """Todos los negocios y lo que nos pagan, del más urgente al que menos."""
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    from app.core import cobros

    banda = ""
    if ok:
        banda = f'<div class="banda ok">{html.escape(ok)}</div>'
    elif mal:
        banda = f'<div class="banda mal">{html.escape(mal)}</div>'

    pares = _cuentas_de_cobro()
    filas = "".join(f"""
        <div class="tarea">
          <div class="tarea-que">
            <a href="/superadmin/clientes/{f["id"]}">{html.escape(f["nombre"])}</a>
            <span class="tenue">{html.escape(c.plan.nombre)} ·
              {planes.pesos(c.precio)} al mes
              {"· pagado hasta el " + cobros.fecha_en_palabras(c.vence_el) if c.vence_el else ""}
              {"· último pago " + cobros.fecha_en_palabras(c.ultimo_pago_el) if c.ultimo_pago_el else ""}</span>
          </div>
          {_chip_cobro(c)}
          {_boton_pago(f["id"], c.precio, "cobros") if c.estado != cobros.SIN_COBRO
           else f'<a class="boton suave mini" href="/superadmin/clientes/{f["id"]}">Ponerle fecha</a>'}
        </div>""" for f, c in pares)

    cabecera = _cabecera(
        "Cobros",
        resumen=(f"Una semana antes de vencer se le avisa al dueño por correo, "
                 f"cada día; {planes.DIAS_DE_GRACIA} días después se pausa solo. "
                 f"Registrar el pago corre la fecha un mes y lo reactiva."))
    return HTMLResponse(_pantalla(
        "Cobros", cabecera, banda + f'<div class="caja">{filas}</div>',
        activo="cobros", ayuda="cobros"))


def _zona_peligrosa(client_id: int, datos: dict) -> str:
    """
    Eliminar el negocio: lo único de la consola que no tiene vuelta atrás.

    Detrás de un `<details>` y pidiendo escribir su nombre corto, que es la
    forma de que no se haga por un clic despistado en la ficha equivocada.
    El bot de casa no se puede eliminar.
    """
    if client_id == database.CLIENTE_POR_DEFECTO:
        return ""
    slug = html.escape(datos.get("slug") or "")
    return f"""
      <details class="caja peligro-zona">
        <summary>Eliminar este negocio</summary>
        <p>Se borra TODO: sus conversaciones, contactos, citas, usuarios del
           panel y su configuración. No se puede deshacer. Si solo no paga,
           <strong>pausarlo</strong> conserva todo.</p>
        <form method="post" action="/superadmin/clientes/{client_id}/eliminar">
          <label for="confirmar">Para confirmar, escribe su nombre corto:
            <code>{slug}</code></label>
          <input id="confirmar" name="confirmar" autocomplete="off"
                 class="mono" required>
          <button type="submit" class="peligro">Eliminar para siempre</button>
        </form>
      </details>"""


@router.post("/clientes/{client_id}/eliminar")
async def eliminar(request: Request, client_id: int):
    """
    Borra un negocio y todo lo suyo. Pide que se escriba su nombre corto.

    Se borra tabla por tabla y con `client_id` explícito: corre sin
    inquilino, así que el filtro automático no añade nada, y RLS deja pasar
    lo que no lleva inquilino anunciado (ver `database`).
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()
    if client_id == database.CLIENTE_POR_DEFECTO:
        return _volver_a_ficha(client_id, mal="El bot de casa no se elimina.")

    formulario = await request.form()
    session = database.get_session()
    try:
        cliente = session.query(database.Client).filter_by(id=client_id).first()
        if cliente is None:
            return RedirectResponse("/superadmin/clientes?mal=Ese+negocio+no+existe.",
                                    status_code=303)
        slug, nombre = cliente.slug, cliente.nombre
        if (formulario.get("confirmar") or "").strip().lower() != slug:
            return _volver_a_ficha(
                client_id, mal="El nombre corto no coincide: no se borró nada.")

        # Los mensajes y leads antes que los contactos (las citas apuntan a
        # su contacto), y todo antes que la fila del negocio.
        for modelo in (database.Message, database.Lead, database.Contact,
                       database.Ajuste, database.PushSubscription,
                       database.ProcessedMessage, database.PanelUser,
                       database.IAUso):
            session.query(modelo).filter(modelo.client_id == client_id).delete(
                synchronize_session=False)
        session.delete(cliente)
        session.commit()
    finally:
        session.close()

    _olvidar_caches(client_id)
    print(f"[superadmin] Cliente {client_id} ({slug}) ELIMINADO.")
    return RedirectResponse(
        f"/superadmin/clientes?ok={quote_plus(f'{nombre} eliminado para siempre.')}",
        status_code=303)


# ── Pausar y reanudar ────────────────────────────────────────────────

@router.post("/clientes/{client_id}/estado")
def cambiar_estado(request: Request, client_id: int):
    """
    La palanca comercial: pausar a quien no paga.

    Es un `UPDATE` de una columna y surte efecto en menos de un minuto (lo
    que dure el caché de `tenencia`, que además se invalida aquí mismo). El
    webhook de ese negocio deja de procesarse y su panel deja de abrir. No
    se borra nada: al volver, tiene su historial intacto.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    session = database.get_session()
    try:
        cliente = session.query(database.Client).filter_by(id=client_id).first()
        if cliente is None:
            return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                    status_code=303)

        cliente.active = not cliente.active
        cliente.paused_at = None if cliente.active else database.ahora_utc()
        # Una pausa (o reanudación) a mano es una decisión tuya, no del
        # cobro: el próximo pago no debe deshacerla sola.
        cliente.pausado_por = None
        nombre, activo = cliente.nombre, cliente.active
        session.commit()
    finally:
        session.close()

    _olvidar_caches(client_id)

    accion = "reanudado" if activo else "pausado"
    print(f"[superadmin] Cliente {client_id} ({nombre}) {accion}.")
    # Codificado: un "&" o un "#" en el nombre del negocio cortaba el
    # mensaje en la dirección.
    return RedirectResponse(
        f"/superadmin/clientes?ok={quote_plus(f'{nombre} {accion}.')}",
        status_code=303)


def _olvidar_caches(client_id: int):
    """
    Todo lo que este proceso tiene guardado de un cliente.

    Hay que tirarlo entero al cambiarle algo, y en este orden de
    importancia: la configuración (que lleva sus credenciales), el cliente
    de Gemini (que lleva su clave y su modelo) y su icono. Sin esto, un
    cambio tardaría hasta un minuto en verse — o no se vería nunca, porque
    los cachés de Gemini y del icono no caducan.
    """
    config.olvidar(client_id)          # incluye tenencia.olvidar()
    pwa.olvidar(client_id)

    from app.bot.cerebro import gemini
    gemini.olvidar(client_id)


# ── Editar un cliente ────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════
#  LA FICHA DE UN CLIENTE
# ══════════════════════════════════════════════════════════════════════
#
# Eran once bloques apilados en una sola página, y encontrar cualquier
# cosa consistía en recorrerla entera. Ahora se agrupan por FRECUENCIA DE
# USO, que es lo que decide dónde se busca algo: lo de todos los días
# arriba, lo que se toca una vez al dar de alta detrás de una pestaña.
#
# Las pestañas son ENLACES de verdad (`?bloque=avisos`), no JavaScript:
# se recargan, se comparten por chat y funcionan con el botón de atrás.
# Una consola que se opera un domingo no puede depender de que un guion
# cargue.
#
# ── UN FORMULARIO POR TARJETA ─────────────────────────────────────────
# Se acabó el formulario gigante. Cada tarjeta guarda LO SUYO, con su
# botón al lado. Eso obliga a que `guardar()` sepa aplicar solo los
# campos que le llegan — ver la nota de CAMPOS_DE_LA_FICHA — pero a
# cambio nadie vuelve a preguntarse qué acaba de guardar.

PESTANAS = (
    ("resumen",       "Resumen",               ""),
    ("avisos",        "Avisos y áreas",        ""),
    ("whatsapp",      "WhatsApp e IA",         ""),
    ("usuarios",      "Usuarios",              ""),
    ("integraciones", "Integraciones y marca", ""),
    ("contenido",     "Contenido del bot",     "/contenido"),
    ("mapa",          "Mapa de conversación",  "/mapa"),
)


def _pestanas_ficha(client_id: int, activa: str) -> str:
    partes = []
    for clave, etiqueta, sufijo in PESTANAS:
        href = (f"/superadmin/clientes/{client_id}{sufijo}" if sufijo
                else f"/superadmin/clientes/{client_id}?bloque={clave}")
        marca = " activa" if clave == activa else ""
        partes.append(f'<a class="pestana{marca}" href="{href}">{etiqueta}</a>')
    return f'<div class="pestanas">{"".join(partes)}</div>'


def _cabecera_ficha(client_id: int, datos: dict) -> str:
    """
    Nombre, los dos chips de estado y las dos acciones de operación.

    `Probar credenciales` y `Pausar` van aquí y no dentro de una tarjeta
    porque no pertenecen a ninguna: son lo que se le hace al cliente
    entero, y se necesitan desde cualquier pestaña.
    """
    estado = ('<span class="chip morado">activo</span>' if datos["active"]
              else '<span class="chip neutro">pausado</span>')
    accion = "Reanudar" if not datos["active"] else "Pausar"

    return _cabecera(
        html.escape(datos["nombre"]),
        resumen=(f'<span class="mono">{html.escape(datos["slug"] or "")} · '
                 f'id {client_id}</span> · '
                 f'<a class="volver" href="/superadmin/clientes">volver al listado</a>'),
        chips=f'{estado}{_chip_credenciales(datos.get("token_estado") or "")}',
        acciones=f"""
        <form method="post" action="/superadmin/clientes/{client_id}/probar">
          <button class="suave" type="submit">Probar credenciales</button>
        </form>
        <form method="post" action="/superadmin/clientes/{client_id}/estado">
          <button type="submit">{accion}</button>
        </form>""")


@router.get("/clientes/{client_id}", response_class=HTMLResponse)
def ficha(request: Request, client_id: int, mal: str = "", ok: str = "",
          bloque: str = "resumen"):
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    session = database.get_session()
    try:
        cliente = session.query(database.Client).filter_by(id=client_id).first()
        if cliente is None:
            return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                    status_code=303)
        datos = {c.name: getattr(cliente, c.name)
                 for c in database.Client.__table__.columns}
    finally:
        session.close()

    if bloque not in {"resumen", "avisos", "whatsapp", "usuarios",
                      "integraciones"}:
        bloque = "resumen"

    banda = ""
    if ok:
        banda = f'<div class="banda ok">{html.escape(ok)}</div>'
    elif mal:
        banda = f'<div class="banda mal">{html.escape(mal)}</div>'

    if bloque == "resumen":
        cuerpo = _bloque_resumen(request, client_id, datos)
    elif bloque == "avisos":
        cuerpo = _caja_avisos(client_id, datos)
    elif bloque == "whatsapp":
        cuerpo = _bloque_whatsapp(client_id, datos, mal)
    elif bloque == "usuarios":
        cuerpo = _caja_usuarios(client_id, acceso.listar_usuarios(client_id),
                                _direccion_de_entrada(request, datos))
    else:
        cuerpo = _bloque_integraciones(client_id, datos)

    return HTMLResponse(_pantalla(
        datos["nombre"], _cabecera_ficha(client_id, datos), banda + cuerpo,
        activo="clientes", pestanas=_pestanas_ficha(client_id, bloque),
        ayuda=bloque,
        guiones=("superadmin-logo.js",) if bloque == "integraciones" else ()))


def _val(datos: dict):
    def leer(clave, defecto=""):
        return html.escape(str(datos.get(clave) or defecto))
    return leer


def _bloque_resumen(request: Request, client_id: int, datos: dict) -> str:
    """
    Lo que se mira al entrar: cómo va, qué se le entrega y quién es.

    La banda de fallo va arriba del todo porque es la única señal que
    existe de que un lead se perdió — el cliente final recibió su
    respuesta con normalidad y nadie más se enteró.
    """
    val = _val(datos)
    gastado = consumo.del_mes(client_id)
    actividad = database.actividad_por_cliente().get(client_id, {})

    limite = datos.get("ia_limite_mensual") or 0
    agotado = bool(limite) and gastado["mensajes"] >= limite
    cupo_texto = (f'{gastado["mensajes"]:,} / {limite:,}' if limite
                  else f'{gastado["mensajes"]:,}')

    ultimo = actividad.get("ultimo")
    ultimo = ultimo.strftime("%d/%m/%Y") if ultimo else "nunca"

    # Lo que pasa ahora, con lo que eligió el dueño en su panel incluido;
    # la columna `ia_activa` es solo cómo nació. Ver `_ia_ahora`.
    estado_ia = _ia_ahora(client_id)
    encendida = (estado_ia["ia_encendida"] if estado_ia
                 else bool(datos["ia_activa"]))
    ia = "encendida" if encendida else "apagada"
    if not planes.de(datos).ia:
        ia = "no incluida en su plan"

    metricas = f"""
      <div class="metricas">
        <div class="metrica">
          <p class="rotulo">IA en {gastado["periodo"]}</p>
          <p class="valor{" mal" if agotado else ""}">{cupo_texto}</p>
          <p class="pie">{"sin cupo este mes" if agotado
                          else ("mensajes · sin tope" if not limite
                                else "mensajes del tope")}</p>
        </div>
        <div class="metrica">
          <p class="rotulo">Conversación</p>
          <p class="valor">{actividad.get("contactos", 0):,}</p>
          <p class="pie">contactos · {actividad.get("mensajes", 0):,} mensajes
             · último {ultimo}</p>
        </div>
        <div class="metrica">
          <p class="rotulo">Plan</p>
          <p class="valor" style="font-size:15px">{html.escape(planes.de(datos).nombre)}</p>
          <p class="pie">IA {ia} · {_cupo_avisos(client_id)} áreas de aviso</p>
        </div>
      </div>"""

    tiene_propio = bool(datos.get("negocio_config"))
    aviso_contenido = "" if tiene_propio else """
      <div class="banda avisa">Este negocio todavía lee el
        <code>negocio.toml</code> del repositorio. En cuanto se guarde algo
        desde el editor de contenido o el mapa, pasa a la base y el archivo
        deja de afectarle.</div>"""

    return (_banda_de_fallo(client_id)
            + metricas
            + _caja_cobro(client_id, datos)
            + aviso_contenido
            + _caja_meta(request, client_id, datos)
            + f"""
      <form method="post" action="/superadmin/clientes/{client_id}">
        <input type="hidden" name="_bloque" value="resumen">
        <div class="caja">
          <h2>Identidad</h2>
          <div class="rejilla">
            <div>
              <label for="nombre">Nombre del negocio</label>
              <input id="nombre" name="nombre" value="{val("nombre")}" required
                     maxlength="80">
            </div>
            <div>
              <label for="slug">Nombre corto (con el que entra al panel)</label>
              <input id="slug" name="slug" value="{val("slug")}" required
                     maxlength="32" pattern="[a-z0-9-]+" class="mono">
              <p class="tenue">Para entrar al panel ya no hace falta: se
                 entra con usuario y clave (pestaña
                 <a href="/superadmin/clientes/{client_id}?bloque=usuarios">Usuarios</a>).
                 Sigue sirviendo de subdominio y a quien aún escribe el
                 negocio en vez de su usuario.</p>
            </div>
          </div>
          <div class="caja-pie">
            <button type="submit" class="guardar-caja">Guardar identidad</button>
          </div>
        </div>
      </form>""" + _zona_peligrosa(client_id, datos))


def _caja_cobro(client_id: int, datos: dict) -> str:
    """
    Lo que nos paga este negocio: hasta cuándo, cuánto, y el botón para
    anotar un pago. Ver `app/core/cobros.py`.

    Registrar un pago corre la fecha un mes y, si lo había pausado el
    cobro, lo reactiva. La fecha también se puede poner a mano, que es lo
    que hace falta la primera vez o para corregir.
    """
    from app.core import cobros

    c = cobros.cuenta(datos)
    estados = {
        cobros.SIN_COBRO: ("neutro", "sin cobro: no tiene fecha"),
        cobros.AL_DIA: ("bien", "al día"),
        cobros.POR_VENCER: ("avisa", f"vence en {c.dias} días" if c.dias
                            else "vence hoy"),
        cobros.VENCIDO: ("mal", f"vencido · se pausa el "
                         f"{cobros.fecha_en_palabras(c.pausa_el)}"),
        cobros.PAUSADO: ("mal", "pausado por impago"),
    }
    clase, texto = estados[c.estado]
    ultimo = (f"Último pago: {cobros.fecha_en_palabras(c.ultimo_pago_el)} · "
              f"{planes.pesos(c.ultimo_pago_monto or 0)}"
              if c.ultimo_pago_el else "Sin pagos registrados.")
    vence = datos.get("vence_el")
    return f"""
      <div class="caja">
        <div class="etiqueta-fila">
          <h2>Cobro</h2>
          <span class="chip {clase}"><i class="punto"></i>{html.escape(texto)}</span>
        </div>
        <p class="tenue">{html.escape(ultimo)}</p>
        <form method="post" action="/superadmin/clientes/{client_id}/pago"
              class="rejilla">
          <div>
            <label for="monto">Monto recibido</label>
            <input id="monto" name="monto" type="number" min="0" class="cifra"
                   value="{c.precio}">
          </div>
          <div style="align-self:end">
            <button type="submit">Registrar pago</button>
            <p class="tenue">Corre el vencimiento un mes
               {"y lo reactiva" if c.estado == cobros.PAUSADO else ""}.</p>
          </div>
        </form>
        <form method="post" action="/superadmin/clientes/{client_id}">
          <input type="hidden" name="_bloque" value="resumen">
          <div class="rejilla">
            <div>
              <label for="vence_el">Pagado hasta</label>
              <input id="vence_el" name="vence_el" type="date"
                     value="{vence.isoformat() if vence else ""}">
              <p class="tenue">Vacío = no se le cobra.</p>
            </div>
            <div>
              <label for="precio_mensual">Precio pactado</label>
              <input id="precio_mensual" name="precio_mensual" type="number"
                     min="0" class="cifra"
                     value="{datos.get("precio_mensual") if datos.get("precio_mensual") is not None else ""}"
                     placeholder="{planes.de(datos).precio} (el de su plan)">
            </div>
          </div>
          <div class="caja-pie">
            <button type="submit" class="guardar-caja suave">Guardar fecha y precio</button>
          </div>
        </form>
      </div>"""


def _banda_de_fallo(client_id: int) -> str:
    """
    El último aviso que Meta aceptó y luego no pudo entregar.

    Un 200 de Meta es "lo acepto", no "lo entregué": si después no puede,
    lo dice en un webhook de `statuses`, no como error del envío. Esta
    banda es la única señal que existe de que un lead se perdió.
    """
    from app.bot import notificaciones

    try:
        with tenencia.usar(client_id):
            ultimo = notificaciones.ultimo_no_entregado()
    except Exception:
        ultimo = None

    if not ultimo:
        return ""

    # Dos orígenes con causas distintas: Meta, que acepta y luego no
    # entrega, y el servidor de correo de la plataforma (ver
    # `correo._enviar_o_anotar`). Explicar el de Meta al lado de un correo
    # mandaría a buscar el problema donde no está.
    if "@" in (ultimo["numero"] or ""):
        explicacion = ("Lo dijo el servidor de correo de la plataforma. Si se "
                       "repite con todas las áreas, es el SMTP (SMTP_HOST, "
                       "SMTP_USUARIO, SMTP_CLAVE); si es solo esta, la "
                       "dirección.")
    else:
        explicacion = ("Lo dice Meta después de aceptarlo. La causa más "
                       "común: esa persona no le ha escrito al bot en 24 h y "
                       "el negocio no tiene plantilla de avisos.")

    return f"""
      <div class="banda mal">
        <strong>Un aviso no se entregó.</strong>
        {html.escape(ultimo["cuando"])} · a
        <span class="mono">{html.escape(ultimo["numero"])}</span> ·
        {html.escape(ultimo["motivo"])}
        <br><span class="tenue">{explicacion}
        <a href="/superadmin/clientes/{client_id}?bloque=avisos">Ver los
        avisos</a>.</span>
      </div>"""


def _bloque_whatsapp(client_id: int, datos: dict, mal: str = "") -> str:
    """
    Las credenciales de Meta y el paquete de IA. Dos tarjetas, dos
    formularios, dos botones.

    Los secretos salen SIEMPRE vacíos con el marcador diciéndolo con
    todas las letras: están cifrados en la base, y descifrarlos para
    meterlos en un `value=` los dejaría en el HTML, en el historial del
    navegador y en cualquier caché por el camino.
    """
    val = _val(datos)
    roto = (datos.get("token_estado") or "") == "mal"
    marca_rota = " malo" if roto else ""

    # El motivo real, tal como lo devolvió Meta al probar. Solo aparece
    # justo después de probar, que es cuando significa algo: guardarlo
    # sería enseñar el error de la semana pasada al lado de un token que
    # a lo mejor ya se rotó.
    motivo = (f'<p class="motivo">{html.escape(mal)}</p>'
              if roto and mal else "")

    # Lo que está pasando AHORA, no lo que dice la columna. `ia_activa` es
    # solo cómo nace: en cuanto el dueño pulsa "Encender" o "Apagar" en su
    # panel, manda lo que eligió (`cerebro.plan_activo`). El selector
    # enseñaba la columna, así que decía "No" con la IA encendida y "Sí"
    # con la IA apagada, según quién la tocó el último.
    estado = _ia_ahora(client_id)
    encendida = (estado["ia_encendida"] if estado and planes.de(datos).ia
                 else bool(datos["ia_activa"]))

    return f"""
      <form method="post" action="/superadmin/clientes/{client_id}">
        <input type="hidden" name="_bloque" value="whatsapp">
        <div class="caja">
          <h2>WhatsApp</h2>
          <p class="tenue">Cada cliente trae su propia App de Meta. La firma
             de sus webhooks se valida con SU <code>app_secret</code>, así
             que estas credenciales son suyas y no del despliegue.</p>
          <div class="rejilla">
            <div>
              <label for="pnid">phone_number_id</label>
              <input id="pnid" name="phone_number_id" class="mono"
                     value="{val("phone_number_id")}">
              <p class="tenue">La clave de enrutamiento del webhook.</p>
            </div>
            <div>
              <label for="waba">waba_id</label>
              <input id="waba" name="waba_id" value="{val("waba_id")}" class="mono">
            </div>
          </div>
          <div class="rejilla">
            <div>
              <label for="app_id">App ID</label>
              <input id="app_id" name="app_id" value="{val("app_id")}" class="mono">
            </div>
            <div>
              <label for="app_secret">App Secret</label>
              <input id="app_secret" name="app_secret" type="password"
                     autocomplete="off" class="mono secreto{marca_rota}"
                     placeholder="{_marca_secreto(datos, "app_secret")}">
              {motivo}
              <p class="tenue">Con esto se valida la firma de sus webhooks.
                 Sin esto, todos sus mensajes se rechazan.</p>
            </div>
          </div>
          <label for="token">Token permanente</label>
          <input id="token" name="whatsapp_token" type="password"
                 autocomplete="off" class="mono secreto{marca_rota}"
                 placeholder="{_marca_secreto(datos, "whatsapp_token")}">
          {motivo}
          <p class="tenue">Los tokens de Meta caducan o se regeneran. Aquí se
             rota sin desplegar. Tiene que ser de un System User: el que Meta
             enseña de primeras dura 24 h y deja el bot mudo al día
             siguiente.</p>
          <div class="caja-pie">
            <p class="tenue"><strong>Vacío = no se toca.</strong> Lo que hay
               guardado no se pinta nunca: escribe algo solo si quieres
               cambiarlo.</p>
            <button type="submit" class="guardar-caja">Guardar WhatsApp</button>
          </div>
        </div>
      </form>

      <form method="post" action="/superadmin/clientes/{client_id}">
        <input type="hidden" name="_bloque" value="whatsapp">
        <div class="caja">
          <h2>Paquete de IA</h2>
          {_estado_de_la_ia(client_id, datos)}
          <div class="rejilla">
            <div>
              <label for="plan">Plan</label>
              {_selector_plan(planes.codigo_de(datos))}
              <p class="tenue">Es la puerta comercial: decide si trae IA
                 (en Básico el dueño no ve el interruptor) y cuántas áreas
                 con su usuario puede tener: {_resumen_cupos()}.</p>
            </div>
            <div>
              <label for="ia_activa">¿Encendida?</label>
              <select id="ia_activa" name="ia_activa">
                <option value="no"{"" if encendida else " selected"}>No — responde con el menú</option>
                <option value="si"{" selected" if encendida else ""}>Sí — entiende lo que escriben</option>
              </select>
              <p class="tenue">Surte efecto al guardar, sin desplegar. El
                 dueño puede apagarla y encenderla después desde su
                 panel.</p>
            </div>
            <div>
              <label for="limite">Tope mensual</label>
              <input id="limite" name="ia_limite_mensual" type="number" min="0"
                     class="cifra"
                     value="{datos.get("ia_limite_mensual") or 0}">
              <p class="tenue">0 = sin tope.</p>
            </div>
            <div>
              <label for="modelo">Modelo</label>
              <input id="modelo" name="gemini_modelo" value="{val("gemini_modelo")}"
                     class="mono"
                     placeholder="{html.escape(config.base().GEMINI_MODELO)}">
              <p class="tenue">Los modelos caducan: cambiarlo aquí es un
                 UPDATE, no un despliegue.</p>
            </div>
          </div>
          <label for="gemini">Clave de Gemini propia del cliente</label>
          <input id="gemini" name="gemini_api_key" type="password"
                 autocomplete="off" class="mono secreto"
                 placeholder="{_marca_secreto(datos, "gemini_api_key")}">
          <p class="tenue">Si la trae él, paga él y no se le factura consumo.
             Vacío = usa la del despliegue y se le mide.</p>
          <div class="caja-pie">
            <button type="submit" class="suave"
                    formaction="/superadmin/clientes/{client_id}/probar-ia"
                    formnovalidate>Probar la IA</button>
            <button type="submit" class="guardar-caja">Guardar IA</button>
          </div>
        </div>
      </form>"""


def _ia_ahora(client_id: int):
    """
    `cerebro.estado()` de ESE negocio, o None si no se pudo leer.

    Con `tenencia.usar`: el super-admin corre sin inquilino, y el plan que
    eligió el dueño es un ajuste suyo — sin fijarlo se leería el de nadie.
    """
    from app.bot import cerebro
    try:
        with tenencia.usar(client_id):
            return cerebro.estado()
    except Exception as e:
        print(f"[superadmin] No se pudo leer el estado de la IA de "
              f"{client_id}: {e}")
        return None


def _estado_de_la_ia(client_id: int, datos: dict) -> str:
    """
    Una línea que dice si la IA de este negocio contesta hoy, y por qué no.

    Existe porque "la IA ya no responde" no se podía diagnosticar desde
    aquí: la ficha enseñaba lo contratado y cómo nacía, pero no lo que el
    dueño eligió después en su panel ni el último fallo de Gemini. Eso
    solo se veía entrando a SU panel, o en los logs del hosting.
    """
    estado = _ia_ahora(client_id)
    if estado is None:
        return ('<div class="banda avisa">No se pudo leer el estado de la '
                'IA de este negocio. Mira el log del servidor.</div>')

    if not estado["contratada"]:
        return ('<div class="banda avisa"><strong>IA apagada:</strong> no '
                'tiene el paquete contratado. El bot entiende los títulos '
                'de sus botones escritos a mano, y nada más.</div>')

    if not estado["clave_configurada"]:
        return ('<div class="banda mal"><strong>IA apagada:</strong> no hay '
                'clave de Gemini, ni propia ni del despliegue.</div>')

    if not estado["ia_encendida"]:
        from app.bot import cerebro
        from app.core import ajustes
        with tenencia.usar(client_id):
            elegido = ajustes.leer(cerebro.AJUSTE_PLAN, None)
        porque = ("el dueño la apagó desde su panel" if elegido == cerebro.BASICO
                  else "nunca se encendió")
        return (f'<div class="banda avisa"><strong>IA apagada ahora mismo:'
                f'</strong> está contratada, pero {porque}. Ponla en '
                f'<strong>Sí</strong> aquí abajo y guarda.</div>')

    fallo = estado.get("ultimo_fallo")
    if fallo:
        return (f'<div class="banda mal"><strong>IA encendida, pero su último '
                f'intento falló</strong> ({html.escape(fallo["cuando"])} UTC): '
                f'{html.escape(fallo["motivo"])}<br><span class="tenue">Mientras '
                f'falle, el bot responde con el menú. Pulsa '
                f'<strong>Probar la IA</strong> para ver si ya '
                f'responde.</span></div>')

    agotado = (estado["tope_mensual"]
               and estado["restantes_mes"] is not None
               and estado["restantes_mes"] <= 0)
    if agotado:
        return ('<div class="banda mal"><strong>IA sin cupo este mes:</strong> '
                'gastó su tope mensual y responde con el menú hasta el mes '
                'que viene.</div>')

    return (f'<div class="banda ok"><strong>IA encendida</strong> con '
            f'<span class="mono">{html.escape(estado["modelo"] or "")}</span>. '
            f'Sin fallos desde que arrancó el servidor.</div>')


@router.post("/clientes/{client_id}/probar-ia")
def probar_ia(request: Request, client_id: int):
    """
    Le hace una pregunta de verdad a Gemini con la clave y el modelo de
    ESTE negocio, y dice qué contestó.

    Lo que "Probar credenciales" es para Meta. Sin esto, comprobar la IA de
    un cliente en producción pedía escribirle a su bot desde un teléfono y
    adivinar por qué respondía con el menú.

    ⚠️  Un error de Google puede llevar dentro la clave, y este mensaje
    viaja en la URL de la redirección. Se tapa antes de salir de aquí,
    igual que `meta_estado._tapar` con los tokens de Meta.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()
    if not _cliente_existe(client_id):
        return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                status_code=303)

    # Cliente de Gemini nuevo: si la clave falló una vez, el proceso la da
    # por perdida hasta que se olvide (`gemini._intento_fallido`), y la
    # prueba repetiría el fallo viejo en vez de probar la clave de ahora.
    _olvidar_caches(client_id)

    from app.bot.cerebro import gemini

    modelo, clave = "", ""
    try:
        with tenencia.usar(client_id):
            modelo = config.GEMINI_MODELO
            clave = config.GEMINI_API_KEY or ""
            respuesta = gemini.comprobar()
            gemini.olvidar_fallo()
    except Exception as e:
        motivo = str(e)
        if clave:
            motivo = motivo.replace(clave, "(la clave)")
        print(f"[superadmin] La IA de {client_id} no respondió: {motivo}")
        return _volver_a_ficha(
            client_id, bloque="whatsapp",
            mal=f"La IA NO respondió con el modelo {modelo or '(ninguno)'}: "
                f"{motivo[:300]}")

    return _volver_a_ficha(
        client_id, bloque="whatsapp",
        ok=f"La IA respondió con el modelo {modelo}: «{respuesta[:40]}». "
           f"La clave y el modelo sirven.")


def _bloque_integraciones(client_id: int, datos: dict) -> str:
    """
    Lo que se toca una vez y no se vuelve a mirar: datos públicos,
    Google, push y marca. Por eso está detrás de una pestaña.

    Es larga, así que lleva barra fija abajo con el contador de cambios
    en vez de un botón por tarjeta: aquí se recorre entera y se guarda al
    final.
    """
    val = _val(datos)
    return f"""
      <form method="post" action="/superadmin/clientes/{client_id}"
            data-cuenta-cambios="integraciones">
        <input type="hidden" name="_bloque" value="integraciones">

        <div class="caja">
          <h2>Datos públicos del negocio</h2>
          <p class="tenue">Lo que el bot le enseña a SUS clientes. No tiene
             nada que ver con los avisos: esto se publica, aquello se
             reparte.</p>
          <div class="rejilla">
            <div>
              <label for="bwa">WhatsApp público del negocio</label>
              <input id="bwa" name="business_whatsapp_number" class="mono"
                     value="{val("business_whatsapp_number")}">
            </div>
            <div>
              <label for="bmail">Correo del negocio</label>
              <input id="bmail" name="business_email" value="{val("business_email")}">
            </div>
            <div>
              <label for="bweb">Web del negocio</label>
              <input id="bweb" name="business_website" value="{val("business_website")}">
            </div>
          </div>
        </div>

        <div class="caja">
          <h2>Google (citas y leads)</h2>
          <p class="tenue">Sin esto, este negocio no agenda citas ni registra
             leads en su hoja. El bot sigue vendiendo igual.</p>
          <div class="rejilla">
            <div>
              <label for="cal">ID del calendario</label>
              <input id="cal" name="google_calendar_id" class="mono"
                     value="{val("google_calendar_id")}">
            </div>
            <div>
              <label for="sheet">ID de la hoja de cálculo</label>
              <input id="sheet" name="google_sheets_spreadsheet_id" class="mono"
                     value="{val("google_sheets_spreadsheet_id")}">
            </div>
          </div>
          <label for="gjson">JSON de la cuenta de servicio</label>
          <textarea id="gjson" name="google_service_account_json" rows="3"
                    class="mono secreto"
                    placeholder="{_marca_secreto(datos, "google_service_account_json")}"></textarea>
          <p class="tenue">El contenido completo del archivo, no una ruta.
             Recuerda compartirle el calendario y la hoja a ese correo de
             servicio, o no podrá escribir en ellos.
             <strong>Vacío = no se toca.</strong></p>
        </div>

        <div class="caja">
          <h2>Avisos al celular (push)</h2>
          <p class="tenue">Se generan con
             <code>python scripts/push_setup.py</code>, un par por cliente.
             Sin ellas su panel no ofrece activar los avisos.</p>
          <div class="rejilla">
            <div>
              <label for="vpub">Clave pública VAPID</label>
              <input id="vpub" name="vapid_public_key" class="mono"
                     value="{val("vapid_public_key")}">
            </div>
            <div>
              <label for="vmail">Correo de contacto VAPID</label>
              <input id="vmail" name="vapid_contact_email"
                     value="{val("vapid_contact_email")}">
            </div>
          </div>
          <label for="vpriv">Clave privada VAPID</label>
          <input id="vpriv" name="vapid_private_key" type="password"
                 autocomplete="off" class="mono secreto"
                 placeholder="{_marca_secreto(datos, "vapid_private_key")}">
        </div>

        <div class="caja">
          <h2>Marca y datos</h2>
          <div class="rejilla">
            <div>
              <label for="color">Color</label>
              <input id="color" name="marca_color" value="{val("marca_color")}"
                     class="mono" placeholder="#16a34a">
              <p class="tenue">El del NEGOCIO, para su cuadrito. La
                 herramienta es de Nitro en los dos paneles.</p>
            </div>
            <div>
              <label for="historial">Días de historial que se le guardan</label>
              <input id="historial" name="historial_dias" type="number" min="0"
                     class="cifra" value="{datos.get("historial_dias") or ""}"
                     placeholder="{config.HISTORIAL_DIAS} (la política de la plataforma)">
            </div>
          </div>
          <label for="logo-archivo">Logo</label>
          <input id="logo-archivo" type="file" accept="image/png,image/jpeg,image/webp">
          <p class="tenue" id="logo-nota">Elige la imagen y se convierte
             sola. PNG con fondo transparente es lo que mejor queda.</p>
          <img id="logo-vista" alt="" hidden
               style="max-width:96px;border-radius:12px;background:var(--papel);
                      border:1px solid var(--borde);padding:6px">
          <details class="mas">
            <summary>Pegar la cadena a mano</summary>
            <div>
              <textarea id="logo" name="logo" rows="3" class="mono"
                        placeholder="data:image/png;base64,iVBORw0...">{val("logo")}</textarea>
            </div>
          </details>
          <p class="tenue">Se guarda en la base, no en un archivo: en el
             hosting no hay disco que sobreviva al despliegue. Al cambiarlo,
             quien tenga el panel instalado en el celular tiene que
             desinstalarlo y volver a añadirlo para ver el icono nuevo.</p>
        </div>

        <div class="guardar-fijo">
          <span class="contador" data-contador-de="integraciones">Sin cambios</span>
          <button type="submit">Guardar integraciones y marca</button>
        </div>
      </form>"""


def _url_publica(request: Request) -> str:
    """
    La dirección por la que se llega a este servicio desde internet.

    Se fuerza `https` salvo en local. Detrás del proxy del hosting, el
    `scheme` que ve la aplicación es `http` a menos que se lea
    `X-Forwarded-Proto`, y aquí no se puede fallar: esta URL se copia y se
    pega en el panel de Meta, que **rechaza los webhooks que no sean
    https**. Una URL mal armada aquí es un cliente que no recibe nada y un
    rato buscando el problema en el sitio equivocado.
    """
    host = request.headers.get("host", "") or request.url.netloc
    local = host.startswith("127.0.0.1") or host.startswith("localhost")
    return f"{'http' if local else 'https'}://{host}"


def _caja_meta(request: Request, client_id: int, datos: dict) -> str:
    """
    Lo que el cliente tiene que pegar en SU App de Meta, y si sus
    credenciales sirven.

    Los dos datos van en cajas de SOLO LECTURA, no en `<input readonly>`.
    No es un matiz de estilo: un cuadro de texto invita a "corregirlo", y
    cambiarle el `webhook_token` a un cliente que ya lo tiene pegado en
    Meta lo deja sin recibir mensajes sin que nada dé error. Lo que hace
    falta aquí es copiarlo, así que el único control es Copiar.
    """
    token = datos.get("webhook_token") or ""
    verify = datos.get("verify_token") or ""

    if not token:
        # Un cliente de antes del cambio de modelo. No se le inventa uno
        # aquí: pintar la ficha no debería escribir en la base, y darle una
        # URL nueva sin que nadie la pida es prometer algo que no está
        # configurado en Meta.
        return """
      <div class="caja">
        <h2>Lo que el cliente pega en su App de Meta</h2>
        <p class="tenue">Este negocio todavía no tiene URL propia de
           webhook: viene de cuando había una sola App para todos. Entra
           por <code>/webhook</code> y se seguirá atendiendo hasta que se
           le migre.</p>
      </div>"""

    url = f"{_url_publica(request)}/webhook/{token}"
    revisado = datos.get("token_revisado")
    # Sin fecha no se dice nada: el chip de al lado ya dice "sin
    # comprobar" cuando lo esta, y un "todavia sin comprobar" al lado de
    # un chip que dice "credenciales rotas" se contradice con el.
    cuando = (f'<span class="tenue">última comprobación '
              f'{html.escape(str(revisado)[:16])}</span>' if revisado else "")

    def caja_copiable(ident: str, etiqueta: str, valor: str) -> str:
        return f"""
        <div class="etiqueta-fila">
          <label>{etiqueta}</label>
          <span class="chip neutro">no editable</span>
        </div>
        <div class="solo-lectura">
          <span class="valor" id="{ident}">{html.escape(valor)}</span>
          <button type="button" class="suave mini"
                  data-copiar="{ident}">Copiar</button>
        </div>"""

    return f"""
      <div class="caja">
        <h2>Lo que el cliente pega en su App de Meta</h2>
        <p class="tenue">Estos dos datos son NUESTROS y se los das tú. Los
           pega en su App → WhatsApp → Configuración → Webhook. Hasta que lo
           haga, no le entra ni un mensaje.</p>

        {caja_copiable("url_webhook", "URL de devolución de llamada", url)}
        {caja_copiable("verify_token", "Token de verificación", verify)}

        <p class="tenue"><strong>Si cambian, el cliente deja de recibir
           mensajes sin dar error.</strong> Por eso no se editan desde
           aquí: se generan una vez, al dar de alta.</p>

        <p class="tenue">Y que se suscriba al campo <code>messages</code>.
           Sin esa casilla, Meta acepta el webhook y no le manda nunca
           nada — es el fallo que más despista, porque todo lo demás
           parece bien.</p>

        <div class="caja-pie">
          <p class="tenue">{_chip_credenciales(datos.get("token_estado") or "")}
             {cuando}<br>Probar le pregunta a Meta por el token, el número y
             el tramo de envío. Es lo que distingue "el bot está caído" de
             "el token que te dieron caduca mañana".</p>
          <form method="post" action="/superadmin/clientes/{client_id}/probar">
            <button type="submit" class="suave">Probar credenciales</button>
          </form>
        </div>
      </div>"""


def _marca_secreto(datos: dict, columna: str) -> str:
    """
    Qué poner de marcador en un campo de credencial.

    Los secretos NUNCA se pintan en el formulario. Están cifrados en la
    base, y descifrarlos para meterlos en un `value=` los dejaría en el
    HTML, en el historial del navegador y en cualquier caché por el camino.
    Se dice si hay algo guardado, y ya.

    Dejar el campo vacío = no tocar lo que hubiera. Es lo contrario que en
    los campos normales, donde vacío significa borrar, así que el
    marcador tiene que decirlo con todas las letras.
    """
    return ("guardado — escribe algo solo si quieres cambiarlo"
            if datos.get(columna) else "sin configurar")


# Las credenciales del formulario: campo → columna. Se tratan aparte del
# resto por dos motivos que no se pueden mezclar:
#
#   - Se guardan CIFRADAS (app/core/secretos.py).
#   - Vacío significa "no lo toques", no "bórralo". El formulario nunca
#     enseña el valor guardado, así que si vacío borrara, abrir la ficha y
#     darle a Guardar dejaría al cliente sin token — y sin bot.
SECRETOS_DEL_FORMULARIO = ("whatsapp_token", "app_secret", "gemini_api_key",
                           "google_service_account_json", "vapid_private_key")


# ── Los campos de la ficha, y por qué se pregunta si VINIERON ─────────
#
# Desde que hay un formulario por tarjeta, un guardado trae solo LOS
# CAMPOS DE SU TARJETA. Por eso todo lo de aquí se aplica **solo si el
# campo llegó**: `columna in formulario`, nunca `formulario.get(columna)`.
#
# La diferencia importa y no da error si se equivoca. Con `.get()`, un
# campo ausente vale "" y se guardaría como vacío: guardar la tarjeta de
# identidad borraría el phone_number_id, el número del dueño y las claves
# de Google — todo a la vez, en silencio, y el cliente dejaría de recibir
# mensajes sin que nada lo dijera.
#
# Vacío SÍ significa borrar, pero solo cuando el campo viene en el
# formulario: es la única forma de quitar un dato que ya no aplica.
CAMPOS_TEXTO = ("phone_number_id", "waba_id", "app_id", "gemini_modelo",
                "owner_phone_number", "business_whatsapp_number",
                "business_email", "business_website",
                "google_calendar_id", "google_sheets_spreadsheet_id",
                "vapid_public_key", "vapid_contact_email",
                "marca_color", "logo")

# Enteros que admiten "sin valor". `None` no es 0: en `historial_dias`
# significa "la política de la plataforma" y en `max_destinos_avisos`
# "lo que dé su plan", que son cosas distintas de un cero.
CAMPOS_ENTEROS = ("historial_dias", "max_destinos_avisos")

CAMPOS_BOOLEANOS = ("ia_activa",)


@router.post("/clientes/{client_id}")
async def guardar(request: Request, client_id: int):
    """
    Guarda una tarjeta de la ficha.

    Lee el formulario entero en vez de declarar veinte parámetros: son
    campos que se añaden y se quitan, y una firma de veinte argumentos se
    desincroniza del HTML a la primera.

    **Solo toca lo que le llega.** Cada tarjeta manda lo suyo, y lo que no
    viene se queda como estaba. Ver la nota de CAMPOS_TEXTO: es la regla
    que hace seguro haber partido el formulario gigante en siete.

    `_bloque` dice a qué pestaña volver. Sin él, guardar los avisos
    devolvería al resumen y habría que buscar otra vez dónde se estaba.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    formulario = await request.form()
    bloque = (formulario.get("_bloque") or "resumen").strip()

    def campo(nombre: str) -> str:
        return (formulario.get(nombre) or "").strip()

    def volver(mal: str):
        return _volver_a_ficha(client_id, mal=mal, bloque=bloque)

    nuevos_secretos = {}
    for columna in SECRETOS_DEL_FORMULARIO:
        if columna not in formulario:
            continue
        valor = campo(columna)
        if not valor:
            continue                      # vacío = no tocar
        if not secretos.hay_clave():
            return volver("Falta SECRETS_KEY: no se puede guardar cifrada "
                          "esa credencial, y en claro no se guarda.")
        nuevos_secretos[columna] = secretos.cifrar(valor)

    slug = campo("slug").lower() if "slug" in formulario else None
    if slug is not None:
        if not SLUG_VALIDO.match(slug) or slug in SLUGS_PROHIBIDOS:
            return volver(f"El nombre corto {slug!r} no vale: solo minúsculas, "
                          f"números y guiones, y no puede ser uno reservado.")

    if "nombre" in formulario and not campo("nombre"):
        return volver("El negocio necesita un nombre.")

    session = database.get_session()
    try:
        cliente = session.query(database.Client).filter_by(id=client_id).first()
        if cliente is None:
            return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                    status_code=303)

        # Dos cosas que no pueden repetirse entre clientes, y que si se
        # repitieran no darían error hasta el peor momento: el slug es con
        # lo que entra al panel, y el phone_number_id es con lo que el
        # webhook decide de quién es cada mensaje.
        if slug is not None:
            choque = (session.query(database.Client)
                      .filter(database.Client.id != client_id,
                              database.Client.slug == slug).first())
            if choque:
                return volver(f"Ya hay otro negocio con el nombre corto {slug!r}.")
            cliente.slug = slug

        if "phone_number_id" in formulario:
            pnid = campo("phone_number_id") or None
            if pnid:
                choque = (session.query(database.Client)
                          .filter(database.Client.id != client_id,
                                  database.Client.phone_number_id == pnid).first())
                if choque:
                    return volver(f"Ese phone_number_id ya lo usa "
                                  f"{choque.nombre!r}. Es la clave con la que "
                                  f"el webhook enruta: no puede repetirse.")

        if "nombre" in formulario:
            cliente.nombre = campo("nombre")

        # `webhook_token` y `verify_token` NO se tocan aquí, aunque sean
        # columnas del cliente: no están en ningún formulario porque el
        # cliente ya los tiene pegados en su App de Meta, y cambiarlos lo
        # deja sin recibir mensajes sin que nada dé error. Se generan una
        # vez, al dar de alta.

        for columna in CAMPOS_TEXTO:
            if columna in formulario:
                setattr(cliente, columna, campo(columna) or None)

        # El número del dueño, solo con dígitos. Es a donde va un aviso
        # cuando no hay áreas, y "+57 300 111 2233" lo rechaza Meta sin
        # decir que el problema era el formato.
        if "owner_phone_number" in formulario:
            cliente.owner_phone_number = _solo_digitos(
                campo("owner_phone_number")) or None

        for columna in CAMPOS_BOOLEANOS:
            if columna in formulario:
                setattr(cliente, columna, campo(columna) == "si")

        for columna in CAMPOS_ENTEROS:
            if columna in formulario:
                valor = campo(columna)
                setattr(cliente, columna, int(valor) if valor else None)

        if "plan" in formulario:
            elegido = campo("plan").lower()
            if elegido in planes.PLANES:
                cliente.plan = elegido
                cliente.ia_contratada = planes.PLANES[elegido].ia

        if "vence_el" in formulario:
            from datetime import date as _date
            texto = campo("vence_el")
            cliente.vence_el = _date.fromisoformat(texto) if texto else None
            cliente.recordatorio_enviado_el = None

        if "precio_mensual" in formulario:
            texto = campo("precio_mensual")
            cliente.precio_mensual = max(0, int(texto)) if texto else None

        if "ia_limite_mensual" in formulario:
            cliente.ia_limite_mensual = max(0, int(campo("ia_limite_mensual") or 0))

        for columna, cifrado in nuevos_secretos.items():
            setattr(cliente, columna, cifrado)

        # ── Las áreas de aviso ───────────────────────────────────────
        #
        # Viven en `negocio_config` con el resto del contenido del
        # negocio, pero se editan AQUÍ: son configuración, no algo que el
        # bot diga. Ver `_caja_avisos`.
        #
        # Solo se tocan si el formulario las trae, que es lo mismo que
        # decir "solo desde la pestaña de avisos". Sin esta condición,
        # guardar la tarjeta de identidad las borraría todas: el
        # formulario no las manda, `leer_destinos` devolvería una lista
        # vacía, y el negocio se quedaría avisando solo al dueño sin que
        # nada lo dijera.
        if "destino-0-correo" in formulario:
            # El cupo se lee del formulario y no de `_cupo_avisos()`: en
            # esta misma petición puede haber cambiado —le acabas de subir
            # el plan o de escribir un número— y la base todavía tiene el
            # valor viejo. Con el de la base, subir el cupo y llenar las
            # áreas nuevas en el mismo guardado recortaría justo las que se
            # acaban de escribir.
            tope_areas = campo("max_destinos_avisos")
            cupo = (int(tope_areas) if tope_areas
                    else planes.de({"plan": cliente.plan,
                                    "ia_contratada": cliente.ia_contratada}).areas)

            negocio = copy.deepcopy(cliente.negocio_config or {})
            negocio.setdefault("avisos", {})["destinos"] = (
                contenido.leer_destinos(formulario, max(1, cupo)))

            # Reasignar y no mutar en sitio: con una columna JSON,
            # SQLAlchemy no se entera de un cambio hecho dentro del
            # diccionario y el UPDATE sale sin él. Silencioso, y de los que
            # se diagnostican mirando al sitio equivocado.
            cliente.negocio_config = negocio

        session.commit()
    except ValueError:
        return volver("Los campos numéricos tienen que ser números.")
    finally:
        session.close()

    # "¿Encendida?" manda sobre lo que el dueño eligiera en su panel. La
    # columna `ia_activa` sola no bastaba: es cómo NACE, y en cuanto el
    # dueño había pulsado "Apagar" una vez, cambiarla aquí no hacía nada —
    # la ficha decía "Sí" y el bot seguía respondiendo con el menú.
    if "ia_activa" in formulario:
        from app.bot import cerebro
        from app.core import ajustes
        with tenencia.usar(client_id):
            ajustes.escribir(cerebro.AJUSTE_PLAN,
                             cerebro.PRO if campo("ia_activa") == "si"
                             else cerebro.BASICO)

    _olvidar_caches(client_id)

    aviso = "Guardado."
    if nuevos_secretos:
        aviso += f" Credenciales actualizadas: {len(nuevos_secretos)}."
    return _volver_a_ficha(client_id, ok=aviso, bloque=bloque)


# ── Los usuarios del panel ───────────────────────────────────────────
#
# Quién puede entrar al panel de un negocio. Hasta ahora esto solo se hacía
# por terminal (`scripts/panel_usuario.py`), lo que significaba que si un
# cliente perdía su clave un domingo había que sacar el portátil. La lógica
# ya estaba entera en `app/core/acceso.py`; lo que faltaba era la pantalla.
#
# El rol NO se ofrece en el formulario a propósito: la columna existe
# ("dueno" / "asesor") pero hoy no la mira nadie, así que un selector
# prometería una diferencia de permisos que no es cierta. Se enseña lo que
# hay guardado y se crea con el valor por defecto.


def _caja_usuarios(client_id: int, usuarios: list[dict],
                   entrar_en: str = "/admin/login") -> str:
    """
    La lista de quién entra a este panel, con lo que se puede hacerle.

    Todo lo de aquí es una **acción inmediata**: cambiar una clave surte
    efecto al pulsar, no al guardar. Se dice con esas palabras en la
    pantalla porque es la única pestaña donde no hay botón de guardar, y
    sin decirlo alguien escribiría una clave nueva y se iría a buscarlo.

    Y dice CÓMO se entra, con la dirección y el usuario. El 13-sep-2026 el
    dueño añadió un usuario aquí, su clave de siempre dejó de servir, y la
    pantalla no decía ni que eso pasaba ni con qué usuario se entraba
    ahora: "creo que la cambié en superadmin pero no sé dónde".
    """
    activos = [u for u in usuarios if u["active"]]
    de_baja = [u for u in usuarios if not u["active"]]

    def fila(u: dict) -> str:
        nombre = html.escape(u["email"])
        uid = u["id"]
        visto = u["ultimo_acceso"]
        visto = visto.strftime("%d/%m/%Y") if visto else "nunca entró"
        estado = ('<span class="chip morado">puede entrar</span>' if u["active"]
                  else '<span class="chip neutro">sin acceso</span>')

        # A un usuario activo le cambia la clave, y a uno de baja lo
        # devuelve con una clave nueva. Reactivar SIN clave nueva no se
        # ofrece: si se le quitó el acceso a alguien, que vuelva con la de
        # antes es justamente lo que no se quiere.
        boton_clave = "Cambiar clave" if u["active"] else "Devolverle el acceso"
        clave = f"""
            <form method="post" class="usuario-accion"
                  action="/superadmin/clientes/{client_id}/usuarios">
              <input type="hidden" name="email" value="{nombre}">
              <label>{"Clave nueva" if u["active"] else "Con esta clave nueva"}
                <input type="password" name="clave" required minlength="8"
                       autocomplete="new-password" placeholder="8 o más">
              </label>
              <button class="suave" type="submit">{boton_clave}</button>
            </form>"""

        renombrar = f"""
            <form method="post" class="usuario-accion"
                  action="/superadmin/clientes/{client_id}/usuarios/renombrar">
              <input type="hidden" name="id" value="{uid}">
              <label>Usuario
                <input name="usuario" value="{nombre}" required
                       autocomplete="off" autocapitalize="none"
                       spellcheck="false" class="mono">
              </label>
              <button class="suave" type="submit">Cambiar usuario</button>
            </form>"""

        # Quitar el acceso al ÚLTIMO dejaría al negocio fuera de su propio
        # panel. Se dice en vez de esconder el botón: un botón que falta no
        # explica nada, y "¿cómo le quito el acceso?" era la pregunta.
        if u["active"] and len(activos) > 1:
            quitar = f"""
            <form method="post"
                  action="/superadmin/clientes/{client_id}/usuarios/baja">
              <input type="hidden" name="email" value="{nombre}">
              <button class="peligro" type="submit">Quitar acceso</button>
            </form>"""
        elif u["active"]:
            quitar = ('<p class="tenue">Es el único que puede entrar: añade '
                      'otro usuario antes de quitarle el acceso.</p>')
        else:
            # Borrar solo a quien ya no tiene acceso: dos pasos para lo que
            # no tiene vuelta atrás.
            # La pregunta va como JSON dentro del atributo: el nombre de
            # usuario es texto libre, y metido entre comillas simples a
            # mano, una comilla en el nombre cerraba la cadena de JS.
            pregunta = html.escape(json.dumps(
                f"¿Borrar a {u['email']} para siempre? Su nombre de "
                f"usuario queda libre.", ensure_ascii=False))
            quitar = f"""
            <form method="post"
                  action="/superadmin/clientes/{client_id}/usuarios/borrar"
                  onsubmit="return confirm({pregunta})">
              <input type="hidden" name="id" value="{uid}">
              <button class="peligro" type="submit">Borrar para siempre</button>
            </form>"""

        return f"""
        <div class="caja-interna">
          <div class="area-cabecera">
            <h3 class="mono">{nombre}</h3>{estado}
            <span class="tenue">{html.escape(u["rol"])} · {visto}</span>
          </div>
          <div class="usuario-acciones">
            {renombrar}
            {clave}
          </div>
          <div class="fila-acciones" style="justify-content:flex-start">
            {quitar}
          </div>
        </div>"""

    entrar_en = html.escape(entrar_en)

    como_se_entra = f"""
        <div class="banda ok"><strong>Cómo se entra:</strong>
          <span class="mono">{entrar_en}</span> → <strong>Usuario</strong>
          (el nombre de la lista) y su <strong>clave</strong>. La clave no se
          puede ver: si nadie la recuerda, pon una nueva aquí abajo.</div>"""

    # La trampa que dejó al dueño fuera: el cliente por defecto entra con la
    # clave del servidor MIENTRAS no tenga usuarios, y deja de poder en
    # cuanto se crea el primero. Ver `acceso._rampa`.
    rampa = ""
    if client_id == database.CLIENTE_POR_DEFECTO and config.ADMIN_API_KEY:
        rampa = ("""
        <div class="banda avisa"><strong>La clave del servidor ya no abre este
          panel.</strong> Mientras no tenía usuarios se entraba con
          <code>ADMIN_API_KEY</code>; en cuanto se crea el primero, deja de
          servir y solo entran los de esta lista.</div>""" if activos else """
        <div class="banda avisa"><strong>Hoy se entra con la clave del
          servidor</strong> (<code>ADMIN_API_KEY</code>), sin usuario. En
          cuanto añadas el primer usuario, esa clave <strong>deja de
          servir</strong> y solo entran los de esta lista.</div>""")

    # Sin usuarios pero con la rampa puesta SÍ se puede entrar: decir
    # "nadie puede entrar" al lado de "hoy se entra con la clave del
    # servidor" son dos bandas que se contradicen.
    aviso = "" if activos or rampa else (
        '<div class="banda mal"><strong>Nadie puede entrar.</strong> Este '
        'negocio no tiene ningún usuario con acceso.</div>')

    lista_baja = ""
    if de_baja:
        lista_baja = f"""
        <details class="interno">
          <summary>Sin acceso ({len(de_baja)})</summary>
          {"".join(fila(u) for u in de_baja)}
        </details>"""

    return f"""
      <div class="caja">
        <h2>Usuarios del panel</h2>
        <p class="tenue">Quién puede entrar al panel de este negocio. El
           usuario es lo que se escribe al entrar: un correo, un nombre o lo
           que quieras, y es único en toda la plataforma.</p>
        {como_se_entra}
        {rampa}
        <div class="banda avisa"><strong>Acciones inmediatas:</strong> no
          dependen de ningún botón de guardar. Lo que se pulse aquí surte
          efecto al momento.</div>
        {aviso}
        {"".join(fila(u) for u in activos)}
        {lista_baja}
      </div>

      <div class="caja">
        <h2>Añadir un usuario</h2>
        <form method="post" action="/superadmin/clientes/{client_id}/usuarios">
          <div class="rejilla">
            <div>
              <label for="nuevo-email">Usuario</label>
              <input id="nuevo-email" name="email" required class="mono"
                     autocomplete="off" autocapitalize="none" spellcheck="false"
                     placeholder="nico, caja-2 o alguien@negocio.com">
              <p class="tenue">Lo que escribirá al entrar. Sin distinguir
                 mayúsculas.</p>
            </div>
            <div>
              <label for="nuevo-clave">Su clave</label>
              <input id="nuevo-clave" name="clave" type="password" required
                     minlength="8" autocomplete="new-password">
              <p class="tenue">8 caracteres o más. Si ese usuario ya está en
                 este negocio, esto le cambia la clave en vez de duplicarlo.</p>
            </div>
          </div>
          <div class="caja-pie">
            <button type="submit" class="guardar-caja">Añadir usuario</button>
          </div>
        </form>
      </div>"""


def _direccion_de_entrada(request: Request, datos: dict) -> str:
    """
    Dónde entra este negocio a su panel, tal como hay que dictárselo.

    Con subdominios es el suyo; sin ellos, la misma dirección desde la que
    se está mirando esta consola, que es la del despliegue.
    """
    dominio = tenencia.dominio_base()
    if dominio and datos.get("slug"):
        return f"https://{datos['slug']}.{dominio}/admin/login"
    return f"{request.url.scheme}://{request.url.netloc}/admin/login"


def _volver_a_ficha(client_id: int, ok: str = "", mal: str = "",
                    bloque: str = ""):
    """
    De vuelta a la ficha, a LA MISMA pestaña de la que se salió.

    Sin el bloque, cada guardado devolvería al resumen y habría que
    volver a buscar dónde se estaba. Con siete pestañas eso deja de ser
    un detalle.
    """
    from urllib.parse import quote_plus
    partes = [f"ok={quote_plus(ok)}" if ok else f"mal={quote_plus(mal)}"]
    if bloque:
        partes.append(f"bloque={quote_plus(bloque)}")
    return RedirectResponse(
        f"/superadmin/clientes/{client_id}?{'&'.join(partes)}", status_code=303)


def _cliente_existe(client_id: int) -> bool:
    session = database.get_session()
    try:
        return bool(session.query(database.Client)
                    .filter_by(id=client_id).first())
    finally:
        session.close()


@router.post("/clientes/{client_id}/pago")
async def registrar_pago(request: Request, client_id: int):
    """Anota un pago: corre el vencimiento un mes, y reactiva si hace falta."""
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    from app.core import cobros

    formulario = await request.form()
    texto = (formulario.get("monto") or "").strip()
    try:
        monto = max(0, int(texto)) if texto else None
        nuevo = cobros.registrar_pago(client_id, monto)
    except ValueError as e:
        return _volver_a_ficha(client_id, mal=f"No se registró: {e}")
    _olvidar_caches(client_id)
    aviso = f"Pago registrado. Queda pagado hasta el {cobros.fecha_en_palabras(nuevo)}."
    # Se puede registrar desde la ficha, desde Hoy y desde Cobros: se
    # vuelve a donde se estaba, que es donde se sigue trabajando.
    volver = (formulario.get("volver") or "").strip()
    if volver in ("hoy", "cobros"):
        destino = "/superadmin" if volver == "hoy" else "/superadmin/cobros"
        return RedirectResponse(f"{destino}?ok={quote_plus(aviso)}", status_code=303)
    return _volver_a_ficha(client_id, ok=aviso)


@router.post("/clientes/{client_id}/probar")
def probar_credenciales(request: Request, client_id: int):
    """
    Le pregunta a Meta si las credenciales de este cliente sirven.

    Guarda el resultado en `token_estado` para que se vea en el listado
    sin tener que entrar a cada ficha: con veinte clientes, lo que hace
    falta es barrer de un vistazo quién está roto, no comprobar de uno en
    uno.

    Escribe en la base aunque falle. Un "falla" es tan informativo como un
    "va bien", y no guardarlo dejaría al listado diciendo "sin comprobar"
    justo del cliente que sí se comprobó.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    session = database.get_session()
    try:
        cliente = session.query(database.Client).filter_by(id=client_id).first()
        if cliente is None:
            return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                    status_code=303)

        # Se descifra aquí y no se pasa la fila entera: lo que necesita
        # `meta_estado` son cinco cadenas, y cuanto menos viaje una
        # credencial descifrada, mejor.
        token = secretos.descifrar(cliente.whatsapp_token or "")
        app_secret = secretos.descifrar(cliente.app_secret or "")
        app_id = cliente.app_id or ""
        pnid = cliente.phone_number_id or ""
        waba = cliente.waba_id or ""
    finally:
        session.close()

    from app.integrations import meta_estado
    resultado = meta_estado.revisar(token, app_id, app_secret, pnid, waba)

    session = database.get_session()
    try:
        session.query(database.Client).filter_by(id=client_id).update({
            "token_estado": resultado["estado"],
            "token_revisado": database.ahora_utc(),
        })
        session.commit()
    finally:
        session.close()

    _olvidar_caches(client_id)

    resumen = " · ".join(
        f"{x['titulo']}{' — ' + x['detalle'] if x['detalle'] else ''}"
        for x in resultado["lineas"])

    # A la pestana de WhatsApp cuando falla, y no al resumen: el motivo
    # real solo sirve al lado del campo que hay que cambiar. En el
    # resumen seria un texto rojo sin nada que hacer con el.
    if resultado["estado"] == meta_estado.OK:
        return _volver_a_ficha(client_id, ok=resumen)
    return _volver_a_ficha(client_id, mal=resumen, bloque="whatsapp")


@router.post("/clientes/{client_id}/probar-avisos")
async def probar_avisos(request: Request, client_id: int):
    """
    Manda un aviso de prueba a cada área y dice qué pasó con cada una.

    PRUEBA LO QUE HAY EN PANTALLA, no lo guardado. El botón vive dentro del
    formulario de la ficha, así que llegan los números tal como están
    escritos ahora mismo — se puede probar un número antes de guardarlo, y
    no hay forma de creer que se está probando lo nuevo mientras se prueba
    lo viejo.

    Va con `tenencia.usar()` porque el envío usa el token y el número de
    ESE negocio: sin fijar el inquilino, `/superadmin` corre sin ninguno y
    los mensajes saldrían por el número del bot de casa (ver el docstring
    del módulo).
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    if not _cliente_existe(client_id):
        return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                status_code=303)

    from app.bot import notificaciones

    formulario = await request.form()
    cupo = _cupo_avisos(client_id)
    destinos = contenido.leer_destinos(formulario, cupo)

    if not destinos:
        # Sin áreas escritas, se prueba el número del dueño, que es a donde
        # iría todo en ese caso.
        dueno = _solo_digitos(formulario.get("owner_phone_number"))
        if dueno:
            destinos = [{"nombre": "Dueño", "numero": dueno, "opciones": []}]

    try:
        with tenencia.usar(client_id):
            resultados = notificaciones.probar_destinos(destinos)
    except Exception as e:
        return _volver_a_ficha(client_id, mal=f"No se pudo probar: {e}",
                               bloque="avisos")

    if not resultados:
        return _volver_a_ficha(
            client_id, bloque="avisos",
            mal="No hay ningún número al que avisar: ni áreas ni número del "
                "dueño. Un lead de este negocio no le llegaría a nadie.")

    partes = []
    for area, numero, ok, explica in resultados:
        quien = f"{area} ({numero})" if area else numero
        partes.append(f"{'OK' if ok else 'FALLA'} · {quien}: {explica}")

    resumen = " | ".join(partes)

    if all(ok for _, _, ok, _ in resultados):
        return _volver_a_ficha(client_id, ok=resumen, bloque="avisos")
    return _volver_a_ficha(client_id, mal=resumen, bloque="avisos")


@router.post("/clientes/{client_id}/usuarios")
def usuario_guardar(request: Request, client_id: int,
                    email: str = Form(...), clave: str = Form(...)):
    """
    Da de alta a alguien en el panel de un negocio, o le cambia la clave.

    Las dos cosas son la misma llamada (`acceso.crear_usuario`): si el
    correo ya está, le cambia la clave y lo reactiva. Es lo que hace falta
    el día que un cliente llama diciendo que no puede entrar.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    email = acceso.normalizar_usuario(email)
    if not email:
        return _volver_a_ficha(client_id, mal="Hace falta un nombre de usuario.",
                               bloque="usuarios")
    if len(clave) < 8:
        return _volver_a_ficha(
            client_id, bloque="usuarios",
            mal="La clave del panel necesita 8 caracteres o más.")
    if not _cliente_existe(client_id):
        return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                status_code=303)

    ya_estaba = any(u["email"] == email
                    for u in acceso.listar_usuarios(client_id))
    try:
        acceso.crear_usuario(client_id, email, clave)
    except ValueError as e:
        return _volver_a_ficha(client_id, mal=str(e), bloque="usuarios")

    accion = "Clave cambiada" if ya_estaba else "Usuario creado"
    print(f"[superadmin] {accion} para {email} en el cliente {client_id}.")
    return _volver_a_ficha(client_id, ok=f"{accion}: {email}.",
                           bloque="usuarios")


@router.post("/clientes/{client_id}/usuarios/baja")
def usuario_baja(request: Request, client_id: int, email: str = Form(...)):
    """
    Le quita el acceso a alguien. No borra la fila: así queda constancia de
    que ese correo estuvo dentro.

    Su sesión en curso sigue viva hasta que caduque (ver `acceso.leer_pase`),
    que son horas, no días. Si hay prisa de verdad, la palanca inmediata es
    pausar el negocio.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    email = (email or "").strip().lower()
    activos = [u for u in acceso.listar_usuarios(client_id) if u["active"]]

    # El último acceso no se da de baja desde aquí: dejaría al negocio
    # fuera de su propio panel sin que nadie lo pidiera. Lo que se quiere
    # cuando alguien no paga es pausarlo, que además le corta el bot.
    if len(activos) <= 1 and any(u["email"] == email for u in activos):
        return _volver_a_ficha(
            client_id, bloque="usuarios",
            mal="Es el único acceso que le queda a este negocio. Crea otro "
                "usuario antes de darlo de baja, o pausa el negocio entero.")

    if not acceso.desactivar_usuario(client_id, email):
        return _volver_a_ficha(client_id, bloque="usuarios",
                               mal=f"Ese negocio no tiene ningún {email}.")

    print(f"[superadmin] {email} dado de baja en el cliente {client_id}.")
    return _volver_a_ficha(client_id, ok=f"{email} ya no puede entrar.",
                           bloque="usuarios")


@router.post("/clientes/{client_id}/usuarios/renombrar")
def usuario_renombrar(request: Request, client_id: int,
                      id: int = Form(...), usuario: str = Form(...)):
    """Le cambia el nombre de usuario a alguien, sin tocar su clave."""
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    try:
        nuevo = acceso.renombrar_usuario(client_id, id, usuario)
    except ValueError as e:
        return _volver_a_ficha(client_id, mal=str(e), bloque="usuarios")

    print(f"[superadmin] usuario {id} del cliente {client_id} → {nuevo}.")
    return _volver_a_ficha(
        client_id, bloque="usuarios",
        ok=f"Ahora entra con el usuario «{nuevo}» y la misma clave.")


@router.post("/clientes/{client_id}/usuarios/borrar")
def usuario_borrar(request: Request, client_id: int, id: int = Form(...)):
    """
    Borra para siempre a alguien que ya no tiene acceso.

    Solo a los de baja (`acceso.borrar_usuario`): a quien todavía puede
    entrar primero se le quita el acceso, que se deshace; borrar no.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    if not acceso.borrar_usuario(client_id, id):
        return _volver_a_ficha(
            client_id, bloque="usuarios",
            mal="Solo se borra a quien ya no tiene acceso. Quítaselo primero.")

    print(f"[superadmin] usuario {id} del cliente {client_id} borrado.")
    return _volver_a_ficha(client_id, ok="Usuario borrado.", bloque="usuarios")


# ── El contenido: textos, menú, enlaces y precios ────────────────────

def _contenido_de(client_id: int):
    """
    La configuración de contenido de un negocio, y su fila.

    Si todavía no tiene la suya, se parte del `negocio.toml` del
    repositorio: es la plantilla, y así el editor abre con algo que
    funciona en vez de con una página en blanco. Al guardar, ese cliente
    pasa a tener contenido propio — y con eso deja de leer variables de
    entorno del proceso (ver `config_cliente`).
    """
    session = database.get_session()
    try:
        cliente = session.query(database.Client).filter_by(id=client_id).first()
        if cliente is None:
            return None, None
        return cliente.nombre, copy.deepcopy(
            cliente.negocio_config or leer_negocio_toml())
    finally:
        session.close()


@router.get("/clientes/{client_id}/contenido", response_class=HTMLResponse)
def contenido_form(request: Request, client_id: int, mal: str = "", ok: str = ""):
    """
    El editor de contenido: índice fijo a la izquierda, bloques a la
    derecha.

    Sin el índice, llegar a "Horario" es bajar por encima de treinta y
    cuatro textos y de todo el menú. Es una página de dos metros y el
    índice es lo único que la convierte en algo que se recorre.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    nombre, negocio = _contenido_de(client_id)
    if negocio is None:
        return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                status_code=303)

    banda = ""
    if ok:
        banda = f'<div class="banda ok">{html.escape(ok)}</div>'
    elif mal:
        banda = f'<div class="banda mal">{html.escape(mal)}</div>'

    cabecera = _cabecera(
        f"Contenido de {html.escape(nombre)}",
        resumen='La letra pequeña: horario, textos de las citas, precios.',
        acciones=f'<a class="volver" href="/superadmin/clientes/{client_id}">'
                 f'← volver a la ficha</a>')

    cuerpo = f"""
      {banda}
      <div class="editor-columnas">
        <nav class="indice">
          {contenido.indice(negocio)}
          <div class="separador">
            <a href="/superadmin/clientes/{client_id}/contenido.json" download>
              Descargar una copia</a>
          </div>
        </nav>

        <form method="post" action="/superadmin/clientes/{client_id}/contenido"
              data-cuenta-cambios="contenido">
          {contenido.pintar(negocio, _cupo_avisos(client_id))}
          <div class="guardar-fijo">
            <span class="contador" data-contador-de="contenido">Sin cambios</span>
            <button type="submit">Guardar contenido</button>
            <p class="aviso"><strong>Se valida entero:</strong> si una opción
               apunta a un enlace que no existe, no se guarda nada. Lo peor
               que puede pasar es que no te deje guardar — nunca que el bot
               se quede diciendo algo roto.</p>
          </div>
        </form>
      </div>"""

    return HTMLResponse(_pantalla(
        f"Contenido · {nombre}", cabecera, cuerpo, activo="clientes",
        pestanas=_pestanas_ficha(client_id, "contenido"), ayuda="contenido",
        guiones=("superadmin-contenido.js",)))


@router.get("/clientes/{client_id}/contenido.json")
def contenido_copia(request: Request, client_id: int):
    """
    El contenido de un negocio, tal cual está guardado, como archivo.

    Es el "deshacer" del editor, y a propósito el más barato: la validación
    impide guardar algo ROTO, pero no devuelve un texto que se borró sin
    querer. Con la copia del día anterior a mano, eso se arregla pegando.

    Un historial de versiones sería lo bonito. Sería también otra tabla,
    otra pantalla y una decisión de cuánto guardar; esto son diez líneas y
    cubre el caso que duele.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    nombre, negocio = _contenido_de(client_id)
    if negocio is None:
        return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                status_code=303)

    dia = database.ahora_utc().strftime("%Y-%m-%d")
    session = database.get_session()
    try:
        cliente = session.query(database.Client).filter_by(id=client_id).first()
        slug = cliente.slug if cliente else str(client_id)
    finally:
        session.close()

    return JSONResponse(negocio, headers={
        "Content-Disposition":
            f'attachment; filename="contenido-{slug}-{dia}.json"'})


@router.post("/clientes/{client_id}/contenido")
async def contenido_guardar(request: Request, client_id: int):
    """
    Guarda el contenido, y **solo si es válido**.

    La validación no es un extra: es lo que hace que se le pueda dar esto
    a alguien que no programa. Armar una `ConfiguracionCliente` es lo mismo
    que revienta el arranque con un `negocio.toml` roto, así que aquí caza
    exactamente los mismos errores — una opción que nombra un enlace
    inexistente, un bloque de precios que no está— antes de escribir nada.
    """
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    nombre, actual = _contenido_de(client_id)
    if actual is None:
        return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                status_code=303)

    formulario = await request.form()
    nuevo = contenido.leer(formulario, actual, _cupo_avisos(client_id))

    from urllib.parse import quote_plus

    if not nuevo.get("menu"):
        return RedirectResponse(
            f"/superadmin/clientes/{client_id}/contenido?"
            f"mal={quote_plus('El menú no puede quedarse vacío: es lo que el bot ofrece.')}",
            status_code=303)

    try:
        ConfiguracionCliente(fila={"id": client_id, "nombre": nombre},
                             negocio=nuevo)
    except Exception as e:
        return RedirectResponse(
            f"/superadmin/clientes/{client_id}/contenido?"
            f"mal={quote_plus(f'No se guardó nada. {e}')}",
            status_code=303)

    session = database.get_session()
    try:
        session.query(database.Client).filter_by(id=client_id).update(
            {"negocio_config": nuevo})
        session.commit()
    finally:
        session.close()

    _olvidar_caches(client_id)

    print(f"[superadmin] Contenido del cliente {client_id} actualizado.")
    return RedirectResponse(
        f"/superadmin/clientes/{client_id}/contenido?"
        f"ok={quote_plus('Guardado. Ya está en vivo: el próximo mensaje usa esto.')}",
        status_code=303)


# ── El mapa de la conversación ───────────────────────────────────────
#
# La misma configuración que el editor de contenido, vista como el árbol
# que es. Ver `app/web/mapa.py` para el porqué.

# Lo que el mapa administra. El resto del contenido —horario, IA, avisos,
# las pestañas del Sheet, los orígenes— NO viaja en el formulario y por
# tanto no se toca al guardar. Es la misma regla que sostiene
# `contenido.leer`, y sin ella guardar una vez borraría lo que no se ve.
SECCIONES_DEL_MAPA = ("textos", "menu", "enlaces", "precios",
                      "variables", "ia")

# `conversacion` va aparte porque el mapa solo toca UNA de sus claves
# (`pedir_nombre`) y las demás —los plazos, las palabras que piden
# asesor— se editan en el contenido completo. Pisarla entera borraría
# esas otras sin que nadie se enterara hasta que un cliente escribiera
# "asesor" y el bot no reaccionara.
SECCION_MEZCLADA = "conversacion"


def _sin_retornos(valor):
    """
    Los saltos de línea, todos en `\\n`, por todo el mapa.

    Lo que se escribe en el editor ya llega bien —el navegador devuelve
    `\\n` al leer un cuadro de texto—, pero un texto PEGADO desde Word o
    desde el Bloc de notas trae `\\r\\n`, y ese `\\r` acaba dentro del
    mensaje que se manda por WhatsApp: no se ve, no da error, y no hay
    forma de quitarlo desde la pantalla.

    Los espacios y las líneas en blanco NO se tocan: son parte de lo que
    se quiso escribir. Ver `contenido._como_se_escribio`.
    """
    if isinstance(valor, str):
        return valor.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(valor, list):
        return [_sin_retornos(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _sin_retornos(v) for k, v in valor.items()}
    return valor


@router.get("/clientes/{client_id}/mapa", response_class=HTMLResponse)
def mapa_form(request: Request, client_id: int, ok: str = "", mal: str = ""):
    if not acceso.super_habilitado():
        return _sin_clave()
    if not _entrada_valida(request):
        return _login()

    nombre, negocio = _contenido_de(client_id)
    if negocio is None:
        return RedirectResponse("/superadmin?mal=Ese+negocio+no+existe.",
                                status_code=303)

    banda = ""
    if ok:
        banda = f'<div class="banda ok">{html.escape(ok)}</div>'
    elif mal:
        banda = f'<div class="banda mal">{html.escape(mal)}</div>'

    # ¿Este negocio ya tiene contenido propio, o está leyendo el archivo
    # del repositorio? Es la diferencia entre que guardar surta efecto o
    # no, así que la pantalla lo dice.
    session = database.get_session()
    try:
        fila = session.query(database.Client).filter_by(id=client_id).first()
        tiene_propio = bool(fila and fila.negocio_config)
    finally:
        session.close()

    cabecera = _cabecera(
        f"Mapa de {html.escape(nombre)}",
        resumen='El recorrido que vive el cliente: saludo, menú y cada rama.',
        acciones=f'<a class="volver" href="/superadmin/clientes/{client_id}">'
                 f'← volver a la ficha</a>')

    return HTMLResponse(_pantalla(
        f"Mapa · {nombre}", cabecera,
        banda + mapa.pintar(negocio, client_id, nombre, tiene_propio),
        activo="clientes", pestanas=_pestanas_ficha(client_id, "mapa"),
        ayuda="mapa"))


@router.post("/clientes/{client_id}/mapa")
async def mapa_guardar(request: Request, client_id: int):
    """
    Guarda el mapa. Responde JSON porque lo llama el propio editor.

    Se valida ARMANDO la configuración entera antes de escribir, igual que
    el editor de contenido: si una opción apunta a un enlace que no
    existe, o el menú tiene dos opciones con el mismo id, no se guarda
    nada. Es lo que hace seguro dejar esto en manos de quien no programa —
    lo peor que puede pasar es que no le deje guardar.
    """
    if not acceso.super_habilitado():
        return JSONResponse({"ok": False, "error": "deshabilitado"},
                            status_code=503)
    if not _entrada_valida(request):
        return JSONResponse({"ok": False, "error": "no autorizado"},
                            status_code=401)

    nombre, actual = _contenido_de(client_id)
    if actual is None:
        return JSONResponse({"ok": False, "error": "Ese negocio no existe."},
                            status_code=404)

    try:
        enviado = await request.json()
    except Exception:
        enviado = None
    if not isinstance(enviado, dict):
        return JSONResponse({"ok": False, "error": "El mapa llegó ilegible."},
                            status_code=400)

    return JSONResponse(guardar_mapa(client_id, nombre, actual, enviado))


def guardar_mapa(client_id: int, nombre: str, actual: dict, enviado: dict,
                 secciones: tuple = SECCIONES_DEL_MAPA) -> dict:
    """
    Aplica lo que mandó el editor del mapa y lo guarda, SOLO si es válido.

    Devuelve lo que el editor espera: `{"ok": True, ...}` o `{"ok": False,
    "error", "donde", "ruta"}`. Es la única puerta de guardado del mapa, y
    la usan el super-admin y el dueño desde su panel
    (`app/web/panel_bot.py`): los dos pasan por las mismas validaciones, así
    que ninguno puede dejar el bot diciendo algo roto.

    `secciones` son las que se aceptan del formulario: al dueño de un plan
    sin IA no se le toma la de la IA.
    """
    enviado = _sin_retornos(enviado)

    nuevo = copy.deepcopy(actual)
    for seccion in secciones:
        if seccion in enviado:
            nuevo[seccion] = enviado[seccion]

    if isinstance(enviado.get(SECCION_MEZCLADA), dict):
        mezcla = dict(nuevo.get(SECCION_MEZCLADA) or {})
        mezcla.update(enviado[SECCION_MEZCLADA])
        nuevo[SECCION_MEZCLADA] = mezcla

    # Una opción que trae su propio texto o su propio enlace se queda sin
    # el puntero al bloque compartido. Lo hace también el editor al
    # escribir, pero se repite aquí a propósito: una pestaña vieja en el
    # navegador de alguien mandaría los dos, y el resultado sería un
    # cambio guardado que no se usa. Ya pasó.
    def _quitar_punteros(opciones):
        for opcion in opciones or []:
            if not isinstance(opcion, dict):
                continue
            if (opcion.get("mensaje") or "").strip():
                opcion.pop("precios", None)
            if (opcion.get("url") or "").strip():
                opcion.pop("enlace", None)
            _quitar_punteros(opcion.get("submenu"))

    _quitar_punteros(nuevo.get("menu"))

    # `donde` y `ruta` son lo que convierte "no se guardó" en "no se
    # guardó, y es ESTE botón": el editor abre ese paso solo. Ver
    # `_revisar_mapa`.
    fallo, donde, ruta = _revisar_mapa(nuevo)
    if fallo:
        return {"ok": False, "error": fallo, "donde": donde, "ruta": ruta}

    try:
        ConfiguracionCliente(fila={"id": client_id, "nombre": nombre},
                             negocio=nuevo)
    except Exception as e:
        # El respaldo: lo que `_revisar_mapa` no supo ver. Su mensaje
        # nombra la opción por su identificador, que no sale en ninguna
        # pantalla, así que se busca a qué paso corresponde para poder
        # llevar allí igualmente.
        donde, ruta = _donde_esta(nuevo, str(e))
        return {"ok": False, "error": str(e), "donde": donde, "ruta": ruta}

    session = database.get_session()
    try:
        session.query(database.Client).filter_by(id=client_id).update(
            {"negocio_config": nuevo})
        session.commit()
    finally:
        session.close()

    _olvidar_caches(client_id)

    # Se relee DE LA BASE lo que quedó, en vez de responder con lo que se
    # acaba de mandar. Un "guardado" que solo repite lo que le dijeron no
    # prueba nada: si algo no llegó a escribirse, se ve aquí.
    session = database.get_session()
    try:
        guardado = (session.query(database.Client)
                    .filter_by(id=client_id).first().negocio_config) or {}
    finally:
        session.close()

    opciones = len(guardado.get("menu") or [])
    textos = len(guardado.get("textos") or {})
    saludo = (guardado.get("textos") or {}).get("bienvenida", "")

    print(f"[superadmin] Mapa del cliente {client_id} actualizado "
          f"({opciones} opciones, {textos} textos).")
    return {"ok": True, "opciones": opciones, "textos": textos,
            "saludo": saludo[:80]}


def _donde_esta(negocio: dict, mensaje: str):
    """
    A qué paso del mapa se refiere un error que solo nombra un id.

    Es para los errores de `ConfiguracionCliente`, que hablan de
    `la opción 'taladro_percutor'` — un identificador que el dueño no ve
    en ninguna pantalla. Se busca ese id en el árbol y se devuelve el
    mismo `(donde, ruta)` que da `_revisar_mapa`, así el editor puede
    llevar hasta él igual que con los demás.

    Si no se reconoce ningún id, se devuelve vacío: el mensaje se enseña
    tal cual, que es lo que pasaba siempre.
    """
    encontrado = ["", []]

    def buscar(opciones, sendero, ruta):
        for i, opcion in enumerate(opciones or []):
            if not isinstance(opcion, dict):
                continue
            aqui = ruta + [i]
            nombre = _nombre_de_paso(opciones, i)
            camino = " → ".join(sendero + [nombre])
            ident = (opcion.get("id") or "").strip()
            if ident and f"'{ident}'" in mensaje:
                encontrado[0], encontrado[1] = camino, aqui
                return True
            if buscar(opcion.get("submenu"), sendero + [nombre], aqui):
                return True
        return False

    buscar(negocio.get("menu"), ["El menú"], [])
    return encontrado[0], encontrado[1]


def _nombre_de_paso(lista: list, i: int) -> str:
    """
    Cómo se llama ese paso EN LA PANTALLA: "Botón 2 · Servicios".

    Tiene que decir exactamente lo que está escrito en la tarjeta del
    árbol, porque es lo que va a buscar con los ojos quien lea el error.
    Es la misma cuenta que hace `superadmin-mapa.js:tituloDePaso`, y si
    una cambia hay que cambiar la otra: un error que nombra un botón que
    en pantalla se llama de otra forma manda a buscar donde no es.
    """
    visibles = [o for o in lista if isinstance(o, dict) and not o.get("oculta")]
    que = "Fila" if len(visibles) > mapa.MAX_BOTONES else "Botón"
    titulo = ""
    if isinstance(lista[i], dict):
        titulo = (lista[i].get("title") or "").strip()
    return f"{que} {i + 1} · {titulo or '(sin texto)'}"


def _revisar_mapa(negocio: dict):
    """
    Lo que `ConfiguracionCliente` no puede cazar por sí sola.

    Un menú vacío **sí se permite**: un negocio nuevo nace en blanco y hay
    que poder guardarlo a medias mientras se arma. Lo que no se permite es
    lo que rompería una conversación de verdad.

    Devuelve `(motivo, donde, ruta)`:

        motivo   qué pasa, en una frase
        donde    el recorrido hasta el paso, como se lee en pantalla
        ruta     los índices de ese paso, para que el editor lo ABRA

    Los tres, vacíos, si todo está bien.

    ⚠️  **Un error tiene que decir DÓNDE está.** Antes decía solo qué
    pasaba —"'Ver un ejemplo' abre más opciones pero está vacía"— y con un
    menú de tres niveles eso deja al dueño abriendo pasos uno por uno
    buscando cuál es. Peor: dos botones pueden llamarse igual en ramas
    distintas. Por eso `ruta` viaja en la respuesta y el editor abre el
    paso solo (ver `guardar()` en `superadmin-mapa.js`); el texto de
    `donde` es para leerlo, la `ruta` es para llegar.
    """
    vistos = {}

    def recorrer(opciones, sendero, ruta):
        opciones = opciones or []
        for i, opcion in enumerate(opciones):
            aqui = ruta + [i]

            if not isinstance(opcion, dict):
                camino = " → ".join(sendero + [f"el paso {i + 1}"])
                return "Hay un paso que no es un paso.", camino, aqui

            nombre = _nombre_de_paso(opciones, i)
            camino = " → ".join(sendero + [nombre])

            ident = (opcion.get("id") or "").strip()
            if not ident:
                return "Se quedó sin identificador.", camino, aqui

            # Los ids son ÚNICOS en todo el árbol, no por rama: el bot
            # busca la opción que tocó el cliente sin recordar dónde
            # estaba (bot_logic._opcion_elegida). Dos iguales harían que
            # una de las dos no se pudiera pulsar nunca.
            if ident in vistos:
                return (f"Tiene el mismo identificador ('{ident}') que "
                        f"«{vistos[ident]}», y el bot no podría distinguir "
                        f"cuál pulsó el cliente. Cámbiale el título a uno "
                        f"de los dos.", camino, aqui)
            vistos[ident] = camino

            if not (opcion.get("title") or "").strip():
                return ("No tiene texto en el botón, así que el cliente "
                        "vería un botón en blanco.", camino, aqui)

            # El tope depende de CÓMO le llegue: un botón admite 20
            # caracteres y una fila de lista 24. No es un detalle — con un
            # botón pasado, Meta **rechaza el mensaje entero** y el
            # cliente no recibe nada, ni el texto que lo acompañaba. Antes
            # aquí se pedían 24 siempre, así que un botón de 22 pasaba la
            # revisión y luego dejaba mudo al bot.
            de_lista = len([o for o in opciones
                            if isinstance(o, dict) and not o.get("oculta")]) > mapa.MAX_BOTONES
            tope = 24 if de_lista else 20
            if len(opcion["title"]) > tope:
                como = "una fila de lista" if de_lista else "un botón"
                return (f"Su texto tiene {len(opcion['title'])} caracteres y "
                        f"le llega como {como}, que admite {tope}. Pasado "
                        f"eso WhatsApp rechaza el mensaje entero y el "
                        f"cliente no recibe nada.", camino, aqui)

            accion = opcion.get("accion")
            if accion not in mapa.ACCIONES_VALIDAS:
                return (f"Tiene una acción que el bot no entiende "
                        f"({accion!r}).", camino, aqui)

            if accion == "submenu" and not opcion.get("submenu"):
                return ("Abre más opciones pero está vacía: el cliente "
                        "pulsaría y no recibiría nada.", camino, aqui)

            # Los punteros a los bloques compartidos. Los valida también
            # `ConfiguracionCliente`, pero allí el mensaje solo sabe el
            # identificador de la opción —y el dueño no ve identificadores
            # en ninguna pantalla—. Aquí se caza antes, con su sitio.
            enlace = opcion.get("enlace")
            if enlace and enlace not in (negocio.get("enlaces") or {}):
                return (f"Pide el enlace '{enlace}', que ya no existe en "
                        f"tus enlaces compartidos.", camino, aqui)

            precios = opcion.get("precios")
            if precios and precios not in (negocio.get("precios") or {}):
                return (f"Pide el bloque de precios '{precios}', que ya no "
                        f"existe.", camino, aqui)

            fallo = recorrer(opcion.get("submenu"), sendero + [nombre], aqui)
            if fallo[0]:
                return fallo
        return "", "", []

    return recorrer(negocio.get("menu"), ["El menú"], [])


# ── Consumo en JSON ──────────────────────────────────────────────────

@router.get("/consumo")
def consumo_json(request: Request, periodo: str = ""):
    """
    El consumo de IA de todos los clientes, en JSON.

    Existe para poder facturar sin copiar números de una pantalla: se pega
    en una hoja de cálculo y ya. Los tokens son los reales de Gemini.
    """
    if not acceso.super_habilitado():
        return JSONResponse({"error": "deshabilitado"}, status_code=503)
    if not _entrada_valida(request):
        return JSONResponse({"error": "no autorizado"}, status_code=401)

    periodo = periodo or consumo.periodo_actual()
    return {"periodo": periodo, "clientes": consumo.uso_de_todos(periodo)}
