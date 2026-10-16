"""
AVISOS EN VIVO PARA EL PANEL
=============================
Cuando entra o sale un mensaje, hay que contárselo a los paneles que estén
abiertos. Antes cada panel lo averiguaba preguntando cada 3 segundos, lo
que costaba cientos de consultas a la base para que casi siempre la
respuesta fuera "no hay nada nuevo". Ahora el servidor avisa él, y el
mensaje aparece al instante.

Es un repartidor en memoria, sin Redis ni servicios extra: cada panel
abierto deja una cola aquí y se queda escuchando.

    ⚠️  CADA COLA ES DE UN NEGOCIO, Y SOLO RECIBE LO SUYO.

Esto no es un detalle de organización: hasta la Fase 3 `_suscriptores` era
un `set` global y `_repartir` recorría TODAS las colas. Con dos clientes
con el panel abierto, uno veía en vivo los mensajes de los clientes del
otro —teléfono, nombre y texto completo—, sin que nada diera error. Ahora
las colas están agrupadas por inquilino y un aviso solo baja por las de su
negocio.

    ⚠️  ESTO DEPENDE DE QUE HAYA UN SOLO PROCESO.

`render.yaml` y el `Dockerfile` arrancan uvicorn sin `--workers`, así que
todo ocurre dentro del mismo proceso y una cola en memoria alcanza. Si
algún día se añaden workers, cada uno tendría sus propias colas y un
mensaje que entra por el worker A no llegaría al panel conectado al B. La
salida en ese caso, sin montar servicios nuevos, sería LISTEN/NOTIFY de
Postgres.
"""

import asyncio

# El event loop del servidor, guardado al arrancar. Hace falta porque
# `publicar()` se llama también desde hilos que no son el suyo (ver abajo).
_loop = None

# Las colas de los paneles abiertos, agrupadas por inquilino:
#   {client_id: {cola, cola, ...}}
_suscriptores: dict = {}

# Tope de avisos pendientes por panel. Solo se llena si un panel deja de
# leer (pestaña congelada, red muerta); en ese caso se tiran los más
# viejos, y al reconectar el panel se pone al día solo pidiendo lo que le
# falta desde el último id que tenía.
LIMITE_COLA = 200


def capturar_loop():
    """Se llama al arrancar el servidor, desde el lifespan de main.py."""
    global _loop
    _loop = asyncio.get_running_loop()


def _inquilino_actual():
    """
    De qué negocio es la petición en curso, o None.

    El import va dentro y no arriba porque `tenencia` acaba importando la
    configuración, que a su vez llega hasta aquí: arriba serían módulos
    importándose en círculo. Mismo motivo que en `database.tenencia_actual`.
    """
    from app.core import tenencia
    return tenencia.actual_o_none()


def suscribir() -> asyncio.Queue:
    """
    Deja una cola para el panel que se está abriendo.

    El inquilino se resuelve AQUÍ, en la petición que abre el canal, y se
    queda pegado a la cola. No se puede resolver al repartir: para entonces
    el que corre es el negocio que recibió el mensaje, no el que está
    escuchando.
    """
    cola = asyncio.Queue(maxsize=LIMITE_COLA)
    _suscriptores.setdefault(_inquilino_actual(), set()).add(cola)
    return cola


def desuscribir(cola: asyncio.Queue):
    """
    Retira una cola. Busca en todos los inquilinos en vez de pedir el
    `client_id`: quien cierra el canal es un `finally`, y ahí no puede
    depender de que el contexto siga puesto. Son un puñado de paneles.
    """
    for client_id, colas in list(_suscriptores.items()):
        colas.discard(cola)
        if not colas:
            _suscriptores.pop(client_id, None)


def publicar(evento: dict):
    """
    Reparte un aviso a los paneles abiertos DE ESE NEGOCIO.

    `call_soon_threadsafe` no es opcional: esto se llama desde dos sitios
    distintos. Cuando entra un mensaje de WhatsApp corre en el hilo del
    event loop, pero cuando el dueño responde desde el panel corre en un
    hilo del threadpool (los handlers del panel son funciones normales, no
    async). Tocar las colas directamente desde ahí corrompería el loop.

    Y por eso el inquilino se lee aquí y viaja como argumento: `_repartir`
    se ejecuta más tarde y en el hilo del loop, donde el contexto de esta
    petición ya no está.
    """
    if _loop is None or not _suscriptores:
        return

    client_id = _inquilino_actual()
    if client_id is None:
        # Sin inquilino no hay a quién entregar. La tentación sería
        # repartir a todos "por si acaso", que es exactamente la fuga que
        # se acaba de cerrar. El mensaje ya está guardado: el panel lo verá
        # al refrescar el listado.
        print("[eventos] aviso descartado: no hay inquilino fijado. "
              "Algún camino de entrada no pasa por `tenencia.usar()`.")
        return

    try:
        _loop.call_soon_threadsafe(_repartir, client_id, evento)
    except RuntimeError:
        # El servidor se está apagando y el loop ya no acepta trabajo.
        # Perder un aviso aquí no importa: el mensaje ya está guardado.
        pass


def _repartir(client_id: int, evento: dict):
    for cola in list(_suscriptores.get(client_id, ())):
        try:
            cola.put_nowait(evento)
        except asyncio.QueueFull:
            try:
                cola.get_nowait()        # tira el más viejo
                cola.put_nowait(evento)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
