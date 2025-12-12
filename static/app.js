// =====================
// CONFIG
// =====================
const API_BASE = "";

// =====================
// ESTADO GLOBAL
// =====================
let filtroTransportadora = "";
let filtroVencimento = "";
let filtroNumeroFatura = "";

let filtroDataInicioFaturas = "";
let filtroDataFimFaturas = "";
let filtroStatus = "";

let ultimaListaFaturas = [];

// =====================
// HELPERS
// =====================
function formatCurrency(valor) {
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
  return d.toLocaleDateString("pt-BR");
}

// =====================
// DASHBOARD
// =====================
async function carregarDashboard() {
  try {
    const params = new URLSearchParams();
    if (filtroTransportadora) params.append("transportadora", filtroTransportadora);
    if (filtroVencimento) params.append("ate_vencimento", filtroVencimento);

    const urlResumo =
      params.toString().length > 0
        ? `${API_BASE}/dashboard/resumo?${params}`
        : `${API_BASE}/dashboard/resumo`;

    const resp = await fetch(urlResumo);
    const data = await resp.json();

    document.getElementById("cardTotal").textContent = formatCurrency(data.total);
    document.getElementById("cardPendentes").textContent = formatCurrency(data.pendentes);
    document.getElementById("cardAtrasadas").textContent = formatCurrency(data.atrasadas);
    document.getElementById("cardEmDia").textContent = formatCurrency(data.em_dia);

    renderResumoDashboard(ultimaListaFaturas);
  } catch (e) {
    console.error(e);
  }
}

// =====================
// DASHBOARD BACKLOG (horizontal)
// =====================
function renderResumoDashboard(lista) {
  const thead = document.getElementById("theadResumoDashboard");
  const tbody = document.getElementById("tbodyResumoDashboard");
  if (!thead || !tbody) return;

  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);

  const weekday = hoje.getDay();
  let diasAteQuarta = (3 - weekday + 7) % 7;
  if (diasAteQuarta === 0) diasAteQuarta = 7;

  const proxQuarta = new Date(hoje);
  proxQuarta.setDate(hoje.getDate() + diasAteQuarta);
  proxQuarta.setHours(0, 0, 0, 0);
  const proxQuartaTime = proxQuarta.getTime();

  const datasSet = new Set();
  lista.forEach((f) => {
    if ((f.status || "").toLowerCase() !== "pago" && f.data_vencimento) {
      datasSet.add(f.data_vencimento);
    }
  });

  const datas = Array.from(datasSet).sort();

  let header = `<tr>
    <th>Transportadora</th>
    <th>Atrasado</th>
    <th>Em dia</th>
    <th>Total</th>`;
  datas.forEach((d) => (header += `<th>${formatDate(d)}</th>`));
  header += "</tr>";
  thead.innerHTML = header;

  const grupos = {};
  lista.forEach((f) => {
    if ((f.status || "").toLowerCase() === "pago") return;

    const t = f.transportadora || "Outros";
    grupos[t] ??= { atrasado: 0, emDia: 0, total: 0, porData: {} };

    const valor = Number(f.valor || 0);
    grupos[t].total += valor;

    const venc = parseISODateLocal(f.data_vencimento);
    const vencTime = venc ? venc.setHours(0, 0, 0, 0) : null;

    if ((f.status || "").toLowerCase() === "atrasado") {
      grupos[t].atrasado += valor;
    } else if (vencTime !== null) {
      if (vencTime < proxQuartaTime) grupos[t].atrasado += valor;
      else if (vencTime === proxQuartaTime) grupos[t].emDia += valor;
    }

    grupos[t].porData[f.data_vencimento] =
      (grupos[t].porData[f.data_vencimento] || 0) + valor;
  });

  tbody.innerHTML = "";
  Object.entries(grupos).forEach(([t, g]) => {
    let row = `<tr>
      <td>${t}</td>
      <td>${formatCurrency(g.atrasado)}</td>
      <td>${formatCurrency(g.emDia)}</td>
      <td>${formatCurrency(g.total)}</td>`;
    datas.forEach((d) => {
      row += `<td>${g.porData[d] ? formatCurrency(g.porData[d]) : "-"}</td>`;
    });
    row += "</tr>";
    tbody.innerHTML += row;
  });
}

// =====================
// FATURAS
// =====================
async function carregarFaturas() {
  const params = new URLSearchParams();
  if (filtroTransportadora) params.append("transportadora", filtroTransportadora);
  if (filtroVencimento) params.append("ate_vencimento", filtroVencimento);
  if (filtroNumeroFatura) params.append("numero_fatura", filtroNumeroFatura);

  const url =
    params.toString().length > 0
      ? `${API_BASE}/faturas?${params}`
      : `${API_BASE}/faturas`;

  const resp = await fetch(url);
  ultimaListaFaturas = await resp.json();
  renderizarFaturas();
  carregarDashboard();
}

function renderizarFaturas() {
  const tbody = document.getElementById("tbodyFaturas");
  tbody.innerHTML = "";

  let lista = [...ultimaListaFaturas];

  if (filtroStatus) {
    lista = lista.filter((f) => (f.status || "").toLowerCase() === filtroStatus);
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
      <td class="acoes">
        <button class="menu-btn">⋮</button>
        <div class="menu-dropdown">
          <button data-acao="editar">Editar</button>
          <button data-acao="excluir">Excluir</button>
          <button data-acao="anexos">Anexos</button>
        </div>
      </td>`;
    tbody.appendChild(tr);
  });
}

// =====================
// MENU ⋮ — EVENT DELEGATION (CORRIGIDO)
// =====================
document.addEventListener("DOMContentLoaded", () => {
  const tbody = document.getElementById("tbodyFaturas");

  tbody.addEventListener("click", async (e) => {
    const btnMenu = e.target.closest(".menu-btn");
    const btnAcao = e.target.closest(".menu-dropdown button");

    if (btnMenu) {
      e.preventDefault();
      e.stopPropagation();

      document
        .querySelectorAll(".menu-dropdown.ativo")
        .forEach((m) => m.classList.remove("ativo"));

      btnMenu
        .closest(".acoes")
        .querySelector(".menu-dropdown")
        .classList.toggle("ativo");
      return;
    }

    if (btnAcao) {
      e.preventDefault();
      e.stopPropagation();

      const acao = btnAcao.dataset.acao;
      const tr = btnAcao.closest("tr");
      const id = tr.dataset.faturaId;

      if (acao === "excluir") await excluirFatura(id);
      if (acao === "editar") {
        const f = ultimaListaFaturas.find((x) => String(x.id) === String(id));
        if (f) preencherFormularioEdicao(f);
      }
      if (acao === "anexos") abrirModalAnexos(id);

      document
        .querySelectorAll(".menu-dropdown.ativo")
        .forEach((m) => m.classList.remove("ativo"));
    }
  });

  carregarFaturas();
});

// =====================
// CRUD
// =====================
async function excluirFatura(id) {
  if (!confirm(`Excluir fatura ${id}?`)) return;
  await fetch(`${API_BASE}/faturas/${id}`, { method: "DELETE" });
  carregarFaturas();
}

function preencherFormularioEdicao(f) {
  ativarAba("cadastro");
  document.getElementById("formFatura").dataset.editId = f.id;
  document.getElementById("inputTransportadora").value = f.transportadora;
  document.getElementById("inputNumeroFatura").value = f.numero_fatura;
  document.getElementById("inputValor").value = f.valor;
  document.getElementById("inputVencimento").value = f.data_vencimento;
  document.getElementById("inputStatus").value = f.status;
  document.getElementById("inputObservacao").value = f.observacao ?? "";
}

// =====================
// ABAS
// =====================
function ativarAba(aba) {
  document.querySelectorAll(".section").forEach((s) => s.classList.remove("visible"));
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));

  document.getElementById(`${aba}Section`).classList.add("visible");
  document.getElementById(`tab${aba.charAt(0).toUpperCase() + aba.slice(1)}`).classList.add("active");
}
