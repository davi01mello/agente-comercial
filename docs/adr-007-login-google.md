# ADR-007: Login com a conta Google do CITi

- **Status:** aceito
- **Data:** 2026-10-20
- **Autor:** Davi Mello (com o Claude)
- **Contexto:** T5. Antes de qualquer deploy com dado real (o banco passou a guardar o texto integral dos documentos
  do Drive, sem mascarar: [ADR-006](adr-006-importacao-drive.md))

## Decisões do Davi
- **Entra quem tem conta Google `@citi.org.br`.** Mais ninguém.
- **Sem papéis por enquanto:** todo membro logado conversa, registra, aprova/rejeita na Fila e sincroniza as fontes. O
  plano prevê curador e dono do playbook; se o time quiser separar, é uma lista de e-mails no `.env` e uma checagem nas
  rotas de aprovar e sincronizar (o ponto está marcado em `app/main.py`).

## Como funciona (`app/auth.py`)
1. `GET /auth/login` manda ao Google (fluxo de código de autorização, com `state`, `nonce` e PKCE).
2. O Google volta em `GET /auth/callback`. O servidor troca o código por um `id_token` **com o segredo do cliente**
   e **confere a assinatura, o emissor, a validade e o público** (`google.oauth2.id_token`).
3. Só entra quem tem `email_verified = true`, e-mail terminando em `@citi.org.br` **e** `hd = citi.org.br` (a conta é do
   Workspace do CITi: uma conta pessoal com e-mail parecido não passa). O `hd` que vai na URL é só um atalho de tela do
   Google; quem decide é o servidor.
4. A pessoa fica numa **sessão**: cookie assinado (`SESSION_SECRET`), `HttpOnly`, `SameSite=Lax`, `Secure` em produção,
   7 dias. Os dados dela entram na tabela `usuarios` (e-mail, nome, último acesso).

### O que a sessão muda
- **Toda rota exige login**, por uma dependência do app inteiro (`exigir_login`): uma rota nova nasce protegida. Ficam
  abertos a página, o `/health`, os arquivos estáticos e `/auth/*`. Um teste percorre TODAS as rotas e falha se uma
  responder sem sessão.
- **O autor vem da sessão.** `autor` (em `POST /insights`) e `por_quem` (em aprovar/rejeitar) deixaram de ser do
  corpo: se vierem, são ignorados. Ninguém registra nem aprova em nome de outra pessoa. Quando uma pessoa troca de nome
  no Google, os itens novos levam o nome novo.
- **POST com `Origin` de outro site é recusado** (403), além do `SameSite=Lax`.
- **Em produção o app não sobe sem login completo** (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET` com 32+
  caracteres, `APP_URL` em https). `/docs` e `/openapi.json` ficam desligados em produção (não passam pelo login).
- **No dev, sem `GOOGLE_CLIENT_ID`, o login fica desligado** e todos entram como "Dev local" (a tela mostra "sem
  login"). Para testar o login de verdade no computador: crie o cliente OAuth e ponha `http://localhost:8000/auth/callback`
  entre os endereços autorizados.

### Fora de escopo
Papéis, convite/bloqueio de pessoas, logout em todos os aparelhos e "esqueci a sessão em outro computador" (a sessão é
um cookie, sem lista no servidor; para derrubar todas, troque o `SESSION_SECRET`). Os scripts de linha de comando
(`importar_notion`, `sincronizar_drive`) e a sincronização automática do Drive rodam no servidor e não passam pelo login.

## Consequências
- O `.env` e a Railway ganham `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET` e `APP_URL`.
- A tela ganhou a entrada com o Google, o nome de quem entrou no topo e o botão Sair; o campo "Seu nome" saiu.
- Trocar o domínio (`AUTH_DOMINIO`) derruba quem estava logado com o domínio antigo na próxima requisição.
