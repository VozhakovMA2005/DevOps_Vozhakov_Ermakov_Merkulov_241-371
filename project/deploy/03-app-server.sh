#!/usr/bin/env bash
# Сервер приложения. Пункты задания 5, 7, 8, 9, 10, 11.
#
# Что делает:
#   ставит Python и сборочные пакеты
#   создаёт системного пользователя запуска — без оболочки и без пароля
#   готовит каталоги кода и настроек с правильными правами
#   ставит службу systemd с автозапуском и перезапуском после сбоя
#   открывает порт приложения клиенту
#
# Запуск (от root, на машине audfond-app):
#   bash 03-app-server.sh
#
# Код и настройки кладёт уже deploy.sh — этот скрипт готовит окружение.

. "$(dirname "$0")/lib.sh"

need_root
HERE="$(cd "$(dirname "$0")" && pwd)"

step "Пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-dev \
    build-essential libpq-dev \
    postgresql-client \
    rsync curl >/dev/null
ok "Python $(python3 -V | awk '{print $2}') и сборочные пакеты установлены"
info "клиент psql нужен шагу раздачи прав в deploy.sh"

step "Пользователь запуска приложения: $APP_USER"
# --system: служебная учётная запись. Оболочка nologin и отсутствие пароля
# означают, что войти под ней нельзя ни по SSH, ни локально.
if ! id -u "$APP_USER" >/dev/null 2>&1; then
    adduser --system --group --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER" >/dev/null
    ok "создан системный пользователь без оболочки"
else
    info "пользователь уже есть"
fi
# Администратор должен иметь право читать каталоги приложения
usermod -aG "$APP_USER" "$ADMIN_USER" 2>/dev/null || true

step "Каталоги и права"
# Код: владеет администратор, группа — приложение. Приложение читает и
# выполняет, но записать в свой каталог не может. Посторонним закрыто.
install -d -m 750 -o "$ADMIN_USER" -g "$APP_USER" "$APP_DIR"
install -d -m 750 -o "$APP_USER"   -g "$APP_USER" "$APP_DIR/backups"

# Настройки: владелец root, читает только группа приложения
install -d -m 750 -o root -g "$APP_USER" "$CONF_DIR"
if [ ! -f "$CONF_DIR/audfond.env" ]; then
    install -m 640 -o root -g "$APP_USER" "$HERE/audfond.env.example" "$CONF_DIR/audfond.env"
    warn "создан $CONF_DIR/audfond.env из образца — впишите адрес базы, пароль и ключ подписи"
else
    chown root:"$APP_USER" "$CONF_DIR/audfond.env"
    chmod 640 "$CONF_DIR/audfond.env"
    info "настройки уже есть, права приведены к 640 root:$APP_USER"
fi
ok "код в $APP_DIR (750), настройки в $CONF_DIR (640)"

step "Служба systemd"
install -m 644 -o root -g root "$HERE/audfond.service" /etc/systemd/system/audfond.service
systemctl daemon-reload
systemctl enable audfond >/dev/null
ok "служба установлена и включена в автозапуск"
info "запускать пока рано: кода ещё нет, это сделает deploy.sh"

step "Межсетевой экран"
ufw allow 8000/tcp comment 'AudFond: веб-интерфейс и API' >/dev/null
ok "порт 8000 открыт клиентам"

step "Готово"
info "Дальше, от имени $ADMIN_USER:"
info "    1) впишите настройки в $CONF_DIR/audfond.env  (sudo nano)"
info "    2) выложите код и накатите схему:  sudo bash deploy.sh"
