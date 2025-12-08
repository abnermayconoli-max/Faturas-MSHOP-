function formatCurrency(value) {
  const num = Number(value || 0);
  return num.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("pt-BR");
}

async function carregarFaturas() {
  try {
    const params = new URLSearchParams();

    const t = document.getElementById("filtro-transportadora").value.trim();
    const nf = document.getElementById("filtro-numero").value.trim();
    const venc = document.getElementById("filtro-vencimento").value;

    if (t) params.append("transportadora", t);
    if (nf) params.append("numero_fatura", nf);
    if (venc) params.append("ate_vencimento", venc);

    const url = "/faturas" + (params.toString() ? "?" + params.toString() : "");
    const resp = await fetch(url);

    if (!resp.ok) {
      throw new Error("Erro HTTP " + resp.status);
    }

    const dados = await resp.json();
    const tbody = document.querySelector("#tabela-faturas tbody");
    tbody.innerHTML = "";

    if (!dados.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 7;
      td.textContent = "Nenhuma fatura encontrada.";
      td.style.textAlign = "center";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    for (const f of dados) {
      const tr = document.createElement("tr");

      tr.innerHTML = `
        <td>${f.id}</td>
        <td>${f.transportadora}</td>
        <td>${f.responsavel || ""}</td>
        <td>${f.numero_fatura}</td>
        <td>${formatCurrency(f.valor)}</td>
        <td>${formatDate(f.data_vencimento)}</td>
        <td>${f.status}</td>
      `;

      tbody.appendChild(tr);
    }
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar faturas");
  }
}

async function carregarDashboard() {
  try {
    const resp = await fetch("/dashboard/resumo");
    if (!resp.ok) return;

    const k = await resp.json();
    document.getElementById("kpi-total").textContent = formatCurrency(k.total);
    document.getElementById("kpi-pendentes").textContent = formatCurrency(k.pendentes);
    document.getElementById("kpi-atrasadas").textContent = formatCurrency(k.atrasadas);
    document.getElementById("kpi-em-dia").textContent = formatCurrency(k.em_dia);
  } catch (err) {
    console.error(err);
  }
}

function initTabs() {
  const buttons = document.querySelectorAll(".tab-button");
  const contents = document.querySelectorAll(".tab-content");

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      contents.forEach((c) => c.classList.remove("active"));

      btn.classList.add("active");
      const id = "tab-" + btn.dataset.tab;
      document.getElementById(id).classList.add("active");

      if (btn.dataset.tab === "dashboard") {
        carregarDashboard();
      }
    });
  });
}

function initFiltros() {
  document.getElementById("btn-filtrar").addEventListener("click", () => {
    carregarFaturas();
  });

  document.getElementById("btn-atualizar").addEventListener("click", () => {
    carregarFaturas();
  });

  document.getElementById("btn-limpar").addEventListener("click", () => {
    document.getElementById("filtro-transportadora").value = "";
    document.getElementById("filtro-numero").value = "";
    document.getElementById("filtro-vencimento").value = "";
    carregarFaturas();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initFiltros();
  carregarFaturas();
  carregarDashboard();
});
