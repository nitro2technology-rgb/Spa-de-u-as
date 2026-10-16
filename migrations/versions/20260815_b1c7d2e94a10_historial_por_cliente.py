"""historial por cliente

Añade `clients.historial_dias`: cuántos días de conversación se le guardan
a cada negocio.

Era una variable de entorno del proceso (`HISTORIAL_DIAS`), o sea el mismo
plazo para todos los inquilinos. No puede serlo: son datos de terceros y
cada negocio tiene su criterio — uno necesita un año de historial y otro
quiere que no quede nada pasados 30 días.

Queda **nullable a propósito**. NULL significa "la política de la
plataforma", que sigue siendo `config.HISTORIAL_DIAS`, así que los clientes
que ya existen no cambian de comportamiento y el valor por defecto se puede
mover sin tocar ninguna fila. Ver `database.limpiar_mensajes_antiguos`.

Revision ID: b1c7d2e94a10
Revises: accfaea915eb
Create Date: 2026-08-15 16:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b1c7d2e94a10'
down_revision: Union[str, None] = 'accfaea915eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients',
                  sa.Column('historial_dias', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('clients', 'historial_dias')
