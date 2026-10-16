/* EL INTERRUPTOR DE TEMA
   ─────────────────────────────────────────────────────────────────
   Claro u oscuro lo elige QUIEN USA EL PANEL, y se recuerda. El sistema
   operativo solo decide la primera vez: quien atiende conversaciones a
   las once de la noche quiere poder cambiarlo sin tocar el ajuste de
   todo su equipo.

   La clase se pone en `<html>` desde un guion inline del <head>, antes
   de pintar nada. Si se hiciera aquí, con `defer`, la página aparecería
   un instante en claro antes de volverse oscura — ese destello blanco a
   oscuras molesta de verdad. */

const CLAVE_TEMA = 'n2t-tema';

function temaActual() {
  return document.documentElement.classList.contains('tema-oscuro')
    ? 'oscuro' : 'claro';
}

function ponerTema(tema) {
  const raiz = document.documentElement;
  raiz.classList.remove('tema-claro', 'tema-oscuro');
  raiz.classList.add('tema-' + tema);
  try { localStorage.setItem(CLAVE_TEMA, tema); } catch (e) {}

  const etiqueta = tema === 'oscuro' ? 'Modo claro' : 'Modo oscuro';

  document.querySelectorAll('[data-tema-boton]').forEach(function (b) {
    // Solo se escribe dentro del botón si el botón es texto. En el rail
    // es un icono, y meterle `textContent` le borraría el SVG dejando un
    // hueco donde había un botón — sin error, sin pista.
    if (!b.firstElementChild) b.textContent = etiqueta;
    b.setAttribute('aria-label',
      tema === 'oscuro' ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro');
    b.title = etiqueta;
  });
}

document.addEventListener('click', function (e) {
  const boton = e.target.closest('[data-tema-boton]');
  if (!boton) return;
  ponerTema(temaActual() === 'oscuro' ? 'claro' : 'oscuro');
});

// Al cargar, el boton tiene que decir lo que va a hacer, no lo que hay.
ponerTema(temaActual());
