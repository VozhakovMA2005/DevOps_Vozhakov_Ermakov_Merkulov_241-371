-- Права внутри базы audfond. Выполняется ПОСЛЕ наката миграций,
-- потому что раздаёт права на уже созданные таблицы и последовательности.

\set ON_ERROR_STOP on

-- Подключиться к базе может только приложение и владелец схемы.
-- PUBLIC — это «любая роль в кластере», и по умолчанию ей можно слишком много.
REVOKE ALL ON DATABASE audfond FROM PUBLIC;
GRANT CONNECT ON DATABASE audfond TO af_app;

ALTER SCHEMA public OWNER TO af_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO af_app;   -- видеть объекты, но не создавать

-- Приложению — работа с данными и ничего больше
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO af_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO af_app;

-- То же для таблиц, которые создадут будущие миграции: иначе после
-- каждого обновления схемы права пришлось бы раздавать заново
ALTER DEFAULT PRIVILEGES FOR ROLE af_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO af_app;
ALTER DEFAULT PRIVILEGES FOR ROLE af_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO af_app;
