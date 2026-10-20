# Deploy na Railway

**O login com a conta Google do CITi (T5) é obrigatório em produção:** com `APP_ENV=prod`, o app NÃO sobe sem as
variáveis do login (abaixo). Só entra quem tem conta `@citi.org.br` ([ADR-007](adr-007-login-google.md)).

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
   - **Login (T5):** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET` (32+ caracteres aleatórios) e
     `APP_URL` (o endereço público, com `https://`, sem barra no fim). Passo a passo abaixo.
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

## Login: cliente OAuth do Google (uma vez)

1. No Google Cloud (o projeto do CITi): **APIs e serviços → Tela de consentimento OAuth**. Tipo de usuário **Interno**
   (só aparece se o projeto estiver dentro da organização Google Workspace do CITi: é o que impede conta de fora até de
   chegar na tela). Nome do app: "Cérebro Comercial CITi"; e-mail de suporte; salvar. Escopos padrão (`openid`, e-mail e
   perfil) bastam.
2. **Credenciais → Criar credenciais → ID do cliente OAuth → Aplicativo da Web.** Em **URIs de redirecionamento
   autorizados** ponha os dois: `http://localhost:8000/auth/callback` (para testar no computador) e
   `https://<o-domínio-da-railway>/auth/callback`. Copie o **ID do cliente** e o **Segredo**.
3. Gere o segredo da sessão: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
4. No `.env` do computador: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (e `APP_URL=http://localhost:8000`). Na Railway:
   as quatro variáveis do passo 3 da seção acima.
5. Abra o app: aparece a tela de entrada. Entre com a conta do CITi. Uma conta pessoal (@gmail) tem que ser recusada.

Se o projeto não estiver dentro da organização (tipo **Externo**, em modo de teste), o app continua só aceitando
`@citi.org.br`, porque quem decide é o servidor, mas o Google só deixa entrar quem está na lista de usuários de teste.

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

- ~~Login do time (T5)~~: feito (ADR-007). Continua importante: o banco guarda o texto integral dos documentos do
  Drive, sem mascarar. Só abra o domínio para o time depois de conferir que uma conta de fora é recusada.
- A busca nos documentos funciona igual no SQLite e no Postgres (BM25 em Python, ver o ADR-006); não depende de
  `tsvector`. Reavaliar se o acervo passar de alguns milhares de pedaços.
