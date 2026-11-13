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
# С чем сравнивается ветка: проверки истории и защиты файлов приёмки (ЛР5)
BASE ?= origin/main
# Образ приложения и реестр для публикации (ЛР5): make push REGISTRY=…
APP_IMAGE := audfond:0.5.0
REGISTRY ?=

DOCKER_READY := $(shell docker info >/dev/null 2>&1 && test -f .env.docker && echo 1 || echo 0)
LOCAL ?= $(if $(filter 1,$(DOCKER_READY)),0,1)

# Образ проверок: в нём закреплённые инструменты из requirements-dev.lock
TESTS_IMAGE := audfond-tests:0.5.0

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
DEPS_CMD := $(RUN) python scripts/deps_check.py
DEPS_PRE := true
else
# --build: проверки идут по ТЕКУЩЕМУ коду. Без него compose берёт уже собранный
# образ проверок, и после правки кода проверялась бы прежняя копия дерева.
# Неизменённые слои берутся из кэша, пересборка без правок — секунды
RUN  := $(COMPOSE) --profile test run --rm --build tests
MODE := в контейнерах (docker compose, .env.docker)
MIGRATE_CMD := $(COMPOSE) run --rm migrate
ADMIN_CMD   := $(COMPOSE) run --rm migrate admin
SEED_CMD    := $(COMPOSE) run --rm migrate python scripts/seed_demo.py
BACKUP_CMD  := bash scripts/container_backup.sh
RESTORE_CMD  = bash scripts/container_restore.sh $(if $(YES),--yes,) FILE=$(FILE)
DRILL_PREFIX := $(RUN)
# Проверке зависимостей нужен pypi.org, а служба tests работает во внутренней
# сети без выхода наружу. Поэтому — отдельный запуск образа проверок в сети по
# умолчанию. Дерево проекта подключается только для чтения: проверяются
# текущие lock-файлы, а не те, что были при сборке образа
DEPS_CMD := docker run --rm --cap-drop ALL --security-opt no-new-privileges:true \
  -v "$(CURDIR):/src:ro" -v "$(CURDIR)/reports:/src/reports" -w /src \
  $(TESTS_IMAGE) python scripts/deps_check.py
DEPS_PRE := docker image inspect $(TESTS_IMAGE) >/dev/null 2>&1 || \
  { echo "Нет образа проверок $(TESTS_IMAGE): сначала make build"; exit 1; }
endif

.PHONY: help mode setup run test test-cov test-report quality types sast secrets \
        waivers coverage-services migrate migrate-check migrate-drill restore-drill \
        migrate-drill-local restore-drill-local mutants seed create-admin \
        backup restore backup-local restore-local verify verify-local verify-docker \
        docker-env build preflight up down logs ps shell container-check persist-drill \
        shutdown-drill failover-drill restore-new-volume lock clean deps-check image-scan secrets-branch guard ci checks-image \
        push publish registry-up registry-down registry-ls \
        test-unit test-int schema-check secrets-scan build-app ci-sync codeowners-check

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

build-app: ## Собрать только образ приложения (стадия build в CI)
	$(COMPOSE) build migrate

checks-image: ## Собрать только образ проверок (первая стадия make ci в контейнерах)
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
	@mkdir -p reports
	set -o pipefail; python3 scripts/container_check.py | tee reports/container-check.txt

# Сканер работает в контейнере и в любом режиме нуждается в Docker. Образ
# передаётся ему файлом, без доступа к docker.sock
image-scan: ## Анализ образа приложения на уязвимости (Trivy): HIGH и CRITICAL с исправлением
	@mkdir -p reports && chmod a+rwx reports
	python3 scripts/image_scan.py

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
schema-check: ## Схема базы совпадает с моделями: накат на одноразовую базу и alembic check
	$(DRILL_PREFIX) bash scripts/migrate_drill.sh --schema-only

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
	$(RUN) pytest -c pyproject.toml

# Стадии test и test-int из ТЗ 7.1 по отдельности. Модульным тестам база не
# нужна, они идут секунды. Интеграционные идут на PostgreSQL и проверяют оба
# порога покрытия: обработчики и сервисный слой покрывают именно они
test-unit: ## Модульные тесты, без базы (отчёт reports/junit-unit.xml)
	@mkdir -p reports && chmod a+rwx reports
	$(RUN) pytest -c pyproject.toml tests/unit --junitxml=reports/junit-unit.xml

test-int: ## Интеграционные тесты на PostgreSQL и пороги покрытия 70% и 80% (отчёты для CI)
	@mkdir -p reports && chmod a+rwx reports
	$(RUN) sh -c "pytest -c pyproject.toml tests/integration \
	  --junitxml=reports/junit-int.xml \
	  --cov=app --cov-config=pyproject.toml --cov-report=term-missing:skip-covered \
	  --cov-report=xml:reports/coverage.xml \
	  --cov-report=html:reports/htmlcov && \
	  coverage json --rcfile=pyproject.toml -q --include='app/services/*' -o reports/coverage-services.json && \
	  coverage report --rcfile=pyproject.toml --include='app/services/*' --skip-covered --fail-under=80"

test-cov: ## Тесты с отчётом о покрытии в консоль
	$(RUN) pytest -c pyproject.toml --cov=app --cov-config=pyproject.toml --cov-report=term-missing

# Оба порога покрытия из ТЗ 7.1 за один прогон: общий 70% (fail_under в
# pyproject.toml) и 80% для сервисного слоя — по тем же данным покрытия
test-report: ## Тесты с отчётами для CI: junit, coverage xml и html, оба порога покрытия
	@mkdir -p reports && chmod a+rwx reports
	$(RUN) sh -c "pytest -c pyproject.toml \
	  --junitxml=reports/junit.xml \
	  --cov=app --cov-config=pyproject.toml --cov-report=term-missing \
	  --cov-report=xml:reports/coverage.xml \
	  --cov-report=html:reports/htmlcov && \
	  coverage json --rcfile=pyproject.toml -q --include='app/services/*' -o reports/coverage-services.json && \
	  coverage report --rcfile=pyproject.toml --include='app/services/*' --skip-covered --fail-under=80"
	@echo "Отчёты: reports/junit.xml, reports/coverage.xml, reports/htmlcov/, reports/coverage-services.json"

# Отчёт линтера пишется первым запуском, итог даёт второй: так отчёт есть и
# тогда, когда проверка падает, — именно тогда он и нужен
quality: ## Линтер и форматирование (отчёт reports/ruff.xml)
	@mkdir -p reports && chmod a+rwx reports
	$(RUN) sh -c "ruff check --config pyproject.toml --output-format=junit --output-file=reports/ruff.xml . ; \
	  ruff check --config pyproject.toml . && ruff format --config pyproject.toml --check ."

types: ## Проверка типов (отчёт reports/mypy.xml)
	@mkdir -p reports && chmod a+rwx reports
	$(RUN) mypy --config-file pyproject.toml app scripts --junit-xml reports/mypy.xml

sast: ## Статический анализ на безопасность (ТЗ 7.1)
	@mkdir -p reports && chmod a+rwx reports
	$(RUN) sh -c "bandit -q -c pyproject.toml -r app scripts \
	  -f json -o reports/bandit.json; bandit -q -c pyproject.toml -r app scripts"

# Поиск идёт по файлам РЕПОЗИТОРИЯ (git ls-files) на машине, в любом режиме.
# В образе проверок лежит копия дерева на момент сборки: новый файл с
# секретом туда не попадёт, пока образ не пересобран, и проверка его не
# увидела бы. Сценарий — только стандартная библиотека, окружение не нужно
secrets: ## Поиск секретов и запрещённых файлов в репозитории (ТЗ 7.2)
	@mkdir -p reports
	python3 scripts/secret_scan.py --report reports/secrets.json

# Коммиты ветки смотрятся на машине, а не в контейнере: нужен git и история,
# а в образ проверок .git не попадает. Сценарий — только стандартная библиотека
secrets-scan: secrets secrets-branch ## Стадия secrets-scan (ТЗ 7.1): дерево и все коммиты ветки

secrets-branch: ## Секреты во ВСЕХ коммитах ветки, включая удалённые позже: [BASE=origin/main]
	@mkdir -p reports
	python3 scripts/secret_scan.py --since $(BASE) --report reports/secrets-branch.json

waivers: ## Запрет исключений без обоснования и снижения порогов (пункт 14)
	$(RUN) python scripts/waiver_check.py

# Защита файлов приёмки. Сценарий берётся в той редакции, что уже лежит в
# BASE, а не в проверяемой ветке, и запускается из временного каталога вне
# дерева с ключом -I: файл, подложенный в ветку (например argparse.py рядом),
# подменить модуль не сможет. Сам Makefile при этом — из ветки, поэтому на
# GitHub та же проверка идёт отдельным workflow guard-main из main
# (.github/workflows/guard-main.yml). Нужен git — идёт на машине
GUARD_PATH := $(shell git rev-parse --show-prefix 2>/dev/null)scripts/acceptance_guard.py

guard: ## Защита файлов приёмки: удалённые тесты, ослабленные проверки [BASE=origin/main]
	@mkdir -p reports
	@if git cat-file -e "$(BASE):$(GUARD_PATH)" 2>/dev/null; then \
	  echo "Сценарий проверки — из $(BASE), а не из этой ветки"; \
	  tmp="$$(mktemp -d)"; \
	  git show "$(BASE):$(GUARD_PATH)" > "$$tmp/acceptance_guard.py"; \
	  python3 -I "$$tmp/acceptance_guard.py" --base "$(BASE)" --project-dir . --report reports/guard.md; \
	  rc=$$?; rm -rf "$$tmp"; exit $$rc; \
	else \
	  echo "В $(BASE) сценария ещё нет: запускается версия из ветки"; \
	  python3 scripts/acceptance_guard.py --base "$(BASE)" --project-dir . --report reports/guard.md; \
	fi

codeowners-check: ## Каждый критический файл закреплён в .github/CODEOWNERS за двумя ответственными
	python3 scripts/codeowners_check.py

ci-sync: ## Стадии .github/workflows/ci.yml и make ci совпадают, порядок ТЗ 7.1 соблюдён
	python3 scripts/ci_sync_check.py

deps-check: ## Зависимости из lock-файлов — на известные уязвимости (нужен pypi.org)
	@mkdir -p reports && chmod a+rwx reports
	@$(DEPS_PRE)
	$(DEPS_CMD)

mutants: ## Мутационная проверка: подменить условия в правилах, тесты должны упасть
	$(RUN) python scripts/mutation_check.py

coverage-services: ## Отдельный порог покрытия для сервисного слоя: 80% (ТЗ 7.1)
	$(RUN) sh -c "pytest -c pyproject.toml -q --cov=app --cov-config=pyproject.toml >/dev/null && \
	  coverage report --rcfile=pyproject.toml --include='app/services/*' --fail-under=80"

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

# Весь конвейер: те же цели, что вызывает сервер CI, в том же порядке.
# Порядок стадий и отметка для публикации — scripts/ci_local.sh
ci: ## Конвейер CI локально: стиль, безопасность, тесты, миграции, копия, сборка, образ
	@MAKE="$(MAKE)" bash scripts/ci_local.sh

# Публикация — только образа, прошедшего make ci для этого же коммита:
# scripts/push_image.sh проверяет отметку reports/ci-passed, чистоту дерева
# и метку коммита в образе. Тег — sha-<SHA коммита>, latest не ставится
push: ## Опубликовать проверенный образ с тегом sha-<коммит>: make push REGISTRY=localhost:5000
	@REGISTRY="$(REGISTRY)" APP_IMAGE="$(APP_IMAGE)" bash scripts/push_image.sh

publish: ## Конвейер целиком и публикация, только если он пройден: make publish REGISTRY=…
	@test -n "$(REGISTRY)" || (echo "Укажите реестр: make publish REGISTRY=localhost:5000" && exit 1)
	@$(MAKE) --no-print-directory ci
	@$(MAKE) --no-print-directory push

registry-up: ## Локальный реестр образов на 127.0.0.1:5000 («локальный docker hub»)
	@bash scripts/registry.sh up

registry-ls: ## Образы и теги в локальном реестре
	@bash scripts/registry.sh ls

registry-down: ## Остановить локальный реестр (образы остаются)
	@bash scripts/registry.sh down

verify-local: ## Полная проверка, явно без контейнеров
	@$(MAKE) --no-print-directory LOCAL=1 verify

verify-docker: ## Полная проверка, явно в контейнерах
	@$(MAKE) --no-print-directory LOCAL=0 verify

clean: ## ОПАСНО: удалить контейнеры И ТОМ С ДАННЫМИ базы
	@read -r -p "Удалить контейнеры и том с данными базы? [да/нет] " a && [ "$$a" = "да" ]
	$(COMPOSE) --profile test down -v --remove-orphans
