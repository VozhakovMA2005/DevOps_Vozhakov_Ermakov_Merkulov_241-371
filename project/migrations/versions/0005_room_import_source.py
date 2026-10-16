"""Происхождение помещения: какой загрузкой оно заведено

Этап 3 (ЛР №3), третье из трёх последовательных изменений схемы.
Основание: ТЗ 4.1.1 и 4.2 — результат импорта должен быть прослеживаемым.

Это изменение специально сделано отдельным шагом и специально меняет таблицу,
в которой к моменту наката УЖЕ ЕСТЬ ДАННЫЕ. Пункт 9 задания требует проверить
обновление не только чистой базы, но и заполненной: столбец добавляется
nullable, без значения по умолчанию и без перезаписи существующих строк,
поэтому накат не блокирует таблицу надолго и не теряет данные. У помещений,
заведённых вручную до этого изменения, значение остаётся NULL — и это
правильный ответ на вопрос «каким импортом заведено», а не ноль и не заглушка.

ON DELETE SET NULL: удаление записи журнала не должно уносить за собой
помещения. Обратное было бы потерей данных аудиторного фонда из-за чистки
служебного журнала.

Revision ID: 0005_room_import_source
Revises: 0004_import_row_error
Создана: 2026-10-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_room_import_source"
down_revision = "0004_import_row_error"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("room", sa.Column("import_job_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_room_import_job_id",
        "room",
        "import_job",
        ["import_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Запрос «что приехало этой загрузкой» идёт по этому столбцу
    op.create_index("ix_room_import_job_id", "room", ["import_job_id"])


def downgrade() -> None:
    op.drop_index("ix_room_import_job_id", table_name="room")
    op.drop_constraint("fk_room_import_job_id", "room", type_="foreignkey")
    op.drop_column("room", "import_job_id")
