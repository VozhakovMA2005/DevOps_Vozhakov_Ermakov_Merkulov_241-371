"""Журнал импорта данных из XLSX — ТЗ 4.1.1.

Две таблицы, и разделены они не случайно.

``import_job`` — одна запись на одну загрузку файла: кто загрузил, когда, что
получилось. Запись заводится ДО разбора файла, поэтому в журнале остаются и
неудачные попытки, а не только успешные.

``import_row_error`` — построчные причины отказа. ТЗ требует «частичное
сохранение корректных строк файла при наличии ошибок в отдельных строках с
подробным фиксированием причин сбоев в журнале импорта». Значит отказ по одной
строке не должен отменять остальные, а причина отказа должна быть видна по
каждой строке отдельно — одним текстовым полем в ``import_job`` это не
выразить.

Журнал не переписывается: исправление ошибки — это новая загрузка.
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.user import AppUser


class ImportKind(enum.StrEnum):
    """Что именно загружают. Список расширяется, значения не переиспользуются."""

    ROOMS = "ROOMS"  # реестр помещений
    STUDENTS = "STUDENTS"  # списки обучающихся, этап 5


class ImportStatus(enum.StrEnum):
    """Итог загрузки.

    PENDING остаётся только у записи, разбор которой прервался аварийно, —
    по нему и видно, что процесс упал, а не «тихо ничего не сделал».
    """

    PENDING = "PENDING"  # запись заведена, разбор ещё идёт
    DRY_RUN = "DRY_RUN"  # сухой прогон: проверено, в базу ничего не внесено
    APPLIED = "APPLIED"  # все строки приняты
    PARTIAL = "PARTIAL"  # часть строк принята, часть отклонена
    FAILED = "FAILED"  # не принято ни одной строки


#: Итоги, при которых данные в базу внесены. Используется и в сервисе, и в API
APPLIED_STATUSES = frozenset({ImportStatus.APPLIED, ImportStatus.PARTIAL})


class ImportJob(TimestampMixin, Base):
    __tablename__ = "import_job"
    __table_args__ = (
        CheckConstraint("file_size >= 0", name="ck_import_job_file_size"),
        CheckConstraint("rows_total >= 0", name="ck_import_job_rows_total"),
        CheckConstraint("rows_failed >= 0", name="ck_import_job_rows_failed"),
        Index("ix_import_job_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[ImportKind] = mapped_column(
        Enum(ImportKind, name="import_kind", native_enum=True), nullable=False
    )
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status", native_enum=True),
        nullable=False,
        default=ImportStatus.PENDING,
    )
    #: Имя файла как его назвал пользователь. Сам файл не храним: он не нужен
    #: после разбора, а хранение чужих файлов — отдельная ответственность
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Сухой прогон (ТЗ 4.1.1: «предварительная валидация в режиме сухого
    #: прогона без изменения данных в БД»)
    dry_run: Mapped[bool] = mapped_column(nullable=False, default=False)

    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Кто загрузил. Запись остаётся, даже если пользователя потом заблокируют
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT")
    )
    #: Причина отказа по файлу целиком: не тот формат, нет обязательных колонок
    message: Mapped[str | None] = mapped_column(String(500))

    created_by: Mapped[AppUser | None] = relationship(lazy="joined")
    errors: Mapped[list[ImportRowError]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ImportRowError.row_number",
    )

    def __repr__(self) -> str:  # pragma: no cover — текст для отладки, в тестах не проверяется
        return f"<ImportJob {self.id} {self.kind} {self.status}>"


class ImportRowError(Base):
    """Одна отклонённая строка файла.

    Без TimestampMixin: время загрузки одно для всех строк и уже записано в
    ``import_job``, дублировать его по каждой строке незачем.
    """

    __tablename__ = "import_row_error"
    __table_args__ = (
        CheckConstraint("row_number > 0", name="ck_import_row_error_row_number"),
        Index("ix_import_row_error_job_row", "job_id", "row_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("import_job.id", ondelete="CASCADE"), nullable=False
    )
    #: Номер строки в файле, как его видит пользователь в Excel (с заголовком)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Заголовок колонки, если ошибка относится к конкретному полю
    column_name: Mapped[str | None] = mapped_column(String(60))
    #: Код правила или проверки: EMPTY, NOT_A_NUMBER, RULE_D5, UNKNOWN_BUILDING…
    error_code: Mapped[str] = mapped_column(String(40), nullable=False)
    #: Текст для человека, по-русски (ТЗ 4.5)
    message: Mapped[str] = mapped_column(String(300), nullable=False)
    #: Значение, на котором споткнулись. Обрезается: в файле может быть что угодно
    value: Mapped[str | None] = mapped_column(String(200))

    job: Mapped[ImportJob] = relationship(back_populates="errors")

    def __repr__(self) -> str:  # pragma: no cover — текст для отладки, в тестах не проверяется
        return f"<ImportRowError строка {self.row_number} {self.error_code}>"
