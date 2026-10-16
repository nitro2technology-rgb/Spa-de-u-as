# Especificación técnica — cómo está construido hoy

> **Para qué sirve este documento.** Este repositorio nació como el software de
> **barberías** (panel de gestión + bot de WhatsApp) y es la **base** del software
> para **spa de uñas**. Aquí está descrito, tal cual está hoy en el código, cómo
> funciona por dentro, para decidir qué se queda, qué se cambia y qué se agrega
> *antes* de escribir una sola línea del proyecto nuevo.
>
> Es una **fotografía del código al 16-oct-2026**, no una propuesta. Lo que es
> propuesta está marcado y vive solo en la §12. El complemento desde el lado de
> quien lo usa está en `Especificacion de uso.md`.
>
> **Si algo de aquí no coincide con el código, gana el código.** Cada afirmación
> lleva la ruta del archivo donde se comprueba.

---

## 0. Qué se leyó y qué no se pudo comprobar

**Leído completo:** todo `app/barberia/` (≈8.000 líneas), `app/core/planes.py`,
`app/core/database.py` (modelos y columnas de módulos), `app/main.py`,
`app/bot/bot_logic.py` (entrada y puntos de enganche), `CLAUDE.md`,
`docs/CONTINUAR_AQUI.md` (2.133 líneas), `README.md` (estructura), migraciones de
la barbería, `render.yaml`, `Dockerfile` y `requirements.txt`.

**Ejecutado hoy (16-oct-2026), con SQLite y dependencias recién instaladas:**

| Suite | Verificaciones | Resultado |
|---|---|---|
| `tests/test_barberia.py` | 238 | ✅ todo en orden |
| `tests/test_multitenant.py` | 235 | ✅ |
| `tests/test_regresion.py` | 518 | ✅ |
| `tests/test_panel.py` | 366 | ✅ (necesita `av` instalado para la prueba de audio) |
| `tests/test_ia.py` | 87 | ✅ |
| `tests/test_rls.py` | — | ⏭️ **No corrió**: exige PostgreSQL (`RLS_DATABASE_URL`) |

Es decir: **la base está sana tal como se recibe**. Dos avisos para quien las corra:
**se corren de una en una** (levantan servidores en puertos fijos y se pisan si se
lanzan en paralelo; así falló una primera tanda mía y no era un fallo del código) y
las políticas de RLS **no están verificadas hoy**, solo leídas.

**Documentos que el código cita y que NO están en el repositorio:**

| Cita en el código | Dónde se cita | Consecuencia |
|---|---|---|
| `Instrucciones SAAS barberia.md` (las reglas de negocio, §1–§11) | `app/barberia/__init__.py`, `planes.py`, `modelos.py` | Las "§7 de la especificación", "§11.5 decisión provisional", etc. no se pueden leer. Lo que se sabe de ellas está en los comentarios del código |
| `design_handoff_barbersaas/README.md` (cómo se ve y se comporta; pantallas 3a, 2a, 6.2.x…) | `paginas.py`, `pantallas.py`, `barberia.css` | El diseño de alta fidelidad no está; solo su implementación en CSS/HTML |

Conviene pedir esos dos archivos: son la "especificación de la barbería" original
y la que habría que **modificar** para el spa.

**Estado del repositorio:** un solo commit (`Primer commit - Base software Spa de
uñas`). El nombre del repo ya dice "Spa de uñas", pero **el contenido sigue siendo
100 % barbería**: tablas `barb_*`, roles `BARBERO`, textos, catálogo de "Corte
clásico", marca "BarberSaaS". Nada se ha adaptado todavía.

---

## 1. Visión general

Un **único despliegue** (un proceso FastAPI) atiende a **muchos negocios** (multi-
inquilino). Sobre esa plataforma conviven **dos productos**, que un negocio contrata
por separado (`clients.bot_contratado`, `clients.barberia_contratada`):

```
                      ┌────────────────────────────────────────────────┐
                      │ PLATAFORMA (Nitro2Tech) — un solo despliegue   │
                      │  tenencia · RLS · acceso · cobros · correo ·   │
                      │  super-admin · planes                          │
                      └──────────────┬─────────────────────────────────┘
          ┌──────────────────────────┴───────────────────────────┐
          │ PRODUCTO 1: BOT DE WHATSAPP                          │ PRODUCTO 2: PANEL DE GESTIÓN
          │ app/bot, app/web (/admin), app/integrations          │ app/barberia (/entrar, /b, /yo)
          │ menú editable, IA (Gemini), panel de conversaciones, │ caja, agenda, cobros, nómina,
          │ avisos por área, Google Calendar/Sheets              │ gastos, sedes, usuarios, actividad
          └───────────────────────┬──────────────────────────────┘
                                  │ se tocan en UN punto:
                                  ▼
              `clients.proveedor_agenda = "barberia"`  →  el bot agenda en la
              agenda del panel (app/barberia/bot.py) en vez de Google Calendar
```

- **Quién entra:** el dueño y su equipo (por navegador, instalable como PWA en el
  celular) y el **cliente final** (solo por WhatsApp). El cliente final **no** tiene
  usuario ni pantalla web.
- **Quién administra la plataforma:** Nitro2Tech, desde `/superadmin` (el bot) y
  `/superadmin/barberias` (la consola de barberías).
- **Cómo se cobra a los negocios:** mensualidad por plan, con fecha "pagado hasta",
  7 días de aviso, 2 de gracia y pausa automática (`app/core/cobros.py`).
  El cobro a los *clientes finales* del negocio (servicios) es el módulo de caja.

> **Nombre comercial.** La interfaz se llama **BarberSaaS**
> (`paginas.PRODUCTO`) y la web de marketing (repo `Nitro2Tech`) lo vende como
> **Degradé**. Son el mismo producto.

---

## 2. Stack y despliegue

| Capa | Tecnología | Dónde |
|---|---|---|
| Lenguaje | Python 3.12 (imagen `python:3.12-slim`) | `Dockerfile` |
| Servidor | FastAPI 0.115 + Uvicorn 0.30, **un solo proceso** | `requirements.txt` |
| ORM / migraciones | SQLAlchemy 2.0.35, Alembic 1.19 | `app/core/database.py`, `migrations/` |
| Base de datos | **PostgreSQL** en producción (psycopg 3); **SQLite** en pruebas y local | `DATABASE_URL` |
| Interfaz | **HTML generado en Python** (f-strings), sin plantillas ni build; CSS y JS planos servidos desde `/estaticos` con versión por contenido | `app/web/activos.py`, `app/web/estaticos/` |
| WhatsApp | Cloud API de Meta, por `requests` | `app/bot/whatsapp_client.py` |
| IA | Google Gemini (`google-genai`), solo plan con IA | `app/bot/cerebro/gemini.py` |
| Google | Calendar y Sheets (cuenta de servicio) — **no los usa la agenda de barbería** | `app/integrations/` |
| Correo | `smtplib` (variables `SMTP_*`) | `app/core/correo.py` |
| Notificaciones push | VAPID (`pywebpush`) | `app/core/push.py` |
| Hosting | Render (`render.yaml`), disco persistente, base administrada; también `Dockerfile` | raíz |

**Arranque:** `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
Si una migración falla, el servidor no arranca (deliberado).

**Restricción dura — un solo proceso.** No se agrega `--workers` ni se escala a
más de una instancia. Tres cosas dependen de ello:
1. El bus de avisos en vivo (`app/core/eventos.py`) es una cola en memoria.
2. El freno de intentos de clave (`app/core/freno.py`, `cuentas.FrenoPorUsuario`).
3. El **candado de reservas** de la agenda (`agenda._CANDADO`, un `threading.Lock`).

**Tareas de fondo** (dentro del mismo proceso, arrancadas en `lifespan` de `main.py`):
`cobros.vigilar` (cada hora) y `recordatorios.vigilar` (cada 10 min).

**Variables de entorno que importan para la barbería:** `DATABASE_URL`,
`SECRETS_KEY` (cifra credenciales), `SESSION_SECRET` (firma sesiones; si falta se
deriva de `SECRETS_KEY`), `SUPERADMIN_KEY`, `PANEL_URL` (base de los enlaces de los
correos; por defecto `https://bot.nitro2tech.com`), `SMTP_HOST/PUERTO/USUARIO/CLAVE/
DESDE/NOMBRE`, `DOMINIO_BASE` (opcional: subdominio por negocio),
`PANEL_SESION_INACTIVIDAD_HORAS` (5) y `PANEL_SESION_MAXIMA_HORAS` (12).

---

## 3. Mapa del código

```
app/
├── main.py                 FastAPI: middleware de inquilino, webhooks, routers, lifespan
├── config.py               Configuración por inquilino (cascada), se valida al importar
├── core/                   ── PLATAFORMA (compartida por los dos productos) ──
│   ├── tenencia.py         Quién es el inquilino de esta petición (ContextVar)
│   ├── database.py         Modelos base, sesiones, filtro automático por client_id
│   ├── acceso.py           Hash de clave (PBKDF2), pase firmado, usuarios del panel
│   ├── planes.py           Los planes que se venden y sus cupos
│   ├── cobros.py           Mensualidad, avisos, gracia, pausa por impago
│   ├── correo.py           Envío SMTP
│   ├── equipo.py           Roles del panel del bot y áreas
│   ├── freno.py            Freno de intentos por IP
│   ├── secretos.py         Cifrado de credenciales por cliente
│   └── (eventos, push, media, message_log, huecos, estadisticas, consumo…)
├── bot/                    ── PRODUCTO 1: BOT ──
│   ├── bot_logic.py        Máquina de estados de la conversación
│   ├── whatsapp_client.py  Único sitio que habla con Meta (aplica topes de texto)
│   ├── notificaciones.py   Avisos al dueño / áreas
│   └── cerebro/            Menú (sin IA) o Gemini (con IA)
├── integrations/           Google Calendar/Sheets, estado de credenciales de Meta
├── web/                    ── PANEL DEL BOT + SUPER-ADMIN + estáticos ──
│   ├── admin_ui.py         /admin: bandeja, chat, contactos, configuración
│   ├── superadmin.py       /superadmin: consola de la plataforma (3.960 líneas)
│   ├── mapa.py, contenido.py   editores de lo que dice el bot
│   ├── paginas_publicas.py /privacidad /terminos /eliminar-datos
│   ├── guia.py             /conectar (guía para conectar WhatsApp)
│   ├── pwa.py              manifiesto, service worker, iconos
│   └── estaticos/          barberia.css (1.556 l.) · barberia.js (231 l.) · panel*.js/css · fuentes
└── barberia/               ── PRODUCTO 2: PANEL DE GESTIÓN ──
    ├── modelos.py          19 tablas `barb_*`
    ├── permisos.py         Roles, secciones, `Persona`, puertas por sede
    ├── cuentas.py          Entrar, freno, sesión, claves, recuperación, alta de personal y sedes
    ├── operacion.py        Catálogo, clientes, caja, cobrar, anular, gastos
    ├── agenda.py           Horarios, huecos, reservar (con candado), estados de cita
    ├── nomina.py           Liquidación quincenal, adelantos, "Hoy llevas", "Mis ganancias"
    ├── reportes.py         Resumen (KPIs), actividad, cifras por sede
    ├── sedes.py, usuarios.py   Pantallas Sedes y Usuarios (lógica)
    ├── bot.py              El bot agenda aquí (sede→servicio→barbero→día→hora)
    ├── recordatorios.py    Recordatorio de 2 h antes por WhatsApp
    ├── consola.py          /superadmin/barberias
    ├── rutas.py            Rutas HTTP: /entrar, /b/…, /yo/…
    ├── paginas.py          Armazón HTML (login, panel, barbero, cuenta pausada)
    ├── pantallas.py, pantallas_agenda.py   HTML de cada pantalla
    └── formato.py          Pesos, fechas, quincenas, zona horaria
migrations/versions/        20260924_e1b5c3a7d902 (fase 0), f2c6d4b8e013 (fase 1), a4d7e9b2c015 (fase 2)
scripts/                    demo_barberia.py, servir_barberia.py (datos de mentira + servidor local), meta_setup, etc.
tests/                      test_barberia.py (1.212 l.), test_multitenant, test_regresion, test_panel, test_ia, test_rls
negocio.toml               Plantilla de contenido del bot (el menú de ejemplo es de Nitro, no de barbería)
```

**Regla de dependencias.** `app/barberia/__init__.py` **no importa nada** a
propósito: `database.py` carga `modelos` al final de su propio módulo y cualquier
import de más cerraría un círculo. `bot_logic.py` importa `barberia.bot`;
`barberia.bot` importa `bot_logic` **dentro de las funciones**, por la misma razón.

---

## 4. Multi-inquilino (lo que sostiene todo)

Cada negocio es una fila de `clients`. Todo dato de negocio lleva `client_id`.

### 4.1 Cómo se sabe de quién es una petición
- **Panel (`/entrar`, `/b`, `/yo`, `/admin`):** del **pase de sesión** firmado en una
  cookie (`app/core/acceso.py`). El middleware de `main.py` (`fijar_inquilino`) lo
  lee y fija el `ContextVar` (`tenencia.usar`). Sin pase, se atiende con el cliente
  por defecto (id 1), que solo sirve la pantalla de entrada.
- **Con `DOMINIO_BASE`** puesta, sale del subdominio (`resolver_por_host`).
  Hoy **no está activada**.
- **Webhook de WhatsApp:** de la URL `/webhook/{webhook_token}`, nunca del cuerpo.
- **Exentos del middleware:** `/webhook*`, `/superadmin*`, `/estaticos*` y `/`.

### 4.2 Las dos cerraduras
1. **Filtro del ORM:** toda consulta sobre un modelo de `database.MODELOS_DEL_INQUILINO`
   añade `client_id = <inquilino actual>`.
2. **Row-Level Security de PostgreSQL:** una política por tabla (migraciones).

> **Una tabla nueva con `client_id` necesita las DOS:** entrar en
> `MODELOS_DEL_INQUILINO` y llevar su política en una migración. Si falta la
> segunda, todo funciona y nadie se entera. `barberia/modelos.py::_registrar()` suma
> las 19 tablas `barb_*` a la tupla; las tres migraciones crean las políticas.
> `tests/test_rls.py` es lo único que lo caza y solo corre contra PostgreSQL.

### 4.3 Reglas que no dan error visible al romperse (de `CLAUDE.md`)
| Regla | Por qué |
|---|---|
| No leer `config.X` de un cliente en el cuerpo de un módulo/clase | Se evalúa al importar y queda con los valores del primer negocio |
| Hilo nuevo ⇒ `tenencia.envolver_para_hilo()` | Los `ContextVar` no cruzan `ThreadPoolExecutor` ni `threading.Thread` |
| Sin `--workers` | Bus y frenos en memoria |
| `StreamingResponse`: guardar `client_id` antes y envolver con `tenencia.usar()` | El cuerpo corre fuera de la petición |
| `/superadmin` corre **sin** inquilino | Mira a todos; con uno fijado el filtro recortaría cada listado |
| Consultar filas de **otro** cliente ⇒ `tenencia.usar(ese_id)` | `filter_by(client_id=X)` + filtro automático se contradicen: cero filas, sin error |
| Textos del dueño nunca por `str.format` | Una llave rara dejaba mudo al bot (`huecos.rellenar`) |
| Topes de Meta (texto 4096; cuerpo con botones/lista 1024; título de botón **20**; fila de lista 24; 1–3 botones) | Pasarse **descarta el mensaje entero**, sin error |
| Un 200 de Meta es "lo acepto", no "lo entregué" | La entrega fallida llega por webhook `statuses` |

**La barbería respeta esto así:** `cuentas._candidatos` y `enlace_valido` buscan
usuarios con `tenencia.sin_inquilino()` (el login corre antes de saber de quién es);
`consola.py` toca filas de una barbería con `tenencia.usar(id)`; `recordatorios`
itera negocios con `sin_inquilino()` y trabaja cada uno con `usar()`.

---

## 5. El módulo de barbería: activación, planes y datos

### 5.1 Qué lo enciende (columnas de `clients`)

| Columna | Significado | Quién la toca |
|---|---|---|
| `barberia_contratada` (bool, def. false) | Puerta del módulo: sin ella nadie de ese negocio entra a `/b` ni `/yo` | Solo `/superadmin` |
| `bot_contratado` (bool, def. true) | Si compró el bot (los clientes de antes lo tienen) | Solo `/superadmin` |
| `proveedor_agenda` (`"google"` \| `"barberia"`) | Dónde agenda el bot | Alta de barbería |
| `max_sedes`, `max_barberos` (int, null) | Cupos pactados; null = los del plan | Consola |
| `plan`, `precio_mensual`, `vence_el`, `ultimo_pago_*`, `pausado_por`… | Cobro de la mensualidad | Consola / `cobros` |

La puerta está **en el servidor**: `cuentas.persona_de` devuelve `None` si el negocio
está pausado o no tiene el módulo, y se consulta **en cada petición**.

### 5.2 Planes (`app/core/planes.py`)

Tres planes de barbería (los del bot —Básico/Pro/Premium— viven en el mismo
diccionario pero no se ofrecen a una barbería: `ORDEN` vs `ORDEN_BARBERIA`).

| Código | Nombre | $/mes | Bot | IA | Sedes | Barberos | Instalación |
|---|---|---|---|---|---|---|---|
| `barberia` | Barbería | 89.000 | no | no | 1 | 5 | — |
| `barberia_bot` | Barbería + Bot | 149.000 | sí | no | 2 | 8 | 250.000 |
| `barberia_bot_ia` | Barbería + Bot IA | 219.000 | sí | sí | 3 | 10 | 250.000 |

⚠️ **Son precios de ejemplo** (comentario en `planes.py`: "la especificación los
deja pendientes (§11.1)"). Los cupos efectivos son
`planes.cupo_de_sedes(fila)` / `cupo_de_barberos(fila)`: el valor pactado en
`max_*` manda sobre el del plan; un 0 o vacío cuenta como "no dicho".

### 5.3 Modelo de datos (19 tablas `barb_*`, todas con `client_id` + RLS)

Dinero: `Numeric(12,2)`; porcentajes: `Numeric(5,2)`. **Nunca `float`.**
Fechas: `DateTime(timezone=True)` siempre en **UTC** (`modelos.ahora()`); SQLite las
devuelve sin zona, por eso `modelos.en_utc()` las normaliza antes de comparar.
Se usa prefijo `barb_` y no un esquema de PostgreSQL porque las pruebas corren en
SQLite y `tablas_sin_cerradura()` solo revisa `current_schema()`.

**Fase 0 — personas y acceso** (`e1b5c3a7d902`)

| Tabla | Para qué | Columnas clave |
|---|---|---|
| `barb_sedes` | Un local | `nombre`, `direccion`, `telefono`, `zona_horaria` (**definida pero no se lee**, §10), `activo` |
| `barb_personal` | Cada persona del equipo | `panel_user_id`→`panel_users`, `nombre`, `correo`, `telefono`, `rol`, `esquema_pago`, `comision_defecto`, `sueldo_fijo`, `alquiler_silla`, `meta_quincena`, `clave_temporal`, `activo`, `eliminado_en` (borrado lógico) |
| `barb_personal_sede` | En qué sedes trabaja (muchos a muchos) | `UNIQUE(personal_id, sede_id)` |
| `barb_actividad` | Auditoría: quién hizo qué. **Nada se edita ni se borra** | `actor` (texto, aparte del `personal_id`), `accion`, `tabla`, `registro_id`, `sede_id`, `detalle`, `motivo`, `antes`/`despues` (JSON) |
| `barb_recuperaciones` | Enlaces de "Olvidé mi contraseña" | `token_hash` (SHA-256, único), `vence_en`, `usado_en` |

**Fase 1 — catálogo, clientes, dinero** (`f2c6d4b8e013`)

| Tabla | Para qué | Notas |
|---|---|---|
| `barb_servicios` | Qué se hace en la silla | `nombre`, `orden`, `activo`. **Global del negocio**; el precio va por sede |
| `barb_servicio_sede` | Precio y duración de un servicio **en una sede** | `precio`, `duracion_minutos`; sin fila = no se ofrece ahí |
| `barb_comision_servicio` | Excepción de comisión de un barbero para un servicio | Manda sobre `comision_defecto` |
| `barb_clientes` | Quien se sienta en la silla | `contact_id`→`contacts` (une con el bot por celular), `telefono` (solo dígitos, único por negocio), `notas` |
| `barb_citas` | **La única agenda** (citas del bot, del panel y clientes sin cita) | `sede_id`, `barbero_id`, `cliente_id`, `inicio`, `fin`, `estado`, `origen`, `propina`, `servicio_id` (lo reservado), `recordatorio_en`, `motivo_cancelacion`, `motivo_anulacion`, `anulada_en` |
| `barb_cita_servicios` | Lo que **de verdad** se hizo y cobró, **congelado** | `nombre`, `precio`, `porcentaje_barbero`, `monto_barbero`, `monto_barberia` |
| `barb_cajas` | Caja de una sede en un día | `base_inicial`, `efectivo_esperado/contado`, `diferencia`, `abierta_por/cerrada_por` |
| `barb_pagos` | Partes de un cobro (un pago dividido = 2 filas) | `metodo`, `monto` (incluye la propina) |
| `barb_gastos` | Arriendo, servicios, insumos… | `categoria`, `tipo` (FIJO/VARIABLE), `caja_id` (si salió de la caja) |
| `barb_adelantos` | Plata adelantada a alguien | `liquidacion_id` se llena al aprobar la liquidación que lo descuenta |
| `barb_liquidaciones` | Pago quincenal | `UNIQUE(personal_id, periodo_inicio)`; estados BORRADOR/APROBADA/PAGADA. En borrador **no hay fila**: se calcula en vivo |

**Fase 2 — agenda** (`a4d7e9b2c015`)

| Tabla | Para qué |
|---|---|
| `barb_horarios` | Cuándo se atiende, por día de semana (0=lunes), en **hora local** de la sede. `personal_id` vacío = horario de la sede; con él, el de ese barbero. Varias filas el mismo día = tramos |
| `barb_bloqueos` | Un rato sin agenda (almuerzo, vacaciones, festivo), de un barbero o de toda la sede |

**Restricciones CHECK en la base:** `rol IN ('DUENO','ADMIN','RECEPCION','BARBERO')`,
`esquema_pago IN ('COMISION','FIJO_MAS_COMISION','ALQUILER_SILLA')`,
`estado` de cita (7 valores), `origen` de cita (`WALK_IN`,`PANEL`,`WHATSAPP`,`WEB`),
`metodo` de pago (`EFECTIVO`,`TRANSFERENCIA`,`TARJETA`,`OTRO`), `tipo` de gasto,
`estado` de liquidación, `dia_semana BETWEEN 0 AND 6`.
→ **Cambiar un rol o un estado exige migración**, no solo código.

**Inventario / productos:** **no existe** ninguna tabla. `nomina.calcular` deja
`productos = 0` ("la venta de productos llega en la Fase 3").

### 5.4 Roles y permisos (`app/barberia/permisos.py`)

| Rol (BD) | En pantalla | Entra a | Secciones de `/b` |
|---|---|---|---|
| `DUENO` | Dueño | `/b/resumen` | todas (9) |
| `ADMIN` | Administrador de sede | `/b/resumen` | resumen, agenda, caja, gastos, inventario, actividad |
| `RECEPCION` | Recepción | `/b/caja` | agenda, caja |
| `BARBERO` | Barbero | `/yo/dia` | ninguna de `/b`; su panel es `/yo` |

Secciones, en el orden de la barra: `resumen`, `agenda`, `caja`, `equipo`
("Barberos y pagos"), `gastos`, `inventario`, `actividad`, `sedes`, `usuarios`.
Cuatro pestañas de celular: Resumen · Caja · Pagos · Actividad (recepción: Agenda · Caja).

**Tres puertas, en este orden, en cada petición:**
1. **Módulo** — negocio activo y con `barberia_contratada`.
2. **Sede** — todos menos el dueño solo ven las sedes de `barb_personal_sede`
   (`permisos.sede_permitida`; una sede ajena en la URL se **ignora**, no da error).
3. **Rol** — `permisos.puede_ver_seccion`.

> **La puerta es el servidor.** Esconder "Usuarios" de la barra no impide escribir
> `/b/usuarios`. Toda ruta pasa por `rutas._exigir`; una ruta nueva que se salte
> `_exigir` le enseña a un barbero la caja de todas las sedes, sin error.

**Reglas finas que viven en la lógica, no en la matriz:**
- Un **barbero** solo toca *sus* citas (`agenda._puede_tocar`), solo anula servicios
  **de hoy** y solo cobra citas propias.
- **Recepción no puede anular**; debe pedírselo al dueño o administrador.
- **Solo el dueño** cambia el esquema de pago, agrega sedes y administra usuarios.
- El administrador **no ve nómina** (decisión explícita: la §5 del diseño le quita
  "nómina/liquidaciones"; si se cambia, es añadir `"equipo"` a su tupla).
- La **actividad** del administrador se filtra a sus sedes; lo que no es de ninguna
  sede (usuarios, contraseñas, nómina) es solo del dueño.
- El dueño **no puede** quitarse el rol, apagarse el acceso ni quitarse a sí mismo.

**Doble identidad del acceso.** El usuario/clave es una fila de `panel_users`
(misma tabla y hash que el panel del bot). `barb_personal` añade lo propio del
negocio. **`panel_users.rol` ≠ `barb_personal.rol`:** el dueño va con `"dueno"`
(si su plan trae bot, atiende conversaciones); todo el resto con `"barberia"`
(`equipo.ROL_BARBERIA`), que `equipo.de_pase` **deja fuera de `/admin`**. Sin eso,
cualquier barbero entraría a las conversaciones del bot como si fuera el dueño.

### 5.5 Autenticación y sesión (`cuentas.py`, `rutas.py`)

- **Una sola pantalla de entrada** para todos los roles (`/entrar`); el rol decide
  el destino. Se entra con **usuario, correo o celular**.
- **Hash:** PBKDF2-SHA256, 210.000 vueltas (`acceso.hash_clave`).
- **Freno:** 5 intentos por **(usuario + IP)** y 15 min fuera, diciendo cuántos
  quedan; encima, el freno por IP de la plataforma. Es por usuario+IP y no solo por
  usuario para que nadie deje fuera al dueño tecleando su nombre cinco veces.
- **No se revela qué usuarios existen:** "no existe" y "clave incorrecta" dan el
  mismo mensaje. Solo con la clave **correcta** se distingue *desactivado* y
  *barbería pausada* (el dueño ve la pantalla de cuenta pausada con cuánto debe y
  cómo pagar).
- **Sesión:** el mismo pase firmado y la misma cookie del panel del bot
  (`COOKIE` de `admin_ui`). Sin "Recordarme": 5 h de inactividad / 12 h tope y cookie
  de sesión. Con él: 30 días y cookie persistente. El pase **recordado** se
  reconoce por su propio vencimiento firmado, así una renovación no convierte una
  sesión corta en una de 30 días. Cada pantalla renueva por uso.
- **Clave temporal:** el dueño o el super-admin la ponen (`Nombre-1234`); mientras
  `clave_temporal` esté activa **ninguna otra pantalla abre** (se redirige a
  `/cambiar-contrasena`). Mínimo 8 caracteres.
- **Recuperación por correo:** enlace de 30 min y un solo uso; se guarda el **hash**
  del token; máximo 3 enlaces vigentes por persona; el enlace se arma con
  `PANEL_URL` y **no con el `Host` de la petición** (para que nadie pueda mandar a
  una víctima un enlace legítimo que lleve a otro sitio); la pantalla responde
  igual exista o no el usuario.
- **Avisos de "hecho"** viajan en una cookie de un solo uso (`barb_aviso`, 60 s), no
  en `?aviso=texto`: con la URL cualquiera armaría un enlace que muestre un aviso
  falso dentro del panel del dueño.
- **Redirecciones:** `volver` se valida (`startswith("/b/agenda")`) para que no sea
  un redireccionador abierto.

---

## 6. Reglas de negocio de la barbería

### 6.1 Dinero (`operacion.py`)
- **Montos congelados.** Al cobrar se copian precio, porcentaje, nombre, parte del
  barbero y parte de la barbería a `barb_cita_servicios`. Cambiar el catálogo o la
  comisión **no toca lo ya cobrado ni las liquidaciones**.
- **Nada se borra.** Un servicio se **anula** con motivo (estado `ANULADA`) y queda
  en Actividad. Una caja cerrada no se edita.
- `Decimal` siempre; se redondea **al peso** (`ROUND_HALF_UP`) solo al guardar la
  parte de cada quien y al mostrar. Tope por monto: $100.000.000.
- Texto → dinero: solo se toman los dígitos (`"$394.000"` → 394000); un número no
  se reinterpreta (`241000.00` no son 24 millones).

### 6.2 Cobrar (`operacion.cobrar`)
1. Valida: ≥ 1 servicio, método válido, sede permitida, propina ≥ 0.
2. Todos los servicios deben estar en el catálogo **de esa sede**.
3. `total = Σ precios + propina`.
4. Métodos: `efectivo`, `transferencia`, `tarjeta` o `dividido`. **Dividido** es
   *solo efectivo + transferencia*; el efectivo va entre $1 y total−1.
5. Sin `cita_id` → **cliente sin cita**: se crea una visita `COMPLETADA`, origen
   `WALK_IN`, que "empezó hace lo que dura el servicio y terminó ahora" (para no
   ocupar en la agenda un rato que aún no pasó).
   Con `cita_id` → se cobra **esa** cita agendada (debe ser del barbero, de esa
   sede y activa) y pasa a `COMPLETADA` con lo que de verdad se hizo.
6. **Si la caja de la sede está cerrada, se abre sola** con base $0 a nombre de
   quien cobra y queda en Actividad. (El diseño lo pone como primera opción; el
   código lo marca "la decisión sigue abierta".)
7. Por cada servicio: `pct = _porcentaje(...)` → excepción por servicio
   (`barb_comision_servicio`) → si no, `comision_defecto`; **`ALQUILER_SILLA` ⇒ 100 %**.
   `monto_barbero = precio × pct / 100` (al peso); `monto_barberia = precio − monto_barbero`.
8. La **propina va en la cita, no en el pago** (un pago dividido la contaría dos
   veces) y es **100 % del barbero**. El `Pago` sí incluye la propina: es lo que
   entró a la caja.
9. Devuelve lo que le tocó al barbero (`Σ monto_barbero + propina`).

### 6.3 Caja (`operacion.py`)
- Una caja **abierta por sede** a la vez (base inicial al abrir).
- `esperado = base + efectivo cobrado − gastos pagados de la caja`. Solo cuenta el
  **efectivo**; transferencia y tarjeta se muestran pero no entran al arqueo. Los
  pagos de servicios **anulados no cuentan**.
- Cerrar: se guarda `esperado`, `contado` y `diferencia = contado − esperado`
  (negativa = faltante). Cerrada, **no se recalcula** ni se edita.
- Cierre con diferencia ≠ 0 aparece en "Para revisar" del Resumen durante 7 días.

### 6.4 Anular (`operacion.anular`)
Motivo obligatorio (cuatro motivos predefinidos en la hoja del barbero). Un barbero
anula solo lo suyo **del día**; dueño y administrador, cualquier día de sus sedes;
recepción, no. La cita pasa a `ANULADA` con `motivo_anulacion` y `anulada_en`; sus
montos salen de caja, resumen y liquidación. Se registra en Actividad.

### 6.5 Nómina (`nomina.py`)
Quincenas: **1–15 y 16–fin de mes** (`formato.quincena_de`).

```
Le pagas = comisiones (+ sueldo fijo si FIJO_MAS_COMISION) + propinas
           + productos (hoy 0) − descuentos
descuentos = adelantos sin descontar (fecha ≤ fin de quincena) + alquiler de silla (si aplica)
```

- Tres esquemas: `COMISION` (50/50, 60/40…), `FIJO_MAS_COMISION`, `ALQUILER_SILLA`.
- **BORRADOR** (sin fila) → se calcula en vivo y cambia con cada cobro.
  **APROBAR** congela las cifras en `barb_liquidaciones` y **liga los adelantos**
  (`liquidacion_id`). **PAGADA** es final (revertirla "exige anular con motivo", fuera
  de alcance hoy). Dos aprobaciones del mismo período chocan por el `UNIQUE`.
- Solo cuentan citas `COMPLETADA` (no anuladas).
- Vista del barbero: **"Hoy llevas"** (Σ su parte + propinas de hoy) y **"Mis
  ganancias"** (neto de la quincena, meta, gráfica día por día, desglose y
  descuentos). Si la liquidación ya está guardada, el neto es el congelado.
- Solo **barberos** (`rol = BARBERO`) entran a la liquidación; el dueño, el
  administrador y recepción no tienen esquema de pago en pantalla.

### 6.6 Agenda (`agenda.py`)
**Un HUECO** es un inicio en el que cabe el servicio entero: dentro del horario,
fuera de todo bloqueo y sin pisar ninguna cita que ocupe.

- **Qué citas ocupan:** `PENDIENTE`, `CONFIRMADA`, `EN_CURSO`, `COMPLETADA`.
  `CANCELADA`, `ANULADA` y `NO_ASISTIO` **liberan** el hueco.
- **Horario:** el propio del barbero en esa sede; si no tiene filas, el de la
  sede. Por defecto una sede nueva nace con **lun–sáb 8:00–20:00, dom 10:00–16:00**.
- **Rejilla:** huecos cada **30 min** (`PASO_MINUTOS`); no se ofrece un hueco que
  empieza en menos de **30 min** (`ANTICIPACION_MINUTOS`); se miran **21 días**
  (`DIAS_A_MIRAR`).
- **"El que esté libre":** a cada hora le toca el barbero con **menos citas ese día**
  (decisión §11.6 del diseño, marcada provisional).
- **Reservar va con candado.** Entre que el cliente ve los horarios y toca uno
  pasan minutos; `reservar` vuelve a calcular los huecos **dentro** de
  `_CANDADO` y levanta `Ocupado` si ya no está. Un `threading.Lock` basta porque
  hay un solo proceso; con varios procesos habría que pasar a una restricción
  `EXCLUDE` de PostgreSQL (`btree_gist`) sobre (barbero, rango). **Está
  documentado como pendiente** en la migración de la Fase 1.
- **Estados de cita:** `PENDIENTE` ("Sin confirmar") → `CONFIRMADA` → `EN_CURSO` →
  `COMPLETADA`; salidas: `CANCELADA`, `NO_ASISTIO` ("No vino"), `ANULADA`.
  Toda cita creada por `reservar` **entra `CONFIRMADA`** (quien la pide por
  WhatsApp o en el local la acaba de confirmar). Transiciones permitidas por
  `cambiar_estado`: empezar y "no vino" desde activas; confirmar solo desde `PENDIENTE`.
- **Una cita reserva UN servicio** (`barb_citas.servicio_id`); lo realmente hecho
  (varios) se registra al cobrar.
- **"Sin cobro":** una cita activa cuyo fin pasó hace > 30 min. Se pinta distinta en
  la agenda, aparece en "Para revisar" y avisa en la ficha de la cita.
- **Ocupación** = horas con cliente en silla (citas `COMPLETADA`) ÷ horas de horario
  de los barberos, en %. `None` si no hay horario que medir.

### 6.7 Resumen (`reportes.resumen`)
Todo sale de los montos **congelados**, nunca de los precios actuales.

| Cifra | Definición |
|---|---|
| Ingresos | Lo facturado en servicios (**sin propinas**: son del barbero) |
| Ganancia neta | Σ `monto_barberia` (la parte de la barbería) − gastos |
| Margen | neta ÷ ingresos |
| Ticket | ingresos ÷ visitas |
| Cambio | vs. periodo anterior (ayer / semana pasada / mes pasado) |
| Ocupación | ver §6.6 |

Periodos: **hoy / semana (lun–dom) / mes**. Más: gráfica (por hora, día o semana),
"Cómo llegan los clientes" (WhatsApp / sin cita / local; **sin la fila de WhatsApp
si el plan no trae bot**), "Cómo pagan", ranking de los 5 barberos que más
facturan y **"Para revisar"** (máx. 4: caja con diferencia, servicios anulados hoy,
citas sin cobro).

### 6.8 Catálogo
- `CATALOGO_INICIAL` (lo que nace con la primera sede): Corte clásico $35.000/40 min,
  Corte + barba $50.000/60, Barba $20.000/25, Cejas $10.000/15, Tintura $60.000/75,
  Lavado $8.000/10.
- Una sede nueva **copia los precios de la primera** (`sembrar_catalogo`).
- Un servicio nuevo nace con el **mismo precio en todas las sedes**; el precio se
  edita por sede en la pantalla Sedes y se registra en Actividad ("Lo ya cobrado no
  cambia").
- Gastos: categorías `Arriendo`, `Servicios públicos`, `Insumos`, `Mantenimiento`;
  tipo `FIJO`/`VARIABLE`; opcionalmente "Pagado de la caja" (exige caja abierta).

### 6.9 Clientes (`ClienteBarberia`)
Se identifican por **celular** (solo dígitos, único por negocio). Se vinculan al
`Contact` del bot por los **últimos 10 dígitos** (el bot guarda `573001112233`; en el
local se teclea `300 111 2233`). Vacío = "Cliente de paso" (decisión §11.5,
provisional). La **nota** de la ficha (máx. 500) la ve el barbero al atender. El bot
la usa también para "La última vez fue Corte clásico con Andrés".

### 6.10 Actividad (auditoría)
Acciones que se registran hoy: `SEDE`, `PRECIO`, `CAJA`, `SERVICIO`, `ANULACION`,
`CITA`, `USUARIO`, `CLAVE`, `PAGO`, `ADELANTO`. Filtros de pantalla: Todo ·
Anulaciones · Caja y adelantos · Citas sin cobro · Precios. El `actor` es texto
(puede ser "Bot de WhatsApp" o "Nitro2Tech (soporte)", que no son personas).
`registrar()` **nunca tumba** la operación que la llamó: si falla, solo lo anota en
el log.

---

## 7. Rutas HTTP de la barbería

Todas las de `/b` y `/yo` pasan por `rutas._exigir`. Los formularios funcionan **sin
JavaScript** (POST + redirección 303 con aviso en cookie).

| Ruta | Método | Quién | Qué hace |
|---|---|---|---|
| `/entrar` | GET/POST | público | Entrada única; el rol decide el destino |
| `/entrar/recuperar`, `/recuperar` | GET/POST | público | Pedir enlace de clave nueva |
| `/restablecer/{token}` | GET/POST | público | Crear clave con el enlace (410 si venció) |
| `/cambiar-contrasena` | GET/POST | sesión | Obligatoria con clave temporal |
| `/salir` | GET/POST | sesión | Cierra sesión |
| `/b` → destino del rol | GET | sesión | |
| `/b/{seccion}` | GET | por rol | Cada sección; parámetros `sede`, `periodo`, `filtro`, `fecha` y los que abren cajones (`nuevo`, `editar`, `quitar`, `adelanto`, `esquema`, `nueva`, `cita`, `bloquear`, `bloqueo`, `horario`) |
| `/b/agenda/cita` | POST | agenda | Nueva cita (`origen = PANEL`) |
| `/b/agenda/cita/{id}/estado` · `/cancelar` | POST | agenda | Confirmar / "No vino" / cancelar |
| `/b/agenda/bloqueo` · `/{id}/quitar` | POST | agenda | Bloquear/desbloquear un rato |
| `/b/clientes/{id}/nota` | POST | agenda | Nota de la ficha del cliente |
| `/b/caja/abrir` · `/{id}/cerrar` | POST | caja | Abrir con base / cerrar con arqueo |
| `/b/gastos` | POST | gastos | Registrar gasto |
| `/b/equipo/{id}/aprobar` · `/liquidacion/{id}/pagar` · `/adelanto` · `/{id}/esquema` | POST | equipo | Nómina |
| `/b/sedes/{id}/estado` · `/{id}/horario` · `/precios` · `/servicio` · `/nueva` | POST | sedes | Sedes, horarios, precios, servicios |
| `/b/usuarios` · `/{id}` · `/{id}/acceso` · `/{id}/quitar` · `/{id}/restablecer` | POST | usuarios | Alta, edición, interruptor, borrado lógico, clave temporal |
| `/yo`, `/yo/dia`, `/yo/ganancias` | GET | barbero | "Mi día" y "Mis ganancias" |
| `/yo/servicios` | POST | barbero | Cobrar (con o sin cita) |
| `/yo/servicios/{id}/anular` | POST | barbero | Anular uno suyo de hoy |
| `/yo/citas/{id}/{empezar\|no-vino}` | POST | barbero | Cambiar estado de su cita |
| `/superadmin/barberias` (+`/{id}/pago`, `/pausa`, `/reactivar`, `/plan`, `/limites`, `/restablecer-dueno`) | GET/POST | super-admin | Consola (ver §8) |

Pantallas de **"cajón"** (panel lateral), **diálogo** y **hoja** (celular, desde
abajo) se abren con parámetros de URL y se cierran con enlace, `Esc` o tocando el velo.

---

## 8. Consola Nitro2Tech para barberías (`consola.py`)

`/superadmin/barberias`, con la **misma sesión** del super-admin del bot y **sin
inquilino**. Hace:

- **Listado** con filtros (Todas · Al día · Vence pronto · En gracia · Pausadas ·
  Nuevas), búsqueda por barbería o dueño, y columnas Plan · Sedes (uso/cupo) ·
  Barberos (uso/cupo) · Mensualidad · Estado.
- **Alta** (`dar_de_alta`): crea el `Client` (con `barberia_contratada`,
  `proveedor_agenda = "barberia"`, flags de bot/IA según plan, `vence_el` = hoy +
  14 días si hay "prueba"), la primera sede (con catálogo y horario por defecto) y el
  **dueño** (usuario sugerido `nombre.i`, clave temporal `Nitro-NNNN`), y le manda el
  acceso por correo. Un mismo correo no puede ser dueño de dos barberías.
- **Ficha**: dueño, cambiar plan, límites (**nunca por debajo de lo que ya usa**),
  registrar pago (`cobros.registrar_pago`: corre la fecha un mes y reactiva lo que
  pausó el cobro; una pausa a mano no la deshace un pago), pausar (motivos: falta
  de pago / lo pidió el cliente / revisión) y reactivar, y restablecer la clave del
  dueño (queda en Actividad como "Nitro2Tech (soporte)").
- **Estados derivados** (`_estado`): Pausada, Instalando bot (plan con bot sin
  `phone_number_id`), Sin cobro, En prueba, En gracia, Vence pronto, Al día.

**Pendiente según el propio código:** KPIs de plataforma, pantalla de cobros propia
de barberías, reglas de cobro editables, consumo del bot y "Entrar a su panel como
soporte".

---

## 9. El bot de WhatsApp y su relación con la agenda

### 9.1 Cómo se engancha (`bot_logic.py`, `barberia/bot.py`)
`bot_logic` solo desvía cuando `barberia_bot.es_barberia()` dice que el negocio tiene
`barberia_contratada` **y** `proveedor_agenda == "barberia"`. Sin inquilino devuelve
`False` (no levanta `SinInquilino`, que dejaría mudo al bot de siempre).
Puntos de enganche: la opción "cita" del menú (`_ofrecer_dias`), el despacho por
estado (`state in barberia_bot.ESTADOS`), los botones del recordatorio (antes del
despacho, porque llegan en cualquier punto del flujo) y la cancelación
(`_gestionar_cita`, que mira el prefijo `barb:`).

### 9.2 Recorrido de agendar
```
BARB_SEDE → BARB_SERVICIO → BARB_BARBERO → BARB_DIA → BARB_HORA → (reserva)
```
- Lo elegido viaja en `contact.temp_data` (JSON: `sede`, `servicio`, `barbero`, `dia`).
- **Un paso con una sola opción se salta solo** (una sede, un barbero).
- Ids de fila: `bsede_{id}`, `bserv_{id}`, `bbarb_{id}` (`0` = "El que esté libre"),
  `bdia_{YYYY-MM-DD}`, `bhora_{ISO}`.
- Hasta **10 filas** por lista; si hay más horas libres se reparten a lo largo del día
  y no solo las de la mañana. ≤ 3 horas salen como **botones**, más como lista.
- Se recorta **antes** de mandar (título de fila 24, descripción 72, botón 20) para
  que lo recortado siga teniendo sentido; `whatsapp_client` los vuelve a aplicar.
- Si el cliente **escribe** en vez de tocar: si es otra opción del menú, cambia de
  idea; si no, se repite la pregunta. Un botón viejo o datos que ya no cuadran
  **reinician** el recorrido en vez de dejar al bot mudo.
- Sin sedes, servicios, barberos u horarios libres (`_sin_agenda`): **la cita no se
  pierde**, se registra como cita manual para que la confirme una persona.
- Si dos clientes eligen el mismo hueco, el segundo recibe "Esa hora se acaba de
  ocupar. Estas siguen libres:" (por `Ocupado`).

### 9.3 La cita también queda como `Lead`
Además de la cita se guarda un `Lead` de tipo `cita` con
`google_event_id = "barb:{cita_id}"`. Así "Cancelar", "Reagendar", el aviso al dueño
y todo lo que el bot ya sabía hacer con una cita siguen funcionando sin duplicar
lógica. Cancelar una cita de barbería desde el bot llama a `agenda.cancelar`.
Tras reservar, el bot responde: servicio con barbero, fecha y hora, lugar (sede y
dirección), precio, y "Te escribo 2 horas antes para que confirmes".

### 9.4 Recordatorio de 2 horas antes (`recordatorios.py`)
Revisión cada 10 min. Toda cita `PENDIENTE`/`CONFIRMADA` que empieza en las próximas
2 h y no tiene `recordatorio_en` recibe **uno**, y se marca **siempre** (también si
no pudo salir, para no reintentar cada 10 min).
- **Solo negocios con plan que trae el bot** (`bot_contratado` + `proveedor_agenda =
  "barberia"`).
- **Ventana de 24 h de WhatsApp** (`notificaciones.ventana_abierta`): con ventana
  abierta, mensaje con dos botones **"Confirmo"** / **"Cancelar"** (ids
  `brec_ok_{id}` / `brec_no_{id}`). Cerrada → solo vale una **plantilla aprobada por
  Meta** (`negocio_config["barberia"]["plantilla_recordatorio"]`, variables:
  nombre, hora, barbero, sede), sin botones. Sin plantilla → no sale y queda en el log.
- Cada plantilla **la cobra Meta**.
- "Confirmo" pasa `PENDIENTE` → `CONFIRMADA`; "Cancelar" cancela y marca el `Lead`
  como `cancelada`. La cita del botón se verifica **de ese contacto** (el id viaja
  en el botón y podría ser de otro).

### 9.5 Lo del bot que se hereda tal cual
Máquina de estados (`NEW → ASKED_NAME → ASKED_NEED → …`), menú editable por negocio
(`negocio_config`, editor "mapa" y "contenido"), toma de control manual, panel de
conversaciones `/admin` (inbox, chat, etiquetas, nota interna, imágenes y notas de
voz, notificaciones push), avisos por área por **correo**, IA opcional (Gemini, con
tope de 8 s y respaldo al menú), estadísticas, `/conectar` y la App de Meta
**por cliente** (`/webhook/{token}` con firma validada con el `app_secret` de ese
cliente). Está documentado a fondo en `docs/CONTINUAR_AQUI.md` §3, §10 y §11.

> ⚠️ **Hallazgo:** el menú de ejemplo de `negocio.toml` es el de **Nitro2Tech**
> (chatbot, Power BI, páginas web…), **no** el de una barbería. Una barbería nueva
> nace con ese menú "en blanco" que se arma desde el editor; solo el flujo de
> **agendar** es específico de barbería. No hay menú de barbería prediseñado.

---

## 10. Capa de presentación

- **HTML en f-strings de Python** (`paginas.py`, `pantallas*.py`); todo texto que
  venga de la base o de quien escribe pasa por `e()` (`html.escape`). Los nombres de
  barberías y personas los escribe gente.
- **Una sola página adaptable**, no dos: tablas → tarjetas por debajo de 768 px;
  `solo-escritorio` / `solo-celular` / `solo-escritorio-bloque` para lo que cambia.
  Puntos de corte: **< 768** celular · **768–1023** escritorio con barra lateral de
  72 px · **≥ 1024** escritorio completo.
- **Tokens de diseño** (`barberia.css`, `:root`): neutros con sesgo violeta
  (`--ink #1A1823`, `--night #15131C`, `--mist #F3F0F8`), acento **violeta**
  (`--violet #56377F`, `--lilac #B69CF0`), semáforos propios (`--ok`, `--warn`,
  `--danger`, `--info`), degradados (`--grad-hero`, `--grad-barbero`,
  `--grad-entrada`), tipografías **Unbounded** (títulos) y **Manrope** (texto),
  autoalojadas en `/estaticos/fuentes/`.
- **Marca:** el logo **"Nitro 2Tech"** (`barberia/nitro-wordmark.png`) y el nombre
  "BarberSaaS" son de la plataforma, no del negocio. El titular de la entrada es
  *"Cada corte registrado, cada peso en su lugar."*
- **Componentes:** cajón lateral, diálogo, hoja inferior (celular), toast (cookie de
  un solo uso, 2,6 s), chips, interruptor, KPI, gráfica de barras, barras apiladas,
  ranking, tabla-tarjeta, agenda por columnas de barbero (`PX_HORA = 52`), línea roja
  de "ahora".
- **JavaScript (`barberia.js`, 231 l.)** solo comodidad; el panel funciona sin él:
  mostrar/ocultar contraseña, formato de dinero mientras se teclea, arqueo en vivo,
  total y "Para ti" de la hoja de cobro, usuario autocompletado (`Daniel Castro` →
  `daniel.c`), "Generar otra" clave temporal, foco atrapado en cajones/diálogos.
- **Trampas de CSS ya sufridas** (de `CONTINUAR_AQUI.md` §4, aplican igual):
  `[hidden]` necesita `!important`; en flex, `min-width: 0` en lo que deba encoger;
  nada de columnas `auto` en rejillas; un comentario CSS mal cerrado se come las
  reglas de detrás sin error; `.acciones > button` y no `.acciones button`.
- **Zona horaria:** el servidor manda instantes UTC y **el navegador** los traduce;
  solo lo que depende de la zona de la sede se calcula en servidor (`formato.py`).

---

## 11. Seguridad y verificación

### 11.1 Resumen de controles
Aislamiento por inquilino en dos capas · puerta de módulo/sede/rol en el servidor en
cada petición · hash PBKDF2 · freno por usuario+IP y por IP · sin enumeración de
usuarios · tokens de recuperación hasheados, de un solo uso y 30 min · cookies
`HttpOnly`, `SameSite=Lax`, `Secure` si hay HTTPS · avisos y redirecciones no
manipulables por URL · escape HTML de todo texto de usuario · credenciales de
clientes cifradas con `SECRETS_KEY` (`secretos.py`) y **tapadas** en mensajes de
error (`meta_estado._tapar`) · borrado lógico de personas y auditoría inmutable.

### 11.2 Pruebas (scripts que devuelven 0 o 1, **sin pytest**)
```bash
python tests/test_multitenant.py    # aislamiento entre clientes (la más importante)
python tests/test_regresion.py      # flujo del bot
python tests/test_ia.py             # la IA y sus topes
python tests/test_panel.py          # panel de atención
python tests/test_barberia.py       # el panel de barberías, fases 0–2 (1.212 l.)
python tests/test_rls.py            # cerraduras de la base; pide PostgreSQL (RLS_DATABASE_URL)
```
**Se corren de una en una** (puertos fijos; en paralelo se pisan). Dependencias
extra para correrlas: `av` (audio de `test_panel`) y, para `test_rls`, PostgreSQL.
Estado al 16-oct-2026: ver la tabla de la §0 (todas en verde salvo `test_rls`, que no corrió).

`test_barberia.py` cubre: esquema, planes, entrar (todos los resultados), sesión y
"Recordarme", quién ve qué, aislamiento entre barberías, panel del bot cerrado para
el personal, módulo contratado, clave temporal, recuperación, alta de personal,
y las fases 1 y 2 (cobrar, anular, caja, gastos, nómina, precios, sedes, usuarios,
consola, agenda). Usan SQLite temporal y **no** llaman a Meta ni a Google.

**Lo que las suites no ven** (y `CLAUDE.md` lo exige): cómo se ve una pantalla
(*"nada visual se da por bueno sin abrirlo en el navegador, en los dos temas y en
ancho de teléfono"*) y si Meta acepta un mensaje. Para mirar la barbería:
```bash
python scripts/servir_barberia.py   # http://127.0.0.1:8098/entrar  (SQLite temporal con "Filo Barbería")
python scripts/demo_barberia.py --si   # siembra una DEMO en Render. NUNCA contra producción
```

---

## 12. Deuda, huecos e inconsistencias encontradas

Cosas reales del código de hoy, en orden de importancia para quien vaya a copiarlo:

| # | Hallazgo | Dónde | Efecto |
|---|---|---|---|
| 1 | **La zona horaria está fija en `America/Bogota`.** `barb_sedes.zona_horaria` existe y **ninguna línea la lee**; `formato.ZONA`, `rutas._hoy()` y `formato.hoy_en` la fijan | `formato.py`, `rutas.py` | Una sede en otra zona vería horarios, "hoy" y quincenas corridos, sin error |
| 2 | **El Inventario no existe** (Fase 3). Aparece en la barra del dueño/administrador con un cartel "En construcción" | `paginas.VACIOS` | Sección visible y vacía; `productos = 0` en la nómina |
| 3 | **Los recordatorios del plan "Barbería" (sin bot) no existen.** El plan dice "Recordatorios de cita por correo y notificación" pero `recordatorios.py` solo sirve por WhatsApp y lo declara "para después" | `planes.py` vs `recordatorios.py` | Promesa comercial sin código |
| 4 | **La acción `CRUCE` nunca se registra**, pero hay un filtro "Citas sin cobro" en Actividad con ese nombre | `reportes.py` | El filtro siempre sale vacío (el cruce real sí aparece en "Para revisar") |
| 5 | **Origen `WEB`** existe en la base y en pantalla ("Web") pero **nada crea citas con él** | `modelos.py` | Reservado para una reserva web futura |
| 6 | **Dos citas solapadas del mismo barbero solo las evita un `Lock`** del proceso. Falta la restricción `EXCLUDE` | `agenda.py` | Seguro mientras haya un solo proceso |
| 7 | **Una cita reserva un solo servicio**; el bot ofrece uno por reserva | `agenda.reservar` | No hay reserva combinada ("corte + barba" es un servicio del catálogo) |
| 8 | **Precios y cupos de planes son de ejemplo**; el cobro se paga por Nequi a un número fijo en `planes.py` | `planes.py` | Hay que definirlos antes de vender |
| 9 | **Decisiones marcadas "provisionales"** en código: cliente sin datos permitido (§11.5), reparto por menos citas (§11.6), caja que se abre sola (6.4) | `operacion.py`, `agenda.py` | Confirmar con el dueño del producto |
| 10 | **Roles, estados y métodos en `CHECK` de la base** | migraciones | Un cambio de vocabulario exige migración |
| 11 | **Citas de la agenda desde el panel entran siempre `CONFIRMADA`**; `PENDIENTE` solo existe si se crea por otro camino | `agenda.reservar` | El estado "Sin confirmar" casi no se ve hoy |
| 12 | **Marca y textos de barbería incrustados en Python** (no en configuración): "BarberSaaS", titular, "barbero/barberos", `CATALOGO_INICIAL`, `MOTIVOS_ANULACION`, `CATEGORIAS_GASTO`, textos del bot | `paginas.py`, `pantallas*.py`, `operacion.py`, `bot.py` | Todo cambio de vocabulario es un cambio de código (ver §13) |
| 13 | Los **dos documentos de diseño/especificación** que el código cita no están en el repo | — | Ver §0 |
| 14 | `barberia.css` (1.556 l.) y `pantallas*.py` son grandes y están acoplados por nombres de clase | — | Cuidado al renombrar clases |
| 15 | **Solo un barbero puede cobrar.** El único camino de cobro es `POST /yo/servicios`, que exige `barbero=True` (`_exigir`), y `operacion.cobrar` usa `persona.personal_id` como el barbero de la cita. **Recepción, administrador y dueño no pueden registrar un servicio**, aunque la tarjeta de rol de Recepción dice "Registra servicios, cobra y abre o cierra caja" (`permisos.DESCRIPCION_ROL`). Hoy recepción solo agenda y abre/cierra caja | `rutas.py`, `operacion.py`, `permisos.py` | Texto que promete más que el código. Un dueño que también atiende, o una recepción que cobra, no pueden hoy |

---

## 13. Mapa de adaptación a spa de uñas *(propuesta, no decisión)*

> Esta sección **sí es propuesta**: sirve de lista de verificación para modificar la
> especificación antes de empezar. Nada de lo de aquí está hecho. Las preguntas
> abiertas están en `Especificacion de uso.md` §12.

### 13.1 Qué se reutiliza sin tocar (la plataforma)
`app/core/*` (tenencia, RLS, acceso, cobros, correo, planes como mecanismo),
`app/bot/*` (WhatsApp, menú, IA, avisos), `app/web/*` (panel de conversaciones,
super-admin, PWA, estáticos), migraciones/Alembic, Dockerfile/`render.yaml`, el
modelo "pase firmado + puertas en el servidor".

### 13.2 Qué cambia de nombre y de vocabulario
| Barbería | Spa de uñas (a decidir) | Dónde vive hoy |
|---|---|---|
| Barbería / BarberSaaS / Degradé | nombre del producto | `paginas.PRODUCTO`, `TITULAR`, textos, correos, `planes.py` |
| Barbero (`BARBERO`) | manicurista / técnica / "profesional" | `modelos.py` (CHECK), `permisos.py`, toda la UI |
| Silla (`alquiler_silla`) | mesa / estación / cabina | `modelos.Personal`, `nomina.py`, textos |
| Corte, barba, cejas, tintura, lavado | manicure, pedicure, semipermanente, acrílico/gel, retoque, nail art, retiro… | `operacion.CATALOGO_INICIAL` |
| "Cliente sin cita" / "walk-in" | "Cliente sin cita" | `operacion.cobrar`, `modelos.WALK_IN` |
| Prefijo de tablas `barb_` | `spa_` (o dejar `barb_` y no renombrar) | `modelos.py` + migraciones + RLS + `MODELOS_DEL_INQUILINO` |
| Paleta violeta Nitro | paleta del spa | `barberia.css :root` (tokens) |

### 13.3 Qué probablemente cambia de comportamiento (por la naturaleza del servicio)
Estos puntos salen de comparar *cómo funciona una silla de barbería* con *cómo suele
funcionar un servicio de uñas*; **hay que validarlos con quien conoce el negocio**:

1. **Duración variable y servicios combinados.** En uñas es común reservar varios
   servicios juntos (manicure + pedicure) y que la duración dependa de la
   técnica/diseño. Hoy: una cita = un servicio = una duración fija (`ServicioSede`).
2. **Más de una persona atendiendo a la vez / estaciones.** Hoy la agenda es por
   barbero (columna por persona) y un barbero atiende una cita a la vez.
3. **Anticipos o depósitos** para reservar (muy común en uñas para frenar
   inasistencias). Hoy no hay pago previo: el cobro es al final.
4. **Retoque y garantía** (volver en X días). Hoy no hay concepto de seguimiento.
5. **Productos / inventario** (esmaltes, geles, acrílicos): hoy no existe y el
   código lo da por "Fase 3". En uñas el consumo de insumos pesa más.
6. **Ficha del cliente más rica:** alergias, forma/largo preferidos, fotos de
   referencia o de trabajos anteriores, historial de diseños. Hoy: una nota de texto
   de 500 caracteres.
7. **Comisión:** en barbería hay `COMISION` / `FIJO_MAS_COMISION` / `ALQUILER_SILLA`.
   Validar si el spa necesita los tres, otros, o paga por servicio.
8. **Recordatorios:** 2 h antes por WhatsApp hoy; en uñas suele ser el día anterior.
9. **Catálogo de servicios con precio por sede y duración por sede:** probablemente
   igual; valorar *recargos* (diseño, largo, extras) como opciones del servicio.

### 13.4 Archivos que tocan casi seguro (por tipo de cambio)
- **Solo vocabulario/marca:** `paginas.py`, `pantallas.py`, `pantallas_agenda.py`,
  `permisos.py` (nombres de rol), `planes.py` (nombres y textos), `bot.py`
  (mensajes), `recordatorios.py` (mensaje), `operacion.py` (listas de motivos,
  categorías, catálogo), `negocio.toml`, `barberia.css` (tokens).
- **Esquema (exige migración + RLS + `MODELOS_DEL_INQUILINO`):** `modelos.py` y una
  migración nueva si se renombran tablas, roles o se agregan entidades
  (varios servicios por cita, anticipos, inventario, ficha ampliada).
- **Lógica:** `agenda.py` (duraciones/combinados/estaciones), `operacion.py` (cobro,
  anticipos), `nomina.py` (esquemas), `reportes.py` (KPIs).
- **Correcciones que conviene hacer *antes* de copiar** (de la §12): leer
  `Sede.zona_horaria` (#1), decidir si el inventario entra (#2), decidir el recordatorio
  sin bot (#3), quitar o implementar `CRUCE` (#4).

### 13.5 Cómo organizar el trabajo (sugerencia)
1. Línea base: las suites ya están en verde en el estado actual (§0); volver a
   correrlas **de una en una** después de cada bloque de cambios.
2. Obtener los dos documentos de especificación/diseño de la barbería (§0).
3. Modificar **primero** `Especificacion de uso.md` (decisiones de producto) y de ahí
   esta especificación técnica.
4. Recién entonces: renombrar vocabulario → migración de esquema → lógica → pruebas
   → **mirar cada pantalla en el navegador** (`servir_barberia.py` adaptado).
5. Mantener `docs/CONTINUAR_AQUI.md` al día (es el único archivo de continuidad).
