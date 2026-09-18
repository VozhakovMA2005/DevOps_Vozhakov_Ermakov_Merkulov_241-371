# Развёртывание, диагностика, восстановление

Поддерживаются два способа: контейнеры и systemd-служба (ТЗ 4.5).

## 1. Контейнеры

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # в JWT_SECRET
make up
make create-admin
```

Что происходит: поднимается PostgreSQL 17, ждёт готовности (`pg_isready`),
затем контейнер приложения накатывает миграции и запускает uvicorn.

Устройство образа:

- многостадийная сборка, компиляторы в конечный образ не попадают;
- процесс работает от пользователя `audfond` (uid 10001), не от root;
- теги базовых образов закреплены, `latest` не используется;
- объявлен `HEALTHCHECK` на `/healthz`;
- заданы ограничения процессора и памяти;
- порт базы наружу не публикуется;
- `exec uvicorn` в точке входа — процесс 1 сам получает SIGTERM и завершается
  корректно за 10 секунд.

Проверить перечисленное: `make container-check`.

## 2. systemd-служба

```bash
sudo useradd --system --home /opt/audfond --shell /usr/sbin/nologin audfond
sudo rsync -a --exclude .git ./ /opt/audfond/
sudo chown -R audfond:audfond /opt/audfond
sudo -u audfond python3 -m venv /opt/audfond/.venv
sudo -u audfond /opt/audfond/.venv/bin/pip install -r /opt/audfond/requirements.txt

sudo mkdir -p /etc/audfond
sudo install -m 0640 -o root -g audfond .env /etc/audfond/audfond.env

sudo cp deploy/audfond.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now audfond
```

Секреты лежат в `/etc/audfond/audfond.env` с правами `0640` — вне репозитория
и недоступны прочим пользователям. Служба перезапускается при аварийном
завершении (`Restart=on-failure`).

```bash
systemctl status audfond
journalctl -u audfond -f
```

---

## Диагностика

| Симптом | Что смотреть |
|---|---|
| `/readyz` отдаёт `DB_UNAVAILABLE` | база не поднялась или неверный `DATABASE_URL` |
| `/readyz` отдаёт `MIGRATIONS_NOT_APPLIED` | `make migrate` |
| Приложение не стартует, пишет про `JWT_SECRET` | не задан ключ подписи |
| 401 на всех адресах | истёк токен; войдите заново |
| 403 при записи | роль только для чтения |
| Ответ 500 | найдите `request_id` из ответа в журнале: `make logs \| grep <id>` |

Журнал структурированный, в формате JSON: время, уровень, тип события, адрес,
результат, `request_id`. Пароли и токены в журнал не пишутся.

---

## Резервное копирование и восстановление

```bash
make backup                                  # backups/audfond-20260918-2210.dump
make restore FILE=backups/audfond-20260918-2210.dump
```

Копия снимается `pg_dump -Fc`, восстановление — `pg_restore --clean --if-exists`.

Проверять восстановление надо не «когда-нибудь», а сразу: удалите тестовую
запись, восстановитесь из копии и убедитесь, что запись вернулась. Копия,
которую ни разу не разворачивали, — это не копия.

Каталог `backups/` исключён из репозитория.
