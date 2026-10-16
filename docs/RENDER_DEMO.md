# Ver el panel de barberías en la web (demo en Render)

Una **demo aparte**: su propio servicio web y su propia base. No toca el bot
en producción ni su base.

> ⚠️ **No uses "New → Blueprint" con este repositorio.** El `render.yaml` es
> el del bot en producción (`nitro2tech-bot-pro`, `nitro2tech-db`) y un
> Blueprint intentaría crear o tocar recursos con esos nombres. La demo se
> crea a mano, con los pasos de abajo: un Web Service creado a mano no lee
> el `render.yaml`.

## 1. La base de datos

Render → **New → PostgreSQL**

| Campo | Valor |
|---|---|
| Name | `barberias-demo-db` |
| Region | Oregon (la misma del servicio) |
| Plan | **Free** para mirar (se borra a los 30 días) o **Basic-256mb** si la vas a enseñar a clientes |

Cuando esté lista, copia la **Internal Database URL** (para el servicio) y la
**External Database URL** (para sembrar datos desde tu computador, paso 4).

## 2. El servicio web

Render → **New → Web Service** → conecta `nitro2technology-rgb/barberias`.

| Campo | Valor |
|---|---|
| Name | `barberias-demo` |
| Region | Oregon |
| Branch | `fase-2` (la más reciente; `fase-1` si solo quieres la anterior) |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Plan | Free para mirar (se duerme a los 15 min y tarda ~1 min en despertar) o Starter |
| Health Check Path | `/` (en Advanced) |

**Environment variables** (en la misma pantalla):

| Variable | Valor |
|---|---|
| `PYTHON_VERSION` | `3.12.7` |
| `DATABASE_URL` | la **Internal Database URL** del paso 1 |
| `SECRETS_KEY` | genera una con el comando de abajo |
| `SESSION_SECRET` | genera otra con el comando de abajo |
| `SUPERADMIN_KEY` | una clave tuya para entrar a la consola |
| `PANEL_URL` | `https://barberias-demo.onrender.com` (la dirección que te dé Render) |

Para generar `SECRETS_KEY` y `SESSION_SECRET` (en tu computador, dentro de
la carpeta `Codigo`):

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    python -c "import secrets; print(secrets.token_urlsafe(32))"

El correo (SMTP) es opcional: sin él, "Olvidé mi contraseña" no envía nada,
y todo lo demás funciona.

## 3. Desplegar y comprobar

Dale **Create Web Service**. En los **Logs** del despliegue tienen que
aparecer las migraciones, terminando en:

    Running upgrade c8f1a3e57d20 -> e1b5c3a7d902, el panel de barberías…
    Running upgrade e1b5c3a7d902 -> f2c6d4b8e013, el panel de barberías, fase 1…
    Running upgrade f2c6d4b8e013 -> a4d7e9b2c015, el panel de barberías, fase 2: la agenda

Si ves `Cliente inicial creado` **sin** esas líneas encima, el esquema lo
hizo `create_all` y no Alembic: revisa el Start Command (ver §3.8 de
`CONTINUAR_AQUI.md`).

## 4. Llenarla de datos (opcional)

La base nace vacía. Hay dos formas de tener algo que mirar:

**a) Desde la consola, como en la vida real.** Entra a
`https://barberias-demo.onrender.com/superadmin/login` con tu
`SUPERADMIN_KEY` → **Barberías → Nueva barbería**. Te muestra el usuario y la
contraseña temporal del dueño; con ellos entras en `/entrar`.

**b) Con los datos de demostración** (Filo Barbería con tres semanas de
trabajo, y Navaja Club pausada). Desde tu computador, en la carpeta `Codigo`:

    set DATABASE_URL=postgresql://…(la External Database URL)…
    python scripts/demo_barberia.py --si

(En PowerShell: `$env:DATABASE_URL="postgresql://…"`.) Solo corre después
del primer despliegue y una sola vez. Luego entras en
`https://barberias-demo.onrender.com/entrar` con `ricardo` / `filo2026`
(dueño) o `andres.m` / `filo2026` (barbero).

## 5. Actualizarla

Con **Auto-Deploy** encendido, cada `git push` a la rama configurada vuelve
a desplegar solo. Para pasar a otra fase, cambia **Settings → Branch**.

## 6. Probar el bot con la agenda de la barbería (Fase 2)

El bot agenda en la barbería solo si la barbería tiene su WhatsApp conectado
y `proveedor_agenda = "barberia"` (las barberías creadas desde la consola ya
nacen así). Para conectar el número de una barbería se usa la ficha del
negocio en `/superadmin/clientes/{id}` (App de Meta, token, número), igual
que con cualquier cliente del bot, y su URL de webhook en su App de Meta.

El recordatorio de 2 horas antes sale por WhatsApp si el cliente escribió en
las últimas 24 horas. Para los demás hace falta una **plantilla aprobada en
Meta** (variables: nombre, hora, barbero, sede), cuyo nombre se pone en el
contenido del negocio como `barberia.plantilla_recordatorio`. Sin ella, esos
recordatorios no salen y queda anotado en los logs.
