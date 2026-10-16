"""Построчные причины отказа при импорте

Этап 3 (ЛР №3), второе из трёх последовательных изменений схемы.
Основание: ТЗ 4.1.1 — «частичное сохранение корректных строк файла при наличии
ошибок в отдельных строках с подробным фиксированием причин сбоев в журнале
импорта» и выгрузка детализированного отчёта об ошибках.

ON DELETE CASCADE здесь осознанно: построчные ошибки не имеют смысла без своей
записи журнала, это её часть, а не самостоятельные данные.

Revision ID: 0004_import_row_error
Revises: 0003_import_job
Создана: 2026-10-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_import_row_error"
down_revision = "0003_import_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_row_error",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("column_name", sa.String(length=60), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["import_job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("row_number > 0", name="ck_import_row_error_row_number"),
    )
    # Отчёт об ошибках всегда читается по одной загрузке и в порядке строк
    op.create_index(
        "ix_import_row_error_job_row", "import_row_error", ["job_id", "row_number"]
    )


def downgrade() -> None:
    op.drop_index("ix_import_row_error_job_row", table_name="import_row_error")
    op.drop_table("import_row_error")
