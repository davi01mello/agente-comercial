/* Cérebro Comercial CITi: interface (sem framework e sem build).

   Fala sempre com a API de verdade (FastAPI). Não há base de exemplo nem modo de demonstração: sem servidor, a tela
   avisa e não mostra nada inventado.
   Regra de segurança: todo texto que vem do usuário ou do modelo entra na página como texto (textContent),
   nunca como HTML. O único innerHTML é o SVG do mascote, que é gerado aqui mesmo. */
"use strict";

(() => {
  // ---------------------------------------------------------------- utilitários
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  function el(tag, props = {}, ...filhos) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const f of filhos.flat()) {
      if (f == null || f === false) continue;
      n.append(f instanceof Node ? f : document.createTextNode(String(f)));
    }
    return n;
  }

  const normalizar = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const capital = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);
  const dataBr = (iso) => (iso ? iso.split("-").reverse().join("/") : "");
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

  const guardar = {
    ler(chave) { try { return localStorage.getItem(chave); } catch { return null; } },
    escrever(chave, valor) { try { localStorage.setItem(chave, valor); } catch { /* sem armazenamento: segue sem lembrar */ } },
  };

  // ---------------------------------------------------------------- vocabulário do playbook
  const SECOES = [
    ["fundamentos", "Fundamentos"],
    ["prospeccao", "Prospecção"],
    ["qualificacao", "Qualificação"],
    ["reuniao_diagnostico", "Reunião e diagnóstico"],
    ["proposta", "Proposta"],
    ["negociacao_fechamento", "Negociação e fechamento"],
    ["pos_venda", "Pós-venda"],
  ];
  const NOME_SECAO = Object.fromEntries(SECOES);
  const TIPOS = {
    aprendizado: "Aprendizado", hipotese: "Hipótese", regra: "Regra", case: "Case",
    objecao: "Objeção", perfil_segmento: "Perfil de segmento", template: "Template",
  };
  const EVIDENCIA = { 1: "Opinião", 2: "Observação única", 3: "Padrão repetido", 4: "Resultado medido" };
  const STATUS = {
    proposto: "Proposto", validado: "Validado", consolidado: "Consolidado",
    obsoleto: "Obsoleto", historico_a_validar: "Histórico a validar",
  };
  const RELACOES = { reforca: "reforça", contradiz: "contradiz", duplica: "duplica", substitui: "substitui" };
  const SEGMENTOS = ["hotelaria", "varejo", "saúde", "educação", "indústria", "setor público", "startups", "terceiro setor", "outros"];

  const estado = {
    modo: "conectando",  // "vivo" (o servidor respondeu) | "fora" (não respondeu)
    tela: "conversar",
    itens: [],
    conversa: [],
    ocupado: false,
    reg: novoReg(),  // o rascunho do curador em andamento
    filtro: { secao: null, segmento: null, busca: "", historico: false, origem: null, mostrar: {} },
    fontes: null,  // o resumo de GET /fontes/resumo
    filtroFontes: { status: null, busca: "", origem: null },
    sync: { id: null, dry: false, exec: null, acompanhando: false, teto: 1, origem: "notion" },
    fila: { origem: null, selecionados: new Set(), mostrar: 30, confirmando: false, aprovando: null, visiveis: [],
      atual: null, processando: null, erro: null, ajuda: false },
    focoAntes: null,
    pessoa: null,  // quem entrou (GET /auth/eu): {email, nome, dev, dominio}; null enquanto não entrou
    erroCarga: null,  // a mensagem, quando a base não carregou
    sobreItem: null,  // o item aberto no centro ("INS-12"): a pergunta pode levá-lo como contexto
    sobreTirado: false,  // a pessoa tirou o chip "Sobre INS-12" deste item
    ultimaResposta: null,  // os códigos citados na última resposta do Cérebro, na ordem das notas (o mapa usa)
    telaHash: null,  // o endereço da tela aberta no centro ("#fila", "#item/INS-12")
    abas: [],  // as abas abertas além do Hoje (os endereços), lembradas no localStorage
    pastas: new Set(),  // as pastas da árvore que a pessoa abriu
  };
  const aoVivo = () => estado.modo === "vivo";

  // ---------------------------------------------------------------- mascote (a marca)
  // Um cerebrozinho em traço que levanta uma nota (a prova), com o anel do orbe do CITi na cintura. O desenho é o do
  // Design System (Cerebro.mascote) e só usa classes: as cores vêm dos tokens no CSS. O "símbolo" é a versão pequena
  // (barra lateral, avatar da resposta e botão do celular). Os humores trocam a boca, os olhos e a nota: "pensando"
  // (esperando o modelo), "sem-resposta" (o modelo falhou) e "nota-em-branco" (base vazia). Erro nunca vai no rosto
  // dele: fica no texto.
  const CONTORNO = "M37 92C29 92 25 84 29 78C23 74 23 63 31 61C29 52 37 46 45 49C47 41 57 39 61 45C64 39 75 39 78 47C86 45 93 52 90 60C96 63 96 74 90 78C93 86 86 93 79 91C74 96 65 96 61 92C56 96 43 96 37 92Z";
  const SULCOS = "M61 45C59 50 62 53 60 57M38 56q5-4 10 0M72 53q5-4 10 0M32 86q4-3.5 8-1M80 85q4-2.5 8 1";
  const HUMORES = {
    padrao: { olhoY: 62, olhoA: 10, boca: "M54 77q6 4.5 12 0", nota: "acena" },
    pensando: { olhoY: 58, olhoA: 9, boca: "M57 78h6", nota: "parada" },
    "sem-resposta": { olhoY: 62, olhoA: 10, boca: "M55 80q5-3.6 10 0", nota: "apagada" },
    "nota-em-branco": { olhoY: 62, olhoA: 10, boca: "M54 77q6 4.5 12 0", nota: "branca" },
  };
  let seqMascote = 0;
  function mascote({ forma = "", humor = "padrao" } = {}) {
    if (forma === "simbolo") {
      return `<svg viewBox="20 24 88 76" aria-hidden="true" focusable="false"><path class="mc-corpo grosso" d="${CONTORNO}"/><path class="mc-sulco grosso" d="M61 45C59 50 62 53 60 57"/><rect class="mc-olho" x="46.5" y="61" width="8" height="12" rx="4"/><rect class="mc-olho" x="65.5" y="61" width="8" height="12" rx="4"/><path class="mc-boca grosso" d="M53 78q7 5 14 0"/><g transform="rotate(9 96 38)"><rect class="mc-nota" x="85" y="26" width="22" height="24" rx="6"/><path class="mc-nota-linha" d="M90.5 34h11M90.5 39.5h11M90.5 45h6"/></g></svg>`;
    }
    const h = HUMORES[humor] || HUMORES.padrao;
    const id = `masc${++seqMascote}`;  // o gradiente do anel precisa de um id por desenho
    const linhas = h.nota === "branca" ? "" : '<path class="mc-nota-linha" d="M97 34h12M97 39h12M97 44h7"/>';
    const pensa = humor === "pensando"
      ? '<g class="mc-pensa"><circle cx="50" cy="31" r="2.2"/><circle cx="60" cy="28" r="2.2"/><circle cx="70" cy="31" r="2.2"/></g>'
      : "";
    return `<svg viewBox="0 0 120 120" aria-hidden="true" focusable="false">
      <defs><linearGradient id="${id}" x1="0" x2="1"><stop offset="0" class="mc-anel-ponta"/><stop offset=".5" class="mc-anel-meio"/><stop offset="1" class="mc-anel-ponta"/></linearGradient></defs>
      <path class="mc-chao" d="M14 104H106"/><path class="mc-chao cruz" d="M60 99v10M55 104h10"/>
      <g transform="rotate(-12 60 76)"><path class="mc-anel tras" d="M10 76A50 12 0 0 1 110 76" stroke="url(#${id})"/></g>
      <path class="mc-pe" d="M50 94.5v9.5M70 94.5v9.5"/>
      <g class="mc-respira"><path class="mc-corpo" d="${CONTORNO}"/><path class="mc-sulco" d="${SULCOS}"/>
        <rect class="mc-olho piscar" x="48" y="${h.olhoY}" width="6" height="${h.olhoA}" rx="3"/><rect class="mc-olho piscar" x="66" y="${h.olhoY}" width="6" height="${h.olhoA}" rx="3"/>
        <ellipse class="mc-bochecha" cx="42.5" cy="76" rx="4" ry="2.4"/><ellipse class="mc-bochecha" cx="77.5" cy="76" rx="4" ry="2.4"/>
        <path class="mc-boca" d="${h.boca}"/></g>
      <g transform="rotate(-12 60 76)"><path class="mc-anel" d="M110 76A50 12 0 0 1 10 76" stroke="url(#${id})"/></g>
      <g class="mc-mao ${h.nota}"><path class="mc-pe braco" d="M90 66 99 51"/><g transform="rotate(9 103 38)"><rect class="mc-nota" x="92" y="26" width="22" height="24" rx="5"/>${linhas}</g></g>
      ${pensa}</svg>`;
  }
  // Pinta o mascote em todo [data-mascote] da página (o valor é a forma; o data-humor, o humor).
  function pintarMascotes(raiz = document) {
    for (const alvo of $$("[data-mascote]", raiz)) alvo.innerHTML = mascote({ forma: alvo.dataset.mascote, humor: alvo.dataset.humor });
  }
  function mascoteEm(classe, { forma = "", humor = "padrao" } = {}) {
    const s = el("span", { class: `mascote ${classe}`, "data-mascote": forma, "data-humor": humor, "aria-hidden": "true" });
    s.innerHTML = mascote({ forma, humor });
    return s;
  }
  // Quando o Cérebro responde ou um item é aprovado, o mascote da barra acena uma vez (no lugar da rajada da cena).
  function pulsarMascote() {
    for (const m of $$(".mascote.marca-viva")) {
      m.classList.remove("acenou");
      void m.offsetWidth;  // reinicia a animação
      m.classList.add("acenou");
    }
  }

  // O que é enfeite nunca derruba o início da página: um erro aqui vai para o console e a tela segue. Foi assim que a
  // tela ficou em branco em 27/10 (o fundo em canvas quebrava com a janela em 0 px e levava o iniciar() junto).
  function seguro(fn, nome) {
    try {
      return fn();
    } catch (e) {
      console.error(`Cérebro: a peça "${nome}" falhou e foi pulada.`, e);
      return undefined;
    }
  }

  // ---------------------------------------------------------------- API
  class ErroApi extends Error {
    constructor(msg, status) { super(msg); this.status = status; }
  }
  function mensagemErro(status, dados) {
    const det = dados && dados.detail;
    if (status === 502) return "O modelo não respondeu. Tente de novo em instantes.";
    if (status === 503) return "O serviço não está configurado. Avise quem cuida do servidor.";
    if (typeof det === "string") return det;
    if (Array.isArray(det)) return det.map((e) => `${(e.loc || []).slice(1).join(".") || "campo"}: ${e.msg}`).join(" · ");
    if (status === 404) return "Não achei isso no servidor. Recarregue a página.";
    return "Algo deu errado do lado do servidor. Tente de novo em instantes.";
  }
  async function chamar(metodo, url, corpo, sinal) {
    let r;
    try {
      r = await fetch(url, {
        method: metodo,
        headers: corpo && !(corpo instanceof FormData) ? { "Content-Type": "application/json" } : {},  // o FormData põe o dele
        body: corpo instanceof FormData ? corpo : (corpo ? JSON.stringify(corpo) : undefined),
        signal: sinal,
      });
    } catch (e) {
      if (e && e.name === "AbortError") throw new ErroApi("Parei de esperar a resposta.", -1);  // o "Parar" do chat
      throw new ErroApi("Sem conexão com o servidor. Confira a internet e tente de novo.", 0);
    }
    let dados = null;
    try { dados = await r.json(); } catch { /* resposta sem JSON */ }
    if (r.status === 401 && estado.modo === "vivo") {  // a sessão acabou (ou nunca existiu): volta para a entrada
      mostrarEntrada(estado.pessoa ? "Sua sessão acabou. Entre de novo." : "");
      throw new ErroApi("Entre com a sua conta Google do CITi.", 401);
    }
    if (!r.ok) throw new ErroApi(mensagemErro(r.status, dados), r.status);
    return dados;
  }

  // ---- login (T5): GET /auth/eu diz quem entrou; sem sessão, a tela de entrada cobre o app
  const MOTIVOS_LOGIN = {
    dominio: "Essa conta não é do CITi. Escolha a conta @citi.org.br.",
    cancelado: "Você cancelou a entrada. Quando quiser, é só tentar de novo.",
    erro: "Não consegui concluir a entrada. Tente de novo.",
  };
  function mostrarEntrada(mensagem) {
    estado.pessoa = null;
    const caixaAviso = $("#entrada-aviso");
    caixaAviso.textContent = mensagem || "";
    caixaAviso.hidden = !mensagem;
    $("#entrada-login").hidden = false;
    document.body.classList.add("sem-login");
    pintarVoce();
    $("#entrada-botao").focus({ preventScroll: true });
  }
  async function verificarLogin() {
    // Volta do Google com ?login=<motivo>: mostra o motivo e limpa o endereço
    const motivo = new URLSearchParams(location.search).get("login");
    if (motivo) history.replaceState(null, "", location.pathname + location.hash);
    try {
      const r = await fetch("/auth/eu", { headers: { Accept: "application/json" } });
      if (r.status === 401) { mostrarEntrada(MOTIVOS_LOGIN[motivo] || ""); return false; }
      if (!r.ok) throw new Error(String(r.status));
      estado.pessoa = await r.json();
    } catch {
      aviso("Não consegui confirmar quem está logado. Recarregue a página.", "erro");
      return false;
    }
    $("#entrada-dominio").textContent = `@${estado.pessoa.dominio}`;
    $("#entrada-login").hidden = true;
    document.body.classList.remove("sem-login");
    pintarVoce();
    return true;
  }
  function pintarVoce() {
    const caixa = $("#voce");
    const p = estado.pessoa;
    caixa.hidden = !p;
    if (!p) { caixa.replaceChildren(); return; }
    const iniciais = p.nome.split(/\s+/).filter(Boolean).slice(0, 2).map((x) => x[0]).join("").toUpperCase();
    caixa.replaceChildren(...[  // replaceChildren(null) escreveria o texto "null": só entra o que existe
      el("span", { class: "avatar", "aria-hidden": "true", text: iniciais || "?" }),
      el("span", { class: "quem-entrou" },
        el("span", { class: "nome", title: p.email, text: p.nome }),
        el("span", { class: "t-legenda", text: p.dev ? "Sem login neste computador" : `@${p.dominio}` })),
      p.dev ? null : el("button", { type: "button", class: "btn fantasma", onclick: sairDoApp }, "Sair")].filter(Boolean));
    pintarModo();
  }
  async function sairDoApp() {
    try { await fetch("/auth/logout", { method: "POST" }); } catch { /* sai do mesmo jeito */ }
    location.reload();
  }
  async function detectarModo() {
    try {
      const ctrl = new AbortController();
      const limite = setTimeout(() => ctrl.abort(), 2500);
      const r = await fetch("/health", { signal: ctrl.signal });
      clearTimeout(limite);
      if (!r.ok) return "fora";
      const d = await r.json();
      return d && d.status === "ok" ? "vivo" : "fora";
    } catch {
      return "fora";
    }
  }
  // A API entrega no máximo 100 itens por chamada: sem pedir as páginas seguintes, a Fila de uma importação grande
  // (centenas de itens vindos do Notion) mostraria só os 100 mais recentes e esconderia o resto.
  async function itensDoStatus(status) {
    const porId = new Map();
    for (let offset = 0; ; offset += 100) {
      const r = await chamar("GET", `/insights?status=${status}&limit=100&offset=${offset}`);
      for (const i of r.itens) porId.set(i.id, i);
      if (!r.itens.length || offset + r.itens.length >= r.total) break;
    }
    return [...porId.values()];
  }
  async function carregarItens() {
    try {
      const porStatus = await Promise.all(
        ["validado", "consolidado", "proposto", "historico_a_validar"].map(itensDoStatus),
      );
      estado.itens = porStatus.flat().map((i) => ({ ...i, codigo: `INS-${i.id}` }));
      estado.erroCarga = null;
    } catch (e) {
      estado.erroCarga = e.message;
      aviso(`Não consegui carregar a base: ${e.message}`, "erro");
    }
    try { estado.fontes = await chamar("GET", "/fontes/resumo"); } catch { /* sem o resumo, o contador fica em 0 */ }
    atualizarNumeros();
  }

  // ---------------------------------------------------------------- peças comuns
  function aviso(msg, tipo = "ok") {
    const t = el("div", { class: `torrada ${tipo}`, role: tipo === "erro" ? "alert" : "status", text: msg });
    $("#torradas").append(t);
    setTimeout(() => t.remove(), 5600);
  }
  // Quem escreve, registra e aprova é a pessoa que entrou com o Google (o servidor decide o autor pela sessão: o nome
  // daqui é só para mostrar na tela).
  function nomeDoUsuario() { return estado.pessoa ? estado.pessoa.nome : "Você"; }
  function exigirAutor() { return nomeDoUsuario(); }
  function acharItem(codigo) {
    return estado.itens.find((i) => i.codigo === codigo) || null;  // só o que existe no banco
  }
  function itemPorId(id) {
    return estado.itens.find((i) => i.id === id) || null;
  }
  const ICONES = {
    busca: [["circle", {"cx":  "11", "cy":  "11", "r":  "7"}], ["path", {"d":  "m20 20-3.5-3.5"}]],
    hoje: [["path", {"d":  "M3 10.5 12 3l9 7.5"}], ["path", {"d":  "M5 9.5V21h14V9.5"}]],
    camadas: [["path", {"d":  "m12 3 9 5-9 5-9-5z"}], ["path", {"d":  "m3 13 9 5 9-5"}]],
    mapa: [["circle", {"cx":  "6", "cy":  "6", "r":  "2.5"}], ["circle", {"cx":  "18", "cy":  "8", "r":  "2.5"}], ["circle", {"cx":  "10", "cy":  "18", "r":  "2.5"}], ["path", {"d":  "M8.4 6.4 15.6 7.6M6.8 8.4l2.4 7.2M16.6 10.1l-5 6"}]],
    fila: [["path", {"d":  "M3 13h5l1.5 3h5L16 13h5"}], ["path", {"d":  "M5.5 5h13L21 13v6H3v-6z"}]],
    lacuna: [["circle", {"cx":  "12", "cy":  "12", "r":  "9"}], ["path", {"d":  "M9.5 9.2a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.3-2.5 4"}], ["path", {"d":  "M12 17.5h.01"}]],
    preparar: [["rect", {"x":  "3.5", "y":  "5", "width":  "17", "height":  "15.5", "rx":  "2"}], ["path", {"d":  "M8 3v4M16 3v4M3.5 10h17"}], ["path", {"d":  "m9 15 2 2 4-4"}]],
    fontes: [["ellipse", {"cx":  "12", "cy":  "5.5", "rx":  "7.5", "ry":  "2.5"}], ["path", {"d":  "M4.5 5.5v13c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-13"}], ["path", {"d":  "M4.5 12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5"}]],
    clipe: [["path", {"d":  "m20 11.5-8.2 8.2a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8"}]],
    enviar: [["path", {"d":  "M12 19V5M6 11l6-6 6 6"}]],
    seta: [["path", {"d":  "M5 12h14M13 6l6 6-6 6"}]],
    registrar: [["path", {"d":  "M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"}], ["path", {"d":  "m13.5 6.5 4 4"}]],
    refazer: [["path", {"d":  "M20 12a8 8 0 1 1-2.3-5.7"}], ["path", {"d":  "M20 4v5h-5"}]],
    copiar: [["rect", {"x":  "8.5", "y":  "8.5", "width":  "12", "height":  "12", "rx":  "2"}], ["path", {"d":  "M15.5 8.5V5a1.5 1.5 0 0 0-1.5-1.5H5A1.5 1.5 0 0 0 3.5 5v9A1.5 1.5 0 0 0 5 15.5h3.5"}]],
    "seta-dir": [["path", {"d":  "m9 6 6 6-6 6"}]],
    x: [["path", {"d":  "M6 6l12 12M18 6 6 18"}]],
    mais: [["path", {"d":  "M12 5v14M5 12h14"}]],
    usuarios: [["circle", {"cx":  "9", "cy":  "8", "r":  "3.5"}], ["path", {"d":  "M2.5 20c.8-3.5 3.4-5.5 6.5-5.5s5.7 2 6.5 5.5"}], ["path", {"d":  "M16 4.6a3.5 3.5 0 0 1 0 6.8M18.5 14.8c1.6.8 2.6 2.6 3 5.2"}]],
    alerta: [["path", {"d":  "M12 3.5 2.5 20h19z"}], ["path", {"d":  "M12 10v4.5M12 17.5h.01"}]],
    brilho: [["path", {"d":  "M12 3.5 13.8 9l5.7 1.8-5.7 1.8L12 18.2l-1.8-5.6-5.7-1.8L10.2 9z"}], ["path", {"d":  "M19 3v3M17.5 4.5h3"}]],
    voltar: [["path", {"d":  "m15 6-6 6 6 6"}]],
    ligacao: [["path", {"d":  "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"}], ["path", {"d":  "M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"}]],
    escudo: [["path", {"d":  "M12 3 4.5 6v5.5c0 4.5 3.2 8 7.5 9.5 4.3-1.5 7.5-5 7.5-9.5V6z"}], ["path", {"d":  "M12 8.5v4M12 15.5h.01"}]],
    check: [["path", {"d":  "m5 12.5 4.5 4.5L19 7.5"}]],
    relogio: [["circle", {"cx":  "12", "cy":  "12", "r":  "9"}], ["path", {"d":  "M12 7v5l3 2"}]],
    doc: [["path", {"d":  "M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"}], ["path", {"d":  "M14 3v5h5M8.5 13h7M8.5 16.5h5"}]],
    sinc: [["path", {"d":  "M20 12a8 8 0 0 1-14 5.3M4 12a8 8 0 0 1 14-5.3"}], ["path", {"d":  "M18 3v4h-4M6 21v-4h4"}]],
    recolher: [["rect", {"x":  "3.5", "y":  "4.5", "width":  "17", "height":  "15", "rx":  "2"}], ["path", {"d":  "M9.5 4.5v15"}]],
    chat: [["path", {"d":  "M20.5 12a8 8 0 0 1-11.8 7L3.5 20.5 5 15.6A8 8 0 1 1 20.5 12z"}]],
  };
  const NS_SVG = "http://www.w3.org/2000/svg";
  function icone(nome, classe = "ic") {
    const s = document.createElementNS(NS_SVG, "svg");
    s.setAttribute("class", classe);
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("aria-hidden", "true");
    for (const [tag, attrs] of ICONES[nome] || []) {
      const n = document.createElementNS(NS_SVG, tag);
      for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
      s.append(n);
    }
    return s;
  }
  // A evidência: 1 a 4 segmentos acesos (a cor nunca vai sozinha; o leitor de tela ouve o nome).
  function trilha(n, grande = false) {
    const s = el("span", { class: `trilha n${n}${grande ? " g" : ""}`, role: "img", "aria-label": `Evidência ${n} de 4: ${EVIDENCIA[n]}` });
    for (let i = 1; i <= 4; i++) s.append(el("i"));
    return s;
  }
  function pontoEv(n) { return el("span", { class: `ponto-ev e${n}`, "aria-hidden": "true" }); }
  function metaItem(it, { secao = true } = {}) {
    const m = el("div", { class: "meta" });
    m.append(el("span", { class: "etiqueta tipo", "data-tipo": it.tipo, text: TIPOS[it.tipo] || it.tipo }));
    if (secao) m.append(el("span", { class: "etiqueta", text: NOME_SECAO[it.secao] || it.secao }));
    m.append(el("span", { class: "etiqueta", text: it.segmento ? capital(it.segmento) : "Todos os segmentos" }));
    if (it.status && it.status !== "validado" && it.status !== "proposto") {
      m.append(el("span", { class: `etiqueta status-${it.status}`, text: STATUS[it.status] }));
    }
    return m;
  }
  function avisosDeEvidencia(it) {
    const lista = [...(it.avisos || [])];
    if (it.tipo === "hipotese") lista.push("Hipótese: ainda não foi testada.");
    else if (it.evidencia === 1) lista.push("Evidência 1: é uma opinião, sem caso que sustente.");
    else if (it.evidencia === 2) lista.push("Evidência 2: se apoia em um único caso.");
    if (it.status === "historico_a_validar") lista.push("Veio de uma fonte antiga e ainda não foi revisado.");
    return [...new Set(lista)];
  }
  function listaAvisos(lista) {
    return el("ul", { class: "avisos" }, lista.map((a) => el("li", { class: "aviso", text: a })));
  }
  function relacaoChip(rel, origem, removivel) {
    const alvo = itemPorId(rel.relacionado_id, origem);
    const codigo = alvo ? alvo.codigo : `INS-${rel.relacionado_id}`;
    const chip = el("span", { class: "rel", "data-tipo": rel.tipo },
      el("b", { text: RELACOES[rel.tipo] || rel.tipo }),
      el("button", { type: "button", class: "cita", onclick: () => abrirItem(codigo), title: alvo ? alvo.titulo : "Abrir item" }, codigo));
    if (removivel) chip.append(el("button", { type: "button", "aria-label": `Remover relação com ${codigo}`, onclick: removivel, text: "×" }));
    return chip;
  }
  function vazio(titulo, texto, ...extra) {
    return el("div", { class: "vazio" }, mascoteEm("m mascote-vazio", { humor: "padrao" }), el("h3", { text: titulo }), el("p", { text: texto }), ...extra);
  }
  function autoAltura(t) {
    t.style.height = "auto";
    t.style.height = `${Math.min(t.scrollHeight, 150)}px`;
  }

  // Texto do modelo -> parágrafos, listas, negrito, a linha do próximo passo e as fontes como notas numeradas (sem HTML
  // do modelo). A nota é o número da fonte na resposta (1, 2, 3, na ordem em que aparecem), e o mesmo número vai ao
  // cartão do mapa. `notas` é o Map código -> número da resposta; sem ele (a fala da própria pessoa), a citação não
  // ganha número.
  const RE_PROXIMO = /^\s*(?:\*\*)?\s*Pr[óo]ximo passo(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.+)$/i;
  function inline(txt, docs, notas) {
    const partes = [];
    const re = /\[((?:EX|INS)-\d+)\]|\[(DOC-\d+)\]|\*\*([^*]+)\*\*/g;
    let i = 0, m;
    while ((m = re.exec(txt))) {
      if (m.index > i) partes.push(document.createTextNode(txt.slice(i, m.index)));
      if (m[1]) partes.push(chipCitacao(m[1], notas));
      else if (m[2]) partes.push(chipDocumento(m[2], docs, notas));
      else partes.push(el("strong", { text: m[3] }));
      i = re.lastIndex;
    }
    if (i < txt.length) partes.push(document.createTextNode(txt.slice(i)));
    return partes;
  }
  function blocoProximo(texto, docs, notas) {
    return el("div", { class: "proximo" }, icone("seta-dir", "ic"),
      el("p", {}, el("b", { text: "Próximo passo:" }), " ", ...inline(texto, docs, notas)));
  }
  function formatar(texto, docs, notas = null) {
    const frag = document.createDocumentFragment();
    for (const bloco of String(texto).trim().split(/\n{2,}/)) {
      const linhas = bloco.split("\n").filter((l) => l.trim());
      if (!linhas.length) continue;
      if (linhas.every((l) => /^\s*[-*•]\s+/.test(l))) {
        frag.append(el("ul", {}, linhas.map((l) => el("li", {}, inline(l.replace(/^\s*[-*•]\s+/, ""), docs, notas)))));
      } else if (linhas.every((l) => /^\s*\d+[.)]\s+/.test(l))) {
        frag.append(el("ol", {}, linhas.map((l) => el("li", {}, inline(l.replace(/^\s*\d+[.)]\s+/, ""), docs, notas)))));
      } else {
        let p = null;
        for (const l of linhas) {
          const m = RE_PROXIMO.exec(l);
          if (m) { p = null; frag.append(blocoProximo(m[1], docs, notas)); continue; }  // sem a linha, nada aparece
          if (!p) { p = el("p"); frag.append(p); } else p.append(el("br"));
          p.append(...inline(l, docs, notas));
        }
      }
    }
    return frag;
  }

  // A nota: um quadrado com o número da fonte. A do documento do Drive (ou do anexo) é tracejada, sem preenchimento.
  function nota(numero, doc = false) {
    return el("span", { class: `nota${doc ? " doc" : ""}`, "aria-hidden": "true", text: String(numero) });
  }
  function numeroDaNota(notas, codigo) {
    if (!notas) return null;
    if (!notas.has(codigo)) notas.set(codigo, notas.size + 1);
    return notas.get(codigo);
  }

  // A prévia ao passar o mouse (ou focar) numa nota. É um balão só, fora do painel, para o painel não cortá-lo.
  const previa = { no: null, dono: null };
  function mostrarPrevia(dono, conteudo) {
    if (!previa.no) {
      previa.no = el("div", { class: "previa-cita", id: "previa-cita", role: "tooltip", hidden: true });
      document.body.append(previa.no);
    }
    previa.dono = dono;
    previa.no.replaceChildren(...conteudo);
    previa.no.hidden = false;
    dono.setAttribute("aria-describedby", "previa-cita");
    const r = dono.getBoundingClientRect();
    const x = Math.min(Math.max(8, r.left), Math.max(8, innerWidth - previa.no.offsetWidth - 8));
    let y = r.top - previa.no.offsetHeight - 8;
    if (y < 8) y = r.bottom + 8;  // sem espaço em cima: abre embaixo
    previa.no.style.left = `${x}px`;
    previa.no.style.top = `${y}px`;
  }
  function esconderPrevia(dono) {
    if (!previa.no || (dono && previa.dono !== dono)) return;
    previa.no.hidden = true;
    if (previa.dono) previa.dono.removeAttribute("aria-describedby");
    previa.dono = null;
  }
  function ligarPrevia(no, montar) {
    no.addEventListener("mouseenter", () => mostrarPrevia(no, montar()));
    no.addEventListener("focus", () => mostrarPrevia(no, montar()));
    no.addEventListener("mouseleave", () => esconderPrevia(no));
    no.addEventListener("blur", () => esconderPrevia(no));
  }
  function chipCitacao(codigo, notas) {
    const item = acharItem(codigo);
    if (!item) return document.createTextNode(`[${codigo}]`);  // fora da base carregada: texto simples, sem destino inventado
    const n = numeroDaNota(notas, codigo);
    const chip = el("button", { type: "button", class: "cita", "aria-label": `${n ? `Fonte ${n}: ` : ""}${codigo}, ${item.titulo}`,
      onclick: () => abrirItem(codigo) }, n ? nota(n) : null, codigo);
    ligarPrevia(chip, () => [
      el("span", { class: "t-rotulo", text: `${codigo} · ${TIPOS[item.tipo] || item.tipo} · ${NOME_SECAO[item.secao] || item.secao}` }),
      el("strong", { text: item.titulo }),
      el("span", { class: "evid" }, trilha(item.evidencia), EVIDENCIA[item.evidencia]),
      el("span", { class: "t-legenda", text: `${item.segmento ? capital(item.segmento) : "Todos os segmentos"} · clique para abrir` }),
    ]);
    return chip;
  }

  // [DOC-n]: um documento do Drive (ou o texto de um anexo) que o consultor leu mas o time ainda não revisou. Abre o
  // documento fora da página. Só vira link se o servidor mandou esse documento junto com a resposta (o modelo não inventa
  // um destino).
  function chipDocumento(codigo, docs, notas) {
    const doc = (docs || []).find((d) => `DOC-${d.id}` === codigo);
    const url = doc ? linkSeguro(doc.url) : null;
    if (!url) return document.createTextNode(`[${codigo}]`);
    const n = numeroDaNota(notas, codigo);
    const chip = el("a", {
      class: "cita doc", href: url, target: "_blank", rel: "noopener noreferrer",
      "aria-label": `${n ? `Fonte ${n}: ` : ""}${codigo}, documento ainda não revisado: ${doc.titulo}`,
    }, n ? nota(n, true) : null, codigo);
    ligarPrevia(chip, () => [
      el("span", { class: "t-rotulo", text: `${codigo} · Documento` }),
      el("strong", { text: doc.titulo }),
      el("span", {}, el("span", { class: "selo alerta", text: "Não revisado" })),
      el("span", { class: "t-legenda", text: `${doc.categoria ? `pasta ${doc.categoria} · ` : ""}${url.startsWith("/") ? "Abre o texto" : "Abre no Drive"}` }),
    ]);
    return chip;
  }
  // Rodapé da resposta com os documentos que ela cita: o aviso de que não passaram pela revisão do time.
  function rodapeDocumentos(texto, docs, notas) {
    const citados = (docs || []).filter((d) => texto.includes(`[DOC-${d.id}]`) && linkSeguro(d.url));
    if (!citados.length) return null;
    return el("div", { class: "docs-citados" },
      el("p", { class: "nota-msg", text: "Documentos ainda não revisados pelo time:" }),
      el("ul", {}, citados.map((d) => el("li", {},
        notas && notas.has(`DOC-${d.id}`) ? nota(notas.get(`DOC-${d.id}`), true) : null,
        notas && notas.has(`DOC-${d.id}`) ? " " : null,
        el("a", { href: linkSeguro(d.url), target: "_blank", rel: "noopener noreferrer", text: d.titulo }),
        d.categoria ? el("span", { class: "pasta-doc", text: ` · ${d.categoria}` }) : null))));
  }

  // Uma fala no painel. A da pessoa é um balão; a do Cérebro (ou o erro) leva o mascote, o texto com as notas numeradas
  // e, abaixo, o que a acompanha. A última resposta com notas fica guardada: o mapa (PR 3) a usa.
  function adicionarMsg(caixa, { papel, texto, quem, nota: avisoFinal, extra, docs, registrar = false, lacunaId = null, lacunaPergunta = null, sobre = null }) {
    const vazia = caixa.querySelector(".conversa-vazia");
    if (vazia) vazia.remove();
    let linha;
    if (papel === "eu") {
      linha = el("div", { class: "fala-eu" }, sobre ? el("p", { class: "sobre-fala t-legenda", text: `Sobre ${sobre}` }) : null, formatar(texto, docs, null));
    } else {
      const notas = new Map();
      linha = el("div", { class: `fala-ele${papel === "erro" ? " erro" : ""}` },
        el("div", { class: "quem" },
          papel === "erro" ? mascoteEm("m mascote-erro", { humor: "sem-resposta" }) : mascoteEm("p", { forma: "simbolo" }),
          el("span", { class: "t-rotulo", text: quem })),
        el("div", { class: "resposta" }, formatar(texto, docs, notas)));
      if (extra) linha.append(extra);
      const citados = rodapeDocumentos(texto, docs, notas);
      if (citados) linha.append(citados);
      if (avisoFinal) linha.append(el("p", { class: "nota-msg", text: avisoFinal }));
      if (papel === "cerebro" && lacunaId) {  // a base não soube responder: a pergunta foi guardada como lacuna
        linha.append(el("div", { class: "lacuna-selo" },
          el("span", { class: "t-rotulo", text: "Lacuna guardada" }),
          el("span", { text: "Guardei como lacuna: a base não cobre isso." }),
          el("button", { type: "button", class: "btn fantasma", onclick: () => registrarDoChat({ lacunaId, lacunaPergunta }) }, "Registrar o que você sabe")));
      }
      if (papel === "cerebro" && registrar) {
        linha.append(el("button", { type: "button", class: "btn fantasma registrar-isso", onclick: () => registrarDoChat({ lacunaId, lacunaPergunta }) },
          icone("registrar", "ic p"), "Registrar isso"));
      }
      if (papel === "cerebro" && notas.size) estado.ultimaResposta = { notas: [...notas.keys()], docs: docs || [] };
    }
    caixa.append(linha);
    caixa.scrollTop = caixa.scrollHeight;
    return linha;
  }
  function digitando(caixa, aoParar) {
    const linha = el("div", { class: "fala-ele pensando-linha", role: "status" },
      mascoteEm("m", { humor: "pensando" }), el("span", { class: "t-rotulo", text: "Lendo a base" }),
      aoParar ? el("button", { type: "button", class: "btn fantasma", onclick: aoParar }, "Parar") : null);
    caixa.append(linha);
    caixa.scrollTop = caixa.scrollHeight;
    return linha;
  }

  // ---------------------------------------------------------------- a casca: rotas, abas e a barra lateral
  // A navegação é por hash, para o link funcionar ("#item/INS-12", "#base/proposta"). Os endereços antigos
  // (#conversar, #playbook, #briefing) continuam abrindo a tela certa. As abas abertas ficam no localStorage, que pode
  // falhar: sem ele, a tela abre só com o Hoje.
  const TELAS = ["hoje", "cerebro", "item", "base", "fila", "registrar", "preparar", "fontes"];
  const APELIDOS = { conversar: "cerebro", playbook: "base", briefing: "preparar" };
  const NOME_TELA = { fila: "Fila", registrar: "Rascunho", preparar: "Preparar reunião", fontes: "Fontes" };
  const MAX_ABAS = 8;

  function lerRota() {
    if (!location.hash && CELULAR.matches) return { tela: "cerebro", arg: null, hash: "#cerebro" };  // no celular, começa no chat
    let decodificado;
    try {
      decodificado = decodeURIComponent((location.hash || "").slice(1));
    } catch {
      return { tela: "hoje", arg: null, hash: "#hoje" };  // um link com "%" quebrado não derruba a navegação
    }
    const [bruta, ...resto] = decodificado.split("/");
    const tela = APELIDOS[bruta] || bruta;
    if (!TELAS.includes(tela)) return { tela: "hoje", arg: null, hash: "#hoje" };
    const arg = resto.join("/") || null;
    return { tela, arg, hash: `#${tela}${arg ? `/${arg}` : ""}` };
  }
  function rotear() {
    const rota = lerRota();
    esconderPrevia();  // a prévia de uma nota não fica presa quando a tela muda e a nota some
    fecharNavCelular();
    if (rota.tela !== "cerebro") fecharGavetaCerebro();  // abrir um item pela gaveta mostra o item, não a gaveta
    document.body.classList.toggle("ver-centro", rota.tela !== "cerebro");  // no celular, uma coluna por vez
    if (rota.tela === "cerebro") {  // o Cérebro é o painel da direita: a tela do centro continua a que estava
      if (!estado.telaHash) mostrarTela(lerRotaPadrao());
      mostrarCerebro();
      return;
    }
    mostrarTela(rota);
  }
  // As larguras da casca: até 860 px é o celular (uma coluna); até 1279 px o Cérebro vira gaveta.
  const CELULAR = matchMedia("(max-width: 860px)");
  const ESTREITO = matchMedia("(max-width: 1279px)");
  const ehGaveta = () => ESTREITO.matches && !CELULAR.matches;
  function lerRotaPadrao() { return { tela: "hoje", arg: null, hash: "#hoje" }; }
  function mostrarTela(rota) {
    estado.tela = rota.tela;
    estado.telaHash = rota.hash;
    document.body.classList.toggle("fila-aberta", rota.tela === "fila");
    abrirAba(rota.hash);
    for (const s of $$(".tela")) s.hidden = s.dataset.tela !== rota.tela;
    pintarAbas();
    marcarAtivos();
    atualizarSobre();
    if (rota.tela === "hoje") seguro(pintarHoje, "hoje");
    if (rota.tela === "item") pintarItem(rota.arg);
    if (rota.tela === "base") abrirBase(rota.arg);
    if (rota.tela === "fila") pintarFila();
    if (rota.tela === "registrar") {
      if (estado.reg.enviado) estado.reg = novoReg();  // depois de enviado, voltar à tela começa um relato novo
      pintarRegistrar();
    }
    if (rota.tela === "fontes") pintarFontes();
    if (rota.tela === "preparar") montarBriefing();
    const tela = $(`.tela[data-tela="${rota.tela}"]`);
    if (tela) tela.scrollTop = 0;
  }
  // O painel do Cérebro: fixo no desktop, gaveta de 861 a 1279 px e tela cheia no celular.
  // Na Fila, de 1280 px em diante, o painel vira um trilho de 64 px (a lista e o detalhe ganham a largura); o trilho abre o
  // Cérebro por cima, do mesmo jeito que a gaveta de 861 a 1279 px. Ao sair da Fila, o painel volta como estava.
  const trilhoDaFila = () => document.body.classList.contains("fila-aberta") && !ESTREITO.matches;
  function mostrarCerebro() {
    if (ehGaveta() || trilhoDaFila()) abrirGavetaCerebro();
    else if (!CELULAR.matches) $("#campo-chat").focus();
  }
  function abrirGavetaCerebro() {
    if (document.body.classList.contains("cerebro-aberto")) { $("#campo-chat").focus(); return; }
    estado.focoAntes = document.activeElement;
    document.body.classList.add("cerebro-aberto");
    $("#fundo-cerebro").hidden = false;
    $("#abrir-cerebro").setAttribute("aria-expanded", "true");
    $("#campo-chat").focus();
  }
  function fecharGavetaCerebro() {
    if (!document.body.classList.contains("cerebro-aberto")) return false;
    document.body.classList.remove("cerebro-aberto");
    $("#fundo-cerebro").hidden = true;
    $("#abrir-cerebro").setAttribute("aria-expanded", "false");
    if (estado.focoAntes && document.contains(estado.focoAntes)) estado.focoAntes.focus();
    return true;
  }
  // Celular: o botão do mascote abre a coluna de navegação (Esc ou tocar fora fecha).
  function abrirNavCelular() {
    const nav = $("#nav-celular");
    nav.hidden = false;
    $("#nav-mascote").setAttribute("aria-expanded", "true");
    for (const a of $$("a.no", nav)) {
      if (a.getAttribute("href") === (document.body.classList.contains("ver-centro") ? estado.telaHash : "#cerebro")) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
    $("a.no", nav).focus();
  }
  function fecharNavCelular() {
    const nav = $("#nav-celular");
    if (nav.hidden) return false;
    nav.hidden = true;
    $("#nav-mascote").setAttribute("aria-expanded", "false");
    return true;
  }

  function rotuloDaAba(hash) {
    const [tela, arg] = hash.slice(1).split("/");
    if (tela === "item") {
      const it = acharItem(arg);
      return { codigo: arg, texto: it ? it.titulo : "fora da base" };
    }
    if (tela === "base") return { texto: arg ? `Base · ${NOME_SECAO[arg] || arg}` : "Base" };
    return { texto: NOME_TELA[tela] || tela };
  }
  function lerAbas() {
    try {
      const lidas = JSON.parse(guardar.ler("cerebro.abas") || "[]");
      estado.abas = Array.isArray(lidas) ? lidas.filter((h) => typeof h === "string" && h.startsWith("#")).slice(-MAX_ABAS) : [];
    } catch {
      estado.abas = [];  // o que estava guardado não é JSON: começa do zero
    }
  }
  function guardarAbas() { guardar.escrever("cerebro.abas", JSON.stringify(estado.abas)); }
  function abrirAba(hash) {
    if (hash === "#hoje" || estado.abas.includes(hash)) return;
    estado.abas.push(hash);
    if (estado.abas.length > MAX_ABAS) estado.abas.shift();  // a mais antiga sai
    guardarAbas();
  }
  function fecharAba(hash) {
    const i = estado.abas.indexOf(hash);
    if (i < 0) return;
    estado.abas.splice(i, 1);
    guardarAbas();
    if (estado.telaHash === hash) location.hash = estado.abas[Math.min(i, estado.abas.length - 1)] || "#hoje";
    else pintarAbas();
  }
  function pintarAbas() {
    const aba = (hash, fixa) => {
      const r = fixa ? { texto: "Hoje" } : rotuloDaAba(hash);
      const ativa = hash === estado.telaHash;
      return el("div", { class: `aba${fixa ? " fixa" : ""}${ativa ? " ativa" : ""}` },
        el("a", { href: hash, "aria-current": ativa ? "page" : null, title: r.codigo ? `${r.codigo} · ${r.texto}` : r.texto },
          r.codigo ? el("span", { class: "t-dado", text: r.codigo }) : null, el("span", { class: "txt", text: r.texto })),
        fixa ? null : el("button", { type: "button", class: "x", "aria-label": `Fechar a aba ${r.codigo || r.texto}`,
          onclick: () => fecharAba(hash) }, icone("x", "ic p")));
    };
    $("#abas").replaceChildren(aba("#hoje", true), ...estado.abas.map((h) => aba(h, false)));
  }
  function marcarAtivos() {
    for (const a of $$("#barra a.no")) {
      if (a.getAttribute("href") === estado.telaHash) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
  }

  // Na Fila: o que as pessoas registraram (proposto) e o que veio de fontes antigas, ainda sem revisão (histórico a validar)
  function estaNaFila(i) { return i.status === "proposto" || i.status === "historico_a_validar"; }
  function itensDaBase() { return estado.itens.filter((i) => i.status === "validado" || i.status === "consolidado"); }
  // Os mais fortes primeiro: evidência, depois consolidado, depois o mais novo.
  function maisFortes(itens) {
    return [...itens].sort((a, b) => (b.evidencia - a.evidencia)
      || (Number(b.status === "consolidado") - Number(a.status === "consolidado")) || (b.id - a.id));
  }
  function atualizarNumeros() {
    const naFila = estado.itens.filter(estaNaFila).length;
    for (const contador of [$("#contador-fila"), $("#contador-fila-celular")]) {
      contador.textContent = naFila;
      contador.hidden = naFila === 0;
    }
    seguro(pintarBarra, "árvore");
    if (estado.tela === "hoje") seguro(pintarHoje, "hoje");
  }
  function pintarModo() {
    const dev = Boolean(estado.pessoa && estado.pessoa.dev);
    for (const m of [$("#modo"), $("#modo-celular")]) {  // o selo da barra e o do topo do Cérebro no celular
      m.dataset.modo = estado.modo;
      m.className = `selo ${m.id === "modo-celular" ? "modo-celular " : ""}${aoVivo() ? (dev ? "" : "vivo") : "alerta"}`;
      m.replaceChildren(...(aoVivo() && !dev ? [el("span", { class: "ponto-vivo", "aria-hidden": "true" })] : []),
        aoVivo() ? (dev ? "Dev local" : "Ao vivo") : "Sem servidor");
    }
    document.body.classList.toggle("sem-servidor", !aoVivo());
    const anexar = $("#anexar");
    anexar.disabled = !aoVivo();
    anexar.title = aoVivo() ? "Anexar um arquivo (docx, pdf, xlsx, csv, txt ou md, até 10 MB)" : "Só com o servidor ligado";
    const faixa = $("#faixa-servidor");
    faixa.hidden = aoVivo();
    faixa.replaceChildren(...(aoVivo() ? [] : [
      el("span", { text: "Sem conexão com o servidor. Nada aparece nem vai para a base até ele responder." }),
      el("button", { type: "button", class: "btn", onclick: () => location.reload() }, "Tentar conectar")]));
  }

  // A árvore da base: as 7 etapas como pastas, com os 20 itens mais fortes dentro e o "ver todos" que abre a etapa.
  const POR_PASTA = 20;
  function pintarBarra() {
    const base = itensDaBase();
    const pastas = SECOES.map(([chave, nome]) => {
      const da = maisFortes(base.filter((i) => i.secao === chave));
      const pasta = el("details", { class: "pasta", open: estado.pastas.has(chave) || null },
        el("summary", { class: "no" }, el("span", { class: "dobra", "aria-hidden": "true" }),
          el("span", { class: "txt", text: nome }), el("span", { class: "cont", text: String(da.length) })),
        ...da.slice(0, POR_PASTA).map((it) => el("a", { class: "no filho", href: `#item/${it.codigo}`, title: it.titulo },
          pontoEv(it.evidencia), el("span", { class: "txt", text: it.titulo }))),
        el("a", { class: "no filho ver-todos", href: `#base/${chave}` },
          el("span", { class: "txt", text: da.length > POR_PASTA ? `Ver todos (${da.length})` : "Ver a etapa" })));
      pasta.addEventListener("toggle", () => { if (pasta.open) estado.pastas.add(chave); else estado.pastas.delete(chave); });
      return pasta;
    });
    if (!base.length) {
      pastas.push(el("p", { class: "t-legenda arvore-vazia", text: aoVivo() ? "A base ainda não tem itens aprovados." : "Sem conexão com o servidor." }));
    }
    $("#arvore").replaceChildren(...pastas);
    marcarAtivos();
  }

  // Os 7 nós da base por etapa (Hoje e, no PR 3, o mapa): a cor da borda é a evidência média, e o tracejado marca a
  // "pouca base" (nenhum item com evidência 3 ou mais). A cor nunca vai sozinha: o número e o "evid." vão junto.
  function nosEtapas(itens, { href } = {}) {
    return el("div", { class: "nos-etapas" }, SECOES.map(([chave, nome]) => {
      const da = itens.filter((i) => i.secao === chave);
      const media = da.length ? da.reduce((t, i) => t + i.evidencia, 0) / da.length : 0;
      const pouca = !da.some((i) => i.evidencia >= 3);
      const tom = Math.min(4, Math.max(1, Math.round(media)));
      const rotulo = da.length ? `evid. ${media.toFixed(1).replace(".", ",")}` : "sem itens";
      return el(href ? "a" : "div", {
        class: `no-etapa c${tom}`, href: href ? href(chave) : null, role: href ? null : "img",
        "aria-label": `${nome}: ${da.length} ${da.length === 1 ? "item" : "itens"}, ${rotulo}${pouca ? ", pouca base" : ""}`,
      },
      el("div", { class: `cx${pouca ? " pouca" : ""}`, "aria-hidden": "true" }, el("span", { class: "numero", text: String(da.length) })),
      el("b", { text: nome, "aria-hidden": "true" }),
      el("span", { class: "t-dado", text: rotulo, "aria-hidden": "true" }));
    }));
  }

  // ---------------------------------------------------------------- Hoje (a tela inicial no desktop)
  function metrica(icon, rotulo, n, legenda, tom, href) {
    return el("a", { class: "metrica", href },
      icone(icon, "ic g"),
      el("span", {}, el("span", { class: "t-rotulo", text: rotulo }),
        el("span", { class: `numero${tom ? ` ${tom}` : ""}`, text: String(n).padStart(2, "0") }),
        el("span", { class: "t-legenda", text: legenda })));
  }
  function atalhoGrande(href, icon, titulo, texto, extra = "") {
    return el("a", { class: `atalho-grande${extra ? ` ${extra}` : ""}`, href },
      el("span", { class: "bola" }, icone(icon)),
      el("span", { class: "txt" }, el("b", { text: titulo }), el("span", { text: texto })),
      icone("seta", "ic seta"));
  }
  function seloDaFila(it) {
    if ((it.relacoes || []).some((r) => r.tipo === "contradiz")) return el("span", { class: "selo risco", text: "Contradiz" });
    if (it.status === "historico_a_validar") return el("span", { class: "selo alerta", text: "Histórico a validar" });
    return el("span", { class: "selo", text: ORIGEM_ITEM[it.fonte] || it.fonte });
  }
  function painelFila(fila) {
    const sec = el("section", { class: "painel raso" }, el("div", { class: "cab-painel" },
      el("h2", { class: "t-secao", text: "Esperando você na Fila" }),
      fila.length ? el("a", { class: "btn primario", href: "#fila", text: "Triar agora" }) : null));
    if (!fila.length) {
      sec.append(el("p", { class: "t-p suave", text: "Fila em dia: nada esperando revisão." }));
      return sec;
    }
    for (const it of fila.slice(0, 3)) {
      sec.append(el("a", { class: "linha-lista", href: `#item/${it.codigo}` },
        pontoEv(it.evidencia), el("span", { class: "txt", text: it.titulo }), seloDaFila(it)));
    }
    const resto = fila.length - 3;
    if (resto > 0) sec.append(el("p", { class: "t-legenda", text: `e mais ${resto} ${resto === 1 ? "item" : "itens"}` }));
    return sec;
  }
  function cartaoSync(u) {
    const partes = [
      `${FONTE_DA_SYNC[u.origem] || u.origem}, ${dataHora(u.fim || u.inicio)}${u.fim ? "" : " (não terminou)"}`,
      `${u.paginas_novas} ${u.paginas_novas === 1 ? "página nova" : "páginas novas"}`,
      `${u.paginas_alteradas} ${u.paginas_alteradas === 1 ? "alterada" : "alteradas"}`,
    ];
    return el("div", { class: "cartao ultima-sync" }, el("span", { class: "ponto-vivo", "aria-hidden": "true" }),
      el("span", { class: "t-p" }, el("b", { class: "forte", text: "Última sincronização: " }), partes.join(" · ")),
      el("a", { class: "btn fantasma", href: "#fontes" }, "Fontes", icone("seta", "ic p")));
  }
  function pintarHoje() {
    if (!aoVivo()) {  // sem servidor não há base nem Fila para contar, e "base vazia" seria mentira
      const caixa = vazio("Sem conexão com o servidor", "Sem ele eu não tenho a base e não invento nada. Confira a internet e tente de novo.",
        el("button", { type: "button", class: "btn primario", onclick: () => location.reload() }, "Tentar conectar"));
      caixa.querySelector(".mascote").replaceWith(mascoteEm("m mascote-vazio", { humor: "sem-resposta" }));
      $("#hoje").replaceChildren(caixa);
      return;
    }
    if (estado.erroCarga) {
      $("#hoje").replaceChildren(vazio("Não consegui carregar a base", estado.erroCarga,
        el("button", { type: "button", class: "btn primario", onclick: async () => { await carregarItens(); pintarHoje(); } }, "Tentar de novo")));
      return;
    }
    const base = itensDaBase();
    const fila = estado.itens.filter(estaNaFila).sort((a, b) => b.id - a.id);
    const nome = estado.pessoa ? estado.pessoa.nome.split(/\s+/)[0] : "";
    const dia = new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" }).replace("-feira", "");
    const resumo = fila.length
      ? ` ${fila.length} ${fila.length === 1 ? "espera" : "esperam"} a leitura do time na Fila.`
      : " A Fila está em dia.";
    const filhos = [
      el("header", { class: "hoje-cab" },
        el("p", { class: "t-rotulo", text: `Cérebro Comercial · ${dia}` }),
        el("h1", { class: "t-display", text: nome ? `Olá, ${nome}` : "Olá" }),
        el("p", { class: "t-corpo" },
          el("b", { class: "forte", text: `${base.length} ${base.length === 1 ? "item aprovado" : "itens aprovados"} na base.` }), resumo)),
      el("div", { class: "metricas" },
        metrica("camadas", "Base", base.length, base.length === 1 ? "item aprovado" : "itens aprovados", "", "#base"),
        metrica("fila", "Fila", fila.length, "esperando aprovação", "marca", "#fila")),
      el("div", { class: "cab-tela" }, el("p", { class: "t-rotulo", text: "Começar por" }),
        el("div", { class: "comecar" },
          atalhoGrande("#preparar", "preparar", "Preparar reunião", "Um briefing com a prova de cada ponto"),
          atalhoGrande("#registrar", "registrar", "Registrar um relato", "O curador transforma em item", "sereno"))),
    ];
    if (base.length) {
      filhos.push(el("section", { class: "painel" },
        el("div", { class: "cab-tela" }, el("h2", { class: "t-titulo", text: "A base por etapa" }),
          el("p", { class: "t-p suave", text: "A cor da borda é a evidência média. Tracejado: pouca base, nenhum item com evidência 3 ou mais." })),
        nosEtapas(base, { href: (chave) => `#base/${chave}` })));
    } else {
      filhos.push(vazio("A base ainda está vazia",
        "Sem itens aprovados eu não monto roteiro: prefiro não inventar. Registre o primeiro relato ou aprove o que está na Fila.",
        el("div", { class: "botoes" },
          el("a", { class: "btn primario", href: "#registrar", text: "Registrar o primeiro" }),
          fila.length ? el("a", { class: "btn", href: "#fila", text: "Abrir a Fila" }) : null)));
      filhos[filhos.length - 1].querySelector(".mascote").replaceWith(mascoteEm("m mascote-vazio", { humor: "nota-em-branco" }));
    }
    filhos.push(el("div", { class: "duas-colunas" }, painelFila(fila)));
    const ultima = aoVivo() && estado.fontes && estado.fontes.ultima_execucao;
    if (ultima) filhos.push(cartaoSync(ultima));
    $("#hoje").replaceChildren(...filhos);
  }

  // ---------------------------------------------------------------- conversar
  const ATALHOS_CHAT = [
    "O que funciona numa reunião de diagnóstico?",
    "O cliente disse que está caro. Como respondemos?",
    "Como apresentar o Discovery?",
  ];
  async function perguntar(texto, { semFala = false } = {}) {
    texto = texto.trim();
    if (!texto || estado.ocupado) return;
    const caixa = $("#mensagens");
    const campo = $("#campo-chat");
    const compor = $("#form-chat");
    compor.classList.remove("com-erro");
    $("#aviso-chat").hidden = true;
    const sobre = codigoSobre();
    const enviado = sobre ? comPrefixoDoItem(sobre, texto) : texto;
    const falaEu = semFala ? null : adicionarMsg(caixa, { papel: "eu", texto, quem: nomeDoUsuario(), sobre });
    campo.value = ""; autoAltura(campo); atualizarContadorMsg();
    estado.ocupado = true; $("#enviar-chat").disabled = true;
    const parar = new AbortController();
    const indicador = digitando(caixa, () => parar.abort());
    try {
      const r = await chamar("POST", "/chat", { mensagem: enviado, historico: historicoParaApi() }, parar.signal);
      const resposta = r.resposta;
      const docs = r.documentos || [];
      const lacunaId = r.lacuna_id || null;
      indicador.remove();
      adicionarMsg(caixa, { papel: "cerebro", texto: resposta, quem: "Cérebro", docs,
        registrar: true, lacunaId, lacunaPergunta: texto });
      estado.conversa.push({ role: "user", text: enviado, mostrar: texto, sobre }, { role: "model", text: resposta, docs, lacunaId });
      salvarConversa();
      pulsarMascote();
    } catch (e) {
      indicador.remove();
      if (!campo.value.trim()) { campo.value = texto; autoAltura(campo); atualizarContadorMsg(); }  // a pergunta volta ao campo, para tentar de novo
      if (e.status === -1) {  // parou de esperar: nada foi respondido
        if (falaEu) falaEu.remove();
      } else if (e.status === 422) {  // dado pessoal (ou texto inválido): nada foi ao modelo, e a mensagem não repete o dado
        if (falaEu) falaEu.remove();
        const aviso422 = $("#aviso-chat");  // a frase fica junto ao campo até a pessoa mexer no texto (a torrada some em 5 s)
        aviso422.textContent = /dado pessoal/i.test(e.message)
          ? "Essa mensagem tem um dado pessoal (e-mail, CPF, CNPJ ou telefone) e não foi enviada ao modelo. Tire o dado e envie de novo."
          : e.message;
        aviso422.hidden = false;
        compor.classList.add("com-erro");
        campo.addEventListener("input", () => { compor.classList.remove("com-erro"); aviso422.hidden = true; }, { once: true });
      } else {
        let linhaErro = null;
        const extra = e.status === 502
          ? el("div", { class: "botoes" }, el("button", { type: "button", class: "btn", onclick: () => {
            linhaErro.remove();
            if (campo.value.trim() === texto) { campo.value = ""; autoAltura(campo); atualizarContadorMsg(); }
            perguntar(texto, { semFala: true });
          } }, "Tentar de novo"))
          : null;
        linhaErro = adicionarMsg(caixa, { papel: "erro", texto: e.message, extra,
          quem: e.status === 502 ? "Não consegui responder agora" : "Não deu certo" });
      }
    } finally {
      estado.ocupado = false; $("#enviar-chat").disabled = false;
      campo.focus();
    }
  }
  function pintarAtalhosChat() {
    return el("div", { class: "atalhos" }, ATALHOS_CHAT.map((texto) =>
      el("button", { type: "button", class: "atalho", onclick: () => perguntar(texto) }, icone("brilho", "ic p"), el("span", { text: texto }))));
  }
  function conversaVazia() {
    return el("div", { class: "conversa-vazia" }, mascoteEm(""),
      el("div", {}, el("h3", { class: "t-titulo", text: "Pergunte ao Cérebro" }),
        el("p", { class: "t-p", text: "Ele responde com o que o time já aprovou e mostra de onde veio cada parte." })),
      pintarAtalhosChat());
  }
  // O histórico do chat fica só neste navegador (localStorage), por pessoa: não vai para o servidor, e a tela funciona
  // sem ele. Guarda as últimas 30 falas, com os documentos e a lacuna de cada resposta, para reconstruir a conversa.
  const chaveConversa = () => `cerebro.conversa:${estado.pessoa ? estado.pessoa.email : "dev"}`;
  function salvarConversa() {
    if (estado.conversa.length > 30) estado.conversa = estado.conversa.slice(-30);
    guardar.escrever(chaveConversa(), JSON.stringify(estado.conversa.slice(-30)));
  }
  function lerConversaSalva() {
    try {
      const lida = JSON.parse(guardar.ler(chaveConversa()) || "[]");
      return Array.isArray(lida)
        ? lida.filter((m) => m && (m.role === "user" || m.role === "model") && typeof m.text === "string").slice(-30) : [];
    } catch {
      return [];  // o que estava guardado não é JSON: começa uma conversa nova
    }
  }
  // Ao servidor vai só o papel e o texto (os documentos e a lacuna são da tela).
  const historicoParaApi = () => estado.conversa.slice(-30).map(({ role, text }) => ({ role, text }));

  // "Sobre INS-12": com um item aberto no centro, a pergunta leva o item como contexto. Não há rota para isso: o código
  // escreve "Sobre o item INS-12 (título):" antes do texto, e o chip sai com o ×.
  function codigoSobre() { return estado.sobreItem && !estado.sobreTirado ? estado.sobreItem : null; }
  function comPrefixoDoItem(codigo, texto) {
    const item = acharItem(codigo);
    return `Sobre o item ${codigo}${item ? ` (${item.titulo.slice(0, 120)})` : ""}: ${texto}`.slice(0, 4000);  // o limite do servidor
  }
  function atualizarSobre() {
    const [tela, arg] = (estado.telaHash || "").slice(1).split("/");
    const codigo = tela === "item" && arg && acharItem(arg) ? arg : null;
    if (codigo !== estado.sobreItem) { estado.sobreItem = codigo; estado.sobreTirado = false; }
    const ativo = codigoSobre();
    const chip = $("#sobre-chip");
    chip.hidden = !ativo;
    chip.replaceChildren(...(ativo ? [
      el("span", { text: `Sobre ${ativo}` }),
      el("button", { type: "button", "aria-label": "Tirar o item da pergunta", onclick: () => { estado.sobreTirado = true; atualizarSobre(); } }, icone("x", "ic p")),
    ] : []));
  }
  // O contador só aparece perto do limite de 4.000 caracteres.
  function atualizarContadorMsg() {
    const n = $("#campo-chat").value.length;
    const c = $("#contador-msg");
    c.hidden = n < 3800;
    c.classList.toggle("perto", n >= 3950);
    c.textContent = `${n.toLocaleString("pt-BR")} / 4.000`;
  }

  function iniciarConversa({ restaurar = false } = {}) {
    const caixa = $("#mensagens");
    caixa.replaceChildren(conversaVazia());
    estado.conversa = [];
    estado.ultimaResposta = null;
    const salvas = restaurar ? lerConversaSalva() : [];
    if (!restaurar) guardar.escrever(chaveConversa(), "[]");  // "Nova conversa" esquece a anterior
    if (salvas.length) {  // reconstrói a conversa guardada
      estado.conversa = salvas;
      salvas.forEach((m, i) => {
        if (m.role === "user") {
          adicionarMsg(caixa, { papel: "eu", quem: nomeDoUsuario(), texto: m.mostrar || m.text, sobre: m.sobre || null });
        } else {
          const antes = salvas[i - 1];
          adicionarMsg(caixa, { papel: "cerebro", quem: "Cérebro", texto: m.text, docs: m.docs || [], registrar: true,
            lacunaId: m.lacunaId || null, lacunaPergunta: antes ? (antes.mostrar || antes.text) : null });
        }
      });
    }
  }

  // ---------------------------------------------------------------- anexar arquivo no chat
  // O clipe manda o arquivo (docx, pdf, xlsx, csv, txt ou md, até 10 MB) para POST /fontes/anexo. O texto fica na busca do
  // consultor (como [DOC-n], "ainda não revisado") e o curador propõe itens para a Fila em segundo plano: a tela
  // acompanha por GET /fontes/{id}. Dado pessoal barra tudo, e a tela nunca o repete.
  const EXTENSOES_ANEXO = [".docx", ".pdf", ".xlsx", ".csv", ".txt", ".md"];
  const MAX_ANEXO = 10 * 1024 * 1024;
  const quantosItens = (fonte) => Object.values(fonte.itens || {}).reduce((t, n) => t + n, 0);

  // O nome do arquivo pode ter dado pessoal (o servidor já omite esse título): a tela não o repete.
  const RE_PESSOAL = [
    ["e-mail", /[\w.+-]+@[\w-]+\.[\w.-]+/],
    ["telefone", /\(?\b\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b/],
    ["CPF ou CNPJ", /\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\b\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2}\b/],
  ];
  function nomeDoAnexo(nome) {
    return RE_PESSOAL.some(([, re]) => re.test(nome)) ? "arquivo com dado pessoal no nome" : nome;
  }

  // A linha do anexo no chat: o nome, o que está acontecendo e, se couber, uma ação.
  function linhaDoAnexo(nome) {
    const estadoTxt = el("p", { class: "anexo-estado t-p", role: "status", text: "Enviando…" });
    const acoes = el("div", { class: "botoes" });
    const nomeTxt = el("b", { text: nome });
    const linha = el("div", { class: "fala-ele anexo" },
      el("div", { class: "quem" }, icone("doc", "ic p"), el("span", { class: "t-rotulo", text: "Anexo" })),
      el("p", { class: "anexo-nome t-p" }, nomeTxt), estadoTxt, acoes);
    $("#mensagens").append(linha);
    $("#mensagens").scrollTop = $("#mensagens").scrollHeight;
    return {
      linha,
      nomear(titulo) { nomeTxt.textContent = titulo; },  // depois da resposta, vale o título que o servidor guardou
      dizer(texto, { tom = "", nota = null, botoes = [] } = {}) {
        estadoTxt.textContent = texto;
        estadoTxt.className = `anexo-estado t-p${tom ? ` ${tom}` : ""}`;
        acoes.replaceChildren(...botoes);
        const velha = $(".nota-msg", linha);
        if (velha) velha.remove();
        if (nota) linha.append(el("p", { class: "nota-msg", text: nota }));
        $("#mensagens").scrollTop = $("#mensagens").scrollHeight;
      },
    };
  }
  async function acompanharAnexo(id, painel) {
    for (let tentativa = 0; tentativa < 90; tentativa++) {  // até uns 3 minutos
      let fonte;
      try { fonte = await chamar("GET", `/fontes/${id}`); } catch { fonte = null; }
      if (fonte && fonte.status === "importada") {
        await carregarItens();
        const n = quantosItens(fonte);
        painel.dizer(n ? `Virou ${n} ${n === 1 ? "item" : "itens"} na Fila.` : "O curador leu o arquivo e não propôs itens.", {
          tom: "ok", botoes: n ? [el("a", { class: "btn", href: "#fila" }, "Ver na Fila")] : [] });
        return;
      }
      if (fonte && fonte.status === "falha") {
        painel.dizer("O curador falhou neste arquivo.", { tom: "risco", botoes: [
          el("button", { type: "button", class: "btn", onclick: () => tentarAnexoDeNovo(id, painel) }, "Tentar de novo")] });
        return;
      }
      await esperar(2000);
    }
    painel.dizer("O curador está demorando. O arquivo já está na busca; confira a Fila daqui a pouco.", { tom: "alerta" });
  }
  async function tentarAnexoDeNovo(id, painel) {
    painel.dizer("Lendo e propondo itens…");
    try {
      await chamar("POST", `/fontes/${id}/curar`);
      acompanharAnexo(id, painel);
    } catch (e) {
      painel.dizer(e.message, { tom: "risco" });
    }
  }
  async function enviarArquivo(arquivo) {
    if (!aoVivo() || !arquivo) return;
    const painel = linhaDoAnexo(nomeDoAnexo(arquivo.name));
    const ext = `.${arquivo.name.split(".").pop().toLowerCase()}`;
    if (!EXTENSOES_ANEXO.includes(ext)) { painel.dizer(`Formato não suportado. Anexe ${EXTENSOES_ANEXO.join(", ")}.`, { tom: "risco" }); return; }
    if (arquivo.size > MAX_ANEXO) { painel.dizer("O arquivo passa de 10 MB.", { tom: "risco" }); return; }
    const corpo = new FormData();
    corpo.append("arquivo", arquivo);
    try {
      const r = await chamar("POST", "/fontes/anexo", corpo);
      const f = r.fonte;
      if (f.titulo) painel.nomear(f.titulo);
      const nota = r.ja_existia ? "Este arquivo já tinha sido anexado." : (r.aviso || null);
      if (f.status === "pulada_dado_pessoal") {  // o tipo, nunca o dado
        painel.dizer("Tem dado pessoal: não entra. Nada dele foi lido pelo modelo.", { tom: "risco", nota: "Troque o dado por algo genérico no arquivo e anexe de novo." });
      } else if (f.status === "vazia") {
        painel.dizer("Não achei texto para ler. Nada foi guardado.", { tom: "alerta" });
      } else if (f.status === "so_busca") {
        painel.dizer("O chat já acha trechos dele, mas ele não vira item.", { tom: "alerta", nota });
      } else if (f.status === "importada") {
        const n = quantosItens(f);
        painel.dizer(n ? `Virou ${n} ${n === 1 ? "item" : "itens"} na Fila.` : "Já foi lido antes, sem itens novos.", {
          tom: "ok", nota, botoes: n ? [el("a", { class: "btn", href: "#fila" }, "Ver na Fila")] : [] });
      } else if (r.curando) {
        painel.dizer("Lendo e propondo itens…", { nota });
        acompanharAnexo(f.id, painel);
      } else {  // a_curar sem curador rodando (o servidor reiniciou, por exemplo) ou falha: dá para pedir de novo
        painel.dizer("Guardado, esperando o curador.", { tom: "alerta", nota, botoes: [
          el("button", { type: "button", class: "btn", onclick: () => tentarAnexoDeNovo(f.id, painel) }, "Pedir ao curador")] });
      }
      await carregarItens();
    } catch (e) {
      painel.dizer(e.status === 413 ? "O arquivo passa de 10 MB." : e.message, { tom: "risco" });
    }
  }

  // ---------------------------------------------------------------- registrar (o rascunho do curador, prancha 3)
  // Três caminhos levam à mesma tela: "Registrar isso" no chat (POST /chat/registrar), "Registrar o que você sabe" de
  // uma lacuna (o mesmo, com o lacuna_id) e "Registrar um relato" (POST /registrar/propor). Nenhum grava nada: quem grava
  // é o POST /insights, depois que a pessoa revisa o formulário. O item sempre nasce proposto.
  const ORIGENS_REG = { relato: "Veio de um relato", chat: "Veio da conversa", lacuna: "Veio de uma lacuna" };
  const FRASE_EVID = { 1: "sem caso que sustente", 2: "um único caso", 3: "vários casos", 4: "exige um número" };
  // O campo do servidor (nos avisos de dado pessoal) -> o campo do formulário.
  const CAMPO_PARA_ID = {
    titulo: "r-titulo", descricao: "r-descricao", o_que_foi_feito: "r-feito", resultado: "r-resultado",
    contexto_cliente: "r-contexto", segmento: "r-segmento", servico: "r-servico",
  };
  function novoReg() {
    return { conversa: [], proposta: null, ocupado: false, origem: "relato", lacunaId: null, lacunaPergunta: null,
      evidencia: 1, sugerida: null, perguntas: [], erro: null, enviado: null };
  }
  function propostaVazia() {
    return { insight: { titulo: "", tipo: "aprendizado", secao: "reuniao_diagnostico", segmento: null, evidencia: 1, descricao: "",
      o_que_foi_feito: null, resultado: null, contexto_cliente: null, data_evento: null, servico: null }, relacoes: [], perguntas: [], avisos: [] };
  }
  function novoRegistro() {
    estado.reg = novoReg();
    if (estado.tela === "registrar") pintarRegistrar();
  }
  // O relato que o servidor monta sozinho quando a pessoa não escreve um texto: as últimas falas dela no chat.
  const relatoDaConversa = () => estado.conversa.filter((m) => m.role === "user").map((m) => m.text.trim()).filter(Boolean)
    .slice(-3).join("\n\n").slice(0, 8000);
  function aplicarProposta(proposta, relato) {
    const r = estado.reg;
    proposta.relacoes = proposta.relacoes || [];
    r.proposta = proposta;
    r.evidencia = Number(proposta.insight.evidencia) || 1;
    r.sugerida = r.evidencia;
    r.perguntas = proposta.perguntas || [];
    r.conversa.push({ role: "user", text: relato }, { role: "model", text: r.perguntas.length ? r.perguntas.join("\n") : "Rascunho pronto para revisar." });
    r.erro = null;
  }
  // O curador não respondeu (502 ou sem conexão): o formulário em branco continua, para preencher à mão. Dado pessoal
  // no relato (422): sem rascunho, a pessoa tira o dado e tenta de novo; a mensagem do servidor não repete o dado.
  function tratarErroCurador(e) {
    const r = estado.reg;
    if (e.status === 502 || e.status === 0) {
      r.erro = { msg: `${e.message} O formulário está em branco: preencha à mão.` };
      if (!r.proposta) r.proposta = propostaVazia();
    } else {
      r.erro = { msg: e.message };
    }
  }
  async function registrarDoChat({ texto = null, lacunaId = null, lacunaPergunta = null } = {}) {
    if (estado.reg.ocupado) return;
    estado.reg = novoReg();
    const r = estado.reg;
    Object.assign(r, { origem: lacunaId ? "lacuna" : "chat", lacunaId, lacunaPergunta, ocupado: true });
    if (location.hash === "#registrar") pintarRegistrar(); else location.hash = "#registrar";
    const relato = (texto || relatoDaConversa()).slice(0, 8000);
    try {
      const corpo = { historico: historicoParaApi() };
      if (texto) corpo.texto = texto;
      if (lacunaId) corpo.lacuna_id = lacunaId;
      const proposta = await chamar("POST", "/chat/registrar", corpo);
      aplicarProposta(proposta, relato);
      pulsarMascote();
    } catch (e) {
      tratarErroCurador(e);
    } finally {
      r.ocupado = false;
      if (estado.reg === r) pintarRegistrar();
    }
  }
  async function relatar(texto) {
    texto = texto.trim();
    const r = estado.reg;
    if (!texto || r.ocupado) return;
    r.ocupado = true; r.erro = null;
    pintarRegistrar();
    try {
      const proposta = await chamar("POST", "/registrar/propor", { texto, conversa: r.conversa.slice(-10) });
      aplicarProposta(proposta, texto);
      pulsarMascote();
    } catch (e) {
      tratarErroCurador(e);
    } finally {
      r.ocupado = false;
      if (estado.reg === r) pintarRegistrar();
    }
  }

  function campo(rotulo, id, controle, inteiro = false) {
    controle.id = id;
    return el("div", { class: `campo${inteiro ? " inteiro" : ""}` }, el("label", { for: id, text: rotulo }), controle);
  }
  function selecionar(opcoes, valor) {
    const s = el("select");
    for (const [v, t] of opcoes) s.append(el("option", { value: v, text: t }));
    s.value = valor;
    return s;
  }

  // O erro no campo, na hora: a mensagem fica embaixo do campo, ligada a ele por aria-describedby.
  function marcarErroCampo(id, msg, comEscudo = false) {
    const ctl = $(`#${id}`);
    if (!ctl) return;
    const caixa = ctl.closest(".campo");
    caixa.classList.add("erro");
    let ajuda = $(`#${id}-ajuda`, caixa);
    if (!ajuda) { ajuda = el("p", { class: "ajuda", id: `${id}-ajuda` }); caixa.append(ajuda); }
    ajuda.replaceChildren(...(comEscudo ? [icone("escudo", "ic p")] : []), msg);
    ctl.setAttribute("aria-invalid", "true");
    ctl.setAttribute("aria-describedby", ajuda.id);
    ctl.addEventListener(ctl.matches("div") ? "click" : "input", () => limparErroCampo(id), { once: true });
  }
  function limparErroCampo(id) {
    const ctl = $(`#${id}`);
    if (!ctl) return;
    const caixa = ctl.closest(".campo");
    caixa.classList.remove("erro");
    const ajuda = $(`#${id}-ajuda`, caixa);
    if (ajuda) ajuda.remove();
    ctl.removeAttribute("aria-invalid");
    ctl.removeAttribute("aria-describedby");
  }
  function focarPrimeiroErro() {
    const ctl = $("#rascunho [aria-invalid='true']");
    if (!ctl) return;
    (ctl.matches("div") ? $("button", ctl) : ctl).focus();
  }
  // O que a pessoa precisa corrigir antes de enviar (as regras do servidor, avisadas antes do envio).
  function validarRascunho(d) {
    const erros = {};
    if (!d.titulo) erros["r-titulo"] = "Escreva um título.";
    if (!d.descricao) erros["r-descricao"] = "Escreva a descrição.";
    if (d.tipo === "regra" && d.evidencia < 3) erros["r-evid-grupo"] = "Para virar regra, a evidência precisa ser 3 ou 4.";
    if (d.evidencia === 4 && !/\d/.test(d.resultado || "")) erros["r-resultado"] = "Evidência 4 exige um número no campo Resultado.";
    return erros;
  }
  // "Encontrei possível dado pessoal: e-mail em 'contexto_cliente'; telefone em 'resultado'. Por LGPD..." -> o tipo e o
  // campo de cada achado. O dado em si nunca vem na mensagem, e a tela nunca o repete.
  function camposComDadoPessoal(msg) {
    const trecho = (/dado pessoal:\s*(.+?)\.\s*Por LGPD/s.exec(msg) || [])[1];
    if (!trecho) return [];
    return trecho.split(";").map((x) => /^\s*(.+?)\s+em\s+'([^']+)'/.exec(x)).filter(Boolean).map((m) => [m[1], m[2]]);
  }
  function mostrarAvisoRegistro(erro) {
    const caixa = $("#registrar-aviso");
    caixa.hidden = !erro;
    caixa.replaceChildren(...(erro ? [icone("escudo", "ic p"), el("span", { class: "t-p", text: erro.msg }),
      erro.fila ? el("a", { class: "btn", href: "#fila", text: "Abrir a Fila" }) : null].filter(Boolean) : []));
  }

  function chipLigacao(rel, aoTirar) {
    const alvo = itemPorId(rel.relacionado_id);
    const codigo = alvo ? alvo.codigo : `INS-${rel.relacionado_id}`;
    return el("span", { class: "rel", "data-tipo": rel.tipo },
      icone("ligacao", "ic p"), el("b", { text: RELACOES[rel.tipo] || rel.tipo }), el("span", { class: "t-dado", text: codigo }),
      alvo ? el("span", { class: "txt-ligacao", text: alvo.titulo }) : null,
      el("button", { type: "button", "aria-label": `Tirar a ligação com ${codigo}`, onclick: aoTirar }, icone("x", "ic p")));
  }
  function cartaoPerguntas() {
    const r = estado.reg;
    const entrada = el("input", { id: "resposta-curador", placeholder: "Responda, ou deixe em branco", autocomplete: "off", maxlength: "4000" });
    const responder = () => {
      const t = entrada.value.trim();
      if (t) relatar(t); else { r.perguntas = []; pintarRegistrar(); }
    };
    entrada.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); responder(); } });
    return el("div", { class: "cartao pergunta-curador", role: "group", "aria-label": "Pergunta do curador" },
      el("span", { class: "bola" }, icone("brilho", "ic p")),
      el("div", { class: "pergunta-corpo" },
        el("p", { class: "t-rotulo", text: "O curador perguntou" }),
        r.perguntas.length === 1
          ? el("p", { class: "t-corpo forte", text: r.perguntas[0] })
          : el("ol", { class: "lista-perguntas" }, r.perguntas.map((p) => el("li", { text: p }))),
        el("div", { class: "linha-resposta" },
          el("label", { class: "sr", for: "resposta-curador", text: "Resposta ao curador" }), entrada,
          el("button", { type: "button", class: "btn", onclick: responder }, "Responder"))));
  }
  function painelRelato() {
    const area = el("textarea", { id: "campo-reg", rows: "5", maxlength: "8000", placeholder: "Conte o que aconteceu, do jeito que contaria para um colega…" });
    const form = el("form", { class: "painel relato", novalidate: true },
      el("div", { class: "campo" }, el("label", { for: "campo-reg", text: "O que aconteceu" }), area),
      el("p", { class: "t-legenda", text: "O curador organiza em um item, aponta o que faltou e você revisa antes de ir para a Fila. Sem dado pessoal de cliente." }),
      el("div", { class: "botoes" }, el("button", { type: "submit", class: "btn primario" }, "Enviar ao curador")));
    form.addEventListener("submit", (e) => { e.preventDefault(); relatar(area.value); });
    area.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); form.requestSubmit(); } });
    return form;
  }
  function formularioRascunho() {
    const r = estado.reg;
    const it = r.proposta.insight;
    const v = (x) => (x == null ? "" : x);
    const area = (x, linhas, limite, dica) => {
      const a = el("textarea", { rows: String(linhas), maxlength: String(limite), placeholder: dica || null });
      a.value = v(x);
      return a;
    };
    const opcoes = [1, 2, 3, 4].map((n) => {
      const t = trilha(n, true);
      t.removeAttribute("role"); t.removeAttribute("aria-label"); t.setAttribute("aria-hidden", "true");
      return el("button", { type: "button", class: "cartao evidencia-op", role: "radio", "aria-checked": String(r.evidencia === n),
        onclick: () => {
          r.evidencia = n;
          opcoes.forEach((b, i) => b.setAttribute("aria-checked", String(i === n - 1)));
          limparErroCampo("r-evid-grupo");
        } }, t, el("b", { text: EVIDENCIA[n] }), el("span", { class: "t-legenda", text: FRASE_EVID[n] }));
    });
    const grupo = el("div", { class: "evidencias", id: "r-evid-grupo", role: "radiogroup", "aria-labelledby": "rotulo-evid" }, ...opcoes);

    const relacoes = el("div", { class: "relacoes" });
    const pintarRelacoes = () => {
      relacoes.replaceChildren();
      if (!r.proposta.relacoes.length) relacoes.append(el("span", { class: "t-p suave", text: "Nenhuma ligação com itens que já existem." }));
      r.proposta.relacoes.forEach((rel, i) => relacoes.append(chipLigacao(rel, () => { r.proposta.relacoes.splice(i, 1); pintarRelacoes(); })));
    };
    pintarRelacoes();

    const form = el("form", { class: "painel rascunho", id: "rascunho", novalidate: true, "aria-label": "Rascunho do item" });
    form.addEventListener("submit", enviarParaFila);
    form.append(
      campo("Título", "r-titulo", el("input", { class: "titulo-campo", maxlength: "200", value: v(it.titulo) })),
      el("div", { class: "linha-campos" },
        campo("Tipo", "r-tipo", selecionar(Object.entries(TIPOS), it.tipo)),
        campo("Etapa", "r-secao", selecionar(SECOES, it.secao)),
        campo("Segmento", "r-segmento", el("input", { list: "lista-segmentos", maxlength: "100", value: v(it.segmento), placeholder: "Todos os segmentos" })),
        campo("Serviço", "r-servico", el("input", { maxlength: "100", value: v(it.servico), placeholder: "Opcional" })),
        campo("Data do acontecido", "r-data", el("input", { type: "date", value: v(it.data_evento) }))),
      campo("Descrição", "r-descricao", area(it.descricao, 4, 4000), true),
      el("div", { class: "linha-campos" },
        campo("O que foi feito", "r-feito", area(it.o_que_foi_feito, 2, 4000)),
        campo("Resultado", "r-resultado", area(it.resultado, 2, 2000, "Um número, se houver: obrigatório na evidência 4"))),
      el("div", { class: "campo inteiro" },
        el("p", { class: "t-rotulo", id: "rotulo-evid", text: r.sugerida ? `Evidência · o curador sugeriu ${r.sugerida}` : "Evidência" }), grupo),
      campo("Contexto do cliente (sem dado pessoal)", "r-contexto", area(it.contexto_cliente, 2, 2000), true),
      el("div", { class: "campo inteiro" }, el("p", { class: "t-rotulo", text: "Ligações sugeridas" }), relacoes),
      el("datalist", { id: "lista-segmentos" }, SEGMENTOS.map((s) => el("option", { value: s }))));
    if (r.proposta.avisos && r.proposta.avisos.length) {
      form.append(el("div", { class: "campo inteiro" }, el("p", { class: "t-rotulo", text: "Para o revisor" }), listaAvisos(r.proposta.avisos)));
    }
    form.append(el("div", { class: "barra-envio" },
      el("span", { class: "t-p suave" }, "Nada é gravado até você enviar. O item entra como ", el("b", { class: "forte", text: "proposto" }), " e espera alguém do time aprovar."),
      el("div", { class: "botoes" },
        el("button", { type: "button", class: "btn", onclick: novoRegistro }, "Descartar"),
        el("button", { type: "submit", class: "btn primario", id: "enviar-fila" }, icone("check", "ic p"), "Enviar para a Fila"))));
    return form;
  }
  function painelEnviado(criado) {
    const r = estado.reg;
    return el("div", { class: "painel enviado", role: "status" },
      mascoteEm("m", { humor: "padrao" }),
      el("div", { class: "enviado-corpo" },
        el("h2", { class: "t-secao", text: "Enviado para a Fila" }),
        el("p", { class: "t-p suave", text: `O INS-${criado.id} entra como proposto e espera alguém do time aprovar.${r.lacunaId ? " A lacuna foi marcada como resolvida." : ""}` }),
        el("div", { class: "botoes" },
          el("a", { class: "btn primario", href: "#fila", text: "Ver na Fila" }),
          el("a", { class: "btn", href: `#item/INS-${criado.id}`, text: `Abrir o INS-${criado.id}` }),
          el("button", { type: "button", class: "btn fantasma", onclick: novoRegistro }, "Registrar outro relato"))));
  }
  function carregandoCurador() {
    return el("div", { class: "carregando", role: "status" }, mascoteEm("m", { humor: "pensando" }),
      el("p", { class: "t-rotulo", text: "O curador está organizando o relato" }),
      el("span", { class: "esqueleto" }), el("span", { class: "esqueleto" }), el("span", { class: "esqueleto curto" }));
  }
  // O que a pessoa já editou no formulário volta para o rascunho antes de qualquer repintura (ao sair da aba e voltar,
  // por exemplo): senão o formulário recomeçaria da proposta do curador.
  function guardarEdicoes() {
    const r = estado.reg;
    if (!r.proposta || !$("#rascunho")) return;
    const d = lerRascunho();
    Object.assign(r.proposta.insight, { titulo: d.titulo || "", tipo: d.tipo, secao: d.secao, segmento: d.segmento, servico: d.servico,
      data_evento: d.data_evento, descricao: d.descricao || "", o_que_foi_feito: d.o_que_foi_feito, resultado: d.resultado,
      contexto_cliente: d.contexto_cliente });
  }
  function pintarRegistrar() {
    guardarEdicoes();
    const r = estado.reg;
    $("#registrar-titulo").textContent = r.proposta || r.ocupado || r.enviado ? "Revise antes de enviar para a Fila" : "Registrar um relato";
    const origem = $("#registrar-origem");
    origem.hidden = !(r.proposta || r.ocupado || r.enviado);
    origem.textContent = ORIGENS_REG[r.origem];
    const filhos = [];
    if (r.lacunaPergunta) {
      filhos.push(el("p", { class: "t-p suave" }, "Lacuna: ", el("b", { class: "forte", text: `“${r.lacunaPergunta}”` })));
    }
    if (r.enviado) filhos.push(painelEnviado(r.enviado));
    else if (r.ocupado) filhos.push(carregandoCurador());
    else if (!r.proposta) filhos.push(painelRelato());
    else {
      if (r.perguntas.length) filhos.push(cartaoPerguntas());
      filhos.push(formularioRascunho());
    }
    $("#registrar-corpo").replaceChildren(...filhos);
    mostrarAvisoRegistro(r.erro);
    const area = $("#campo-reg");
    if (area && estado.tela === "registrar") area.focus({ preventScroll: true });
  }
  function lerRascunho() {
    const v = (id) => { const x = $(`#${id}`).value.trim(); return x === "" ? null : x; };
    return {
      titulo: v("r-titulo"), tipo: v("r-tipo"), secao: v("r-secao"),
      descricao: v("r-descricao"), segmento: v("r-segmento"), servico: v("r-servico"),
      o_que_foi_feito: v("r-feito"), resultado: v("r-resultado"), contexto_cliente: v("r-contexto"),
      data_evento: v("r-data"), evidencia: estado.reg.evidencia,
      relacoes: (estado.reg.proposta.relacoes || []).map((rel) => ({ relacionado_id: rel.relacionado_id, tipo: rel.tipo })),
    };
  }
  async function enviarParaFila(ev) {
    ev.preventDefault();
    const r = estado.reg;
    if (!r.proposta) return;
    const dados = lerRascunho();
    for (const id of ["r-titulo", "r-descricao", "r-resultado", "r-evid-grupo", ...Object.values(CAMPO_PARA_ID)]) limparErroCampo(id);
    mostrarAvisoRegistro(null);
    const erros = validarRascunho(dados);
    if (Object.keys(erros).length) {
      for (const [id, msg] of Object.entries(erros)) marcarErroCampo(id, msg);
      focarPrimeiroErro();
      return;
    }
    const botao = $("#enviar-fila");
    botao.disabled = true;
    try {
      const corpo = { ...dados, fonte: "chat" };
      if (r.lacunaId) corpo.lacuna_id = r.lacunaId;  // salvar o item resolve a lacuna de onde ele veio
      const criado = await chamar("POST", "/insights", corpo);
      await carregarItens();
      r.enviado = criado;
      aviso("Enviado para a Fila.", "ok");
      pulsarMascote();
      atualizarNumeros();
      pintarRegistrar();
    } catch (e) {
      botao.disabled = false;
      const achados = e.status === 422 ? camposComDadoPessoal(e.message) : [];
      if (achados.length) {  // o tipo e o campo, nunca o dado
        for (const [tipo, campoServidor] of achados) {
          const id = CAMPO_PARA_ID[campoServidor];
          if (id) marcarErroCampo(id, `Possível ${tipo} neste campo. Troque por algo genérico e envie de novo. Nada foi gravado.`, true);
        }
        focarPrimeiroErro();
        mostrarAvisoRegistro({ msg: "Encontrei dado pessoal no rascunho. Nada foi gravado." });
        return;
      }
      mostrarAvisoRegistro({ msg: e.message, fila: e.status === 409 });  // 409 duplicado, relação que não existe, 502...
    }
  }

  // ---------------------------------------------------------------- fila (a triagem pelo teclado, prancha 4)
  // A lista à esquerda, o item selecionado à direita. Teclado (fora de campo de texto): J e K movem, Enter abre, A aprova,
  // R vai ao motivo (obrigatório), X marca, Shift+A aprova os marcados (com a confirmação) e ? mostra os atalhos. Nada é
  // otimista: o cartão fica "aprovando…" até o servidor responder. O lote é um laço de POST /insights/{id}/aprovar.
  const ORIGEM_ITEM = { chat: "Chat", notion: "Notion", drive: "Drive", canva: "Canva", reuniao: "Reunião", upload: "Arquivo" };
  const POR_PAGINA_FILA = 30;
  const ATALHOS_FILA = [
    ["J", "K", "mover"], ["A", null, "aprovar"], ["R", null, "rejeitar"], ["X", null, "marcar"],
    ["⇧A", null, "aprovar marcados, sem ler um a um"], ["?", null, "todos os atalhos"],
  ];

  // "hoje", "ontem" ou o dia: a data de quando o item foi registrado (sem criado_em, nada).
  function dataRelativa(iso) {
    if (!iso) return "";
    const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
    if (Number.isNaN(d.getTime())) return "";
    const dias = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86400000);
    if (dias <= 0) return "hoje";
    if (dias === 1) return "ontem";
    return d.toLocaleDateString("pt-BR", { day: "numeric", month: "short" }).replace(".", "");
  }
  const filaAtual = () => estado.itens.find((i) => i.id === estado.fila.atual) || null;

  function pintarFila() {
    const f = estado.fila;
    const itens = estado.itens.filter(estaNaFila).sort((a, b) => b.id - a.id);
    for (const id of [...f.selecionados]) if (!itens.some((i) => i.id === id)) f.selecionados.delete(id);  // já decididos
    $("#titulo-fila").textContent = itens.length ? `${itens.length} ${itens.length === 1 ? "item esperando" : "itens esperando"} a leitura do time` : "Nada para revisar";
    $("#teclas-fila").hidden = !itens.length || CELULAR.matches;
    const lista = $("#lista-fila");
    if (!itens.length) {  // a Fila em dia
      $("#filtros-fila").replaceChildren();
      $("#lote-fila").replaceChildren();
      lista.replaceChildren(vazio("Nada para revisar",
        "Itens novos chegam pela conversa, pelo Registrar e pela sincronização das fontes.",
        el("a", { class: "btn primario", href: "#registrar", text: "Registrar algo" })));
      return;
    }
    const origens = [...new Set(itens.map((i) => i.fonte))];
    if (f.origem && !origens.includes(f.origem)) f.origem = null;
    const visiveis = itens.filter((i) => !f.origem || i.fonte === f.origem);
    f.visiveis = visiveis;
    if (!visiveis.some((i) => i.id === f.atual)) f.atual = visiveis.length ? visiveis[0].id : null;
    const reiniciar = (origem) => () => { f.origem = origem; f.mostrar = POR_PAGINA_FILA; pintarFila(); };
    $("#filtros-fila").replaceChildren(
      chip(`Todas as origens (${itens.length})`, !f.origem, reiniciar(null)),
      ...(origens.length > 1 ? origens.map((o) => chip(`${ORIGEM_ITEM[o] || o} (${itens.filter((i) => i.fonte === o).length})`, f.origem === o,
        reiniciar(f.origem === o ? null : o))) : []));
    pintarLote();
    const coluna = el("div", { class: "fila-lista", role: "list", "aria-label": "Itens esperando" },
      ...visiveis.slice(0, f.mostrar).map(itemDaFila));
    if (visiveis.length > f.mostrar) {
      coluna.append(el("button", { type: "button", class: "btn fantasma",
        onclick: () => { f.mostrar += POR_PAGINA_FILA; pintarFila(); } },
      `Mostrar mais ${Math.min(POR_PAGINA_FILA, visiveis.length - f.mostrar)} (restam ${visiveis.length - f.mostrar})`));
    }
    lista.replaceChildren(coluna, el("aside", { class: "fila-detalhe", id: "fila-detalhe", "aria-label": "Item selecionado" }));
    pintarDetalhe();
    pintarTeclasFila();
  }
  function itemDaFila(it) {
    const f = estado.fila;
    const marcado = f.selecionados.has(it.id);
    const atual = f.atual === it.id;
    const caixa = el("input", { type: "checkbox", class: "marcar", checked: marcado ? "" : null, "aria-label": `Marcar ${it.codigo}: ${it.titulo}` });
    caixa.addEventListener("change", () => alternarMarca(it.id, caixa.checked));
    const corpo = el("button", { type: "button", class: "fila-corpo", "aria-current": atual ? "true" : null,
      onclick: () => { if (CELULAR.matches) abrirItem(it.codigo); else selecionarNaFila(it.id); } },
    el("span", { class: "linha-topo" }, el("span", { class: "t-dado", text: it.codigo }),
      el("span", { class: "t-rotulo", text: TIPOS[it.tipo] || it.tipo }), seloDaFila(it)),
    el("b", { class: "titulo", text: it.titulo }),
    el("span", { class: "evid" }, trilha(it.evidencia),
      [EVIDENCIA[it.evidencia], ORIGEM_ITEM[it.fonte] || it.fonte, dataRelativa(it.criado_em)].filter(Boolean).join(" · ")));
    const processando = f.processando === it.id;
    return el("article", { class: `fila-item${atual ? " selecionado" : ""}${marcado ? " marcado" : ""}${processando ? " aprovando" : ""}`,
      "data-id": String(it.id), role: "listitem", "aria-busy": processando ? "true" : null }, caixa, corpo);
  }
  function selecionarNaFila(id, { foco = false } = {}) {
    const f = estado.fila;
    f.atual = id;
    f.erro = null;
    for (const cartao of $$("#lista-fila .fila-item")) {
      const dele = Number(cartao.dataset.id) === id;
      cartao.classList.toggle("selecionado", dele);
      const corpo = $(".fila-corpo", cartao);
      if (dele) corpo.setAttribute("aria-current", "true"); else corpo.removeAttribute("aria-current");
      if (dele && foco) { corpo.focus(); cartao.scrollIntoView({ block: "nearest" }); }
    }
    pintarDetalhe();
  }
  function moverNaFila(delta) {
    const f = estado.fila;
    if (!f.visiveis.length) return;
    const i = f.visiveis.findIndex((x) => x.id === f.atual);
    const novo = f.visiveis[Math.min(f.visiveis.length - 1, Math.max(0, (i < 0 ? 0 : i) + delta))];
    selecionarNaFila(novo.id, { foco: true });
  }
  function alternarMarca(id, marcado) {
    const f = estado.fila;
    if (marcado) f.selecionados.add(id); else f.selecionados.delete(id);
    f.confirmando = false;
    const cartao = $(`#lista-fila .fila-item[data-id="${id}"]`);
    if (cartao) { cartao.classList.toggle("marcado", marcado); $("input.marcar", cartao).checked = marcado; }
    pintarLote();
  }

  // O item selecionado: o texto, a contradição com um item já aprovado, o motivo e as ações.
  function pintarDetalhe() {
    const f = estado.fila;
    const caixa = $("#fila-detalhe");
    const it = filaAtual();
    if (!caixa) return;
    if (!it) { caixa.replaceChildren(); return; }
    const ocupado = f.processando === it.id;
    const contradiz = (it.relacoes || []).filter((r) => r.tipo === "contradiz")
      .map((r) => estado.itens.find((o) => o.id === r.relacionado_id)).filter((o) => o && !estaNaFila(o) && o.status !== "obsoleto");
    const avs = avisosDeEvidencia(it);
    const motivo = el("textarea", { id: "motivo-fila", rows: "2", maxlength: "1000", placeholder: "Por exemplo: um caso só, e vai contra o que já está aprovado" });
    motivo.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); rejeitarAtual(); }
      if (e.key === "Escape") { e.stopPropagation(); motivo.blur(); }
    });
    caixa.replaceChildren(...[
      el("p", { class: "t-rotulo marca", text: `${it.codigo} · ${TIPOS[it.tipo] || it.tipo} · ${(STATUS[it.status] || it.status).toLowerCase()}` }),
      el("div", { class: "meta" },
        el("span", { class: "selo", text: [ORIGEM_ITEM[it.fonte] || it.fonte, it.autor, dataRelativa(it.criado_em)].filter(Boolean).join(" · ") })),
      el("h2", { class: "t-titulo", text: it.titulo }),
      el("p", { class: "desc", text: it.descricao }),
      el("div", { class: "meta" },
        el("span", { class: "etiqueta", text: NOME_SECAO[it.secao] || it.secao }),
        el("span", { class: "etiqueta", text: it.segmento ? capital(it.segmento) : "Todos os segmentos" }),
        el("span", { class: "evid" }, trilha(it.evidencia), EVIDENCIA[it.evidencia]),
        linkOrigem(it)),
      ...contradiz.map((o) => el("div", { class: "contradiz-aprovado", role: "note" },
        el("p", { class: "t-rotulo" }, icone("alerta", "ic p"), "Contradiz um item aprovado"),
        el("div", { class: "contradiz-duplo" },
          el("div", { class: "cartao" }, el("span", { class: "t-legenda", text: "Este item" }), el("b", { text: it.titulo })),
          el("a", { class: "cartao", href: `#item/${o.codigo}` }, el("span", { class: "t-legenda", text: `${o.codigo} · ${STATUS[o.status] || o.status}` }), el("b", { text: o.titulo }))),
        el("p", { class: "t-p suave", text: `Aprovar não muda o ${o.codigo}: os dois ficam na base, ligados por “contradiz”, e o mapa mostra a linha entre eles.` }))),
      avs.length ? listaAvisos(avs) : null,
      f.erro && f.erro.id === it.id ? el("div", { class: "aviso-registro", role: "alert" }, icone("alerta", "ic p"), el("span", { class: "t-p", text: f.erro.msg }),
        f.erro.recarregar ? el("button", { type: "button", class: "btn", onclick: async () => { f.erro = null; await carregarItens(); atualizarNumeros(); pintarFila(); } }, "Recarregar a Fila") : null) : null,
      el("div", { class: "campo" }, el("label", { for: "motivo-fila", text: "Motivo para rejeitar (obrigatório)" }), motivo),
      el("div", { class: "botoes" },
        el("button", { type: "button", class: "btn primario", disabled: ocupado || null, onclick: aprovarAtual },
          icone("check", "ic p"), ocupado ? "Aprovando…" : "Aprovar", ocupado ? null : tecla("A")),
        el("button", { type: "button", class: "btn perigo", disabled: ocupado || null, onclick: rejeitarAtual }, "Rejeitar", tecla("R")),
        el("button", { type: "button", class: "btn fantasma", onclick: () => moverNaFila(1) }, "Próximo", tecla("J")),
        el("a", { class: "btn fantasma", href: `#item/${it.codigo}` }, "Abrir", tecla("↵"))),
    ].filter(Boolean));
  }
  async function aprovarAtual() {
    const f = estado.fila;
    const it = filaAtual();
    if (!it || f.processando) return;
    const r = await decidir(it, "aprovar");
    if (!r.ok) { f.erro = { id: it.id, msg: r.msg, recarregar: r.recarregar }; pintarDetalhe(); }
  }
  async function rejeitarAtual() {
    const f = estado.fila;
    const it = filaAtual();
    if (!it || f.processando) return;
    const campo = $("#motivo-fila");
    if (!campo.value.trim()) { marcarErroCampo("motivo-fila", "Para rejeitar, escreva o motivo."); campo.focus(); return; }
    const r = await decidir(it, "rejeitar", campo.value);
    if (!r.ok) { f.erro = { id: it.id, msg: r.msg, recarregar: r.recarregar }; pintarDetalhe(); }
  }

  // A barra do lote: quantos estão marcados, "Aprovar os marcados (⇧A)", a confirmação e o progresso "7 de 12".
  function pintarLote() {
    const f = estado.fila;
    const caixa = $("#lote-fila");
    const n = f.selecionados.size;
    if (f.aprovando) {
      caixa.replaceChildren(el("div", { class: "barra-lote" }, el("span", { class: "lote-info", role: "status",
        text: `Aprovando ${f.aprovando.feitos} de ${f.aprovando.total}…` })));
      return;
    }
    const todosMarcados = f.visiveis.length > 0 && f.visiveis.every((i) => f.selecionados.has(i.id));
    const codigos = [...f.selecionados].map((id) => estado.itens.find((i) => i.id === id)).filter(Boolean).map((i) => i.codigo);
    const resumo = codigos.length <= 3 ? codigos.join(", ").replace(/, ([^,]*)$/, " e $1") : `${codigos.slice(0, 2).join(", ")} e mais ${codigos.length - 2}`;
    caixa.replaceChildren(el("div", { class: "barra-lote", role: "region", "aria-label": "Aprovar vários de uma vez" }, ...[
      el("button", { type: "button", class: "btn fantasma",
        onclick: () => {
          for (const i of f.visiveis) { if (todosMarcados) f.selecionados.delete(i.id); else f.selecionados.add(i.id); }
          f.confirmando = false;
          pintarFila();
        } }, todosMarcados ? "Desmarcar todos" : `Selecionar todos (${f.visiveis.length})`),
      n ? el("span", { class: "selo marca", text: `${n} ${n === 1 ? "marcado" : "marcados"}` }) : null,
      el("span", { class: "lote-info", text: n ? resumo : "Marque com X os itens que quer aprovar de uma vez" }),
      n && !f.confirmando
        ? el("button", { type: "button", class: "btn", onclick: pedirLote },
          n === 1 ? "Aprovar o item marcado" : "Aprovar os marcados", tecla("⇧A"))
        : null,
      n && f.confirmando
        ? el("button", { type: "button", class: "btn primario", id: "confirmar-lote", onclick: aprovarSelecionados },
          `Confirmar: aprovar ${n} sem ler um a um`)
        : null,
      n && f.confirmando
        ? el("button", { type: "button", class: "btn fantasma", onclick: () => { f.confirmando = false; pintarLote(); } }, "Cancelar")
        : null].filter(Boolean)));
  }
  function pedirLote() {  // o primeiro Shift+A pede a confirmação; o segundo a confirma
    const f = estado.fila;
    if (!f.selecionados.size || f.aprovando) return;
    if (!f.confirmando) { f.confirmando = true; pintarLote(); const b = $("#confirmar-lote"); if (b) b.focus(); } else aprovarSelecionados();
  }
  async function aprovarSelecionados() {
    const autor = exigirAutor();
    if (!autor) return;
    const f = estado.fila;
    const ids = [...f.selecionados];
    f.confirmando = false;
    f.aprovando = { feitos: 0, total: ids.length };
    pintarLote();
    let aprovados = 0;
    const falhas = [];
    let semServidor = false;
    for (const id of ids) {  // um por um: quando um falha, a fila segue e diz qual falhou
      try {
        await chamar("POST", `/insights/${id}/aprovar`);
        aprovados += 1;
        f.selecionados.delete(id);
      } catch (e) {
        falhas.push(`INS-${id}`);
        if (e.status === 0) { semServidor = true; break; }  // sem servidor: não adianta tentar os outros
      }
      f.aprovando.feitos += 1;
      pintarLote();
    }
    f.aprovando = null;
    await carregarItens();
    if (aprovados) pulsarMascote();
    const restantes = semServidor ? ids.length - aprovados : falhas.length;
    aviso(restantes
      ? `${aprovados} aprovados. ${restantes} não foram aprovados${semServidor ? " (o servidor parou de responder)" : `: ${falhas.slice(0, 5).join(", ")}${falhas.length > 5 ? "…" : ""}`}. Continuam marcados.`
      : `${aprovados} ${aprovados === 1 ? "item aprovado" : "itens aprovados"}. Já estão na base.`, restantes ? "erro" : "ok");
    atualizarNumeros();
    pintarFila();
  }

  // A legenda fixa no rodapé e o painel de "todos os atalhos" (a tecla ?).
  function pintarTeclasFila() {
    const f = estado.fila;
    const caixa = $("#teclas-fila");
    caixa.replaceChildren(...[
      ...ATALHOS_FILA.map(([a, b, texto]) => el("span", { class: "t-legenda" }, tecla(a), b ? tecla(b) : null, texto)),
      f.ajuda ? el("div", { class: "atalhos-todos", role: "dialog", "aria-label": "Atalhos da Fila" },
        el("p", { class: "t-rotulo", text: "Todos os atalhos da Fila" }),
        el("ul", {},
          [["J ou ↓", "próximo item"], ["K ou ↑", "item anterior"], ["Enter", "abrir o item"], ["A", "aprovar o item"],
            ["R", "ir ao motivo para rejeitar (⌘↵ confirma)"], ["X", "marcar ou desmarcar"],
            ["⇧A", "aprovar os marcados, com confirmação"], ["?", "mostrar ou esconder esta lista"]]
            .map(([k, t]) => el("li", {}, tecla(k), ` ${t}`)))) : null].filter(Boolean));
  }
  function teclasDaFila(e) {
    if (estado.tela !== "fila" || paleta.aberta || e.metaKey || e.ctrlKey || e.altKey) return;
    const alvo = e.target;
    if (alvo.matches("textarea, select, [contenteditable]") || (alvo.matches("input") && !["checkbox", "button"].includes(alvo.type))) return;  // digitando
    const f = estado.fila;
    if (e.key === "?") { e.preventDefault(); f.ajuda = !f.ajuda; pintarTeclasFila(); return; }
    if (e.key === "Escape" && f.ajuda) { f.ajuda = false; pintarTeclasFila(); return; }
    if (e.shiftKey && e.key.toLowerCase() === "a") { e.preventDefault(); pedirLote(); return; }
    if (e.shiftKey) return;
    const k = e.key.toLowerCase();
    if (k === "j" || k === "arrowdown") { e.preventDefault(); moverNaFila(1); }
    else if (k === "k" || k === "arrowup") { e.preventDefault(); moverNaFila(-1); }
    else if (k === "a") { e.preventDefault(); aprovarAtual(); }
    else if (k === "r") { e.preventDefault(); const c = $("#motivo-fila"); if (c) c.focus(); }
    else if (k === "x") { e.preventDefault(); if (f.atual != null) alternarMarca(f.atual, !f.selecionados.has(f.atual)); }
    else if (k === "enter" && (alvo === document.body || alvo.matches(".fila-corpo, .marcar"))) {  // Enter abre o item selecionado
      const it = filaAtual();
      if (it) { e.preventDefault(); abrirItem(it.codigo); }
    }
  }

  // Aprovar ou rejeitar um item: o servidor decide, e a tela só reflete (nada de atualização otimista). Devolve
  // { ok } ou { ok: false, msg, recarregar }: quem chamou mostra o erro onde faz sentido.
  async function decidir(it, acao, motivo) {
    const f = estado.fila;
    if (acao === "rejeitar" && !(motivo && motivo.trim())) return { ok: false, msg: "Para rejeitar, escreva o motivo." };
    f.processando = it.id;
    f.erro = null;
    if (estado.tela === "fila") pintarFila();
    try {
      await chamar("POST", `/insights/${it.id}/${acao}`, acao === "aprovar" ? undefined : { motivo: motivo.trim() });
      await carregarItens();
      const i = f.visiveis.findIndex((x) => x.id === it.id);  // o próximo da lista ganha o foco
      const proximo = f.visiveis[i + 1] || f.visiveis[i - 1];
      f.atual = proximo ? proximo.id : null;
      aviso(acao === "aprovar" ? `${it.codigo} aprovado. Já está na base.` : `${it.codigo} rejeitado e marcado como obsoleto.`, "ok");
      pulsarMascote();
      return { ok: true };
    } catch (e) {
      return { ok: false, msg: e.message, recarregar: e.status === 422 && /outra pessoa/.test(e.message) };
    } finally {
      f.processando = null;
      atualizarNumeros();
      if (estado.tela === "fila") pintarFila();
    }
  }

  // ---------------------------------------------------------------- fontes
  const ORIGEM = { notion: "Notion", drive: "Drive", upload: "Arquivo" };
  // [rótulo, cor, o que significa e o que fazer]
  const STATUS_FONTE = {
    a_curar: ["Esperando o curador", "alerta", "Passou na triagem e espera o curador propor itens a partir dela."],
    importada: ["Virou itens", "ok", "O curador já propôs itens a partir dela. Eles estão na Fila, esperando aprovação."],
    falha: ["Falhou", "risco", "O curador falhou nesta página. A próxima sincronização tenta de novo."],
    vazia: ["Vazia", "mudo", "Quase sem texto (uma página só de índice, por exemplo). Não vai ao curador."],
    pulada_dado_pessoal: ["Dado pessoal", "risco", "Tem e-mail, CPF, CNPJ ou telefone, então nunca vai ao modelo. Para ela entrar, limpe o dado na página de origem."],
    pulada_longa: ["Longa demais", "alerta", "Passa de 5 trechos. Divida a página na origem para ela entrar."],
    pulada_duplicata: ["Duplicata", "mudo", "Tem o mesmo conteúdo de outra página já lida."],
    so_busca: ["Só na busca", "alerta", "O chat acha trechos dela, mas ela não foi ao curador (planilha ou documento longo demais para virar itens)."],
    removida: ["Removida", "mudo", "Saiu da origem (apagada ou sem compartilhamento). Os itens ainda não revisados viraram obsoletos."],
  };
  // O Drive tem outras razões e outros remédios que o Notion: a explicação muda com a origem.
  const STATUS_FONTE_DRIVE = {
    a_curar: "Passou na triagem e espera o curador propor itens a partir dele.",
    importada: "O curador já propôs itens a partir dele. Eles estão na Fila, esperando aprovação.",
    falha: "O curador falhou neste documento. A próxima sincronização tenta de novo.",
    vazia: "Sem texto que dê para ler (PDF só de imagem, arquivo em branco ou formato não suportado). Não vai ao curador nem à busca. Para entrar, salve como Google Doc ou PDF com texto.",
    pulada_longa: "Arquivo grande demais para baixar (veja o limite no motivo). Divida-o ou salve uma versão menor no Drive para ele entrar.",
    pulada_duplicata: "Tem o mesmo conteúdo de outro arquivo já lido.",
    removida: "Saiu da pasta do Drive (apagado, movido ou sem acesso). Os itens ainda não revisados viraram obsoletos.",
    so_busca: "O chat acha trechos dele (marcados [DOC-n]), mas ele não foi ao curador: é planilha ou documento longo demais para virar itens.",
  };
  const PULADAS = ["vazia", "pulada_dado_pessoal", "pulada_longa", "pulada_duplicata"];
  const ROTULO_ITEM = { historico_a_validar: "na Fila", proposto: "na Fila", validado: "aprovado", consolidado: "consolidado", obsoleto: "obsoleto" };

  // Só https, ou o texto de um anexo (/fontes/<id>/texto), que o próprio servidor entrega: nunca um endereço qualquer.
  function linkSeguro(url) { return typeof url === "string" && /^(https:\/\/|\/fontes\/\d+\/texto$)/.test(url) ? url : null; }
  function dataHora(iso) {
    if (!iso) return "";
    const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);  // o servidor manda em UTC, sem o "Z"
    return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  }
  function linkOrigem(it) {
    const url = it.fonte && it.fonte !== "chat" ? linkSeguro(it.fonte_ref) : null;
    if (!url) return null;
    return el("a", { class: "origem", href: url, target: "_blank", rel: "noopener noreferrer", title: "Abrir a página de origem" },
      `${ORIGEM[it.fonte] || it.fonte} ↗`);
  }
  function numeroCartao(n, rotulo, cor) {
    return el("div", { class: "cartao-numero", style: cor ? `--c:${cor}` : null },
      el("b", { text: String(n) }), el("span", { text: rotulo }));
  }
  function resumoDeItens(itens) {
    const partes = Object.entries(itens || {}).map(([st, n]) => `${n} ${ROTULO_ITEM[st] || st}`);
    return partes.length ? partes.join(" · ") : null;
  }
  function cartaoFonte(f) {
    const [rotulo, cor, explicaPadrao] = STATUS_FONTE[f.status] || [f.status, "mudo", ""];
    const explica = (f.origem === "drive" && STATUS_FONTE_DRIVE[f.status]) || explicaPadrao;
    const url = linkSeguro(f.url);
    const titulo = url
      ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: f.titulo })
      : document.createTextNode(f.titulo);
    const gerou = resumoDeItens(f.itens);
    return el("article", { class: "item fonte" },
      el("div", { class: "meta" },
        el("span", { class: "etiqueta", text: ORIGEM[f.origem] || f.origem }),
        f.categoria ? el("span", { class: "etiqueta pasta", text: f.categoria }) : null,
        el("span", { class: `etiqueta estado-${cor}`, text: rotulo })),
      el("h3", {}, titulo),
      el("p", { class: "explica", text: explica }),
      f.motivo ? el("p", { class: "motivo-fonte", text: `Motivo: ${f.motivo}` }) : null,
      el("div", { class: "linha-evid" },
        gerou ? el("span", { class: "evid", text: `Itens gerados: ${gerou}` }) : null,
        el("span", { text: `Editada em ${dataHora(f.editado_em)} · lida em ${dataHora(f.importado_em)}` })));
  }
  function orientacaoFontes() {
    return el("div", { class: "painel passo-a-passo" },
      vazio("Nada lido ainda", "Quando o Cérebro ler o Notion ou o Drive, cada página ou documento aparece aqui, com o que aconteceu com ele."),
      el("ol", {},
        el("li", {}, "Peça a quem cuida do servidor para ligar o Notion ou o Drive (no Notion, a integração só enxerga as páginas compartilhadas com ela; no Drive, a pasta precisa estar compartilhada com a conta do Cérebro)."),
        el("li", {}, "Escolha a origem (Notion ou Drive) no painel acima."),
        el("li", {}, "Clique em ", el("b", { text: "Só simular" }), " acima: lê o Notion e estima o custo, sem gravar nada."),
        el("li", {}, "Clique em ", el("b", { text: "Sincronizar agora" }), ". Os itens propostos aparecem na Fila."),
      ));
  }

  // ---- sincronizar o Notion ou o Drive pela tela (POST /fontes/sincronizar + GET /fontes/execucoes/{id})
  const FASE_SYNC = { curando: "O curador está propondo itens…", fim: "Terminando…" };
  const FONTE_DA_SYNC = { notion: "Notion", drive: "Drive" };
  function faseDaSync(e) {
    if (!e) return "Começando…";
    if (e.fase === "sincronizando") return `Lendo o ${FONTE_DA_SYNC[e.origem] || "origem"}…`;
    return FASE_SYNC[e.fase] || "Trabalhando…";
  }
  const POR_PAGINA_FONTES = 50;
  let painelSync = null;  // o elemento do painel na tela de Fontes (recriado a cada pintarFontes)

  function usd(v, casas = 4) { return `US$ ${Number(v || 0).toFixed(casas).replace(".", ",")}`; }
  function resumoDaExecucao(e) {
    const c = e.contagens;
    const partes = [`${c.lidas} lidas`, `${c.novas} novas`, `${c.alteradas} alteradas`, `${c.puladas} puladas`];
    if (c.removidas) partes.push(`${c.removidas} removidas`);
    if (c.falhas) partes.push(`${c.falhas} com falha`);
    if (!e.dry_run) partes.push(`${c.curadas} curadas`, `${c.insights_propostos} itens propostos`);
    return partes.join(" · ");
  }
  function fraseFinal(e) {
    if (e.status === "erro") {
      return e.erro === "interrompida"
        ? "A sincronização foi interrompida (o servidor reiniciou). O que estava pela metade não entrou: rode de novo."
        : `A sincronização deu erro (${e.erro || "desconhecido"}). O que estava pela metade não entrou: tente de novo.`;
    }
    if (e.dry_run) return `Simulação concluída, nada foi gravado. Estimativa do curador: ${usd(e.estimativa_usd)}.`;
    if (e.status === "parou_no_teto") {
      return `Parou no teto de gasto (${usd(e.gasto_usd)} de ${usd(e.teto_usd, 2)}). Clique em Sincronizar agora de novo para continuar de onde parou.`;
    }
    return `Sincronização concluída. ${e.contagens.insights_propostos} itens propostos, ${usd(e.gasto_usd)} gastos. Eles estão na Fila.`;
  }
  function pintarPainelSync() {
    if (!painelSync || !painelSync.isConnected) return;
    const sy = estado.sync;
    const e = sy.exec;
    const rodando = Boolean(sy.id) && (!e || e.status === "rodando");
    const filhos = [];
    if (rodando) {
      const fase = faseDaSync(e);
      filhos.push(
        el("div", { class: "sync-linha", role: "status" },
          el("span", { class: "girando", "aria-hidden": "true" }),
          el("b", { text: `${sy.dry ? "Simulando" : "Sincronizando"}: ${fase}` })),
        e ? el("p", { class: "sync-num", text: resumoDaExecucao(e) }) : null,
        e && !e.dry_run ? el("p", { class: "sync-num", text: `Gasto do curador: ${usd(e.gasto_usd)} de ${usd(e.teto_usd, 2)}` }) : null,
        el("p", { class: "dica", text: "Pode trocar de tela ou fechar a aba: a sincronização continua no servidor." }));
    } else {
      if (e) {
        filhos.push(el("p", { class: `sync-final${e.status === "erro" ? " erro" : ""}`, text: fraseFinal(e) }),
          el("p", { class: "sync-num", text: resumoDaExecucao(e) }));
      }
      const teto = el("input", { type: "number", id: "sync-teto", min: "0.01", step: "0.25", value: String(sy.teto), "aria-label": "Teto de gasto do curador, em dólares" });
      teto.addEventListener("change", () => {
        const v = Number(String(teto.value).replace(",", "."));
        if (v > 0) sy.teto = v; else teto.value = String(sy.teto);
      });
      filhos.push(el("div", { class: "sync-origem", role: "group", "aria-label": "O que sincronizar" },
        ...Object.entries(FONTE_DA_SYNC).map(([o, nome]) => chip(nome, sy.origem === o, () => { sy.origem = o; pintarPainelSync(); }))));
      filhos.push(el("div", { class: "sync-acoes" },
        el("button", { type: "button", class: "btn primario", onclick: () => iniciarSincronizacao(false) }, "Sincronizar agora"),
        el("button", { type: "button", class: "btn fantasma", onclick: () => iniciarSincronizacao(true) }, "Só simular"),
        el("label", { class: "sync-teto" }, "Teto de gasto (US$)", teto)));
    }
    painelSync.replaceChildren(...filhos.filter(Boolean));
  }
  async function iniciarSincronizacao(dry) {
    const sy = estado.sync;
    if (sy.id && (!sy.exec || sy.exec.status === "rodando")) return;
    try {
      const r = await chamar("POST", "/fontes/sincronizar", { origem: sy.origem, dry_run: dry, teto_usd: sy.teto });
      acompanharExecucao(r.execucao_id, dry);
    } catch (e) {
      if (e.status === 409) {  // já há uma rodando (aberta por outra pessoa ou outra aba): só acompanha
        const m = /#(\d+)/.exec(e.message);
        if (m) acompanharExecucao(Number(m[1]), false);
      }
      aviso(e.message, "erro");
    }
  }
  async function acompanharExecucao(id, dry) {
    const sy = estado.sync;
    if (sy.id === id && sy.acompanhando) return;
    Object.assign(sy, { id, dry, exec: null, acompanhando: true });
    pintarPainelSync();
    let falhasDeRede = 0;
    while (sy.id === id) {
      try {
        sy.exec = await chamar("GET", `/fontes/execucoes/${id}`);
        falhasDeRede = 0;
      } catch {
        falhasDeRede += 1;
        if (falhasDeRede >= 5) { aviso("Perdi o contato com o servidor. Recarregue a página para ver como terminou.", "erro"); break; }
      }
      pintarPainelSync();
      if (sy.exec && sy.exec.status !== "rodando") {
        aviso(fraseFinal(sy.exec), sy.exec.status === "erro" ? "erro" : "ok");
        if (!sy.exec.dry_run) { await carregarItens(); atualizarNumeros(); if (estado.tela === "fontes") pintarFontes(); }
        break;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    sy.acompanhando = false;
  }

  async function pintarFontes() {
    const box = $("#fontes-conteudo");
    let resumo;
    try {
      resumo = await chamar("GET", "/fontes/resumo");
    } catch (e) {
      aviso(`Não consegui carregar as fontes: ${e.message}`, "erro");
      return;
    }
    estado.fontes = resumo;
    atualizarNumeros();

    const ultima = resumo.ultima_execucao;
    const sy = estado.sync;
    if (ultima && !ultima.fim && !sy.id) acompanharExecucao(ultima.id, false);  // reabriu a tela com uma rodando
    painelSync = el("div", { class: "painel sync", "aria-label": "Sincronizar o Notion ou o Drive" });
    if (!resumo.total) { box.replaceChildren(painelSync, orientacaoFontes()); pintarPainelSync(); return; }

    const por = resumo.por_status;
    const n = (...chaves) => chaves.reduce((t, c) => t + (por[c] || 0), 0);
    const frasesDeSync = Object.entries(FONTE_DA_SYNC).map(([o, nome]) => {
      const u = (resumo.ultima_por_origem || {})[o] || (!resumo.ultima_por_origem && o === "notion" ? ultima : null);
      return u
        ? `${nome}: ${dataHora(u.fim || u.inicio)}${u.fim ? "" : " (não terminou)"} · ${u.paginas_lidas} lidos, ${u.paginas_novas} novos, ${u.paginas_alteradas} alterados${u.paginas_falhas ? `, ${u.paginas_falhas} com falha` : ""}`
        : `${nome}: nunca sincronizado`;
    });
    const filtro = estado.filtroFontes;

    // A lista vem do servidor, já filtrada e paginada: são milhares de páginas.
    const linhas = el("div", { class: "lista" });
    const rodape = el("div", { class: "rodape-fontes" });
    let carregadas = 0;
    let total = 0;
    async function carregarLista(reiniciar) {
      const params = new URLSearchParams({ limit: String(POR_PAGINA_FONTES), offset: String(reiniciar ? 0 : carregadas) });
      if (filtro.status) params.set("status", filtro.status);
      if (filtro.origem) params.set("origem", filtro.origem);
      if (filtro.busca.trim()) params.set("q", filtro.busca.trim());
      let lista;
      try { lista = await chamar("GET", `/fontes?${params}`); }
      catch (e) { aviso(`Não consegui carregar as fontes: ${e.message}`, "erro"); return; }
      if (reiniciar) { linhas.replaceChildren(); carregadas = 0; }
      total = lista.total;
      for (const f of lista.itens) linhas.append(cartaoFonte(f));
      carregadas += lista.itens.length;
      if (!total) linhas.replaceChildren(el("div", { class: "embrulho" }, vazio("Nada com esse filtro", "Tire o filtro ou mude a busca.")));
      rodape.replaceChildren(...(total > carregadas
        ? [el("p", { class: "resumo-lista", text: `Mostrando ${carregadas} de ${total}` }),
           el("button", { type: "button", class: "btn fantasma", onclick: () => carregarLista(false) },
             `Mostrar mais ${Math.min(POR_PAGINA_FONTES, total - carregadas)}`)]
        : total ? [el("p", { class: "resumo-lista", text: `${total} ${total === 1 ? "fonte" : "fontes"}` })] : []));
    }

    const busca = el("input", { type: "search", class: "busca", placeholder: "Buscar pelo título", "aria-label": "Buscar fonte pelo título" });
    busca.value = filtro.busca;
    let espera = null;
    busca.addEventListener("input", () => {
      filtro.busca = busca.value;
      clearTimeout(espera);
      espera = setTimeout(() => carregarLista(true), 300);
    });
    const origens = Object.keys(resumo.por_origem || {}).filter((o) => resumo.por_origem[o]);
    if (filtro.origem && !origens.includes(filtro.origem)) filtro.origem = null;
    const chips = el("div", { class: "filtros" }, busca,
      ...(origens.length > 1 ? origens.sort().map((o) =>
        chip(`${ORIGEM[o] || o} (${resumo.por_origem[o]})`, filtro.origem === o,
          () => { filtro.origem = filtro.origem === o ? null : o; pintarFontes(); })) : []),
      chip(`Todas (${resumo.total})`, !filtro.status && !filtro.origem, () => { filtro.status = null; filtro.origem = null; pintarFontes(); }),
      ...Object.keys(STATUS_FONTE).filter((st) => por[st]).map((st) =>
        chip(`${STATUS_FONTE[st][0]} (${por[st]})`, filtro.status === st, () => { filtro.status = filtro.status === st ? null : st; pintarFontes(); })));

    box.replaceChildren(
      el("div", { class: "fontes-resumo" },
        numeroCartao(resumo.total, "fontes lidas"),
        numeroCartao(n("importada"), "viraram itens", "var(--ok)"),
        numeroCartao(n("a_curar", "falha"), "esperando o curador", "var(--alerta)"),
        numeroCartao(n(...PULADAS), "puladas", "var(--risco)"),
        numeroCartao(n("so_busca"), "só na busca", "var(--alerta)"),
        numeroCartao(n("removida"), "removidas")),
      painelSync,
      el("div", { class: "barra-fontes" }, ...frasesDeSync.map((t, i) => el("span", { text: `${i ? "" : "Última sincronização · "}${t}` }))),
      chips,
      linhas,
      rodape);
    pintarPainelSync();  // só pinta depois de entrar na tela (o painel desconectado é ignorado)
    carregarLista(true);
  }

  // ---------------------------------------------------------------- playbook
  function itensDoPlaybook() {
    const ok = new Set(["validado", "consolidado"]);
    if (estado.filtro.historico) ok.add("historico_a_validar");
    return estado.itens.filter((i) => ok.has(i.status));
  }
  function chip(rotulo, ativo, aoClicar) {
    return el("button", { type: "button", class: "chip", "aria-pressed": String(Boolean(ativo)), onclick: aoClicar }, rotulo);
  }
  const POR_PAGINA_PLAYBOOK = 12;  // por etapa do funil: centenas de cartões de uma vez ficam lentos e cansam
  function abrirBase(secao) {
    estado.filtro.secao = NOME_SECAO[secao] ? secao : null;
    estado.filtro.mostrar = {};
    pintarBase();
  }
  function pintarBase() {
    const todos = itensDoPlaybook();
    const funil = $("#funil");
    funil.replaceChildren();
    $("#titulo-base").textContent = estado.filtro.secao ? NOME_SECAO[estado.filtro.secao] : "A base inteira";
    SECOES.forEach(([chave, nome]) => {
      const n = todos.filter((x) => x.secao === chave).length;
      funil.append(el("button", {
        type: "button", class: "etapa-filtro", "aria-pressed": String(estado.filtro.secao === chave),
        "aria-label": `${nome}: ${n} ${n === 1 ? "item" : "itens"}`,
        onclick: () => { estado.filtro.secao = estado.filtro.secao === chave ? null : chave; estado.filtro.mostrar = {}; pintarBase(); },
      }, el("span", { class: "num-etapa", text: String(n) }), el("span", { text: nome })));
    });

    const filtros = $("#filtros");
    filtros.replaceChildren();
    const busca = el("input", { type: "search", id: "busca-base", class: "busca", placeholder: "Buscar na base", "aria-label": "Buscar na base" });
    busca.value = estado.filtro.busca;
    busca.addEventListener("input", () => { estado.filtro.busca = busca.value; estado.filtro.mostrar = {}; pintarGruposBase(); });
    const refiltrar = (mudar) => () => { mudar(); estado.filtro.mostrar = {}; pintarBase(); };
    filtros.append(busca, chip("Todos os segmentos", !estado.filtro.segmento, refiltrar(() => { estado.filtro.segmento = null; })));
    for (const s of [...new Set(estado.itens.map((i) => i.segmento).filter(Boolean))].sort()) {
      filtros.append(chip(capital(s), estado.filtro.segmento === s, refiltrar(() => { estado.filtro.segmento = s; })));
    }
    // De onde veio o item (Notion, Chat, Drive...). Só aparece quando há mais de uma origem.
    const origens = [...new Set(todos.map((i) => i.fonte).filter(Boolean))];
    if (origens.length > 1) {
      if (estado.filtro.origem && !origens.includes(estado.filtro.origem)) estado.filtro.origem = null;
      filtros.append(el("span", { class: "separador", "aria-hidden": "true" }),
        chip("Todas as origens", !estado.filtro.origem, refiltrar(() => { estado.filtro.origem = null; })),
        ...origens.sort().map((o) => chip(`${ORIGEM_ITEM[o] || o} (${todos.filter((i) => i.fonte === o).length})`, estado.filtro.origem === o,
          refiltrar(() => { estado.filtro.origem = estado.filtro.origem === o ? null : o; }))));
    }
    filtros.append(chip("Incluir histórico a validar", estado.filtro.historico, refiltrar(() => { estado.filtro.historico = !estado.filtro.historico; })));
    pintarGruposBase();
  }
  function pintarGruposBase() {
    const box = $("#grupos");
    box.replaceChildren();
    const f = estado.filtro;
    const termo = normalizar(f.busca.trim());
    const itens = itensDoPlaybook().filter((i) =>
      (!f.secao || i.secao === f.secao) &&
      (!f.segmento || !i.segmento || i.segmento === f.segmento) &&
      (!f.origem || i.fonte === f.origem) &&
      (!termo || normalizar(`${i.titulo} ${i.descricao}`).includes(termo)));
    if (!itens.length) {
      const nadaAinda = itensDoPlaybook().length === 0;
      box.append(el("div", { class: "embrulho" }, vazio(
        nadaAinda ? "Nenhum item validado ainda" : "Nada com esses filtros",
        nadaAinda ? "Registre um relato e aprove na Fila. Ele aparece aqui, na etapa do funil a que pertence."
          : "Tire um filtro ou busque outra palavra.",
        nadaAinda ? el("a", { class: "btn primario", href: "#registrar", text: "Registrar um relato" }) : null)));
      return;
    }
    SECOES.forEach(([chave, nome], i) => {
      const doGrupo = itens.filter((x) => x.secao === chave);
      if (!doGrupo.length) return;
      const quantos = f.mostrar[chave] || POR_PAGINA_PLAYBOOK;
      box.append(el("section", { class: "grupo", "aria-label": nome },
        el("h2", {}, el("span", { class: "num", text: String(i + 1).padStart(2, "0") }), nome,
          el("span", { class: "qtd", text: `${doGrupo.length} ${doGrupo.length === 1 ? "item" : "itens"}` })),
        el("div", { class: "grade" }, doGrupo.slice(0, quantos).map(cartaoPlaybook)),
        doGrupo.length > quantos
          ? el("button", { type: "button", class: "btn fantasma mais",
              onclick: () => { f.mostrar[chave] = quantos + POR_PAGINA_PLAYBOOK; pintarGruposBase(); } },
            `Mostrar mais ${Math.min(POR_PAGINA_PLAYBOOK, doGrupo.length - quantos)} (restam ${doGrupo.length - quantos})`)
          : null));
    });
  }
  function cartaoPlaybook(it) {
    return el("button", { type: "button", class: "item cartao", onclick: () => abrirItem(it.codigo) },
      metaItem(it, { secao: false }),
      el("span", { class: "titulo-cartao", text: it.titulo }),
      el("span", { class: "desc", text: it.descricao }),
      el("span", { class: "pe" }, el("span", { class: "evid" }, trilha(it.evidencia), EVIDENCIA[it.evidencia]), el("span", { text: it.codigo })));
  }

  // ---------------------------------------------------------------- página do item
  // O item abre numa aba do centro (no lugar da gaveta), no modelo da "Estação da conta": o rótulo, o título, a faixa de
  // propriedades, o texto, a evidência, de onde veio e as ligações. Tudo sai do que o GET /insights já trouxe. Não há
  // "editar": a API não tem rota de edição.
  const FRASE_NIVEL = { 1: "Opinião, sem caso que sustente.", 2: "Observação única: se apoia em um único caso.",
    3: "Padrão repetido: visto em vários casos.", 4: "Resultado medido: exige um número, e ele está no item." };
  const ORDEM_LIGACAO = ["contradiz", "substitui", "reforca", "duplica"];
  function abrirItem(codigo) {
    if (!acharItem(codigo)) { aviso(`${codigo} não está na base carregada.`, "erro"); return; }
    location.hash = `#item/${codigo}`;
  }
  // As ligações do item: as que saem dele (relacoes) e as que chegam nele (calculadas dos itens carregados).
  function ligacoesDoItem(it) {
    const saem = (it.relacoes || []).map((r) => ({ tipo: r.tipo, id: r.relacionado_id, chega: false }));
    const chegam = estado.itens.filter((o) => o.id !== it.id)
      .flatMap((o) => (o.relacoes || []).filter((r) => r.relacionado_id === it.id).map((r) => ({ tipo: r.tipo, id: o.id, chega: true })));
    return [...saem, ...chegam].sort((a, b) => ORDEM_LIGACAO.indexOf(a.tipo) - ORDEM_LIGACAO.indexOf(b.tipo));
  }
  function linhaLigacao(l) {
    const outro = estado.itens.find((i) => i.id === l.id);
    const rotulo = `${l.chega ? "← " : ""}${capital(RELACOES[l.tipo] || l.tipo)}`;
    const filhos = outro
      ? [pontoEv(outro.evidencia), el("span", { class: "t-dado", text: outro.codigo }), el("span", { class: "txt", text: outro.titulo }),
        estaNaFila(outro) ? el("span", { class: "selo alerta", text: "na Fila" }) : null,
        outro.status === "obsoleto" ? el("span", { class: "selo risco", text: "obsoleto" }) : null]
      : [el("span", { class: "txt suave", text: `INS-${l.id} · fora da base atual` })];  // um item que não está carregado
    return el(outro ? "a" : "div", { class: `ligacao ${l.tipo}`, href: outro ? `#item/${outro.codigo}` : null },
      el("span", { class: "tipo", text: rotulo }), ...filhos.filter(Boolean));
  }
  function faixa(pares) {
    return el("dl", { class: "faixa" }, pares.filter(([, v]) => v).map(([k, v]) =>
      el("div", {}, el("dt", { text: k }), el("dd", {}, v))));
  }
  function textoDoItem(titulo, texto, destaque = false) {
    return texto ? el("section", { class: `texto-item${destaque ? " destaque" : ""}` },
      el("h2", { class: "t-rotulo", text: titulo }), el("p", { class: "t-corpo", text: texto })) : null;
  }
  async function decidirNoItem(it, acao, motivo) {
    const r = await decidir(it, acao, motivo);
    if (!r.ok) aviso(r.msg, "erro");
    if (estado.telaHash === `#item/${it.codigo}`) pintarItem(it.codigo);
  }
  function perguntarSobre() {
    estado.sobreTirado = false;
    atualizarSobre();
    if (CELULAR.matches) location.hash = "#cerebro"; else mostrarCerebro();
  }
  function pintarItem(codigo) {
    const corpo = $("#item-conteudo");
    const it = codigo ? acharItem(codigo) : null;
    if (!it) {
      corpo.replaceChildren(vazio(`${codigo || "Esse item"} não está na base`,
        "Ele pode ter sido rejeitado ou ainda não ter sido carregado.", el("a", { class: "btn", href: "#hoje", text: "Voltar ao Hoje" })));
      return;
    }
    const ligacoes = ligacoesDoItem(it);
    const origem = linkOrigem(it);
    const motivo = el("div", { class: "motivo", hidden: true },
      el("label", { class: "t-rotulo", for: "motivo-item", text: "Motivo da rejeição (obrigatório)" }),
      el("textarea", { id: "motivo-item", rows: "2", maxlength: "1000", placeholder: "Ex.: duplica outro item e não traz nada novo" }),
      el("div", { class: "botoes" },
        el("button", { type: "button", class: "btn perigo", onclick: () => decidirNoItem(it, "rejeitar", $("#motivo-item").value) }, "Confirmar rejeição"),
        el("button", { type: "button", class: "btn fantasma", onclick: () => { motivo.hidden = true; } }, "Cancelar")));
    const avs = avisosDeEvidencia(it);

    corpo.replaceChildren(...[  // replaceChildren(null) escreveria o texto "null": só entra o que existe
      el("header", { class: "cab-tela" },
        el("p", { class: "t-rotulo marca", text: `${it.codigo} · ${TIPOS[it.tipo] || it.tipo}` }),
        el("h1", { class: "t-display", text: it.titulo })),
      // no celular, a evidência vira o quadro grande do topo (prancha 2b)
      el("div", { class: `evidencia-topo c${it.evidencia}` },
        el("div", { class: "evidencia-quadro", role: "img", "aria-label": `Evidência ${it.evidencia} de 4, ${EVIDENCIA[it.evidencia].toLowerCase()}` },
          el("span", { class: "numero", text: String(it.evidencia) }), el("span", { class: "t-rotulo", text: "de 4" })),
        el("div", {}, el("p", { class: "evid" }, EVIDENCIA[it.evidencia]), el("p", { class: "t-legenda", text: FRASE_NIVEL[it.evidencia] }))),
      it.status === "obsoleto"
        ? el("div", { class: "aviso-obsoleto", role: "note" }, el("b", { text: "Obsoleto." }), ` ${it.motivo_obsolescencia || "Foi rejeitado ou substituído."}`)
        : null,
      faixa([
        ["Etapa", NOME_SECAO[it.secao]],
        ["Segmento", it.segmento ? capital(it.segmento) : "Todos os segmentos"],
        ["Serviço", it.servico],
        ["Evidência", el("span", { class: "evid" }, trilha(it.evidencia), EVIDENCIA[it.evidencia])],
        ["Status", STATUS[it.status] || it.status],
        ["Autor", it.autor],
        ["Data do evento", dataBr(it.data_evento)],
        ["Criado em", it.criado_em ? dataHora(it.criado_em).split(",")[0] : null],
      ]),
      el("p", { class: "desc", text: it.descricao }),
      textoDoItem("O que foi feito", it.o_que_foi_feito),
      textoDoItem(it.evidencia === 4 ? "Resultado medido" : "Resultado", it.resultado, it.evidencia === 4),
      textoDoItem("Contexto do cliente", it.contexto_cliente),
      el("section", { class: "evidencia-secao" },
        el("h2", { class: "t-secao", text: "Evidência" }),
        el("div", { class: "evid" }, trilha(it.evidencia, true), el("b", { text: EVIDENCIA[it.evidencia] })),
        el("p", { class: "t-p suave", text: FRASE_NIVEL[it.evidencia] })),
      avs.length ? listaAvisos(avs) : null,
      el("section", { class: "de-onde-veio" },
        el("h2", { class: "t-secao", text: "De onde veio" }),
        el("div", { class: "meta" },
          el("span", { class: "selo", text: ORIGEM_ITEM[it.fonte] || it.fonte }),
          origem, !origem && it.fonte_ref && it.fonte !== "chat" ? el("span", { class: "t-p suave", text: it.fonte_ref }) : null,
          el("span", { class: "t-p suave", text: `Registrado por ${it.autor}` }))),
      el("section", { class: "ligacoes-secao" },
        el("h2", { class: "t-secao", text: "Ligações" }),
        ligacoes.length ? el("div", { class: "ligacoes" }, ligacoes.map(linhaLigacao))
          : el("p", { class: "t-p suave", text: "Este item não tem ligações com outros itens." })),
      el("div", { class: "botoes acoes-item" },
        el("button", { type: "button", class: "btn primario", onclick: perguntarSobre }, icone("chat", "ic p"), "Perguntar sobre este item"),
        el("button", { type: "button", class: "btn", onclick: () => {
          const copiar = navigator.clipboard ? navigator.clipboard.writeText(it.codigo) : Promise.reject(new Error("sem área de transferência"));
          copiar.then(() => aviso(`${it.codigo} copiado.`, "ok"), () => aviso("Não consegui copiar. Selecione o código na tela.", "erro"));
        } }, icone("copiar", "ic p"), "Copiar código"),
        estaNaFila(it) ? el("button", { type: "button", class: "btn", onclick: () => decidirNoItem(it, "aprovar") }, icone("check", "ic p"), "Aprovar") : null,
        estaNaFila(it) ? el("button", { type: "button", class: "btn perigo", onclick: () => { motivo.hidden = false; $("#motivo-item").focus(); } }, "Rejeitar") : null),
      estaNaFila(it) ? motivo : null].filter(Boolean));
    pintarAbas();  // o título da aba pode ter chegado agora
  }

  // ---------------------------------------------------------------- briefing (POST /briefing)
  // O servidor escolhe os itens aprovados e confere as fontes de cada ponto; aqui só se mostra o que ele devolveu.
  const SECOES_BRIEFING = {
    cases: ["var(--ambar)", "A base não tem case para esta reunião."],
    perfil: ["#93a6ff", "A base não tem o perfil deste segmento."],
    roteiro: ["var(--ciano)", "A base não tem material para conduzir esta reunião."],
    objecoes: ["var(--risco)", "A base não tem objeções registradas para este segmento."],
    proposta: ["var(--ok)", "A base não tem estrutura de proposta testada para este segmento."],
  };
  function pintarSegmentosBriefing() {
    const s = $("#b-segmento");
    if (s.options.length) return;
    for (const seg of SEGMENTOS) s.append(el("option", { value: seg, text: capital(seg) }));
  }
  function itemLista(ponto, docs) {
    const fontes = ponto.fontes.map((f) => `[${f.codigo}]`).join(" ");
    const li = el("li", {}, inline(`${ponto.texto} ${fontes}`, docs));
    if (ponto.evidencia_minima != null && ponto.evidencia_minima <= 2) {
      li.append(el("span", { class: "marca-evid", text: ponto.evidencia_minima === 1 ? "opinião" : "caso único" }));
    }
    if (ponto.nao_revisado) li.append(el("span", { class: "marca-evid", text: "documento não revisado" }));
    return li;
  }
  function bloco(titulo, cor, conteudo, classes = "") {
    return el("article", { class: `bloco ${classes}`, style: `--c:${cor}` }, el("h3", { text: titulo }), conteudo);
  }
  const semBase = (t) => el("p", { class: "sem-base", text: t });

  async function montarBriefing(ev) {
    if (ev) ev.preventDefault();
    pintarSegmentosBriefing();
    const seg = $("#b-segmento").value;
    const tipo = $("#b-tipo").value;
    const contexto = $("#b-contexto").value.trim();
    const botao = $("#form-briefing button[type=submit]");
    const saida = $("#briefing-saida");
    if (botao.disabled) return;
    botao.disabled = true;
    saida.replaceChildren(el("p", { class: "contexto-briefing", role: "status", text: "Montando o briefing com o que a base tem…" }));
    let b;
    try {
      b = await chamar("POST", "/briefing", { segmento: seg, tipo_reuniao: tipo, contexto: contexto || null });
    } catch (e) {
      saida.replaceChildren(el("p", { class: "contexto-briefing", role: "alert", text: e.message }));
      return;
    } finally {
      botao.disabled = false;
    }

    saida.replaceChildren();
    const nomeTipo = { diagnostico: "diagnóstico", proposta: "proposta", negociacao: "negociação" }[b.tipo_reuniao];
    saida.append(el("div", { class: "cab-briefing" }, el("h2", { text: `Reunião de ${nomeTipo} · ${capital(b.segmento)}` })));
    if (b.resumo) saida.append(el("p", { class: "contexto-briefing", text: b.resumo }));
    if (b.avisos.length) saida.append(listaAvisos(b.avisos));

    const grade = el("div", { class: "briefing-saida" });
    for (const secao of b.secoes) {
      const [cor, vazioTxt] = SECOES_BRIEFING[secao.chave];
      grade.append(bloco(secao.titulo, cor, secao.pontos.length
        ? el(secao.chave === "roteiro" ? "ol" : "ul", {}, secao.pontos.map((p) => itemLista(p, b.documentos)))
        : semBase(vazioTxt), secao.chave === "roteiro" ? "largo" : ""));
    }
    if (b.lacunas.length) {
      grade.append(bloco("O que a base não cobre", "var(--ambar)", el("ul", {}, b.lacunas.map((l) => el("li", { text: l }))), "lacuna largo"));
    }
    saida.append(grade);
  }

  // ---------------------------------------------------------------- paleta Cmd+K: buscar ou agir
  // Busca nos itens já carregados (a API não tem busca própria de itens) e, ao vivo, nas fontes (GET /fontes?q=).
  // Teclado: setas movem, Enter abre, Cmd+Enter pergunta ao Cérebro, Tab troca o filtro e Esc fecha.
  const paleta = { aberta: false, termo: "", filtro: "tudo", sel: 0, opcoes: [], fontes: [], pedido: 0, espera: null, focoAntes: null };
  const FILTROS_PALETA = [["tudo", "Tudo"], ["itens", "Itens"], ["fontes", "Fontes"], ["acoes", "Ações"]];
  const TELAS_PALETA = [["#hoje", "hoje", "Hoje"], ["#fila", "fila", "Fila"], ["#preparar", "preparar", "Preparar reunião"], ["#fontes", "fontes", "Fontes"]];
  const MAX_ITENS_PALETA = 8;

  // O trecho que bate com o termo vai num <mark> (a comparação ignora acento e maiúscula).
  function marcarTermo(texto, termo) {
    const n = normalizar(termo);
    const plano = [...texto].map((c) => normalizar(c) || c).join("");
    const i = n ? plano.indexOf(n) : -1;
    if (i < 0) return [texto];
    const letras = [...texto];
    return [letras.slice(0, i).join(""), el("mark", { text: letras.slice(i, i + n.length).join("") }), letras.slice(i + n.length).join("")];
  }
  function tecla(t) { return el("span", { class: "tecla", text: t }); }
  function segmentoDoTermo(termo) {
    const n = normalizar(termo.trim());
    return n.length >= 3 ? SEGMENTOS.find((s) => normalizar(s).startsWith(n) || n.includes(normalizar(s))) || null : null;
  }
  function itensDaPaleta(termo) {
    const n = normalizar(termo.trim());
    if (!n) return [];
    const achados = estado.itens.filter((i) => normalizar(`${i.codigo} ${i.titulo}`).includes(n) && i.status !== "obsoleto");
    const comeca = (i) => Number(normalizar(i.titulo).startsWith(n) || normalizar(i.codigo) === n);
    return achados.sort((a, b) => comeca(b) - comeca(a) || (b.evidencia - a.evidencia)).slice(0, MAX_ITENS_PALETA);
  }
  function opcoesDaPaleta() {
    const termo = paleta.termo.trim();
    const grupos = { perguntar: [], itens: [], fontes: [], acoes: [], telas: [] };
    if (termo) {
      grupos.perguntar.push({ mascote: true, titulo: `Perguntar ao Cérebro: “${termo}”`, sub: "Responde com notas da base e dos documentos",
        dir: [tecla("↵")], agir: () => perguntarDaPaleta(termo) });
    }
    for (const it of itensDaPaleta(termo)) {
      grupos.itens.push({ icone: "camadas", titulo: it.titulo, marcar: true,
        sub: `${TIPOS[it.tipo] || it.tipo} · ${NOME_SECAO[it.secao] || it.secao}`,
        dir: [estaNaFila(it) ? el("span", { class: "selo alerta", text: "na Fila" }) : trilha(it.evidencia), el("span", { class: "t-dado suave", text: it.codigo })],
        agir: () => { location.hash = `#item/${it.codigo}`; } });
    }
    for (const f of paleta.fontes) {
      const [rotulo, cor] = STATUS_FONTE[f.status] || [f.status, "mudo"];
      const quando = f.importado_em ? ` · lida em ${dataHora(f.importado_em).split(" ")[0]}` : "";
      grupos.fontes.push({ icone: "doc", titulo: f.titulo, marcar: true,
        sub: `${ORIGEM[f.origem] || f.origem}${f.categoria ? ` · pasta ${f.categoria}` : ""}${quando}`,
        dir: [el("span", { class: `selo ${{ ok: "ok", alerta: "alerta", risco: "risco" }[cor] || ""}`, text: rotulo })],
        agir: () => { const url = linkSeguro(f.url); if (url) window.open(url, "_blank", "noopener"); else location.hash = "#fontes"; } });
    }
    const seg = segmentoDoTermo(termo);
    grupos.acoes.push({ icone: "preparar", titulo: seg ? `Preparar reunião com ${seg}` : "Preparar reunião",
      sub: seg ? "Abre o briefing com o segmento já escolhido" : "Um briefing com a prova de cada ponto",
      agir: () => prepararDaPaleta(seg) });
    grupos.acoes.push({ icone: "registrar", titulo: "Registrar o que aconteceu", sub: "Conta ao curador; o item entra na Fila antes da base",
      agir: () => { novoRegistro(); location.hash = "#registrar"; } });
    const nTermo = normalizar(termo);
    for (const [hash, icon, nome] of TELAS_PALETA) {
      if (hash === "#fontes" && !aoVivo()) continue;
      if (nTermo && !normalizar(nome).includes(nTermo)) continue;
      grupos.telas.push({ icone: icon, titulo: nome, sub: "Abrir a tela", agir: () => { location.hash = hash; } });
    }
    return grupos;
  }
  function pintarPaleta() {
    const g = opcoesDaPaleta();
    const conta = { itens: g.itens.length, fontes: g.fontes.length, acoes: g.acoes.length };
    const blocos = {
      tudo: [["Perguntar", g.perguntar], [`Itens · ${conta.itens}`, g.itens], [`Fontes · ${conta.fontes}`, g.fontes], ["Ações", g.acoes], ["Telas", g.telas]],
      itens: [[`Itens · ${conta.itens}`, g.itens]],
      fontes: [[`Fontes · ${conta.fontes}`, g.fontes]],
      acoes: [["Ações", g.acoes], ["Telas", g.telas]],
    }[paleta.filtro].filter(([, lista]) => lista.length);
    paleta.opcoes = blocos.flatMap(([, lista]) => lista);
    paleta.sel = Math.min(paleta.sel, Math.max(0, paleta.opcoes.length - 1));

    $("#paleta-filtros").replaceChildren(...FILTROS_PALETA.map(([chave, nome]) => {
      const n = chave === "tudo" ? g.perguntar.length + conta.itens + conta.fontes + conta.acoes : conta[chave];
      return el("button", { type: "button", class: "chip", tabindex: "-1", "aria-pressed": String(paleta.filtro === chave),
        onclick: () => { paleta.filtro = chave; paleta.sel = 0; pintarPaleta(); $("#paleta-campo").focus(); } },
      nome, el("span", { class: "t-dado", text: String(n) }));
    }));

    let i = 0;
    const lista = [];
    for (const [titulo, opcoes] of blocos) {
      lista.push(el("p", { class: "t-rotulo ck-grupo", text: titulo, role: "presentation" }));
      for (const op of opcoes) {
        const indice = i++;
        lista.push(el("div", {
          class: `ck-item${indice === paleta.sel ? " sim" : ""}`, id: `paleta-op-${indice}`, role: "option",
          "aria-selected": String(indice === paleta.sel),
          onclick: () => escolherNaPaleta(indice),
          onmousemove: () => { if (paleta.sel !== indice) { paleta.sel = indice; marcarSelecaoPaleta(); } },
        },
        el("span", { class: "caixa" }, op.mascote ? mascoteEm("p", { forma: "simbolo" }) : icone(op.icone, "ic p")),
        el("span", { class: "txt" }, el("b", {}, ...(op.marcar ? marcarTermo(op.titulo, paleta.termo) : [op.titulo])), el("span", { text: op.sub })),
        op.dir ? el("span", { class: "dir" }, ...op.dir) : null));
      }
    }
    const termo = paleta.termo.trim();
    if (termo && !g.itens.length && !g.fontes.length && paleta.filtro !== "acoes") {
      lista.push(el("p", { class: "ck-nada", text: `Nada com «${termo}». Perguntar ao Cérebro?` }));
    }
    $("#paleta-lista").replaceChildren(...lista);
    marcarSelecaoPaleta();
  }
  function marcarSelecaoPaleta() {
    $$("#paleta-lista .ck-item").forEach((o, i) => {
      o.classList.toggle("sim", i === paleta.sel);
      o.setAttribute("aria-selected", String(i === paleta.sel));
    });
    const campo = $("#paleta-campo");
    if (paleta.opcoes.length) {
      campo.setAttribute("aria-activedescendant", `paleta-op-${paleta.sel}`);
      $(`#paleta-op-${paleta.sel}`).scrollIntoView({ block: "nearest" });
    } else {
      campo.removeAttribute("aria-activedescendant");
    }
  }
  function escolherNaPaleta(indice) {
    const op = paleta.opcoes[indice];
    if (!op) return;
    fecharPaleta(false);
    op.agir();
  }
  function perguntarDaPaleta(texto) {
    fecharPaleta(false);
    if (CELULAR.matches) location.hash = "#cerebro";
    else mostrarCerebro();
    perguntar(texto);
  }
  function prepararDaPaleta(seg) {
    pintarSegmentosBriefing();
    if (seg) $("#b-segmento").value = seg;
    if (location.hash === "#preparar") montarBriefing();
    else location.hash = "#preparar";
  }
  function buscarFontesDaPaleta() {
    clearTimeout(paleta.espera);
    paleta.fontes = [];
    const termo = paleta.termo.trim();
    if (!aoVivo() || termo.length < 2) return;  // as fontes só existem com o servidor
    const pedido = ++paleta.pedido;
    paleta.espera = setTimeout(async () => {
      try {
        const r = await chamar("GET", `/fontes?${new URLSearchParams({ q: termo, limit: "5" })}`);
        if (pedido !== paleta.pedido || !paleta.aberta) return;  // só o último pedido vale
        paleta.fontes = r.itens;
        pintarPaleta();
      } catch { /* sem as fontes, a paleta segue com os itens */ }
    }, 250);
  }
  function montarPaleta() {
    const campo = el("input", { id: "paleta-campo", type: "text", autocomplete: "off", spellcheck: "false",
      placeholder: "Buscar um item, uma fonte ou o que fazer", role: "combobox", "aria-expanded": "true",
      "aria-controls": "paleta-lista", "aria-autocomplete": "list", "aria-label": "Buscar ou agir" });
    campo.addEventListener("input", () => {
      paleta.termo = campo.value;
      paleta.sel = 0;
      buscarFontesDaPaleta();
      pintarPaleta();
    });
    campo.addEventListener("keydown", (e) => {
      const n = paleta.opcoes.length;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (n) { paleta.sel = (paleta.sel + (e.key === "ArrowDown" ? 1 : -1) + n) % n; marcarSelecaoPaleta(); }
      } else if (e.key === "Enter") {
        e.preventDefault();
        if ((e.metaKey || e.ctrlKey) && paleta.termo.trim()) perguntarDaPaleta(paleta.termo.trim());
        else escolherNaPaleta(paleta.sel);
      } else if (e.key === "Tab") {  // Tab troca o filtro: o foco fica no campo
        e.preventDefault();
        const i = FILTROS_PALETA.findIndex(([c]) => c === paleta.filtro);
        paleta.filtro = FILTROS_PALETA[(i + (e.shiftKey ? -1 : 1) + FILTROS_PALETA.length) % FILTROS_PALETA.length][0];
        paleta.sel = 0;
        pintarPaleta();
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();  // o Esc fecha só a paleta (não a gaveta nem a navegação que estiverem atrás)
        fecharPaleta();
      }
    });
    const fundo = el("div", { class: "ck-fundo", id: "paleta", hidden: true },
      el("div", { class: "ck", role: "dialog", "aria-modal": "true", "aria-label": "Buscar ou agir" },
        el("div", { class: "ck-entrada" }, icone("busca"), campo, tecla("Esc")),
        el("div", { class: "ck-filtros", id: "paleta-filtros", role: "group", "aria-label": "Filtro" }),
        el("div", { class: "ck-lista", id: "paleta-lista", role: "listbox", "aria-label": "Resultados" }),
        el("div", { class: "ck-pe" },
          el("span", { class: "t-legenda" }, tecla("↑"), tecla("↓"), "navegar"),
          el("span", { class: "t-legenda" }, tecla("↵"), "abrir"),
          el("span", { class: "t-legenda" }, tecla("⌘↵"), "perguntar ao Cérebro"),
          el("span", { class: "t-legenda" }, tecla("Tab"), "filtro"),
          el("span", { class: "t-legenda ck-alcance", id: "paleta-alcance" }))));
    fundo.addEventListener("mousedown", (e) => { if (e.target === fundo) fecharPaleta(); });
    document.body.append(fundo);
  }
  function abrirPaleta(termo = "") {
    if (!$("#paleta")) montarPaleta();
    paleta.focoAntes = paleta.aberta ? paleta.focoAntes : document.activeElement;
    Object.assign(paleta, { aberta: true, termo, filtro: "tudo", sel: 0, fontes: [] });
    fecharNavCelular();
    $("#paleta").hidden = false;
    const campo = $("#paleta-campo");
    campo.value = termo;
    $("#paleta-alcance").textContent = aoVivo()
      ? `Busca nos ${estado.itens.length} itens carregados e nas fontes`
      : "Sem servidor: só as telas e as ações";
    pintarPaleta();
    campo.focus();
  }
  function fecharPaleta(devolverFoco = true) {
    if (!paleta.aberta) return false;
    paleta.aberta = false;
    clearTimeout(paleta.espera);
    $("#paleta").hidden = true;
    if (devolverFoco && paleta.focoAntes && document.contains(paleta.focoAntes)) paleta.focoAntes.focus();
    return true;
  }

  // ---------------------------------------------------------------- eventos e início
  function ligarCampo(campoMsg, formulario) {
    campoMsg.addEventListener("input", () => autoAltura(campoMsg));
    campoMsg.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); formulario.requestSubmit(); }
    });
  }
  function ligarEventos() {
    window.addEventListener("hashchange", rotear);
    $("#entrada-botao").addEventListener("click", () => {
      $("#entrada-botao").setAttribute("aria-busy", "true");
      const rascunho = $("#campo-chat").value.trim();  // a ida ao Google recarrega a página: o texto espera na volta
      if (rascunho) guardar.escrever("cerebro.rascunho-chat", rascunho);
    });

    const formChat = $("#form-chat");
    ligarCampo($("#campo-chat"), formChat);
    formChat.addEventListener("submit", (e) => { e.preventDefault(); perguntar($("#campo-chat").value); });


    $("#form-briefing").addEventListener("submit", montarBriefing);
    $("#nova-conversa").addEventListener("click", () => {
      if (!estado.ocupado) iniciarConversa();  // "Nova conversa" limpa também o que ficou guardado neste navegador
      $("#campo-chat").focus();
    });
    $("#campo-chat").addEventListener("input", atualizarContadorMsg);
    document.addEventListener("keydown", teclasDaFila);
    const anexar = $("#anexar");
    const arquivo = $("#arquivo-anexo");
    anexar.addEventListener("click", () => arquivo.click());
    arquivo.addEventListener("change", () => {
      const escolhido = arquivo.files && arquivo.files[0];
      arquivo.value = "";
      if (escolhido) enviarArquivo(escolhido);
    });

    // A barra lateral recolhe num trilho só de ícones; o navegador lembra a escolha (se o localStorage deixar).
    const app = $("#app");
    const recolher = $("#recolher-barra");
    const aplicarBarra = (recolhida) => {
      app.classList.toggle("barra-recolhida", recolhida);
      recolher.setAttribute("aria-expanded", String(!recolhida));
      recolher.setAttribute("aria-label", recolhida ? "Abrir a barra lateral" : "Recolher a barra lateral");
      recolher.title = recolher.getAttribute("aria-label");
    };
    aplicarBarra(guardar.ler("cerebro.barra") === "recolhida");

    // A gaveta do Cérebro (de 861 a 1279 px): o botão no topo do centro ou Cmd+J; Esc e o fundo fecham.
    $("#abrir-cerebro").addEventListener("click", abrirGavetaCerebro);
    $("#trilho-cerebro").addEventListener("click", abrirGavetaCerebro);
    $("#fechar-cerebro").addEventListener("click", fecharGavetaCerebro);
    $("#fundo-cerebro").addEventListener("click", fecharGavetaCerebro);
    $("#nav-mascote").addEventListener("click", () => { if (!fecharNavCelular()) abrirNavCelular(); });
    document.addEventListener("click", (e) => {
      if (!$("#nav-celular").hidden && !e.target.closest("#nav-celular, #nav-mascote")) fecharNavCelular();
    });
    $("#abrir-busca").addEventListener("click", () => abrirPaleta());
    $("#abrir-busca-celular").addEventListener("click", () => abrirPaleta());
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {  // a paleta: buscar ou agir
        e.preventDefault();
        if (!fecharPaleta()) abrirPaleta();
        return;
      }
      if (paleta.aberta) return;  // com a paleta aberta, o teclado é dela
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        if ((ehGaveta() || trilhoDaFila()) && fecharGavetaCerebro()) return;
        mostrarCerebro();
        return;
      }
      if (e.key === "Escape") esconderPrevia();
      if (e.key === "Escape" && (fecharNavCelular() || fecharGavetaCerebro())) e.preventDefault();
    });
    ESTREITO.addEventListener?.("change", () => { if (!ehGaveta()) fecharGavetaCerebro(); });
    recolher.addEventListener("click", () => {
      const recolhida = !app.classList.contains("barra-recolhida");
      aplicarBarra(recolhida);
      guardar.escrever("cerebro.barra", recolhida ? "recolhida" : "aberta");
    });
  }

  async function iniciar() {
    seguro(pintarMascotes, "mascote");
    ligarEventos();
    seguro(lerAbas, "abas");
    estado.modo = await detectarModo();
    pintarModo();
    if (!aoVivo()) {  // nada de dado inventado: sem servidor a tela só avisa
      atualizarNumeros();
      aviso("Não consegui falar com o servidor. Confira a internet e tente de novo.", "erro");
      rotear();
      return;
    }
    if (!(await verificarLogin())) return;  // sem sessão: a tela de entrada fica; o Google devolve para cá
    const rascunho = guardar.ler("cerebro.rascunho-chat");
    if (rascunho) { $("#campo-chat").value = rascunho; guardar.escrever("cerebro.rascunho-chat", ""); }
    await carregarItens();
    atualizarNumeros();
    iniciarConversa({ restaurar: true });
    atualizarContadorMsg();
    rotear();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
