# Bot genérico de captación y ventas para WhatsApp

Bot de WhatsApp Business (Cloud API oficial de Meta) que:
1. Da la bienvenida y capta el nombre del cliente.
2. Le muestra los **servicios** en una lista desplegable.
3. Cada servicio abre su propio **submenú de botones**, donde el cliente puede:
   - **Ver planes y precios** → recibe las tarifas y el enlace al detalle.
   - **Ver ejemplos** → recibe el enlace al portafolio de ese servicio.
   - **Agendar una reunión** → elige entre días y horas **realmente libres**
     de Google Calendar; el bot crea el evento y avisa al dueño.
   - **Hablar con un asesor** → el bot se calla en ese chat y avisa al dueño.
4. Guarda todo en base de datos y en el Google Sheet: una pestaña por servicio,
   con el **recorrido** de cada cliente (`Vio precios > Agendó reunión`), para
   ver en qué punto se cae la gente.
5. Trae un **panel de atención manual** para leer las conversaciones y responder
   a mano cuando haga falta, con **imágenes y notas de voz** en los dos sentidos
   (§6.8), instalable en el celular como app.

Es **multi-inquilino**: un solo despliegue atiende a varios negocios, cada
mensaje se enruta por su `phone_number_id` y cada negocio entra a su propio
panel. Un cliente nuevo se da de alta desde `/superadmin` (§14) y sus textos se
editan desde el navegador: no se toca Python ni la terminal. `negocio.toml` se
queda como **plantilla** de la que parten los clientes nuevos.

## Estructura del proyecto

El repositorio está partido en **tres capas**, y de esa división sale la regla
para saber dónde va cada cosa:

| Capa | Dónde vive | Qué es | ¿Se toca para un cliente nuevo? |
|---|---|---|---|
| **Contenido** | `negocio.toml`, `app/marca/`, `.env` | Lo que cambia de un negocio a otro: textos, servicios, precios, horarios, colores, logo y credenciales | **Sí, siempre.** Es lo único |
| **Motor** | `app/` | El código que corre en producción. Es el mismo para todos los clientes | Casi nunca |
| **Herramientas** | `scripts/`, `tests/`, `docs/` | Se ejecutan o se leen, no se editan: setup, diagnóstico, pruebas y guías | No |

> **La regla de oro:** si estás a punto de escribir el nombre de un negocio, un
> precio o un horario dentro de un `.py`, estás en el archivo equivocado. Eso va
> en `negocio.toml`.

### ¿Dónde toco para…?

| Quiero cambiar… | Archivo |
|---|---|
| Nombre del negocio, textos, servicios, precios, enlaces, horarios, colores | `negocio.toml` |
| El logo del panel instalable | `app/marca/logo.png` |
| Tokens, claves y credenciales | `.env` (plantilla en `.env.example`) |
| Qué responde el bot y en qué orden (el flujo) | `app/bot/bot_logic.py` |
| Cómo se envía un mensaje a WhatsApp | `app/bot/whatsapp_client.py` |
| El comportamiento de la IA (plan Pro) | `app/bot/cerebro/gemini.py` |
| Tablas y columnas de la base de datos | `app/core/database.py` |
| El aspecto o las funciones del panel del dueño | `app/web/admin_ui.py` |
| Los colores del panel | `[marca] color` en `negocio.toml` (el panel se tiñe solo) |
| Cómo se manejan imágenes y notas de voz | `app/core/media.py` |
| Cómo se calculan los huecos libres o se crea la cita | `app/integrations/calendar_service.py` |
| Qué columnas se escriben en el Google Sheet | `app/integrations/sheets_service.py` |
| Rutas HTTP nuevas / arranque del servidor | `app/main.py` |
| La configuración del despliegue | `render.yaml` · `Dockerfile` |

### El mapa completo

#### `app/` — el motor (lo que corre en producción)

```
app/
├── main.py                  Servidor FastAPI. Recibe el webhook de Meta, monta los
│                            routers y arranca/apaga todo. Rutas: GET / (salud),
│                            GET /webhook (verificación) y POST /webhook (mensajes)
├── config.py                Solo MECÁNICA: lee negocio.toml y el .env, valida y
│                            expone los valores derivados. Sin contenido de negocio
│
├── bot/                     ── LA CONVERSACIÓN ──
│   ├── bot_logic.py         Máquina de estados: capta nombre → pregunta necesidad →
│   │                        vende, agenda o deriva a un humano. El corazón del bot
│   ├── whatsapp_client.py   Enviar mensajes por la Cloud API de Meta (texto, botones,
│   │                        listas). No sabe nada del negocio
│   ├── notificaciones.py    Avisos al dueño. Si la ventana de 24 h está cerrada,
│   │                        reintenta con plantilla en vez de fallar en silencio
│   └── cerebro/             Qué hacer cuando el cliente ESCRIBE en vez de tocar el menú
│       ├── base.py          La interfaz (`Decision`). Lo ÚNICO que bot_logic conoce
│       ├── menu.py          Plan Básico: no decide nada. El bot de siempre
│       └── gemini.py        Plan Pro: el ÚNICO archivo del repo que sabe que Gemini
│                            existe. Por eso los dos planes son un solo código
│
├── core/                    ── PIEZAS TRANSVERSALES ──
│   ├── database.py          Modelos y sesiones (Contact, Lead, ProcessedMessage,
│   │                        PushSubscription), migración del esquema y SQLite en WAL
│   ├── message_log.py       Historial de ida y vuelta de cada chat + la ventana de 24 h
│   ├── ajustes.py           Lo que el dueño cambia desde el panel y sobrevive al
│   │                        redeploy (hoy: Básico ↔ Pro)
│   ├── eventos.py           Bus en memoria: reparte cada mensaje nuevo a los paneles
│   │                        abiertos (SSE). Por eso el server corre en un solo proceso
│   ├── push.py              Notificación al celular aunque el panel esté cerrado (VAPID)
│   └── media.py             Imágenes y notas de voz: bajarlas de Meta, subirlas,
│                            cachearlas un día y convertir el audio a OGG/Opus
│
├── integrations/            ── SERVICIOS EXTERNOS (todos fallan "hacia fuera") ──
│   ├── google_client.py     Credenciales de la cuenta de servicio y clientes de la API
│   ├── calendar_service.py  Huecos realmente libres y creación del evento. Nunca cachea
│   └── sheets_service.py    Una fila por lead, en la pestaña de su servicio. Solo de ida
│
├── web/                     ── TODO LO QUE SE SIRVE POR HTTP, ADEMÁS DEL WEBHOOK ──
│   ├── admin_ui.py          El panel del dueño: login, bandeja, hilo del chat, respuesta
│   │                        manual y canal en vivo. Rutas bajo /admin
│   ├── admin_api.py         API JSON con clave `X-Admin-Key`: /admin/takeover, /release,
│   │                        /plan, /status, /contacts
│   ├── paginas_publicas.py  /privacidad — Meta la exige para pasar la App a modo En vivo
│   └── pwa.py               /manifest.webmanifest, /sw.js e iconos: el panel instalable
│
└── marca/                   ── IDENTIDAD DEL CLIENTE ──
    ├── logo.png             Deja aquí el logo del negocio y el icono se genera solo
    └── README.md            Formatos aceptados y qué pasa si no dejas ninguno
```

#### `scripts/` — herramientas de puesta en marcha

Se corren **a mano y una sola vez**, desde tu máquina. Nada de `app/` importa
esta carpeta: el servidor no las necesita.

```
scripts/
├── meta_setup.py         Revisa/arregla el lado de Meta (token, número, suscripción, plantillas)
├── google_setup.py       Verifica que la cuenta de servicio pueda leer y escribir de verdad
├── gemini_setup.py       Comprueba la clave de IA y prueba mensajes antes de exponer el bot
├── push_setup.py         Genera el par de claves VAPID para los avisos al celular
├── panel_usuario.py      Alta y baja de quien entra al panel, si no hay /superadmin a mano
├── negocio_a_la_base.py  Copia un negocio.toml a la columna del cliente, validándolo antes
└── web_button.py         Genera el botón de WhatsApp (click-to-chat) para la web del negocio
```

#### `tests/` — la red de seguridad

Correr **las cuatro primeras** antes de cada despliegue. No tocan Meta, ni Google, ni
`bot.db`: usan una base temporal y sustituyen los envíos por falsos.

```
tests/
├── test_regresion.py    Lógica del bot de punta a punta (la suite grande)
├── test_panel.py        El panel por HTTP, con el servidor levantado de verdad
├── test_ia.py           Plan Pro, con un Gemini de mentira (incluye "si la IA se cae")
├── test_multitenant.py  Que lo de un cliente NO se mezcle con lo de otro (la que más vale)
└── test_rls.py          Que la BASE tampoco los mezcle. Pide PostgreSQL: sin él se salta sola
```

#### `docs/` — para retomar el proyecto

```
docs/
├── CONTINUAR_AQUI.md        EMPEZAR AQUÍ. Estado, trampas, cómo verificar y qué falta
├── META_VERIFICACION.md     El trámite de Meta, para leerlo sin saber de código
└── META_VERIFICACION.pdf    Lo mismo, en PDF (`scripts/pdf_de_documento.py` lo genera)
```

`CONTINUAR_AQUI.md` es **el único archivo que hay que leer para seguir**. Antes
ese papel se repartía entre seis, y tener seis sitios donde mirar significaba
que ninguno estaba al día.

#### La raíz

```
negocio.toml             EL archivo de contenido. Secciones: [negocio] [marca] [enlaces]
                         [horario] [conversacion] [ia] [precios] [textos] [avisos]
                         [origenes] [sheets] y [[menu]] con sus submenús
render.yaml              Despliegue en Render: un solo servicio sirve los dos planes,
                         con disco persistente en /var/data para que la base sobreviva
Dockerfile               Imagen para desplegar en cualquier otro sitio (VPS, Railway)
requirements.txt         Dependencias de Python
.env.example             Plantilla de credenciales, comentada. Cópiala a .env
CLAUDE.md                Instrucciones para asistentes de IA que trabajen en el repo
README.md                Este archivo
```

**Fuera del repositorio** (los genera o los pones tú, y están en `.gitignore`):
`.env` con las credenciales reales, `google-credentials.json` de la cuenta de
servicio, `bot.db` de la base local, `venv/` y `graphify-out/` con el grafo de
conocimiento.

Todos los comandos de este README se corren **desde la raíz del proyecto**
(la carpeta que contiene `app/`).

## Pruebas

Antes de desplegar cualquier cambio:

```bash
python tests/test_regresion.py   # lógica del bot
python tests/test_panel.py       # panel de atención manual
python tests/test_ia.py          # plan Pro (con un Gemini de mentira)
```

Usa una base SQLite temporal y no llama a la API de Meta (reemplaza las funciones
de envío por unas que solo anotan lo que se habría mandado), así que se puede
correr las veces que haga falta sin gastar mensajes ni tocar `bot.db`. Devuelve
código de salida 1 si algo falla.

Tampoco llama a Google: el agendamiento y el Sheet se prueban simulados, así que
no crea eventos ni filas reales.

Cubre (328 verificaciones de lógica + 244 del panel + 68 de la IA): la migración de
la base, el menú de servicios y sus submenús, los límites de texto de WhatsApp, el
flujo completo de captación, el recorrido del cliente y a qué pestaña del Sheet va
cada fila, el cálculo de horarios libres, el agendamiento con sus casos límite
(doble-booking, día lleno, sin disponibilidad, Google caído), la deduplicación, la
detección de origen, la toma de control manual con sus tres disparos y sus dos
formas de liberación, la autenticación de `/admin`, el generador del botón web, la
validación de firma del webhook, y las imágenes y notas de voz (incluida la
conversión de audio de verdad, sin simularla).

Para probar contra Google **de verdad** (crea y borra un evento real):

```bash
python scripts/google_setup.py check
```

## 1. Requisitos previos en Meta

1. Crea una cuenta en [Meta for Developers](https://developers.facebook.com/) y una App tipo "Business".
2. Dentro de la App, agrega el producto **WhatsApp**.
3. En "API Setup" obtienes: un **token de acceso temporal** (o genera uno permanente
   con un System User), y el **Phone Number ID** de tu número de pruebas.
4. Ahí mismo defines la URL de tu webhook y un **Verify Token** (una palabra
   que tú inventas, debe coincidir con `VERIFY_TOKEN` en tu `.env`).

## 2. Instalación local

```bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edita .env con tus datos reales (token, phone number id, número del dueño)
```

> **No borres la línea `DATABASE_URL=sqlite:///./bot.db` de tu `.env`.** El valor
> por defecto del código apunta al disco del servidor (`/var/data/bot.db`), que
> en producción es lo correcto pero en tu máquina no existe: sin esa línea el bot
> no arranca en local y falla con `unable to open database file`.
>
> No afecta a producción: `.env` no se versiona ni entra al contenedor, y en el
> hosting las variables se definen en su panel.

## 3. Correr el servidor

```bash
uvicorn app.main:app --reload --port 8000
```

Para que Meta pueda llegar a tu máquina local durante pruebas, expón el puerto
con un túnel, por ejemplo [ngrok](https://ngrok.com/):

```bash
ngrok http 8000
```

Copia la URL pública que te da ngrok (algo como `https://xxxx.ngrok-free.app`)
y en Meta for Developers, en la configuración del webhook, pon:
- **Callback URL**: `https://xxxx.ngrok-free.app/webhook`
- **Verify Token**: el mismo que pusiste en tu `.env`

Suscríbete al campo `messages` para empezar a recibir mensajes entrantes.

## 4. Personalizar para un negocio nuevo

El camino normal **no pasa por aquí**: se da de alta el negocio en
`/superadmin` (§14) y se editan sus textos, su menú, sus precios y su horario
desde el navegador, en su editor de contenido. Se guarda validado y **está en
vivo al instante**, sin desplegar y sin reiniciar nada.

**`negocio.toml` es la plantilla.** De ahí parte el contenido de cada cliente
nuevo el día que se le da de alta; a partir de ese momento el negocio lee **su
propia copia**, guardada en la base (`clients.negocio_config`), y editar el
archivo ya no le afecta. El archivo está comentado paso a paso, con los límites
de WhatsApp y las trampas de formato anotadas donde hacen falta, así que sigue
siendo el sitio donde entender qué significa cada cosa — y donde cambiar de qué
parten los clientes nuevos.

Dos caminos más, para cuando el editor no llega:

```bash
python scripts/negocio_a_la_base.py <cliente> --ver   # qué tiene guardado hoy
python scripts/negocio_a_la_base.py <cliente>         # copiarle este negocio.toml
```

Sirven para las dos secciones que el editor todavía no cubre —las pestañas del
Sheet (`[sheets.pestanas]`) y los orígenes (`[origenes]`)— y para arrancar un
cliente desde un TOML preparado a mano.

> **Mientras un cliente no tenga su contenido en la base**, lee las variables
> de entorno del proceso, que son del despliegue y no suyas. Es la rampa que
> queda de antes de la migración, y hoy solo la usa el cliente por defecto.

Si nombras un enlace o unos precios que no existen, no se guarda nada y se dice
cuál falla — al arrancar si fue en `negocio.toml`, y en la pantalla si fue en el
editor. Un mensaje en blanco no llega nunca a un cliente.

En `app/config.py` queda solo la mecánica (credenciales, límites técnicos, las
funciones que arman los valores derivados). Resuelve al negocio de cada
petición, así que `bot_logic.py` no se entera de nada.

### 4.1 Cómo se define el menú

Cada entrada `[[menu]]` de `negocio.toml` es un servicio, y su clave `accion`
decide qué hace el bot cuando el cliente la elige:

| `accion` | Qué hace |
|---|---|
| `submenu` | Abre otro grupo de opciones (las de su clave `submenu`) |
| `info` | Manda un texto y después vuelve a ofrecer opciones (las de `luego`) |
| `enlace` | Manda un enlace y deja el menú abierto |
| `cita` | Arranca el agendamiento con Google Calendar |
| `humano` | Pasa la conversación a un asesor y calla al bot en ese chat |

**El formato lo elige el bot solo**: hasta 3 opciones las manda como botones,
visibles en el chat; de 4 en adelante como lista desplegable, que obliga al
cliente a un toque más para abrirla.

**Límites de texto de WhatsApp.** Si te pasas, WhatsApp corta la palabra por la
mitad sin avisar, o rechaza el envío entero. Las pruebas fallan si algún texto
se pasa, así que te enteras antes de desplegar:

| | Máximo |
|---|---|
| Título de un botón | 20 caracteres (y **no** tiene descripción) |
| Título de una fila de lista | 24 caracteres |
| Descripción de una fila | 72 caracteres |
| Opciones por lista | 10 filas |
| Botones por mensaje | 3 |
| Un mensaje de texto | 4.096 caracteres |

Dos claves más que ayudan al montar un menú:

- **`oculta`**: la opción existe y se llega a ella desde el `luego` de otra, pero
  no gasta uno de los tres botones del menú donde vive. Así se puede ofrecer
  "Ver un ejemplo" justo después de los precios, que es cuando más pesa.
- **Contenido vacío**: una opción de `enlace` o `info` sin su URL o sin su texto
  **no se muestra**. Puedes dejarla escrita y aparece sola el día que la llenes,
  en vez de mandar a un cliente a un enlace que no es lo que le prometiste.
- **`enlace` y `precios` van por nombre**, no repitiendo el contenido: `enlace =
  "precios"` busca esa clave en `[enlaces]`, y `precios = "chatbot"` busca ese
  texto en `[precios]`. Así se cambia una URL en un sitio y vale para todas las
  opciones que la usen.

### 4.2 Los asteriscos en los textos

En WhatsApp `*texto*` es **negrita**, no una viñeta. Si empiezas varias líneas
con `* `, WhatsApp empareja unos asteriscos con otros y pone en negrita todo lo
que quede en medio. Usa `•` para las viñetas y reserva `*` para resaltar a
propósito. Hay una prueba que lo vigila.

## 5. Pasar a producción (número real + token permanente)

### 5.1 Registrar el número real en la WABA

En **business.facebook.com** → Configuración del negocio → Cuentas → Cuentas de
WhatsApp → tu WABA → *Números de teléfono* → **Agregar número de teléfono**.

- El número **no puede estar activo en la app de WhatsApp normal ni en WhatsApp
  Business**. Si lo está, primero hay que borrar esa cuenta desde la app
  (Ajustes → Cuenta → Eliminar mi cuenta). Si no, la verificación falla.
- Meta pide un *nombre para mostrar* que pasa por aprobación (suele tardar
  minutos, a veces horas). Debe corresponder al negocio real.
- Verificación por SMS o llamada al número.

Una vez registrado, copia su **Phone Number ID** (no el número) a `PHONE_NUMBER_ID`
en `.env`, y el **ID de la WABA** a `WABA_ID`.

### 5.2 Token permanente vía System User

El token que aparece en *API Setup* dura 24h y no sirve en producción.

1. business.facebook.com → Configuración del negocio → **Usuarios → Usuarios del
   sistema** → *Agregar*. Nombre: ej. `bot-whatsapp`. Rol: **Administrador**.
2. En ese usuario: **Agregar activos** → *Cuentas de WhatsApp* → selecciona tu
   WABA → activa **Control total**.
3. También **Agregar activos** → *Apps* → tu App → **Control total**.
4. **Generar nuevo token** → elige tu App → marca los permisos
   `whatsapp_business_messaging` y `whatsapp_business_management` →
   caducidad **Nunca**.
5. Copia el token (se muestra **una sola vez**) a `WHATSAPP_TOKEN` en `.env`.

### 5.3 App Secret (firma del webhook)

En developers.facebook.com → tu App → **Configuración → Básica**: copia el
**Identificador de la app** a `APP_ID` y el **Clave secreta de la app** a
`APP_SECRET` en `.env`.

Con `APP_SECRET` definido, `app/main.py` valida la cabecera `X-Hub-Signature-256` de
cada webhook entrante y rechaza lo que no venga firmado por Meta. Sin esto,
cualquiera que descubra tu URL pública puede inyectar mensajes falsos.

### 5.4 Suscribir la WABA a la App

Meta a veces **no** hace este paso solo desde la UI, y sin él el webhook queda
configurado pero nunca llega ningún mensaje:

```bash
python scripts/meta_setup.py subscribe
```

### 5.5 Verificar todo

```bash
python scripts/meta_setup.py check
```

Revisa: variables presentes, token válido **y sin fecha de expiración**, permisos
correctos, que `PHONE_NUMBER_ID` pertenezca a la WABA, y que haya una App suscrita.

### 5.6 Webhook definitivo

En developers.facebook.com → tu App → WhatsApp → **Configuración → Webhooks**:
- **Callback URL**: `https://tu-dominio-definitivo/webhook`
- **Verify token**: el mismo valor de `VERIFY_TOKEN` en `.env`
- Suscríbete al campo **`messages`**

Con el número real ya no hay lista de destinatarios pre-verificados: cualquier
cliente puede escribir. Falta definir el hosting con HTTPS permanente (Render,
Railway o un VPS) para no depender de ngrok.

### 5.7 Base de datos

En local no toques nada: usa un archivo SQLite (`bot.db`) y funciona solo.

En el servidor la base va en un **disco** que sobrevive a los despliegues.
`render.yaml` ya lo trae configurado y no hay que hacer nada (§11.4). Solo hace
falta Postgres si algún cliente creciera mucho, y en ese caso basta con definir
`DATABASE_URL` en el panel del hosting: el código no cambia.

> ⚠️ Lo que **no** puede hacerse es dejar SQLite sin disco en el servidor: ahí sí
> el archivo se borra en cada redeploy y perderías contactos y conversaciones.

**El historial se limpia solo.** Al arrancar el servicio se borran las
conversaciones más viejas que `HISTORIAL_DIAS`:

| Variable | Por defecto | Qué hace |
|---|---|---|
| `HISTORIAL_DIAS` | 180 | Días de conversación que se guardan. En `0` no borra nada |

Sin esto la tabla de mensajes crece para siempre, y el disco es justamente lo que
se paga en el hosting. **Los leads y las citas no se tocan**: viven en su propia
tabla y en el Google Sheet. Lo que se borra es el texto de conversaciones de hace
medio año, que ya nadie va a abrir en el panel.

## 6. Toma de control manual (atendido por humano)

Cuando un contacto queda marcado como *atendido por humano*, el bot **deja de
responderle**: el mensaje llega, se registra, y ahí se queda para que una persona
conteste a mano desde WhatsApp Manager sin que el bot escriba encima.

### 6.1 Cómo se activa

Hay tres caminos, y los tres dejan el contacto en estado `HUMANO`:

| Camino | Cuándo |
|---|---|
| **Palabra clave** | El cliente escribe algo de `HUMAN_TAKEOVER_KEYWORDS` en cualquier punto del flujo ("quiero hablar con un asesor", "atención humana"...). Se compara sin tildes ni mayúsculas. |
| **Rama "Otra consulta"** | Al terminar esa rama, si `TAKEOVER_ON_OTHER_QUERY = True` (por defecto). |
| **Manual** | `POST /admin/takeover` desde el panel o con curl. |

En los dos primeros, el dueño recibe un WhatsApp avisándole que ese número quedó
esperando respuesta humana.

### 6.2 Cómo vuelve el bot

- **Automático**: cuando la conversación lleva `HUMAN_TAKEOVER_TIMEOUT_MINUTES`
  (180 por defecto, o sea 3 horas) sin que se mueva nada. Esto evita que un
  contacto quede mudo para siempre si nadie lo desmarca.
- **Manual**: el botón del panel, o `POST /admin/release`.

El contador se mide desde **lo último que pasó, venga de quien venga**: el último
mensaje del cliente, tu última respuesta manual, o el momento en que se tomó la
conversación. Es decir, el bot solo vuelve cuando **los dos lados** llevan ese
rato callados. Mientras cualquiera de los dos escriba, no interrumpe.

Medirlo solo por tu última respuesta salía caro: si tardabas más de la cuenta y
el cliente contestaba después, el bot se despertaba **en medio** de la
conversación. Medirlo solo por el cliente tenía el problema opuesto: quien
insistía cada pocos minutos dejaba al bot mudo para siempre.

Al soltarla, la conversación queda en estado `DONE`, no `NEW`. La diferencia se
nota cuando el cliente vuelve a escribir: en vez de saludarlo desde cero
("¿cómo te llamas?") a alguien cuyo nombre ya sabemos, lo reconoce y le ofrece el
menú. Si tenía una cita, lo pasa otra vez a un asesor.

### 6.3 El panel: leer y responder a mano

WhatsApp Manager no sirve como bandeja de atención, y los servicios de terceros
(Chatwoot, Wati, Callbell) cobran suscripción. El proyecto trae su propia bandeja
mínima, sin dependencias externas:

```
https://tu-dominio/admin/inbox
```

**Cómo sabe el panel de qué negocio eres.** Hay dos formas, y la variable
`DOMINIO_BASE` elige:

- **Vacía (lo habitual):** todos los negocios comparten la misma dirección y el
  formulario pide **`Negocio` + `Clave`**. El nombre del negocio es su
  identificador corto (`panaderia`), y se perdonan mayúsculas, tildes y
  espacios. Dejarlo en blanco entra al cliente por defecto, para que el dueño
  del bot siga entrando solo con su clave mientras sea el único. No cuesta ni un
  dominio ni una línea de DNS.
- **Con valor:** cada cliente entra por su subdominio (`panaderia.tudominio.com`)
  y el formulario vuelve a pedir solo la clave, porque la dirección ya dice quién
  es. Es más sólido —cada negocio con su propio origen, su propia cookie y su
  propia app instalable— pero exige dominio y DNS.

Se puede cambiar de una a otra sin tocar código.

Cada negocio tiene sus propias claves de acceso, en la tabla `panel_users`. Se
crean con:

```bash
python scripts/panel_usuario.py crear 1 tu@correo.com   # 1 = id o slug del cliente
python scripts/panel_usuario.py listar 1
python scripts/panel_usuario.py baja 1 tu@correo.com
```

Mientras el **primer** cliente (el dueño del bot) no tenga ninguno, sigue
entrando con `ADMIN_API_KEY`, como siempre. En cuanto se le crea un usuario, esa
rampa se apaga. Los demás clientes nunca entran con esa clave: es una variable de
entorno del proceso, o sea la misma para todos, y por eso no puede ser la
contraseña de nadie.

La sesión queda en una cookie `HttpOnly` que **no contiene ninguna clave**, sino
un pase firmado que caduca solo. El pase dice de qué negocio y de qué usuario es,
y se rechaza si se presenta en el panel de otro cliente.

#### El panel se tiñe con la marca del cliente

Todo el color sale de un puñado de variables CSS (`:root`), y el acento es
**`[marca] color` de `negocio.toml`**: los botones, las burbujas que salen del
negocio, la conversación activa y el anillo de foco. Cambias esa línea y el panel
entero cambia de color — es lo que hace que no parezca una herramienta genérica
con el nombre del cliente encima.

El color del texto sobre ese acento **se calcula solo** según su brillo
(`config.color_legible_sobre`): con una marca amarilla, las letras de los botones
se vuelven oscuras en vez de desaparecer.

El modo oscuro solo redefine esas variables, no las reglas. Los semáforos de
estado (urgente / esperando / terminado) sí llevan color propio a propósito: un
semáforo que cambia de color según el cliente no serviría de nada.

Al pie se lee **"Creado por Nitro 2Tech"**. Sale de `[marca] creado_por`, y quien
revenda el bot con su nombre lo cambia ahí o lo deja vacío para quitarlo.

**Caducidad de la sesión:**

| Variable | Por defecto | Qué hace |
|---|---|---|
| `PANEL_SESION_INACTIVIDAD_HORAS` | 5 | Horas sin usar el panel tras las cuales pide la clave otra vez |
| `PANEL_SESION_MAXIMA_HORAS` | 12 | Tope absoluto de una sesión, se use o no |

Es **deslizante**: mientras trabajes se renueva sola y no te echa en medio de una
conversación. Solo cuenta lo que haces tú (abrir la bandeja, abrir un chat,
enviar un mensaje); las consultas que el panel hace de fondo no la mantienen
viva, porque si no una pestaña olvidada no caducaría nunca.

El tope absoluto existe para que una pestaña abierta desde el lunes no siga
dentro el viernes. Si caduca con el panel abierto, la pantalla se va al login
sola en vez de quedarse sin actualizar en silencio.

Cambiar `SESSION_SECRET` invalida todas las sesiones de golpe, de todos los
clientes — es la forma de echar a un dispositivo perdido. (Si esa variable está
vacía, la firma se deriva de `SECRETS_KEY` y es esa la que hay que rotar. Antes
este papel lo hacía `ADMIN_API_KEY`, que ya no firma nada.)

Dar de baja a un usuario le cierra el paso al entrar, pero **no le corta la
sesión en curso**: esa muere sola con el plazo de inactividad. Comprobar la
tabla en cada petición costaría una consulta por latido del canal en vivo.

**Freno a los intentos de clave:** tras `PANEL_MAX_INTENTOS_LOGIN` fallos (8) se
bloquea esa IP durante `PANEL_BLOQUEO_LOGIN_MINUTOS` (15). El contador vive en
memoria: se borra al reiniciar el servicio, que para esto sobra.

**Qué puedes hacer:**

- Ver todas las conversaciones, con el último mensaje de cada una
- Abrir un hilo y leerlo completo: lo que escribió el cliente, lo que respondió el
  bot, y qué botón tocó en cada paso
- **Escribir una respuesta y enviarla por WhatsApp** desde ahí mismo
- Devolver la conversación al bot con un botón

Al enviar un mensaje, la conversación **se marca sola como atendida por humano**:
el bot se calla para no escribir encima de ti. No hay que acordarse de pausarlo.

Se ve bien en el celular, que es desde donde vas a responder casi siempre.

**Los mensajes aparecen al instante.** El servidor los empuja al panel en cuanto
los guarda, por un canal que queda abierto (`/admin/api/stream`). No hay que
refrescar ni esperar a ningún ciclo, y mientras no pasa nada no cuesta ni una
consulta a la base — antes se preguntaba cada 3 segundos y cada pregunta salía
cara.

Si ese canal no funciona (redes que cortan las conexiones largas, algún proxy),
el panel se da cuenta y vuelve solo al método antiguo de preguntar cada pocos
segundos. Más lento, pero nunca te quedas sin ver los mensajes.

Cada canal abierto queda apuntado **a su negocio** y solo recibe los mensajes de
ese negocio, aunque haya varios paneles de varios clientes escuchando a la vez.

> ⚠️ Esto depende de que el servidor corra en **un solo proceso**, que es como
> lo arrancan `render.yaml` y el `Dockerfile`. Si alguien añade `--workers`, los
> mensajes dejan de repartirse bien. Está avisado en los dos archivos.

### 6.4 La ventana de 24 horas

WhatsApp solo permite responder texto libre **dentro de las 24 horas** siguientes
al último mensaje del cliente. Pasado ese plazo hace falta una plantilla aprobada
por Meta, y un envío normal falla con el error `131047`.

El panel lo muestra siempre: te dice cuántas horas quedan, y si la ventana se
cerró esconde el formulario y te explica por qué en vez de dejarte escribir un
mensaje que va a fallar.

En la bandeja, las conversaciones con la ventana cerrada llevan una etiqueta roja.

### 6.5 Endpoints (API JSON)

Todos piden la cabecera `X-Admin-Key` con el valor de `ADMIN_API_KEY`. Si esa
variable está vacía, los endpoints responden 503 (deshabilitados) — así no quedan
abiertos a internet por olvido. Genera una clave con:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

```bash
# Silenciar al bot en una conversación
curl -X POST https://tu-dominio/admin/takeover \
     -H "X-Admin-Key: TU_CLAVE" -H "Content-Type: application/json" \
     -d '{"phone": "573001234567"}'

# Devolvérsela al bot
curl -X POST https://tu-dominio/admin/release \
     -H "X-Admin-Key: TU_CLAVE" -H "Content-Type: application/json" \
     -d '{"phone": "573001234567"}'

# Ver quién está siendo atendido a mano
curl "https://tu-dominio/admin/contacts?solo_humanos=true" -H "X-Admin-Key: TU_CLAVE"
```

### 6.6 Deduplicación de mensajes

Meta reintenta el webhook si el servidor tarda o falla, reenviando el **mismo**
mensaje. La tabla `processed_messages` guarda el ID de cada mensaje ya atendido
para no contestar dos veces ni duplicar leads. Se limpia sola al arrancar,
borrando los de más de 7 días.

### 6.7 Instalar el panel en el celular

El panel se instala como una app, con icono propio y sin barra de direcciones.
No hay que compilar nada ni pasar por la App Store: aparece solo al desplegar.

**Cómo se instala:**

| | |
|---|---|
| **Android (Chrome)** | Abrir `https://tu-dominio/admin/inbox` → menú ⋮ → *Instalar aplicación* |
| **iPhone (Safari)** | Abrir la misma dirección → botón compartir → *Añadir a pantalla de inicio* |

En iPhone tiene que ser **Safari**: Chrome en iOS no ofrece instalar.

**Cómo ponerle la cara del negocio** (todo opcional, funciona sin tocar nada):

| Variable | Por defecto | Qué hace |
|---|---|---|
| `APP_NOMBRE` | `<negocio> · Conversaciones` | Lo que se lee al instalar |
| `APP_NOMBRE_CORTO` | el nombre del negocio | Lo que va debajo del icono (~12 caracteres) |
| `MARCA_COLOR` | `#16a34a` | Barra de estado del celular y fondo del icono |
| `MARCA_COLOR_FONDO` | `#f6f7f9` | Pantalla de arranque |

**El icono**: si dejas el logo del negocio en `app/marca/logo.png` se usa ese; si
no, se dibuja con las iniciales sobre el color de marca. Un logo con fondo
transparente se pega centrado sobre el color de marca; uno que ya trae su propio
fondo se usa a sangre, ocupando el icono entero. Los detalles, en
`app/marca/README.md`.

Se genera una vez y queda en memoria, así que al cambiar el logo hay que
**reiniciar el servicio**.

> 🔒 **El service worker no guarda NADA de `/admin/`.** Solo el manifiesto y los
> iconos. Cachear el HTML del panel dejaría la pantalla de un cliente guardada en
> el celular, y podría reaparecer después de cerrar sesión. Si algún día hay que
> tocar `app/web/pwa.py`, esa es la regla que no se puede romper.

Instalado sigue siendo la misma web: la sesión caduca igual (§6.3) y los mensajes
llegan al instante por el mismo canal en vivo. **No hay notificaciones push** —
hay que abrir la app para ver lo nuevo.

### 6.8 Imágenes y notas de voz

El panel funciona como un chat de WhatsApp: se ven las imágenes y los audios que
manda el cliente, y se le pueden mandar imágenes y notas de voz a mano.

**El bot no manda archivos por su cuenta y tampoco los interpreta.** Gemini no ve
las imágenes ni transcribe los audios: eso multiplicaría el coste por mensaje y no
es lo que hace falta. Quien mira la foto es una persona.

#### Lo que pasa cuando el cliente manda algo

El archivo queda en el historial, dispara el aviso al celular (§6.7) y el bot
responde con dos botones:

> ¡Recibimos tu imagen! 📷 Un asesor la revisará.
> ¿Te ayudamos con algo más mientras tanto?
>
> **[ Ver el menú ]  [ Hablar con asesor ]**

**No se silencia al bot automáticamente.** Si el cliente solo mandaba una foto de
referencia y quería seguir viendo precios, callar al bot lo dejaría esperando. Solo
se pasa a una persona si toca el segundo botón. Los textos y los botones salen de
`[textos]` en `negocio.toml` (`media_imagen`, `media_boton_menu`…).

#### Lo que puedes mandar tú desde el panel

- **📎 Imagen** — el selector ofrece galería, explorador de archivos y hacer una
  foto (en el celular). **Nada se envía hasta confirmarlo**: la imagen se abre
  primero en una ventana sobre el chat, con un campo para el comentario y los
  botones *Enviar* y *Cancelar*. Mandarle la foto equivocada a un cliente no se
  puede deshacer.
- **🎤 Nota de voz** — **mantén pulsado** el micrófono para grabar y **suelta para
  enviar**, como en WhatsApp.
  - **Arrastra a la izquierda** sin soltar y la grabación se cancela.
  - **Arrastra hacia arriba** y el botón se queda pulsado solo: puedes levantar el
    dedo, y luego un toque envía o *Descartar* la tira.
  - A los 5 minutos se corta y se envía lo grabado, para que una grabación
    olvidada no choque contra el tope de 16 MB de Meta.

#### La barra de escribir

A la derecha hay **un solo botón**, no dos: con la caja vacía es el micrófono, y
en cuanto escribes algo pasa a ser el avión de enviar.

Mientras grabas, el clip y la caja de texto se apartan y en su sitio aparece:

```
 🎤  0:07   ‹ Desliza para cancelar                    [🎤]
 ^rojo,     ^contador                                   ^el que tienes pulsado
  latiendo
```

El micrófono rojo mide lo mismo que el botón del clip, y la caja del contador lo
mismo que la de escribir: ocupan su sitio exacto, sin que la barra pegue un salto
de tamaño al empezar a grabar.

Cuando te vas hacia arriba a leer mensajes viejos aparece una **flecha hacia
abajo** flotando sobre el hilo, justo encima del micrófono: te devuelve al último
mensaje de un toque. Con la conversación al día no se ve.

El micrófono de la derecha **no se mueve mientras grabas**, y eso no es estético:
es el botón que tienes bajo el dedo. Si desapareciera, el navegador perdería la
captura del puntero y "soltar para enviar" dejaría de funcionar.

#### Los límites los pone Meta, no el bot

| | Lo que acepta |
|---|---|
| Imagen | **solo JPEG y PNG**, 8 bits, máx **5 MB** |
| Nota de voz | **OGG/Opus mono** *y* `"voice": true` en el envío. Máx 16 MB, pero ver abajo |
| Documento | PDF, Office, txt — se reciben y se ven; enviarlos no está montado |

> ⚠️ **Para que se vea como nota de voz hacen falta las dos cosas.** Con el formato
> correcto pero sin la bandera `voice`, Meta acepta el envío, el cliente lo recibe
> y lo puede reproducir… como un archivo adjunto. Se ve bien en los logs y mal en
> el teléfono, que es la peor combinación. Aquí ya van las dos.

> ⚠️ **El botón de reproducir solo aparece hasta 512 KB.** Por encima, WhatsApp lo
> cambia por uno de descarga y deja de parecer una nota de voz. Por eso se graba a
> 16 kbps mono, que es lo que usa el propio WhatsApp: se entiende igual y da para
> más de cuatro minutos antes de llegar al tope. Si te pasas, el panel te avisa.

Las dos conversiones que hacen falta se hacen solas en el servidor y no hay que
saber que existen:

- **Las fotos de iPhone llegan en HEIC** y los editores a veces dan PNG de 16 bits.
  Meta los rechaza con un error que no dice cuál de las tres cosas falló. Pillow los
  convierte a JPEG y los comprime si pasan de 5 MB.
- **Ningún navegador graba en OGG/Opus**: Chrome graba WebM (que Meta ni siquiera
  acepta) y Safari graba MP4/AAC (que se vería como adjunto). PyAV los convierte.
  Su rueda de PyPI trae ffmpeg dentro, así que **no hay que instalar nada por `apt`
  ni pasar el despliegue a Docker**.

Si el conversor faltara, la nota de voz **se envía igual** —como archivo de audio,
para no dejarte sin responder— pero el panel te lo dice en vez de callárselo.
`GET /admin/status` trae un bloque `archivos` que confirma si el servidor puede
convertir, y con qué versión.

#### Dónde se guardan (y por qué se borran al día siguiente)

**El disco es solo un caché.** Meta conserva 7 días todo lo que entra por el
webhook, así que el bot no necesita guardar nada más que un rato:

1. Cuando llega el webhook **no se descarga nada**, solo se anota el id. Bajar 5 MB
   mientras Meta espera el `200` es pedir que dé el webhook por fallido y lo
   reintente — y además así las fotos que nadie mira nunca tocan el disco.
2. Al abrir la conversación, el panel baja el archivo y lo guarda.
3. **Al día siguiente se borra** (`MEDIA_CACHE_DIAS`). Si vuelves a abrir esa
   conversación, se baja otra vez de Meta y no notas nada.
4. Pasados los 7 días de Meta, la burbuja sigue ahí y dice *"📷 Imagen — ya no
   disponible"*. **El registro y el aviso nunca se pierden**, solo el archivo.

Por eso cada burbuja tiene un botón **Guardar**: lo que te importe, bájalo. Con
5 MB por imagen harían falta unas 200 imágenes vistas el mismo día para llenar el
disco de 1 GB, y hay un tope duro (`MEDIA_CACHE_MB`, 200 por defecto) que borra lo
más viejo antes de que a la base le falte sitio.

Las imágenes se sirven desde `GET /admin/media/{id}`, **detrás de la sesión del
panel**. Son fotos que alguien mandó por privado —una factura, una cédula, el
interior de su casa— y no pueden quedar en una URL abierta.

## 7. Botón de WhatsApp para la página web

Un enlace *click-to-chat* (`https://wa.me/...`) abre WhatsApp con la conversación
ya empezada, y de ahí responde el mismo bot. No hace falta un widget de chat ni
JavaScript de terceros.

Llena `BUSINESS_WHATSAPP_NUMBER` en `.env` (el número **visible** del negocio,
formato internacional sin `+`) y genera el HTML:

```bash
python scripts/web_button.py                     # muestra los dos snippets y el enlace
python scripts/web_button.py --flotante          # solo el botón fijo en la esquina
python scripts/web_button.py --en-linea          # solo el botón para una sección
python scripts/web_button.py --enlace            # solo la URL (sirve para un QR o la bio de Instagram)
python scripts/web_button.py --origen instagram  # botón de otro canal
python scripts/web_button.py -o boton.html       # página de ejemplo para ver cómo queda
```

Copias la salida y la pegas en el sitio: el flotante justo antes de `</body>`, el
otro donde quieras que aparezca. El número y el mensaje inicial salen de
`app/config.py`, así que no hay que escribirlos a mano en cada página.

El logo de WhatsApp va embebido como SVG dentro del snippet: no carga imágenes de
servidores externos, así que no se rompe si un CDN cae ni rastrea a tus visitantes.

### 7.1 De dónde llegó cada cliente

Cada canal tiene su propio mensaje precargado, definido en `config.ORIGENES`:

| Origen | Frase que lo identifica |
|---|---|
| `web` | "vengo de la página web" |
| `instagram` | "los vi en Instagram" |
| `qr` | "escaneé su código QR" |

Cuando llega un mensaje que contiene una de esas frases, el bot guarda el canal en
`Contact.origen`. Ese dato aparece en la notificación al dueño, en
`GET /admin/contacts`, y va a ser una columna del Google Sheet.

Detalles de cómo funciona:

- Se compara **sin tildes ni mayúsculas**, así que da igual cómo lo escriba el cliente.
- **El primer origen conocido no se pisa.** Si alguien llegó por la web y meses
  después escribe desde el botón de Instagram, sigue contando como `web`. La idea
  es saber qué canal lo trajo la primera vez.
- Si el cliente **borra el mensaje precargado** antes de enviarlo, no hay nada que
  detectar y queda como `directo`. Es normal que pase con una parte de los
  visitantes: tómalo como un piso, no como el número exacto.

Para agregar un canal nuevo (una campaña, un volante con QR), basta con otra
entrada en `config.ORIGENES` y generar su botón con `--origen <clave>`.

Para cambiar el texto del botón, edita `WEB_BUTTON_LABEL` en `app/config.py`.

**Fuera de alcance:** un widget de chat en vivo embebido en la web (tipo
Intercom/Tidio) que no sea WhatsApp. Eso sería un canal aparte con su propio
backend, no es "conectar WhatsApp a la web".

## 8. Configuración de Google (Calendar + Sheets)

Setup previo que hay que dejar listo **antes** de programar la integración de
agenda y hojas de cálculo. Se hace una sola vez y sirve para las dos APIs.

### 8.1 Proyecto y APIs

1. Entra a [Google Cloud Console](https://console.cloud.google.com/) con la cuenta
   de Google **dueña del calendario del negocio**.
2. Crea un proyecto nuevo (ej. `nitro2tech-whatsapp-bot`).
3. **APIs y servicios → Biblioteca**: busca y habilita **Google Calendar API** y
   **Google Sheets API**. Ambas en el mismo proyecto.

### 8.2 Cuenta de servicio

1. **APIs y servicios → Credenciales → Crear credenciales → Cuenta de servicio**.
2. Nombre: ej. `bot-whatsapp`. No hace falta asignarle roles de IAM: los permisos
   reales se dan compartiendo el calendario y el sheet (paso 6.3).
3. Abre la cuenta creada → pestaña **Claves** → *Agregar clave* → *Crear clave
   nueva* → **JSON**. Se descarga un archivo.
4. Copia el email de la cuenta de servicio, con forma
   `bot-whatsapp@tu-proyecto.iam.gserviceaccount.com`.

Una cuenta de servicio **no es una persona**: no tiene calendario propio ni ve
nada por defecto. Solo accede a lo que le compartas explícitamente.

### 8.3 Compartir los recursos con la cuenta de servicio

- **Calendar**: calendar.google.com → el calendario del negocio → *Configuración y
  uso compartido* → *Compartir con determinadas personas* → agrega el email de la
  cuenta de servicio con permiso **"Hacer cambios en los eventos"**.
  En esa misma pantalla, más abajo, copia el **ID del calendario** →
  `GOOGLE_CALENDAR_ID` (es `primary` o algo tipo `abc123@group.calendar.google.com`).
- **Sheets**: crea el Google Sheet, botón *Compartir*, agrega el mismo email como
  **Editor**. El `GOOGLE_SHEETS_SPREADSHEET_ID` es el tramo de la URL entre
  `/d/` y `/edit`.

### 8.4 Guardar las credenciales

**Nunca** subas el JSON al repositorio (`.gitignore` ya lo bloquea). En local,
déjalo en la carpeta del proyecto y apunta la variable a su ruta; en el hosting,
pega el **contenido completo** del JSON como valor de la variable de entorno.

## 9. Agendamiento con Google Calendar

Cuando un cliente elige "Agendar una cita", el bot consulta la disponibilidad
**real** del calendario y crea el evento. No guarda texto libre.

### 9.1 Cómo se ve la conversación

```
Bot:  ¿Qué día te queda mejor? 📅
      [ Ver días ▾ ]  → Jueves 6 ago · 18 horarios disponibles
                        Viernes 7 ago · 18 horarios disponibles
                        Lunes 10 ago · 14 horarios disponibles

Cli:  (toca "Viernes 7 ago")

Bot:  Estos horarios están libres el Viernes 7 de agosto. ¿Cuál prefieres?
      [ 9:00 am ]  [ 9:30 am ]  [ 10:00 am ]

Cli:  (toca "9:30 am")

Bot:  ¡Cita agendada, Nico! 📅
      Te esperamos el Viernes 7 de agosto a las 9:30 am.
```

Cero texto libre: el cliente no puede pedir un horario que no exista.

### 9.2 Verificar la configuración

```bash
python scripts/google_setup.py check
```

Comprueba credenciales, y que la cuenta de servicio pueda **leer y escribir** en
el calendario y en el Sheet (crea y borra un evento y una pestaña de prueba).
Si falta compartir un recurso, Google responde 404 "no encontrado" en vez de un
error de permisos — el script lo traduce a lenguaje entendible.

### 9.3 Horario de atención

En `app/config.py` / `.env`:

| Variable | Qué hace |
|---|---|
| `BUSINESS_HOURS_START` / `_END` | Jornada. Los huecos se generan dentro de este rango |
| `APPOINTMENT_DURATION_MINUTES` | Duración de cada cita, y cada cuánto empieza un hueco |
| `BUSINESS_DAYS` (app/config.py) | Días laborables. `[0,1,2,3,4]` = lunes a viernes |
| `BUSINESS_TIMEZONE` | Sin esto los eventos se crean en UTC y aparecen corridos |
| `APPOINTMENT_MIN_NOTICE_MINUTES` | Anticipación mínima. Evita ofrecer una cita en 5 minutos |
| `APPOINTMENT_SEARCH_DAYS` | Cuántos días adelante se buscan huecos |

### 9.4 Cómo se evita el doble-booking

Tres capas, porque entre que el bot muestra un horario y el cliente lo toca pueden
pasar minutos:

1. La disponibilidad **nunca se guarda en caché**: se consulta a Google en cada paso.
2. Al elegir día, se vuelve a preguntar por los horarios de ese día — no se reutiliza
   lo que se calculó al armar la lista.
3. Justo antes de crear el evento se comprueba una última vez que el hueco siga
   libre. Si alguien se adelantó, el bot lo dice y ofrece los que quedan.

El `event_id` de Google se guarda en `Lead.google_event_id`, para poder mover o
cancelar la cita después sin buscarla a mano.

### 9.5 Si Google se cae

La cita **no se pierde**. El bot registra el lead como pendiente, le responde al
cliente que un asesor le confirma el horario, y te avisa por WhatsApp. Una API de
terceros caída no puede costarte un cliente.

## 10. Seguimiento en Google Sheets

Cada lead que genera el bot aparece como una fila del Sheet, separado por tipo,
en segundos y sin intervención manual.

### 10.1 Una pestaña por servicio

El bot **las crea solas** al arrancar, con sus encabezados. Si el Sheet está recién
hecho y solo tiene la pestaña por defecto vacía, la reaprovecha renombrándola.

| Pestaña | Columnas |
|---|---|
| Chatbots para WhatsApp | Fecha de contacto · Nombre · Teléfono · Recorrido · Mensaje · Origen · Estado |
| Tableros Power BI | *(las mismas)* |
| Páginas web | *(las mismas)* |
| Automatizaciones | *(las mismas)* |
| Otras consultas | *(las mismas)* — quien nunca llegó a elegir un servicio |
| Citas agendadas | Fecha de contacto · Nombre · Teléfono · Servicio · Recorrido · Día de la cita · Hora · Origen · Estado · ID del evento |

Se organiza por **servicio** y no por tipo de resultado, porque es como se mira
el negocio: cuántos preguntaron por tableros, no cuántos "leads de tipo venta".

Cada pestaña sale de la clave `sheet` de su opción en `NEED_OPTIONS`. Para
agregar un servicio nuevo basta con declarar su pestaña en `SHEETS_TABS` y
apuntarla desde la opción.

### 10.2 La columna Recorrido

Es la más útil y la que no tiene ningún CRM barato: guarda **por dónde pasó** cada
cliente dentro de ese servicio, en orden.

```
Vio precios > Vio ejemplos > Agendó reunión
Vio precios > Pidió asesor
Vio precios
```

Con eso ves dónde se cae la gente, no solo dónde acabó. Si veinte personas entran
a Power BI, quince ven precios y solo dos agendan, el problema está en el precio o
en lo que sigue después — y eso antes era invisible.

Si alguien cambia de servicio a media conversación, el recorrido empieza de cero:
mezclar los pasos de dos servicios daría una fila que no describe a nadie.

La columna **Origen** te dice por qué canal llegó cada cliente (`web`, `instagram`,
`qr`, `directo`) — ver §7.1.

### 10.3 Las citas salen dos veces

Una reunión agendada desde Power BI se escribe en **dos** pestañas: en "Citas
agendadas", para tenerlas todas juntas sin ir servicio por servicio, y en
"Tableros Power BI", para que ahí se vea el movimiento completo de ese servicio.

Es el mismo cliente en dos filas. **Si cuentas clientes sumando pestañas, los
duplicas.**

### 10.4 Es solo de ida

El Sheet es tu tablero: el bot no lo lee ni pisa lo que escribas. Puedes marcar
filas como confirmadas, agregar notas o colores, y no reordena columnas de una
pestaña que ya existe.

La única excepción es al **cancelar o reagendar** una cita: ahí el bot borra la
fila de esa reunión, en "Citas agendadas" y en la pestaña de su servicio. Si no,
el Sheet mostraría reuniones que ya no existen en el calendario y las cuentas del
mes saldrían infladas.

Si agregas una columna en `config.SHEETS_TABS`, añádela también a mano al final
de la fila de encabezados en el Sheet.

### 10.5 Detalles que evitan sorpresas

- Las filas se escriben en modo **RAW**. Con el modo "interpretado" de Sheets, la
  fecha se guardaba como su número de serie (`46240.0125`) y los teléfonos se
  convertían en números, perdiendo el cero inicial en los países que lo usan.
- La fecha va en formato **ISO** (`2026-08-06 14:30`), así ordenar esa columna
  da el orden cronológico real. Con `06/08/2026` no pasaría.
- **Un fallo del Sheet nunca corta una conversación.** Si Google no responde, el
  lead ya está en la base de datos y ya se notificó por WhatsApp; el error solo
  queda en los logs.

## 11. Hosting y despliegue

El bot no puede depender de `ngrok` + tu computadora encendida. Necesita una URL
HTTPS fija, que es la que se configura una sola vez en el webhook de Meta.

### 11.1 Lo que hay que hacer sea cual sea la plataforma

**La base tiene que sobrevivir al redeploy.** Hay dos formas y las dos valen:

- **Un disco** (lo que usa este proyecto): la base es un archivo SQLite en una
  carpeta que el hosting no borra. Es lo más barato con diferencia y a un negocio
  le sobra. En Render viene ya configurado en `render.yaml` (§11.4).
- **Postgres**: para un cliente con mucho volumen. Solo hay que poner su cadena
  de conexión en `DATABASE_URL`. `app/core/database.py` normaliza sola la URL que
  entregan los servicios de hosting, así que puedes pegarla tal cual venga —
  maneja tanto `postgres://` como `postgresql://`.

Lo que **no** vale es SQLite sin disco: ahí el archivo se borra en cada redeploy
y perderías contactos y conversaciones.

> Con SQLite, el código pone la base en modo **WAL** al conectarse. Hace falta
> porque el webhook, el panel y el canal en vivo la tocan a la vez, y sin eso el
> segundo en llegar recibe `database is locked`. Es automático, no hay que
> configurarlo.

**Variables de entorno en el panel del servicio**, nunca subiendo el `.env`:

```
WHATSAPP_TOKEN, PHONE_NUMBER_ID, WABA_ID, APP_ID, APP_SECRET,
VERIFY_TOKEN, OWNER_PHONE_NUMBER, BUSINESS_WHATSAPP_NUMBER,
ADMIN_API_KEY, DATABASE_URL
```

**Comando de arranque:**

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

`--host 0.0.0.0` es obligatorio: con el default (`127.0.0.1`) el proceso solo
escucha dentro del contenedor y el servicio lo marca como caído.

**Webhook en Meta** → `https://tu-dominio/webhook`, con tu `VERIFY_TOKEN`, suscrito
al campo `messages`. Esto ya no vuelve a cambiar.

### 11.2 Comprobación de salud

`GET /` devuelve `{"status": "ok"}`. Sirve como health check del hosting y para
conectar un monitor de uptime (UptimeRobot o similar) que te avise si el bot se
cae — con un número real de clientes, enterarte tarde cuesta ventas.

### 11.3 Con Docker

Hay un `Dockerfile` listo, válido para un VPS o para Render/Railway en modo Docker.
Corre como usuario sin privilegios y lee el puerto de `PORT`.

```bash
docker build -t nitro-bot .
docker run -p 8000:8000 --env-file .env nitro-bot
```

### 11.4 Desplegar en Render (paso a paso)

El repositorio trae un `render.yaml`, así que Render crea el servicio ya
configurado en vez de tener que llenar el formulario a mano.

1. **La base de datos no hay que crearla.** `render.yaml` declara un disco de
   1 GB en `/var/data` y pone la base ahí dentro. Se crea sola en el primer
   arranque y sobrevive a los despliegues.
   - **No crees un Postgres.** El gratuito de Render caduca a los 30 días y luego
     lo borran con los datos dentro; el de pago cuesta casi lo mismo que el
     servicio web entero, para guardar las conversaciones de un solo negocio.
2. **New → Blueprint** en el panel de Render, y conecta el repositorio. Render
   lee `render.yaml` y te pide las variables marcadas como secretas.
3. **Pega las variables.** Salen todas de tu `.env`. `DATABASE_URL` **no** te la
   va a pedir: ya viene puesta en `render.yaml`.
4. **`GOOGLE_SERVICE_ACCOUNT_JSON` es la excepción**: en local es la ruta al
   archivo, pero en el servidor ese archivo no existe (no se versiona). Pega el
   **contenido completo del JSON**, de la primera llave a la última. El código
   detecta cuál de las dos formas es.
5. **Espera al primer deploy** y comprueba que `https://tu-servicio.onrender.com/`
   devuelve `{"status":"ok"}`.
6. **Actualiza el webhook en Meta** con la URL definitiva (§5.6). Esta ya no
   vuelve a cambiar.
7. **Entra al panel** en `https://tu-servicio.onrender.com/admin/inbox`.

La base arranca vacía: los contactos y leads de las pruebas locales se quedan en
`bot.db`, que no se sube. Las tablas se crean solas en el primer arranque.

> ⚠️ **Si vienes de un despliegue con Postgres**: borra `DATABASE_URL` de
> *Environment* en el panel de Render. Lo que esté escrito ahí **gana sobre
> `render.yaml`**, así que el servicio seguiría usando el Postgres viejo mientras
> el disco se queda vacío — y no da ningún error que te avise. Cuando confirmes
> que el bot responde, ya puedes borrar el Postgres.

> ⚠️ **Con disco no hay despliegues sin corte.** Un disco solo puede estar montado
> en una instancia, así que Render apaga la vieja antes de encender la nueva:
> unos segundos de caída en cada deploy. No se pierde ningún mensaje (Meta
> reintenta los webhooks que no reciban respuesta), pero conviene no desplegar en
> hora punta.

> Si en vez del runtime de Python usas el `Dockerfile`, ten en cuenta que el
> contenedor corre como usuario `bot` y `/var/data` sería de root: habría que
> darle permiso de escritura. Con `render.yaml` tal cual está no aplica.

### 11.5 Notas por plataforma

- **Render / Railway**: conectas el repositorio y listo; la base va en el disco
  que declara `render.yaml`. En Render, el free tier **duerme el servicio tras 15
  minutos sin tráfico** — para un bot de WhatsApp eso significa que el primer
  mensaje de un cliente se pierde mientras despierta. Hace falta el plan pago.
  En Railway no hay `render.yaml`: ahí tienes que crear el volumen a mano y
  apuntar `DATABASE_URL` a un archivo dentro de él.
- **VPS**: además del contenedor necesitas un proxy con HTTPS (Caddy es el más
  simple: renueva el certificado solo) y algo que reinicie el proceso al arrancar
  la máquina (`restart: unless-stopped` en docker-compose, o una unidad systemd).

## 12. Cuando algo no funciona

### 12.1 Lo primero: ¿llegó el mensaje al servidor?

```bash
curl https://tu-dominio/admin/status -H "X-Admin-Key: TU_CLAVE"
```

Devuelve el estado de la base, de Google, la configuración efectiva (útil para
confirmar que las variables del hosting llegaron al proceso) y unos contadores de
webhooks que se reinician en cada despliegue:

| Qué ves | Qué significa |
|---|---|
| `webhooks_recibidos` sube | Meta entrega bien; el problema es del bot |
| Sigue en `0` tras escribir | El mensaje **nunca llegó**; el problema es de Meta |
| `rechazados_por_firma` sube | El `APP_SECRET` no coincide con el de la App |

Esa distinción ahorra horas: separa "el bot no respondió" de "el mensaje no llegó",
que se parecen mucho desde fuera y se arreglan en sitios opuestos.

### 12.2 El bot solo responde a unos pocos números

Síntoma: escribes tú y funciona; escribe un cliente cualquiera y no pasa nada,
con `webhooks_recibidos` sin moverse.

Causa: **la App está en modo Desarrollo**. Meta solo entrega los webhooks de
personas vinculadas a la App, así que el mensaje le llega a tu WhatsApp pero
nunca a tu servidor.

Solución: developers.facebook.com → tu App → interruptor de arriba a **En vivo**.
Para poder activarlo hace falta una URL de política de privacidad en
Configuración → Básica; el bot publica una en `/privacidad`, así que puedes usar
`https://tu-dominio/privacidad`.

### 12.3 Al abrir el chat sale el número y no el nombre del negocio

```bash
python scripts/meta_setup.py perfil
```

Si dice `business_verification_status: not_verified`, falta verificar el negocio
en business.facebook.com → Configuración del negocio → Centro de seguridad. El
nombre puede estar bien puesto y aun así no mostrarse sin esa verificación.

### 12.4 No llegan los avisos de leads al dueño

WhatsApp solo permite texto libre dentro de las 24 h siguientes al último mensaje
de esa persona. Si llevas días sin escribirle al bot, el aviso normal falla y se
usa la plantilla de respaldo:

```bash
python scripts/meta_setup.py plantillas
```

Comprueba que la plantilla configurada exista, esté **aprobada** y tenga las 4
variables. Ojo con el idioma: `es` y `es_ES` son plantillas distintas.

### 12.5 Un cliente escribe y el bot no le contesta

Míralo en el panel: si la conversación tiene la etiqueta *atendido por ti*, el bot
está callado a propósito porque alguien respondió a mano. Se reactiva con el botón
*Devolver la conversación al bot*, o solo tras `HUMAN_TAKEOVER_TIMEOUT_MINUTES` de
silencio del cliente.

### 12.6 Las conversaciones desaparecen al desplegar

Pregúntale al servicio dónde tiene la base:

```bash
curl https://tu-dominio/admin/status -H "X-Admin-Key: TU_CLAVE"
```

En `base_de_datos` verás:

```json
{ "motor": "sqlite",
  "archivo": "/var/data/bot.db",
  "sobrevive_al_despliegue": true,
  "modo_concurrencia": "wal" }
```

- **`sobrevive_al_despliegue: false`** → la base está dentro de la carpeta del
  código y el hosting la reemplaza entera en cada deploy. Revisa que el disco
  esté montado en `/var/data` y que `DATABASE_URL` no esté puesta a mano en el
  panel del hosting apuntando a otro sitio: **lo del panel gana sobre
  `render.yaml`**.
- **`archivo` empieza sin `/`** → te faltó una barra: son cuatro
  (`sqlite:////var/data/bot.db`), no tres.
- **`modo_concurrencia` distinto de `wal`** → el panel y el webhook van a
  chocar bajo carga. No debería pasar: se configura solo.

Una desaparición **la primera vez** es normal si vienes de Postgres: el disco
arranca vacío y el historial viejo se queda en la base anterior. Lo que no es
normal es que vuelva a pasar en el **segundo** despliegue.

## 13. El plan Pro: el bot con IA (Gemini)

Se venden dos planes sobre **este mismo código**:

| | Plan Básico | Plan Pro |
|---|---|---|
| El cliente toca el menú | ✅ | ✅ |
| El cliente **escribe** y el bot entiende | ❌ "no entendí" | ✅ lo lleva a lo que pidió |
| Responde preguntas sueltas del negocio | ❌ | ✅ |
| Agenda contra Google Calendar | ✅ | ✅ (igual) |
| Coste por mensaje | 0 | el de la clave del cliente |

### 13.1 No son dos códigos

Es **un repo con un interruptor**, y el interruptor está en el panel del dueño.
`IA_ACTIVA=false` es el plan Básico y es el valor de partida.

Eso significa que **un arreglo en el bot llega a los dos planes solo**, sin nada
que copiar de un sitio a otro. Es la razón de que esté hecho así y no con dos
repositorios: con miles de clientes, arreglar cada cosa dos veces no se sostiene,
y a los pocos meses tendrías dos productos distintos.

Lo que sostiene esa propiedad es **una sola regla**:

> **Nada de IA fuera de `app/bot/cerebro/gemini.py`.**
> Si un cambio de Gemini pide tocar otro archivo, es que la interfaz de
> `cerebro/base.py` se quedó corta: se arregla ahí, no se esparce la IA.

La superficie compartida son ~6 líneas en `bot_logic.py`, dentro de
`_handle_need_response`. Con la IA apagada esas líneas no hacen nada: el bot
recorre exactamente el mismo camino de siempre. Quien lo demuestra es
`tests/test_regresion.py`, que pasa sin haber cambiado ni una coma.

### 13.2 Lo que la IA NO hace

Tres cosas, y no son negociables:

- **No escribe precios ni textos de venta.** Elige *qué* opción del menú
  corresponde; el texto que recibe el cliente sale de `negocio.toml` como
  siempre. Un modelo no puede equivocarse en un precio si nunca se le pide que
  lo escriba.
- **No agenda.** Puede decidir que el cliente quiere una cita, pero la cita la
  crea el mismo código de siempre, con la disponibilidad real del calendario.
- **No puede inventar acciones.** Si devuelve un id que no está en el menú del
  negocio, se descarta.

### 13.3 La garantía: si la IA se cae, el bot sigue vendiendo

**Cualquier** fallo —sin clave, sin librería, cuota agotada, timeout, JSON roto,
id inventado, tope diario superado— acaba en el menú de siempre. Nunca en un
cliente sin respuesta.

Es el mismo trato que ya tenían Calendar y Sheets: una API de terceros caída no
puede costarte un cliente. `tests/test_ia.py` prueba los seis casos uno a uno.

### 13.4 Encender la IA: conectar y activar

Son dos pasos, y **los dos los puede hacer el dueño del negocio**:

1. **Conectar**: pega su clave en `GEMINI_API_KEY`, en las variables del
   servicio.
2. **Activar**: entra a `/admin/inbox` y le da a **Encender IA**.

Tiene efecto en el siguiente mensaje. **No hace falta reiniciar ni volver a
desplegar**, y queda guardado en la base, así que sobrevive a los despliegues.

La tarjeta del panel dice la verdad en los tres estados:

| Estado | Qué se ve |
|---|---|
| Sin clave | "Plan Básico" + cómo conseguir la clave. **Sin botón**, porque no haría nada |
| Con clave, IA apagada | "Plan Básico" + botón **Encender IA** |
| IA encendida | "Plan Pro · IA encendida" + botón **Apagar IA** |

Ese botón es también lo que te deja **enseñarle a un cliente los dos planes en
la misma conversación**: escribe algo, apagas, vuelve a escribir. Sin clave el
plan Pro es imposible aunque `IA_ACTIVA` esté en `true` — así el panel nunca
promete algo que no puede cumplir.

> **Lo del panel gana sobre `IA_ACTIVA`.** La variable de entorno es solo el
> valor de partida (el plan contratado); en cuanto el dueño toca el botón, manda
> él. Si no fuera así, el siguiente despliegue le volvería a encender lo que él
> mismo apagó.

**Un solo servicio sirve los dos planes.** No hace falta un despliegue por plan:
`render.yaml` deja la IA apagada y el botón del panel la enciende. Eso importa
sobre todo cuando hay **un solo número de WhatsApp**, porque Meta entrega sus
webhooks a una única URL — con dos servicios habría que cambiar esa URL en Meta
cada vez que quisieras alternar.

La clave la saca **cada cliente** en [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
con la cuenta de Google del negocio, igual que ya pone su token de Meta. Así el
consumo lo paga quien lo usa y el precio del plan no depende de cuánto hable su
bot.

> ⚠️ **Una suscripción a Google AI Pro / Gemini Advanced NO sirve.** Es un
> producto de consumo (la app de Gemini, Gemini en Gmail y Docs) y **no incluye
> acceso por API**. Lo que necesita el bot es una clave de AI Studio, que se crea
> gratis y se factura aparte.

Desde fuera, el estado se consulta con:

```bash
curl https://tu-dominio/admin/plan -H "X-Admin-Key: TU_CLAVE"
curl -X POST https://tu-dominio/admin/plan -H "X-Admin-Key: TU_CLAVE" \
     -H "Content-Type: application/json" -d '{"plan": "pro"}'
```

`/admin/status` también lo incluye, en la clave `ia`. Es lo primero que hay que
mirar cuando alguien dice "contraté el Pro y responde igual que antes": casi
siempre es la clave sin poner o el plan sin activar.

Antes de ponerlo delante de nadie:

```bash
python scripts/gemini_setup.py check
python scripts/gemini_setup.py probar "cuanto vale una pagina web"
```

`probar` enseña a qué opción del menú habría ido ese mensaje, **sin mandarle nada
a nadie**. Es la forma de ver si el menú del cliente está bien redactado: la IA
elige leyendo los títulos y las descripciones que él mismo escribió.

### 13.5 El coste, y cómo está acotado

Tres frenos, y el primero es el que de verdad importa:

- **Los toques de botón y de lista nunca llegan a la IA.** Solo el texto libre
  que hoy acabaría en "no entendí". El grueso del tráfico sigue costando cero.
- **Tope por contacto y día** (`IA_MAX_MENSAJES_DIA`, 40 por defecto). Frena a
  quien escriba en bucle antes de que le vacíe la cuota al negocio.
- **Tope por cliente y mes** (`clients.ia_limite_mensual`, desde el super-admin).
  Este protege tu margen: el peor caso de un cliente deja de ser "lo que decida
  gastar" y pasa a ser un número que tú elegiste. En 0, sin tope.

Los tres degradan igual: **pasado el tope el bot no se calla, sigue con el
menú**, que es gratis y vende. Es el mismo camino que ya recorre cuando Gemini
da timeout. Por eso el tope mensual se puede poner generoso sin miedo.

### 13.5.1 El medidor: qué se factura

Cada respuesta de la IA suma una fila en `ia_uso` (una por cliente y mes):
mensajes, tokens de entrada y tokens de salida. **Los tokens son los reales**
que devuelve Gemini en `usage_metadata`, no una estimación — facturar sobre una
estimación es facturar sobre una suposición.

Un intento que falla no se anota: no gastó nada que se pueda cobrar, y contarlo
convertiría una clave mal puesta en consumo del cliente.

El consumo de todos se ve en `/superadmin`, y se saca en JSON para pegarlo en
una hoja de cálculo:

```bash
curl https://tu-dominio/superadmin/consumo?periodo=2026-08 \
     -H "Cookie: super_nitro=..."
```

Referencia de costes: con `gemini-3.1-flash-lite`, unos **$0.17 por cada 1.000
mensajes interpretados** (prompt de ~450 tokens, sin historial). Un cliente
normal está entre $0.20 y $1 al mes.

### 13.6 El carácter del bot

Sale de `[ia]` en `negocio.toml`, junto al resto del contenido. El cliente no
toca Python:

```toml
[ia]
rol  = "el asistente comercial de {negocio}"
tono = "cercano y claro, tuteando, sin tecnicismos"

nunca = [
  "inventar precios, descuentos o promociones que no estén escritos",
  "prometer plazos de entrega o fechas concretas",
]
siempre_derivar = ["quejas", "reclamos", "devoluciones"]
max_palabras = 60
```

`nunca` es la lista importante: es donde se le cierra la puerta a lo que le
costaría dinero o credibilidad al negocio. Repásala con cada cliente.

## 14. El super-admin: la consola de la plataforma

Un solo despliegue atiende a varios negocios, así que hace falta un sitio donde
operarlos. Está en `/superadmin` y **no es el panel de ningún cliente**: es tu
herramienta.

```
https://tu-dominio/superadmin
```

Entras con `SUPERADMIN_KEY`. Mientras esa variable esté vacía, `/superadmin`
responde 503 y no existe — que es lo correcto para una consola de administración
colgada de internet. Su cookie es distinta de la del panel de los clientes: un
pase de una no sirve para la otra, en ninguno de los dos sentidos.

**Qué se hace ahí:**

- **Dar de alta un negocio.** En un paso: su fila en `clients`, su token de
  WhatsApp cifrado, su contenido (`negocio_config`, copiado del `negocio.toml`
  del repositorio como plantilla y **validado antes de guardar**) y el usuario
  con el que entrará a su panel. Los cuatro juntos a propósito: un cliente sin
  usuario no puede entrar, y uno sin contenido propio leería variables de
  entorno del proceso, que son del despliegue y no suyas.
- **Pausar por impago.** Un `UPDATE` de una columna. El webhook de ese negocio
  deja de procesarse, su panel deja de abrir, y no se le borra nada: al volver
  tiene su historial intacto. Surte efecto al instante.
- **Ver el consumo de IA por cliente**, que es el único coste que escala con el
  número de clientes. También en JSON, en `/superadmin/consumo`.
- **Ajustar el paquete de cada uno**: IA encendida o apagada, tope mensual,
  modelo de Gemini, color de marca y logo.

> El `phone_number_id` es la **clave de enrutamiento**: llega en cada webhook y
> es lo que dice de qué negocio es el mensaje. Por eso el alta lo exige y no
> deja repetirlo.

### 14.1 El logo de cada negocio

`clients.logo` guarda la imagen en base64 (o como data URI) dentro de la base, no
como archivo. En el hosting no hay disco que sobreviva al despliegue, y un logo
son unos cientos de kilobytes que la base guarda sin quejarse. Si esa columna
está vacía se usa `app/marca/logo.png`, y si tampoco lo hay, las iniciales del
negocio sobre su color de marca.

Al cambiarlo, quien tenga el panel instalado en el celular tiene que
desinstalarlo y volver a añadirlo para ver el icono nuevo: el navegador se lo
quedó guardado una semana.

### 14.2 Dar de alta un cliente, de principio a fin

**Antes, en Meta.** El cliente tiene su propia WABA y la conecta a tu App. De
ahí salen las dos cosas que necesitas: su **`phone_number_id`** y un **token
permanente**. Después hay que suscribir su WABA a tu webhook — la interfaz de
Meta a veces no lo hace sola, y sin eso no llega ni un mensaje:

```bash
python scripts/meta_setup.py --cliente panaderia subscribe
python scripts/meta_setup.py --cliente panaderia check
```

> `--cliente` toma las credenciales de la fila de ese negocio en vez de tu
> `.env`. Sin él tendrías que pegarle su token al `.env` y acordarte de
> quitarlo — que es justo el paso del que uno se olvida.

**El alta, en `/superadmin`.** Un formulario, y crea las cuatro cosas a la vez:
la fila del negocio, su token **cifrado**, su contenido copiado de la plantilla
y **validado**, y el usuario con el que entrará al panel. En cuanto guardas, ese
negocio ya atiende: no hay que desplegar nada.

**Su contenido.** Nace con tu menú y tus textos; para darle los suyos:

```bash
# Dar de alta un negocio: /superadmin → "Dar de alta un negocio"
python scripts/negocio_a_la_base.py panaderia C:\clientes\panaderia\negocio.toml
```

El segundo **valida antes de guardar**: si el menú nombra un enlace que no
existe, falla ahí y no en la primera conversación de su cliente.

**Sus textos y su menú, en el navegador.** En la ficha del negocio, botón
**"Editar sus textos y su menú"**. Desde ahí se cambia todo lo que el cliente
ve y oye, sin abrir un editor ni la terminal:

- Los ~34 mensajes del bot, cada uno con su nombre en cristiano ("Saludo a quien
  escribe por primera vez", "Cuando no entiende lo que le escriben").
- **El menú**: las opciones y sus sub-opciones, qué hace cada una, qué enlace o
  qué bloque de precios manda. Con botones para añadir opciones nuevas.
- Los enlaces y los bloques de precios, que el menú usa por su nombre.
- El carácter del bot cuando tiene IA, y su horario de atención.

> **Nada se guarda si algo no cuadra.** Al darle a Guardar se arma la
> configuración entera y se valida: si una opción apunta a un enlace que no
> existe, lo dice y **no toca nada**. Es la misma comprobación que revienta el
> despliegue con un `negocio.toml` roto, así que aquí caza exactamente lo mismo
> antes de escribir. Por eso se le puede dar a alguien que no programa.
>
> Y lo que el editor no muestra —las pestañas del Sheet, los orígenes— se
> conserva intacto: guardar sobrescribe solo lo que está en pantalla.

**El resto, en la ficha del negocio** (`/superadmin` → editar): el número del
dueño para los avisos de lead, su calendario y su hoja de Google, sus claves de
push, su color y su logo, y los días de historial que se le guardan.

```bash
python scripts/push_setup.py                                # un par de claves VAPID por cliente
python scripts/google_setup.py --cliente panaderia check    # verifica su calendario y su hoja
python scripts/panel_usuario.py crear panaderia asesor@panaderia.com   # más gente en su panel
```

**Lo que le entregas:** la dirección del panel, su nombre corto y su clave.

> **Las credenciales nunca se muestran en la ficha.** Están cifradas, y
> descifrarlas para pintarlas en un formulario las dejaría en el HTML y en el
> historial del navegador. El campo dice si hay algo guardado, y **dejarlo vacío
> significa "no lo toques"** — si vacío borrara, abrir la ficha y darle a
> Guardar dejaría al cliente sin token y sin bot.

## Próximos módulos posibles (no incluidos en este template base)

- Panel de administración (ej: Streamlit) para ver leads sin entrar a la base de datos
- Recordatorios automáticos de citas (vía templates aprobados)
- **Fase 2 de la IA**: Gemini conduciendo con herramientas (agendar, cancelar y
  escalar como funciones que el modelo llama), y detección semántica de "quiero
  hablar con una persona" en vez de la lista de palabras de `[conversacion]`.
  La interfaz de `app/bot/cerebro/base.py` ya está preparada para recibirlo.
