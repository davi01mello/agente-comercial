# Modelo do playbook (Fase 0, v0)

Fonte da verdade do que o código deve refletir. Se mudar aqui, mude em `app/models.py`.

## Seções (eixo principal)
fundamentos · prospeccao · qualificacao · reuniao_diagnostico · proposta · negociacao_fechamento · pos_venda

## Filtros transversais
- Segmento: hotelaria, varejo, saúde, educação, indústria, setor público, startups, terceiro setor, outros
- Serviço: a preencher com o portfólio real do CITi
- Materiais: cases, templates, objeções e respostas

## Tipos de item
aprendizado · hipotese · regra · case · objecao · perfil_segmento · template

## Campos
Obrigatórios: titulo, tipo, secao, descricao, evidencia, autor, data, fonte, status.
Opcionais: segmento, servico, o_que_foi_feito, resultado, contexto_cliente, relacoes, motivo_obsolescencia.

## Escala de evidência
1 opinião · 2 observação única · 3 padrão repetido (3+) · 4 resultado medido.
Virar `regra` exige nível 3 ou 4 + aprovação do curador.

## Ciclo de vida (status)
proposto → validado → consolidado | obsoleto (com motivo). `historico_a_validar` = veio de fonte antiga.
