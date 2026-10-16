/* Lo que comparten todas las pantallas
   ─────────────────────────────────────────────────────────────────
   Vivía dentro de una f-string de Python. Ahí, cada llave había que
   escribirla doblada para que Python no la tomara por un hueco, y un
   descuido no daba un error de JavaScript: daba un error de Python al
   arrancar el servidor.

   Los guiones del panel comparten ámbito y se ejecutan EN ORDEN (van con
   `defer`, que lo respeta). Lo que declara `panel-base.js` lo ven los
   demás. Los valores que dependen del negocio llegan en `PANEL`, que la
   página define antes que estos archivos. */

// Cómo se llama cada estado en pantalla. Va aquí y no en el guion del
// hilo porque el listado también los pinta, y el listado vive en las dos
// pantallas: la bandeja suelta y la barra lateral del chat.
const ETIQUETAS_ESTADO = PANEL.etiquetasEstado;

const telefono = decodeURIComponent(location.pathname.split('/').pop());

// El id del último mensaje que ya tenemos pintado. El canal en vivo
// arranca desde aquí para no perderse nada ni repetir.
let ultimoId = Number(document.body.dataset.ultimoId || 0);

// La caja del hilo. En la bandeja no existe, y vale null: los guiones
// comprueban antes de tocarla.
const caja = document.getElementById('chat');
