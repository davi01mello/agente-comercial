# ADR-004: Consultor (pergunta → resposta citando os itens aprovados)

- **Status:** aceito
- **Data:** 2026-10-12
- **Autor:** Rafael Nóbrega
- **Contexto:** T3, PR 3 (`t3c-fila-e-consultor`)

## Contexto

Até o PR 2, o consultor lia arquivos `.md` fixos (`knowledge/exemplos.md`, fictício). Agora ele lê o **banco**:
só os itens que alguém aprovou na Fila (`validado` e `consolidado`). `proposto`, `historico_a_validar` e
`obsoleto` nunca entram.

A base vai **inteira** em toda pergunta, no `system_instruction`. O RAG fica para a T8 (ADR-003 §4). Por isso o
tamanho de cada item decide o custo de cada pergunta e até quantos itens dá para ir sem RAG.

A regra continua **"o LLM propõe, o código dispõe"**, mas aqui o código decide menos que no curador: o que entra na
base, o formato dela e a barreira de dado pessoal ficam no código; o **conteúdo** da resposta (o que citar, que
aviso dar) fica com o modelo, e quem confere é o golden set.

## 1. Como escolhi o formato do item e quanto ele custa?

**Como funciona** (`app/knowledge.py`): um item por linha, no formato da spec do Davi.

```
[INS-12] título | tipo | seção | segmento | evid 3 | resumo | resultado
```

- **O id na frente, igual ao que a tela transforma em link.** O modelo copia `[INS-12]` como está, e a tela faz
  o link.
- **Resumo:** os primeiros 160 caracteres da descrição, sem partir palavra. É o bastante para o modelo saber do
  que o item trata, e o título já carrega a ideia principal.
- **Vazio fica explícito:** `sem segmento` e `sem resultado registrado`, em vez de um campo em branco. Um campo
  vazio deixa o modelo deduzir; o texto explícito diz que não há.
- **A evidência vai como número** (`evid 3`), e a legenda (1 opinião … 4 resultado medido) fica uma vez só no
  prompt, não repetida em cada linha.
- **Ficam de fora:** `autor` (o consultor não precisa) e `contexto_cliente` (pode ter dado pessoal).
- **`|` e quebra de linha dentro do texto** viram `/` e espaço, para um item não desmontar a linha.
- **Ordem:** maior evidência primeiro, depois o mais recente. Se um dia a base precisar ser cortada, o que fica é
  o mais forte.

**Medição** (`count_tokens` do Gemini, no golden set, em 2026-10-12):

| Formato | Tokens por item |
|---|---|
| Completo (`knowledge/exemplos.md`, o do ADR-003 §4) | **293** (o ADR-003 mediu 294) |
| Enxuto (`tests/golden/base.json`, 19 itens) | **73** |

O enxuto custa **4 vezes menos**. A estimativa do plano, por caracteres (≈70 contra 246), acertou o enxuto e
subestimou o completo.

**O que muda na conta do RAG:**
- Pelos tokens, o orçamento de 100 mil do ADR-003 §4 agora cabe cerca de **1.350 itens** ((100.000 − 829) ÷ 73).
- Mesmo assim, o aviso de RAG (`ITENS_ANTES_DO_RAG`) **continua em 300**, como pede a spec. Com 73 tokens por
  item, o limite deixou de ser custo: 300 itens dão cerca de 22 mil tokens, ou US$ 0,016 por pergunta no 3.8 Flash.
  O limite passa a ser **qualidade**: com centenas de itens parecidos, o modelo acha pior o item certo e cita
  menos (o golden set já mostra isso com 19 itens, ver §3.4).
- **Sugestão ao Davi:** manter 300 e rever o número com um golden set numa base maior, em vez de subir pelo
  custo.

**O que isso perde:**
- **O "o que foi feito"** (`o_que_foi_feito`) e o `servico` não entram na linha. Para perguntas de "como fazer",
  o modelo só tem o título e 160 caracteres da descrição.
- **O resto da descrição** depois dos 160 caracteres.
- **As relações entre itens** (`contradiz`, `substitui`...). O consultor não sabe que um item contradiz outro e
  pode citar os dois como se concordassem.
- **A data do evento.** A ordem usa a data, mas a linha não mostra; o modelo não consegue dizer "isso é de 2025".

**Quando muda:** quando a revisão das respostas mostrar que falta o "como" (→ pôr o `o_que_foi_feito` resumido na
linha) ou quando a base tiver a primeira relação `contradiz` entre itens aprovados (→ mostrar as relações).

## 2. O que o consultor faz com a base vazia ou só com itens fracos?

**Base vazia** (garantido pelo código):
- `compor_base` não manda uma base em branco. Manda uma frase: "A base ainda não tem nenhum item aprovado.
  Para qualquer pergunta, diga que a base não cobre o tema."
- O prompt manda dizer, com estas palavras, "A base não cobre <tema>." É a mesma frase que o golden set confere
  nas perguntas sem cobertura.
- Teste: `test_base_vazia_avisa_o_modelo` confere a frase que vai ao modelo. **O que o modelo responde** com a
  base vazia não foi testado com o Gemini (o golden set roda com os 19 itens).

**Base só de itens fracos** (garantido só pelo prompt):
- Não há regra no código. Os avisos são do prompt (`consultor.md`, "Avisos obrigatórios"):
  - resposta apoiada num único item: "isso vem de um único item da base";
  - evidência 1 ou tipo hipótese: dizer que ainda não foi validado;
  - evidência 2: avisar que se apoia em um único caso.
- No golden set, a base mistura os 4 níveis (3 itens de evidência 1, 7 de 2, 7 de 3 e 2 de 4). Nas perguntas que
  caem em itens fracos, o modelo avisou:
  - P06 e P17 (hipóteses): disse que é "hipótese com evidência de opinião", "ainda não testada";
  - P05, P13 e P20: avisou que o item de evidência 2 "se apoia em um único caso".
- O teste **não confere** esses avisos (é texto livre). Uma base só com itens fracos não foi rodada.

**Por que não no código, por enquanto:** o código só sabe quais itens a resposta citou depois que ela volta. Daria
para conferir os `[INS-n]` citados e, se todos forem de evidência ≤ 2, acrescentar um aviso fixo no fim da
resposta. Não fiz porque a spec pede o aviso no prompt e o golden set não mostrou o modelo esquecendo esse aviso.
Fica como a primeira correção se isso aparecer (ver "Rever quando").

## 3. O que o golden set mostrou?

**Como funciona** (`tests/golden/`): 19 itens fictícios e as 20 perguntas de `docs/perguntas-teste.md`, validadas
pelo comercial. Roda só à mão, com a chave (`pytest -m live tests/golden`), e confere em cada resposta:
- nenhum id inventado;
- nenhuma citação agrupada (`[INS-2, INS-7]`);
- pergunta coberta: cita **pelo menos um** dos ids esperados;
- pergunta sem cobertura (P03, P11, P12, P13 e P19): diz "A base não cobre".

Foram 3 rodadas.

**3.1 Rodada 1 (`gemini-3.5-flash-lite`): citação agrupada e 3 erros sem retry**
- **Citação agrupada:** 6 grupos como `[INS-2, INS-7]`, em 5 das 17 respostas (P01, P05, P16, P18 e P20). A tela
  só transforma `[INS-n]` sozinho em link, então o grupo aparecia como texto puro.
  - Pior: a expressão do teste também só achava `[INS-n]` sozinho. Na P16, o modelo citou `[INS-2, INS-7]` e o
    relatório registrou só `[16]`. A medição de cobertura saía menor que a real.
  - **Corrigido** (commit `fix: consultor cita um item por colchete`): o prompt pede um colchete por item
    ("[INS-2] [INS-7]"), o teste acha qualquer `INS-n` (dentro ou fora de grupo) e falha com citação agrupada.
- **3 erros do Gemini (500 e 504)** em P03, P04 e P07. As 3 perguntas não tiveram resposta.
  - O `llm.py` só repete 429, 503 e falha de rede, como pede a spec ("só para 429/503/timeout"). 500 (erro
    interno) e 504 (prazo estourado no servidor) caem direto no erro amigável.
  - As mesmas 3 perguntas passaram na rodada 3, sem mudança nenhuma: eram erros passageiros.
  - **Não corrigido** (está fora da spec). **Sugestão ao Davi:** incluir 500 e 504 em `CODIGOS_TEMPORARIOS`. A
    mudança é de uma linha mais os testes; o prazo total (ADR-003 §5.4) continua limitando o pior caso.

**3.2 Rodada 2 (`gemini-3.8-flash`): não mediu nada**
- As 20 perguntas deram erro do Gemini (429, 503 e 504). Na camada gratuita, o 3.8 Flash estava sem cota ou
  sobrecarregado.
- A comparação entre flash e flash-lite (que a spec lista para depois) continua sem dado. Precisa de uma chave paga.

**3.3 Rodada 3 (`gemini-3.5-flash-lite`, depois da correção): 21 passed**
- O teste de tokens e as 20 perguntas passaram.
- Nenhuma citação agrupada e nenhum id inventado.
- As 5 perguntas sem cobertura disseram "A base não cobre". Nas que tinham algo de outro contexto, o modelo mostrou
  isso deixando claro que era de outro caso (P03, P12 e P13), como o prompt pede.

**3.4 O que o teste não pega**

O teste passa, mas a régua é baixa. Três fraquezas aparecem lendo a rodada 3:
- **Cobertura parcial:** das 30 citações esperadas, saíram **26**. Ficaram de fora:
  - P05 ("por que perdemos propostas"): o INS-18 (proposta só por e-mail). Pior: a resposta diz que, fora o
    INS-17, "a base não possui dados sobre os motivos de perda". É uma lacuna falsa;
  - P10 ("perguntas da reunião de diagnóstico"): o INS-8 (resumo das dores 2 dias depois);
  - P16 ("práticas comprovadas"): o INS-3 (objeção "está caro", 2 de 3 fecharam);
  - P20 ("preparar reunião com indústria"): o INS-9 (perguntar orçamento e decisor).
- **A P16 mistura evidência 3 e 4.** A resposta diz "as práticas com resultados medidos (evidência 4) são" e põe
  na lista o INS-7, que é evidência 3. O usuário sai achando que a regra do piloto foi medida. É exatamente a
  distinção que a pergunta testa.
- **O critério é fraco:** basta citar **1** id esperado por pergunta. A P16 passaria citando só o INS-16, e a P20
  passaria citando só o INS-17.

**Não corrigido**, de propósito: com 19 itens e uma rodada por modelo, ajustar o prompt para as 4 faltas seria
ajustar para este golden set. O próximo passo é endurecer o teste, não o prompt:
- exigir uma fração mínima dos esperados (por exemplo, 2 de 3), em vez de 1;
- na P16, falhar se a resposta disser "evidência 4" e citar um item de evidência menor.

## Consequências

**Fica mais fácil:**
- confiar no que o consultor usa, porque só entra o que alguém aprovou na Fila;
- crescer a base sem RAG, porque cada item custa 73 tokens em vez de 293;
- clicar na fonte de cada afirmação, porque o formato `[INS-n]` é conferido pelo golden set;
- trocar de modelo e comparar, porque o golden set roda igual em qualquer um (falta só a cota).

**Fica mais difícil / custa:**
- os avisos de evidência fraca e o que citar dependem do modelo, sem regra no código;
- o modelo não vê o "o que foi feito", as relações entre itens nem a data;
- o golden set gasta cota a cada rodada e, na camada gratuita, pode não medir nada (rodada 2).

**Rever quando:**
- o Gemini der 500 ou 504 em uso real (→ incluir no retry, se o Davi aprovar);
- uma resposta usar só itens de evidência ≤ 2 sem avisar (→ aviso fixo pelo código, a partir dos `[INS-n]`
  citados);
- a base passar de 300 itens (→ RAG, T8), ou um golden set numa base maior mostrar o modelo perdendo itens
  antes disso;
- houver chave paga (→ rodar o golden set no 3.8 Flash e comparar qualidade, custo e latência com o flash-lite);
- o teste for endurecido (fração mínima de esperados, P16) e começar a falhar (→ aí sim ajustar o prompt).
