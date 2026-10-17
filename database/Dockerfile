# Imagem oficial e publica do PostgreSQL.
FROM postgres:16

# Todo arquivo .sql colocado aqui roda sozinho quando o banco nasce.
# E assim que as tabelas do projeto sao criadas.
COPY database.sql /docker-entrypoint-initdb.d/01.sql

# O banco proprio do antifraude Pix. Roda depois do 01.sql (a ordem e a do
# nome) e cria o banco `antifraud` ao lado do `bootcamp`.
COPY antifraud.sql /docker-entrypoint-initdb.d/02.sql
