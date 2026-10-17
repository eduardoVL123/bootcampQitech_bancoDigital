-- ============================================================
-- O banco do antifraude Pix (antifraud-api)
-- ============================================================
--
-- Um banco proprio, ao lado do `bootcamp` da fase 1, no mesmo container.
-- O antifraude nao le nenhuma tabela do banco digital: tudo de que ele
-- precisa chega no payload ou e o historico que ele mesmo gravou.
--
-- Este arquivo roda uma vez so, quando o volume do Postgres nasce (o
-- Dockerfile o copia como 02.sql, depois do 01.sql da fase 1). Mudou
-- alguma coisa aqui: docker compose down -v.

CREATE DATABASE antifraud;

\connect antifraud
