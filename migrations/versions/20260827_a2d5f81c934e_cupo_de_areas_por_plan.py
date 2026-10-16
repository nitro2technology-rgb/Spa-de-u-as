"""el cupo de areas de aviso lo decide el plan, y se puede ajustar

`clients.max_destinos_avisos`.

Cuántas áreas puede tener un negocio recibiendo avisos —Ventas, Soporte,
Contratos— pasa a ser parte de lo que se vende:

    sin IA (Básico)   3 áreas
    con IA (Pro)      6 áreas

Antes era `MAX_DESTINOS_AVISOS = 3`, una constante en el código. El número
lo decide la venta, y una venta no puede depender de un despliegue: si un
cliente negocia una área más, eso tiene que resolverse en `/superadmin` en
diez segundos y no en la siguiente subida a producción.

EN NULL LO DECIDE EL PLAN
-------------------------
Que es lo que quiere el 95% de los casos. La columna es para el caso
suelto, y manda sobre el plan cuando tiene algo — el mismo patrón que
`gemini_modelo` sobre su variable de entorno.

    ⚠️  Y la misma trampa: con la columna puesta, cambiar el plan del
        cliente NO cambia su cupo. Es lo correcto —es lo pactado con ESE
        negocio— pero desde fuera "le subí a Pro y sigue con 3" encaja con
        dos historias distintas. En la ficha se ve cuál manda.

EL CUPO SALE DE `ia_contratada`, NO DE `plan_activo()`
------------------------------------------------------
Los dos suenan igual y significan cosas distintas, y elegir mal aquí
tendría una consecuencia fea: `plan_activo()` es operativo —lo que el
dueño tiene encendido AHORA— así que apagar la IA un rato desde su panel
le borraría áreas de aviso, y al volver a encenderla no reaparecerían
solas porque el editor ya habría guardado la lista recortada.

`ia_contratada` es comercial: lo que compró. Eso es lo que paga el cupo.

Bajar es seguro: se pierde el ajuste suelto de quien lo tuviera, y todos
vuelven al cupo de su plan.

Revision ID: a2d5f81c934e
Revises: f7c3a9e21b48
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "a2d5f81c934e"
down_revision = "f7c3a9e21b48"
branch_labels = None
depends_on = None


def upgrade():
    # NULL = "lo que diga el plan". No se rellena con 3 a los que ya
    # existen: eso les congelaría el cupo actual y dejaría de seguir al
    # plan el día que alguno suba a Pro, sin que nadie lo note.
    op.add_column("clients", sa.Column(
        "max_destinos_avisos", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("clients", "max_destinos_avisos")
