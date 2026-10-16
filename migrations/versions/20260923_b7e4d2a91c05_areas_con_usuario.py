"""cada área del negocio tiene su usuario, y solo ve sus conversaciones

Tres columnas, ninguna tabla nueva —así que no hacen falta políticas de
RLS: las tres tablas ya tienen la suya—.

    panel_users.area_id        el área por la que entra ese usuario. NULL
                               es el dueño: lo ve todo.
    contacts.area              el área a la que el dueño REASIGNÓ esa
                               conversación. NULL = la que diga la opción
                               del menú que eligió el cliente.
    push_subscriptions.user_id quién tiene ese dispositivo, para que el
                               aviso al celular de un cliente de Ventas no
                               le suene a Soporte. NULL = de antes de esto:
                               se trata como del dueño.

El área en sí (nombre, correo, de qué opciones del menú se encarga) sigue
en `negocio_config.avisos.destinos`, con un `id` estable. Ver
`app/core/equipo.py`.

Bajar es seguro: se pierden las asignaciones y todos vuelven a verlo todo.

Revision ID: b7e4d2a91c05
Revises: a2d5f81c934e
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "b7e4d2a91c05"
down_revision = "a2d5f81c934e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("panel_users", sa.Column("area_id", sa.String(), nullable=True))
    op.add_column("contacts", sa.Column("area", sa.String(), nullable=True))
    op.add_column("push_subscriptions",
                  sa.Column("user_id", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("push_subscriptions", "user_id")
    op.drop_column("contacts", "area")
    op.drop_column("panel_users", "area_id")
