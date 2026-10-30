#!/usr/bin/env bash
# Предварительная проверка машины перед запуском контейнеров — make preflight.
#
# Проверяет то, на чём запуск падает на середине, а не в начале: Docker и
# docker compose, доступ к образам, права на файлы, .env.docker, свободный
# порт, место на диске и память. Ничего не меняет — только смотрит и говорит,
# что исправить. Первым разделом печатает сведения о машине: этот вывод
# прикладывается к сообщению о сбое.
#
#   bash scripts/preflight.sh     (make preflight; make up вызывает её сам)
#
# Код возврата 1 — есть препятствие, запуск не начнётся. Предупреждения
# запуск не останавливают.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
ENV_FILE="$ROOT/.env.docker"
FAILED=0
WARNED=0

ok()   { printf '  ОК    %s\n' "$1"; }
bad()  { printf '  СБОЙ  %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; FAILED=1; }
warn() { printf '  !     %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; WARNED=1; }
fact() { printf '  %s: %s\n' "$1" "$2"; }

# Значение из .env.docker без подключения файла целиком
env_value() {
    [ -f "$ENV_FILE" ] || return 0
    grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"'
}

# Код ответа HTTPS-адреса: 000 — не ответил за отведённое время
http_code() {
    curl -s -o /dev/null -w '%{http_code}' --max-time "${2:-15}" "$1" 2>/dev/null || true
}

HTTP_PORT="$(env_value HTTP_PORT)"; HTTP_PORT="${HTTP_PORT:-8080}"
HTTP_BIND="$(env_value HTTP_BIND)"; HTTP_BIND="${HTTP_BIND:-0.0.0.0}"
BIND_OK=1

# ---------------------------------------------------------------------------
echo "Сведения о машине"
fact "система" "$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
fact "ядро" "$(uname -r)"
fact "процессоры" "$(nproc)"
fact "память" "$(awk '/MemTotal/ {printf "%.1f ГБ", $2/1048576}' /proc/meminfo)"
fact "свободно на диске" "$(df -h --output=avail /var/lib 2>/dev/null | tail -1 | tr -d ' ')"
fact "адреса" "$(hostname -I 2>/dev/null)"
fact "пользователь" "$(id -un), группы: $(id -Gn | tr ' ' ',')"
fact "umask" "$(umask)"
fact "docker" "$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'нет ответа')"
fact "docker compose" "$(docker compose version --short 2>/dev/null || echo 'нет')"
fact "python3" "$(python3 --version 2>/dev/null || echo 'нет')"
fact "каталог проекта" "$ROOT"

# ---------------------------------------------------------------------------
echo
echo "1. Docker"
if ! command -v docker >/dev/null 2>&1; then
    bad "docker не установлен" "docs/containers.md, раздел 1"
elif ! docker info >/dev/null 2>&1; then
    if id -nG | grep -qw docker; then
        bad "docker не отвечает" "sudo systemctl status docker"
    else
        bad "нет доступа к docker у пользователя $(id -un)" \
            "sudo usermod -aG docker $(id -un), затем выйти и зайти по ssh заново"
    fi
else
    ok "docker отвечает, доступ без sudo"
fi
if docker compose version >/dev/null 2>&1; then
    ok "docker compose $(docker compose version --short 2>/dev/null)"
else
    bad "нет docker compose v2" "пакет docker-compose-plugin"
fi
command -v python3 >/dev/null 2>&1 && ok "python3 установлен (используется make container-check)" \
    || bad "нет python3" "sudo apt-get install -y python3"
command -v curl >/dev/null 2>&1 || bad "нет curl" "sudo apt-get install -y curl"

# ---------------------------------------------------------------------------
echo
echo "2. Настройки .env.docker"
if [ ! -f "$ENV_FILE" ]; then
    bad ".env.docker нет" "make docker-env"
else
    mode="$(stat -c '%a' "$ENV_FILE")"
    [ "${mode: -2}" = "00" ] && ok ".env.docker закрыт (права $mode)" \
        || bad ".env.docker открыт другим пользователям (права $mode)" "chmod 600 .env.docker"
    weak=""
    for name in POSTGRES_PASSWORD JWT_SECRET ADMIN_PASSWORD; do
        value="$(env_value "$name")"
        if [ -z "$value" ] || printf '%s' "$value" | grep -qiE 'CHANGE_ME|СГЕНЕРИРУЙТЕ'; then
            weak="$weak $name"
        fi
    done
    [ -z "$weak" ] && ok "пароли и ключ не заглушки" \
        || bad "заглушка вместо значения:$weak" "make docker-env создаёт файл со случайными значениями"
    if [ "$HTTP_BIND" != "0.0.0.0" ] && ! hostname -I | tr ' ' '\n' | grep -qx "$HTTP_BIND"; then
        bad "HTTP_BIND=$HTTP_BIND — такого адреса у машины нет" "адреса машины: $(hostname -I)"
        BIND_OK=0
    else
        ok "Nginx будет слушать $HTTP_BIND:$HTTP_PORT"
    fi
fi

# ---------------------------------------------------------------------------
echo
echo "3. Права на файлы проекта"
# Код читают пользователи контейнеров (10001 — приложение, 101 — Nginx), а не
# владелец каталога. Образ выставляет права на код сам, файлы Nginx открывает
# make up, но закрытый каталог — признак, что что-то ещё прочитать не удастся
closed="$(find . \( -path ./.venv -o -path ./.git -o -path ./reports -o -path ./backups \
    -o -name '__pycache__' -o -name '.*_cache' \) -prune \
    -o \( -type f ! -name '.env' ! -name '.env.*' ! -perm -o=r -print \) \
    -o \( -type d ! -perm -o=x -print \) 2>/dev/null | head -200)"
count="$(printf '%s' "$closed" | grep -c . || true)"
if [ "$count" = "0" ]; then
    ok "файлы проекта читаются другими пользователями"
else
    warn "закрыто для чтения другим пользователям: $count файлов и каталогов, например $(printf '%s' "$closed" | head -1)" \
         "сборка образа выставляет права сама; для единообразия: chmod -R u=rwX,go=rX . && chmod 600 .env .env.docker"
fi

# ---------------------------------------------------------------------------
echo
echo "4. Образы"
images="$(grep -E '^ARG PYTHON_IMAGE=' docker/Dockerfile | cut -d= -f2)"
images="$images $(grep -E '^\s+image:\s' docker-compose.yml | awk '{print $2}' | grep -v '^audfond')"
missing=""
for image in $images; do
    if docker image inspect "$image" >/dev/null 2>&1; then
        ok "$image — уже на машине"
    else
        missing="$missing $image"
    fi
done
if [ -n "$missing" ]; then
    hub="$(http_code https://registry-1.docker.io/v2/ 20)"
    mirrors="$(docker info --format '{{range .RegistryConfig.Mirrors}}{{.}} {{end}}' 2>/dev/null)"
    reachable=""
    [ "$hub" = "401" ] && reachable="Docker Hub"
    for m in $mirrors; do
        code="$(http_code "${m%/}/v2/" 20)"
        [ "$code" = "200" ] || [ "$code" = "401" ] && reachable="$reachable $m"
    done
    if [ -n "$reachable" ]; then
        warn "не загружены:$missing" "будут загружены при запуске через: $reachable; заранее: docker pull$missing"
    else
        bad "не загружены:$missing, а Docker Hub (код $hub) и зеркала недоступны" \
            "зеркала — docs/containers.md, раздел 1; затем docker pull$missing"
    fi
fi
pypi="$(http_code https://pypi.org/simple/pip/ 20)"
files="$(http_code https://files.pythonhosted.org/ 20)"
if [ "$pypi" = "200" ] && [ "$files" != "000" ]; then
    ok "PyPI доступен"
elif docker image inspect audfond:0.4.0 >/dev/null 2>&1; then
    warn "PyPI отвечает с ошибками (pypi.org: $pypi, files.pythonhosted.org: $files)" \
         "образ уже собран: при неизменном requirements.lock пакеты не загружаются"
else
    bad "PyPI недоступен (pypi.org: $pypi, files.pythonhosted.org: $files), образ не собран" \
        "сборка загружает пакеты с PyPI; проверьте сеть машины"
fi

# ---------------------------------------------------------------------------
echo
echo "5. Порт, диск, память"
holder="$(docker ps --filter "publish=$HTTP_PORT" --format '{{.Names}}' 2>/dev/null | head -1)"
if [ "$BIND_OK" = "0" ]; then
    warn "порт не проверен: сначала исправьте HTTP_BIND"
elif [ -n "$holder" ]; then
    ok "порт $HTTP_PORT занят контейнером окружения $holder, он будет пересоздан"
elif ! python3 -c "import socket,sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind((sys.argv[1], int(sys.argv[2])))" \
        "$HTTP_BIND" "$HTTP_PORT" 2>/dev/null; then
    # Проверка пробным занятием порта: работает без ss и netstat
    bad "порт $HTTP_PORT уже занят другой программой" \
        "кто занял: sudo ss -ltnp | grep :$HTTP_PORT; или другой HTTP_PORT в .env.docker"
else
    ok "порт $HTTP_PORT свободен"
fi
free_kb="$(df --output=avail /var/lib 2>/dev/null | tail -1 | tr -d ' ')"
if [ -n "$free_kb" ] && [ "$free_kb" -lt 3145728 ]; then
    bad "на диске меньше 3 ГБ ($((free_kb / 1024)) МБ)" "образы и сборка занимают около 2 ГБ"
else
    ok "места на диске достаточно"
fi
mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if [ "$mem_kb" -lt 1500000 ]; then
    warn "памяти $((mem_kb / 1024)) МБ — меньше рекомендованных 2 ГБ" \
         "VBoxManage modifyvm audfond-app --memory 2048 (при выключенной машине)"
else
    ok "памяти достаточно"
fi

# ---------------------------------------------------------------------------
echo
if [ "$FAILED" != "0" ]; then
    echo "Есть препятствия (СБОЙ), запуск невозможен. Устраните их и повторите make preflight."
    exit 1
fi
[ "$WARNED" != "0" ] && echo "Препятствий нет, есть предупреждения (!)." || echo "Препятствий нет."
exit 0
