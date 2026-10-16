# Cutí: especificaciones de uso

> **Este repositorio (`Spa-de-u-as`) ya no es el código de Cutí.** Era una copia del
> software de barberías sacada el 16-oct-2026 para explorar la idea. Cutí se hizo
> como una **marca más del mismo producto**, en el repositorio vivo
> **`nitro2technology-rgb/Bot-whatsapp-pro`**, y desde allí se despliega. **No
> trabajes aquí:** lo que cambies no llega a producción. Conviene archivar este
> repositorio (GitHub → Settings → Archive).

Última actualización: 16-oct-2026. Lo que sigue describe lo que **existe**.

## Qué es

**Cutí** es el software de gestión para **spas de uñas** (agenda, reservas en
línea, caja, pagos a técnicas, gastos, clientas, fidelización y chatbot de
WhatsApp). Es la **misma plataforma** que **Degradé** (barberías): el mismo
código, la misma base de datos y el mismo despliegue. Cambia lo que se ve:
nombre, paleta, tipografía, palabras, iconos y la página de reservas.

| | Degradé | Cutí |
|---|---|---|
| Para | Barberías | Spas de uñas |
| Dirección | `degrade.nitro2tech.com` | `cuti.nitro2tech.com` |
| Sección en el superadmin | Barberías | Spas de uñas |
| Paleta | Violeta y lila sobre noche | Ciruela y rosados pastel |
| Títulos | Unbounded | Fraunces (serif suave) |
| Profesional | barbero | técnica |

## Cómo funciona por dentro

- **La marca es del cliente:** columna `clients.marca` (`"degrade"` | `"cuti"`).
  Todo cliente anterior es Degradé. Una vez dentro, manda la marca del cliente; en
  la entrada y en `/prueba` manda la dirección por la que llegó.
- **Qué cambia por marca** está en `app/barberia/marca.py` (nombre, titular,
  catálogo de servicios, vocabulario) y en el bloque `html[data-marca="cuti"]` de
  `app/web/estaticos/barberia.css` (paleta).
- **Vocabulario:** el panel está escrito con palabras de barbería y se traduce al
  entregarlo (`marca.localizar`: «barbero» → «técnica», «barbería» → «spa», «corte»
  → «servicio»), con la concordancia correcta. Degradé pasa intacto. Vale también
  para correos, avisos del celular y los mensajes del bot de WhatsApp.
- **Correos:** los de un spa llegan firmados por «Cutí».
- **Consola (`/superadmin`):** dos secciones, **Barberías** y **Spas de uñas**. Cada
  una lista y da de alta solo lo suyo; Cobros, Planes y Consumo son de toda la
  plataforma. La marca de un negocio se cambia en su ficha.
- **Prueba gratis de 7 días:** `cuti.nitro2tech.com/prueba` crea un spa (marca
  Cutí, catálogo de uñas).
- **Planes y precios:** los mismos que Degradé (49.500 · 130.000 · 330.000 al mes);
  en Cutí se leen «Técnica individual», «Administrador de spas» y «Spa ilimitado».
  En el plan individual **la dueña es la técnica**: no hay «Usuarios» y al entrar
  elige entre el panel de administrador y «Mi día de técnica».
- **Página de reservas de las clientas:** otro diseño (rosa pastel, media luna en
  vez del poste, frasco de esmalte en vez de tijeras), con tres temas: Pétalo,
  Claro y Ciruela. Los datos son los mismos.
- **Sitio nitro2tech.com:** landing en `/servicios/software/cuti`, repositorio
  `Nitro2Tech`.

## Cómo se dio de alta un spa

1. `/superadmin/unas` → «Nuevo spa de uñas», o la prueba gratis en
   `cuti.nitro2tech.com/prueba`.
2. La dueña recibe un correo de «Cutí» con su usuario y contraseña temporal.
3. Para el chatbot, cada spa trae su propia App de Meta, como cualquier cliente.

## Dominio de Cutí

Variable `CUTI_URL` (`https://cuti.nitro2tech.com`) en Render + el dominio agregado
al servicio (Settings → Custom Domains) + un CNAME en el DNS. Sin ella todo
funciona en la dirección de Degradé.

## El logo

Provisional (una media luna sobre ciruela). Las especificaciones de los archivos
finales están en `instrucciones/LOGO_CUTI.md` de `Bot-whatsapp-pro`.

## Qué falta

- Logo e iconos definitivos.
- Demo en vivo en la landing (la de Degradé es un clon a mano de ~4.800 líneas).
- Funciones propias de un spa: abono para reservar, galería de diseños, foto de
  referencia que sube la clienta.

## Dónde mirar

`Bot-whatsapp-pro` → `instrucciones/CONTINUAR_AQUI.md` (estado y trampas) y
`tests/test_marca.py` (lo que está garantizado: Degradé intacto, Cutí con lo suyo).
