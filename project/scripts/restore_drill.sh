#!/usr/bin/env bash
# Учения по восстановлению — пункт 12 задания, ТЗ 4.2.
#
# «Резервная копия, которую ни разу не разворачивали, — это не копия».
# Сценарий проверяет весь путь целиком и на настоящих командах:
#
#   1. поднимает одноразовую базу и заполняет её известными данными
#   2. снимает копию теми же scripts/backup.sh, что и в бою
#   3. ПОРТИТ данные: удаляет помещения и подменяет название корпуса
#   4. убеждается, что данные действительно испорчены
#   5. восстанавливает теми же scripts/restore.sh
#   6. сверяет всё до последней записи с состоянием до порчи
#
# Боевую базу сценарий не трогает: он работает на временной базе с меткой
# времени в имени и удаляет её за собой.
#
#   ADMIN_DATABASE_URL=postgresql://postgres@localhost:5432/postgres \
#     bash scripts/restore_drill.sh

. "$(dirname "$0")/lib.sh"

require_command pg_dump "Поставьте postgresql-client."
require_command pg_restore "Поставьте postgresql-client."
load_admin_env

PY="$(python_bin)"
STAMP="$(date +%s)"
DRILL_DB="audfond_drill_restore_$STAMP"
DRILL_URL="$(database_url_for "$DRILL_DB")"
BACKUP_FILE=""

cleanup() {
    psql -q -d postgres -c "DROP DATABASE IF EXISTS \"$DRILL_DB\"" >/dev/null 2>&1 || true
    [ -n "$BACKUP_FILE" ] && rm -f "$BACKUP_FILE"
}
trap cleanup EXIT

sql() { psql -q -t -A -d "$DRILL_DB" "$@"; }

# --------------------------------------------------------------------------- #
step "1. Одноразовая база с известными данными"
# --------------------------------------------------------------------------- #
psql -q -d postgres -c "CREATE DATABASE \"$DRILL_DB\"" >/dev/null
info "создана $DRILL_DB"

( cd "$ROOT" && DATABASE_URL="$DRILL_URL" "$PY" -m alembic upgrade head >/dev/null 2>&1 )
ok "схема накатана до последней ревизии"

sql >/dev/null <<'SQL'
INSERT INTO department (code, name) VALUES ('DRILL', 'Подразделение для учений');
INSERT INTO building (code, name, address, floors_count, has_basement, passport_area)
VALUES ('DR', 'Корпус для учений', 'ул. Проверочная, 1', 4, false, 2000.00);
INSERT INTO room (building_id, number, floor, room_type_id, area, seats, staff_seats, is_usable)
SELECT b.id, lpad(gs::text, 3, '0'), 1 + (gs % 3), t.id, 50.00 + gs, 15 + gs, 1, true
  FROM generate_series(1, 12) AS gs, building b, room_type t
 WHERE b.code = 'DR' AND t.code = 'SEMINAR';
INSERT INTO room_measurement (room_id, area, seats, staff_seats, measured_on, source, note)
SELECT r.id, r.area, r.seats, r.staff_seats, CURRENT_DATE, 'INITIAL', 'учения'
  FROM room r;
SQL

ROOMS_BEFORE="$(sql -c "SELECT count(*) FROM room")"
HISTORY_BEFORE="$(sql -c "SELECT count(*) FROM room_measurement")"
VOLUME_BEFORE="$(sql -c "SELECT coalesce(sum(volume), 0) FROM room")"
NAME_BEFORE="$(sql -c "SELECT name FROM building WHERE code = 'DR'")"
CHECKSUM_BEFORE="$(sql -c "
    SELECT md5(string_agg(number || ':' || area || ':' || volume, ',' ORDER BY number))
      FROM room")"

ok "помещений $ROOMS_BEFORE, записей истории $HISTORY_BEFORE, объём $VOLUME_BEFORE"
info "контрольная сумма данных: ${CHECKSUM_BEFORE:0:16}…"

# --------------------------------------------------------------------------- #
step "2. Резервная копия"
# --------------------------------------------------------------------------- #
DATABASE_URL="$DRILL_URL" bash "$ROOT/scripts/backup.sh" --keep 50
BACKUP_FILE="$(ls -1t "$ROOT"/backups/audfond-"$DRILL_DB"-*.dump | head -1)"
[ -n "$BACKUP_FILE" ] || die "Копия не создана"
ok "копия снята: $(basename "$BACKUP_FILE")"

# --------------------------------------------------------------------------- #
step "3. Порча данных"
# --------------------------------------------------------------------------- #
# Два разных вида порчи: потеря строк и тихая подмена значения. Второй опаснее:
# база остаётся работоспособной, а данные неверны
sql >/dev/null <<'SQL'
DELETE FROM room_measurement;
DELETE FROM room WHERE (id % 2) = 0;
UPDATE building SET name = 'ИСПОРЧЕНО' WHERE code = 'DR';
UPDATE room SET area = 1.00, seats = 0 WHERE (id % 3) = 0;
SQL

ROOMS_BROKEN="$(sql -c "SELECT count(*) FROM room")"
NAME_BROKEN="$(sql -c "SELECT name FROM building WHERE code = 'DR'")"
info "после порчи: помещений $ROOMS_BROKEN, название корпуса «$NAME_BROKEN»"

[ "$ROOMS_BROKEN" != "$ROOMS_BEFORE" ] || die "Порча не состоялась — учения бессмысленны"
[ "$NAME_BROKEN" = "ИСПОРЧЕНО" ] || die "Подмена названия не состоялась"
ok "данные действительно испорчены: строки удалены, значения подменены"

# --------------------------------------------------------------------------- #
step "4. Восстановление"
# --------------------------------------------------------------------------- #
DATABASE_URL="$DRILL_URL" bash "$ROOT/scripts/restore.sh" --yes "$BACKUP_FILE"

# --------------------------------------------------------------------------- #
step "5. Сверка с состоянием до порчи"
# --------------------------------------------------------------------------- #
ROOMS_AFTER="$(sql -c "SELECT count(*) FROM room")"
HISTORY_AFTER="$(sql -c "SELECT count(*) FROM room_measurement")"
VOLUME_AFTER="$(sql -c "SELECT coalesce(sum(volume), 0) FROM room")"
NAME_AFTER="$(sql -c "SELECT name FROM building WHERE code = 'DR'")"
CHECKSUM_AFTER="$(sql -c "
    SELECT md5(string_agg(number || ':' || area || ':' || volume, ',' ORDER BY number))
      FROM room")"

compare() {
    local what="$1" before="$2" after="$3"
    if [ "$before" = "$after" ]; then
        ok "$what: $after — совпадает"
    else
        die "$what не восстановлено: было «$before», стало «$after»"
    fi
}

compare "помещений" "$ROOMS_BEFORE" "$ROOMS_AFTER"
compare "записей истории обмеров" "$HISTORY_BEFORE" "$HISTORY_AFTER"
compare "суммарный объём" "$VOLUME_BEFORE" "$VOLUME_AFTER"
compare "название корпуса" "$NAME_BEFORE" "$NAME_AFTER"
compare "контрольная сумма данных" "$CHECKSUM_BEFORE" "$CHECKSUM_AFTER"

step "6. Схема после восстановления"
REVISION="$( cd "$ROOT" && DATABASE_URL="$DRILL_URL" "$PY" -m alembic current 2>/dev/null | tail -1 )"
info "ревизия: $REVISION"
CHECK="$( cd "$ROOT" && DATABASE_URL="$DRILL_URL" "$PY" -m alembic check 2>&1 | tail -1 )"
case "$CHECK" in
    *"No new upgrade operations detected"*) ok "схема совпадает с моделями" ;;
    *) die "После восстановления схема расходится с моделями: $CHECK" ;;
esac

step "Итог"
ok "копия снята, данные испорчены, восстановление вернуло их полностью"
info "временная база и файл копии удалены"
