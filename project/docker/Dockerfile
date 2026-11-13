# Образ приложения AudFond — ЛР4, пункты 1–5.
#
# Многостадийная сборка:
#   builder — ставит зависимости в виртуальное окружение /opt/venv
#   runtime — то, что работает в бою: окружение, код, ничего лишнего
#   test    — runtime плюс инструменты проверок (make verify в контейнерах)
#
# Воспроизводимость (пункт 2):
#   - базовый образ закреплён точной версией, latest запрещён;
#   - зависимости ставятся из requirements.lock, где закреплены ВСЕ пакеты,
#     включая транзитивные, и у каждого — контрольная сумма. С ключом
#     --require-hashes pip откажется ставить пакет, если файл на сервере
#     подменён или версия не та;
#   - в образ не попадает ничего из рабочего каталога сверх нужного (.dockerignore).
#
# Сборка: make build (или docker compose build)
#
# Анализ образа на уязвимости — make image-scan (ЛР5). Базовый образ —
# последний выпуск безопасности ветки 3.12: на выпуске декабря 2024 года в
# пакетах системы накопились уязвимости с уже выпущенными исправлениями.
# Обновлять — правкой этой строки, с проверкой make image-scan.
# Исправления безопасности Debian, вышедшие после сборки базового образа,
# ставятся при сборке (стадия base): официальный образ пересобирается с
# задержкой, а пакет с готовым исправлением не должен попадать в образ

ARG PYTHON_IMAGE=python:3.12.16-slim

# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH
# Обновляются только пакеты, которые уже есть в базовом образе; новые не
# ставятся, списки пакетов в образе не остаются
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
FROM base AS builder
WORKDIR /build
# Отдельный слой под зависимости: пока lock-файл не менялся, слой берётся
# из кэша и правка кода не переустанавливает пакеты.
#
# Загруженные пакеты сохраняются в кэше сборки на машине (--mount=type=cache),
# а не в образе. При обрыве загрузки повторный make up загружает только
# недостающие пакеты. Для нестабильной сети увеличены таймаут и число
# повторов pip (ENV выше). Контрольные суммы проверяются и для пакетов из кэша
COPY requirements.lock .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m venv /opt/venv \
 && pip install --require-hashes --no-deps -r requirements.lock

# ---------------------------------------------------------------------------
FROM base AS runtime

ARG GIT_COMMIT=unknown
LABEL org.opencontainers.image.title="AudFond" \
      org.opencontainers.image.version="0.5.0" \
      org.opencontainers.image.revision="${GIT_COMMIT}"

# Процесс приложения работает не от root (пункт 3, ТЗ 4.5). Номер задан
# явно: по нему проверка в make container-check и права на файлы
RUN groupadd --gid 10001 audfond \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin audfond

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Код принадлежит root и доступен только для чтения: процесс приложения
# не может изменить собственный код, в том числе при компрометации
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini wsgi.py ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
# COPY переносит права файлов без изменений. При закрытых правах в рабочем
# каталоге (600 у файлов, 700 у каталогов, например при umask 077)
# пользователь приложения не может прочитать код, и импорт пакета app
# завершается ошибкой. Поэтому права выставляются явно: чтение — всем,
# запись — только root
RUN chmod -R u=rwX,go=rX /app \
 && chmod 0755 /usr/local/bin/entrypoint.sh

# Коммит в образ записывается как метка и как значение по умолчанию.
# Это не секрет: он и так отдаётся адресом /version
ENV GIT_COMMIT=${GIT_COMMIT}

USER 10001:10001
EXPOSE 8000

# Корректное завершение (пункт 5): docker stop шлёт SIGTERM процессу 1.
# entrypoint заменяет себя на uvicorn через exec, поэтому сигнал получает
# сам сервер: он перестаёт принимать запросы, дожидается текущих и
# закрывает соединения с базой
STOPSIGNAL SIGTERM

# Живость внутри контейнера: без curl, стандартной библиотекой Python
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["serve"]

# ---------------------------------------------------------------------------
# Стадия проверок: тот же образ плюс инструменты разработчика
FROM runtime AS test
USER root

# Клиент PostgreSQL той же основной версии, что и сервер: pg_dump отказывается
# снимать копию с более нового сервера. В репозитории Debian версия старее,
# поэтому клиент берётся из официального репозитория PostgreSQL (PGDG).
# PG_CLIENT_FROM_PGDG=0 — ничего не ставить: клиент уже есть в базовом образе
ARG PG_MAJOR=17
ARG PG_CLIENT_FROM_PGDG=1
RUN if [ "$PG_CLIENT_FROM_PGDG" = "1" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends postgresql-common ca-certificates \
      && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
      && apt-get install -y --no-install-recommends "postgresql-client-${PG_MAJOR}" \
      && rm -rf /var/lib/apt/lists/*; \
    fi \
 && pg_dump --version

COPY requirements-dev.lock ./
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --require-hashes --no-deps -r requirements-dev.lock

COPY tests ./tests
COPY pyproject.toml Makefile ./
# Остальное дерево нужно проверке секретов: она смотрит весь репозиторий
COPY docs ./docs
COPY deploy ./deploy
COPY docker ./docker
COPY docker-compose.yml .dockerignore .env.example .env.docker.example .gitignore \
     CONTRIBUTING.md README.md requirements.txt requirements-dev.txt requirements.lock ./
# Образ проверок в бой не идёт. Дерево отдаётся пользователю проверок:
# линтер, анализатор типов и pytest пишут свои кэши и отчёты рядом с кодом
RUN mkdir -p /app/reports /app/backups && chown -R 10001:10001 /app
USER 10001:10001
# Образ проверок запускается разово и сервер не поднимает: проверка живости
# из runtime (запрос к :8000) здесь бессмысленна и помечала бы контейнер
# нездоровым. Запрет на отключение healthcheck касается долгоживущих служб
HEALTHCHECK NONE
ENTRYPOINT []
CMD ["pytest", "-q"]
