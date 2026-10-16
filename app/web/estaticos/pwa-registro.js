/* Registro de la app instalable
   ─────────────────────────────────────────────────────────────────
   Vivía dentro de una f-string de Python. Ahí, cada llave había que
   escribirla doblada para que Python no la tomara por un hueco, y un
   descuido no daba un error de JavaScript: daba un error de Python al
   arrancar el servidor.

   Los guiones del panel comparten ámbito y se ejecutan EN ORDEN (van con
   `defer`, que lo respeta). Lo que declara `panel-base.js` lo ven los
   demás. Los valores que dependen del negocio llegan en `PANEL`, que la
   página define antes que estos archivos. */

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(e =>
      console.warn('[pwa] no se pudo registrar el service worker', e));
  });
}
