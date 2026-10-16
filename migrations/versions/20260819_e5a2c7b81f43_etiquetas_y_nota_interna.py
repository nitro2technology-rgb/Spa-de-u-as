"""etiquetas y nota interna

Dos columnas nuevas en `contacts`, las dos SOLO del panel: ni el bot las
lee ni el cliente las ve nunca.

- `etiquetas`: las que se pone el negocio a su manera ("cliente viejo",
  "pidió descuento"), guardadas como una lista JSON.
- `nota_interna`: lo que se deja quien atiende, para sí mismo o para el
  compañero del turno siguiente.

POR QUÉ NO HAY TABLA NUEVA
--------------------------
Lo relacionalmente correcto para unas etiquetas de muchos-a-uno sería una
tabla aparte. Se descartó a sabiendas:

  · Son dos o tres etiquetas por contacto y unos cientos de contactos por
    negocio. No hay nada que optimizar.
  · Una tabla nueva con `client_id` cuesta DOS cosas —entrar en
    `database.MODELOS_DEL_INQUILINO` y su propia política de RLS— y el
    día que a alguien se le olvide la segunda, esa tabla se queda sin
    cerradura y **nadie se entera**: todo sigue funcionando.
  · `contacts` ya está hecha así: `servicio`, `recorrido` y
    `estado_atencion` también viven en su propia columna.

Como van dentro de `contacts`, heredan la política de RLS que esa tabla
ya tiene desde `c3f1a7d2b904`. No hace falta tocar nada más.

Bajar es seguro: se pierden las etiquetas y las notas, que son datos que
no existían antes de esta migración.

Revision ID: e5a2c7b81f43
Revises: c3f1a7d2b904
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "e5a2c7b81f43"
down_revision = "c3f1a7d2b904"
branch_labels = None
depends_on = None


def upgrade():
    # Las dos aceptan NULL: los contactos que ya existen no tienen ni
    # etiquetas ni nota, y "no tiene" se dice con NULL y no con "" ni con
    # "[]" — así hay una sola forma de decirlo.
    op.add_column("contacts", sa.Column("etiquetas", sa.Text(), nullable=True))
    op.add_column("contacts", sa.Column("nota_interna", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("contacts", "nota_interna")
    op.drop_column("contacts", "etiquetas")
