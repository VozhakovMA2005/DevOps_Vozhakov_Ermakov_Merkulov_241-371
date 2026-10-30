#!/bin/sh
# Точка входа контейнера приложения.
#
# serve   — запустить веб-сервис (по умолчанию)
# migrate — только накатить миграции и выйти
# admin   — создать первого администратора
# любое другое — выполнить как команду
#
# Миграции при запуске serve: MIGRATE_ON_START=true (по умолчанию). Когда
# экземпляров несколько, каждый накатывал бы их сам, наперегонки. Поэтому в
# docker-compose.yml миграции идут отдельной одноразовой службой migrate, а
# экземплярам приложения выставлено MIGRATE_ON_START=false.

set -eu

# Пока оболочка ждёт базу, процесс 1 — она сама. Процесс 1 без своего
# обработчика игнорирует SIGTERM, и docker stop ждал бы stop_grace_period,
# а потом убивал контейнер. Поэтому сигнал обрабатывается явно. После exec
# обработчик уже не нужен: сигнал получает сам сервер
trap 'echo "Остановка до запуска сервера"; exit 143' TERM INT

wait_for_db() {
    attempt=1
    while [ "$attempt" -le 30 ]; do
        if python -c "
import os, sys
from sqlalchemy import create_engine, text
try:
    create_engine(os.environ['DATABASE_URL']).connect().execute(text('SELECT 1'))
except Exception:
    sys.exit(1)
" 2>/dev/null; then
            return 0
        fi
        echo "Ожидание базы данных, попытка $attempt из 30"
        attempt=$((attempt + 1))
        sleep 1
    done
    echo "База данных недоступна в течение 30 секунд" >&2
    exit 1
}

case "${1:-serve}" in
    serve)
        wait_for_db
        if [ "${MIGRATE_ON_START:-true}" = "true" ]; then
            python -m alembic upgrade head
        fi
        if [ "${SEED_DEMO:-false}" = "true" ]; then
            python scripts/seed_demo.py || true
        fi
        # exec: uvicorn становится процессом 1 и сам получает SIGTERM от
        # docker stop. Без exec сигнал достался бы оболочке, а сервер был бы
        # убит через stop_grace_period сигналом SIGKILL, не закончив запросы.
        # --proxy-headers: адрес клиента берётся из X-Forwarded-For от Nginx
        exec uvicorn wsgi:app \
            --host "${APP_HOST:-0.0.0.0}" \
            --port "${APP_PORT:-8000}" \
            --no-access-log \
            --proxy-headers \
            --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
            --timeout-graceful-shutdown "${GRACEFUL_TIMEOUT:-10}"
        ;;
    migrate)
        wait_for_db
        exec python -m alembic upgrade head
        ;;
    admin)
        wait_for_db
        exec python scripts/create_admin.py
        ;;
    *)
        exec "$@"
        ;;
esac
