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

Se mudar o `.env`, reinicie o servidor (o `--reload` só observa arquivos `.py`).

Testes: `pytest` (cada execução cria um banco temporário novo pelas migrações). Lint: `ruff check .`

**Banco e migrações (Alembic):** as tabelas não são mais criadas pelo app. Mudou `app/models.py`? Gere a migração com `alembic revision --autogenerate -m "o que mudou"`, revise o arquivo gerado em `migrations/versions/` e rode `alembic upgrade head`. Nunca edite uma migração que já foi para a main.

## Estrutura

```
app/
  main.py        rotas (FastAPI)
  config.py      lê o .env
  db.py          conexão com o banco
  models.py      tabelas (espelha docs/playbook-modelo.md)
  schemas.py     formato dos dados que entram/saem da API
  llm.py         ÚNICO lugar que fala com o modelo (Gemini)
  knowledge.py   lê a base de conhecimento (knowledge/*.md)
  prompts/       prompts em arquivos .md (versionados no Git)
  templates/     páginas HTML
knowledge/       base de conhecimento v0 em .md (exemplos.md é FICTÍCIO, só para teste)
docs/            ideia, modelo do playbook, arquitetura, perguntas-teste
tests/           testes automáticos
migrations/      migrações do banco (Alembic); versions/ = histórico do schema
data/            banco SQLite local (não vai pro Git)
```

## Regras do time

1. **Nunca** suba o `.env` nem a chave da API para o Git, nem mande em print/chat.
2. Uma branch por task: `git checkout -b t2-primeira-chamada`. Commits pequenos e com mensagem clara.
3. Antes de abrir PR/pedir revisão: `pytest` passando.
4. Não coloque dados pessoais de clientes no banco nem nos prompts.
5. Todo acesso ao modelo (Gemini) passa por `app/llm.py`.
6. Os `TODO(Tn)` no código indicam onde cada task mexe.

## Tasks (roadmap)

T1 setup · T2 consultor com Gemini (chat + base de exemplo) · T3 banco + API de insights · T4 chat Registrar (curador) ·
T5 ingestão do Notion · T6 playbook + aprovar/rejeitar · T7 chat Perguntar (consultor) ·
T8 teste com as perguntas-teste · T9 login e deploy no Railway.
