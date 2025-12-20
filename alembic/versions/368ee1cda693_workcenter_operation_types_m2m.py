"""workcenter operation types m2m

Revision ID: 368ee1cda693
Revises: dc8971a80d24
Create Date: 2025-12-19 15:29:55.401098

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect



# revision identifiers, used by Alembic.
revision: str = '368ee1cda693'
down_revision: Union[str, Sequence[str], None] = 'dc8971a80d24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slugify_code(s: str) -> str:
    """
    DB'deki work_center.type gibi serbest text'ten
    operation_type.code üretmek için basit bir normalizasyon.
    Örn: "CNC Torna" -> "CNC_TORNA"
    """
    s = (s or "").strip().upper()
    s = s.replace("İ", "I").replace("Ğ", "G").replace("Ü", "U").replace("Ş", "S").replace("Ö", "O").replace("Ç", "C")
    out = []
    prev_underscore = False
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            prev_underscore = False
        else:
            if not prev_underscore:
                out.append("_")
                prev_underscore = True
    code = "".join(out).strip("_")
    return code or "UNSPEC"


def upgrade():
    bind = op.get_bind()
    insp = inspect(bind)

    # 1) join table
    if "work_center_operation_type" not in insp.get_table_names():
        op.create_table(
            "work_center_operation_type",
            sa.Column("work_center_id", sa.Integer(), sa.ForeignKey("work_center.id"), primary_key=True),
            sa.Column("operation_type_id", sa.Integer(), sa.ForeignKey("operation_type.id"), primary_key=True),
        )

    # 2) distinct type values (work_center.type varsa)
    cols = [c["name"] for c in insp.get_columns("work_center")]
    if "type" in cols:
        rows = bind.execute(sa.text("SELECT DISTINCT type FROM work_center WHERE type IS NOT NULL")).fetchall()

        for (wc_type,) in rows:
            code = _slugify_code(wc_type)
            name = (wc_type or "").strip()

            bind.execute(
                sa.text(
                    """
                    INSERT INTO operation_type (code, name, description, is_active, created_at)
                    VALUES (:code, :name, NULL, TRUE, NOW())
                    ON CONFLICT (code) DO NOTHING
                    """
                ),
                {"code": code, "name": name},
            )

        wcs = bind.execute(sa.text("SELECT id, type FROM work_center WHERE type IS NOT NULL")).fetchall()
        for wc_id, wc_type in wcs:
            code = _slugify_code(wc_type)
            ot = bind.execute(
                sa.text("SELECT id FROM operation_type WHERE code = :code"),
                {"code": code},
            ).fetchone()

            if ot:
                ot_id = ot[0]
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO work_center_operation_type (work_center_id, operation_type_id)
                        VALUES (:wc_id, :ot_id)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {"wc_id": wc_id, "ot_id": ot_id},
                )

        # 3) drop old column
        op.drop_column("work_center", "type")


def downgrade():
    bind = op.get_bind()

    # 1) add back type column (not null -> önce nullable ekleyip doldurup not null yapmak daha güvenli)
    op.add_column("work_center", sa.Column("type", sa.String(), nullable=True))

    # 2) type değerini M2M'den geri doldur
    #    Eğer bir work_center'ın birden fazla operation_type'ı varsa ilkini alacağız (deterministic: min(id))
    rows = bind.execute(
        sa.text(
            """
            SELECT wc.id as work_center_id, ot.name as op_name
            FROM work_center wc
            JOIN work_center_operation_type wcot ON wcot.work_center_id = wc.id
            JOIN operation_type ot ON ot.id = wcot.operation_type_id
            """
        )
    ).fetchall()

    # group first op_name per work_center
    first = {}
    for wc_id, op_name in rows:
        if wc_id not in first:
            first[wc_id] = op_name

    for wc_id, op_name in first.items():
        bind.execute(
            sa.text("UPDATE work_center SET type = :t WHERE id = :id"),
            {"t": op_name, "id": wc_id},
        )

    # type hala NULL kalan varsa "UNSPEC" bas
    bind.execute(sa.text("UPDATE work_center SET type = 'UNSPEC' WHERE type IS NULL"))

    # now enforce NOT NULL
    op.alter_column("work_center", "type", existing_type=sa.String(), nullable=False)

    # 3) drop join table
    op.drop_table("work_center_operation_type")
