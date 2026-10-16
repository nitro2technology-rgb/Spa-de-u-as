/* El listado de conversaciones
   ─────────────────────────────────────────────────────────────────
   Vivía dentro de una f-string de Python. Ahí, cada llave había que
   escribirla doblada para que Python no la tomara por un hueco, y un
   descuido no daba un error de JavaScript: daba un error de Python al
   arrancar el servidor.

   Los guiones del panel comparten ámbito y se ejecutan EN ORDEN (van con
   `defer`, que lo respeta). Lo que declara `panel-base.js` lo ven los
   demás. Los valores que dependen del negocio llegan en `PANEL`, que la
   página define antes que estos archivos.

   El buscador y los filtros trabajan sobre lo que YA está cargado. Son
   como mucho unas decenas de conversaciones: una ida al servidor por
   letra escrita se notaría más que lo que ahorra, y encima dejaría de
   funcionar en cuanto la red va lenta, que es justo cuando uno busca. */

// Lo último que llegó del servidor. Se guarda para poder repintar al
// escribir en el buscador o al cambiar de filtro sin volver a pedirlo.
let CONVERSACIONES = [];
let BUSQUEDA = '';
let FILTRO = 'todas';

function inicialesDe(nombre) {
  const partes = (nombre || '').split(/\s+/).filter(Boolean);
  if (!partes.length) return '?';
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
  return (partes[0][0] + partes[1][0]).toUpperCase();
}

/* La hora, contada desde quien mira.

   El servidor manda el instante en UTC y es el navegador quien lo
   traduce: es el único de los dos que sabe en qué huso está sentado
   quien atiende. Hoy da la hora; ayer, "ayer"; más atrás, la fecha. */
function cuandoFue(iso) {
  if (!iso) return '';
  const t = new Date(iso);
  if (isNaN(t)) return '';

  const hoy = new Date();
  const mismoDia = t.toDateString() === hoy.toDateString();
  if (mismoDia) {
    return t.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  }

  const ayer = new Date(hoy);
  ayer.setDate(ayer.getDate() - 1);
  if (t.toDateString() === ayer.toDateString()) return 'ayer';

  return t.toLocaleDateString([], {day: '2-digit', month: '2-digit'});
}

function pasaElFiltro(c) {
  if (FILTRO === 'urgente') return c.estado_atencion === 'urgente';
  if (FILTRO === 'esperando') return c.estado_atencion === 'esperando';
  if (FILTRO === 'mias') return !!c.atendido_por_humano;
  return true;
}

function pasaLaBusqueda(c) {
  if (!BUSQUEDA) return true;
  const donde = (c.name || '') + ' ' + c.phone + ' ' +
                (c.etiquetas || []).join(' ');
  return donde.toLowerCase().includes(BUSQUEDA);
}

function pintarListado(conversaciones) {
  if (conversaciones) CONVERSACIONES = conversaciones;

  const contenedor = document.querySelector('.lista-scroll');
  if (!contenedor) return;

  const visibles = CONVERSACIONES.filter(c => pasaElFiltro(c) && pasaLaBusqueda(c));

  // El contador cuenta TODAS, no las que dejó ver el filtro: es el
  // tamaño de la bandeja, no el del resultado de una búsqueda.
  const cuenta = document.querySelector('[data-cuenta]');
  if (cuenta) {
    cuenta.textContent = CONVERSACIONES.length === 1
      ? '1 activa' : CONVERSACIONES.length + ' activas';
  }

  if (!visibles.length) {
    const vacio = document.createElement('p');
    vacio.className = 'lista-vacia';
    vacio.textContent = CONVERSACIONES.length
      ? 'Ninguna conversación coincide.'
      : 'Todavía no hay conversaciones.';
    contenedor.replaceChildren(vacio);
    return;
  }

  contenedor.replaceChildren(...visibles.map(c => {
    const a = document.createElement('a');
    a.className = 'conversacion' + (c.phone === telefono ? ' activa' : '');
    a.href = '/admin/chat/' + encodeURIComponent(c.phone);

    const arriba = document.createElement('div');
    arriba.className = 'conv-arriba';

    const inicial = document.createElement('span');
    inicial.className = 'conv-inicial';
    inicial.setAttribute('aria-hidden', 'true');
    inicial.textContent = inicialesDe(c.name);

    const texto = document.createElement('div');
    texto.className = 'conv-texto';

    const linea = document.createElement('div');
    linea.className = 'conv-linea';
    const nombre = document.createElement('span');
    nombre.className = 'conv-nombre';
    nombre.textContent = c.name || c.phone;
    const hora = document.createElement('span');
    hora.className = 'conv-hora';
    hora.textContent = cuandoFue(c.cuando);
    linea.append(nombre, hora);

    const resumen = document.createElement('div');
    resumen.className = 'resumen' + (c.resumen ? '' : ' tenue');
    resumen.textContent = c.resumen || 'sin mensajes';

    texto.append(linea, resumen);
    arriba.append(inicial, texto);

    const chips = document.createElement('div');
    chips.className = 'conv-chips';
    const etiqueta = (txt, clase) => {
      const s = document.createElement('span');
      s.className = 'chip' + (clase ? ' ' + clase : '');
      s.textContent = txt;
      chips.appendChild(s);
    };
    // El estado va PRIMERO: es lo que se busca al barrer el listado.
    if (c.estado_atencion) {
      etiqueta(ETIQUETAS_ESTADO[c.estado_atencion] || c.estado_atencion,
               'estado ' + c.estado_atencion);
    }
    if (c.atendido_por_humano) etiqueta('atendido por ti', 'humano');
    if (c.servicio) etiqueta(c.servicio, 'servicio');
    (c.etiquetas || []).forEach(t => etiqueta(t, 'etiqueta'));
    if (c.es_dueno) etiqueta('tu número');
    if (c.origen && c.origen !== PANEL.origenPorDefecto) etiqueta(c.origen);
    if (!c.ventana_abierta) etiqueta('ventana cerrada', 'cerrada');

    a.append(arriba, chips);
    return a;
  }));
}

async function refrescarListado() {
  if (!document.querySelector('.lista-scroll') || document.hidden) return;

  try {
    const r = await fetch('/admin/api/conversaciones');
    if (r.status === 401) { location.href = '/admin/login'; return; }
    if (!r.ok) return;
    pintarListado((await r.json()).conversaciones);
  } catch (e) { /* se reintenta */ }
}

// ── El buscador y los filtros ────────────────────────────────────────
const _buscador = document.getElementById('buscar-conversacion');
if (_buscador) {
  _buscador.addEventListener('input', function () {
    BUSQUEDA = _buscador.value.trim().toLowerCase();
    pintarListado();
  });
}

document.querySelectorAll('.filtro').forEach(function (boton) {
  boton.addEventListener('click', function () {
    FILTRO = boton.dataset.filtro;
    document.querySelectorAll('.filtro').forEach(function (otro) {
      otro.classList.toggle('activo', otro === boton);
    });
    pintarListado();
  });
});

// Primera pintada, sin pedirle nada al servidor.
const _inicial = document.getElementById('listado-inicial');
if (_inicial) pintarListado(JSON.parse(_inicial.textContent));
