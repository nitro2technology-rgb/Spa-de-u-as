# Especificaciones de uso — versión Spa de uñas

Documento de arranque para crear la segunda marca de la plataforma: la misma
base que **Degradé** (barberías), pero para spas de uñas. Escrito el
16-oct-2026 después de leer `CLAUDE.md`, `docs/CONTINUAR_AQUI.md`, el paquete
`app/barberia/`, `app/core/planes.py` y el sitio `Nitro2Tech/`.

> **Estado:** propuesta para decidir, no código hecho. Lo que no pude
> comprobar está marcado con ⚠️.

---

## 1. Qué se quiere

| | |
|---|---|
| Producto nuevo | Software de gestión + chatbot de WhatsApp para **spas de uñas** |
| Producto actual | **Degradé**, para barberías (nombre interno en código: *BarberSaaS*). **No se toca** |
| Lo que se comparte | Base de datos, motor, bot, cobros, super-admin, panel de atención |
| Lo que cambia | Nombre, paleta, logo, textos, y la página web que ve el cliente final del spa |
| Chatbot | Opcional por plan, igual que en Degradé |

La idea: dos marcas distintas de cara al cliente, un solo producto por dentro.

---

## 2. Lo que encontré al leer el proyecto

1. **El módulo de barbería ya es el 80 % del spa.** `app/barberia/` (≈9.500
   líneas) trae sedes, personal, agenda, citas con varios servicios, caja,
   pagos, gastos, nómina por comisión, recordatorios, clientes, permisos por
   rol y el bot de citas. Un spa de uñas necesita lo mismo con otro
   vocabulario.
2. **Este repositorio (`Spa-de-u-as`) es hoy una copia de la base de barbería**
   (un solo commit, «Base software Spa de uñas»). Todo dice todavía
   «barbería»: 798 menciones en 40 archivos (`app/barberia/*`, `barberia.css`,
   `barberia.js`, `planes.py`, `database.py`, `equipo.py`, `bot_logic.py`,
   `main.py`, `superadmin.py`, `acceso.py`, tests y scripts).
3. **El nombre de marca está escrito como constante de módulo**
   (`PRODUCTO = "BarberSaaS"`, `TITULAR = …` en `app/barberia/paginas.py`; el
   logo de `paginas._logo`). Es justo la trampa que el `CLAUDE.md` prohíbe
   (se evalúa al importar y se congela). Para tener dos marcas hay que
   volverlo función de quien está entrando.
4. **El diseño ya está en variables CSS** (`:root { --violet … --lilac … }` en
   `barberia.css`). Cambiar de paleta es sobreescribir ~60 variables, no
   reescribir 1.556 líneas.
5. **Las tablas son `barb_*`** (sedes, personal, citas, caja…) con
   `client_id` y RLS. Renombrarlas rompería Degradé: se quedan, y «barbero»
   pasa a ser «técnica» solo en pantalla.
6. **La página pública de reservas de la barbería («Mi página») no está en
   este repositorio.** Aquí solo hay `/privacidad`, `/terminos` y
   `/eliminar-datos`. El sitio de Nitro2Tech describe una página de reservas
   (sede → servicio → barbero → día → hora) y la prueba gratis
   `degrade.nitro2tech.com/prueba`, pero su código vive en otro lado. ⚠️ Hay
   que ubicar ese repositorio antes de diseñar la página del spa.
7. **Precios inconsistentes en Degradé:** `planes.py` dice *«PRECIOS DE
   EJEMPLO»* (89.000 / 149.000 / 219.000) y el sitio publica otros reales
   (49.500 / 130.000 / 330.000). Antes de copiar la estructura de planes hay
   que saber cuáles mandan.

---

## 3. Decisión 1 (la que manda sobre todo): ¿un código o dos?

Pediste que compartan base de datos «y todo». Eso se puede hacer de dos formas
y la diferencia es grande.

### Opción A — Un solo código y un solo despliegue, dos marcas (recomendada)

Una columna nueva `clients.marca` (`"degrade"` | el nombre del spa). Cada
negocio pertenece a una marca, y de ella salen nombre, logo, paleta, textos y
planes. Degradé es el valor por defecto, así que **ningún cliente actual
cambia**.

- Todo arreglo del motor llega a las dos marcas sin copiarlo.
- Un cliente es de una marca u otra; el mismo negocio no puede ser las dos.
- Dominios distintos (`degrade.nitro2tech.com`, `<spa>.nitro2tech.com`)
  apuntan al mismo servicio, y la marca se deduce del dominio **o** del
  cliente.
- Riesgo: un cambio compartido puede afectar a Degradé. Se cubre con las
  cuatro suites (`test_multitenant`, `test_regresion`, `test_ia`,
  `test_panel`) + `test_barberia`, más pruebas nuevas de marca.

### Opción B — Dos repositorios, dos despliegues, una base

Es lo que sugiere tener ya `Spa-de-u-as` como repo aparte. **No lo
recomiendo**, por cosas que ya se pueden ver en el código:

- `main.py` arranca `cobros.vigilar()` y `recordatorios.vigilar()` dentro de
  cada proceso y **no tienen candado** (busqué `lock`/`advisory`: nada). Con
  dos despliegues sobre la misma base, cada cobro y cada recordatorio de
  cita **saldría dos veces** (correos duplicados al dueño, avisos dobles al
  cliente final).
- Las migraciones de Alembic las tendría que dueñear un solo repositorio; si
  los dos generan migraciones sobre la misma base, se pisan y el segundo
  despliegue revienta.
- Cada mejora o arreglo hay que portarlo a mano a la otra copia; en semanas
  las dos divergen.
- Dos `/superadmin`, dos listas de clientes.

Si por algo se quiere B de todos modos, hay que resolver antes: candado en
los dos vigilantes (por ejemplo `pg_try_advisory_lock`), un solo dueño de las
migraciones y un proceso para portar cambios.

### Qué hacer con este repo

Con la Opción A, `Spa-de-u-as` sirve de **borrador** para el trabajo de marca
y después se integra al repositorio principal de Degradé (o se vuelve él). ⚠️
Necesito saber si el repositorio de Degradé existe aparte o si esta copia es
el único código.

---

## 4. Nombres propuestos

Degradé es el nombre de una técnica de corte (el difuminado). Busqué lo mismo
para uñas: una palabra de la técnica o de la anatomía de la uña, corta, en
español, con acento bonito, que suene a marca hermana.

| # | Nombre | Qué es | A favor | En contra |
|---|---|---|---|---|
| 1 | **Lúnula** | La media luna blanca de la base de la uña | Única, fácil de defender como marca, el isotipo sale solo (una media luna), no la usa ningún software conocido del sector | Quien no conozca el término tiene que aprenderlo |
| 2 | **Ombré** | El degradado de color en las uñas | Es la pareja natural de *Degradé* (la misma idea, otro oficio); el cliente la reconoce al instante | Palabra común: difícil de posicionar en buscadores y de registrar |
| 3 | **Nácar** | El brillo perlado del esmalte y de la concha | Elegante, femenina sin ser infantil, dos sílabas | Más genérica; ya hay negocios de belleza con ese nombre |
| 4 | **Glasé** | La tendencia «uñas glaseadas» | Actual, se pronuncia fácil | Es moda: puede envejecer |
| 5 | **Cutí** | De *cutícula* | Corta, simpática | Suena a marca de consumo, menos a software |

**Mi recomendación: Lúnula**, con **Ombré** de respaldo si prefieres que la
pareja *Degradé / Ombré* cuente sola su historia. Nombre interno del código,
siguiendo el patrón de *BarberSaaS*: **NailSaaS**.

⚠️ No pude verificar disponibilidad. Antes de decidir: buscar el nombre en la
SIC (Superintendencia de Industria y Comercio, clase 9/42/44), el subdominio
`<nombre>.nitro2tech.com`, el dominio propio y los usuarios de Instagram y
TikTok.

Evitar: *Gelish*, *Shellac*, *OPI*, *CND* (marcas registradas de esmaltes).

---

## 5. Identidad visual

### 5.1 Paleta

Degradé usa violeta y lila sobre noche (`#1A1823`, `#56377F`, `#B69CF0`) y
crema. El spa tiene que **leerse distinto de un vistazo**, así que sale del
violeta. Tres propuestas, todas con la misma estructura de variables:

| | A · **Rosa nácar** (recomendada) | B · Salvia y arena | C · Cereza y champán |
|---|---|---|---|
| Fondo oscuro (`--ink`) | `#2B1B24` ciruela | `#1F2B26` bosque | `#2A1519` vino |
| Color de marca (`--violet`) | `#A8456B` rosa profundo | `#4F7A68` salvia | `#9E2B45` cereza |
| Acento claro (`--lilac`) | `#F2B8C6` rosa pálido | `#B7D3C3` menta | `#F0C6B8` durazno |
| Fondo claro (`--mist`) | `#FDF3F1` | `#F4EEE4` | `#FBF1EC` |
| Detalle | `#C9A66B` dorado | `#C9785D` terracota | `#C9A66B` champán |
| Sensación | Salón clásico, cálido | Spa de bienestar, sereno | Premium, nocturno |

Reglas heredadas del proyecto que aquí también aplican:

- **Los semáforos (ok / aviso / peligro) no siguen a la marca.** Un «urgente»
  se lee igual en todos los paneles. Solo cambian las variables de marca.
- **La plataforma sigue siendo Nitro** dentro del panel (el acento del panel
  de atención es el morado de Nitro, decisión cerrada en `CONTINUAR_AQUI` §1).
  La marca del spa manda en *su* panel de gestión y en su página pública; el
  pie conserva la firma «creado por Nitro 2Tech».
- Hay que comprobar el contraste (AA, 4,5:1) de texto sobre el rosa de marca;
  el dorado no sirve para texto pequeño sobre claro.

### 5.2 Logo

- Isotipo + wordmark propios; con Lúnula, una media luna que también se lee
  como la base de una uña.
- Se necesitan: wordmark horizontal (claro y oscuro), isotipo cuadrado
  512×512 (para el icono instalable; si trae fondo se usa a sangre, ver
  `app/marca/README.md`), y favicon.
- El wordmark de Nitro (`app/web/estaticos/barberia/nitro-wordmark.png`) se
  queda como firma de plataforma.

### 5.3 Tipografía

Degradé usa Unbounded (títulos) + Manrope (texto). Para el spa conviene un
título más suave (una serif de display o una redondeada). Las fuentes se sirven
desde el propio servidor (`scripts/traer_fuentes.py`), no desde Google, así
que cambiar de fuente es correr ese script con la nueva y subir los `.woff2`.
Opcional: puede quedarse Manrope para el texto y cambiar solo el título.

---

## 6. Página web que ve el cliente final del spa

Es la parte más distinta. **La de Degradé no se toca**; la del spa es otra
página con otro diseño, sobre los mismos datos (sedes, servicios, técnicas,
horarios, citas).

Lo que cambia respecto a la de barbería (⚠️ el código de la de barbería no
está en este repo, así que esto es el diseño, no un diff):

| Barbería | Spa de uñas |
|---|---|
| Servicios de 20–45 min | Servicios de 45–150 min; puede combinar varios en una visita (manicure + pedicure) |
| Escoger barbero | Escoger técnica, o «cualquiera disponible» |
| Lista de cortes | **Catálogo de diseños con fotos** (galería de trabajos) |
| Reservar y listo | Opcional: **abono** para confirmar y reducir inasistencias |
| — | Foto de referencia que sube la clienta; preguntar si trae retiro de gel/acrílico (suma tiempo) |

Pasos de la reserva: sede → servicios (con extras) → técnica → día → hora →
datos y, si el spa lo activa, abono → tiquete con enlace para cancelar o
mover.

Se sirve en el dominio de la marca del spa y con la paleta de §5. Es un
añadido sobre el motor de citas existente, no un motor nuevo.

---

## 7. Qué cambia en el producto (vocabulario)

Un **diccionario por marca** (un solo lugar) que dice cómo se llama cada cosa:

| Barbería | Spa |
|---|---|
| Barbero / `BARBERO` | Técnica / manicurista |
| Corte, barba | Manicure, pedicure, semipermanente, acrílicas, nail art |
| Plan «Barbería» | Plan «Spa» |
| «Cada corte registrado, cada peso en su lugar.» | Titular propio del spa |
| Mensajes del bot («tu barbero…») | Mensajes del bot del spa |

Los **códigos internos no se renombran** (`BARBERO`, `barb_*`,
`barberia_contratada`): renombrar columnas con RLS en una base compartida es
riesgo sin beneficio. Solo cambia lo que se ve.

---

## 8. Planes

Misma estructura que Degradé (`planes.py`): solo gestión; gestión + bot;
gestión + bot con IA. Cada marca ve solo los suyos (`ORDEN_BARBERIA` →
`ORDEN_SPA`).

| Plan | Incluye |
|---|---|
| Spa | Agenda, caja, pagos a técnicas, gastos, recordatorios |
| Spa + Bot | Lo anterior + bot de WhatsApp que agenda |
| Spa + Bot IA | Lo anterior + el bot entiende lo que escriben |

**Precios: pendientes, no los invento.** Ver el punto 7 de §2 (los de Degradé
ni siquiera coinciden entre código y sitio).

---

## 9. El chatbot

Ya existe y se reutiliza (`app/barberia/bot.py`, `bot_logic.py`):

- Agenda citas con huecos reales, avisa al área o al dueño, recordatorios 2 h
  antes, IA opcional (`ia_contratada`, y la puerta es `cerebro.plan_activo()`).
- **Cada spa trae su propia App de Meta y su propio webhook**
  (`/webhook/{token}`); la plataforma no cambia ese modelo.
- Hay que reescribir los **textos** del bot y de su menú base para uñas
  (plantilla `negocio.toml` del spa).
- Atención a las reglas de Meta del `CLAUDE.md`: título de botón ≤ 20
  caracteres, nada de `str.format` sobre textos del dueño (`huecos.rellenar`).
- Los servicios de uñas duran más: revisar que la búsqueda de huecos y el
  recordatorio manejen citas de 2–3 h y varios servicios encadenados.

---

## 10. Por dónde iniciar (orden propuesto)

**Fase 0 — Decidir (sin código)**
1. Opción A o B (§3). *Recomiendo A.*
2. Elegir nombre (§4) y paleta (§5.1). Verificar disponibilidad.
3. Confirmar dónde vive el repo de Degradé y su página de reservas.
4. Precios (§8).

**Fase 1 — Capa de marca (el cimiento; no cambia nada visible para Degradé)**
1. Migración: `clients.marca`, valor por defecto = Degradé.
2. Un módulo `marca` con nombre, titular, logo, diccionario de vocabulario,
   colores y planes por marca; se consulta **por petición**, nunca al importar.
3. Sustituir `PRODUCTO`/`TITULAR`/`_logo` y los textos fijos por esa consulta.
4. Tema CSS: `barberia.css` queda con los tokens de Degradé como base y un
   bloque `[data-marca="spa"] { … }` con los del spa.
5. Prueba que demuestre que un cliente de Degradé se ve y se comporta igual
   que antes.

**Fase 2 — El spa se ve como spa**
1. Paleta, logo, tipografía, vocabulario, planes, correos del producto.
2. Consola: elegir la marca al dar de alta un negocio.
3. Textos del bot y plantilla `negocio.toml` para uñas.

**Fase 3 — Página pública del spa** (§6): catálogo con fotos, servicios
combinados, técnica, abono opcional.

**Fase 4 — Lo propio de uñas** (solo si hace falta): abono, galería, fotos de
referencia, inventario de esmaltes, garantía de retoque.

**Para cerrar cada fase:** las cuatro suites + `test_barberia` en verde, y
**abrir en el navegador** las dos marcas, en tema claro y oscuro y a ancho de
teléfono (regla del `CLAUDE.md`: las suites ya estuvieron en verde con el
panel roto en pantalla). `python scripts/servir_barberia.py` y
`demo_barberia.py` sirven para eso; habrá que darles un modo «spa».

---

## 11. Riesgos y trampas a vigilar

- **Degradé debe quedar intacto:** defecto de marca = Degradé y prueba de
  regresión visual/funcional antes de desplegar. Recordar que el push a `main`
  **es** el despliegue en producción.
- **No leer la marca al importar un módulo** (`config.X` congelado). Todo
  dato de marca se resuelve por petición/inquilino.
- **Hilos nuevos** con `tenencia.envolver_para_hilo()`; **no** agregar
  `--workers` a uvicorn (el bus de avisos es de un solo proceso).
- **Tabla nueva con `client_id`** = `MODELOS_DEL_INQUILINO` **y** su política
  RLS en migración; correr `tests/test_rls.py` contra PostgreSQL.
- **`/superadmin` sigue sin inquilino** y verá clientes de las dos marcas;
  mostrar la marca de cada uno en el listado.
- **Cobros:** hoy el cobro es el mismo para todos; si el spa tiene otro medio
  de pago o WhatsApp de cobros, `planes.MEDIOS_DE_PAGO` es hoy global.
- **Meta:** el spa también necesita su App, su WABA y su método de pago antes
  de que el bot responda (desde el 1-oct-2026 Meta cobra incluso las
  respuestas).
- **Legal:** `/privacidad` y `/terminos` llevan el nombre del producto; el
  nombre nuevo debe entrar ahí también.

---

## 12. Lo que necesito de ti para empezar

1. ¿Opción **A** (un código, dos marcas) o **B** (dos repos)?
2. ¿Cuál nombre? (mi voto: **Lúnula**) y ¿cuál paleta? (mi voto: **A · Rosa
   nácar**).
3. ¿Dónde está el repositorio de Degradé y su página de reservas pública?
4. ¿Precios de los tres planes del spa, o los dejo como ejemplo marcado?
5. ¿El abono (pago anticipado) entra en la primera versión o después?

---

## 13. Registro y prueba gratis de 7 días (decisión del 16-oct-2026)

Hoy: `nitro2tech.com` → botón «Empezar prueba gratis» (`degradeTrialUrl` en
`Nitro2Tech/app/config/services.ts`) → `degrade.nitro2tech.com/prueba` → el
dueño elige plan, crea usuario y clave, entra 7 días. ⚠️ Esa página y su
código no están en este repo.

**Recomendación: la marca la decide la puerta por la que entra el dueño, y se
guarda en el cliente.**

1. **Una página `/prueba`, dos entradas.** `degrade.nitro2tech.com/prueba` y
   `<spa>.nitro2tech.com/prueba` apuntan al **mismo servicio**. El servidor
   lee el `Host` y pinta la página con la marca que toca (colores, logo,
   textos, planes de esa marca). Respaldo: `?marca=spa`.
2. **Al registrarse, se guarda `clients.marca`** junto con el resto del alta
   (lo que hoy hace la consola al dar de alta). Desde ese momento la marca
   sale **de la fila del cliente**, no del dominio ni de un parámetro: así el
   dueño ve siempre su marca aunque entre desde otra URL, su sesión, el panel
   de equipo y los correos coinciden.
3. **Entrar después:** el usuario ya es único en toda la plataforma
   (`acceso.autenticar_usuario`), así que al entrar se encuentra su cliente y
   de él se lee la marca. Un login con la marca equivocada en la URL se
   corrige solo (se redirige a la suya).
4. **En el sitio de Nitro2Tech:** una `spaTrialUrl` junto a `degradeTrialUrl`
   y una landing propia del spa (tema `spa` al lado de `nitro`, `degrade` y
   `whatsapp`). Nada de lo de Degradé se toca.
5. **Marca → planes:** el formulario solo ofrece los planes de esa marca
   (`ORDEN_BARBERIA` / `ORDEN_SPA`), ninguno marcado de antemano.
6. **Lo que se comparte:** la misma base, el mismo `/superadmin`, los mismos
   cobros y el mismo bot. El superadmin muestra la marca de cada cliente.

**La página que ven los clientes del spa** es aparte: se sirve por la marca
del negocio (`<negocio>.<spa>.nitro2tech.com` o una ruta pública por slug) con
su propia plantilla y paleta, leyendo las mismas tablas de citas. Degradé usa
la suya, sin cambios.

**Dominios:** certificado comodín por marca (`*.nitro2tech.com` ya cubre
ambas si los subdominios son del mismo dominio). Con `DOMINIO_BASE` hoy el
subdominio *es* el negocio; hay que decidir si el subdominio de marca
(`degrade.`, `<spa>.`) convive con el de negocio, o si el de negocio pasa a
`slug.<marca>.nitro2tech.com`. ⚠️ Pendiente de ver cómo lo resuelve hoy el
repo de Degradé.
