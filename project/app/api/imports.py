"""Импорт реестра помещений из XLSX и журнал импорта — ТЗ 4.1.1.

Загрузка идёт как multipart/form-data, а не JSON: это файл (ТЗ 4.6).
Предел размера берётся из настройки MAX_UPLOAD_BYTES и проверяется до разбора,
чтобы заведомо большой файл не читался в память целиком.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.deps import AppConfig, CurrentUser, DbSession, FundAdmin, page_params
from app.errors import ImportFormatError, NotFound, PayloadTooLarge
from app.models import ImportJob, ImportKind, ImportStatus
from app.schemas import page_envelope
from app.schemas.imports import ImportJobDetail, ImportJobOut
from app.services import imports as service
from app.services.paging import paginate

Pagination = Annotated[tuple[int, int], Depends(page_params)]

router = APIRouter(prefix="/api/v1/imports", tags=["импорт"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: Расширение проверяем отдельно от содержимого: понятный отказ до разбора
ALLOWED_SUFFIXES = (".xlsx", ".xlsm")


def _xlsx_response(payload: bytes, filename: str) -> Response:
    return Response(
        content=payload,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/template.xlsx", summary="Шаблон-образец для загрузки помещений")
def download_template(user: CurrentUser) -> Response:
    return _xlsx_response(service.build_template(), "audfond-rooms-template.xlsx")


@router.post("/rooms", status_code=201, summary="Загрузить реестр помещений из XLSX")
async def import_rooms(
    session: DbSession,
    config: AppConfig,
    user: FundAdmin,
    file: UploadFile = File(..., description="Книга Excel по шаблону-образцу"),
    dry_run: bool = Query(
        default=False,
        description="Сухой прогон: только проверить файл, данные не изменять",
    ),
):
    filename = file.filename or "upload.xlsx"
    if not filename.lower().endswith(ALLOWED_SUFFIXES):
        raise ImportFormatError(
            "Ожидается файл .xlsx",
            details={"filename": filename, "allowed": list(ALLOWED_SUFFIXES)},
        )

    content = await file.read()
    if len(content) > config.max_upload_bytes:
        raise PayloadTooLarge(
            f"Файл больше допустимых {config.max_upload_bytes} байт",
            details={"file_size": len(content), "limit": config.max_upload_bytes},
        )
    if not content:
        raise ImportFormatError("Файл пустой", details={"filename": filename})

    # Разбор и запись файла — долгая синхронная работа. Внутри async-обработчика
    # она остановила бы цикл событий: экземпляр перестал бы отвечать всем,
    # включая healthcheck, и был бы помечен нездоровым. Поэтому — в пуле потоков
    job = await run_in_threadpool(
        service.import_rooms,
        session,
        content=content,
        filename=filename,
        dry_run=dry_run,
        user_id=user.id,
    )
    return ImportJobDetail.model_validate(job)


@router.get("", summary="Журнал загрузок")
def list_jobs(
    session: DbSession,
    user: CurrentUser,
    paging: Pagination,
    kind: ImportKind | None = None,
    status: ImportStatus | None = None,
):
    page, page_size = paging
    rows, total = paginate(session, service.query_jobs(kind, status), page, page_size)
    return page_envelope(
        [ImportJobOut.model_validate(row) for row in rows], total, page, page_size
    )


@router.get("/{job_id}", summary="Загрузка с построчными ошибками")
def get_job(job_id: int, session: DbSession, user: CurrentUser):
    job = session.get(ImportJob, job_id)
    if job is None:
        raise NotFound(f"Загрузка №{job_id} не найдена", details={"import_job_id": job_id})
    return ImportJobDetail.model_validate(job)


@router.get("/{job_id}/errors.xlsx", summary="Отчёт об ошибках загрузки в XLSX")
def download_error_report(job_id: int, session: DbSession, user: CurrentUser) -> Response:
    job = session.get(ImportJob, job_id)
    if job is None:
        raise NotFound(f"Загрузка №{job_id} не найдена", details={"import_job_id": job_id})
    return _xlsx_response(
        service.build_error_report(job), f"audfond-import-{job_id}-errors.xlsx"
    )
