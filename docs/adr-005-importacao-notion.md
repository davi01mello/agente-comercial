# ADR-005: Importação do Notion (staging, triagem e curador em lote)

- **Status:** aceito
- **Data:** 2026-10-13 (atualizado em 2026-10-19, na T4c: a rodada real no §5 e a execução pela API no §6)
- **Autor:** Rafael Nóbrega
- **Contexto:** T4, em 3 PRs: `t4a-notion-fontes` (ler e triar, sem o modelo), `t4b-notion-curador` (o curador e o
  teto de gasto) e `t4c-sincronizar-tela` (a execução pela API)

## Contexto

A T4 traz as páginas do Notion do comercial para o banco **sem misturar com o que o time aprovou**:
- cada página vira uma linha da tabela `fontes` (o "staging");
- a página passa por uma triagem;
- o curador da T3 propõe itens a partir dela, que entram na Fila como `historico_a_validar`. Nunca como `validado`.

O que guiou as decisões:
- **É a primeira vez que o app lê dado real.** O Notion do comercial tem preços, propostas e nomes de cliente.
- **Respostas do Davi (2026-10-13):**
  - conteúdo real só vai ao modelo com a chave **paga** do Gemini;
  - página com e-mail, CPF, CNPJ ou telefone **nunca** vai ao modelo, nem com a chave paga: é pulada e aparece no
    relatório ("pulada por dado pessoal: título e motivo"), sem repetir o dado;
  - primeiro uma área de teste ("Cérebro: teste"), com teto de US$ 1;
  - a conta dele: ~US$ 0,01 por página (uma chamada do curador e uma de relações).
- **A orientação mudou (Davi, 2026-10-16 e 19):** a integração vê a **página comercial inteira**, só leitura. A página
  fictícia e a "Cérebro: teste" caíram. A chave paga ficou ativa em 2026-10-19, e a curadoria real foi liberada com o
  teto combinado com o Davi (~US$ 2 para a rodada toda). O resto continua: dado pessoal barrado pelo código, nada entra
  como `validado` (§4.4 e §5).
- **"O LLM propõe, o código dispõe"** continua valendo. O status, o autor, a fonte, a triagem e o teto ficam no código,
  com teste.

Como uma execução funciona (`app/importacao.py`):
1. **Sincroniza:** busca as páginas compartilhadas com a integração e lê os blocos só das novas ou editadas.
   Converte os blocos em markdown (`app/markdown_notion.py`) e faz a triagem.
2. **Confere as que sumiram do Notion**, quando a lista veio completa.
3. **Cura** (só fora do `--dry-run` e sempre com teto de gasto): um item por trecho.

## 1. Página grande: como dividir para caber no curador sem perder contexto?

**Como funciona** (`app/trechos.py`):
- **Página normal** (até 8.000 caracteres): vai **inteira**, numa chamada só. É o limite de texto que o curador já
  aceita no Registrar (`RegistrarIn.texto`), então é uma régua só no app inteiro.
- **Página grande:**
  - é cortada nos títulos (`#`, `##`, `###`), e as seções vizinhas são juntadas, em ordem, até 8.000 caracteres por
    trecho;
  - uma seção sozinha maior que isso é dividida entre parágrafos, depois entre linhas e, em último caso, no meio da
    linha.
- **O contexto:** cada trecho leva no topo o título da página e, na página grande, o caminho das seções e a parte:
  ```
  Página do Notion: Manual do comercial
  Seção: Prospecção › Indicação
  (parte 2 de 4)
  ```
- **Um item por trecho:** o curador faz um item por chamada (ADR-003), então a página grande vira um item por trecho.
- **Longa demais:** mais de **5 trechos** (~40 mil caracteres, ~10 mil tokens). A página é **pulada**, e o relatório
  diz "longa demais: N trechos (limite 5)". Uma página assim é um manual inteiro: melhor alguém dividi-la no Notion
  do que mandar 25 trechos de uma vez.
- **Vazia:** menos de 20 caracteres de texto (sem títulos e sem marcadores como `[subpágina: …]`). Não vai ao modelo.
  Uma página-índice, só com subpáginas, cai aqui.

**Por que não um item por seção em toda página:** custaria N vezes a conta do Davi e geraria itens fracos de seções que
não são aprendizado (agenda, links). Um prompt novo de "extração" (página → lista de itens) seria um prompt e um schema
sem golden set, e a spec pede o curador da T3.

**O que isso perde:**
- uma página normal com 3 aprendizados vira **1 item**, que o curador resume: o revisor vê só o principal;
- na página grande, um aprendizado espalhado em 2 seções que caem em trechos diferentes vira 2 itens parciais;
- a página longa demais não entra até alguém dividi-la.

**Quando muda:** quando a revisão na Fila mostrar com frequência páginas cujo item "esconde" outros aprendizados
(→ um item por seção, ou um prompt de extração com golden set próprio).

## 2. Duplicata entre páginas: como detectar?

**Como funciona:**
- O `hash_conteudo` é o SHA-256 do markdown **normalizado**: Unicode NFC, sem espaços no fim das linhas, no máximo uma
  linha em branco seguida. O **título fica de fora**.
- Uma página com o mesmo hash de outra fonte (menos as removidas e as com dado pessoal) fica `pulada_duplicata`, e o
  relatório diz "mesmo conteúdo de “<título da outra>”".
- Na mesma execução, vale a ordem da busca (da edição mais antiga para a mais nova): a primeira fica e a cópia é
  pulada.

**Por que hash exato:** é o mesmo hash que a spec já pede para o sync. Pega o caso mais comum, a página duplicada
("Cópia de …") e o modelo copiado várias vezes, sem dependência nova nem limiar para calibrar. Similaridade
(embeddings, MinHash) traria falso positivo, e um falso positivo **esconde** conhecimento que era diferente.

**O que isso perde:**
- **A quase-duplicata** (uma frase a mais) passa como página diferente, e os dois itens chegam à Fila.
- **Os itens não são ligados como `duplica`:** os candidatos do curador são só `validado` e `consolidado`
  (ADR-003 §1), então dois itens pendentes parecidos não se veem. Quem pega isso é o revisor.
- **Uma seção colada em várias páginas** não é detectada (o hash é da página inteira).
- **Se a original mudar ou sair do Notion**, a cópia continua `pulada_duplicata` até ela própria ser editada.

**Quando muda:** quando a Fila mostrar muitos itens repetidos vindos de páginas diferentes (→ hash por seção, ou
incluir `historico_a_validar` nos candidatos do curador).

## 3. O que fazer com página apagada ou movida?

**Como se detecta:**
- As fontes que **não vieram** na busca desta execução são conferidas uma a uma (`pages.retrieve`):
  - **na lixeira:** a página vem com `in_trash`;
  - **404:** apagada **ou** sem compartilhamento com a integração. A API não diferencia os dois;
  - **a página ainda existe** (o search só não a listou): nada muda.
- **Só se confere com a lista completa:**
  - sem `--limite-paginas`;
  - sem o Notion avisar que cortou a busca (`request_status: incomplete`).
  - Senão, uma página só "não vista" seria dada como removida por engano. O relatório avisa que a conferência não
    foi feita.
- **Movida dentro da área compartilhada:** o id não muda. A URL que gravamos é montada pelo id
  (`https://www.notion.so/<id>`), e não a do Notion, que repete o título no endereço. Então para nós nada muda.
- **Movida para fora da área compartilhada:** dá 404, igual a apagada.

**O que se faz:**
- A fonte vira `removida`. O markdown fica, para auditoria: nada é apagado.
- Os itens dela que **ninguém revisou** (`historico_a_validar`) vão para `obsoleto`, com o motivo "a página saiu do
  Notion" e o histórico, pela regra do domínio (`validar_transicao`).
- Os itens **já aprovados** (`validado`, `consolidado`) **não mudam**: foram decisão do time. O relatório avisa
  quantos são, para alguém conferir no Playbook.
- **Se a página voltar**, é lida e curada de novo, como uma página alterada.
- **A mesma regra vale para a página alterada:** quando o hash muda, os pendentes que o conteúdo antigo gerou viram
  `obsoleto` ("a página do Notion mudou"), e o curador propõe itens novos. Sem isso, cada edição empilharia uma versão
  nova na Fila.

**O que isso perde:**
- Se alguém tirar o compartilhamento por engano, os pendentes viram obsoletos. Quando a página voltar, os itens
  voltam como itens novos, não os mesmos.
- Uma página grande com uma vírgula a mais refaz todos os trechos. O custo é pequeno: no máximo ~US$ 0,05 por página.

## 4. Outras decisões que a spec obrigou a tomar

**4.1 "Rodar duas vezes seguidas = zero mudança".**
- **A chave da página é `origem` + `id_externo`** (o id da página), única no banco.
- **Página com o mesmo `last_edited_time`** nem tem os blocos lidos.
- **Data nova com o mesmo hash** grava só a data (e o título, se mudou). O título fica fora do hash: renomear a página
  não traz conhecimento novo.
- **Página já curada** (`importada`) não volta ao curador.
- **O teste confere, tabela por tabela,** que a 2ª execução não muda `fontes`, `insights`, `historico_status` nem
  `relacoes`. A única linha nova é a da própria execução em `execucoes_importacao`.
- **O `--dry-run` também grava a execução** (desde a T4c), com `dry_run=True` e sem teto: é por ela que a tela
  acompanha uma simulação pedida pela API (§6). As fontes não mudam, e o `/fontes/resumo` ignora essas linhas (a
  "última sincronização" é a última de verdade).
- **Limite conhecido:** o Notion arredonda o `last_edited_time` para o minuto (changelog do Notion). Uma edição feita
  no mesmo minuto da importação só é vista na próxima edição.

**4.2 Status de uma fonte:**

| Status | O que significa |
|---|---|
| `a_curar` | Passou na triagem e espera o curador (ou a execução parou no teto) |
| `importada` | O curador propôs os itens |
| `falha` | O curador falhou nela. Nada dela foi gravado, e a próxima execução tenta de novo. Uma falha que se repete gasta a cada execução (sempre dentro do teto) e aparece em "Falhas" no relatório, para alguém decidir |
| `vazia` | Quase sem texto |
| `pulada_dado_pessoal` | Tem e-mail, CPF, CNPJ ou telefone |
| `pulada_longa` | Mais de 5 trechos |
| `pulada_duplicata` | Mesmo conteúdo de outra fonte |
| `removida` | Saiu do Notion |

- **Por que duas fases** (`a_curar` e depois `importada`): se o teto parar a execução no meio, o que faltou continua
  esperando, e a próxima execução continua de onde parou, sem refazer nem duplicar nada.
- **A tabela `fontes` tem os campos da spec e a coluna `motivo`** (pedido do Davi na T4b): por que a página foi pulada,
  falhou no curador ou saiu do Notion ("e-mail no conteúdo", "6 trechos (limite 5)"), sem o dado e cortada em 200
  caracteres. A tela de Fontes mostra. A página que volta a `a_curar` ou vira `importada` fica sem motivo.
- **Uma página que falha ao ser lida no Notion** (403, rede) não muda de status: só aparece em "Falhas" no relatório
  da execução, e a próxima tenta de novo. O `falha` da fonte é só o do curador.

**4.3 Dado pessoal** (resposta 1 do Davi):
- **A regra é a mesma do curador** (`dominio.exigir_sem_dados_pessoais`), aplicada no **título e no texto**, antes de
  qualquer coisa. A `DadoPessoalNaEntrada` passou a levar a lista do que achou (tipo e onde, nunca o dado), e é dela
  que sai o motivo do relatório: "telefone no título", "e-mail no conteúdo".
- **A página pulada não guarda o texto** (`markdown` vazio), só o hash, que basta para saber se ela mudou.
- **Título com dado pessoal** é gravado e mostrado como "(título omitido: tem dado pessoal)". Se só o título muda
  (o texto é o mesmo) e o dado pessoal aparece ou some dele, a página passa pela triagem de novo: corrigir o título no
  Notion libera a página, e um título que ganha um telefone a barra.
- **A pessoa mencionada com @** vira "@pessoa" no markdown. O filtro não pega nomes, então isso evita que o nome de
  quem foi marcado vá ao modelo.
- **Nomes digitados no texto e valores de contrato passam.** É por isso que a escolha das páginas importa
  (resposta 2 do Davi).
- **O `propor_lote` confere de novo o dado pessoal** antes do modelo. A triagem já fez isso, mas a regra não pode
  depender de quem chama.

**4.4 Chave paga** (resposta 1 do Davi):
- Avaliei uma trava no código (`GEMINI_CHAVE_PAGA=true` no `.env`) e **não fiz**. O Davi pediu para desenvolver e
  testar **com páginas fictícias e a chave grátis**, e a trava bloquearia exatamente esse teste, ou teria de ser
  desligada para ele, o que a anula. Além disso, o código não consegue conferir se a chave é mesmo paga.
- **A regra fica no processo**, com duas rodadas em ordem:
  1. "Cérebro: teste fictício", com a chave grátis;
  2. "Cérebro: teste", com as páginas reais, só depois da cobrança ativa e da chave nova.
- O `--dry-run` nunca chama o modelo, então pode rodar com página real a qualquer momento.
- **Como ficou (2026-10-19):** a 2ª rodada passou a ser a página comercial inteira (Contexto), e só começou com a
  chave paga no `.env`. A regra continua no processo: o código não sabe se a chave é paga.

**4.5 Curador em lote** (`curadoria.propor_lote`):
- Não há ninguém para responder às perguntas, então o curador roda como **último turno**: o modelo é avisado de que
  não deve perguntar e, se perguntar, a pergunta vira aviso.
- O autor é o texto fixo **"importação Notion"**: nunca o nome de uma pessoa, e não depende da permissão de usuários
  da integração.
- `fonte` e `fonte_ref` são postos pelo código.
- Os avisos do curador **não são gravados**, como no `POST /insights`. O histórico de criação de cada item diz
  "Importado do Notion (execução #N)".
- Os itens de uma página entram **todos juntos ou nenhum**: se o curador falhar no 2º trecho, nem o item do 1º entra,
  e a página fica `falha`, com o motivo. A próxima execução tenta de novo.
- **O item que vai ser gravado também é conferido** (`curadoria.exigir_item_sem_dados_pessoais`): se o modelo devolver
  algo com cara de dado pessoal (um número que parece telefone, por exemplo), a página fica `falha` com "o item proposto
  tem possível dado pessoal (telefone em contexto_cliente)". É a mesma regra do `POST /insights`, que desde a T4b
  responde 422 em vez de só avisar (pedido do Davi): dado pessoal de cliente não entra na base por nenhum caminho.

**4.6 Teto de gasto e estimativa:**
- **O `--dry-run` estima sem chamar o modelo:**
  - por trecho, entrada = 1.976 tokens de instruções (medido, ADR-003 §4) + caracteres ÷ 4 + 60, e saída = 1.250
    (**medido** na rodada real, §5; era 800, uma suposição);
  - mais a chamada de relações: 1.187 de entrada (30 candidatos no pior caso) e 100 de saída;
  - nos preços do `.env`.
  - Uma página de 3 mil caracteres dá **~US$ 0,0080**, comparável com os ~US$ 0,01 do Davi.
  - O relatório diz "até N chamadas": a de relações só acontece quando há candidatos (§5).
- **O teto (`--teto-usd`, padrão US$ 1, o do teste):** antes de cada página, confere se o gasto **real** até ali mais
  **2 ×** a estimativa da página cabe. O "2 ×" cobre o JSON refeito e um raciocínio maior que o estimado. Se não couber,
  para, imprime o relatório parcial, e a próxima execução continua.
- **O gasto real** é a soma do `custo_usd` que o `llm.py` já calcula para o log (`llm.medir_gasto()`), a partir dos
  tokens que o Gemini informa. Não depende do nível do log. Uma resposta que vier sem a contagem de tokens conta como
  a estimativa da página (pessimista).
- **O relatório** mostra o custo real ao lado do teto, as páginas que ficaram esperando e as falhas do curador.
- **Sem teto, o curador não roda.** O script sempre passa um teto.
- **Limite honesto:** se uma página sozinha gastar mais que o dobro da estimativa, o teto pode ser passado em no máximo
  o custo dela (~US$ 0,05 no pior caso).

**4.7 Leitura do Notion** (`app/notion.py`):
- **SDK oficial** (`notion-client` 3.1) com o **retry dele desligado**. O nosso faz o que ele não faz:
  - um intervalo mínimo de 0,35 s entre requisições (~2,9 por segundo; o Notion permite 180 por minuto, 3 por segundo
    em média);
  - o 529 (sobrecarga) repetido como o 429, respeitando o `Retry-After` (em segundos ou em data, até 60 s), como a
    documentação do Notion manda;
  - 500, 502, 503, 504, timeout e rede repetidos com espera de 1, 2, 4 e 8 s, até 5 tentativas.
- **Versão da API fixa em `2026-03-11`.**
- **Erro inesperado** (um bug, o banco recusando um valor): o que estava pela metade é desfeito, a execução é fechada,
  e o script mostra só o **tipo** do erro, nunca a mensagem, que pode trazer texto de página (o SQLAlchemy mostra os
  parâmetros do SQL).
- **O log** do SDK é só o caminho (com ids) e o código do erro. Os testes ligam DEBUG em todos os loggers e conferem
  que nem o token nem texto de página aparecem.
- **Linhas de banco de dados do Notion** são tratadas como páginas (a spec diz "páginas"): entram o título e os
  blocos, não as colunas.
- **Não usei o `GET /v1/pages/{id}/markdown`**, que devolve a página já em markdown: a spec pede página → blocos →
  markdown, e com os blocos o código decide o que vai ao modelo (por exemplo, trocar a pessoa mencionada).

## 5. Resultado da rodada real (2026-10-19)

A página comercial inteira, com a chave paga, em execuções do script (`gemini-3.8-flash`). Os números vêm do log
(`chamada_llm` e `importacao_notion`, que têm só números) e das contagens do banco. Nenhum título entra aqui.

**O que aconteceu, execução por execução:**

| Execução | O quê | Resultado |
|---|---|---|
| dry-run | A página inteira, sem gravar | 2.022 páginas lidas, 3.346 requisições ao Notion. 266 páginas (282 trechos) para o curador |
| #1 | 10 páginas, com o curador | 7 curadas, 8 itens, US$ 0,0469 |
| #2 | A mesma coisa de novo | Zero mudança |
| #3 | A página inteira | Interrompida com Ctrl+C na sincronização (823 páginas lidas) |
| #4 | A página inteira | Sincronizou o resto (1.200 novas). Interrompida com Ctrl+C na curadoria, depois de 72 páginas (US$ 0,4726) |
| #5 | O resto | 187 páginas curadas, 202 itens, US$ 1,3265, em 40 min (~13 s por página) |
| #6 | A mesma coisa de novo | Zero mudança: 21 requisições, 15 s, US$ 0 |

**Total:**
- 266 páginas curadas, que são as mesmas 266 do dry-run, e nenhuma falha do curador;
- 282 chamadas do curador e 282 itens na Fila (`historico_a_validar`);
- **US$ 1,8461**, dentro dos ~US$ 2 combinados com o Davi. Dá US$ 0,0069 por página, contra os ~US$ 0,01 da conta
  dele.

**As interrupções confirmaram o §4.2:** depois dos dois Ctrl+C, a execução seguinte continuou de onde a anterior parou,
sem refazer e sem duplicar nada. São 266 fontes `importada` e uma chamada do curador para cada item.

**Estimado × real** (a estimativa é a do dry-run, com as constantes da época):

| | Estimado | Real |
|---|---|---|
| Chamadas do curador | 282 | 282 |
| Entrada do curador (tokens) | 714.329 | 718.585 (**+0,6%**) |
| Saída do curador (tokens) | 225.600 (800 por chamada) | 344.948: média de 1.223 (**+53%**), mediana de 1.163 e máximo de 3.482 |
| Chamadas de relações | 282 | **16** |
| Entrada de relações (tokens) | 334.734 | 6.462 (404 por chamada) |
| Saída de relações (tokens) | 28.200 | 2.322 (145 por chamada) |
| **Custo** | **US$ 1,7385** | **US$ 1,8461 (+6%)** |

- **O total bateu por coincidência.** A saída do curador, subestimada, deixou de fora ~US$ 0,45. A chamada de relações,
  estimada para toda página, pôs ~US$ 0,34 a mais. Ela só acontece quando há candidatos (`validado` e `consolidado`,
  ADR-003 §1), e a base tinha 2 itens aprovados.
- **A entrada estava certa:** os caracteres ÷ 4 e as instruções medidas ficaram a 0,6% do real.
- **A saída do curador é quase toda raciocínio:** ~940 tokens de raciocínio (77%) e ~280 do JSON. A suposição de ~350
  para o JSON estava certa. O que faltou foi o raciocínio.

**O que mudou no código (pela regra de "mais de 50%"):**
- `TOKENS_SAIDA_CURAR` passou de 800 para **1.250** (a média medida, arredondada para cima). Com ela, a estimativa
  desta rodada daria US$ 2,21, 20% acima do real. É pessimista de propósito: quando o time aprovar os itens da Fila, a
  chamada de relações passa a acontecer de verdade.
- **A folga do teto passa a cobrir o pior trecho medido** (US$ 0,0161: 4.063 tokens de entrada e 3.482 de saída). Com
  800, duas vezes a estimativa dele dava ~US$ 0,0146 e ficaria abaixo do custo real. Com 1.250, dá ~US$ 0,0180.
- **A relações continua como estava:** 1.187 de entrada (o pior caso) e 100 de saída. A saída medida, 145, ficou 45%
  acima (abaixo da regra), e a entrada do pior caso, quase 3 vezes a real, cobre a diferença.
- O relatório passou a dizer "até N chamadas".

**Puladas: 1.756 de 2.022 (87%).**

| Motivo | Páginas |
|---|---|
| Vazia (menos de 20 caracteres de texto) | 1.658 (82%) |
| Dado pessoal | 57 (38 com e-mail e telefone, 16 só com telefone, 2 só com e-mail e 1 com e-mail, CPF e telefone) |
| Duplicata | 40 |
| Longa demais | 1 |

- **82% de vazias é esperado** (Davi, 2026-10-19). A maioria é linha de banco de dados do Notion, em que o conteúdo
  fica nas colunas, e a importação lê só o título e os blocos (§4.7). O relatório das vazias por banco
  (`guias/ferramentas/vazias_por_banco.py`, fora do repositório) foi direto para o Davi, porque os nomes dos bancos
  são dado real.
- **As 57 com dado pessoal não foram revisadas uma a uma.** Pode haver falso positivo, como um número de 11 dígitos.
  O motivo de cada uma está na tela de Fontes, e ela entra depois de limpa no Notion.
- **A página longa demais** foi para o Davi, com o link, para ser dividida.

**Na Fila: 282 itens, nenhum revisado ainda.**
- Por tipo: 97 `template`, 91 `aprendizado`, 29 `case`, 28 `hipotese`, 25 `perfil_segmento`, 6 `objecao` e 6
  `regra`;
- por seção: 92 em prospecção, 57 em fundamentos, 44 em qualificação, 33 em pós-venda, 20 em proposta, 19 em reunião
  de diagnóstico e 17 em negociação e fechamento;
- por evidência: 158 com 1, 108 com 2, 8 com 3 e 8 com 4;
- nenhuma relação gravada (as 16 chamadas não acharam ligação com os 2 itens aprovados).

A pergunta do §1 (o curador acertou tipo, seção e evidência? alguma página "escondeu" aprendizados?) e a do §2
(itens repetidos vindos de páginas diferentes?) dependem da revisão do time na Fila. Os gatilhos de "Rever quando"
continuam valendo.

## 6. A execução pela API (T4c)

**Como funciona:**
- **`POST /fontes/sincronizar`** recebe `{origem: "notion", dry_run, limite_paginas, teto_usd}`, as mesmas opções do
  script, com teto padrão de US$ 1. Campo desconhecido dá 422: um `"teto"` digitado errado não é ignorado em silêncio.
- **A requisição devolve 202** `{execucao_id}` na hora. A importação roda numa `BackgroundTasks` do FastAPI, que começa
  depois que a resposta sai, com a própria sessão do banco (a da requisição já fechou).
- **`GET /fontes/execucoes/{id}`** devolve `status` (`rodando`, `concluida`, `parou_no_teto` ou `erro`), `fase`
  (`sincronizando`, `curando` ou `fim`), as contagens, o gasto, o teto, a estimativa e o erro. Para um id que não
  existe, dá 404. Serve também para as execuções do script, porque a tabela é a mesma.
- **As contagens são gravadas a cada página,** num commit curto entre uma página e outra, nunca no meio de uma. A tela
  acompanha a execução enquanto ela roda, e o commit nunca leva uma página pela metade.
- **O script e a API chamam as mesmas funções** de `app/importacao.py` (`conferir_configuracao` e `executar`). A regra
  fica num lugar só.

**As decisões:**
- **409 se já houver uma importação de verdade rodando.** A resposta traz o número dela. Um dry-run rodando não
  bloqueia nada, porque não muda as fontes.
  - A conferência e a criação da execução ficam dentro de um `threading.Lock`. Sem ele, duas requisições ao mesmo tempo
    veriam "nenhuma rodando" e criariam duas.
- **503 quando falta o `NOTION_TOKEN`, ou a `GEMINI_API_KEY` fora do dry-run.** A mensagem é a mesma do script, e nada
  é criado. É 503, e não 422, porque o que falta é a configuração do servidor, não algo que quem pediu errou.
- **Na subida do servidor (lifespan), toda execução `rodando` vira `erro`, "interrompida".** Sem isso, um servidor que
  caiu no meio de uma execução travaria o 409 para sempre.
- **No erro, a execução guarda só o tipo** ("ErroNotion (401)", "RuntimeError"), nunca a mensagem. A de um erro
  inesperado pode ter texto de página (o SQLAlchemy põe os parâmetros do SQL nela). **A `fase` fica onde a execução
  caiu**, para dizer se foi na sincronização ou na curadoria.
- **O teto não pode ser infinito:** um `1e999` no JSON vira infinito, e um teto infinito deixaria o curador gastar sem
  limite. O `allow_inf_nan=False` recusa, e nada é criado. A resposta sai 500, e não 422, porque o FastAPI repete o
  valor no detalhe do erro, e infinito não é JSON válido.
- **A migração (`ad4589712565`) preenche as execuções antigas:** as com `fim` viram `concluida`, e as sem `fim` viram
  `erro` ("interrompida").
- **Sem login por enquanto:** o comentário `# T5: exigir papel admin` marca onde entra o "só admin".

**Limites conhecidos:**
- **A trava do 409 vale dentro de um processo.** No dev, com um `uvicorn` só, ela basta. Com vários workers, a
  conferência continua no banco, mas duas requisições exatamente ao mesmo tempo em workers diferentes poderiam passar.
  Fica para quando houver deploy.
- **O script não confere o 409:** não rode o script e a API ao mesmo tempo.
- **A subida do servidor marca como interrompida qualquer execução `rodando`**, inclusive uma do script que esteja
  rodando naquele instante. Quando o script termina, ele grava o status certo por cima.
- **Ctrl+C no `uvicorn`:** o 1º espera a execução acabar ("Waiting for background tasks to complete"), e só o 2º força
  a saída. O `--reload` também espera. Como uma rodada grande leva ~40 min (§5), editar um arquivo durante ela adia o
  reload até o fim.
- **As execuções de antes da T4c ficam incompletas na API:**
  - as contagens novas (puladas, curadas, itens e gasto) ficam em zero, porque o script antigo não as gravava;
  - o script antigo fechava a execução (com `fim`) mesmo quando ela caía. Por isso, uma execução antiga interrompida
    com Ctrl+C aparece como `concluida`. Foi o caso da #3 e da #4 do §5. A migração só reconhece como interrompida a
    que ficou sem `fim` (processo morto).

**O teste na mão (2026-10-19, Notion real):**
- **dry-run com 10 páginas pela API:** `concluida`, `dry_run: true`, sem teto, e o `/fontes/resumo` continuou mostrando
  a última execução de verdade;
- **rodada de verdade com teto de US$ 0,05:** 2.022 páginas lidas, 0 novas e gasto zero (tudo já estava sincronizado);
- **o dry-run do script** apareceu no `GET /fontes/execucoes/{id}`, porque a tabela é a mesma;
- **um id que não existe** deu 404.

O 409 e a interrupção não deram para ver na mão: com tudo sincronizado, a rodada acaba em segundos. Os testes
automáticos cobrem os dois casos (`tests/test_sincronizar_api.py`).

## Consequências

**Fica mais fácil:**
- trazer o Notion sem contaminar a base: nada entra como `validado`, e o consultor só lê o que o time aprovou
  (ADR-004);
- rodar a importação quantas vezes quiser: ela é incremental, não duplica e retoma de onde parou;
- saber quanto vai custar antes (`--dry-run`) e não passar do teto;
- pedir e acompanhar uma importação pela API (e, em breve, pela tela de Fontes), com o mesmo resultado do script;
- testar tudo sem rede: o SDK oficial roda de verdade contra um Notion falso, com um workspace fictício em JSON.

**Fica mais difícil / custa:**
- uma página normal vira um item só, e o revisor pode precisar registrar à mão o que ficou de fora;
- página com dado pessoal (inclusive falso positivo, como um número de 11 dígitos) precisa ser limpa no Notion para
  entrar;
- página longa demais precisa ser dividida no Notion;
- quase-duplicatas chegam à Fila.

**Rever quando:**
- uma rodada mostrar o custo real longe do estimado (→ ajustar as constantes de saída; a 1ª rodada já ajustou a do
  curador, §5);
- a importação rodar com mais de um worker (→ a trava do 409 precisa ir para o banco, §6);
- a Fila mostrar páginas que "escondem" aprendizados (→ §1) ou muitos itens repetidos (→ §2);
- o Drive entrar (Fase 2): a mesma tabela `fontes` serve (`origem`), mas documentos longos vão exigir outra regra de
  "longa demais".
