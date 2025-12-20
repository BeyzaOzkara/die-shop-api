"""add operation_type_id to work_order_operation

Revision ID: 87ad32020421
Revises: 368ee1cda693
Create Date: 2025-12-19 16:32:28.952112

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '87ad32020421'
down_revision: Union[str, Sequence[str], None] = '368ee1cda693'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        "work_order_operation",
        sa.Column("operation_type_id", sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        "fk_work_order_operation_operation_type",
        "work_order_operation",
        "operation_type",
        ["operation_type_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_index(
        "ix_work_order_operation_operation_type_id",
        "work_order_operation",
        ["operation_type_id"],
    )

def downgrade():
    op.drop_index("ix_work_order_operation_operation_type_id", table_name="work_order_operation")
    op.drop_constraint("fk_work_order_operation_operation_type", "work_order_operation", type_="foreignkey")
    op.drop_column("work_order_operation", "operation_type_id")
