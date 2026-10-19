# ADR-006: Importação do Drive e busca nos documentos ([DOC-n])

- **Status:** aceito
- **Data:** 2026-10-19
- **Autor:** Davi Mello (com o Claude)
- **Contexto:** T6. Reaproveita a importação do [ADR-005](adr-005-importacao-notion.md) e o consultor do
  [ADR-004](adr-004-consultor.md)

## Contexto

O comercial guarda o conhecimento numa pasta do Drive, "Conhecimento Comercial", com subpastas (Ensinamentos, Pasta de
dicas, Resumo). São ~14 arquivos: docx, PDFs (3 com mais de 50 MB, em imagem) e Google Docs, muitos com marcações como
[Experiência], [Opinião], [faço sempre], [aconteceu 1x].

Decisões do Davi (2026-10-19):
- desenvolver **direto contra a pasta real**, sem Drive falso dentro do produto (os testes usam arquivos sintéticos);
- **não mascarar nem pular dado pessoal** nos documentos do Drive: "é privado e não sai do agente". A barreira de dado
  pessoal continua valendo para o Notion e para o /registrar. No Drive, o relatório só **avisa** ("contém e-mail,
  telefone, mantido por decisão do time");
- o time quer **finalizar a semana com o Drive funcionando**: o que está nos documentos precisa ser achado no chat
  mesmo antes da revisão na Fila.

## Decisão

### 1. Dois caminhos para o mesmo documento
1. **Curadoria (Fila).** O texto do arquivo passa pelo mesmo curador do Notion (`Origem` em `app/importacao.py`), que
   propõe itens `historico_a_validar`. O time aprova na Fila. Só então viram `[INS-n]` e entram no playbook.
2. **Busca (chat).** Os mesmos textos viram pedaços de ~1.500 caracteres (`trechos_documento`). A cada pergunta, os
   5 melhores pedaços (no máximo 2 por documento) vão ao consultor, que os cita como **`[DOC-n]`** e avisa, uma vez,
   que vêm de documento do Drive ainda não revisado.

A base aprovada **sempre ganha**: se um `[DOC-n]` contradiz um `[INS-n]`, o consultor segue o item aprovado. Documento
não tem nível de evidência e não ganha número inventado. O texto do documento vai ao modelo dentro de
`<documento>…</documento>`, como **dado não confiável** (instrução escrita dentro de um documento não é seguida).

### 2. Leitura do Drive (`app/drive.py`)
- **Conta de serviço**, escopo `drive.readonly`. A pasta é compartilhada com o e-mail dela (de preferência num drive
  compartilhado do CITi, para não depender de uma pessoa).
- Credencial por `GOOGLE_APPLICATION_CREDENTIALS` (caminho do JSON, no computador) ou `GOOGLE_SERVICE_ACCOUNT_JSON`
  (conteúdo, na Railway). `DRIVE_PASTA_ID` é o id da pasta raiz.
- HTTP simples (`google-auth` + `requests`), sem o cliente gigante do Google. Lista com subpastas (atalhos e lixeira
  ficam de fora), repete em 429/5xx, nunca loga nome de arquivo nem texto.
- Documentos nativos do Google saem **exportados** (texto puro; planilha em CSV). Arquivos comuns baixam em blocos de
  1 MB para o disco.

### 3. Texto do arquivo (`app/extrair_texto.py`)
docx (títulos, listas e tabelas na ordem), pdf (**só a camada de texto**; sem OCR), xlsx, csv, txt, md. PDF só de
imagem dá texto vazio e a fonte fica `vazia`, com o motivo. OCR fica fora desta entrega: se o time quiser os 3 PDFs
grandes, o caminho é exportá-los como texto (ou pedir OCR numa T futura).

### 4. Incremental, com teto e tudo-ou-nada
- Só baixa o que mudou (`modifiedTime`); arquivo "tocado" com o mesmo texto (hash) não volta ao curador.
- Arquivo acima de `DRIVE_MAX_MB` (30) não é baixado: `pulada_longa`, reavaliada a cada rodada.
- Planilha, ou documento com mais de `DRIVE_MAX_TRECHOS` (12) trechos, vira **`so_busca`**: o chat acha, o curador não
  recebe (lista de dados não é aprendizado; documento enorme custaria caro e geraria itens ruins).
- Mesma regra de teto do ADR-005 (gasto + 2 × estimativa ≤ teto) e cada documento entra por inteiro ou não entra.
- Uma sincronização por vez, em todo o app (409 se já há uma rodando).

### 5. Sincronização automática
Com `DRIVE_SYNC_INTERVALO_MIN > 0`, o servidor sincroniza a pasta de tempos em tempos (`app/agendador.py`; primeira
rodada 30 s depois de subir). Cada rodada é uma execução comum, aparece na tela de Fontes e usa o teto
`DRIVE_SYNC_TETO_USD` (0,5). Rodada sem novidade só custa a listagem. Sem fila externa, porque o app tem um processo
só; se um dia tiver mais de um, a trava passa a ser do banco. **Recomendado na Railway: 15.**

### 6. Busca (`app/busca.py`)
BM25 em Python, sem acento e sem as palavras vazias do português, com título e pasta pesando o dobro. É de propósito: o
SQLite (dev) e o Postgres (prod) não têm a mesma busca de texto, e algumas centenas de pedaços cabem na memória. O
índice se refaz sozinho quando os pedaços ou os documentos mudam. A consulta é a pergunta mais as duas últimas falas
do usuário. **Se o acervo passar de alguns milhares de pedaços, é aqui que entram o `tsvector` do Postgres ou os
embeddings (T8).** Isso substitui a nota antiga do deploy ("a busca precisa de tsvector").

### 7. Tela
- Fontes: escolher **Notion ou Drive** ao sincronizar, última sincronização por origem, filtro por origem, a pasta do
  arquivo em cada cartão, o status **Só na busca** e explicações próprias do Drive.
- Chat: `[DOC-n]` vira link tracejado para o arquivo no Drive (só se o servidor mandou o documento junto) e a resposta
  mostra o rodapé "Documentos do Drive, ainda não revisados pelo time".

## Consequências
- Dado pessoal dos documentos do Drive **vai ao Gemini** (chave paga) e fica no banco. Fica registrado como decisão do
  time (2026-10-19). A tela de Fontes e o relatório avisam; **o acesso ao app precisa do login (T5)** antes de abrir
  para o time, porque agora o banco tem texto integral dos documentos.
- O que o chat responde com `[DOC-n]` não passou por revisão: o aviso na resposta e o rodapé existem por isso. Quem
  aprova a Fila transforma o que presta em `[INS-n]`.
- Teste contra a pasta real: `pytest -m live tests/live` (não chama o Gemini, não grava no banco).
