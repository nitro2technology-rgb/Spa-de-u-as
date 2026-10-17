# Cutí: especificaciones de uso y técnicas

> **Este repositorio (`Spa-de-u-as`) ya no es el código de Cutí.** Era una copia del
> software de barberías sacada el 16-oct-2026 para explorar la idea. Cutí se hizo
> como una **marca más del mismo producto**, en el repositorio vivo
> **`nitro2technology-rgb/Bot-whatsapp-pro`**, y desde allí se despliega. **No
> trabajes aquí:** lo que cambies no llega a producción. Conviene archivar este
> repositorio (GitHub → Settings → Archive). Este archivo es solo la ficha de lo que
> Cutí **es y hace**.

Última actualización: **19-oct-2026**. Lo que sigue describe lo que **existe**.

---

# PARTE 1 · ESPECIFICACIONES DE USO

## Qué es

**Cutí** es el software de gestión para **spas de uñas**: agenda, reservas en línea,
caja, pagos a manicuristas, gastos, clientas, fidelización y chatbot de WhatsApp. Es la
**misma plataforma** que **Degradé** (barberías): el mismo código, la misma base de datos
y el mismo despliegue. Cambia lo que se ve: nombre, paleta, tipografía, palabras, iconos
y la página de reservas.

| | Degradé | Cutí |
|---|---|---|
| Para | Barberías | Spas de uñas |
| Dirección | `degrade.nitro2tech.com` | `cuti.nitro2tech.com` |
| Sección en el superadmin | Barberías | Spas de uñas |
| Paleta | Violeta y lila sobre noche | Ciruela y rosados pastel |
| Títulos | Unbounded | Fraunces (serif suave) |
| Profesional | barbero | **manicurista** |
| Funciones de spa (abono, diseños, foto de referencia) | no | **sí** |

**Planes y precios:** los mismos que Degradé (49.500 · 130.000 · 330.000 al mes); en
Cutí se leen «Manicurista individual», «Administrador de spas» y «Spa ilimitado». En el
plan individual **la dueña es la manicurista**: no hay «Usuarios» y al entrar elige entre
el panel de administrador y «Mi día de manicurista».

## Cómo se da de alta un spa

1. `/superadmin/unas` → «Nuevo spa de uñas», o la prueba gratis de 7 días en
   `cuti.nitro2tech.com/prueba`.
2. La dueña recibe un correo de «Cutí» con su usuario y contraseña temporal.
3. **La primera vez que entra** pasa por un **asistente** (bienvenida, usuario, logo y
   portada, descripción y galería, servicios —mínimo 3—, sede, equipo) y luego por un
   **recorrido de burbujas** por el panel. Se puede repetir desde Configuración → «Ver la
   guía otra vez».
4. Para el chatbot, cada spa trae su propia App de Meta, como cualquier cliente.

## La reserva de la clienta (página pública `/reservar/{spa}`)

Son **4 pasos iguales en Cutí y en Degradé**, cada uno con su botón **Siguiente**:

1. **Servicio.** Antes de elegirlo ve los **3 favoritos** del spa y «Ver más diseños».
   Con un servicio elegido, Cutí pregunta **«¿Ya sabes qué diseño quieres?»**:
   - **Ver los diseños de ese servicio** → «Quiero este» ya trae el servicio y el precio.
     Si el diseño tiene un extra opcional («Con pepitas +$10.000») se agrega o se quita
     con un toque y el **total** se actualiza.
   - **Tengo mi propia idea** → ve de inmediato la **descripción y las condiciones**
     (las escribe el spa) y sube **la foto de su diseño**. El precio es «desde» y el spa
     lo confirma.
   - **Lo decido en la cita.**
2. **Con quién** (manicurista, o «la que esté libre»).
3. **Fecha y hora**, en la misma pantalla.
4. **Datos** (nombre, celular, correo opcional, nota y foto de referencia opcional).

Si el spa tiene varias sedes, primero se pregunta la sede.

**Código de reserva.** Al terminar, la clienta recibe un código único (8 letras y
números, p. ej. `RSRD-HAFG`) con el aviso «guárdalo en tu celular o toma un pantallazo».
También le llega por correo (si lo dejó) y por WhatsApp si reservó con el bot. Con él, en
**«¿Ya reservaste? Consulta o cambia tu cita»** (al pie de toda la página de reservas):
- ve su cita (sin celular ni correo en pantalla);
- **cambia la fecha u hora** (con la misma manicurista);
- **la cancela**, con confirmación.
Con **menos de 2 horas** por delante ya no se cambia ni se cancela desde ahí: tiene que
escribirle al spa. Si ya había abonado, la página le avisa que el spa decide qué pasa con
ese dinero.

## Funciones propias de un spa (solo Cutí)

**Mi página** (la dueña):
- **Galería de diseños** (hasta 24): foto, nombre, **servicio al que pertenece**
  (obligatorio: así la clienta ve el precio), descripción corta, **extra opcional**
  (nombre y valor fijo) y **estrella de favorito** (máximo 3; sin ninguno salen los más
  pedidos). Cada diseño se edita después.
- **Diseños propios de tus clientas:** los dos textos que lee quien trae su idea (qué es y
  condiciones). Vacíos, sale un texto de siempre.
- **Abono para reservar:** monto fijo o porcentaje, a dónde se abona, y un plazo en horas
  (pasado el plazo sin abono, la hora se libera sola; 0 = sin plazo). **No hay pasarela de
  pago:** la clienta abona por Nequi o transferencia y manda el comprobante.

**Servicios y precios:** cada servicio puede tener una **descripción corta** (la clienta la
lee al elegirlo).

**En la cita (agenda):** diseño pedido, foto de referencia (privada), nota de la clienta,
**código de reserva**, y los estados:
- **Abono pendiente / recibido** → la dueña lo marca «recibido» cuando le llega.
- **Precio por confirmar** (diseño propio) → ve la foto, le escribe por WhatsApp desde el
  botón y escribe cuánto suma el diseño; se suma al cobrar.

**Al cobrar:** el abono recibido se **descuenta** de lo que falta (queda como un pago por
transferencia: el ingreso no cambia y el arqueo de efectivo tampoco) y el extra del diseño
entra como una línea más del servicio (con su comisión).

**Manicurista («Mi día»):** ve el diseño, la nota, la foto de referencia y si falta el
abono, de la siguiente cita.

## Otras cosas de la plataforma

- **Correos:** los de un spa llegan firmados por «Cutí».
- **Consola (`/superadmin`):** dos secciones, **Barberías** y **Spas de uñas**. Cada una
  lista y da de alta solo lo suyo; Cobros, Planes y Consumo son de toda la plataforma. La
  marca de un negocio se cambia en su ficha.
- **Página de reservas:** otro diseño (rosa pastel, media luna en vez del poste, frasco de
  esmalte en vez de tijeras), con tres temas: Pétalo, Claro y Ciruela.
- **Sitio nitro2tech.com:** landing en `/servicios/software/cuti` (repositorio `Nitro2Tech`).
- **Dominio de Cutí:** variable `CUTI_URL` (`https://cuti.nitro2tech.com`) en Render + el
  dominio agregado al servicio + un CNAME en el DNS. Sin ella todo funciona en la
  dirección de Degradé.
- **El logo:** una **uña almendra** en degradé rosa, con su lúnula y un brillo, sobre una
  ficha ciruela (`instrucciones/LOGO_CUTI.md` de `Bot-whatsapp-pro`).

---

# PARTE 2 · ESPECIFICACIONES TÉCNICAS

## Arquitectura

- **Un solo despliegue** (Render, FastAPI, **un solo proceso** de uvicorn) atiende a todos
  los negocios. Base **PostgreSQL** con **Row-Level Security**: cada tabla del negocio lleva
  `client_id`, el ORM filtra por el inquilino en curso y la base lo vuelve a exigir.
- **La marca es del cliente:** `clients.marca` (`"degrade"` | `"cuti"`). Qué cambia por marca
  está en `app/barberia/marca.py` (nombre, catálogo de servicios, vocabulario,
  `funciones_de_spa`) y en el bloque `html[data-marca="cuti"]` de `app/web/estaticos/barberia.css`.
- **Vocabulario:** el panel está escrito con palabras de barbería y se traduce al entregarlo
  (`marca.localizar`: «barbero» → «manicurista», «barbería» → «spa», «corte» → «servicio»),
  con concordancia. Degradé pasa intacto. Vale para correos, avisos y el bot.
- **Las funciones de spa** (`app/barberia/spa.py`) solo existen con
  `marca.actual().funciones_de_spa`; en Degradé no hay pestaña, campos ni rutas que respondan.

## Módulos

| Archivo | Qué hace |
|---|---|
| `portal.py` | Reserva pública en 4 pasos (`pantalla`), confirmación, subida de la foto del diseño propio |
| `portal_cita.py` | «Mi cita»: consultar, cambiar y cancelar con el código |
| `agenda.py` | Citas: `reservar` (con candado), `reprogramar`, `cancelar`, `codigo_nuevo`, `cita_por_codigo` |
| `spa.py` | Abono, diseños, favoritos, recargo, diseño propio, foto pendiente, precio por confirmar |
| `pantallas_spa.py` · `rutas_spa.py` | Pantallas y rutas del panel y de la página pública de Cutí |
| `operacion.py` (`cobrar`) | Caja: descuenta el abono y suma el extra del diseño como una línea de servicio |
| `guia.py` · `pantallas_guia.py` · `rutas_guia.py` | Asistente y recorrido de la primera vez |
| `marca.py` | Marcas, catálogo y vocabulario |

## Datos (tablas y columnas de Cutí)

- `barb_perfil`: `abono_activo/tipo/valor/instrucciones/horas`, `propio_descripcion`, `propio_condiciones`.
- `barb_servicios.descripcion` (una línea).
- `barb_disenos` (RLS): título, foto (`contenido`), `miniatura` 480 px, `servicio_id`, `descripcion`,
  `recargo`, `recargo_nombre`, `favorito`.
- `barb_referencias` (RLS): foto de referencia **privada**; `cita_id` (NULL mientras espera su
  reserva) y `token`. Las que no llegan a reserva se borran a las 24 h.
- `barb_citas`: `abono_monto/estado/aplicado/hasta`, `nota_cliente`, `diseno_id/nombre`,
  `extra_monto/extra_nombre`, `precio_por_confirmar`, **`codigo`** (único por negocio).
- `barb_personal.guia/guia_paso`: estado de la guía por persona.
- Migraciones (en orden): `d7f9b1c3e456` (guía) → `e8a0c2d4f567` (abono, diseños, referencias) →
  `f1b3d5e7a890` (descripciones, extra, favoritos) → `a2c4e6f8b013` (código de reserva, textos del
  diseño propio, foto pendiente).

## Reglas que no se pueden romper

- **La foto de referencia es PRIVADA.** Solo sale por `/b/spa/referencia/{cita}.jpg`, con sesión
  del panel y permiso sobre esa cita. La foto pendiente (sin cita) no sale por ninguna ruta.
- **El código de reserva es la única llave de «Mi cita».** La página muestra lo mínimo (nunca
  celular ni correo), tiene freno por IP y no distingue «no existe» de «es de otro negocio».
- **La reserva son 4 pasos iguales para todas las marcas**; Cutí agrega subpasos dentro del
  primero, no pasos propios.
- **El extra del diseño sale de la cita**, no del formulario de cobro.
- Una tabla nueva con `client_id` entra en `MODELOS_DEL_INQUILINO` **y** lleva su política RLS.

## Rutas principales

| Ruta | Para qué |
|---|---|
| `GET /reservar/{slug}` | Los 4 pasos (`?servicio=&barbero=&dia=&inicio=` y, en Cutí, `&diseno=&extra=&idea=&ref=`) |
| `POST /reservar/{slug}` | Reserva |
| `POST /reservar/{slug}/propio` | Sube la foto del diseño propio (antes de elegir con quién) |
| `GET /reservar/{slug}/cita` · `POST …/cita/mover` · `POST …/cita/cancelar` | Mi cita |
| `POST /b/pagina/disenos…` · `/b/pagina/abono` · `/b/pagina/propio` | Mi página (la dueña) |
| `POST /b/agenda/cita/{id}/abono` · `/precio` | Abono y precio de una cita |
| `GET /b/spa/diseno/{id}[-m].jpg` · `/b/spa/referencia/{cita}.jpg` | Fotos para el panel |

## Capacidad (medida el 17-oct-2026)

Con PostgreSQL local, un proceso, 4 núcleos (en Render, plan `starter`, será peor):
- **Una misma hora pedida por 30 personas a la vez:** gana una, 29 reciben «esa hora se acaba de
  ocupar». Correcto.
- Paso 1 ~20 páginas/s · entrada de Cutí ~11 páginas/s · **paso «fecha y hora» ~2 páginas/s**
  (calcula 14 días, ~99 consultas): con 20 personas a la vez, ~9 s de espera. Reservar ~2/s.
- **Alcanza** para ~10 barberías y ~30 spas. Para ~500 spas faltan, en orden: guardar unos segundos
  los días con hueco, sacar las fotos de la base a un almacenamiento de archivos, subir el plan y,
  solo después, varios procesos (exige Redis para los avisos y los frenos).
- Reproducir: `scripts/prueba_de_carga.py` en `Bot-whatsapp-pro`.

## Verificación

`python tests/test_multitenant.py · test_regresion.py · test_ia.py · test_marca.py · test_spa.py ·
test_guia.py · test_barberia.py · test_rls.py` (este último pide PostgreSQL). Devuelven 0 o 1.
`test_panel.py` trae 3 fallas anteriores a estos cambios (plantillas de Meta), sin investigar.

## Qué falta

- Demo en vivo en la landing de Cutí (la de Degradé es un clon a mano de ~4.800 líneas).
- **Capacidad:** guardar los días con hueco (siguiente paso), fotos fuera de la base, plan de
  servidor/base, Redis para varios procesos.
- Probar la guía y las funciones de spa con una cuenta real de producción.
- Archivar este repositorio.

## Dónde mirar

`Bot-whatsapp-pro` → `instrucciones/CONTINUAR_AQUI.md` (estado, trampas, capacidad),
`instrucciones/proyecto.md` (mapa) y `tests/test_marca.py` + `tests/test_spa.py` (lo que está
garantizado).
