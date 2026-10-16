/* El hilo de la conversación
   ─────────────────────────────────────────────────────────────────
   Vivía dentro de una f-string de Python. Ahí, cada llave había que
   escribirla doblada para que Python no la tomara por un hueco, y un
   descuido no daba un error de JavaScript: daba un error de Python al
   arrancar el servidor.

   Los guiones del panel comparten ámbito y se ejecutan EN ORDEN (van con
   `defer`, que lo respeta). Lo que declara `panel-base.js` lo ven los
   demás. Los valores que dependen del negocio llegan en `PANEL`, que la
   página define antes que estos archivos. */

const area = document.querySelector('textarea[name="texto"]');
const form = area ? area.closest('form') : null;
const contador = document.getElementById('contador');
const CLAVE_BORRADOR = 'borrador:' + location.pathname;

function ajustarAltura() {
  area.style.height = 'auto';
  area.style.height = Math.min(area.scrollHeight, 320) + 'px';
}

function actualizarContador() {
  if (!contador) return;
  const quedan = PANEL.limiteWhatsapp - area.value.length;
  // Solo molestamos cuando de verdad se acerca al límite.
  contador.textContent = quedan < 500 ? quedan + ' caracteres restantes' : '';
}

const filaEnvio = document.getElementById('fila-envio');

// Marca de que el guion está vivo. Sin ella el CSS deja los dos botones a
// la vista, que es lo correcto si el JavaScript no cargó: el micrófono no
// serviría, pero el formulario de respaldo se puede enviar igual.
if (filaEnvio) filaEnvio.classList.add('js');

// A la derecha solo hay sitio para un botón: el micrófono si la caja está
// vacía, el avión de enviar en cuanto hay algo escrito. Se llama al
// teclear, al recuperar un borrador y después de enviar.
function actualizarBotonDerecha() {
  if (!filaEnvio || !area) return;
  filaEnvio.classList.toggle('escribiendo', area.value.trim().length > 0);
}

if (area) {
  // Recuperamos lo que se estuviera escribiendo si la página se recargó.
  const borrador = sessionStorage.getItem(CLAVE_BORRADOR);
  if (borrador) { area.value = borrador; }
  ajustarAltura(); actualizarContador(); actualizarBotonDerecha();

  area.addEventListener('input', () => {
    ajustarAltura();
    actualizarContador();
    actualizarBotonDerecha();
    sessionStorage.setItem(CLAVE_BORRADOR, area.value);
  });

  // Enter envía; Shift+Enter hace salto de línea. isComposing evita
  // enviar a medias cuando se escribe con teclado predictivo o acentos.
  area.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (area.value.trim()) form.requestSubmit();
    }
  });

  // El envío NO recarga la página: la cajita se vacía en cuanto das
  // Enter y el mensaje sale de fondo. Antes esto era un POST de
  // formulario y el texto se quedaba a la vista hasta que Meta
  // contestaba — un segundo largo en el que parecía que no se había
  // enviado, y se acababa mandando dos veces.
  form.addEventListener('submit', (e) => {
    e.preventDefault();

    const texto = area.value.trim();
    if (!texto) return;

    // Vaciar YA. Todo lo demás ocurre después y de fondo.
    area.value = '';
    sessionStorage.removeItem(CLAVE_BORRADOR);
    ajustarAltura();
    actualizarContador();
    actualizarBotonDerecha();
    area.focus();

    enviar(texto);
  });
}

// La burbuja la pinta el canal en vivo cuando el servidor guarda el
// mensaje, así que aquí no se pinta nada: hacerlo dejaría el mensaje
// duplicado en cuanto llegue el aviso.
async function enviar(texto) {
  try {
    const r = await fetch('/admin/api/chat/' + encodeURIComponent(telefono) + '/enviar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({texto: texto})
    });

    if (r.status === 401) { location.href = '/admin/login'; return; }

    const datos = await r.json().catch(() => null);
    if (!r.ok || !datos || !datos.ok) {
      devolverTexto(texto, (datos && datos.error) || 'No se pudo enviar.');
    }
  } catch (err) {
    devolverTexto(texto, 'Sin conexión: el mensaje no llegó a salir.');
  }
}

// Si el envío falla, el texto vuelve a la cajita para no perderlo. Solo
// si no empezaste a escribir otra cosa mientras tanto: en ese caso se
// queda en el aviso, de donde se puede copiar.
function devolverTexto(texto, motivo) {
  if (area && !area.value.trim()) {
    area.value = texto;
    sessionStorage.setItem(CLAVE_BORRADOR, texto);
    ajustarAltura();
    actualizarContador();
    actualizarBotonDerecha();
    avisar(motivo);
  } else {
    avisar(motivo + ' El mensaje era: "' + texto + '"');
  }
}

// ── Adjuntar una imagen ─────────────────────────────────────────────
// El input no lleva `capture`, así que el celular ofrece las tres cosas
// —galería, explorador y hacer una foto— y decide quien la manda.
//
// Nada sale hasta confirmarlo: la foto se enseña primero en una ventana
// sobre el chat. Mandar por error la imagen equivocada a un cliente no
// se puede deshacer.

const campoArchivo = document.getElementById('archivo');
const btnAdjuntar = document.getElementById('btn-adjuntar');
// Se declara aquí arriba, junto al otro, porque `subirAdjunto` bloquea
// los dos botones y con `const` no vale usarlo antes de declararlo.
const btnGrabar = document.getElementById('btn-grabar');

// Las piezas de la vista de grabación. Viven en el HTML y aquí solo se
// muestran, se ocultan y se refrescan.
const cronometro = document.getElementById('cronometro');
const pistaCancelar = document.getElementById('pista-cancelar');
const btnDescartar = document.getElementById('descartar-audio');

if (btnDescartar) {
  btnDescartar.addEventListener('click', cancelarGrabacion);
}

if (btnAdjuntar && campoArchivo) {
  btnAdjuntar.addEventListener('click', () => campoArchivo.click());

  campoArchivo.addEventListener('change', () => {
    const archivo = campoArchivo.files[0];
    // El input se vacía YA, para poder volver a elegir la misma foto si
    // se cancela la vista previa o el envío falla.
    campoArchivo.value = '';
    if (archivo) previsualizar(archivo);
  });
}

// La ventana con la foto antes de mandarla. Se arma entera aquí y se
// destruye al cerrarla: no vive en el HTML de la página porque la
// mayoría de las veces no hace falta.
function previsualizar(archivo) {
  const url = URL.createObjectURL(archivo);

  const fondo = document.createElement('div');
  fondo.className = 'previa-fondo';

  const caja = document.createElement('div');
  caja.className = 'previa';

  const img = document.createElement('img');
  img.alt = 'Imagen que vas a enviar';

  const pie = document.createElement('input');
  pie.type = 'text';
  pie.className = 'previa-pie';
  pie.placeholder = 'Añade un comentario (opcional)';
  pie.maxLength = 1024;
  // Lo que ya estuviera escrito en la cajita pasa a ser el pie de foto:
  // es lo que uno espera después de escribir y luego adjuntar.
  if (area && area.value.trim()) pie.value = area.value.trim();

  const acciones = document.createElement('div');
  acciones.className = 'previa-acciones';

  const cancelar = document.createElement('button');
  cancelar.type = 'button';
  cancelar.className = 'secundario';
  cancelar.textContent = 'Cancelar';

  const enviar = document.createElement('button');
  enviar.type = 'button';
  enviar.textContent = 'Enviar';
  enviar.disabled = true;   // hasta que la foto se vea, no hay nada que confirmar

  const cargando = document.createElement('div');
  cargando.className = 'previa-cargando';
  cargando.textContent = 'Cargando la imagen…';

  acciones.append(cancelar, enviar);
  caja.append(cargando, img, pie, acciones);
  fondo.appendChild(caja);
  document.body.appendChild(fondo);

  function cerrar() {
    URL.revokeObjectURL(url);
    fondo.remove();
    document.removeEventListener('keydown', alTeclado);
  }

  function alTeclado(e) {
    if (e.key === 'Escape') cerrar();
    if (e.key === 'Enter' && !enviar.disabled) enviar.click();
  }

  img.addEventListener('load', () => {
    cargando.remove();
    enviar.disabled = false;
    enviar.focus();
  });

  img.addEventListener('error', () => {
    cargando.textContent = 'No se pudo abrir esa imagen.';
    img.remove();
  });

  cancelar.addEventListener('click', cerrar);

  // Tocar fuera de la ventana también cancela, como cualquier modal.
  fondo.addEventListener('click', (e) => { if (e.target === fondo) cerrar(); });
  document.addEventListener('keydown', alTeclado);

  enviar.addEventListener('click', async () => {
    const comentario = pie.value.trim();
    cerrar();
    // La cajita se limpia solo si su texto se fue como pie de foto.
    if (area && comentario && comentario === area.value.trim()) {
      area.value = '';
      sessionStorage.removeItem(CLAVE_BORRADOR);
      ajustarAltura(); actualizarContador(); actualizarBotonDerecha();
    }
    await subirAdjunto(archivo, 'imagen', comentario);
  });

  img.src = url;
}

// Sube el archivo y deja que la burbuja la pinte el canal en vivo, igual
// que con el texto. `enviando` bloquea los dos botones mientras tanto:
// una imagen tarda lo suyo y es fácil darle dos veces.
let enviando = false;

async function subirAdjunto(archivo, clase, pie) {
  if (enviando) return;
  enviando = true;
  if (btnAdjuntar) btnAdjuntar.disabled = true;
  if (btnGrabar) btnGrabar.disabled = true;
  avisar(clase === 'audio' ? 'Enviando la nota de voz…' : 'Enviando la imagen…');

  try {
    const cuerpo = new FormData();
    cuerpo.append('archivo', archivo);
    cuerpo.append('clase', clase);
    if (pie) cuerpo.append('texto', pie);

    const r = await fetch('/admin/api/chat/' + encodeURIComponent(telefono) + '/adjunto',
                          {method: 'POST', body: cuerpo});

    if (r.status === 401) { location.href = '/admin/login'; return; }

    const datos = await r.json().catch(() => null);
    if (!r.ok || !datos || !datos.ok) {
      avisar((datos && datos.error) || 'No se pudo enviar el archivo.');
    } else if (datos.aviso) {
      // Se envió, pero no como se esperaba. El caso típico: salió como
      // archivo de audio y no como nota de voz. Callarlo dejaría al
      // dueño creyendo que el cliente recibió otra cosa.
      avisar(datos.aviso);
    } else {
      quitarAviso();
    }
  } catch (err) {
    avisar('Sin conexión: el archivo no llegó a salir.');
  } finally {
    enviando = false;
    if (btnAdjuntar) btnAdjuntar.disabled = false;
    if (btnGrabar) btnGrabar.disabled = false;
  }
}

// ── Grabar una nota de voz ──────────────────────────────────────────
// Como en WhatsApp: se mantiene pulsado el micrófono para grabar y al
// soltar se envía. Deslizando hacia arriba SIN soltar, el botón se queda
// pulsado solo y se puede levantar el dedo; entonces se envía con un
// toque, o se descarta con la X.
//
// Se usan eventos de puntero y no de ratón/tacto por separado: son los
// mismos para dedo, ratón y lápiz, y con setPointerCapture el "soltar"
// llega aunque el dedo se haya ido fuera del botón. Sin eso, arrastrar
// un poco y soltar dejaba el micrófono grabando para siempre.
//
// channelCount 1 porque Meta exige mono; pedirlo al micrófono evita
// mezclar dos canales después.

const PIXELES_PARA_BLOQUEAR = 60;   // cuánto hay que subir el dedo
const PIXELES_PARA_CANCELAR = 90;   // cuánto hay que arrastrarlo a la izquierda
const MINIMO_GRABANDO_MS = 500;     // por debajo de esto fue un toque suelto
// Una grabación fijada que se olvide encendida acabaría chocando con el
// tope de 16 MB de Meta y fallando al enviarse. Cinco minutos es mucho
// más de lo que dura una nota de voz y evita esa sorpresa.
const MAXIMO_GRABANDO_MS = 5 * 60 * 1000;

let grabadora = null;
let trozos = [];
let pistaAudio = null;
let bloqueado = false;
let descartar = false;
let inicioGrabacion = 0;
let yInicial = 0;
let xInicial = 0;
let reloj = null;
// ¿Sigue el dedo encima? Hace falta aparte de `grabadora` por la primera
// vez: pedir el micrófono abre un diálogo de permiso, para entonces ya
// soltaste el botón, y sin esto la grabación arrancaba con nadie
// pulsando y el micrófono se quedaba abierto.
let pulsando = false;

if (btnGrabar) {
  // Sin getUserMedia no hay nada que hacer: pasa en HTTP sin cifrar y en
  // navegadores viejos. Se esconde el botón en vez de dejarlo fallando.
  if (!navigator.mediaDevices || !window.MediaRecorder || !window.PointerEvent) {
    btnGrabar.hidden = true;
  } else {
    btnGrabar.addEventListener('pointerdown', async (e) => {
      // Ya bloqueado, este toque significa "envíalo".
      if (bloqueado) { pararGrabacion(); return; }
      if (grabadora || enviando) return;

      e.preventDefault();
      yInicial = e.clientY;
      xInicial = e.clientX;
      pulsando = true;
      try { btnGrabar.setPointerCapture(e.pointerId); } catch (err) {}
      await empezarGrabacion();
    });

    // Dos gestos sobre el mismo botón: arrastrar a la IZQUIERDA cancela,
    // subir el dedo deja el botón "autopulsado". Se mira cuál de los dos
    // movimientos manda para que un arrastre en diagonal no dispare los
    // dos a la vez.
    btnGrabar.addEventListener('pointermove', (e) => {
      if (!grabadora || bloqueado) return;

      const izquierda = xInicial - e.clientX;
      const arriba = yInicial - e.clientY;

      if (izquierda > arriba) {
        if (izquierda >= PIXELES_PARA_CANCELAR) { cancelarGrabacion(); return; }
        // El texto se va apagando conforme arrastras: así se ve que el
        // gesto está haciendo algo antes de llegar al final.
        if (pistaCancelar) {
          pistaCancelar.style.opacity =
            String(Math.max(0.25, 1 - izquierda / PIXELES_PARA_CANCELAR));
        }
      } else if (arriba > PIXELES_PARA_BLOQUEAR) {
        fijarGrabacion();
      }
    });

    // Soltar envía… salvo que esté fijado, que entonces sigue grabando.
    const alSoltar = () => {
      pulsando = false;
      if (grabadora && !bloqueado) pararGrabacion();
    };
    btnGrabar.addEventListener('pointerup', alSoltar);
    btnGrabar.addEventListener('pointercancel', alSoltar);

    // El menú contextual del pulsado largo en el celular tapaba el
    // micrófono justo cuando se está usando.
    btnGrabar.addEventListener('contextmenu', (e) => e.preventDefault());
  }
}

async function empezarGrabacion() {
  try {
    pistaAudio = await navigator.mediaDevices.getUserMedia(
      {audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}});
  } catch (err) {
    avisar('No se pudo usar el micrófono. Revisa el permiso del navegador.');
    return;
  }

  // La primera vez, pedir el micrófono abre el diálogo de permiso y para
  // cuando lo aceptas ya soltaste el botón. Si nadie sigue pulsando, no
  // se empieza nada: si no, quedaría grabando sin que nadie lo sepa y
  // solo pararía al recargar. Se avisa de que hay que volver a pulsar.
  if (!pulsando) {
    pistaAudio.getTracks().forEach(t => t.stop());
    pistaAudio = null;
    avisar('Micrófono listo. Mantén pulsado para grabar.');
    return;
  }

  trozos = [];
  descartar = false;
  bloqueado = false;
  inicioGrabacion = Date.now();

  grabadora = new MediaRecorder(pistaAudio);
  grabadora.addEventListener('dataavailable', (ev) => {
    if (ev.data && ev.data.size) trozos.push(ev.data);
  });
  grabadora.addEventListener('stop', alTerminarGrabacion);
  grabadora.start();

  btnGrabar.classList.add('grabando');
  if (filaEnvio) filaEnvio.classList.add('grabando');
  if (pistaCancelar) pistaCancelar.style.opacity = '1';
  pintarGrabacion();

  // El contador corre cuatro veces por segundo y no una: así el primer
  // "0:01" no tarda hasta un segundo entero en aparecer.
  reloj = setInterval(pintarGrabacion, 250);
}

function fijarGrabacion() {
  bloqueado = true;
  btnGrabar.classList.add('fijado');
  btnGrabar.title = 'Toca para enviar';
  pintarGrabacion();
}

function pararGrabacion() {
  if (grabadora && grabadora.state === 'recording') grabadora.stop();
}

function cancelarGrabacion() {
  descartar = true;
  pararGrabacion();
}

async function alTerminarGrabacion() {
  const duracion = Date.now() - inicioGrabacion;
  const tipo = (grabadora && grabadora.mimeType) || 'audio/webm';

  // Soltar el micrófono en cuanto se para: si no, el navegador deja el
  // punto rojo encendido y parece que sigue escuchando.
  if (pistaAudio) pistaAudio.getTracks().forEach(t => t.stop());
  pistaAudio = null;
  grabadora = null;
  bloqueado = false;
  clearInterval(reloj);
  reloj = null;
  btnGrabar.classList.remove('grabando', 'fijado');
  btnGrabar.title = 'Mantén pulsado para grabar';
  if (filaEnvio) filaEnvio.classList.remove('grabando');
  if (btnDescartar) btnDescartar.hidden = true;
  if (pistaCancelar) pistaCancelar.style.opacity = '1';

  const audio = new Blob(trozos, {type: tipo});
  trozos = [];

  if (descartar) { descartar = false; quitarAviso(); return; }

  // Un toque suelto sobre el micrófono no es una nota de voz de medio
  // segundo: es alguien que tocó donde no quería.
  if (duracion < MINIMO_GRABANDO_MS || audio.size < 1200) {
    avisar('Mantén pulsado el micrófono para grabar.');
    return;
  }

  await subirAdjunto(audio, 'audio', '');
}

// Refresca el contador y el texto de ayuda mientras se graba.
//
// Los elementos ya están en el HTML y solo se muestran u ocultan: antes
// esto creaba una banda nueva cada vez, y montar y tirar nodos cuatro
// veces por segundo no tiene sentido.
function pintarGrabacion() {
  const transcurrido = Date.now() - inicioGrabacion;

  if (cronometro) cronometro.textContent = comoReloj(transcurrido);

  if (pistaCancelar) {
    pistaCancelar.textContent = bloqueado
      ? 'Toca el micrófono para enviar'
      : '\\u2039 Desliza para cancelar';
  }
  // El botón de descartar solo tiene sentido con la grabación fijada:
  // mientras mantienes el dedo, para cancelar se arrastra.
  if (btnDescartar) btnDescartar.hidden = !bloqueado;

  // Corte de seguridad de una grabación olvidada. Se envía lo grabado
  // hasta aquí en vez de tirarlo: es lo que menos sorprende.
  if (transcurrido >= MAXIMO_GRABANDO_MS) {
    avisar('La grabación llegó a 5 minutos y se envía tal cual.');
    pararGrabacion();
  }
}

// Milisegundos a "m:ss".
function comoReloj(ms) {
  const total = Math.floor(ms / 1000);
  return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
}

function quitarAviso() {
  const banda = document.getElementById('aviso-envio');
  if (banda) banda.remove();
}

function avisar(motivo) {
  let banda = document.getElementById('aviso-envio');
  if (!banda) {
    banda = document.createElement('div');
    banda.id = 'aviso-envio';
    banda.className = 'banda alerta';
    // Pasada la ventana de 24 h no hay formulario donde colgarlo, así
    // que en ese caso el aviso va al final del hilo.
    const destino = document.querySelector('form.responder');
    if (destino) destino.parentNode.insertBefore(banda, destino);
    else if (caja) caja.appendChild(banda);
    else return;
  }
  banda.textContent = motivo;
}

// ── Estado de atención ──────────────────────────────────────────────
// Se marca aquí y se ve en el listado, que es donde sirve: saber a quién
// hay que atender ya sin abrir conversación por conversación.

const cajaEstados = document.querySelector('details.estados');

if (cajaEstados) {
  cajaEstados.querySelectorAll('button[data-estado]').forEach(boton => {
    boton.addEventListener('click', async () => {
      const estado = boton.dataset.estado;
      const resumen = cajaEstados.querySelector('summary');

      // Se pinta antes de que conteste el servidor: marcar un chat es
      // algo que se hace de pasada y esperar medio segundo se nota.
      const antes = resumen.className;
      const antesTexto = resumen.textContent;
      resumen.className = 'chip estado ' + (estado || 'sin-estado');
      resumen.textContent = ETIQUETAS_ESTADO[estado] || 'Marcar estado';
      cajaEstados.open = false;

      try {
        const r = await fetch('/admin/api/chat/' + encodeURIComponent(telefono) + '/estado', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({estado: estado})
        });
        if (r.status === 401) { location.href = '/admin/login'; return; }
        if (!r.ok) throw new Error('no se guardó');

        refrescarListado();
      } catch (e) {
        // No se pudo: se deja como estaba en vez de mentir.
        resumen.className = antes;
        resumen.textContent = antesTexto;
        avisar('No se pudo cambiar el estado.');
      }
    });
  });
}

// ── Eliminar el chat ────────────────────────────────────────────────
// Dos toques a propósito: borra de la base y no se puede deshacer.

// Devuelve la conversación a su principio. Es lo que hace falta para
// PROBAR un cambio: el saludo y el menú solo se ven al empezar de cero, y
// quien prueba su propio bot ya tiene una conversación a medias. No borra
// nada: ni el historial, ni el nombre, ni sus leads.
const botonReiniciar = document.getElementById('reiniciar-chat');
if (botonReiniciar) {
  botonReiniciar.addEventListener('click', async () => {
    botonReiniciar.disabled = true;
    try {
      const r = await fetch('/admin/api/chat/' + encodeURIComponent(telefono) + '/reiniciar',
                            {method: 'POST'});
      if (r.status === 401) { location.href = '/admin/login'; return; }
      const datos = await r.json().catch(() => null);
      avisar(datos && datos.ok
        ? 'Listo: su próximo mensaje empieza desde el saludo.'
        : ((datos && datos.error) || 'No se pudo reiniciar.'));
    } catch (e) {
      avisar('No se pudo reiniciar: ' + e);
    }
    botonReiniciar.disabled = false;
  });
}

const botonBorrar = document.getElementById('borrar-chat');
if (botonBorrar) {
  let armado = false;

  const desarmar = () => {
    armado = false;
    botonBorrar.textContent = 'Eliminar chat';
    botonBorrar.classList.remove('armado');
  };

  botonBorrar.addEventListener('click', async () => {
    if (!armado) {
      armado = true;
      botonBorrar.textContent = 'Confirmar: borra todo y no se recupera';
      botonBorrar.classList.add('armado');
      setTimeout(() => { if (armado) desarmar(); }, 6000);
      return;
    }

    botonBorrar.disabled = true;
    try {
      const r = await fetch('/admin/api/chat/' + encodeURIComponent(telefono) + '/borrar',
                            {method: 'POST'});
      if (r.status === 401) { location.href = '/admin/login'; return; }

      const datos = await r.json().catch(() => null);
      if (!r.ok || !datos || !datos.ok) {
        avisar((datos && datos.error) || 'No se pudo borrar.');
        botonBorrar.disabled = false;
        desarmar();
        return;
      }

      let aviso = 'Chat borrado: ' + datos.mensajes + ' mensajes.';
      // Las citas del calendario NO se tocan. Callarlo dejaría una cita
      // reservada sin dueño visible en el panel.
      if (datos.citas_en_calendar && datos.citas_en_calendar.length) {
        aviso += ' Tenía ' + datos.citas_en_calendar.length +
                 ' cita(s) en Google Calendar y siguen ahí: bórralas a mano si hace falta.';
      }
      location.href = '/admin/inbox?aviso=' + encodeURIComponent(aviso);
    } catch (e) {
      avisar('Sin conexión: no se borró nada.');
      botonBorrar.disabled = false;
      desarmar();
    }
  });
}

// El mensaje más reciente queda abajo: al abrir el chat se baja solo.
// El scroll es el de la caja del hilo, no el de la página.

function irAlFinal() {
  if (caja) caja.scrollTop = caja.scrollHeight;
}

// Las fechas sueltas de la ficha del contacto, con el mismo criterio que
// las horas del hilo: el servidor manda el instante, aquí se escribe.
document.querySelectorAll('[data-fecha]').forEach(function (t) {
  const d = new Date(t.dateTime);
  if (!isNaN(d)) {
    t.textContent = d.toLocaleDateString([], {day: '2-digit', month: 'short',
                                              year: 'numeric'});
  }
});

// Las burbujas que vinieron pintadas del servidor traen el instante en
// UTC y la hora en blanco: aquí se rellenan y se parte el hilo por días.
// Va antes de bajar al final porque los separadores cambian el alto.
ponerSeparadores();

// Se llama varias veces a propósito. El fondo se mueve mientras terminan
// de cargar las fuentes y mientras el campo de texto se ajusta a su
// contenido: con una sola llamada quedaba a medio bajar.
irAlFinal();
requestAnimationFrame(irAlFinal);
window.addEventListener('load', irAlFinal);

// ¿Seguimos "pegados" al fondo? Se guarda según lo que hagas al hacer
// scroll, en vez de medirlo justo cuando llega un mensaje: al medirlo en
// ese instante, la altura aún no contaba la burbuja recién añadida y la
// vista se quedaba unos píxeles corta.
const MARGEN_FONDO = 80;   // a menos de esto del final, cuenta como "abajo"

// Se declara aquí, antes de engancharse los eventos: el manejador de
// scroll lo usa, y con `const` no vale leerlo antes de declararlo.
const btnBajar = document.getElementById('bajar-al-final');

function distanciaAlFondo() {
  if (!caja) return 0;
  return caja.scrollHeight - caja.scrollTop - caja.clientHeight;
}

// ¿Seguimos "pegados" al fondo?
//
// La regla es la clave de todo esto: **solo el usuario suelta el ancla.**
// Antes se recalculaba en cada evento `scroll`, y ahí estaba el fallo:
// mientras las imágenes cargan, el contenido crece, la distancia al
// final se dispara y cualquier scroll disparado por el propio navegador
// durante ese acomodo dejaba `pegadoAlFondo` en false. A partir de ese
// momento ya nada volvía a bajar el hilo, y el chat se quedaba abierto
// por la mitad.
//
// Ahora un `scroll` solo puede VOLVER a anclar (si acabaste abajo), pero
// nunca desanclar. Desanclar es cosa de un gesto explícito: rueda del
// ratón, arrastrar con el dedo o teclas de navegación.
let pegadoAlFondo = true;

// ¿Hay un dedo o un botón del ratón apretado sobre el hilo? Es lo que
// distingue arrastrar la barra de scroll —que sí debe soltar el ancla—
// de que el navegador mueva el scroll él solo mientras carga.
let gestoEnCurso = false;

if (caja) {
  caja.addEventListener('pointerdown', () => { gestoEnCurso = true; });
  // En window y no en la caja: el ratón se suelta muchas veces fuera,
  // sobre todo arrastrando la barra de scroll.
  window.addEventListener('pointerup', () => { gestoEnCurso = false; });
  window.addEventListener('pointercancel', () => { gestoEnCurso = false; });

  caja.addEventListener('scroll', () => {
    if (distanciaAlFondo() < MARGEN_FONDO) pegadoAlFondo = true;
    else if (gestoEnCurso) pegadoAlFondo = false;
    actualizarBotonBajar();
  }, {passive: true});

  // La rueda y el dedo sí sueltan el ancla directamente: son gestos
  // inequívocos de "quiero leer hacia arriba".
  ['wheel', 'touchmove'].forEach((gesto) => {
    caja.addEventListener(gesto, () => {
      pegadoAlFondo = distanciaAlFondo() < MARGEN_FONDO;
      actualizarBotonBajar();
    }, {passive: true});
  });

  // Cada vez que una imagen o un audio termina de cargar, se vuelve a
  // bajar. En fase de captura porque `load` no burbujea: en la de
  // burbuja no llegaría nunca hasta el contenedor.
  //
  // De paso se le quita a la imagen el hueco reservado, para que a
  // partir de ahora mande su proporción real.
  caja.addEventListener('load', (e) => {
    if (e.target && e.target.tagName === 'IMG') e.target.classList.add('cargada');
    if (pegadoAlFondo) requestAnimationFrame(irAlFinal);
  }, true);

  // Cuando la caja de texto crece al escribir varias líneas, el hilo se
  // encoge por abajo. Es otra cosa distinta de que crezca el contenido.
  if (window.ResizeObserver) {
    new ResizeObserver(() => {
      if (pegadoAlFondo) irAlFinal();
    }).observe(caja);
  }

  // Red de seguridad para el primer par de segundos, que es cuando el
  // hilo se está acomodando: fuentes, imágenes que faltaban por cachear,
  // la barra del navegador del celular que aparece y desaparece. Sale
  // barato y evita depender de que llegue cada evento.
  [50, 150, 400, 800, 1500, 2500].forEach((cuando) => {
    setTimeout(() => { if (pegadoAlFondo) irAlFinal(); }, cuando);
  });
}

// ── Botón para volver al último mensaje ─────────────────────────────
// Solo aparece cuando te has ido hacia arriba a leer. Con la
// conversación al día no pinta nada tapando el hilo.

function actualizarBotonBajar() {
  if (!btnBajar || !caja) return;
  // Se mira la distancia real y no `pegadoAlFondo`: ese sigue en true
  // mientras el hilo se acomoda al abrir, y el botón parpadearía.
  btnBajar.hidden = distanciaAlFondo() < 120;
}

if (btnBajar && caja) {
  btnBajar.addEventListener('click', () => {
    // Volver a anclar además de bajar: si no, el siguiente mensaje que
    // entrara no arrastraría la vista y habría que tocarlo otra vez.
    pegadoAlFondo = true;
    caja.scrollTo({top: caja.scrollHeight, behavior: 'smooth'});
    actualizarBotonBajar();
  });
}

// ── Pintado de mensajes nuevos ─────────────────────────────────────
// Los mensajes se añaden al hilo sin recargar la página: así no se
// pierde lo que estés escribiendo, ni la posición del scroll.

const ETIQUETAS = PANEL.etiquetasAutor;

// El adjunto de un mensaje: la imagen, el reproductor o el enlace de
// descarga. Devuelve null si el mensaje era solo texto.
//
// Todo con createElement, nunca innerHTML ni plantillas de cadena: el
// nombre de un documento lo pone quien lo manda, y pegarlo como HTML
// sería dejarle escribir en el panel.
function crearAdjunto(m) {
  if (!m.media_tipo) return null;

  const caja = document.createElement('div');
  caja.className = 'adjunto';

  // Sin media_id no hay de dónde bajarlo: caducó en Meta (borra a los 7
  // días) o nunca llegó a subirse. Queda la constancia de que existió.
  if (!m.media_disponible) {
    const ido = document.createElement('div');
    ido.className = 'adjunto-ido';
    ido.textContent = (m.media_etiqueta || 'Archivo') + ' — ya no disponible';
    caja.appendChild(ido);
    return caja;
  }

  if (m.media_tipo === 'image') {
    const enlace = document.createElement('a');
    enlace.href = m.media_url;
    enlace.target = '_blank';
    enlace.rel = 'noopener';
    const img = document.createElement('img');
    img.src = m.media_url;
    img.alt = m.media_etiqueta || 'Imagen';
    img.loading = 'lazy';
    enlace.appendChild(img);
    caja.appendChild(enlace);
  } else if (m.media_tipo === 'audio') {
    const audio = document.createElement('audio');
    audio.controls = true;
    audio.preload = 'none';
    audio.src = m.media_url;
    caja.appendChild(audio);
  } else {
    const enlace = document.createElement('a');
    enlace.className = 'adjunto-archivo';
    enlace.href = m.media_url;
    enlace.target = '_blank';
    enlace.rel = 'noopener';
    enlace.textContent = m.media_etiqueta || 'Archivo';
    caja.appendChild(enlace);
  }

  // Guardar el archivo es lo que de verdad se hace con una imagen que
  // manda un cliente, y el caché del servidor solo la conserva un día.
  const bajar = document.createElement('a');
  bajar.className = 'adjunto-bajar';
  bajar.href = m.media_url + '?descargar=1';
  bajar.textContent = 'Guardar';
  caja.appendChild(bajar);

  return caja;
}

/* LAS HORAS, EN LA DEL QUE MIRA
   ───────────────────────────────────────────────────
   El servidor manda el instante en UTC y aquí se traduce. Es el
   navegador el único de los dos que sabe en qué huso está sentado quien
   atiende: antes el panel escribía "15:31 UTC" para un mensaje que en
   Medellín llegó a las 10:31, y había que restar cinco a mano. */

function horaLocal(iso) {
  const t = new Date(iso);
  if (!iso || isNaN(t)) return '';
  return t.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
}

function diaLocal(iso) {
  const t = new Date(iso);
  if (!iso || isNaN(t)) return '';

  const hoy = new Date();
  if (t.toDateString() === hoy.toDateString()) return 'Hoy';

  const ayer = new Date(hoy);
  ayer.setDate(ayer.getDate() - 1);
  if (t.toDateString() === ayer.toDateString()) return 'Ayer';

  return t.toLocaleDateString([], {weekday: 'long', day: 'numeric',
                                   month: 'long'});
}

/* Los separadores de día.

   Se ponen aquí y no en el servidor porque el día depende del huso de
   quien mira: un mensaje de las 20:00 en Medellín es del día siguiente
   en UTC, y el servidor habría partido el hilo por donde no toca.

   Se recalcula entero en vez de ir añadiendo: son unas decenas de
   burbujas y así no hay dos caminos que puedan discrepar. */
function ponerSeparadores() {
  if (!caja) return;

  caja.querySelectorAll('.dia').forEach(function (d) { d.remove(); });

  let ultimo = '';
  Array.from(caja.querySelectorAll('.burbuja')).forEach(function (b) {
    const iso = b.dataset.iso;
    if (!iso) return;

    const dia = diaLocal(iso);
    if (dia && dia !== ultimo) {
      const sep = document.createElement('div');
      sep.className = 'dia';
      sep.textContent = dia;
      b.parentNode.insertBefore(sep, b);
      ultimo = dia;
    }

    const hora = b.querySelector('[data-hora]');
    if (hora && !hora.textContent) hora.textContent = horaLocal(iso);
  });
}

function crearBurbuja(m) {
  const div = document.createElement('div');
  div.className = 'burbuja ' + m.quien;
  div.dataset.iso = m.iso || '';

  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = (ETIQUETAS[m.quien] || m.quien) + ' · ';
  const hora = document.createElement('time');
  hora.setAttribute('data-hora', '');
  hora.dateTime = m.iso || '';
  hora.textContent = horaLocal(m.iso);
  meta.appendChild(hora);
  div.appendChild(meta);

  const adjunto = crearAdjunto(m);
  if (adjunto) div.appendChild(adjunto);

  // Una imagen puede venir sin pie de foto: entonces no hay texto que
  // pintar y una caja vacía solo dejaría un hueco raro debajo.
  if (m.texto) {
    const texto = document.createElement('div');
    texto.className = 'texto';
    // textContent y no innerHTML: el mensaje lo escribe el cliente y no
    // puede acabar interpretándose como HTML.
    texto.textContent = m.texto;
    div.appendChild(texto);
  }

  return div;
}

// Añade una burbuja al hilo si es de esta conversación. Solo bajamos la
// vista si ya venías al final: si estabas leyendo hacia arriba no te
// movemos. Se hace en el siguiente frame, cuando el navegador ya midió
// la burbuja nueva.
function anadirAlHilo(m) {
  if (!caja || m.phone !== telefono) return;
  caja.appendChild(crearBurbuja(m));
  // El mensaje que entra puede estrenar día: a las 00:03 el separador
  // "Hoy" tiene que aparecer solo.
  ponerSeparadores();
  if (pegadoAlFondo) requestAnimationFrame(irAlFinal);
  // Añadir una burbuja no dispara `scroll`, así que el botón de bajar no
  // se enteraría: si estabas leyendo arriba y entra un mensaje, tiene
  // que aparecer.
  else actualizarBotonBajar();
}

// Plan B: preguntar por los mensajes nuevos. Solo se usa si el canal en
// vivo no está disponible.
async function buscarNuevos() {
  if (document.hidden || !caja) return;

  try {
    const r = await fetch('/admin/api/chat/' + encodeURIComponent(telefono) +
                          '?desde=' + ultimoId);
    // Sesión caducada con la pestaña abierta. Sin esto el hilo dejaba de
    // traer mensajes sin avisar y parecía que el cliente no contestaba.
    if (r.status === 401) { location.href = '/admin/login'; return; }
    if (!r.ok) return;
    const datos = await r.json();
    if (!datos.mensajes.length) return;

    for (const m of datos.mensajes) {
      caja.appendChild(crearBurbuja(m));
      ultimoId = Math.max(ultimoId, m.id);
    }
    ponerSeparadores();
    if (pegadoAlFondo) requestAnimationFrame(irAlFinal);

    refrescarListado();
  } catch (e) { /* sin red: se reintenta en el siguiente ciclo */ }
}
