# Единый командный интерфейс — ТЗ 7.1.
# В CI выполняются те же команды, что и локально.
#
# Контур проверок один, а запускать его можно двумя способами:
#   без контейнеров — в локальном окружении .venv (стенд этапа 2)
#   в контейнерах   — в образе tests (этап 4)
#
# Способ выбирается сам: если докер не установлен или не запущен, команды идут
# в локальном окружении. Принудительно:
#   make LOCAL=1 verify    без контейнеров
#   make LOCAL=0 verify    в контейнерах
#
# Развёртывание тоже поддерживается двумя способами: в контейнерах (up/down) и
# без них (setup/run) — см. deploy/audfond.service.

SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose
VENV := .venv
PY := $(VENV)/bin/python

DOCKER_READY := $(shell docker info >/dev/null 2>&1 && echo 1 || echo 0)
LOCAL ?= $(if $(filter 1,$(DOCKER_READY)),0,1)

ifeq ($(LOCAL),1)
RUN  := bash scripts/run.sh
MODE := без контейнеров, окружение $(VENV)
MIGRATE_CMD := $(RUN) python -m alembic upgrade head
ADMIN_CMD   := $(RUN) python scripts/create_admin.py
SEED_CMD    := $(RUN) python scripts/seed_demo.py
BACKUP_CMD  := bash scripts/backup.sh
RESTORE_CMD  = bash scripts/restore.sh $(if $(YES),--yes,) FILE=$(FILE)
# Учения тоже идут через run.sh: он читает .env, где лежит адрес роли учений
DRILL_PREFIX := $(RUN)
else
RUN  := $(COMPOSE) --profile test run --rm tests
MODE := в контейнерах
MIGRATE_CMD := $(COMPOSE) run --rm app migrate
ADMIN_CMD   := $(COMPOSE) run --rm app admin
SEED_CMD    := $(COMPOSE) run --rm app python scripts/seed_demo.py
BACKUP_CMD  := @mkdir -p backups && $(COMPOSE) exec -T db pg_dump \
                 -U $${POSTGRES_USER:-audfond} -Fc $${POSTGRES_DB:-audfond} \
                 > backups/audfond-$$(date +%Y%m%d-%H%M%S).dump
RESTORE_CMD  = $(COMPOSE) exec -T db pg_restore -U $${POSTGRES_USER:-audfond} \
                 -d $${POSTGRES_DB:-audfond} --clean --if-exists < $(FILE)
DRILL_PREFIX := $(RUN)
endif

.PHONY: help mode setup run test test-cov test-report quality types sast secrets \
        waivers coverage-services migrate migrate-check migrate-drill restore-drill \
        migrate-drill-local restore-drill-local mutants seed create-admin \
        backup restore backup-local restore-local verify verify-local verify-docker \
        up down logs ps shell container-check clean

help: ## Показать список команд
	@printf '\nСпособ запуска проверок: \033[33m%s\033[0m\n' "$(MODE)"
	@printf 'Переключить: make LOCAL=1 … (без контейнеров) или make LOCAL=0 … (в контейнерах)\n\n'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

mode: ## Показать, каким способом пойдут проверки
	@echo "$(MODE)"

# --------------------------------------------------------------------------- #
# Настройка и запуск без контейнеров (systemd-вариант, этап 2)
# --------------------------------------------------------------------------- #

setup: ## Первоначальная настройка проекта одной командой
	bash scripts/setup.sh

run: ## Запустить приложение локально (нужен .env и доступная база)
	$(RUN) sh -c 'python -m alembic upgrade head && \
	  uvicorn wsgi:app --host $${APP_HOST:-127.0.0.1} --port $${APP_PORT:-8000} --reload'

# --------------------------------------------------------------------------- #
# Контейнеры (этап 4)
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
	$(MIGRATE_CMD)

# Обратимость проверяется на ОДНОРАЗОВОЙ базе, а не на той, что в настройках:
# downgrade base снёс бы все данные. Поэтому make verify безопасно запускать на
# стенде с боевыми данными.
migrate-check: ## Обратимость миграций на одноразовой базе: upgrade, downgrade, upgrade
	$(DRILL_PREFIX) bash scripts/migrate_drill.sh --clean-only

create-admin: ## Создать первого администратора (логин и пароль из .env)
	$(ADMIN_CMD)

seed: ## Загрузить демонстрационные данные (пароль учёток — SEED_PASSWORD)
	$(SEED_CMD)

backup: ## Резервная копия базы в backups/
	$(BACKUP_CMD)

restore: ## Восстановить базу из копии: make restore FILE=backups/....dump [YES=1]
	@test -n "$(FILE)" || (echo "Укажите файл: make restore FILE=backups/....dump" && exit 1)
	$(RESTORE_CMD)

backup-local: ## Резервная копия без контейнеров, явной командой
	bash scripts/backup.sh

restore-local: ## Восстановление без контейнеров: make restore-local FILE=…​ [YES=1]
	bash scripts/restore.sh $(if $(YES),--yes,) FILE=$(FILE)

# --------------------------------------------------------------------------- #
# Проверки
# --------------------------------------------------------------------------- #

test: ## Прогнать тесты
	$(RUN) pytest

test-cov: ## Тесты с отчётом о покрытии в консоль
	$(RUN) pytest --cov=app --cov-report=term-missing

test-report: ## Тесты с отчётами для CI: junit, coverage xml и html
	@mkdir -p reports
	$(RUN) pytest \
	  --junitxml=reports/junit.xml \
	  --cov=app --cov-report=term-missing \
	  --cov-report=xml:reports/coverage.xml \
	  --cov-report=html:reports/htmlcov
	@echo "Отчёты: reports/junit.xml, reports/coverage.xml, reports/htmlcov/index.html"

quality: ## Линтер и форматирование
	$(RUN) sh -c "ruff check . && ruff format --check ."

types: ## Проверка типов
	$(RUN) mypy app scripts

sast: ## Статический анализ на безопасность (ТЗ 7.1)
	@mkdir -p reports
	$(RUN) sh -c "bandit -q -c pyproject.toml -r app scripts \
	  -f json -o reports/bandit.json; bandit -q -c pyproject.toml -r app scripts"

secrets: ## Поиск секретов и запрещённых файлов в репозитории (ТЗ 7.2)
	$(RUN) python scripts/secret_scan.py

waivers: ## Запрет исключений без обоснования и снижения порогов (пункт 14)
	$(RUN) python scripts/waiver_check.py

mutants: ## Мутационная проверка: подменить условия в правилах, тесты должны упасть
	$(RUN) python scripts/mutation_check.py

coverage-services: ## Отдельный порог покрытия для сервисного слоя: 80% (ТЗ 7.1)
	$(RUN) sh -c "pytest -q --cov=app >/dev/null && \
	  coverage report --include='app/services/*' --fail-under=80"

migrate-drill: ## Учения по миграциям: чистая база и база с данными (пункт 9)
	$(DRILL_PREFIX) bash scripts/migrate_drill.sh

restore-drill: ## Учения по восстановлению: копия, порча, восстановление (пункт 12)
	$(DRILL_PREFIX) bash scripts/restore_drill.sh

migrate-drill-local: ## Те же учения по миграциям, явно без контейнеров
	bash scripts/migrate_drill.sh

restore-drill-local: ## Те же учения по восстановлению, явно без контейнеров
	bash scripts/restore_drill.sh

verify: quality types sast secrets waivers migrate-check test ## Полная проверка перед запросом на слияние
	@printf '\n\033[32mВсе проверки пройдены\033[0m (%s)\n' "$(MODE)"

verify-local: ## Полная проверка, явно без контейнеров
	@$(MAKE) --no-print-directory LOCAL=1 verify

verify-docker: ## Полная проверка, явно в контейнерах
	@$(MAKE) --no-print-directory LOCAL=0 verify

clean: ## Убрать контейнеры и данные базы
	$(COMPOSE) down -v --remove-orphans
