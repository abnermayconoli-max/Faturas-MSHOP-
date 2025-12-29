// URL base (vazio = mesmo domínio)
const API_BASE = "";

// ============ ESTADO (FILTROS) ============

// Filtros globais (sidebar + busca)
let filtroTransportadora = "";
let filtroVencimentoDe = "";
let filtroVencimentoAte = "";
let filtroNumeroFatura = "";

// Filtros só da aba Faturas
let filtroDataInicioFaturas = "";
let filtroDataFimFaturas = "";
let filtroStatus = "";

// modo do dashboard (pendente/pago)
let dashboardModo = "pendente";

// Cache da última lista vinda da API
let ultimaListaFaturas = [];
let ultimaListaHistorico = [];

// ✅ usuário logado (/me)
let usuarioLogado = null;

// ============ HELPERS ============

function formatCurrency(valor) {
  if (valor === null || valor === undefined) return "R$ 0,00";
  const n = Number(valor) || 0;
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
}

// converte string ISO (yyyy-mm-dd ou data completa) pra Date LOCAL
function parseISODateLocal(isoDate) {
  if (!isoDate) return null;

  if (/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    const [y, m, d] = isoDate.split("-").map(Number);
    return new Date(y, m - 1, d);
  }

  const d = new Date(isoDate);
  return Number.isNaN(d.getTime()) ? null : d;
}

// dd/mm/aaaa
function formatDate(isoDate) {
  if (!isoDate) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    const [y, m, d] = isoDate.split("-");
    return `${d}/${m}/${y}`;
  }
  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString("pt-BR");
}

function formatDateTime(isoDateTime) {
  if (!isoDateTime) return "";
  const d = new Date(isoDateTime);
  if (Number.isNaN(d.getTime())) return isoDateTime;
  return d.toLocaleString("pt-BR");
}

// ✅ fetch com tratamento de auth
async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);

  // se caiu sessão
  if (resp.status === 401) {
    window.location.href = "/login?next=/";
    return null;
  }
  // se precisa trocar senha
  if (resp.status === 403) {
    window.location.href = "/change-password";
    return null;
  }

  if (!resp.ok) {
    // tenta ler JSON detail
    let detalhe = "";
    try {
      const ct = resp.headers.get("content-type") || "";
      if (ct.includes("application/json")) {
        const j = await resp.json();
        detalhe = j?.detail ? String(j.detail) : JSON.stringify(j);
      } else {
        detalhe = await resp.text();
      }
    } catch (_) {}
    const err = new Error(`HTTP ${resp.status} - ${detalhe || "Erro"}`);
    err.status = resp.status;
    err.detail = detalhe;
    throw err;
  }

  const ct = resp.headers.get("content-type") || "";
  if (ct.includes("application/json")) return await resp.json();
  return await resp.text();
}

// ✅ carrega /me e preenche Perfil
async function carregarUsuarioLogado() {
  try {
    usuarioLogado = await fetchJson(`${API_BASE}/me`);
    renderPerfil();
  } catch (e) {
    console.error("Erro ao carregar /me:", e);
    // se der erro, não bloqueia o site
  }
}

// ✅ render perfil
function renderPerfil() {
  const box = document.getElementById("perfilBox");
  if (!box) return;

  if (!usuarioLogado) {
    box.innerHTML = `<p>Não foi possível carregar o perfil.</p>`;
    return;
  }

  const role = (usuarioLogado.role || "").toLowerCase();
  const isAdmin = role === "admin";

  box.innerHTML = `
    <div class="perfil-grid">
      <div class="perfil-card">
        <h3>Seu perfil</h3>
        <p><strong>Usuário:</strong> ${usuarioLogado.username || "-"}</p>
        <p><strong>Email:</strong> ${usuarioLogado.email || "-"}</p>
        <p><strong>Permissão:</strong> ${usuarioLogado.role || "-"}</p>
      </div>

      <div class="perfil-card">
        <h3>Ações</h3>
        <div class="perfil-actions">
          <a class="primary-link" href="/change-password">Trocar senha</a>
          <button id="btnLogout" type="button" class="btn-warn">Sair</button>
          ${
            isAdmin
              ? `<button id="btnAdmin" type="button" class="secondary">Configurações (Admin)</button>`
              : ""
          }
        </div>
        ${
          isAdmin
            ? `<p class="perfil-hint">Como admin, você pode cadastrar usuários, adicionar transportadoras e definir responsáveis.</p>`
            : `<p class="perfil-hint">Se você precisar de permissões de admin, fale com o administrador.</p>`
        }
      </div>
    </div>
  `;

  // listeners
  const btnLogout = document.getElementById("btnLogout");
  if (btnLogout) btnLogout.addEventListener("click", () => (window.location.href = "/logout"));

  const btnAdmin = document.getElementById("btnAdmin");
  if (btnAdmin) btnAdmin.addEventListener("click", () => (window.location.href = "/admin"));
}

// ============ DASHBOARD ============

async function carregarDashboard() {
  try {
    const titulo = document.getElementById("tituloResumoDashboard");
    if (titulo) titulo.textContent = "Resumo por transportadora";

    const params = new URLSearchParams();
    if (filtroTransportadora) params.append("transportadora", filtroTransportadora);
    if (filtroVencimentoDe) params.append("de_vencimento", filtroVencimentoDe);
    if (filtroVencimentoAte) params.append("ate_vencimento", filtroVencimentoAte);

    const urlResumo =
      params.toString().length > 0
        ? `${API_BASE}/dashboard/resumo?${params.toString()}`
        : `${API_BASE}/dashboard/resumo`;

    const dataResumo = await fetchJson(urlResumo);
    if (!dataResumo) return;

    const boxTotalGeral = document.getElementById("cardTotalGeralBox");
    const boxEmDia = document.getElementById("cardEmDiaBox");
    const boxAtrasado = document.getElementById("cardAtrasadoBox");
    const boxPago = document.getElementById("cardPagoBox");

    const elTotalGeral = document.getElementById("cardTotalGeral");
    const elEmDia = document.getElementById("cardEmDia");
    const elAtrasado = document.getElementById("cardAtrasado");
    const elPago = document.getElementById("cardPago");

    const cardsWrap = document.getElementById("cardsDashboard");

    if (dashboardModo === "pago") {
      if (boxTotalGeral) boxTotalGeral.style.display = "none";
      if (boxEmDia) boxEmDia.style.display = "none";
      if (boxAtrasado) boxAtrasado.style.display = "none";
      if (boxPago) boxPago.style.display = "block";
      if (cardsWrap) cardsWrap.classList.add("pago-only");

      if (elPago) elPago.textContent = formatCurrency(dataResumo.total_pago ?? 0);
    } else {
      if (boxTotalGeral) boxTotalGeral.style.display = "block";
      if (boxEmDia) boxEmDia.style.display = "block";
      if (boxAtrasado) boxAtrasado.style.display = "block";
      if (boxPago) boxPago.style.display = "none";
      if (cardsWrap) cardsWrap.classList.remove("pago-only");

      if (elTotalGeral) elTotalGeral.textContent = formatCurrency(dataResumo.total_geral ?? 0);
      if (elEmDia) elEmDia.textContent = formatCurrency(dataResumo.total_em_dia ?? 0);
      if (elAtrasado) elAtrasado.textContent = formatCurrency(dataResumo.total_atrasado ?? 0);
      if (elPago) elPago.textContent = formatCurrency(dataResumo.total_pago ?? 0);
    }

    let lista = Array.isArray(ultimaListaFaturas) ? [...ultimaListaFaturas] : [];
    if (lista.length === 0) {
      const urlF =
        params.toString().length > 0
          ? `${API_BASE}/faturas?${params.toString()}`
          : `${API_BASE}/faturas`;

      lista = await fetchJson(urlF);
      if (!lista) return;
    }

    if (dashboardModo === "pago") {
      renderResumoDashboardPago(lista);
    } else {
      renderResumoDashboardPendente(lista);
    }
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar dashboard");
  }
}

// ======== DASHBOARD: PENDENTE ========

function renderResumoDashboardPendente(lista) {
  const thead = document.getElementById("theadResumoDashboard");
  const tbody = document.getElementById("tbodyResumoDashboard");
  if (!thead || !tbody) return;

  // datas pendente/atrasado
  const datasSet = new Set();
  (lista || []).forEach((f) => {
    const st = (f.status || "").toLowerCase();
    if (st !== "pago" && f.data_vencimento) datasSet.add(f.data_vencimento);
  });
  const datas = Array.from(datasSet).sort();

  // header
  let headerHtml = `
    <tr>
      <th>Responsável</th>
      <th>Transportadora</th>
      <th>Total atrasado</th>
      <th>Total em dia</th>
      <th>Total geral</th>
  `;
  datas.forEach((d) => (headerHtml += `<th>${formatDate(d)}</th>`));
  headerHtml += "</tr>";
  thead.innerHTML = headerHtml;

  // calcular corte: "quarta da próxima semana" quando hoje é segunda, senão próxima quarta normal.
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);

  // próxima quarta (dom=0, seg=1, ter=2, qua=3)
  const wd = hoje.getDay();
  let diasAteQuarta = (3 - wd + 7) % 7;
  if (diasAteQuarta === 0) diasAteQuarta = 7;
  let inicioEmDia = new Date(hoje);
  inicioEmDia.setDate(hoje.getDate() + diasAteQuarta);

  // ✅ se HOJE é SEGUNDA (1), pula mais 7 dias (vira a quarta da semana seguinte)
  if (wd === 1) {
    inicioEmDia.setDate(inicioEmDia.getDate() + 7);
  }
  inicioEmDia.setHours(0, 0, 0, 0);
  const inicioTime = inicioEmDia.getTime();

  // agrupa por transportadora, mantendo o responsavel
  const grupos = {};
  (lista || []).forEach((f) => {
    const transp = f.transportadora || "Sem nome";
    const resp = f.responsavel || "";
    if (!grupos[transp]) {
      grupos[transp] = {
        responsavel: resp,
        totalAtrasado: 0,
        totalEmDia: 0,
        totalGeral: 0,
        porData: {},
      };
    }
    if (!grupos[transp].responsavel && resp) grupos[transp].responsavel = resp;

    const valor = Number(f.valor || 0);
    const st = (f.status || "").toLowerCase();
    if (st === "pago") return;

    grupos[transp].totalGeral += valor;

    const d = parseISODateLocal(f.data_vencimento);
    const vencTime = d ? d.setHours(0, 0, 0, 0) : null;

    if (vencTime !== null) {
      if (st === "atrasado") {
        grupos[transp].totalAtrasado += valor;
      } else if (st === "pendente") {
        // ✅ regra: em dia = vencimento >= inicioEmDia
        if (vencTime < inicioTime) grupos[transp].totalAtrasado += valor;
        else grupos[transp].totalEmDia += valor;
      }
    }

    const key = f.data_vencimento;
    grupos[transp].porData[key] = (grupos[transp].porData[key] || 0) + valor;
  });

  // ordem fixa (para garantir agrupamento bonito por responsável)
  const transpOrder = ["DHL", "Pannan", "Transbritto", "PDA", "GLM", "Garcia", "Excargo"];
  const ordem = Object.keys(grupos).sort((a, b) => {
    const ia = transpOrder.indexOf(a);
    const ib = transpOrder.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });

  tbody.innerHTML = "";

  // totais gerais
  let totalGeralAtrasado = 0;
  let totalGeralEmDia = 0;
  let totalGeral = 0;
  const totaisPorData = {};

  // subtotal por responsável
  let respAtual = null;
  let subAtrasado = 0;
  let subEmDia = 0;
  let subGeral = 0;
  let subPorData = {};

  function flushSubtotalResponsavel() {
    if (!respAtual) return;

    const trTotalResp = document.createElement("tr");
    let html = `
      <td><strong>${respAtual || "-"}</strong></td>
      <td><strong>Total</strong></td>
      <td><strong>${formatCurrency(subAtrasado)}</strong></td>
      <td><strong>${formatCurrency(subEmDia)}</strong></td>
      <td><strong>${formatCurrency(subGeral)}</strong></td>
    `;
    datas.forEach((d) => {
      const v = subPorData[d] || 0;
      html += `<td><strong>${v ? formatCurrency(v) : "-"}</strong></td>`;
    });
    trTotalResp.innerHTML = html;
    tbody.appendChild(trTotalResp);

    // ✅ linha em branco (igual na sua 1ª imagem)
    const spacer = document.createElement("tr");
    spacer.className = "spacer-row";
    spacer.innerHTML = `<td colspan="${5 + datas.length}">&nbsp;</td>`;
    tbody.appendChild(spacer);

    // reseta subtotais
    subAtrasado = 0;
    subEmDia = 0;
    subGeral = 0;
    subPorData = {};
  }

  ordem.forEach((transp) => {
    const g = grupos[transp];
    const resp = g.responsavel || "-";

    // quando muda o responsável, fecha o subtotal do anterior
    if (respAtual === null) respAtual = resp;
    if (resp !== respAtual) {
      flushSubtotalResponsavel();
      respAtual = resp;
    }

    // acumula total geral
    totalGeralAtrasado += g.totalAtrasado;
    totalGeralEmDia += g.totalEmDia;
    totalGeral += g.totalGeral;

    // acumula subtotal do responsável
    subAtrasado += g.totalAtrasado;
    subEmDia += g.totalEmDia;
    subGeral += g.totalGeral;

    datas.forEach((d) => {
      const v = g.porData[d] || 0;
      totaisPorData[d] = (totaisPorData[d] || 0) + v;
      subPorData[d] = (subPorData[d] || 0) + v;
    });

    // linha normal
    const tr = document.createElement("tr");
    let html = `
      <td>${g.responsavel || "-"}</td>
      <td>${transp}</td>
      <td>${formatCurrency(g.totalAtrasado)}</td>
      <td>${formatCurrency(g.totalEmDia)}</td>
      <td>${formatCurrency(g.totalGeral)}</td>
    `;
    datas.forEach((d) => {
      const val = g.porData[d] || 0;
      html += `<td>${val ? formatCurrency(val) : "-"}</td>`;
    });
    tr.innerHTML = html;
    tbody.appendChild(tr);
  });

  // fecha o último responsável
  if (ordem.length > 0) flushSubtotalResponsavel();

  // total geral final
  if (Object.keys(grupos).length > 0) {
    const trTotal = document.createElement("tr");
    let html = `
      <td><strong>-</strong></td>
      <td><strong>Total geral</strong></td>
      <td><strong>${formatCurrency(totalGeralAtrasado)}</strong></td>
      <td><strong>${formatCurrency(totalGeralEmDia)}</strong></td>
      <td><strong>${formatCurrency(totalGeral)}</strong></td>
    `;
    datas.forEach((d) => {
      const v = totaisPorData[d] || 0;
      html += `<td><strong>${v ? formatCurrency(v) : "-"}</strong></td>`;
    });
    trTotal.innerHTML = html;
    tbody.appendChild(trTotal);
  }
}

// ======== DASHBOARD: PAGO ========

function renderResumoDashboardPago(lista) {
  const thead = document.getElementById("theadResumoDashboard");
  const tbody = document.getElementById("tbodyResumoDashboard");
  if (!thead || !tbody) return;

  const pagos = (lista || []).filter((f) => (f.status || "").toLowerCase() === "pago");

  const datasSet = new Set();
  pagos.forEach((f) => {
    if (f.data_vencimento) datasSet.add(f.data_vencimento);
  });
  const datas = Array.from(datasSet).sort();

  let headerHtml = `
    <tr>
      <th>Responsável</th>
      <th>Transportadora</th>
      <th>Total pago</th>
  `;
  datas.forEach((d) => (headerHtml += `<th>${formatDate(d)}</th>`));
  headerHtml += `</tr>`;
  thead.innerHTML = headerHtml;

  const grupos = {};
  pagos.forEach((f) => {
    const transp = f.transportadora || "Sem nome";
    const resp = f.responsavel || "";
    if (!grupos[transp]) grupos[transp] = { responsavel: resp, totalPago: 0, porData: {} };
    if (!grupos[transp].responsavel && resp) grupos[transp].responsavel = resp;

    const valor = Number(f.valor || 0);
    grupos[transp].totalPago += valor;

    const key = f.data_vencimento;
    grupos[transp].porData[key] = (grupos[transp].porData[key] || 0) + valor;
  });

  // ordem fixa (igual pendente)
  const transpOrder = ["DHL", "Pannan", "Transbritto", "PDA", "GLM", "Garcia", "Excargo"];
  const ordem = Object.keys(grupos).sort((a, b) => {
    const ia = transpOrder.indexOf(a);
    const ib = transpOrder.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });

  tbody.innerHTML = "";

  const totaisPorData = {};
  let totalGeralPago = 0;

  // subtotal por responsável
  let respAtual = null;
  let subPago = 0;
  let subPorData = {};

  function flushSubtotalResponsavel() {
    if (!respAtual) return;

    const trTotalResp = document.createElement("tr");
    let html = `
      <td><strong>${respAtual || "-"}</strong></td>
      <td><strong>Total</strong></td>
      <td><strong>${formatCurrency(subPago)}</strong></td>
    `;
    datas.forEach((d) => {
      const v = subPorData[d] || 0;
      html += `<td><strong>${v ? formatCurrency(v) : "-"}</strong></td>`;
    });
    trTotalResp.innerHTML = html;
    tbody.appendChild(trTotalResp);

    // ✅ linha em branco
    const spacer = document.createElement("tr");
    spacer.className = "spacer-row";
    spacer.innerHTML = `<td colspan="${3 + datas.length}">&nbsp;</td>`;
    tbody.appendChild(spacer);

    subPago = 0;
    subPorData = {};
  }

  ordem.forEach((transp) => {
    const g = grupos[transp];
    const resp = g.responsavel || "-";

    if (respAtual === null) respAtual = resp;
    if (resp !== respAtual) {
      flushSubtotalResponsavel();
      respAtual = resp;
    }

    totalGeralPago += g.totalPago;

    datas.forEach((d) => {
      const v = g.porData[d] || 0;
      totaisPorData[d] = (totaisPorData[d] || 0) + v;
      subPorData[d] = (subPorData[d] || 0) + v;
    });
    subPago += g.totalPago;

    const tr = document.createElement("tr");
    let html = `
      <td>${g.responsavel || "-"}</td>
      <td>${transp}</td>
      <td>${formatCurrency(g.totalPago)}</td>
    `;
    datas.forEach((d) => {
      const val = g.porData[d] || 0;
      html += `<td>${val ? formatCurrency(val) : "-"}</td>`;
    });

    tr.innerHTML = html;
    tbody.appendChild(tr);
  });

  if (ordem.length > 0) flushSubtotalResponsavel();

  // total geral
  const trTotal = document.createElement("tr");
  let html = `
    <td><strong>-</strong></td>
    <td><strong>Total pago</strong></td>
    <td><strong>${formatCurrency(totalGeralPago)}</strong></td>
  `;
  datas.forEach((d) => {
    const v = totaisPorData[d] || 0;
    html += `<td><strong>${v ? formatCurrency(v) : "-"}</strong></td>`;
  });
  trTotal.innerHTML = html;
  tbody.appendChild(trTotal);
}

// ============ FATURAS (LISTA + RESUMO) ============

async function carregarFaturas() {
  try {
    const params = new URLSearchParams();
    if (filtroTransportadora) params.append("transportadora", filtroTransportadora);
    if (filtroVencimentoDe) params.append("de_vencimento", filtroVencimentoDe);
    if (filtroVencimentoAte) params.append("ate_vencimento", filtroVencimentoAte);
    if (filtroNumeroFatura) params.append("numero_fatura", filtroNumeroFatura);

    const url =
      params.toString().length > 0
        ? `${API_BASE}/faturas?${params.toString()}`
        : `${API_BASE}/faturas`;

    const faturas = await fetchJson(url);
    if (!faturas) return;

    ultimaListaFaturas = faturas;

    renderizarFaturas();
    carregarDashboard();
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar faturas");
  }
}

function renderizarFaturas() {
  const tbody = document.getElementById("tbodyFaturas");
  if (!tbody) return;

  tbody.innerHTML = "";

  let lista = Array.isArray(ultimaListaFaturas) ? [...ultimaListaFaturas] : [];

  if (filtroDataInicioFaturas || filtroDataFimFaturas) {
    lista = lista.filter((f) => {
      if (!f.data_vencimento) return false;
      const d = parseISODateLocal(f.data_vencimento);
      if (!d) return false;
      const time = d.setHours(0, 0, 0, 0);

      if (filtroDataInicioFaturas) {
        const dIni = parseISODateLocal(filtroDataInicioFaturas);
        if (!dIni) return false;
        const ini = dIni.setHours(0, 0, 0, 0);
        if (time < ini) return false;
      }

      if (filtroDataFimFaturas) {
        const dFim = parseISODateLocal(filtroDataFimFaturas);
        if (!dFim) return false;
        const fim = dFim.setHours(0, 0, 0, 0);
        if (time > fim) return false;
      }

      return true;
    });
  }

  if (filtroStatus) {
    const alvo = filtroStatus.toLowerCase();
    lista = lista.filter((f) => (f.status || "").toLowerCase() === alvo);
  }

  let total = 0;
  let pendentes = 0;
  let atrasadas = 0;
  let pagas = 0;

  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const hojeTime = hoje.getTime();

  lista.forEach((f) => {
    const valor = Number(f.valor || 0);
    total += valor;

    const status = (f.status || "").toLowerCase();
    const d = parseISODateLocal(f.data_vencimento);
    const vencTime = d ? d.setHours(0, 0, 0, 0) : null;

    if (status === "pago") {
      pagas += valor;
    } else if (status === "pendente") {
      if (vencTime !== null && vencTime < hojeTime) atrasadas += valor;
      else pendentes += valor;
    } else if (status === "atrasado") {
      atrasadas += valor;
    }
  });

  const elTotal = document.getElementById("fatTotal");
  const elPend = document.getElementById("fatPendentes");
  const elAtr = document.getElementById("fatAtrasadas");
  const elPag = document.getElementById("fatPagas");
  if (elTotal) elTotal.textContent = formatCurrency(total);
  if (elPend) elPend.textContent = formatCurrency(pendentes);
  if (elAtr) elAtr.textContent = formatCurrency(atrasadas);
  if (elPag) elPag.textContent = formatCurrency(pagas);

  if (lista.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 10;
    td.textContent = "Nenhuma fatura encontrada.";
    td.style.textAlign = "center";
    td.style.padding = "12px";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  lista.forEach((f) => {
    const tr = document.createElement("tr");
    tr.dataset.faturaId = f.id;

    tr.innerHTML = `
      <td>${f.id}</td>
      <td>${f.transportadora}</td>
      <td>${f.responsavel ?? ""}</td>
      <td>${f.numero_fatura}</td>
      <td>${formatCurrency(f.valor)}</td>
      <td>${formatDate(f.data_vencimento)}</td>
      <td>${f.status}</td>
      <td>${f.observacao ?? ""}</td>
      <td>${f.data_pagamento ? formatDate(f.data_pagamento) : "-"}</td>
      <td class="acoes">
        <button type="button" class="menu-btn" aria-label="Ações">⋮</button>
        <div class="menu-dropdown">
          <button type="button" data-acao="editar">Editar</button>
          <button type="button" data-acao="excluir">Excluir</button>
          <button type="button" data-acao="anexos">Anexos</button>
        </div>
      </td>
    `;

    tbody.appendChild(tr);
  });
}

// ============ HISTÓRICO ============

async function carregarHistorico() {
  try {
    const params = new URLSearchParams();
    if (filtroTransportadora) params.append("transportadora", filtroTransportadora);

    const url =
      params.toString().length > 0
        ? `${API_BASE}/historico_pagamentos?${params.toString()}`
        : `${API_BASE}/historico_pagamentos`;

    const hist = await fetchJson(url);
    if (!hist) return;

    ultimaListaHistorico = hist;

    renderizarHistorico();
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar histórico");
  }
}

function renderizarHistorico() {
  const tbody = document.getElementById("tbodyHistorico");
  if (!tbody) return;

  tbody.innerHTML = "";

  const lista = Array.isArray(ultimaListaHistorico) ? [...ultimaListaHistorico] : [];

  if (lista.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 8;
    td.textContent = "Nenhum pagamento registrado.";
    td.style.textAlign = "center";
    td.style.padding = "12px";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  lista.forEach((h) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${h.id}</td>
      <td>${h.fatura_id}</td>
      <td>${h.transportadora}</td>
      <td>${h.responsavel ?? ""}</td>
      <td>${h.numero_fatura}</td>
      <td>${formatCurrency(h.valor)}</td>
      <td>${formatDate(h.data_vencimento)}</td>
      <td>${formatDateTime(h.pago_em)}</td>
    `;
    tbody.appendChild(tr);
  });
}

function exportarHistorico() {
  const params = new URLSearchParams();
  if (filtroTransportadora) params.append("transportadora", filtroTransportadora);

  const url =
    params.toString().length > 0
      ? `${API_BASE}/historico_pagamentos/exportar?${params.toString()}`
      : `${API_BASE}/historico_pagamentos/exportar`;

  window.open(url, "_blank");
}

// ============ MENU 3 PONTINHOS (DELEGAÇÃO) ============

function fecharTodosMenus() {
  document.querySelectorAll(".menu-dropdown.ativo").forEach((m) => {
    m.classList.remove("ativo");
    m.style.position = "";
    m.style.left = "";
    m.style.top = "";
    m.style.right = "";
    m.style.bottom = "";
    m.style.maxHeight = "";
    m.style.overflowY = "";
  });
}

function setupMenuDelegation() {
  const tbody = document.getElementById("tbodyFaturas");
  if (!tbody) return;

  tbody.addEventListener("click", async (e) => {
    const menuBtn = e.target.closest(".menu-btn");
    const acaoBtn = e.target.closest(".menu-dropdown button[data-acao]");

    if (menuBtn) {
      e.preventDefault();
      e.stopPropagation();

      const acoesCell = menuBtn.closest(".acoes");
      const dropdown = acoesCell ? acoesCell.querySelector(".menu-dropdown") : null;
      const jaAberto = dropdown && dropdown.classList.contains("ativo");

      fecharTodosMenus();
      if (!dropdown || jaAberto) return;

      dropdown.classList.add("ativo");

      const btnRect = menuBtn.getBoundingClientRect();

      dropdown.style.position = "fixed";
      dropdown.style.left = "0px";
      dropdown.style.top = "0px";

      const dropRect = dropdown.getBoundingClientRect();
      const dropH = dropRect.height || 180;

      const margem = 8;
      const spaceBelow = window.innerHeight - btnRect.bottom;
      const spaceAbove = btnRect.top;

      const left = Math.max(margem, btnRect.right - dropRect.width);
      dropdown.style.left = `${left}px`;

      if (spaceBelow >= dropH + margem) {
        dropdown.style.top = `${btnRect.bottom + margem}px`;
      } else if (spaceAbove >= dropH + margem) {
        dropdown.style.top = `${btnRect.top - dropH - margem}px`;
      } else {
        if (spaceBelow >= spaceAbove) {
          dropdown.style.top = `${btnRect.bottom + margem}px`;
          dropdown.style.maxHeight = `${Math.max(120, spaceBelow - 2 * margem)}px`;
        } else {
          dropdown.style.top = `${margem}px`;
          dropdown.style.maxHeight = `${Math.max(120, spaceAbove - 2 * margem)}px`;
        }
        dropdown.style.overflowY = "auto";
      }

      return;
    }

    if (acaoBtn) {
      e.preventDefault();
      e.stopPropagation();

      const acao = acaoBtn.dataset.acao;
      const tr = acaoBtn.closest("tr");
      const id = tr ? tr.dataset.faturaId : null;
      if (!id) return;

      const faturaObj = (ultimaListaFaturas || []).find((f) => String(f.id) === String(id));

      if (acao === "excluir") {
        await excluirFatura(id);
      } else if (acao === "editar") {
        if (faturaObj) preencherFormularioEdicao(faturaObj);
      } else if (acao === "anexos") {
        abrirModalAnexos(id);
      }

      fecharTodosMenus();
    }
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest(".menu-dropdown") || e.target.closest(".menu-btn")) return;
    fecharTodosMenus();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") fecharTodosMenus();
  });
}

// ============ EXCLUIR / EDITAR / ANEXOS ============

async function excluirFatura(id) {
  if (!confirm(`Excluir fatura ${id}?`)) return;

  try {
    await fetchJson(`${API_BASE}/faturas/${id}`, { method: "DELETE" });
    await carregarFaturas();
    await carregarHistorico();
  } catch (err) {
    console.error(err);
    alert("Erro ao excluir fatura");
  }
}

function preencherFormularioEdicao(f) {
  ativarAba("cadastro");
  document.getElementById("inputTransportadora").value = f.transportadora;
  document.getElementById("inputNumeroFatura").value = f.numero_fatura;
  document.getElementById("inputValor").value = f.valor;
  document.getElementById("inputVencimento").value = f.data_vencimento;
  document.getElementById("inputStatus").value = f.status;
  document.getElementById("inputObservacao").value = f.observacao ?? "";
  document.getElementById("formFatura").dataset.editId = f.id;
}

async function abrirModalAnexos(faturaId) {
  document.getElementById("modalFaturaId").textContent = faturaId;
  const lista = document.getElementById("listaAnexos");
  lista.innerHTML = "Carregando...";

  try {
    const anexos = await fetchJson(`${API_BASE}/faturas/${faturaId}/anexos`);
    if (!anexos) return;

    if (!anexos.length) {
      lista.innerHTML = "<li>Sem anexos.</li>";
    } else {
      lista.innerHTML = "";

      anexos.forEach((a) => {
        const li = document.createElement("li");

        const link = document.createElement("a");
        link.href = `${API_BASE}/anexos/${a.id}`;
        link.target = "_blank";
        link.textContent = a.original_name;

        const btnExcluir = document.createElement("button");
        btnExcluir.type = "button";
        btnExcluir.className = "btn-excluir-anexo";
        btnExcluir.textContent = "Excluir";

        btnExcluir.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();

          if (!confirm(`Excluir o anexo "${a.original_name}"?`)) return;

          try {
            await fetchJson(`${API_BASE}/anexos/${a.id}`, { method: "DELETE" });
            abrirModalAnexos(faturaId);
          } catch (err) {
            console.error(err);
            alert("Erro ao excluir anexo");
          }
        });

        li.appendChild(link);
        li.appendChild(btnExcluir);
        lista.appendChild(li);
      });
    }
  } catch (err) {
    console.error(err);
    lista.innerHTML = "<li>Erro ao carregar anexos.</li>";
  }

  document.getElementById("modalAnexos").classList.add("open");
}

// ============ FORMULÁRIO ============

async function salvarFatura(e) {
  e.preventDefault();

  const form = document.getElementById("formFatura");
  const editId = form.dataset.editId || null;

  const payload = {
    transportadora: document.getElementById("inputTransportadora").value,
    numero_fatura: document.getElementById("inputNumeroFatura").value,
    valor: parseFloat(document.getElementById("inputValor").value || "0"),
    data_vencimento: document.getElementById("inputVencimento").value,
    status: document.getElementById("inputStatus").value,
    observacao: document.getElementById("inputObservacao").value || null,
  };

  try {
    let resp;

    if (editId) {
      resp = await fetchJson(`${API_BASE}/faturas/${editId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      resp = await fetchJson(`${API_BASE}/faturas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }

    if (!resp) return;

    const fatura = resp;

    const inputAnexos = document.getElementById("inputAnexos");
    if (inputAnexos && inputAnexos.files && inputAnexos.files.length > 0) {
      const fd = new FormData();
      for (const file of inputAnexos.files) fd.append("files", file);

      try {
        await fetchJson(`${API_BASE}/faturas/${fatura.id}/anexos`, {
          method: "POST",
          body: fd,
        });
        inputAnexos.value = "";
      } catch (e) {
        console.error("Erro upload anexos:", e);
        alert(`A fatura foi salva, mas o upload do anexo FALHOU.\n\n${e.message || ""}`);
      }
    }

    form.reset();
    delete form.dataset.editId;

    await carregarFaturas();
    await carregarHistorico();
    ativarAba("faturas");
  } catch (err) {
    console.error(err);
    alert("Erro ao salvar fatura");
  }
}

// ============ ABAS / NAVEGAÇÃO ============

function ativarAba(aba) {
  const dash = document.getElementById("dashboardSection");
  const cad = document.getElementById("cadastroSection");
  const fat = document.getElementById("faturasSection");
  const hist = document.getElementById("historicoSection");
  const perfil = document.getElementById("perfilSection"); // ✅ novo

  const tabDash = document.getElementById("tabDashboard");
  const tabCad = document.getElementById("tabCadastro");
  const tabFat = document.getElementById("tabFaturas");
  const tabHist = document.getElementById("tabHistorico");
  const tabPerfil = document.getElementById("tabPerfil"); // ✅ novo

  [dash, cad, fat, hist, perfil].forEach((s) => {
    if (s) s.classList.remove("visible");
  });

  [tabDash, tabCad, tabFat, tabHist, tabPerfil].forEach((t) => {
    if (t) t.classList.remove("active");
  });

  if (aba === "dashboard") {
    dash.classList.add("visible");
    tabDash.classList.add("active");
  } else if (aba === "cadastro") {
    cad.classList.add("visible");
    tabCad.classList.add("active");
  } else if (aba === "historico") {
    hist.classList.add("visible");
    tabHist.classList.add("active");
    carregarHistorico();
  } else if (aba === "perfil") {
    if (perfil) perfil.classList.add("visible");
    if (tabPerfil) tabPerfil.classList.add("active");
    renderPerfil();
  } else {
    fat.classList.add("visible");
    tabFat.classList.add("active");
  }
}

// ============ EXPORTAR EXCEL (CSV) ============

function exportarExcel() {
  const params = new URLSearchParams();
  if (filtroTransportadora) params.append("transportadora", filtroTransportadora);
  if (filtroNumeroFatura) params.append("numero_fatura", filtroNumeroFatura);

  const url =
    params.toString().length > 0
      ? `${API_BASE}/faturas/exportar?${params.toString()}`
      : `${API_BASE}/faturas/exportar`;

  window.open(url, "_blank");
}

// ============ INIT ============

document.addEventListener("DOMContentLoaded", () => {
  setupMenuDelegation();

  const tabDashboard = document.getElementById("tabDashboard");
  const tabCadastro = document.getElementById("tabCadastro");
  const tabFaturas = document.getElementById("tabFaturas");
  const tabHistorico = document.getElementById("tabHistorico");
  const tabPerfil = document.getElementById("tabPerfil"); // ✅ novo

  if (tabDashboard) tabDashboard.addEventListener("click", () => ativarAba("dashboard"));
  if (tabCadastro) tabCadastro.addEventListener("click", () => ativarAba("cadastro"));
  if (tabFaturas) tabFaturas.addEventListener("click", () => ativarAba("faturas"));
  if (tabHistorico) tabHistorico.addEventListener("click", () => ativarAba("historico"));
  if (tabPerfil) tabPerfil.addEventListener("click", () => ativarAba("perfil"));

  const btnPend = document.getElementById("btnDashboardPendente");
  const btnPago = document.getElementById("btnDashboardPago");

  if (btnPend && btnPago) {
    btnPend.addEventListener("click", () => {
      dashboardModo = "pendente";
      btnPend.classList.add("active");
      btnPago.classList.remove("active");
      carregarDashboard();
    });

    btnPago.addEventListener("click", () => {
      dashboardModo = "pago";
      btnPago.classList.add("active");
      btnPend.classList.remove("active");
      carregarDashboard();
    });
  }

  const btnHome = document.getElementById("btnHome");
  if (btnHome) {
    btnHome.addEventListener("click", () => {
      filtroTransportadora = "";
      filtroVencimentoDe = "";
      filtroVencimentoAte = "";
      filtroNumeroFatura = "";
      filtroDataInicioFaturas = "";
      filtroDataFimFaturas = "";
      filtroStatus = "";

      const de = document.getElementById("filtroVencimentoDe");
      const ate = document.getElementById("filtroVencimentoAte");
      if (de) de.value = "";
      if (ate) ate.value = "";

      const buscaNumero = document.getElementById("buscaNumero");
      if (buscaNumero) buscaNumero.value = "";

      const ini = document.getElementById("filtroDataInicioFaturas");
      const fim = document.getElementById("filtroDataFimFaturas");
      if (ini) ini.value = "";
      if (fim) fim.value = "";

      const statusSelect = document.getElementById("filtroStatus");
      if (statusSelect) statusSelect.value = "";

      document.querySelectorAll(".transportadora-btn").forEach((b) => b.classList.remove("selected"));

      dashboardModo = "pendente";
      if (btnPend && btnPago) {
        btnPend.classList.add("active");
        btnPago.classList.remove("active");
      }

      ativarAba("dashboard");
      carregarFaturas();
      carregarHistorico();
    });
  }

  document.querySelectorAll(".transportadora-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      filtroTransportadora = btn.dataset.transportadora || "";
      document.querySelectorAll(".transportadora-btn").forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
      carregarFaturas();
      carregarHistorico();
    })
  );

  const inputDe = document.getElementById("filtroVencimentoDe");
  const inputAte = document.getElementById("filtroVencimentoAte");

  if (inputDe) {
    inputDe.addEventListener("change", (e) => {
      filtroVencimentoDe = e.target.value;
      carregarFaturas();
    });
  }
  if (inputAte) {
    inputAte.addEventListener("change", (e) => {
      filtroVencimentoAte = e.target.value;
      carregarFaturas();
    });
  }

  const btnLimparFiltros = document.getElementById("btnLimparFiltros");
  if (btnLimparFiltros) {
    btnLimparFiltros.addEventListener("click", () => {
      filtroVencimentoDe = "";
      filtroVencimentoAte = "";
      filtroNumeroFatura = "";
      filtroDataInicioFaturas = "";
      filtroDataFimFaturas = "";
      filtroStatus = "";

      if (inputDe) inputDe.value = "";
      if (inputAte) inputAte.value = "";

      const buscaNumero = document.getElementById("buscaNumero");
      if (buscaNumero) buscaNumero.value = "";

      const ini = document.getElementById("filtroDataInicioFaturas");
      const fim = document.getElementById("filtroDataFimFaturas");
      if (ini) ini.value = "";
      if (fim) fim.value = "";

      const statusSelect = document.getElementById("filtroStatus");
      if (statusSelect) statusSelect.value = "";

      carregarFaturas();
      carregarHistorico();
    });
  }

  const btnLimparPeriodoFaturas = document.getElementById("btnLimparPeriodoFaturas");
  if (btnLimparPeriodoFaturas) {
    btnLimparPeriodoFaturas.addEventListener("click", () => {
      filtroDataInicioFaturas = "";
      filtroDataFimFaturas = "";

      const ini = document.getElementById("filtroDataInicioFaturas");
      const fim = document.getElementById("filtroDataFimFaturas");
      if (ini) ini.value = "";
      if (fim) fim.value = "";

      renderizarFaturas();
    });
  }

  const buscaNumero = document.getElementById("buscaNumero");
  if (buscaNumero) {
    buscaNumero.addEventListener("input", (e) => {
      filtroNumeroFatura = e.target.value.trim();
      carregarFaturas();
    });
  }

  const ini = document.getElementById("filtroDataInicioFaturas");
  const fim = document.getElementById("filtroDataFimFaturas");
  if (ini) ini.addEventListener("change", (e) => ((filtroDataInicioFaturas = e.target.value), renderizarFaturas()));
  if (fim) fim.addEventListener("change", (e) => ((filtroDataFimFaturas = e.target.value), renderizarFaturas()));

  const statusSelect = document.getElementById("filtroStatus");
  if (statusSelect) statusSelect.addEventListener("change", (e) => ((filtroStatus = e.target.value), renderizarFaturas()));

  const btnAtualizar = document.getElementById("btnAtualizarFaturas");
  if (btnAtualizar) btnAtualizar.addEventListener("click", (e) => (e.preventDefault(), carregarFaturas()));

  const btnExportar = document.getElementById("btnExportarExcel");
  if (btnExportar) btnExportar.addEventListener("click", exportarExcel);

  // ✅ histórico botões
  const btnAtualizarHistorico = document.getElementById("btnAtualizarHistorico");
  if (btnAtualizarHistorico) btnAtualizarHistorico.addEventListener("click", (e) => (e.preventDefault(), carregarHistorico()));

  const btnExportarHistorico = document.getElementById("btnExportarHistorico");
  if (btnExportarHistorico) btnExportarHistorico.addEventListener("click", exportarHistorico);

  const formFatura = document.getElementById("formFatura");
  if (formFatura) formFatura.addEventListener("submit", salvarFatura);

  const modalFechar = document.getElementById("modalFechar");
  if (modalFechar)
    modalFechar.addEventListener("click", () => document.getElementById("modalAnexos").classList.remove("open"));

  const modal = document.getElementById("modalAnexos");
  if (modal)
    modal.addEventListener("click", (e) => {
      if (e.target.id === "modalAnexos") document.getElementById("modalAnexos").classList.remove("open");
    });

  // ✅ carrega tudo
  carregarUsuarioLogado(); // perfil (e valida sessão)
  carregarFaturas();
  carregarHistorico();
});
