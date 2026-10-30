# Единый командный интерфейс — ТЗ 7.1.
# В CI выполняются те же команды, что и локально.
#
# Команды работают двумя способами:
#   без контейнеров — локальное окружение .venv и стенд ЛР2 (этапы 2–3)
#   в контейнерах   — docker compose, ЛР4
#
# Способ выбирается сам: контейнеры — если Docker запущен И создан файл
# настроек контейнеров .env.docker (make docker-env). Иначе — без них.
# Принудительно:
#   make LOCAL=1 verify    без контейнеров
#   make LOCAL=0 verify    в контейнерах

SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose --env-file .env.docker
VENV := .venv
PY := $(VENV)/bin/python
GIT_COMMIT ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
export GIT_COMMIT
# Без служебных аттестаций сборки (provenance): с ними каждая сборка даёт
# новый идентификатор образа даже без единого изменения, и make up зря
# пересоздаёт контейнеры приложения. Без них тот же вход даёт тот же образ
export BUILDX_NO_DEFAULT_ATTESTATIONS := 1

DOCKER_READY := $(shell docker info >/dev/null 2>&1 && test -f .env.docker && echo 1 || echo 0)
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
MODE := в контейнерах (docker compose, .env.docker)
MIGRATE_CMD := $(COMPOSE) run --rm migrate
ADMIN_CMD   := $(COMPOSE) run --rm migrate admin
SEED_CMD    := $(COMPOSE) run --rm migrate python scripts/seed_demo.py
BACKUP_CMD  := bash scripts/container_backup.sh
RESTORE_CMD  = bash scripts/container_restore.sh $(if $(YES),--yes,) FILE=$(FILE)
DRILL_PREFIX := $(RUN)
endif

.PHONY: help mode setup run test test-cov test-report quality types sast secrets \
        waivers coverage-services migrate migrate-check migrate-drill restore-drill \
        migrate-drill-local restore-drill-local mutants seed create-admin \
        backup restore backup-local restore-local verify verify-local verify-docker \
        docker-env build preflight up down logs ps shell container-check persist-drill \
        shutdown-drill failover-drill restore-new-volume lock clean

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

run: ## Запустить приложение локально, без контейнеров (нужен .env и база)
	bash scripts/run.sh sh -c 'python -m alembic upgrade head && \
	  uvicorn wsgi:app --host $${APP_HOST:-127.0.0.1} --port $${APP_PORT:-8000} --reload'

# --------------------------------------------------------------------------- #
# Контейнеры (ЛР4)
# --------------------------------------------------------------------------- #

docker-env: ## Создать .env.docker со случайными паролями (один раз)
	python3 scripts/docker_env.py

build: ## Собрать образы приложения и проверок
	$(COMPOSE) build migrate
	$(COMPOSE) --profile test build tests

# Изменение окружения — только после успешной проверки (пункт 14): сначала
# сборка, затем make container-check по файлам и образу, и лишь потом запуск.
# Если проверка упала, работающие контейнеры не трогаются
preflight: ## Проверить машину до запуска: Docker, образы, права, порт, диск
	@bash scripts/preflight.sh

up: preflight ## Проверить машину, собрать, проверить (container-check) и запустить
	@# Настройки Nginx подключаются в контейнер файлами, и читает их
	@# пользователь 101. Закрытые права (600) ломают запуск Nginx
	@chmod a+r docker/nginx/default.conf docker/nginx/proxy.inc
	$(COMPOSE) build migrate
	python3 scripts/container_check.py --no-runtime
	$(COMPOSE) up -d --wait
	@# Настройки Nginx подключены файлами: после их правки контейнер не
	@# пересоздаётся, поэтому конфигурацию надо проверить и перечитать
	$(COMPOSE) exec -T nginx nginx -t -q && $(COMPOSE) exec -T nginx nginx -s reload
	@echo "Сервис: http://<адрес машины>:$${HTTP_PORT:-8080}/ — на стенде http://192.168.56.10:8080/ (только через Nginx)"

down: ## Остановить и удалить контейнеры (том с данными остаётся)
	$(COMPOSE) down

logs: ## Журнал приложения и Nginx
	$(COMPOSE) logs -f --tail 50 app1 app2 nginx

ps: ## Состояние служб и их здоровье
	$(COMPOSE) ps -a

shell: ## Оболочка внутри контейнера приложения
	$(COMPOSE) exec app1 sh

container-check: ## Проверка окружения: latest, root, секреты, healthcheck, порты, лимиты
	python3 scripts/container_check.py

persist-drill: ## Учения: данные переживают пересоздание контейнеров и новый образ
	bash scripts/container_drill.sh persist

shutdown-drill: ## Учения: корректное завершение по SIGTERM
	bash scripts/container_drill.sh shutdown

failover-drill: ## Учения: балансировка, отказ узла, повтор, ограничение частоты
	bash scripts/container_drill.sh failover

restore-new-volume: ## Восстановить базу в НОВЫЙ том: make restore-new-volume FILE=…
	@test -n "$(FILE)" || (echo "Укажите файл: make restore-new-volume FILE=\$$(ls -t backups/*.dump | head -1)" && exit 1)
	bash scripts/container_drill.sh new-volume FILE=$(FILE)

lock: ## Пересобрать requirements.lock с контрольными суммами (нужен pip-tools)
	$(VENV)/bin/pip-compile -q --generate-hashes --strip-extras --no-emit-index-url \
	  --output-file requirements.lock requirements.txt
	$(VENV)/bin/pip-compile -q --generate-hashes --strip-extras --no-emit-index-url \
	  --output-file requirements-dev.lock requirements-dev.txt

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
	@mkdir -p reports && chmod a+rwx reports
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
	@mkdir -p reports && chmod a+rwx reports
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

clean: ## ОПАСНО: удалить контейнеры И ТОМ С ДАННЫМИ базы
	@read -r -p "Удалить контейнеры и том с данными базы? [да/нет] " a && [ "$$a" = "да" ]
	$(COMPOSE) --profile test down -v --remove-orphans
