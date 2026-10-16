/* EL EDITOR DEL MAPA DE LA CONVERSACION
   ====================================
   948 lineas de JavaScript que vivian dentro de una cadena de Python.
   Es la pieza mas grande del super-admin y la que mas se toca: el arbol
   de opciones del menu, arrastrar y soltar, y el guardado.

   Los datos del negocio NO se interpolan aqui: la pagina los define en
   `let datos = ...` antes de cargar este archivo, igual que el panel del
   cliente hace con `PANEL`. */

// ── Qué paso está abierto ─────────────────────────────────────────────
// Un solo objeto para todo el mapa, porque la vista previa se pinta a
// partir de él: cada paso tiene su MOMENTO de la conversación.
//
//   {tipo:'saludo'}                 el saludo y el menú (módulo 1)
//   {tipo:'vuelve'}                 cuando escribe alguien conocido
//   {tipo:'vacio'}                  mientras no haya menú
//   {tipo:'opcion', ruta:[0,1]}     un botón concreto
let paso = {tipo: 'saludo'};
let sucio = false;

// El paso que impidio el ultimo guardado, y por que: {ruta, texto}.
// Se pinta dentro de ese paso al abrirlo (ver `editorPaso`) y se borra
// en cuanto se vuelve a pulsar Guardar. No sobrevive a una recarga: si
// no se guardo, no hay nada que recordar al volver.
let error = null;

function esElError(ruta) {
  return !!error && (error.ruta || []).join() === (ruta || []).join();
}

// ── Qué grupos están plegados ─────────────────────────────────────────
//
// El arbol salia entero desplegado. Con un menu de tres niveles eso son
// treinta tarjetas seguidas, y encontrar donde esta uno es ir bajando y
// contando sangrias. Se pliega por rutas (`"0,1"`), no por objetos, para
// que sobreviva a `dibujar()`, que rehace el arbol entero en cada cambio.
//
// Vive solo en memoria: al recargar sale todo desplegado otra vez. Lo
// contrario —guardarlo— obligaria a decidir que pasa cuando el menu
// cambia por debajo, y no vale la complicacion.
const plegados = new Set();

function clave(ruta) { return (ruta || []).join(); }

function plegado(ruta) { return plegados.has(clave(ruta)); }

function alternarPliegue(ruta) {
  const k = clave(ruta);
  if (plegados.has(k)) { plegados.delete(k); } else { plegados.add(k); }
  dibujar();
}

// Al abrir un paso hondo hay que poder VERLO: si alguno de sus padres
// esta plegado, la tarjeta ni siquiera se dibuja. Pasa al llegar desde
// un error de guardado, que abre el paso culpable esté donde esté.
function desplegarHasta(ruta) {
  for (let i = 0; i < (ruta || []).length; i++) {
    plegados.delete(clave(ruta.slice(0, i)));
  }
}

function todosLosGrupos(lista, ruta, acc) {
  acc = acc || [];
  (lista || []).forEach(function (o, i) {
    if ((o.submenu || []).length) {
      acc.push(ruta.concat([i]));
      todosLosGrupos(o.submenu, ruta.concat([i]), acc);
    }
  });
  return acc;
}

function plegarTodo(plegar) {
  plegados.clear();
  if (plegar) {
    todosLosGrupos(datos.menu, []).forEach(function (r) { plegados.add(clave(r)); });
  }
  dibujar();
}

function abierto(tipo, ruta) {
  if (paso.tipo !== tipo) return false;
  if (tipo !== 'opcion') return true;
  return (paso.ruta || []).join() === (ruta || []).join();
}

function abrir(tipo, ruta) {
  paso = {tipo: tipo, ruta: ruta};
  if (tipo === 'opcion') desplegarHasta(ruta);
  dibujar();
}

function marcarSucio() {
  sucio = true;
  // `data-sucio` y no un color a mano: el ambar de "sin guardar" sale
  // de la hoja de estilo, y a oscuras es otro ambar.
  const pista = document.getElementById('pista-guardado');
  pista.textContent = 'Cambios sin guardar';
  pista.dataset.sucio = 'si';
}

window.addEventListener('beforeunload', function (e) {
  if (sucio) { e.preventDefault(); e.returnValue = ''; }
});

// ── Recorrer el árbol ─────────────────────────────────────────────────
function opcionEn(ruta) {
  let lista = datos.menu, opcion = null;
  for (const i of ruta) {
    opcion = lista[i];
    if (!opcion) return null;
    lista = opcion.submenu || [];
  }
  return opcion;
}

function listaEn(ruta) {
  if (ruta.length === 0) return datos.menu;
  const padre = opcionEn(ruta.slice(0, -1));
  return padre ? (padre.submenu = padre.submenu || []) : datos.menu;
}

function todosLosIds(lista, acc) {
  acc = acc || [];
  for (const o of lista || []) { acc.push(o.id); todosLosIds(o.submenu, acc); }
  return acc;
}

function idLibre(titulo) {
  let base = (titulo || 'opcion').toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 24);
  if (!base) base = 'opcion';
  const usados = todosLosIds(datos.menu);
  if (!usados.includes(base)) return base;
  let n = 2;
  while (usados.includes(base + '_' + n)) n++;
  return base + '_' + n;
}

function visibles(lista) { return (lista || []).filter(o => !o.oculta); }

// ¿Este grupo sale como botones o como lista? No lo decidimos nosotros:
// lo decide la cantidad, en la API de Meta.
function formatoDe(lista) {
  return visibles(lista).length > K.max_botones ? 'lista' : 'botones';
}

function nombreAccion(clave) {
  const a = K.acciones.find(x => x.clave === clave);
  return a ? a.nombre : clave;
}

function escapar(t) {
  const d = document.createElement('div');
  d.textContent = t == null ? '' : t;
  return d.innerHTML;
}

function conVariables(texto) {
  let t = texto || '';
  for (const par of Object.entries(datos.variables || {})) {
    t = t.split('{' + par[0] + '}').join(par[1] || ('{' + par[0] + '}'));
  }
  return t.split('{negocio}').join(K.negocio)
          .split('{name}').join('Ana')
          .split('{url}').join('(el enlace)');
}

// ── El árbol, paso a paso ─────────────────────────────────────────────
function tarjeta(tipo, ruta, titulo, sellos, editor) {
  const div = document.createElement('div');
  div.className = 'paso' + (abierto(tipo, ruta) ? ' elegido' : '')
                + (tipo === 'saludo' ? ' inicio' : '')
                // El que impidio guardar se queda marcado en rojo aunque
                // se abra otro paso: si no, basta con pulsar en cualquier
                // sitio para perder de vista cual era.
                + (tipo === 'opcion' && esElError(ruta) ? ' senalado' : '');
  let html = '<div class="titulo">' + escapar(titulo) + '</div>';
  sellos.forEach(function (s) {
    html += '<span class="sello ' + s[0] + '">' + escapar(s[1]) + '</span>';
  });
  div.innerHTML = html;
  div.onclick = function (e) { e.stopPropagation(); abrir(tipo, ruta); };
  if (abierto(tipo, ruta) && editor) div.appendChild(editor());
  return div;
}

function dibujar() {
  const arbol = document.getElementById('arbol');
  arbol.innerHTML = '';
  const vacio = visibles(datos.menu).length === 0;
  const formato = formatoDe(datos.menu);

  // MÓDULO 1: cómo empieza la conversación. El saludo y el menú van
  // juntos porque son el mismo momento —el cliente los recibe seguidos—,
  // y porque el menú es lo que se hace DESPUÉS de saludar: tenerlo como
  // un paso aparte obligaba a buscar dónde se añade un botón.
  arbol.appendChild(tarjeta('saludo', null, '1 · Saludo y menú',
    vacio ? [['texto', 'Texto'], ['', 'Todavía sin botones']]
          : [['texto', 'Texto'],
             [formato === 'botones' ? 'boton' : 'lista',
              formato === 'botones' ? 'Botones' : 'Lista desplegable']],
    editorSaludo));

  // Los botones del menú cuelgan del módulo 1, cada uno con el suyo.
  arbol.appendChild(rama(datos.menu, []));

  // MÓDULO 2: el otro saludo. Es otro momento, así que es otro módulo, y
  // al abrirlo la vista previa pinta ese caso.
  arbol.appendChild(tarjeta('vuelve', null, '2 · Si ya te había escrito',
    [['texto', 'Texto'], ['', 'No le vuelve a pedir el nombre']],
    editorVuelve));

  // MÓDULO 3: lo que pasa cuando ESCRIBE en vez de pulsar. Es un momento
  // más de la conversación, y el que más se veía roto desde el teléfono:
  // "no entendí" una y otra vez, sin botones a la vista.
  const conMenu = !datos.conversacion
    || datos.conversacion.menu_tras_no_entendi !== false;
  arbol.appendChild(tarjeta('no_entiende', null, '3 · Si escribe algo que no entiende',
    [['texto', 'Texto'], conMenu ? ['boton', 'Y le enseña el menú'] : ['', 'Solo el texto']],
    editorNoEntiende));

  // Y solo si hace falta: qué contesta mientras no haya menú.
  if (vacio) {
    arbol.appendChild(tarjeta('vacio', null, 'Mientras el menú esté vacío',
      [['texto', 'Texto'], ['', 'Lo que responde hoy']], editorVacio));
  }

  vistaPrevia();

  // ⚠️  Los cuadros de texto se acomodan AQUI, y no solo al crearlos.
  //
  // `campo()` lo pide al construir cada uno, pero en ese momento el
  // cuadro todavia no esta en la pagina —la tarjeta se arma entera y
  // luego se cuelga del arbol—, y un elemento suelto mide cero: no hay
  // nada que medir, asi que `acomodarCampo` se rinde. Funcionaba en la
  // primera carga de puro azar (el guion de los campos corre despues) y
  // dejaba de funcionar en cuanto se repintaba el arbol.
  if (window.acomodarCampos) window.acomodarCampos(arbol);
}

function rama(lista, ruta) {
  const caja = document.createElement('div');
  caja.className = 'rama';
  const formato = formatoDe(lista);
  const cuantas = visibles(lista).length;

  if (cuantas > 0 && ruta.length > 0) {
    const cab = document.createElement('p');
    cab.className = 'grupo';
    cab.innerHTML = formato === 'botones'
      ? 'Estas <strong>' + cuantas + '</strong> le llegan como <strong>botones</strong>, a la vista.'
      : 'Estas <strong>' + cuantas + '</strong> le llegan como <strong>una lista desplegable</strong>: ve un botón y tiene que abrirlo.';
    caja.appendChild(cab);
  }

  if (cuantas === 0 && ruta.length > 0) {
    const vacio = document.createElement('div');
    vacio.className = 'vacio';
    vacio.textContent = 'Sin opciones dentro. Al pulsar, el cliente no recibiría nada.';
    caja.appendChild(vacio);
  }

  (lista || []).forEach(function (opcion, i) {
    const ruta_hijo = ruta.concat([i]);
    const hijos = visibles(opcion.submenu).length;
    let queHace = nombreAccion(opcion.accion);
    if (opcion.accion === 'submenu') {
      queHace = hijos ? 'Abre ' + hijos + (hijos === 1 ? ' botón' : ' botones')
                      : 'Abre más botones (todavía ninguno)';
    }

    const tarjetaOpcion = tarjeta('opcion', ruta_hijo, tituloDePaso(lista, i),
      [[formato === 'botones' ? 'boton' : 'lista',
        formato === 'botones' ? 'Botón' : 'Fila de lista'], ['', queHace]],
      function () { return editorPaso(opcion); });

    // El triangulito que pliega lo que cuelga de esta opcion. Solo lo
    // llevan las que tienen algo dentro: en las demas seria un boton que
    // no hace nada. `stopPropagation` para que plegar no ABRA el paso —
    // son dos cosas distintas y estan a tres pixeles.
    if (hijos) {
      const pliega = document.createElement('button');
      pliega.type = 'button';
      pliega.className = 'plegar';
      pliega.setAttribute('aria-expanded', plegado(ruta_hijo) ? 'false' : 'true');
      pliega.title = plegado(ruta_hijo)
        ? 'Ver las ' + hijos + ' opciones de dentro'
        : 'Plegar las ' + hijos + ' opciones de dentro';
      pliega.textContent = plegado(ruta_hijo) ? '▸' : '▾';
      pliega.onclick = function (e) { e.stopPropagation(); alternarPliegue(ruta_hijo); };
      const titulo = tarjetaOpcion.querySelector('.titulo');
      if (titulo) titulo.insertBefore(pliega, titulo.firstChild);
    }

    caja.appendChild(tarjetaOpcion);

    if (opcion.accion === 'submenu' && !plegado(ruta_hijo)) {
      caja.appendChild(rama(opcion.submenu, ruta_hijo));
    }
  });

  // El aviso ANTES de que pase, no después de guardar.
  if (cuantas === K.max_botones) {
    const aviso = document.createElement('div');
    aviso.className = 'aviso-formato';
    aviso.textContent = 'Estás en el tope de ' + K.max_botones + ' botones. '
      + 'Si añades una más, las ' + (K.max_botones + 1)
      + ' pasan a ser una lista desplegable y el cliente tendrá que abrirla para verlas.';
    caja.appendChild(aviso);
  }

  // En la raíz NO se pone botón de añadir: ya lo tiene el módulo 1, que
  // es donde se está mirando. Dos botones para lo mismo, uno encima del
  // otro, hacen dudar de si hacen cosas distintas.
  if (ruta.length > 0) {
    const anadir = document.createElement('button');
    anadir.type = 'button';
    anadir.className = 'suave';
    anadir.textContent = '+ Agregar otro botón aquí dentro';
    anadir.onclick = function (e) { e.stopPropagation(); nuevaOpcion(ruta); };
    caja.appendChild(anadir);
  }
  return caja;
}

// "Botón 1 · Herramientas". El número primero porque es lo que NO
// cambia: dice qué es y en qué orden le llega, aunque todavía no tenga
// texto. Antes ponía "(sin título)", que no dice ni qué es.
function tituloDePaso(lista, i) {
  const que = formatoDe(lista) === 'botones' ? 'Botón' : 'Fila';
  const texto = (lista[i].title || '').trim();
  return que + ' ' + (i + 1) + (texto ? ' · ' + texto : ' · (sin texto)');
}


function nuevaOpcion(ruta) {
  const lista = ruta.length === 0
    ? datos.menu
    : (opcionEn(ruta).submenu = opcionEn(ruta).submenu || []);
  lista.push({id: idLibre('opcion'), title: '', accion: 'info', mensaje: ''});
  marcarSucio();
  abrir('opcion', ruta.concat([lista.length - 1]));
}

// ── Los editores: cada uno enseña LO SUYO ─────────────────────────────
function caja(hijos) {
  const c = document.createElement('div');
  c.className = 'editor';
  c.onclick = function (e) { e.stopPropagation(); };
  return c;
}

function siguientePaso(c, texto, etiquetaBoton, alPulsar) {
  const pie = document.createElement('div');
  pie.className = 'siguiente';
  const p = document.createElement('p');
  p.textContent = texto;
  pie.appendChild(p);
  if (etiquetaBoton) pie.appendChild(boton(etiquetaBoton, alPulsar));
  c.appendChild(pie);
}

function editorSaludo() {
  const c = caja();
  const pide = datos.conversacion ? datos.conversacion.pedir_nombre !== false : true;

  conDefecto(campo(c, 'Lo primero que le dices', datos.textos.bienvenida || '',
        function (v) { datos.textos.bienvenida = v; vistaPrevia(); },
        pide ? 'Después de esto, el bot le pregunta su nombre.'
             : 'Después de esto va directo al menú.', true), 'bienvenida');

  // Preguntar el nombre es un mensaje más antes de poder venderle, y casi
  // todo el mundo lo tiene puesto en su WhatsApp.
  etiqueta(c, '¿Y el nombre del cliente?');
  const sel = document.createElement('select');
  [['si', 'Preguntárselo (un mensaje más)'],
   ['no', 'Usar el que tiene puesto en WhatsApp']].forEach(function (o) {
    const op = document.createElement('option');
    op.value = o[0]; op.textContent = o[1];
    op.selected = (pide ? 'si' : 'no') === o[0];
    sel.appendChild(op);
  });
  sel.onchange = function () {
    datos.conversacion = datos.conversacion || {};
    datos.conversacion.pedir_nombre = (sel.value === 'si');
    marcarSucio();
    dibujar();
  };
  c.appendChild(sel);
  ayudita(c, pide
    ? 'Se lo pregunta y espera la respuesta antes de ofrecer el menú.'
    : 'Lo toma de su perfil de WhatsApp. Si no tiene ninguno puesto, se lo '
      + 'pregunta igual: sin nombre se estropean los textos que lo usan.');

  // ── El menú, dentro del mismo módulo ──
  const menu = document.createElement('div');
  menu.className = 'siguiente';
  const t = document.createElement('p');
  t.innerHTML = '<strong>Y después, el menú</strong>';
  menu.appendChild(t);
  c.appendChild(menu);

  conDefecto(campo(c, 'Lo que dice al ofrecer el menú',
        datos.textos.preguntar_necesidad || '',
        function (v) { datos.textos.preguntar_necesidad = v; vistaPrevia(); },
        'Puedes usar {name}.', true), 'preguntar_necesidad');

  // Estas dos SOLO existen si el menú sale como lista. Pedirlas cuando
  // salen botones es pedir que se llene algo que nadie verá.
  if (formatoDe(datos.menu) === 'lista') {
    ayudita(c, 'Como tienes más de ' + K.max_botones + ' botones, el cliente '
      + 've uno solo que abre la lista. Esto es lo que lee en él:');
    campo(c, 'Etiqueta del botón', datos.textos.menu_boton || '',
          function (v) { datos.textos.menu_boton = v; vistaPrevia(); },
          'Máximo 20 caracteres.');
    campo(c, 'Título de la lista', datos.textos.menu_seccion || '',
          function (v) { datos.textos.menu_seccion = v; vistaPrevia(); },
          'La cabecera que ve al abrirla. Máximo 24 caracteres.');
  }

  const cuantos = visibles(datos.menu).length;
  siguientePaso(c, cuantos === 0
    ? 'Todavía no ofrece nada. Añade el primer botón:'
    : 'Tiene ' + cuantos + (cuantos === 1 ? ' botón' : ' botones')
      + ', y cada uno se edita ahí abajo.',
    cuantos === 0 ? '+ Agregar el primer botón' : '+ Agregar otro botón',
    function () { nuevaOpcion([]); });
  return c;
}

function editorVuelve() {
  const c = caja();
  conDefecto(campo(c, 'Cómo saluda a quien ya había escrito',
        datos.textos.bienvenida_de_vuelta || '',
        function (v) { datos.textos.bienvenida_de_vuelta = v; vistaPrevia(); },
        'Puedes usar {name}: el bot ya sabe cómo se llama. Va directo al menú.',
        true), 'bienvenida_de_vuelta');
  return c;
}

// Un <select> de dos o más salidas. Todas las decisiones de "sí o no" del
// mapa se ven igual y se guardan igual: en `datos.conversacion`.
function eleccion(donde, rotulo, valores, elegido, alCambiar) {
  etiqueta(donde, rotulo);
  const sel = document.createElement('select');
  valores.forEach(function (o) {
    const op = document.createElement('option');
    op.value = o[0]; op.textContent = o[1];
    op.selected = elegido === o[0];
    sel.appendChild(op);
  });
  sel.onchange = function () {
    datos.conversacion = datos.conversacion || {};
    alCambiar(sel.value);
    marcarSucio();
    dibujar();
  };
  donde.appendChild(sel);
  return sel;
}

function editorNoEntiende() {
  const c = caja();
  datos.conversacion = datos.conversacion || {};
  const conMenu = datos.conversacion.menu_tras_no_entendi !== false;

  ayudita(c, 'Antes de decir que no entiende, lo intenta: si lo que escribe '
    + 'es el texto de uno de tus botones ("quiero una página web"), hace lo '
    + 'que hace ese botón, esté donde esté la conversación. Con la IA '
    + 'encendida entiende además otras formas de decirlo. Esto es lo que '
    + 'responde cuando ni así.');

  conDefecto(campo(c, 'Lo que dice cuando no entiende',
        datos.textos.no_entendi || '',
        function (v) { datos.textos.no_entendi = v; vistaPrevia(); },
        '', true), 'no_entendi');

  eleccion(c, '¿Y después?',
    [['si', 'Enseñarle otra vez el menú'],
     ['no', 'Nada más, solo la frase']],
    conMenu ? 'si' : 'no',
    function (v) { datos.conversacion.menu_tras_no_entendi = (v === 'si'); });

  if (conMenu) {
    conDefecto(campo(c, 'Lo que pregunta encima del menú',
          datos.textos.no_entendi_menu || '',
          function (v) { datos.textos.no_entendi_menu = v; vistaPrevia(); },
          'Llega en el mismo mensaje que la frase de arriba, con los botones '
          + 'debajo. Puedes usar {name}.', true), 'no_entendi_menu');
  } else {
    ayudita(c, 'Ojo: sin menú, quien no acierta a escribir algo que el bot '
      + 'reconozca recibe la misma frase una y otra vez, sin ningún botón a '
      + 'la vista.');
  }

  const pie = document.createElement('div');
  pie.className = 'siguiente';
  const t = document.createElement('p');
  t.innerHTML = '<strong>Y en cualquier momento</strong>';
  pie.appendChild(t);
  c.appendChild(pie);

  const frases = campo(c, 'Frases que lo devuelven al menú principal',
    (datos.conversacion.palabras_menu || []).join('\n'),
    function (v) {
      datos.conversacion.palabras_menu = v.split('\n')
        .map(function (x) { return x.trim(); }).filter(Boolean);
    },
    'Una por línea. Valen estés donde estés: a mitad de agendar, después '
    + 'de unos precios, cuando le pidió que cuente su consulta. Una palabra '
    + 'sola ("menú") cuenta solo si es lo único que escribe, para no '
    + 'confundirla con "el menú de mi restaurante". Si lo dejas vacío usa '
    + 'las que ves en gris.', true);
  frases.placeholder = (K.palabras_menu_defecto || []).join('\n');
  return c;
}

function editorVacio() {
  const c = caja();
  campo(c, 'Lo que responde mientras no haya menú',
        datos.textos.sin_configurar || '',
        function (v) { datos.textos.sin_configurar = v; vistaPrevia(); },
        'Además te avisa a ti por WhatsApp: para ti es un lead que se '
        + 'está perdiendo.', true);
  return c;
}

function editorPaso(opcion) {
  const c = caja();
  const formato = formatoDe(listaEn(paso.ruta));

  // Por que este paso impidio el ultimo guardado. Va lo primero: es lo
  // que se viene a ver cuando el editor abre este paso solo.
  if (esElError(paso.ruta)) {
    const motivo = document.createElement('p');
    motivo.className = 'motivo';
    motivo.textContent = 'Por esto no se guardó: ' + error.texto;
    c.appendChild(motivo);
  }

  // ⚠️  Este campo NO redibuja el árbol.
  //
  // Redibujarlo destruye y vuelve a crear este mismo recuadro, así que el
  // cursor se perdía en cada tecla: se escribía una letra y había que
  // volver a pulsar dentro para escribir la siguiente. Se actualiza a
  // mano el título de la tarjeta —lo único del árbol que depende de
  // esto— y se repinta la vista previa, que es barata.
  campo(c, 'Texto', opcion.title || '', function (v) {
    opcion.title = v;
    if (!opcion._id_a_mano) opcion.id = idLibre(v);

    const tarjeta = c.parentElement;
    const cabecera = tarjeta && tarjeta.querySelector('.titulo');
    if (cabecera) {
      const hermanos = listaEn(paso.ruta);
      cabecera.textContent = tituloDePaso(hermanos, paso.ruta[paso.ruta.length - 1]);
    }
    vistaPrevia();
  // El tope depende de si sale como boton (20) o como fila de lista
  // (24), y no es un detalle: pasado eso Meta RECHAZA el mensaje entero
  // y el cliente no recibe nada, ni el texto que lo acompañaba. Antes
  // aqui ponia 24 siempre, y "WhatsApp corta el resto" — que tampoco es
  // verdad: no corta, descarta.
  }, formato === 'lista'
       ? 'Lo que el cliente lee en la fila. Máximo 24 caracteres.'
       : 'Lo que el cliente lee dentro del botón. Máximo 20 caracteres: '
         + 'pasado eso WhatsApp no manda el mensaje.');

  // El texto pequeño SOLO se ve en las listas. Con botones no existe.
  if (formato === 'lista') {
    campo(c, 'Texto pequeño debajo', opcion.description || '',
          function (v) { opcion.description = v; vistaPrevia(); },
          'Se ve porque estas opciones salen como lista.');
  }

  const sel = document.createElement('select');
  // "enlace" ya no se ofrece porque hacía lo mismo que responder un
  // texto. Lo guardado sigue valiendo, y aquí se enseña como lo que es.
  const actual = opcion.accion === 'enlace' ? 'info' : opcion.accion;
  K.acciones.forEach(function (a) {
    const op = document.createElement('option');
    op.value = a.clave; op.textContent = a.nombre;
    op.selected = (actual === a.clave);
    sel.appendChild(op);
  });
  sel.onchange = function () { opcion.accion = sel.value; marcarSucio(); dibujar(); };
  etiqueta(c, 'Cuando el cliente la pulsa…');
  c.appendChild(sel);
  const ayuda = K.acciones.find(a => a.clave === actual);
  if (ayuda) ayudita(c, ayuda.ayuda);

  camposDeLaAccion(c, opcion);

  // La lógica que hay detrás de un menú de citas: estas opciones solo
  // tienen sentido para quien ya agendó. Sin esto, a quien nunca lo hizo
  // le aparece "cambiar mi cita" y el único sitio al que puede llevarle
  // es a "no encontramos ninguna reunión".
  const linea = document.createElement('label');
  linea.className = 'marca';
  const marca = document.createElement('input');
  marca.type = 'checkbox';
  marca.checked = !!opcion.solo_con_cita;
  marca.onchange = function () {
    if (marca.checked) { opcion.solo_con_cita = true; }
    else { delete opcion.solo_con_cita; }
    marcarSucio();
    dibujar();
  };
  linea.appendChild(marca);
  linea.appendChild(document.createTextNode(
    ' Enseñársela solo a quien ya tiene una cita'));
  c.appendChild(linea);
  if (K.acciones_de_cita.includes(actual) && !opcion.solo_con_cita) {
    ayudita(c, 'Ojo: sin marcar esto, a quien nunca agendó le aparece igual '
      + 'y solo puede llevarle a "no encontramos ninguna reunión".');
  }

  // Lo que el cliente NO ve. Va aparte y plegado, y lo dice: si no, se
  // llena a ciegas buscándolo en la pantalla de al lado.
  const interno = document.createElement('details');
  interno.className = 'interno';
  const resumen = document.createElement('summary');
  resumen.textContent = 'Para tus informes (esto el cliente no lo ve)';
  interno.appendChild(resumen);
  interno.onclick = function (e) { e.stopPropagation(); };
  campo(interno, 'Cómo se llama este servicio en los informes',
        opcion.servicio || '', function (v) { opcion.servicio = v; });
  campo(interno, 'Cómo se llama este paso en el recorrido',
        opcion.paso || '', function (v) { opcion.paso = v; });
  c.appendChild(interno);

  const barra = document.createElement('div');
  barra.className = 'acciones-paso';
  barra.appendChild(boton('Subir', function () { mover(-1); }));
  barra.appendChild(boton('Bajar', function () { mover(1); }));
  barra.appendChild(boton('Quitar este paso', function () { quitar(); }, true));
  c.appendChild(barra);
  return c;
}

function camposDeLaAccion(c, opcion) {
  const a = opcion.accion;

  if (a === 'submenu') {
    campo(c, 'Lo que dice al abrir estas opciones', opcion.mensaje || '',
          function (v) { opcion.mensaje = v; vistaPrevia(); }, '', true);
    siguientePaso(c, 'Las opciones de dentro se añaden justo debajo, en el mapa.',
                  '+ Añadir una opción aquí dentro',
                  function () { nuevaOpcion(paso.ruta); });
  }

  if (a === 'info' || a === 'enlace') {
    // ⚠️  El texto puede venir de la sección [precios] en vez de estar en
    // la opción. Es la misma indirección que tenían los enlaces: la
    // opción dice `precios = "chatbot"` y `config_cliente._opcion`
    // SOBRESCRIBE su mensaje con ese bloque.
    //
    // Eso hacía dos cosas, las dos malas: el recuadro salía vacío aunque
    // el bot sí mandara un texto, y lo que se escribiera aquí lo pisaba
    // el bloque compartido al construir la configuración. O sea que se
    // editaba a ciegas algo que nunca se iba a usar.
    //
    // Ahora se enseña lo que el cliente recibe de verdad, y al tocarlo la
    // opción se queda con SU texto: se quita `precios` para que nada lo
    // vuelva a pisar. Los otros servicios que compartían ese bloque
    // siguen igual.
    campo(c, 'Lo que responde',
          opcion.mensaje || (datos.precios || {})[opcion.precios] || '',
          function (v) {
            opcion.mensaje = v;
            delete opcion.precios;
            vistaPrevia();
          }, opcion.precios
             ? 'Este texto venía de tus precios compartidos. Al cambiarlo, '
               + 'esta opción se queda con el suyo y las demás no se tocan.'
             : '', true);
    // ⚠️  El enlace se guarda EN LA OPCIÓN, no en el diccionario común.
    //
    // Antes se escribía en `[enlaces]` con una clave, y las opciones
    // apuntaban a ella por nombre. Eso permite compartir un enlace entre
    // varias —el `precios` del dueño lo usaban cuatro— y por eso mismo
    // era una trampa: **vaciar el campo en UNA borraba el enlace de las
    // otras tres**, que se quedaban apuntando a algo que ya no existe. Al
    // guardar reventaba con "pide el enlace X, que no está en [enlaces]",
    // señalando una opción que nadie había tocado.
    //
    // `bot_logic` lee `opcion.url` directamente, así que cada opción
    // puede llevar el suyo y nadie pisa a nadie. Lo que ya estaba
    // compartido sigue funcionando hasta que se edite: `config_cliente`
    // resuelve `enlace` igual que siempre. Por eso al escribir aquí se
    // quita `enlace` — si se quedara, ganaría sobre lo que se acaba de
    // escribir.
    campo(c, 'Enlace que acompaña (opcional)',
          opcion.url || datos.enlaces[opcion.enlace] || '', function (v) {
            const url = v.trim();
            if (url) {
              opcion.url = url;
              delete opcion.enlace;
            } else {
              // Se BORRAN las dos claves en vez de dejarlas vacías: una
              // opción de texto con `url` en blanco no se le enseña al
              // cliente (ver `_opciones_para_mostrar`).
              delete opcion.url;
              delete opcion.enlace;
            }
            vistaPrevia();
          }, 'Se pega dentro del mensaje donde escribas {url}. Es de esta '
             + 'opción: no afecta a las demás.');
  }

  if (a === 'info') {
    // Es un mensaje entero, no un rotulo: va en cuadro y admite saltos.
    campo(c, 'Qué pregunta después (opcional)', opcion.pregunta || '',
          function (v) { opcion.pregunta = v; vistaPrevia(); }, '', true);
    ayudita(c, 'Se manda pegado a tu respuesta, justo encima de los botones '
      + 'de abajo. Si lo dejas vacío no se dice nada: el cliente recibe tu '
      + 'texto y los botones, y ya.');
    siguientes(c, opcion);
  }

  if (a === 'cita') ayudita(c, 'Necesita el calendario de Google en la ficha del negocio.');
  if (a === 'humano') {
    // Es un ajuste del NEGOCIO y no de esta opción: un menú suele tener
    // un "Hablar con un asesor" en cada rama, y decidirlo cuatro veces
    // es invitar a que queden distintos sin querer.
    datos.conversacion = datos.conversacion || {};
    const pide = datos.conversacion.asesor_pide_detalle !== false;

    eleccion(c, 'Antes de avisarte…',
      [['no', 'Pasarlo directo, sin preguntar'],
       ['si', 'Pedirle que cuente su consulta']],
      pide ? 'si' : 'no',
      function (v) { datos.conversacion.asesor_pide_detalle = (v === 'si'); });
    ayudita(c, pide
      ? 'Es un mensaje más, y quien llegó hasta este botón casi siempre ya '
        + 'dijo lo que quiere con los que pulsó antes.'
      : 'Te avisa al instante y le dice al cliente que en unos momentos le '
        + 'escriben.');

    if (pide) {
      conDefecto(campo(c, 'Lo que le pide', datos.textos.otra_consulta || '',
            function (v) { datos.textos.otra_consulta = v; vistaPrevia(); },
            'Puedes usar {name}.', true), 'otra_consulta');
      conDefecto(campo(c, 'Lo que dice cuando ya la contó',
            datos.textos.paso_a_asesor || '',
            function (v) { datos.textos.paso_a_asesor = v; vistaPrevia(); },
            'Puedes usar {name}. Lo que escribió va en el aviso que te llega.',
            true), 'paso_a_asesor');
    } else {
      conDefecto(campo(c, 'Lo que le dice', datos.textos.asesor_directo || '',
            function (v) { datos.textos.asesor_directo = v; vistaPrevia(); },
            'Puedes usar {name}. El aviso que te llega dice qué botón pulsó y '
            + 'por dónde llegó hasta él, así que sabes de qué va sin '
            + 'preguntárselo.', true), 'asesor_directo');
    }
    ayudita(c, 'Te llega un aviso y el bot se calla en ese chat. Esto vale '
      + 'para TODOS tus botones de "Pasar a una persona".');
  }
}

// "Y le vuelve a ofrecer…": que botones salen DESPUES de esta respuesta.
//
// Ademas de las opciones hermanas, aqui salen SIEMPRE las dos salidas
// fijas —"Menú principal" y "Atrás"—, que no son opciones de ningun menu:
// las arma el bot. Antes solo se podian ofrecer las hermanas, asi que una
// rama honda dejaba al cliente sin ninguna forma de volver: leia la
// respuesta y se quedaba ahi. La unica salida era escribir a mano una
// opcion "volver" en cada grupo, y nadie se acuerda de hacerlo en todos.
function siguientes(c, opcion) {
  const luego = opcion.luego || [];
  const caja = document.createElement('div');

  function casilla(donde, clave, rotulo, ayuda) {
    const linea = document.createElement('label');
    linea.className = 'marca';
    const marca = document.createElement('input');
    marca.type = 'checkbox';
    marca.checked = luego.includes(clave);
    marca.onchange = function () {
      const puesto = new Set(opcion.luego || []);
      if (marca.checked) { puesto.add(clave); } else { puesto.delete(clave); }
      opcion.luego = Array.from(puesto);
      marcarSucio();
      vistaPrevia();
    };
    linea.appendChild(marca);
    linea.appendChild(document.createTextNode(' ' + rotulo));
    if (ayuda) {
      const nota = document.createElement('small');
      nota.className = 'tenue';
      nota.textContent = '  ' + ayuda;
      linea.appendChild(nota);
    }
    donde.appendChild(linea);
  }

  listaEn(paso.ruta).forEach(function (otra) {
    if (otra.id === opcion.id) return;
    casilla(caja, otra.id, otra.title || otra.id);
  });

  etiqueta(c, 'Y le vuelve a ofrecer…');
  c.appendChild(caja);

  const salidas = document.createElement('div');
  salidas.className = 'salidas-fijas';
  const titulo = document.createElement('p');
  titulo.className = 'ayuda';
  titulo.textContent = 'Estas dos existen siempre, no hace falta crearlas:';
  salidas.appendChild(titulo);
  (K.fijas || []).forEach(function (f) {
    casilla(salidas, f.clave, f.nombre, f.ayuda);
  });
  c.appendChild(salidas);

  // El aviso ANTES de que pase, igual que en el arbol: a partir de 4 el
  // cliente deja de ver los botones y tiene que abrir una lista.
  const marcadas = (opcion.luego || []).length;
  if (marcadas > K.max_botones) {
    ayudita(c, 'Son ' + marcadas + ', así que le llegan como lista '
      + 'desplegable: verá un botón y tendrá que abrirlo.');
  }
}

// ── La vista previa ───────────────────────────────────────────────────
function burbuja(clase, texto) {
  const b = document.createElement('div');
  b.className = 'burbuja ' + clase;
  b.textContent = texto;
  return b;
}

function nota(texto) {
  const n = document.createElement('div');
  n.className = 'wa-nota';
  n.textContent = texto;
  return n;
}

function opcionesWa(lista, resaltar) {
  const c = document.createElement('div');
  const vis = visibles(lista);
  if (vis.length === 0) return c;

  if (formatoDe(lista) === 'botones') {
    c.className = 'wa-botones';
    vis.forEach(function (o) {
      const b = document.createElement('div');
      b.className = 'wa-boton';
      b.textContent = o.title || '(sin título)';
      if (o.id === resaltar) b.classList.add('wa-foco');
      c.appendChild(b);
    });
  } else {
    c.className = 'wa-lista';
    const b = document.createElement('div');
    b.className = 'wa-boton';
    b.textContent = '☰ ' + (datos.textos.menu_boton || 'Ver opciones');
    c.appendChild(b);
    const filas = document.createElement('div');
    filas.className = 'filas';
    const titulo = document.createElement('div');
    titulo.className = 'fila';
    const s = document.createElement('small');
    s.textContent = datos.textos.menu_seccion || '¿Qué necesitas?';
    titulo.appendChild(s);
    filas.appendChild(titulo);
    vis.forEach(function (o) {
      const f = document.createElement('div');
      f.className = 'fila';
      f.textContent = o.title || '(sin título)';
      if (o.description) {
        const d = document.createElement('small');
        d.textContent = o.description;
        f.appendChild(d);
      }
      if (o.id === resaltar) f.classList.add('wa-foco');
      filas.appendChild(f);
    });
    c.appendChild(filas);
  }
  return c;
}

function vistaPrevia() {
  const chat = document.getElementById('vista');
  const pie = document.getElementById('pie-vista');
  chat.innerHTML = '';
  const vacio = visibles(datos.menu).length === 0;

  // Cada paso pinta SU momento. Es lo que hace que se vea lo que se está
  // escribiendo en vez de tener que imaginárselo.
  if (paso.tipo === 'vuelve') {
    chat.appendChild(nota('Ana ya había escrito antes'));
    chat.appendChild(burbuja('cliente', 'Hola de nuevo'));
    chat.appendChild(burbuja('bot', conVariables(
      datos.textos.bienvenida_de_vuelta || '(sin texto: escríbelo al lado)')));
    if (!vacio) {
      chat.appendChild(burbuja('bot', conVariables(
        datos.textos.preguntar_necesidad || '¿En qué te ayudo?')));
      chat.appendChild(opcionesWa(datos.menu, null));
    }
    pie.textContent = 'Quien vuelve no tiene que decir su nombre otra vez.';
    chat.scrollTop = chat.scrollHeight;
    return;
  }

  if (paso.tipo === 'no_entiende') {
    const conMenu = !datos.conversacion
      || datos.conversacion.menu_tras_no_entendi !== false;
    const ejemplo = visibles(datos.menu)[0];
    chat.appendChild(nota('Ana ya tiene el menú más arriba y escribe:'));
    if (ejemplo && ejemplo.title) {
      chat.appendChild(burbuja('cliente', 'Quiero ' + ejemplo.title.toLowerCase()));
      chat.appendChild(nota('Es el texto de un botón: hace lo que hace «'
        + ejemplo.title + '».'));
    }
    chat.appendChild(burbuja('cliente', 'mmm no sé, lo otro'));
    const frase = conVariables(datos.textos.no_entendi || K.defectos.no_entendi);
    const pregunta = conVariables(datos.textos.no_entendi_menu
      || K.defectos.no_entendi_menu);
    chat.appendChild(burbuja('bot', conMenu && !vacio
      ? frase + '\n\n' + pregunta : frase));
    if (conMenu && !vacio) chat.appendChild(opcionesWa(datos.menu, null));
    pie.textContent = conMenu && !vacio
      ? 'La frase, la pregunta y los botones llegan en un solo mensaje.'
      : 'Solo la frase, sin botones.';
    chat.scrollTop = chat.scrollHeight;
    return;
  }

  chat.appendChild(burbuja('cliente', 'Hola'));
  chat.appendChild(burbuja('bot', conVariables(
    datos.textos.bienvenida || '(sin saludo: escríbelo al lado)')));

  // Si el negocio NO pregunta el nombre, el cliente no contesta nada:
  // el bot ya lo sabe por su perfil de WhatsApp y va directo al menú.
  const pideNombre = datos.conversacion
    ? datos.conversacion.pedir_nombre !== false : true;

  if (pideNombre) {
    chat.appendChild(burbuja('cliente', 'Ana'));
  } else {
    chat.appendChild(nota('Toma "Ana" de su perfil de WhatsApp'));
  }

  if (vacio) {
    chat.appendChild(burbuja('bot', conVariables(
      datos.textos.sin_configurar ||
      '¡Hola! Gracias por escribir. En un momento te atendemos.')));
    chat.appendChild(nota('El menú está vacío: responde esto y te avisa a ti.'));
    pie.textContent = 'Así se ve hoy la conversación completa.';
    chat.scrollTop = chat.scrollHeight;
    return;
  }

  chat.appendChild(burbuja('bot', conVariables(
    datos.textos.preguntar_necesidad || '¿En qué te ayudo?')));

  const ruta = (paso.tipo === 'opcion' && paso.ruta) || [];
  chat.appendChild(opcionesWa(
    datos.menu, ruta.length && datos.menu[ruta[0]] ? datos.menu[ruta[0]].id : null));

  if (paso.tipo === 'saludo') {
    pie.textContent = formatoDe(datos.menu) === 'botones'
      ? 'Con ' + K.max_botones + ' o menos, los botones se ven directamente.'
      : 'Con más de ' + K.max_botones + ', el cliente tiene que abrir la lista.';
    chat.scrollTop = chat.scrollHeight;
    return;
  }

  // El recorrido hasta el paso abierto, para verlo en contexto.
  let lista = datos.menu;
  for (let nivel = 0; nivel < ruta.length; nivel++) {
    const opcion = lista[ruta[nivel]];
    if (!opcion) break;
    if (opcion.solo_con_cita) {
      chat.appendChild(nota('Esta opción solo la ve quien ya tiene una cita'));
    }
    chat.appendChild(burbuja('cliente', opcion.title || '(sin título)'));

    if (opcion.accion === 'submenu') {
      chat.appendChild(burbuja('bot', conVariables(opcion.mensaje || '¿Por dónde seguimos?')));
      const hijos = opcion.submenu || [];
      const siguiente = (ruta[nivel + 1] !== undefined) ? hijos[ruta[nivel + 1]] : null;
      chat.appendChild(opcionesWa(hijos, siguiente ? siguiente.id : null));
      lista = hijos;
      continue;
    }

    if (opcion.accion === 'info' || opcion.accion === 'enlace') {
      let texto = conVariables(
        opcion.mensaje || (datos.precios || {})[opcion.precios]
        || '(sin texto: escríbelo al lado)');
      const url = opcion.url || datos.enlaces[opcion.enlace];
      if (url) texto = texto.split('(el enlace)').join(url);
      chat.appendChild(burbuja('bot', texto));
      if (opcion.accion === 'info' && (opcion.luego || []).length) {
        if (opcion.pregunta) chat.appendChild(burbuja('bot', conVariables(opcion.pregunta)));
        // Las salidas fijas no estan en `lista` —no son opciones de
        // ningun menu—, asi que se arman aqui con su etiqueta. Sin esto
        // se marcaba la casilla y la vista previa no cambiaba, que es
        // justo lo que esta pantalla promete que no pasa.
        const luego = (opcion.luego || [])
          .map(function (id) {
            const fija = (K.fijas || []).find(function (f) { return f.clave === id; });
            if (fija) return {id: id, title: fija.nombre};
            return lista.find(function (o) { return o.id === id; });
          })
          .filter(Boolean);
        chat.appendChild(opcionesWa(luego, null));
      }
    } else if (opcion.accion === 'cita') {
      chat.appendChild(burbuja('bot', '¿Qué día te viene bien?'));
      chat.appendChild(nota('Aquí ofrece los días libres de tu calendario.'));
    } else if (opcion.accion === 'humano') {
      const pide = !datos.conversacion
        || datos.conversacion.asesor_pide_detalle !== false;
      if (pide) {
        chat.appendChild(burbuja('bot', conVariables(
          datos.textos.otra_consulta || K.defectos.otra_consulta)));
        chat.appendChild(burbuja('cliente', '¿Hacen envíos a otras ciudades?'));
        chat.appendChild(burbuja('bot', conVariables(
          datos.textos.paso_a_asesor || K.defectos.paso_a_asesor)));
      } else {
        chat.appendChild(burbuja('bot', conVariables(
          datos.textos.asesor_directo || K.defectos.asesor_directo)));
      }
      chat.appendChild(nota('El bot se calla en este chat y te avisa a ti.'));
    } else if (opcion.accion === 'menu') {
      chat.appendChild(nota('Vuelve a ofrecer el menú principal.'));
    } else if (opcion.accion === 'reagendar') {
      chat.appendChild(burbuja('bot', '¿Para qué día lo movemos?'));
      chat.appendChild(nota('Busca su cita, le ofrece otros días y la mueve '
        + 'en tu calendario.'));
    } else if (opcion.accion === 'cancelar') {
      chat.appendChild(burbuja('bot', 'Listo, cancelé tu cita.'));
      chat.appendChild(nota('La borra de tu calendario y de tu hoja.'));
    } else if (opcion.accion === 'terminar') {
      chat.appendChild(burbuja('bot', '¡Gracias por escribir!'));
      chat.appendChild(nota('Se despide y calla hasta que el cliente vuelva.'));
    }
    break;
  }

  pie.textContent = 'El recorrido hasta el paso que tienes abierto.';
  chat.scrollTop = chat.scrollHeight;
}

// ── Piezas del formulario ─────────────────────────────────────────────
function etiqueta(donde, texto) {
  const l = document.createElement('label');
  l.textContent = texto;
  donde.appendChild(l);
}

function ayudita(donde, texto) {
  const p = document.createElement('p');
  p.className = 'ayuda';
  p.textContent = texto;
  donde.appendChild(p);
}

// `area` = el valor es el CUERPO de un mensaje y puede llevar saltos de
// linea. Sin area es un rotulo de WhatsApp —la etiqueta de un boton, el
// titulo de una lista— que va en una sola linea por obligacion de Meta.
//
// ⚠️  No es una preferencia visual: un `<input>` NO GUARDA SALTOS DE
// LINEA. El navegador se los quita al pintar el campo, asi que un texto
// guardado con saltos los perdia solo con abrir esta pantalla. Antes de
// mover un campo de textarea a input, mira `mapa.TEXTOS_DE_UNA_LINEA`.
function campo(donde, nombre, valor, alCambiar, ayuda, area) {
  etiqueta(donde, nombre);
  const entrada = document.createElement(area ? 'textarea' : 'input');
  if (area) entrada.rows = 3;
  entrada.value = valor || '';
  entrada.oninput = function () { alCambiar(entrada.value); marcarSucio(); };
  donde.appendChild(entrada);
  if (ayuda) ayudita(donde, ayuda);
  // El cuadro crece con lo que se escriba. Se pide DESPUES de meterlo en
  // la pagina: un elemento suelto todavia no tiene altura que medir.
  if (area && window.acomodarCampo) window.acomodarCampo(entrada);
  return entrada;
}

// Le pone de marcador lo que el bot diría si se deja vacío.
function conDefecto(entrada, clave) {
  entrada.placeholder = K.defectos[clave] || '';
  return entrada;
}


function boton(texto, alPulsar, peligro) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'suave';
  b.textContent = texto;
  if (peligro) b.style.color = 'var(--mal)';
  b.onclick = function (e) { e.stopPropagation(); alPulsar(); };
  return b;
}

function mover(delta) {
  const lista = listaEn(paso.ruta);
  const i = paso.ruta[paso.ruta.length - 1];
  const j = i + delta;
  if (j < 0 || j >= lista.length) return;
  const guardado = lista[i];
  lista[i] = lista[j];
  lista[j] = guardado;
  marcarSucio();
  abrir('opcion', paso.ruta.slice(0, -1).concat([j]));
}

function quitar() {
  const opcion = opcionEn(paso.ruta);
  const dentro = (opcion.submenu || []).length;
  const aviso = dentro
    ? 'Se lleva también las ' + dentro + ' opciones que tiene dentro. ¿Seguro?'
    : '¿Quitar este paso?';
  if (!window.confirm(aviso)) return;
  listaEn(paso.ruta).splice(paso.ruta[paso.ruta.length - 1], 1);
  marcarSucio();
  abrir('saludo');
}

// ── Cómo responde la IA ───────────────────────────────────────────────
function pintarIA() {
  const c = document.getElementById('ia');
  // Sin caja de IA en la página (un plan que no la trae), no hay nada que
  // pintar: lo que tenga guardado se queda como está.
  if (!c) return;
  c.innerHTML = '';
  datos.ia = datos.ia || {};

  K.campos_ia.forEach(function (campoIA) {
    if (campoIA.forma === 'lista') {
      const valor = (datos.ia[campoIA.clave] || []).join('\n');
      campo(c, campoIA.nombre, valor, function (v) {
        datos.ia[campoIA.clave] = v.split('\n')
          .map(function (x) { return x.trim(); }).filter(Boolean);
      }, campoIA.ayuda, true);
    } else if (campoIA.forma === 'numero') {
      const entrada = campo(c, campoIA.nombre, datos.ia[campoIA.clave] || 60,
                            function (v) { datos.ia[campoIA.clave] = v; },
                            campoIA.ayuda);
      entrada.type = 'number';
      entrada.min = 10;
    } else {
      campo(c, campoIA.nombre, datos.ia[campoIA.clave] || '',
            function (v) { datos.ia[campoIA.clave] = v; }, campoIA.ayuda);
    }
  });
}

// ── Los demás textos ──────────────────────────────────────────────────
function pintarOtrosTextos() {
  const caja = document.getElementById('otros-textos');
  caja.innerHTML = '';

  K.grupos_de_textos.forEach(function (g) {
    const bloque = document.createElement('details');
    bloque.className = 'interno';
    const titulo = document.createElement('summary');

    // Cuántos ha tocado el negocio, para no tener que abrirlos todos
    // buscando dónde cambió algo.
    const propios = g.campos.filter(function (c) {
      return (datos.textos[c.clave] || '').trim();
    }).length;
    titulo.textContent = g.grupo + '  (' + propios + ' de ' + g.campos.length
      + ' escritos por ti)';
    bloque.appendChild(titulo);

    g.campos.forEach(function (c) {
      // Cuadro o renglon segun lo que sea el texto, no segun lo que mida:
      // `una_linea` lo dice desde Python (`mapa.TEXTOS_DE_UNA_LINEA`).
      const entrada = campo(bloque, c.nombre, datos.textos[c.clave] || '',
                            function (v) { datos.textos[c.clave] = v; },
                            '', !c.una_linea);
      // El defecto va de marcador, no de valor: si se metiera dentro, al
      // guardar quedaría como texto propio del negocio y dejaría de
      // seguir al del producto cuando este mejore.
      entrada.placeholder = c.defecto || '(el bot no dice nada aquí)';
    });

    caja.appendChild(bloque);
  });
}


// ── Variables ─────────────────────────────────────────────────────────
function pintarVariables() {
  const c = document.getElementById('variables');
  c.innerHTML = '';
  const nombres = Object.keys(datos.variables);

  if (nombres.length === 0) {
    const p = document.createElement('p');
    p.className = 'vacio';
    p.textContent = 'Ninguna todavía. {negocio} funciona siempre, sin declararla.';
    c.appendChild(p);
  }

  nombres.forEach(function (nombre) {
    const fila = document.createElement('div');
    fila.className = 'variable';

    const n = document.createElement('input');
    n.value = nombre;
    n.onchange = function () {
      const nuevo = n.value.trim();
      if (!nuevo || nuevo === nombre) { n.value = nombre; return; }
      datos.variables[nuevo] = datos.variables[nombre];
      delete datos.variables[nombre];
      marcarSucio(); pintarVariables(); vistaPrevia();
    };

    const v = document.createElement('input');
    v.value = datos.variables[nombre];
    v.oninput = function () {
      datos.variables[nombre] = v.value;
      marcarSucio();
      vistaPrevia();
    };

    fila.appendChild(n);
    fila.appendChild(v);
    fila.appendChild(boton('Quitar', function () {
      delete datos.variables[nombre];
      marcarSucio(); pintarVariables(); vistaPrevia();
    }, true));
    c.appendChild(fila);
  });
}

function agregarVariable() {
  let n = 'variable', i = 2;
  while (datos.variables[n] !== undefined) { n = 'variable' + i; i++; }
  datos.variables[n] = '';
  marcarSucio();
  pintarVariables();
}

// ── Guardar ───────────────────────────────────────────────────────────
async function guardar() {
  const banda = document.getElementById('banda-guardado');
  banda.hidden = false;
  banda.className = 'banda';
  banda.textContent = 'Guardando…';

  // El error de la vez anterior deja de valer aqui: o esta arreglado, o
  // el servidor lo vuelve a decir dentro de un momento. Dejarlo pintado
  // mientras se guarda haria dudar de cual de los dos se esta leyendo.
  const habia = error;
  error = null;
  if (habia) dibujar();

  try {
    // A dónde se guarda: la página lo dice (`GUARDAR_EN`). El mismo mapa
    // lo usan el super-admin y el dueño desde su panel, cada uno por su
    // ruta y con su sesión.
    const r = await fetch(GUARDAR_EN, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(datos),
    });
    const respuesta = await r.json();

    if (respuesta.ok) {
      banda.className = 'banda ok';
      // El servidor sigue releyendo de la base antes de responder —es la
      // diferencia entre "se envió" y "quedó escrito"— pero eso ya no se
      // le cuenta a quien edita: el detalle era andamiaje para cazar un
      // fallo, y una vez cazado solo estorba. Sigue en la respuesta por
      // si hace falta mirarlo.
      banda.textContent = 'Guardado exitosamente';
      sucio = false;
      const pista = document.getElementById('pista-guardado');
      pista.textContent = 'Sin cambios';
      pista.dataset.sucio = 'no';
    } else {
      banda.className = 'banda mal';
      banda.innerHTML = '';

      const que = document.createElement('div');
      que.textContent = 'No se guardó nada. ' + (respuesta.error || '');
      banda.appendChild(que);

      // DÓNDE está, y no solo qué pasa. Con un menú de tres niveles,
      // "'Ver un ejemplo' está vacía" deja abriendo pasos uno por uno
      // hasta dar con el que es — y dos botones pueden llamarse igual en
      // ramas distintas.
      if (respuesta.donde) {
        const donde = document.createElement('div');
        donde.className = 'banda-donde';
        donde.textContent = 'Está en: ' + respuesta.donde;
        banda.appendChild(donde);
      }

      // Y se ABRE solo, con el motivo escrito DENTRO del paso.
      //
      // Llevar hasta alli y dejar la explicacion arriba del todo obliga a
      // ir y volver: la banda se queda fuera de la pantalla en cuanto el
      // paso esta hondo. Con el motivo dentro, el sitio y la razon se
      // leen de una vez, que es lo que hacia falta.
      if (respuesta.ruta && respuesta.ruta.length
          && opcionEn(respuesta.ruta)) {
        error = {ruta: respuesta.ruta, texto: respuesta.error || ''};
        abrir('opcion', respuesta.ruta);
        const tarjeta = document.querySelector('#arbol .paso.elegido');
        if (tarjeta) {
          // `start` y no `center`: la tarjeta lleva dentro el editor
          // entero, asi que centrarla dejaba su TITULO por encima del
          // borde de arriba — se llegaba al sitio sin ver cual era. El
          // hueco para la cabecera lo pone `scroll-margin-top`.
          //
          // Y de golpe, sin `behavior: 'smooth'`. Con el suave probando
          // esto la pagina se quedo QUIETA mas de una vez —un desplazado
          // suave lo cancela cualquier otro desplazamiento, y al abrir el
          // paso la vista previa mueve su propio chat—, o sea que a veces
          // avisaba del error y no llevaba a ninguna parte. El destello
          // es lo que dice donde aterrizo la vista; la animacion sobraba.
          tarjeta.scrollIntoView({block: 'start'});
          // Quitar y volver a poner la clase en el mismo cuadro de
          // animacion no reinicia nada: sin leer `offsetWidth` en medio,
          // al guardar dos veces seguidas el segundo aviso no parpadea.
          tarjeta.classList.remove('destello');
          void tarjeta.offsetWidth;
          tarjeta.classList.add('destello');
        }
        return;
      }
    }
  } catch (e) {
    banda.className = 'banda mal';
    banda.textContent = 'No se pudo hablar con el servidor: ' + e;
  }
  banda.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

dibujar();
pintarOtrosTextos();
pintarIA();
pintarVariables();
// Lo mismo que al final de `dibujar()`: estos tres tambien arman sus
// cuadros sueltos y los cuelgan despues.
if (window.acomodarCampos) window.acomodarCampos();
