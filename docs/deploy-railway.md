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
   - **Drive (T6):** `DRIVE_PASTA_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` (o **conteúdo** inteiro do JSON da conta de
     serviço, não o caminho) e `DRIVE_SYNC_INTERVALO_MIN=15` para o servidor sincronizar a pasta sozinho
     (0 desliga). Passo a passo da conta de serviço abaixo.
4. Aba **Settings → Networking → Generate Domain**.
5. Abra `https://<o-domínio>/health`: deve responder `{"status":"ok"}`.

## O que testamos antes

As migrações sobem, descem e sobem de novo num Postgres 16 de verdade, `alembic check` não aponta diferença, e a API
(Fila, aprovar, Fontes) responde igual ao SQLite. Para repetir: aponte `DATABASE_URL` para um Postgres local e rode
`alembic upgrade head && alembic check`.

## Drive: conta de serviço (uma vez)

1. No Google Cloud (projeto do CITi): **APIs e serviços → Biblioteca → Google Drive API → Ativar**.
2. **IAM → Contas de serviço → Criar** (ex.: `cerebro-drive`). Sem papéis. Em **Chaves → Adicionar chave → JSON**:
   baixa o arquivo. É uma senha: não vai para o Git (o `.gitignore` já barra `service-account*.json`).
3. No Drive, **compartilhe a pasta "Conhecimento Comercial"** com o e-mail da conta de serviço
   (`...@...iam.gserviceaccount.com`) como **Leitor**. De preferência a pasta fica num drive compartilhado do CITi.
4. No computador: `GOOGLE_APPLICATION_CREDENTIALS=<caminho do JSON>` e `DRIVE_PASTA_ID=<id da pasta>` no `.env`.
   Na Railway: `GOOGLE_SERVICE_ACCOUNT_JSON` com o conteúdo do arquivo.
5. Conferir sem gastar: `python -m scripts.sincronizar_drive --dry-run` e `pytest -m live tests/live`.
6. Sincronizar de verdade: `python -m scripts.sincronizar_drive` (ou o botão na tela de Fontes, escolhendo **Drive**).

## O que ainda falta para o dado real

- Login do time (T5). Agora mais importante: o banco guarda o texto integral dos documentos do Drive, sem mascarar.
- A busca nos documentos funciona igual no SQLite e no Postgres (BM25 em Python, ver o ADR-006); não depende de
  `tsvector`. Reavaliar se o acervo passar de alguns milhares de pedaços.
