# Arquitetura (v0)

```
Notion / Drive ──► ingestão (script) ──► banco (SQLite dev / Postgres prod)
                                           ├─ insights
                                           └─ fontes (documentos importados)
Chat "Registrar" ──► curador (Gemini) ──► proposta ──► humano aprova ──► playbook
Chat "Perguntar" ──► consultor (Gemini) ──► playbook + fontes ──► resposta com citações
/playbook ──► documento navegável por seção
```

## Decisões
- Python + FastAPI + SQLAlchemy: uma linguagem só, simples de aprender e de deployar.
- SQLite no dev (zero instalação); Postgres no Railway em produção (só muda `DATABASE_URL`).
- Sem RAG: o playbook validado cabe no contexto do modelo. Os documentos do Drive entram por uma busca de palavras
  (BM25, `app/busca.py`) que traz os melhores trechos a cada pergunta, citados como [DOC-n] (ADR-006). Embeddings
  (T8) só se o acervo crescer muito.
- Todo acesso ao modelo (Gemini) passa por `app/llm.py`. Prompts são arquivos em `app/prompts/`, versionados.
- Nada vira regra sem aprovação humana.
