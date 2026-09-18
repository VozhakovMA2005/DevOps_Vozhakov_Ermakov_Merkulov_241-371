# Единый командный интерфейс — ТЗ 7.1.
# В CI выполняются те же команды, что и локально.
#
# Развёртывание поддерживается двумя способами: в контейнерах (up/down) и без
# них (setup/run) — см. deploy/audfond.service.

SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose
RUN_TESTS := $(COMPOSE) --profile test run --rm tests
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help setup run test quality types migrate migrate-check seed create-admin \
        backup restore verify up down logs ps shell container-check clean

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------------- #
# Запуск без контейнеров (systemd-вариант, этап 2)
# --------------------------------------------------------------------------- #

setup: ## Создать виртуальное окружение и поставить зависимости
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt
	@test -f .env || (cp .env.example .env && echo "Создан .env — подставьте свои значения")

run: ## Запустить приложение локально (нужен .env и доступная база)
	set -a && source .env && set +a && \
	$(PY) -m alembic upgrade head && \
	$(VENV)/bin/uvicorn wsgi:app --host $${APP_HOST:-127.0.0.1} --port $${APP_PORT:-8000} --reload

# --------------------------------------------------------------------------- #
# Контейнеры
# --------------------------------------------------------------------------- #

up: ## Поднять приложение и базу в контейнерах
	$(COMPOSE) up --build -d
	@echo "Веб-интерфейс: http://localhost:$${APP_PORT_EXPOSED:-8000}/"

down: ## Остановить контейнеры
	$(COMPOSE) down

logs: ## Смотреть журнал приложения
	$(COMPOSE) logs -f app

ps: ## Состояние служб
	$(COMPOSE) ps

shell: ## Оболочка внутри контейнера приложения
	$(COMPOSE) run --rm app sh

container-check: ## Проверить образ: не root, нет latest, есть healthcheck
	@bash scripts/container_check.sh

# --------------------------------------------------------------------------- #
# Данные
# --------------------------------------------------------------------------- #

migrate: ## Накатить миграции
	$(COMPOSE) run --rm app migrate

migrate-check: ## Проверить обратимость миграций: upgrade, downgrade, upgrade
	$(COMPOSE) run --rm app sh -c "\
	  python -m alembic upgrade head && \
	  python -m alembic downgrade base && \
	  python -m alembic upgrade head && \
	  python -m alembic check"

create-admin: ## Создать первого администратора (логин и пароль из .env)
	$(COMPOSE) run --rm app admin

seed: ## Загрузить демонстрационные данные
	$(COMPOSE) run --rm app python scripts/seed_demo.py

backup: ## Резервная копия базы в backups/
	@mkdir -p backups
	$(COMPOSE) exec -T db pg_dump -U $${POSTGRES_USER:-audfond} -Fc $${POSTGRES_DB:-audfond} \
	  > backups/audfond-$$(date +%Y%m%d-%H%M%S).dump
	@ls -1t backups | head -1 | sed 's/^/Создана копия: backups\//'

restore: ## Восстановить базу из копии: make restore FILE=backups/....dump
	@test -n "$(FILE)" || (echo "Укажите файл: make restore FILE=backups/....dump" && exit 1)
	$(COMPOSE) exec -T db pg_restore -U $${POSTGRES_USER:-audfond} \
	  -d $${POSTGRES_DB:-audfond} --clean --if-exists < $(FILE)
	@echo "База восстановлена из $(FILE)"

# --------------------------------------------------------------------------- #
# Проверки
# --------------------------------------------------------------------------- #

test: ## Прогнать тесты в контейнере
	$(RUN_TESTS)

test-cov: ## Тесты с отчётом о покрытии
	$(RUN_TESTS) pytest --cov=app --cov-report=term-missing

quality: ## Линтер и форматирование
	$(RUN_TESTS) sh -c "ruff check . && ruff format --check ."

types: ## Проверка типов
	$(RUN_TESTS) mypy app

verify: quality types migrate-check test ## Полная проверка перед запросом на слияние
	@echo "Все проверки пройдены"

clean: ## Убрать контейнеры и данные базы
	$(COMPOSE) down -v --remove-orphans
