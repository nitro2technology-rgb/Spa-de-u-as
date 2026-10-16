/* LA AGENDA
   ─────────────────────────────────────────────────────────────────
   La misma gente que la bandeja, vista como directorio. La bandeja
   responde a "¿a quién atiendo ahora?"; esto, a "¿quién me ha escrito?".

   Pinta la tabla y filtra al escribir. El filtro trabaja sobre lo que ya
   está cargado: son como mucho unos cientos de contactos, y una ida al
   servidor por letra escrita se notaría más que lo que ahorra.

   Los guiones del panel comparten ámbito y se ejecutan EN ORDEN. Lo que
   declara `panel-base.js` lo ven los demás. */

let CONTACTOS = [];
let BUSCADO = '';

function inicialesDe(nombre) {
  const partes = (nombre || '').split(/\s+/).filter(Boolean);
  if (!partes.length) return '?';
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
  return (partes[0][0] + partes[1][0]).toUpperCase();
}

/* La fecha, en la de quien mira.

   El servidor manda el instante en UTC; el navegador es el único de los
   dos que sabe en qué huso está sentado quien atiende. */
function fechaDe(iso) {
  if (!iso) return '—';
  const t = new Date(iso);
  if (isNaN(t)) return '—';

  const hoy = new Date();
  if (t.toDateString() === hoy.toDateString()) {
    return t.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  }

  const ayer = new Date(hoy);
  ayer.setDate(ayer.getDate() - 1);
  if (t.toDateString() === ayer.toDateString()) return 'Ayer';

  return t.toLocaleDateString([], {day: '2-digit', month: 'short'});
}

function chip(texto, clase) {
  const s = document.createElement('span');
  s.className = 'chip' + (clase ? ' ' + clase : '');
  s.textContent = texto;
  return s;
}

// El icono que abre el hilo. Va como SVG y no como archivo: son tres
// trazos y sigue el color del texto.
const _FLECHA =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
  'aria-hidden="true"><path d="M5 12h13"/><path d="m12 5 7 7-7 7"/></svg>';

function pintarContactos() {
  const cuerpo = document.querySelector('.tabla-cuerpo');
  if (!cuerpo) return;

  const visibles = CONTACTOS.filter(function (c) {
    if (!BUSCADO) return true;
    const donde = (c.name || '') + ' ' + c.phone + ' ' +
                  (c.etiquetas || []).join(' ');
    return donde.toLowerCase().includes(BUSCADO);
  });

  if (!visibles.length) {
    const vacio = document.createElement('p');
    vacio.className = 'tabla-vacia';
    vacio.textContent = CONTACTOS.length
      ? 'Ningún contacto coincide.'
      : 'Todavía no te ha escrito nadie.';
    cuerpo.replaceChildren(vacio);
    return;
  }

  cuerpo.replaceChildren(...visibles.map(function (c) {
    const fila = document.createElement('a');
    fila.className = 'tabla-fila';
    fila.href = '/admin/chat/' + encodeURIComponent(c.phone);

    // 1. Quién es.
    const quien = document.createElement('div');
    quien.className = 'celda-contacto';
    const inicial = document.createElement('span');
    inicial.className = 'conv-inicial';
    inicial.setAttribute('aria-hidden', 'true');
    inicial.textContent = inicialesDe(c.name);
    const nombres = document.createElement('div');
    nombres.className = 'celda-nombres';
    const nombre = document.createElement('span');
    nombre.className = 'celda-nombre';
    nombre.textContent = c.name || 'Sin nombre';
    const origen = document.createElement('span');
    origen.className = 'celda-origen';
    origen.textContent = c.origen || '—';
    nombres.append(nombre, origen);
    quien.append(inicial, nombres);

    // 2. El teléfono, con cifras del mismo ancho para poder compararlos
    //    de un vistazo en una columna.
    const tel = document.createElement('span');
    tel.className = 'celda-telefono telefono';
    tel.textContent = c.phone;

    // 3. Lo que describe a este contacto: lo que dedujo el bot y lo
    //    que le puso una persona a mano.
    const etiquetas = document.createElement('div');
    etiquetas.className = 'celda-etiquetas';
    if (c.servicio) etiquetas.appendChild(chip(c.servicio, 'servicio'));
    (c.etiquetas || []).forEach(t => etiquetas.appendChild(chip(t, 'etiqueta')));
    if (c.estado_atencion) {
      etiquetas.appendChild(chip(
        ETIQUETAS_ESTADO[c.estado_atencion] || c.estado_atencion,
        'estado ' + c.estado_atencion));
    }
    // Que el último mensaje sea del cliente es lo único que dice, sin que
    // nadie tenga que acordarse de marcarlo, que ahí falta contestar.
    if (c.esperando) etiquetas.appendChild(chip('sin responder', 'humano'));
    if (!etiquetas.childElementCount) {
      const nada = document.createElement('span');
      nada.className = 'celda-vacia';
      nada.textContent = '—';
      etiquetas.appendChild(nada);
    }

    // 4. Cuándo escribió por última vez, y qué dijo.
    const ultimo = document.createElement('div');
    ultimo.className = 'celda-ultimo';
    const cuando = document.createElement('span');
    cuando.className = 'celda-cuando';
    cuando.textContent = fechaDe(c.cuando);
    const texto = document.createElement('span');
    texto.className = 'celda-resumen';
    texto.textContent = c.resumen || 'sin mensajes';
    ultimo.append(cuando, texto);

    // 5. Y la salida hacia su conversación.
    const ir = document.createElement('span');
    ir.className = 'celda-ir';
    ir.setAttribute('aria-hidden', 'true');
    ir.innerHTML = _FLECHA;

    fila.append(quien, tel, etiquetas, ultimo, ir);
    return fila;
  }));
}

const _buscarContacto = document.getElementById('buscar-contacto');
if (_buscarContacto) {
  _buscarContacto.addEventListener('input', function () {
    BUSCADO = _buscarContacto.value.trim().toLowerCase();
    pintarContactos();
  });
}

const _datos = document.getElementById('contactos-inicial');
if (_datos) {
  CONTACTOS = JSON.parse(_datos.textContent);
  pintarContactos();
}
