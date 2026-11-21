# ЛР6: Continuous Delivery и проверка работающего релиза

## Что подготовлено

Комплект продолжает актуальный main AudFond: 7f52e41b515e742102ccbaa33d6ae70da173f44f. Репозиторий получен 17 ноября 2026 года. Основание: приложенная методичка «Лабораторная работа №6. Continuous Delivery и проверка работающего релиза» и ТЗ А.В.00001-01 33 01-1, прежде всего 4.5, 4.6, 7.1–7.4.

В методичке ЛР6 посвящена CD. Таблица этапов старого ТЗ дополнительно упоминает аналитику; этот комплект реализует именно выданное задание CD и приемку из 7.1, не добавляя несвязанные отчеты.

Внешняя структура повторяет ЛР5: пять автономных HTML-инструкций, audfond-source.zip и by-task-lr6.zip. В исходниках сохранены исходное ТЗ, прежние документы, приложение, миграции и тесты. Новые материалы — project/deploy/cd/, project/docs/cd.md, workflow CD, проверка readiness и версия 0.6.0.

Принцип приемки: CI зеленый → образ опубликован → отдельный стенд → контейнеры healthy → healthz/readyz → совпадение version+commit → вход → каталог → карточка. Только после этого current записывается как принятый. В базе должны быть тестовые помещения: пустой каталог не принимается.

## Структура стенда

Рекомендуется отдельная Ubuntu Server 24.04 VM с Python 3.12+, Docker Engine 24+ и Compose 2.24+ с поддержкой up --wait, run --pull never и env_file. Проверьте команды на установленной версии; при отсутствии ключа обновите Compose. Требуется не менее 4 ГБ RAM и 10 ГБ свободного места. Контейнерный проект — audfond-staging, собственный том audfond-staging_db-data и собственные сети. Рабочее окружение ЛР5 audfond не изменяется.

Каталог /opt/audfond-cd содержит проверенный контроллер, принадлежащий root; /srv/audfond-staging принадлежит отдельному пользователю audfond-cd. Приложение и PostgreSQL хранят параметры в отдельных env-файлах с правами 600. Код с сервера не собирается. Используются GHCR и ссылки image@sha256:... . Nginx слушает только 127.0.0.1:18080. Для демонстрации применяется SSH-туннель. Это закрытый тестовый стенд; для публичного размещения потребуется TLS и отдельная конфигурация прокси.

## Подготовка отдельной учетной записи

Команды выполняет администратор НОВОЙ тестовой VM. Docker и Compose предварительно устанавливаются из официальной документации Docker для Ubuntu. Добавление в группу docker дает управление всем Docker-хостом, поэтому используйте выделенную VM и не размещайте на ней посторонние нагрузки.

```bash
sudo adduser --disabled-password --gecos '' audfond-cd
sudo usermod -aG docker audfond-cd
sudo install -d -o root -g root -m 755 /opt/audfond-cd
sudo install -d -o audfond-cd -g audfond-cd -m 700 /srv/audfond-staging
sudo install -d -o audfond-cd -g audfond-cd -m 700 /home/audfond-cd/.ssh
# Из распакованного audfond-source:
sudo install -o root -g root -m 644 project/deploy/cd/cd.py /opt/audfond-cd/cd.py
sudo install -o audfond-cd -g audfond-cd -m 600 project/deploy/cd/deploy.env.example /srv/audfond-staging/deploy.env
sudo install -o audfond-cd -g audfond-cd -m 600 project/deploy/cd/app.env.example /srv/audfond-staging/app.env
sudo install -o audfond-cd -g audfond-cd -m 600 project/deploy/cd/db.env.example /srv/audfond-staging/db.env
sudo install -o audfond-cd -g audfond-cd -m 600 project/deploy/cd/smoke.env.example /srv/audfond-staging/smoke.env
```

На машине администратора сгенерируйте отдельный ключ ed25519. Приватную часть храните как CD_SSH_KEY в GitHub Environment staging. Публичную добавьте в authorized_keys пользователя audfond-cd с префиксом restrict. Файл должен принадлежать audfond-cd и иметь права 600. Ключ используется только для этого стенда. Не добавляйте пароли в Git, HTML или команды коммитов.

```bash
ssh-keygen -t ed25519 -f ./audfond-cd-key -C audfond-staging-cd
# В /home/audfond-cd/.ssh/authorized_keys:
# restrict ssh-ed25519 <публичная часть> audfond-staging-cd
sudo chown audfond-cd:audfond-cd /home/audfond-cd/.ssh/authorized_keys
sudo chmod 600 /home/audfond-cd/.ssh/authorized_keys
```

Для автоматического ключа допускается пустая passphrase, поскольку ключ читает ssh в pipeline; защищайте его Environment secrets. Администраторские ключи и ключи для туннеля должны быть отдельными. Ключ restrict не дает порт-форвардинг. В CD_KNOWN_HOSTS поместите проверенную строку known_hosts целевой VM. Сверьте fingerprint через консоль VM: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub. Не используйте StrictHostKeyChecking=no и не доверяйте результату ssh-keyscan без сверки.

## Настройки окружения

Редактируйте четыре файла непосредственно на VM. Формат строго KEY=value: без кавычек, export, подстановок и повторяющихся ключей. Для паролей используйте secrets.token_urlsafe(36), чтобы избежать специальных символов Docker env и URL. DATABASE_URL должен буквально соответствовать db.env. Пользователь smoke — observer; bootstrap создает его вместе с тестовыми помещениями. Не меняйте этот пароль только в smoke.env: измените пароль пользователя в приложении согласованно, иначе приемка входа закономерно упадет.

```bash
sudo -iu audfond-cd
python3 -c 'import secrets; print(secrets.token_urlsafe(36))'
# Заполните db.env: POSTGRES_PASSWORD=<первое случайное значение>
# app.env: JWT_SECRET=<другое случайное значение>
# app.env: DATABASE_URL=postgresql+psycopg://audfond:<POSTGRES_PASSWORD>@db:5432/audfond_staging
# smoke.env: SMOKE_PASSWORD=<третье значение, минимум 8 символов>
# deploy.env: IMAGE_REPOSITORY=ghcr.io/vozhakovma2005/audfond
chmod 600 /srv/audfond-staging/{deploy,app,db,smoke}.env
```

APP_ENV=production используется для строгой проверки настроек приложения, но сама среда остается отдельным тестовым стендом. COOKIE_SECURE=false допустим здесь из-за loopback HTTP внутри SSH-туннеля. GIT_COMMIT и INSTANCE_ID запрещены в app.env: коммит должен приходить из собранного образа. MIGRATE_ON_START=false предотвращает неуправляемый накат при старте. У базы нет опубликованного порта.

Для приватного GHCR один раз выполните docker login ghcr.io от audfond-cd, используя персональный токен только read:packages и учетную запись, имеющую доступ к пакету. Пароль вводится через stdin. Не переносите GITHUB_TOKEN с CI на VM и не передавайте registry credentials в app.env. Если образ публичный, вход на VM не требуется.

```bash
read -r -s -p 'GHCR read token: ' REGISTRY_TOKEN
printf '\n'
printf '%s' "$REGISTRY_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_LOGIN --password-stdin
unset REGISTRY_TOKEN
chmod 600 ~/.docker/config.json
```

## Первый запуск

Сначала изменения из задач ЛР6 должны пройти PR, ревью, CI и публикацию в main. Запишите полный SHA из успешного job publish. Bootstrap — осознанное локальное создание нового тестового стенда: он накатывает миграции и запускает seed_demo.py. Обычный deploy данные не создает и не перезаписывает.

```bash
# На VM от audfond-cd; подставьте реальный полный SHA, без угловых скобок.
SHA=FULL_40_HEX_SHA_OF_PUBLISHED_MAIN
python3 /opt/audfond-cd/cd.py bootstrap --root /srv/audfond-staging --tag "sha-$SHA" --commit "$SHA"
python3 /opt/audfond-cd/cd.py status --root /srv/audfond-staging
python3 /opt/audfond-cd/cd.py check --root /srv/audfond-staging
```

Если bootstrap не прошел, он оставляет pending и не объявляет релиз принятым. После устранения причины администратор сохраняет копию release-state.json и release-history.jsonl, затем только на этом НОВОМ стенде без current убирает файл состояния и повторяет bootstrap. Том не удаляется; seed идемпотентен. Если current уже существует, применяется recover, а bootstrap запрещен.

На своем компьютере откройте туннель администраторским ключом, допускающим forwarding:

```bash
ssh -N -L 18080:127.0.0.1:18080 ADMIN_LOGIN@STAGING_HOST
# Браузер: http://127.0.0.1:18080
# Вход: observer и пароль из smoke.env; каталог содержит помещения.
```

## Настройка GitHub CD

Settings → Environments → New environment → staging. Ограничьте deployment branches только main. Для полностью автоматического тестового стенда не задавайте required reviewers; если они включены, CD будет ждать ручного одобрения после публикации. Защита main и обязательный ci-gate из ЛР5 сохраняются.

Environment variables: CD_HOST — адрес VM, доступный GitHub runner по SSH; CD_USER=audfond-cd. Environment secrets: CD_SSH_KEY и CD_KNOWN_HOSTS. Repository variable: CD_ENABLED=true включается ТОЛЬКО после успешного bootstrap. Старый LOCAL_REGISTRY можно использовать для ЛР5 независимо; CD этого комплекта берет образ из GHCR.

GitHub-hosted runner не может подключиться к вашей домашней VM за NAT без сетевого маршрута. До включения CD обеспечьте доступный защищенный SSH endpoint или существующий VPN. Если машина доступна только локальному trusted runner, осознанно замените runs-on у обеих CD jobs на выделенный runner с доступом к VM; не запускайте недоверенные PR на этом runner.

В CI добавлена job deploy-staging с needs: publish. Только успешный push в main запускает доставку sha-<40 hex>. Публикация тега v0.6.0 сама автоматический деплой не запускает: этот тег можно выбрать вручную. Общая concurrency-группа не отменяет активный деплой; flock на VM немедленно отклоняет конфликтующую локальную операцию. Устаревший SHA, переставший быть вершиной main до начала SSH-доставки, пропускается.

## Выпуск конкретной версии и ручной возврат

Actions → CD manual → Run workflow → Branch main. Для deploy укажите существующий тег образа 0.6.0 или sha-<полный SHA>. Префикс v относится к Git-тегу, у образа его нет. Для rollback, recover, check поле tag оставьте пустым.

```bash
# Локально на VM, те же операции, что у pipeline:
python3 /opt/audfond-cd/cd.py deploy --tag 0.6.0
python3 /opt/audfond-cd/cd.py rollback
python3 /opt/audfond-cd/cd.py check
python3 /opt/audfond-cd/cd.py status
# Из каталога project на самой VM доступны также:
make release-deploy TAG=0.6.0
make release-rollback
make release-check
```

previous — предыдущий ПРИНЯТЫЙ digest, не последний скачанный тег. После успешного rollback прежний current становится previous. Повторный deploy того же digest только проверяет текущее состояние и не стирает previous. История содержит started/failed/restored/accepted/recovery-failed/recovered и UTC-время. Секреты, HTTP-токены и содержимое env туда не записываются.

Если процесс прервали после записи намерения, pending сохраняется. Новая доставка блокируется. recover возвращает и проверяет current, то есть последний принятый образ, и только после успеха снимает pending. Не очищайте pending вручную у работающего стенда с current. При recovery-failed требуется разбор Docker/БД администратором; зеленого статуса не будет.

## Миграции, резервирование и границы rollback

В ЛР6 схема не меняется. Контроллер получает head из скачанного образа и сравнивает с сохраненным current.schema. Несовпадение блокируется ДО изменения работающего стека. Это позволяет безопасно возвращать бинарный релиз без уничтожения данных. /readyz дополнительно проверяет фактическую Alembic-ревизию БД против кода образа.

Если будущая функция меняет схему, сначала оформите отдельную задачу: совместимые expand/contract миграции, резервная копия, проверка восстановления и план понижения Alembic либо восстановления БД. Не обходите guard заменой schema в JSON. Сохраненное состояние не заменяет резервную копию. ТЗ требует понижения миграции при изменении схемы; для задач ЛР6 миграций нет, поэтому downgrade не требуется.

```bash
# Копия базы на отдельном стенде; от audfond-cd:
umask 077
mkdir -p /srv/audfond-staging/backups
docker compose -p audfond-staging -f /srv/audfond-staging/compose.json exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > /srv/audfond-staging/backups/before-release.dump
# Хранить отдельно от Git; проверить восстановление на отдельной одноразовой БД.
```

## Аннотированный тег после приемки

Команды выполняет администратор на уже принятом коммите main. До тега убедитесь, что версия приложения и OCI равна 0.6.0, а /version.commit совпадает с этим коммитом. Не переставляйте существующий тег.

~~~bash
git fetch origin --tags
git switch main
git pull --ff-only
git tag -a v0.6.0 -m "ЛР6: CD и проверка работающего релиза"
git push origin v0.6.0
# Дождаться CI и publish для тега, затем CD manual deploy с тегом образа 0.6.0.
~~~

## Проверки перед PR

```bash
cd project
make cd-test
make verify
make guard
make ci-sync
make codeowners-check
make ci
```

Новые unittest не требуют базы и Docker, но make verify и полный CI требуют рабочий Docker/PostgreSQL либо локальное окружение из инструкции ЛР5. make quality по-прежнему проверяет весь Python-код, включая deploy/cd. Пороги покрытия 70%/80%, сканеры и защита критических файлов не ослаблены. Изменения deploy/**, Dockerfile, Makefile, CI и тестов требуют одобрения CODEOWNERS.

## Что проверено при подготовке и что проверять на стенде

Точный отчет находится в project/docs/lr6-validation.md. Здесь не создавались реальные GitHub Issues, PR, теги, registry-образы или удаленные релизы. Шаблоны не подменяют живые доказательства. Стендовые команды в инструкциях нужно выполнить на целевой VM; результаты CI и демонстрации приложите к PR. Документ с методичкой использован как источник задания, его текст не изменен.
