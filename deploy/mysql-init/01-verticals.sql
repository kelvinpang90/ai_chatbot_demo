-- The verticals' own database, for the local stand-in MySQL only.
--
-- The mysql:8 image creates exactly one database from MYSQL_DATABASE, and the
-- verticals want a second one (see app/config.py on why it is not the audit
-- log's). Anything in /docker-entrypoint-initdb.d runs once, on an empty data
-- directory, which is what this throwaway container always has.
--
-- On the VPS the equivalent is one grant run by hand, recorded in
-- backend/.env.example next to VERTICALS_MYSQL_URL. Nothing here reaches
-- production: docker-compose.prod.yml has no MySQL of its own.
CREATE DATABASE IF NOT EXISTS ai_chatbot_verticals
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON `ai_chatbot_verticals`.* TO 'chatbot'@'%';
FLUSH PRIVILEGES;
