"""
HERRAMIENTA DE SETUP / DIAGNÓSTICO DE META
===========================================
Script de línea de comandos para hacer y verificar la configuración del
lado de Meta sin depender de la UI (que a veces no suscribe la WABA sola).

No lo usa el bot en tiempo de ejecución: es solo para ti, al migrar a
producción o cuando algo deja de llegar.

Uso (desde la raíz del proyecto):
    python scripts/meta_setup.py check         # revisa token, número y suscripción
    python scripts/meta_setup.py subscribe     # suscribe la WABA a la App
    python scripts/meta_setup.py unsubscribe   # deshace la suscripción
    python scripts/meta_setup.py test-message 573001234567

CONTRA UN CLIENTE CONCRETO
--------------------------
Sin `--cliente` trabaja con las credenciales del `.env`, que son las
tuyas. Con él, las saca de la fila de ese negocio en `clients`:

    python scripts/meta_setup.py --cliente panaderia check
    python scripts/meta_setup.py --cliente panaderia subscribe

Es lo que evita tener que pegar el token de un cliente en tu `.env` para
revisarle la WABA y acordarse de quitarlo después — que es exactamente el
tipo de paso manual del que se olvida uno.
"""

import argparse
import os
import re
import sys
from datetime import datetime

import requests

# Al correr "python scripts/meta_setup.py", Python solo pone scripts/ en la
# ruta de búsqueda, así que el paquete app no se encontraría. Añadimos la
# raíz del proyecto antes de importarlo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config  # noqa: E402

GRAPH = f"https://graph.facebook.com/{config.GRAPH_API_VERSION}"

OK = "[OK]"
FAIL = "[X]"
WARN = "[!]"


def _auth_params():
    return {"access_token": config.WHATSAPP_TOKEN}


def _show_error(response):
    """Imprime el error de la Graph API de forma legible."""
    try:
        error = response.json().get("error", {})
        print(f"    {FAIL} {error.get('message', response.text)}")
        if error.get("error_user_msg"):
            print(f"        {error['error_user_msg']}")
        code = error.get("code")
        subcode = error.get("error_subcode")
        if code:
            print(f"        (code={code} subcode={subcode})")
    except ValueError:
        print(f"    {FAIL} HTTP {response.status_code}: {response.text}")


# ── Comandos ─────────────────────────────────────────────────────────

def cmd_check(args):
    """Revisa de punta a punta que la configuración de Meta esté completa."""
    problemas = 0

    print("\n=== 1. Variables de entorno ===")
    requeridas = {
        "WHATSAPP_TOKEN": config.WHATSAPP_TOKEN,
        "PHONE_NUMBER_ID": config.PHONE_NUMBER_ID,
        "WABA_ID": config.WABA_ID,
        "VERIFY_TOKEN": config.VERIFY_TOKEN,
        "OWNER_PHONE_NUMBER": config.OWNER_PHONE_NUMBER,
    }
    for nombre, valor in requeridas.items():
        if valor:
            # Nunca imprimimos el valor completo de un secreto
            print(f"    {OK} {nombre} definido ({len(valor)} caracteres)")
        else:
            print(f"    {FAIL} {nombre} NO está definido en .env")
            problemas += 1

    opcionales = {"APP_ID": config.APP_ID, "APP_SECRET": config.APP_SECRET}
    for nombre, valor in opcionales.items():
        if valor:
            print(f"    {OK} {nombre} definido")
        else:
            print(f"    {WARN} {nombre} sin definir "
                  f"(necesario para validar la firma del webhook)")

    if not config.WHATSAPP_TOKEN:
        print("\nSin token no se puede seguir. Llena WHATSAPP_TOKEN en .env.")
        return 1

    problemas += _check_token()
    problemas += _check_phone_number()
    problemas += _check_subscription()

    print()
    if problemas:
        print(f"{FAIL} {problemas} problema(s) encontrado(s). Revisa arriba.")
    else:
        print(f"{OK} Todo en orden del lado de Meta.")
    return 1 if problemas else 0


def _check_token():
    """Verifica si el token es válido y si expira (los permanentes no expiran)."""
    print("\n=== 2. Token de acceso ===")

    if not (config.APP_ID and config.APP_SECRET):
        print(f"    {WARN} Sin APP_ID/APP_SECRET no se puede inspeccionar el token.")
        print("        Se probará indirectamente en el paso siguiente.")
        return 0

    response = requests.get(
        f"{GRAPH}/debug_token",
        params={
            "input_token": config.WHATSAPP_TOKEN,
            "access_token": f"{config.APP_ID}|{config.APP_SECRET}",
        },
        timeout=15,
    )
    if response.status_code >= 400:
        _show_error(response)
        return 1

    data = response.json().get("data", {})

    if not data.get("is_valid"):
        print(f"    {FAIL} El token NO es válido (probablemente expiró).")
        return 1
    print(f"    {OK} Token válido.")

    expira = data.get("expires_at", 0)
    if expira == 0:
        print(f"    {OK} No expira — es un token permanente (System User).")
    else:
        fecha = datetime.fromtimestamp(expira).strftime("%Y-%m-%d %H:%M")
        print(f"    {FAIL} EXPIRA el {fecha} — es un token temporal.")
        print("        Genera uno permanente con un System User antes de producción.")
        return 1

    scopes = data.get("scopes", [])
    print(f"    ... permisos: {', '.join(scopes) or '(ninguno)'}")
    for necesario in ("whatsapp_business_messaging", "whatsapp_business_management"):
        if necesario not in scopes:
            print(f"    {FAIL} Falta el permiso '{necesario}'.")
            return 1

    return 0


def _check_phone_number():
    """Confirma que el PHONE_NUMBER_ID pertenece a la WABA configurada."""
    print("\n=== 3. Número de WhatsApp ===")

    if not config.WABA_ID:
        print(f"    {WARN} Sin WABA_ID no se puede listar los números de la cuenta.")
        return 1

    response = requests.get(
        f"{GRAPH}/{config.WABA_ID}/phone_numbers",
        params={
            **_auth_params(),
            "fields": "id,display_phone_number,verified_name,quality_rating,"
                      "code_verification_status,platform_type",
        },
        timeout=15,
    )
    if response.status_code >= 400:
        _show_error(response)
        return 1

    numeros = response.json().get("data", [])
    if not numeros:
        print(f"    {FAIL} La WABA no tiene números registrados.")
        return 1

    encontrado = False
    for numero in numeros:
        marca = ""
        if numero.get("id") == config.PHONE_NUMBER_ID:
            marca = "  <-- el que usa el bot (PHONE_NUMBER_ID)"
            encontrado = True
        print(f"    - {numero.get('display_phone_number')} "
              f"({numero.get('verified_name')}) id={numero.get('id')}{marca}")
        print(f"      calidad={numero.get('quality_rating')} "
              f"verificado={numero.get('code_verification_status')} "
              f"plataforma={numero.get('platform_type')}")

    if not encontrado:
        print(f"    {FAIL} PHONE_NUMBER_ID no coincide con ningún número de esta WABA.")
        print("        Copia el 'id' correcto de la lista de arriba a tu .env.")
        return 1

    print(f"    {OK} PHONE_NUMBER_ID pertenece a la WABA.")
    return 0


def _check_subscription():
    """Verifica que la App esté suscrita a los webhooks de la WABA."""
    print("\n=== 4. Suscripción de la WABA a la App ===")

    if not config.WABA_ID:
        print(f"    {WARN} Sin WABA_ID no se puede verificar.")
        return 1

    response = requests.get(
        f"{GRAPH}/{config.WABA_ID}/subscribed_apps", params=_auth_params(), timeout=15
    )
    if response.status_code >= 400:
        _show_error(response)
        return 1

    apps = response.json().get("data", [])
    if not apps:
        print(f"    {FAIL} Ninguna App suscrita — los mensajes entrantes NO van a llegar.")
        print("        Corre: python scripts/meta_setup.py subscribe")
        return 1

    for app in apps:
        info = app.get("whatsapp_business_api_data", {})
        print(f"    {OK} App suscrita: {info.get('name')} (id={info.get('id')})")
    return 0


def cmd_perfil(args):
    """
    Muestra cómo ven los clientes el número: nombre, verificación y perfil.

    Si al abrir el chat aparece el número en vez del nombre del negocio,
    casi siempre es porque falta la verificación del negocio en Meta.
    """
    print("\n=== Cómo aparece tu número ===")
    respuesta = requests.get(
        f"{GRAPH}/{config.PHONE_NUMBER_ID}",
        params={**_auth_params(),
                "fields": "verified_name,display_phone_number,name_status,"
                          "quality_rating,is_official_business_account"},
        timeout=15,
    )
    if respuesta.status_code >= 400:
        _show_error(respuesta)
        return 1

    numero = respuesta.json()
    print(f"    Nombre para mostrar : {numero.get('verified_name')}")
    print(f"    Número              : {numero.get('display_phone_number')}")
    print(f"    Estado del nombre   : {numero.get('name_status')}")
    print(f"    Calidad             : {numero.get('quality_rating')}")

    print("\n=== Verificación del negocio ===")
    respuesta = requests.get(
        f"{GRAPH}/{config.WABA_ID}",
        params={**_auth_params(),
                "fields": "name,account_review_status,business_verification_status"},
        timeout=15,
    )
    if respuesta.status_code >= 400:
        _show_error(respuesta)
        return 1

    waba = respuesta.json()
    verificado = waba.get("business_verification_status") == "verified"
    print(f"    Cuenta (WABA)       : {waba.get('name')}")
    print(f"    Revisión de la WABA : {waba.get('account_review_status')}")

    if verificado:
        print(f"    {OK} Negocio verificado.")
    else:
        print(f"    {FAIL} Negocio SIN verificar "
              f"({waba.get('business_verification_status')}).")
        print("        Mientras no esté verificado, quien no te tenga guardado")
        print(f"        en sus contactos ve el número y no '{numero.get('verified_name')}'.")
        print("        Se hace en business.facebook.com > Configuración del negocio")
        print("        > Centro de seguridad > Iniciar verificación.")

    if numero.get("is_official_business_account"):
        print(f"    {OK} Cuenta oficial (con el check verde).")
    else:
        print(f"    {WARN} Sin el check verde. Es un distintivo aparte que Meta")
        print("        concede según la notoriedad de la marca; no se pide sin más.")

    print("\n=== Perfil que ve el cliente ===")
    respuesta = requests.get(
        f"{GRAPH}/{config.PHONE_NUMBER_ID}/whatsapp_business_profile",
        params={**_auth_params(),
                "fields": "about,address,description,email,websites,"
                          "vertical,profile_picture_url"},
        timeout=15,
    )
    if respuesta.status_code >= 400:
        _show_error(respuesta)
        return 1

    perfil = (respuesta.json().get("data") or [{}])[0]
    campos = [("description", "Descripción"), ("about", "Info (frase corta)"),
              ("email", "Email"), ("websites", "Sitio web"),
              ("address", "Dirección"), ("vertical", "Categoría")]
    for clave, etiqueta in campos:
        valor = perfil.get(clave)
        marca = OK if valor else WARN
        print(f"    {marca} {etiqueta:20s}: {valor if valor else '(vacío)'}")

    print(f"    {OK if perfil.get('profile_picture_url') else WARN} "
          f"{'Foto de perfil':20s}: "
          f"{'puesta' if perfil.get('profile_picture_url') else '(sin foto)'}")

    return 0


def cmd_plantillas(args):
    """
    Lista las plantillas de la cuenta y su estado de aprobación.

    Sirven para escribirle a alguien pasadas las 24 horas de su último
    mensaje: es el único camino que le queda al bot para avisarte de un
    lead cuando llevas días sin escribirle.
    """
    if not config.WABA_ID:
        print(f"{FAIL} Falta WABA_ID en .env.")
        return 1

    respuesta = requests.get(
        f"{GRAPH}/{config.WABA_ID}/message_templates",
        params={**_auth_params(), "fields": "name,status,language,category,components",
                "limit": 50},
        timeout=20,
    )
    if respuesta.status_code >= 400:
        _show_error(respuesta)
        return 1

    plantillas = respuesta.json().get("data", [])

    print("\n=== Plantillas de la cuenta ===")
    if not plantillas:
        print(f"    {WARN} No hay ninguna todavía.")
    for p in plantillas:
        marca = OK if p.get("status") == "APPROVED" else WARN
        print(f"    {marca} {p.get('name')}  [{p.get('language')}]  "
              f"{p.get('status')}  ({p.get('category')})")
        for c in p.get("components", []):
            if c.get("type") == "BODY":
                print(f"        {c.get('text', '')[:100]}")

    print("\n=== La que usa el bot para avisarte ===")
    if not config.OWNER_TEMPLATE_NAME:
        print(f"    {WARN} OWNER_TEMPLATE_NAME está vacío.")
        print("        Sin ella, los avisos de leads NO te llegan si llevas")
        print("        más de 24h sin escribirle al bot.")
        return 0

    elegida = next((p for p in plantillas
                    if p.get("name") == config.OWNER_TEMPLATE_NAME
                    and p.get("language") == config.OWNER_TEMPLATE_LANG), None)

    if not elegida:
        print(f"    {FAIL} '{config.OWNER_TEMPLATE_NAME}' en idioma "
              f"'{config.OWNER_TEMPLATE_LANG}' no existe en esta cuenta.")
        print("        Ojo con el idioma: 'es' y 'es_ES' son plantillas distintas.")
        return 1

    if elegida.get("status") != "APPROVED":
        print(f"    {WARN} Existe pero está en estado {elegida.get('status')}.")
        print("        Hasta que Meta la apruebe, los avisos fuera de la ventana fallan.")
        return 1

    variables = 0
    for c in elegida.get("components", []):
        if c.get("type") == "BODY":
            variables = len(re.findall(r"\{\{\d+\}\}", c.get("text", "")))

    print(f"    {OK} '{config.OWNER_TEMPLATE_NAME}' aprobada, con {variables} variable(s).")
    if variables != 4:
        print(f"    {FAIL} El bot envía 4 variables (tipo, nombre, teléfono, detalle)")
        print(f"        y la plantilla espera {variables}. Meta rechazará el envío.")
        return 1

    return 0


def cmd_subscribe(args):
    """POST /{WABA_ID}/subscribed_apps — el paso que la UI de Meta a veces no hace."""
    if not config.WABA_ID:
        print(f"{FAIL} Falta WABA_ID en .env.")
        return 1

    response = requests.post(
        f"{GRAPH}/{config.WABA_ID}/subscribed_apps", params=_auth_params(), timeout=15
    )
    if response.status_code >= 400:
        _show_error(response)
        return 1

    print(f"{OK} WABA suscrita a la App. Respuesta: {response.json()}")
    print("Verifica con: python scripts/meta_setup.py check")
    return 0


def cmd_unsubscribe(args):
    if not config.WABA_ID:
        print(f"{FAIL} Falta WABA_ID en .env.")
        return 1

    response = requests.delete(
        f"{GRAPH}/{config.WABA_ID}/subscribed_apps", params=_auth_params(), timeout=15
    )
    if response.status_code >= 400:
        _show_error(response)
        return 1

    print(f"{OK} Suscripción eliminada. Respuesta: {response.json()}")
    return 0


def cmd_test_message(args):
    """
    Envía un texto de prueba. OJO: WhatsApp solo permite texto libre si ese
    número te escribió en las últimas 24h. Si no, hay que usar una plantilla
    aprobada y esto va a fallar con error 131047.
    """
    from app.bot import whatsapp_client as wa

    destino = args.phone
    response = wa.send_text_message(
        destino, f"Mensaje de prueba de {config.BUSINESS_NAME} (meta_setup.py)."
    )
    if response.status_code >= 400:
        _show_error(response)
        print("\nSi el error es 131047 ('re-engagement message'), es normal:")
        print("ese número no te ha escrito en las últimas 24h. Escríbele tú")
        print("primero desde WhatsApp al número del negocio y reintenta.")
        return 1

    print(f"{OK} Mensaje enviado a {destino}. Respuesta: {response.json()}")
    return 0


def _inquilino(argumento: str):
    """
    Deja puesto el negocio contra el que se va a trabajar.

    Sin esto, todos los comandos usan las credenciales del `.env` — o sea
    las tuyas—, y para revisar la WABA de un cliente había que pegarle su
    token al `.env` y acordarse de quitarlo después. Con `--cliente`, la
    configuración se resuelve desde su fila en `clients` (que además la
    tiene cifrada) y no hay nada que deshacer.

    Devuelve un gestor de contexto: se usa dentro de un `with`.
    """
    from app.core import tenencia
    from app.core.database import Client, get_session

    session = get_session()
    try:
        consulta = session.query(Client)
        fila = (consulta.filter_by(id=int(argumento)).first()
                if argumento.isdigit() else
                consulta.filter_by(slug=argumento).first())
        if fila is None:
            sys.exit(f"No hay ningún cliente '{argumento}'. Usa su id o su "
                     f"nombre corto.")
        print(f"Trabajando sobre: {fila.nombre} (id {fila.id})\n")
        return tenencia.usar(fila.id)
    finally:
        session.close()


class _SinInquilino:
    """Para poder usar el mismo `with` cuando no se pasó --cliente."""
    def __enter__(self): return None
    def __exit__(self, *_): return False


def main():
    parser = argparse.ArgumentParser(description="Setup y diagnóstico de Meta / WhatsApp Cloud API")
    parser.add_argument(
        "--cliente", default="",
        help="Id o nombre corto del negocio sobre el que trabajar. "
             "Sin esto se usan las credenciales del .env.")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("check", help="Revisa toda la configuración de Meta")
    sub.add_parser("perfil", help="Cómo ven los clientes tu número (nombre y verificación)")
    sub.add_parser("plantillas", help="Plantillas de la cuenta y su estado de aprobación")
    sub.add_parser("subscribe", help="Suscribe la WABA a la App")
    sub.add_parser("unsubscribe", help="Elimina la suscripción de la WABA")

    p_test = sub.add_parser("test-message", help="Envía un mensaje de prueba")
    p_test.add_argument("phone", help="Número destino, formato internacional sin '+'")

    args = parser.parse_args()

    comandos = {
        "check": cmd_check,
        "perfil": cmd_perfil,
        "plantillas": cmd_plantillas,
        "subscribe": cmd_subscribe,
        "unsubscribe": cmd_unsubscribe,
        "test-message": cmd_test_message,
    }

    with (_inquilino(args.cliente) if args.cliente else _SinInquilino()):
        return comandos[args.comando](args)


if __name__ == "__main__":
    sys.exit(main())
