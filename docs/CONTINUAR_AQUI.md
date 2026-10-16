# CONTINUAR AQUÍ

**El único archivo que hay que leer para seguir con este proyecto.**
Al 27 de agosto de 2026, después de la sesión que cambió el modelo
de Meta y los avisos.

Antes tenían este papel seis archivos —`AUDIT.md`, `MIGRACION_README.md`,
`CONTINUAR_MANANA.md`, `PENDIENTES.md`, `REDISENO_ESTADO.md` y las
instrucciones del rediseño—. Describían trabajo que ya está hecho, y
tener seis sitios donde mirar significa que ninguno está al día. Se
borraron; lo que seguía siendo cierto está aquí. Git guarda el resto si
alguna vez hace falta mirar atrás.

Lo que **no** está aquí y sigue vivo:

| Archivo | Para qué |
|---|---|
| `README.md` | Cómo funciona el bot y cómo se monta uno nuevo |
| `CLAUDE.md` | Las reglas que se rompen fácil, en corto |
| `docs/META_VERIFICACION.pdf` | El trámite de Meta, escrito para leerlo sin saber de código |
| `docs/PANEL_SUPERADMIN.md` | Qué hace cada pantalla de `/superadmin` |
| `diseñosuperadmin.md` | Cómo se ve `/superadmin` y por qué. La especificación del rediseño, ya implementada (§11.11) |

---

## 1. Qué es este proyecto ahora

Un bot de WhatsApp **multi-inquilino**: un solo despliegue atiende a
todos los negocios. Vivo en producción desde el 15-ago-2026 sobre
PostgreSQL, con Row-Level Security desde el 19-ago-2026.

Desde el **27-ago-2026 cada negocio trae su propia App de Meta**: la
plataforma pone hosting, base de datos y panel, y el número sigue siendo
del cliente. Ver §10 — es el cambio con más consecuencias desde la
migración multi-inquilino.

    Quién pone qué, que es la pregunta que más se repite:

      del cliente    App de Meta · WABA · su número · su método de pago
      de la plataforma   hosting · base de datos · panel · el correo de
                         los avisos · la clave de Gemini (y su factura)

**Cada cliente le paga a Meta sus propios mensajes.** La plataforma no
adelanta ni factura nada de eso, así que un cliente más cuesta
prácticamente cero.

- El inquilino sale de **su URL de webhook** (`/webhook/{token}`) o del
  pase de sesión (panel), y viaja en un `ContextVar`
  (`app/core/tenencia.py`). El `phone_number_id` del mensaje ya no
  decide: confirma.
- Cada negocio tiene su configuración en la base (`negocio_config`), sus
  credenciales cifradas y su contenido editable desde `/superadmin`.
- `/superadmin` cubre el ciclo completo de un cliente **sin tocar la
  terminal**: alta, pausa, credenciales, usuarios del panel, logo, plan
  de IA y el mapa de lo que dice el bot.
- El panel de atención (`/admin`) está rediseñado entero: entrada,
  conversaciones, contactos y configuración.

### Decisiones cerradas — no las reabras sin motivo

- **Un solo proceso.** El bus de avisos en vivo es una cola en memoria.
  Ver §3.9.
- **La plataforma es Nitro, también dentro del panel de un cliente.** El
  acento es el morado de Nitro y no `config.MARCA_COLOR`; del negocio se
  ve su cuadrito y su nombre. Si alguien "arregla" esto poniendo el color
  del cliente de acento otra vez, está deshaciendo una decisión.
- **Los semáforos no siguen a la marca.** Un "urgente" tiene que leerse
  igual en todos los paneles.
- **El `server_default="1"` de `client_id` se queda.** Es la red que
  permitió migrar sin reescribir cuarenta consultas a la vez.
- **No se puede borrar un negocio desde `/superadmin`, solo pausar.** Un
  botón de borrar al lado de uno de pausar es un accidente esperando.
- **La App de Meta es del cliente, no nuestra.** Se decidió el
  27-ago-2026 y cierra un cuello de botella entero: nuestro App Review
  dejó de bloquear todas las ventas. Ver §10.

---

## 2. Por dónde seguir

### Etapa 4 del rediseño · super-admin por tareas · 24-sep-2026

  · Barra: Hoy · Clientes · Cobros · Dar de alta. `/superadmin` es "Hoy"
    (cobros que piden algo, negocios con algo roto, números del mes); el
    listado de negocios pasó a `/superadmin/clientes`; `/superadmin/cobros`
    los ordena por urgencia con "Registrar pago" en cada fila.
  · Eliminar un negocio: zona peligrosa de su ficha, escribiendo su nombre
    corto. Borra sus filas de todas las tablas del inquilino. El bot de
    casa no se puede eliminar.
  · Un dueño pausado por impago que entra con su clave CORRECTA ve cuánto
    debe y cómo pagar (`acceso.pausado_por_impago`). Solo sin subdominios:
    con `DOMINIO_BASE`, su subdominio sigue dando 404.

PARA DESPLEGAR LAS CUATRO ETAPAS (el push lo hace todo; migran solas
`b7e4d2a91c05` y `c8f1a3e57d20`):
  1. En la ficha de cada cliente: elegir su plan y ponerle "Pagado hasta".
  2. Que cada dueño ponga su correo en su panel > Equipo.
  3. SMTP configurado en Render, o no salen avisos ni cobros por correo.
  4. `test_rls` contra PostgreSQL antes, si se puede.

### Etapa 3 del rediseño · "Mi bot" y estadísticas · 24-sep-2026

  · `/admin/mi-bot` (`app/web/panel_bot.py`): el dueño edita su bot con el
    MISMO mapa que el super-admin, y guarda por la MISMA puerta
    (`superadmin.guardar_mapa`, sacada de `mapa_guardar`). Sin IA en su
    plan no ve esa caja y el servidor ignora esa sección.
  · `mapa.pintar(..., guardar_en, con_ia, aviso_del_archivo)`: el JS guarda
    en `GUARDAR_EN`, no en una ruta fija.
  · `/admin/estadisticas` (`app/core/estadisticas.py`): personas, mensajes,
    citas, consultas y respuestas humanas; mensajes por día; qué eligieron
    en el menú; de dónde llegaron; por área. Días en hora de Colombia.
  · Las dos pantallas son solo del dueño.

### Etapa 2 del rediseño · cobros y "Mi plan" · 24-sep-2026

  · Precios en `planes.py`: Básico $70.000, Pro $100.000, Premium
    $130.000 al mes; pago por Nequi 317 886 2390 y comprobante por
    WhatsApp. `clients.precio_mensual` para un precio pactado.
  · `app/core/cobros.py`: `clients.vence_el` es "pagado hasta". 7 días
    antes, un correo diario al dueño y banda en su bandeja; 2 días de
    gracia; al tercero se pausa solo (`pausado_por = "impago"`). Corre cada
    hora dentro del proceso (`cobros.vigilar`, arrancado en `main`).
  · Registrar un pago (tarjeta "Cobro" de la ficha en /superadmin) corre la
    fecha un mes y reactiva lo que pausó el cobro. Una pausa a mano NO la
    deshace un pago. `vence_el` vacío = no se cobra (el bot de casa).
  · `/admin/mi-plan`: plan, lo que incluye, uso, vencimiento, cómo pagar y
    los tres planes. Solo el dueño.
  · Migración `c8f1a3e57d20`: seis columnas en `clients`, sin tablas nuevas.

Al desplegar: ponerle "Pagado hasta" a cada cliente que pague; sin fecha
no se le cobra ni se le pausa nunca. Los correos de cobro necesitan SMTP y
el correo del dueño (Equipo) o el del negocio.

### Etapa 1 del rediseño · planes y áreas con usuario · 24-sep-2026

  · Planes en `app/core/planes.py`: Básico (sin áreas, sin IA), Pro (3
    áreas, IA), Premium (5, IA). `clients.plan` guarda el código; una
    etiqueta vieja se deduce de `ia_contratada`. El super-admin elige el
    plan con un desplegable (sustituye al "¿compró la IA?").
  · Cada área es una persona con usuario (`panel_users.area_id`) y SOLO ve
    las conversaciones de sus opciones del menú. La puerta está en
    `app/core/equipo.py` y la pregunta TODA ruta del panel. Lo que no es
    de ningún área es del dueño; el dueño reasigna desde la ficha.
  · El dueño arma su equipo en `/admin/equipo` (`app/web/panel_equipo.py`).
  · Avisos: a las áreas SOLO por correo. Lo que no es de nadie, al correo
    del dueño (`avisos.correo_dueno`). El WhatsApp del dueño, último recurso.
  · Arreglado: el bot no anotaba `Contact.servicio` en menús armados en el
    mapa (no escribe `sheet`), así que el reparto por áreas no funcionaba.
  · Migración `b7e4d2a91c05`: tres columnas, ninguna tabla nueva.

Al desplegar: el dueño de cada negocio tiene que poner su correo en
Equipo. Sin él, lo huérfano sigue yendo a las áreas sin opciones marcadas,
como antes.

### Revisión completa · 23-sep-2026 (SIN desplegar hasta el push)

Auditoría de todo el código. Cada fallo tiene su prueba en la sección
"Revisión del 23-sep-2026" de `test_regresion` (y el del lote de mensajes
en `test_multitenant`). Los que más importan:

  · `OWNER_PHONE_NUMBER` tenía por defecto `573001234567`, un número real:
    un negocio sin áreas ni dueño le mandaba sus leads a un desconocido.
    Ahora vacío; un aviso que no sale por ninguna área cae al dueño.
  · El editor de contenido reconstruía cada opción de cero y borraba el
    tercer nivel, la `url` propia, `oculta` y `solo_con_cita` con un
    guardado. Ahora parte de la opción que había (`contenido._leer_opcion`).
  · El webhook atendía solo `messages[0]` de cada entrega.
  · `whatsapp_client._post` no cazaba errores de red: el lead no se guardaba.
  · Duración de cita 0 → bucle infinito; zona horaria vacía → sin respuesta.
  · Correo: asunto con salto de línea no salía; área solo-correo sin SMTP
    contaba como avisada; los fallos del hilo ahora se anotan.
  · A una reacción 👍 se le contestaba. El caché de archivos solo se
    limpiaba en el cliente 1.

Pendiente de esta revisión: `test_rls` sin correr; el freno de
`/superadmin` se salta con un `X-Forwarded-For` falso (depende de si hay
Cloudflare delante de Render); ancho de teléfono sin comprobar (no se tocó
CSS).

### Dónde quedó · 7-sep-2026

**Todo lo de abajo está EN PRODUCCIÓN.** `render.yaml` apunta a `main` y
no lleva `autoDeploy: false`: el push es el despliegue, sin paso
intermedio ni confirmación.

    2b624cd  los saltos de línea de un mensaje dejan de borrarse solos
    c4b3fa7  un error del mapa dice en qué paso está, y lleva hasta él
    b950d7f  una llave en un texto del dueño dejaba MUDO al bot
    b83e9ec  pasarse de un tope de Meta descarta el mensaje entero
    a17693f  "Menú principal" y "Atrás" se pueden ofrecer siempre
    05c4432  el "no entendí" se colaba detrás de una respuesta correcta

Seis arreglos, y **cuatro de ellos son el mismo cliente sin recibir
NADA**: el bot no daba error, el panel guardaba bien, y en el chat no
llegaba nada. Vale la pena leer por qué, porque los cuatro se veían igual
desde fuera y ninguno dejaba rastro más que una línea en el log:

| Qué pasaba | Dónde |
|---|---|
| Un `<input>` se comía los saltos de línea al pintar el campo | §4.10 |
| Un `{name}` en un texto del dueño reventaba el envío | §3.15 |
| Pasarse de un tope de Meta descarta el mensaje entero | **§3.16** |
| El "no entendí" pegado detrás de una respuesta correcta | §3.18 |

**Si algo vuelve a "no llegar", §3.16 es el primer sitio donde mirar**, y
el log lo dice ahora con todas las letras: `META RECHAZÓ el mensaje … EL
CLIENTE NO LO RECIBIÓ`.

Lo demás del 6 y 7-sep, en corto: los cuadros de texto crecen con lo que
se escribe (§4.11) y el árbol del mapa se pliega (§4.11b); un error de
guardado dice en qué paso está y abre ese paso (§4.12); y hay dos salidas
—"Menú principal" y "Atrás"— que se pueden ofrecer después de cualquier
respuesta sin tener que crearlas (§3.17).

Verificado: las cuatro suites en verde, con **veintiocho comprobaciones
nuevas**. `test_rls` NO se ha vuelto a correr —pide PostgreSQL— y no hace
falta: nada de estos seis commits toca modelos ni consultas. La última
vez que corrió, contra PostgreSQL 18.6 sobre base vacía con las
migraciones aplicadas, `test_multitenant` (198) y `test_rls` (11)
salieron las dos en exit 0.

**Lo que queda por comprobar es en el WhatsApp de verdad**, que es lo
único que estas pruebas no pueden tocar: entrar al bot, ir a la opción
que fallaba y ver que ahora contesta. Ojo con §3.12 — si la conversación
de prueba está a medias, el bot sigue por donde iba; el botón *Reiniciar*
del panel la devuelve al principio sin borrar nada.

Dos cabos sueltos, ninguno bloquea:

  · La base de ensayo `prueba_hmqr` quedó en Render con los datos de las
    pruebas. Bórrala. La de `.env.rls` ya no existe — se borró al acabar
    el ensayo de RLS y hubo que crear otra.
  · Lo que quedó fuera del brief está en el punto 6 de aquí abajo y
    explicado en §11.11. No es deuda escondida: es una decisión con su
    motivo.

**Para volver a mirarlo en el navegador** —que es obligatorio antes de dar
por bueno cualquier cambio visual (§4.4)— ya no hay que montar nada:

    python scripts/servir_de_prueba.py
    → http://127.0.0.1:8099/superadmin   ·   clave: prueba

Siembra una base de mentira con los cuatro estados que la consola pinta
distinto (bien, credenciales rotas, pausado, recién dado de alta) y un
menú de tres niveles con textos que llevan saltos de línea y espacios de
más. Sin eso la consola se ve vacía, "Requiere atención" no aparece
nunca, y el mapa sale sin un solo paso: justo lo que se acaba de cambiar
es lo que no se puede mirar.

Esas cuarenta líneas se escribieron **tres veces** en sesiones distintas,
cada una en un temporal que se perdió al acabar. Por eso ahora están en
`scripts/`.

> ⚠️ **El 27-ago-2026 el modelo cambió de raíz.** La plataforma dejó de
> tener UNA App de Meta con los números de todos los clientes dentro.
> Ahora **cada negocio trae la suya**, y nosotros ponemos hosting, base de
> datos y panel. Ver §10.
>
> La consecuencia que importa: **nuestro App Review ya no bloquea vender.**
> Era un punto único de fallo — mientras Meta no nos aprobara a nosotros,
> no se podía conectar a NINGÚN cliente. Ahora el trámite de cada quien
> bloquea solo a ese quien, y corren en paralelo.

### Lo que falta para vender — solo una cosa

**1. Dar de alta al primer cliente real por el camino nuevo.**

No es código: está todo hecho y desplegado. Es el paso comercial, y a la
vez **la comprobación del supuesto sobre el que se apoya todo el modelo**:
que un negocio dueño de su App y de su WABA no necesita App Review propio.
Si eso falla, falla barato y con el sitio exacto donde mirar ya escrito.

    Se le manda        https://bot.nitro2tech.com/conectar
    Él devuelve        4 datos, que se pegan en /superadmin
    Se comprueba       el botón "Probar credenciales" de su ficha

### Lo que hay que hacer antes del 1-oct-2026

**2. Configurar el método de pago de Meta.** Tuyo y de cada cliente.

Hasta esa fecha, responderle a alguien que acaba de escribir es gratis, así
que el bot funciona sin tarjeta. **A partir de ahí Meta cobra también esos
mensajes, y sin forma de pago el bot deja de responder** — no se degrada,
se calla.

Lo tuyo está sin hacer y ya se nota: es lo que bloqueó los avisos por
WhatsApp toda la sesión del 27-ago (§11.6). Está en el Billing Hub de la
WABA, y son cinco minutos.

Para los clientes es el paso 5 de la guía de `/conectar`, y ahí se explica
que **le pagan a Meta directamente con su tarjeta**: la plataforma no
adelanta ni factura sus mensajes.

### Y luego, por orden de lo que aprieta

**3. Marcar `ia_contratada` a quien ya tenga IA.** Nace en `false` para
todos, incluido el cliente 1 (§11.1). Quien la tuviera encendida está en
plan Básico hasta que se le marque la casilla en su ficha. El bot no se
rompe: responde con el menú.

**4. Migrar el bot de casa a su URL propia y retirar `/webhook` a secas.**
No antes de tener un cliente real funcionando por el camino nuevo: esa
puerta es lo único que sostiene al cliente 1 hoy. Su `webhook_token` ya
existe y su URL está a la vista en `/superadmin`; cambiar de puerta es
pegarla en Meta, sin tocar código (§10.1).

**5. Repasar los otros tres bloques de precios** (Power BI, página web,
automatización). Cuelgan del bloque compartido: guardan `["precios",
"url"]` y no `mensaje` propio. Funciona; el día que se editen desde el
panel esa opción se independiza (§3.13). No es código.

**6. El menú, dentro del editor de contenido, sigue siendo una tarjeta
de diez campos por opción** y no la fila de cuatro que pedía el brief
(§11.11). No se cambió porque `contenido._leer_opcion` lee esos diez del
formulario: dejar seis fuera del HTML los borraría de cada opción al
siguiente guardado, en silencio. El sitio donde se arma el menú de
verdad es el mapa; si esa tarjeta se reduce algún día, hay que reducir
`_leer_opcion` en el mismo commit.

### Lo que ya NO hace falta mirar

La migración multi-inquilino está entera, RLS incluida. El rediseño del
panel del cliente, en sus cinco etapas más Configuración. El bot manda
1,00 mensajes por cada uno del cliente (§6). La rampa del cliente 1 está
apagada. Y desde el 27-ago: la App de Meta por cliente (§10), los dos
planes (§11.1), los avisos por área y por correo (§11.2–11.8), la guía de
conexión (§11.9), el CSS del super-admin fuera de Python (§11.10) y el
rediseño entero de `/superadmin` (§11.11).

### El estado de tu cuenta de Meta

Comprobado contra la Graph API y no supuesto
(`python scripts/meta_setup.py check`):

| | |
|---|---|
| Verificación de negocio | 🔄 `pending`. Es para el bot de casa; **ya no bloquea vender** |
| App Review | ⬜ Sin enviar, y **ya no hace falta** (§10) |
| Plantilla `aviso_lead` | ✅ Aprobada, `[es]`, con las 4 variables correctas |
| Método de pago | ⬜ **Sin configurar.** Ver el punto 2 |

> **Dos nombres que se confunden, y ahora hay que explicárselo también a
> cada cliente.** La *Business Verification* es la de los documentos, es
> gratis, y es la que levanta el tope de 250 mensajes cada 24 h. *Meta
> Verified* es una suscripción de pago con distintivo y **no desbloquea
> nada**.

## 3. Trampas que ya costaron tiempo — no vuelvas a pisarlas

### 3.1 El contexto no viaja a todos los hilos

Verificado empíricamente, no supuesto:

| | ¿hereda el inquilino? |
|---|---|
| `run_in_threadpool` (webhook) | ✅ sí |
| Middleware de Starlette | ✅ sí |
| `ThreadPoolExecutor.submit` | ❌ **no** |
| `threading.Thread` | ❌ **no** |

**Si agregas un hilo nuevo, envuélvelo con `tenencia.envolver_para_hilo()`.** Hoy lo usan el `_ejecutor` de `gemini.py` y el hilo de `push.py`. El síntoma de olvidarlo es que se lea la configuración base — o sea, la clave de Gemini del dueño respondiendo a otro cliente y cargándole el consumo a él.

### 3.2 Nada de leer configuración de cliente al importar un módulo

`config.py` solo puede resolver por inquilino lo que **no** esté definido en su cuerpo. Y leer `config.LO_QUE_SEA` en el cuerpo de un módulo lo congela con los valores del primer negocio.

Ya se corrigieron cuatro casos: `whatsapp_client.BASE_URL` → `_url()`, `pwa.CABECERA_HTML` → `cabecera_html()`, `_SCRIPT_LISTADO` → `_script_listado()`, y `Contact.origen` → `default=lambda: ...`.

**Ojo: el cuerpo de una CLASE también se evalúa al importar.** Ese fue el que se escapó (`Contact.origen`) y provocó un import circular. Para buscarlos:

```bash
for f in $(grep -rl "config\." app --include=*.py); do python - "$f" <<'PY'
import ast, sys
arbol = ast.parse(open(sys.argv[1], encoding="utf-8").read())
def escanear(cuerpo, en_clase=False):
    for nodo in cuerpo:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        if isinstance(nodo, ast.ClassDef): escanear(nodo.body, True); continue
        for s in ast.walk(nodo):
            if isinstance(s, ast.Attribute) and isinstance(s.value, ast.Name) and s.value.id == "config":
                print(f"{sys.argv[1]}:{s.lineno}: config.{s.attr}{' [en clase]' if en_clase else ''}")
escanear(arbol.body)
PY
done
```

Lo único que puede quedar ahí son los ajustes **del sistema** (`DATABASE_URL`, `GRAPH_API_VERSION`, `APP_SECRET`…), que son constantes de verdad en `config.py`.

### 3.3 Import circular: `config` → `tenencia` → `database` → `config`

`config.actual()` importa `tenencia` **dentro de la función**, no arriba. Si lo subes al encabezado, rompes el arranque. Lo mismo con `database.tenencia_actual()`.

### 3.4 `config.py` valida al importar, y tiene que seguir haciéndolo

La última línea de `config.py` llama a `base()`. Es deliberado: construir la configuración es lo que detecta un `negocio.toml` roto (una opción del menú que nombra un enlace inexistente), y eso debe reventar el **despliegue**, no la primera conversación con un cliente. Hay una prueba de regresión que lo cubre.

### 3.5 Alembic genera código roto

`--autogenerate` emitió `postgresql.JSONB(astext_type=Text())` con `Text` sin calificar, que revienta con `NameError` al aplicar la migración. **Revisa siempre lo que genera** y corrige a `sa.Text()`.

### 3.6 El cuerpo de una respuesta en streaming corre fuera de la petición

El canal SSE (`/admin/api/stream`) devuelve un generador. Ese generador se
consume **después** de que el endpoint devolvió, así que no hay que dar por
supuesto que el `ContextVar` del inquilino sigue puesto ahí dentro.

Por eso `stream()` guarda el `client_id` en una variable local antes de
devolver, y la recuperación de mensajes perdidos va dentro de un
`with tenencia.usar(inquilino)`. Sin eso, esa consulta correría **sin
filtro** y le entregaría al panel los mensajes de todos los negocios.

Vale para cualquier `StreamingResponse` que se añada, y para cualquier
tarea de fondo que se lance desde un endpoint.

### 3.7 Si llamas al bot por debajo del webhook, fija el inquilino

`eventos.publicar()` descarta el aviso cuando no hay inquilino, en vez de
repartirlo a todos. Es lo correcto, pero tiene una consecuencia práctica:
las pruebas que llaman a `bot_logic.handle_incoming_message` directamente
—sin pasar por el webhook— tienen que envolverse en
`with tenencia.usar(...)` o el canal en vivo no entrega nada y la prueba
falla sin explicar por qué. Está resuelto en `tests/test_panel.py`, en el
ayudante `msg()`, y anotado ahí mismo.

### 3.8 Una base estrenada con el código viejo deja a Alembic sin constancia

Pasó al desplegar (15-ago-2026) y costó vaciar la base y empezar de nuevo.

`init_db()` llama a `create_all()`, que crea las tablas que falten **sin
avisar a Alembic**. Si una base se estrena con un despliegue que NO corre
`alembic upgrade head` —el comando de arranque viejo, un script, una
prueba—, el esquema queda construido por la puerta de atrás y
`alembic_version` vacía. A partir de ahí:

- `alembic upgrade head` intenta crear las tablas desde cero y revienta
  con `relation "clients" already exists`.
- Y si las tablas venían del código **anterior** a la tenencia, además
  les falta `client_id`, así que el arranque muere con
  `column messages.client_id does not exist` — que es lo correcto: mejor
  no arrancar que atender con un esquema a medias.

**Cómo se arregla:** vaciar la base (o borrarla y recrearla) y desplegar
con el comando de arranque bueno, para que Alembic la construya él.

    alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT

**Cómo se evita:** que ese comando esté puesto **antes** de que nada toque
una base nueva. Ojo: lo que esté escrito a mano en el panel de Render gana
sobre el `render.yaml`.

**La señal de que quedó bien** son las líneas `Running upgrade` en los
logs del despliegue. Si ves `Cliente inicial creado` sin ellas encima, el
esquema lo hizo `create_all` y hay que rehacerlo.

### 3.13 Lo propio de una opcion GANA sobre el puntero compartido

Es el fallo que mas costo de toda la sesion: tres rondas de "lo cambio y
sigue igual", y solo se cerro cuando el diagnostico enseño el dato:

    chatbot_precios -> guarda: ["mensaje", "precios", "url"]
                       texto_que_manda: "...Instalacion: $3..."

O sea: el texto nuevo ESTABA guardado en `mensaje`, y el bot mandaba otro.

En `config_cliente._opcion`, `enlace` y `precios` no son datos de la
opcion: son el nombre de algo que vive en otra seccion y que varias
opciones comparten. Escribiendo un TOML a mano son comodos. El problema
era que **sobrescribian siempre**:

    precios = "chatbot"  ->  o["mensaje"] = self._precios[nombre]

Asi que una opcion con su propio `mensaje` Y un `precios` heredado mandaba
el bloque compartido. El cambio estaba en la base y no se usaba, que es el
peor sitio donde puede estar un cambio.

**Ahora el puntero solo rellena lo que la opcion no diga por si misma**, y
eso arregla los datos que ya quedaron con las dos cosas sin pedirle a
nadie que vuelva a guardar. Los TOML de siempre no cambian: sus opciones
con `precios` no traen `mensaje` propio.

Y al guardar desde el panel, el servidor **quita el puntero** de toda
opcion que traiga lo suyo. Se hace en el servidor y no solo en el editor a
proposito: una pestaña vieja en el navegador de alguien mandaria las dos
cosas otra vez.

> El sintoma que lo delataba, y que dijo el dueño sin saber lo que
> significaba: **"los links si me los cambia, los textos no"**. Los
> enlaces ya estaban arreglados, los precios no. Una asimetria asi señala
> el sitio exacto; conviene preguntarla antes de mirar el guardado.

### 3.13b Las listas de nombres fijas, otra vez

`self._precios` era, como `_enlaces`, un diccionario de cuatro nombres
escritos en el codigo. Un negocio no podia crear un bloque de precios
suyo: se aceptaba en la pantalla y lo rechazaba el guardado. Corregido
igual. **Es el tercer sitio con el mismo patron**; si aparece un cuarto
puntero o una cuarta lista, mirarlo antes de que lo sufra un cliente.

Es el fallo que mas costo, y el patron se repitio dos veces el mismo dia.

En `config_cliente._opcion`, dos claves no son datos de la opcion sino
punteros a una seccion compartida, y al construir la configuracion
SOBRESCRIBEN lo que la opcion tuviera escrito:

    enlace  = "precios"   ->  o["url"]     = self._enlaces[nombre]
    precios = "chatbot"   ->  o["mensaje"] = self._precios[nombre]

Con un contenido escrito a mano en el TOML eso es comodo: se comparte un
enlace o un bloque de precios entre varias opciones. Desde un editor es
una trampa doble:

1. El recuadro sale **vacio** —la opcion no guarda ese texto— aunque el
   bot si mande algo. Se escribe sin saber sobre que.
2. Lo que se escriba se guarda en `mensaje`… y al construir la
   configuracion lo pisa el bloque compartido. **El cambio se guarda y no
   se usa.**

El dueno lo vivio entero: cambio sus precios, el panel dijo "guardado",
borro la conversacion, probo desde otro numero, y el bot siguio mandando
los precios viejos. La URL si le habia cambiado — porque esa mitad ya
estaba arreglada, y por eso parecia que "los links si, los textos no".

**La regla:** cuando el editor escribe el valor propio de una opcion,
tiene que QUITAR el puntero. Vale para `url`/`enlace` y para
`mensaje`/`precios`, y hay que mirarlo si algun dia se añade otro puntero
parecido. Lo que ya estaba compartido sigue funcionando hasta que se
edite; al editarlo, esa opcion se independiza y las demas no se tocan.

### 3.12 Un cambio de contenido NO se ve en una conversacion a medias

Costo una tarde entera de diagnostico y tres arreglos a ciegas, asi que
conviene leerlo antes de dar por roto el guardado.

El dueno cambiaba el saludo en el panel, le escribia a su bot y el bot
seguia por donde iba. Parecia que no se guardaba. **Se guardaba bien**, y
la configuracion del proceso tambien era la nueva — se comprobo con el
diagnostico, que relee de la base y resuelve el texto por el mismo camino
que el bot.

Lo que pasaba es de logica del bot, no de configuracion:

    El saludo SOLO se manda a quien esta en estado NEW.

Quien prueba su propio bot ya tiene una conversacion a medias, asi que su
proximo mensaje se atiende por donde iba: `ASKED_NEED`, `ASKING_DATE`, lo
que sea. El saludo no reaparece hasta pasadas las
`CONVERSATION_TIMEOUT_HOURS` (24 h) de silencio. Vale igual para el menu y
para todo lo que solo ocurre al principio.

**La herramienta que faltaba:** el boton *Reiniciar* de la conversacion en
el panel (`admin_ui`, junto a Eliminar). Devuelve ese contacto al
principio sin borrarle nada — ni historial, ni nombre, ni leads. Sirve
para probar y tambien para atender: un cliente atascado a mitad de un
formulario tenia que esperar un dia.

> Antes de tocar el guardado la proxima vez: **/admin/status** dice de
> donde sale el contenido y que saludo esta usando el bot AHORA. Si ahi
> aparece lo nuevo, el guardado no es el problema.

### 3.11 Una lista de nombres escrita a mano acaba siendo un techo

Pasó el 19-ago-2026 y bloqueó al dueño: no podía guardar su mapa porque
"la opción X pide el enlace Y, que no está en [enlaces]" — **estando Y en
[enlaces]**.

`config_cliente._enlaces` era un diccionario de **cuatro nombres fijos**
escritos en el código (`precios`, `powerbi_demo`, `web_demo`,
`automatizacion_demo`). Con un `negocio.toml` que traía justo esos cuatro
no se notaba nunca. Desde que el contenido se edita desde el panel, sí:
crear un enlace nuevo se aceptaba en la pantalla y lo rechazaba el
guardado, señalando la sección donde el enlace **sí estaba**.

Ahora vale cualquiera que el negocio declare; los cuatro de siempre se
mantienen encima porque además pueden venir por variable de entorno.

> El patrón, que es lo que hay que mirar en el resto del código: **una
> lista de nombres escrita a mano en Python es un techo invisible en
> cuanto el contenido se edita desde fuera.** Lo mismo pasó con las
> acciones del bot el mismo día: el editor rechazaba `reagendar` y
> `cancelar` porque no estaban en su lista, aunque el bot sí las
> entendía.

### 3.10 La columna del cliente gana sobre la variable de entorno

Pasó el 18-ago-2026 con el modelo de Gemini y costó una vuelta entera.

La cascada de `config_cliente._valor` es **columna → entorno → TOML →
defecto**. O sea que cambiar `GEMINI_MODELO` en Render **no hace nada** si
ese cliente tiene la columna `gemini_modelo` con un valor: la columna
manda, y con razón — es la configuración de ESE negocio, no la del
despliegue.

Lo que lo vuelve difícil de ver es que el valor por defecto del código era
`gemini-3.1-flash-lite`, el mismo texto que tenía la columna. Así que
"sigue diciendo 3.1" encajaba con dos historias distintas: que ganara la
columna, o que la variable no estuviera llegando al proceso y cayera al
defecto. Desde fuera no se distinguen.

**Cómo se mira:** el campo "Modelo" de la ficha en `/superadmin` enseña la
COLUMNA (`val("gemini_modelo")`), y de gris el defecto. Si tiene algo
escrito, manda eso. Vaciarlo lo pone en NULL y devuelve el mando a la
variable de entorno.

Vale para todo lo que tenga columna en `clients`: el número del dueño, el
calendario, la hoja, las claves de push, la marca, los días de historial.

> Lo bueno: **guardar la ficha surte efecto al instante**, sin desplegar.
> Se comprobó en producción — el modelo cambió con el proceso arrancado
> cuatro minutos antes y sin reiniciarlo, porque guardar llama a
> `_olvidar_caches`.

### 3.9 Sigue sin poder haber más de un proceso

`app/core/eventos.py` reparte los avisos en vivo desde una cola en memoria. **No agregues `--workers`** a uvicorn ni escales a más de una instancia hasta mover ese bus a Redis o a `LISTEN/NOTIFY` de Postgres. El síntoma sería silencioso: mensajes que aparecen tarde o no aparecen.

### 3.14 "La IA tardó demasiado" casi nunca es el modelo

Salió en producción el 18-ago-2026 como *"Gemini tardó más de 8.0s; se
responde con el menú"*. El modelo respondía en **0,7–1 s**. Eran otras dos
cosas, y las dos vuelven fácil:

- **El `import` de la librería corría dentro del cronómetro.**
  `google.genai` arrastra pydantic y httpx: 1,3 s en un escritorio y más
  en una instancia pequeña, y `_construir_cliente()` se ejecutaba en el
  hilo cronometrado. O sea que **el primer cliente que escribiera después
  de cada despliegue se llevaba el menú**, y el panel culpaba al modelo.
  Lo paga `gemini.precalentar()` al arrancar, en un hilo aparte; hay una
  prueba en `test_ia.py` que mide con reloj que al primer mensaje no le
  quede nada por importar.
- **El SDK reintenta por su cuenta y el cronómetro no lo alcanza.** Una
  llamada de 28,6 s no era el modelo pensando. `ThreadPoolExecutor` **no
  cancela nada**: nos rendimos a los 8 s, el cliente recibe su menú, y ese
  hilo sigue reintentando. Con cuatro hilos, unos cuantos tropiezos
  seguidos dejan a los mensajes siguientes esperando turno — un mal rato
  de Google convertido en un bot lento para todos, sin ninguna señal. El
  cliente se construye ahora con **dos intentos** y esperas cortas.

**El tope de 8 s no se toca.** El webhook procesa el mensaje **antes** de
contestarle a Meta (`app/main.py`), así que ese plazo es el margen antes
de que Meta reintente y el cliente reciba un duplicado. La solución nunca
es dar más tiempo.

> ⚠️ Y el plazo por intento **no se puede bajar de 10 s**: se intentó
> repartir el presupuesto y Google lo rechaza con un 400 —*"Manually set
> deadline 4s is too short. Minimum allowed deadline is 10s"*—. La capa
> HTTP no puede rendirse antes que nuestro cronómetro; quien manda en lo
> que espera el cliente sigue siendo `IA_TIMEOUT_SEGUNDOS`.

---

### 3.15 Una llave en un texto del dueño dejaba MUDO al bot

El 7-sep-2026: "puse algo en *Ver ejemplos* de Páginas web y al pulsar el
botón no sale nada, es como si el bot se congelara ahí".

Y se congelaba de verdad. El texto de una opción se mandaba así:

    elegida.get("mensaje", config.WEBSITE_MESSAGE).format(url=…)

**`str.format` trata TODA llave como un hueco suyo**, y estos textos no
los escribe un programador: los escribe el dueño en `/superadmin`, donde
nadie le dice que `{` sea un carácter especial. Peor: el propio editor le
dice *"Puedes usar {name}"* al lado de varios campos.

    "Hola {name}, mira los ejemplos"   →  KeyError: 'name'
    "Abrimos de {9 a 6}"               →  KeyError: '9 a 6'

Y aquí viene lo que hizo que costara encontrarlo. Ese `KeyError` subía
hasta `main`, donde lo recogía **un `except (KeyError, IndexError)`
puesto para los payloads mal formados de Meta**, y se anotaba:

    [main] Payload inesperado, se ignora: 'name'

O sea: el cliente no recibía absolutamente nada, y el log culpaba a Meta
de un fallo nuestro. Desde el teléfono, un botón que no hace nada.

**La regla, y no admite excepciones:** un texto que escribe el dueño no
pasa NUNCA por `str.format`. Se rellena con `huecos.rellenar`, que cambia
los huecos que se le nombran y **deja intacto lo que no reconoce** — un
`{descuento}` que nadie declaró se manda tal cual, se ve raro y eso es
una pista para quien lo escribió; lo que no puede es dejar al cliente sin
respuesta. `config_cliente._rellenar` ya lo había decidido así para las
variables del negocio; el bot seguía usando format en veintitrés sitios.

Dos cosas más que salieron del mismo tirón:

  · **El mensaje de un submenú no rellenaba `{name}` en absoluto**, así
    que el cliente leía "Hola {name}" literal mientras el resto de textos
    sí lo cambiaban. Ahora todos van por el mismo sitio.

  · **El bot corre en su propio `try`** (`main`), separado del de los
    payloads. Cazar `Exception` entera y anotarla con la traza y con "ese
    cliente se quedó SIN respuesta" es lo que convierte el próximo fallo
    de este tipo en cinco minutos en vez de una tarde. Un fallo
    atendiendo un mensaje no puede tumbar el webhook: Meta reintentaría
    y acabaría cortando las entregas del cliente.

Lo vigila `test_regresion.py` ("Una llave rara en un texto NO puede dejar
mudo al bot").

---

### 3.16 Pasarse de un tope de Meta NO recorta: DESCARTA el mensaje

La segunda mitad del "Ver ejemplos no entrega nada", y la de verdad. Lo
de §3.15 era real y estaba, pero el síntoma seguía: **en `/superadmin` el
texto estaba perfectamente guardado y en el chat no llegaba nada.**

    Si un payload se pasa de un tope de la Cloud API, Meta descarta el
    mensaje ENTERO y devuelve un 400. No manda una versión corta.

Y el bot no se entera: no hay excepción, el código sigue como si todo
hubiera ido bien. Solo queda una línea en el log del servidor. Visto
desde el teléfono, un botón que no hace nada.

Los topes, y las cuatro formas de caer ahí —todas al alcance de quien
escribe textos en el panel sin saber que los topes existen—:

| | Tope | Cómo se caía |
|---|---|---|
| Texto suelto | 4096 | un mensaje largo de verdad |
| Cuerpo con botones o lista | 1024 | **el mensaje de un submenú** |
| Título de un botón | **20** | el editor decía 24 |
| Título de una fila de lista | 24 | |
| Botones por mensaje | 1 a 3 | un grupo cuyas opciones se esconden todas → **cero** |

Lo más traicionero es el cruce de los dos primeros: el mismo texto que
sale bien como mensaje suelto tumba el envío en cuanto lleva botones
debajo, porque el tope baja de 4096 a 1024.

`send_list_message` recortaba sus filas con cuidado desde siempre;
**`send_button_message` no aplicaba ni uno**, y el cuerpo no lo miraba
ninguna de las dos. Ahora los topes se aplican en `whatsapp_client`, que
es el único sitio que habla con Meta, y **no se confía en que quien llama
se acuerde**.

Dos decisiones al aplicarlos:

  · **Se PARTE, no se recorta.** Un texto que no cabe se manda en varios
    mensajes. Lo escribió el dueño para que su cliente lo lea, y perder
    la mitad final sin avisar es lo mismo que perderlo entero, solo que
    más difícil de notar. Los títulos de botón sí se recortan: ahí no
    hay dónde seguir.

  · **Cero opciones ya no es un mensaje interactivo**, es un texto. Antes
    era otra forma de que el cliente no recibiera nada, ni el texto.

Y el aviso del log ahora dice lo que es: `META RECHAZÓ el mensaje … EL
CLIENTE NO LO RECIBIÓ`. Antes ponía "Error enviando mensaje", que se lee
como un aviso y no como una entrega perdida.

**El editor también avisa antes**: `_revisar_mapa` pide 20 caracteres
cuando el grupo sale como botones y 24 cuando sale como lista. Antes
pedía 24 siempre, así que un botón de 22 pasaba la revisión y luego
dejaba mudo al bot.

Lo vigila `test_regresion.py` ("Pasarse de los topes de Meta NO puede
dejar mudo al bot"), que sustituye `_post` en vez de los envíos: lo que
hay que hacer correr es justamente el código que aplica los topes.

---

### 3.17 "Menú principal" y "Atrás" existen siempre (7-sep-2026)

En *"y le vuelve a ofrecer…"* solo se podían marcar las opciones
**hermanas**, las del mismo grupo. En una rama honda eso deja al cliente
sin ninguna forma de volver: lee la respuesta y se queda ahí, con el menú
principal a dos mensajes de distancia y sin ningún botón que lleve. La
única salida era escribir a mano una opción "volver" en cada grupo, y
nadie se acuerda de hacerlo en todos.

Ahora hay **dos salidas fijas** que se pueden ofrecer después de
cualquier respuesta, y que **no son opciones de ningún menú**: las arma
el bot, así que existen aunque el negocio no tenga nada escrito — lo que
importa, porque un negocio nuevo nace en blanco y sin `[cierre]`.

    __menu__    "Menú principal"   vuelve al menú de arriba
    __atras__   "Atrás"            vuelve al grupo del que venía

Las etiquetas se editan como cualquier otro texto
(`boton_volver_menu`, `boton_atras`) y están en `TEXTOS_DE_UNA_LINEA`:
son etiquetas de botón, con su tope de 20 (§3.16).

**Cómo sabe "Atrás" a dónde volver, sin recordar nada.** El dato viaja
**dentro del propio botón**: el id que se le manda a Meta es
`__atras__:web_precios`, y al volver dice de dónde venía. Un id de botón
admite 256 caracteres, de sobra. La alternativa era una columna nueva en
`contacts` y acordarse de mantenerla en cada rama; esto no necesita
migración ni guarda estado entre mensajes.

Atrás lleva al grupo que contiene la opción cuya respuesta se estaba
leyendo, con **el mismo texto con que se ofreció la primera vez**: volver
tiene que devolver a un sitio reconocible. Si esa opción colgaba del menú
principal, atrás **es** el menú principal.

Dos detalles al tocar esto:

  · **`atras` está en `ACCIONES_VALIDAS` pero NO en `ACCIONES`.** O sea:
    el validador la acepta, el desplegable no la ofrece. No es algo que
    se configure como la acción de una opción — se marca en "y le vuelve
    a ofrecer…". Es el mismo trato que tiene `enlace`, y sin ello
    `test_multitenant` falla, que es justo lo que tiene que hacer si el
    bot aprende una acción que el editor no conoce.

  · **La vista previa las pinta.** No están en `datos.menu`, así que hubo
    que armarlas también ahí: marcar una casilla y que el teléfono de al
    lado no cambie es justo lo que esa pantalla promete que no pasa.

Lo vigila `test_regresion.py` ("'Menú principal' y 'Atrás' se pueden
ofrecer siempre").

---

### 3.18 Un texto por defecto puesto donde no tocaba

El campo *"qué pregunta después"* de una opción caía en
`FALLBACK_MESSAGE` cuando estaba vacío. Y `FALLBACK_MESSAGE` es el
**"Disculpa, no entendí bien 🤔"**. O sea que a un cliente que acababa de
pulsar un botón y recibir exactamente lo que pidió, se le contestaba que
no se le había entendido:

    Página web creada por nosotros: 👇
    https://www.neo-redes.com/
    La tuya se diseña con la identidad de tu negocio.

    Disculpa, no entendí bien 🤔 ¿Puedes elegir una de las opciones…?

Solo salía cuando la opción tenía a quién ofrecer después, así que
estuvo escondido hasta que aparecieron las salidas fijas (§3.17): de
golpe, opciones que nunca habían tenido `luego` lo tenían.

> **El patrón:** un texto por defecto solo vale si dice lo mismo que
> diría el campo vacío. Aquí "vacío" significaba *"no digas nada más"*, y
> el defecto decía justo lo contrario. Si un campo opcional no tiene nada
> sensato que decir cuando está vacío, **lo que toca es callar**, no
> buscarle un texto prestado de otra situación.

Lo vigila `test_regresion.py` ("Una respuesta correcta NO lleva pegado el
'no entendí'").

---

### 3.19 Lo que el cliente escribe se entiende en cualquier paso (13-sep-2026)

Tres quejas del dueño el mismo día, y las tres eran el bot sin escuchar:

| Qué pasaba | Qué hace ahora | Dónde |
|---|---|---|
| "No entendí" → el cliente escribe "Quiero una página web" → otro "no entendí", sin botones a la vista | Reconoce el título de un botón escrito a mano, **también sin IA**; y el "no entendí" va con el menú debajo, en un solo mensaje | `cerebro/menu.py`, `bot_logic._no_entendi` |
| "Quiero volver al menú" a mitad de algo se tomaba como respuesta (la consulta para el asesor, un día) | Frases de `conversacion.palabras_menu` valen en cualquier estado menos NEW/ASKED_NAME | `bot_logic._pide_volver_al_menu` |
| "Hablar con un asesor" pedía contar la consulta otra vez | `conversacion.asesor_pide_detalle = false` avisa directo y dice `textos.asesor_directo` | `bot_logic._pasar_directo_a_asesor` |

Todo se edita en el **mapa**: paso nuevo "3 · Si escribe algo que no
entiende", y el paso de cualquier botón "Pasar a una persona". Los valores
por defecto de los dos interruptores son los de siempre salvo el menú tras
el "no entendí", que nace encendido: sin él, el bot parecía trabado.

Tres detalles que no se ven y conviene no deshacer:

  · **"menú" suelto solo cuenta si es lo único que escribe.** Nitro vende
    chatbots: "quiero cambiar el menú de mi restaurante" es una venta, no
    una orden de volver. Las frases de varias palabras sí cuentan dentro de
    un mensaje.
  · **El reconocedor sin IA no adivina.** Exige todas las palabras con peso
    del título (sin verbos como "crear" o "agendar"), y si dos opciones
    empatan —"Ver ejemplos" existe en tres ramas— no elige ninguna.
  · **Con IA, si Gemini no sabe o falla, se prueba el reconocedor sin IA**
    (`cerebro.interpretar`). Tras una cita solo se acepta que ELIJA una
    opción: su respuesta libre inventaría datos de una reunión que no
    conoce.

**La IA "que ya no responde" (mismo día).** En producción el cliente 1
tenía la IA contratada, "nace encendida" en No y clave propia guardada; la
clave del `.env` y `gemini-3.5-flash-lite` sí responden. La ficha no podía
decir más: lo que el dueño elige en su panel (`ajuste plan_ia`) y el último
fallo de Gemini no se veían desde `/superadmin`. Ahora la tarjeta de IA
dice si contesta HOY y por qué no, "¿Encendida?" escribe también ese ajuste
(antes cambiar la columna no hacía nada si el dueño había pulsado Apagar
una vez), y hay botón **Probar la IA** con la clave y el modelo de ese
negocio. Su error se tapa antes de ir a la URL.

### 3.20 Se entra con USUARIO y clave (13-sep-2026)

El dueño se quedó fuera de su panel: *"El negocio o la clave no son
correctos"*. Había añadido un usuario en `/superadmin` → Usuarios, y **al
crear el primer usuario la clave del servidor (`ADMIN_API_KEY`) deja de
abrir el panel del cliente 1** (`acceso._rampa`). Nada lo decía, y el
login pedía "Negocio" sin decir con qué usuario se entraba.

Ahora:

  · El login pide **Usuario** y clave. El usuario es un texto libre (un
    correo, "caja-2"…) y **único en toda la plataforma**, así que dice solo
    de qué negocio es. Sigue guardado en la columna `panel_users.email`:
    renombrarla era una migración sobre una tabla con RLS a cambio de nada.
  · La unicidad la impone `acceso.crear_usuario`/`renombrar_usuario`, **no
    un índice**: un índice único global rompería el despliegue si ya hubiera
    dos iguales en producción (`alembic upgrade && uvicorn`: sin migración
    no arranca). El login prueba todos los que casen por si acaso.
  · Las formas viejas siguen valiendo (`acceso.entrar`): escribir el nombre
    corto del negocio en la casilla, o dejarla vacía para el cliente 1.
  · Usuarios en la ficha: cambiar usuario, cambiar clave, quitar acceso y,
    ya sin acceso, borrar. Dice la dirección y cómo se entra, y avisa de la
    rampa de `ADMIN_API_KEY`.

> ⚠️ **La búsqueda del usuario va con `tenencia.sin_inquilino()`**, nuevo.
> El login corre con el cliente 1 puesto por el middleware, y con él el
> filtro automático no encontraría NUNCA al usuario de otro negocio. Es la
> misma trampa de `acceso.autenticar`, pero al revés: allí hacía falta
> fijar un inquilino; aquí, quitarlo. `test_rls` no se ha corrido con esto
> (pide PostgreSQL); sin inquilino anunciado la política deja pasar, que es
> lo que se necesita.

---

## 4. Trampas del diseño — la interfaz

Salieron haciendo el rediseño y son igual de fáciles de volver a pisar
que las de arriba.

### 4.1 Las cuatro suites en verde NO quieren decir que se vea bien

Pasó **cuatro veces**: el JavaScript con un agujero `{VARIABLE}` que lo
rompía entero, la pantalla de entrada centrada dentro de una página de
doble alto, el punto del bot convertido en una barra verde, y la bandeja
del móvil sin ninguna forma de abrir una conversación. Las suites ven el
HTML servido; no ven una pantalla.

**Nada visual se da por bueno sin abrirlo en el navegador**, en los dos
temas y en ancho de teléfono. Y con datos realistas: el solape de la
tabla de contactos solo aparecía con un último mensaje largo.

De cada fallo salió una prueba, que es lo que impide que vuelva:

- que no queden agujeros `{VARIABLE}` en el JavaScript servido;
- que toda clase del HTML de la entrada exista en la hoja;
- que el `@font-face` del logo siga declarado;
- que la conversación marque el cuerpo con `hay-hilo` y la bandeja no;
- que el icono del rail ponga su relleno a cero.

### 4.2 Las horas y los días los escribe el NAVEGADOR

El servidor manda el instante en UTC (`iso`) y el navegador lo traduce:
es el único de los dos que sabe en qué huso está sentado quien atiende.
El panel llegó a escribir "15:31 UTC" para un mensaje que en Medellín
llegó a las 10:31.

Por lo mismo, los separadores de día tampoco pueden venir del servidor:
un mensaje de las 20:00 en Medellín ya es del día siguiente en UTC, y el
hilo se partiría por donde no toca.

### 4.3 `[hidden]` necesita `!important`

El navegador aplica `hidden` con `display: none`, pero cualquier regla
nuestra que fije un `display` —y casi todos los botones fijan uno para
centrar su contenido— le gana por especificidad. El síntoma es un
elemento que el JavaScript dio por escondido y que sigue ahí.

### 4.4 En una pantalla estrecha, nada que no pueda encoger

Dos caras del mismo problema, y las dos llegaron a producción.

**En una rejilla, nada de columnas `auto`.** Con `1fr auto 34px`, un
último mensaje largo se quedaba con todo el ancho y la primera columna
colapsaba a **0px**: el nombre desaparecía y el cuadrito de iniciales se
pintaba encima del texto.

**En un flex, `min-width: 0` en lo que tenga que encoger.** Salió el
20-ago-2026, dicho por el dueño: en el teléfono la bandeja *"se ve
cortada hacia la derecha"* — el buscador, el último filtro, la hora de
cada conversación y el botón del pie.

Un flex item trae `min-width: auto`, que significa **no encojas por
debajo de tu contenido mínimo**. Y el contenido mínimo de la lista es el
**nombre más largo que haya**, porque el nombre va en `nowrap` para poder
cortarlo con puntos suspensivos. Un solo contacto con nombre largo
estiraba la columna entera a 452px dentro de una pantalla de 390.

    .col-lista { width: auto; flex: 1; min-width: 0; }
                                      ↑ sin esto, la lista manda

> Lo que las une, y es lo que hay que recordar: **con datos de prueba
> cortos ninguna de las dos se reproduce.** Hace falta un nombre largo de
> verdad y un último mensaje largo de verdad. Por eso esta llegó a
> producción con las cuatro suites en verde: una prueba que pide HTML no
> mide anchos, y los nombres de ejemplo eran cortos.

La forma de cazarlo sin ojo clínico, en el navegador:

    document.querySelectorAll('*').forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.right > innerWidth + 1) console.log(el, r.right);
    });

### 4.5 El titular hueco necesita su propia Manrope

El "2Tech" de la entrada va vaciado, y con la Manrope normal el 2, la e y
la h salen con rayas cruzadas por dentro: sus letras están hechas de
piezas superpuestas, invisibles cuando el texto va relleno. Bajar el peso
solo afina las rayas.

`scripts/fuente_del_logo.py` funde esas piezas y deja
`manrope-logo.woff2` (3 KB, solo las letras del logo). Si algún día se
cambia la tipografía del panel hay que correr **los dos** scripts:
`traer_fuentes.py` y `fuente_del_logo.py`.

### 4.6 En el teléfono hay que elegir qué se ve

No caben las cuatro columnas, y cuál se queda depende de dónde estés. Lo
marca `body.hay-hilo`, que solo lleva la página de una conversación:

- **En la bandeja** mandan la lista y la barra de navegación, que va
  **abajo** —56px de ancho son el 14% de la pantalla, y arriba a la
  izquierda es la esquina más incómoda para el pulgar—.
- **Con una conversación abierta**, el hilo entero y la flecha de volver.
  Sin barra: es lo mismo que hace WhatsApp.

Hay que descontar `env(safe-area-inset-bottom)`, o en un iPhone sin botón
la barra queda debajo de la franja del gesto y sus iconos no se tocan.

Y los botones del hilo se quedan en **icono**: con las palabras, la
cabecera se parte en dos filas y son 44px menos de conversación en cada
teléfono, para siempre.

### 4.7 Las etiquetas libres no se guardan a mano

La columna `etiquetas` de `contacts` es JSON, y quien la lee y la escribe
es `database.etiquetas_de()` y `guardar_etiquetas()`. Ese lector tolera
JSON roto a propósito: son datos que edita gente, y una excepción ahí
dejaría el panel entero sin pintar por una etiqueta mal guardada.

El servidor recorta, normaliza y quita repetidas, y devuelve **las que
quedaron**. El panel repinta con eso y no con lo que mandó, o se vería
una etiqueta de 60 caracteres que en la base está cortada a 24.

> **La nota interna no se le manda NUNCA al cliente.** El bot no lee esa
> columna, y quien escribe una nota cuenta con eso. Hay una prueba que lo
> vigila.

### 4.8 Un `display` de la hoja le gana a una clase suelta

Es la versión con `display` de la trampa de §4.3, y mordió el
20-ago-2026 al sacar la ficha en el teléfono.

Por debajo de 1200px la ficha deja de ser la cuarta columna y se abre
como **panel encima del hilo**, con el botón de la cabecera. Es el MISMO
elemento movido de sitio, no una copia: por eso las etiquetas y la nota
siguen funcionando sin tocar su JavaScript, y por eso no hay dos fichas
que acaben diferenciándose.

Lo que costó la vuelta fue apagar el botón en el escritorio:

    .ver-ficha              { display: none; }        (0,1,0)
    .acciones-chat button   { display: inline-flex; } (0,1,1)  ← gana

El botón salía en pantalla ancha, donde la ficha ya está a la vista y no
significa nada. **No da ningún error**: solo un botón de más que nadie
mira dos veces. Se arregla dándole padre al selector
(`.acciones-chat .ver-ficha`), y hay una prueba en `test_panel.py`.

Otras dos que salieron del mismo rato:

- **El aspa de cerrar necesita `sticky`, no `absolute` ni `fixed`.** La
  ficha tiene su propio scroll: en `absolute` el aspa se va con el
  contenido y al llegar a la nota interna —el final, y lo que más se
  viene a escribir— no queda ningún botón de cerrar. Y `fixed` tampoco
  vale, que es lo que no es obvio: la ficha lleva un `transform` para
  entrar deslizándose, y **un `transform` distinto de `none` convierte a
  sus hijos fijos en absolutos respecto a él**. Queda `sticky` con
  `float`, que lo saca del flujo sin empujar la cabecera.

- **Un Escape hace UNA cosa.** El campo de etiqueta nueva ya usaba
  Escape para cancelarse. Escuchando en burbuja, su handler corre
  primero y ya ha escondido el campo cuando el de la ficha pregunta, así
  que un solo Escape cerraba las dos cosas. El de la ficha va en fase de
  **captura**, para ver el estado de antes.

  Y de paso apareció uno viejo: `cerrarCampo()` esconde un campo que
  tiene el foco, y eso dispara `blur`, del que cuelga `confirmar()`. O
  sea que arrepentirse **guardaba** la etiqueta. Ahora se vacía el campo
  antes de esconderlo.

### 4.9 Una regla por etiqueta alcanza a lo que no debía

El 20-ago-2026 el dueño pidió algo menor: que *"Marcar estado"* midiera
lo mismo que los botones de al lado. Era un `<summary>` y no un
`<button>`, así que se había quedado fuera de la regla que iguala a los
demás — una pastilla de 94x23 entre tres cuadrados de 34x34, y 6px más
abajo. Entró en la misma regla, con su icono.

**Lo que apareció buscando eso ya estaba en producción.** Las opciones
del desplegable de estados también son `<button>`, y viven dentro de
`.acciones-chat`. O sea que se llevaban el tamaño de los controles de la
cabecera:

    .acciones-chat button { width: 34px; height: 34px; }

En el teléfono eso dejaba cada opción en **34px de ancho** dentro de un
menú de 48px: *"Esperando al cliente"* recortado a nada. Se comprobó
sirviendo el CSS de antes y el de después uno al lado del otro, para no
atribuirse un fallo ajeno ni al revés — idénticos, era de antes.

Se acota con `>`:

    .acciones-chat > button,
    .acciones-chat .estados > summary { ... }

> El patrón: **una regla que selecciona por etiqueta dentro de un
> contenedor alcanza a todo lo que ese contenedor llegue a tener dentro,
> hoy y dentro de un año.** Un menú desplegable, un tooltip, cualquier
> cosa que se meta ahí después. Cuando la regla describe "los controles
> de esta fila" y no "todos los botones de aquí abajo", el selector debe
> decirlo.

### 4.10 Un `<input>` se come los saltos de línea, y nadie se entera

El 6-sep-2026 el dueño avisó de que los textos del mapa no se guardaban
como los dejaba: escribía un mensaje en varias líneas y volvía convertido
en un párrafo corrido. **No era la base ni el guardado** — se comprobó el
camino entero (base, `ConfiguracionCliente`, el JSON que sirve la
pantalla) y todo conservaba el texto tal cual. Era el navegador.

**Un `<input type="text">` no puede contener un salto de línea.** No lo
avisa: al PINTAR el campo se los quita en silencio. Así que un texto ya
guardado con saltos los perdía **solo con abrir la pantalla**, y el
siguiente guardado escribía la versión aplastada encima. En el editor de
contenido bastaba con entrar y pulsar Guardar sin tocar nada, porque un
formulario manda todos sus campos, incluidos los que nadie miró.

Lo que decidía si un campo era renglón o cuadro era, en cada editor, una
cosa distinta y ninguna tenía que ver con el asunto:

    mapa         "el texto por defecto mide más de 40 caracteres"
    contenido    una casilla True/False escrita a mano, campo por campo

Con ese criterio, mensajes enteros iban en renglón —el cuerpo de cada
opción del menú, el "cómo pregunta qué necesita", el "cómo pregunta si
necesita algo más"— y perdían los saltos.

Ahora lo decide **una sola lista**, `mapa.TEXTOS_DE_UNA_LINEA`, que leen
los dos editores. Y dice lo único que importa de verdad:

> Va en renglón lo que WhatsApp manda como **rótulo** —la etiqueta de un
> botón, el título de una lista, la línea pequeña de una fila—, porque
> Meta lo manda en una línea con tope de caracteres. Todo lo demás es el
> **cuerpo de un mensaje**, y ahí WhatsApp respeta los saltos y los
> espacios tal cual.

Dos trampas más del mismo viaje, las dos igual de mudas:

  · **Un formulario manda los saltos en `\r\n`.** Ese `\r` se guardaba
    dentro del mensaje y viajaba a WhatsApp. No se ve, no da error y se
    acumula. Se normaliza al leer (`contenido._como_se_escribio` y
    `superadmin._sin_retornos`).

  · **El HTML se come el salto pegado a `<textarea>`.** Un texto que
    empiece por una línea en blanco la perdía en cada carga. Por eso
    `contenido._campo` escribe un `\n` de más justo después de la
    etiqueta de apertura. **No lo quites.**

Y `.strip()` dejó de aplicarse al cuerpo de un mensaje: una línea en
blanco al final o una sangría son parte de lo que se quiso escribir. Solo
se recorta lo que es **solo** espacios, que es un campo vacío escrito con
la barra espaciadora y tiene que contar como vacío para que el bot caiga
en su texto por defecto.

Lo vigila `test_regresion.py` ("Un mensaje se guarda con los saltos y los
espacios que tiene"), incluido que el salto pegado al `<textarea>` siga
ahí.

### 4.10b Un comentario CSS mal cerrado se come las reglas de detrás

Se coló editando §4.11 y **no dio ningún error**: al añadir un párrafo al
comentario del `textarea`, el texto nuevo quedó DESPUÉS del `*/`. Desde
ahí hasta el siguiente `*/`, todo era basura para el navegador — y entre
esa basura estaba la regla `textarea { min-height … max-height … }`.

Resultado: los cuadros dejaron de crecer y volvieron a salir con su
barrita, exactamente como antes de arreglarlo. La pantalla se veía "casi
bien", que es la peor forma de romperse.

    python -c "import re,io; s=io.open('app/web/estaticos/superadmin.css',
    encoding='utf-8').read(); print('*/' not in re.sub(r'/\\*.*?\\*/','',s,flags=re.S))"

Eso dice `True` si están todos emparejados. Merece la pena cuando se toca
un comentario largo: son los que se editan sin releer.

### 4.11 Los cuadros de texto crecen con lo que se escribe

Del mismo aviso: un `<textarea rows="3">` no se mueve, y los textos del
bot no son de tres renglones. `superadmin-campos.js` les pone la altura
de su contenido en cada tecla, con tope de `min(460px, 60vh)` — en un
teléfono, 460px son dos tercios de la pantalla.

Tres cosas que costaron y no se ven al leer el código:

  · **Primero `height:auto`, luego `scrollHeight`.** Sin eso el cuadro
    crece y no vuelve a encoger nunca al borrar.
  · **Un campo escondido mide cero.** Dentro de un `<details>` cerrado
    `scrollHeight` es 0, así que se recalcula al abrirlo.
  · **`field-sizing: content` no basta.** Hace lo mismo en una línea de
    CSS, pero hoy solo la entienden los Chrome nuevos: en Firefox y en
    Safari el cuadro se quedaría clavado y nadie se enteraría. Está
    puesta, y el guion sigue haciendo falta.

`textarea.mono` queda fuera a propósito: es el JSON de la cuenta de
servicio y el logo en base64, una línea de veinte mil caracteres.

**Y se acomodan al final de `dibujar()`, no solo al crearlos.** `campo()`
lo pide al construir cada cuadro, pero ahí todavía no está en la página
—la tarjeta se arma entera y luego se cuelga del árbol—, y un elemento
suelto mide cero: no hay nada que medir. Funcionaba en la primera carga
de puro azar (el guion de los campos corre después) y dejaba de
funcionar en cuanto se repintaba el árbol, que es a cada cambio.

### 4.11b El árbol se pliega

Salía entero desplegado. Con tres niveles son treinta tarjetas seguidas y
encontrar dónde está uno es ir bajando y contando sangrías. Cada opción
con algo dentro lleva su triángulo, y arriba hay *Plegar todo* /
*Desplegar todo*.

Se guarda por RUTAS (`"0,1"`) y no por objetos, porque `dibujar()` rehace
el árbol entero en cada cambio y los objetos no sobreviven. Vive solo en
memoria: al recargar sale todo desplegado, y no se guarda a propósito —
habría que decidir qué pasa cuando el menú cambia por debajo.

**Al abrir un paso se despliega lo que haga falta para verlo**
(`desplegarHasta`). Sin eso, llegar a un paso desde un error de guardado
(§4.12) podía dejarlo escondido dentro de un grupo plegado: el editor
decía "es este" y no se veía ninguno.

### 4.12 Un error que no dice DÓNDE está no sirve de mucho

El mapa se valida entero antes de escribir nada, y eso es lo que hace
seguro dejarlo en manos de quien no programa: lo peor que pasa es que no
deje guardar. Pero el aviso decía solo **qué** pasaba:

> "'Ver un ejemplo' abre más opciones pero está vacía: el cliente
> pulsaría y no recibiría nada."

Con un menú de tres niveles eso deja abriendo pasos uno por uno buscando
cuál es. Y dos botones pueden llamarse igual en ramas distintas, así que
el título ni siquiera identifica el sitio.

`_revisar_mapa` devuelve ahora tres cosas: el motivo, **dónde** —el
recorrido tal y como se lee en pantalla— y la **ruta**, los índices del
paso. Con la ruta, el editor **abre ese paso solo**, lo trae a la vista y
escribe el motivo dentro de él.

Tres decisiones que parecen detalles y no lo son:

  · **`donde` habla el idioma de la pantalla**: "Botón 2 · Ver un
    ejemplo", no el identificador `ver_ejemplo` —que no sale en ninguna
    parte— ni "el paso 2". Lo arma `_nombre_de_paso`, que repite la
    cuenta de `superadmin-mapa.js:tituloDePaso` (más de 3 en el grupo →
    "Fila"; si no, "Botón"). **Si una cambia hay que cambiar la otra**: un
    error que nombra un botón que en pantalla se llama de otro modo manda
    a buscar donde no es. Lo vigila `test_regresion.py`.

  · **El motivo va DENTRO del paso**, no solo en la banda de arriba. Con
    un paso hondo, la banda se queda fuera de la pantalla en cuanto se
    baja hasta él: había que ir y volver para leer qué pasaba.

  · **El desplazamiento es de golpe, sin `behavior: 'smooth'`.** Con el
    suave la página se quedó quieta más de una vez —a un desplazado suave
    lo cancela cualquier otro, y al abrir el paso la vista previa mueve su
    propio chat—, o sea que avisaba del error y no llevaba a ninguna
    parte. El destello rojo es lo que dice dónde aterrizó la vista.

Y `.paso` lleva `scroll-margin-top: 88px` porque la cabecera es sticky:
sin eso se llega al paso con su título escondido justo detrás.

Los errores de `ConfiguracionCliente` —el respaldo, los que nombran la
opción por su identificador— pasan por `_donde_esta`, que busca ese id en
el árbol para poder llevar igual. Si no reconoce ninguno, el mensaje se
enseña tal cual y no se inventa un sitio.

---

## 5. Cómo verificar que no rompiste nada

Las pruebas **no usan pytest**: son scripts que devuelven 0 o 1.

```bash
python tests/test_multitenant.py    # aislamiento entre clientes (la más importante)
python tests/test_regresion.py      # flujo del bot
python tests/test_ia.py             # la IA y sus topes
python tests/test_panel.py          # el panel de atención
```

Las cuatro pasan limpias. **Un fallo es una regresión**, sin excepciones
que recordar.

Y lo que las cuatro NO pueden ver, dicho aquí para no volver a confiarse:

  · **Cómo se ve una pantalla.** Han estado en verde con el panel roto
    (§4.1). Para eso está `python scripts/servir_de_prueba.py`.
  · **Si Meta acepta el mensaje.** Las pruebas sustituyen los envíos, así
    que un payload que Meta rechazaría pasa en verde. Por eso las de
    §3.16 sustituyen `_post` y no los envíos: para hacer correr el código
    que aplica los topes. Si escribes una prueba de envío, mira eso antes
    o estarás probando tu propio doble.

La quinta necesita PostgreSQL, así que se salta sola en una máquina sin
base y solo se corre contra una de ensayo — **nunca la de producción**,
porque escribe y borra filas:

```bash
RLS_DATABASE_URL="postgresql://..." python tests/test_rls.py
```

> **Una tabla nueva con `client_id` necesita DOS cosas**: entrar en
> `database.MODELOS_DEL_INQUILINO` (el filtro del ORM) y su política en
> una migración (la cerradura de PostgreSQL, ver `c3f1a7d2b904`). Si
> falta la segunda, todo funciona y nadie se entera de que esa tabla
> quedó sin cerradura. `test_rls.py` es lo único que lo caza.
>
> Columnas nuevas en una tabla que ya tiene política **sí** la heredan;
> por eso las etiquetas y la nota interna no necesitaron una nueva.

**Y para cualquier cosa visual, el navegador** (§4.1). En producción el
panel vive en `https://bot.nitro2tech.com` (§7.6); la dirección de
`onrender.com` sigue funcionando y las dos sirven lo mismo. Para
levantarlo en local con una base limpia — `bot.db` de la raíz es anterior a la
migración y ya no arranca, le falta `messages.client_id`:

```bash
DATABASE_URL="sqlite:///C:/ruta/suelta/prueba.db" \
  ADMIN_API_KEY="una-clave-de-prueba" \
  python -m uvicorn app.main:app --port 8399
```

Después de tocar código:

```bash
python -m graphify update .
```

---

## 6. El bot y lo que cuesta cada mensaje

Desde el **1-oct-2026** Meta cobra cada mensaje de servicio, así que una
respuesta partida en dos son dos cobros en el recibo del cliente.

    python scripts/medir_verbosidad.py            # el resumen
    python scripts/medir_verbosidad.py --detalle  # y qué manda en cada paso

Está en **1,00 mensajes por cada uno del cliente**, que era el objetivo:
una respuesta por cada cosa que hace. Venía de 1,19.

Lo que hay que respetar:

- **`_decir_y_ofrecer()` es el único sitio que sabe juntar un texto con
  sus opciones.** Si aparece otra rama con el mismo patrón —decir algo y
  acto seguido preguntar cómo seguir—, que la use en vez de repetirla.
- **El cuerpo de un mensaje interactivo admite 1024 caracteres**, y uno
  de texto suelto 4096. Pasarse **no recorta**: Meta rechaza el mensaje
  entero y el cliente se queda sin nada, que es peor que el mensaje que
  se quería ahorrar. Por eso, cuando no cabe, se vuelve a partir en dos.
- **El aviso al dueño no cuenta.** Sale por el mismo sitio que la
  respuesta al cliente, y contarlo llevó a una conclusión falsa la
  primera vez que se midió. Va a otro número y no se le cobra al cliente.

---

## 7. Lo que sigue siendo así a propósito

### 7.1 El `server_default="1"` se queda

Es la red que permitió migrar sin reescribir cuarenta consultas a la vez.
Quitarlo hoy no arregla nada y puede romper una inserción olvidada.

### 7.2 No se puede borrar un negocio, solo pausar

Deliberado. Significa que las filas de prueba se quedan en el listado; si
molestan, se quitan con un `DELETE` a mano.

### 7.3 Dos ajustes que solo existen como variable de entorno

`OWNER_TEMPLATE_NAME` (la plantilla con la que el bot avisa al dueño
pasadas 24 h) e `IA_MAX_MENSAJES_DIA` (tope diario de IA por contacto).
En cuanto un cliente tiene `negocio_config` deja de leer el entorno
(`config_cliente.py:153`), así que esos dos valores se le pierden.

**Desde el 20-ago-2026 ya no hay ningún cliente que lea el entorno.** Se
comprobó que ninguno de los dos estaba puesto en Render, así que al apagar
la rampa no se perdió nada. De los dos:

- **`OWNER_TEMPLATE_NAME` ya no depende del entorno.** El mismo día se le
  dio sitio en el contenido del negocio —`[avisos].plantilla`, con
  `plantilla_idioma` al lado— y un campo en el editor. El cliente 1 ya
  tiene puesta `aviso_lead` [es], comprobado en `/admin/status`. Un
  negocio nuevo hay que acordarse de dárselo: nace sin plantilla, y sin
  ella sus leads se pierden pasadas 24 h sin que nadie lo note.
- **`IA_MAX_MENSAJES_DIA` sigue sin tener otra vía** y se queda en su
  defecto de 40 (`config_cliente.py:575`), que es lo que llevaba usando
  siempre. Si algún día hace falta cambiarlo por cliente, el patrón a
  copiar es el de la plantilla.

> Y de paso: en la cascada, un valor **vacío** en el TOML cuenta como "no
> dicho" y cae al defecto, igual que en `_col` y `_env`. Antes no, y un
> campo numérico que alguien dejara en blanco desde el editor reventaba en
> el `int()` de quien lo leía.

> La forma de mirarlo sin entrar a la base es `/admin/status`:
> `configuracion.plantilla_avisos` e `ia.tope_diario`.

### 7.4 El freno de los intentos de clave vive en memoria

Se pierde al reiniciar y no se comparte entre procesos. Da igual mientras
haya un solo proceso (§3.9). El día que el bus de avisos se mueva a Redis
o a `LISTEN/NOTIFY`, el freno se muda con él.

### 7.5 Secciones que el editor de contenido no cubre

Las pestañas del Sheet (`[sheets.pestanas]`) y los orígenes
(`[origenes]`) **se conservan intactas al guardar**, pero no se editan
desde el panel. Se siguen tocando con `scripts/negocio_a_la_base.py`.

---

### 7.6 El panel vive en un subdominio, no en una subruta

Desde el 20-ago-2026 la plataforma tiene dominio propio:

    https://nitro2tech.com        la web corporativa (Vercel), intacta
    https://bot.nitro2tech.com    el panel y las políticas (Render)

Se montó con **un solo registro CNAME** en Namecheap —`bot` apuntando al
host de Render— y el certificado lo emite Render solo. La dirección de
`onrender.com` sigue funcionando: NO se activó `DOMINIO_BASE`, así que
el modo de resolución no cambió y el panel se sigue entrando con el
nombre del negocio y la clave.

**Por qué no `nitro2tech.com/plataforma/cliente1`**, que es lo que se
pidió primero. Una subruta obliga a cinco cosas, y ninguna es pequeña:

1. Un proxy delante, porque la web y el bot son dos servidores distintos.
2. Un tercer modo de resolución del inquilino: hoy sale del subdominio o
   del pase, y por ruta no se sabe hacer.
3. Reescribir todas las rutas absolutas del HTML servido —`/estaticos/`,
   `/admin/`, los iconos—, que bajo un prefijo apuntarían a otro sitio.
4. **La PWA se rompe.** El service worker y el manifiesto están en la
   raíz a propósito: el alcance de un service worker es la carpeta desde
   la que se sirve.
5. Todos los clientes comparten cookies, porque comparten origen.

Y el punto de fondo, que ya está en el docstring del middleware: con
subdominios hay **dos** comprobaciones que deben coincidir —la dirección
dice un negocio y el pase firmado dice el mismo—; sin ellos queda una
sola. Una subruta deja el aislamiento igual que hoy a cambio de todo ese
trabajo.

**El día que haga falta un subdominio por cliente** —`panaderia.nitro2tech.com`—
ya está escrito: es un wildcard `*.nitro2tech.com` en el DNS y poner
`DOMINIO_BASE`. Lo hace `tenencia.resolver_por_host`, que se escribió
para eso.

> ⚠️ **Activar `DOMINIO_BASE` tiene un efecto que no es obvio**: la
> resolución pasa a ser estricta y un host que no sea de ningún cliente
> deja de servir. `/privacidad` por `onrender.com` daría **404**, y esas
> URLs están pegadas en el panel de la App de Meta. Hay que cambiarlas
> antes. `/webhook` y `/superadmin` no se ven afectados: están excluidos
> del middleware.

## 8. Lo que depende de fuera

| | Estado |
|---|---|
| `SUPERADMIN_KEY` en Render | ✅ Puesta |
| Row-Level Security | ✅ Desplegada el 19-ago-2026 |
| Verificación de negocio ante Meta | 🔄 **Enviada**, en `pending`. Es para el bot de casa; **ya no bloquea vender** (§10) |
| App Review (Advanced Access) | ⬜ Sin enviar, y **ya no hace falta**: cada cliente trae su propia App, así que no mandamos mensajes en nombre de nadie (§10) |
| Que un cliente dueño de su App no necesite App Review | ⬜ **Sin comprobar contra un caso real.** Es el supuesto que sostiene el modelo nuevo; se resuelve con el primer alta (§2) |
| `nitro2tech.com` | ✅ Comprado y respondiendo (20-ago-2026), con la web corporativa en Vercel |
| `bot.nitro2tech.com` | ✅ El panel y las políticas. Un CNAME en Namecheap al host de Render, certificado automático. Ver §7.6 |
| Webhook de Meta | ✅ Apunta a `bot.nitro2tech.com/webhook` desde el 20-ago-2026. Comprobado: entra tráfico y `rechazados_por_firma` en 0 |
| Perfil de WhatsApp | 🔄 Sitio web ya actualizado. **Falta la dirección**, y tiene que ser idéntica al certificado |
| `SESSION_SECRET` en Render | ⬜ Opcional: si falta se deriva de `SECRETS_KEY` |
| `SMTP_*` en Render | ✅ Puestas el 27-ago-2026. Sin ellas los avisos por correo no salen y el bot funciona igual (§11.8) |
| Método de pago de Meta (el nuestro) | ⬜ **Sin configurar.** Bloquea las plantillas ya, y TODO el 1-oct-2026 |
| Plantilla `aviso_lead` | ✅ Aprobada en Meta, `[es]`, 4 variables |

### Fechas que condicionan el proyecto

| Fecha | Qué pasa |
|---|---|
| **1-sep-2026** | Meta publica las tarifas por país de los mensajes de servicio |
| **1-oct-2026** | Meta empieza a cobrar los mensajes de servicio |
| **15-oct-2026** | Embedded Signup v2 se descontinúa — construir directo sobre **v4**, y desconfiar de los tutoriales, que casi todos son de v2 |
| **16-oct-2026** | Google retira `gemini-2.5-flash` y `gemini-2.5-flash-lite` |

---

## 9. El mapa: qué hace cada archivo que no es obvio

```
app/core/tenencia.py          quién es el inquilino de esta petición
app/core/config_cliente.py    la configuración de UN negocio
app/core/secretos.py          cifrado de credenciales por cliente
app/core/acceso.py            quién entra al panel de cada negocio
app/core/freno.py             el freno a los intentos de clave
app/core/consumo.py           el medidor de IA: qué se factura
app/core/eventos.py           el bus de avisos en vivo (un solo proceso)
app/core/correo.py            los avisos por correo a cada area
app/core/huecos.py            rellena {name} y {url} SIN str.format
app/integrations/meta_estado.py  si las credenciales de un cliente sirven
app/web/guia.py               /conectar: la guia que se le manda al cliente

Y los del super-admin, que desde el 27-ago tambien viven fuera de Python
(§11.10): `superadmin.css`, `superadmin-mapa.js` (el editor del arbol),
`superadmin-contenido.js`, `superadmin-campos.js` (los cuadros que
crecen), `superadmin-logo.js`, `superadmin-tema.js` (el
interruptor de tema y el contador de cambios) y `nitro-logo.svg`.
app/web/paginas_publicas.py   privacidad, términos y borrado de datos
app/web/superadmin.py         la consola de la plataforma
app/web/mapa.py               el editor de lo que dice el bot
app/web/activos.py            CSS y JS con versión por contenido

scripts/servir_de_prueba.py   levanta el panel con una base sembrada
scripts/negocio_a_la_base.py  pasa un negocio.toml a la base
scripts/panel_usuario.py      alta y baja de usuarios del panel
scripts/medir_verbosidad.py   cuántos mensajes manda el bot
scripts/traer_fuentes.py      baja Manrope e IBM Plex y las deja aquí
scripts/fuente_del_logo.py    la Manrope sin solapes, solo para el logo
scripts/pdf_de_documento.py   genera META_VERIFICACION.pdf desde su .md
```

Y los del panel, que se cargan **en orden** y comparten ámbito:
`panel-base.js` declara lo que ven los demás; después `panel-plan.js`,
`panel-listado.js`, `panel-chat.js`, `panel-ficha.js`, `panel-vivo.js`,
`panel-contactos.js`, `panel-ajustes.js`, `panel-login.js`, y siempre al
final `panel-tema.js` y `pwa-registro.js`.

---

## 10. La App de Meta es de cada cliente (27-ago-2026)

El cambio de modelo. Antes había UNA App de Meta —la nuestra— y los
números de todos los clientes vivían dentro. Eso tenía dos problemas, y
el segundo no es técnico:

- Conectar el número de un cliente dependía de que Meta nos aprobara el
  **App Review a nosotros**. Un trámite ajeno como cuello de botella de
  todas las ventas.
- Nos hacía **dueños de números que no son nuestros**. Si un cliente se
  iba, su número estaba en nuestra App.

Ahora cada negocio crea su App desde su propio `developers.facebook.com`,
con su WABA y su número, y nos entrega cuatro credenciales. Nosotros
ponemos hosting, base y panel.

> El supuesto sobre el que se apoya: un negocio dueño de su App **y** de
> su WABA no necesita App Review — Meta lo trata como desarrollador
> directo. **Todavía no está comprobado contra un cliente real**, y es lo
> primero que hay que hacer (§2).

### 10.1 Cada cliente tiene su propia URL de webhook

`/webhook/{webhook_token}`, y **no es celo de aislamiento: lo obliga la
firma.**

Meta firma cada webhook con el App Secret, que ahora es de cada cliente.
Para saber con cuál validarlo hay que saber primero de quién es el POST — y
lo único que lo diría dentro del cuerpo es el `phone_number_id`, que es
justo lo que todavía no se puede dar por auténtico. Elegir con qué secreto
comprobar la autenticidad usando un dato del propio mensaje sin firmar es
hacer la comprobación al revés.

Con el inquilino en la URL el orden queda bien:

    URL → cliente → su App Secret → firma → parsear → atender

Y resuelve además el **GET de verificación**, que no trae
`phone_number_id` por ningún lado: con una sola URL no habría manera de
saber qué cliente está configurando su webhook.

El `phone_number_id` se sigue mirando, pero ya como **confirmación**: caza
el error más probable del alta, que es un cliente pegando la URL de otro.
Con la firma sola no se cazaría —cada uno firma bien lo suyo— y los
mensajes de un negocio entrarían en la bandeja del vecino.

`/webhook` a secas sigue abierto para el bot de casa. **Se retira cuando
el último cliente esté migrado**: hasta entonces es la única puerta que
valida con un secreto compartido.

### 10.2 Quitar los globales de `config.py` no rompe nada, y hay que saber por qué

`APP_ID`, `APP_SECRET` y `VERIFY_TOKEN` bajaron a la cascada por
inquilino. Al no estar ya definidos en el cuerpo de `config.py`,
`config.APP_SECRET` pasa por el `__getattr__` que resuelve el inquilino; y
sin inquilino cae en `base()`, que lee del **entorno**. O sea que los
scripts y los caminos sin migrar siguen viendo la variable de Render de
siempre.

**Volver a subirlos ahí es lo que rompería**: se convertirían en el valor
de todos, y el App Secret del dueño validaría la firma de otro cliente.

### 10.3 Meta devuelve el token DENTRO de sus mensajes de error

Salió comprobando el botón *Probar credenciales* en el navegador, y es el
tipo de fallo que ninguna suite ve.

A un token mal copiado, Meta contesta *"Malformed access token EAAG…"*,
con el token entero pegado. Ese texto se pintaba en la banda del
super-admin y viajaba en la URL de redirección — o sea al **historial del
navegador y a los logs del servidor**, que son los dos peores sitios donde
puede estar la credencial de un cliente.

Se tapa en `meta_estado._tapar()`, que es el único módulo que conoce los
secretos y por tanto el único donde no se puede olvidar. Hay prueba de
regresión, incluida la de que una cadena corta (`"123"`) **no** se tapa,
para que no destroce textos normales.

> El patrón, que vale para lo que venga: **lo que devuelve un tercero en
> un mensaje de error no es texto neutro.** Antes de pintarlo o de
> meterlo en una URL, hay que preguntarse qué trae dentro.

### 10.4 El tramo de 250 muerde callado

Un negocio que todavía no completó su Business Verification puede mandar
**250 mensajes cada 24 h**. Al 251 Meta rechaza, el bot deja de responder
de golpe y no hay ninguna señal: es el mismo silencio que un token
revocado o que un cliente pausado.

Por eso `meta_estado` lee el tramo de envío del número y lo enseña como
**aviso** aunque todo lo demás esté bien. `aviso` y `mal` no significan lo
mismo y no hay que mezclarlos: *mal* es "esto no funciona"; *aviso* es
"funciona, y hay algo que saber" — que es exactamente lo que hace que este
caso no se vea venir.

### 10.5 Lo que NO se toca al editar la ficha de un cliente

`webhook_token` y `verify_token` son columnas del cliente y **no están en
el formulario a propósito**. El cliente ya los tiene pegados en su App de
Meta: cambiarlos lo deja sin recibir mensajes y sin que nada dé error.

Por lo mismo, la caja que los enseña va **arriba** del formulario y no
dentro. No es un campo que se edite, es un dato que se entrega.



---

## 11. Dos planes y los avisos por area (27-ago-2026)

### 11.1 El paquete de IA se CONTRATA

`clients.ia_contratada`, y solo se toca desde `/superadmin`. Separa lo
comercial de lo operativo, que estaban mezclados:

    ia_contratada   lo vendimos. Solo /superadmin.
    ia_activa       si lo contrato, como nace: encendido o apagado.
    ajuste plan_ia  lo que el dueno eligio despues en su panel.

Hasta ahora la puerta era `cerebro.hay_clave()` — "hay clave de Gemini?".
**Esa nunca fue la pregunta**: la clave la ponemos nosotros y es la misma
para todos, asi que cualquier cliente podia entrar a su panel, darle a
"Encender IA" y cargarnos el consumo sin haber comprado nada.

En False, `plan_activo()` devuelve siempre Basico Y el panel no enseña el
control. **Las dos cosas.** Esconder el boton mientras el endpoint sigue
aceptando la peticion no es una puerta, es un adorno — por eso
`cambiar_plan()` tambien lo comprueba.

> ⚠️ **Nace en False para todos, incluido el cliente 1.** Al desplegar,
> quien tuviera la IA encendida se queda en Basico hasta que se le marque
> la casilla. El bot no se rompe: responde con el menu, que es lo que ya
> hace cuando Gemini falla. El valor por defecto de algo que se cobra
> tiene que ser "no lo compro".

La variable de entorno `IA_CONTRATADA` **solo la ve un cliente sin
configuracion propia** — o sea la configuracion base de los scripts y las
pruebas. Mismo patron que `ia_activa`, y por lo mismo: con el entorno
mandando sobre la columna, ponerla en Render se la regalaria a todos.

### 11.2 Los avisos se reparten entre hasta 3 areas

Antes todo iba a `OWNER_PHONE_NUMBER`: un solo numero recibia las citas,
las consultas, las peticiones de asesor y las cancelaciones. Ahora un
negocio declara sus areas en `[avisos].destinos` de su `negocio_config`, y
dice de que opciones del menu se encarga cada una:

    Ventas    -> opt_ventas
    Soporte   -> opt_soporte
    Contratos -> (ninguna)     <- recoge lo que nadie reclamo

Se enruta por `Contact.servicio`, que es la opcion de PRIMER NIVEL que
eligio el cliente y que ya se venia guardando. Por eso el editor solo
ofrece opciones de primer nivel: un submenu ahi seria una casilla que
nunca se cumple.

**LA REGLA QUE NO SE PUEDE ROMPER**: un aviso nunca se queda sin
destinatario. Un aviso que no se entrega es una venta que nadie atiende, y
no da ningun error — se ve igual que un dia sin clientes. De ahi el orden
de `notificaciones.a_quien()`:

  1. Los destinos que reclaman esa opcion.
  2. Si ninguno, los que no reclaman ninguna (el area general).
  3. Si tampoco, TODAS antes que perderlo.
  4. Sin areas configuradas, el numero del dueno — como siempre.

Con la lista vacia se cae directo al paso 4, asi que un negocio que no
configure nada funciona exactamente como antes.

Otras dos decisiones, por si se reabren:

- **Un area sin numero se descarta entera**, aunque tenga nombre y
  casillas. Es la forma de borrarla. Guardarla a medias la dejaria en la
  lista pareciendo configurada y sin poder recibir nada.
- **El tope se aplica DESPUES de descartar las invalidas.** Al reves, un
  area a medio llenar gastaba un cupo y dejaba fuera a una buena que venia
  detras, sin decir nada.

- **El aviso de "tu bot no tiene menu" NO se enruta**, y no es un olvido:
  no es un lead de un area, es que el bot esta a medio configurar.
  Mandarselo a Ventas seria avisarle al que no puede arreglarlo.

### 11.3 Cuantas areas: lo decide el plan, y se puede ajustar

    sin IA (Basico)   3 areas
    con IA (Pro)      6 areas

`clients.max_destinos_avisos` en NULL = lo que da el plan, que es lo que
quiere casi todo el mundo. Con algo escrito manda eso, para el caso
pactado con un negocio concreto.

Era una constante (`MAX_DESTINOS_AVISOS = 3`) y dejo de serlo por un
motivo que no es tecnico: **el numero lo decide la venta, y una venta no
puede depender de un despliegue.** Si un cliente negocia un area mas, eso
se resuelve en /superadmin en diez segundos.

> ⚠️ La misma trampa que §3.10: con la columna puesta, cambiarle el plan
> al cliente NO le cambia el cupo. Es lo correcto —es lo pactado con ESE
> negocio— pero desde fuera "le subi a Pro y sigue con 3" encaja con dos
> historias. El campo de la ficha enseña de marcador lo que daria su plan,
> asi que se ve cual manda.

**EL CUPO SALE DE `ia_contratada`, NO DE `plan_activo()`.** Suenan igual y
elegir mal aqui tiene una consecuencia fea: `plan_activo()` es operativo,
asi que apagar la IA un rato desde el panel le recortaria las areas — y al
volver a encenderla no reapareceran, porque el editor ya habria guardado
la lista corta. `ia_contratada` es lo que compro, y eso es lo que paga el
cupo.

Un cero cuenta como "no dicho" y cae al plan, igual que dejarlo vacio. Un
negativo se acota a 1: nunca puede dejar a un negocio sin poder recibir
nada.

### 11.4 Las areas se editan en la FICHA, no en el contenido

Estuvieron en el editor de contenido y el dueño no las encontro. Ese es el
sintoma que lo justifica: **si hay que explicar donde esta, esta mal
puesto.**

Y estaban mal por una razon de fondo, no solo de sitio: los numeros de
aviso **no son contenido**. El editor de contenido es lo que el bot DICE
—textos, menu, precios—; a quien se le avisa es configuracion, y va al
lado del numero del dueño, que es lo mismo con otro nombre. Ahora una sola
caja —"Avisos: a quien le llega un lead"— tiene el numero del dueño, el
cupo y las areas.

    ⚠️  LAS AREAS VIVEN EN `negocio_config`, QUE ES LO QUE EL EDITOR DE
        CONTENIDO REESCRIBE ENTERO.

Por eso `contenido.leer()` **no toca `avisos.destinos`**. Si alguien vuelve
a poner ahi un `avisos["destinos"] = leer_destinos(formulario)`, el
formulario ya no trae esos campos, asi que guardaria una lista vacia y
**borraria todas las areas del negocio** — sin error, y el dueño lo
notaria cuando dejaran de llegarle los leads. Hay prueba de regresion.

Dos detalles del guardado desde la ficha, los dos silenciosos si se
rompen:

- **El cupo se lee del FORMULARIO, no de la base.** En esa misma peticion
  puede haber cambiado —le acabas de subir el plan— y con el valor viejo
  se recortarian justo las areas que se acaban de escribir.
- **`negocio_config` se REASIGNA, no se muta en sitio.** Con una columna
  JSON, SQLAlchemy no se entera de un cambio hecho dentro del diccionario
  y el UPDATE sale sin el.

### 11.5 El pais va en su propio cuadro, y hay boton de prueba

El dueño intento configurar un numero y no le llego el aviso. La pregunta
con la que lo conto —"si quiero agregar un numero de España, como lo
pongo?"— señala el sitio: el campo pedia "con indicativo y sin signos" y
esperaba que quien lo rellenara supiera armar el formato internacional.

Ahora son dos cuadros —**Pais** y **Su WhatsApp**— y se juntan en
`config_cliente._leer_destinos`, que es por donde pasa todo el mundo.

Se guardan APARTE (`indicativo` y `numero`) y no unidos, porque volver a
partirlos para pintarlos no se puede hacer bien: `57` y `571` son los dos
prefijos validos y partir por el sitio equivocado deja un numero que
parece bien y no existe.

**Al unir hay una trampa**: si el numero ya viene entero no se le pega el
pais otra vez. Pasa con lo guardado antes de que existieran los dos
cuadros y con quien pega el numero completo en el cuadro de la derecha. Se
distingue **por longitud y no por prefijo** —`57` es un comienzo valido de
un numero local, asi que "empieza por el indicativo" no prueba nada—: un
local no llega a 11 digitos en ningun pais que nos importe (Colombia 10,
España 9, Mexico 10, EE.UU. 10) y uno internacional siempre los pasa.

La lista de indicativos es un `datalist`, no un `<select>`: un desplegable
cerrado seria un techo invisible el dia que un cliente tenga un numero de
un pais que no este. Es §3.11 otra vez.

#### El boton "Mandar un aviso de prueba"

Lo que de verdad faltaba. **Un aviso que no llega no da ninguna señal**:
el cliente final recibe su respuesta con normalidad y el unico rastro
queda en los logs del hosting, que es donde no va a mirar quien administra
el bot. Entre "el numero esta mal escrito", "hace mas de 24 h que esa
persona no le escribe al bot y no hay plantilla" y "el token no tiene
permiso", desde fuera no se distingue nada: en los tres casos no pasa
nada.

El boton manda un mensaje de verdad a cada numero y traduce lo que
contesta Meta. Cada codigo manda a mirar a un sitio distinto y por eso no
se meten todos en "revisa el numero":

    131026  el numero no recibe WhatsApp -> casi siempre el pais
    131030  la App del cliente sigue en modo prueba
    131047  fuera de la ventana de 24 h -> hace falta plantilla
    190     el token no vale para enviar

Dos decisiones del boton:

- **Prueba lo que hay EN PANTALLA, no lo guardado.** Vive dentro del
  formulario de la ficha, asi que se puede probar un numero antes de
  guardarlo — y no hay forma de creer que se prueba lo nuevo mientras se
  prueba lo viejo.
- **Pasa por la MISMA limpieza que usa el bot.** Con una normalizacion
  propia, la prueba diria que va bien y el aviso seguiria sin llegar, que
  es peor que no tener prueba.
- Envia por `wa._post` y no por `send_text_message`: una prueba no debe
  quedar en el historial, o cada comprobacion crearia una conversacion
  falsa con el numero de Ventas en la bandeja del panel.

### 11.6 UN 200 DE META ES "LO ACEPTO", NO "LO ENTREGUE"

La trampa mas cara de todo este bloque, y la que explicaba el sintoma
entero: *"dice que le llego pero no les llega"*.

`send_text_message` devuelve 200 cuando Meta **acepta** el mensaje. Si
luego no puede entregarlo —el destinatario no le ha escrito al bot en
24 h, el numero no tiene WhatsApp, lo que sea— eso **NO vuelve como error
de la llamada**. Vuelve despues, en un webhook de estado (`statuses`).

Y ese webhook se estaba tirando entero:

    # Ignoramos eventos de "estado de entrega" (delivered/read)
    if "messages" not in value: return ignored

O sea que la unica señal de que un lead no le llego a nadie se perdia. Y
tiene una consecuencia peor de lo que parece:

    `_avisar_a` reintenta por PLANTILLA cuando el envio falla. Como el
    envio devuelve 200, ese reintento NUNCA se disparaba. La red de
    seguridad de la ventana de 24 h estaba, y no se activaba jamas.

**Ahora los `statuses` fallidos se anotan** (`main._anotar_entregas_fallidas`
-> `notificaciones.anotar_no_entregado`) y el ultimo sale en la ficha del
cliente, en rojo. Solo los fallidos: los `delivered` y `read` llegan varios
por mensaje y no dicen nada que guardar.

Se guarda en un `Ajuste` del cliente y no en una tabla nueva: una tabla con
`client_id` cuesta su politica de RLS, y el dia que se olvide queda sin
cerradura sin que nadie se entere.

> **Y el boton de prueba mentia.** Leia el 200 y decia "le llego". Ahora
> dice "aceptado" y, antes de mandar nada, mira en NUESTRA base si esa
> persona le escribio al bot en 24 h (`notificaciones.ventana_abierta`) —
> que es la causa n.º 1 de que un aviso aceptado no se entregue, y la
> unica que se puede saber por adelantado. Un diagnostico que dice OK
> cuando la cosa esta rota es peor que no tener diagnostico.

**La consecuencia practica para vender:** un numero de area recien
configurado NUNCA le ha escrito al bot, asi que su ventana esta cerrada
desde el primer minuto. O esa persona le escribe una vez al bot, o el
negocio necesita su plantilla de avisos aprobada en Meta. Conviene decirlo
en el alta.

### 11.7 La ventana se pregunta ANTES de enviar

El arreglo de fondo del sintoma "a mi me llega y a los demas no".

`_avisar_a` intentaba el texto libre y solo reintentaba con plantilla
**si el envio devolvia error**. Como Meta devuelve 200 aunque no vaya a
entregarlo (§11.6), esa condicion no se cumplia nunca:

    LA RED DE SEGURIDAD LLEVABA AHI DESDE EL PRINCIPIO Y NO SE ACTIVO
    JAMAS.

Ahora se pregunta antes: si esa persona no le ha escrito al bot en 24 h
(`notificaciones.ventana_abierta`, que mira NUESTRA base), el aviso sale
directo por plantilla. La decision es nuestra y no depende de que Meta nos
diga que fallo — que ademas nos lo dice tarde y por otro canal.

Con la ventana abierta se sigue mandando el texto bonito: es mas legible
que la plantilla y no gasta una.

**Un aviso sin variables no intenta la plantilla.** La plantilla espera un
numero fijo de huecos y Meta rechaza el envio si no cuadran. Le pasa al
aviso de "tu bot no tiene menu", que no es un lead y va sin datos: ese
sigue por texto libre, y si no llega es asumible porque no es una venta.

> **Al escribir la prueba se colo un numero que otra prueba ya usaba**
> como cliente — y ese cliente si le habia escrito al bot, asi que su
> ventana estaba abierta y la comprobacion fallaba diciendo la verdad. El
> numero de una prueba de ventanas tiene que ser exclusivo de ella.

### 11.8 Los avisos a las areas van por CORREO

La conclusion de todo el bloque anterior. **WhatsApp no sirve para avisar
a un equipo**, y costo tres rondas descubrirlo porque cada puerta se
descubria al cerrar la anterior:

    1. La ventana de 24 h. El de Ventas nunca le escribe al bot, asi que
       su ventana esta cerrada desde el primer minuto.
    2. Fuera de la ventana hace falta una plantilla aprobada por Meta.
    3. Y una plantilla es un mensaje COBRADO: Meta la rechaza si la cuenta
       del negocio no tiene moneda y metodo de pago configurados.

Tres puertas, cada una capaz de bloquear el aviso por su cuenta, y las
tres fallando en silencio. La tercera solo se vio cuando el bot empezo a
escuchar los webhooks de estado (§11.6) — antes de eso era invisible.

**El correo no tiene ninguna de las tres.** `app/core/correo.py`, con
`smtplib` de la libreria estandar, sin dependencias nuevas.

    SMTP_HOST, SMTP_PUERTO, SMTP_USUARIO, SMTP_CLAVE, SMTP_DESDE
    PANEL_URL   (para el enlace a la conversacion dentro del correo)

Sin `SMTP_HOST` y `SMTP_DESDE` esto no hace nada y el bot funciona igual,
como con las claves de push.

**La cuenta remitente es de la PLATAFORMA, no de cada cliente.** Pedirle a
cada negocio las credenciales de su correo seria otra credencial que
custodiar y otro paso donde atascarse en el alta, para algo que el
destinatario no ve: el aviso dice de que negocio es en el asunto.

**El correo lleva DOS enlaces y los dos importan**: `wa.me` para
escribirle al cliente desde el telefono, y el del panel para responder
desde ahi. Quien recibe el aviso en Ventas puede no tener usuario del
panel, y aun asi tiene que poder contactar al cliente — que es para lo que
existe el aviso.

**Un area vale con solo correo.** Antes hacia falta el numero si o si, y
eso dejaba fuera al caso que ahora es el normal. El WhatsApp del area
sigue siendo opcional y se usa ADEMAS del correo, no en su lugar: el dia
que un negocio tenga su facturacion y su plantilla en orden, los dos
avisos salen sin tocar nada.

> **El envio va en un hilo** (`tenencia.envolver_para_hilo`, §3.1) porque
> el webhook tiene 8 segundos antes de que Meta lo reintente. El boton de
> prueba usa `enviar_ahora`, que espera el resultado: ahi el objetivo es
> justamente saber si salio.

### 11.9 La guia de conexion se sirve desde el propio bot

`/conectar` (`app/web/guia.py`). Es de la PLATAFORMA, no de un negocio —
esa es la diferencia con `paginas_publicas.py`, que sirve las politicas
con el nombre y el correo de CADA cliente porque son suyas. Meterla en el
marco por inquilino la haria firmar con el nombre del negocio equivocado.

Reusa las fuentes que ya sirve el panel (`/estaticos/fuentes.css`) en vez
de pedirlas a Google: es la unica pagina que alguien va a abrir con una
conexion mala, en mitad de un tramite.

> Al comprobarla en el navegador salio un desborde de 5px que sacaba
> scroll horizontal a toda la pagina: la barra de avance va FUERA del
> contenedor y llevaba los margenes negativos que solo tienen sentido
> estando dentro. Ninguna suite lo habria visto. Es el §4.4 otra vez.
### 11.10 El CSS y el JS del super-admin salieron de Python

Era el punto 3 de §2 y estaba desde hacia semanas. **1.222 lineas** de CSS
y JavaScript que vivian dentro de cadenas de Python:

    superadmin.css            175 lineas   (el suyo + el del mapa)
    superadmin-mapa.js        957 lineas   <- el editor del arbol
    superadmin-contenido.js    57 lineas
    superadmin-logo.js         50 lineas

`mapa.py` paso de 1.359 lineas a ~330. Lo que habia dentro no era un
adorno: era una aplicacion JavaScript entera sin resaltado, sin
autocompletado, y donde un error de sintaxis no daba un error de
JavaScript sino **un error de Python al arrancar el servidor**.

**Salio facil por una razon que conviene saber**: los cinco bloques eran
cadenas normales (`"""` y `r"""`), no f-strings. Sin llaves dobladas que
deshacer y sin interpolacion de Python dentro. Si algun dia hay que sacar
un bloque que SI sea f-string, hay que deshacer todos los `{{` y `}}` y
pasar los valores por un objeto global, como hace el panel del cliente con
`PANEL`.

**Lo que se queda en Python**: el `<template>` vacio que clona el editor
de contenido. Es marcado, no comportamiento, y sacarlo obligaria a crearlo
desde JavaScript solo para poder clonarlo.

#### Y un agujero que aparecio al hacerlo

Al mover el CSS a `/estaticos`, `/superadmin` paso a depender de una ruta
que **el middleware de inquilino filtra**. `/superadmin` esta exento del
middleware, pero su CSS ya no.

Con `DOMINIO_BASE` sin poner no se nota. El dia que se active (§7.6), la
resolucion pasa a ser estricta y `/estaticos` en el host pelado daria 404:
**la consola se serviria sin estilos**, meses despues, al tocar una
variable que no tiene ninguna relacion aparente.

`/estaticos` esta ahora exento del middleware, por el mismo motivo por el
que ya vivia fuera de `/admin`: son archivos sin nada de nadie y pedirlos
no deberia depender de resolver un inquilino.

> Lo cazo una prueba de `test_multitenant` que fallaba al pedir el CSS
> —esa suite corre CON `DOMINIO_BASE` puesto—. Sin ella habria llegado a
> produccion dormido.

---

### 11.11 El rediseño de `/superadmin`

Era el punto 5 de §2. La especificación está en `diseñosuperadmin.md`; lo
que sigue es lo que hay que saber para no deshacerlo sin querer.

**La identidad es la de Nitro** —morado `#6D28D9`, neutros con sesgo
violeta, Manrope + IBM Plex Mono— la misma del panel del cliente. Lo que
distingue a la consola no es otra paleta: es la **estructura**. Barra
lateral oscura de operación, densidad de tabla, y mono en cada
identificador. Los semáforos NO siguen a la marca en ningún tema.

**Once bloques apilados pasaron a siete pestañas**: Resumen · Avisos y
áreas · WhatsApp e IA · Usuarios · Integraciones y marca · Contenido del
bot · Mapa. Son **enlaces de verdad** (`?bloque=avisos`), no JavaScript:
se recargan, se comparten por chat y el botón de atrás funciona. Una
consola que se opera un domingo no puede depender de que un guion cargue.

**"Requiere atención"** en la barra lateral es lo nuevo de verdad. Un
cliente con las credenciales rotas o sin cupo está tan mudo como uno
pausado y no lo dice nadie; ahora sale en TODAS las pantallas, con enlace
a su ficha. Si no hay ninguno, el bloque no se pinta: un hueco fijo que
dice "todo bien" se deja de mirar a la semana.

#### La trampa que trajo partir el formulario

Un formulario por tarjeta significa que **un guardado trae solo los
campos de su tarjeta**. Por eso `guardar()` pregunta `columna in
formulario` y nunca `formulario.get(columna)`.

Con `.get()`, un campo ausente vale `""` y se guardaría como vacío:
darle a "Guardar identidad" borraría de golpe el `phone_number_id`, el
número del dueño y las claves de Google. Sin error, y el cliente dejaría
de recibir mensajes. Lo mismo con las áreas de aviso, que solo se tocan
si el formulario trae `destino-0-correo`.

    Vacío = borrar, SOLO si el campo vino en el formulario.
    Campo ausente = no se toca.

#### Tres cosas que solo se vieron abriéndolo en el navegador

Las cuatro suites estaban en verde con las tres puestas. Es §4.4 otra vez.

1. **Los botones secundarios eran invisibles a oscuras.** El color del
   texto sobre el morado estaba como regla (`:root[data-tema] button`) y
   le ganaba por especificidad a `.suave`, que es transparente: texto
   casi negro sobre fondo oscuro. Ahora es una **ficha**
   (`--sobre-morado`), y una ficha no compite con nadie.

2. **Las casillas salían cuadrados negros.** La regla de `input` —pensada
   para cuadros de texto— le ponía fondo, borde y once píxeles de
   relleno, y Chrome dejaba de dibujarles la marca. `input[type=checkbox]`
   les devuelve su forma nativa.

3. **`color-scheme` seguía al sistema operativo, no al tema elegido.**
   Estaba en un `<meta content="light dark">`, así que con el sistema a
   oscuras y el tema en claro el navegador pintaba sus controles
   —casillas, flechas de los `<select>`, barras de scroll— en oscuro
   sobre tarjeta blanca. Ahora va **con las fichas**, junto a los
   colores, y no puede desincronizarse de ellos.

#### El interruptor de tema tiene TRES estados

`Sistema · Claro · Oscuro`, no dos. Con dos, quien prueba el manual una
vez ya no puede volver a seguir a su sistema: no hay forma de borrar la
elección. Se guarda en `localStorage` bajo `superadmin:tema` y lo aplica
un guion en línea de dos líneas en el `<head>`, antes del CSS — con
`defer` la página aparecería un instante en claro antes de volverse
oscura.

El CSS tiene que anular la regla del sistema con
`:root:not([data-tema="claro"])`, o el interruptor no podría devolver a
claro a quien tiene el sistema en oscuro.

#### Detalles que no se pueden tocar

- **No existe borrar cliente.** Solo pausar, y se dice al pie de la tabla.
- **Webhook y verify token: cajas de solo lectura**, no `<input>`. Un
  cuadro de texto invita a "corregirlo", y cambiárselos a un cliente que
  ya los tiene pegados en Meta lo deja mudo sin dar ningún error.
- **Los secretos salen vacíos**, con "vacío = no se toca" escrito al
  lado. Lo guardado no se pinta nunca.
- **`.marca` es del editor del mapa** (una fila de casilla). El logo de
  Nitro es `.n-marca`: pisar la otra convertiría cada casilla del mapa en
  un logotipo.
- **La vista previa de WhatsApp no se invierte** en el tema oscuro. Es
  una simulación de otra aplicación, y si cambiara de color dejaría de
  parecerse a lo que el cliente va a ver en su teléfono — que es lo único
  para lo que sirve.
- **Los 34 textos del editor de contenido no se pintan enteros**: tres
  abiertos y el resto en un `<details>`. Sus campos siguen dentro del
  formulario aunque esté cerrado, así que se envían igual; con pestañas
  de JavaScript habría que acordarse de eso, y el día que se olvidara se
  guardarían vacíos los treinta y uno que nadie abrió.

#### Lo que quedó fuera del brief, y por qué

El brief pedía que **el menú del editor de contenido** fuera una fila de
`número · texto · enlace · quitar`. Se dejó como tarjeta. `_leer_opcion`
lee diez campos por opción (`accion`, `mensaje`, `servicio`, `paso`,
`pregunta`, `sheet`, `luego`, `precios`…) y lo que no viaja en el
formulario se pierde: reducir el HTML sin reducir el lector borraría seis
campos de cada opción al siguiente guardado, en silencio. Los **enlaces**
sí son filas, que es donde el formato encaja de verdad.

El brief también pedía el **número del paso en un cuadro morado** dentro
del mapa. El título del paso lo arma `superadmin-mapa.js` como una sola
cadena (`"Botón 1 · Texto"`) y lo reescribe con `textContent` cada vez
que se edita el título, lo que borraría cualquier marcado interno. El
paso abierto se distingue por borde, fondo morado tenue y sombra.
