"""
EL MAPA DE LA CONVERSACIÓN
===========================
Armar lo que dice un bot viendo, al lado, **cómo le llega al cliente**.

    izquierda   el recorrido, un paso cada vez
    derecha     ese mismo momento, pintado como el chat de WhatsApp

DOS REGLAS QUE SOSTIENEN ESTA PANTALLA
--------------------------------------
**1. Un paso enseña lo suyo y nada más.** El inicio de la conversación es
el saludo, y punto: ni la etiqueta del botón de la lista, ni qué contesta
si el menú está vacío, ni cómo saluda a quien ya escribió. Cada una de
esas cosas es un paso aparte y aparece cuando toca. Amontonarlas obliga a
saber de antemano qué hace cada una, que es justo lo que no se sabe.

**2. Lo que se escribe, se ve.** Todo campo editable tiene su reflejo en
la columna derecha, y para lograrlo la vista previa cambia de momento
según el paso abierto: al abrir "si ya te había escrito" pinta a un
cliente que vuelve; al abrir el menú vacío pinta el mensaje de cortesía.
Lo único que no se puede reflejar —el nombre del servicio en los
informes— va aparte y **dice con todas las letras que el cliente no lo
ve**. Un campo que se escribe y no se refleja en ningún sitio es un campo
que se llena a ciegas.

EL FORMATO NO SE ELIGE
----------------------
WhatsApp lo decide por la cantidad: hasta 3 opciones llegan como botones,
a la vista; de 4 en adelante llegan como UNA lista desplegable que el
cliente tiene que abrir. Por eso cada paso lleva su sello, cada grupo dice
en qué formato sale, la vista previa lo pinta distinto, y al llegar a 3
avisa antes de que se añada la cuarta.

LO QUE ES "ENTRENAR LA IA" AQUÍ
-------------------------------
No se entrena ningún modelo: se escriben las instrucciones que recibe en
cada mensaje. Son cinco, las mismas que arma `gemini._instrucciones`, ni
una más.

LO QUE ESTE EDITOR NO TOCA
--------------------------
El horario, los avisos al dueño, los textos de las citas, las pestañas del
Sheet y los orígenes. Se guardan intactos.
"""

from app.web import activos
import html
import json


# Qué pasa cuando el cliente pulsa una opción. Primero lo que más se usa.
#
#     "Mandar un enlace" ya no está, y no es un descuido: hacía LO MISMO
#     que responder un texto. Las dos mandan tu mensaje y las dos admiten
#     un enlace dentro; la única diferencia real era que la de texto puede
#     además seguir ofreciendo opciones. Tener dos nombres para una cosa
#     obliga a elegir entre ellos sin poder saber en qué se diferencian.
#     Las configuraciones que ya usan `enlace` siguen funcionando: el bot
#     la entiende igual y aquí se enseña como lo que es.
ACCIONES = [
    ("info", "Responder con un texto",
     "Manda tu mensaje. Puedes meterle un enlace y seguir ofreciendo "
     "opciones después."),
    ("submenu", "Abrir más botones",
     "Muestra otro grupo de botones dentro de esta opción. Si pones más "
     "de 3, le llegarán como lista."),
    ("cita", "Agendar una cita",
     "Ofrece los días y horas libres de tu calendario de Google."),
    ("humano", "Pasar a una persona",
     "Te avisa para que atiendas tú y calla al bot en ese chat. Abajo "
     "eliges si antes le pide que cuente su consulta."),
    ("menu", "Volver al menú principal",
     "Vuelve a ofrecer el menú de arriba, sin preguntar el nombre otra vez."),
    ("reagendar", "Cambiar una cita de día",
     "Le busca otro día y hora, y mueve la reunión en tu calendario."),
    ("cancelar", "Cancelar una cita",
     "La borra de tu calendario y se lo confirma."),
    ("terminar", "Despedirse y terminar",
     "Se despide y calla. Si el cliente escribe de nuevo, el bot vuelve."),
]

# Las que trabajan sobre una cita que YA existe. Se ofrecen normalmente
# junto a `solo_con_cita`, porque a quien nunca agendó solo pueden
# llevarle a "no encontramos ninguna reunión".
ACCIONES_DE_CITA = ("reagendar", "cancelar")

# Lo que el BOT entiende, que es más de lo que el editor ofrece:
#
#   `enlace`  hay negocios con esto guardado de antes, y no se les puede
#             invalidar la configuración por haber simplificado una
#             pantalla. Hace lo mismo que `info`.
#
#   `atras`   no se elige, se marca. Es una de las dos salidas fijas que
#             se ofrecen DESPUÉS de una respuesta ("y le vuelve a
#             ofrecer…"), y el bot la arma sola: no es algo que se
#             configure como la acción de una opción. Está aquí para que
#             el validador no rechace un mapa que la traiga, no para
#             ofrecerla en el desplegable.
ACCIONES_VALIDAS = tuple(a for a, _, _ in ACCIONES) + ("enlace", "atras")

# El tope de WhatsApp. No es una preferencia nuestra: son botones de la
# API de Meta, y con más de tres el mensaje se manda como lista.
MAX_BOTONES = 3


# ⚠️  QUÉ TEXTOS CABEN EN UNA SOLA LÍNEA, Y POR QUÉ IMPORTA TANTO
# ----------------------------------------------------------------------
# Estos son **rótulos de la interfaz de WhatsApp**: la etiqueta de un
# botón, el título de una lista, la línea pequeña de una fila. Meta los
# manda como una sola línea con un tope de caracteres, así que un salto
# ahí no se ve — se pierde, o hace que rechace el mensaje entero.
#
# Todo lo demás es el CUERPO de un mensaje, y un cuerpo puede tener los
# saltos de línea y los espacios que quiera: WhatsApp los respeta tal
# cual. Por eso esta lista dice quién va en `<input>` y quién en
# `<textarea>`, y **no se decide por lo largo que sea el texto**.
#
# La trampa que esto arregla, y que no daba ningún error: un `<input>` no
# admite saltos de línea. El navegador se los come al PINTAR el campo, así
# que un texto guardado con saltos los perdía solo con abrir la pantalla, y
# el siguiente guardado escribía la versión aplastada. En el editor de
# contenido, donde se envía el formulario entero, bastaba con entrar y
# pulsar Guardar sin tocar nada.
#
# Los dos editores —el mapa y el contenido— leen esta misma lista. Tenían
# cada uno su criterio (aquí, "el texto por defecto mide más de 40
# caracteres"; allí, una casilla escrita a mano) y no coincidían.
TEXTOS_DE_UNA_LINEA = frozenset({
    "menu_boton",             # etiqueta del botón que abre la lista (20)
    "menu_seccion",           # cabecera de la lista (24)
    "boton_volver_menu",      # etiqueta de botón (20)
    "boton_atras",            # etiqueta de botón (20)
    "cita_boton_dias",        # etiqueta de botón (20)
    "cita_seccion_dias",      # cabecera de lista (24)
    "cita_dia_descripcion",   # la línea pequeña de cada fila (72)
    "cita_boton_horarios",    # etiqueta de botón (20)
    "cita_seccion_horarios",  # cabecera de lista (24)
    "media_boton_menu",       # etiqueta de botón (20)
    "media_boton_asesor",     # etiqueta de botón (20)
})


def cabe_en_una_linea(clave: str) -> bool:
    """Si ese texto es un rótulo de WhatsApp y no el cuerpo de un mensaje."""
    return clave in TEXTOS_DE_UNA_LINEA

# Las cinco instrucciones que recibe el modelo. Son EXACTAMENTE las que
# lee `gemini._instrucciones`: (clave, etiqueta, ayuda, forma).
CAMPOS_IA = [
    ("rol", "Quién dice ser",
     'Se le dice tal cual: "Eres …". Puedes usar {negocio}.', "texto"),
    ("tono", "Cómo habla",
     "Una clínica y una discoteca no escriben igual.", "texto"),
    ("nunca", "Lo que tiene PROHIBIDO",
     "Uno por línea. Aquí se le cierra la puerta a inventar lo que te "
     "costaría dinero o credibilidad.", "lista"),
    ("siempre_derivar", "Temas que pasa a una persona",
     "Uno por línea. Un reclamo mal contestado por un bot cuesta más que "
     "un reclamo sin contestar.", "lista"),
    ("max_palabras", "Largo máximo de una respuesta",
     "En palabras. Es WhatsApp: un párrafo largo no se lee. Se le pide al "
     "modelo y además se recorta al recibirlo.", "numero"),
]


# El resto de los textos del bot: los que no son un paso del recorrido
# pero SÍ salen por WhatsApp. Estaban solo en el editor de contenido, y el
# dueño se topó con lo evidente — está probando desde el panel y no podía
# tocar lo que el bot contesta cuando no entiende algo.
#
# Agrupados por CUÁNDO los dice, no por cómo se llaman por dentro.
GRUPOS_DE_TEXTOS = [
    ("Durante la conversación", [
        # Las dos salidas fijas. Van las primeras porque se pueden
        # ofrecer después de cualquier respuesta y son lo que evita que
        # el cliente se quede en un callejón sin salida.
        ("boton_volver_menu", "Botón de volver al menú principal"),
        ("boton_atras", "Botón de volver atrás"),
        # "no entendí" y los del botón de asesor ya no están aquí: se
        # editan DENTRO de su paso, al lado de la vista previa y de la
        # decisión que los enciende. Ver `TEXTOS_EN_PASOS`.
        ("aviso_asesor",
         "Cuando ESCRIBE que quiere hablar con un asesor"),
        ("cierre", "Cómo pregunta si necesita algo más"),
        ("despedida", "Despedida"),
        ("enlace_web", "Mensaje que acompaña al enlace de la web"),
    ]),
    ("Cuando le mandan un archivo", [
        ("media_imagen", "Al recibir una foto"),
        ("media_audio", "Al recibir una nota de voz"),
        ("media_documento", "Al recibir un documento"),
        ("media_otro", "Al recibir otra cosa"),
        ("media_boton_menu", "Botón de menú tras un archivo"),
        ("media_boton_asesor", "Botón de asesor tras un archivo"),
        ("media_detalle_asesor", "Nota interna al pedir asesor con archivo"),
    ]),
    ("Al agendar una cita", [
        ("cita_preguntar_dia", "Al empezar: qué día"),
        ("cita_boton_dias", "Etiqueta del botón de días"),
        ("cita_seccion_dias", "Título de la lista de días"),
        ("cita_dia_descripcion", "Descripción de cada día"),
        ("cita_preguntar_hora", "Al elegir día: qué hora"),
        ("cita_boton_horarios", "Etiqueta del botón de horarios"),
        ("cita_seccion_horarios", "Título de la lista de horarios"),
        ("cita_confirmada", "Confirmación de la cita"),
    ]),
    ("Cuando algo de la cita sale mal", [
        ("cita_horario_tomado", "Si le quitan el horario mientras elegía"),
        ("cita_dia_lleno", "Si el día se llenó"),
        ("cita_sin_disponibilidad", "Si no hay horarios en semanas"),
        ("cita_respaldo", "Si Google falla y se anota a mano"),
        ("cita_cancelada", "Al cancelar una cita"),
        ("cita_reagendar", "Al cambiar una cita de día"),
        ("cita_no_encontrada", "Si no encuentra la cita que quiere cambiar"),
    ]),
]


# Los textos que se editan dentro de un paso del recorrido y no en "Los
# demás textos". Van con el paso porque ahí se ve CUÁNDO se dicen y la
# decisión que los enciende —el "no entendí" junto a si vuelve a enseñar
# el menú; los del asesor junto a si pide o no la consulta—. Y no están en
# los dos sitios a la vez: dos cuadros para el mismo texto se desincronizan
# en pantalla, y cuál gana al guardar depende de cuál se tocó último.
#
# `test_multitenant` junta esta lista con GRUPOS_DE_TEXTOS para comprobar
# que no queda ningún texto del bot sin poderse editar.
TEXTOS_EN_PASOS = frozenset({
    "bienvenida", "preguntar_necesidad", "menu_boton", "menu_seccion",
    "bienvenida_de_vuelta", "sin_configurar",
    "no_entendi", "no_entendi_menu",
    "otra_consulta", "paso_a_asesor", "asesor_directo",
})


_COLUMNAS = ["Fecha de contacto", "Nombre", "Teléfono", "Recorrido",
             "Mensaje", "Origen", "Estado"]


def negocio_en_blanco(nombre: str) -> dict:
    """
    Con qué nace un negocio nuevo.

    En blanco de verdad: sin menú, sin textos, sin enlaces ni precios. Lo
    único que trae es **fontanería**, y conviene saber por qué:

    Las dos pestañas del Sheet no son contenido, son el sitio donde caen
    los leads. `bot_logic._registrar_en_sheet` escribe en "otros" a quien
    no eligió servicio y en "citas" a quien agendó; si esas pestañas no
    existen, `sheets_service.registrar_lead` devuelve False y lo deja
    anotado en el log — o sea que el negocio perdería sus leads en
    silencio. Nacer sin menú es lo que se pidió; nacer perdiendo leads, no.
    """
    return {
        "negocio": {"nombre": nombre},
        "sheets": {
            "pestanas_por_defecto": ["Hoja 1", "Hoja1", "Sheet1", "Sheet 1"],
            "pestanas": {
                "otros": {"nombre": "Consultas", "formato": "servicio",
                          "columnas": list(_COLUMNAS)},
                "citas": {"nombre": "Citas agendadas", "formato": "cita",
                          "columnas": ["Fecha de contacto", "Nombre",
                                       "Teléfono", "Servicio", "Recorrido",
                                       "Día de la cita", "Hora", "Origen",
                                       "Estado", "ID del evento"]},
            },
        },
    }


# Lo que se enseña cuando un negocio todavía no tiene contenido propio.
# Mientras lea el archivo del repositorio, lo que se guarde aquí es lo que
# empieza a mandar — y hasta ese primer guardado, editar el archivo era lo
# único que le afectaba. Decirlo evita la duda de "guardo y no cambia".
AVISO_DEL_ARCHIVO = """
      <div class="banda mal">
        <strong>Este negocio todavía lee el negocio.toml del
        repositorio.</strong> Lo que ves aquí sale de ese archivo. En
        cuanto guardes, su contenido pasa a la base y el archivo deja de
        afectarle: es lo que hace falta para poder editarlo desde aquí.
      </div>"""


def pintar(negocio: dict, client_id: int, nombre: str,
           tiene_propio: bool = True, guardar_en: str = None,
           con_ia: bool = True, aviso_del_archivo: bool = True) -> str:
    """
    La página entera del mapa: los datos van embebidos como JSON.

    `tiene_propio` dice si este negocio ya tiene contenido en la base o si
    lo que se está viendo sale del `negocio.toml` del repositorio.

    Lo usan DOS pantallas: el super-admin y el dueño desde su panel
    (`app/web/panel_bot.py`). `guardar_en` es la ruta a la que guarda cada
    una; `con_ia` quita la caja de la IA a un plan que no la trae, y
    `aviso_del_archivo` calla la banda del negocio.toml, que al dueño no le
    dice nada.
    """
    guardar_en = guardar_en or f"/superadmin/clientes/{int(client_id)}/mapa"
    datos = json.dumps({
        "textos": negocio.get("textos") or {},
        "menu": negocio.get("menu") or [],
        "enlaces": negocio.get("enlaces") or {},
        # Los bloques de precios compartidos: el editor los necesita para
        # poder ENSEÑAR lo que el bot manda hoy en las opciones que
        # apuntan a uno de ellos.
        "precios": negocio.get("precios") or {},
        "variables": negocio.get("variables") or {},
        "ia": negocio.get("ia") or {},
        # Entera, aunque el mapa solo toque `pedir_nombre`: así lo demás
        # (los plazos de la conversación, las palabras que piden asesor)
        # vuelve tal cual y no se pierde al guardar.
        "conversacion": negocio.get("conversacion") or {},
    }, ensure_ascii=False)

    # Lo que el bot dice HOY en cada texto que no esté escrito. Sin esto
    # el recuadro sale vacío y el bot contesta algo: se edita a ciegas, sin
    # saber siquiera qué se está cambiando.
    from app.core.config_cliente import (PALABRAS_MENU_POR_DEFECTO,
                                         TEXTOS_POR_DEFECTO)

    constantes = json.dumps({
        "grupos_de_textos": [
            {"grupo": grupo,
             # `una_linea` decide si el campo sale como renglón o como
             # cuadro. Antes lo decidía lo largo que fuera el texto por
             # defecto, y eso metía en un `<input>` mensajes enteros —que
             # entonces no podían llevar saltos de línea. Ver
             # `TEXTOS_DE_UNA_LINEA`.
             "campos": [{"clave": c, "nombre": n,
                         "defecto": TEXTOS_POR_DEFECTO.get(c, ""),
                         "una_linea": cabe_en_una_linea(c)}
                        for c, n in campos]}
            for grupo, campos in GRUPOS_DE_TEXTOS
        ],
        "defectos": TEXTOS_POR_DEFECTO,
        # De marcador en el cuadro de frases del paso "si no entiende":
        # vacío, el bot usa estas.
        "palabras_menu_defecto": list(PALABRAS_MENU_POR_DEFECTO),
        "acciones": [{"clave": a, "nombre": n, "ayuda": h}
                     for a, n, h in ACCIONES],
        "campos_ia": [{"clave": c, "nombre": n, "ayuda": h, "forma": f}
                      for c, n, h, f in CAMPOS_IA],
        "acciones_de_cita": list(ACCIONES_DE_CITA),
        "max_botones": MAX_BOTONES,
        "negocio": nombre,
        # Las dos salidas que se pueden ofrecer después de CUALQUIER
        # respuesta, tenga el negocio lo que tenga escrito. No son
        # opciones de ningún menú: las arma el bot (`bot_logic`), y aquí
        # solo hacen falta sus etiquetas para poder pintarlas.
        "fijas": [
            {"clave": clave,
             "nombre": (negocio.get("textos") or {}).get(texto)
                       or TEXTOS_POR_DEFECTO.get(texto, ""),
             "ayuda": ayuda}
            for clave, texto, ayuda in (
                ("__menu__", "boton_volver_menu",
                 "Vuelve al menú de arriba, sin preguntar el nombre otra vez."),
                ("__atras__", "boton_atras",
                 "Vuelve al grupo del que venía este paso."),
            )
        ],
    }, ensure_ascii=False)

    # Los dos van dentro de un <script>, y lo que llevan lo escribió una
    # persona: un "</script>" en un texto cerraba el bloque y el resto se
    # ejecutaba como código. `<` escapado, igual que en el panel.
    datos = datos.replace("<", "\\u003c")
    constantes = constantes.replace("<", "\\u003c")

    caja_ia = CAJA_IA if con_ia else ""

    # Sin <h1> ni enlaces de vuelta: los pone el armazon del super-admin
    # (`superadmin._pantalla`), con la cabecera fija y las pestanas de la
    # ficha. Repetirlos aqui daba dos titulos y dos formas de volver.
    return f"""
      {"" if tiene_propio or not aviso_del_archivo else AVISO_DEL_ARCHIVO}

      <div id="banda-guardado" class="banda" hidden></div>

      <div class="mapa-columnas">
        <div class="caja">
          <h2>La conversación</h2>
          <p class="tenue">Un paso cada vez. Pulsa uno para abrirlo: a la
             derecha se pinta ese mismo momento. El triángulo de cada
             opción pliega lo que tiene dentro.</p>
          <div class="pliegues">
            <button type="button" class="suave" onclick="plegarTodo(true)">
              Plegar todo</button>
            <button type="button" class="suave" onclick="plegarTodo(false)">
              Desplegar todo</button>
          </div>
          <div id="arbol"></div>
        </div>

        <div>
          <div class="telefono">
            <div class="telefono-barra">
              <span class="telefono-avatar"></span>
              <span>{html.escape(nombre)}</span>
            </div>
            <div class="telefono-chat" id="vista"></div>
          </div>
          <p class="tenue" id="pie-vista"></p>
        </div>
      </div>

      <div class="caja">
        <h2>Los demás textos del bot</h2>
        <p class="tenue">Lo que dice fuera del recorrido: cuando no entiende,
           cuando le mandan una foto, cuando agenda. <strong>Si dejas uno
           vacío, el bot dice lo que ves en gris</strong> — puedes copiarlo y
           cambiarlo.</p>
        <div id="otros-textos"></div>
      </div>

      {caja_ia}

      <div class="caja">
        <h2>Tus variables</h2>
        <p class="tenue">Lo que se repite en muchos textos y cambia una vez
           al año. Se escriben entre llaves —<code>{{celular}}</code>— y el
           bot las cambia por su valor al responder.</p>
        <div id="variables"></div>
        <button type="button" class="suave" onclick="agregarVariable()">
          Añadir una variable</button>
      </div>

      <div class="guardar-fijo">
        <span class="contador" id="pista-guardado" data-sucio="no">Sin cambios</span>
        <button type="button" onclick="guardar()">Guardar el mapa</button>
        <p class="aviso">Nada se guarda hasta que lo pulses, y se valida
           entero: si una opción apunta a un enlace que no existe, te lo
           dice y no toca nada.</p>
      </div>

      <script>
      const CLIENTE = {int(client_id)};
      const GUARDAR_EN = {json.dumps(guardar_en)};
      const K = {constantes};
      let datos = {datos};
      </script>
      <script src="{activos.url('superadmin-mapa.js')}" defer></script>
    """


# La caja de la IA: aparte porque un plan sin IA no la enseña.
CAJA_IA = """      <div class="caja">
        <h2>Cómo responde la IA</h2>
        <p class="tenue">Esto <strong>no entrena un modelo</strong>: son las
           instrucciones que recibe en cada mensaje, y son exactamente las
           cinco que el bot le manda. Solo entran en juego cuando el cliente
           escribe algo que no encaja con ninguna opción del menú.</p>
        <div id="ia"></div>
      </div>"""


# El CSS del mapa se fue a `app/web/estaticos/superadmin.css`, junto al
# del resto del super-admin: es la misma pantalla y se cargaban juntos.


