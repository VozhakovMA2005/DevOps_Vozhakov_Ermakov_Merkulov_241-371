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
# Первый запуск (от root, на машине audfond-db):
#   OWNER_PASSWORD='...' APP_PASSWORD='...' bash 02-db-server.sh
#
# Повторный запуск — без паролей: они берутся из файла паролей.
#   bash 02-db-server.sh
#
# Пароли не хранятся в репозитории: задаются при первом запуске и сохраняются
# только в файле /etc/audfond/db-passwords (права 600, владелец root).
#
# Смена пароля — осознанное действие, а не побочный эффект повторного запуска:
# пароль роли приложения записан ещё и в настройках службы на другой машине, и
# молча поменять его здесь значит уронить работающее приложение. Поэтому
# расхождение с записанным паролем останавливает сценарий, а сменить пароль
# можно только явно: ROTATE_PASSWORDS=1.

. "$(dirname "$0")/lib.sh"

need_root

PG_VERSION="${PG_VERSION:-17}"
OWNER_PASSWORD="${OWNER_PASSWORD:-}"
APP_PASSWORD="${APP_PASSWORD:-}"
PASSWORDS_FILE="$CONF_DIR/db-passwords"

stored_password() {
    [ -f "$PASSWORDS_FILE" ] || return 0
    grep "^$1=" "$PASSWORDS_FILE" | cut -d= -f2- || true
}

STORED_OWNER="$(stored_password OWNER_PASSWORD)"
STORED_APP="$(stored_password APP_PASSWORD)"

# Повторный запуск: не заданный пароль берётся из файла
[ -n "$OWNER_PASSWORD" ] || OWNER_PASSWORD="$STORED_OWNER"
[ -n "$APP_PASSWORD" ]   || APP_PASSWORD="$STORED_APP"

[ -n "$OWNER_PASSWORD" ] || die "Задайте OWNER_PASSWORD (пароль роли миграций)"
[ -n "$APP_PASSWORD" ]   || die "Задайте APP_PASSWORD (пароль роли приложения)"
[ ${#APP_PASSWORD} -ge 12 ] || die "APP_PASSWORD короче 12 символов.
    Сгенерировать подходящий:  head -c 18 /dev/urandom | base64 | tr -d '/+=' | cut -c1-20
    Новый пароль af_app затем вписывается в DATABASE_URL в /etc/audfond/audfond.env
    на сервере приложения — иначе служба не войдёт в базу."

# Заглушки из инструкций паролями не являются. Их легко вставить как есть,
# и тогда пароль роли окажется опубликованным в документации
for value in "$OWNER_PASSWORD" "$APP_PASSWORD"; do
    case "$value" in
        *ваш-*|*ваш_*|*CHANGE_ME*|*ПАРОЛЬ*|*пароль-миграций*|*пароль-приложения*)
            if [ "$value" = "$STORED_OWNER" ] || [ "$value" = "$STORED_APP" ]; then
                die "В $PASSWORDS_FILE записана заглушка из инструкции: «$value».
    Значит, роли в базе сейчас с этим паролем. Задайте настоящие пароли явно:
        sudo env ROTATE_PASSWORDS=1 OWNER_PASSWORD='…' APP_PASSWORD='…' bash 02-db-server.sh
    и впишите новый APP_PASSWORD в DATABASE_URL в /etc/audfond/audfond.env на
    сервере приложения (между «af_app:» и «@»)."
            fi
            die "Похоже на заглушку из инструкции: «$value».
    Подставьте настоящий пароль. Повторный запуск можно делать вообще без
    паролей — они возьмутся из $PASSWORDS_FILE" ;;
    esac
done

# Смена пароля роли приложения ломает работающую службу на другой машине:
# там в настройках записан прежний пароль. Поэтому только явно
if [ "${ROTATE_PASSWORDS:-0}" != "1" ]; then
    if [ -n "$STORED_APP" ] && [ "$APP_PASSWORD" != "$STORED_APP" ]; then
        die "APP_PASSWORD отличается от записанного в $PASSWORDS_FILE.
    Если продолжить, у роли af_app сменится пароль, и служба на сервере
    приложения перестанет подключаться к базе: в её настройках записан прежний.
    Повторный запуск делайте без паролей:  sudo bash 02-db-server.sh
    Сменить пароль сознательно:            ROTATE_PASSWORDS=1 и затем
    поправить DATABASE_URL в /etc/audfond/audfond.env на сервере приложения."
    fi
    if [ -n "$STORED_OWNER" ] && [ "$OWNER_PASSWORD" != "$STORED_OWNER" ]; then
        die "OWNER_PASSWORD отличается от записанного в $PASSWORDS_FILE.
    Повторный запуск делайте без паролей:  sudo bash 02-db-server.sh
    Сменить пароль сознательно:            ROTATE_PASSWORDS=1"
    fi
fi

# Пароль роли учений человек не вводит и никуда не вписывает: роль нужна
# только сценариям проверок, которые читают его из файла паролей. Поэтому
# он генерируется здесь, а не требуется в командной строке.
if [ -z "${DRILL_PASSWORD:-}" ]; then
    if [ -f "$CONF_DIR/db-passwords" ] && grep -q '^DRILL_PASSWORD=' "$CONF_DIR/db-passwords"; then
        DRILL_PASSWORD="$(grep '^DRILL_PASSWORD=' "$CONF_DIR/db-passwords" | cut -d= -f2-)"
    else
        DRILL_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | cut -c1-24)"
    fi
fi

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
# Роль учений подключается к служебной базе postgres и к создаваемым ею
# временным базам. Имена временных баз заранее неизвестны, поэтому all.
# К базе audfond она всё равно не подключится: права CONNECT у неё нет
host    all        af_drill    $APP_IP/32    scram-sha-256    # AudFond
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
    -v drill_password="$DRILL_PASSWORD" \
    < "$SQL_DIR/roles.sql"
ok "база audfond, роли af_owner, af_app и af_drill готовы"

step "Пароли"
install -d -m 700 -o root -g root "$CONF_DIR"
cat > "$CONF_DIR/db-passwords" <<PWD
# Пароли ролей базы. Файл читает только root.
# В репозитории этого файла нет и быть не должно.
OWNER_PASSWORD=$OWNER_PASSWORD
APP_PASSWORD=$APP_PASSWORD
DRILL_PASSWORD=$DRILL_PASSWORD
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
