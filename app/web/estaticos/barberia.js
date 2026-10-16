/* ══════════════════════════════════════════════════════════════════
   EL PANEL DE LA BARBERÍA — lo mínimo que no puede hacer el HTML
   ══════════════════════════════════════════════════════════════════
   El panel funciona sin esto: los formularios se envían solos, los
   filtros son enlaces y el servidor valida todo otra vez. Aquí va solo
   lo que es comodidad:

     · "Mostrar / Ocultar" la contraseña.
     · El aviso de "hecho" que llega en `<body data-aviso>` (2,6 s; uno a
       la vez, el nuevo reemplaza al anterior).
     · Los montos se escriben con formato mientras se teclean ($394.000).
     · El arqueo de la caja en vivo, y "Cerrar caja" apagado hasta que
       haya un conteo.
     · La hoja de cobro del barbero: total, "Para ti" y el texto del botón
       que dice qué falta.
     · El usuario que se autocompleta con el nombre (Daniel Castro →
       daniel.c) y "Generar otra" contraseña temporal.
     · Paneles, diálogos y hojas: Esc los cierra, el foco no se sale de
       ellos y al abrir va al primer campo.
   ══════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var DURACION_AVISO = 2600;
  var temporizador = null;

  function avisar(texto) {
    var caja = document.querySelector('.aviso');
    if (!caja || !texto) return;
    caja.textContent = texto;
    caja.hidden = false;
    clearTimeout(temporizador);
    temporizador = setTimeout(function () { caja.hidden = true; }, DURACION_AVISO);
  }
  window.barberiaAvisar = avisar;

  // ── Dinero ──────────────────────────────────────────────────────
  function digitos(texto) { return String(texto || '').replace(/\D/g, ''); }
  function valor(texto) { var d = digitos(texto); return d ? parseInt(d, 10) : 0; }
  function pesos(n) {
    var signo = n < 0 ? '−' : '';
    return signo + '$' + Math.abs(Math.round(n)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }

  function formatearDinero(campo) {
    var d = digitos(campo.value);
    campo.value = d ? pesos(parseInt(d, 10)) : '';
  }

  // ── Arqueo (6.2.3) ──────────────────────────────────────────────
  function arqueo(form) {
    var esperado = parseInt(form.getAttribute('data-arqueo'), 10) || 0;
    var campo = form.querySelector('[name="contado"]');
    var salida = form.querySelector('[data-arqueo-resultado]');
    var boton = form.querySelector('[data-requiere-conteo]');
    var hay = digitos(campo.value) !== '';
    if (boton) boton.disabled = !hay;
    if (!salida) return;
    if (!hay) { salida.hidden = true; return; }
    var dif = valor(campo.value) - esperado;
    salida.hidden = false;
    salida.className = 'arqueo-resultado ' + (dif === 0 ? 'ok' : dif < 0 ? 'mal' : 'aviso');
    salida.textContent = dif === 0 ? 'Cuadra exacto'
      : dif < 0 ? 'Falta ' + pesos(-dif) : 'Sobra ' + pesos(dif);
  }

  // ── Hoja de cobro (6.4) ─────────────────────────────────────────
  function cobro(form) {
    var pct = parseInt(form.getAttribute('data-porcentaje'), 10) || 0;
    var subtotal = 0, elegidos = 0;
    form.querySelectorAll('[name="servicios"]:checked').forEach(function (c) {
      subtotal += parseInt(c.getAttribute('data-precio'), 10) || 0;
      elegidos += 1;
    });
    var propina = form.querySelector('[name="propina"]:checked');
    propina = propina ? parseInt(propina.value, 10) || 0 : 0;
    var metodo = form.querySelector('[name="metodo"]:checked');
    metodo = metodo ? metodo.value : '';
    var total = subtotal + propina;
    var suyo = Math.round(subtotal * pct / 100) + propina;

    var dividido = form.querySelector('[data-dividido]');
    if (dividido) {
      dividido.hidden = metodo !== 'dividido';
      var efectivo = valor((dividido.querySelector('input') || {}).value);
      var resto = dividido.querySelector('[data-resto]');
      if (resto) resto.textContent = efectivo > 0 && efectivo < total
        ? 'y ' + pesos(total - efectivo) + ' por transferencia' : '';
    }

    var t = form.querySelector('[data-total]');
    var s = form.querySelector('[data-suyo]');
    if (t) t.textContent = pesos(total);
    if (s) s.textContent = pesos(suyo);

    var boton = form.querySelector('[data-boton-cobro]');
    if (!boton) return;
    if (!elegidos) { boton.disabled = true; boton.textContent = 'Elige qué le hiciste'; }
    else if (!metodo) { boton.disabled = true; boton.textContent = 'Elige cómo pagó'; }
    else { boton.disabled = false; boton.textContent = 'Registrar ' + pesos(total); }
  }

  function anular(form) {
    var boton = form.querySelector('[data-boton-anular]');
    var elegido = form.querySelector('[name="motivo"]:checked');
    if (!boton) return;
    boton.disabled = !elegido;
    boton.classList.toggle('listo', !!elegido);
  }

  function requiereCampos(form) {
    var boton = form.querySelector('[data-requiere-campos]');
    if (!boton) return;
    var faltan = false;
    form.querySelectorAll('[data-requerido]').forEach(function (c) {
      if (c.hasAttribute('data-dinero') ? valor(c.value) <= 0 : !c.value.trim()) faltan = true;
    });
    boton.disabled = faltan;
  }

  // ── Usuarios (6.2.9) ────────────────────────────────────────────
  function sinTildes(texto) {
    return texto.normalize('NFD').replace(/[̀-ͯ]/g, '');
  }
  function sugerirUsuario(nombre) {
    var partes = sinTildes(nombre).toLowerCase().split(/\s+/)
      .map(function (p) { return p.replace(/[^a-z0-9]/g, ''); })
      .filter(Boolean);
    if (!partes.length) return '';
    return partes[0] + (partes.length > 1 ? '.' + partes[partes.length - 1][0] : '');
  }

  function refrescar(form) {
    if (!form) return;
    if (form.hasAttribute('data-arqueo')) arqueo(form);
    if (form.hasAttribute('data-cobro')) cobro(form);
    if (form.hasAttribute('data-anular')) anular(form);
    requiereCampos(form);
  }

  document.addEventListener('input', function (ev) {
    var campo = ev.target;
    if (campo.matches('[data-dinero]')) formatearDinero(campo);
    if (campo.matches('[data-autocompletar-usuario]')) {
      var usuario = campo.form && campo.form.querySelector('[data-usuario]');
      if (usuario && !usuario.hasAttribute('data-tocado')) usuario.value = sugerirUsuario(campo.value);
    }
    if (campo.matches('[data-usuario]')) {
      campo.setAttribute('data-tocado', '');
      var limpio = campo.value.toLowerCase().replace(/[^a-z0-9._]/g, '');
      if (limpio !== campo.value) campo.value = limpio;
    }
    refrescar(campo.form);
  });
  document.addEventListener('change', function (ev) {
    var form = ev.target.form;
    // "Nueva cita": elegir barbero, servicio o día vuelve a pedir las horas
    // libres. Sin JavaScript está el botón "Ver horas libres".
    if (form && form.hasAttribute('data-auto-enviar')) { form.submit(); return; }
    refrescar(form);
  });

  document.addEventListener('click', function (ev) {
    var ver = ev.target.closest('[data-ver-clave]');
    if (ver) {
      var campo = ver.parentElement.querySelector('input');
      if (!campo) return;
      var mostrar = campo.type === 'password';
      campo.type = mostrar ? 'text' : 'password';
      ver.textContent = mostrar ? 'Ocultar' : 'Mostrar';
      ver.setAttribute('aria-pressed', mostrar ? 'true' : 'false');
      campo.focus();
      return;
    }
    var generar = ev.target.closest('[data-generar-temporal]');
    if (generar) {
      var nueva = generar.getAttribute('data-generar-temporal') + '-' +
        (1000 + Math.floor(Math.random() * 9000));
      var caja = generar.closest('.clave-temporal');
      caja.querySelector('[data-temporal]').value = nueva;
      caja.querySelector('[data-temporal-texto]').textContent = nueva;
    }
  });

  // ── Paneles, diálogos y hojas ───────────────────────────────────
  var ENFOCABLES = 'a[href], button:not([disabled]), input:not([type="hidden"]):not([disabled]), select, textarea';

  function superpuesto() { return document.querySelector('[data-cerrar-en]'); }

  document.addEventListener('keydown', function (ev) {
    var abierto = superpuesto();
    if (!abierto) return;
    if (ev.key === 'Escape') {
      window.location.href = abierto.getAttribute('data-cerrar-en');
      return;
    }
    if (ev.key !== 'Tab') return;
    var lista = Array.prototype.filter.call(abierto.querySelectorAll(ENFOCABLES),
      function (el) { return el.offsetParent !== null; });
    if (!lista.length) return;
    var primero = lista[0], ultimo = lista[lista.length - 1];
    if (ev.shiftKey && document.activeElement === primero) { ev.preventDefault(); ultimo.focus(); }
    else if (!ev.shiftKey && document.activeElement === ultimo) { ev.preventDefault(); primero.focus(); }
  });

  document.addEventListener('DOMContentLoaded', function () {
    avisar(document.body.getAttribute('data-aviso'));
    // Que un "atrás" del navegador no repita el aviso.
    if (document.body.hasAttribute('data-aviso') && window.history.replaceState) {
      var url = new URL(window.location.href);
      if (url.searchParams.has('aviso')) {
        url.searchParams.delete('aviso');
        window.history.replaceState(null, '', url.pathname + url.search);
      }
    }

    document.querySelectorAll('form').forEach(refrescar);
    document.querySelectorAll('[data-solo-sin-js]').forEach(function (b) { b.hidden = true; });

    var abierto = superpuesto();
    if (abierto) {
      document.body.style.overflow = 'hidden';
      // Al primer campo solo si el formulario lo pide (`autofocus`); si no,
      // a lo primero que se pueda tocar ("Cerrar", arriba). Enfocar un
      // campo de la mitad desplazaba la ficha y se abría por el medio.
      var primero = abierto.querySelector('[autofocus]') || abierto.querySelector(ENFOCABLES);
      if (primero) primero.focus();
    }
  });
})();
