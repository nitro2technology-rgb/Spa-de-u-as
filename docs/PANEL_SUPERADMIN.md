# El panel de super-admin — qué hace y qué tiene que seguir haciendo

**Documento para rediseñar `/superadmin`.** Describe cada pantalla, cada
control y qué pasa al tocarlo. No propone diseño: dice qué trabajo hace la
herramienta, para que el diseño se pueda decidir con el problema delante.

Al 27 de agosto de 2026.

---

## 1. Qué es esto y quién lo usa

Es la consola con la que se **opera una plataforma de bots de WhatsApp
multi-inquilino**. Un solo despliegue atiende a todos los negocios
clientes; esta consola los administra.

**La usa una sola persona**: el dueño de la plataforma. No es un producto
que se venda ni que vea un cliente. Cada negocio cliente tiene *su propio*
panel aparte (`/admin`), rediseñado y con otra identidad visual.

> Esa diferencia importa para el diseño. `/admin` es un panel de atención
> que alguien mira **todo el día** mientras responde clientes.
> `/superadmin` es una **herramienta de operación**: se entra a hacer una
> cosa concreta —dar de alta, pausar a quien no paga, arreglar unas
> credenciales— y se sale. Se usa a ráfagas, a veces desde el celular un
> domingo.

### Escala real

Hoy hay **1 cliente**. El diseño debería aguantar bien con 5–30, que es el
horizonte realista. No hace falta que escale a cientos.

---

## 2. Mapa de pantallas

```
/superadmin/login              Entrar (una sola clave)
/superadmin                    Listado de clientes           ← la portada
/superadmin/nuevo              Alta de un negocio
/superadmin/clientes/{id}      Ficha del cliente             ← la más densa
  ├── /contenido               Editor de lo que dice el bot
  ├── /contenido.json          Descarga una copia (no es pantalla)
  └── /mapa                    Editor visual de la conversación
/superadmin/consumo            Consumo de IA en JSON (no es pantalla)
```

Cuatro pantallas de verdad, más dos que devuelven datos.

---

## 3. Pantalla por pantalla

### 3.1 Entrar (`/login`)

Lo más simple del sistema: **un campo de clave y un botón**. No hay
usuario, no hay "recordarme", no hay recuperación.

- Si la clave del sistema no está configurada, la consola entera responde
  "no disponible" y no existe.
- Hay un **freno a los intentos**: tras varios fallos bloquea unos minutos
  y lo dice.
- Exige HTTPS salvo en local.

**Estados que hay que diseñar:** normal · clave incorrecta · bloqueado por
intentos.

---

### 3.2 Listado de clientes (`/superadmin`) — la portada

Es lo primero que se ve y donde se pasa más tiempo. Una tabla con **una
fila por negocio**.

| Columna | Qué lleva |
|---|---|
| **Negocio** | Nombre, y debajo su nombre corto e id |
| **Estado** | `activo` / `pausado` + el semáforo de credenciales (ver abajo) |
| **Plan** | Texto libre del plan, y si tiene IA |
| **IA (mes)** | Mensajes consumidos / tope, y tokens. En rojo si se quedó sin cupo |
| **Conversación** | Nº de contactos, nº de mensajes, fecha del último |
| **Acciones** | `pausar` / `reanudar` · `editar` |

**Arriba** hay un resumen —cuántos activos de cuántos, total de mensajes de
IA del mes— y un **selector de mes** que recarga la tabla con los datos de
ese periodo.

#### El semáforo de credenciales

Cada cliente tiene su propia App de Meta, y sus credenciales pueden estar
rotas sin que nada dé error. Por eso cada fila muestra uno de:

- `credenciales ok`
- `revisar credenciales` — funciona, pero hay algo que saber
- `credenciales rotas` — no funciona
- `sin comprobar`

> **Esto es lo más importante del listado y hoy está mal resuelto**: es
> texto pequeño debajo del estado. Un cliente activo con el token roto está
> tan mudo como uno pausado, y ahora mismo se parecen demasiado. Debería
> poder barrerse la tabla y ver de un vistazo quién necesita atención.

---

### 3.3 Alta de un negocio (`/nuevo`)

Un formulario largo, de una sola pasada, agrupado en cuatro bloques:

1. **Identidad** — nombre del negocio y nombre corto (con el que entra al panel)
2. **WhatsApp** — `phone_number_id`, `waba_id`, App ID, App Secret, token permanente, número del dueño
3. **Paquete de IA** — si contesta hoy (y por qué no), si lo compró, si está encendida, tope mensual
4. **Acceso al panel** — correo y clave del primer usuario

Al crearlo, el sistema **genera solos** dos datos y lleva a la ficha para
entregárselos al cliente: su URL de webhook y su código de verificación.

**Puede fallar** por: nombre corto inválido o reservado, `phone_number_id`
repetido, clave corta, o falta la clave de cifrado del sistema. Cada fallo
vuelve al formulario con una banda explicando cuál.

---

### 3.4 Ficha del cliente (`/clientes/{id}`) — la pantalla densa

**Es donde más falta hace el rediseño.** Hoy son **once bloques apilados
en una columna**, casi todos dentro de un único formulario gigante con un
solo botón *Guardar* al final.

En orden actual:

| # | Bloque | Qué hace |
|---|---|---|
| 1 | **Estado** | Activo/pausado, IA, consumo del mes. Botones a *Armar la conversación* y *El contenido completo* |
| 2 | **Lo que el cliente pega en su App de Meta** | Su URL de webhook y su código, en campos de solo lectura para copiar. Semáforo de credenciales + botón **Probar credenciales** |
| 3 | **Usuarios del panel** | Tabla de quién entra al panel del cliente: correo, estado, cambiar clave, dar de baja. Y un formulario para añadir |
| 4 | **Identidad** | Nombre y nombre corto |
| 5 | **WhatsApp** | `phone_number_id`, `waba_id`, App ID, App Secret, token |
| 6 | **Paquete de IA** | Si contesta hoy, si lo compró, si está encendida, tope mensual, modelo, clave propia, botón Probar la IA |
| 7 | **Avisos: a quién le llega un lead** | Ver abajo — es un bloque grande por sí solo |
| 8 | **Datos públicos del negocio** | WhatsApp público, correo, web |
| 9 | **Google (citas y leads)** | Calendario, hoja de cálculo, JSON de cuenta de servicio |
| 10 | **Avisos al celular (push)** | Claves VAPID |
| 11 | **Marca y datos** | Color, logo, plan, días de historial |

> **Los bloques 4–11 están en UN formulario con un solo Guardar.** Los
> bloques 2 y 3 tienen sus propios botones y actúan por su cuenta. Esa
> mezcla es confusa y es parte de lo que hay que resolver.

#### El bloque de avisos, en detalle

Es el más trabajado y el que más se usa. Dice **a quién le llega un lead**
cuando un cliente final agenda, pregunta o pide un asesor.

- **Número del dueño** — la red de seguridad: si no hay áreas, todo va ahí
- **Números incluidos en su plan** — cuántas áreas puede tener (3 sin IA,
  6 con IA, o lo que se escriba)
- **De 3 a 6 áreas**, cada una con:
  - su **correo** (la vía principal, la que siempre llega)
  - nombre del área (*Ventas*, *Soporte*, *Contratos*)
  - su WhatsApp, opcional, en dos campos: **país** y **número**
  - **casillas** con las opciones del menú de ese negocio, para decir de
    qué se encarga
- Un botón **Mandar un aviso de prueba** que envía de verdad y dice qué pasó
- Y, si Meta rechazó un aviso, una **banda roja** con el motivo

---

### 3.5 Editor de contenido (`/clientes/{id}/contenido`)

Un formulario **muy largo** —el más largo del sistema— con todo lo que el
bot dice. Nueve bloques:

1. **El negocio** — nombre, WhatsApp público, correo, web
2. **Lo que dice el bot** — ~35 textos: saludo, menú, citas, archivos…
3. **El menú** — opciones y sub-opciones, con botón para añadir
4. **Enlaces** — URLs con nombre, que las opciones usan
5. **Bloques de precios** — textos largos compartidos
6. **Avisos al dueño** — los textos de cada tipo de aviso + la plantilla de Meta
7. **Opciones de cierre**
8. **El carácter del bot** — solo si tiene IA: rol, tono, qué nunca hacer
9. **Horario y conversación** — zona horaria, días, duración de citas

Tiene un **botón de guardar fijo abajo**, porque la página es larguísima y
perder los cambios por no encontrarlo sería absurdo. Y un botón para
**descargar una copia** de lo guardado.

**Nada se guarda si algo no cuadra**: al guardar se valida entero y, si una
opción del menú apunta a un enlace que no existe, lo dice y no toca nada.

---

### 3.6 Editor del mapa (`/clientes/{id}/mapa`) — la más visual

**Es la pantalla más elaborada y la que mejor funciona hoy.** Arma la
conversación del bot paso a paso, con vista previa en vivo.

Dos columnas:

- **Izquierda: los pasos.** Una lista de tarjetas plegables —*1 · Saludo y
  menú*, *2 · Si ya te había escrito*…— que se abren de una en una. Dentro,
  los textos y las opciones de ese momento.
- **Derecha: la vista previa.** Una **simulación de un chat de WhatsApp**
  que muestra cómo se ve ese paso, con burbujas y el nombre del negocio.

Al pulsar un paso a la izquierda, la derecha pinta ese momento. También hay
botón de guardar fijo abajo.

Son ~950 líneas de JavaScript: árbol de opciones anidadas, añadir y quitar,
y el guardado.

---

## 4. Lo que NO se puede perder en el rediseño

Decisiones ya tomadas, con su motivo. No son preferencias.

**No existe borrar un cliente, solo pausar.** Un botón de borrar al lado de
uno de pausar es un accidente esperando. Pausar deja el historial intacto.

**Los semáforos no siguen a la marca.** Un "urgente" o un "roto" tiene que
leerse igual siempre.

**Las credenciales nunca se pintan en pantalla.** Los campos de token,
clave y secreto salen vacíos con un texto que dice si hay algo guardado.
Vacío significa *no lo toques*, no *bórralo* — y eso hay que decirlo con
todas las letras junto al campo.

**La URL de webhook y su código son de solo lectura.** No son campos que se
editen: son datos que se entregan. Cambiarlos deja al cliente sin recibir
mensajes y sin ningún error.

**El bloque de avisos va junto.** El número del dueño, el cupo y las áreas
son lo mismo. Estuvieron repartidos en dos pantallas y el dueño no los
encontró.

**Todo tiene que funcionar en el celular**, incluida la tabla del listado.
Se usa para pausar a alguien un domingo.

---

## 5. Lo que hay que arreglar (los problemas conocidos)

Esto es lo que motiva el rediseño:

1. **La ficha es una columna de once bloques.** Sin jerarquía: "Marca y
   datos" pesa lo mismo que "WhatsApp". Hay que decidir qué es frecuente y
   qué es de una vez.

2. **El guardado es confuso.** Un formulario gigante con un solo botón, y
   dentro otros bloques con botones propios que actúan solos.

3. **El semáforo de credenciales no se ve.** Es lo más accionable del
   listado y está en texto pequeño.

4. **No hay jerarquía visual.** Todas las cajas son iguales: mismo borde,
   mismo fondo, mismo peso.

5. **El editor de contenido es interminable.** Nueve bloques y ~35 campos
   de texto seguidos, sin navegación interna.

6. **No hay estado vacío.** Con un solo cliente, la portada se ve pobre y
   no orienta sobre qué hacer.

---

## 6. Identidad visual actual

**El super-admin NO usa el morado de Nitro.** Hoy va con una paleta
neutra de grises azulados:

```
Claro    tinta #0f172a · papel #f8fafc · caja #ffffff · borde #e2e8f0
         tenue #64748b · acento #1e293b · mal #b91c1c · bien #15803d
Oscuro   tinta #e2e8f0 · papel #0b1120 · caja #111a2e · borde #1e293b
         tenue #94a3b8 · acento #e2e8f0 · mal #f87171 · bien #4ade80
```

El **panel del cliente** (`/admin`), que es otra herramienta, sí usa el
morado de Nitro `#6D28D9` (claro) / `#A78BFA` (oscuro) con neutros de sesgo
violeta, y las fuentes **Manrope** e **IBM Plex Mono**.

> **Decisión abierta para el diseño**: si el super-admin debería adoptar la
> identidad de Nitro (coherencia) o mantenerse deliberadamente distinto
> (para que no haya duda de en qué herramienta estás). Las dos se defienden;
> hoy es lo segundo, pero por inercia, no por decisión.

**Dos temas obligatorios**, claro y oscuro, por `prefers-color-scheme`. No
hay interruptor manual.

---

## 7. Restricciones técnicas

Quien implemente esto trabaja con:

- **HTML generado desde Python** con f-strings. Sin plantillas, sin build,
  sin framework. El CSS y el JavaScript **ya están en archivos aparte**
  (`app/web/estaticos/superadmin.css`, `superadmin-mapa.js`, etc.) y se
  sirven con el hash del contenido en la dirección.
- **Sin dependencias nuevas de frontend.** Nada de React, Tailwind ni
  librerías de componentes. CSS y JavaScript a mano.
- Se puede usar todo lo moderno del navegador: grid, flex, `:has()`,
  propiedades personalizadas, `<details>`, `<dialog>`.
- Las fuentes se sirven desde el propio dominio (Manrope e IBM Plex Mono ya
  están ahí). No se pueden pedir a Google.

---

## 8. Datos reales para diseñar con ellos

No uses texto de relleno. Esto es lo que hay de verdad:

**Un cliente en el listado**

```
Nitro 2Tech            activo · credenciales ok
principal · id 1       Plan: —  ·  IA: sí
                       0 / 0 mensajes  ·  0 tokens
                       12 contactos · 340 mensajes · 27/08/2026
```

**Áreas de aviso de un negocio con tres**

```
Ventas      ventas@panaderia.com      57 300 111 2233   → Comprar
Soporte     soporte@panaderia.com     —                 → Tengo un problema
Contratos   contratos@panaderia.com   —                 → (todo lo demás)
```

**Lo que se le entrega al cliente**

```
URL de devolución de llamada
https://bot.nitro2tech.com/webhook/0tKj0nTTDp3Vv-ujpuHcvRhd89TtyUzL

Token de verificación
au8C7iFm_gGo3xP4qt27QeREjYMwv56g
```

**Un fallo de credenciales, como se ve hoy**

```
FALLA · Ventas (34612345678): Ese número no recibe WhatsApp. Casi
siempre es el país: revisa el indicativo y que el número vaya sin el
cero inicial.
```

**Nombres de negocio para probar el ancho**

`Nitro 2Tech` · `Panadería Doña Rosa` · `Comercializadora de Alimentos
del Valle S.A.S.`

---

## 9. Prioridad, si hay que elegir

Por lo que más se usa y peor está:

1. **Ficha del cliente** — la más densa y la más rota
2. **Listado** — es la portada y el semáforo no se ve
3. **Editor de contenido** — larguísimo, sin navegación
4. **Alta** — funciona bien, solo necesita el mismo lenguaje visual
5. **Mapa** — es el que mejor está; tocarlo poco
6. **Entrar** — dos campos, casi nada que decidir
