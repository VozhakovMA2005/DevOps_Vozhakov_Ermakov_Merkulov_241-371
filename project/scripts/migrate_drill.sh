#!/usr/bin/env bash
# Учения по миграциям — пункт 9 задания.
#
# Проверяется два разных случая, и второй важнее первого.
#
#   1. ЧИСТАЯ БАЗА. Накат с нуля до последней ревизии, затем alembic check:
#      схема обязана совпадать с моделями. Это ловит ситуацию «модель поменяли,
#      миграцию забыли».
#
#   2. БАЗА С ДАННЫМИ. Схема поднимается до состояния предыдущего этапа,
#      заполняется данными, и только потом накатываются новые миграции.
#      Проверяется, что данные на месте и не изменились. Это ловит миграцию,
#      которая на пустой базе проходит, а на заполненной теряет данные —
#      например столбец NOT NULL без значения по умолчанию.
#
#   3. ПОЛНЫЙ ОТКАТ И ПОВТОРНЫЙ НАКАТ. Требование ТЗ 4.6: каждая миграция
#      содержит механизмы накатывания и полного отката.
#
# Обе базы — временные, создаются и удаляются сценарием. Боевую базу он не
# трогает: имена баз получают признак drill и метку времени.
#
# Нужна роль с правом создавать базы — та же, что и для набора тестов:
#
#   ADMIN_DATABASE_URL=postgresql://postgres@localhost:5432/postgres \
#     bash scripts/migrate_drill.sh
#
# Роль приложения создавать базы не может и не должна (ТЗ 4.4).

. "$(dirname "$0")/lib.sh"

require_command psql "Поставьте postgresql-client."
load_admin_env

CLEAN_ONLY=0
[ "${1:-}" = "--clean-only" ] && CLEAN_ONLY=1

PY="$(python_bin)"
STAMP="$(date +%s)"
CLEAN_DB="audfond_drill_clean_$STAMP"
FILLED_DB="audfond_drill_filled_$STAMP"

#: Ревизия, на которой закончился предыдущий этап. С неё начинается проверка
#: наката на заполненную базу
BASE_REVISION="${BASE_REVISION:-0002_seed_reference}"

cleanup() {
    for name in "$CLEAN_DB" "$FILLED_DB"; do
        psql -q -d postgres -c "DROP DATABASE IF EXISTS \"$name\"" >/dev/null 2>&1 || true
    done
}
trap cleanup EXIT

alembic_on() {
    local database="$1"; shift
    ( cd "$ROOT" && DATABASE_URL="$(database_url_for "$database")" "$PY" -m alembic "$@" )
}

psql_on() {
    local database="$1"; shift
    psql -q -t -A -d "$database" "$@"
}

# --------------------------------------------------------------------------- #
step "1. Чистая база: накат с нуля"
# --------------------------------------------------------------------------- #
psql -q -d postgres -c "CREATE DATABASE \"$CLEAN_DB\"" >/dev/null
info "создана $CLEAN_DB"

alembic_on "$CLEAN_DB" upgrade head >/dev/null
REVISIONS="$(alembic_on "$CLEAN_DB" history 2>/dev/null | grep -c ' -> ' || true)"
ok "накатано ревизий: $REVISIONS, схема на head"

info "сверка схемы с моделями (alembic check)"
if alembic_on "$CLEAN_DB" check 2>&1 | grep -q "No new upgrade operations detected"; then
    ok "схема совпадает с моделями"
else
    alembic_on "$CLEAN_DB" check || true
    die "Схема расходится с моделями: модель изменили, миграцию не добавили"
fi

TABLES="$(psql_on "$CLEAN_DB" -c "
    SELECT count(*) FROM information_schema.tables
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")"
ok "таблиц в схеме: $TABLES"

# --------------------------------------------------------------------------- #
step "2. Полный откат и повторный накат"
# --------------------------------------------------------------------------- #
alembic_on "$CLEAN_DB" downgrade base >/dev/null
LEFTOVERS="$(psql_on "$CLEAN_DB" -c "
    SELECT count(*) FROM information_schema.tables
     WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
       AND table_name <> 'alembic_version'")"
[ "$LEFTOVERS" = "0" ] || die "После полного отката осталось таблиц: $LEFTOVERS"

TYPES="$(psql_on "$CLEAN_DB" -c "
    SELECT count(*) FROM pg_type t
      JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE n.nspname = 'public' AND t.typtype = 'e'")"
[ "$TYPES" = "0" ] || die "После отката остались перечисления: $TYPES. Их нужно удалять явно"
ok "откат полный: ни таблиц, ни перечислений не осталось"

alembic_on "$CLEAN_DB" upgrade head >/dev/null
ok "повторный накат прошёл — миграции обратимы (ТЗ 4.6)"

if [ "$CLEAN_ONLY" = "1" ]; then
    step "Итог"
    ok "чистая база: накат с нуля, схема совпадает с моделями"
    ok "обратимость: полный откат и повторный накат"
    info "часть «база с данными» пропущена по ключу --clean-only"
    info "полная проверка: make migrate-drill"
    exit 0
fi

# --------------------------------------------------------------------------- #
step "3. База с данными: накат новых миграций поверх"
# --------------------------------------------------------------------------- #
psql -q -d postgres -c "CREATE DATABASE \"$FILLED_DB\"" >/dev/null
info "создана $FILLED_DB"

alembic_on "$FILLED_DB" upgrade "$BASE_REVISION" >/dev/null
ok "схема поднята до состояния предыдущего этапа ($BASE_REVISION)"

info "заполняю данными"
psql_on "$FILLED_DB" >/dev/null <<'SQL'
INSERT INTO department (code, name) VALUES ('DRILL', 'Подразделение для учений');
INSERT INTO building (code, name, address, floors_count, has_basement, passport_area)
VALUES ('DR', 'Корпус для учений', 'ул. Проверочная, 1', 3, false, 1000.00);
INSERT INTO room (building_id, number, floor, room_type_id, area, seats, staff_seats, is_usable)
SELECT b.id, '101', 1, t.id, 60.00, 20, 1, true
  FROM building b, room_type t WHERE b.code = 'DR' AND t.code = 'SEMINAR';
INSERT INTO room (building_id, number, floor, room_type_id, area, seats, staff_seats, is_usable)
SELECT b.id, '102', 1, t.id, 45.00, 15, 1, true
  FROM building b, room_type t WHERE b.code = 'DR' AND t.code = 'SEMINAR';
SQL

ROOMS_BEFORE="$(psql_on "$FILLED_DB" -c "SELECT count(*) FROM room")"
VOLUME_BEFORE="$(psql_on "$FILLED_DB" -c "SELECT coalesce(sum(volume), 0) FROM room")"
info "помещений: $ROOMS_BEFORE, суммарный объём: $VOLUME_BEFORE человек"

info "накатываю оставшиеся миграции на заполненную базу"
alembic_on "$FILLED_DB" upgrade head >/dev/null

ROOMS_AFTER="$(psql_on "$FILLED_DB" -c "SELECT count(*) FROM room")"
VOLUME_AFTER="$(psql_on "$FILLED_DB" -c "SELECT coalesce(sum(volume), 0) FROM room")"
[ "$ROOMS_BEFORE" = "$ROOMS_AFTER" ] \
    || die "Данные потеряны: было помещений $ROOMS_BEFORE, стало $ROOMS_AFTER"
[ "$VOLUME_BEFORE" = "$VOLUME_AFTER" ] \
    || die "Данные изменились: объём был $VOLUME_BEFORE, стал $VOLUME_AFTER"
ok "данные на месте и не изменились: помещений $ROOMS_AFTER, объём $VOLUME_AFTER"

NEW_COLUMN="$(psql_on "$FILLED_DB" -c "
    SELECT count(*) FROM information_schema.columns
     WHERE table_name = 'room' AND column_name = 'import_job_id'")"
[ "$NEW_COLUMN" = "1" ] || die "Новый столбец room.import_job_id не появился"

NULLS="$(psql_on "$FILLED_DB" -c "SELECT count(*) FROM room WHERE import_job_id IS NULL")"
ok "новый столбец добавлен, у прежних помещений он пуст ($NULLS из $ROOMS_AFTER) — это верно:"
info "   они заведены вручную, а не импортом"

info "откат заполненной базы до предыдущего этапа и накат обратно"
alembic_on "$FILLED_DB" downgrade "$BASE_REVISION" >/dev/null
ROOMS_ROLLED="$(psql_on "$FILLED_DB" -c "SELECT count(*) FROM room")"
[ "$ROOMS_BEFORE" = "$ROOMS_ROLLED" ] \
    || die "Откат потерял данные: было $ROOMS_BEFORE, стало $ROOMS_ROLLED"
alembic_on "$FILLED_DB" upgrade head >/dev/null
ok "откат и накат на заполненной базе данных не теряют"

step "Итог"
ok "чистая база: накат с нуля, схема совпадает с моделями"
ok "обратимость: полный откат и повторный накат"
ok "заполненная база: новые миграции данных не теряют"
info "временные базы удалены"
