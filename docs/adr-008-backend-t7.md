# ADR-008: Fechamento do back-end (T7): lacunas, registrar pelo chat, briefing e anexo

- **Status:** aceito
- **Data:** 2026-10-21
- **Autor:** Davi Mello (com o Claude)
- **Contexto:** a API que faltava para a interface (Rafael) fechar as telas. Nada aqui muda a regra central: **o modelo
  propõe, o código dispõe, e nada vira regra sem aprovação humana.**

## 1. Lacunas: o que o time perguntou e a base não soube responder
- Quem decide que é lacuna é o **código**: a resposta do consultor tem a frase do prompt ("A base não cobre…",
  comparada sem acento e sem diferença de maiúscula). O modelo não escreve na tabela.
- A pergunta (que já passou pela barreira de dado pessoal do `/chat`) fica em `lacunas`. As parecidas se juntam pela
  **chave**: as palavras úteis da pergunta, sem repetir e em ordem ("preço hotelaria" = "hotelaria, preço?").
- `POST /chat` devolve `lacuna_id` quando registrou uma. `GET /lacunas` lista as abertas agrupadas, as mais repetidas
  primeiro (`vezes`, `pessoas`). Registrar um item com `lacuna_id` (`POST /insights`) resolve a lacuna (e as parecidas);
  `POST /lacunas/{id}/resolver` tira da lista sem registrar nada.
- Registrar a lacuna nunca derruba o chat (se o banco falhar, só vai para o log).

## 2. "Registrar isso" a partir do chat
- `POST /chat/registrar` transforma o que a pessoa contou (o `texto`, ou as **últimas 3 falas dela** no histórico; as
  do modelo nunca entram) em **proposta** do curador. Mesma barreira de dado pessoal e mesmo rascunho do
  `/registrar/propor`. **Não grava**: quem grava é o `POST /insights`, depois que a pessoa confere (e o item nasce
  `proposto`, na Fila).

## 3. Briefing de reunião (`POST /briefing`)
- Entrada: `segmento`, `tipo_reuniao` (diagnostico | proposta | negociacao) e `contexto` (até 1.500 caracteres, passa
  pela barreira de dado pessoal). Não grava nada.
- **O código escolhe os itens**, o modelo só organiza: aprovados (`validado`/`consolidado`) do segmento ou sem segmento,
  por prioridade (evidência, data), com teto por tipo. No diagnóstico, se o segmento tem menos de 3 itens, entram até 3
  de **outros segmentos**, marcados (o modelo precisa dizer, no ponto, que são de outro segmento). Documentos do Drive
  achados pela busca entram como `[DOC-n]`, valendo menos que os itens.
- **O código confere o que o modelo devolveu:** ponto sem fonte válida (id que não foi enviado, mal escrito ou
  ausente) é **descartado** e contado em `avisos`; o id escrito no meio do texto sai (ele vai em `fontes`); o texto é
  cortado em 400 caracteres e cada seção em 6 pontos. A `evidencia_minima` do ponto é a **menor** dos itens citados
  (calculada pelo código, não declarada pelo modelo); ponto que cita documento sai com `nao_revisado`.
- **Lacunas em duas camadas:** primeiro as que o código calcula (sem case, sem perfil, sem objeção, seção da reunião
  vazia), depois até 5 do modelo, sem repetir.
- **Sem item aprovado e sem documento, o modelo nem é chamado** (`usou_modelo: false`, seções vazias, lacunas e aviso).
  Preferimos um briefing vazio e honesto a um inventado.
- Usa o modelo do consultor. Falha do modelo: 502.

## 4. Anexo no chat vira fonte (`POST /fontes/anexo`)
- Aceita docx, pdf, xlsx, csv, txt e md, **até 10 MB**. docx/xlsx (zip) abertos passam de 100 MB: recusado (zip bomb);
  PDF lê até 400 páginas. **O arquivo não é guardado**: só o texto extraído (`fontes`, origem `upload`) e os pedaços de
  busca.
- Mesmo pipeline do Notion e do Drive: o texto fica **na busca** (o consultor cita como `[DOC-n]`, "ainda não
  revisado") e o curador, em segundo plano, propõe itens `historico_a_validar` na Fila (autor "anexo no chat", sem
  número de execução no histórico). O link do `[DOC-n]` é `GET /fontes/{id}/texto` (o texto extraído).
- Triagem: sem texto → `vazia`; planilha ou mais de 5 trechos → `so_busca` (acha na busca, não vai ao curador);
  o resto → `a_curar`. Acompanhe o curador em `GET /fontes/{id}` (`importada` ou `falha`); `POST /fontes/{id}/curar`
  tenta de novo. O mesmo texto anexado de novo devolve a fonte que já existe (`ja_existia`), sem gastar o modelo.
- **Dado pessoal BARRA** (decisão minha, o Davi pode virar): como no chat e no Notion, o texto com e-mail, CPF, CNPJ ou
  telefone **não é guardado nem enviado ao modelo** (`pulada_dado_pessoal`, com o tipo no motivo). O anexo é escrito ou
  colado por uma pessoa na hora e pode ter dado de cliente que ela nem viu; o Drive não barra porque é a pasta curada do
  time. Para anexos seguirem o Drive, basta `barra_dado_pessoal=False` em `UPLOAD` (`app/anexos.py`).
- Sem teto de gasto por anexo: é um arquivo (até 5 chamadas do curador), disparado por uma pessoa logada.

## O que fica de fora
- OCR de PDF de imagem; anexar mais de um arquivo por chamada (a tela manda um por vez); guardar o arquivo original.
- Fila de tarefas de verdade: o curador do anexo roda em `BackgroundTasks`. Se o servidor reiniciar no meio, a fonte
  fica `a_curar` e `POST /fontes/{id}/curar` retoma.
