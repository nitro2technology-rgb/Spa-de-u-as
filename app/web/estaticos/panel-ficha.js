/* LA FICHA DEL CONTACTO: ETIQUETAS Y NOTA
   ─────────────────────────────────────────────────────────────────
   Las dos son SOLO del panel: el bot no las lee y el cliente no las ve
   nunca. La nota lo dice en su propio placeholder, porque quien escribe
   ahí tiene que estar seguro de que no se le va a escapar.

   El servidor recorta, quita repetidas y aplica el tope, así que después
   de guardar se repinta con lo que RESPONDIÓ y no con lo que se mandó.
   Si no, se vería en pantalla una etiqueta de 60 caracteres que en la
   base quedó cortada a 24. */

const _cajaEtiquetas = document.querySelector('[data-etiquetas]');
const _nota = document.querySelector('[data-nota]');
const _guardado = document.querySelector('[data-guardado]');

function etiquetasActuales() {
  if (!_cajaEtiquetas) return [];
  return [..._cajaEtiquetas.querySelectorAll('[data-etiqueta]')]
    .map(e => e.dataset.etiqueta);
}

function pintarEtiquetas(etiquetas) {
  if (!_cajaEtiquetas) return;

  // El chip del servicio y los controles se quedan: lo que se rehace son
  // las etiquetas libres, que son las únicas que cambian.
  _cajaEtiquetas.querySelectorAll('[data-etiqueta]').forEach(e => e.remove());

  const anadir = _cajaEtiquetas.querySelector('[data-anadir-etiqueta]');
  etiquetas.forEach(function (texto) {
    const chip = document.createElement('span');
    chip.className = 'chip etiqueta';
    chip.dataset.etiqueta = texto;
    chip.textContent = texto;

    const quitar = document.createElement('button');
    quitar.type = 'button';
    quitar.className = 'quitar-etiqueta';
    quitar.setAttribute('aria-label', 'Quitar la etiqueta ' + texto);
    quitar.textContent = '×';
    chip.appendChild(quitar);

    _cajaEtiquetas.insertBefore(chip, anadir);
  });
}

async function guardarEtiquetas(etiquetas) {
  const r = await fetch('/admin/api/chat/' + encodeURIComponent(telefono) +
                        '/etiquetas', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({etiquetas: etiquetas})
  });
  if (r.status === 401) { location.href = '/admin/login'; return null; }
  if (!r.ok) return null;
  return (await r.json()).etiquetas || [];
}

if (_cajaEtiquetas) {
  const campo = _cajaEtiquetas.querySelector('[data-nueva-etiqueta]');
  const boton = _cajaEtiquetas.querySelector('[data-anadir-etiqueta]');

  boton.addEventListener('click', function () {
    boton.hidden = true;
    campo.hidden = false;
    campo.value = '';
    campo.focus();
  });

  function cerrarCampo() {
    campo.hidden = true;
    boton.hidden = false;
  }

  async function confirmar() {
    const texto = campo.value.trim();
    cerrarCampo();
    if (!texto) return;

    const quedaron = await guardarEtiquetas(etiquetasActuales().concat([texto]));
    if (quedaron) pintarEtiquetas(quedaron);
  }

  campo.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); confirmar(); }
    // Escape cancela sin guardar: escribir media etiqueta y arrepentirse
    // tiene que ser posible sin recargar la página.
    //
    // Se vacía ANTES de esconderlo, y no es por limpieza: esconder un
    // campo que tiene el foco dispara `blur`, y de `blur` cuelga
    // `confirmar()`. Sin vaciarlo, arrepentirse GUARDABA la etiqueta.
    else if (e.key === 'Escape') {
      e.preventDefault();
      campo.value = '';
      cerrarCampo();
    }
  });
  campo.addEventListener('blur', confirmar);

  _cajaEtiquetas.addEventListener('click', async function (e) {
    const quitar = e.target.closest('.quitar-etiqueta');
    if (!quitar) return;

    const chip = quitar.closest('[data-etiqueta]');
    const quedan = etiquetasActuales().filter(t => t !== chip.dataset.etiqueta);
    const respuesta = await guardarEtiquetas(quedan);
    if (respuesta) pintarEtiquetas(respuesta);
  });
}

/* La nota se guarda sola.

   Al salir del campo y, si se sigue escribiendo, cada dos segundos de
   pausa. NO hay botón de guardar a propósito: una nota que se pierde por
   no haber pulsado un botón es peor que no tener notas, y aquí se
   escribe justo cuando hay prisa. */
if (_nota) {
  let reloj = null;
  let ultimaGuardada = _nota.value;

  async function guardarNota() {
    if (_nota.value === ultimaGuardada) return;
    const texto = _nota.value;

    try {
      const r = await fetch('/admin/api/chat/' + encodeURIComponent(telefono) +
                            '/nota', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({nota: texto})
      });
      if (r.status === 401) { location.href = '/admin/login'; return; }
      if (!r.ok) return;

      ultimaGuardada = texto;
      if (_guardado) {
        _guardado.hidden = false;
        setTimeout(function () { _guardado.hidden = true; }, 1800);
      }
    } catch (e) { /* sin red: se reintenta al siguiente cambio */ }
  }

  _nota.addEventListener('input', function () {
    clearTimeout(reloj);
    reloj = setTimeout(guardarNota, 2000);
  });
  _nota.addEventListener('blur', function () {
    clearTimeout(reloj);
    guardarNota();
  });
}

/* ABRIR LA FICHA EN UNA PANTALLA ESTRECHA
   ─────────────────────────────────────────────────────────────────
   Por debajo de 1200px la ficha deja de ser la cuarta columna y pasa a
   abrirse encima del hilo (ver la hoja). No se duplica nada: es el mismo
   elemento, así que todo lo de arriba —las etiquetas, la nota que se
   guarda sola— sigue funcionando sin enterarse.

   La clase `ficha-cerrandose` existe solo para que la salida se vea:
   quitando `ficha-abierta` a secas, la ficha vuelve a `display:none` de
   golpe y no hay transición desde la que animar. */

const _verFicha = document.getElementById('ver-ficha');
const _ficha = document.getElementById('ficha-contacto');
const _veloFicha = document.querySelector('[data-velo-ficha]');
const _cerrarFicha = document.querySelector('[data-cerrar-ficha]');

if (_verFicha && _ficha) {
  let _relojFicha = null;

  function abrirFicha() {
    clearTimeout(_relojFicha);
    document.body.classList.remove('ficha-cerrandose');
    document.body.classList.add('ficha-abierta');
    _verFicha.setAttribute('aria-expanded', 'true');
    // El foco entra con ella: quien navega con teclado no tiene que
    // recorrer el hilo entero para llegar a las etiquetas.
    if (_cerrarFicha) _cerrarFicha.focus();
  }

  function cerrarFicha(devolverFoco) {
    if (!document.body.classList.contains('ficha-abierta')) return;
    document.body.classList.remove('ficha-abierta');
    document.body.classList.add('ficha-cerrandose');
    _verFicha.setAttribute('aria-expanded', 'false');
    clearTimeout(_relojFicha);
    _relojFicha = setTimeout(function () {
      document.body.classList.remove('ficha-cerrandose');
    }, 220);
    // Solo si se cerró a propósito. Si se fue por un cambio de ancho,
    // robar el foco sería una sorpresa.
    if (devolverFoco) _verFicha.focus();
  }

  _verFicha.addEventListener('click', function () {
    if (document.body.classList.contains('ficha-abierta')) cerrarFicha(true);
    else abrirFicha();
  });

  if (_cerrarFicha) {
    _cerrarFicha.addEventListener('click', function () { cerrarFicha(true); });
  }
  if (_veloFicha) {
    _veloFicha.addEventListener('click', function () { cerrarFicha(true); });
  }

  // En fase de CAPTURA, y ahí está el detalle: el campo de etiqueta
  // nueva también escucha Escape para cancelarse. Burbujeando, su
  // handler corre primero y ya ha escondido el campo cuando esto
  // pregunta, así que un solo Escape cerraba las dos cosas —el campo y
  // la ficha entera—. Capturando, esto ve el estado de ANTES.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    // Un Escape, una cosa: si se está escribiendo una etiqueta, ese
    // Escape es suyo y la ficha se queda donde está.
    const campo = _ficha.querySelector('[data-nueva-etiqueta]');
    if (campo && !campo.hidden) return;
    cerrarFicha(true);
  }, true);

  // Al ensanchar —una tablet que gira— la ficha vuelve a ser columna y
  // el panel ya no pinta nada. Sin esto, el velo se quedaba puesto
  // encima de un panel que ya no estaba abierto: la pantalla quedaba
  // gris y sin responder, y no había forma de saber por qué.
  window.matchMedia('(min-width: 1201px)').addEventListener('change', function (e) {
    if (e.matches) {
      document.body.classList.remove('ficha-abierta', 'ficha-cerrandose');
      _verFicha.setAttribute('aria-expanded', 'false');
    }
  });
}

/* EL ÁREA QUE ATIENDE ESTA CONVERSACIÓN (solo el dueño la ve y la cambia)
   ─────────────────────────────────────────────────────────────────
   Se guarda al elegir, sin botón: es un solo dato y el cambio se nota
   enseguida en el panel del área. Si falla, se vuelve a la que estaba —
   un desplegable que dice "Ventas" cuando la conversación sigue siendo
   del dueño es peor que un error. */
const _elegirArea = document.querySelector('[data-asignar-area]');
if (_elegirArea) {
  let _areaAntes = _elegirArea.value;
  _elegirArea.addEventListener('change', async function () {
    const r = await fetch('/admin/api/chat/' + encodeURIComponent(telefono) +
                          '/area', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({area: _elegirArea.value})
    });
    if (r.status === 401) { location.href = '/admin/login'; return; }
    if (!r.ok) { _elegirArea.value = _areaAntes; return; }
    _areaAntes = _elegirArea.value;
    if (_guardado) {
      _guardado.hidden = false;
      setTimeout(function () { _guardado.hidden = true; }, 1800);
    }
  });
}
