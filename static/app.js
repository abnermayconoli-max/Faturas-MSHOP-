const API_BASE = "/api";

// -------------------------
// Troca de abas
// -------------------------
const tabButtons = document.querySelectorAll(".tab-button");
const tabContents = document.querySelectorAll(".tab-content");

tabButtons.forEach(btn => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;

    tabButtons.forEach(b => b.classList.remove("active"));
    tabContents.forEach(c => c.classList.remove("active"));

    btn.classList.add("active");
    document.getElementById(`tab-${tab}`).classList.add("active");

    if (tab === "faturas") {
      carregarFaturas();
    } else if (tab === "dashboard") {
      carregarDashboard();
    }
  });
});

// -------------------------
// Helpers
// -------------------------
function formatMoney(v) {
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

// Mapa: transportadora -> responsável
const responsavelPorTransportadora = {
  "DHL": "Gabrielly",
  "Pannan": "Gabrielly",
  "Garcia": "Juliana",
  "Excargo": "Juliana",
  "Transbritto": "Larissa",
  "PDA": "Larissa",
  "GLM": "Larissa",
};

// -------------------------
// Cadastro de fatura
// -------------------------
const formCadastro = document.getElementById("form-cadastro");

formCadastro.addEventListener("submit", async (e) => {
  e.preventDefault();

  const dados = {
    transportadora: document.getElementById("cad-transportadora").value.trim(),
    numero_fatura: document.getElementById("cad-numero").value.trim(),
    valor: parseFloat(document.getElementById("cad-valor").value || "0"),
    data_vencimento: document.getElementById("cad-vencimento").value,
    status: document.getElementById("cad-status").value,
    observacao: document.getElementById("cad-observacao").value.trim() || null,
  };

  try {
    const resp = await fetch(`${API_BASE}/faturas`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      alert("Erro ao salvar fatura: " + (err.detail || resp.statusText));
      return;
    }

    alert("Fatura cadastrada com sucesso!");
    formCadastro.reset();
    carregarFaturas();
  } catch (e) {
    console.error(e);
    alert("Erro ao salvar fatura (ver console).");
  }
});

// -------------------------
// Listar faturas + separar por responsável
// -------------------------
const containerFaturas = document.getElementById("faturas-por-responsavel");
const filtroInput = document.getElementById("filtro-transportadora");
const btnAplicarFiltro = document.getElementById("btn-aplicar-filtro");
const btnLimparFiltro = document.getElementById("btn-limpar-filtro");

btnAplicarFiltro.addEventListener("click", () => carregarFaturas());
btnLimparFiltro.addEventListener("click", () => {
  filtroInput.value = "";
  carregarFaturas();
});

async function carregarFaturas() {
  containerFaturas.innerHTML = "Carregando...";

  try {
    const resp = await fetch(`${API_BASE}/faturas`);
    if (!resp.ok) throw new Error("Falha ao buscar faturas");

    const todas = await resp.json();

    const filtro = filtroInput.value.trim().toLowerCase();
    const filtradas = filtro
      ? todas.filter(f => f.transportadora.toLowerCase().includes(filtro))
      : todas;

    // agrupar por responsável
    const grupos = {
      Gabrielly: [],
      Juliana: [],
      Larissa: [],
      Outros: [],
    };

    for (const f of filtradas) {
      const respNome = responsavelPorTransportadora[f.transportadora] || "Outros";
      if (!grupos[respNome]) grupos[respNome] = [];
      grupos[respNome].push(f);
    }

    // montar HTML
    containerFaturas.innerHTML = "";

    const ordemResp = ["Gabrielly", "Juliana", "Larissa", "Outros"];

    ordemResp.forEach(nome => {
      const lista = grupos[nome];
      if (!lista || lista.length === 0) return;

      const div = document.createElement("div");
      div.className = "grupo-responsavel";

      const subtitulo = {
        Gabrielly: "DHL, Pannan",
        Juliana: "Garcia, Excargo",
        Larissa: "Transbritto, PDA, GLM",
        Outros: "Demais transportadoras",
      }[nome];

      div.innerHTML = `
        <h2>${nome}</h2>
        <div class="subtitulo">${subtitulo}</div>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Transportadora</th>
              <th>Nº Fatura</th>
              <th>Valor</th>
              <th>Vencimento</th>
              <th>Status</th>
              <th>Observação</th>
            </tr>
          </thead>
          <tbody>
            ${lista
              .map(f => {
                const dt = f.data_vencimento
                  ? new Date(f.data_vencimento + "T00:00:00")
                  : null;

                const hoje = new Date();
                let badgeClass = "pendente";
                let statusLabel = f.status;
                if (f.status.toLowerCase() === "pago") {
                  badgeClass = "pago";
                } else if (dt && dt < hoje && f.status.toLowerCase() !== "pago") {
                  badgeClass = "atrasada";
                  statusLabel = statusLabel || "Atrasada";
                }

                return `
                  <tr>
                    <td>${f.id}</td>
                    <td>${f.transportadora}</td>
                    <td>${f.numero_fatura}</td>
                    <td>${formatMoney(f.valor)}</td>
                    <td>${dt ? dt.toLocaleDateString("pt-BR") : ""}</td>
                    <td><span class="badge ${badgeClass}">${statusLabel}</span></td>
                    <td>${f.observacao ? f.observacao.replace(/</g, "&lt;") : ""}</td>
                  </tr>
                `;
              })
              .join("")}
          </tbody>
        </table>
      `;

      containerFaturas.appendChild(div);
    });

    if (!containerFaturas.innerHTML) {
      containerFaturas.innerHTML = "<p>Nenhuma fatura encontrada.</p>";
    }
  } catch (e) {
    console.error(e);
    containerFaturas.innerHTML = "<p>Erro ao carregar faturas.</p>";
  }
}

// -------------------------
// Dashboard
// -------------------------
const lblTotalValor = document.getElementById("dash-total-valor");
const lblPendentes = document.getElementById("dash-pendentes");
const lblAtrasadas = document.getElementById("dash-atrasadas");
const lblEmDia = document.getElementById("dash-em-dia");
const btnAtualizarDash = document.getElementById("btn-atualizar-dashboard");

btnAtualizarDash.addEventListener("click", carregarDashboard);

async function carregarDashboard() {
  try {
    const resp = await fetch(`${API_BASE}/dashboard`);
    if (!resp.ok) throw new Error("Falha ao buscar dashboard");

    const d = await resp.json();

    lblTotalValor.textContent = formatMoney(d.total_valor || 0);
    lblPendentes.textContent = `${d.pendentes_qtd} (${formatMoney(d.pendentes_valor || 0)})`;
    lblAtrasadas.textContent = `${d.atrasadas_qtd} (${formatMoney(d.atrasadas_valor || 0)})`;
    lblEmDia.textContent   = `${d.em_dia_qtd} (${formatMoney(d.em_dia_valor || 0)})`;
  } catch (e) {
    console.error(e);
    alert("Erro ao carregar dashboard.");
  }
}

// -------------------------
// Exportar CSV (Excel)
// -------------------------
const btnExportarFiltro = document.getElementById("btn-exportar-filtro");
const btnExportarTodas = document.getElementById("btn-exportar-todas");
const btnExportarTodas2 = document.getElementById("btn-exportar-todas-2");

async function baixarArquivo(url) {
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error("Erro ao gerar arquivo");

    const blob = await resp.blob();
    const urlBlob = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = urlBlob;
    a.download = "faturas.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(urlBlob);
  } catch (e) {
    console.error(e);
    alert("Erro ao exportar arquivo.");
  }
}

btnExportarFiltro.addEventListener("click", () => {
  const filtro = filtroInput.value.trim();
  const url = filtro
    ? `${API_BASE}/faturas/exportar?transportadora=${encodeURIComponent(filtro)}`
    : `${API_BASE}/faturas/exportar`;
  baixarArquivo(url);
});

btnExportarTodas.addEventListener("click", () => {
  baixarArquivo(`${API_BASE}/faturas/exportar`);
});

btnExportarTodas2.addEventListener("click", () => {
  baixarArquivo(`${API_BASE}/faturas/exportar`);
});

// -------------------------
// Inicialização
// -------------------------
carregarFaturas();
