/* LA PANTALLA DE ENTRADA
   ─────────────────────────────────────────────────────────────────
   Una sola cosa: enseñar la clave escrita.

   Parece un adorno y no lo es. La clave del panel se la damos nosotros
   al cliente, así que la primera vez la copia de un mensaje y no puede
   comprobar lo que pegó. Sin esto, "clave incorrecta" tres veces
   seguidas y una llamada. */

document.addEventListener('click', function (e) {
  const boton = e.target.closest('[data-ver-clave]');
  if (!boton) return;

  const campo = boton.parentElement.querySelector('input');
  if (!campo) return;

  const oculta = campo.type === 'password';
  campo.type = oculta ? 'text' : 'password';
  boton.textContent = oculta ? 'Ocultar' : 'Ver';
  campo.focus();
});
