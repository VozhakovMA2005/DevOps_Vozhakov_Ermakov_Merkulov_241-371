#!/usr/bin/env bash
# Базовая подготовка машины — выполняется на ОБЕИХ: сервере приложения и
# сервере базы данных. Пункты задания 2, 3, 4 и частично 10.
#
# Что делает:
#   имя узла и записи в /etc/hosts
#   постоянный адрес на внутреннем интерфейсе
#   пользователь администрирования с входом по ключу и правом sudo
#   запрет удалённого входа под root и запрет входа по паролю
#   межсетевой экран: по умолчанию всё входящее закрыто, кроме SSH из стенда
#
# Запуск (от root, с консоли машины):
#   ROLE=app  PUBKEY="ssh-ed25519 AAAA... egor@notebook" bash 01-base.sh
#   ROLE=db   PUBKEY="ssh-ed25519 AAAA... egor@notebook" bash 01-base.sh

. "$(dirname "$0")/lib.sh"

need_root

ROLE="${ROLE:-}"
PUBKEY="${PUBKEY:-}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
IFACE="${IFACE:-enp0s8}"   # вторая сетевая карта VirtualBox (Host-only)

case "$ROLE" in
    app) MY_HOST="$APP_HOST"; MY_IP="$APP_IP" ;;
    db)  MY_HOST="$DB_HOST";  MY_IP="$DB_IP" ;;
    *)   die "Укажите ROLE=app или ROLE=db" ;;
esac

[ -n "$PUBKEY" ] || die "Укажите PUBKEY='содержимое вашего id_ed25519.pub'"
case "$PUBKEY" in
    ssh-*) : ;;
    *) die "PUBKEY не похож на открытый ключ: должен начинаться с ssh-" ;;
esac

# Пароль нужен не для входа — вход только по ключу, — а для sudo.
# Без пароля учётная запись не смогла бы выполнить ни одной команды через
# sudo: он спрашивает пароль самого пользователя, а не root.
[ -n "$ADMIN_PASSWORD" ] || die "Укажите ADMIN_PASSWORD — пароль для sudo пользователя $ADMIN_USER"
[ ${#ADMIN_PASSWORD} -ge 8 ] || die "ADMIN_PASSWORD короче 8 символов"

step "Пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq sudo ufw curl ca-certificates gnupg >/dev/null
ok "sudo, ufw, curl установлены"

step "Имя узла и /etc/hosts"
hostnamectl set-hostname "$MY_HOST"
# Записи обеих машин: дальше можно обращаться по имени, а не по адресу
backup_once /etc/hosts
sed -i "/audfond-app/d;/audfond-db/d" /etc/hosts
printf '%s %s\n%s %s\n' "$APP_IP" "$APP_HOST" "$DB_IP" "$DB_HOST" >> /etc/hosts
ok "узел $MY_HOST, в /etc/hosts записаны обе машины"

step "Постоянный адрес на интерфейсе $IFACE"
if ! ip link show "$IFACE" >/dev/null 2>&1; then
    warn "интерфейса $IFACE нет. Доступные:"
    ip -brief link show | awk '{print "      " $1}'
    die "Укажите нужный через IFACE=... (вторая карта, Host-only)"
fi
mkdir -p /etc/network/interfaces.d
cat > "/etc/network/interfaces.d/$IFACE" <<CFG
# Внутренняя сеть стенда AudFond. Адрес постоянный: по нему ходят
# сервер приложения, сервер базы и клиент с хост-машины.
auto $IFACE
iface $IFACE inet static
    address $MY_IP
    netmask 255.255.255.0
CFG
ifdown "$IFACE" >/dev/null 2>&1 || true
ifup "$IFACE" >/dev/null 2>&1 || warn "интерфейс поднимется после перезагрузки"
ok "адрес $MY_IP закреплён за $IFACE"

step "Пользователь администрирования: $ADMIN_USER"
if ! id -u "$ADMIN_USER" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "Администратор стенда AudFond" "$ADMIN_USER" >/dev/null
    ok "пользователь создан"
else
    info "пользователь уже есть"
fi
usermod -aG sudo "$ADMIN_USER"

# Пароль задаём только ради sudo. По SSH он не поможет: вход по паролю
# запрещён ниже, пускают только по ключу.
printf '%s:%s\n' "$ADMIN_USER" "$ADMIN_PASSWORD" | chpasswd
ok "пароль для sudo задан (по SSH вход по паролю всё равно запрещён)"

install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/$ADMIN_USER/.ssh"
touch "/home/$ADMIN_USER/.ssh/authorized_keys"
grep -qxF "$PUBKEY" "/home/$ADMIN_USER/.ssh/authorized_keys" \
    || echo "$PUBKEY" >> "/home/$ADMIN_USER/.ssh/authorized_keys"
chmod 600 "/home/$ADMIN_USER/.ssh/authorized_keys"
chown "$ADMIN_USER:$ADMIN_USER" "/home/$ADMIN_USER/.ssh/authorized_keys"
ok "открытый ключ записан, вход по паролю этому пользователю не нужен"

step "SSH: запрет root и запрет паролей"
backup_once /etc/ssh/sshd_config
set_option /etc/ssh/sshd_config PermitRootLogin no
set_option /etc/ssh/sshd_config PasswordAuthentication no
set_option /etc/ssh/sshd_config PubkeyAuthentication yes
set_option /etc/ssh/sshd_config KbdInteractiveAuthentication no
set_option /etc/ssh/sshd_config AllowUsers "$ADMIN_USER"
sshd -t || die "Конфигурация sshd не прошла проверку, перезапуск отменён"
systemctl restart ssh
ok "удалённый вход под root запрещён, вход только по ключу"

step "Межсетевой экран"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
# SSH разрешаем из двух сетей:
#   сеть стенда — обычная работа по постоянным адресам;
#   сеть NAT VirtualBox — первое подключение через проброс порта, пока
#   постоянные адреса ещё не настроены. Без второго правила скрипт отрезал бы
#   доступ самому себе на первом же запуске.
ufw allow from "$LAN" to any port 22 proto tcp comment 'SSH из сети стенда' >/dev/null
ufw allow from "$NAT_NET" to any port 22 proto tcp comment 'SSH через проброс порта NAT' >/dev/null
ufw --force enable >/dev/null
ok "входящее закрыто, SSH разрешён из $LAN и $NAT_NET"
info "порты роли ($MY_HOST) откроет следующий скрипт"

step "Готово"
info "Проверьте вход по ключу с хост-машины:"
info "    ssh $ADMIN_USER@$MY_IP"
info "Файлы дальше заносите тем же ключом, без паролей:"
info "    scp -r deploy $ADMIN_USER@$MY_IP:~/"
info "Дальше: ROLE=db → 02-db-server.sh, ROLE=app → 03-app-server.sh"
