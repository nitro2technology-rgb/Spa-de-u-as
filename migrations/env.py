"""
ENTORNO DE ALEMBIC
==================
Le dice a Alembic dos cosas: a qué base apuntar y cuál es el esquema que
debería tener.

Las dos salen de la aplicación, no de alembic.ini:

  - La URL, de `app.core.database.DATABASE_URL`, que ya pasó por
    `_normalizar_url()`. Esa función arregla las dos formas en que los
    servicios de hosting entregan mal la URL de Postgres
    ("postgres://" y "postgresql://" a secas). Si Alembic leyera
    DATABASE_URL por su cuenta, se saltaría ese arreglo y fallaría al
    conectarse justo donde la app funciona.

  - El esquema, de `Base.metadata`. Los modelos de SQLAlchemy son la
    única fuente de verdad: `--autogenerate` compara la base real contra
    ellos.
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# La raíz del proyecto, para poder importar `app`. Alembic se ejecuta
# desde la raíz, pero al correrlo desde otro sitio (o desde un cron) el
# import fallaría sin esto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Base, DATABASE_URL  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata


def _opciones_comunes():
    """
    Lo que necesitan por igual el modo online y el offline.

    `render_as_batch` solo se activa en SQLite y es lo que permite que las
    migraciones corran también ahí: SQLite no sabe hacer ALTER TABLE para
    cambiar una restricción o una clave primaria, así que Alembic recrea
    la tabla, copia los datos y la renombra. Sin esto, cualquier migración
    que toque una restricción funcionaría en producción (PostgreSQL) y
    reventaría en local.
    """
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        "render_as_batch": DATABASE_URL.startswith("sqlite"),
    }


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse, para revisarlo antes de aplicarlo."""
    context.configure(
        url=DATABASE_URL,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_opciones_comunes(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Se conecta y aplica lo que falte. Es lo que corre al desplegar."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, **_opciones_comunes())

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
