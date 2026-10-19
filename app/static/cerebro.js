/* Cérebro Comercial CITi: interface (sem framework e sem build).

   Com o FastAPI no ar, fala com a API de verdade (modo "Ao vivo"). Sem servidor, por exemplo aberta como
   arquivo ou numa prévia, entra sozinha no modo "Demonstração", com a base de exemplo fictícia.
   Regra de segurança: todo texto que vem do usuário ou do modelo entra na página como texto (textContent),
   nunca como HTML. O único innerHTML é o SVG do orbe, que é gerado aqui mesmo. */
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

  function rng(semente) {
    let s = semente | 0;
    return () => {
      s = (s + 0x6d2b79f5) | 0;
      let t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const normalizar = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const capital = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);
  const hora = () => new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
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

  // Base de exemplo: os mesmos itens fictícios de knowledge/exemplos.md (EX-06 existe só na demonstração).
  const EXEMPLOS = [
    {
      id: 1, codigo: "EX-01", tipo: "aprendizado", secao: "reuniao_diagnostico", segmento: "varejo",
      titulo: "Abrir a reunião com diagnóstico antes de apresentar a solução",
      descricao: "Começar a primeira reunião entendendo o problema do cliente, antes de mostrar qualquer solução, deixa o cliente menos travado e mais aberto a falar de orçamento e prazo.",
      o_que_foi_feito: "Nos primeiros 20 minutos, só perguntas: processo atual, onde dói, quanto custa o problema hoje, quem decide. A solução só apareceu no fim, ligada às dores ditas pelo próprio cliente.",
      resultado: "O cliente pediu proposta na mesma semana. Na reunião anterior, abrindo com a solução, a conversa travou em \"vamos pensar\".",
      evidencia: 2, status: "validado", autor: "Membro do comercial A (fictício)", data_evento: "2026-03-12", fonte: "reuniao", relacoes: [],
    },
    {
      id: 2, codigo: "EX-02", tipo: "case", secao: "proposta", segmento: "hotelaria",
      titulo: "Case: check-in digital para a Rede Hotel Exemplo",
      descricao: "Rede regional de 4 hotéis (fictícia) com filas no check-in na alta temporada e retrabalho da recepção com fichas em papel.",
      o_que_foi_feito: "Diagnóstico com recepção e gerência de 2 unidades; proposta em duas fases (piloto em 1 hotel, depois expansão); check-in pré-preenchido pelo hóspede antes da chegada.",
      resultado: "No piloto, o tempo médio de check-in caiu de 9 para 4 minutos (30 dias de medição). A rede aprovou a expansão para os outros 3 hotéis.",
      resumo: "Rede Hotel Exemplo: piloto de check-in digital em 1 hotel, tempo médio caiu de 9 para 4 minutos e a rede expandiu para os outros 3",
      evidencia: 4, status: "consolidado", autor: "Membro do comercial B (fictício)", data_evento: "2025-11-20", fonte: "drive", relacoes: [],
    },
    {
      id: 3, codigo: "EX-03", tipo: "objecao", secao: "negociacao_fechamento", segmento: null,
      titulo: "Objeção \"está caro\": reancorar no custo do problema e oferecer fase menor",
      descricao: "Baixar o preço de cara desvaloriza a proposta. Funciona melhor voltar ao custo do problema levantado no diagnóstico e, se o orçamento ainda não fechar, reduzir escopo, não preço.",
      o_que_foi_feito: "\"No diagnóstico vocês estimaram que esse problema custa X por mês. O investimento se paga em Y meses. Se o orçamento deste ano não comportar, dá pra começar por uma fase 1 menor.\"",
      resultado: "Em 3 negociações com essa objeção, 2 fecharam com escopo reduzido e 1 fechou com o escopo original.",
      evidencia: 3, status: "validado", autor: "Membro do comercial C (fictício)", data_evento: "2026-05-08", fonte: "chat",
      relacoes: [{ relacionado_id: 1, tipo: "reforca" }],
    },
    {
      id: 4, codigo: "EX-04", tipo: "hipotese", secao: "prospeccao", segmento: null,
      titulo: "Hipótese: prospectar em eventos do setor converte mais que LinkedIn",
      descricao: "Contato presencial em eventos do setor geraria conversas mais quentes do que mensagens frias no LinkedIn.",
      o_que_foi_feito: "Nada ainda. Levantada como ideia em reunião do time.",
      resultado: "Sem dado. Para validar, comparar a taxa de reunião marcada por contato nos dois canais no mesmo período.",
      evidencia: 1, status: "proposto", autor: "Membro do comercial A (fictício)", data_evento: "2026-08-02", fonte: "chat", relacoes: [],
    },
    {
      id: 5, codigo: "EX-05", tipo: "perfil_segmento", secao: "fundamentos", segmento: "hotelaria",
      titulo: "Perfil do segmento: hotelaria",
      descricao: "Dores típicas: filas e retrabalho na recepção, planilhas e papel, reservas desconectadas da operação. Em hotel independente decide o dono ou o gerente geral; em rede, a diretoria de operações, com o financeiro aprovando. Evite fechar e implantar na alta temporada.",
      o_que_foi_feito: "Consolidado a partir de 3 conversas comerciais com hotéis.",
      resultado: "Não se aplica (perfil).",
      pontos: [
        "Dores típicas: fila e retrabalho na recepção, planilha e papel, reservas desconectadas da operação",
        "Em rede, decide a diretoria de operações, com o financeiro aprovando o orçamento",
        "Evite fechar e implantar na alta temporada; a melhor janela de decisão é a baixa temporada",
        "O que convence: piloto em uma unidade com métrica clara antes de expandir",
      ],
      evidencia: 3, status: "validado", autor: "Membro do comercial B (fictício)", data_evento: "2026-01-15", fonte: "notion",
      relacoes: [{ relacionado_id: 2, tipo: "reforca" }],
    },
    {
      id: 6, codigo: "EX-06", tipo: "hipotese", secao: "prospeccao", segmento: null,
      titulo: "Ligar na segunda de manhã pode facilitar marcar reunião",
      descricao: "Quem registrou acredita que ligações na segunda de manhã marcam mais reuniões do que em outros horários.",
      o_que_foi_feito: null, resultado: null,
      evidencia: 1, status: "proposto", autor: "Membro do comercial D (fictício)", data_evento: null, fonte: "chat", relacoes: [],
      avisos: ["Sem dado que sustente: registrado como hipótese (evidência 1)."],
    },
  ];

  const estado = {
    modo: "demo",
    tela: "conversar",
    itens: EXEMPLOS.map((i) => ({ ...i })),
    conversa: [],
    ocupado: false,
    reg: { conversa: [], proposta: null, ocupado: false },
    filtro: { secao: null, segmento: null, busca: "", historico: false, origem: null, mostrar: {} },
    fontes: null,  // o resumo de GET /fontes/resumo
    filtroFontes: { status: null, busca: "" },
    fila: { origem: null, selecionados: new Set(), mostrar: 30, confirmando: false, aprovando: null, visiveis: [] },
    proximoId: 100,
    focoAntes: null,
  };
  const aoVivo = () => estado.modo === "vivo";

  // ---------------------------------------------------------------- orbe (o mascote)
  let seqOrbe = 0;
  function orbe(classe = "") {
    const id = `orb${++seqOrbe}`;
    const r = rng(42);
    const pts = [];
    while (pts.length < 11) {
      const x = 60 + (r() * 2 - 1) * 30;
      const y = 60 + (r() * 2 - 1) * 30;
      if (Math.hypot(x - 60, y - 60) < 30) pts.push([x, y]);
    }
    let linhas = "";
    pts.forEach((p, i) => {
      pts.map((q, j) => [j, Math.hypot(q[0] - p[0], q[1] - p[1])])
        .filter(([j]) => j > i).sort((a, b) => a[1] - b[1]).slice(0, 2)
        .forEach(([j]) => { linhas += `<line x1="${p[0].toFixed(1)}" y1="${p[1].toFixed(1)}" x2="${pts[j][0].toFixed(1)}" y2="${pts[j][1].toFixed(1)}"/>`; });
    });
    const nos = pts.map((p, i) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${(1.5 + r() * 1.5).toFixed(1)}" style="--d:${(i * 0.37).toFixed(2)}s"/>`).join("");
    return `<svg class="orbe ${classe}" viewBox="0 0 120 120" aria-hidden="true" focusable="false">
      <defs>
        <radialGradient id="${id}v" cx="38%" cy="32%" r="75%">
          <stop offset="0" stop-color="#dcd5ff" stop-opacity=".95"/><stop offset=".36" stop-color="#7f74ff" stop-opacity=".78"/>
          <stop offset=".8" stop-color="#2a1f8f" stop-opacity=".94"/><stop offset="1" stop-color="#160f4e"/>
        </radialGradient>
        <radialGradient id="${id}n" cx="64%" cy="68%" r="52%">
          <stop offset="0" stop-color="#ff7ad9" stop-opacity=".55"/><stop offset="1" stop-color="#ff7ad9" stop-opacity="0"/>
        </radialGradient>
        <linearGradient id="${id}a" x1="0" x2="1">
          <stop offset="0" stop-color="#7fd7ff" stop-opacity=".08"/><stop offset=".5" stop-color="#cdb8ff"/><stop offset="1" stop-color="#7fd7ff" stop-opacity=".08"/>
        </linearGradient>
        <clipPath id="${id}c"><circle cx="60" cy="60" r="37"/></clipPath>
      </defs>
      <g transform="rotate(-16 60 60)"><path d="M5 62 A55 15 0 0 1 115 62" fill="none" stroke="url(#${id}a)" stroke-width="3" opacity=".5"/></g>
      <circle cx="60" cy="60" r="38" fill="url(#${id}v)"/>
      <circle cx="60" cy="60" r="38" fill="url(#${id}n)"/>
      <g clip-path="url(#${id}c)">
        <g class="rede" stroke="#ebe6ff" stroke-opacity=".45" stroke-width=".7">${linhas}</g>
        <g class="nos" fill="#f6f3ff">${nos}</g>
      </g>
      <ellipse cx="46" cy="40" rx="13" ry="7.5" fill="#fff" opacity=".3" transform="rotate(-30 46 40)"/>
      <circle cx="60" cy="60" r="38" fill="none" stroke="#d3cbff" stroke-opacity=".55" stroke-width="1"/>
      <g transform="rotate(-16 60 60)"><path d="M115 62 A55 15 0 0 1 5 62" fill="none" stroke="url(#${id}a)" stroke-width="3.2"/></g>
    </svg>`;
  }
  function pintarOrbes(raiz = document) {
    for (const alvo of $$("[data-orbe]", raiz)) alvo.innerHTML = orbe(alvo.dataset.orbe);
  }
  const orbeEm = (classe) => { const s = el("span", { class: classe }); s.innerHTML = orbe(); return s; };

  // ---------------------------------------------------------------- cena: a cidade à noite
  const cena = (() => {
    const cv = $("#cena");
    const ctx = cv.getContext("2d");
    const calmo = matchMedia("(prefers-reduced-motion: reduce)");
    let W = 0, H = 0, dpr = 1, ceu = null, cidade = null;
    let estrelas = [], nos = [], arestas = [], faiscas = [], luzes = [];
    let rodando = false, ultimo = 0;

    const tela = (w, h) => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; };

    function predios(c, r, o) {
      let x = -20;
      while (x < W + 20) {
        const w = o.larg[0] + r() * (o.larg[1] - o.larg[0]);
        const h = H * (o.alt[0] + r() * (o.alt[1] - o.alt[0]));
        const topo = o.base - h;
        c.fillStyle = o.cor;
        c.fillRect(x, topo, w - 2, H - topo);
        if (r() < 0.35) c.fillRect(x + w * 0.28, topo - h * 0.07, w * 0.44, h * 0.07);
        if (r() < 0.22) {
          c.fillRect(x + w * 0.48, topo - h * 0.2, 2, h * 0.2);
          luzes.push({ x: x + w * 0.48 + 1, y: topo - h * 0.2, antena: true, f: r() * 6.28 });
        }
        c.fillStyle = o.aresta;
        c.fillRect(x, topo, 1.5, H - topo);
        if (o.janelas) {
          const cols = Math.floor((w - 10) / 9), linhas = Math.floor((H - topo - 14) / 12);
          for (let i = 0; i < cols; i++) {
            for (let j = 0; j < linhas; j++) {
              if (r() >= o.acesas) continue;
              const tom = o.tons[Math.floor(r() * o.tons.length)];
              const wx = x + 6 + i * 9, wy = topo + 10 + j * 12;
              c.fillStyle = `${tom}${(0.3 + r() * 0.55).toFixed(2)})`;
              c.fillRect(wx, wy, 4, 6);
              if (r() < 0.035) luzes.push({ x: wx, y: wy, tom, f: r() * 6.28 });
            }
          }
        }
        x += w + (r() < 0.3 ? r() * 16 : 0);
      }
    }

    function montar() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth; H = window.innerHeight;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      const r = rng(7);
      luzes = [];

      // céu, névoa do horizonte e lua
      ceu = tela(cv.width, cv.height);
      const f = ceu.getContext("2d");
      f.scale(dpr, dpr);
      const g = f.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, "#04051a"); g.addColorStop(0.42, "#121048"); g.addColorStop(0.68, "#36217e");
      g.addColorStop(0.84, "#78398e"); g.addColorStop(1, "#1a0f33");
      f.fillStyle = g; f.fillRect(0, 0, W, H);
      const nevoa = f.createRadialGradient(W * 0.64, H * 0.84, 0, W * 0.64, H * 0.84, W * 0.7);
      nevoa.addColorStop(0, "rgba(255,140,190,.34)"); nevoa.addColorStop(0.42, "rgba(140,80,220,.16)"); nevoa.addColorStop(1, "rgba(0,0,0,0)");
      f.fillStyle = nevoa; f.fillRect(0, 0, W, H);
      const lx = W * 0.8, ly = H * (W > 860 ? 0.14 : 0.42), lr = Math.max(34, Math.min(W, H) * 0.07);
      const halo = f.createRadialGradient(lx, ly, lr * 0.6, lx, ly, lr * 4.2);
      halo.addColorStop(0, "rgba(205,195,255,.32)"); halo.addColorStop(1, "rgba(205,195,255,0)");
      f.fillStyle = halo; f.beginPath(); f.arc(lx, ly, lr * 4.2, 0, 7); f.fill();
      const lua = f.createRadialGradient(lx - lr * 0.35, ly - lr * 0.35, lr * 0.1, lx, ly, lr);
      lua.addColorStop(0, "#fbf8ff"); lua.addColorStop(0.7, "#d2c8ff"); lua.addColorStop(1, "#9c8df0");
      f.fillStyle = lua; f.beginPath(); f.arc(lx, ly, lr, 0, 7); f.fill();
      f.fillStyle = "rgba(118,98,210,.17)";
      for (let i = 0; i < 6; i++) {
        const a = r() * 6.28, d = r() * lr * 0.6;
        f.beginPath(); f.arc(lx + Math.cos(a) * d, ly + Math.sin(a) * d, lr * (0.08 + r() * 0.14), 0, 7); f.fill();
      }

      // estrelas de fundo
      estrelas = [];
      const n = Math.round((W * H) / 5200);
      for (let i = 0; i < n; i++) estrelas.push({ x: r() * W, y: r() * H * 0.72, t: r() * 1.3 + 0.3, f: r() * 6.28, v: 0.5 + r() * 1.5 });

      // constelação: a base de conhecimento (itens e relações)
      nos = [];
      const k = Math.max(9, Math.round(W / 105));
      for (let i = 0; i < k; i++) nos.push({ x: W * (0.05 + r() * 0.9), y: H * (0.05 + r() * 0.42), f: r() * 6.28 });
      arestas = [];
      nos.forEach((a, i) => {
        nos.map((b, j) => [j, Math.hypot(b.x - a.x, b.y - a.y)]).filter(([j]) => j !== i)
          .sort((p, q) => p[1] - q[1]).slice(0, 2)
          .forEach(([j, d]) => { if (d < W * 0.24 && !arestas.some(([p, q]) => (p === j && q === i) || (p === i && q === j))) arestas.push([i, j]); });
      });

      // cidade em três planos, moldura da janela e luz de mesa
      cidade = tela(cv.width, cv.height);
      const c = cidade.getContext("2d");
      c.scale(dpr, dpr);
      predios(c, r, { base: H * 0.7, alt: [0.1, 0.26], larg: [28, 70], cor: "#251b58", aresta: "rgba(170,150,255,.07)", janelas: false });
      predios(c, r, { base: H * 0.8, alt: [0.14, 0.36], larg: [36, 90], cor: "#170f3c", aresta: "rgba(170,150,255,.09)", janelas: true, acesas: 0.24, tons: ["rgba(150,160,255,", "rgba(255,190,120,"] });
      predios(c, r, { base: H * 0.93, alt: [0.18, 0.44], larg: [48, 120], cor: "#0b0821", aresta: "rgba(170,150,255,.1)", janelas: true, acesas: 0.33, tons: ["rgba(255,196,120,", "rgba(150,170,255,", "rgba(255,120,200,"] });
      const mesa = c.createLinearGradient(0, H * 0.86, 0, H);
      mesa.addColorStop(0, "rgba(5,4,15,0)"); mesa.addColorStop(1, "rgba(5,4,15,.92)");
      c.fillStyle = mesa; c.fillRect(0, H * 0.86, W, H * 0.14);
      const lampada = c.createRadialGradient(W * 0.02, H * 0.98, 0, W * 0.02, H * 0.98, Math.max(W, H) * 0.42);
      lampada.addColorStop(0, "rgba(255,170,90,.28)"); lampada.addColorStop(1, "rgba(255,170,90,0)");
      c.fillStyle = lampada; c.fillRect(0, 0, W, H);
      const tela2 = c.createRadialGradient(W * 0.74, H, 0, W * 0.74, H, Math.max(W, H) * 0.3);
      tela2.addColorStop(0, "rgba(110,150,255,.2)"); tela2.addColorStop(1, "rgba(110,150,255,0)");
      c.fillStyle = tela2; c.fillRect(0, 0, W, H);
    }

    function quadro(ms) {
      const s = ms / 1000;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(ceu, 0, 0);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#e9e5ff";
      for (const e of estrelas) {
        ctx.globalAlpha = 0.3 + 0.7 * Math.abs(Math.sin(e.f + s * e.v * 0.6));
        ctx.fillRect(e.x, e.y, e.t, e.t);
      }
      ctx.globalAlpha = 1;
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(184,150,255,.2)";
      ctx.beginPath();
      for (const [a, b] of arestas) { ctx.moveTo(nos[a].x, nos[a].y); ctx.lineTo(nos[b].x, nos[b].y); }
      ctx.stroke();
      if (!calmo.matches && faiscas.length < 3 && Math.random() < 0.015 && arestas.length) {
        const [a, b] = arestas[Math.floor(Math.random() * arestas.length)];
        faiscas.push({ a, b, p: 0 });
      }
      for (const fz of faiscas) {
        fz.p += 0.014;
        const A = nos[fz.a], B = nos[fz.b];
        const x = A.x + (B.x - A.x) * fz.p, y = A.y + (B.y - A.y) * fz.p;
        const g = ctx.createRadialGradient(x, y, 0, x, y, 11);
        g.addColorStop(0, "rgba(170,232,255,.95)"); g.addColorStop(1, "rgba(170,232,255,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 11, 0, 7); ctx.fill();
      }
      faiscas = faiscas.filter((fz) => fz.p < 1);
      for (const n of nos) {
        const p = 0.6 + 0.4 * Math.sin(n.f + s * 1.3);
        const g = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, 10);
        g.addColorStop(0, `rgba(236,230,255,${(0.92 * p).toFixed(3)})`);
        g.addColorStop(0.35, `rgba(184,150,255,${(0.34 * p).toFixed(3)})`);
        g.addColorStop(1, "rgba(184,150,255,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(n.x, n.y, 10, 0, 7); ctx.fill();
      }
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(cidade, 0, 0);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      for (const l of luzes) {
        if (l.antena) {
          ctx.fillStyle = `rgba(255,90,120,${Math.sin(l.f + s * 2.2) > 0.6 ? 1 : 0.15})`;
          ctx.beginPath(); ctx.arc(l.x, l.y, 1.8, 0, 7); ctx.fill();
        } else {
          ctx.fillStyle = `${l.tom}${(0.2 + 0.65 * (0.5 + 0.5 * Math.sin(l.f + s * 0.4))).toFixed(2)})`;
          ctx.fillRect(l.x, l.y, 4, 6);
        }
      }
    }

    function laco(ms) {
      if (!rodando) return;
      if (!document.hidden && ms - ultimo > 32) { quadro(ms); ultimo = ms; }
      requestAnimationFrame(laco);
    }
    function ligar() { if (!rodando && !calmo.matches) { rodando = true; requestAnimationFrame(laco); } }

    let espera = 0;
    function iniciar() {
      montar(); quadro(performance.now()); ligar();
      window.addEventListener("resize", () => {
        clearTimeout(espera);
        espera = setTimeout(() => { montar(); quadro(performance.now()); }, 150);
      });
      calmo.addEventListener?.("change", () => { if (calmo.matches) rodando = false; else ligar(); });
    }
    // Quando o Cérebro responde ou um item é aprovado, uma rajada de sinapses atravessa a constelação.
    function pulsar() {
      if (!arestas.length) return;
      for (let i = 0; i < 6; i++) {
        const [a, b] = arestas[Math.floor(Math.random() * arestas.length)];
        faiscas.push({ a, b, p: Math.random() * 0.25 });
      }
      if (calmo.matches) quadro(performance.now());
    }
    return { iniciar, pulsar };
  })();

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
    if (!r.ok) throw new ErroApi(mensagemErro(r.status, dados), r.status);
    return dados;
  }
  async function detectarModo() {
    if (/[?&]demo\b/.test(location.search)) return "demo";
    try {
      const ctrl = new AbortController();
      const limite = setTimeout(() => ctrl.abort(), 2500);
      const r = await fetch("/health", { signal: ctrl.signal });
      clearTimeout(limite);
      if (!r.ok) return "demo";
      const d = await r.json();
      return d && d.status === "ok" ? "vivo" : "demo";
    } catch {
      return "demo";
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
    if (!aoVivo()) return;
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
  function exigirAutor() {
    const nome = $("#autor").value.trim();
    if (nome) return nome;
    aviso("Escreva seu nome no campo \"Você\", no topo, para registrar e aprovar itens.", "erro");
    $("#autor").focus();
    return null;
  }
  function acharItem(codigo) {
    const todos = aoVivo() ? estado.itens : [...estado.itens, ...EXEMPLOS];  // ao vivo: só o que existe no banco
    return todos.find((i) => i.codigo === codigo) || null;
  }
  function itemPorId(id, origem) {
    const pool = origem && origem.codigo && origem.codigo.startsWith("EX-") ? EXEMPLOS : estado.itens;
    return pool.find((i) => i.id === id) || null;
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
    if (it.codigo && it.codigo.startsWith("EX-")) lista.push("Item fictício da base de exemplo.");
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
    return el("div", { class: "vazio" }, orbeEm("orbe-vazio"), el("h3", { text: titulo }), el("p", { text: texto }), ...extra);
  }
  function autoAltura(t) {
    t.style.height = "auto";
    t.style.height = `${Math.min(t.scrollHeight, 150)}px`;
  }

  // Texto do modelo -> parágrafos, listas, negrito e citações clicáveis (sem HTML do modelo).
  function inline(txt) {
    const partes = [];
    const re = /\[((?:EX|INS)-\d+)\]|\*\*([^*]+)\*\*/g;
    let i = 0, m;
    while ((m = re.exec(txt))) {
      if (m.index > i) partes.push(document.createTextNode(txt.slice(i, m.index)));
      if (m[1]) partes.push(chipCitacao(m[1]));
      else partes.push(el("strong", { text: m[2] }));
      i = re.lastIndex;
    }
    if (i < txt.length) partes.push(document.createTextNode(txt.slice(i)));
    return partes;
  }
  function formatar(texto) {
    const frag = document.createDocumentFragment();
    for (const bloco of String(texto).trim().split(/\n{2,}/)) {
      const linhas = bloco.split("\n").filter((l) => l.trim());
      if (!linhas.length) continue;
      if (linhas.every((l) => /^\s*[-*•]\s+/.test(l))) {
        frag.append(el("ul", {}, linhas.map((l) => el("li", {}, inline(l.replace(/^\s*[-*•]\s+/, ""))))));
      } else if (linhas.every((l) => /^\s*\d+[.)]\s+/.test(l))) {
        frag.append(el("ol", {}, linhas.map((l) => el("li", {}, inline(l.replace(/^\s*\d+[.)]\s+/, ""))))));
      } else {
        const p = el("p");
        linhas.forEach((l, i) => { if (i) p.append(el("br")); p.append(...inline(l)); });
        frag.append(p);
      }
    }
    return frag;
  }
  function chipCitacao(codigo) {
    const item = acharItem(codigo);
    return el("button", { type: "button", class: "cita", title: item ? item.titulo : "Abrir item", onclick: () => abrirItem(codigo) }, codigo);
  }

  function adicionarMsg(caixa, { papel, texto, quem, nota, extra }) {
    const linha = el("div", { class: `linha${papel === "eu" ? " eu" : ""}` });
    if (papel !== "eu") linha.append(orbeEm("av"));
    const bolha = el("div", { class: `msg ${papel}` }, el("span", { class: "quem", text: quem }), formatar(texto));
    if (extra) bolha.append(extra);
    if (nota) bolha.append(el("p", { class: "nota", text: nota }));
    bolha.append(el("span", { class: "hora", text: hora() }));
    linha.append(bolha);
    caixa.append(linha);
    caixa.scrollTop = caixa.scrollHeight;
    return linha;
  }
  function digitando(caixa) {
    const linha = el("div", { class: "linha" }, orbeEm("av"),
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
    fontes: ["Fontes", "As páginas que o Cérebro leu e o que virou item. Nada daqui entra no playbook sem passar pela Fila."],
    playbook: ["Playbook", "O que o time já validou, na ordem do funil."],
    briefing: ["Briefing de reunião", "Prévia da T9: um roteiro montado só com o que está na base."],
  };
  function pintarTopo(tela) {
    const box = $("#ident");
    box.replaceChildren();
    if (tela === "conversar") {
      box.append(orbeEm("av-topo"), el("div", {},
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
      : "Base de exemplo com dados fictícios. Rode o app com o uvicorn para usar a API de verdade.";
  }
  function pintarModo() {
    const m = $("#modo");
    m.dataset.modo = estado.modo;
    m.textContent = aoVivo() ? "Ao vivo" : "Demonstração · dados fictícios";
  }

  // ---------------------------------------------------------------- conversar
  const ATALHOS_CHAT = [
    ["Preparar proposta para rede de hotelaria", "Vou apresentar proposta para uma rede de hotelaria. Como conduzo e que cases temos?", "var(--ciano)"],
    ["Cliente disse que está caro", "O cliente disse que está caro. Como respondemos?", "var(--ambar)"],
    ["Testar hipótese: eventos ou LinkedIn", "Pensei em prospectar em eventos do setor em vez de LinkedIn. O que você acha?", "var(--lilas)"],
    ["O que a base não cobre?", "O que a base ainda não cobre?", "var(--risco)"],
  ];
  const RESPOSTAS_DEMO = {
    hotelaria: `Para uma rede de hotelaria, eu conduziria em três tempos.

- Abra com diagnóstico, não com a solução: processo atual, onde dói, quanto custa o problema e quem decide [EX-01].
- Em rede, quem decide costuma ser a diretoria de operações, com o financeiro aprovando o orçamento. Evite propor implantação na alta temporada [EX-05].
- Proponha um piloto em uma unidade com métrica clara antes de expandir. No case da Rede Hotel Exemplo, o check-in caiu de 9 para 4 minutos no piloto e a rede aprovou a expansão [EX-02].

Se o preço travar, volte ao custo do problema levantado no diagnóstico e ofereça uma fase menor em vez de desconto [EX-03].`,
    caro: `A base tem um caminho para isso, com padrão repetido em 3 negociações [EX-03].

- Não baixe o preço de cara. Volte ao custo do problema que o próprio cliente estimou no diagnóstico.
- Mostre em quantos meses o investimento se paga.
- Se o orçamento não fechar, reduza o escopo para uma fase 1, não o preço.

Isso depende de um diagnóstico bem feito antes [EX-01].`,
    eventos: `Fazendo o advogado do diabo: isso ainda é uma hipótese, sem nenhum dado [EX-04].

- Risco: evento custa tempo e dinheiro, e uma conversa quente pode não virar reunião marcada.
- O que a base mostra: ninguém testou os dois canais no mesmo período.
- Como medir: durante um mês, conte contatos e reuniões marcadas por canal e compare a taxa.

Se testar, registre o resultado para essa hipótese ganhar evidência.`,
    lacunas: `Pelas perguntas de teste, a base ainda não cobre:

- Preço praticado por tipo de serviço.
- Motivos das propostas perdidas.
- Prospecção com resultado medido (só existe uma hipótese [EX-04]).
- Segmentos além de hotelaria e varejo.

Esses são bons primeiros registros.`,
  };
  function respostaDemo(texto) {
    const t = normalizar(texto);
    if (/nao cobre|lacuna|falta na base|ainda nao/.test(t)) return RESPOSTAS_DEMO.lacunas;
    if (/hotel|pousada|hotelaria/.test(t)) return RESPOSTAS_DEMO.hotelaria;
    if (/caro|preco|desconto|orcamento/.test(t)) return RESPOSTAS_DEMO.caro;
    if (/evento|linkedin|hipotese|prospec/.test(t)) return RESPOSTAS_DEMO.eventos;
    const tema = texto.trim().replace(/\s+/g, " ").slice(0, 70);
    return `A base não cobre isso ainda ("${tema}").

Hoje ela tem material sobre hotelaria, reunião de diagnóstico, a objeção de preço e uma hipótese de prospecção. Se você viveu algo sobre esse tema, registre em Registrar para eu poder usar nas próximas respostas.`;
  }
  const NOTA_DEMO = "Modo demonstração: resposta simulada com itens fictícios.";

  async function perguntar(texto) {
    texto = texto.trim();
    if (!texto || estado.ocupado) return;
    const caixa = $("#mensagens");
    const campo = $("#campo-chat");
    adicionarMsg(caixa, { papel: "eu", texto, quem: $("#autor").value.trim() || "Você" });
    campo.value = ""; autoAltura(campo);
    estado.ocupado = true; $("#enviar-chat").disabled = true; pensando(true);
    const indicador = digitando(caixa);
    try {
      let resposta;
      if (aoVivo()) {
        resposta = (await chamar("POST", "/chat", { mensagem: texto, historico: estado.conversa.slice(-30) })).resposta;
      } else {
        await esperar(900 + Math.random() * 700);
        resposta = respostaDemo(texto);
      }
      indicador.remove();
      adicionarMsg(caixa, { papel: "cerebro", texto: resposta, quem: "Cérebro", nota: aoVivo() ? null : NOTA_DEMO });
      estado.conversa.push({ role: "user", text: texto }, { role: "model", text: resposta });
      cena.pulsar();
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
    const exemplo = aoVivo() ? estado.itens.find((i) => i.status === "validado" || i.status === "consolidado") : null;
    const toque = aoVivo()
      ? (exemplo ? `Toque numa fonte, como [${exemplo.codigo}], para ver o item inteiro.` : "Quando houver itens aprovados, toque numa fonte para ver o item inteiro.")
      : "Toque numa fonte, como [EX-02], para ver o item inteiro.";
    adicionarMsg(caixa, {
      papel: "cerebro", quem: "Cérebro",
      texto: `Oi! Eu respondo com base no que o time aprovou e mostro de onde tirei cada ponto. ${toque}`,
    });
    if (!aoVivo()) {
      const pergunta = ATALHOS_CHAT[0][1];
      adicionarMsg(caixa, { papel: "eu", quem: $("#autor").value.trim() || "Você", texto: pergunta });
      adicionarMsg(caixa, { papel: "cerebro", quem: "Cérebro", texto: RESPOSTAS_DEMO.hotelaria, nota: NOTA_DEMO });
      estado.conversa.push({ role: "user", text: pergunta }, { role: "model", text: RESPOSTAS_DEMO.hotelaria });
    }
  }

  // ---------------------------------------------------------------- registrar (curador)
  const EXEMPLOS_RELATO = [
    "Hoje abri a reunião com o hotel do centro com diagnóstico em vez de apresentar o CITi, e o cara destravou. Acho que vale pra todos",
    "Cliente de varejo disse que estava caro. Voltei ao custo do problema e fechamos a fase 1 em 2 semanas",
    "Acho que ligar na segunda de manhã marca mais reunião",
  ];
  const RE_PESSOAL = [
    ["e-mail", /[\w.+-]+@[\w-]+\.[\w.-]+/],
    ["telefone", /\(?\b\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b/],
    ["CPF ou CNPJ", /\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\b\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2}\b/],
  ];

  function curarDemo(texto, conversa, autor) {
    const turno = 1 + conversa.filter((m) => m.role === "user").length;
    const ultimo = turno >= 3;
    const relatos = [...conversa.filter((m) => m.role === "user").map((m) => m.text), texto];
    const tudo = relatos.join(" ");
    const t = normalizar(tudo);
    const medido = /de \d+ para \d+|\d+\s*(%|min|minutos|dias|semanas|reunioes|clientes|vezes)/.test(t);
    let tipo = "aprendizado", evidencia = 2;
    if (/\bacho\b|talvez|pensei|ideia/.test(t) && !medido && !/fechamos|fechou|pediu/.test(t)) { tipo = "hipotese"; evidencia = 1; }
    if (/caro|preco|desconto/.test(t)) tipo = "objecao";
    if (medido) { evidencia = 4; if (/piloto|projeto|implant/.test(t)) tipo = "case"; }
    else if (/\b(3|tres|4|quatro|5|cinco)\s+(reunioes|vezes|clientes|negociacoes)/.test(t)) evidencia = 3;

    let secao = "reuniao_diagnostico";
    if (/ligar|ligacao|linkedin|prospec|evento|contato frio/.test(t)) secao = "prospeccao";
    else if (/caro|preco|desconto|negoci|fechamos|fechou/.test(t)) secao = "negociacao_fechamento";
    else if (/proposta|escopo|piloto/.test(t)) secao = "proposta";
    else if (/qualific|lead/.test(t)) secao = "qualificacao";
    else if (/pos-venda|suporte|renova/.test(t)) secao = "pos_venda";

    const segmento = /hotel|pousada/.test(t) ? "hotelaria" : /loja|varejo|mercado/.test(t) ? "varejo"
      : /clinica|hospital|saude/.test(t) ? "saúde" : /escola|faculdade|educa/.test(t) ? "educação" : null;

    const avisos = [];
    if (/vale pra todos|vale para todos|sempre funciona/.test(t) && evidencia < 3) avisos.push("\"Vale para todos\" se apoia em um caso só: ficou como observação única (evidência 2).");
    if (/ignore|marque como|consolidado|evidencia 4/.test(t)) avisos.push("O texto pedia para mudar status ou evidência. A instrução foi ignorada.");
    for (const [nome, re] of RE_PESSOAL) if (re.test(tudo)) avisos.push(`Possível ${nome} no relato: dado pessoal de cliente não deve entrar na base (LGPD).`);
    if (tipo === "hipotese") avisos.push("Sem dado que sustente: registrado como hipótese (evidência 1).");

    const frases = tudo.split(/(?<=[.!?])\s+|\n+/).map((f) => f.trim()).filter(Boolean);
    const comResultado = frases.find((f) => /\d/.test(f) || /fech|pediu|virou|destrav|aprovou/.test(normalizar(f)));
    const perguntas = [];
    if (!ultimo && turno === 1) {
      if (!medido && !/fech|pediu|virou|aprovou/.test(t)) perguntas.push("Qual foi o resultado? A conversa virou proposta ou próximo passo?");
      if (!segmento) perguntas.push("Qual o segmento do cliente?");
    }
    if (ultimo && !segmento) avisos.push("Ficou sem resposta: qual o segmento do cliente?");

    const primeira = relatos[0].split(/(?<=[.!?])\s+/)[0].replace(/\s+/g, " ").trim();
    const titulo = capital(primeira.length > 110 ? `${primeira.slice(0, 107).trimEnd()}…` : primeira).replace(/[.!]$/, "");
    const candidatos = estado.itens.filter((i) => ["validado", "consolidado"].includes(i.status) && i.secao === secao);
    const relacoes = candidatos.slice(0, 2).map((c) => ({ relacionado_id: c.id, tipo: "reforca" }));

    return {
      insight: {
        titulo, tipo, secao, segmento, evidencia, autor,
        descricao: relatos.join(" ").replace(/\s+/g, " ").slice(0, 600),
        o_que_foi_feito: null,
        resultado: comResultado && (medido || /fech|pediu|virou|destrav|aprovou/.test(normalizar(comResultado))) ? comResultado : null,
        contexto_cliente: null, data_evento: null, servico: null,
      },
      relacoes, perguntas: perguntas.slice(0, 2), avisos,
    };
  }

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
      let proposta;
      if (aoVivo()) {
        proposta = await chamar("POST", "/registrar/propor", { texto, autor, conversa: estado.reg.conversa.slice(-10) });
      } else {
        await esperar(1000 + Math.random() * 600);
        proposta = curarDemo(texto, estado.reg.conversa, autor);
      }
      indicador.remove();
      const perguntas = proposta.perguntas || [];
      const resumo = perguntas.length
        ? `Já montei um rascunho ao lado. Antes de fechar, ${perguntas.length === 1 ? "uma pergunta" : "duas perguntas"}:`
        : "Pronto. O rascunho está ao lado: revise, ajuste o que quiser e envie para a Fila.";
      const extra = perguntas.length ? el("ol", { class: "lista-perguntas" }, perguntas.map((p) => el("li", { text: p }))) : null;
      adicionarMsg(caixa, { papel: "cerebro", quem: "Curador", texto: resumo, extra, nota: aoVivo() ? null : "Modo demonstração: curadoria simulada." });
      estado.reg.conversa.push({ role: "user", text: texto }, { role: "model", text: perguntas.length ? perguntas.join("\n") : resumo });
      estado.reg.proposta = proposta;
      pintarRascunho();
      cena.pulsar();
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
        "Conte o que aconteceu no campo ao lado. O curador preenche tipo, seção, segmento e evidência, e você ajusta antes de enviar para a Fila.",
        aoVivo() ? null : el("div", { class: "exemplos" },
          el("span", { class: "rotulo", text: "Experimente um destes relatos" }),
          EXEMPLOS_RELATO.map((txt) => el("button", { type: "button", class: "exemplo", text: txt, onclick: () => relatar(txt) })))));
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
      let criado;
      if (aoVivo()) {
        criado = await chamar("POST", "/insights", { ...dados, autor, fonte: "chat" });
        await carregarItens();
      } else {
        criado = { ...dados, autor, fonte: "chat", id: estado.proximoId++, status: "proposto", avisos: estado.reg.proposta.avisos || [] };
        estado.itens.push({ ...criado, codigo: `INS-${criado.id}` });
      }
      aviso(`Enviado para a Fila como proposto (INS-${criado.id}).`, "ok");
      cena.pulsar();
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
        if (aoVivo()) await chamar("POST", `/insights/${id}/aprovar`, { por_quem: autor });
        else { const it = itemPorId(id); if (it) it.status = "validado"; }
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
    if (aoVivo()) await carregarItens();
    if (aprovados) { cena.pulsar(); }
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
      if (aoVivo()) {
        const corpo = acao === "aprovar" ? { por_quem: autor } : { por_quem: autor, motivo: motivo.trim() };
        await chamar("POST", `/insights/${it.id}/${acao}`, corpo);
        await carregarItens();
      } else {
        it.status = acao === "aprovar" ? "validado" : "obsoleto";
        if (acao === "rejeitar") it.motivo_obsolescencia = motivo.trim();
      }
      aviso(acao === "aprovar" ? `${it.codigo} aprovado. Já aparece no Playbook.` : `${it.codigo} rejeitado e marcado como obsoleto.`, "ok");
      cena.pulsar();
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
    removida: ["Removida", "mudo", "Saiu da origem (apagada ou sem compartilhamento). Os itens ainda não revisados viraram obsoletos."],
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
    const [rotulo, cor, explica] = STATUS_FONTE[f.status] || [f.status, "mudo", ""];
    const url = linkSeguro(f.url);
    const titulo = url
      ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: f.titulo })
      : document.createTextNode(f.titulo);
    const gerou = resumoDeItens(f.itens);
    return el("article", { class: "item fonte vidro" },
      el("div", { class: "meta" },
        el("span", { class: "etiqueta", text: ORIGEM[f.origem] || f.origem }),
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
      vazio("Nenhuma página lida ainda", "Quando o Cérebro ler o Notion, cada página aparece aqui, com o que aconteceu com ela."),
      el("ol", {},
        el("li", {}, "No .env, preencha ", el("code", { text: "NOTION_TOKEN" }), " (a integração só enxerga as páginas compartilhadas com ela)."),
        el("li", {}, "Simule sem gravar nada: ", el("code", { text: "python -m scripts.importar_notion --dry-run" })),
        el("li", {}, "Importe de verdade: ", el("code", { text: "python -m scripts.importar_notion" }), ". Depois volte aqui."),
      ));
  }
  async function pintarFontes() {
    const box = $("#fontes-conteudo");
    if (!aoVivo()) {
      box.replaceChildren(el("div", { class: "painel vidro" }, vazio("As fontes só aparecem com o servidor ligado",
        "No modo demonstração não há páginas importadas. Rode o app com o uvicorn e importe o Notion.")));
      return;
    }
    let resumo, lista;
    try {
      [resumo, lista] = await Promise.all([chamar("GET", "/fontes/resumo"), chamar("GET", "/fontes?limit=200")]);
    } catch (e) {
      aviso(`Não consegui carregar as fontes: ${e.message}`, "erro");
      return;
    }
    estado.fontes = resumo;
    atualizarNumeros();
    if (!resumo.total) { box.replaceChildren(orientacaoFontes()); return; }

    const por = resumo.por_status;
    const n = (...chaves) => chaves.reduce((s, c) => s + (por[c] || 0), 0);
    const ultima = resumo.ultima_execucao;
    const quando = ultima
      ? `Última sincronização: ${dataHora(ultima.fim || ultima.inicio)}${ultima.fim ? "" : " (não terminou)"} · ${ultima.paginas_lidas} lidas, ${ultima.paginas_novas} novas, ${ultima.paginas_alteradas} alteradas${ultima.paginas_falhas ? `, ${ultima.paginas_falhas} com falha` : ""}`
      : "Nenhuma sincronização registrada.";

    const filtro = estado.filtroFontes;

    const busca = el("input", { type: "search", class: "busca", placeholder: "Buscar pelo título", "aria-label": "Buscar fonte pelo título" });
    busca.value = filtro.busca;
    const aoBuscar = () => { filtro.busca = busca.value; pintarLinhas(); };
    const linhas = el("div", { class: "lista" });
    function pintarLinhas() {
      const itens = lista.itens.filter((f) =>
        (!filtro.status || f.status === filtro.status) &&
        (!filtro.busca || f.titulo.toLowerCase().includes(filtro.busca.toLowerCase())));
      linhas.replaceChildren(...(itens.length
        ? itens.map(cartaoFonte)
        : [el("div", { class: "painel vidro" }, vazio("Nada com esse filtro", "Tire o filtro ou mude a busca."))]));
    }
    busca.addEventListener("input", aoBuscar);

    const chips = el("div", { class: "filtros" }, busca,
      chip(`Todas (${resumo.total})`, !filtro.status, () => { filtro.status = null; pintarFontes(); }),
      ...Object.keys(STATUS_FONTE).filter((s) => por[s]).map((s) =>
        chip(`${STATUS_FONTE[s][0]} (${por[s]})`, filtro.status === s, () => { filtro.status = filtro.status === s ? null : s; pintarFontes(); })));

    box.replaceChildren(
      el("div", { class: "fontes-resumo" },
        numeroCartao(resumo.total, "páginas lidas"),
        numeroCartao(n("importada"), "viraram itens", "var(--ok)"),
        numeroCartao(n("a_curar", "falha"), "esperando o curador", "var(--alerta)"),
        numeroCartao(n(...PULADAS), "puladas", "var(--risco)"),
        numeroCartao(n("removida"), "removidas")),
      el("div", { class: "barra-fontes" },
        el("span", { text: quando }),
        el("span", { class: "dica", text: "Para sincronizar: python -m scripts.importar_notion (pelo botão chega na T4c)" })),
      chips,
      ...(lista.total > lista.itens.length
        ? [el("p", { class: "resumo-lista", text: `Mostrando as ${lista.itens.length} mais recentes de ${lista.total}` })]
        : []),
      linhas);
    pintarLinhas();
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

  // ---------------------------------------------------------------- briefing (prévia da T9)
  function pintarSegmentosBriefing() {
    const s = $("#b-segmento");
    if (s.options.length) return;
    for (const seg of SEGMENTOS) s.append(el("option", { value: seg, text: capital(seg) }));
    s.value = "hotelaria";
  }
  function baseUtil() {
    const vistos = new Set();
    return (aoVivo() ? estado.itens : [...estado.itens, ...EXEMPLOS]).filter((i) => {
      if (vistos.has(i.codigo) || !["validado", "consolidado"].includes(i.status)) return false;
      vistos.add(i.codigo);
      return true;
    });
  }
  function marcaEvid(it) {
    if (it.evidencia <= 2) return el("span", { class: "marca-evid", text: it.evidencia === 1 ? "opinião" : "caso único" });
    return null;
  }
  function itemLista(texto, it) {
    return el("li", {}, inline(texto), it ? marcaEvid(it) : null);
  }
  function bloco(titulo, cor, conteudo, classes = "") {
    return el("article", { class: `bloco vidro ${classes}`, style: `--c:${cor}` }, el("h3", { text: titulo }), conteudo);
  }
  const semBase = (t) => el("p", { class: "sem-base", text: t });

  function montarBriefing(ev) {
    if (ev) ev.preventDefault();
    pintarSegmentosBriefing();
    const seg = $("#b-segmento").value;
    const tipo = $("#b-tipo").value;
    const contexto = $("#b-contexto").value.trim();
    const base = baseUtil();
    const cases = base.filter((i) => i.tipo === "case" && i.segmento === seg);
    const perfil = base.find((i) => i.tipo === "perfil_segmento" && i.segmento === seg);
    const conducao = base.filter((i) => i.secao === "reuniao_diagnostico");
    const objecoes = base.filter((i) => i.tipo === "objecao" && (!i.segmento || i.segmento === seg));
    const nomeSeg = capital(seg);

    const saida = $("#briefing-saida");
    saida.replaceChildren();
    const nomeTipo = { diagnostico: "diagnóstico", proposta: "proposta", negociacao: "negociação" }[tipo];
    saida.append(el("div", { class: "cab-briefing" },
      el("h2", { text: `Reunião de ${nomeTipo} · ${nomeSeg}` }),
      el("span", { class: "previa", text: "Prévia da T9 · cada ponto com a fonte" })));
    if (contexto) saida.append(el("p", { class: "contexto-briefing", text: `Contexto: ${contexto}` }));

    const grade = el("div", { class: "briefing-saida" });
    grade.append(bloco("Cases parecidos", "var(--ambar)", cases.length
      ? el("ul", {}, cases.map((c) => itemLista(`${c.resumo || c.titulo} [${c.codigo}]`, c)))
      : semBase(`A base não tem case de ${seg}.`)));
    grade.append(bloco(`O que sabemos de ${seg}`, "#93a6ff", perfil
      ? el("ul", {}, (perfil.pontos || [perfil.descricao]).map((p) => itemLista(`${p} [${perfil.codigo}]`, perfil)))
      : semBase(`A base não tem perfil do segmento ${seg}.`)));

    const passos = [];
    const diag = conducao[0];
    if (diag) {
      const deOutro = diag.segmento && diag.segmento !== seg ? ` (aprendizado de ${diag.segmento})` : "";
      passos.push([`Abra com diagnóstico, não com a solução: processo atual, onde dói, quanto custa o problema e quem decide${deOutro} [${diag.codigo}]`, diag]);
    }
    if (perfil) passos.push([`Confirme quem decide e quando: em rede, operações decide e o financeiro aprova; fuja da alta temporada [${perfil.codigo}]`, perfil]);
    if (cases[0] && tipo !== "diagnostico") passos.push([`Apresente o piloto em uma unidade, com a métrica do case como referência [${cases[0].codigo}]`, cases[0]]);
    if (diag) passos.push([`Ligue cada parte da solução a uma dor que o próprio cliente disse [${diag.codigo}]`, diag]);
    grade.append(bloco("Roteiro de condução", "var(--ciano)", passos.length
      ? el("ol", {}, passos.map(([t, it]) => itemLista(t, it)))
      : semBase("A base não tem material de condução de reunião."), "largo"));

    grade.append(bloco("Objeções prováveis", "var(--risco)", objecoes.length
      ? el("ul", {}, objecoes.map((o) => itemLista(`"Está caro": volte ao custo do problema e ofereça uma fase menor, não desconto [${o.codigo}]`, o)))
      : semBase("A base não tem objeções registradas para esse segmento.")));
    grade.append(bloco("Estrutura da proposta", "var(--ok)", cases.length
      ? el("ol", {},
        itemLista("Contexto e dores levantadas no diagnóstico"),
        itemLista(`Piloto em uma unidade com métrica clara [${cases[0].codigo}]`, cases[0]),
        itemLista(`Expansão condicionada ao resultado do piloto [${cases[0].codigo}]`, cases[0]),
        objecoes[0] ? itemLista(`Investimento e retorno, ancorados no custo do problema [${objecoes[0].codigo}]`, objecoes[0]) : null)
      : semBase(`A base não tem estrutura de proposta testada em ${seg}.`)));

    const lacunas = [`Nenhum item sobre preço praticado em ${seg}.`];
    if (!cases.length) lacunas.push(`Nenhum case de ${seg}.`);
    if (!perfil) lacunas.push(`Nenhum perfil do segmento ${seg}.`);
    if (!base.some((i) => i.secao === "pos_venda" && (!i.segmento || i.segmento === seg))) lacunas.push(`Nada sobre pós-venda em ${seg}.`);
    if (cases.length) lacunas.push("Nenhum case de rede com mais de 4 unidades.");
    grade.append(bloco("O que a base não cobre", "var(--ambar)", el("ul", {}, lacunas.map((l) => el("li", { text: l }))), "lacuna largo"));
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
    const autor = $("#autor");
    autor.value = guardar.ler("cerebro.autor") || "";
    autor.addEventListener("input", () => guardar.escrever("cerebro.autor", autor.value.trim()));

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
    // O 1º atalho é sobre o caso fictício de hotelaria: só existe na demonstração.
    const atalhos = ATALHOS_CHAT.filter((_, i) => !aoVivo() || i > 0);
    $("#atalhos-chat").replaceChildren(...atalhos.map(([rotulo, texto, cor]) =>
      el("button", { type: "button", class: "atalho", style: `--c:${cor}`, onclick: () => perguntar(texto) }, el("span", { class: "ponto" }), rotulo)));
  }

  async function iniciar() {
    pintarOrbes();
    cena.iniciar();
    ligarEventos();
    pintarTopo("conversar");
    estado.modo = await detectarModo();
    pintarModo();
    pintarAtalhosChat();
    if (aoVivo()) estado.itens = [];
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
