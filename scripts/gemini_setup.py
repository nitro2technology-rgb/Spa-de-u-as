"""
DIAGNÓSTICO DE LA IA (Gemini) — PLAN PRO
=========================================
Comprueba que la clave del cliente sirve de verdad y que su bot entiende
lo que le escriben, ANTES de ponerlo delante de nadie.

Se corre a mano, en la máquina de quien configura el cliente. No hace
falta en el servidor.

Uso (desde la raíz del proyecto):
    python scripts/gemini_setup.py check          # ¿la clave sirve?
    python scripts/gemini_setup.py probar "hola, cuanto vale una web"

`probar` es el que de verdad importa: enseña qué opción del menú habría
elegido el bot con ese mensaje. Es la forma de ver si el menú del cliente
está bien redactado, porque la IA elige a partir de los títulos y las
descripciones que él mismo escribió en negocio.toml.
"""

import argparse
import os
import sys

# Al correr "python scripts/gemini_setup.py", Python solo pone scripts/ en
# la ruta de búsqueda, así que el paquete app no se encontraría. Añadimos
# la raíz del proyecto antes de importarlo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config  # noqa: E402

OK = "[OK]"
FAIL = "[X]"
WARN = "[!]"


def _todas_las_opciones():
    """
    El menú entero en una lista plana, igual que lo ve el bot.

    Se copia de bot_logic en vez de importarlo para que este script no
    arrastre la base de datos ni el cliente de WhatsApp: tiene que poder
    correrse en una máquina recién clonada, con solo el .env puesto.
    """
    opciones = []
    for opcion in config.NEED_OPTIONS:
        opciones.append(opcion)
        opciones.extend(opcion.get("submenu", []))
    opciones.extend(config.CIERRE_OPTIONS)
    return opciones


def _avisar_si_esta_apagada():
    """
    IA_ACTIVA no hace falta para probar la clave, pero olvidarla es el
    error más fácil de cometer: la clave funciona, el script dice que todo
    está bien, y el bot desplegado sigue sin IA porque el interruptor
    quedó en false.
    """
    if not config.IA_ACTIVA:
        print(f"    {WARN} IA_ACTIVA está en false.")
        print("        La clave se puede probar igual, pero el bot NO usará la IA")
        print("        hasta que la pongas en true (en .env o en el panel de Render).")


def cmd_check(args):
    print("\n=== 1. Configuración ===")
    _avisar_si_esta_apagada()

    if not config.GEMINI_API_KEY:
        print(f"    {FAIL} Falta GEMINI_API_KEY.")
        print("        Se saca gratis en https://aistudio.google.com/apikey")
        print("        con la cuenta de Google del negocio, y se pega en el .env")
        print("        (en local) o en las variables del servicio (en Render).")
        return 1

    # Nunca se imprime entera: esta salida se pega en chats y en tickets.
    clave = config.GEMINI_API_KEY
    print(f"    {OK} Clave presente ({clave[:6]}…{clave[-4:]}, {len(clave)} caracteres).")
    print(f"    ... modelo: {config.GEMINI_MODELO}")
    print(f"    ... se rinde a los: {config.IA_TIMEOUT_SEGUNDOS}s")
    tope = config.IA_MAX_MENSAJES_DIA
    print(f"    ... tope por contacto y día: {tope if tope > 0 else 'sin tope'}")

    print("\n=== 2. La librería ===")
    try:
        import google.genai  # noqa: F401
        print(f"    {OK} google-genai instalada.")
    except ImportError:
        print(f"    {FAIL} Falta la librería. Instálala con:")
        print("        pip install -r requirements.txt")
        return 1

    print("\n=== 3. La clave contra el modelo ===")
    from app.bot.cerebro import gemini

    try:
        respuesta = gemini.comprobar()
        print(f"    {OK} El modelo respondió: {respuesta[:60]!r}")
    except gemini.GeminiNoDisponible as e:
        print(f"    {FAIL} {e}")
        print("        Si la clave es nueva, dale un minuto: tardan un poco en")
        print("        activarse. Si sigue fallando, revisa que sea de AI Studio")
        print("        y no de otro producto de Google Cloud.")
        return 1

    print("\n=== 4. El menú que va a interpretar ===")
    opciones = _todas_las_opciones()
    print(f"    {OK} {len(opciones)} opciones cargadas de negocio.toml.")
    sin_texto = [o["id"] for o in opciones
                 if not o.get("title") and not o.get("description")]
    if sin_texto:
        print(f"    {WARN} Sin título ni descripción: {', '.join(sin_texto)}")
        print("        La IA elige leyendo esos textos. Una opción sin texto es")
        print("        una opción que nunca va a elegir.")

    print(f"\n{OK} La IA quedó lista.")
    print("    Pruébala con un mensaje real:")
    print('        python scripts/gemini_setup.py probar "cuanto vale una pagina web"')
    return 0


def cmd_probar(args):
    """
    El mensaje de un cliente, contra el menú del negocio. Enseña la
    decisión sin mandarle nada a nadie.
    """
    if not config.GEMINI_API_KEY:
        print(f"{FAIL} Falta GEMINI_API_KEY. Corre primero: "
              f"python scripts/gemini_setup.py check")
        return 1

    from app.bot.cerebro import gemini

    opciones = _todas_las_opciones()

    # `interpretar` espera un contacto para el tope diario. Aquí no hay
    # base de datos, así que se le pasa uno de mentira con los mismos
    # atributos. Con el tope en 0 no se toca ninguno, pero se dejan
    # puestos para que este script use exactamente el mismo camino que el
    # bot de verdad — si no, no probaría lo que dice probar.
    class ContactoDePrueba:
        phone = "diagnostico"
        name = "Prueba"
        ia_mensajes_dia = 0
        ia_dia = None

    print(f'\nMensaje: "{args.mensaje}"')
    decision = gemini.interpretar(ContactoDePrueba(), args.mensaje, opciones)

    print("\n=== Qué haría el bot ===")
    if decision.intencion:
        elegida = next((o for o in opciones if o["id"] == decision.intencion), None)
        titulo = elegida.get("title", "?") if elegida else "?"
        accion = elegida.get("accion", "?") if elegida else "?"
        print(f"    {OK} Lo lleva a la opción '{titulo}'")
        print(f"    ... id: {decision.intencion}   acción: {accion}")
        print("    ... el texto que recibe sale de negocio.toml, no de la IA.")
    elif decision.respuesta:
        print(f"    {OK} Le responde directamente:")
        print(f"        {decision.respuesta}")
    else:
        print(f"    {WARN} No lo entendió: le respondería el 'no entendí' de siempre")
        print("        y le volvería a ofrecer el menú.")
        print("        Si el mensaje era claro, revisa los títulos y las")
        print("        descripciones del menú en negocio.toml: es lo que lee la IA.")

    if decision.motivo:
        print(f"\n    (motivo interno: {decision.motivo})")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Diagnóstico de la IA del plan Pro (Gemini)")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("check", help="Verifica la clave, la librería y el menú")

    p = sub.add_parser("probar", help="Prueba un mensaje contra el menú del negocio")
    p.add_argument("mensaje", help="Lo que escribiría un cliente")

    args = parser.parse_args()
    return {"check": cmd_check, "probar": cmd_probar}[args.comando](args)


if __name__ == "__main__":
    sys.exit(main())
