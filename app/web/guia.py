"""
LA GUÍA DE CONEXIÓN
====================
La página que se le manda a un cliente nuevo para que conecte su WhatsApp:

    /conectar

Es lo primero que ve de nosotros alguien que acaba de contratar, y lo
único que va a tener delante mientras pelea con el panel de Meta. Por eso
vive aquí y no en un enlace a un documento suelto: una dirección que no
caduca, servida por el mismo dominio que su panel.

    ⚠️  ES UNA PÁGINA DE LA PLATAFORMA, NO DE UN NEGOCIO.

Esa es la diferencia con `paginas_publicas.py`, y es deliberada. Las
políticas se sirven con el nombre y el correo de CADA cliente, porque son
suyas: es su negocio el que responde por los datos. Esta no. Esta la firma
Nitro, la lee alguien que todavía no es cliente del todo, y el soporte al
que escribe es el nuestro. Meterla en el marco por inquilino la haría
decir el nombre del negocio equivocado — el del inquilino de la petición,
que sin sesión es el cliente por defecto.

POR QUÉ NO USA GOOGLE FONTS
---------------------------
Manrope e IBM Plex Mono ya se sirven desde `/estaticos/fuentes/` para el
panel. Pedirlas otra vez a Google sería una dependencia externa nueva en
la única página que alguien va a abrir desde una conexión mala, en mitad
de un trámite, con nuestro logo encima. Se reutiliza lo que ya está.

QUÉ TIENE QUE SEGUIR SIENDO CIERTO
----------------------------------
Los cuatro avisos que lleva no son adorno; cada uno es un rato perdido que
ya le pasó a alguien:

  · el número se va de la app normal de WhatsApp — VA ARRIBA DEL TODO,
    porque leerlo en el paso 4 es tarde;
  · el token que Meta enseña de primeras dura 24 h;
  · sin la casilla `messages`, todo parece bien y no llega nada;
  · *Meta Verified* no es la verificación que levanta el tope de 250.

Si algún día se reordenan los pasos, esos avisos se mueven con el paso al
que pertenecen.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.web import activos

router = APIRouter(tags=["publico"])

# El WhatsApp y el correo de soporte de la plataforma. Van aquí, juntos y
# con nombre, y no repartidos por el HTML: el día que cambie el número hay
# un solo sitio que tocar, y se ve de un vistazo qué se está publicando.
SOPORTE_WHATSAPP = "573161775681"
SOPORTE_WHATSAPP_BONITO = "316 177 5681"
SOPORTE_CORREO = "atencion@nitro2tech.com"

# El mensaje con el que se abre el chat de soporte, ya empezado. Termina
# a propósito sin el número del paso: es el dato que necesitamos y así lo
# único que tiene que hacer es escribirlo.
_SALUDO = ("Hola%2C%20estoy%20conectando%20mi%20WhatsApp%20"
           "y%20me%20trab%C3%A9%20en%20el%20paso%20")


_ESTILO = """
/* Los mismos tokens que el panel (app/web/estaticos/panel.css): el
   morado de Nitro y sus neutros con sesgo violeta. Quien abre esto acaba
   de contratar el producto; la guía tiene que parecer parte de él. */
:root {
  --acc:#6D28D9; --accSoft:rgba(109,40,217,.07);
  --accLine:rgba(109,40,217,.22);
  --bg:#F6F5FA; --surf:#FFFFFF; --surf2:#F4F2FB;
  --line:#E7E4F1; --line2:#D5D0E6;
  --txt:#171326; --txt2:#5C5670; --txt3:#8B85A1;
  --ok:#0F7B4F;   --okSoft:#E7F5EE;   --okLine:rgba(15,123,79,.28);
  --warn:#95590A; --warnSoft:#FBF1E1; --warnLine:rgba(149,89,10,.3);
  --err:#B42318;  --errSoft:#FCEBEA;  --errLine:rgba(180,35,24,.3);
  --sh1:0 1px 2px rgba(23,19,38,.05);
  --ring:0 0 0 3px rgba(109,40,217,.18);
}
@media (prefers-color-scheme: dark) {
  :root {
    --acc:#A78BFA; --accSoft:rgba(167,139,250,.11);
    --accLine:rgba(167,139,250,.28);
    --bg:#0A0812; --surf:#161122; --surf2:#1F1932;
    --line:#272038; --line2:#3B3255;
    --txt:#EEEBF7; --txt2:#A8A1C0; --txt3:#7B7494;
    --ok:#4ADE80;   --okSoft:rgba(74,222,128,.1);   --okLine:rgba(74,222,128,.3);
    --warn:#FBBF24; --warnSoft:rgba(251,191,36,.1); --warnLine:rgba(251,191,36,.32);
    --err:#FCA5A5;  --errSoft:rgba(252,165,165,.09);--errLine:rgba(252,165,165,.3);
    --sh1:0 1px 2px rgba(0,0,0,.5);
    --ring:0 0 0 3px rgba(167,139,250,.24);
  }
}

* { box-sizing: border-box; }

body {
  margin:0; background:var(--bg); color:var(--txt);
  font-family:Manrope, -apple-system, 'Segoe UI', sans-serif;
  font-size:17px; line-height:1.65; -webkit-font-smoothing:antialiased;
}
.envoltura { max-width:47rem; margin:0 auto; padding:0 1.25rem 6rem; }

/* Barra de avance.

   Va FUERA de `.envoltura` para poder ocupar el ancho entero de la
   pantalla, así que NO puede llevar los márgenes negativos que usaría
   estando dentro: ahí sumarían 40px al 100% del cuerpo y sacarían scroll
   horizontal a la página entera. Se alinea con el texto por dentro, con
   `.avance-dentro`, que repite el ancho del contenedor. */
.avance { position:sticky; top:0; z-index:20;
  background:var(--bg); border-bottom:1px solid var(--line);
  padding:.7rem 1.25rem; margin-bottom:2.5rem; }
.avance-dentro { max-width:47rem; margin:0 auto;
  display:flex; align-items:center; gap:.9rem; }
.avance-texto { font-size:.78rem; font-weight:600; letter-spacing:.04em;
  text-transform:uppercase; color:var(--txt3); white-space:nowrap;
  font-variant-numeric:tabular-nums; }
.avance-riel { flex:1; min-width:0; height:6px; background:var(--line);
  border-radius:999px; overflow:hidden; }
.avance-barra { height:100%; width:0%; background:var(--acc);
  border-radius:999px; transition:width .35s ease; }

header { padding:3rem 0 0; }
.marca { font-family:'IBM Plex Mono', ui-monospace, monospace;
  font-size:.75rem; font-weight:600; letter-spacing:.16em;
  text-transform:uppercase; color:var(--acc); margin:0 0 1.1rem; }
h1 { font-size:clamp(2.1rem, 6vw, 3.1rem); font-weight:800; line-height:1.08;
  letter-spacing:-.025em; text-wrap:balance; margin:0 0 1.1rem; }
.entrada { font-size:1.14rem; color:var(--txt2); max-width:38rem;
  margin:0 0 1.6rem; }
.tiempo { display:inline-flex; align-items:center; gap:.55rem;
  font-size:.88rem; color:var(--txt2); background:var(--surf);
  border:1px solid var(--line); border-radius:999px; padding:.4rem .95rem;
  box-shadow:var(--sh1); }
.tiempo strong { color:var(--txt); font-weight:700; }

/* Avisos */
.aviso { border:1px solid var(--line); border-left:4px solid var(--txt3);
  background:var(--surf); border-radius:10px; padding:1.1rem 1.25rem;
  margin:1.5rem 0; }
.aviso h3 { margin:0 0 .5rem; font-size:.95rem; font-weight:700; }
.aviso p { margin:0 0 .6rem; font-size:.96rem; color:var(--txt2); }
.aviso p:last-child { margin-bottom:0; }
.aviso strong { color:var(--txt); }
.aviso--alto { border-left-color:var(--err); border-color:var(--errLine);
  background:var(--errSoft); }
.aviso--alto h3 { color:var(--err); }
.aviso--ojo { border-left-color:var(--warn); border-color:var(--warnLine);
  background:var(--warnSoft); }
.aviso--ojo h3 { color:var(--warn); }
.aviso--bien { border-left-color:var(--ok); border-color:var(--okLine);
  background:var(--okSoft); }
.aviso--bien h3 { color:var(--ok); }

h2.seccion { font-size:.8rem; font-weight:700; letter-spacing:.13em;
  text-transform:uppercase; color:var(--txt3); margin:3.5rem 0 1.25rem;
  padding-bottom:.6rem; border-bottom:1px solid var(--line); }

.paso { background:var(--surf); border:1px solid var(--line);
  border-radius:16px; padding:1.5rem 1.6rem; margin-bottom:1.1rem;
  box-shadow:var(--sh1); transition:border-color .2s ease, opacity .2s ease; }
.paso:has(.casilla:checked) { border-color:var(--okLine); opacity:.72; }
.paso-cabeza { display:flex; align-items:flex-start; gap:1rem;
  margin-bottom:.9rem; }
.numero { flex:none; width:2.1rem; height:2.1rem; display:grid;
  place-items:center; border-radius:50%; background:var(--accSoft);
  border:1px solid var(--accLine); color:var(--acc);
  font-family:'IBM Plex Mono', ui-monospace, monospace;
  font-size:.88rem; font-weight:600; font-variant-numeric:tabular-nums; }
.paso:has(.casilla:checked) .numero { background:var(--okSoft);
  border-color:var(--okLine); color:var(--ok); }
.paso-titulo { flex:1; min-width:0; margin:0; padding-top:.18rem;
  font-size:1.2rem; font-weight:700; letter-spacing:-.012em;
  text-wrap:balance; }
.paso-cuerpo { padding-left:3.1rem; }
.paso-cuerpo > p { margin:0 0 .85rem; color:var(--txt2); }
.paso-cuerpo > p:last-child { margin-bottom:0; }
.paso-cuerpo strong { color:var(--txt); font-weight:600; }

ol.pasitos, ul.lista { margin:0 0 .95rem; padding-left:1.25rem;
  color:var(--txt2); }
ol.pasitos li, ul.lista li { margin-bottom:.45rem; }
ol.pasitos li::marker { color:var(--txt3); font-weight:600; }
ul.lista li::marker { color:var(--acc); }

/* Lo que se lee LITERAL en la pantalla de Meta. El mono tiene trabajo:
   separa "esto es un nombre que vas a ver" de la prosa que lo rodea. */
.ui { font-family:'IBM Plex Mono', ui-monospace, monospace;
  font-size:.87em; font-weight:500; background:var(--surf2);
  border:1px solid var(--line); border-radius:5px; padding:.09em .38em;
  color:var(--txt); white-space:nowrap; }
.ruta { font-family:'IBM Plex Mono', ui-monospace, monospace;
  font-size:.84rem; background:var(--surf2); border:1px solid var(--line);
  border-radius:10px; padding:.7rem .9rem; margin:0 0 .95rem;
  color:var(--txt2); overflow-x:auto; white-space:nowrap; }
.ruta b { color:var(--acc); font-weight:600; }

.hecho { display:flex; align-items:center; gap:.6rem;
  margin:1.15rem 0 0 3.1rem; padding-top:1rem;
  border-top:1px dashed var(--line); cursor:pointer;
  font-size:.9rem; font-weight:600; color:var(--txt2); user-select:none; }
.casilla { appearance:none; -webkit-appearance:none; flex:none;
  width:1.25rem; height:1.25rem; border:2px solid var(--line2);
  border-radius:6px; background:var(--surf); cursor:pointer;
  display:grid; place-items:center;
  transition:background .15s ease, border-color .15s ease; }
.casilla:checked { background:var(--ok); border-color:var(--ok); }
.casilla:checked::after { content:""; width:.34rem; height:.62rem;
  border:solid var(--surf); border-width:0 2.5px 2.5px 0;
  transform:rotate(43deg) translateY(-1px); }
.casilla:focus-visible { outline:none; box-shadow:var(--ring); }
.hecho:has(.casilla:checked) { color:var(--ok); }

.datos { display:grid; gap:.9rem; margin:0 0 .95rem; }
.dato label { display:block; font-size:.78rem; font-weight:700;
  letter-spacing:.05em; text-transform:uppercase; color:var(--txt3);
  margin-bottom:.35rem; }
.dato input { width:100%;
  font-family:'IBM Plex Mono', ui-monospace, monospace; font-size:.85rem;
  padding:.65rem .8rem; background:var(--surf2);
  border:1px solid var(--line2); border-radius:10px; color:var(--txt); }
.dato input::placeholder { color:var(--txt3); }
.dato input:focus-visible { outline:none; border-color:var(--acc);
  box-shadow:var(--ring); }

.cierre { background:var(--surf); border:1px solid var(--accLine);
  border-radius:16px; padding:1.8rem; margin-top:1.1rem; }
.cierre h3 { margin:0 0 .4rem; font-size:1.28rem; font-weight:800;
  letter-spacing:-.015em; }
.cierre > p { margin:0 0 1.2rem; color:var(--txt2); }
.envio { display:grid; gap:.55rem; }
.envio-fila { display:flex; align-items:baseline; gap:.8rem;
  padding:.7rem .9rem; background:var(--surf2);
  border:1px solid var(--line); border-radius:10px; }
.envio-fila .que { font-family:'IBM Plex Mono', ui-monospace, monospace;
  font-size:.85rem; font-weight:600; color:var(--acc); flex:none; }
.envio-fila .donde { font-size:.88rem; color:var(--txt2); }
a.contacto { text-decoration:none;
  transition:border-color .15s ease, background .15s ease; }
a.contacto:hover, a.contacto:focus-visible { border-color:var(--acc);
  background:var(--accSoft); }
a.contacto:focus-visible { outline:none; box-shadow:var(--ring); }

footer { margin-top:3.5rem; padding-top:1.5rem;
  border-top:1px solid var(--line); font-size:.87rem; color:var(--txt3); }
footer a { color:var(--acc); }

@media (prefers-reduced-motion: reduce) {
  .avance-barra, .paso, .casilla, a.contacto { transition:none; }
}
@media (max-width: 560px) {
  body { font-size:16px; }
  .paso { padding:1.25rem 1.1rem; }
  .paso-cuerpo, .hecho { padding-left:0; margin-left:0; }
  .paso-cabeza { gap:.75rem; }
}
"""


_GUION = """
(function () {
  "use strict";
  var LLAVE = "nitro-conexion-whatsapp";
  var casillas = Array.prototype.slice.call(document.querySelectorAll(".casilla"));
  var campos = [document.getElementById("urlNitro"),
                document.getElementById("codigoNitro")];
  var barra = document.getElementById("avanceBarra");
  var texto = document.getElementById("avanceTexto");

  // Todo acceso a localStorage va envuelto: en una ventana privada o con
  // las cookies bloqueadas, el acceso MISMO lanza. La guía tiene que
  // pintarse igual sin nada guardado — y quien la abre está en mitad de
  // un trámite, no en condiciones de depurar por qué no carga.
  function leer() {
    try { return JSON.parse(localStorage.getItem(LLAVE) || "{}") || {}; }
    catch (e) { return {}; }
  }
  function guardar(estado) {
    try { localStorage.setItem(LLAVE, JSON.stringify(estado)); }
    catch (e) { /* sin guardado, la guía funciona igual */ }
  }
  function pintarAvance() {
    var hechos = casillas.filter(function (c) { return c.checked; }).length;
    var total = casillas.length;
    barra.style.width = (total ? (hechos / total) * 100 : 0) + "%";
    texto.textContent = hechos === total ? "listo, los " + total
                                         : hechos + " de " + total;
  }

  var estado = leer();
  casillas.forEach(function (casilla) {
    var id = casilla.getAttribute("data-paso");
    if (estado["paso" + id]) casilla.checked = true;
    casilla.addEventListener("change", function () {
      var actual = leer();
      actual["paso" + id] = casilla.checked;
      guardar(actual);
      pintarAvance();
    });
  });
  campos.forEach(function (campo) {
    if (!campo) return;
    if (estado[campo.id]) campo.value = estado[campo.id];
    campo.addEventListener("input", function () {
      var actual = leer();
      actual[campo.id] = campo.value;
      guardar(actual);
    });
  });
  pintarAvance();
})();
"""


def _cuerpo() -> str:
    """Los ocho pasos. Ver el docstring del módulo sobre los avisos."""
    return f"""
<div class="avance" role="status" aria-live="polite">
  <div class="avance-dentro">
    <span class="avance-texto" id="avanceTexto">0 de 9</span>
    <div class="avance-riel"><div class="avance-barra" id="avanceBarra"></div></div>
  </div>
</div>

<div class="envoltura">

<header>
  <p class="marca">Nitro 2Tech</p>
  <h1>Conecta tu WhatsApp</h1>
  <p class="entrada">
    Para que tu bot pueda responder, WhatsApp tiene que darle permiso.
    Ese permiso se pide una sola vez, desde tu propia cuenta de Meta, y
    aquí está el camino completo. Al final nos envías cuatro datos y
    nosotros hacemos el resto.
  </p>
  <span class="tiempo">Toma unos <strong>45 minutos</strong> · se puede hacer por partes</span>
</header>

<div class="aviso aviso--alto">
  <h3>Lee esto antes de empezar</h3>
  <p>
    El número que conectes <strong>dejará de funcionar en la aplicación
    normal de WhatsApp</strong>. No podrás usarlo desde tu teléfono como
    hasta ahora: a partir de ese momento las conversaciones se atienden
    desde el panel que te dimos.
  </p>
  <p>
    Por eso <strong>no uses tu número personal</strong>. Usa uno nuevo, o
    uno que tu negocio ya tenga apartado para atención al cliente. Si
    dudas, escríbenos antes de llegar al paso 4 — deshacerlo después es
    engorroso.
  </p>
</div>

<h2 class="seccion">Lo que necesitas a mano</h2>

<div class="paso">
  <div class="paso-cuerpo" style="padding-left:0">
    <ul class="lista">
      <li>Una <strong>cuenta de Facebook</strong> tuya. No hace falta tener página del negocio.</li>
      <li>El <strong>número de teléfono</strong> que va a atender, con acceso para recibir un SMS o una llamada.</li>
      <li>Los datos de tu empresa: nombre legal, NIT y dirección, tal como aparecen en tu Cámara de Comercio.</li>
      <li>Los <strong>dos datos que te dimos</strong> nosotros: una dirección web y un código. Los pegas en el paso 7.</li>
    </ul>
  </div>
</div>

<h2 class="seccion">El camino, paso a paso</h2>

<div class="paso">
  <div class="paso-cabeza">
    <span class="numero">1</span>
    <h3 class="paso-titulo">Crea el portafolio de tu negocio</h3>
  </div>
  <div class="paso-cuerpo">
    <p>Es la carpeta donde Meta guarda todo lo de tu empresa. Si ya
       manejas anuncios de Facebook, probablemente ya tienes uno y
       puedes saltarte este paso.</p>
    <div class="ruta">Entra a <b>business.facebook.com</b></div>
    <ol class="pasitos">
      <li>Inicia sesión con tu cuenta de Facebook.</li>
      <li>Si te pide crear un portafolio, ponle el <strong>nombre legal
          de tu empresa</strong>, no el comercial. Meta va a comparar ese
          nombre con tus documentos más adelante.</li>
      <li>Escribe tu correo de trabajo cuando lo pida.</li>
    </ol>
  </div>
  <label class="hecho"><input type="checkbox" class="casilla" data-paso="1"> Hecho</label>
</div>

<div class="paso">
  <div class="paso-cabeza">
    <span class="numero">2</span>
    <h3 class="paso-titulo">Crea la aplicación</h3>
  </div>
  <div class="paso-cuerpo">
    <p>Es el permiso en sí: lo que le va a dar acceso al bot. Suena
       técnico y son cuatro clics.</p>
    <div class="ruta">Entra a <b>developers.facebook.com</b> → <b>Mis aplicaciones</b> → <b>Crear aplicación</b></div>
    <ol class="pasitos">
      <li>Cuando pregunte qué quieres hacer, elige la opción de
          <span class="ui">Empresa</span> o <span class="ui">Otro</span>.</li>
      <li>De tipo, elige <span class="ui">Empresa</span>.</li>
      <li>Ponle el nombre de tu negocio y <strong>conéctala al portafolio
          del paso 1</strong>. Ese enlace es importante: es lo que le dice
          a Meta que la aplicación y el número son del mismo dueño.</li>
    </ol>
  </div>
  <label class="hecho"><input type="checkbox" class="casilla" data-paso="2"> Hecho</label>
</div>

<div class="paso">
  <div class="paso-cabeza">
    <span class="numero">3</span>
    <h3 class="paso-titulo">Añade WhatsApp a la aplicación</h3>
  </div>
  <div class="paso-cuerpo">
    <p>Ya dentro de tu aplicación recién creada, Meta te muestra una
       lista de productos que puedes agregarle.</p>
    <ol class="pasitos">
      <li>Busca <span class="ui">WhatsApp</span> en la lista y pulsa
          <span class="ui">Configurar</span>.</li>
      <li>Meta te va a crear una cuenta de WhatsApp Business
          automáticamente. Déjala como viene.</li>
    </ol>
    <div class="aviso aviso--ojo">
      <h3>El número de prueba no sirve</h3>
      <p>Meta te regala un número de prueba y es tentador usarlo. Solo
         puede escribirle a cinco contactos que registres a mano, así que
         parecerá que todo funciona y tus clientes no recibirán nada. El
         número de verdad se conecta en el paso siguiente.</p>
    </div>
  </div>
  <label class="hecho"><input type="checkbox" class="casilla" data-paso="3"> Hecho</label>
</div>

<div class="paso">
  <div class="paso-cabeza">
    <span class="numero">4</span>
    <h3 class="paso-titulo">Conecta tu número</h3>
  </div>
  <div class="paso-cuerpo">
    <p>Este es el paso del aviso de arriba. <strong>El número que pongas
       aquí sale de la aplicación normal de WhatsApp.</strong></p>
    <div class="ruta">En tu aplicación → <b>WhatsApp</b> → <b>Configuración de la API</b></div>
    <ol class="pasitos">
      <li>Pulsa <span class="ui">Agregar número de teléfono</span>.</li>
      <li>Escribe el nombre con el que quieres que te vean tus clientes,
          la categoría de tu negocio y una descripción corta.</li>
      <li>Escribe el número y elige si quieres el código por
          <strong>SMS o por llamada</strong>.</li>
      <li>Escribe el código que te llegue.</li>
    </ol>
    <p>Cuando termine, verás tu número en la lista con un identificador
       largo debajo. <strong>Ese identificador nos lo tienes que
       enviar</strong> — es el primero de los cuatro datos del final.</p>
  </div>
  <label class="hecho"><input type="checkbox" class="casilla" data-paso="4"> Hecho</label>
</div>

<div class="paso">
  <div class="paso-cabeza">
    <span class="numero">5</span>
    <h3 class="paso-titulo">Configura el método de pago</h3>
  </div>
  <div class="paso-cuerpo">
    <p>WhatsApp <strong>cobra los mensajes que tu negocio envía</strong>.
       Son céntimos por conversación, y <strong>le pagas a Meta
       directamente con tu tarjeta</strong>: nosotros no te cobramos los
       mensajes ni los adelantamos.</p>
    <div class="ruta"><b>business.facebook.com</b> → <b>Configuración del negocio</b> → <b>Facturación y pagos</b></div>
    <ol class="pasitos">
      <li>Elige tu cuenta de WhatsApp.</li>
      <li>Configura la <strong>moneda</strong> y añade una
          <strong>tarjeta</strong>.</li>
    </ol>

    <div class="aviso aviso--alto">
      <h3>Desde el 1 de octubre de 2026 esto deja de ser opcional</h3>
      <p>
        Hasta esa fecha, responderle a alguien que te acaba de escribir es
        gratis, así que tu bot funciona sin tarjeta. A partir de ahí Meta
        cobra también esos mensajes — y <strong>sin forma de pago el bot
        deja de responder</strong>. No es que se degrade: se calla.
      </p>
      <p>
        Déjalo puesto ahora y te olvidas. Configurarlo cuesta dos minutos;
        descubrirlo el día que tus clientes dejen de recibir respuesta,
        bastante más.
      </p>
    </div>
  </div>
  <label class="hecho"><input type="checkbox" class="casilla" data-paso="5"> Hecho</label>
</div>
<div class="paso">
  <div class="paso-cabeza">
    <span class="numero">6</span>
    <h3 class="paso-titulo">Genera la llave permanente</h3>
  </div>
  <div class="paso-cuerpo">
    <p>Es el paso donde se atasca todo el mundo, así que vale la pena
       leerlo entero antes de hacerlo.</p>

    <div class="aviso aviso--alto">
      <h3>La llave que Meta te muestra de primeras dura 24 horas</h3>
      <p>
        En la pantalla de configuración hay un botón que genera una llave
        de inmediato. <strong>Esa no sirve.</strong> Caduca al día
        siguiente y tu bot se queda mudo sin avisar, normalmente un
        sábado.
      </p>
      <p>
        La que necesitas se genera desde <strong>Usuarios del sistema</strong>,
        que está en otro menú. Es lo que se hace abajo.
      </p>
    </div>

    <div class="ruta"><b>business.facebook.com</b> → <b>Configuración del negocio</b> → <b>Usuarios</b> → <b>Usuarios del sistema</b></div>
    <ol class="pasitos">
      <li>Pulsa <span class="ui">Agregar</span>. Ponle un nombre
          cualquiera que reconozcas, por ejemplo <span class="ui">bot</span>,
          y dale el rol de <span class="ui">Administrador</span>.</li>
      <li>Con ese usuario seleccionado, pulsa
          <span class="ui">Agregar activos</span>. Elige
          <span class="ui">Aplicaciones</span>, marca la aplicación del
          paso 2 y dale <strong>control total</strong>.</li>
      <li>Repite con <span class="ui">Cuentas de WhatsApp</span>: marca la
          tuya y dale control total también.</li>
      <li>Ahora sí, pulsa <span class="ui">Generar nuevo token</span>.</li>
      <li>Elige tu aplicación y, <strong>donde dice caducidad, elige
          que nunca caduque</strong>.</li>
      <li>En la lista de permisos, marca estos dos:
          <span class="ui">whatsapp_business_messaging</span> y
          <span class="ui">whatsapp_business_management</span>.</li>
      <li>Pulsa generar y <strong>copia la llave que sale</strong>.</li>
    </ol>

    <div class="aviso aviso--ojo">
      <h3>Cópiala ahora, no se vuelve a mostrar</h3>
      <p>Meta enseña esa llave una sola vez. Si cierras la ventana sin
         copiarla, hay que generar otra. Pégala en un sitio seguro
         mientras terminas los pasos que faltan.</p>
    </div>
  </div>
  <label class="hecho"><input type="checkbox" class="casilla" data-paso="6"> Hecho</label>
</div>

<div class="paso">
  <div class="paso-cabeza">
    <span class="numero">7</span>
    <h3 class="paso-titulo">Dile a Meta dónde entregar tus mensajes</h3>
  </div>
  <div class="paso-cuerpo">
    <p>Aquí es donde usas los dos datos que te dimos nosotros. Le dicen a
       Meta a qué dirección mandar los mensajes que te escriban.</p>

    <div class="datos">
      <div class="dato">
        <label for="urlNitro">Dirección que te dio Nitro 2Tech</label>
        <input id="urlNitro" type="text" spellcheck="false"
               placeholder="https://bot.nitro2tech.com/webhook/…">
      </div>
      <div class="dato">
        <label for="codigoNitro">Código de verificación que te dio Nitro 2Tech</label>
        <input id="codigoNitro" type="text" spellcheck="false"
               placeholder="pégalo aquí para tenerlo a mano">
      </div>
    </div>
    <p style="font-size:.86rem;color:var(--txt3)">
      Puedes pegarlos arriba para tenerlos a la vista mientras haces el
      paso. Se guardan solo en este navegador.
    </p>

    <div class="ruta">En tu aplicación → <b>WhatsApp</b> → <b>Configuración</b> → <b>Webhooks</b> → <b>Editar</b></div>
    <ol class="pasitos">
      <li>En <span class="ui">URL de devolución de llamada</span>, pega
          la dirección.</li>
      <li>En <span class="ui">Token de verificación</span>, pega el
          código.</li>
      <li>Pulsa <span class="ui">Verificar y guardar</span>.</li>
      <li>Vuelve a la lista y pulsa <span class="ui">Administrar</span>.
          Busca la fila que dice <span class="ui">messages</span> y
          <strong>marca su casilla de suscripción</strong>.</li>
    </ol>

    <div class="aviso aviso--ojo">
      <h3>No te saltes la última casilla</h3>
      <p>Si guardas la dirección pero no marcas
         <span class="ui">messages</span>, todo se ve correctamente
         configurado y <strong>no te llega ni un mensaje</strong>. Es el
         fallo que más tiempo hace perder, precisamente porque no se ve.</p>
    </div>
  </div>
  <label class="hecho"><input type="checkbox" class="casilla" data-paso="7"> Hecho</label>
</div>

<div class="paso">
  <div class="paso-cabeza">
    <span class="numero">8</span>
    <h3 class="paso-titulo">Envíanos los cuatro datos</h3>
  </div>
  <div class="paso-cuerpo">
    <p>Con esto ya podemos encender tu bot. Los cuatro salen de las
       pantallas por las que acabas de pasar.</p>

    <div class="aviso aviso--ojo">
      <h3>Mándalos por un canal privado</h3>
      <p>Son las llaves de tu WhatsApp: quien las tenga puede escribirles
         a tus clientes en tu nombre. Nada de grupos ni correos
         compartidos.</p>
    </div>
  </div>
  <label class="hecho"><input type="checkbox" class="casilla" data-paso="8"> Hecho</label>
</div>

<div class="paso">
  <div class="paso-cabeza">
    <span class="numero">9</span>
    <h3 class="paso-titulo">Verifica tu negocio</h3>
  </div>
  <div class="paso-cuerpo">
    <p>Tu bot ya funciona sin esto. Pero <strong>hasta que Meta verifique
       tu empresa solo puedes atender a 250 personas distintas cada 24
       horas</strong>, y al pasarte el bot deja de responder hasta el día
       siguiente.</p>
    <div class="ruta"><b>business.facebook.com</b> → <b>Configuración del negocio</b> → <b>Centro de seguridad</b></div>
    <ol class="pasitos">
      <li>Pulsa <span class="ui">Iniciar verificación</span>.</li>
      <li>Escribe los datos de tu empresa <strong>exactamente como
          aparecen en tu Cámara de Comercio</strong>: una tilde de
          diferencia es motivo de rechazo.</li>
      <li>Sube el certificado de Cámara de Comercio y, si lo pide, un
          recibo de servicios a nombre de la empresa.</li>
    </ol>
    <p>Meta suele tardar de unos días a un par de semanas. Es gratis.</p>

    <div class="aviso aviso--bien">
      <h3>No confundas esto con Meta Verified</h3>
      <p>Meta te va a ofrecer una suscripción de pago llamada
         <strong>Meta Verified</strong>, con distintivo azul.
         <strong>No la necesitas</strong> y no sirve para esto. La que
         levanta el límite es la verificación de negocio, que es gratuita
         y se hace con documentos.</p>
    </div>
  </div>
  <label class="hecho"><input type="checkbox" class="casilla" data-paso="9"> Hecho</label>
</div>

<h2 class="seccion">Lo que nos envías</h2>

<div class="cierre">
  <h3>Los cuatro datos</h3>
  <p>Todos salen de las pantallas de los pasos 2, 4 y 6.</p>
  <div class="envio">
    <div class="envio-fila">
      <span class="que">Identificador del número</span>
      <span class="donde">El número largo que quedó debajo de tu número, en el paso 4</span>
    </div>
    <div class="envio-fila">
      <span class="que">Llave permanente</span>
      <span class="donde">La que generaste con el usuario del sistema, en el paso 6</span>
    </div>
    <div class="envio-fila">
      <span class="que">Identificador de la app</span>
      <span class="donde">En tu aplicación → Configuración → Básica, arriba del todo</span>
    </div>
    <div class="envio-fila">
      <span class="que">Clave secreta de la app</span>
      <span class="donde">En la misma pantalla, pulsando «Mostrar» al lado de la clave</span>
    </div>
  </div>
</div>

<div class="aviso aviso--bien">
  <h3>Y ya está</h3>
  <p>
    En cuanto nos lleguen, comprobamos que todo responda y te avisamos.
    Si algo quedó mal copiado lo vemos al instante y te decimos qué
    repetir — no hace falta que rehagas nada por tu cuenta.
  </p>
</div>

<h2 class="seccion">Si te trabas</h2>

<div class="cierre">
  <h3>Escríbenos</h3>
  <p>
    Dinos el <strong>número del paso</strong> y mándanos una captura de lo
    que ves. Es mucho más rápido que intentar describirlo, y casi siempre
    lo resolvemos en el momento.
  </p>
  <div class="envio">
    <a class="envio-fila contacto"
       href="https://wa.me/{SOPORTE_WHATSAPP}?text={_SALUDO}">
      <span class="que">WhatsApp</span>
      <span class="donde">{SOPORTE_WHATSAPP_BONITO} — lo más rápido</span>
    </a>
    <a class="envio-fila contacto" href="mailto:{SOPORTE_CORREO}">
      <span class="que">Correo</span>
      <span class="donde">{SOPORTE_CORREO}</span>
    </a>
  </div>
</div>

<footer>
  <p>
    Las llaves de los pasos 6 y 8 son las de tu WhatsApp. Mándalas por
    mensaje directo, nunca en un grupo.
  </p>
  <p>Nitro 2Tech · <a href="https://nitro2tech.com">nitro2tech.com</a></p>
</footer>

</div>"""


@router.get("/conectar", response_class=HTMLResponse)
def conectar():
    """
    La guía de conexión. Pública y sin sesión: la abre alguien que
    todavía no tiene panel.

    `noindex` porque no es una página de captación — es una instrucción
    para un cliente concreto, y no tiene sentido que salga en Google
    descolgada de quien se la mandó.
    """
    return HTMLResponse(f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Conecta tu WhatsApp · Nitro 2Tech</title>
<link rel="stylesheet" href="{activos.url('fuentes.css')}">
<style>{_ESTILO}</style>
</head>
<body>
{_cuerpo()}
<script>{_GUION}</script>
</body>
</html>""")
