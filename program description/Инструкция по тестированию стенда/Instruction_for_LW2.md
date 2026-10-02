# audfond — Развёртывание в Linux-среде (Части 1 и 2)

## Стенд

| Узел          | Адрес          | Роль                                                                |
|---------------|----------------|---------------------------------------------------------------------|
| `audfond-app` | 192.168.56.10  | Python 3.11, venv; служба `audfond`; порт 8000 открыт               |
| `audfond-db`  | 192.168.56.11  | PostgreSQL 17; роли `af_owner` и `af_app`; порт 5432 только для .10 |
| Ваш компьютер | 192.168.56.1   | Браузер-клиент, «посторонний узел», SSH к обеим машинам             |

---

# Часть 1. Создать машины

## Шаг 1. Поставить VirtualBox и скачать образ Debian
*На вашем компьютере.*

1. Установить VirtualBox с `virtualbox.org`.
2. Скачать образ **debian-12.x.0-amd64-netinst.iso** со страницы `debian.org/download`.
3. Создать сеть для стенда: **File → Tools → Network Manager → Host-only Networks**. Если сети нет — **Create**. Проверить: адрес `192.168.56.1`, маска `255.255.255.0`, DHCP выключен.

---

## Шаг 2. Создать две виртуальные машины
*VirtualBox, одинаково для обеих.*

Имена: `audfond-app` и `audfond-db`. Настройки одинаковые.

| Параметр          | Значение                                |
|-------------------|-----------------------------------------|
| Тип               | Linux / Debian (64-bit)                 |
| Память            | 1024 МБ                                 |
| Процессоры        | 2                                       |
| Диск              | 10 ГБ                                   |
| Сеть, адаптер 1   | NAT                                     |
| Сеть, адаптер 2   | Host-only Adapter                       |

Второй адаптер включается в **Settings → Network → Adapter 2 → Enable Network Adapter → Host-only Adapter**.

### Проброс порта

**Settings → Network → Adapter 1 → Advanced → Port Forwarding**.

| Машина        | Host Port | Guest Port |
|---------------|-----------|------------|
| audfond-app   | 2210      | 22         |
| audfond-db    | 2211      | 22         |

---

## Шаг 3. Установить Debian — без графики
*В каждой машине.*

Выбирать **Install** (не Graphical install).

1. Язык, страна, раскладка — на выбор.
2. **Hostname**: `audfond-app` или `audfond-db`. Domain name — оставить пустым.
3. **Пароль root — оставить пустым**, нажать Continue дважды.
4. Создать пользователя — например `egor`.
5. Разметка диска: **Guided — use entire disk**, всё в один раздел.
6. **Software selection** — пробелом **снять** галочки:
   - ✗ Debian desktop environment
   - ✗ GNOME

   и **оставить**:
   - ✓ SSH server
   - ✓ standard system utilities
7. GRUB — на основной диск (`/dev/sda`).

---

# Часть 2. Настроить

## Шаг 4. Ключ SSH и перенос файлов
*С вашего компьютера.*

Создать ключ (в PowerShell или Git Bash):

```bash
ssh-keygen -t ed25519 -C "egor@notebook"
```

Посмотреть открытую часть:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

Перенести папку `deploy` на обе машины:

```bash
# на вашем компьютере
scp -P 2210 -r deploy egor@127.0.0.1:~/
scp -P 2211 -r deploy egor@127.0.0.1:~/
```

---

## Шаг 5. Базовая настройка обеих машин

```bash
# с хоста заходим на audfond-db
ssh -p 2211 egor@127.0.0.1

cd ~/deploy
sudo env ROLE=db \
         PUBKEY="ssh-ed25519 AAAA... egor@notebook" \
         ADMIN_PASSWORD='пароль-для-sudo-2026' \
         bash 01-base.sh
```

```bash
# с хоста заходим на audfond-app
ssh -p 2210 egor@127.0.0.1

cd ~/deploy
sudo env ROLE=app \
         PUBKEY="ssh-ed25519 AAAA... egor@notebook" \
         ADMIN_PASSWORD='пароль-для-sudo-2026' \
         bash 01-base.sh
```

Проверка — прямой вход по ключу:

```bash
ssh deployer@192.168.56.11
ssh deployer@192.168.56.10
```

---

## Шаг 6. Сервер базы данных

```bash
# на вашем компьютере
scp -r deploy deployer@192.168.56.11:~/
```

```bash
# с хоста заходим на audfond-db
ssh deployer@192.168.56.11
cd ~/deploy

sudo env OWNER_PASSWORD='пароль-миграций-2026' \
         APP_PASSWORD='пароль-приложения-2026' \
         bash 02-db-server.sh
```

Проверка прав роли приложения:

```bash
psql "postgresql://af_app@192.168.56.11/audfond" -c "DROP TABLE room;"
# ERROR: must be owner of table room
```

---

## Шаг 7. Сервер приложения и служба

```bash
# на вашем компьютере
scp -r deploy deployer@192.168.56.10:~/
```

```bash
# с хоста заходим на audfond-app
ssh deployer@192.168.56.10
cd ~/deploy

sudo bash 03-app-server.sh
```

Сгенерировать ключ подписи:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Открыть файл настроек:

```bash
sudo nano /etc/audfond/audfond.env
```

Заменить значения:

```ini
DATABASE_URL=postgresql+psycopg://af_app:пароль-приложения-2026@192.168.56.11:5432/audfond
JWT_SECRET=сюда-вставить-сгенерированный-ключ
COOKIE_SECURE=false
```

---

## Шаг 8. Выложить приложение

```bash
# на вашем компьютере
scp -r audfond-source deployer@192.168.56.10:~/audfond
```

```bash
# audfond-app
cd ~/audfond
sudo env OWNER_PASSWORD='пароль-миграций-2026' bash deploy/deploy.sh
```

Ожидаемый результат:

```json
ОК  приложение отвечает: {"status":"ok","checks":{"database":"ok",...}}
```

Создать администратора:

```bash
sudo bash deploy/manage.sh create-admin
```

Адрес в браузере: http://192.168.56.10:8000/

---

## Шаг 9. Проверить стенд целиком

```bash
# audfond-app
sudo bash ~/audfond/deploy/check.sh
```