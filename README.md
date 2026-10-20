# Cérebro Comercial CITi

Chat + playbook vivo para acumular e consultar o conhecimento comercial do CITi.
Você joga um insight solto no chat, o agente estrutura e propõe onde ele entra no playbook,
um humano aprova. Depois, qualquer pessoa pergunta ao "consultor", que responde com base na
base de conhecimento (playbook, Notion, Drive), citando as fontes.

Ideia completa, modelo de dados e decisões: pasta `docs/`.

## Rodando localmente

Pré-requisitos: Python 3.11+ e Git. Chave da API do Gemini: aistudio.google.com/apikey.

**Mac / Linux**

```bash
git clone https://github.com/davi01mello/agente-comercial.git
cd agente-comercial
python3.11 -m venv .venv      # use python3.11 explícito: o python3 do Mac costuma ser 3.9
source .venv/bin/activate     # o terminal passa a mostrar (.venv)
pip install -r requirements.txt
cp .env.example .env          # depois edite o .env e coloque a GEMINI_API_KEY
alembic upgrade head          # cria/atualiza as tabelas do banco
uvicorn app.main:app --reload
```

**Windows**

```powershell
git clone https://github.com/davi01mello/agente-comercial.git
cd agente-comercial
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # depois edite o .env e coloque a GEMINI_API_KEY
alembic upgrade head          # cria/atualiza as tabelas do banco
uvicorn app.main:app --reload
```

Abra http://127.0.0.1:8000 (chat com o consultor) e http://127.0.0.1:8000/docs (documentação automática da API).

### Interface

A página inicial tem cinco telas: **Conversar** (consultor), **Registrar** (curador e rascunho), **Fila** (aprovar ou
rejeitar), **Playbook** (itens validados na ordem do funil) e **Briefing** (prévia da T9). Fica tudo em
`app/templates/index.html`, `app/static/cerebro.css` e `app/static/cerebro.js`, sem framework e sem build.

- Com o servidor no ar, a interface usa a API de verdade (selo **Ao vivo** no topo).
- Sem servidor, ou com `?demo` na URL (`http://127.0.0.1:8000/?demo`), entra no modo **Demonstração**, com a base de
  exemplo fictícia e respostas simuladas. Serve para mostrar o produto sem chave do Gemini.
- Aprovar e rejeitar chamam `POST /insights/{id}/aprovar` (sem corpo) e `POST /insights/{id}/rejeitar` (corpo
  `{"motivo"}`). Quem aprova, registra ou rejeita é a **pessoa logada** (T5): o servidor pega o nome da sessão.
- **Login (T5):** só entra quem tem conta Google `@citi.org.br`. No dev, sem `GOOGLE_CLIENT_ID` no `.env`, o login fica
  desligado e você entra como "Dev local". Para testar o login de verdade, siga "Login: cliente OAuth do Google" em
  [docs/deploy-railway.md](docs/deploy-railway.md). Em produção (`APP_ENV=prod`) o app não sobe sem ele
  ([ADR-007](docs/adr-007-login-google.md)).
- Todo texto do usuário ou do modelo entra na página como texto, nunca como HTML (há um teste que garante isso).

Se mudar o `.env`, reinicie o servidor (o `--reload` só observa arquivos `.py`).

Testes: `pytest` (cada execução cria um banco temporário novo pelas migrações). Lint: `ruff check .`

Golden set do consultor (chama o Gemini de verdade e gasta cota, por isso fica fora do `pytest` normal e do CI):
`pytest -m live tests/golden`. As respostas da rodada ficam em `tests/golden/ultima_execucao.md` (fora do Git).

### Importar o Notion (T4)

Traz as páginas do Notion compartilhadas com a integração interna para a tabela `fontes` (o "staging"), sem misturar
com o que o time aprovou. Decisões no `docs/adr-005-importacao-notion.md`.

1. Coloque o token da integração no `.env` (`NOTION_TOKEN=`, nunca no chat). A integração só enxerga as páginas
   compartilhadas com ela: no Notion, ••• → Connections → a integração. As subpáginas vão junto.
2. Primeiro, uma simulação (não muda nenhuma fonte e não chama o modelo; só a execução fica registrada):

   ```bash
   python -m scripts.importar_notion --dry-run
   ```

3. Depois, de verdade, com o curador. Precisa de `GEMINI_API_KEY` com a **chave paga** (veja abaixo). O teto padrão
   é US$ 1; `--teto-usd 0.50` muda, e `--limite-paginas N` lê só as N primeiras:

   ```bash
   python -m scripts.importar_notion
   ```

   O curador propõe um item por trecho, e os itens entram na Fila como `historico_a_validar`, com o link da página.
   Se o próximo passo não couber no teto, ele para, e a próxima execução continua de onde parou.

4. **Ou pela API**, com o servidor no ar (também em http://127.0.0.1:8000/docs). As opções são as mesmas do script:

   ```bash
   curl -s -X POST http://127.0.0.1:8000/fontes/sincronizar -H 'content-type: application/json' -d '{"origem":"notion","dry_run":true}'
   ```

   - A resposta (202) traz o `execucao_id`, e a importação roda em segundo plano. Para acompanhar, use
     `GET /fontes/execucoes/{id}`, que mostra o status, a fase, as contagens (atualizadas a cada página), o gasto e o
     teto.
   - Corpo: `origem` (`"notion"`), `dry_run` (padrão `false`), `limite_paginas` e `teto_usd` (padrão 1.0).
   - **409** se já houver uma importação de verdade rodando. **503** se faltar o `NOTION_TOKEN`, ou a `GEMINI_API_KEY`
     fora do dry-run.
   - Se o servidor cair no meio de uma execução, ela vira `erro` ("interrompida") na próxima subida. O que já tinha
     entrado fica, e a próxima execução continua de onde parou.
   - Não rode o script e a API ao mesmo tempo: o 409 só vale para a API.

- **Triagem:** página com e-mail, CPF, CNPJ ou telefone (no título ou no texto) **nunca** vai ao modelo e o texto dela
  não é guardado; página sem texto, duplicata exata de outra ou longa demais (mais de 5 trechos de 8.000 caracteres)
  também é pulada. O relatório e a coluna `motivo` (a tela de Fontes mostra) dizem o porquê, sem repetir o dado.
- **Rodar de novo não duplica nada:** página com a mesma data de edição nem é relida, e página relida com o mesmo
  texto não gera nada novo. Página que saiu do Notion vira `removida` (nada é apagado). Quando uma página muda ou sai,
  os itens dela que ninguém revisou viram `obsoleto`; os já aprovados não mudam.
- **Conteúdo real do comercial só com a chave PAGA do Gemini** (decisão do Davi): na camada gratuita o Google pode usar
  e ler o que enviamos. O `.env` da importação real leva o `NOTION_TOKEN` e a `GEMINI_API_KEY` paga (cobrança ativa
  no projeto do Google Cloud). O código não consegue conferir se a chave é paga, então isso fica no processo. O
  `--dry-run` não chama o modelo e pode rodar sempre.
- **Custo:** a rodada da página comercial inteira (266 páginas curadas) custou US$ 1,85, ~US$ 0,007 por página
  (ADR-005 §5).
- Testes sem rede: `tests/notion_falso.py` serve o workspace FICTÍCIO de `tests/fixtures/notion/workspace.json`.

### Importar o Drive (T6)

A pasta "Conhecimento Comercial" do Drive entra pelo mesmo curador do Notion, e **também fica pesquisável no chat**
(o consultor cita como `[DOC-n]`, avisando que o documento ainda não foi revisado). Decisão do time: nos documentos do
Drive o dado pessoal **não** é mascarado nem pulado (só avisado). Detalhes no [ADR-006](docs/adr-006-importacao-drive.md).

1. Crie a conta de serviço e compartilhe a pasta com ela (passo a passo em [docs/deploy-railway.md](docs/deploy-railway.md)).
2. No `.env`: `DRIVE_PASTA_ID` e `GOOGLE_APPLICATION_CREDENTIALS` (caminho do JSON da conta de serviço).
3. Confira sem gastar: `python -m scripts.sincronizar_drive --dry-run` (e `pytest -m live tests/live`, que só lista e lê).
4. Sincronize: `python -m scripts.sincronizar_drive` (`--teto-usd 1` limita o gasto do curador), ou pelo botão da tela de
   Fontes, escolhendo **Drive**. Com `DRIVE_SYNC_INTERVALO_MIN=15` o servidor faz isso sozinho a cada 15 minutos.

- Lê docx, PDF **com texto** (PDF de imagem fica `vazia`: não há OCR), xlsx, csv, txt, md e Google Docs/Planilhas/Slides.
- Arquivo acima de `DRIVE_MAX_MB` (30) não é baixado. Planilha ou documento com mais de `DRIVE_MAX_TRECHOS` (12) trechos
  vai **só para a busca** (`so_busca`), não para o curador.
- Testes sem rede: `tests/drive_falso.py` serve arquivos SINTÉTICOS; nenhum documento real do CITi vai para o Git.

### API para a interface (T7)

Tudo exige login (T5). Detalhes e decisões no [ADR-008](docs/adr-008-backend-t7.md).

| Rota | Para quê |
|---|---|
| `POST /chat` | Já devolvia `resposta` e `documentos`; agora também `lacuna_id` (quando o consultor disse que a base não cobre). |
| `POST /chat/registrar` | "Registrar isso": vira **proposta** do curador a partir do `texto` ou das últimas falas da pessoa. Não grava; quem grava é `POST /insights` (aceita `lacuna_id`). |
| `GET /lacunas` | O que o time perguntou e a base não soube responder, agrupado, as mais repetidas primeiro. |
| `POST /lacunas/{id}/resolver` | Tira da lista (as parecidas junto). |
| `POST /briefing` | Roteiro da reunião só com a base: cases, perfil, condução, objeções, proposta e lacunas, cada ponto com as fontes. |
| `POST /fontes/anexo` | Anexo do chat (docx, pdf, xlsx, csv, txt, md; até 10 MB) vira fonte: busca + curador. |
| `GET /fontes/{id}` · `GET /fontes/{id}/texto` · `POST /fontes/{id}/curar` | Acompanhar o curador do anexo, ler o texto extraído (link do `[DOC-n]`) e tentar de novo. |

**Banco e migrações (Alembic):** as tabelas não são mais criadas pelo app. Mudou `app/models.py`? Gere a migração com `alembic revision --autogenerate -m "o que mudou"`, revise o arquivo gerado em `migrations/versions/` e rode `alembic upgrade head`. Nunca edite uma migração que já foi para a main. No SQLite o app liga as chaves estrangeiras (`PRAGMA foreign_keys=ON`, em `app/db.py`), como o Postgres faz: relação para insight inexistente dá erro também no dev. Se uma migração futura precisar recriar uma tabela (batch), teste `upgrade`, `downgrade` e `upgrade` de novo antes do PR.

## Estrutura

```
app/
  main.py        rotas (FastAPI)
  config.py      lê o .env
  db.py          conexão com o banco
  models.py      tabelas (espelha docs/playbook-modelo.md)
  schemas.py     formato dos dados que entram/saem da API
  llm.py         ÚNICO lugar que fala com o modelo (Gemini)
  knowledge.py   monta a base do consultor: os itens aprovados do banco, um por linha ([INS-n])
  notion.py      ÚNICO lugar que fala com o Notion (só leitura, com limite de requisições e backoff)
  markdown_notion.py  blocos do Notion → markdown
  trechos.py     página grande → trechos que cabem no curador
  importacao.py  importação do Notion: sincroniza com a tabela fontes, faz a triagem e o relatório (o script e o
                 POST /fontes/sincronizar usam as mesmas funções); o curador em lote serve também ao Drive
  drive.py       ÚNICO lugar que fala com o Google Drive (conta de serviço, só leitura)
  extrair_texto.py  docx, pdf, xlsx, csv, txt → texto
  importacao_drive.py  importação do Drive (incremental, com teto) e os trechos de busca
  busca.py       busca nos documentos (BM25 em Python): os trechos que o consultor recebe como [DOC-n]
  agendador.py   sincronização automática do Drive (DRIVE_SYNC_INTERVALO_MIN)
  auth.py        login com a conta Google do CITi (sessão, autor da sessão; toda rota exige login)
  prompts/       prompts em arquivos .md (versionados no Git)
  templates/     página da interface (index.html)
  static/        CSS e JS da interface
knowledge/       exemplos.md: a base v0 da T2 (FICTÍCIA). O consultor não lê mais; o modo demonstração da tela
                 tem uma cópia própria
docs/            ideia, modelo do playbook, arquitetura, perguntas-teste
scripts/         linha de comando: python -m scripts.importar_notion e python -m scripts.sincronizar_drive
tests/           testes automáticos
migrations/      migrações do banco (Alembic); versions/ = histórico do schema
data/            banco SQLite local (não vai pro Git)
```

## Regras do time

1. **Nunca** suba o `.env` nem a chave da API para o Git, nem mande em print/chat.
2. Uma branch por task: `git checkout -b t2-primeira-chamada`. Commits pequenos e com mensagem clara.
3. Antes de abrir PR/pedir revisão: `pytest` passando.
4. Não coloque dados pessoais de clientes no banco nem nos prompts.
5. Todo acesso ao modelo (Gemini) passa por `app/llm.py`, e todo acesso ao Notion, por `app/notion.py`.
6. Os `TODO(Tn)` no código indicam onde cada task mexe.

## Tasks (roadmap)

T1 setup · T2 consultor com Gemini (chat + base de exemplo) · T3 banco + API de insights · T4 chat Registrar (curador) ·
T5 ingestão do Notion · T6 playbook + aprovar/rejeitar · T7 chat Perguntar (consultor) ·
T8 teste com as perguntas-teste · T9 login e deploy no Railway.
