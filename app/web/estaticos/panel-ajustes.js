/* LA CONFIGURACIÓN
   ─────────────────────────────────────────────────────────────────
   Los avisos del navegador y el tema. Son ajustes de QUIEN ATIENDE, no
   del negocio: lo del negocio se toca en /superadmin y cambia lo que ven
   sus clientes.

   LO IMPORTANTE DE LOS AVISOS
   ---------------------------
   Son **por dispositivo**. Cada navegador se suscribe por su cuenta, así
   que activarlos en el computador de la oficina no los activa en el
   celular. Por eso el estado que se enseña sale de ESTE navegador
   (`pushManager.getSubscription`) y no de la lista del servidor: el
   servidor sabe cuántos dispositivos hay apuntados, pero no cuál de
   ellos eres tú.

   Y el permiso del navegador **solo se puede pedir una vez**. Si el
   usuario dice que no, Chrome no vuelve a preguntar por mucho que se lo
   pidamos: hay que decirle que lo cambie él en los ajustes del sitio. Un
   botón que insista sin explicar eso deja a la gente pulsando en vano. */

const _estado = document.querySelector('[data-estado-avisos]');
const _texto = document.querySelector('[data-texto-avisos]');
const _boton = document.querySelector('[data-avisos]');

// La clave viaja en base64url y el navegador la exige como bytes.
function claveABytes(base64) {
  const relleno = '='.repeat((4 - base64.length % 4) % 4);
  const limpio = (base64 + relleno).replace(/-/g, '+').replace(/_/g, '/');
  const crudo = atob(limpio);
  return Uint8Array.from([...crudo].map(c => c.charCodeAt(0)));
}

function pintarEstado(clase, texto, etiquetaBoton) {
  if (!_estado) return;
  _estado.className = 'ajuste-estado ' + clase;
  if (_texto) _texto.textContent = texto;

  if (!_boton) return;
  if (etiquetaBoton) {
    _boton.textContent = etiquetaBoton;
    _boton.hidden = false;
    _boton.disabled = false;
    // Activar es la acción principal; desactivar no debe invitar.
    _boton.className = etiquetaBoton === 'Activar'
      ? 'boton-solido' : 'boton-contorno';
  } else {
    _boton.hidden = true;
  }
}

async function registroListo() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null;
  if (!('Notification' in window)) return null;
  return navigator.serviceWorker.ready;
}

async function mirarAvisos() {
  if (!_estado) return;   // el servidor no tiene claves: no hay interruptor

  const registro = await registroListo();
  if (!registro) {
    pintarEstado('apagado', 'Este navegador no admite avisos', '');
    return;
  }

  // Denegado no es "apagado": es una puerta que solo puede abrir el
  // usuario desde los ajustes del navegador. Decirlo evita que se quede
  // pulsando un botón que nunca va a funcionar.
  if (Notification.permission === 'denied') {
    pintarEstado('bloqueado',
      'Bloqueados en este navegador. Para permitirlos, ábrelos en los ' +
      'ajustes del sitio (el candado junto a la dirección).', '');
    return;
  }

  const suscripcion = await registro.pushManager.getSubscription();
  if (suscripcion) {
    pintarEstado('encendido', 'Activados en este dispositivo', 'Desactivar');
  } else {
    pintarEstado('apagado', 'Desactivados en este dispositivo', 'Activar');
  }
}

async function activar(registro) {
  // El permiso SOLO se pide tras un clic: pedirlo al cargar hace que
  // algunos navegadores lo bloqueen de por vida.
  if (await Notification.requestPermission() !== 'granted') {
    await mirarAvisos();
    return;
  }

  const r = await fetch('/admin/api/push/clave');
  if (r.status === 401) { location.href = '/admin/login'; return; }
  const clave = r.ok ? (await r.json()).clave : '';
  if (!clave) {
    pintarEstado('apagado', 'El servicio no tiene sus claves de avisos', '');
    return;
  }

  const suscripcion = await registro.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: claveABytes(clave)
  });

  const guardado = await fetch('/admin/api/push/suscribir', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(suscripcion)
  });
  if (guardado.status === 401) { location.href = '/admin/login'; return; }
  if (!guardado.ok) throw new Error('no se guardó la suscripción');
}

async function desactivar(registro) {
  const suscripcion = await registro.pushManager.getSubscription();
  if (!suscripcion) return;

  // Primero se le dice al servidor y después se cancela aquí. Al revés,
  // si la red falla en medio, el servidor seguiría mandando avisos a un
  // dispositivo que ya no puede recibirlos.
  const r = await fetch('/admin/api/push/baja', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({endpoint: suscripcion.endpoint})
  });
  if (r.status === 401) { location.href = '/admin/login'; return; }

  await suscripcion.unsubscribe();
}

if (_boton) {
  _boton.addEventListener('click', async function () {
    const registro = await registroListo();
    if (!registro) return;

    const quiereActivar = _boton.textContent === 'Activar';
    _boton.disabled = true;
    _boton.textContent = 'Un momento…';

    try {
      if (quiereActivar) await activar(registro);
      else await desactivar(registro);
    } catch (e) {
      console.warn('[avisos] no se pudo cambiar', e);
      pintarEstado('apagado', 'No se pudo cambiar. Inténtalo otra vez.',
                   quiereActivar ? 'Activar' : 'Desactivar');
      return;
    }

    await mirarAvisos();
  });
}

mirarAvisos();

// El tema lo cambia `panel-tema.js`; aquí solo se dice cuál está puesto.
// Se refresca en cada clic porque el botón y este texto viven en la
// misma fila y quedarían diciendo cosas distintas.
function pintarTema() {
  const donde = document.querySelector('[data-tema-actual]');
  if (!donde) return;
  donde.textContent = document.documentElement.classList.contains('tema-oscuro')
    ? 'Modo oscuro' : 'Modo claro';
}

document.addEventListener('click', function (e) {
  if (e.target.closest('[data-tema-boton]')) setTimeout(pintarTema, 0);
});
pintarTema();
