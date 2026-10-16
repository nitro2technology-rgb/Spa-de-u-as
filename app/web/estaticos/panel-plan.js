/* El interruptor de la IA
   ─────────────────────────────────────────────────────────────────
   Vivía dentro de una f-string de Python. Ahí, cada llave había que
   escribirla doblada para que Python no la tomara por un hueco, y un
   descuido no daba un error de JavaScript: daba un error de Python al
   arrancar el servidor.

   Los guiones del panel comparten ámbito y se ejecutan EN ORDEN (van con
   `defer`, que lo respeta). Lo que declara `panel-base.js` lo ven los
   demás. Los valores que dependen del negocio llegan en `PANEL`, que la
   página define antes que estos archivos. */

// El botón de encender/apagar la IA. Recarga al terminar en vez de
// repintar la tarjeta a mano: es una acción que se hace de higos a
// brevas, y una recarga deja el panel entero coherente sin código que
// mantener.
document.querySelectorAll('.plan-btn').forEach(function (boton) {
  boton.addEventListener('click', function () {
    const quiere = boton.dataset.plan;
    boton.disabled = true;
    boton.textContent = 'Un momento…';

    fetch('/admin/api/plan', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({plan: quiere}),
    }).then(function (r) {
      return r.json().then(function (d) { return {ok: r.ok, datos: d}; });
    }).then(function (res) {
      if (!res.ok) {
        // El caso típico: se quitó la clave del servicio y el panel aún
        // enseñaba el botón. Se dice qué pasó en vez de dejarlo colgado.
        alert(res.datos.error || 'No se pudo cambiar el plan.');
        boton.disabled = false;
        boton.textContent = quiere === 'pro' ? 'Encender IA' : 'Apagar IA';
        return;
      }
      location.reload();
    }).catch(function () {
      alert('Sin conexión: el cambio no llegó a guardarse.');
      boton.disabled = false;
      boton.textContent = quiere === 'pro' ? 'Encender IA' : 'Apagar IA';
    });
  });
});
