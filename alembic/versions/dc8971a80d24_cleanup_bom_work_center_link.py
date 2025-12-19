"""cleanup bom work_center link

Revision ID: dc8971a80d24
Revises: 19fc91dd1a7a
Create Date: 2025-12-18 15:06:11.023243

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc8971a80d24'
down_revision: Union[str, Sequence[str], None] = '19fc91dd1a7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 0) preferred_work_center_id yoksa ekle
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name='component_bom'
              AND column_name='preferred_work_center_id'
        ) THEN
            ALTER TABLE component_bom ADD COLUMN preferred_work_center_id integer;
        END IF;
    END$$;
    """)

    # 1) FK (preferred_work_center_id -> work_center.id) yoksa ekle
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'component_bom_preferred_work_center_id_fkey'
        ) THEN
            ALTER TABLE component_bom
            ADD CONSTRAINT component_bom_preferred_work_center_id_fkey
            FOREIGN KEY (preferred_work_center_id)
            REFERENCES work_center (id);
        END IF;
    END$$;
    """)

    # 2) Eski work_center_id varsa preferred_work_center_id'ye taşı
    op.execute("""
        UPDATE component_bom
        SET preferred_work_center_id = work_center_id
        WHERE preferred_work_center_id IS NULL
          AND work_center_id IS NOT NULL
    """)

    # 3) work_center_id FK constraint adını bul ve drop et
    op.execute("""
    DO $$
    DECLARE
        fk_name text;
    BEGIN
        SELECT conname INTO fk_name
        FROM pg_constraint
        WHERE conrelid = 'component_bom'::regclass
          AND contype = 'f'
          AND pg_get_constraintdef(oid) LIKE '%(work_center_id)%';

        IF fk_name IS NOT NULL THEN
            EXECUTE format('ALTER TABLE component_bom DROP CONSTRAINT %I', fk_name);
        END IF;
    END$$;
    """)

    # 4) work_center_id kolonu varsa drop et
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name='component_bom' AND column_name='work_center_id'
        ) THEN
            ALTER TABLE component_bom DROP COLUMN work_center_id;
        END IF;
    END$$;
    """)


def downgrade():
    # 1) work_center_id'yi geri ekle
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name='component_bom' AND column_name='work_center_id'
        ) THEN
            ALTER TABLE component_bom ADD COLUMN work_center_id integer;
        END IF;
    END$$;
    """)

    # 2) preferred -> legacy'ye kopyala
    op.execute("""
        UPDATE component_bom
        SET work_center_id = preferred_work_center_id
        WHERE work_center_id IS NULL
          AND preferred_work_center_id IS NOT NULL
    """)

    # 3) work_center_id FK ekle (adı sabit)
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'component_bom_work_center_id_fkey'
        ) THEN
            ALTER TABLE component_bom
            ADD CONSTRAINT component_bom_work_center_id_fkey
            FOREIGN KEY (work_center_id)
            REFERENCES work_center (id);
        END IF;
    END$$;
    """)

    # 4) preferred FK'yi kaldır, sonra kolonu kaldır
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname='component_bom_preferred_work_center_id_fkey'
        ) THEN
            ALTER TABLE component_bom DROP CONSTRAINT component_bom_preferred_work_center_id_fkey;
        END IF;
    END$$;
    """)

    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name='component_bom' AND column_name='preferred_work_center_id'
        ) THEN
            ALTER TABLE component_bom DROP COLUMN preferred_work_center_id;
        END IF;
    END$$;
    """)
    # 1) work_center_id kolonu geri ekle (yoksa)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name='component_bom' AND column_name='work_center_id'
            ) THEN
                ALTER TABLE component_bom ADD COLUMN work_center_id integer;
            END IF;
        END$$;
    """)

    # 2) preferred -> legacy'ye kopyala
    op.execute("""
        UPDATE component_bom
        SET work_center_id = preferred_work_center_id
        WHERE work_center_id IS NULL
          AND preferred_work_center_id IS NOT NULL
    """)

    # 3) FK'yi yeniden ekle (çakışmasın diye IF NOT EXISTS yok, ama isim sabit veriyoruz)
    # Eğer aynı isimle başka constraint varsa hata verir; o durumda adı değiştiririz.
    op.create_foreign_key(
        "component_bom_work_center_id_fkey",
        "component_bom",
        "work_center",
        ["work_center_id"],
        ["id"],
    )