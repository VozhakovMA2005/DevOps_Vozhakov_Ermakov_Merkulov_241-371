#!/bin/sh
# Точка входа контейнера.
#
# serve   — накатить миграции и запустить веб-сервис (по умолчанию)
# migrate — только миграции
# admin   — создать первого администратора
# любое другое — выполнить как команду

set -eu

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
        echo "Жду базу данных… попытка $attempt"
        attempt=$((attempt + 1))
        sleep 1
    done
    echo "База данных не поднялась за 30 секунд" >&2
    exit 1
}

case "${1:-serve}" in
    serve)
        wait_for_db
        python -m alembic upgrade head
        if [ "${SEED_DEMO:-false}" = "true" ]; then
            python scripts/seed_demo.py || true
        fi
        # exec: uvicorn становится процессом 1 и сам получает SIGTERM (ТЗ 4.5)
        exec uvicorn wsgi:app \
            --host "${APP_HOST:-0.0.0.0}" \
            --port "${APP_PORT:-8000}" \
            --no-access-log \
            --timeout-graceful-shutdown 10
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
