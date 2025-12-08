function formatValor(valor) {
  const n = Number(valor || 0);
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function formatDataiso(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("pt-BR");
}

/* ---------- Tabs ----------- */

document.querySelectorAll(".tab-button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document
      .querySelectorAll(".tab-button")
      .forEach((b) => b.classList.remove("active"));
    document
      .querySelectorAll(".tab-content")
      .forEach((c) => c.classList.remove("active"));

    btn.classList.add("active");
    const tabId = "tab-" + btn.dataset.tab;
    document.getElementById(tabId).classList.add("active");
  });
});

/* ---------- Faturas ----------- */

async function carregarFaturas() {
  try {
    const transportadora = document.getElementById("filtro-transportadora").value.trim();
    const ateVenc = document.getElementById("filtro-ate-vencimento").value;
    const numeroFatura = document.getElementById("filtro-numero-fatura").value.trim();

    const params = new URLSearchParams();
    if (transportadora) params.append("transportadora", transportadora);
    if (ateVenc) params.append("ate_vencimento", ateVenc);
    if (numeroFatura) params.append("numero_fatura", numeroFatura);

    const url = "/faturas" + (params.toString() ? `?${params.toString()}` : "");
    const resp = await fetch(url);

    if (!resp.ok) {
      alert("Erro ao carregar faturas");
      return;
    }

    const dados = await resp.json();
    const tbody = document.querySelector("#tabela-faturas tbody");
    tbody.innerHTML = "";

    if (!Array.isArray(dados) || dados.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 8;
      td.textContent = "Nenhuma fatura encontrada";
      td.style.textAlign = "center";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    dados.forEach((f) => {
      const tr = document.createElement("tr");

      tr.innerHTML = `
        <td>${f.id}</td>
        <td>${f.transportadora}</td>
        <td>${f.responsavel || ""}</td>
        <td>${f.numero_fatura}</td>
        <td>${formatValor(f.valor)}</td>
        <td>${formatDataiso(f.data_vencimento)}</td>
        <td>${f.status}</td>
        <td>${f.observacao || ""}</td>
      `;

      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error(e);
    alert("Erro ao carregar faturas");
  }
}

/* ---------- Dashboard ----------- */

async function carregarDashboard() {
  try {
    const resp = await fetch("/dashboard/resumo");
    if (!resp.ok) return;

    const d = await resp.json();
    document.getElementById("card-total").textContent = formatValor(d.total);
    document.getElementById("card-pendentes").textContent = formatValor(d.pendentes);
    document.getElementById("card-atrasadas").textContent = formatValor(d.atrasadas);
    document.getElementById("card-em-dia").textContent = formatValor(d.em_dia);
  } catch (e) {
    console.error(e);
  }
}

/* ---------- Listeners ----------- */

document.getElementById("btn-filtrar").addEventListener("click", (e) => {
  e.preventDefault();
  carregarFaturas();
});

document.getElementById("btn-limpar").addEventListener("click", (e) => {
  e.preventDefault();
  document.getElementById("filtro-transportadora").value = "";
  document.getElementById("filtro-ate-vencimento").value = "";
  document.getElementById("filtro-numero-fatura").value = "";
  carregarFaturas();
});

document.getElementById("btn-recarregar").addEventListener("click", (e) => {
  e.preventDefault();
  carregarFaturas();
});

/* ---------- Inicialização ----------- */

carregarFaturas();
carregarDashboard();
