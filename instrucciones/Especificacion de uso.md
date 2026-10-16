# Especificación de uso — cómo funciona hoy

> **Para qué sirve este documento.** Describe, desde el lado de quien lo usa, **cómo
> funciona hoy el software de barberías** (nombre en pantalla: *BarberSaaS*; en la
> web de Nitro2Tech: *Degradé*). Es la base sobre la que se va a construir el
> software para **spa de uñas**, así que está escrito para poder **recorrerlo con
> el dedo y decidir qué se queda, qué cambia y qué se agrega** (la §12 reúne las
> preguntas de producto que esa decisión necesita).
>
> No hace falta saber programar para leerlo. El detalle técnico (tablas, archivos,
> reglas internas) está en `Especificacion tecnica.md`.
>
> Es una **fotografía del 16-oct-2026**, leída del código. Donde algo **no
> funciona como promete la pantalla**, se dice (marcado con ⚠️).

---

## 1. Qué es, en una página

Un negocio (la barbería) contrata a **Nitro2Tech** un panel web para llevar su día
a día. Con él:

| Tarea | Cómo se resuelve hoy |
|---|---|
| **Agenda** | Una columna por barbero, por día; las citas las pone la recepción en el panel **o el cliente por WhatsApp** (si el plan trae bot) |
| **Cobrar** | El barbero registra cada servicio que hizo y cómo le pagaron; el sistema calcula al instante cuánto le toca a él y cuánto a la barbería |
| **Caja** | Una caja por sede y por día, con arqueo de efectivo (lo que debería haber contra lo que se contó) |
| **Pagar a los barberos** | Liquidación cada quincena, con adelantos y tres formas de pago (comisión, fijo + comisión, alquiler de silla) |
| **Gastos** | Arriendo, servicios, insumos; pueden salir de la caja |
| **Control** | "Actividad": quién hizo qué, nada se borra |
| **Varias sedes** | Un mismo dueño, varias sedes; cada persona ve solo las suyas |

Y, si el plan lo incluye, un **bot de WhatsApp** que atiende al cliente final: le
muestra sedes, servicios, barberos y horas libres, le **agenda la cita** y se la
recuerda 2 horas antes.

**Dos pantallas distintas según quién eres:**
- Dueño, administrador y recepción usan el **panel de gestión** (`/b/…`), pensado
  para computador pero que también se ve bien en celular.
- El **barbero** usa **"Mi día"** (`/yo/…`), pensado para el celular, de fondo
  oscuro (menos brillo en el local), con lo mínimo: su siguiente cita, "Hoy llevas",
  registrar un cliente y sus ganancias.

**El cliente final no tiene cuenta ni pantalla web.** Solo habla con el bot.

---

## 2. Quién usa qué

| Quién | Rol | Cómo entra | A dónde llega | Qué puede hacer |
|---|---|---|---|---|
| **Nitro2Tech** (la plataforma) | Super-admin | `/superadmin` con una clave propia | Consola de barberías | Dar de alta barberías, cambiar plan y límites, registrar pagos, pausar/reactivar, restablecer la clave del dueño |
| **Dueño** | `DUENO` | Usuario y contraseña | Resumen | **Todo**: ve todas las sedes, la nómina, los usuarios y los precios |
| **Administrador de sede** | `ADMIN` | Usuario y contraseña | Resumen | Caja, agenda, gastos, inventario y actividad **de sus sedes**. **No ve** la nómina, ni Sedes, ni Usuarios |
| **Recepción** | `RECEPCION` | Usuario y contraseña | Caja | **Agenda** y **caja** de sus sedes. No ve reportes |
| **Barbero** | `BARBERO` | Usuario y contraseña | "Mi día" | Sus citas, cobrar sus servicios, anular los suyos **de hoy**, ver sus ganancias |
| **Cliente final** | — | WhatsApp | — | Agendar, confirmar o cancelar su cita |

Reglas que conviene tener claras:
- **Cada persona ve solo sus sedes.** Si alguien escribe a mano la dirección de una
  sede ajena, simplemente se ignora.
- **El dueño no puede** quitarse el rol, apagarse el acceso ni quitarse a sí mismo
  (se quedaría fuera de su propia barbería).
- **Solo el dueño** agrega sedes, cambia precios por sede, define cómo se paga a cada
  barbero y administra usuarios.
- Un **barbero** puede estar en **varias sedes** ("rota entre sedes") y entonces elige
  en cuál trabajó al registrar un cliente.

> ⚠️ **Solo un barbero puede cobrar.** Recepción, administrador y dueño **no tienen
> pantalla para registrar un servicio**, aunque la tarjeta del rol Recepción dice
> "Registra servicios, cobra y abre o cierra caja". Hoy la recepción agenda y
> abre/cierra caja, pero el cobro lo hace el barbero desde su celular.

---

## 3. Cómo nace una barbería (lo hace Nitro2Tech)

En `/superadmin/barberias` → **Nueva barbería**:

1. **Datos:** nombre de la barbería, nombre de la primera sede (por defecto
   "Principal"), nombre del dueño, **correo** (obligatorio y válido), celular.
2. **Plan** (precios de ejemplo, por definir):

| Plan | $/mes | Bot | IA | Sedes | Barberos |
|---|---|---|---|---|---|
| **Barbería** | 89.000 | no | no | 1 | 5 |
| **Barbería + Bot** | 149.000 (+250.000 de instalación) | sí | no | 2 | 8 |
| **Barbería + Bot IA** | 219.000 (+250.000 de instalación) | sí | sí | 3 | 10 |

3. **Prueba:** casilla "Empieza con 14 días gratis" (marcada por defecto).
4. Al crear, el sistema **hace todo lo demás**: crea la barbería, su primera sede con
   los **6 servicios de ejemplo** y el horario por defecto, y el usuario del
   **dueño** (el usuario sale de su nombre: "Ricardo Gómez" → `ricardo.g`).
5. **Le llega un correo al dueño** con la dirección de entrada, su usuario y una
   **contraseña temporal** (`Nitro-NNNN`). Al primer ingreso se le obliga a crear una propia.
6. Un mismo correo **no puede ser dueño de dos barberías**.

**Después, Nitro2Tech puede, desde la ficha:**
- **Cambiar de plan** (se cobra el nuevo precio desde el próximo mes).
- **Ajustar límites** de sedes y barberos *pactados con ese cliente* (nunca por
  debajo de lo que ya usa).
- **Registrar un pago:** corre la fecha de "pagado hasta" un mes.
- **Pausar** (motivo: falta de pago / el cliente lo pidió / revisión) y **reactivar**.
- **Restablecer la contraseña del dueño** (queda en Actividad como "Nitro2Tech (soporte)").

**Estados que muestra el listado:** Al día · Vence pronto · En gracia · Pausada · En
prueba · Instalando bot (plan con bot al que aún no se le conectó el WhatsApp) · Sin cobro.

**Calendario de cobro (automático):** el dueño recibe un aviso diario desde 7 días
antes de vencer; vencido, el servicio sigue **2 días de gracia**; **al tercero se
pausa solo**. Un dueño pausado por impago que entra con su clave correcta ve cuánto
debe y cómo pagar (Nequi y comprobante por WhatsApp); su equipo solo ve "El panel
no está disponible por ahora".

---

## 4. Entrar y cuidar la cuenta

**Pantalla de entrada** (una sola para todos los roles). A la izquierda, la marca
con el titular *"Cada corte registrado, cada peso en su lugar."*; a la derecha, el
formulario. En el celular, la marca pasa arriba como cabecera.

- **Usuario, correo o celular** + **contraseña** (con botón "Mostrar").
- **"Recordarme"** (marcado por defecto): la sesión dura **30 días**. Sin marcarlo,
  la sesión se cierra tras **5 h sin uso** o a las **12 h**, y al cerrar el navegador.
- **Quién llega a dónde:** Dueño y Administrador → Resumen · Recepción → Caja ·
  Barbero → Mi día.

**Si algo sale mal, lo que dice la pantalla:**

| Situación | Mensaje |
|---|---|
| Vacío | "Escribe tu usuario y tu contraseña." (marca el campo vacío) |
| Usuario o clave mal | "Usuario o contraseña incorrectos. **Te quedan N intentos.**" (no dice cuál de los dos) |
| 5 intentos fallidos | "Bloqueamos el acceso por 15 minutos. El dueño puede restablecer tu contraseña desde Usuarios." |
| Usuario desactivado (con la clave buena) | "Este usuario está desactivado. Pídele al dueño que lo vuelva a activar." |
| Barbería pausada (con la clave buena) | Al dueño: pantalla con lo que debe y cómo pagar. Al resto: "El panel no está disponible por ahora. Habla con el dueño." |
| Plan sin el panel | "Tu plan no incluye el panel de la barbería. Habla con Nitro2Tech para agregarlo." |
| Sesión vencida | "Tu sesión terminó. Entra de nuevo." |

**Contraseña temporal.** Si el dueño te creó el usuario, la clave que te dio es
temporal: al entrar **no se abre ninguna otra pantalla** hasta crear una propia
(mínimo 8 caracteres, escrita dos veces). Con una clave propia, para cambiarla hay
que escribir también la actual.

**"Olvidé mi contraseña".** Se escribe usuario, correo o celular; llega un enlace al
correo (si la persona tiene uno guardado), **válido 30 minutos y de un solo uso**.
La pantalla responde siempre lo mismo ("Revisa tu correo"), exista o no el usuario,
para que nadie pueda averiguar quién tiene cuenta.

---

## 5. El panel de gestión (dueño, administrador, recepción)

### 5.1 Cómo se ve y se mueve
- **Escritorio:** barra lateral oscura con el nombre de la barbería y su plan arriba;
  las secciones que tu rol puede ver; abajo, tu nombre y rol, "Cambiar contraseña" y
  "Salir". La cabecera de cada pantalla trae el título, un subtítulo con el periodo o
  la fecha y, a la derecha, los filtros.
- **Filtros:** **Sede** ("Todas" + cada una, solo si tienes más de una) y **Periodo**
  (Hoy / Semana / Mes, solo en Resumen).
- **Celular:** las sedes pasan a chips bajo la cabecera y las secciones a **pestañas**
  abajo (hasta cuatro: *Resumen · Caja · Pagos · Actividad*; cada rol ve solo las que
  le tocan — recepción ve *Agenda · Caja*). Las tablas se vuelven tarjetas.
- **Insignias** en la barra: Caja "N abierta(s)"; Actividad "N hoy".
- **Aviso de "hecho"** (una franja que aparece 2,6 s): "Caja abierta.", "Gasto
  registrado.", "Cita agendada."…
- **Paneles laterales ("cajones")** para crear o editar; se cierran con **Cerrar**,
  **Esc** o tocando fuera.

| Sección | Dueño | Administrador | Recepción |
|---|:-:|:-:|:-:|
| Resumen | ✅ | ✅ | — |
| Agenda | ✅ | ✅ | ✅ |
| Caja | ✅ | ✅ | ✅ |
| Barberos y pagos | ✅ | — | — |
| Gastos | ✅ | ✅ | — |
| Inventario | ✅ | ✅ | — |
| Actividad | ✅ | ✅ (solo sus sedes) | — |
| Sedes | ✅ | — | — |
| Usuarios | ✅ | — | — |

### 5.2 Resumen — "Cómo va el negocio"
Para Hoy, la Semana o el Mes, y para una sede o todas:

- **Ganancia neta** (tarjeta grande): lo que le queda a la barbería, y debajo
  "Te queda el N% de lo facturado en X servicios" (o "Pierdes el N%").
- **Ingresos** (con "+9% frente a ayer/la semana pasada/el mes pasado"), **Gastos**
  (con "Insumos es el 40%"), **Ticket promedio** (por visita) y **Ocupación** (horas
  con cliente en silla ÷ horas de horario; "—" si no hay horario que medir).
- **Gráfica** de ingresos por hora (hoy), por día (semana) o por semana (mes), con
  "Mejor momento".
- **Cómo llegan los clientes** (WhatsApp / sin cita / agendados en el local — la fila
  de WhatsApp **no aparece si el plan no trae bot**) y **Cómo pagan** (transferencia /
  efectivo / tarjeta).
- **Barberos que más facturan:** los 5 primeros, con barra, servicios y ocupación.
- **Para revisar** (máx. 4, cada uno lleva a su pantalla): una caja que cerró con
  faltante o sobrante, servicios anulados hoy, citas que ya pasaron y no tienen cobro.
  Si no hay nada: *"Nada pendiente. Todo cuadra."*

> Las **propinas no cuentan como ingreso** de la barbería: son del barbero.
> Todas las cifras salen de lo **cobrado y congelado**, no de los precios de hoy.

### 5.3 Agenda
- **Una columna por barbero** de la sede elegida (si hay "Todas", se muestra la
  primera de las tuyas y lo dice). El eje va del primer al último horario de la sede.
  La **línea roja** marca la hora actual. Se navega con ‹ Hoy ›.
- **Color por estado** (con leyenda): Completada · En curso · Confirmada · Sin
  confirmar · No vino · **Sin cobro** (la cita ya pasó hace más de 30 min y nadie la
  cobró ni la marcó "no vino"). Las que vinieron por WhatsApp llevan esa etiqueta.
- **Tocar una cita** abre su ficha: cuándo, servicio, celular, y — mientras esté
  activa — **Confirmar** (si estaba sin confirmar), **No vino** y **Cancelar la cita**
  (motivo opcional; el horario queda libre). También la **Ficha del cliente** con una
  **nota** (hasta 500 caracteres) que **el barbero ve al atenderlo**.
- **Nueva cita:** se elige barbero (o "El que esté libre"), servicio (con precio y
  duración) y día; el panel muestra las **horas realmente libres** y se completa con
  el celular o nombre del cliente (opcional). Entra **Confirmada**.
  *"El que esté libre"* le da a cada hora el barbero con menos citas ese día.
- **Bloquear horario:** a un barbero o a toda la sede, un día y un rango (por defecto
  12:00–13:00, "Almuerzo"). Mientras esté bloqueado, **ni el panel ni el bot** agendan
  ahí. Se quita tocándolo.
- Si dos personas intentan el mismo hueco a la vez, la segunda recibe *"Ese horario ya
  se ocupó. Elige otro."* Una sede sin horario ese día muestra *"La sede no atiende
  este día."*
- Una cita **solo ocupa** el hueco si está Pendiente, Confirmada, En curso o
  Completada; Cancelada, Anulada y "No vino" lo **liberan**.

### 5.4 Caja
Una tarjeta **por sede**, con tres estados:

- **Sin abrir:** *"La caja de hoy no se ha abierto. Se abre sola con el primer cobro,
  o ábrela aquí con la base que dejaste."* Campo **Base al abrir** + **Abrir caja**.
- **Abierta:** "Vendido hoy", quién y a qué hora la abrió, el desglose
  (Transferencia · Tarjeta · Efectivo) y el **Arqueo de efectivo**:

```
   Base al abrir
 − (nada: la base suma)   + efectivo cobrado hoy
 − Gastos pagados de la caja
 = Debería haber            ← lo que el sistema espera
   Cuánto contaste          ← lo escribes tú
```
  Mientras escribes lo contado, la pantalla dice en vivo **"Cuadra exacto"**,
  **"Falta $X"** o **"Sobra $X"**; **Cerrar caja** está apagado hasta que haya un conteo.
- **Cerrada:** quién y a qué hora, lo que se contó y la diferencia. **No se edita.**

> *"Una caja cerrada no se puede editar. Si hay que corregir algo, se anula con motivo
> y queda en Actividad."* Solo el **efectivo** entra al arqueo; transferencias y
> tarjetas se muestran aparte. Los servicios **anulados** no cuentan.
>
> Si el barbero cobra con la caja cerrada, **se abre sola** con base $0 a su nombre y
> queda anotado en Actividad.

### 5.5 Barberos y pagos (solo dueño) — la quincena
Quincenas: **del 1 al 15 y del 16 al fin de mes.**

- **Tres tarjetas:** Total de la quincena · Falta por pagar · Adelantos a descontar.
- **Una fila por barbero:** esquema (con nota: "Sobre lo que factura", "$X por
  quincena", "Paga $X por quincena"), **Comisiones**, **Propinas**, **Productos**
  (hoy siempre $0), **Descuentos** (adelantos y/o alquiler, con su nota) y **Le pagas**.
- **Acción por fila, en orden:** **Aprobar** (congela las cifras y liga los adelantos)
  → **Marcar pagada** → *Pagada* (final). Mientras es borrador, los números **cambian
  con cada cobro**.
- **Registrar adelanto** (botón arriba): a quién, cuánto, nota. *"Se descuenta en la
  liquidación de esta quincena."*
- **Tocar el esquema** de un barbero (solo el dueño) abre **"Cómo se le paga a …"**:

| Esquema | Cómo funciona |
|---|---|
| **Comisión** | Se lleva un % de lo que factura (50/50, 60/40…) |
| **Fijo + comisión** | Un sueldo fijo por quincena **más** un % |
| **Alquiler de silla** | Se queda con **todo** lo que factura (100 %) y **paga un alquiler** por quincena |

  Más: su porcentaje, sueldo fijo, alquiler y **meta de la quincena**. *"Lo ya cobrado
  no cambia."* Además puede haber una **comisión distinta por servicio** para un barbero
  (manda sobre su porcentaje general; hoy se guarda pero no tiene pantalla para editarla).

### 5.6 Gastos
Tabla del **mes** (concepto, categoría, tipo, sede, fecha, monto) con **total**, y el
formulario **Registrar gasto**: ¿En qué se gastó? · Monto · **Categoría** (Arriendo,
Servicios públicos, Insumos, Mantenimiento) · **Tipo** (Fijo cada mes / Variable) ·
Sede · casilla **"Pagado de la caja (resta del arqueo)"**, que exige la caja de esa
sede abierta (si no: *"La caja de esa sede está cerrada. Ábrela o registra el gasto
sin marcar «Pagado de la caja»."*).

### 5.7 Inventario
⚠️ **No existe todavía.** La sección aparece, con un cartel *"En construcción — Aquí
verás el stock de cada producto por sede y cuándo pedir más. Llega con el
inventario, en la Fase 3."* Tampoco hay venta de productos: en la nómina, "Productos"
vale siempre $0.

### 5.8 Actividad — "Quién hizo qué. Nada se borra, todo queda aquí."
Lista cronológica (lo más reciente primero, hasta 200 líneas) con **quién**, **qué
hizo**, el detalle y el **motivo** si lo hay; punto de color por tipo (rojo anulación,
violeta caja/adelanto/pago, lila precios…). **Filtros:** Todo · Anulaciones · Caja y
adelantos · Citas sin cobro · Precios. El administrador ve solo lo de sus sedes; lo
que no es de ninguna sede (usuarios, contraseñas, nómina) lo ve solo el dueño.

Se anota: abrir/cerrar caja (con faltante o sobrante), servicios registrados y
anulados (con motivo), citas agendadas/canceladas/"no vino", cambios de precio, de
horario, de sede, altas y cambios de usuarios, cambios de contraseña, adelantos,
liquidaciones aprobadas y pagadas, y cómo se le paga a alguien.

> ⚠️ El filtro **"Citas sin cobro"** hoy siempre sale vacío (nada registra ese tipo
> de línea). Esas citas sí se ven en *Resumen → Para revisar* y en la Agenda.

### 5.9 Sedes (solo dueño)
- **Una tarjeta por sede:** nombre y dirección, **interruptor** abierta al público /
  pausada (*pausar no borra nada*), barberos, lo facturado este mes, **horario** (con
  "Editar") y el precio del primer servicio.
- **Horario de la sede:** por día de la semana, casilla abierto/cerrado y hora de
  apertura y cierre. *"Los barberos de la sede trabajan este horario. El bot solo
  ofrece horas dentro de él."* Una sede nueva nace lun–sáb 8 a. m.–8 p. m., domingo
  10 a. m.–4 p. m. (La interfaz permite **un tramo por día**.)
- **Barra del plan:** *"Usas 3 sedes de 3 y 8 barberos de 10 que incluye tu plan."* con
  **Agregar sede** (si queda cupo) y **Ampliar plan** (abre el WhatsApp de Nitro2Tech).
- **Servicios y precios:** tabla servicios × sedes con el precio editable por sede
  (*"Lo ya cobrado no cambia"*), y **Servicio nuevo** (nombre + un precio que se
  aplica a todas las sedes; la duración nace en 30 min).
- Una sede **nueva** arranca con los **mismos servicios y precios** que la primera.

### 5.10 Usuarios (solo dueño)
- **Tarjetas:** Usuarios con acceso · Barberos de tu plan ("8 de 10") · Desactivados.
- **Tabla:** persona (@usuario), **Rol** (chip de color), Sedes, Contacto, **Último
  ingreso**, **Acceso** (interruptor) y **Editar / Quitar**.
- **Agregar usuario:** nombre completo, **usuario** (se autocompleta: "Daniel Castro"
  → `daniel.c`; solo letras sin tilde, números, punto y guion bajo), correo o celular
  (para recuperar la clave), **rol** (cada uno con su descripción, ver §2), **sedes**
  donde trabaja (el Dueño marca todas) y una **contraseña temporal** (`Filo-4827`, con
  "Generar otra"). Si el plan ya tiene el máximo de barberos: *"Llegaste a los N
  barberos de tu plan. Amplía el plan para agregar más."*
- **Interruptor de Acceso:** apagado no puede entrar pero **sigue en la lista**
  (y su puesto del plan sigue ocupado).
- **Quitar:** borrado **lógico**; su nombre de usuario queda libre y su historial
  (servicios, cajas, pagos) se conserva. *"Si solo quieres bloquearlo por un tiempo,
  apaga su acceso."*
- **Restablecer contraseña** (dentro de Editar): genera una temporal nueva que se le
  exige cambiar.

---

## 6. El panel del barbero — "Mi día"

Fondo oscuro, hecho para el celular. Arriba: **"Hola, Andrés"**, la sede y la fecha, y
**"Hoy llevas $X"** (su parte de cada servicio **más sus propinas**, sin contar lo
anulado) con el número de servicios y de propinas. Dos vistas: **Mi día** y **Mis
ganancias**.

### 6.1 Mi día
1. **Tu siguiente cita** (tarjeta grande): hora, cliente, servicio y duración,
   **nota del cliente** si la hay, y de dónde vino ("Agendó por WhatsApp" / "Agendado
   en el local"). Botones **No vino** y **Empezar**. Al empezar pasa a **"Atendiendo
   ahora"** y el botón se vuelve **Cobrar**.
2. **Después:** las demás citas del día, con su estado (Confirmada / Sin confirmar).
3. **Ya hiciste:** lo cobrado hoy, del más reciente al más antiguo: hora, cliente,
   servicios y método, **+$ lo tuyo** y **Anular**. Lo anulado sale tachado con su motivo.
4. Botón flotante **"Registrar cliente sin cita"**.

### 6.2 Cobrar (la hoja que sube desde abajo)
Sirve para quien llegó **sin cita** ("Cliente sin cita — Para quien llega sin
reservar") y para **cobrar una cita agendada** ("Cobrar a {nombre}", con lo reservado
ya marcado):

1. **¿En qué sede?** (solo si trabajas en varias y no es una cita agendada).
2. **¿Qué le hiciste? Puedes marcar varios** — cada servicio con su precio en esa sede.
3. **¿Cómo pagó?** Efectivo · Transfer. · Tarjeta · **Dividido** (si es dividido, se
   pide cuánto fue en **efectivo** y el resto se toma como transferencia).
4. **Propina:** Nada · 5 mil · 10 mil · 20 mil.
5. **Celular o nombre del cliente** (opcional; en una cita agendada no se pregunta).
6. Al pie, en vivo: **Cobra $X** y **Para ti $Y** (estimado con tu porcentaje).
7. **Registrar.** Aviso: *"Servicio registrado. Ganaste $Y."*

Si falta algo (servicio, método, efectivo del dividido) el botón o el servidor lo
dicen: "Elige qué le hiciste.", "Elige cómo pagó.", "En un pago dividido, el efectivo
va entre $1 y $…".

### 6.3 Anular un servicio
Solo **los tuyos y de hoy** (después, solo el dueño o el administrador). Se elige un
motivo — *Lo registré por error · Quedó repetido · El cliente no pagó · Cambió de
servicio* — y **Anular**. *"No se borra: queda anulado con el motivo y el dueño lo ve
en Actividad."* Sus montos salen de la caja, del resumen y de tu liquidación.

### 6.4 Mis ganancias
La **quincena en curso**: el **neto** ("Lo que te pagan el 15/30, ya descontados los
adelantos"), tu **meta** con barra de progreso ("Te faltan $X para llegar a $Y"),
**Día por día** (barras) y el desglose: tu % de los servicios (o "tu fijo y tu %", o
"lo que facturaste, todo tuyo"), **Propinas (son todas tuyas)**, **Productos
vendidos**, y los **descuentos** (adelantos y alquiler de la silla).

---

## 7. El cliente final por WhatsApp (solo con plan que trae bot)

### 7.1 Agendar — la conversación
El cliente escribe al número del negocio. Tras el saludo y su nombre, elige la
opción de **agendar** del menú, y el bot lo guía con **listas y botones**:

```
Bot      ¿En qué sede te atendemos?                  ← solo si hay más de una sede
         [lista: Chapinero · Usaquén · Cedritos]

Bot      ¡Hola, Camila! ¿Qué te vas a hacer? La última vez fue Corte clásico con Andrés.
         [lista: Corte clásico — $35.000 · 40 min | Barba — $20.000 · 25 min | …]

Bot      ¿Con quién te quieres atender?              ← solo si hay más de un barbero
         [lista: El que esté libre — "Te damos la hora más cercana" | Andrés | Sofía…]

Bot      ¿Qué día te queda bien?
         [lista: Hoy… — 3 horarios libres | Mañana… — 7 horarios libres | …]

Bot      Andrés tiene libre el mañana, vie 17 de oct:
         [hasta 3 horas → botones · más de 3 → lista de hasta 10 horas]

Bot      Listo, quedó tu cita ✂️
         Corte clásico con Andrés
         Mañana, vie 17 de oct, 3:30 p. m.
         Chapinero, Cra. 13 #60-20
         $35.000
         Te escribo 2 horas antes para que confirmes.
         [Menú principal …]
```

- **Un paso con una sola opción se salta solo** (una sola sede o un solo barbero).
- Si el cliente **escribe** en vez de tocar: si es otra opción del menú, cambia de
  idea; si no, el bot repite la pregunta.
- Si la hora **se ocupó** mientras elegía: *"Esa hora se acaba de ocupar. Estas siguen
  libres:"* y vuelve a ofrecer.
- Si el día **se llenó**: *"Ese día se llenó. ¿Qué otro día te queda bien?"*
- Si **no hay** sedes, servicios, barberos u horarios libres: la solicitud **no se
  pierde**; queda como cita manual para que una persona del negocio la confirme.
- Se ofrecen días hasta **21 días** adelante (10 días con huecos), cada **30 minutos**,
  y **nunca** una hora que empiece en menos de **30 minutos**.
- La cita **entra confirmada** en la Agenda del panel y le **avisa al dueño**.

### 7.2 Recordatorio y confirmación
**2 horas antes**, el bot le escribe:
*"Hola, Camila. Te recuerdo tu cita de hoy a las 3:30 p. m. con Andrés en Chapinero.
¿Nos confirmas?"* con **[Confirmo]** y **[Cancelar]**.
- **Confirmo** → la cita queda Confirmada: *"¡Perfecto! Te esperamos a las …"*
- **Cancelar** → se cancela y se libera el horario: *"Listo, cancelé tu cita de las ….
  Cuando quieras, agenda otra desde el menú."*
- Cada cita recibe **un solo** recordatorio.
- **Si pasaron más de 24 h desde que el cliente escribió** (WhatsApp no deja mandar
  texto libre), solo sale si el negocio tiene una **plantilla** aprobada por Meta
  (sin botones). Sin plantilla, **el recordatorio no sale** y queda en el registro.
  Cada plantilla **la cobra Meta**.

### 7.3 Cancelar o reagendar por su cuenta
Desde el menú del bot (gestionar su cita) puede **cancelar**; la cita se cancela
también en la Agenda del panel con el motivo *"El cliente la canceló por WhatsApp"*.

### 7.4 Atención manual
Cuando el plan incluye el bot, el **dueño** también tiene el panel de conversaciones
(`/admin`): bandeja, chat, etiquetas, nota interna, imágenes y notas de voz, y puede
**tomar el control** de una conversación para responder a mano. **El resto del
personal** (barberos, recepción, administradores) **no entra ahí**.

---

## 8. Un día típico, de punta a punta

| Hora | Quién | Qué pasa |
|---|---|---|
| 7:50 | Recepción | Entra a **Caja**, abre la caja con una **base** de $50.000 (o se abrirá sola con el primer cobro) |
| 8:00 | Cliente | Por WhatsApp agenda el corte de las 3:30 con Andrés (cae en la Agenda, Confirmada) |
| 9:15 | Andrés | En **Mi día** ve su siguiente cita; llega alguien sin cita → **Registrar cliente sin cita**, marca Corte clásico, **Efectivo**, propina 10 mil → *"Ganaste $27.500"* |
| 12:00 | Recepción | **Bloquea** el almuerzo de Andrés (12:00–13:00) |
| 13:30 | Dueño | Mira el **Resumen** desde el celular: ingresos, ticket, ocupación |
| 15:30 | Cliente | Le llegó el recordatorio a la 1:30 y tocó **Confirmo**. Andrés toca **Empezar**, termina y toca **Cobrar** |
| 18:00 | Un cliente no llegó | Andrés (o recepción) lo marca **No vino**; el hueco queda libre |
| 19:30 | Recepción | **Cierra la caja**: cuenta el efectivo, la pantalla dice "Falta $5.000"; queda en Actividad y en *Para revisar* |
| 1 y 16 | Dueño | En **Barberos y pagos**: revisa cada fila, **Aprueba**, paga y marca **Pagada** |

---

## 9. Las cuentas, con ejemplos

**Cobrar un servicio.** Corte clásico $35.000, barbero al **50 %**, propina $10.000,
paga en efectivo:
```
Cliente paga           $45.000   (35.000 + 10.000)
Al barbero             $27.500   (17.500 de su 50 % + 10.000 de propina)
A la barbería          $17.500
Entra a la caja        $45.000   (el pago incluye la propina)
Cuenta como ingreso    $35.000   (la propina no es de la barbería)
```
**Pago dividido.** Total $45.000, efectivo $20.000 → se guardan **dos pagos**:
efectivo $20.000 y transferencia $25.000. Al arqueo solo entran los $20.000.

**Arqueo.** Base $50.000 + efectivo cobrado $200.000 − gasto pagado de la caja $30.000
= **debería haber $220.000**. Si se cuentan $215.000: **"Falta $5.000"**.

**Ganancia neta.** Lo que le queda a la barbería de cada servicio (su parte, no la
del barbero) − los gastos del periodo. Margen = neta ÷ ingresos.

**Liquidación quincenal.**
```
Le pagas = comisiones (+ sueldo fijo si es "Fijo + comisión")
         + propinas
         + productos (hoy $0)
         − descuentos   [ adelantos pendientes + alquiler de silla si aplica ]
```
Ejemplo: comisiones $800.000 + propinas $120.000 − adelanto $100.000 = **$820.000**.
Con "Alquiler de silla" ($400.000 por quincena) el barbero se queda con el 100 % de lo
que factura y se le descuenta el alquiler.

**Nada de esto se recalcula hacia atrás:** el precio y el porcentaje se **congelan al
cobrar**. Cambiar el precio del corte o la comisión de un barbero no toca lo ya
cobrado ni las liquidaciones.

---

## 10. Lo que NO hace hoy (límites reales)

| Tema | Estado hoy |
|---|---|
| **Inventario y venta de productos** | No existe (aparece "En construcción"; "Productos" = $0) |
| **Quién cobra** | Solo el barbero. Recepción/administrador/dueño no registran servicios ⚠️ |
| **Una cita, un servicio** | Se reserva un solo servicio; "Corte + barba" es un servicio del catálogo. Al cobrar sí se pueden marcar varios |
| **Zona horaria** | Siempre **Bogotá**. El campo "zona horaria" de la sede existe pero no se usa ⚠️ |
| **Recordatorios sin bot** | El plan "Barbería" promete recordatorios por correo/notificación; **no existen**. Solo hay recordatorio por WhatsApp |
| **Reserva por internet (web)** | No hay página de reservas para el cliente; solo WhatsApp y el panel |
| **Anticipos / pagos antes de la cita** | No existen; se cobra al terminar |
| **Cliente con perfil rico** | Solo nombre, celular, correo, barbero preferido (guardado) y una nota de 500 caracteres |
| **Varios tramos de horario en un día** | La base lo soporta; la pantalla de horario edita **un tramo por día** |
| **Comisión por servicio** | Existe en el cálculo; **no hay pantalla** para definirla |
| **Reportes exportables** | No hay exportar a Excel/PDF |
| **Cobro al cliente final con pasarela** | No: se registra el método (efectivo, transferencia, tarjeta, otro) pero no se procesa el pago |
| **Idiomas / monedas** | Solo español de Colombia y pesos (COP) |
| **Marca propia** | El panel muestra el **nombre** del negocio, pero el producto se llama "BarberSaaS" y lleva el logo de Nitro 2Tech; no hay logo ni colores propios por negocio |
| **Menú del bot de barbería** | No hay un menú de barbería prediseñado: el negocio lo arma en el editor del bot. Solo el flujo de **agendar** es específico |

---

## 11. Glosario de lo que se ve en pantalla

| Palabra | Significa |
|---|---|
| **Sin confirmar** | Cita en estado Pendiente |
| **Sin cobro** | Cita que ya pasó (+30 min) y nadie cobró ni marcó "No vino" |
| **No vino** | El cliente no llegó; libera el hueco |
| **Anulado** | Servicio cobrado que se invalidó con motivo; no se borra |
| **Base** | Efectivo con el que abre la caja |
| **Arqueo** | Comparar el efectivo que debería haber con el contado |
| **Quincena** | 1–15 y 16–fin de mes |
| **Esquema** | Cómo se le paga a un barbero (comisión / fijo + comisión / alquiler de silla) |
| **Cupo** | Cuántas sedes y barberos incluye el plan |
| **Temporal** | Contraseña que obliga a crear una propia al entrar |
| **Cajón / hoja / diálogo** | Panel lateral, panel que sube desde abajo (celular) y ventana de confirmación |

---

## 12. Preguntas para adaptar el producto a un spa de uñas

> Esta es la parte **de decisión**. Cada pregunta cuelga de algo que hoy funciona de
> una forma concreta (en cursiva, lo de hoy). Marca la respuesta que corresponda; con
> ellas se modifica este documento y, de ahí, la especificación técnica. **Mi
> propuesta por defecto va con ➜, solo como punto de partida.**

### A. Identidad
1. **Nombre del producto** y de su marca ante el cliente. *Hoy: BarberSaaS / Degradé,
   con el logo de Nitro 2Tech.* ➜ Un nombre nuevo; Nitro 2Tech sigue como "un producto de".
2. **Paleta, tipografías y tono.** *Hoy: violeta oscuro, Unbounded + Manrope, tono
   directo ("Cada corte registrado, cada peso en su lugar").* ➜ Paleta y
   titular nuevos; el resto del sistema de diseño se reutiliza.
3. **¿Una instalación por spa con su marca, o la misma marca para todos?** *Hoy: la
   misma.* ➜ La misma al inicio.

### B. Personas y roles
4. **¿Cómo se llama quien atiende?** *Hoy: "barbero".* ➜ "Manicurista" o "Profesional"
   (neutro por si luego hay pedicura, cejas, masajes…).
5. **¿Se mantienen los cuatro roles** (dueño, administrador de sede, recepción,
   profesional)? *Hoy sí.*
6. **¿Quién cobra?** *Hoy solo el barbero, desde su celular.* En un spa suele cobrar la
   **recepción** o la caja. ➜ Permitir cobrar a recepción y al administrador, y que el
   dueño pueda cobrar si también atiende. (Corrige el ⚠️ de §2.)
7. **¿Hay varios puestos de trabajo (mesas/estaciones/cabinas)** que limiten cuántas
   clientas caben a la vez? *Hoy: la unidad es la persona; una persona = una cita a la vez.*

### C. Servicios y agenda
8. **Catálogo inicial** de servicios, precios y duraciones. *Hoy: 6 de barbería.*
   ➜ Lista del spa: manicure, pedicure, semipermanente, gel/acrílico, retoque, retiro,
   nail art…
9. **¿Varios servicios en una misma cita** (manicure + pedicure)? *Hoy: una cita = un
   servicio.* ➜ Sí: la duración de la cita es la suma.
10. **¿Extras y recargos** (diseño por uña, largo, decoración) sobre el servicio base?
    *Hoy: no existen.*
11. **¿La duración depende de la profesional o del servicio?** *Hoy: del servicio y la
    sede, igual para todos.*
12. **¿Dos profesionales pueden trabajar a la vez con la misma clienta** (manos y pies
    en paralelo)? *Hoy: no.*
13. **Horarios:** ¿tramos partidos (mañana y tarde)? *Hoy: un tramo por día en la
    pantalla; la base soporta varios.* ¿Rejilla de 30 min o de 15?
14. **Anticipación mínima y máxima** para agendar. *Hoy: mínimo 30 min, máximo 21 días.*

### D. Clienta
15. **¿Qué se guarda de cada clienta?** *Hoy: nombre, celular, correo, una nota de 500
    caracteres.* ¿Alergias? ¿Forma/largo/color preferidos? ¿Fotos de referencia o de
    trabajos anteriores? ¿Cumpleaños?
16. **¿Historial de servicios visible** al agendar y al atender? *Hoy: el bot dice "La
    última vez fue…".*
17. **¿Garantía o retoque** (volver en X días sin costo)? *Hoy: no existe.*

### E. Dinero
18. **¿Cómo se paga a las profesionales?** *Hoy: comisión, fijo + comisión o alquiler de
    silla.* ¿Se mantienen los tres? ¿"Alquiler de mesa"? ¿Pago por servicio?
19. **Quincena** (1–15 / 16–fin). *Hoy fija.* ¿Semanal o mensual en el spa?
20. **Propinas:** *hoy 100 % de quien atiende.* ¿Igual?
21. **¿Anticipo o depósito** para reservar (para frenar las inasistencias)? *Hoy: no.* ➜
    Opcional por negocio; con confirmación del comprobante por la recepción.
22. **¿Paquetes, bonos o membresías?** *Hoy: no existen.*
23. **Métodos de pago:** efectivo, transferencia, tarjeta, otro. ¿Se añade algo (Nequi,
    Daviplata, datáfono)? *Hoy: cuatro métodos fijos.*

### F. Inventario
24. **¿Entra el inventario** (esmaltes, geles, acrílicos, limas)? *Hoy: no existe y
    está marcado "Fase 3".* ¿Solo insumos de uso interno, o también productos para
    vender? ¿Descuento automático por servicio?

### G. Bot de WhatsApp
25. **Guion de la conversación.** *Hoy: sede → servicio → barbero → día → hora.* ¿Se
    pregunta por **diseño / referencia (foto)**? ¿Se permite elegir **varios servicios**?
26. **Recordatorio.** *Hoy: 2 horas antes, con Confirmo/Cancelar.* En uñas suele ser el
    **día anterior** (y quizá otro 2 h antes). ¿Cuándo y cuántos?
27. **Plantilla de Meta** para recordar fuera de las 24 h: *hoy la crea cada negocio.*
    ¿Se entrega una plantilla estándar del spa?
28. **Política de cancelación** (cuánto antes, penalización). *Hoy: se cancela
    libremente.*
29. **Lista de espera** cuando el día se llena. *Hoy: no existe.*
30. **¿Y la IA?** *Hoy es un plan aparte.* ¿Se mantiene como plan superior?

### H. Planes y negocio
31. **Planes y precios** del spa. *Hoy: 89 / 149 / 219 mil COP de ejemplo, con cupos de
    sedes y "barberos".* ➜ Cupos de sedes y profesionales; decidir si la instalación del
    bot (250.000) se mantiene.
32. **Cobro a los negocios:** *hoy Nequi y comprobante por WhatsApp.* ¿Igual?

### I. Técnico (lo que condiciona el trabajo)
33. **¿Renombrar las tablas `barb_*` y el rol `BARBERO`?** Es lo más costoso (migración
    + RLS + pruebas). ➜ Renombrar el vocabulario de **pantalla** y dejar los nombres
    internos de la base al inicio, o hacerlo de una vez antes de tener datos reales.
34. **¿Se corrigen antes de copiar** los huecos de la `Especificacion tecnica.md` §12?
    Sobre todo la **zona horaria** (hoy fija en Bogotá), el **cobro por recepción** y los
    recordatorios del plan sin bot.
35. **¿Un repositorio y un despliegue aparte para el spa, o el mismo multi-producto?**
    *Hoy el repo `Spa-de-u-as` es una copia completa que aún dice "barbería" por dentro.*
36. **Los dos documentos originales** de la barbería (*Instrucciones SAAS barberia.md* y
    *design_handoff_barbersaas/README.md*) no están en el repositorio. ¿Se pueden
    conseguir para partir de las reglas y el diseño originales?

---

## 13. Equivalencias de vocabulario (para la adaptación)

| Hoy (barbería) | Propuesta spa de uñas |
|---|---|
| Barbería | Spa / Salón de uñas |
| Barbero | Manicurista / Profesional |
| Silla · "Alquiler de silla" | Mesa / Estación · "Alquiler de mesa" |
| Corte, barba, cejas, tintura, lavado | Manicure, pedicure, semipermanente, gel/acrílico, retoque… |
| Cliente sin cita / de paso | Clienta sin cita |
| "Cada corte registrado, cada peso en su lugar." | Titular nuevo |
| "Pagos a barberos" · "Barberos y pagos" | "Pagos a profesionales" · "Equipo y pagos" |
| "Te escribo 2 horas antes" | Según la decisión 26 |
