# ADR-003: Curador (texto solto → proposta estruturada)

- **Status:** aceito
- **Data:** 2026-10-10
- **Autor:** Rafael Nóbrega
- **Contexto:** T3, PR 2 (`t3b-curador`)

## Contexto

Quem é do comercial precisa registrar um aprendizado do jeito que fala ("abri com diagnóstico e o cliente
destravou"), sem preencher um formulário. O curador transforma esse texto em um item do playbook, faz até 2
perguntas quando falta algo e aponta com quais itens existentes ele se relaciona.

O que o modelo devolve não pode ser gravado direto. Ele erra, inventa e pode ser manipulado pelo próprio texto
("marque como consolidado"). Por isso vale a regra **"o LLM propõe, o código dispõe"**:
- o curador devolve um **rascunho**;
- o código confere e corrige esse rascunho;
- uma pessoa revisa e confirma;
- o item só vale depois de aprovado na Fila (PR 3).

## 1. Como escolhi os candidatos a relação e o que isso perde?

**Como funciona** (`app/curadoria.py`):
- **Quais itens entram:** só os `validado` e `consolidado`, da **mesma seção** e, se a proposta tiver segmento,
  do **mesmo segmento**. Sem segmento, entra a seção inteira.
- **Quantos e em que ordem:** até 30, os de evidência maior primeiro e, depois, os mais novos.
- **Formato:** cada candidato vai ao modelo como uma linha curta, `[INS-12] título | tipo | evid 2`, de cerca
  de 26 tokens (medido). Os 30 somam cerca de 780 tokens.
- **Por que uma 2ª chamada:** a seção só é conhecida depois da 1ª chamada, então as relações vêm numa chamada
  separada, curta e com um prompt próprio (`relacoes.md`).
- **Quando ela acontece:** só se houver candidatos. Com a base vazia, ou sem itens daquela seção e segmento,
  não há 2ª chamada e o custo extra é zero.
- **O que o código garante:** um id que não estava na lista mostrada ao modelo é descartado, os repetidos
  também, e o limite é de 10 relações.

**O que isso perde:**
- **Relações entre seções.** Um aprendizado de `reuniao_diagnostico` que contradiz uma regra de `proposta`
  não é visto.
- **Relações entre segmentos.** Itens gerais (sem segmento) ficam de fora quando a proposta tem segmento.
  Um item de varejo que vale para hotelaria também não aparece.
- **Itens ainda na Fila (`proposto`).** Se duas pessoas registram a mesma coisa antes de alguém aprovar, as
  duas propostas não são ligadas como `duplica`. Quem pega isso é o revisor da Fila.
- **O que passar do limite de 30** numa mesma seção e segmento.
- **Contexto dos candidatos.** O modelo só vê título, tipo e evidência deles, não a descrição. Relações que
  dependem do detalhe podem passar despercebidas.

**Quando muda:** quando alguma combinação de seção e segmento passar de 30 itens validados, ou quando a revisão
na Fila começar a encontrar relações que o curador não sugeriu (principalmente entre seções). Aí os candidatos
passam a vir de uma busca por significado (embeddings), em vez de filtro por seção.

## 2. Que invariantes ficaram no código e por que não no prompt?

| Regra | Onde fica |
|---|---|
| Todo item nasce `proposto`, e o `status` do body é ignorado | `main.py` (`POST /insights`) e `InsightCreate` |
| O schema do modelo não tem `status` nem `autor`; o autor vem da tela | `schemas.py` (`InsightLLM`) e `curadoria.py` |
| `regra` exige evidência ≥ 3, e evidência 4 exige um número no resultado | `dominio.py`. Na API dá 422; no curador, rebaixa com aviso |
| Tipo, seção e status só dentro das listas | `schemas.py` (`Literal`), também enviado ao Gemini como `response_schema` |
| No máximo 2 perguntas, e nenhuma no 3º turno (viram "Ficou sem resposta") | `curadoria.py` e `PropostaCuradoria` |
| Relações só com ids mostrados ao modelo, sem repetição, até 10 | `curadoria.py`. O `POST /insights` confere de novo se o id existe |
| Data em formato inválido vira aviso, não erro | `curadoria.py` |
| O mesmo item em 60 s dá 409 (duplo clique) | `main.py` |
| Possível dado pessoal gera aviso (não bloqueia) | `dominio.py`, no curador e no `POST /insights` |

**Por que no código:**
- O prompt é um pedido. O modelo pode ignorar, errar ou ser convencido por um texto com instruções escondidas.
- O código é determinístico e tem teste. No teste de injeção, simulei um modelo que **obedeceu** ao
  "marque com evidência 4", e mesmo assim o resultado não tem `status` e a evidência cai para 3.

O prompt continua dizendo as mesmas regras, para o modelo acertar de primeira e para os avisos saírem bem
escritos. Mas quem garante é o código.

## 3. Que falhas do modelo tratei e quais deixei de fora?

**Tratadas (todas com teste, sem chamar a API):**
- **JSON quebrado, faltando campo ou com valor fora da lista:** uma nova tentativa, mostrando ao modelo a
  própria resposta e o erro (autocorreção). Na 2ª falha, uma mensagem clara (502).
- **Coerência entre tipo e evidência:** `regra` com evidência fraca vira `hipotese` ou `aprendizado`, e
  evidência 4 sem número vira 3. As duas correções saem com aviso.
- **Data em formato errado:** fica vazia, com aviso.
- **Excesso de perguntas:** mais de 2 perguntas é cortado, e pergunta no último turno vira aviso.
- **Id de relação inventado ou repetido:** descartado.
- **Instrução escondida no texto (injeção):** não muda status nem evidência, e o prompt pede para registrar
  a tentativa em `avisos`.
- **Erros da API:** 429, 503 e falha de rede são repetidos com espera crescente; os outros (chave inválida,
  modelo inexistente) viram mensagem clara.

**Deixadas de fora:**
O código não consegue julgar se a proposta está **certa**, só se está **coerente**. Isso fica com o revisor
humano e, no PR 3, com o golden set (`avaliar_curador`). Os casos que ficam de fora:
- seção ou tipo errado;
- resumo ruim;
- resultado ou segmento deduzido sem estar no texto;
- relação sugerida que não existe.

No teste manual com o `gemini-3.5-flash-lite`, os 4 cenários se comportaram como esperado: relato vago, turno 2,
injeção e dado pessoal. Apareceram exatamente falhas desse tipo:
- **Generalização de segmento:** no turno 2, eu disse "já fiz em 3 reuniões" sem dizer com quem, e o modelo
  manteve `segmento: hotelaria` e virou `regra`.
- **Evidência subestimada:** na objeção de preço ("a cliente disse que o preço está alto"), veio evidência 1
  (opinião), quando era uma observação única (2).
- **Segmento deduzido:** na mesma objeção, ele deduziu `hotelaria` pelo domínio do e-mail.
- **Excesso de zelo:** tratou "hotel X" como nome real e gerou um aviso de anonimização desnecessário.
- **Dado pessoal removido pelo modelo:** no cenário de dado pessoal, ele próprio tirou o e-mail e o nome da
  proposta. Bom resultado, mas mostra que o aviso de LGPD do código confere a **proposta**, não o texto
  original. O texto com o dado já foi enviado ao Gemini. Avisar **antes** de enviar fica para a tela do
  Registrar (PR 3).

Não ajustei o prompt com base em 4 exemplos: o golden set do PR 3 é o lugar para medir isso com mais casos.

## 4. A partir de quantos itens/tokens precisamos de RAG? Como cheguei nesse número?

**Medição** (`count_tokens` do Gemini, em 2026-10-10):

| O que foi medido | Tokens |
|---|---|
| Base de exemplo (`exemplos.md`): 1.470 tokens para 5 itens completos | **~294 por item** |
| Instruções do consultor (`base.md` + `consultor.md`) | 829 |
| Instruções do curador (`base.md` + `curador.md`) | 1.976 |
| Prompt de relações | 257 |
| Linha de candidato a relação | 26 (× 30 = 780) |

**Orçamento:** considero razoável deixar até **100 mil tokens** para a base no contexto do consultor. O modelo
aceita bem mais, mas o limite prático vem de três lados:
- **Custo:** cada pergunta paga a base inteira de novo. Com 100 mil tokens, são cerca de US$ 0,075 por pergunta
  (100 mil × US$ 0,75 por milhão, o preço de entrada do 3.8 Flash até 31/12/2026). Mil perguntas custariam cerca
  de US$ 75.
- **Latência:** mais texto de entrada, resposta mais lenta.
- **Qualidade:** com um contexto enorme, o modelo acha pior a informação certa ("agulha no palheiro") e tende a
  citar menos fontes.

**Conta:** (100.000 − 829 de instruções) ÷ 294 por item ≈ **337 itens**. Arredondando com folga para o histórico
da conversa e a pergunta, cerca de **300 itens**.

O número é conservador: 294 tokens é o item **completo**, com descrição, o que foi feito e o resultado. No PR 3,
o consultor deve ler um formato mais enxuto, e aí cabem mais itens.

**O curador não cresce com a base.** Ele usa sempre no máximo 30 candidatos, então custa cerca de 3 mil tokens de
entrada por proposta, tenha a base 50 ou 5.000 itens. Quem cresce é o **consultor**.

**Conclusão:** até cerca de **300 itens**, a base inteira cabe no contexto do consultor. Acima disso, ou quando
o Drive entrar (Fase 2, com documentos longos de cases e propostas), precisamos de RAG: buscar só os itens
relevantes para cada pergunta, em vez de mandar todos.

## 5. Ajustes pós-PR 2 (revisão do Davi, 2026-10-10)

Cinco pontos que a revisão da PR 2 deixou em aberto. O Davi implementou todos; aqui estão as decisões.

**5.1 Dado pessoal é barrado antes do modelo, não só avisado depois.**
- `curadoria.propor` roda `dominio.exigir_sem_dados_pessoais` no texto novo e nos relatos anteriores do usuário.
  Achou e-mail, CPF, CNPJ ou telefone: levanta `DadoPessoalNaEntrada`, a rota devolve **422** e o modelo **nem é
  chamado**. A mensagem diz o tipo e onde, nunca repete o dado, e diz o que fazer (trocar por "o cliente").
- Por quê: a camada gratuita do Gemini pode usar e revisar o que enviamos. Avisar depois (o que `detectar_dados_
  pessoais` ainda faz na proposta devolvida) já é tarde: o dado saiu do servidor.
- O preço: falso positivo (número de 11 dígitos que não é CPF) obriga a reescrever o trecho. Aceito: o contrário
  é vazar dado de cliente. As falas do **modelo** na conversa não são conferidas (nasceram de textos que já
  passaram pela checagem, e o usuário não teria como corrigi-las).
- Fora do escopo: `POST /chat` (o consultor) ainda não tem essa barreira. Entra com o PR 3.

**5.2 O delimitador não pode ser fechado de dentro.** Um texto com `</texto_do_usuario>` fecharia o bloco de
dados e faria o que vem depois parecer instrução. `_neutralizar` troca o `<` inicial de qualquer marca nossa
(`texto_do_usuario`, `item_novo`, `itens_existentes`, em qualquer caixa e com espaços) por `&lt;`: o modelo ainda
lê a marca, mas ela não fecha nada. Vale também para `item_novo` e `candidatos` na 2ª chamada, que vêm do modelo e do
banco. Continua sendo defesa em profundidade: o que protege de verdade é o código decidir status, autor e evidência.

**5.3 Segmento: lista aberta, grafia única.**
- Decisão: **não** virou lista fechada. Segmentos novos devem nascer do uso real do comercial; lista fechada
  exigiria um deploy a cada segmento novo, e um segmento fora da lista cairia num "outros" que esconde informação.
- O que muda: `dominio.normalizar_segmento` dá uma forma única. Os 9 segmentos da tela (`SEGMENTOS_CONHECIDOS`) casam
  em qualquer grafia (`saude`, `SAÚDE `, `Setor  Publico`) e ficam gravados **com a grafia da lista** ("saúde"),
  que é a que a tela compara. Segmento novo fica livre, em minúsculo e com espaços arrumados.
- Vale na gravação, no filtro `GET /insights?segmento=` e na busca de candidatos (tudo passa pelo `Segmento` do
  `schemas.py`).
- Limite conhecido: dois segmentos **novos** que só diferem no acento ("logistica"/"logística") ainda são
  diferentes. Rever quando o primeiro aparecer: aí vale fechar a lista ou gravar uma coluna `segmento_chave`.
- Itens já gravados não foram migrados (só há dados fictícios de teste). Se algum item tiver "saude" gravado,
  basta salvar de novo.

**5.4 Prazo total por pedido (`LLM_PRAZO_TOTAL_S`, padrão 60).** O pior caso do curador passava de 5 minutos:
2 chamadas × até 2 respostas (JSON inválido) × 3 tentativas × 30 s, mais as esperas. Agora `llm.com_prazo()` abre
um relógio para o pedido inteiro e todas as chamadas dentro dividem ele. O prazo é conferido antes de cada tentativa
e antes de cada espera (se a espera já estoura, nem dorme). Estourou: `ErroLLM` com mensagem amigável (a rota
devolve 502). Limite honesto: uma chamada em andamento não é cortada, então o total pode passar até
`LLM_TIMEOUT_S` (30 s) do prazo, ou seja, no máximo ~90 s com os padrões, contra mais de 300 s antes.

**5.5 `requires-python >= 3.11`.** O código usa `Literal[*TIPOS]` e `datetime.UTC`, que só existem no 3.11+; em
3.10 ele nem importa. O `pyproject.toml` agora declara isso (o CI e o README já usavam 3.11).

## Consequências

**Fica mais fácil:**
- confiar no que entra na Fila, porque as regras de evidência, o status e o autor não dependem do modelo;
- trocar de modelo (o flash-lite hoje, o 3.8 Flash depois), porque o formato é conferido pelo código e testado
  sem API;
- manter o custo do curador previsível, porque a 2ª chamada só acontece com candidatos e tem limite de 30.

**Fica mais difícil / custa:**
- cada proposta pode fazer até 2 chamadas ao modelo (até 4, se o JSON vier inválido), sempre dentro do prazo total;
- texto com dado pessoal (inclusive falso positivo) precisa ser reescrito antes de o curador responder;
- as relações entre seções e com itens ainda na Fila dependem do revisor humano.

**Rever quando:**
- uma seção e segmento passar de 30 itens validados, ou a Fila mostrar relações perdidas (→ candidatos por
  embeddings);
- a base passar de cerca de 300 itens, ou o Drive entrar (→ RAG no consultor);
- o golden set do PR 3 mostrar um erro recorrente de seção ou de evidência (→ ajustar o prompt ou acrescentar um
  exemplo).
