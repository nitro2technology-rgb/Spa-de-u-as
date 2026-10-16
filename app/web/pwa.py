"""
APP INSTALABLE (PWA)
=====================
Hace que el panel se pueda instalar en el celular desde el navegador
("Añadir a pantalla de inicio"): queda con icono propio, sin barra de
direcciones y con el nombre del negocio debajo.

Por qué PWA y no una app nativa: una nativa exigiría una compilación, una
ficha de tienda y una revisión de Apple POR CADA CLIENTE, y eso rompe el
modelo de plantilla. Esto aparece solo al desplegar y no cuesta licencias.

Todo se genera en Python, como en paginas_publicas.py: sin archivos
estáticos, sin build y sin CDN.

Tres rutas, las tres públicas (no llevan nada privado dentro):

    /manifest.webmanifest   la ficha de la app (nombre, colores, iconos)
    /sw.js                  el service worker, servido DESDE LA RAÍZ para
                            que su alcance cubra /admin/*
    /icono-{tamano}.png     el icono, del logo del cliente o de sus
                            iniciales sobre el color de marca
"""

import base64
import html
import io
import os

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from app import config

router = APIRouter(tags=["publico"])

# Pillow solo hace falta para dibujar el icono. Si faltara, el panel tiene
# que seguir funcionando igual: se queda sin icono propio, nada más.
try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    _HAY_PILLOW = True
except ImportError:  # pragma: no cover - solo si alguien recorta requirements
    _HAY_PILLOW = False

# Los únicos tamaños que se sirven. Es una lista cerrada a propósito: si
# fuera libre, cualquiera podría pedir /icono-30000.png y poner al
# servidor a dibujar una imagen gigante.
#   32   pestaña del navegador
#   180  apple-touch-icon (iOS no acepta otro tamaño)
#   192  Android, icono de la pantalla de inicio
#   512  pantalla de arranque y ficha de instalación
TAMANOS_ICONO = (32, 180, 192, 512)

# Carpeta donde el cliente deja su logo. Si no hay ninguno, el icono se
# dibuja con las iniciales del negocio.
CARPETA_MARCA = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "marca")
NOMBRES_LOGO = ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp")

# El icono no cambia entre peticiones: se dibuja una vez y se guarda.
# La clave lleva el INQUILINO además del tamaño: el icono se dibuja con el
# logo y el color de cada negocio, así que con la clave a secas el primero
# en pedirlo le dejaba SU icono a todos los demás paneles.
_CACHE_ICONOS: dict[tuple, bytes] = {}

# Una semana. El icono de un negocio no cambia casi nunca, y si cambia
# basta con desinstalar y volver a añadir a la pantalla de inicio.
#
# PRIVATE, no public, y con `Vary: Cookie`. Sin subdominios, /icono-192.png
# es la MISMA dirección para todos los negocios y lo que devuelve depende
# de la sesión. Con `public`, un proxy o una CDN por delante podía guardar
# el icono de un negocio y servírselo a los demás.
_CACHE_NAVEGADOR = "private, max-age=604800"


# ── Manifiesto ───────────────────────────────────────────────────────

@router.get("/manifest.webmanifest")
def manifiesto():
    """
    La ficha que lee el navegador para saber que esto es instalable.

    `start_url` apunta a la bandeja: al abrir desde el icono se entra
    directo a las conversaciones, no a la raíz.
    """
    iconos = [
        {"src": f"/icono-{t}.png", "sizes": f"{t}x{t}", "type": "image/png"}
        for t in (192, 512)
    ]
    # Android recorta el icono a un círculo o a un cuadrado redondeado
    # según el celular. Un icono "maskable" avisa de que el dibujo está
    # centrado y sobrevive al recorte; sin esto, Android lo mete dentro
    # de un cuadrado blanco con bordes.
    iconos.append({"src": "/icono-512.png", "sizes": "512x512",
                   "type": "image/png", "purpose": "maskable"})

    ficha = {
        "id": "/admin/inbox",
        "name": config.APP_NOMBRE,
        "short_name": config.APP_NOMBRE_CORTO,
        "description": f"Panel de conversaciones de {config.BUSINESS_NAME}",
        "lang": "es",
        "dir": "ltr",
        "start_url": "/admin/inbox",
        "scope": "/",
        "display": "standalone",
        "background_color": config.MARCA_COLOR_FONDO,
        "theme_color": config.MARCA_COLOR,
        "icons": iconos,
    }
    # Por lo mismo que el icono: sin subdominios, la ficha cambia según la
    # sesión y no puede guardarla nadie más que ese navegador.
    return JSONResponse(ficha, media_type="application/manifest+json",
                        headers={"Cache-Control": "private, no-cache",
                                 "Vary": "Cookie"})


# ── Service worker ───────────────────────────────────────────────────

# Se sirve desde la raíz a propósito: el alcance de un service worker es
# la carpeta desde la que se sirve, y desde /admin/ no podría gobernar el
# resto del sitio.
#
# ⚠️ REGLA NO NEGOCIABLE: nada bajo /admin/ pasa por la caché. Guardar el
# HTML del panel dejaría la pantalla de un cliente guardada en el celular,
# y podría reaparecer después de cerrar sesión. Por eso la caché funciona
# con lista blanca (solo iconos y manifiesto) Y ADEMÁS con un corte
# explícito para /admin/: si mañana alguien amplía la lista blanca por
# error, el corte sigue ahí.
_SERVICE_WORKER = """
const CACHE = 'marca-v1';
const PRECARGA = ['/manifest.webmanifest', '/icono-192.png', '/icono-512.png'];

// Lo ÚNICO que se guarda: el manifiesto y los iconos. Todo lo demás va
// a la red siempre.
const CACHEABLE = /^\\/(manifest\\.webmanifest|icono-\\d+\\.png)$/;

self.addEventListener('install', evento => {
  self.skipWaiting();
  evento.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECARGA)).catch(() => {})
  );
});

self.addEventListener('activate', evento => {
  evento.waitUntil(
    caches.keys()
      .then(claves => Promise.all(
        claves.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', evento => {
  const url = new URL(evento.request.url);

  // Nada del panel se guarda NUNCA. Ver el comentario de arriba.
  if (url.pathname.startsWith('/admin')) return;

  if (evento.request.method !== 'GET') return;
  if (url.origin !== self.location.origin) return;
  if (!CACHEABLE.test(url.pathname)) return;

  evento.respondWith(
    caches.match(evento.request).then(guardado => guardado || fetch(evento.request))
  );
});

// ── Avisos al celular ──────────────────────────────────────────────
// Esto corre aunque el panel esté cerrado: es la única parte que sigue
// viva cuando nadie tiene la pestaña abierta.

self.addEventListener('push', evento => {
  let datos = {};
  try { datos = evento.data ? evento.data.json() : {}; } catch (e) {}

  const titulo = datos.titulo || 'Mensaje nuevo';
  const url = datos.url || '/admin/inbox';

  evento.waitUntil(
    self.registration.showNotification(titulo, {
      body: datos.cuerpo || '',
      icon: '/icono-192.png',
      badge: '/icono-192.png',
      // Agrupa por conversación: diez mensajes seguidos del mismo
      // cliente dejan UN aviso actualizado, no diez apilados.
      tag: url,
      renotify: true,
      data: { url: url }
    })
  );
});

self.addEventListener('notificationclick', evento => {
  evento.notification.close();
  const destino = (evento.notification.data && evento.notification.data.url)
                  || '/admin/inbox';

  // Si ya hay una ventana del panel abierta se reutiliza, en vez de
  // acumular pestañas cada vez que llega un aviso.
  evento.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(ventanas => {
        for (const v of ventanas) {
          if (v.url.includes('/admin/') && 'focus' in v) {
            v.navigate(destino);
            return v.focus();
          }
        }
        return self.clients.openWindow(destino);
      })
  );
});
"""


@router.get("/sw.js")
def service_worker():
    return Response(
        _SERVICE_WORKER,
        media_type="application/javascript",
        # Sin no-cache, un navegador podría quedarse meses con una
        # versión vieja del service worker y no enterarse de los cambios.
        headers={"Cache-Control": "no-cache"},
    )


# ── Icono ────────────────────────────────────────────────────────────

@router.get("/icono-{tamano}.png")
def icono(tamano: int):
    if tamano not in TAMANOS_ICONO:
        return JSONResponse({"error": "tamaño no disponible"}, status_code=404)

    if not _HAY_PILLOW:
        return JSONResponse(
            {"error": "falta pillow, el icono no se puede dibujar"},
            status_code=404)

    from app.core import tenencia
    clave = (tenencia.actual_o_none(), tamano)

    if clave not in _CACHE_ICONOS:
        _CACHE_ICONOS[clave] = _dibujar_icono(tamano)

    return Response(_CACHE_ICONOS[clave], media_type="image/png",
                    headers={"Cache-Control": _CACHE_NAVEGADOR,
                             "Vary": "Cookie"})


def olvidar(client_id: int = None):
    """
    Tira el icono cacheado. Hay que llamarlo al cambiarle el logo o el
    color de marca a un negocio, o seguiría sirviendo el de antes durante
    una semana (`_CACHE_NAVEGADOR`).

    Al navegador que ya lo tenga guardado no se le puede quitar de ahí: eso
    se arregla desinstalando y volviendo a añadir a la pantalla de inicio,
    y está dicho en el super-admin al guardar.
    """
    if client_id is None:
        _CACHE_ICONOS.clear()
        return

    for clave in [c for c in _CACHE_ICONOS if c[0] == client_id]:
        _CACHE_ICONOS.pop(clave, None)


def _dibujar_icono(tamano: int) -> bytes:
    """
    El logo del cliente si lo dejó, si no sus iniciales.

    Hay DOS clases de logo y se tratan distinto, porque tratarlas igual
    deja el icono feo en una de las dos:

    - **Con transparencia** (solo el símbolo, sin fondo): se pega
      centrado sobre el color de marca, al 60 % del lienzo.
    - **Sin transparencia** (una imagen cuadrada que YA trae su fondo):
      se usa a sangre, ocupando todo. Pegarlo al 60 % dejaría un
      recuadro flotando encima del color de marca, como una calcomanía.
    """
    logo = _cargar_logo()

    if logo is not None and _trae_su_propio_fondo(logo):
        # ImageOps.fit escala y recorta centrado: un logo que no fuera
        # cuadrado se ajusta sin deformarse.
        lienzo = ImageOps.fit(logo, (tamano, tamano), Image.LANCZOS,
                              centering=(0.5, 0.5)).convert("RGB")
        return _a_png(lienzo)

    fondo = _a_rgb(config.MARCA_COLOR, (22, 163, 74))
    lienzo = Image.new("RGB", (tamano, tamano), fondo)

    if logo is not None:
        # 60 % del lienzo: es el margen que Android recorta en los iconos
        # "maskable". Dibujar más grande haría que le cortara los bordes.
        copia = logo.copy()
        copia.thumbnail((int(tamano * 0.6), int(tamano * 0.6)), Image.LANCZOS)
        lienzo.paste(copia, ((tamano - copia.width) // 2,
                             (tamano - copia.height) // 2), copia)
    else:
        pincel = ImageDraw.Draw(lienzo)
        pincel.text((tamano / 2, tamano / 2), config.iniciales_marca(),
                    font=_fuente(int(tamano * 0.42)),
                    fill=_color_legible_sobre(fondo), anchor="mm")

    return _a_png(lienzo)


def _trae_su_propio_fondo(logo) -> bool:
    """
    ¿El logo es una imagen maciza o un símbolo recortado?

    Si no hay ni un píxel transparente, el diseñador ya le puso su fondo
    y hay que respetarlo entero.
    """
    return logo.getchannel("A").getextrema()[0] == 255


def _a_png(lienzo) -> bytes:
    memoria = io.BytesIO()
    lienzo.save(memoria, format="PNG", optimize=True)
    return memoria.getvalue()


def _cargar_logo():
    """
    El logo del negocio en RGBA, o None si no tiene ninguno.

    Dos sitios, y el orden importa:

      1. **`clients.logo`**, la imagen del negocio guardada en la base. Es
         la que vale con varios inquilinos: un archivo del repositorio es
         del despliegue, o sea de todos, y con dos clientes los dos
         acabarían con el mismo icono.
      2. `app/marca/logo.png`, el archivo del repositorio. Se queda como
         respaldo para el dueño del bot, que es quien lo tenía ahí antes de
         que existieran los inquilinos.

    Un logo ilegible no puede tumbar el panel: se cae a las iniciales sobre
    el color de marca, que es un icono perfectamente presentable.
    """
    if guardado := config.LOGO:
        try:
            return Image.open(io.BytesIO(_bytes_del_logo(guardado))).convert("RGBA")
        except Exception as e:
            print(f"[pwa] El logo guardado de este negocio no se pudo leer, "
                  f"se usan las iniciales: {e}")

    for nombre in NOMBRES_LOGO:
        ruta = os.path.join(CARPETA_MARCA, nombre)
        if os.path.exists(ruta):
            try:
                return Image.open(ruta).convert("RGBA")
            except Exception as e:
                print(f"[pwa] No se pudo leer {nombre}, se usan las "
                      f"iniciales: {e}")
    return None


def _bytes_del_logo(guardado: str) -> bytes:
    """
    La imagen que hay detrás de `clients.logo`.

    Se acepta un data URI (`data:image/png;base64,...`) o base64 pelado.
    Va dentro de la columna y no en un archivo a propósito: en Render no
    hay disco que sobreviva al despliegue, y un logo son unos cientos de
    kilobytes que la base guarda sin quejarse. Una URL externa no sirve:
    el icono se dibuja dentro del webhook del panel y no puede depender de
    que otro servidor conteste.
    """
    if guardado.startswith("data:"):
        guardado = guardado.split(",", 1)[-1]
    return base64.b64decode(guardado, validate=False)


def _fuente(alto: int):
    """
    La fuente que trae Pillow, al tamaño pedido.

    El `size=` existe desde Pillow 10.1; en versiones anteriores la fuente
    por defecto es un mapa de bits diminuto. Se acepta el resultado feo
    antes que reventar el arranque por el icono.
    """
    try:
        return ImageFont.load_default(size=alto)
    except TypeError:  # pragma: no cover - Pillow < 10.1
        return ImageFont.load_default()


def _a_rgb(color: str, respaldo: tuple) -> tuple:
    """'#16a34a' → (22, 163, 74). Si viene mal escrito, el color de casa."""
    # La cuenta vive en config porque el panel también la necesita para su
    # CSS, y config es el módulo del que ya dependen los dos.
    return config.rgb_de(color, respaldo)


def _color_legible_sobre(fondo: tuple) -> tuple:
    """
    Letras negras sobre fondo claro y blancas sobre fondo oscuro, en RGB
    para Pillow. Sin esto, un cliente con el color de marca amarillo
    tendría un icono ilegible.
    """
    return (17, 24, 39) if config.color_legible_sobre(fondo) == "#111827" \
        else (255, 255, 255)


# ── Lo que tiene que llevar cada página del panel ────────────────────

# Las etiquetas que hacen falta en el <head> para que el navegador ofrezca
# instalar y para que iOS haga lo suyo, que va por su cuenta:
#
#  - apple-touch-icon: iOS ignora los iconos del manifiesto y usa este.
#    Tiene que ser PNG de 180×180, no acepta otra cosa.
#  - apple-mobile-web-app-capable: sin esto, al abrir desde el icono iOS
#    muestra igual la barra del navegador y no parece una app.
#  - apple-mobile-web-app-title: el nombre debajo del icono en iOS.
#  - status-bar-style "default" y no "black-translucent": el translúcido
#    mete el contenido POR DEBAJO de la muesca del iPhone, y entonces la
#    cabecera del chat queda tapada salvo que se compensen los márgenes
#    de seguridad a mano. Con "default" iOS deja ese hueco él solo.
#
# Es una FUNCIÓN y no una constante: el color y el nombre son la marca de
# cada negocio, y calculados al importar se quedarían con los del primero.
# Todos los paneles se verían con la marca de otro.
def cabecera_html() -> str:
    # `crossorigin="use-credentials"` hace que el navegador mande la cookie
    # al pedir el manifiesto. Importa cuando todos los negocios comparten
    # la misma dirección: sin eso, el manifiesto se pide sin sesión y todos
    # instalarían la app con el nombre y el icono del cliente por defecto.
    # Con esto, quien ya entró se instala LA SUYA. No es garantía —si se
    # instala antes de entrar, el navegador ya guardó el genérico— pero
    # recupera el caso normal. Con subdominios no cambia nada: la cookie
    # viaja igual por ser el mismo origen.
    #
    # Escapados: los dos los escribe una persona en un formulario, y van
    # dentro de un atributo. Una comilla de más cerraba el atributo.
    color = html.escape(config.MARCA_COLOR or "")
    nombre = html.escape(config.APP_NOMBRE_CORTO or "")
    return f"""<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">
<meta name="theme-color" content="{color}">
<link rel="icon" href="/icono-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/icono-180.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="{nombre}">"""


# El registro del service worker está en `estaticos/pwa-registro.js`, que
# se carga desde TODAS las pantallas del panel (ver `admin_ui._pagina`).
