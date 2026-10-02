#!/usr/bin/env bash
# Выкладка и обновление приложения. Пункт задания 12: один скрипт повторяет
# основные шаги развёртывания.
#
# Что делает:
#   переносит код из рабочей копии в каталог приложения
#   обновляет зависимости в виртуальном окружении
#   накатывает миграции ПОД РОЛЬЮ ВЛАДЕЛЬЦА СХЕМЫ, не под ролью приложения
#   раздаёт права роли приложения на новые таблицы
#   перезапускает службу и ждёт, пока она ответит
#
# Запуск (на машине audfond-app, от администратора):
#   sudo bash deploy.sh                       код берётся из текущего каталога
#   sudo SOURCE=/home/deployer/audfond bash deploy.sh
#
# Пароль роли-владельца берётся из /etc/audfond/db-passwords, если файл
# скопирован с сервера базы, либо из переменной OWNER_PASSWORD.

. "$(dirname "$0")/lib.sh"

need_root
HERE="$(cd "$(dirname "$0")" && pwd)"
SOURCE="${SOURCE:-$(cd "$HERE/.." && pwd)}"

require_file "$SOURCE/requirements.txt" "SOURCE должен указывать на корень проекта"
require_file "$CONF_DIR/audfond.env" "сначала выполните 03-app-server.sh"

step "Проверка настроек"
if grep -q "СГЕНЕРИРУЙТЕ_СВОЙ_КЛЮЧ\|ПАРОЛЬ_ПРИЛОЖЕНИЯ" "$CONF_DIR/audfond.env"; then
    die "В $CONF_DIR/audfond.env остались значения из образца. Впишите свои."
fi
ok "настройки заполнены"

step "Код в $APP_DIR"
# Переносится только то, что нужно для работы. Тесты, docker и служебное
# на сервер не едут: меньше файлов — меньше поверхность.
rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
    --exclude '.env' --exclude 'tests' --exclude 'docker' \
    --exclude '.pytest_cache' --exclude '.ruff_cache' --exclude '.mypy_cache' \
    "$SOURCE/app" "$SOURCE/migrations" "$SOURCE/scripts" \
    "$SOURCE/alembic.ini" "$SOURCE/wsgi.py" \
    "$SOURCE/requirements.txt" \
    "$APP_DIR/"
chown -R "$ADMIN_USER:$APP_USER" "$APP_DIR/app" "$APP_DIR/migrations" "$APP_DIR/scripts"
chown "$ADMIN_USER:$APP_USER" "$APP_DIR/alembic.ini" "$APP_DIR/wsgi.py" "$APP_DIR/requirements.txt"

# Права задаются явно, а не "уберём лишнее от того, что пришло".
# Владелец (deployer) читает и пишет, группа (audfond, от неё работает
# служба) только читает, остальные не видят ничего.
#   X в g=rX — право «войти в каталог» выдаётся каталогам, но не файлам.
# Почему это важно: если у каталога app есть x, но нет r, служебный
# пользователь может войти в каталог, но не может получить его список.
# Python в таком случае находит пакет app (это проверка существования
# файла), но не находит ни одного вложенного модуля, и падает с
# "No module named 'app.main'" — ошибка выглядит как пропавший файл,
# хотя файл на месте.
chmod -R u=rwX,g=rX,o= "$APP_DIR/app" "$APP_DIR/migrations" "$APP_DIR/scripts"
chmod u=rw,g=r,o= "$APP_DIR/alembic.ini" "$APP_DIR/wsgi.py" "$APP_DIR/requirements.txt"
require_file "$APP_DIR/wsgi.py" "перенос кода не состоялся"
require_file "$APP_DIR/app/main.py" "перенос кода не состоялся: нет app/main.py"
ok "код выложен"

step "Виртуальное окружение"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/.venv"
    ok "окружение создано"
fi
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
chown -R "$ADMIN_USER:$APP_USER" "$APP_DIR/.venv"
chmod -R u=rwX,g=rX,o= "$APP_DIR/.venv"
ok "зависимости установлены по закреплённым версиям"

step "Версия"
COMMIT="$(git -C "$SOURCE" rev-parse --short HEAD 2>/dev/null || echo unknown)"
set_option "$CONF_DIR/audfond.env" "GIT_COMMIT" "$COMMIT" "="
ok "развёртывается коммит $COMMIT"

step "Миграции"
# Схему меняет только роль-владелец. У роли приложения прав на DDL нет —
# в этом и смысл разделения.
if [ -z "${OWNER_PASSWORD:-}" ] && [ -f "$CONF_DIR/db-passwords" ]; then
    # shellcheck disable=SC1090
    . "$CONF_DIR/db-passwords"
fi
[ -n "${OWNER_PASSWORD:-}" ] || die "Нет пароля роли af_owner: задайте OWNER_PASSWORD"

DB_URL_APP="$(grep -E '^DATABASE_URL=' "$CONF_DIR/audfond.env" | cut -d= -f2-)"
DB_HOSTPORT="$(printf '%s' "$DB_URL_APP" | sed -E 's|.*@([^/]+)/.*|\1|')"
OWNER_URL="postgresql+psycopg://af_owner:${OWNER_PASSWORD}@${DB_HOSTPORT}/audfond"

( cd "$APP_DIR" && DATABASE_URL="$OWNER_URL" "$APP_DIR/.venv/bin/python" -m alembic upgrade head )
ok "схема накатана до последней ревизии"

step "Права роли приложения"
# После каждой миграции новые таблицы принадлежат владельцу. Права
# приложению выдаются здесь, а не руками — иначе забудется.
if command -v psql >/dev/null 2>&1; then
    PGPASSWORD="$OWNER_PASSWORD" psql -q -v ON_ERROR_STOP=1 \
        "postgresql://af_owner@${DB_HOSTPORT}/audfond" -f "$HERE/sql/grants.sql"
    ok "права выданы"
else
    warn "psql не установлен на сервере приложения"
    info "выполните на сервере базы: sudo -u postgres psql -d audfond -f grants.sql"
fi

step "Проверка доступа служебного пользователя"
# Служба работает не от root, а от пользователя audfond. Проверяем до
# перезапуска, что этот пользователь действительно видит код: иначе
# systemd вернёт невнятный traceback вместо понятной причины.
if ! sudo -u "$APP_USER" test -r "$APP_DIR/app/main.py"; then
    die "$APP_USER не может прочитать $APP_DIR/app/main.py — проверьте права"
fi
if ! ( cd "$APP_DIR" && sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -c "import app.main" ); then
    ls -ld "$APP_DIR" "$APP_DIR/app"
    die "$APP_USER не может импортировать app.main — вывод прав выше"
fi
ok "$APP_USER читает код и импортирует приложение"

step "Перезапуск службы"
systemctl restart audfond
sleep 2
systemctl is-active --quiet audfond || {
    journalctl -u audfond -n 30 --no-pager
    die "Служба не запустилась — журнал выше"
}
ok "служба работает"

step "Проверка готовности"
for _ in $(seq 1 15); do
    if curl -fsS "http://127.0.0.1:8000/readyz" >/dev/null 2>&1; then
        READY="$(curl -fsS http://127.0.0.1:8000/readyz)"
        ok "приложение отвечает: $READY"
        VERSION="$(curl -fsS http://127.0.0.1:8000/version)"
        info "версия: $VERSION"
        exit 0
    fi
    sleep 1
done
journalctl -u audfond -n 30 --no-pager
die "Приложение не ответило на /readyz за 15 секунд"
