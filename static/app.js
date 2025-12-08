// ===============================
// MAPA DE RESPONSÁVEIS POR TRANSP.
// ===============================
const RESPONSAVEIS = {
  "DHL": "Gabrielly",
  "Pannan": "Gabrielly",
  "Garcia": "Juliana",
  "Excargo": "Juliana",
  "Transbritto": "Larissa",
  "PDA": "Larissa",
  "GLM": "Larissa"
};

function responsavelPorTransportadora(tp) {
  return RESPONSAVEIS[tp] || "";
}

function formatMoney(v) {
  if (v == null || isNaN(v)) return "R$ 0,00";
  return "R$ " + Number(v).toFixed(2).replace(".", ",");
}

// ===============================
// NAVEGAÇÃO DE SEÇÕES
// ===============================
document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const sectionId = btn.dataset.section;

    document
      .querySelectorAll(".section")
      .forEach((s) => s.classList.remove("active"));
    document.getElementById(sectionId).classList.add("active");
  });
});

// ===============================
// CARREGAR FATURAS
// ===============================
async function carregarFaturas() {
  try {
    const filtro = document
      .getElementById("filtroTransportadora")
      .value.trim();

    let url = "/api/faturas";
    if (filtro) {
      url += `?transportadora=${encodeURIComponent(filtro)}`;
    }

    const res = await fetch(url);
    if (!res.ok) {
      throw new Error("Erro ao carregar faturas");
    }

    const data = await res.json();
    const tbody = document.getElementById("faturasBody");
    tbody.innerHTML = "";

    data.forEach((f) => {
      const tr = document.createElement("tr");

      const responsavel = responsavelPorTransportadora(f.transportadora);

      tr.innerHTML = `
        <td>${f.id}</td>
        <td>${f.transportadora}</td>
        <td>${responsavel}</td>
        <td>${f.numero_fatura}</td>
        <td>${formatMoney(f.valor)}</td>
        <td>${f.data_vencimento || ""}</td>
        <td>${f.status}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar faturas.");
  }
}

// ===============================
// CADASTRO DE FATURA
// (envia JSON -> POST /api/faturas)
// ===============================
document
  .getElementById("formCadastro")
  .addEventListener("submit", async (e) => {
    e.preventDefault();

    const transportadora =
      document.getElementById("cadTransportadora").value.trim();
    const numero = document.getElementById("cadNumero").value.trim();
    const valorStr = document.getElementById("cadValor").value;
    const vencimento = document.getElementById("cadVencimento").value;
    const status = document.getElementById("cadStatus").value;

    if (!transportadora || !numero || !valorStr || !vencimento) {
      alert("Preencha todos os campos obrigatórios.");
      return;
    }

    const payload = {
      transportadora: transportadora,
      numero_fatura: numero,
      valor: parseFloat(valorStr),
      data_vencimento: vencimento,
      status: status,
    };

    try {
      const res = await fetch("/api/faturas", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        console.error(await res.text());
        throw new Error("Erro ao salvar fatura");
      }

      alert("Fatura salva com sucesso!");
      e.target.reset();

      await carregarFaturas();
      await atualizarDashboard();
    } catch (err) {
      console.error(err);
      alert("Erro ao salvar fatura.");
    }
  });

// ===============================
// DASHBOARD
// ===============================
async function atualizarDashboard() {
  try {
    const res = await fetch("/api/dashboard");
    if (!res.ok) {
      throw new Error("Erro ao carregar dashboard");
    }

    const d = await res.json();
    document.getElementById("dashTotal").textContent = formatMoney(d.total);
    document.getElementById(
      "dashPendentes"
    ).textContent = `${formatMoney(d.pendentes)}`;
    document.getElementById(
      "dashAtrasadas"
    ).textContent = `${formatMoney(d.atrasadas)}`;
    document.getElementById("dashEmDia").textContent = formatMoney(d.em_dia);
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar dashboard.");
  }
}

document
  .getElementById("btnAtualizarDashboard")
  .addEventListener("click", atualizarDashboard);

// ===============================
// FILTRO + EXPORTAÇÃO CSV
// ===============================
document
  .getElementById("btnAplicarFiltro")
  .addEventListener("click", carregarFaturas);

document.getElementById("btnLimparFiltro").addEventListener("click", () => {
  document.getElementById("filtroTransportadora").value = "";
  carregarFaturas();
});

document
  .getElementById("btnExportarTodas")
  .addEventListener("click", () => {
    window.location.href = "/api/exportar";
  });

document
  .getElementById("btnExportarFiltro")
  .addEventListener("click", () => {
    const filtro = document
      .getElementById("filtroTransportadora")
      .value.trim();

    let url = "/api/exportar";
    if (filtro) {
      url += `?transportadora=${encodeURIComponent(filtro)}`;
    }
    window.location.href = url;
  });

// ===============================
// INICIALIZAÇÃO
// ===============================
(async () => {
  await carregarFaturas();
  await atualizarDashboard();
})();
