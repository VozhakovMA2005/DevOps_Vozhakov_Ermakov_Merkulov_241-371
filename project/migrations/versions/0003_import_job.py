"""Журнал импорта: одна запись на одну загрузку файла

Этап 3 (ЛР №3), первое из трёх последовательных изменений схемы.
Основание: ТЗ 4.1.1 — массовый импорт из XLSX с фиксированием результата.

Таблица заводится отдельным шагом, до таблицы построчных ошибок: ошибки
ссылаются на запись журнала, значит журнал должен существовать раньше.

Revision ID: 0003_import_job
Revises: 0002_seed_reference
Создана: 2026-10-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_import_job"
down_revision = "0002_seed_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_job",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("ROOMS", "STUDENTS", name="import_kind"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "DRY_RUN",
                "APPLIED",
                "PARTIAL",
                "FAILED",
                name="import_status",
            ),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False),
        sa.Column("rows_created", sa.Integer(), nullable=False),
        sa.Column("rows_updated", sa.Integer(), nullable=False),
        sa.Column("rows_failed", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["app_user.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("file_size >= 0", name="ck_import_job_file_size"),
        sa.CheckConstraint("rows_total >= 0", name="ck_import_job_rows_total"),
        sa.CheckConstraint("rows_failed >= 0", name="ck_import_job_rows_failed"),
    )
    # Журнал читают «последние загрузки сверху». Отдельный DESC не нужен:
    # btree в PostgreSQL сканируется в обе стороны.
    op.create_index("ix_import_job_created_at", "import_job", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_import_job_created_at", table_name="import_job")
    op.drop_table("import_job")
    # Перечисления PostgreSQL живут отдельно от таблиц: без этого повторный
    # накат упадёт с «type already exists», а ТЗ 4.6 требует полного отката
    sa.Enum(name="import_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="import_kind").drop(op.get_bind(), checkfirst=True)
