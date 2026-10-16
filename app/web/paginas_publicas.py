"""
PÁGINAS PÚBLICAS
=================
Páginas que cualquiera puede ver, sin clave. Son tres, y las tres existen
porque Meta las pide en la configuración de la App:

    /privacidad      Política de privacidad
    /terminos        Términos del servicio
    /eliminar-datos  Cómo pedir que se borren los datos

Sin la primera, la App no pasa a modo "En vivo" y Meta no entrega los
webhooks de la mayoría de usuarios. Las otras dos son campos del panel de
la App —*Terms of Service URL* y *User data deletion*— y el revisor las
abre durante el App Review. Publicarlas desde el propio bot evita montar
otra web solo para eso, y hace que cada negocio sirva las suyas con su
nombre y su correo.

    ESTO NO ES ASESORÍA LEGAL.

El texto describe lo que este bot hace de verdad con los datos, que es lo
que Meta comprueba. Antes de vender, que lo lea un abogado: las
obligaciones de un tratamiento de datos por encargo no las fija un
docstring.

QUIÉN RESPONDE POR LOS DATOS
----------------------------
El bot es multi-inquilino, así que hay dos capas y conviene no mezclarlas:

- **El negocio contratante es el responsable** de los datos de SUS
  clientes finales. Es quien decide para qué se usan.
- **La plataforma los procesa por encargo suyo**, y solo para prestarle el
  servicio.

Por eso los textos distinguen entre el negocio y la plataforma en vez de
decir "nosotros" para todo. Cambiar esa figura tiene consecuencias
legales; no se hace solo porque suene mejor.
"""

import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app import config

router = APIRouter(tags=["publico"])


# El marco de las tres páginas. Va aquí y no repetido en cada una: eran
# cuarenta líneas de CSS idénticas, y una página legal que se ve distinta
# de las otras dos parece de otro sitio — lo último que conviene en algo
# que va a abrir un revisor de Meta.
_MARCO = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo} · {negocio}</title>
<style>
  body {{ font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
         max-width: 760px; margin: 0 auto; padding: 32px 20px 64px;
         line-height: 1.65; color: #1f2937; background: #fff; }}
  h1 {{ font-size: 1.6rem; margin-bottom: .25rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  h3 {{ font-size: .98rem; margin-top: 1.5rem; }}
  .tenue {{ color: #6b7280; font-size: .9rem; }}
  ul {{ padding-left: 1.2rem; }}
  li {{ margin-bottom: .4rem; }}
  a {{ color: #16a34a; }}
  .aviso {{ background: #f3f4f6; border-left: 3px solid #9ca3af;
            padding: 12px 16px; margin: 24px 0; font-size: .95rem; }}
  .pie {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #e5e7eb;
          font-size: .9rem; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #111827; color: #e5e7eb; }}
    .tenue {{ color: #9ca3af; }}
    .aviso {{ background: #1f2937; border-left-color: #4b5563; }}
    .pie {{ border-top-color: #374151; }}
  }}
</style>
</head>
<body>
{cuerpo}
  <div class="pie">
    {negocio}<br>
    Correo: <a href="mailto:{email}">{email}</a><br>
    Sitio web: <a href="{web}" rel="noopener">{web}</a><br>
    <span class="tenue">
      <a href="/privacidad">Privacidad</a> ·
      <a href="/terminos">Términos</a> ·
      <a href="/eliminar-datos">Eliminar mis datos</a>
    </span>
  </div>
</body>
</html>"""


def _pagina(titulo: str, cuerpo: str) -> HTMLResponse:
    """
    El marco, relleno con los datos de ESTE negocio.

    `config.X` se lee aquí dentro y no en el cuerpo del módulo: al importar
    quedaría congelado con los valores del primer negocio, y todos los
    clientes acabarían sirviendo la política del dueño del bot.
    """
    return HTMLResponse(_MARCO.format(
        titulo=html.escape(titulo),
        negocio=html.escape(config.BUSINESS_NAME),
        email=html.escape(config.BUSINESS_EMAIL),
        web=html.escape(config.BUSINESS_WEBSITE),
        cuerpo=cuerpo))


@router.get("/privacidad", response_class=HTMLResponse)
def privacidad():
    negocio = html.escape(config.BUSINESS_NAME)
    email = html.escape(config.BUSINESS_EMAIL)
    numero = html.escape(config.BUSINESS_WHATSAPP_NUMBER or "")
    al_numero = f" al número {numero}" if numero else ""

    return _pagina("Política de privacidad", f"""
  <h1>Política de privacidad</h1>
  <p class="tenue">{negocio} · Atención por WhatsApp</p>

  <p>Esta política explica qué datos recogemos cuando nos escribes por
     WhatsApp{al_numero}, para qué los usamos y con quién se comparten.</p>

  <h2>Qué datos recogemos</h2>
  <ul>
    <li><strong>Tu número de teléfono</strong>, que WhatsApp nos entrega al
        escribirnos.</li>
    <li><strong>El nombre que nos indiques</strong> en la conversación.</li>
    <li><strong>Los mensajes que intercambias con nosotros</strong>, incluidas
        las opciones que elijas en los menús y los archivos que envíes.</li>
    <li><strong>Los datos de la cita</strong> (día y hora) si agendas una.</li>
  </ul>
  <p>No pedimos ni almacenamos contraseñas, datos bancarios ni documentos de
     identidad. Si nos envías algo de eso por tu cuenta, te pediremos que lo
     elimines del chat.</p>

  <h2>Para qué los usamos</h2>
  <ul>
    <li>Responder a tu consulta y darte seguimiento.</li>
    <li>Agendar, confirmar o modificar citas.</li>
    <li>Llevar un registro interno de solicitudes para poder atenderte mejor.</li>
  </ul>
  <p>No vendemos tus datos ni los usamos para publicidad de terceros.</p>

  <h2>El asistente automático y la inteligencia artificial</h2>
  <p>Parte de la atención la da un asistente automático. Cuando está activo,
     <strong>el texto de tu mensaje se envía a Google</strong> (servicio
     Gemini) para interpretar qué necesitas y ayudar a redactar la
     respuesta. Se envía el mensaje y el contexto necesario para entenderlo;
     no se envía tu número de teléfono.</p>
  <p>El uso que Google haga de esos datos se rige por sus propias
     condiciones. En cualquier momento puedes pedir hablar con una persona y
     te derivamos a un asesor.</p>

  <h2>Con quién se comparten</h2>
  <p>Solo con los servicios que hacen falta para prestarte el servicio:</p>
  <ul>
    <li><strong>Meta (WhatsApp Business Platform)</strong>: transporta los
        mensajes.</li>
    <li><strong>Google (Gemini)</strong>: interpreta tu mensaje y ayuda a
        redactar la respuesta automática, cuando el asistente está activo.</li>
    <li><strong>Google (Calendar y Sheets)</strong>: guarda las citas y el
        registro de solicitudes.</li>
    <li><strong>Nuestro proveedor de alojamiento</strong>: mantiene la base de
        datos donde queda la conversación.</li>
  </ul>

  <h2>Quién responde por tus datos</h2>
  <p>La atención de este número la presta {negocio}, que es quien decide para
     qué se usan tus datos y a quién debes dirigirte.</p>
  <p>La plataforma que hace funcionar el asistente los trata únicamente por
     encargo de {negocio} y para prestarle este servicio: no los usa para
     fines propios ni los cede a nadie más.</p>

  <h2>Cuánto tiempo los guardamos</h2>
  <p>Conservamos la conversación y los datos de contacto mientras exista una
     relación comercial contigo, y después el tiempo que exija la normativa
     aplicable. Puedes pedir que los borremos antes.</p>

  <h2>Tus derechos</h2>
  <p>Puedes pedirnos en cualquier momento que te digamos qué datos tuyos
     tenemos, que los corrijamos o que los eliminemos. También puedes pedir
     que dejemos de escribirte.</p>
  <p>Escríbenos a <a href="mailto:{email}">{email}</a> y lo gestionamos. Cómo
     pedir el borrado, paso a paso, está en
     <a href="/eliminar-datos">Eliminar mis datos</a>.</p>
""")


@router.get("/terminos", response_class=HTMLResponse)
def terminos():
    negocio = html.escape(config.BUSINESS_NAME)
    email = html.escape(config.BUSINESS_EMAIL)

    return _pagina("Términos del servicio", f"""
  <h1>Términos del servicio</h1>
  <p class="tenue">{negocio} · Atención automatizada por WhatsApp</p>

  <div class="aviso">
    <strong>Dos públicos, dos secciones.</strong> La primera es para quien
    escribe al WhatsApp del negocio. La segunda, para el negocio que
    contrata el servicio.
  </div>

  <h2>1. Si escribes al WhatsApp del negocio</h2>
  <p>Al escribir aceptas que parte de la atención la dé un asistente
     automático y que la conversación quede registrada, como se explica en la
     <a href="/privacidad">política de privacidad</a>.</p>
  <ul>
    <li>El asistente puede equivocarse. Lo que diga <strong>no es una oferta
        vinculante</strong>: los precios, la disponibilidad y las condiciones
        los confirma una persona del negocio.</li>
    <li>Puedes pedir hablar con una persona en cualquier momento.</li>
    <li>No uses este canal para urgencias médicas o de seguridad.</li>
    <li>No envíes por aquí contraseñas, datos de tarjetas ni documentos de
        identidad.</li>
  </ul>

  <h2>2. Si contratas el servicio para tu negocio</h2>

  <h3>2.1 Qué se presta</h3>
  <p>Un asistente de WhatsApp que atiende a tus clientes, más un panel para
     que tu equipo lea las conversaciones, responda y consulte los contactos.
     El alcance concreto, el precio y la duración son los de tu contrato o tu
     propuesta aceptada; estos términos no los sustituyen.</p>

  <h3>2.2 Los datos de tus clientes son tuyos</h3>
  <p>Tú eres el <strong>responsable</strong> de los datos de las personas que
     escriben a tu WhatsApp: decides para qué se usan y respondes ante ellas.
     La plataforma actúa como <strong>encargada del tratamiento</strong> y los
     trata solo por instrucción tuya y para prestarte el servicio.</p>
  <ul>
    <li>No se usan para fines propios de la plataforma.</li>
    <li>No se ceden a terceros salvo los proveedores necesarios, que están
        listados en la política de privacidad.</li>
    <li>Cada negocio ve únicamente sus datos. El aislamiento está aplicado
        también en la base de datos, no solo en la aplicación.</li>
    <li>Al terminar el servicio puedes pedir una copia y el borrado.</li>
  </ul>

  <h3>2.3 Lo que te toca a ti</h3>
  <ul>
    <li>Cumplir las <strong>políticas de WhatsApp Business y de Meta</strong>.
        Un incumplimiento puede costar el bloqueo de tu número, y eso lo
        decide Meta.</li>
    <li>Tener una base legítima para escribir a esas personas y atender sus
        derechos cuando te los pidan.</li>
    <li>No usar el servicio para spam, engaños ni contenido ilegal.</li>
    <li>Custodiar las claves de acceso al panel de tu equipo.</li>
  </ul>

  <h3>2.4 Lo que depende de terceros</h3>
  <p>El servicio se apoya en Meta, en Google y en un proveedor de
     alojamiento. Una caída, un cambio de condiciones o una decisión de
     cualquiera de ellos —incluido el bloqueo de un número— puede afectar al
     servicio y <strong>queda fuera de nuestro control</strong>.</p>
  <p>Desde el 1 de octubre de 2026 Meta cobra los mensajes de servicio. Ese
     costo lo factura Meta según su tarifa y no está incluido en el precio del
     servicio, salvo que tu contrato diga otra cosa.</p>

  <h3>2.5 Disponibilidad</h3>
  <p>Se trabaja para que el servicio esté disponible de forma continua, pero
     no se garantiza que funcione sin interrupciones ni sin errores. Las
     paradas de mantenimiento se avisan cuando se pueden prever.</p>

  <h3>2.6 Suspensión y terminación</h3>
  <p>El servicio puede suspenderse por falta de pago o por un uso que incumpla
     estos términos o las políticas de Meta. Cualquiera de las dos partes
     puede terminar la relación según lo pactado en el contrato.</p>

  <h3>2.7 Cambios</h3>
  <p>Estos términos pueden cambiar. Un cambio relevante se avisa por el correo
     de contacto de la cuenta antes de que aplique.</p>

  <h3>2.8 Ley aplicable</h3>
  <p>Se aplica la ley colombiana, incluida la normativa de protección de datos
     personales (Ley 1581 de 2012 y sus normas de desarrollo).</p>

  <h2>Contacto</h2>
  <p>Para cualquier duda sobre estos términos, escribe a
     <a href="mailto:{email}">{email}</a>.</p>
""")


@router.get("/eliminar-datos", response_class=HTMLResponse)
def eliminar_datos():
    """
    Las instrucciones de borrado, en su propia URL.

    Meta pide en el panel de la App una dirección donde se explique cómo
    pedir la eliminación de datos, y el revisor la abre. Tiene que
    entenderse sin saber nada del sistema, así que aquí no se habla de
    tablas ni de cuentas: se dice qué escribir y a dónde.
    """
    negocio = html.escape(config.BUSINESS_NAME)
    email = html.escape(config.BUSINESS_EMAIL)
    numero = html.escape(config.BUSINESS_WHATSAPP_NUMBER or "")
    entre_parentesis = f" ({numero})" if numero else ""

    return _pagina("Eliminar mis datos", f"""
  <h1>Cómo pedir que se eliminen tus datos</h1>
  <p class="tenue">{negocio} · Atención por WhatsApp</p>

  <p>Puedes pedir que borremos todo lo que tenemos de ti. No hace falta un
     motivo ni un formulario: basta con pedirlo.</p>

  <h2>Por WhatsApp</h2>
  <p>Escribe <strong>"eliminar mis datos"</strong> al mismo número con el que
     hablas{entre_parentesis} y pide hablar con una persona. Como escribes
     desde tu propio número, no hace falta que demuestres nada más.</p>

  <h2>Por correo</h2>
  <p>Escribe a <a href="mailto:{email}">{email}</a> con el asunto
     <strong>"Eliminar mis datos"</strong> e incluye el número de teléfono con
     el que nos escribiste. Podemos pedirte una comprobación sencilla para
     asegurarnos de que ese número es tuyo: si no, cualquiera podría borrar la
     conversación de otra persona.</p>

  <h2>Qué se elimina</h2>
  <ul>
    <li>La conversación completa: los mensajes que enviaste y los que
        recibiste.</li>
    <li>Los archivos que hayas enviado.</li>
    <li>Tu nombre, tu número y las notas o etiquetas internas asociadas.</li>
    <li>El registro de las solicitudes que dejaste.</li>
  </ul>

  <h2>Qué puede quedar, y por qué</h2>
  <ul>
    <li><strong>Las citas ya agendadas</strong>, si el borrado se pide con una
        cita pendiente: hacen falta para cumplir con esa cita. Se eliminan
        después, si lo pides.</li>
    <li><strong>Lo que la ley obligue a conservar</strong>, como los soportes
        de una operación comercial. Se guarda solo el tiempo obligatorio y no
        se usa para nada más.</li>
    <li><strong>Copias de seguridad</strong>, que se sobrescriben en su ciclo
        normal.</li>
    <li><strong>Lo que tenga WhatsApp en tu propio teléfono.</strong> Eso está
        en tu dispositivo y solo lo borras tú, desde la aplicación.</li>
  </ul>

  <h2>Cuánto tarda</h2>
  <p>Se atiende en un plazo máximo de <strong>30 días</strong>, y normalmente
     mucho antes. Te confirmamos cuando esté hecho.</p>

  <h2>Si escribiste al WhatsApp de otro negocio</h2>
  <p>Esta plataforma hace funcionar el asistente de varios negocios, y cada
     uno responde por los datos de sus propios clientes. Si tu conversación
     fue con otro negocio, pídeselo a él por su mismo WhatsApp: no podemos
     decidir sobre datos que no son nuestros. Si no consigues respuesta,
     escríbenos a <a href="mailto:{email}">{email}</a> y te ayudamos a
     localizar a quién dirigirte.</p>
""")
