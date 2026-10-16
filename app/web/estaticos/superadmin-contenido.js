/* El editor de contenido: anadir opciones y sub-opciones al menu.
   Vivia dentro de una cadena de Python; ver superadmin.css.

   El <template> vacio que clona esto SE QUEDA en el HTML: es marcado,
   no comportamiento, y sacarlo de la pagina obligaria a crearlo desde
   JavaScript solo para poder clonarlo. */
// Clonar la ÚLTIMA opción y vaciarla es más fiable que mantener una
// plantilla aparte: si mañana se le añade un campo al formulario, la
// opción nueva lo hereda sin que haya que acordarse de nada.
function clonarVacia(origen, prefijoViejo, prefijoNuevo) {
  const copia = origen.cloneNode(true);
  copia.querySelectorAll('input, select, textarea').forEach(c => {
    if (c.name) c.name = c.name.replace(prefijoViejo, prefijoNuevo);
    if (c.type === 'checkbox') c.checked = false;
    else if (c.tagName === 'SELECT') c.selectedIndex = 0;
    else c.value = '';
  });
  return copia;
}

function anadirOpcion() {
  const lista = document.getElementById('menu-opciones');
  const bloques = lista.querySelectorAll(':scope > .opcion-principal');
  if (!bloques.length) return;
  const ultimo = bloques[bloques.length - 1];
  const n = bloques.length;
  const copia = clonarVacia(ultimo, /menu-\\d+/g, 'menu-' + n);
  copia.querySelectorAll('.submenu .opcion').forEach(s => s.remove());
  copia.querySelector('.opcion-cabecera strong').textContent = 'Opción ' + (n + 1);
  const sub = copia.querySelector('.submenu');
  if (sub) sub.id = 'sub-' + n;
  const boton = copia.querySelector('button[onclick^="anadirSub"]');
  if (boton) boton.setAttribute('onclick', 'anadirSub(' + n + ')');
  lista.appendChild(copia);
  copia.scrollIntoView({behavior: 'smooth', block: 'center'});
}

function anadirSub(i) {
  const zona = document.getElementById('sub-' + i);
  const existentes = zona.querySelectorAll('.opcion');
  const j = existentes.length;
  let copia;
  if (existentes.length) {
    copia = clonarVacia(existentes[existentes.length - 1],
                        new RegExp('menu-' + i + '-sub-\\\\d+', 'g'),
                        'menu-' + i + '-sub-' + j);
  } else {
    // Sin ninguna sub-opción de la que copiar, se clona la opción padre.
    const padre = zona.parentElement.querySelector(':scope > .opcion');
    copia = clonarVacia(padre, new RegExp('menu-' + i + '(?!-sub)', 'g'),
                        'menu-' + i + '-sub-' + j);
  }
  copia.querySelector('.opcion-cabecera strong').textContent =
      'Sub-opción ' + (i + 1) + '.' + (j + 1);
  zona.appendChild(copia);
  copia.scrollIntoView({behavior: 'smooth', block: 'center'});
}
