/* El canal de mensajes en vivo
   ─────────────────────────────────────────────────────────────────
   Vivía dentro de una f-string de Python. Ahí, cada llave había que
   escribirla doblada para que Python no la tomara por un hueco, y un
   descuido no daba un error de JavaScript: daba un error de Python al
   arrancar el servidor.

   Los guiones del panel comparten ámbito y se ejecutan EN ORDEN (van con
   `defer`, que lo respeta). Lo que declara `panel-base.js` lo ven los
   demás. Los valores que dependen del negocio llegan en `PANEL`, que la
   página define antes que estos archivos. */

let canal = null;
let fallos = 0;
let respaldo = null;

function alLlegar(m) {
  if (m.id <= ultimoId) return;   // ya lo teníamos: el canal reconectó
  ultimoId = m.id;
  // En la bandeja no hay hilo que pintar, solo listado que refrescar.
  if (typeof anadirAlHilo === 'function') anadirAlHilo(m);
  refrescarListado();
}

// Plan B: si el canal en vivo no funciona (una red que corta las
// conexiones largas, un proxy raro), se vuelve a preguntar cada pocos
// segundos. Más lento, pero nunca te quedas sin ver los mensajes.
function arrancarRespaldo() {
  if (respaldo) return;
  console.warn('[panel] Canal en vivo no disponible; se vuelve a consultar por turnos.');
  respaldo = setInterval(() => {
    if (typeof buscarNuevos === 'function') buscarNuevos();
    refrescarListado();
  }, PANEL.segundosPlanB * 1000);
}

function pararRespaldo() {
  if (respaldo) { clearInterval(respaldo); respaldo = null; }
  fallos = 0;
}

function conectar() {
  canal = new EventSource('/admin/api/stream?desde=' + ultimoId);

  canal.onopen = pararRespaldo;
  canal.onmessage = (e) => { pararRespaldo(); alLlegar(JSON.parse(e.data)); };

  // La sesión caducó con la pestaña abierta. Sin esto el hilo se quedaba
  // sin actualizar en silencio y parecía que nadie había contestado.
  canal.addEventListener('caducada', () => {
    canal.close();
    location.href = '/admin/login';
  });

  canal.onerror = () => {
    // EventSource reintenta solo mientras la conexión siga viva. Si se
    // cerró del todo (el navegador ya no va a reintentar) reconectamos a
    // mano, con el id actualizado para no repetir lo que ya está pintado.
    if (++fallos >= 3) arrancarRespaldo();
    if (canal.readyState === EventSource.CLOSED) {
      setTimeout(conectar, Math.min(fallos * 2000, 30000));
    }
  };
}

if (window.EventSource) { conectar(); } else { arrancarRespaldo(); }

// Al volver a la pestaña, ponerse al día enseguida por si el canal se
// durmió mientras el teléfono estaba bloqueado.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  refrescarListado();
  if (!canal || canal.readyState === EventSource.CLOSED) conectar();
});

// ── Avisos al celular ───────────────────────────────────────────────
// El canal en vivo solo funciona con el panel abierto. Esto es lo que
// avisa cuando está cerrado: una notificación del sistema, entregada
// por el service worker.

/* Los avisos del navegador se activan y se desactivan en
   /admin/configuracion (`panel-ajustes.js`).

   Aqui habia un boton que se colaba dentro de la cabecera del chat, y
   tenia dos problemas: aparecia entre "Estado", "Reiniciar" y "Eliminar"
   como si fuera otra accion de esa conversacion, y **solo servia para
   activar** — para desactivarlos no habia nada, aunque el endpoint de
   baja existiera desde el principio. */
