/* La vista previa del logo en la ficha del cliente.
   Vivia dentro de una cadena de Python; ver superadmin.css. */

(function () {
  var archivo = document.getElementById('logo-archivo');
  var campo   = document.getElementById('logo');
  var vista   = document.getElementById('logo-vista');
  var nota    = document.getElementById('logo-nota');
  if (!archivo || !campo) return;

  // El icono se dibuja a 512px como mucho, así que más de esto es peso
  // que se paga en cada carga del panel y no se ve en ninguna parte.
  var MAXIMO = 1024 * 1024;

  function kb(n) { return Math.round(n / 1024) + ' KB'; }

  function pintar() {
    var valor = (campo.value || '').trim();
    if (!valor) { vista.hidden = true; return; }
    vista.src = valor.slice(0, 5) === 'data:'
      ? valor : 'data:image/png;base64,' + valor;
    vista.hidden = false;
  }

  archivo.addEventListener('change', function () {
    var f = archivo.files && archivo.files[0];
    if (!f) return;
    if (f.size > MAXIMO) {
      nota.textContent = 'Esa imagen pesa ' + kb(f.size) +
        '. Achícala a menos de 1 MB: el icono no pasa de 512 px.';
      archivo.value = '';
      return;
    }
    var lector = new FileReader();
    lector.onload = function () {
      campo.value = lector.result;
      nota.textContent = f.name + ' · ' + kb(f.size) +
        '. Todavía no está guardado: dale a Guardar.';
      pintar();
    };
    lector.onerror = function () {
      nota.textContent = 'No se pudo leer ese archivo.';
    };
    lector.readAsDataURL(f);
  });

  // Quien prefiera pegar la cadena a mano sigue pudiendo, y ve lo mismo.
  campo.addEventListener('input', pintar);
  pintar();
})();
