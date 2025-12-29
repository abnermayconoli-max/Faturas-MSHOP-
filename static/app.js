// URL base (vazio = mesmo domínio)
const API_BASE = "";

// ============ ESTADO (FILTROS) ============
let filtroTransportadora = "";
let filtroVencimentoDe = "";
let filtroVencimentoAte = "";
let filtroNumeroFatura = "";

let filtroDataInicioFaturas = "";
let filtroDataFimFaturas = "";
let filtroStatus = "";

let dashboardModo = "pendente";

let ultimaListaFaturas = [];
let ultimaListaHistorico = [];

// cache do usuário logado
let currentUser = null;

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

function parseISODateLocal(isoDate) {
  if (!isoDate) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    const [y, m, d] = isoDate.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  const d = new Date(isoDate);
  return Number.isNaN(d.getTime()) ? null : d;
}

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

// fetch padrão com cookie (sessão)
async function apiFetch(url, options = {}) {
  const opts = {
    credentials: "include",
    ...options,
  };
  const resp = await fetch(url, opts);

  if (resp.status === 401) {
    alert("Sessão expirada. Faça login novamente.");
    window.location.href = "/"; // se tiver página de login separada, mude aqui
    throw new Error("401 não autenticado");
  }
  return resp;
}

// ============ PERFIL / AUTH ============

async function carregarMe() {
  try {
    const resp = await apiFetch(`${API_BASE}/me`);
    if (!resp.ok) throw new Error("Erro ao buscar /me");
    currentUser = await resp.json();

    const nome = document.getElementById("perfilNome");
    const email = document.getElementById("perfilEmail");
    const role = document.getElementById("perfilRole");
    const status = document.getElementById("perfilStatus");

    if (nome) nome.textContent = currentUser.nome || "-";
    if (email) email.textContent = currentUser.email || "-";
    if (role) role.textContent = (currentUser.role || "-").toUpperCase();
    if (status) status.textContent = "Logado";

    // mostra bloco admin se for admin
    const adminSec = document.getElementById("adminConfigSection");
    if (adminSec) {
      adminSec.style.display =
        (currentUser.role || "").toLowerCase() === "admin" ? "block" : "none";
    }
  } catch (err) {
    console.error(err);
  }
}

async function logout() {
  try {
    const resp = await apiFetch(`${API_BASE}/auth/logout`, { method: "POST" });
    if (!resp.ok) throw new Error("Erro ao deslogar");
    alert("Você saiu da conta.");
    window.location.href = "/";
  } catch (err) {
    console.error(err);
    alert("Erro ao deslogar");
  }
}

// Admin: criar user
async function adminCriarUsuario() {
  const nome = document.getElementById("adminNovoUsuarioNome")?.value?.trim() || "";
  const email = document.getElementById("adminNovoUsuarioEmail")?.value?.trim() || "";
  const senha = document.getElementById("adminNovoUsuarioSenha")?.value || "";
  const role = document.getElementById("adminNovoUsuarioRole")?.value || "user";

  if (!nome || !email || !senha) {
    alert("Preencha nome, email e senha.");
    return;
  }

  try {
    const resp = await apiFetch(
      `${API_BASE}/admin/users?nome=${encodeURIComponent(nome)}&email=${encodeURIComponent(
        email
      )}&senha=${encodeURIComponent(senha)}&role=${encodeURIComponent(role)}`,
      { method: "POST" }
    );
    const j = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(j?.detail || "Erro ao criar usuário");

    alert("Usuário cadastrado com sucesso!");
    document.getElementById("adminNovoUsuarioNome").value = "";
    document.getElementById("adminNovoUsuarioEmail").value = "";
    document.getElementById("adminNovoUsuarioSenha").value = "";
    document.getElementById("adminNovoUsuarioRole").value = "user";
  } catch (err) {
    console.error(err);
    alert(String(err.message || err));
  }
}

// Admin: add transportadora
async function adminAddTransportadora() {
  const nome = document.getElementById("adminNovaTransportadora")?.value?.trim() || "";
  const responsavel = document.getElementById("adminNovoResponsavel")?.value?.trim() || "";

  if (!nome) {
    alert("Informe a transportadora.");
    return;
  }

  try {
    const url = `${API_BASE}/admin/transportadoras?nome=${encodeURIComponent(nome)}&responsavel=${encodeURIComponent(
      responsavel
    )}`;

    const resp = await apiFetch(url, { method: "POST" });
    const j = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(j?.detail || "Erro ao adicionar transportadora");

    alert("Transportadora adicionada!");
    document.getElementById("adminNovaTransportadora").value = "";
    document.getElementById("adminNovoResponsavel").value = "";
  } catch (err) {
    console.error(err);
    alert(String(err.message || err));
  }
}

// Admin: alterar responsável
async function adminAlterarResponsavel() {
  const nome = document.getElementById("adminAlterarTransportadora")?.value?.trim() || "";
  const responsavel = document.getElementById("adminAlterarResponsavel")?.value?.trim() || "";

  if (!nome || !responsavel) {
    alert("Preencha transportadora e novo responsável.");
    return;
  }

  try {
    const url = `${API_BASE}/admin/transportadoras/responsavel?nome_transportadora=${encodeURIComponent(
      nome
    )}&responsavel=${encodeURIComponent(responsavel)}`;

    const resp = await apiFetch(url, { method: "PUT" });
    const j = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(j?.detail || "Erro ao alterar responsável");

    alert("Responsável alterado!");
    document.getElementById("adminAlterarTransportadora").value = "";
    document.getElementById("adminAlterarResponsavel").value = "";

    // recarrega listas
    await carregarFaturas();
    await carregarDashboard();
  } catch (err) {
    console.error(err);
    alert(String(err.message || err));
  }
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

    const respResumo = await apiFetch(urlResumo);
    if (!respResumo.ok) throw new Error("Erro ao buscar resumo");

    const dataResumo = await respResumo.json();

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

      const respFat = await apiFetch(urlF);
      if (!respFat.ok) throw new Error("Erro ao buscar faturas");
      lista = await respFat.json();
      ultimaListaFaturas = lista;
    }

    if (dashboardModo ===_toggleis = "pago") {
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

  const datasSet = new Set();
  (lista || []).forEach((f) => {
    const st = (f.status || "").toLowerCase();
    if (st !== "pago" && f.data_vencimento) datasSet.add(f.data_vencimento);
  });
  const datas = Array.from(datasSet).sort();

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

  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);

  const wd = hoje.getDay();
  let diasAteQuarta = (3 - wd + 7) % 7;
  if (diasAteQuarta === 0) diasAteQuarta = 7;
  let inicioEmDia = new Date(hoje);
  inicioEmDia.setDate(hoje.getDate() + diasAteQuarta);

  if (wd === 1) inicioEmDia.setDate(inicioEmDia.getDate() + 7);

  inicioEmDia.setHours(0, 0, 0, 0);
  const inicioTime = inicioEmDia.getTime();

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
        if (vencTime < inicioTime) grupos[transp].totalAtrasado += valor;
        else grupos[transp].totalEmDia += valor;
      }
    }

    const key = f.data_vencimento;
    grupos[transp].porData[key] = (grupos[transp].porData[key] || 0) + valor;
  });

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

  let totalGeralAtrasado = 0;
  let totalGeralEmDia = 0;
  let totalGeral = 0;
  const totaisPorData = {};

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

    const spacer = document.createElement("tr");
    spacer.className = "spacer-row";
    spacer.innerHTML = `<td colspan="${5 + datas.length}">&nbsp;</td>`;
    tbody.appendChild(spacer);

    subAtrasado = 0;
    subEmDia = 0;
    subGeral = 0;
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

    totalGeralAtrasado += g.totalAtrasado;
    totalGeralEmDia += g.totalEmDia;
    totalGeral += g.totalGeral;

    subAtrasado += g.totalAtrasado;
    subEmDia += g.totalEmDia;
    subGeral += g.totalGeral;

    datas.forEach((d) => {
      const v = g.porData[d] || 0;
      totaisPorData[d] = (totaisPorData[d] || 0) + v;
      subPorData[d] = (subPorData[d] || 0) + v;
    });

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

  if (ordem.length > 0) flushSubtotalResponsavel();

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

    const resp = await apiFetch(url);
    if (!resp.ok) throw new Error("Erro ao listar faturas");

    const faturas = await resp.json();
    ultimaListaFaturas = faturas;

    renderizarFaturas();
    await carregarDashboard();
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

    const resp = await apiFetch(url);
    if (!resp.ok) throw new Error("Erro ao listar histórico");

    const hist = await resp.json();
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
    const resp = await apiFetch(`${API_BASE}/faturas/${id}`, { method: "DELETE" });
    if (!resp.ok) throw new Error("Erro ao excluir");
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
    const resp = await apiFetch(`${API_BASE}/faturas/${faturaId}/anexos`);
    if (!resp.ok) throw new Error("Erro ao listar anexos");
    const anexos = await resp.json();

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
            const respDel = await apiFetch(`${API_BASE}/anexos/${a.id}`, {
              method: "DELETE",
            });
            if (!respDel.ok) throw new Error("Erro ao excluir anexo");
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
      resp = await apiFetch(`${API_BASE}/faturas/${editId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      resp = await apiFetch(`${API_BASE}/faturas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }

    if (!resp.ok) throw new Error("Erro ao salvar fatura");

    const fatura = await resp.json();

    const inputAnexos = document.getElementById("inputAnexos");
    if (inputAnexos && inputAnexos.files && inputAnexos.files.length > 0) {
      const fd = new FormData();
      for (const file of inputAnexos.files) fd.append("files", file);

      const respAnexos = await apiFetch(`${API_BASE}/faturas/${fatura.id}/anexos`, {
        method: "POST",
        body: fd,
      });

      if (!respAnexos.ok) {
        let detalhe = "";
        try {
          const ct = respAnexos.headers.get("content-type") || "";
          if (ct.includes("application/json")) {
            const j = await respAnexos.json();
            detalhe = j?.detail ? String(j.detail) : JSON.stringify(j);
          } else {
            detalhe = await respAnexos.text();
          }
        } catch (_) {}

        console.error("Erro ao enviar anexos:", respAnexos.status, detalhe);
        alert(
          `A fatura foi salva, mas o upload do anexo FALHOU.\n\nStatus: ${respAnexos.status}\n${
            detalhe || ""
          }`
        );
      } else {
        inputAnexos.value = "";
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
  const perfil = document.getElementById("perfilSection");

  const tabDash = document.getElementById("tabDashboard");
  const tabCad = document.getElementById("tabCadastro");
  const tabFat = document.getElementById("tabFaturas");
  const tabHist = document.getElementById("tabHistorico");
  const tabPerfil = document.getElementById("tabPerfil");

  [dash, cad, fat, hist, perfil].forEach((s) => s && s.classList.remove("visible"));
  [tabDash, tabCad, tabFat, tabHist, tabPerfil].forEach((t) => t && t.classList.remove("active"));

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
    perfil.classList.add("visible");
    tabPerfil.classList.add("active");
    carregarMe();
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

document.addEventListener("DOMContentLoaded", async () => {
  setupMenuDelegation();

  // tabs
  document.getElementById("tabDashboard")?.addEventListener("click", () => ativarAba("dashboard"));
  document.getElementById("tabCadastro")?.addEventListener("click", () => ativarAba("cadastro"));
  document.getElementById("tabFaturas")?.addEventListener("click", () => ativarAba("faturas"));
  document.getElementById("tabHistorico")?.addEventListener("click", () => ativarAba("historico"));
  document.getElementById("tabPerfil")?.addEventListener("click", () => ativarAba("perfil"));

  // logout
  document.getElementById("btnLogout")?.addEventListener("click", logout);

  // dashboard modo
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

  // home button
  document.getElementById("btnHome")?.addEventListener("click", () => {
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

  // sidebar transportadoras
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

  document.getElementById("btnLimparFiltros")?.addEventListener("click", () => {
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

  document.getElementById("btnLimparPeriodoFaturas")?.addEventListener("click", () => {
    filtroDataInicioFaturas = "";
    filtroDataFimFaturas = "";

    const ini = document.getElementById("filtroDataInicioFaturas");
    const fim = document.getElementById("filtroDataFimFaturas");
    if (ini) ini.value = "";
    if (fim) fim.value = "";

    renderizarFaturas();
  });

  // busca nº fatura (com debounce pra ficar leve)
  let tBusca = null;
  const buscaNumero = document.getElementById("buscaNumero");
  if (buscaNumero) {
    buscaNumero.addEventListener("input", (e) => {
      clearTimeout(tBusca);
      tBusca = setTimeout(() => {
        filtroNumeroFatura = e.target.value.trim();
        carregarFaturas();
      }, 250);
    });
  }

  const ini = document.getElementById("filtroDataInicioFaturas");
  const fim = document.getElementById("filtroDataFimFaturas");
  if (ini) ini.addEventListener("change", (e) => ((filtroDataInicioFaturas = e.target.value), renderizarFaturas()));
  if (fim) fim.addEventListener("change", (e) => ((filtroDataFimFaturas = e.target.value), renderizarFaturas()));

  const statusSelect = document.getElementById("filtroStatus");
  if (statusSelect)
    statusSelect.addEventListener("change", (e) => ((filtroStatus = e.target.value), renderizarFaturas()));

  document.getElementById("btnAtualizarFaturas")?.addEventListener("click", (e) => (e.preventDefault(), carregarFaturas()));
  document.getElementById("btnExportarExcel")?.addEventListener("click", exportarExcel);

  document.getElementById("btnAtualizarHistorico")?.addEventListener("click", (e) => (e.preventDefault(), carregarHistorico()));
  document.getElementById("btnExportarHistorico")?.addEventListener("click", exportarHistorico);

  document.getElementById("formFatura")?.addEventListener("submit", salvarFatura);

  document.getElementById("modalFechar")?.addEventListener("click", () =>
    document.getElementById("modalAnexos")?.classList.remove("open")
  );
  document.getElementById("modalAnexos")?.addEventListener("click", (e) => {
    if (e.target.id === "modalAnexos") {
      document.getElementById("modalAnexos")?.classList.remove("open");
    }
  });

  // Admin buttons no perfil
  document.getElementById("btnAdminCriarUsuario")?.addEventListener("click", adminCriarUsuario);
  document.getElementById("btnAdminAddTransportadora")?.addEventListener("click", adminAddTransportadora);
  document.getElementById("btnAdminAlterarResponsavel")?.addEventListener("click", adminAlterarResponsavel);

  // primeira carga
  await carregarMe();
  await carregarFaturas();
  await carregarHistorico();
});
