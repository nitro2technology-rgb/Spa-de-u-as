/* EL INTERRUPTOR DE TEMA DEL SUPER-ADMIN, Y EL CONTADOR DE CAMBIOS
   ─────────────────────────────────────────────────────────────────
   Dos cosas pequenas que solo tienen sentido juntas: son lo unico que
   esta consola necesita del navegador para funcionar. Todo lo demas
   —pestanas, guardados, filtros— son enlaces y formularios de verdad,
   porque una consola que se opera un domingo no puede depender de que
   un guion cargue.

   ── EL TEMA: TRES ESTADOS ─────────────────────────────────────────
   `Sistema · Claro · Oscuro`, no un interruptor de dos. Con dos, quien
   prueba el manual una vez ya no puede volver a seguir a su sistema
   operativo: no hay forma de borrar la eleccion. El tercer estado ES
   esa forma.

   Se guarda en `localStorage` bajo `superadmin:tema` y se aplica con
   `data-tema` en <html>. El valor `auto` no escribe el atributo: manda
   `prefers-color-scheme`, y por eso el CSS tiene que anular su regla
   con `:not([data-tema="claro"])` (ver superadmin.css).

   SIN DESTELLO: quien pone el atributo al cargar es un guion en linea
   de dos lineas dentro del <head>, antes del CSS. Si se hiciera aqui,
   con `defer`, la pagina apareceria un instante en claro antes de
   volverse oscura — ese fogonazo blanco a oscuras molesta de verdad. */

(function () {
  var CLAVE = 'superadmin:tema';

  function leer() {
    try { return localStorage.getItem(CLAVE) || 'auto'; } catch (e) { return 'auto'; }
  }

  function poner(tema) {
    var raiz = document.documentElement;
    if (tema === 'auto') delete raiz.dataset.tema;
    else raiz.dataset.tema = tema;
    try { localStorage.setItem(CLAVE, tema); } catch (e) {}
    pintar(tema);
  }

  function pintar(tema) {
    document.querySelectorAll('[data-tema-valor]').forEach(function (b) {
      b.setAttribute('aria-pressed', b.dataset.temaValor === tema ? 'true' : 'false');
    });
  }

  document.addEventListener('click', function (e) {
    var boton = e.target.closest('[data-tema-valor]');
    if (boton) poner(boton.dataset.temaValor);
  });

  pintar(leer());

  /* ── EL CONTADOR DE CAMBIOS SIN GUARDAR ─────────────────────────
     Una pestana larga se recorre entera antes de guardar, y "¿le di a
     guardar?" no tiene respuesta si la barra dice siempre lo mismo.
     Cuenta CAMPOS distintos tocados, no pulsaciones: escribir diez
     letras en un cuadro es un cambio, no diez.

     Se compara con el valor de partida, asi que deshacer a mano
     devuelve el contador a "Sin cambios" — que es justo lo que quien
     mira necesita saber.

     El boton de guardar NO se deshabilita sin cambios. Un boton
     apagado obliga a adivinar por que; y guardar sin cambios no hace
     dano ninguno. */
  document.querySelectorAll('form[data-cuenta-cambios]').forEach(function (form) {
    var salida = document.querySelector(
      '[data-contador-de="' + form.dataset.cuentaCambios + '"]');
    if (!salida) return;

    var campos = form.querySelectorAll('input, select, textarea');
    var inicio = new WeakMap();
    campos.forEach(function (c) {
      inicio.set(c, c.type === 'checkbox' || c.type === 'radio' ? c.checked : c.value);
    });

    function contar() {
      var n = 0;
      campos.forEach(function (c) {
        var ahora = c.type === 'checkbox' || c.type === 'radio' ? c.checked : c.value;
        if (ahora !== inicio.get(c)) n++;
      });
      salida.dataset.sucio = n ? 'si' : 'no';
      salida.textContent = n === 0 ? 'Sin cambios'
        : n === 1 ? '1 cambio sin guardar'
        : n + ' cambios sin guardar';
    }

    form.addEventListener('input', contar);
    form.addEventListener('change', contar);
    contar();
  });

  /* ── LA AYUDA, PLEGADA EN PANTALLA ESTRECHA ─────────────────────
     Sale del servidor ABIERTA a propósito: sin JavaScript, la ayuda se
     lee igual — mal colocada, pero nunca escondida. Esto solo la pliega
     donde la columna no cabe y su texto empujaría el formulario dos
     pantallas hacia abajo.

     Se hace una vez, al cargar. Si alguien la abre a mano y luego gira
     el teléfono, se queda como la dejó: volver a cerrársela sería
     deshacerle algo que pidió. */
  var estrecha = window.matchMedia('(max-width: 1180px)');
  if (estrecha.matches) {
    document.querySelectorAll('.ayuda-lateral[open]').forEach(function (d) {
      d.open = false;
    });
  }

  /* ── COPIAR ─────────────────────────────────────────────────────
     La URL de webhook y el token de verificacion se copian, no se
     escriben: van en cajas de solo lectura y esto es su unico boton.
     Sin portapapeles (http en una red local, un navegador viejo) se
     selecciona el texto, que deja copiarlo a mano. */
  document.addEventListener('click', function (e) {
    var boton = e.target.closest('[data-copiar]');
    if (!boton) return;
    var caja = document.getElementById(boton.dataset.copiar);
    if (!caja) return;

    var decir = function (texto) {
      var antes = boton.textContent;
      boton.textContent = texto;
      setTimeout(function () { boton.textContent = antes; }, 1600);
    };

    var seleccionar = function () {
      var rango = document.createRange();
      rango.selectNodeContents(caja);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(rango);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(caja.textContent.trim())
        .then(function () { decir('Copiado'); })
        .catch(function () { seleccionar(); decir('Selecciona y copia'); });
    } else {
      seleccionar();
      decir('Selecciona y copia');
    }
  });
})();
