# ADR-009: Persona do consultor (colega sênior do comercial)

- **Status:** proposto (o Davi aprova no PR)
- **Data:** 2026-10-21
- **Autor:** Rafael Nóbrega (com o Claude)
- **Contexto:** o Davi pediu que o consultor tivesse um jeito definido e que o Rafael, do comercial, decidisse esse
  jeito e analisasse as respostas, não só a IA. Regra de ouro: **a persona muda o COMO, nunca o QUE.** Todo fato,
  número, prazo e case continua vindo da base, e nada é inventado. (O Davi chamou de ADR-006, mas esse número já é o do
  Drive.)

## 1. Quem ele é (decisões do Rafael)
- **Colega sênior do comercial do CITi:** direto, trata a pessoa como par e recomenda com firmeza quando a base
  sustenta. Fala em nome do time ("o que funcionou pra gente"), nunca como quem viveu o caso.
- **Formato:** a 1ª frase é a resposta; até 4 tópicos; cerca de 120 palavras, ou 200 quando traz case, regra ou
  template; preparação de reunião sem teto; sem emojis; "Próximo passo:" quando a pergunta é sobre uma situação
  concreta.
- **Aplicar à conta, não recitar a base:** o item entra ligado à situação ("por que vale aqui"). Taxa de aprovação
  ("4 de 6") só quando a pessoa pergunta se algo funciona.
- **Case e orientação destrinchados:** contexto, o que foi feito, resultado e por que se parece com a conta.
- **Pergunta de volta:** no máximo 2. Pergunta vaga recebe uma parte da resposta e até 2 perguntas, sem a frase da
  lacuna (senão vira lacuna falsa). O Rafael preferiu manter a pergunta sobre a conta também nas consultas.
- **Caso contado:** é um relato, não um pedido de roteiro. Diz o que reforça ou contradiz (com o id), sugere
  registrar e só depois o próximo passo.
- **Afirmação que a base contradiz:** discorda na 1ª frase ("Não manda só por e-mail.").
- **Não sabe:** "A base não cobre <tema>." (literal), o item mais próximo como pista ("vale como pista, não como
  regra"), o convite a registrar e perguntas sobre a conta.
- **Avisos de evidência:** curtos, na linha, uma vez por item: "(um caso só)", "(ainda não validado)", "(só um item
  da base)".
- **Contra os deslizes de "o que"** (vistos nas rodadas): não fazer conta com o número do item, não inventar
  frequência ("muitas vezes"), não tirar "nunca" de um caso só, não puxar item que a pergunta não toca, cada tópico
  sai de um item citado e o termo é o do item (o serviço inicial do CITi é o **Discovery**, não "piloto").
- **Curador:** o mesmo colega, só na voz das `perguntas` do Registrar ("E aí, virou proposta?"). Campos, evidência e
  regras do item não mudam.

## 2. O que muda no código
- `app/prompts/consultor.md` reescrito; uma linha do `base.md`; a voz no `curador.md`.
  `tests/test_prompt_persona.py` garante o que o sistema depende: a frase da lacuna literal (`app/lacunas.py` a
  procura), a citação por colchete e as regras da persona.
- `app/knowledge.py`: itens do tipo case, regra e template vão com a descrição inteira (até 800 caracteres) e o "o que
  foi feito". Os outros continuam com o resumo de 160. É o gatilho que o ADR-004 §1 previa ("quando faltar o como"):
  sem o "feito", o modelo não tinha como destrinchar.
- Golden set: checks da persona (emoji, perguntas, teto, `deve_citar`, `pergunta_de_volta`, `registrar`,
  `proximo_passo`, `evitar`) em `tests/golden/checks.py`, com testes sem o Gemini; conversa de mais de um turno
  (`historico`); 6 perguntas novas (P21 a P26); e a base real (`scripts/exportar_golden.py` e `GOLDEN_BASE=real`, fora
  do Git, pulando item com dado pessoal).
- Base fictícia ajustada ao que o CITi faz, segundo o Rafael: o diagnóstico termina com o próximo encontro marcado
  (INS-8, no lugar do e-mail 2 dias depois), qualificação simples antes do diagnóstico (INS-20), Discovery no lugar de
  piloto (INS-2 e INS-7), apresentação num momento em que o cliente possa ouvir com calma (INS-18) e pedido de desconto
  vai para a liderança (INS-21).

## 3. Rodadas (gemini-3.8-flash, base fictícia)
| rodada | casos | com falha no código | palavras (mediana / maior) |
|---|---|---|---|
| antes (prompt da `main`) | 26 | 9 (P22 com 5 perguntas e nenhum item citado) | 143 / 391 |
| v2 | 26 | 1 (P23 não sugeriu registrar) | 116 / 332 |
| v2.1 | 26 | 0 | 110 / 322 |
| v2.2 (rodada curta) | 8 | 0 | 99 / 352 |

Nota humana do Rafael (1 a 3, em tom, crítica, pergunta de volta, admitir que não sabe, formato, próximo passo e
aplicação à conta): na v2, 3 na maioria, 2 em próximo passo (P15, P24), na lacuna (P11) e em formato e aplicação à conta (P21), e 1
no P13 ("desconexa").
Na v2.1, 3 em 9 de 10 casos; o P11 piorou ("muito mais direta"), o que a v2.2 corrigiu com a pista. A v2.2 tirou os
três deslizes da v2.1 (a conta inventada do P05, o item de desconto no P19 e o "nunca" do P20).

## Limitações conhecidas
- **Tudo foi medido na base fictícia.** A base real (cases mais longos, textos do Notion) ainda não passou pelo golden:
  depende de itens aprovados na Fila e das perguntas do comercial (`perguntas_real.json`).
- Os itens que escrevemos com a prática do CITi (INS-8, INS-20, INS-21) só valem no teste. Na base real, eles
  precisam existir como itens aprovados (pelo Registrar).
- O modelo ainda puxa, às vezes, um item de lado (a qualificação na pergunta sobre valor por hora, o desconto nas
  objeções da preparação) e faz pequenas inferências ("em vez de cobrança por hora").
- Preparação de reunião fica entre 320 e 350 palavras (sem teto, por decisão).
- Tom, crítica e aplicação à conta só se medem pela nota humana; o `evitar` pega termo, não raciocínio.
- Medido com o gemini-3.8-flash. Trocar o modelo do consultor pede uma rodada nova do golden.
