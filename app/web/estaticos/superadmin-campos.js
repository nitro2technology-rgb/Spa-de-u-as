/* LOS CUADROS DE TEXTO CRECEN CON LO QUE SE ESCRIBE
   =================================================
   Un `<textarea rows="3">` mide tres renglones y no se mueve: a partir
   del cuarto hay que escribir mirando por una rendija, con barra propia
   y sin ver el principio de lo que uno acaba de poner. Los textos del
   bot no son de tres renglones —un mensaje de precios tiene diez— y
   quien los escribe no puede leerlos enteros.

   Aqui se le pone la altura de su contenido, y se vuelve a calcular en
   cada tecla.

   TRES COSAS QUE NO SON OBVIAS
   ----------------------------
   1. **Primero `auto`, luego `scrollHeight`.** `scrollHeight` mide el
      contenido *o* la altura fija, lo que sea mayor. Sin ponerlo en
      `auto` antes, el cuadro crece y no vuelve a encoger nunca al borrar.

   2. **Un campo escondido mide cero.** Dentro de un `<details>` cerrado o
      de una pestana que no esta a la vista, `scrollHeight` es 0 y el
      cuadro quedaria de un renglon al abrirlo. Por eso se recalcula
      cuando un `<details>` se abre y cuando el campo aparece en pantalla.

   3. **Se hace aqui y no con `field-sizing: content`.** Esa propiedad de
      CSS hace justo esto en una linea, pero solo la entienden los Chrome
      recientes: en Firefox y en Safari el cuadro se quedaria clavado en
      tres renglones y nadie se enteraria. Ver `superadmin.css`.

   Lo carga `superadmin._documento`, o sea TODAS las pantallas del
   super-admin. `superadmin-mapa.js` ademas llama a `acomodarCampo` a mano
   con los cuadros que crea sobre la marcha. */

(function () {
  'use strict';

  // Hasta donde puede crecer solo. Pasado eso saca su barra: un cuadro de
  // dos pantallas de alto esconde el boton de guardar.
  //
  // En un telefono 460px son dos tercios de la pantalla, asi que manda el
  // menor de los dos. Es el mismo `min(460px, 60vh)` de `superadmin.css`,
  // y los dos tienen que decir lo mismo.
  function maximo() {
    return Math.min(460, Math.round(window.innerHeight * 0.6));
  }

  function acomodarCampo(campo) {
    if (!campo || campo.tagName !== 'TEXTAREA') return;
    // `.mono` no es prosa: es el JSON de la cuenta de servicio y el logo
    // en base64. Son una linea de veinte mil caracteres, y crecer con
    // ellos seria taparle media pantalla a quien rellena esa ficha.
    if (campo.classList.contains('mono')) return;
    if (campo.dataset.sinCrecer !== undefined) return;
    // Escondido: no hay nada que medir. Se acomodara al asomar.
    if (!campo.offsetParent && campo.offsetHeight === 0) return;

    campo.style.height = 'auto';
    var alto = campo.scrollHeight;
    // El borde no entra en `scrollHeight` con `box-sizing: border-box`, y
    // sin sumarlo el cuadro sale dos pixeles corto y parpadea una barra.
    var estilo = window.getComputedStyle(campo);
    alto += parseFloat(estilo.borderTopWidth || 0)
          + parseFloat(estilo.borderBottomWidth || 0);

    var tope = maximo();
    campo.style.height = Math.min(alto, tope) + 'px';
    campo.style.overflowY = alto > tope ? 'auto' : 'hidden';
  }

  function acomodarTodos(donde) {
    (donde || document).querySelectorAll('textarea').forEach(acomodarCampo);
  }

  // En cada tecla, y tambien al pegar o al deshacer: `input` los cubre
  // todos. Va en el documento y no campo por campo, para que valga
  // igual para los cuadros que se crean despues.
  document.addEventListener('input', function (e) {
    if (e.target && e.target.tagName === 'TEXTAREA') acomodarCampo(e.target);
  });

  // Un `<details>` que se abre: sus cuadros acaban de dejar de medir 0.
  // `toggle` no burbujea, asi que se escucha en fase de captura.
  document.addEventListener('toggle', function (e) {
    if (e.target && e.target.tagName === 'DETAILS' && e.target.open) {
      acomodarTodos(e.target);
    }
  }, true);

  // El resto de los sitios donde un cuadro pasa de escondido a visible
  // sin que haya un `toggle`: una pestana, un bloque que se despliega.
  if (window.IntersectionObserver) {
    var mirando = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (entrada) {
        if (entrada.isIntersecting) acomodarCampo(entrada.target);
      });
    });
    var vigilar = function () {
      document.querySelectorAll('textarea').forEach(function (t) {
        mirando.observe(t);
      });
    };
    document.addEventListener('DOMContentLoaded', vigilar);
    if (document.readyState !== 'loading') vigilar();
  }

  // Al cambiar el ancho cambia cuantos renglones ocupa el mismo texto.
  var esperando;
  window.addEventListener('resize', function () {
    clearTimeout(esperando);
    esperando = setTimeout(function () { acomodarTodos(); }, 120);
  });

  document.addEventListener('DOMContentLoaded', function () { acomodarTodos(); });
  if (document.readyState !== 'loading') acomodarTodos();

  // Para quien cree cuadros a mano (`superadmin-mapa.js`).
  window.acomodarCampo = acomodarCampo;
  window.acomodarCampos = acomodarTodos;
})();
