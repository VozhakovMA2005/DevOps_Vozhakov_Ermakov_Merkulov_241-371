# Контракты HTTP API

Программный документ по разделу 5 ТЗ **А.В.00001-01 33 01-1**.
Версия API v1, версия программы v0.1.0.

Машинное описание в формате OpenAPI: `/api/openapi.json`.
Просмотр в браузере: `/api/docs`.

| | |
|---|---|
| Базовый путь | `/api/v1` |
| Формат обмена | JSON, UTF-8 |
| Даты | ISO 8601; отметки времени в UTC |
| Площади | строка с двумя знаками (`"62.50"`), не число с плавающей точкой |
| Всего адресов | 38 |

---

## 1. Аутентификация

Доступ ко всем адресам, кроме `/healthz`, `/readyz`, `/version` и страницы
входа, требует действительного токена (ТЗ 4.6).

### `POST /api/v1/auth/login` — вход

```json
{"username": "admin", "password": "…"}
```

Ответ **200**:

```json
{"access_token": "eyJhbGciOiJIUzI1NiIs…", "token_type": "bearer", "expires_in": 3600}
```

Тот же токен уходит в cookie `audfond_token` с атрибутами `HttpOnly` и
`SameSite=Lax`; в продуктивной среде добавляется `Secure`. Веб-страницы
пользуются cookie, смежные системы — заголовком:

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIs…
```

Отказы: **401** `INVALID_CREDENTIALS` — неизвестный логин или неверный пароль
(ответ одинаковый в обоих случаях); **401** `LOGIN_TEMPORARILY_BLOCKED` —
пять неудачных попыток подряд, в деталях указано `locked_until`;
**403** `ACCOUNT_DISABLED` — учётная запись заблокирована.

### `POST /api/v1/auth/logout` — выход

Удаляет cookie. Ответ **200** `{"status": "ok"}`.

### `GET /api/v1/auth/me` — текущий пользователь

```json
{"id": 1, "username": "admin", "full_name": "Меркулов Григорий",
 "role": "SYS_ADMIN", "role_title": "Администратор системы",
 "is_active": true, "last_login_at": "2026-09-18T19:41:07+00:00"}
```

---

## 2. Роли и права

| Роль | Чтение | Запись | Учётные записи |
|---|---|---|---|
| `SYS_ADMIN` | да | да | да |
| `FUND_ADMIN` | да | да | нет |
| `DISPATCHER` | да | да | нет |
| `OBSERVER` | да | нет | нет |
| `SERVICE` | да | нет | нет |

Нет токена — **401**. Токен есть, роль не подходит — **403**, в деталях
`your_role` и `allowed_roles`.

---

## 3. Учётные записи

Раздел доступен только роли `SYS_ADMIN`.

| Адрес | Метод | Что делает |
|---|---|---|
| `/api/v1/users` | GET | список учётных записей |
| `/api/v1/users` | POST | создать учётную запись |
| `/api/v1/users/{user_id}` | GET | одна учётная запись |
| `/api/v1/users/{user_id}` | PATCH | сменить имя, пароль, роль, блокировку |

```http
POST /api/v1/users
{"username": "ermakov", "full_name": "Ермаков Михаил",
 "password": "не-короче-8-символов", "role": "FUND_ADMIN"}
```

Пароль и его хэш в ответах не возвращаются никогда. Себе самому сменить роль
или снять признак активности нельзя — **403**.

---

## 4. Справочники

### 4.1. Подразделения

| Адрес | Метод |
|---|---|
| `/api/v1/departments` | GET, POST |
| `/api/v1/departments/{department_id}` | GET, PATCH, DELETE |

Параметры списка: `parent_id`, `q`, `page`, `page_size`.

Отказы: **409** `DEPARTMENT_CYCLE` — родитель образует цикл;
**409** `RELATED_NOT_FOUND` — ссылка на несуществующее подразделение;
**409** `HAS_DEPENDENTS` — есть дочерние подразделения или закреплённые
помещения (в деталях `children_count` или `rooms_count`).

### 4.2. Корпуса

| Адрес | Метод |
|---|---|
| `/api/v1/buildings` | GET, POST |
| `/api/v1/buildings/{building_id}` | GET, PATCH, DELETE |
| `/api/v1/buildings/{building_id}/floors` | GET |

Параметры списка: `q`, `page`, `page_size`.

```http
POST /api/v1/buildings
{"code": "A", "name": "Главный корпус", "address": "ул. Большая Семёновская, 38",
 "floors_count": 6, "has_basement": true, "passport_area": "9800.00"}
```

`GET /{id}/floors` отдаёт этажи корпуса с числом помещений — на этом построена
навигация каталога:

```json
{"building": {…}, "floors": [{"floor": -1, "rooms_count": 1}, {"floor": 1, "rooms_count": 2}]}
```

### 4.3. Типы помещений

| Адрес | Метод |
|---|---|
| `/api/v1/room-types` | GET, POST |
| `/api/v1/room-types/{room_type_id}` | PATCH, DELETE |

Список отдаётся целиком, без страниц — справочник короткий.

```json
[{"id": 3, "code": "LECTURE", "name": "Лекционная аудитория",
  "area_norm": "2.50", "is_teaching": true, "note": "Поточные занятия"}]
```

`area_norm: null` означает, что вместимость помещений этого типа не
нормируется и правило D5 к ним не применяется.

### 4.4. Дисциплины и матрица допустимости

| Адрес | Метод |
|---|---|
| `/api/v1/disciplines` | GET, POST |
| `/api/v1/disciplines/{discipline_id}` | GET, PATCH, DELETE |

Параметры списка: `q`, `page`, `page_size`.

```http
POST /api/v1/disciplines
{"code": "IB-02", "name": "Криптографические методы защиты",
 "allowed_room_type_ids": [2, 4]}
```

В ответе матрица разворачивается в полные записи типов:

```json
{"id": 7, "code": "IB-02", "name": "Криптографические методы защиты",
 "allowed_room_types": [{"id": 2, "code": "SEMINAR", …}, {"id": 4, "code": "COMPUTER", …}]}
```

`PATCH` с `allowed_room_type_ids` заменяет матрицу целиком. Ссылка на
несуществующий тип — **409** `RELATED_NOT_FOUND`.

---

## 5. Помещения

| Адрес | Метод |
|---|---|
| `/api/v1/rooms` | GET, POST |
| `/api/v1/rooms/{room_id}` | GET, PATCH, DELETE |
| `/api/v1/rooms/{room_id}/measurements` | GET, POST |
| `/api/v1/rooms/suitable` | GET |

Параметры списка: `building_id`, `floor`, `room_type_id`, `department_id`,
`is_usable`, `area_min`, `area_max`, `q`, `page`, `page_size`.

```http
POST /api/v1/rooms
{"building_id": 1, "number": "201", "floor": 2, "room_type_id": 2,
 "area": "62.50", "seats": 24, "staff_seats": 1,
 "department_id": 3, "is_usable": true}
```

Ответ **201**:

```json
{"id": 7, "building_id": 1, "number": "201", "floor": 2, "room_type_id": 2,
 "department_id": 3, "area": "62.50", "seats": 24, "staff_seats": 1,
 "volume": 25, "normative_capacity": 25, "is_usable": true, "note": null,
 "room_type": {"id": 2, "code": "SEMINAR", "area_norm": "2.50", …}}
```

- `volume` — объём помещения, вместимость в людях. **Считает база**; прислать
  это поле нельзя, запрос будет отклонён с **422**.
- `normative_capacity` — расчётная величина правила D5 для текущей площади и
  типа. `null`, если у типа не задана норма.

Отказы: **409** `D5_NORM_CAPACITY_EXCEEDED`, `FLOOR_OUT_OF_RANGE`,
`DUPLICATE_CODE`, `RELATED_NOT_FOUND`, `HAS_DEPENDENTS`.

### 5.1. История обмеров

```http
POST /api/v1/rooms/7/measurements
{"area": "70.00", "seats": 26, "staff_seats": 1,
 "measured_on": "2026-09-15", "note": "Обмер после ремонта"}
```

Новый обмер переносит значения в карточку помещения. Правило D5 проверяется и
здесь.

`GET` отдаёт историю, новые записи первыми:

```json
[{"id": 12, "room_id": 7, "area": "70.00", "seats": 26, "staff_seats": 1,
  "measured_on": "2026-09-15", "source": "MANUAL",
  "note": "Обмер после ремонта", "measured_by_name": "Ермаков Михаил"}]
```

Источник: `INITIAL` — значения при заведении карточки, `MANUAL` — внесено
человеком, `IMPORT` — загружено из XLSX (этап 3).

Записи истории не изменяются и не удаляются: попытка — **409**
`HISTORY_IMMUTABLE`. Помещение с историей удалить нельзя.

### 5.2. Подбор аудитории

```http
GET /api/v1/rooms/suitable?discipline_id=3&group_size=24&allow_overload=false
```

Параметры: `discipline_id` (обязателен), `group_size` (обязателен, ≥ 1),
`building_id`, `allow_overload`, `limit` (1…200, по умолчанию 50).

```json
{
  "discipline": {"id": 3, "code": "IB-02", "name": "Криптографические методы"},
  "group_size": 24,
  "allow_overload": false,
  "items": [
    {"id": 7, "number": "201", "floor": 2, "area": "62.50", "seats": 24,
     "volume": 25, "seats_margin": 0, "overloaded": false, "room_type": {…}}
  ],
  "rejected": {"D1_not_allowed": 7, "D2_too_small": 4, "D6_not_usable": 1}
}
```

Поле `rejected` объясняет, сколько помещений отсеяло каждое правило. Если
матрица допустимости дисциплины пуста, в ответе появляется поле `reason` с
объяснением, а `items` пуст.

---

## 6. Служебные адреса

Доступны без входа в систему.

```http
GET /healthz
→ 200 {"status": "ok"}
```

```http
GET /readyz
→ 200 {"status": "ok", "version": "0.1.0",
       "checks": {"database": "ok", "migrations": "ok: 0002_seed_reference"}}
→ 503 {"error": {"code": "DB_UNAVAILABLE", …}}
→ 503 {"error": {"code": "MIGRATIONS_NOT_APPLIED", …}}
```

```http
GET /version
→ 200 {"version": "0.1.0", "commit": "a1b2c3d", "app_env": "production"}
```

`/healthz` базы не касается и отвечает, даже когда СУБД лежит. `/readyz`
отвечает 200 только если база доступна **и** ревизия миграций накатана — на
это и опирается проверка релиза.

---

## 7. Постраничный вывод

Списки справочников и помещений возвращают конверт:

```json
{"items": [...], "total": 128, "page": 1, "page_size": 50, "pages": 3}
```

`page` меньше 1 приводится к 1, `page_size` обрезается по `PAGE_SIZE_MAX`
(по умолчанию 200).

---

## 8. Формат ответа об ошибке

Подраздел 4.1.6 ТЗ. Любой отказ:

```json
{
  "error": {"code": "D5_NORM_CAPACITY_EXCEEDED", "message": "…", "details": {…}},
  "request_id": "0f1c8d2b4e6a4c1e9b7d3a5f8c2e1d40"
}
```

`request_id` дублируется в заголовке `X-Request-Id` и пишется в журнал. Свой
идентификатор, присланный в заголовке запроса, сохраняется — так связываются
журналы смежных систем.

**Наружу не отдаются** трассировка стека, текст SQL-запросов и значения
секретов — ни при каком коде ответа.

| HTTP | Код | Когда |
|---|---|---|
| 400 | `INVALID_JSON` | тело не разбирается как JSON |
| 400 | `INVALID_QUERY_PARAM` | параметр запроса неверного вида |
| 401 | `UNAUTHENTICATED` | нет токена, токен повреждён или истёк |
| 401 | `INVALID_CREDENTIALS` | неверный логин или пароль |
| 401 | `LOGIN_TEMPORARILY_BLOCKED` | превышено число попыток входа |
| 403 | `FORBIDDEN` | роль не даёт права на операцию |
| 403 | `ACCOUNT_DISABLED` | учётная запись заблокирована |
| 404 | `NOT_FOUND` | объект или адрес не найден |
| 409 | `RELATED_NOT_FOUND` | ссылка на несуществующий связанный объект |
| 409 | `DUPLICATE_CODE` | нарушена уникальность кода или номера |
| 409 | `HAS_DEPENDENTS` | на запись ссылаются другие данные |
| 409 | `DEPARTMENT_CYCLE` | цикл в иерархии подразделений |
| 409 | `FLOOR_OUT_OF_RANGE` | такого этажа в корпусе нет |
| 409 | `HISTORY_IMMUTABLE` | попытка изменить или удалить запись истории |
| 409 | `D1_DISCIPLINE_NOT_ALLOWED` | правило D1 |
| 409 | `D2_SEATS_EXCEEDED` | правило D2 |
| 409 | `D5_NORM_CAPACITY_EXCEEDED` | правило D5 |
| 409 | `D6_ROOM_NOT_USABLE` | правило D6 |
| 413 | `FILE_TOO_LARGE` | превышен размер загружаемого файла (этап 3) |
| 422 | `VALIDATION_ERROR` | данные не прошли проверку схемы |
| 500 | `INTERNAL_ERROR` | внутренняя ошибка; подробности только в журнале |
| 503 | `DB_UNAVAILABLE` | база недоступна |
| 503 | `MIGRATIONS_NOT_APPLIED` | схема базы не накатана |

При `VALIDATION_ERROR` в `details.fields` перечислены поля и причины:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "Данные не прошли проверку",
           "details": {"fields": [{"field": "floors_count", "error": "Field required"}]}},
 "request_id": "…"}
```

Поля, которых нет в схеме, тоже отклоняются: молча игнорировать лишнее — значит
скрывать опечатку от того, кто её сделал.

---

## 9. Полный перечень адресов

| Метод | Адрес | Роль |
|---|---|---|
| POST | `/api/v1/auth/login` | без входа |
| POST | `/api/v1/auth/logout` | любая |
| GET | `/api/v1/auth/me` | любая |
| GET | `/api/v1/users` | SYS_ADMIN |
| POST | `/api/v1/users` | SYS_ADMIN |
| GET | `/api/v1/users/{user_id}` | SYS_ADMIN |
| PATCH | `/api/v1/users/{user_id}` | SYS_ADMIN |
| GET | `/api/v1/departments` | любая |
| POST | `/api/v1/departments` | запись |
| GET | `/api/v1/departments/{department_id}` | любая |
| PATCH | `/api/v1/departments/{department_id}` | запись |
| DELETE | `/api/v1/departments/{department_id}` | запись |
| GET | `/api/v1/buildings` | любая |
| POST | `/api/v1/buildings` | запись |
| GET | `/api/v1/buildings/{building_id}` | любая |
| PATCH | `/api/v1/buildings/{building_id}` | запись |
| DELETE | `/api/v1/buildings/{building_id}` | запись |
| GET | `/api/v1/buildings/{building_id}/floors` | любая |
| GET | `/api/v1/room-types` | любая |
| POST | `/api/v1/room-types` | запись |
| PATCH | `/api/v1/room-types/{room_type_id}` | запись |
| DELETE | `/api/v1/room-types/{room_type_id}` | запись |
| GET | `/api/v1/rooms` | любая |
| POST | `/api/v1/rooms` | запись |
| GET | `/api/v1/rooms/{room_id}` | любая |
| PATCH | `/api/v1/rooms/{room_id}` | запись |
| DELETE | `/api/v1/rooms/{room_id}` | запись |
| GET | `/api/v1/rooms/{room_id}/measurements` | любая |
| POST | `/api/v1/rooms/{room_id}/measurements` | запись |
| GET | `/api/v1/rooms/suitable` | любая |
| GET | `/api/v1/disciplines` | любая |
| POST | `/api/v1/disciplines` | запись |
| GET | `/api/v1/disciplines/{discipline_id}` | любая |
| PATCH | `/api/v1/disciplines/{discipline_id}` | запись |
| DELETE | `/api/v1/disciplines/{discipline_id}` | запись |
| GET | `/healthz` | без входа |
| GET | `/readyz` | без входа |
| GET | `/version` | без входа |

«Запись» — роли `SYS_ADMIN`, `FUND_ADMIN`, `DISPATCHER`.
