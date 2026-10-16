"""cada negocio tiene su fecha de vencimiento, y se pausa solo si no paga

Todo en `clients`, que no lleva `client_id` ni RLS: ninguna tabla nueva.

    vence_el                  hasta cuándo está pagado. NULL = no se le
                              cobra (el bot de casa, o un cliente que aún
                              no tiene fecha puesta).
    precio_mensual            lo pactado con ÉL; NULL = el precio del plan.
    ultimo_pago_el / _monto   el último pago registrado en /superadmin.
    recordatorio_enviado_el   el día del último correo de cobro, para
                              mandar uno al día y no uno por hora.
    pausado_por               "impago" si lo pausó el cobro automático. Solo
                              esos se reactivan solos al registrar el pago:
                              una pausa a mano no la deshace un pago.

Revision ID: c8f1a3e57d20
Revises: b7e4d2a91c05
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "c8f1a3e57d20"
down_revision = "b7e4d2a91c05"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clients", sa.Column("vence_el", sa.Date(), nullable=True))
    op.add_column("clients", sa.Column("precio_mensual", sa.Integer(), nullable=True))
    op.add_column("clients", sa.Column("ultimo_pago_el", sa.Date(), nullable=True))
    op.add_column("clients", sa.Column("ultimo_pago_monto", sa.Integer(), nullable=True))
    op.add_column("clients", sa.Column("recordatorio_enviado_el", sa.Date(),
                                       nullable=True))
    op.add_column("clients", sa.Column("pausado_por", sa.String(), nullable=True))


def downgrade():
    for columna in ("pausado_por", "recordatorio_enviado_el", "ultimo_pago_monto",
                    "ultimo_pago_el", "precio_mensual", "vence_el"):
        op.drop_column("clients", columna)
