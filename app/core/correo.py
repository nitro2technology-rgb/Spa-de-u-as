"""
AVISOS POR CORREO
==================
Le manda un correo al área que corresponda cuando entra un lead.

POR QUÉ EXISTE, HABIENDO WHATSAPP
---------------------------------
Porque WhatsApp **no sirve** para avisar a un equipo, y costó descubrirlo:

  · Solo se puede escribir texto libre a quien te haya escrito en las
    últimas 24 h. El de Ventas nunca le escribe al bot, así que su ventana
    está cerrada desde el primer minuto.
  · Fuera de esa ventana hace falta una plantilla aprobada por Meta.
  · Y una plantilla es un mensaje COBRADO, así que Meta la rechaza si la
    cuenta del negocio no tiene moneda y método de pago configurados.

Tres puertas, cada una capaz de bloquear el aviso por su cuenta, y las
tres fallando en silencio. El correo no tiene ninguna: llega siempre, no
cuesta nada, y la persona puede reenviarlo o archivarlo.

    NO SUSTITUYE AL BOT. El bot sigue atendiendo por WhatsApp igual; lo
    que cambia es por dónde se entera el negocio de que entró un cliente.

LA CUENTA DESDE LA QUE SE ENVÍA ES DE LA PLATAFORMA
---------------------------------------------------
Una sola, en variables de entorno, para TODOS los clientes.

    SMTP_HOST, SMTP_PUERTO, SMTP_USUARIO, SMTP_CLAVE, SMTP_DESDE

Es la decisión que hace esto replicable: **un cliente nuevo no configura
nada.** Escribe el correo de cada área en su panel y ya recibe avisos. La
alternativa —credenciales de correo por negocio— sería otra credencial que
custodiar y otro paso del alta donde atascarse, para algo que el
destinatario ni siquiera ve.

Lo que sí es de cada negocio es **el nombre que se lee**: el correo llega
como "Panadería Doña Rosa <avisos@nitro2tech.com>". La dirección es
nuestra porque es la única desde la que estamos autorizados a enviar
—falsear el remitente es la vía rápida al spam— pero en la bandeja de
quien lo recibe pone el nombre de su negocio.

    ⚠️  EL TECHO A VIGILAR ES EL DE ENVÍOS DIARIOS.

    Un Gmail normal admite ~500 correos al día y uno de Workspace ~2.000,
    contando los de TODOS los clientes juntos. Con unos pocos negocios
    sobra de largo; el día que no, la salida es un servicio de correo
    transaccional (Resend, SendGrid) con el dominio propio: sube el techo,
    entrega mejor, y **el cliente sigue sin configurar nada** porque solo
    cambian estas cinco variables.

Sin `SMTP_HOST` y `SMTP_DESDE` esto no hace nada y el bot funciona igual,
como con las claves de push.

SIN DEPENDENCIAS NUEVAS
-----------------------
`smtplib` y `email` son de la librería estándar. Un servicio de correo
transaccional (Resend, SendGrid) tendría mejor entregabilidad, pero
añadiría una dependencia y una cuenta más que administrar para algo que
son cuatro avisos al día.
"""

import smtplib
import threading
from email.message import EmailMessage
from email.utils import formataddr

from app import config
from app.core import tenencia

# Cuánto se espera al servidor de correo. Corto: esto corre en un hilo,
# pero un hilo colgado por minuto tampoco es gratis.
TIMEOUT = 20


def configurado() -> bool:
    """¿Se puede enviar? Hacen falta el servidor y la dirección remitente."""
    return bool(config.SMTP_HOST and config.SMTP_DESDE)


def avisar(destinatarios: list, asunto: str, cuerpo: str, html: str = "",
           remitente: str = ""):
    """
    Manda el aviso sin bloquear a quien llama.

    Vuelve enseguida: el trabajo real va en un hilo. Quien llama está
    atendiendo un webhook de Meta, que tiene ocho segundos para responder
    antes de que Meta lo reintente y el cliente reciba un duplicado.

    `envolver_para_hilo` NO es opcional: un `Thread` nuevo arranca con el
    contexto vacío, y sin él este envío no sabría de qué negocio es. Ver
    `app/core/tenencia.py`.
    """
    destinatarios = [d for d in (destinatarios or []) if d and "@" in d]
    if not destinatarios or not configurado():
        return

    threading.Thread(
        target=tenencia.envolver_para_hilo(_enviar_o_anotar),
        args=(destinatarios, asunto, cuerpo, html, remitente),
        daemon=True,
        name="correo-aviso",
    ).start()


def _enviar_o_anotar(destinatarios: list, asunto: str, cuerpo: str,
                     html: str = "", remitente: str = ""):
    """
    El envío del hilo, y el rastro si falla.

    Un fallo aquí no tiene a quién subir: el webhook que lo lanzó ya
    respondió. Antes quedaba una traza en el log del hosting y nada más, o
    sea que un servidor de correo caído dejaba a las áreas sin avisos sin
    ninguna señal donde se mira. Se anota como el último aviso no
    entregado, que es lo que enseña la ficha del negocio en /superadmin.
    """
    try:
        _enviar(destinatarios, asunto, cuerpo, html, remitente)
    except Exception as e:
        motivo = f"correo: {_explicar(e)}"
        print(f"[correo] El aviso a {', '.join(destinatarios)} NO salió: {motivo}")
        try:
            from app.bot import notificaciones
            from app.core.database import ahora_utc
            notificaciones.anotar_no_entregado(
                ", ".join(destinatarios), motivo[:300],
                cuando=ahora_utc().isoformat(timespec="minutes"))
        except Exception as e2:
            print(f"[correo] Tampoco se pudo anotar el fallo: {e2}")


def enviar_ahora(destinatarios: list, asunto: str, cuerpo: str,
                 html: str = "", remitente: str = "") -> tuple:
    """
    Igual, pero esperando el resultado. Devuelve `(ok, explicación)`.

    Existe para el botón de prueba del super-admin: ahí el objetivo es
    justamente **saber si salió**, así que no puede irse a un hilo y
    devolver "ya veremos".
    """
    destinatarios = [d for d in (destinatarios or []) if d and "@" in d]
    if not destinatarios:
        return False, "no hay ninguna dirección de correo válida"
    if not configurado():
        return False, ("la plataforma no tiene servidor de correo "
                       "configurado (SMTP_HOST y SMTP_DESDE)")

    try:
        _enviar(destinatarios, asunto, cuerpo, html, remitente)
        return True, "enviado"
    except Exception as e:
        return False, _explicar(e)


def _explicar(e: Exception) -> str:
    """El fallo de SMTP, en algo que se pueda leer sin ser programador."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return ("el servidor de correo rechazó el usuario o la clave. Si es "
                "Gmail, hace falta una contraseña de aplicación, no la del "
                "correo.")
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "el servidor rechazó la dirección de destino: revisa que esté bien escrita."
    if isinstance(e, smtplib.SMTPSenderRefused):
        return f"el servidor no acepta enviar desde {config.SMTP_DESDE}."
    return f"{type(e).__name__}: {e}"


def armar(destinatarios: list, asunto: str, cuerpo: str,
          html: str = "", remitente: str = "") -> EmailMessage:
    """
    El correo montado, sin enviarlo.

    Está separado del envío para poder comprobar lo que se manda —los
    enlaces, el asunto, que lleve versión HTML— sin levantar un servidor
    de correo. El primer intento de probarlo con un SMTP de mentira dio un
    fallo del propio servidor de mentira, que es exactamente el tipo de
    prueba que no vale la pena mantener.
    """
    mensaje = EmailMessage()
    # En UNA línea. El asunto lleva el nombre del cliente, que lo escribe
    # él, y un salto de línea en una cabecera hace que `EmailMessage`
    # levante ValueError: dentro del hilo, eso era un aviso que no salía.
    mensaje["Subject"] = " ".join(str(asunto or "").split())

    # EL NOMBRE QUE SE VE ES EL DEL NEGOCIO, no el de la plataforma.
    #
    # Quien recibe esto trabaja en la panadería, no en Nitro: en su bandeja
    # tiene que leer "Panadería Doña Rosa", que es lo que le dice de un
    # vistazo qué es. La DIRECCIÓN sigue siendo la nuestra y tiene que
    # serlo — es la única desde la que estamos autorizados a enviar, y
    # falsear el remitente es la forma más rápida de acabar en spam.
    mensaje["From"] = formataddr((" ".join(str(remitente or config.SMTP_NOMBRE
                                               or "Nitro 2Tech").split()),
                                  config.SMTP_DESDE))

    # LOS DESTINATARIOS VAN EN `To`, y la cuenta que envía NO se pone.
    #
    # Estuvo con `To` a la dirección remitente y los destinos en copia
    # oculta, por miedo a que un correo sin destinatario visible cayera en
    # spam. Tenía dos problemas: **le llegaba copia de todo a la cuenta
    # que envía** —que no la pidió nadie— y el `Bcc` no protegía a nadie,
    # porque cada área recibe su propio correo por separado y la lista
    # siempre trae una sola dirección.
    mensaje["To"] = ", ".join(destinatarios)

    mensaje.set_content(cuerpo)
    if html:
        mensaje.add_alternative(html, subtype="html")

    return mensaje


def _enviar(destinatarios: list, asunto: str, cuerpo: str, html: str = "",
            remitente: str = ""):
    """El envío de verdad. Levanta excepción si falla."""
    mensaje = armar(destinatarios, asunto, cuerpo, html, remitente)

    puerto = int(config.SMTP_PUERTO or 587)

    # 465 es SSL desde el primer byte; 587 empieza en claro y sube a TLS
    # con STARTTLS. Mandar por el puerto equivocado da un error que no dice
    # que el problema era el puerto.
    if puerto == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, puerto, timeout=TIMEOUT) as s:
            _autenticar(s)
            s.send_message(mensaje)
    else:
        with smtplib.SMTP(config.SMTP_HOST, puerto, timeout=TIMEOUT) as s:
            s.starttls()
            _autenticar(s)
            s.send_message(mensaje)


def _autenticar(servidor):
    """Algunos relays internos no piden clave; con usuario, se envía."""
    if config.SMTP_USUARIO:
        servidor.login(config.SMTP_USUARIO, config.SMTP_CLAVE or "")
