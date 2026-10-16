# Многостадийная сборка: в конечный образ не попадают ни компиляторы,
# ни исходники зависимостей. Теги образов закреплены — latest запрещён ТЗ 4.5.
FROM python:3.12.8-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---------------------------------------------------------------------------
FROM base AS builder
WORKDIR /build
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------
FROM base AS runtime

# Процесс приложения не должен работать от root (ТЗ 4.5)
RUN groupadd --gid 10001 audfond \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin audfond

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=audfond:audfond app ./app
COPY --chown=audfond:audfond migrations ./migrations
COPY --chown=audfond:audfond scripts ./scripts
COPY --chown=audfond:audfond alembic.ini wsgi.py ./
COPY --chown=audfond:audfond docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER audfond
EXPOSE 8000

# Проверка живости внутри контейнера: без curl, только стандартной библиотекой
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["serve"]

# ---------------------------------------------------------------------------
# Стадия проверок: тот же образ плюс инструменты разработчика
FROM runtime AS test
USER root
# Клиент PostgreSQL нужен проверкам: обратимость миграций, учения по миграциям
# и по восстановлению работают через psql, pg_dump и pg_restore
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY --chown=audfond:audfond tests ./tests
COPY --chown=audfond:audfond pyproject.toml Makefile ./
# Остальное дерево нужно проверке секретов: она смотрит весь репозиторий,
# а не только код приложения
COPY --chown=audfond:audfond docs ./docs
COPY --chown=audfond:audfond deploy ./deploy
COPY --chown=audfond:audfond .env.example .gitignore CONTRIBUTING.md README.md ./
# Каталоги под отчёты и копии: внутри образа их создаёт root, а работает
# непривилегированный пользователь
RUN mkdir -p /app/reports /app/backups \
 && chown audfond:audfond /app/reports /app/backups
USER audfond
ENTRYPOINT []
CMD ["pytest", "-q"]
