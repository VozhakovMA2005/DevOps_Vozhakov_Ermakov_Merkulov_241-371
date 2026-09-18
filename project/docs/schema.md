# Схема данных

PostgreSQL 17. Схема ведётся миграциями Alembic; ручные изменения структуры
запрещены (ТЗ 4.3.2, 7.2).

## Сущности этапа 1

```
app_user ──────┐
               │ measured_by
               ↓
building ──< room >── room_type ──< discipline_room_type >── discipline
   │           │           ↑
   │           │           └── норма площади на человека (правило D5)
   │           ├──< room_measurement
   │           │
department ────┘ (закрепление помещения за подразделением)
   └──< department (иерархия: родитель — дети)
```

Восемь таблиц: `app_user`, `department`, `building`, `room_type`, `room`,
`room_measurement`, `discipline`, `discipline_room_type`.

---

## Таблицы

### `app_user` — учётные записи

| Поле | Тип | Примечание |
|---|---|---|
| `id` | integer PK | |
| `username` | varchar(50) | уникален (`uq_app_user_username`) |
| `full_name` | varchar(150) | |
| `password_hash` | varchar(255) | Argon2id, соль внутри строки хэша |
| `role` | user_role | SYS_ADMIN, FUND_ADMIN, DISPATCHER, OBSERVER, SERVICE |
| `is_active` | boolean | заблокированная запись не входит |
| `failed_attempts` | integer | счётчик неудачных попыток подряд |
| `locked_until` | timestamptz | до какого момента вход закрыт |
| `last_login_at` | timestamptz | |

Пароль в открытом виде не хранится и в ответах API не встречается.

### `department` — подразделения

Иерархия «родитель — дети» через `parent_id`. `ck_department_not_self_parent`
запрещает прямое самородительство; циклы длиннее одного шага проверяет
приложение, обходя цепочку вверх.

### `building` — корпуса

`code` уникален, `floors_count` от 1 до 100, `has_basement` разрешает этаж −1.
Этаж 0 не используется никогда.

### `room_type` — типы помещений

`area_norm numeric(6,2)` — норма площади на одного человека, основа правила D5.
`NULL` означает, что вместимость не нормируется (служебные помещения).
`is_teaching` отмечает учебные типы.

Начальные значения приходят миграцией `0002_seed_reference`: без справочника
типов нельзя завести ни одного помещения.

### `room` — помещения

| Поле | Тип | Примечание |
|---|---|---|
| `building_id` | FK → building | ON DELETE RESTRICT |
| `number` | varchar(30) | уникален внутри корпуса (`uq_room_building_number`) |
| `floor` | smallint | `ck_room_floor_not_zero` |
| `room_type_id` | FK → room_type | RESTRICT |
| `department_id` | FK → department, NULL | закрепление |
| `area` | numeric(9,2) | `ck_room_area_positive` |
| `seats` | integer | места для обучающихся |
| `staff_seats` | integer | места для сотрудников |
| `volume` | integer | **GENERATED ALWAYS AS (seats + staff_seats) STORED** |
| `is_usable` | boolean | правило D6 |

Площади — `numeric`, а не `float`: копейки квадратных метров не должны
плавать. В JSON уходят строкой с двумя знаками.

### `room_measurement` — история обмеров

Площадь, места, дата обмера, автор (`measured_by_id` → `app_user`) и источник
(`MANUAL`, `IMPORT`, `INITIAL`). Записи не изменяются и не удаляются: попытка
удалить возвращает `HISTORY_IMMUTABLE`. Помещение с историей удалить нельзя.

### `discipline` и `discipline_room_type`

Справочник дисциплин и матрица допустимости — связь «многие ко многим» с
`room_type`. Основа правила D1. При удалении дисциплины строки матрицы удаляются
каскадом, при попытке удалить используемый тип помещения — отказ.

---

## Ограничения целостности

Удаление записи, на которую ссылаются другие, запрещено (`ON DELETE RESTRICT` —
ТЗ 4.1.5). Приложение перехватывает это раньше базы и объясняет отказ:

```json
{"error": {"code": "HAS_DEPENDENTS",
           "message": "В корпусе A есть помещения (14), удаление запрещено",
           "details": {"building_id": 1, "rooms_count": 14}}}
```

Имена ограничений базы сопоставлены с понятными сообщениями в
`app/errors.py`, `CONSTRAINT_ERRORS`. Текст SQL наружу не уходит.

---

## Миграции

| Ревизия | Что делает |
|---|---|
| `0001_initial` | все восемь таблиц, перечисления, индексы, ограничения |
| `0002_seed_reference` | начальные типы помещений с нормами площади |

Каждая миграция обратима: `make migrate-check` прогоняет
`upgrade → downgrade → upgrade` и завершает `alembic check`.
