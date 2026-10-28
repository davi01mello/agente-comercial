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
  const hora = () => new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const dataBr = (iso) => (iso ? iso.split("-").reverse().join("/") : "");

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
    reg: { conversa: [], proposta: null, ocupado: false },
    filtro: { secao: null, segmento: null, busca: "", historico: false, origem: null, mostrar: {} },
    fontes: null,  // o resumo de GET /fontes/resumo
    filtroFontes: { status: null, busca: "", origem: null },
    sync: { id: null, dry: false, exec: null, acompanhando: false, teto: 1, origem: "notion" },
    fila: { origem: null, selecionados: new Set(), mostrar: 30, confirmando: false, aprovando: null, visiveis: [] },
    focoAntes: null,
    pessoa: null,  // quem entrou (GET /auth/eu): {email, nome, dev, dominio}; null enquanto não entrou
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
    if (typeof det === "string") return det;
    if (Array.isArray(det)) return det.map((e) => `${(e.loc || []).slice(1).join(".") || "campo"}: ${e.msg}`).join(" · ");
    if (status === 404 || status === 405) return "Esta ação ainda não existe no servidor.";
    return `O servidor respondeu com erro ${status}.`;
  }
  async function chamar(metodo, url, corpo) {
    let r;
    try {
      r = await fetch(url, {
        method: metodo,
        headers: corpo ? { "Content-Type": "application/json" } : {},
        body: corpo ? JSON.stringify(corpo) : undefined,
      });
    } catch {
      throw new ErroApi("Não consegui falar com o servidor. Confira se o uvicorn está rodando.", 0);
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
    caixa.replaceChildren(
      el("span", { class: "voce-nome", title: p.email, text: p.nome }),
      p.dev
        ? el("span", { class: "voce-dev", title: "O login do Google está desligado neste computador (sem GOOGLE_CLIENT_ID no .env)." }, "sem login")
        : el("button", { type: "button", class: "btn fantasma voce-sair", onclick: sairDoApp }, "Sair"));
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
    } catch (e) {
      aviso(`Não consegui carregar os itens: ${e.message}`, "erro");
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
  function sinal(n) {
    const s = el("span", { class: "sinal", role: "img", "aria-label": `Evidência ${n} de 4: ${EVIDENCIA[n]}` });
    for (let i = 1; i <= 4; i++) s.append(el("i", { class: i <= n ? "on" : "" }));
    return s;
  }
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
    return el("div", { class: "vazio" }, mascoteEm("m mascote-vazio"), el("h3", { text: titulo }), el("p", { text: texto }), ...extra);
  }
  function autoAltura(t) {
    t.style.height = "auto";
    t.style.height = `${Math.min(t.scrollHeight, 150)}px`;
  }

  // Texto do modelo -> parágrafos, listas, negrito e citações clicáveis (sem HTML do modelo).
  function inline(txt, docs) {
    const partes = [];
    const re = /\[((?:EX|INS)-\d+)\]|\[(DOC-\d+)\]|\*\*([^*]+)\*\*/g;
    let i = 0, m;
    while ((m = re.exec(txt))) {
      if (m.index > i) partes.push(document.createTextNode(txt.slice(i, m.index)));
      if (m[1]) partes.push(chipCitacao(m[1]));
      else if (m[2]) partes.push(chipDocumento(m[2], docs));
      else partes.push(el("strong", { text: m[3] }));
      i = re.lastIndex;
    }
    if (i < txt.length) partes.push(document.createTextNode(txt.slice(i)));
    return partes;
  }
  function formatar(texto, docs) {
    const frag = document.createDocumentFragment();
    for (const bloco of String(texto).trim().split(/\n{2,}/)) {
      const linhas = bloco.split("\n").filter((l) => l.trim());
      if (!linhas.length) continue;
      if (linhas.every((l) => /^\s*[-*•]\s+/.test(l))) {
        frag.append(el("ul", {}, linhas.map((l) => el("li", {}, inline(l.replace(/^\s*[-*•]\s+/, ""), docs)))));
      } else if (linhas.every((l) => /^\s*\d+[.)]\s+/.test(l))) {
        frag.append(el("ol", {}, linhas.map((l) => el("li", {}, inline(l.replace(/^\s*\d+[.)]\s+/, ""), docs)))));
      } else {
        const p = el("p");
        linhas.forEach((l, i) => { if (i) p.append(el("br")); p.append(...inline(l, docs)); });
        frag.append(p);
      }
    }
    return frag;
  }
  function chipCitacao(codigo) {
    const item = acharItem(codigo);
    return el("button", { type: "button", class: "cita", title: item ? item.titulo : "Abrir item", onclick: () => abrirItem(codigo) }, codigo);
  }

  // [DOC-n]: um documento do Drive que o consultor leu mas o time ainda não revisou. Abre o documento no Drive.
  // Só vira link se o servidor mandou esse documento junto com a resposta (o modelo não inventa um destino).
  function chipDocumento(codigo, docs) {
    const doc = (docs || []).find((d) => `DOC-${d.id}` === codigo);
    const url = doc ? linkSeguro(doc.url) : null;
    if (!url) return document.createTextNode(`[${codigo}]`);
    return el("a", {
      class: "cita doc", href: url, target: "_blank", rel: "noopener noreferrer",
      title: `Documento do Drive ainda não revisado: ${doc.titulo}${doc.categoria ? ` (${doc.categoria})` : ""}`,
    }, codigo);
  }
  // Rodapé da resposta com os documentos que ela cita: o aviso de que não passaram pela revisão do time.
  function rodapeDocumentos(texto, docs) {
    const citados = (docs || []).filter((d) => texto.includes(`[DOC-${d.id}]`) && linkSeguro(d.url));
    if (!citados.length) return null;
    return el("div", { class: "docs-citados" },
      el("p", { class: "nota", text: "Documentos do Drive, ainda não revisados pelo time:" }),
      el("ul", {}, citados.map((d) => el("li", {},
        el("a", { href: d.url, target: "_blank", rel: "noopener noreferrer", text: d.titulo }),
        d.categoria ? el("span", { class: "pasta-doc", text: ` · ${d.categoria}` }) : null))));
  }

  function adicionarMsg(caixa, { papel, texto, quem, nota, extra, docs }) {
    const linha = el("div", { class: `linha${papel === "eu" ? " eu" : ""}` });
    if (papel !== "eu") linha.append(mascoteEm("p av", { forma: "simbolo" }));
    const bolha = el("div", { class: `msg ${papel}` }, el("span", { class: "quem", text: quem }), formatar(texto, docs));
    if (extra) bolha.append(extra);
    const citados = rodapeDocumentos(texto, docs);
    if (citados) bolha.append(citados);
    if (nota) bolha.append(el("p", { class: "nota", text: nota }));
    bolha.append(el("span", { class: "hora", text: hora() }));
    linha.append(bolha);
    caixa.append(linha);
    caixa.scrollTop = caixa.scrollHeight;
    return linha;
  }
  function digitando(caixa) {
    const linha = el("div", { class: "linha" }, mascoteEm("p av", { forma: "simbolo" }),
      el("div", { class: "msg cerebro digitando", role: "status", "aria-label": "Pensando" }, el("i"), el("i"), el("i")));
    caixa.append(linha);
    caixa.scrollTop = caixa.scrollHeight;
    return linha;
  }
  function pensando(sim) { document.body.classList.toggle("pensando", sim); }

  // ---------------------------------------------------------------- topo e navegação
  const TOPO = {
    registrar: ["Registrar", "Conte o que aconteceu. O curador organiza, e você revisa antes de mandar para a Fila."],
    fila: ["Fila de curadoria", "Itens propostos e itens vindos de fontes antigas esperando aprovação. Nada entra no playbook sem alguém aprovar."],
    fontes: ["Fontes", "O que o Cérebro leu do Notion e do Drive e o que virou item. Nada daqui entra no playbook sem passar pela Fila."],
    playbook: ["Playbook", "O que o time já validou, na ordem do funil."],
    briefing: ["Briefing de reunião", "Um roteiro montado só com o que está na base, cada ponto com a fonte."],
  };
  function pintarTopo(tela) {
    const box = $("#ident");
    box.replaceChildren();
    if (tela === "conversar") {
      box.append(mascoteEm("m av-topo", { forma: "simbolo" }), el("div", {},
        el("h1", { text: "Cérebro" }),
        el("p", {}, el("span", { class: "online", text: "Online" }), " · consultor comercial do CITi")));
    } else {
      const [t, s] = TOPO[tela];
      box.append(el("div", {}, el("h1", { text: t }), el("p", { text: s })));
    }
  }
  const TELAS = ["conversar", "registrar", "fila", "fontes", "playbook", "briefing"];
  function rotear() {
    const alvo = (location.hash || "#conversar").slice(1);
    const tela = TELAS.includes(alvo) ? alvo : "conversar";
    for (const s of $$(".tela")) s.hidden = s.dataset.tela !== tela;
    for (const a of $$(".nav a")) {
      if (a.dataset.tela === tela) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
    estado.tela = tela;
    pintarTopo(tela);
    if (tela === "fila") pintarFila();
    if (tela === "fontes") pintarFontes();
    if (tela === "playbook") pintarPlaybook();
    if (tela === "briefing") montarBriefing();
  }
  // Na Fila: o que as pessoas registraram (proposto) e o que veio de fontes antigas, ainda sem revisão (histórico a validar)
  function estaNaFila(i) { return i.status === "proposto" || i.status === "historico_a_validar"; }
  function atualizarNumeros() {
    const noPlaybook = estado.itens.filter((i) => i.status === "validado" || i.status === "consolidado").length;
    const naFila = estado.itens.filter(estaNaFila).length;
    const hipoteses = estado.itens.filter((i) => i.tipo === "hipotese" && i.status !== "obsoleto").length;
    $("#n-playbook").textContent = noPlaybook;
    $("#n-fila").textContent = naFila;
    $("#n-hipoteses").textContent = hipoteses;
    const contador = $("#contador-fila");
    contador.textContent = naFila;
    contador.hidden = naFila === 0;
    $("#n-fontes").textContent = estado.fontes ? estado.fontes.total : 0;
    $("#rodape-base").textContent = aoVivo()
      ? "Ligado ao servidor. O consultor responde só com os itens aprovados no Playbook."
      : "Sem conexão com o servidor. Rode o app com o uvicorn.";
  }
  function pintarModo() {
    const m = $("#modo");
    m.dataset.modo = estado.modo;
    m.textContent = aoVivo() ? "Ao vivo" : "Sem servidor";
  }

  // ---------------------------------------------------------------- conversar
  const ATALHOS_CHAT = [
    ["Cliente disse que está caro", "O cliente disse que está caro. Como respondemos?", "var(--ambar)"],
    ["Testar hipótese: eventos ou LinkedIn", "Pensei em prospectar em eventos do setor em vez de LinkedIn. O que você acha?", "var(--lilas)"],
    ["O que a base não cobre?", "O que a base ainda não cobre?", "var(--risco)"],
  ];
  async function perguntar(texto) {
    texto = texto.trim();
    if (!texto || estado.ocupado) return;
    const caixa = $("#mensagens");
    const campo = $("#campo-chat");
    adicionarMsg(caixa, { papel: "eu", texto, quem: nomeDoUsuario() });
    campo.value = ""; autoAltura(campo);
    estado.ocupado = true; $("#enviar-chat").disabled = true; pensando(true);
    const indicador = digitando(caixa);
    try {
      const r = await chamar("POST", "/chat", { mensagem: texto, historico: estado.conversa.slice(-30) });
      const resposta = r.resposta;
      indicador.remove();
      adicionarMsg(caixa, { papel: "cerebro", texto: resposta, quem: "Cérebro", docs: r.documentos || [] });
      estado.conversa.push({ role: "user", text: texto }, { role: "model", text: resposta });
      pulsarMascote();
    } catch (e) {
      indicador.remove();
      adicionarMsg(caixa, { papel: "erro", texto: e.message, quem: "Não deu certo" });
    } finally {
      estado.ocupado = false; $("#enviar-chat").disabled = false; pensando(false);
      campo.focus();
    }
  }
  function iniciarConversa() {
    const caixa = $("#mensagens");
    caixa.replaceChildren();
    estado.conversa = [];
    const exemplo = estado.itens.find((i) => i.status === "validado" || i.status === "consolidado");
    const toque = exemplo
      ? `Toque numa fonte, como [${exemplo.codigo}], para ver o item inteiro.`
      : "Quando houver itens aprovados, toque numa fonte para ver o item inteiro.";
    adicionarMsg(caixa, {
      papel: "cerebro", quem: "Cérebro",
      texto: `Oi! Eu respondo com base no que o time aprovou e mostro de onde tirei cada ponto. ${toque}`,
    });
  }

  // ---------------------------------------------------------------- registrar (curador)
  function boasVindasRegistro() {
    const caixa = $("#mensagens-reg");
    caixa.replaceChildren();
    adicionarMsg(caixa, {
      papel: "cerebro", quem: "Curador",
      texto: "Me conta o que aconteceu, do jeito que você contaria para um colega. Eu organizo em um item, aponto o que faltou e você revisa antes de ir para a Fila.",
    });
  }
  async function relatar(texto) {
    texto = texto.trim();
    if (!texto || estado.reg.ocupado) return;
    const autor = exigirAutor();
    if (!autor) return;
    const caixa = $("#mensagens-reg");
    const campo = $("#campo-reg");
    adicionarMsg(caixa, { papel: "eu", texto, quem: autor });
    campo.value = ""; autoAltura(campo);
    estado.reg.ocupado = true; $("#enviar-reg").disabled = true; pensando(true);
    const indicador = digitando(caixa);
    try {
      const proposta = await chamar("POST", "/registrar/propor", { texto, conversa: estado.reg.conversa.slice(-10) });
      indicador.remove();
      const perguntas = proposta.perguntas || [];
      const resumo = perguntas.length
        ? `Já montei um rascunho ao lado. Antes de fechar, ${perguntas.length === 1 ? "uma pergunta" : "duas perguntas"}:`
        : "Pronto. O rascunho está ao lado: revise, ajuste o que quiser e envie para a Fila.";
      const extra = perguntas.length ? el("ol", { class: "lista-perguntas" }, perguntas.map((p) => el("li", { text: p }))) : null;
      adicionarMsg(caixa, { papel: "cerebro", quem: "Curador", texto: resumo, extra });
      estado.reg.conversa.push({ role: "user", text: texto }, { role: "model", text: perguntas.length ? perguntas.join("\n") : resumo });
      estado.reg.proposta = proposta;
      pintarRascunho();
      pulsarMascote();
    } catch (e) {
      indicador.remove();
      adicionarMsg(caixa, { papel: "erro", texto: e.message, quem: "Não deu certo" });
    } finally {
      estado.reg.ocupado = false; $("#enviar-reg").disabled = false; pensando(false);
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
  function pintarRascunho() {
    const f = $("#rascunho");
    f.replaceChildren();
    const p = estado.reg.proposta;
    if (!p) {
      f.append(vazio("O rascunho aparece aqui",
        "Conte o que aconteceu no campo ao lado. O curador preenche tipo, seção, segmento e evidência, e você ajusta antes de enviar para a Fila."));
      return;
    }
    const it = p.insight;
    const valor = (v) => (v == null ? "" : v);
    const titulo = el("input", { class: "titulo-campo", maxlength: "200", value: valor(it.titulo) });
    const escala = el("div", { class: "escala", role: "radiogroup", "aria-label": "Evidência" });
    for (const n of [1, 2, 3, 4]) {
      const id = `r-evid-${n}`;
      const radio = el("input", { type: "radio", name: "r-evidencia", id, value: String(n) });
      radio.checked = Number(it.evidencia) === n;
      escala.append(radio, el("label", { for: id, style: `--n:${n}` }, el("b", { text: String(n) }), EVIDENCIA[n]));
    }
    const segmento = el("input", { list: "lista-segmentos", maxlength: "100", value: valor(it.segmento), placeholder: "Todos os segmentos" });
    const lista = el("datalist", { id: "lista-segmentos" }, SEGMENTOS.map((s) => el("option", { value: s })));
    const area = (v, linhas = 3, limite = 4000) => { const a = el("textarea", { rows: String(linhas), maxlength: String(limite) }); a.value = valor(v); return a; };

    const relacoes = el("div", { class: "relacoes" });
    const pintarRelacoes = () => {
      relacoes.replaceChildren();
      if (!p.relacoes.length) relacoes.append(el("span", { class: "evid", text: "Nenhuma relação com itens que já existem." }));
      p.relacoes.forEach((r, i) => relacoes.append(relacaoChip(r, null, () => { p.relacoes.splice(i, 1); pintarRelacoes(); })));
    };
    p.relacoes = p.relacoes || [];
    pintarRelacoes();

    f.append(
      el("div", { class: "rascunho-topo" },
        el("span", { class: "carimbo", text: "Rascunho · nada foi gravado" }),
        el("span", { class: "evid" }, "Vai para a Fila como ", el("strong", { text: "proposto" }))),
      el("div", { class: "campos" },
        campo("Título", "r-titulo", titulo, true),
        campo("Tipo", "r-tipo", selecionar(Object.entries(TIPOS), it.tipo)),
        campo("Seção", "r-secao", selecionar(SECOES, it.secao)),
        el("div", { class: "campo inteiro" }, el("span", { class: "rotulo", id: "rotulo-evid", text: "Evidência" }), escala),
        campo("Segmento", "r-segmento", segmento),
        campo("Data do acontecido", "r-data", el("input", { type: "date", value: valor(it.data_evento) })),
        campo("Descrição", "r-descricao", area(it.descricao, 4), true),
        campo("O que foi feito", "r-feito", area(it.o_que_foi_feito, 2), true),
        campo("Resultado", "r-resultado", area(it.resultado, 2, 2000), true),
        campo("Contexto do cliente (sem dado pessoal)", "r-contexto", area(it.contexto_cliente, 2, 2000), true),
        el("div", { class: "campo inteiro" }, el("span", { class: "rotulo", text: "Relações" }), relacoes)),
      lista,
    );
    if (p.avisos && p.avisos.length) f.append(el("div", { class: "campo" }, el("span", { class: "rotulo", text: "Para o revisor" }), listaAvisos(p.avisos)));
    f.append(el("div", { class: "botoes" },
      el("button", { type: "submit", class: "btn primario", id: "enviar-fila" }, "Enviar para a Fila"),
      el("button", { type: "button", class: "btn fantasma", onclick: descartarRascunho }, "Descartar")));
  }
  function lerRascunho() {
    const v = (id) => { const x = $(`#${id}`).value.trim(); return x === "" ? null : x; };
    const marcado = $("input[name='r-evidencia']:checked");
    return {
      titulo: v("r-titulo"), tipo: v("r-tipo"), secao: v("r-secao"),
      descricao: v("r-descricao"), segmento: v("r-segmento"),
      o_que_foi_feito: v("r-feito"), resultado: v("r-resultado"), contexto_cliente: v("r-contexto"),
      data_evento: v("r-data"), evidencia: marcado ? Number(marcado.value) : 1,
      relacoes: (estado.reg.proposta.relacoes || []).map((r) => ({ relacionado_id: r.relacionado_id, tipo: r.tipo })),
    };
  }
  function descartarRascunho() {
    estado.reg = { conversa: [], proposta: null, ocupado: false };
    boasVindasRegistro();
    pintarRascunho();
  }
  async function enviarParaFila(ev) {
    ev.preventDefault();
    if (!estado.reg.proposta) return;
    const autor = exigirAutor();
    if (!autor) return;
    const dados = lerRascunho();
    if (!dados.titulo || !dados.descricao) { aviso("Preencha título e descrição antes de enviar.", "erro"); return; }
    if (dados.tipo === "regra" && dados.evidencia < 3) { aviso("Para virar regra, a evidência precisa ser 3 ou 4.", "erro"); return; }
    if (dados.evidencia === 4 && !/\d/.test(dados.resultado || "")) { aviso("Evidência 4 exige um número no campo Resultado.", "erro"); return; }
    const botao = $("#enviar-fila");
    botao.disabled = true;
    try {
      const criado = await chamar("POST", "/insights", { ...dados, fonte: "chat" });
      await carregarItens();
      aviso(`Enviado para a Fila como proposto (INS-${criado.id}).`, "ok");
      pulsarMascote();
      descartarRascunho();
      atualizarNumeros();
    } catch (e) {
      aviso(e.message, "erro");
      botao.disabled = false;
    }
  }

  // ---------------------------------------------------------------- fila
  const ORIGEM_ITEM = { chat: "Chat", notion: "Notion", drive: "Drive", canva: "Canva", reuniao: "Reunião" };
  const POR_PAGINA_FILA = 30;
  let barraLote = null;

  function pintarFila() {
    const box = $("#lista-fila");
    box.replaceChildren();
    const f = estado.fila;
    const itens = estado.itens.filter(estaNaFila);
    for (const id of [...f.selecionados]) if (!itens.some((i) => i.id === id)) f.selecionados.delete(id);  // já decididos
    if (!itens.length) {
      box.append(el("div", { class: "painel vidro" }, vazio("A Fila está vazia",
        "Quando alguém registrar um insight, ele aparece aqui para ser aprovado ou rejeitado.",
        el("a", { class: "btn primario", href: "#registrar", text: "Registrar um insight" }))));
      return;
    }
    const origens = [...new Set(itens.map((i) => i.fonte))];
    if (f.origem && !origens.includes(f.origem)) f.origem = null;
    const visiveis = itens.filter((i) => !f.origem || i.fonte === f.origem);
    f.visiveis = visiveis;

    box.append(el("p", { class: "resumo-lista", text: `${itens.length} ${itens.length === 1 ? "item esperando" : "itens esperando"} revisão` }));
    if (origens.length > 1) {
      box.append(el("div", { class: "filtros" },
        chip(`Todas (${itens.length})`, !f.origem, () => { f.origem = null; f.mostrar = POR_PAGINA_FILA; pintarFila(); }),
        ...origens.map((o) => chip(`${ORIGEM_ITEM[o] || o} (${itens.filter((i) => i.fonte === o).length})`, f.origem === o,
          () => { f.origem = f.origem === o ? null : o; f.mostrar = POR_PAGINA_FILA; pintarFila(); }))));
    }
    barraLote = el("div", { class: "barra-lote vidro", role: "region", "aria-label": "Aprovar vários de uma vez" });
    box.append(barraLote);
    atualizarBarraLote();

    for (const it of visiveis.slice(0, f.mostrar)) box.append(cartaoFila(it));
    if (visiveis.length > f.mostrar) {
      box.append(el("button", { type: "button", class: "btn fantasma",
        onclick: () => { f.mostrar += POR_PAGINA_FILA; pintarFila(); } },
        `Mostrar mais ${Math.min(POR_PAGINA_FILA, visiveis.length - f.mostrar)} (restam ${visiveis.length - f.mostrar})`));
    }
  }
  function atualizarBarraLote() {
    if (!barraLote) return;
    const f = estado.fila;
    const n = f.selecionados.size;
    const todosMarcados = f.visiveis.length > 0 && f.visiveis.every((i) => f.selecionados.has(i.id));
    if (f.aprovando) {
      barraLote.replaceChildren(el("span", { class: "lote-info", role: "status",
        text: `Aprovando ${f.aprovando.feitos} de ${f.aprovando.total}…` }));
      return;
    }
    barraLote.replaceChildren(...[  // replaceChildren(null) escreveria o texto "null": só entra o que existe
      el("button", { type: "button", class: "btn fantasma",
        onclick: () => {
          if (todosMarcados) for (const i of f.visiveis) f.selecionados.delete(i.id);
          else for (const i of f.visiveis) f.selecionados.add(i.id);
          f.confirmando = false;
          for (const c of $$("#lista-fila .sel input")) c.checked = f.selecionados.has(Number(c.dataset.id));
          for (const c of $$("#lista-fila .item")) c.classList.toggle("selecionado", f.selecionados.has(Number(c.dataset.id)));
          atualizarBarraLote();
        } }, todosMarcados ? "Desmarcar todos" : `Selecionar todos (${f.visiveis.length})`),
      el("span", { class: "lote-info", text: n ? `${n} ${n === 1 ? "selecionado" : "selecionados"}` : "Marque os itens que quer aprovar de uma vez" }),
      n && !f.confirmando
        ? el("button", { type: "button", class: "btn primario",
            onclick: () => { f.confirmando = true; atualizarBarraLote(); } }, n === 1 ? "Aprovar o item selecionado" : `Aprovar ${n} selecionados`)
        : null,
      n && f.confirmando
        ? el("button", { type: "button", class: "btn primario", onclick: aprovarSelecionados },
            `Confirmar: aprovar ${n} sem ler um a um`)
        : null,
      n && f.confirmando
        ? el("button", { type: "button", class: "btn fantasma",
            onclick: () => { f.confirmando = false; atualizarBarraLote(); } }, "Cancelar")
        : null].filter(Boolean));
  }
  async function aprovarSelecionados() {
    const autor = exigirAutor();
    if (!autor) return;
    const f = estado.fila;
    const ids = [...f.selecionados];
    f.confirmando = false;
    f.aprovando = { feitos: 0, total: ids.length };
    atualizarBarraLote();
    let aprovados = 0;
    const falhas = [];
    let semServidor = false;
    for (const id of ids) {
      try {
        await chamar("POST", `/insights/${id}/aprovar`);
        aprovados += 1;
        f.selecionados.delete(id);
      } catch (e) {
        falhas.push(`INS-${id}`);
        if (e.status === 0) { semServidor = true; break; }  // sem servidor: não adianta tentar os outros
      }
      f.aprovando.feitos += 1;
      atualizarBarraLote();
    }
    f.aprovando = null;
    await carregarItens();
    if (aprovados) { pulsarMascote(); }
    const restantes = semServidor ? ids.length - aprovados : falhas.length;
    aviso(restantes
      ? `${aprovados} aprovados. ${restantes} não foram aprovados${semServidor ? " (o servidor parou de responder)" : `: ${falhas.slice(0, 5).join(", ")}${falhas.length > 5 ? "…" : ""}`}. Continuam marcados.`
      : `${aprovados} ${aprovados === 1 ? "item aprovado" : "itens aprovados"}. Já aparecem no Playbook.`, restantes ? "erro" : "ok");
    atualizarNumeros();
    pintarFila();
  }
  function cartaoFila(it) {
    const idMotivo = `motivo-${it.id}`;
    const motivo = el("div", { class: "motivo", hidden: true },
      el("label", { class: "rotulo", for: idMotivo, text: "Motivo da rejeição" }),
      el("textarea", { id: idMotivo, rows: "2", maxlength: "1000", placeholder: "Ex.: duplica outro item e não traz nada novo" }),
      el("div", { class: "botoes" },
        el("button", { type: "button", class: "btn perigo", onclick: () => decidir(it, "rejeitar", $(`#${idMotivo}`).value) }, "Confirmar rejeição"),
        el("button", { type: "button", class: "btn fantasma", onclick: () => { motivo.hidden = true; } }, "Cancelar")));
    const marcado = estado.fila.selecionados.has(it.id);
    const caixa = el("input", { type: "checkbox", "data-id": String(it.id), checked: marcado ? "" : null,
      "aria-label": `Selecionar ${it.codigo}: ${it.titulo}` });
    caixa.addEventListener("change", () => {
      const f = estado.fila;
      if (caixa.checked) f.selecionados.add(it.id); else f.selecionados.delete(it.id);
      f.confirmando = false;
      card.classList.toggle("selecionado", caixa.checked);
      atualizarBarraLote();
    });
    const card = el("article", { class: marcado ? "item vidro selecionado" : "item vidro", "data-id": String(it.id) },
      el("label", { class: "sel" }, caixa, el("span", { text: "Selecionar" })),
      metaItem(it),
      el("h3", { text: it.titulo }),
      el("p", { class: "desc", text: it.descricao }),
      el("div", { class: "linha-evid" },
        el("span", { class: "evid" }, sinal(it.evidencia), `Evidência ${it.evidencia} · ${EVIDENCIA[it.evidencia]}`),
        el("span", { text: [it.autor, dataBr(it.data_evento), it.codigo].filter(Boolean).join(" · ") }),
        linkOrigem(it)));
    if (it.relacoes && it.relacoes.length) card.append(el("div", { class: "relacoes" }, it.relacoes.map((r) => relacaoChip(r, it))));
    const avs = avisosDeEvidencia(it);
    if (avs.length) card.append(listaAvisos(avs));
    card.append(
      el("div", { class: "botoes" },
        el("button", { type: "button", class: "btn primario", onclick: () => decidir(it, "aprovar") }, "Aprovar"),
        el("button", { type: "button", class: "btn perigo", onclick: () => { motivo.hidden = false; $(`#${idMotivo}`).focus(); } }, "Rejeitar"),
        el("button", { type: "button", class: "btn fantasma", onclick: () => abrirItem(it.codigo) }, "Ver detalhes")),
      motivo);
    return card;
  }
  async function decidir(it, acao, motivo) {
    const autor = exigirAutor();
    if (!autor) return;
    if (acao === "rejeitar" && !(motivo && motivo.trim())) { aviso("Para rejeitar, escreva o motivo.", "erro"); return; }
    try {
      await chamar("POST", `/insights/${it.id}/${acao}`, acao === "aprovar" ? undefined : { motivo: motivo.trim() });
      await carregarItens();
      aviso(acao === "aprovar" ? `${it.codigo} aprovado. Já aparece no Playbook.` : `${it.codigo} rejeitado e marcado como obsoleto.`, "ok");
      pulsarMascote();
      atualizarNumeros();
      pintarFila();
    } catch (e) {
      if (e.status === 404 || e.status === 405) aviso("Aprovar e rejeitar chegam na PR 3 do Rafael. Por enquanto o item continua na Fila.", "erro");
      else aviso(e.message, "erro");
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

  function linkSeguro(url) { return typeof url === "string" && /^https:\/\//.test(url) ? url : null; }
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
    return el("div", { class: "cartao-numero vidro", style: cor ? `--c:${cor}` : null },
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
    return el("article", { class: "item fonte vidro" },
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
    return el("div", { class: "painel vidro passo-a-passo" },
      vazio("Nada lido ainda", "Quando o Cérebro ler o Notion ou o Drive, cada página ou documento aparece aqui, com o que aconteceu com ele."),
      el("ol", {},
        el("li", {}, "No .env do servidor, preencha ", el("code", { text: "NOTION_TOKEN" }), " (Notion: a integração só enxerga as páginas compartilhadas com ela) ou ",
          el("code", { text: "DRIVE_PASTA_ID" }), " e a credencial do Google (Drive: a pasta precisa estar compartilhada com a conta de serviço)."),
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
    painelSync = el("div", { class: "painel vidro sync", "aria-label": "Sincronizar o Notion ou o Drive" });
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
      if (!total) linhas.replaceChildren(el("div", { class: "painel vidro" }, vazio("Nada com esse filtro", "Tire o filtro ou mude a busca.")));
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
  function pintarPlaybook() {
    const todos = itensDoPlaybook();
    const funil = $("#funil");
    funil.replaceChildren();
    SECOES.forEach(([chave, nome], i) => {
      if (i) funil.append(el("span", { class: "fio", "aria-hidden": "true" }));
      const n = todos.filter((x) => x.secao === chave).length;
      funil.append(el("button", {
        type: "button", class: `etapa${n ? " cheia" : ""}`, "aria-pressed": String(estado.filtro.secao === chave),
        "aria-label": `${nome}: ${n} ${n === 1 ? "item" : "itens"}`,
        onclick: () => { estado.filtro.secao = estado.filtro.secao === chave ? null : chave; estado.filtro.mostrar = {}; pintarPlaybook(); },
      }, el("span", { class: "no", text: String(n) }), el("span", { text: nome })));
    });

    const filtros = $("#filtros");
    filtros.replaceChildren();
    const busca = el("input", { type: "search", id: "busca-playbook", class: "busca", placeholder: "Buscar no playbook", "aria-label": "Buscar no playbook" });
    busca.value = estado.filtro.busca;
    busca.addEventListener("input", () => { estado.filtro.busca = busca.value; estado.filtro.mostrar = {}; pintarGrupos(); });
    const refiltrar = (mudar) => () => { mudar(); estado.filtro.mostrar = {}; pintarPlaybook(); };
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
    pintarGrupos();
  }
  function pintarGrupos() {
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
      box.append(el("div", { class: "painel vidro" }, vazio(
        nadaAinda ? "Nenhum item validado ainda" : "Nada com esses filtros",
        nadaAinda ? "Registre um insight e aprove na Fila. Ele aparece aqui, na etapa do funil a que pertence."
          : "Tire um filtro ou busque outra palavra.",
        nadaAinda ? el("a", { class: "btn primario", href: "#registrar", text: "Registrar um insight" }) : null)));
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
              onclick: () => { f.mostrar[chave] = quantos + POR_PAGINA_PLAYBOOK; pintarGrupos(); } },
            `Mostrar mais ${Math.min(POR_PAGINA_PLAYBOOK, doGrupo.length - quantos)} (restam ${doGrupo.length - quantos})`)
          : null));
    });
  }
  function cartaoPlaybook(it) {
    return el("button", { type: "button", class: "item vidro cartao", onclick: () => abrirItem(it.codigo) },
      metaItem(it, { secao: false }),
      el("span", { class: "titulo-cartao", text: it.titulo }),
      el("span", { class: "desc", text: it.descricao }),
      el("span", { class: "pe" }, el("span", { class: "evid" }, sinal(it.evidencia), EVIDENCIA[it.evidencia]), el("span", { text: it.codigo })));
  }

  // ---------------------------------------------------------------- gaveta de detalhe
  function abrirItem(codigo) {
    const it = acharItem(codigo);
    if (!it) { aviso(`Não achei ${codigo} na base carregada.`, "erro"); return; }
    const corpo = $("#gaveta-corpo");
    corpo.replaceChildren();
    const linhas = [
      ["Seção", NOME_SECAO[it.secao]],
      ["Segmento", it.segmento ? capital(it.segmento) : "Todos os segmentos"],
      ["Evidência", el("span", { class: "evid" }, sinal(it.evidencia), `${it.evidencia} · ${EVIDENCIA[it.evidencia]}`)],
      ["Status", STATUS[it.status] || it.status],
      ["O que foi feito", it.o_que_foi_feito],
      ["Resultado", it.resultado],
      ["Contexto", it.contexto_cliente],
      ["Quem registrou", it.autor],
      ["Quando", dataBr(it.data_evento)],
      ["Fonte", it.fonte],
      ["Motivo", it.motivo_obsolescencia],
    ].filter(([, v]) => v);
    corpo.append(
      metaItem(it),
      el("h2", { text: it.titulo }),
      el("p", { class: "desc", text: it.descricao }),
      el("dl", {}, linhas.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", {}, v)])));
    if (it.relacoes && it.relacoes.length) {
      corpo.append(el("span", { class: "rotulo", text: "Relações" }), el("div", { class: "relacoes" }, it.relacoes.map((r) => relacaoChip(r, it))));
    }
    const avs = avisosDeEvidencia(it);
    if (avs.length) corpo.append(listaAvisos(avs));
    corpo.append(el("span", { class: "codigo", text: it.codigo }));
    estado.focoAntes = document.activeElement;
    const g = $("#gaveta");
    g.removeAttribute("inert");
    g.setAttribute("aria-hidden", "false");
    g.classList.add("aberta");
    $("#fundo-gaveta").hidden = false;
    $("#fechar-gaveta").focus();
  }
  function fecharGaveta() {
    const g = $("#gaveta");
    if (!g.classList.contains("aberta")) return;
    g.classList.remove("aberta");
    g.setAttribute("aria-hidden", "true");
    g.setAttribute("inert", "");
    $("#fundo-gaveta").hidden = true;
    if (estado.focoAntes && document.contains(estado.focoAntes)) estado.focoAntes.focus();
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
    return el("article", { class: `bloco vidro ${classes}`, style: `--c:${cor}` }, el("h3", { text: titulo }), conteudo);
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

  // ---------------------------------------------------------------- eventos e início
  function ligarCampo(campoMsg, formulario) {
    campoMsg.addEventListener("input", () => autoAltura(campoMsg));
    campoMsg.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); formulario.requestSubmit(); }
    });
  }
  function ligarEventos() {
    window.addEventListener("hashchange", rotear);
    $("#entrada-botao").addEventListener("click", () => { $("#entrada-botao").setAttribute("aria-busy", "true"); });

    const formChat = $("#form-chat");
    ligarCampo($("#campo-chat"), formChat);
    formChat.addEventListener("submit", (e) => { e.preventDefault(); perguntar($("#campo-chat").value); });

    const formReg = $("#form-reg");
    ligarCampo($("#campo-reg"), formReg);
    formReg.addEventListener("submit", (e) => { e.preventDefault(); relatar($("#campo-reg").value); });
    $("#rascunho").addEventListener("submit", enviarParaFila);

    $("#form-briefing").addEventListener("submit", montarBriefing);
    $("#fechar-gaveta").addEventListener("click", fecharGaveta);
    $("#fundo-gaveta").addEventListener("click", fecharGaveta);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") fecharGaveta(); });
  }

  function pintarAtalhosChat() {
    $("#atalhos-chat").replaceChildren(...ATALHOS_CHAT.map(([rotulo, texto, cor]) =>
      el("button", { type: "button", class: "atalho", style: `--c:${cor}`, onclick: () => perguntar(texto) }, el("span", { class: "ponto" }), rotulo)));
  }

  async function iniciar() {
    seguro(pintarMascotes, "mascote");
    ligarEventos();
    seguro(() => pintarTopo("conversar"), "topo");
    estado.modo = await detectarModo();
    pintarModo();
    if (!aoVivo()) {  // nada de dado inventado: sem servidor a tela só avisa
      atualizarNumeros();
      aviso("Não consegui falar com o servidor. Confira se o uvicorn está rodando e recarregue a página.", "erro");
      return;
    }
    if (!(await verificarLogin())) return;  // sem sessão: a tela de entrada fica; o Google devolve para cá
    pintarAtalhosChat();
    await carregarItens();
    atualizarNumeros();
    iniciarConversa();
    boasVindasRegistro();
    pintarRascunho();
    rotear();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
