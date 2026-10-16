# Imagen para desplegar el bot. Sirve igual en Render, Railway o un VPS
# con Docker — por eso el puerto se lee de la variable PORT: los servicios
# administrados la inyectan ellos, y en un VPS vale el 8000 por defecto.

FROM python:3.12-slim

# No escribir .pyc y no bufferizar la salida: así los print() aparecen en
# los logs del hosting al instante y no minutos después.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Las dependencias van antes que el código: mientras requirements.txt no
# cambie, Docker reutiliza esta capa y el build es mucho más rápido.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Correr como usuario sin privilegios: si alguien logra ejecutar algo
# dentro del contenedor, no lo hace como root.
RUN useradd --create-home --shell /bin/bash bot && chown -R bot:bot /app
USER bot

EXPOSE 8000

# `alembic upgrade head` primero y encadenado con &&, igual que en
# render.yaml: si una migración falla, el servidor NO debe arrancar. Un
# proceso vivo contra un esquema a medias corrompe datos en silencio.
#
# NO AGREGAR --workers. El panel recibe los mensajes al instante porque el
# servidor los reparte desde memoria (app/core/eventos.py), y eso solo
# funciona dentro de un mismo proceso. Ver la nota larga en render.yaml.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
