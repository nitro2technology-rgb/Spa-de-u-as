"""el panel de barberías: módulos contratados, personal, sedes y actividad

Fase 0 de `Instrucciones SAAS barberia.md`: lo que necesitan la entrada y
los roles. Las tablas de citas, caja, pagos e inventario llegan con sus
pantallas.

En `clients` (sin RLS, como siempre):

    barberia_contratada   el panel de gestión (/b, /yo)
    bot_contratado        el bot de WhatsApp; true para todos los de antes
    proveedor_agenda      "google" o "barberia"
    max_sedes, max_barberos   cupos pactados; NULL = los del plan

Tablas nuevas, todas con `client_id` y con su política de RLS en esta
misma migración — una tabla del inquilino sin política funciona igual y
nadie se entera (ver CLAUDE.md):

    barb_sedes, barb_personal, barb_personal_sede, barb_actividad,
    barb_recuperaciones

Revision ID: e1b5c3a7d902
Revises: c8f1a3e57d20
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e1b5c3a7d902"
down_revision = "c8f1a3e57d20"
branch_labels = None
depends_on = None


TABLAS = ("barb_sedes", "barb_personal", "barb_personal_sede",
          "barb_actividad", "barb_recuperaciones")

# La misma política que `c3f1a7d2b904`, letra por letra. Por qué va con
# COALESCE/NULLIF y no con un OR está explicado allí: un OR no corta en
# SQL y revienta con la cadena vacía de una conexión reutilizada.
POLITICA = "aislar_inquilino"
ANUNCIADO = "current_setting('app.client_id', true)"
CONDICION = ("client_id = COALESCE("
             f"NULLIF({ANUNCIADO}, '')::int, client_id)")


def _cliente():
    """La columna `client_id`, igual que `database.columna_cliente()`."""
    return sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"),
                     nullable=False, server_default="1")


def _cuando(nombre, nullable=True):
    return sa.Column(nombre, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    # ── clients ──────────────────────────────────────────────────────
    op.add_column("clients", sa.Column("barberia_contratada", sa.Boolean(),
                                       nullable=False, server_default=sa.false()))
    op.add_column("clients", sa.Column("bot_contratado", sa.Boolean(),
                                       nullable=False, server_default=sa.true()))
    op.add_column("clients", sa.Column("proveedor_agenda", sa.String(),
                                       nullable=False, server_default="google"))
    op.add_column("clients", sa.Column("max_sedes", sa.Integer(), nullable=True))
    op.add_column("clients", sa.Column("max_barberos", sa.Integer(), nullable=True))

    # ── tablas de la barbería ────────────────────────────────────────
    op.create_table(
        "barb_sedes",
        sa.Column("id", sa.Integer(), primary_key=True),
        _cliente(),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("direccion", sa.Text(), nullable=True),
        sa.Column("telefono", sa.String(20), nullable=True),
        sa.Column("zona_horaria", sa.String(50), nullable=False,
                  server_default="America/Bogota"),
        sa.Column("activo", sa.Boolean(), nullable=False),
        _cuando("created_at"),
    )

    op.create_table(
        "barb_personal",
        sa.Column("id", sa.Integer(), primary_key=True),
        _cliente(),
        sa.Column("panel_user_id", sa.Integer(), sa.ForeignKey("panel_users.id"),
                  nullable=True),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("correo", sa.String(120), nullable=True),
        sa.Column("telefono", sa.String(20), nullable=True),
        sa.Column("rol", sa.String(20), nullable=False),
        sa.Column("esquema_pago", sa.String(20), nullable=False),
        sa.Column("comision_defecto", sa.Numeric(5, 2), nullable=False),
        sa.Column("sueldo_fijo", sa.Numeric(12, 2), nullable=False),
        sa.Column("alquiler_silla", sa.Numeric(12, 2), nullable=False),
        sa.Column("meta_quincena", sa.Numeric(12, 2), nullable=True),
        sa.Column("clave_temporal", sa.Boolean(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        _cuando("eliminado_en"),
        _cuando("created_at"),
        sa.CheckConstraint("rol IN ('DUENO','ADMIN','RECEPCION','BARBERO')",
                           name="ck_barb_personal_rol"),
        sa.CheckConstraint(
            "esquema_pago IN ('COMISION','FIJO_MAS_COMISION','ALQUILER_SILLA')",
            name="ck_barb_personal_esquema"),
    )

    op.create_table(
        "barb_personal_sede",
        sa.Column("id", sa.Integer(), primary_key=True),
        _cliente(),
        sa.Column("personal_id", sa.Integer(), sa.ForeignKey("barb_personal.id"),
                  nullable=False),
        sa.Column("sede_id", sa.Integer(), sa.ForeignKey("barb_sedes.id"),
                  nullable=False),
        sa.UniqueConstraint("personal_id", "sede_id", name="uq_barb_personal_sede"),
    )

    op.create_table(
        "barb_actividad",
        sa.Column("id", sa.Integer(), primary_key=True),
        _cliente(),
        sa.Column("personal_id", sa.Integer(), sa.ForeignKey("barb_personal.id"),
                  nullable=True),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("accion", sa.String(40), nullable=False),
        sa.Column("tabla", sa.String(50), nullable=True),
        sa.Column("registro_id", sa.Integer(), nullable=True),
        sa.Column("sede_id", sa.Integer(), sa.ForeignKey("barb_sedes.id"),
                  nullable=True),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        # sa.JSON con variante JSONB, como `JSONPortable`. Escrito a mano y
        # no con --autogenerate: ver §3.5 de CONTINUAR_AQUI.
        sa.Column("antes", sa.JSON().with_variant(
            postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("despues", sa.JSON().with_variant(
            postgresql.JSONB(), "postgresql"), nullable=True),
        _cuando("created_at"),
    )

    op.create_table(
        "barb_recuperaciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        _cliente(),
        sa.Column("personal_id", sa.Integer(), sa.ForeignKey("barb_personal.id"),
                  nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        _cuando("vence_en", nullable=False),
        _cuando("usado_en"),
        _cuando("created_at"),
    )

    for tabla in TABLAS:
        op.create_index(f"ix_{tabla}_client_id", tabla, ["client_id"])
    op.create_index("ix_barb_actividad_created_at", "barb_actividad", ["created_at"])
    op.create_index("ix_barb_recuperaciones_token_hash", "barb_recuperaciones",
                    ["token_hash"], unique=True)

    # ── la segunda cerradura ─────────────────────────────────────────
    if op.get_bind().dialect.name != "postgresql":
        return

    for tabla in TABLAS:
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {POLITICA} ON {tabla}")
        op.execute(f"""
            CREATE POLICY {POLITICA} ON {tabla}
                USING ({CONDICION})
                WITH CHECK ({CONDICION})
        """)


def downgrade():
    for tabla in reversed(TABLAS):
        op.drop_table(tabla)
    for columna in ("max_barberos", "max_sedes", "proveedor_agenda",
                    "bot_contratado", "barberia_contratada"):
        op.drop_column("clients", columna)
