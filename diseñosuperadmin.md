# Rediseño de `/superadmin` — especificación para implementar

Documento de implementación del panel super-admin rediseñado.
Complementa `PANEL_SUPERADMIN.md` (que describe **qué hace** la herramienta);
este dice **cómo se ve y cómo se estructura** ahora.

Referencia visual: `Panel Superadmin.dc.html` (maqueta interactiva).

Restricciones que siguen en pie: HTML generado desde Python con f-strings,
CSS y JS a mano en archivos aparte, sin dependencias nuevas de frontend.

---

## 1. Decisión de identidad

El super-admin **adopta la identidad de Nitro**: morado `#6D28D9`, neutros
con sesgo violeta, Manrope + IBM Plex Mono. Se distingue del panel del
cliente por la **estructura** (barra lateral oscura de operación, densidad
de tabla, tipografía mono en todos los identificadores), no por otra paleta.

### Fichas de color

```css
:root {
  /* marca */
  --morado:        #6D28D9;
  --morado-fuerte: #5B21B6;
  --morado-tenue:  #F3EEFF;
  --morado-borde:  #C4B5FD;

  /* neutros con sesgo violeta */
  --tinta:   #1B1633;
  --texto:   #4A4560;
  --tenue:   #6E6A85;
  --apagado: #9E99B4;
  --papel:   #FAF9FC;
  --caja:    #FFFFFF;
  --borde:   #EDEAF5;
  --borde-2: #E7E4F0;

  /* semáforos — NO siguen a la marca, no cambian nunca */
  --bien:   #15803D;  --bien-fondo:   #ECFDF3;
  --avisa:  #B45309;  --avisa-fondo:  #FEF6E7;
  --mal:    #B91C1C;  --mal-fondo:    #FEF2F2;  --mal-borde: #F0A9A9;
  --neutro: #52607A;  --neutro-fondo: #F1F3F7;
}
```

**Radios:** 9–10px controles · 14–16px tarjetas · 999px chips.
**Sombras:** casi ninguna. Solo las barras fijas (`0 8px 30px rgba(27,22,51,.07)`)
y el diálogo de entrada.
**Tipografía:** Manrope 400/600/700/800. Títulos con `letter-spacing: -0.02em`.
IBM Plex Mono para ids, tokens, números y cupos — nunca para prosa.
**Tamaños:** título de pantalla 26px/800 · título de tarjeta 15px/800 ·
etiqueta de campo 12px/600 · cuerpo 13px · nota 11.5px.

---

## 2. Logo de Nitro

Donde hoy aparece el texto “Nitro superadmin” debe ir **el logo de Nitro
seguido del wordmark**:

- Barra lateral (arriba a la izquierda) — logo 24px + `Nitro` en 800 y
  `superadmin` en 600 con color `--apagado`/`#8A7CB8`.
- Pantalla de entrada — logo 26px sobre el fondo oscuro, wordmark en
  `#F5F3FF` y `superadmin` en `#A78BFA`.
- `<title>` y favicon del documento.

Implementación: **SVG servido desde el propio dominio**
(`app/web/estaticos/nitro-logo.svg`, con hash de contenido en la dirección,
igual que el CSS). Dos variantes o una sola con `currentColor`:

```html
<a class="marca" href="/superadmin">
  <img class="marca-logo" src="/estaticos/nitro-logo.svg?h={hash}" alt="Nitro" width="24" height="24">
  <span class="marca-texto">Nitro <span>superadmin</span></span>
</a>
```

En la maqueta el logo está representado por un cuadrado morado de 24px con
radio 7px: **ese es el hueco donde entra el SVG real**, con el mismo tamaño
y radio.

---

## 3. Modo oscuro con interruptor

Cambia lo que decía el documento anterior: además de respetar el sistema,
**hay interruptor manual** de tres estados.

- Control: un grupo segmentado pequeño al pie de la barra lateral —
  `Sistema · Claro · Oscuro`. En la pantalla de entrada, arriba a la derecha.
- Se guarda en `localStorage` bajo `superadmin:tema` (`auto|claro|oscuro`).
- Se aplica con `data-tema` en `<html>`; sin valor guardado manda
  `prefers-color-scheme`.
- **Sin destello al cargar**: un script en línea de dos líneas en `<head>`,
  antes del CSS.

```html
<script>
  var t = localStorage.getItem('superadmin:tema');
  if (t && t !== 'auto') document.documentElement.dataset.tema = t;
</script>
```

```css
@media (prefers-color-scheme: dark) {
  :root:not([data-tema="claro"]) { /* fichas oscuras */ }
}
:root[data-tema="oscuro"] { /* las mismas fichas oscuras */ }
```

### Fichas oscuras

```
--tinta #E9E4F7 · --texto #C6C0DC · --tenue #9A93B4 · --apagado #7C7597
--papel #0E0A1B · --caja #171129 · --borde #251C3F · --borde-2 #2F2450
--morado #A78BFA · --morado-fuerte #C4B5FD · --morado-tenue #241a3d
--morado-borde #4C3A80
--bien #4ADE80 · --avisa #FBBF24 · --mal #F87171 · --mal-fondo #2A1518
--mal-borde #5A2226 · --neutro #94A3B8 · --neutro-fondo #1E2536
```

Reglas: los semáforos **suben de luminosidad pero no cambian de tono** —
verde sigue verde, rojo sigue rojo. La vista previa de WhatsApp del editor
del mapa **no se invinvierte**: es una simulación de otra app y conserva sus
colores (`#075E54`, `#ECE5DD`, `#DCF8C6`).

---

## 4. Estructura general

Dos zonas: **barra lateral fija de 232px** + **contenido**.

```
┌─ barra lateral ─┬─ contenido ──────────────────────┐
│ logo Nitro      │  cabecera fija de pantalla       │
│ Clientes    (3) │  ───────────────────────────────  │
│ Dar de alta     │  tarjetas / tabla                │
│                 │                                   │
│ REQUIERE ATENCIÓN                                   │
│ [tarjeta roja]  │                                   │
│                 │  ── barra de guardado fija ──    │
│ /admin ↗        │                                   │
│ tema  v…        │                                   │
└─────────────────┴───────────────────────────────────┘
```

**“Requiere atención”** en la barra lateral es nuevo y es el corazón del
rediseño: cualquier cliente con credenciales rotas o sin cupo aparece ahí
como tarjeta roja que lleva directo a su ficha. Si no hay ninguno, el bloque
no se pinta.

En móvil (`< 900px`): la barra lateral se colapsa en una cabecera con menú
`<details>`; el contenido pasa a una sola columna; la tabla del listado se
convierte en tarjetas apiladas (§5).

---

## 5. Listado de clientes

Cabecera: título, resumen (`2 de 3 activos · N mensajes de IA este mes`),
selector de mes y botón **Dar de alta** en morado sólido.

Tabla en grid `1.6fr .9fr .9fr 1fr auto`:
**Negocio · Estado · IA este mes · Conversación · Acciones**.

- Nombre 14.5px/700; debajo `nombrecorto · id N` en mono 12px `--apagado`.
- **Semáforo de credenciales**: barra vertical de 3px en el borde izquierdo
  de la fila (verde/ámbar/rojo/gris) **más** chip con punto y texto
  (`credenciales ok`, `revisar credenciales`, `credenciales rotas`,
  `sin comprobar`). La fila con credenciales rotas además lleva fondo
  `#FDFBFB` (oscuro: `#1B1220`). Se barre la tabla y se ve en un vistazo.
- Estado `activo` en chip morado tenue; `pausado` en chip neutro.
- Cupo agotado: la cifra de IA en `--mal` y peso 600.
- Acciones: `Pausar`/`Reanudar` y `Abrir`, ambos secundarios. **No existe borrar.**
- Al pie: “Los clientes no se borran: pausar conserva el historial.”

**Estado orientador (no vacío):** con pocos clientes, una banda sobre la
tabla dice qué hacer a continuación (“Todo en orden salvo un cliente…”) con
un botón a la acción. Con cero clientes, la banda ocupa el lugar de la tabla
e invita a dar de alta.

**Móvil:** cada fila es una tarjeta con la barra de semáforo arriba,
nombre + chips, y los datos en dos columnas; los botones a ancho completo.

---

## 6. Ficha del cliente — de once bloques a seis pestañas

El cambio principal. Los once bloques apilados se agrupan por **frecuencia
de uso**:

| Pestaña | Contiene (bloques originales) |
|---|---|
| **Resumen** | banda de fallo · métricas (IA, conversación, plan) · lo que se pega en Meta (2) · identidad (4) |
| **Avisos y áreas** | avisos completo (7) |
| **WhatsApp e IA** | WhatsApp (5) · paquete de IA (6) |
| **Usuarios** | usuarios del panel (3) |
| **Integraciones y marca** | datos públicos (8) · Google (9) · push (10) · marca (11) |
| **Contenido del bot** | `/contenido` |
| **Mapa de conversación** | `/mapa` |

Las pestañas son **enlaces reales** (`/superadmin/clientes/{id}?bloque=avisos`
o `#avisos`), no JS: recargan y se pueden compartir.

**Cabecera fija** con nombre del negocio, chip de estado, chip de semáforo, y
las dos acciones de operación: `Probar credenciales` (secundario) y
`Pausar`/`Reanudar` (morado sólido).

### Guardado — una regla, sin excepciones

**Un formulario por tarjeta, un botón por formulario, junto a lo que guarda.**
Se acaba el formulario gigante.

- Tarjeta corta → botón `Guardar identidad` / `Guardar IA` al pie derecho,
  en morado tenue (`--morado-tenue` sobre texto `--morado-fuerte`).
- Pestaña larga (Avisos, Integraciones, Contenido, Mapa) → **barra fija
  abajo** con el contador de cambios (`2 cambios sin guardar` en `--avisa`) y
  el botón en morado sólido. Se pinta sin cambios como “Sin cambios” en
  `--apagado`, botón activo igual.
- Acciones inmediatas (probar credenciales, cambiar clave, dar de baja,
  aviso de prueba) van **siempre** dentro de su tarjeta y se etiquetan como
  lo que son. En Usuarios se dice explícito: “Acciones inmediatas: no
  dependen del botón de guardar”.

### Credenciales

Los campos de secreto salen **vacíos** con marcador de posición
`Hay uno guardado · vacío = no se toca` y fondo `#FBFAFE` (oscuro `#1C1533`).
Si Meta rechaza, el campo se pinta con borde `--mal-borde`, fondo
`--mal-fondo` y una nota debajo con el motivo real.

La URL de webhook y el token de verificación van en **cajas de solo
lectura** (no `<input>`) con botón `Copiar` y chip `no editable`, más la
frase “Si cambian, el cliente deja de recibir mensajes sin dar error”.

### Avisos y áreas

Primero la tarjeta de cabecera: número del dueño, áreas incluidas en el plan
y un medidor `Usando 3 de 6 áreas`. Después **una tarjeta por área**:
correo · nombre del área · país · WhatsApp en grid `1.3fr 1fr .5fr 1fr`, y
debajo las casillas del menú como chips (activa = borde `--morado-borde`,
fondo `--morado-tenue`).

El área que Meta rechazó lleva **filete rojo de 3px arriba**, chip
`Meta rechazó el aviso` y el motivo literal del error. El área que recibe lo
no asignado lleva chip `recibe todo lo demás`.

Al final, `+ Añadir área (3 de 6 usadas)` con borde discontinuo, y en la
barra fija `Mandar un aviso de prueba` junto a `Guardar avisos`.

---

## 7. Editor de contenido

Dos columnas: **índice fijo de los 9 bloques** (210px, `position: sticky`)
+ contenido. El índice marca el bloque activo con fondo `--morado-tenue` y
muestra el número de campos donde ayuda (`35`). Debajo, `Descargar una copia`.

El bloque de 35 textos no se pinta entero: los 2–3 primeros abiertos y el
resto en un `<details>` (`Ver los 33 textos restantes`).

El menú y los enlaces son filas en grid `auto 1fr 1fr auto` (número mono,
texto, enlace destino en `<select>`, quitar) con `+ Añadir opción` al pie.

Barra fija abajo con la advertencia de validación —“Se valida entero: si una
opción apunta a un enlace que no existe, no se guarda nada”— y
`Guardar contenido`.

---

## 8. Mapa de conversación

Se conserva tal cual funciona; solo se le aplica el lenguaje visual.
Izquierda pasos (`1fr`), derecha vista previa (`340px`, sticky).

El paso abierto lleva borde `--morado-borde`, cabecera `--morado-tenue`,
número en cuadro morado y sombra suave morada; los cerrados son filas de
14px con número gris. La vista previa de WhatsApp mantiene sus colores en
ambos temas.

---

## 9. Alta y entrada

**Alta:** columna de 780px, cuatro tarjetas numeradas (Identidad · WhatsApp ·
Paquete de IA · Acceso al panel) y barra fija con `Crear negocio`. Los
errores vuelven como banda roja arriba **y** borde rojo en el campo culpable.

**Entrada:** fondo `#17102B` en ambos temas, logo arriba, tarjeta blanca de
380px con un solo campo y un botón. Tres estados: normal · clave incorrecta
(banda roja + intentos restantes) · bloqueado por intentos (banda roja con
minutos). Nota al pie: `HTTPS verificado · sin usuario, sin recuperación`.

---

## 10. Lo que no se puede tocar al implementar

1. No existe borrar cliente. Solo pausar.
2. Los semáforos no siguen a la marca ni en claro ni en oscuro.
3. Las credenciales guardadas nunca se pintan; vacío = no se toca, dicho con
   todas las letras junto al campo.
4. Webhook y token de verificación: solo lectura, con botón de copiar.
5. El bloque de avisos va junto: dueño + cupo + áreas en la misma pestaña.
6. Todo funciona en el celular, incluido el listado.
7. Un botón de guardar por formulario, al lado de lo que guarda.
