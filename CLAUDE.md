## Bot de WhatsApp multi-inquilino, en producción

Un solo despliegue atiende a todos los negocios. Vivo desde el
15-ago-2026 sobre PostgreSQL, con Row-Level Security desde el
19-ago-2026, y con el panel de atención rediseñado entero.

**Antes de tocar código, lee `docs/CONTINUAR_AQUI.md`.** Es el único
archivo que hace falta: estado, las trampas que ya costaron tiempo, cómo
verificar y qué falta. Antes ese papel se repartía entre seis archivos y
ninguno estaba al día.

**Nada visual se da por bueno sin abrirlo en el navegador**, en los dos
temas y en ancho de teléfono: las cuatro suites ya estuvieron en verde
cuatro veces con el panel roto en pantalla. Ven las respuestas HTTP, no
ven una pantalla.

Las reglas que se rompen fácil y no dan error visible:

- **No leas `config.X` de un cliente en el cuerpo de un módulo ni de una
  clase.** Se evalúa al importar y queda congelado con los valores del
  primer negocio. Solo los ajustes del sistema son constantes.
- **Todo hilo nuevo necesita `tenencia.envolver_para_hilo()`.** Los
  `ContextVar` no cruzan `ThreadPoolExecutor` ni `threading.Thread`.
- **No agregues `--workers` a uvicorn.** El bus de avisos en vivo
  (`app/core/eventos.py`) es una cola en memoria de un solo proceso.
- **El cuerpo de una `StreamingResponse` corre fuera de la petición.**
  Guarda el `client_id` en una variable antes de devolverla y envuelve con
  `tenencia.usar()` lo que consulte la base ahí dentro.
- **`/superadmin` corre SIN inquilino, y así tiene que quedarse.** Mira a
  todos los clientes; con uno fijado, el filtro automático le recortaría
  cada listado a un solo negocio sin dar ningún error.
- **Si consultas filas de un cliente que NO es el inquilino en curso,
  envuelve en `tenencia.usar(ese_id)`.** El `filter_by(client_id=X)` no
  basta: el filtro automático añade el inquilino actual y las dos
  condiciones se contradicen — cero filas y ningún error. Pasa al entrar al
  panel sin subdominios (ver `acceso.autenticar`).

- **Cada cliente trae su propia App de Meta, y por eso tiene su propia
  URL de webhook** (`/webhook/{webhook_token}`). La firma se valida con
  SU `app_secret`, así que el inquilino tiene que salir de la URL —
  nunca del cuerpo, que es lo que todavía no está autenticado.
  `/webhook` a secas es el camino viejo y se retira cuando el último
  cliente esté migrado.

- **`APP_SECRET`, `VERIFY_TOKEN` y `APP_ID` ya NO son constantes del
  sistema.** Están en la cascada por inquilino. Volver a subirlos al
  cuerpo de `config.py` haría que el secreto del dueño validara la firma
  de otro cliente.

- **Una credencial no puede acabar en una URL.** Meta devuelve el token
  DENTRO de sus mensajes de error (`Malformed access token EAAG…`), y ese
  texto se pinta en el super-admin y viaja en la redirección — o sea al
  historial del navegador y a los logs. Se tapa en
  `meta_estado._tapar()`, que es el único sitio que conoce los secretos.

- **El paquete de IA se contrata (`clients.ia_contratada`), y la puerta
  está en `cerebro.plan_activo()`, no solo en el panel.** La clave de
  Gemini la ponemos nosotros y es la misma para todos, así que "¿hay
  clave?" nunca fue la pregunta: sin esta columna, cualquier cliente
  encendía la IA desde su panel y nos cargaba el consumo. Esconder el
  botón sin cerrar el camino que decide es un adorno, no una puerta.

- **Los avisos ya no van a un solo número.** Un negocio reparte entre
  varias áreas (`[avisos].destinos` en `negocio_config`), enrutadas por
  `Contact.servicio`. **Cuántas, lo decide el plan** — 3 sin IA, 6 con IA,
  o lo que diga `clients.max_destinos_avisos`. Sale de `ia_contratada` y
  NO de `plan_activo()`: con el operativo, apagar la IA un rato le
  recortaría las áreas y no volverían.

- **Un 200 de Meta es "lo acepto", NO "lo entregué".** Si luego no puede
  entregarlo, lo dice en un webhook de `statuses`, no como error del
  envío. Por eso el reintento por plantilla de `_avisar_a` no se
  disparaba nunca, y por eso los `statuses` fallidos ahora se anotan
  (`main._anotar_entregas_fallidas`). Nada que lea el código de respuesta
  puede afirmar que un mensaje llegó. Por eso la ventana de 24 h se
  pregunta ANTES de enviar (`notificaciones.ventana_abierta`) y con ella
  cerrada el aviso sale directo por plantilla.

- **Los avisos a las áreas van por CORREO** (`app/core/correo.py`).
  WhatsApp tiene tres puertas capaces de bloquearlos —la ventana de 24 h,
  la plantilla aprobada y la facturación de la cuenta de Meta— y las tres
  fallan en silencio. Un área vale con solo correo; su WhatsApp es
  opcional y se usa además, no en su lugar.

- **Un aviso NUNCA se queda sin destinatario.** Es la regla que gobierna
  el reparto: si nadie reclama esa opción va al área general, y si no hay
  general, a todas. Un aviso que no se entrega es una venta que nadie
  atiende, y no da ningún error — se ve igual que un día sin clientes.
  Ver `notificaciones.a_quien()`.

- **Pasarse de un tope de Meta no recorta: DESCARTA el mensaje entero**,
  y sin excepción — el cliente no recibe nada y solo queda una línea en
  el log. Texto 4096; cuerpo con botones o lista 1024; título de botón
  **20**; de fila de lista 24; de 1 a 3 botones. Los aplica
  `whatsapp_client`, que es el único sitio que habla con Meta: no los
  repitas ni los des por hechos en quien llama. Se parte, no se recorta.
  Ver §3.16.

- **Un texto que escribe el dueño NO pasa nunca por `str.format`.** Usa
  `huecos.rellenar(texto, name=…)`. `format` trata toda llave como un
  hueco suyo, así que un `{name}` —que el editor invita a usar— o un
  `{9 a 6}` levantaban `KeyError`, y ese error lo recogía en `main` el
  `except (KeyError, IndexError)` de los payloads de Meta: el cliente se
  quedaba SIN respuesta y el log culpaba a Meta. Ver §3.15.

- **El cuerpo de un mensaje va en `<textarea>`, nunca en `<input>`.** Un
  `<input>` no puede contener un salto de línea y se los quita al pintar
  el campo, sin avisar: un texto guardado con saltos los perdía solo con
  abrir la pantalla, y el siguiente guardado escribía la versión
  aplastada. Quién va en renglón lo dice `mapa.TEXTOS_DE_UNA_LINEA`, y
  son solo los rótulos que WhatsApp manda en una línea (etiqueta de
  botón, título de lista). Del mismo asunto: un formulario manda los
  saltos en `\r\n` —se normalizan al leer—, el HTML se come el salto
  pegado a `<textarea>` —por eso `contenido._campo` escribe uno de más—,
  y al cuerpo de un mensaje NO se le hace `.strip()`. Ver §4.10.

- **Una tabla nueva con `client_id` necesita DOS cosas**: entrar en
  `database.MODELOS_DEL_INQUILINO` (el filtro del ORM) y su política en una
  migración (la cerradura de PostgreSQL, ver `c3f1a7d2b904`). Si falta la
  segunda, todo funciona y nadie se entera de que esa tabla quedó sin
  cerradura: `tests/test_rls.py` es lo que lo cazaría, y solo corre contra
  una base PostgreSQL.

Verificación (no usan pytest, devuelven 0 o 1):

    python tests/test_multitenant.py    # aislamiento entre clientes
    python tests/test_regresion.py
    python tests/test_ia.py
    python tests/test_panel.py
    python tests/test_rls.py            # las cerraduras de la base; pide PostgreSQL

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
