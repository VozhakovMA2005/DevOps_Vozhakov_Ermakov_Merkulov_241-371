#!/usr/bin/env bash
# Сервер базы данных. Пункты задания 5, 6 и 10.
#
# Что делает:
#   ставит PostgreSQL 17 из официального репозитория PostgreSQL
#   открывает СУБД только на внутреннем адресе стенда
#   разрешает подключения только с сервера приложения и только двум ролям
#   создаёт базу, роль-владельца схемы и роль приложения
#   закрывает порт 5432 для всех, кроме сервера приложения
#
# Запуск (от root, на машине audfond-db):
#   OWNER_PASSWORD='...' APP_PASSWORD='...' bash 02-db-server.sh
#
# Пароли не хранятся в репозитории: задаются при запуске и сохраняются
# только в файле /etc/audfond/db-passwords (права 600, владелец root).

. "$(dirname "$0")/lib.sh"

need_root

PG_VERSION="${PG_VERSION:-17}"
OWNER_PASSWORD="${OWNER_PASSWORD:-}"
APP_PASSWORD="${APP_PASSWORD:-}"

[ -n "$OWNER_PASSWORD" ] || die "Задайте OWNER_PASSWORD (пароль роли миграций)"
[ -n "$APP_PASSWORD" ]   || die "Задайте APP_PASSWORD (пароль роли приложения)"
[ ${#APP_PASSWORD} -ge 12 ] || die "APP_PASSWORD короче 12 символов"

step "Репозиторий PostgreSQL"
export DEBIAN_FRONTEND=noninteractive
if [ ! -f /etc/apt/sources.list.d/pgdg.list ]; then
    install -d -m 755 /usr/share/postgresql-common/pgdg
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list
    apt-get update -qq
fi
ok "репозиторий подключён"

step "Установка PostgreSQL $PG_VERSION"
apt-get install -y -qq "postgresql-$PG_VERSION" >/dev/null
systemctl enable --now postgresql >/dev/null
ok "СУБД установлена и запущена"

PG_CONF="/etc/postgresql/$PG_VERSION/main/postgresql.conf"
PG_HBA="/etc/postgresql/$PG_VERSION/main/pg_hba.conf"
require_file "$PG_CONF" "проверьте версию: PG_VERSION=$PG_VERSION"

step "Сетевая доступность СУБД"
backup_once "$PG_CONF"
# Слушаем только внутренний адрес стенда: наружу СУБД не смотрит вовсе
set_option "$PG_CONF" "listen_addresses" "'localhost,$DB_IP'" " = "
set_option "$PG_CONF" "password_encryption" "scram-sha-256" " = "
ok "СУБД слушает localhost и $DB_IP"

step "Кто и откуда может подключаться"
backup_once "$PG_HBA"
# Убираем прежние строки стенда, чтобы повторный запуск не плодил дубликаты
sed -i '/# AudFond$/d' "$PG_HBA"
cat >> "$PG_HBA" <<HBA
host    audfond    af_owner    $APP_IP/32    scram-sha-256    # AudFond
host    audfond    af_app      $APP_IP/32    scram-sha-256    # AudFond
HBA
ok "подключения к базе audfond — только с $APP_IP и только ролям af_owner и af_app"

step "База и роли"
SQL_DIR="$(cd "$(dirname "$0")/sql" && pwd)"
# Файл передаём на стандартный вход, а не ключом -f. Иначе его читал бы сам
# пользователь postgres, а он не может зайти в домашний каталог администратора:
# права 700 — и psql отвечает «Permission denied».
sudo -u postgres psql -q -v ON_ERROR_STOP=1 \
    -v owner_password="$OWNER_PASSWORD" \
    -v app_password="$APP_PASSWORD" \
    < "$SQL_DIR/roles.sql"
ok "база audfond, роли af_owner и af_app готовы"

step "Пароли"
install -d -m 700 -o root -g root "$CONF_DIR"
cat > "$CONF_DIR/db-passwords" <<PWD
# Пароли ролей базы. Файл читает только root.
# В репозитории этого файла нет и быть не должно.
OWNER_PASSWORD=$OWNER_PASSWORD
APP_PASSWORD=$APP_PASSWORD
PWD
chmod 600 "$CONF_DIR/db-passwords"
ok "записаны в $CONF_DIR/db-passwords, права 600, владелец root"

step "Межсетевой экран"
ufw allow from "$APP_IP" to any port 5432 proto tcp comment 'PostgreSQL только с сервера приложения' >/dev/null
ok "порт 5432 открыт только для $APP_IP"

systemctl restart postgresql
step "Готово"
info "Проверка с этой машины:"
info "    sudo -u postgres psql -c '\\l' | grep audfond"
info "Права на таблицы раздаются после первого наката миграций — это делает deploy.sh"
