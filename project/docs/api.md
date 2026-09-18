# HTTP API

Базовый путь — `/api/v1`. Обмен — JSON в UTF-8. Даты — ISO 8601.
Машинное описание: `/api/openapi.json`, просмотр: `/api/docs`.

Доступ ко всем адресам, кроме `/login`, `/healthz`, `/readyz` и `/version`,
требует входа в систему (ТЗ 4.6).

## Аутентификация

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username": "admin", "password": "…"}
```

Ответ 200:

```json
{"access_token": "eyJhbGciOi…", "token_type": "bearer", "expires_in": 3600}
```

Тот же токен уходит в cookie `audfond_token` с `HttpOnly` и `SameSite=Lax`
(в продуктивной среде — ещё и `Secure`). Веб-страницы пользуются cookie,
смежные системы — заголовком:

```http
Authorization: Bearer eyJhbGciOi…
```

После пяти неудачных попыток подряд вход блокируется на `LOGIN_LOCK_MINUTES`
минут, и даже верный пароль в это время отклоняется — код
`LOGIN_TEMPORARILY_BLOCKED`.

| Адрес | Метод | Роль |
|---|---|---|
| `/api/v1/auth/login` | POST | без входа |
| `/api/v1/auth/logout` | POST | любая |
| `/api/v1/auth/me` | GET | любая |

## Роли

| Роль | Значение | Права |
|---|---|---|
| `SYS_ADMIN` | Администратор системы | всё, включая учётные записи |
| `FUND_ADMIN` | Администратор аудиторного фонда | справочники, помещения, обмеры |
| `DISPATCHER` | Диспетчер расписания | дисциплины, матрица, подбор |
| `OBSERVER` | Наблюдатель | только чтение |
| `SERVICE` | Внешняя информационная система | только чтение |

Нет входа — 401, не та роль — 403.

---

## Справочники

| Адрес | Методы |
|---|---|
| `/api/v1/departments` | GET, POST |
| `/api/v1/departments/{id}` | GET, PATCH, DELETE |
| `/api/v1/buildings` | GET, POST |
| `/api/v1/buildings/{id}` | GET, PATCH, DELETE |
| `/api/v1/buildings/{id}/floors` | GET — этажи с числом помещений |
| `/api/v1/room-types` | GET, POST |
| `/api/v1/room-types/{id}` | PATCH, DELETE |
| `/api/v1/disciplines` | GET, POST |
| `/api/v1/disciplines/{id}` | GET, PATCH, DELETE |

Списки постраничные:

```json
{"items": [...], "total": 128, "page": 1, "page_size": 50, "pages": 3}
```

---

## Помещения

| Адрес | Методы |
|---|---|
| `/api/v1/rooms` | GET (фильтры), POST |
| `/api/v1/rooms/{id}` | GET, PATCH, DELETE |
| `/api/v1/rooms/{id}/measurements` | GET, POST |
| `/api/v1/rooms/suitable` | GET — подбор аудитории |

Фильтры списка: `building_id`, `floor`, `room_type_id`, `department_id`,
`is_usable`, `area_min`, `area_max`, `q`, `page`, `page_size`.

```http
POST /api/v1/rooms
{"building_id": 1, "number": "201", "floor": 2, "room_type_id": 2,
 "area": "62.50", "seats": 24, "staff_seats": 1}
```

Ответ 201:

```json
{"id": 7, "number": "201", "area": "62.50", "seats": 24, "staff_seats": 1,
 "volume": 25, "normative_capacity": 25, "is_usable": true, ...}
```

`volume` считает база, во входных данных не принимается. `normative_capacity` —
правило D5 для текущей площади и типа.

### Подбор аудитории

```http
GET /api/v1/rooms/suitable?discipline_id=3&group_size=24&allow_overload=false
```

```json
{
  "discipline": {"id": 3, "code": "IB-02", "name": "Криптографические методы"},
  "group_size": 24,
  "items": [{"number": "201", "seats": 24, "seats_margin": 0, "overloaded": false, ...}],
  "rejected": {"D1_not_allowed": 7, "D2_too_small": 4, "D6_not_usable": 1}
}
```

Поле `rejected` объясняет, сколько помещений отсеяло каждое правило — чтобы
диспетчер понимал, что менять: матрицу, численность или пригодность.

---

## Формат ошибки

Любой отказ — ТЗ 4.1.6:

```json
{
  "error": {"code": "D5_NORM_CAPACITY_EXCEEDED", "message": "…", "details": {...}},
  "request_id": "0f1c8d2b4e6a…"
}
```

`request_id` дублируется в заголовке `X-Request-Id` и попадает в журнал.
Свой идентификатор в заголовке запроса сохраняется — так связываются журналы
смежных систем.

| HTTP | Коды |
|---|---|
| 400 | `INVALID_JSON`, `INVALID_QUERY_PARAM` |
| 401 | `UNAUTHENTICATED`, `INVALID_CREDENTIALS`, `LOGIN_TEMPORARILY_BLOCKED` |
| 403 | `FORBIDDEN`, `ACCOUNT_DISABLED` |
| 404 | `NOT_FOUND` |
| 409 | `RELATED_NOT_FOUND`, `DUPLICATE_CODE`, `HAS_DEPENDENTS`, `DEPARTMENT_CYCLE`, `FLOOR_OUT_OF_RANGE`, `HISTORY_IMMUTABLE`, `D1_DISCIPLINE_NOT_ALLOWED`, `D2_SEATS_EXCEEDED`, `D5_NORM_CAPACITY_EXCEEDED`, `D6_ROOM_NOT_USABLE` |
| 413 | `FILE_TOO_LARGE` |
| 422 | `VALIDATION_ERROR` |
| 500 | `INTERNAL_ERROR` |
| 503 | `DB_UNAVAILABLE`, `MIGRATIONS_NOT_APPLIED` |

Трассировка стека, текст SQL и значения секретов наружу не отдаются никогда.

---

## Служебные адреса

```http
GET /healthz   →  {"status": "ok"}
GET /readyz    →  {"status": "ok", "checks": {"database": "ok", "migrations": "ok: 0002_seed_reference"}}
GET /version   →  {"version": "0.1.0", "commit": "a1b2c3d", "app_env": "production"}
```

`/readyz` отвечает 503, если база недоступна или миграции не накатаны — на это
и опирается проверка релиза.
