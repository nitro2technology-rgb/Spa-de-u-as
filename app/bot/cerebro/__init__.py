"""
EL CEREBRO DEL BOT
===================
Decide qué hacer con un mensaje que el cliente escribió a mano, en vez de
tocar una opción del menú.

Hay dos implementaciones, y son los dos planes que se venden:

    plan Básico  →  menu.py     reconoce el título de un botón escrito a mano
    plan Pro     →  gemini.py   interpreta lo que escribió y responde
                                (y si no sabe, prueba lo de menu.py)

`bot_logic` no sabe cuál está puesta: siempre llama a `interpretar()` y
siempre recibe una `Decision`. Por eso los dos planes son el mismo código
y un arreglo en el Básico llega al Pro solo, sin nada que replicar.

CÓMO SE ELIGE EL PLAN
---------------------
Se decide **en cada mensaje**, no al arrancar. Eso es lo que permite que
el dueño lo active desde su panel y funcione al instante, sin reiniciar
el servicio ni pedirle a nadie que despliegue.

El orden es:

  1. ¿Lo CONTRATÓ? (`clients.ia_contratada`, se marca en /superadmin). Si
     no, es Básico y no hay más que hablar. Esta es la puerta de verdad:
     la clave de Gemini la ponemos nosotros y es la misma para todos.
  2. ¿Hay clave de Gemini (la suya o la del despliegue)? Sin clave el
     plan Pro no puede funcionar, y prometerlo en el panel sería mentir.
  3. ¿El dueño lo encendió o lo apagó desde su panel? Manda eso.
  4. Si no lo ha tocado nunca, manda `ia_activa`: cómo nació.
"""

from app import config
from app.bot.cerebro import menu
from app.bot.cerebro.base import NO_SE, Decision  # noqa: F401  (re-export)

# La clave del ajuste que guarda lo que eligió el dueño.
AJUSTE_PLAN = "plan_ia"

BASICO = "basico"
PRO = "pro"


def hay_clave() -> bool:
    """
    Si este servicio tiene con qué hablarle a la IA.

    Sin clave el plan Pro no es una opción: el panel lo enseña bloqueado y
    explica cómo conseguirla, en vez de ofrecer un botón que no haría nada.
    """
    return bool(config.GEMINI_API_KEY)


def contratada() -> bool:
    """
    Si este negocio COMPRÓ el paquete de IA.

    Es la primera puerta, antes que la clave. Y tiene que estar aquí, en
    el camino que decide, y no solo en el panel: esconder el botón
    mientras el endpoint sigue aceptando la petición no es una puerta.

    Sin esto, la única puerta era "¿hay clave de Gemini?" — y la clave la
    ponemos nosotros y es la misma para todos, así que cualquier cliente
    podía encenderla desde su panel y cargarnos el consumo sin pagarlo.
    """
    return bool(config.IA_CONTRATADA)


def plan_activo() -> str:
    """`"pro"` o `"basico"`. Ver el orden explicado arriba."""
    if not contratada():
        return BASICO

    if not hay_clave():
        return BASICO

    # El import va aquí dentro: `ajustes` toca la base de datos, y este
    # módulo lo importa `bot_logic`, que a su vez importa medio proyecto.
    # Arriba crearía un círculo de imports al arrancar.
    from app.core import ajustes

    elegido = ajustes.leer(AJUSTE_PLAN, None)
    if elegido in (BASICO, PRO):
        return elegido

    return PRO if config.IA_ACTIVA else BASICO


def cambiar_plan(nuevo: str) -> str:
    """
    Cambia el plan desde el panel. Devuelve el que quedó activo.

    Levanta ValueError si se pide Pro sin clave: es un error de quien
    llama, no un estado posible del sistema.
    """
    if nuevo not in (BASICO, PRO):
        raise ValueError(f"Plan desconocido: {nuevo!r}. Usa 'basico' o 'pro'.")

    if nuevo == PRO and not contratada():
        raise ValueError(
            "Este negocio no tiene contratado el paquete de IA. Se activa "
            "desde /superadmin, en la ficha del cliente.")

    if nuevo == PRO and not hay_clave():
        # Lo lee el DUEÑO en su panel: no le toca a él poner la clave, que
        # es de la plataforma. Decirle "ponla en las variables del
        # servicio" era mandarlo a un sitio al que no tiene acceso.
        raise ValueError(
            "La IA de este negocio todavía no tiene clave. Avísanos y la "
            "dejamos lista.")

    from app.core import ajustes
    ajustes.escribir(AJUSTE_PLAN, nuevo)
    print(f"[cerebro] Plan cambiado a '{nuevo}'.")
    return nuevo


def interpretar(contact, texto: str, opciones: list) -> Decision:
    """Ver `base.interpretar`. Nunca levanta una excepción."""
    if plan_activo() == PRO:
        # El import es perezoso a propósito: en el plan Básico la librería
        # de Gemini no se carga nunca, así que no cuesta ni un milisegundo
        # de arranque a quien no la usa.
        from app.bot.cerebro import gemini
        decision = gemini.interpretar(contact, texto, opciones)
        if decision.intencion or decision.respuesta:
            return decision
        # Gemini no supo, falló o se acabó el cupo. Antes de rendirse se
        # prueba lo del plan Básico: que el cliente con IA reciba "no
        # entendí" ante el título exacto de un botón, que el cliente sin
        # IA sí reconoce, sería vender la IA como un paso atrás.

    return menu.interpretar(contact, texto, opciones)


def estado() -> dict:
    """
    Cómo está la IA ahora mismo, para el panel y para /admin/status.

    No devuelve la clave ni ningún trozo de ella.
    """
    from app.core import consumo

    activo = plan_activo()
    gastado = consumo.del_mes()
    estado = {
        "plan": activo,
        "ia_encendida": activo == PRO,
        # Lo primero que hay que mirar cuando alguien dice "activé la IA y
        # no pasa nada": si no está contratada, no hay nada que activar.
        "contratada": contratada(),
        "clave_configurada": hay_clave(),
        "modelo": config.GEMINI_MODELO if activo == PRO else None,
        "tope_diario": config.IA_MAX_MENSAJES_DIA,

        # El cupo del mes. Sin esto, un dueño que llega al tope ve que el
        # bot "dejó de entender" y no tiene forma de saber por qué: la
        # degradación es silenciosa para el cliente final a propósito, pero
        # para quien administra el bot tiene que ser visible.
        "tope_mensual": config.IA_LIMITE_MENSUAL,
        "consumo_mes": gastado["mensajes"],
        "restantes_mes": consumo.restantes(),
        "periodo": gastado["periodo"],
        # Qué mandaría si el dueño no hubiera tocado nada. Sirve para que
        # el panel pueda decir "vuelve a lo que dejó configurado tu plan".
        "por_defecto": PRO if config.IA_ACTIVA else BASICO,
        "ultimo_fallo": None,
    }

    # El último fallo de la IA, si lo hubo. Sin esto, "activé la IA y el
    # bot responde igual que antes" solo se puede diagnosticar entrando a
    # los logs del hosting — que es justo lo que un dueño de negocio no va
    # a hacer.
    if activo == PRO:
        from app.bot.cerebro import gemini
        estado["ultimo_fallo"] = gemini.ultimo_fallo()

    return estado
