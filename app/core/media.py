"""
ARCHIVOS DEL CHAT (imágenes, notas de voz, documentos)
=======================================================
Lo único que sabe de archivos. Baja de Meta lo que manda el cliente,
sube a Meta lo que manda el dueño desde el panel, y guarda una copia
temporal en disco para no pedir dos veces lo mismo.

**El disco es un caché, no el archivo definitivo.** Meta conserva durante
7 días todo lo que entra por el webhook, así que aquí basta con tener a
mano lo de las últimas horas: si el dueño abre una conversación de hace
tres días, el archivo se vuelve a bajar solo y no nota nada. Eso es lo
que permite un plazo de un día en un disco de 1 GB.

Pasados esos 7 días el archivo se pierde de verdad, pero la FICHA (que
hubo una imagen, cuándo y de quién) vive en la tabla `messages` y no se
borra: la conversación nunca queda con un hueco silencioso.

Como `integrations/`, todo aquí falla "hacia fuera": si Meta no responde
o el disco está lleno, se levanta una excepción que el panel convierte en
un aviso, pero ninguna conversación con un cliente se cae por esto.
"""

import io
import os
import time

import requests

from app import config


class MediaError(Exception):
    """Algo salió mal con un archivo. El panel lo muestra tal cual."""


# Lo que Meta acepta, comprobado en su documentación. Enviar algo fuera de
# esta lista falla con un error opaco, así que se valida antes de subir.
#
# De la imagen no hay lista porque no hace falta comprobarla:
# `preparar_imagen` reconvierte con Pillow todo lo que no sea JPEG o PNG
# —ni WebP ni HEIC, que es justo el formato del iPhone—, así que la regla
# de Meta se cumple por construcción.
MIMES_AUDIO = ("audio/aac", "audio/amr", "audio/mpeg", "audio/mp4", "audio/ogg")

# Para que se vea como NOTA DE VOZ (con su onda y su 1x/2x) y no como un
# archivo adjunto, tiene que ser OGG con codec Opus y en mono.
MIME_NOTA_DE_VOZ = "audio/ogg"

_EXTENSIONES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/amr": ".amr",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "application/pdf": ".pdf",
}

_GRAPH = f"https://graph.facebook.com/{config.GRAPH_API_VERSION}"

# Bajar un archivo tarda más que mandar un mensaje de texto: el timeout de
# 15 s del cliente de mensajes se queda corto con una imagen de 5 MB.
_TIMEOUT = 60


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}


def extension_de(mime: str) -> str:
    """La extensión que le toca a un mime. `.bin` si no lo conocemos."""
    return _EXTENSIONES.get((mime or "").split(";")[0].strip(), ".bin")


# ── Hablar con Meta ──────────────────────────────────────────────────

def descargar(media_id: str) -> tuple[bytes, str]:
    """
    Baja un archivo de Meta. Devuelve (bytes, mime).

    Son DOS peticiones y la segunda es la que sorprende: el id no da el
    archivo, da una URL temporal en otro dominio, y esa URL **también**
    exige la cabecera de autorización. Sin ella responde 401 y es fácil
    perder un rato buscando el error en el sitio equivocado.

    Levanta MediaError si el id ya caducó (Meta borra a los 7 días lo que
    llegó por webhook) o si la descarga falla.
    """
    if not media_id:
        raise MediaError("No hay id de archivo que bajar.")

    # Los fallos de red también son MediaError: el panel sabe pintar esa
    # y ninguna otra. Una excepción de `requests` salía como un 500 con la
    # imagen rota y sin decir por qué.
    try:
        ficha = requests.get(f"{_GRAPH}/{media_id}", headers=_headers(),
                             timeout=_TIMEOUT)
        if ficha.status_code >= 400:
            raise MediaError(
                f"Meta no encuentra el archivo ({ficha.status_code}). "
                "Lo más probable es que haya pasado el plazo de 7 días."
            )

        datos = ficha.json()
        url = datos.get("url")
        if not url:
            raise MediaError("Meta respondió sin URL de descarga.")

        archivo = requests.get(url, headers=_headers(), timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise MediaError(f"Meta no contestó al pedir el archivo: {e}") from e
    except ValueError as e:
        raise MediaError("Meta respondió algo que no se entiende.") from e

    if archivo.status_code >= 400:
        raise MediaError(f"No se pudo bajar el archivo ({archivo.status_code}).")

    mime = datos.get("mime_type") or archivo.headers.get("Content-Type", "")
    return archivo.content, mime.split(";")[0].strip()


def subir(contenido: bytes, mime: str, nombre: str = "archivo") -> str:
    """
    Sube un archivo a Meta y devuelve su media_id, que es lo que se manda
    después en el mensaje.

    Va en multipart, no en JSON, así que no puede reutilizar el `_post` de
    whatsapp_client.
    """
    if not config.PHONE_NUMBER_ID:
        raise MediaError("Falta PHONE_NUMBER_ID: no se puede subir nada.")

    try:
        respuesta = requests.post(
            f"{_GRAPH}/{config.PHONE_NUMBER_ID}/media",
            headers=_headers(),
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": (nombre, contenido, mime)},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        raise MediaError(f"Meta no contestó al subir el archivo: {e}") from e

    if respuesta.status_code >= 400:
        raise MediaError(f"Meta rechazó el archivo ({respuesta.status_code}): "
                         f"{respuesta.text[:200]}")

    media_id = respuesta.json().get("id")
    if not media_id:
        raise MediaError("Meta aceptó el archivo pero no devolvió su id.")

    return media_id


# ── El caché en disco ────────────────────────────────────────────────

def _carpeta() -> str:
    """La carpeta del caché, creada si hacía falta."""
    os.makedirs(config.MEDIA_DIR, exist_ok=True)
    return config.MEDIA_DIR


def ruta_cache(message_id: int, mime: str) -> str:
    """Dónde va el archivo de un mensaje. El id del mensaje lo hace único."""
    return os.path.join(_carpeta(), f"{message_id}{extension_de(mime)}")


def leer_cache(message_id: int, mime: str) -> bytes | None:
    """Los bytes guardados, o None si no están."""
    ruta = os.path.join(config.MEDIA_DIR, f"{message_id}{extension_de(mime)}")
    try:
        with open(ruta, "rb") as f:
            return f.read()
    except OSError:
        return None


def escribir_cache(message_id: int, mime: str, contenido: bytes):
    """
    Guarda una copia. Si falla (disco lleno, permisos), no pasa nada
    grave: se seguirá bajando de Meta cada vez, más lento pero funciona.
    """
    try:
        with open(ruta_cache(message_id, mime), "wb") as f:
            f.write(contenido)
    except OSError as e:
        print(f"[media] No se pudo guardar en caché el mensaje {message_id}: {e}")


def obtener(message_id: int, media_id: str, mime: str) -> tuple[bytes, str]:
    """
    Los bytes de un adjunto, vengan de donde vengan.

    Es lo que llama el panel: mira el caché y, si no está, lo baja de Meta
    y lo guarda para la próxima vez.
    """
    guardado = leer_cache(message_id, mime)
    if guardado is not None:
        return guardado, mime

    contenido, mime_real = descargar(media_id)
    escribir_cache(message_id, mime_real or mime, contenido)
    return contenido, (mime_real or mime)


def limpiar_cache(dias: int = None, tope_mb: int = None) -> int:
    """
    Borra archivos viejos del caché DE TODOS LOS NEGOCIOS. Devuelve cuántos
    borró.

    Cada negocio tiene su carpeta (`<base>/<client_id>`), y esto las
    recorre todas. Antes miraba solo `config.MEDIA_DIR`, que al arrancar
    —sin inquilino— es la del cliente 1: las de los demás crecían sin
    límite hasta llenar el disco.

    Dos criterios, y el segundo existe porque el primero no basta: un pico
    raro de tráfico podría llenar el disco dentro del plazo, y quedarse sin
    sitio no solo pierde imágenes, deja a la BASE sin donde escribir.

    1. Todo lo que pase de `dias`.
    2. Si aun así una carpeta pasa de `tope_mb`, lo más viejo hasta bajar.
       El tope es por negocio, que es por lo que hay una carpeta cada uno:
       el que más archivos recibe no le borra el caché a los demás.

    Borrar aquí no pierde nada mientras el archivo siga vivo en Meta: se
    vuelve a bajar solo la próxima vez que alguien abra esa conversación.
    """
    base = config.carpeta_media_base()
    if not os.path.isdir(base):
        return 0

    # SOLO las carpetas que se llaman como un id de cliente, y nunca los
    # archivos sueltos de la raíz. `MEDIA_DIR` es una variable de entorno:
    # si alguien la apuntara a /var/data, que es donde vive la base SQLite,
    # limpiar "todo lo viejo" de ahí borraría la base.
    borrados = 0
    for nombre in os.listdir(base):
        carpeta = os.path.join(base, nombre)
        if nombre.isdigit() and os.path.isdir(carpeta):
            borrados += _limpiar_carpeta(carpeta, dias, tope_mb)
    return borrados


def _limpiar_carpeta(carpeta: str, dias: int = None, tope_mb: int = None) -> int:
    """La limpieza de `limpiar_cache`, en la carpeta de UN negocio."""
    dias = config.MEDIA_CACHE_DIAS if dias is None else dias
    tope_mb = config.MEDIA_CACHE_MB if tope_mb is None else tope_mb

    archivos = []
    for nombre in os.listdir(carpeta):
        ruta = os.path.join(carpeta, nombre)
        try:
            info = os.stat(ruta)
        except OSError:
            continue
        if os.path.isfile(ruta):
            archivos.append((info.st_mtime, info.st_size, ruta))

    borrados = 0

    # Igual que HISTORIAL_DIAS: un 0 mal puesto no puede significar
    # "bórralo todo ahora mismo".
    if dias > 0:
        limite = time.time() - dias * 86400
        for fecha, _tamano, ruta in list(archivos):
            if fecha < limite and _borrar(ruta):
                archivos.remove((fecha, _tamano, ruta))
                borrados += 1

    total = sum(t for _f, t, _r in archivos)
    if tope_mb > 0 and total > tope_mb * 1024 * 1024:
        for _fecha, tamano, ruta in sorted(archivos):  # del más viejo
            if total <= tope_mb * 1024 * 1024:
                break
            if _borrar(ruta):
                total -= tamano
                borrados += 1

    if borrados:
        print(f"[media] Limpieza: {borrados} archivos borrados del caché "
              f"({carpeta}).")

    return borrados


def _borrar(ruta: str) -> bool:
    try:
        os.remove(ruta)
        return True
    except OSError:
        return False


# ── Dejar los archivos como los quiere Meta ──────────────────────────

def preparar_imagen(contenido: bytes) -> tuple[bytes, str]:
    """
    Deja una imagen en un formato que Meta acepte. Devuelve (bytes, mime).

    Meta solo admite JPEG y PNG de 8 bits, y como mucho 5 MB. Todo lo
    demás lo rechaza con un error que no dice cuál de las tres cosas
    falló. Aquí se arregla en silencio, que es lo que resuelve los dos
    casos reales: la foto HEIC de un iPhone y el PNG de 16 bits que
    escupen algunas herramientas de diseño.

    Si Pillow no puede ni abrirla, es que no era una imagen.
    """
    try:
        from PIL import Image
    except ImportError:
        # Sin Pillow no se puede validar; se manda tal cual y que decida
        # Meta. El panel ya está instalado con Pillow, así que es un caso
        # de laboratorio.
        return contenido, "image/jpeg"

    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen.load()
    except Exception as e:
        raise MediaError("Ese archivo no es una imagen que se pueda leer.") from e

    tope = config.MEDIA_MAX_MB_IMAGEN * 1024 * 1024
    formato = (imagen.format or "").upper()

    # El caso bueno: ya está bien y no hay que tocar nada. Recomprimir una
    # imagen que ya valía solo le quitaría calidad.
    if (formato in ("JPEG", "PNG") and imagen.mode in ("RGB", "RGBA", "L")
            and len(contenido) <= tope):
        return contenido, ("image/png" if formato == "PNG" else "image/jpeg")

    if imagen.mode not in ("RGB", "L"):
        imagen = imagen.convert("RGB")

    # Se recomprime a JPEG bajando calidad y, si aun así no cabe, tamaño.
    # El orden importa: perder un poco de nitidez se nota mucho menos que
    # perder la mitad de los píxeles.
    for calidad in (85, 70, 55):
        salida = io.BytesIO()
        imagen.save(salida, format="JPEG", quality=calidad, optimize=True)
        if salida.tell() <= tope:
            return salida.getvalue(), "image/jpeg"

    imagen.thumbnail((1600, 1600))
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=75, optimize=True)
    if salida.tell() > tope:
        raise MediaError(
            f"La imagen sigue pesando más de {config.MEDIA_MAX_MB_IMAGEN} MB "
            "después de comprimirla.")

    return salida.getvalue(), "image/jpeg"


def a_nota_de_voz(contenido: bytes, mime: str) -> tuple[bytes, str, bool]:
    """
    Convierte una grabación a OGG/Opus mono, que es lo que WhatsApp pinta
    como nota de voz. Devuelve (bytes, mime, es_nota_de_voz).

    Hace falta porque los navegadores no graban en ese formato: Chrome da
    WebM/Opus (que Meta ni siquiera acepta) y Safari da MP4/AAC (que Meta
    acepta, pero lo muestra como un archivo adjunto, no como nota de voz).

    Se transcodifica siempre, aunque el audio ya venga en Opus y bastara
    con reempaquetarlo. Un camino en vez de dos: son unos segundos de
    audio, el ahorro no se nota y el código que no existe no se rompe.

    **El tercer valor importa.** Si la conversión falla y lo que llegó ya
    era un formato que Meta admite, se manda igual —mejor un adjunto que
    nada— pero devolviendo False para que quien llama lo DIGA. Antes esto
    se degradaba en silencio, y el resultado era un audio que se envía sin
    error y aparece como archivo en el teléfono del cliente: perfecto en
    los logs y mal donde se ve.
    """
    base = (mime or "").split(";")[0].strip()

    try:
        return _transcodificar_a_opus(contenido), MIME_NOTA_DE_VOZ, True
    except Exception as e:
        print(f"[media] AVISO: no se pudo convertir a nota de voz: {e}")

    if base in MIMES_AUDIO:
        return contenido, base, False

    raise MediaError(
        "No se pudo preparar la nota de voz y el formato de la grabación "
        f"({base or 'desconocido'}) no lo acepta WhatsApp.")


# Opus para voz. 16 kbps mono es lo que usa el propio WhatsApp: se
# entiende igual y, sobre todo, mantiene el archivo pequeño.
#
# El tamaño no es un detalle estético: Meta solo dibuja el botón de
# reproducir si el audio pesa 512 KB o menos. Por encima lo cambia por un
# icono de descarga, y deja de parecer una nota de voz aunque lo sea. A
# 16 kbps eso son más de cuatro minutos de grabación.
BITRATE_NOTA_DE_VOZ = 16000


def _transcodificar_a_opus(contenido: bytes) -> bytes:
    """
    El trabajo sucio, con PyAV. Aparte para que `a_nota_de_voz` se lea.

    Opus solo funciona a 48 kHz, y Meta exige mono para las notas de voz;
    por eso el remuestreo no es opcional aunque la entrada ya sea Opus.
    """
    import av  # importación perezosa: solo hace falta al mandar una nota de voz

    entrada = av.open(io.BytesIO(contenido))
    try:
        if not entrada.streams.audio:
            raise MediaError("La grabación no tiene pista de audio.")

        buzon = io.BytesIO()
        salida = av.open(buzon, mode="w", format="ogg")
        try:
            # `application=voip` le dice a Opus que esto es una voz y no
            # música: a bitrate bajo se nota, y es para lo que existe.
            pista = salida.add_stream("libopus", rate=48000,
                                      options={"application": "voip"})
            pista.layout = "mono"
            pista.bit_rate = BITRATE_NOTA_DE_VOZ

            remuestreo = av.AudioResampler(format="s16", layout="mono", rate=48000)

            for trozo in entrada.decode(audio=0):
                # El reloj de la entrada no sirve en la salida: se deja
                # que el codificador ponga los tiempos.
                trozo.pts = None
                for remuestreado in _resample(remuestreo, trozo):
                    for paquete in pista.encode(remuestreado):
                        salida.mux(paquete)

            # Lo que quedó en el buffer del remuestreador y del codificador.
            for remuestreado in _resample(remuestreo, None):
                for paquete in pista.encode(remuestreado):
                    salida.mux(paquete)
            for paquete in pista.encode(None):
                salida.mux(paquete)
        finally:
            salida.close()
    finally:
        entrada.close()

    datos = buzon.getvalue()
    if not datos:
        raise MediaError("La conversión devolvió un audio vacío.")

    return datos


def _resample(remuestreador, trozo):
    """
    PyAV cambió esto por el camino: antes devolvía un frame o None, y
    ahora una lista. Se normaliza aquí para que la versión instalada no
    importe.
    """
    resultado = remuestreador.resample(trozo)
    if resultado is None:
        return []
    if isinstance(resultado, list):
        return resultado
    return [resultado]
