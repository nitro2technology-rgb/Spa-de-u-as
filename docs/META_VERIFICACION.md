# La verificación de negocio ante Meta

## Qué es, por qué la necesitas y qué hacer el día que llegue tu registro de Cámara de Comercio

*Documento preparado el 19 de agosto de 2026 para Nitro 2Tech.*

---

## 1. De qué se trata

Meta no deja que cualquiera use WhatsApp para vender. Antes de darte los
permisos serios te pide **demostrar que existes como empresa**: que hay
una sociedad registrada, con un nombre legal, una dirección y alguien
responsable detrás.

Eso es la **verificación de negocio** (Business Verification). No es un
formulario que se aprueba solo: una persona de Meta mira tus documentos y
decide. Puede tardar días o semanas, y puede rechazarlos.

**No es lo mismo que:**

- **Verificar tu número de WhatsApp.** Eso es el SMS de seis dígitos y ya
  lo hiciste.
- **La aprobación del nombre para mostrar.** Es otro trámite, sobre el
  nombre que ve el cliente en el chat.
- **El "check" verde de Instagram o Facebook.** Ese es otro producto.

---

## 2. Por qué te bloquea

Tu bot ya está listo y en producción. La consola de administración deja
dar de alta un cliente, cobrarle, armarle su conversación y atenderlo. Lo
único que no se puede hacer todavía es **conectar el WhatsApp de ese
cliente**, y eso necesita un permiso de Meta llamado *Advanced Access*.

La cadena es esta, y cada paso empieza cuando acaba el anterior:

1. **Registro en Cámara de Comercio** — lo tuyo, en trámite.
2. **Verificación de negocio en Meta** — Meta revisa tus papeles.
3. **App Review (Advanced Access)** — Meta revisa tu aplicación.
4. **Conectar la WhatsApp de un cliente** — aquí empiezas a cobrar.

Por eso conviene empezar el paso 2 **el mismo día** que tengas el
certificado: lo que viene después también son esperas ajenas.

---

## 3. Qué necesitas tener a mano

### Los documentos

En Colombia, lo que Meta suele aceptar para una sociedad recién
registrada:

- **Certificado de existencia y representación legal**, expedido por la
  Cámara de Comercio de Medellín. Es el documento principal. **Que sea
  reciente**: normalmente no aceptan uno de más de 90 días.
- **RUT** (el de la DIAN, con tu NIT). Sirve como documento tributario.
- **Un comprobante de dirección** a nombre de la empresa, si te lo piden:
  extracto bancario o una factura de servicios públicos recientes.

> **Lo que más rechazos causa no es el documento: es que no coincida.**
> El nombre legal y la dirección que escribas en Meta tienen que ser
> **idénticos** a los del certificado, incluida la forma jurídica
> (`S.A.S.`, `LTDA`). Si el certificado dice "NITRO 2TECH S.A.S." y en
> Meta pusiste "Nitro 2Tech", eso solo puede acabar en rechazo.

### Los datos

- **Nombre legal** exacto, como en el certificado.
- **Dirección** completa, como en el certificado.
- **Teléfono de la empresa.** Meta puede llamar o mandar un SMS a ese
  número para comprobarlo, así que tiene que ser uno al que contestes.
- **Sitio web.** Ayuda mucho que el dominio sea de la empresa y que en el
  sitio aparezcan el nombre, el teléfono y el correo. Si el correo es del
  dominio (`algo@tudominio.com`) mejor todavía.

---

## 4. Los pasos, en orden

### Paso 1 — Prepara el Business Manager antes de enviar nada

Entra a tu **Meta Business Suite / Business Manager** y revisa la
información del negocio. Corrige el nombre legal, la dirección, el
teléfono y el sitio web **antes** de iniciar la verificación. Cambiar
esto después de enviar los papeles complica el trámite.

### Paso 2 — Inicia la verificación

En la configuración del negocio, busca el **Centro de seguridad**
(*Security Center*). Ahí aparece el estado de la verificación y el botón
para empezarla.

> Meta cambia de sitio los menús cada pocos meses. Si no lo encuentras
> ahí, busca "verificación del negocio" en el buscador de la
> configuración. El nombre del trámite no cambia aunque cambie el menú.

### Paso 3 — Sube los documentos y espera

Sube el certificado y el RUT. Consejos que ahorran una ronda de rechazo:

- El documento **completo**, con todas sus páginas.
- **Sin editar, sin recortar y sin marcas de agua** que tapen nada.
- Legible: si es una foto, que se lea todo.
- En PDF si puedes.

Después toca esperar. Meta te avisa por correo y en el propio Centro de
seguridad.

### Paso 4 — Si te rechazan, no empieces de cero

Un rechazo casi siempre es por un dato que no coincide o un documento
poco legible. Meta suele decir cuál. Corriges y vuelves a enviar: se
puede apelar y reenviar varias veces.

### Paso 5 — Con la empresa verificada, pide el App Review

Ya verificado, se solicita el **Advanced Access** para los permisos de
WhatsApp Business. Ten preparado:

- Una **descripción clara del caso de uso**, y una por cada permiso que
  pidas: `whatsapp_business_messaging` y `whatsapp_business_management`.
  Los dos textos están escritos y listos para pegar.
- Un **video corto** mostrando el flujo real. Te lo piden casi siempre, y
  tiene que enseñar el permiso EN USO —un mensaje entrando y una respuesta
  saliendo—, no un recorrido por el producto.
- **Las tres URLs públicas** que pide el panel de la App. El bot las
  publica todas, y cada negocio sirve las suyas con su nombre:

  | Campo en Meta | URL |
  |---|---|
  | Privacy Policy URL | `/privacidad` |
  | Terms of Service URL | `/terminos` |
  | User data deletion | `/eliminar-datos` |

> El checklist completo del App Review —con el estado auditado contra la
> API, los textos del caso de uso y el guión del video— se preparó el
> 20-ago-2026 y vive fuera de este repositorio, como página web.

---

## 5. Lo que puedes ir haciendo hoy

Sin esperar al certificado:

- **Revisar el nombre y la dirección en Business Manager** para que
  coincidan con lo que va a decir el certificado.
- **Comprobar que el teléfono de la empresa contesta.**
- **Dejar el sitio web coherente**: nombre de la empresa, teléfono y
  correo visibles.
- **Preparar el texto del caso de uso** para el App Review. Escribirlo con
  calma ahora es mejor que improvisarlo el día que toque.

---

## 6. Dos fechas que te afectan

- **1 de octubre de 2026** — Meta empieza a cobrar los mensajes de
  servicio, que hoy son gratis dentro de la ventana de 24 horas. Ese costo
  es del cliente, no tuyo. El bot ya se puso a dieta para esto: manda
  **un** mensaje por cada cosa que hace el cliente, ni uno de más.
- **15 de octubre de 2026** — se descontinúa Embedded Signup v2, la forma
  automática de conectar la WhatsApp de un cliente. Si algún día se
  automatiza, hay que construir sobre **v4**. Mientras tanto se conecta a
  mano, que funciona igual.

---

> Este documento tiene su versión en PDF, que es la que conviene leer el
> día del trámite. Si se edita el texto de aquí, el PDF se rehace con:
>
>     python scripts/pdf_de_documento.py

---

## 7. Una advertencia honesta

Los menús, los nombres de los botones y la lista exacta de documentos que
acepta Meta **cambian con frecuencia**, y este documento se escribió el 19
de agosto de 2026. Lo que no cambia es el fondo:

**Meta quiere comprobar que la empresa existe, que se llama como dices y
que estás autorizado a representarla.** Cualquier diferencia entre lo que
escribes y lo que dicen tus papeles es una razón para rechazarte.

Si algo del trámite no coincide con lo que lees aquí, hazle caso a lo que
diga la pantalla de Meta y comprueba la lista de documentos aceptados en
su centro de ayuda antes de enviar.
