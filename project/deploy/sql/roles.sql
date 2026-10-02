-- Роли и права базы AudFond. Пункт 6 задания: отдельный пользователь
-- приложения с минимально необходимыми правами.
--
-- Ролей две, и это осознанно:
--   af_owner — владелец схемы. Под ним и только под ним выполняются миграции.
--   af_app   — приложение. Читает и пишет данные, менять схему не может.
--
-- Поэтому даже если приложение захватят, уронить таблицу или подменить
-- схему через него нельзя: прав нет на уровне СУБД, а не на уровне кода.
--
-- Пароли подставляет скрипт 02-db-server.sh через psql -v. В файле их нет.

\set ON_ERROR_STOP on

-- Роли создаются один раз; повторный запуск скрипта только обновит пароль
SELECT 'CREATE ROLE af_owner LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'af_owner') \gexec
SELECT 'CREATE ROLE af_app LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'af_app') \gexec

ALTER ROLE af_owner WITH PASSWORD :'owner_password';
ALTER ROLE af_app   WITH PASSWORD :'app_password';

-- Ни одна из ролей не является суперпользователем и не создаёт другие роли
ALTER ROLE af_owner NOSUPERUSER NOCREATEROLE NOCREATEDB INHERIT;
ALTER ROLE af_app   NOSUPERUSER NOCREATEROLE NOCREATEDB INHERIT;

SELECT 'CREATE DATABASE audfond OWNER af_owner'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'audfond') \gexec
