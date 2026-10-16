"""la App de Meta pasa a ser de cada cliente

Seis columnas nuevas en `clients`. Es el cimiento del cambio de modelo:
se deja de tener UNA App de Meta —la nuestra— con todos los números de
todos los clientes dentro, y cada negocio pasa a traer la suya.

POR QUÉ SE CAMBIA
-----------------
Con una sola App, conectar el número de un cliente dependía de que Meta
nos aprobara el App Review a NOSOTROS. Eso convertía un trámite ajeno en
el cuello de botella de todas las ventas, y además nos hacía dueños de
números que no son nuestros: si un cliente se iba, su número estaba en
nuestra App.

Con la App del cliente, el negocio sigue siendo dueño de su número y de
su WABA, y nosotros ponemos hosting, base de datos y panel.

LO QUE ESO OBLIGA A GUARDAR
---------------------------
  · `app_id` / `app_secret`   la App del cliente. El secreto va cifrado
                              (app/core/secretos.py), como el token.
  · `verify_token`            el que él escribe en Meta y Meta devuelve
                              en el GET de verificación del webhook.
  · `webhook_token`           el trozo aleatorio de SU URL de webhook.
  · `token_estado`            si su token respondía la última vez.
  · `token_revisado`          cuándo se comprobó.

POR QUÉ UNA URL DE WEBHOOK POR CLIENTE
--------------------------------------
Es la consecuencia menos obvia y la que decide el diseño.

La firma del webhook (`X-Hub-Signature-256`) se valida con el App Secret,
que ahora es de cada cliente. Para saber CON CUÁL validar hay que saber
primero de quién es el POST — y con una URL compartida lo único que lo
dice está DENTRO del cuerpo (`phone_number_id`), que es justo lo que
todavía no se puede dar por auténtico.

Poner el inquilino en la URL invierte ese orden: se sabe de quién es
antes de tocar el cuerpo. Y resuelve además el GET de verificación, que
no trae `phone_number_id` por ningún lado y con una sola URL no tendría
forma de distinguir a un cliente de otro.

`webhook_token` es único e indexado por lo mismo que `phone_number_id`:
se busca por él una vez por cada mensaje que entra.

NADA DE RLS AQUÍ
----------------
`clients` es la tabla que dice quién es quién: no lleva `client_id`, está
excluida de `database.MODELOS_DEL_INQUILINO` a propósito y no tiene
política de RLS (ver `c3f1a7d2b904`). Así que estas columnas no necesitan
ni entrar en el filtro del ORM ni una política nueva. Es el caso fácil de
la regla de las dos cosas.

Bajar es seguro mientras el despliegue siga aceptando `/webhook` sin
token: se pierden las credenciales de las Apps de los clientes, que hay
que volver a pedirles.

Revision ID: d4b8e1067c25
Revises: e5a2c7b81f43
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "d4b8e1067c25"
down_revision = "e5a2c7b81f43"
branch_labels = None
depends_on = None


def upgrade():
    # Todas aceptan NULL: los clientes que ya existen siguen atendiendo
    # por la App vieja mientras se les migra uno a uno. Un cliente sin
    # `webhook_token` simplemente no tiene URL propia todavía.
    op.add_column("clients", sa.Column("app_id", sa.String(), nullable=True))
    op.add_column("clients", sa.Column("app_secret", sa.String(), nullable=True))
    op.add_column("clients", sa.Column("verify_token", sa.String(), nullable=True))
    op.add_column("clients", sa.Column("webhook_token", sa.String(), nullable=True))
    op.add_column("clients", sa.Column("token_estado", sa.String(), nullable=True))
    op.add_column("clients", sa.Column("token_revisado", sa.DateTime(), nullable=True))

    # Único y con índice. El índice no es un extra del UNIQUE: es la
    # búsqueda del camino caliente, una por mensaje entrante.
    #
    # Varias filas con NULL no chocan entre sí ni en PostgreSQL ni en
    # SQLite, así que se puede crear ya con los clientes actuales vacíos.
    op.create_index("ix_clients_webhook_token", "clients", ["webhook_token"],
                    unique=True)

    # ── Su URL a los que ya existen ──────────────────────────────────
    #
    # Se rellena aquí y no "cuando haga falta" porque un cliente sin
    # `webhook_token` no tiene nada que pegar en su App de Meta, y en la
    # ficha del super-admin no sale la caja que se lo da. O sea que
    # dejarlo vacío convierte "migrar a un cliente" en un trabajo de
    # base de datos a mano.
    #
    # Esto NO cambia por dónde atiende nadie: `/webhook` a secas sigue
    # funcionando igual, y cada cliente pasa a su URL propia el día que
    # la pegue en Meta. Es una llave que se entrega, no una cerradura que
    # se cambia.
    import secrets as _aleatorio

    conexion = op.get_bind()
    filas = conexion.execute(sa.text("SELECT id FROM clients")).fetchall()
    for (client_id,) in filas:
        conexion.execute(
            sa.text("UPDATE clients SET webhook_token = :w, verify_token = :v, "
                    "token_estado = 'sin_probar' WHERE id = :id"),
            {"w": _aleatorio.token_urlsafe(24),
             "v": _aleatorio.token_urlsafe(24),
             "id": client_id},
        )


def downgrade():
    op.drop_index("ix_clients_webhook_token", table_name="clients")
    op.drop_column("clients", "token_revisado")
    op.drop_column("clients", "token_estado")
    op.drop_column("clients", "webhook_token")
    op.drop_column("clients", "verify_token")
    op.drop_column("clients", "app_secret")
    op.drop_column("clients", "app_id")
