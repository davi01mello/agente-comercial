# Deploy na Railway

**Antes de publicar com dado real: o login (T5) precisa existir.** Hoje o app não tem autenticação: quem tiver o link
lê a base e aprova itens. Dá para publicar para testar a infraestrutura, mas sem importar o Notion de verdade.

## Como o app sobe

`railway.json` (na raiz) manda a Railway rodar `alembic upgrade head && uvicorn ...` e conferir `/health`. As
migrações rodam em todo deploy; o que já foi aplicado não repete. A versão do Python vem de `.python-version` (3.11).

## Passo a passo (uma vez)

1. No workspace **do CITi** na Railway: **New Project → Deploy from GitHub repo** → `agente-comercial`.
2. No mesmo projeto: **New → Database → PostgreSQL**. O SQLite não serve em produção: o disco do serviço é
   apagado a cada deploy.
3. No serviço do app, aba **Variables**:
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (referência ao banco; o app troca o prefixo para o driver certo)
   - `GEMINI_API_KEY` (a chave **paga**), `APP_ENV=prod`
   - `NOTION_TOKEN` só se a importação rodar no servidor (hoje roda na máquina do Davi)
4. Aba **Settings → Networking → Generate Domain**.
5. Abra `https://<o-domínio>/health`: deve responder `{"status":"ok"}`.

## O que testamos antes

As migrações sobem, descem e sobem de novo num Postgres 16 de verdade, `alembic check` não aponta diferença, e a API
(Fila, aprovar, Fontes) responde igual ao SQLite. Para repetir: aponte `DATABASE_URL` para um Postgres local e rode
`alembic upgrade head && alembic check`.

## O que ainda falta para o dado real

- Login do time (T5).
- A busca nos documentos do Drive (T6) precisa funcionar no Postgres (`tsvector`), não só no SQLite.
