# Logo del cliente

Deja aquí el logo del negocio con el nombre `logo.png` (también valen
`logo.jpg`, `logo.jpeg` o `logo.webp`) y el icono de la app instalable lo
usará automáticamente.

**Formato recomendado**: PNG cuadrado, de 512×512 o más. Se reduce solo a
cada tamaño que hace falta.

**Si no dejas ninguno**: el icono se dibuja con las iniciales del negocio
(`BUSINESS_NAME` en `app/config.py`) sobre el color de marca
(`MARCA_COLOR`). No hace falta hacer nada para que funcione.

## Los dos tipos de logo se tratan distinto

| Tu logo | Qué se hace |
|---|---|
| **Con fondo transparente** (solo el símbolo recortado) | Se pega centrado sobre el color de marca, al 60 % del lienzo |
| **Sin transparencia** (una imagen que ya trae su fondo) | Se usa a sangre, ocupando el icono entero |

El 60 % del primer caso no es capricho: es el margen que recorta Android
en los iconos redondeados. Dibujado más grande, se le comerían los bordes.

Y el segundo caso existe porque hacer lo mismo quedaría mal: un logo que
ya trae su fondo, pegado al 60 %, se ve como una calcomanía flotando
encima del color de marca.

> Si tu logo lleva texto, comprueba que no llegue muy al borde: Android
> recorta el icono a un círculo y se comería las puntas. Deja el texto
> dentro del 80 % central.

El icono se genera una vez y se guarda en memoria, así que **al cambiar el
logo hay que reiniciar el servicio** para que se vuelva a dibujar.
