"""
EL EDITOR DE CONTENIDO DE UN NEGOCIO
=====================================
Lo que un cliente dice y ofrece —sus textos, su menú, sus enlaces, sus
precios— vive en `clients.negocio_config`, un JSON con la forma del
`negocio.toml`. Hasta ahora se editaba escribiendo el TOML a mano y
cargándolo con un script.

Este módulo lo convierte en un formulario. Es lo que permite adaptar el
bot de un cliente **sin abrir un editor de texto ni la terminal**.

    DOS REGLAS QUE SOSTIENEN TODO ESTO.

**1. Lo que el formulario no cubre, no se toca.** `leer_formulario` parte
de una copia de la configuración que ya tenía y solo sobrescribe lo que
hay en pantalla. Las secciones que no salen aquí —las pestañas del Sheet,
los orígenes, la marca— sobreviven intactas. Sin eso, guardar una vez
borraría media configuración sin que nadie se diera cuenta hasta que un
cliente lo notara.

**2. Nada se guarda sin validarse.** Quien llama a esto arma una
`ConfiguracionCliente` con el resultado ANTES de escribirlo en la base. Es
lo mismo que detecta una opción del menú que apunta a un enlace que no
existe, y es lo que hace que sea seguro dejar esto en manos de alguien que
no programa: lo peor que puede pasar es que no deje guardar y explique por
qué.

POR QUÉ ES HTML A MANO
----------------------
Igual que el resto del panel: sin plantillas, sin build, sin dependencias.
El único JavaScript es el que añade una fila nueva al menú, y si estuviera
apagado el formulario seguiría sirviendo para editar lo que ya existe.
"""

import copy
import html

# Quién va en una sola línea y quién no. Vive en `mapa` porque es donde
# están las demás reglas de formato de WhatsApp, y se importa aquí para
# que los DOS editores no puedan discrepar: antes cada uno lo decidía por
# su cuenta y no coincidían, así que el mismo texto salía en cuadro en una
# pantalla y en renglón en la otra —y en la del renglón perdía los saltos
# de línea al guardar—.
from app.web.mapa import cabe_en_una_linea

# Lo que el bot sabe hacer cuando alguien toca una opción. Sale de
# `bot_logic._aplicar_opcion`; si algún día se añade una acción nueva
# allí, hay que nombrarla aquí o no se podrá elegir desde el panel.
ACCIONES = [
    ("submenu", "Abrir otro menú de opciones"),
    ("info", "Mandar un texto (y un enlace, si tiene)"),
    ("enlace", "Mandar un enlace"),
    ("cita", "Agendar una cita"),
    ("humano", "Pasar a un asesor"),
    ("menu", "Volver al menú principal"),
    ("terminar", "Despedirse y cerrar"),
    ("cancelar", "Cancelar una cita"),
    ("reagendar", "Cambiar una cita de día"),
]

# Los textos del bot, con nombre humano. El orden es el del recorrido de
# una conversación, no el del archivo: quien edita esto piensa "qué le
# digo primero", no "qué clave va antes".
#
# **Aquí no se dice si el campo es cuadro o renglón.** Lo dice
# `cabe_en_una_linea`, y por eso no puede discrepar del mapa. Cuando se
# decidía aquí, a mano, había mensajes enteros marcados como renglón —el
# "cómo pregunta qué necesita", el cuerpo de cada opción del menú— y un
# renglón no admite saltos de línea: los borraba al guardar.
CAMPOS_TEXTOS = [
    ("bienvenida", "Saludo a quien escribe por primera vez"),
    ("bienvenida_de_vuelta", "Saludo a quien ya había escrito antes"),
    ("preguntar_necesidad", "Cómo pregunta qué necesita"),
    ("menu_boton", "Etiqueta del botón que abre el menú"),
    ("menu_seccion", "Título de la lista de opciones"),
    ("boton_volver_menu", "Botón de volver al menú principal"),
    ("boton_atras", "Botón de volver atrás"),
    ("no_entendi",
     "Cuando no entiende lo que le escriben o no elige opción"),
    ("otra_consulta", "Cuando la consulta no encaja en el menú"),
    ("cierre", "Cómo pregunta si necesita algo más"),
    ("despedida", "Despedida"),
    ("enlace_web", "Mensaje que acompaña al enlace de la web"),
    ("paso_a_asesor", "Cuando ya avisó a una persona"),
    ("aviso_asesor", "Cuando está conectando con un asesor"),
    ("cita_preguntar_dia", "Al empezar a agendar: qué día"),
    ("cita_boton_dias", "Etiqueta del botón de días"),
    ("cita_seccion_dias", "Título de la lista de días"),
    ("cita_dia_descripcion", "Descripción de cada día"),
    ("cita_preguntar_hora", "Al elegir día: qué hora"),
    ("cita_boton_horarios", "Etiqueta del botón de horarios"),
    ("cita_seccion_horarios", "Título de la lista de horarios"),
    ("cita_confirmada", "Confirmación de la cita"),
    ("cita_horario_tomado", "Si le quitan el horario mientras elegía"),
    ("cita_dia_lleno", "Si el día se llenó"),
    ("cita_sin_disponibilidad", "Si no hay horarios en semanas"),
    ("cita_respaldo", "Si Google falla y la cita se anota a mano"),
    ("cita_cancelada", "Al cancelar una cita"),
    ("cita_reagendar", "Al cambiar una cita de día"),
    ("cita_no_encontrada", "Si no encuentra la cita que quiere cambiar"),
    ("media_imagen", "Al recibir una foto"),
    ("media_audio", "Al recibir una nota de voz"),
    ("media_documento", "Al recibir un documento"),
    ("media_otro", "Al recibir otra cosa"),
    ("media_boton_menu", "Botón de menú tras un archivo"),
    ("media_boton_asesor", "Botón de asesor tras un archivo"),
    ("media_detalle_asesor", "Nota interna al pedir asesor con archivo"),
]

CAMPOS_AVISOS = [
    ("cita", "Cuando alguien agenda"),
    ("consulta", "Cuando alguien deja una consulta"),
    ("pide_asesor", "Cuando alguien pide hablar con una persona"),
    ("cancelacion", "Cuando alguien cancela"),
    ("reagenda", "Cuando alguien cambia su cita"),
]

# Campos de una opción del menú: (clave, etiqueta, ayuda).
CAMPOS_OPCION = [
    ("title", "Lo que se lee en el botón",
     "Máximo 20 caracteres si le llega como botón, 24 si le llega como "
     "fila de lista. Pasado eso WhatsApp no manda el mensaje."),
    ("description", "Texto pequeño debajo", ""),
    ("mensaje", "Lo que responde al elegirla", ""),
    ("servicio", "Cómo se llama este servicio en los informes", ""),
    ("paso", "Cómo se llama este paso en el recorrido", ""),
    ("pregunta", "Qué pregunta después", ""),
]


def _e(valor) -> str:
    return html.escape(str(valor if valor is not None else ""))


# Los textos que el CLIENTE lee: los de la conversación, los avisos, el
# cuerpo de cada opción del menú. Ver `_como_se_escribio`.
CLAVES_DE_MENSAJE = frozenset({"mensaje", "pregunta"})


def _como_se_escribio(valor) -> str:
    """
    Un texto que se manda por WhatsApp, tal cual lo escribieron.

    Hace las dos cosas que el `.strip()` de toda la vida hacía mal con un
    mensaje:

    **1. Quita los retornos de carro.** Un navegador manda el contenido de
    un `<textarea>` con los saltos en `\\r\\n`, no en `\\n`. Ese `\\r`
    sobrante se guardaba en la base y viajaba dentro del mensaje: no se
    ve, no da error, y va sumándose en cada guardado.

    **2. Respeta los espacios y las líneas en blanco.** Si alguien separa
    dos párrafos con una línea vacía, o sangra una lista, es porque quiere
    que le llegue así al cliente — WhatsApp lo respeta tal cual. Lo único
    que se recorta es un valor que solo tiene espacios: eso es un campo
    vacío escrito con la barra espaciadora, y tiene que contar como vacío
    para que el bot caiga en su texto por defecto y no mande un mensaje en
    blanco.
    """
    texto = str(valor if valor is not None else "")
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return "" if not texto.strip() else texto


def _lineas(valor) -> str:
    """Una lista, como texto de una línea por elemento."""
    if isinstance(valor, list):
        return "\n".join(str(v) for v in valor)
    return str(valor or "")


def _de_lineas(texto: str) -> list:
    return [l.strip() for l in (texto or "").splitlines() if l.strip()]


# ══════════════════════════════════════════════════════════════════════
#  PINTAR
# ══════════════════════════════════════════════════════════════════════

def pintar(negocio: dict, cupo_avisos: int = 3) -> str:
    """
    El formulario entero, ya con los valores de este negocio.

    `cupo_avisos` es cuántas áreas de aviso le tocan (ver
    `config_cliente.cupo_de_destinos`). Llega por parámetro y no se
    calcula aquí porque este módulo no conoce al cliente: solo ve su
    contenido, que es lo que le permite no tocar la base.
    """
    enlaces = negocio.get("enlaces", {}) or {}
    precios = negocio.get("precios", {}) or {}

    return "".join([
        _bloque_negocio(negocio),
        _bloque_textos(negocio),
        _bloque_menu(negocio, enlaces, precios),
        _bloque_enlaces(enlaces),
        _bloque_precios(precios),
        _bloque_avisos(negocio, cupo_avisos),
        _bloque_ia(negocio),
        _bloque_horario(negocio),
        _PLANTILLA,
    ])


# El índice del editor: qué bloques hay y en qué orden se pintan. La
# lista vive AQUÍ y no en `superadmin.py` porque es la misma que arma
# `pintar()`: separarlas garantizaba que un día el índice enseñara un
# bloque que ya no existe, o se dejara fuera uno nuevo.
#
# El tercer elemento dice de dónde sale el número que se enseña al lado.
# Se enseña "donde ayuda", no en todos: en los textos y en el menú dice
# cuánto hay ahí dentro antes de entrar, y en el horario no diría nada.
BLOQUES_DEL_EDITOR = (
    ("bloque-negocio",  "El negocio",          None),
    ("bloque-textos",   "Lo que dice el bot",  "textos"),
    ("bloque-menu",     "El menú",             "menu"),
    ("bloque-cierre",   "Opciones de cierre",  "cierre"),
    ("bloque-enlaces",  "Enlaces",             "enlaces"),
    ("bloque-precios",  "Bloques de precios",  "precios"),
    ("bloque-avisos",   "Avisos al dueño",     None),
    ("bloque-ia",       "El carácter del bot", None),
    ("bloque-horario",  "Horario y conversación", None),
)


def indice(negocio: dict) -> str:
    """
    La columna de la izquierda del editor: los nueve bloques.

    Es lo que convierte una página de dos metros en algo que se recorre.
    Sin ella, llegar a "Horario" es bajar por encima de treinta y cuatro
    textos y de todo el menú.

    Son anclas de verdad (`#bloque-textos`), no JavaScript: se comparten
    por chat y el botón de atrás funciona. El bloque al que se ha
    saltado se resalta con `.caja:target` — el navegador ya sabe cuál es
    y no hace falta contarle nada.
    """
    filas = []
    for ident, nombre, clave in BLOQUES_DEL_EDITOR:
        cuantos = ""
        if clave:
            valor = negocio.get(clave)
            if clave == "textos":
                # Los que hay CAMPO para escribir, no los que están
                # escritos: el número dice cuánto hay que revisar.
                cuantos = str(len(CAMPOS_TEXTOS))
            elif isinstance(valor, (list, dict)):
                cuantos = str(len(valor))
        cuantos = f'<span class="cuantos">{cuantos}</span>' if cuantos else ""
        filas.append(f'<a href="#{ident}">{nombre}{cuantos}</a>')
    return "".join(filas)


def _campo(nombre, etiqueta, valor, ayuda="", area=False, filas=3):
    # ⚠️  El salto de línea pegado a `<textarea>` es OBLIGATORIO. El HTML
    # se come el primero que va justo después de la etiqueta de apertura,
    # así que un texto que empiece por una línea en blanco la perdía cada
    # vez que se abría esta pantalla — y el siguiente guardado la escribía
    # ya sin ella. Con este salto de más, el del contenido se conserva.
    control = (f'<textarea name="{nombre}" rows="{filas}">\n{_e(valor)}</textarea>'
               if area else
               f'<input type="text" name="{nombre}" value="{_e(valor)}">')
    pie = f'<p class="tenue">{ayuda}</p>' if ayuda else ""
    return f'<label>{_e(etiqueta)}</label>{control}{pie}'


def _bloque_negocio(n: dict) -> str:
    d = n.get("negocio", {}) or {}
    return f"""
    <div class="caja" id="bloque-negocio">
      <h2>El negocio</h2>
      <div class="rejilla">
        <div>{_campo("negocio-nombre", "Nombre", d.get("nombre"))}</div>
        <div>{_campo("negocio-whatsapp", "WhatsApp público", d.get("whatsapp"))}</div>
        <div>{_campo("negocio-email", "Correo", d.get("email"))}</div>
        <div>{_campo("negocio-web", "Página web", d.get("web"))}</div>
        <div>{_campo("negocio-boton_web", "Texto del botón de la web", d.get("boton_web"))}</div>
      </div>
    </div>"""


# Cuantos textos se pintan abiertos. El bloque tiene mas de treinta, y
# una pantalla que empieza con treinta cuadros iguales no se lee: se
# abandona. Los primeros son los que se tocan de verdad —la bienvenida,
# el "no te entendi"—, asi que abiertos van esos.
TEXTOS_A_LA_VISTA = 3


def _bloque_textos(n: dict) -> str:
    t = n.get("textos", {}) or {}

    def fila(clave, etiqueta):
        return (f'<div class="campo">'
                f'{_campo(f"texto-{clave}", etiqueta, t.get(clave), filas=3, area=not cabe_en_una_linea(clave))}'
                f'</div>')

    primeros = "".join(fila(*c) for c in CAMPOS_TEXTOS[:TEXTOS_A_LA_VISTA])
    resto = CAMPOS_TEXTOS[TEXTOS_A_LA_VISTA:]

    # Un <details> y no una pestana: sus campos siguen DENTRO del
    # formulario aunque este cerrado, asi que se envian igual. Con
    # pestanas de JavaScript habria que acordarse de eso, y el dia que se
    # olvidara se guardarian vacios los treinta que no se abrieron.
    plegados = "" if not resto else f"""
      <details class="mas">
        <summary>Ver los {len(resto)} textos restantes</summary>
        <div class="dos-columnas">{"".join(fila(*c) for c in resto)}</div>
      </details>"""

    filas = f'<div class="dos-columnas">{primeros}</div>{plegados}'
    return f"""
    <div class="caja" id="bloque-textos">
      <h2>Lo que dice el bot</h2>
      <p class="tenue">Los huecos entre llaves se rellenan solos:
         <code>{{name}}</code> es el nombre del cliente,
         <code>{{negocio}}</code> el del negocio,
         <code>{{date}}</code> la fecha de la cita.
         Déjalos tal cual si no sabes qué hacen.</p>
      {filas}
    </div>"""


def _bloque_avisos(n: dict, cupo_avisos: int = 3) -> str:
    a = n.get("avisos", {}) or {}
    filas = "".join(
        f'<div class="campo">{_campo(f"aviso-{clave}", etiqueta, a.get(clave), area=True, filas=2)}</div>'
        for clave, etiqueta in CAMPOS_AVISOS)

    # La plantilla va aparte de los textos de arriba a propósito: no es
    # algo que el dueño redacte, es el nombre de una plantilla aprobada en
    # Meta. Sin ella, todo lo de arriba deja de llegar en cuanto pasan 24 h
    # desde el último mensaje del dueño al bot — y falla en silencio, que
    # es lo que la hace fácil de olvidar.
    plantilla = f"""
      <h3>Cuando han pasado más de 24 horas</h3>
      <p class="tenue">WhatsApp solo deja escribirle texto libre a alguien
         durante las 24 h siguientes a su último mensaje. Pasado ese plazo,
         el aviso solo sale si hay una <strong>plantilla aprobada</strong>
         en Meta, y si no la hay <strong>el lead se pierde sin avisar</strong>.
         Para ver cuáles tienes aprobadas:
         <code>python scripts/meta_setup.py plantillas</code>.</p>
      <div class="rejilla">
        <div>{_campo("aviso-plantilla", "Nombre de la plantilla",
                     a.get("plantilla"),
                     "Déjalo vacío solo si no tienes ninguna aprobada.")}</div>
        <div>{_campo("aviso-plantilla_idioma", "Idioma de la plantilla",
                     a.get("plantilla_idioma"),
                     "Como aparece en Meta: 'es' y 'es_ES' son distintas. "
                     "Vacío es 'es'.")}</div>
      </div>
      <p class="tenue">La plantilla tiene que esperar <strong>cuatro</strong>
         variables, en este orden: tipo de aviso, nombre, teléfono y
         detalle. Si espera otro número, Meta rechaza el envío.</p>"""

    return f"""
    <div class="caja" id="bloque-avisos">
      <h2>Avisos al dueño del negocio</h2>
      <p class="tenue">Lo que le llega por WhatsApp al dueño cuando pasa
         algo. No lo ve el cliente final.</p>
      <div class="dos-columnas">{filas}</div>
      {plantilla}
    </div>
    """


def _opciones_del_menu(n: dict) -> list:
    """
    Las opciones de PRIMER NIVEL del menú: `[(id, título)]`.

    Solo el primer nivel, y no todo el árbol, porque es lo que se guarda
    en `Contact.servicio` y por tanto lo único con lo que se puede
    enrutar. Ofrecer un submenú aquí sería ofrecer una casilla que nunca
    se cumpliría.
    """
    salida = []
    for opcion in (n.get("menu") or []):
        if not isinstance(opcion, dict):
            continue
        ident = str(opcion.get("id") or "").strip()
        if ident:
            salida.append((ident, str(opcion.get("title") or ident)))
    return salida


# Los indicativos que se sugieren al escribir. Es una LISTA DE SUGERENCIAS,
# no un desplegable cerrado: un `<select>` con los países de hoy sería un
# techo invisible el día que un cliente tenga un número de un país que no
# está — el mismo patrón de §3.11 del documento. Con `datalist` se puede
# escribir cualquiera y estos salen a mano.
INDICATIVOS = [
    ("57", "Colombia"), ("34", "España"), ("52", "México"),
    ("1", "EE.UU. / Canadá"), ("54", "Argentina"), ("56", "Chile"),
    ("51", "Perú"), ("593", "Ecuador"), ("58", "Venezuela"),
    ("507", "Panamá"), ("506", "Costa Rica"), ("55", "Brasil"),
]

LISTA_INDICATIVOS = (
    '<datalist id="indicativos">'
    + "".join(f'<option value="{c}">{c} · {p}</option>' for c, p in INDICATIVOS)
    + "</datalist>"
)


def _partir_numero(d: dict) -> tuple:
    """
    Un destino guardado, separado en `(indicativo, número local)` para
    pintarlo en los dos cuadros.

    Lo guardado nuevo ya viene partido. Lo guardado ANTES de que existieran
    los dos cuadros trae solo `numero`, con todo junto: eso se pinta entero
    en el cuadro del número y con el país vacío. No se intenta adivinar
    dónde acaba el indicativo — no se puede, `57` y `571` son los dos
    prefijos válidos y partir por el sitio equivocado deja un número que
    parece bien y no existe.

    Al guardar se vuelve a unir, y el que venía entero se reconoce por su
    longitud (ver `config_cliente._leer_destinos`), así que no se duplica.
    """
    indicativo = str(d.get("indicativo") or "")
    numero = str(d.get("numero") or "")

    if indicativo and numero.startswith(indicativo):
        # Guardado con el formato viejo pero con indicativo anotado: se
        # quita para no enseñarlo dos veces.
        return indicativo, numero[len(indicativo):]

    return indicativo, numero


def bloque_destinos(n: dict, cupo: int = 3, rechazos: dict = None) -> str:
    """
    A qué área va cada tipo de aviso. Una tarjeta por área.

    Un negocio con áreas —Ventas, Soporte, Contratos— no quiere que las
    tres reciban todo: quiere que a Soporte le lleguen los soportes. Aquí
    se dice cuál se encarga de qué.

    Las áreas que sobran del cupo NO se pintan una detrás de otra: van
    detrás de `+ Añadir área`, que es un `<details>` y no un botón de
    JavaScript. Sus campos siguen dentro del formulario aunque esté
    cerrado, así que `leer_destinos` las ve igual — un `<details>`
    cerrado se envía como cualquier otro campo.

    `rechazos` es `{numero: motivo}` con lo que Meta contestó al no poder
    entregar. Se pinta EN el área, con su filete rojo y el motivo
    literal: el mismo error en una banda arriba no dice a quién le pasó.
    """
    guardados = ((n.get("avisos") or {}).get("destinos") or [])
    opciones = _opciones_del_menu(n)
    rechazos = rechazos or {}

    aviso_menu = "" if opciones else """
        <p class="tenue">Este negocio todavía no tiene menú, así que aún no
           hay nada que repartir. Ármalo primero y vuelve aquí.</p>"""

    # Cuántas hay puestas de verdad. Es lo que va en el medidor y en el
    # rótulo de "+ Añadir área": el cupo solo dice el techo.
    usadas = sum(1 for d in guardados[:cupo] if (d.get("correo") or "").strip()
                 or (d.get("numero") or "").strip())

    # El área sin ninguna casilla marcada recoge lo que las demás no
    # reclamen. Es la regla que impide que un aviso se quede sin
    # destinatario, así que se dice EN la tarjeta y no en un párrafo al
    # final que nadie relaciona con ninguna.
    def tarjeta(i: int) -> str:
        d = guardados[i] if i < len(guardados) else {}
        marcadas = set(d.get("opciones") or [])
        indicativo, local = _partir_numero(d)
        puesta = bool((d.get("correo") or "").strip() or local.strip())

        casillas = "".join(f"""
          <label class="casilla">
            <input type="checkbox" name="destino-{i}-opcion"
                   value="{_e(ident)}"{" checked" if ident in marcadas else ""}>
            <span>{_e(titulo)}</span>
          </label>""" for ident, titulo in opciones)

        chips = []
        if puesta and not marcadas:
            chips.append('<span class="chip morado">recibe todo lo demás</span>')

        motivo = ""
        completo = (indicativo + local).strip()
        fallo = rechazos.get(completo) if completo else None
        if fallo:
            chips.append('<span class="chip mal">'
                         '<i class="punto"></i>Meta rechazó el aviso</span>')
            motivo = f'<p class="motivo">{_e(fallo)}</p>'

        nombre = (d.get("nombre") or "").strip()
        titulo = _e(nombre) if nombre else f"Área {i + 1}"

        return f"""
      <div class="caja-interna{" rechazada" if fallo else ""}">
        <div class="area-cabecera">
          <h3>{titulo}</h3>{"".join(chips)}
        </div>
        {motivo}
        <input type="hidden" name="destino-{i}-id" value="{_e(d.get("id"))}">
        <div class="rejilla-area">
          <div>{_campo(f"destino-{i}-correo", "Su correo", d.get("correo"),
                       "La vía que siempre llega.")}</div>
          <div>{_campo(f"destino-{i}-nombre", "Cómo se llama el área",
                       d.get("nombre"), "Ventas, Soporte, Contratos…")}</div>
          <div>
            <label>País</label>
            <input type="text" name="destino-{i}-indicativo" class="mono"
                   value="{_e(indicativo)}" list="indicativos"
                   inputmode="numeric" placeholder="57">
          </div>
          <div>
            <label>Su WhatsApp <span class="nota">(opcional)</span></label>
            <input type="text" name="destino-{i}-numero" class="mono"
                   value="{_e(local)}" inputmode="numeric"
                   placeholder="3001112233">
          </div>
        </div>
        <label>De qué se encarga</label>
        <div class="casillas">{casillas or '<p class="tenue">—</p>'}</div>
      </div>"""

    # Las que ya están puestas, más una vacía a mano: pedir un clic para
    # empezar la primera sería un paso de más.
    a_la_vista = min(cupo, max(usadas + 1, 1))
    visibles = "".join(tarjeta(i) for i in range(a_la_vista))

    ocultas = ""
    if a_la_vista < cupo:
        resto = "".join(tarjeta(i) for i in range(a_la_vista, cupo))
        ocultas = f"""
      <details class="mas">
        <summary class="anadir">+ Añadir área ({usadas} de {cupo} usadas)</summary>
        <div>{resto}</div>
      </details>"""
    else:
        ocultas = (f'<p class="tenue">Están las {cupo} áreas que da su plan. '
                   f'Para darle más, súbele el paquete o pon un número '
                   f'pactado arriba.</p>')

    # SIN `<div class="caja">` propio: esto va DENTRO de la pestaña de
    # avisos de la ficha, que ya pone las tarjetas.
    return f"""
      <p class="tenue">Sin ninguna área, todos los avisos van al número del
         dueño. En cuanto pongas una, empiezan a repartirse.</p>
      <p class="tenue"><strong>Con el correo basta.</strong> Es la vía que
         siempre llega: WhatsApp solo deja avisar a quien le haya escrito
         al bot en las últimas 24 h, y un área recién puesta nunca lo ha
         hecho. El WhatsApp del área es opcional y se usa <em>además</em>
         del correo, no en su lugar.</p>
      {aviso_menu}
      <p class="tenue">Si además pones WhatsApp: el <strong>país</strong> va
         aparte y sin "+": <strong>57</strong> Colombia ·
         <strong>34</strong> España · <strong>52</strong> México ·
         <strong>1</strong> EE.UU. El <strong>número</strong>, como se marca
         dentro de ese país y <strong>sin el cero inicial</strong>.</p>
      {visibles}
      {ocultas}
      <p class="tenue"><strong>Deja un área sin ninguna casilla marcada</strong>
         y esa recogerá todo lo que las demás no reclamen — incluido lo que
         pase antes de que el cliente elija nada, como cuando pide hablar
         con una persona. Sin un área así, lo que nadie reclame se le manda
         a todas, que es mejor que perderlo pero peor que tenerlo
         previsto.</p>
      {LISTA_INDICATIVOS}"""


def _bloque_enlaces(enlaces: dict) -> str:
    """
    Los enlaces, uno por fila: número, nombre, dirección.

    En filas y no en una rejilla de cuadros sueltos porque son PARES —el
    nombre con el que se le llama desde el menú y la dirección a la que
    va— y en columnas se lee de un vistazo cuál apunta a dónde. Con cada
    par en su propio cuadro había que emparejarlos con la vista.
    """
    filas = "".join(f"""
      <div class="fila-opcion">
        <span class="num">{i + 1}</span>
        <div><label>Se llama</label>
          <input type="text" value="{_e(clave)}" readonly class="mono"></div>
        <div><label>Va a</label>
          <input type="text" name="enlace-{_e(clave)}" value="{_e(valor)}"></div>
        <span class="nota">lo nombra el menú</span>
      </div>""" for i, (clave, valor) in enumerate(enlaces.items()))

    return f"""
    <div class="caja" id="bloque-enlaces">
      <h2>Enlaces</h2>
      <p class="tenue">Las opciones del menú los usan por su nombre, así
         que una URL se cambia una vez aquí y cambia en todos lados. El
         nombre no se edita: cambiarlo dejaría huérfanas a las opciones
         que lo nombran.</p>
      {filas or '<p class="tenue">Sin enlaces.</p>'}
      <div class="fila-opcion">
        <span class="num">+</span>
        <div><label>Añadir uno: se llama</label>
          <input type="text" name="enlace-nuevo-clave" placeholder="catalogo"
                 class="mono"></div>
        <div><label>Va a</label>
          <input type="text" name="enlace-nuevo-valor" placeholder="https://..."></div>
        <span></span>
      </div>
    </div>"""


def _bloque_precios(precios: dict) -> str:
    filas = "".join(
        f'<div class="campo">{_campo(f"precio-{clave}", clave, valor, area=True, filas=4)}</div>'
        for clave, valor in precios.items())
    return f"""
    <div class="caja" id="bloque-precios">
      <h2>Bloques de precios</h2>
      <p class="tenue">Textos largos que el bot manda cuando alguien pide
         precios. Igual que los enlaces: se nombran desde el menú.</p>
      <div class="dos-columnas">{filas or "<p>Sin bloques de precios.</p>"}</div>
    </div>"""


def _selector(nombre: str, opciones: list, elegido, vacio="(ninguno)") -> str:
    partes = [f'<option value="">{vacio}</option>']
    for valor, etiqueta in opciones:
        sel = " selected" if str(valor) == str(elegido or "") else ""
        partes.append(f'<option value="{_e(valor)}"{sel}>{_e(etiqueta)}</option>')
    return f'<select name="{nombre}">{"".join(partes)}</select>'


def _opcion_html(prefijo: str, opcion: dict, enlaces: dict, precios: dict,
                 titulo: str) -> str:
    # `mensaje` y `pregunta` son lo que el cliente recibe, así que van en
    # cuadro: un renglón no admite saltos de línea y los borraba al
    # guardar. Los demás son rótulos de WhatsApp con tope de caracteres
    # (`title`, `description`) o nombres para los informes.
    campos = "".join(
        f'<div>{_campo(f"{prefijo}-{clave}", etiqueta, opcion.get(clave), ayuda, area=clave in CLAVES_DE_MENSAJE)}</div>'
        for clave, etiqueta, ayuda in CAMPOS_OPCION)

    return f"""
    <div class="opcion">
      <div class="opcion-cabecera">
        <strong>{_e(titulo)}</strong>
        <label class="quitar">
          <input type="checkbox" name="{prefijo}-eliminar" value="si"> eliminar
        </label>
      </div>
      <div class="rejilla">
        <div>
          <label>Identificador</label>
          <input type="text" name="{prefijo}-id" value="{_e(opcion.get("id"))}">
          <p class="tenue">Sin espacios ni tildes. Es interno; el cliente no lo ve.</p>
        </div>
        <div>
          <label>Qué hace al tocarla</label>
          {_selector(f"{prefijo}-accion", ACCIONES, opcion.get("accion"), "(nada)")}
        </div>
        {campos}
        <div>
          <label>Enlace que manda</label>
          {_selector(f"{prefijo}-enlace", [(k, k) for k in enlaces], opcion.get("enlace"))}
        </div>
        <div>
          <label>Bloque de precios que manda</label>
          {_selector(f"{prefijo}-precios", [(k, k) for k in precios], opcion.get("precios"))}
        </div>
        <div>
          <label>Opciones que ofrece después</label>
          <input type="text" name="{prefijo}-luego"
                 value="{_e(', '.join(opcion.get('luego', []) or []))}">
          <p class="tenue">Identificadores separados por comas.</p>
        </div>
        <div>
          <label>Pestaña del Sheet</label>
          <input type="text" name="{prefijo}-sheet" value="{_e(opcion.get("sheet"))}">
        </div>
      </div>
    </div>"""


def _bloque_menu(n: dict, enlaces: dict, precios: dict) -> str:
    bloques = []
    for i, opcion in enumerate(n.get("menu", []) or []):
        sub = "".join(
            _opcion_html(f"menu-{i}-sub-{j}", s, enlaces, precios,
                         f"Sub-opción {i + 1}.{j + 1}")
            for j, s in enumerate(opcion.get("submenu", []) or []))

        bloques.append(f"""
        <div class="opcion-principal">
          {_opcion_html(f"menu-{i}", opcion, enlaces, precios, f"Opción {i + 1}")}
          <div class="submenu" id="sub-{i}">
            <p class="tenue">Sub-opciones (solo se usan si la acción es
               "Abrir otro menú de opciones")</p>
            {sub}
          </div>
          <button type="button" class="suave" onclick="anadirSub({i})">
            + sub-opción
          </button>
        </div>""")

    cierre = "".join(
        _opcion_html(f"cierre-{i}", o, enlaces, precios, f"Cierre {i + 1}")
        for i, o in enumerate(n.get("cierre", []) or []))

    return f"""
    <div class="caja" id="bloque-menu">
      <h2>El menú</h2>
      <p class="tenue">Lo que el cliente ve como lista o botones. El orden
         de aquí es el orden en que aparecen.</p>
      <div id="menu-opciones">{"".join(bloques)}</div>
      <button type="button" onclick="anadirOpcion()">+ Añadir una opción</button>
    </div>

    <div class="caja" id="bloque-cierre">
      <h2>Opciones de cierre</h2>
      <p class="tenue">Lo que se ofrece al final de una conversación.</p>
      {cierre}
    </div>"""


def _bloque_ia(n: dict) -> str:
    ia = n.get("ia", {}) or {}
    return f"""
    <div class="caja" id="bloque-ia">
      <h2>El carácter del bot (solo con IA activada)</h2>
      <div class="rejilla">
        <div>{_campo("ia-rol", "Quién dice ser", ia.get("rol"))}</div>
        <div>{_campo("ia-tono", "Cómo habla", ia.get("tono"))}</div>
        <div>{_campo("ia-max_palabras", "Máximo de palabras por respuesta",
                     ia.get("max_palabras", 60))}</div>
      </div>
      {_campo("ia-nunca", "Lo que tiene PROHIBIDO hacer", _lineas(ia.get("nunca")),
              "Uno por línea. Es la lista más importante: aquí se le cierra "
              "la puerta a lo que le costaría dinero o credibilidad al negocio.",
              area=True, filas=5)}
      {_campo("ia-siempre_derivar", "Temas que siempre pasa a una persona",
              _lineas(ia.get("siempre_derivar")), "Uno por línea.",
              area=True, filas=3)}
    </div>"""


def _bloque_horario(n: dict) -> str:
    h = n.get("horario", {}) or {}
    c = n.get("conversacion", {}) or {}
    dias = h.get("dias", []) or []
    nombres = ["lunes", "martes", "miércoles", "jueves", "viernes",
               "sábado", "domingo"]
    casillas = "".join(
        f'<label class="dia"><input type="checkbox" name="horario-dias" '
        f'value="{i}"{" checked" if i in dias else ""}> {nombre}</label>'
        for i, nombre in enumerate(nombres))

    return f"""
    <div class="caja" id="bloque-horario">
      <h2>Horario y conversación</h2>
      <div class="rejilla">
        <div>{_campo("horario-zona", "Zona horaria", h.get("zona"),
                     "Sin esto las citas de Google salen corridas.")}</div>
        <div>{_campo("horario-inicio", "Abre a las", h.get("inicio"))}</div>
        <div>{_campo("horario-fin", "Cierra a las", h.get("fin"))}</div>
        <div>{_campo("horario-duracion_cita_min", "Duración de cada cita (minutos)",
                     h.get("duracion_cita_min", 60))}</div>
        <div>{_campo("horario-anticipacion_min", "Anticipación mínima (minutos)",
                     h.get("anticipacion_min", 60))}</div>
        <div>{_campo("conversacion-takeover_minutos",
                     "Minutos antes de que el bot retome una conversación atendida a mano",
                     c.get("takeover_minutos", 180))}</div>
      </div>
      <label>Días que atiende</label>
      <div class="dias">{casillas}</div>
      {_campo("conversacion-palabras_asesor",
              "Palabras con las que alguien pide un asesor",
              _lineas(c.get("palabras_asesor")), "Una por línea.",
              area=True, filas=4)}
    </div>"""


# La plantilla vacía que clona el JavaScript, y el JavaScript. Va al final
# del formulario, escondida.
# El <template> vacío que clona el JavaScript. Se queda aquí porque es
# MARCADO, no comportamiento: sacarlo obligaría a crearlo desde JavaScript
# solo para poder clonarlo. El JavaScript sí se fue, a
# `app/web/estaticos/superadmin-contenido.js`.
_PLANTILLA = '<template id="plantilla-opcion"></template>'


# ══════════════════════════════════════════════════════════════════════
#  LEER
# ══════════════════════════════════════════════════════════════════════

def leer_destinos(formulario, cupo: int = 3) -> list:
    """
    Las áreas que reciben avisos, sacadas del formulario.

    Un área **sin correo ni número se descarta entera**, aunque tenga
    nombre y casillas marcadas. Es la forma de borrar una: se vacían los
    dos. Si se guardara a medias, quedaría en la lista pareciendo
    configurada y sin poder recibir nada.

    Las casillas llegan repetidas con el mismo nombre —una por opción
    marcada—, así que hay que pedirlas con `getlist` y no con `get`, que
    devolvería solo la primera. Con `get`, un área con tres opciones se
    guardaría con una.
    """
    destinos = []
    for i in range(cupo):
        numero = (formulario.get(f"destino-{i}-numero") or "").strip()
        correo = (formulario.get(f"destino-{i}-correo") or "").strip()

        # Un área vale si hay POR DONDE avisarle. Antes hacía falta el
        # número sí o sí, y eso dejaba fuera al área que solo quiere
        # correo — que es el caso normal desde que se vio que WhatsApp no
        # sirve para avisar a un equipo.
        if not numero and not correo:
            continue

        indicativo = (formulario.get(f"destino-{i}-indicativo") or "").strip()

        opciones = []
        if hasattr(formulario, "getlist"):
            opciones = [o for o in formulario.getlist(f"destino-{i}-opcion") if o]

        destinos.append({
            # El id viaja escondido en el formulario: es lo que une el área
            # con su usuario, y no puede salir del nombre, que se edita.
            "id": (formulario.get(f"destino-{i}-id") or "").strip(),
            "nombre": (formulario.get(f"destino-{i}-nombre") or "").strip(),
            # Se guardan APARTE y se juntan al construir la configuracion
            # (`config_cliente._leer_destinos`). Guardar solo el numero
            # unido obligaria a adivinar donde acaba el indicativo para
            # volver a pintarlo, y eso no se puede hacer bien.
            "indicativo": indicativo,
            "numero": numero,
            "correo": correo,
            "opciones": opciones,
        })

    return destinos


def leer(formulario, negocio_actual: dict, cupo_avisos: int = 3) -> dict:
    """
    El formulario enviado, convertido en la configuración nueva.

    **Parte de una copia de la que había.** Lo que este editor no muestra
    —las pestañas del Sheet, los orígenes, la marca— se conserva tal cual.
    Sin eso, guardar una vez borraría media configuración en silencio.
    """
    nuevo = copy.deepcopy(negocio_actual or {})

    def dato(nombre, defecto=""):
        return (formulario.get(nombre) or defecto).strip()

    # Un texto que se manda por WhatsApp. `dato` le quitaría los saltos y
    # los espacios de los extremos, que en un mensaje son parte de lo que
    # se quiso escribir. Ver `_como_se_escribio`.
    def mensaje(nombre):
        return _como_se_escribio(formulario.get(nombre))

    # ── Negocio ──
    negocio = nuevo.setdefault("negocio", {})
    for clave in ("nombre", "whatsapp", "email", "web", "boton_web"):
        negocio[clave] = dato(f"negocio-{clave}")

    # ── Textos y avisos ──
    textos = nuevo.setdefault("textos", {})
    for clave, _ in CAMPOS_TEXTOS:
        textos[clave] = mensaje(f"texto-{clave}")

    avisos = nuevo.setdefault("avisos", {})
    for clave, _ in CAMPOS_AVISOS:
        avisos[clave] = mensaje(f"aviso-{clave}")

    # `destinos` NO se toca aquí, y no es un olvido: las áreas se editan
    # en la ficha del cliente, no en el editor de contenido. Escribirlas
    # desde aquí las borraría —el formulario ya no trae esos campos, así
    # que se guardaría una lista vacía— y sin dar ningún error. Es la
    # regla 1 del docstring de este módulo: lo que el formulario no cubre,
    # no se toca.
    #
    # No están en CAMPOS_AVISOS porque no son textos que se redacten:
    # ver `_bloque_avisos`.
    avisos["plantilla"] = dato("aviso-plantilla")
    avisos["plantilla_idioma"] = dato("aviso-plantilla_idioma")

    # ── Enlaces y precios ──
    enlaces = nuevo.setdefault("enlaces", {})
    for clave in list(enlaces):
        enlaces[clave] = dato(f"enlace-{clave}")
    if (nueva := dato("enlace-nuevo-clave")):
        enlaces[nueva.lower().replace(" ", "_")] = dato("enlace-nuevo-valor")

    precios = nuevo.setdefault("precios", {})
    for clave in list(precios):
        precios[clave] = dato(f"precio-{clave}")

    # ── Menú y cierre ──
    # Cada opción parte de la que ya había, buscada por su id: ver
    # `_leer_opcion`, que es donde se explica lo que se perdía.
    previas = {}
    _indexar_opciones(negocio_actual.get("menu"), previas)
    _indexar_opciones(negocio_actual.get("cierre"), previas)

    nuevo["menu"] = _leer_opciones(formulario, "menu", con_submenu=True,
                                   previas=previas)
    leidas = _leer_opciones(formulario, "cierre", previas=previas)
    if leidas:
        nuevo["cierre"] = leidas

    # ── IA ──
    ia = nuevo.setdefault("ia", {})
    ia["rol"] = dato("ia-rol")
    ia["tono"] = dato("ia-tono")
    ia["nunca"] = _de_lineas(formulario.get("ia-nunca"))
    ia["siempre_derivar"] = _de_lineas(formulario.get("ia-siempre_derivar"))
    ia["max_palabras"] = _entero(dato("ia-max_palabras"), 60)

    # ── Horario y conversación ──
    horario = nuevo.setdefault("horario", {})
    horario["zona"] = dato("horario-zona")
    horario["inicio"] = dato("horario-inicio")
    horario["fin"] = dato("horario-fin")
    horario["duracion_cita_min"] = _entero(dato("horario-duracion_cita_min"), 60)
    horario["anticipacion_min"] = _entero(dato("horario-anticipacion_min"), 60)

    dias = [_entero(d, None) for d in _todos(formulario, "horario-dias")]
    horario["dias"] = sorted(d for d in dias if d is not None)

    conversacion = nuevo.setdefault("conversacion", {})
    conversacion["takeover_minutos"] = _entero(
        dato("conversacion-takeover_minutos"), 180)
    conversacion["palabras_asesor"] = _de_lineas(
        formulario.get("conversacion-palabras_asesor"))

    return nuevo


def _todos(formulario, nombre) -> list:
    """Todos los valores de un campo repetido (las casillas de los días)."""
    if hasattr(formulario, "getlist"):
        return formulario.getlist(nombre)
    valor = formulario.get(nombre)
    return [valor] if valor else []


def _entero(texto, defecto):
    try:
        return int(str(texto).strip())
    except (ValueError, TypeError):
        return defecto


def _indexar_opciones(opciones, indice: dict):
    """`{id: opción}` de todo el árbol, a la profundidad que tenga."""
    for opcion in opciones or []:
        if not isinstance(opcion, dict):
            continue
        ident = str(opcion.get("id") or "").strip()
        if ident:
            indice.setdefault(ident, opcion)
        _indexar_opciones(opcion.get("submenu"), indice)


def _leer_opciones(formulario, raiz: str, con_submenu=False,
                   previas: dict = None) -> list:
    """
    Reconstruye la lista de opciones a partir de los campos numerados.

    Se descarta lo que venga sin identificador o marcado para eliminar. Lo
    primero es lo que hace que una fila recién añadida y no rellenada
    desaparezca sola en vez de guardar una opción vacía que el cliente
    vería como un botón en blanco.
    """
    opciones = []
    for i in range(_cuantas(formulario, raiz)):
        prefijo = f"{raiz}-{i}"
        # En las de primer nivel, los submenús SÍ salen en el formulario,
        # así que manda lo que venga de él. En las de más adentro no: su
        # propio submenú (el tercer nivel) se conserva tal cual.
        opcion = _leer_opcion(formulario, prefijo, previas,
                              conservar_submenu=not con_submenu)
        if opcion is None:
            continue

        if con_submenu:
            sub = []
            for j in range(_cuantas(formulario, f"{prefijo}-sub")):
                hija = _leer_opcion(formulario, f"{prefijo}-sub-{j}", previas,
                                    conservar_submenu=True)
                if hija is not None:
                    sub.append(hija)
            if sub:
                opcion["submenu"] = sub

        opciones.append(opcion)
    return opciones


def _cuantas(formulario, raiz: str) -> int:
    """Cuántas filas de esta familia trae el formulario."""
    tope = -1
    for nombre in formulario.keys():
        if nombre.startswith(f"{raiz}-") and nombre.endswith("-id"):
            resto = nombre[len(raiz) + 1:-3]
            if resto.isdigit():
                tope = max(tope, int(resto))
    return tope + 1


# Lo que este formulario enseña de una opción, y por tanto lo único que
# puede cambiarle. Todo lo demás se conserva de lo que ya tenía.
CLAVES_DEL_FORMULARIO = ("accion", "title", "description", "mensaje",
                         "servicio", "paso", "pregunta", "sheet", "enlace",
                         "precios")


def _leer_opcion(formulario, prefijo: str, previas: dict = None,
                 conservar_submenu: bool = False):
    """
    Una opción, o None si hay que descartarla.

    ⚠️  PARTE DE LA OPCIÓN QUE YA HABÍA, y no de cero.

    Este formulario tiene dos niveles de menú y los diez campos de
    `CLAVES_DEL_FORMULARIO`. El mapa tiene más: un tercer nivel, la URL
    propia de una opción, `oculta` y `solo_con_cita`. Construida de cero,
    la opción perdía todo eso con UN guardado aquí, sin tocar nada — y el
    `negocio.toml` usa `oculta` y `solo_con_cita`: las opciones escondidas
    aparecían en el menú de todos y "Mi cita" se le ofrecía a quien nunca
    agendó. Es la regla 1 del docstring de este módulo, aplicada dentro de
    cada opción.
    """
    if formulario.get(f"{prefijo}-eliminar"):
        return None

    identificador = (formulario.get(f"{prefijo}-id") or "").strip()
    if not identificador:
        return None

    anterior = (previas or {}).get(identificador) or {}
    fuera = set(CLAVES_DEL_FORMULARIO) | {"luego", "id"}
    if not conservar_submenu:
        fuera.add("submenu")
    opcion = {"id": identificador}
    opcion.update({k: copy.deepcopy(v) for k, v in anterior.items()
                   if k not in fuera})

    for clave in CLAVES_DEL_FORMULARIO:
        # Los dos que se le mandan al cliente van tal cual se escribieron
        # —saltos de línea incluidos—; el resto son identificadores y
        # rótulos, y ahí un espacio de sobra solo estorba.
        crudo = formulario.get(f"{prefijo}-{clave}")
        valor = (_como_se_escribio(crudo) if clave in CLAVES_DE_MENSAJE
                 else (crudo or "").strip())
        if valor:
            opcion[clave] = valor

    # Si aquí se le eligió un enlace compartido que no tenía, eso es lo que
    # se quiere que mande: su URL propia, que no sale en este formulario,
    # ganaría sobre él (ver `config_cliente._opcion`) y el cambio se
    # guardaría sin usarse.
    if opcion.get("enlace") and opcion["enlace"] != anterior.get("enlace"):
        opcion.pop("url", None)

    luego = [x.strip() for x in
             (formulario.get(f"{prefijo}-luego") or "").split(",") if x.strip()]
    if luego:
        opcion["luego"] = luego

    return opcion
