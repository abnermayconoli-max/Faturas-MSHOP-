// URL base da API (mesmo domínio)
const API_BASE = "";

// Estado de filtros
let filtroTransportadora = "";
let filtroVencimento = "";
let filtroNumeroFatura = "";

// =====================
// HELPERS
// =====================

function formatCurrency(valor) {
  if (valor === null || valor === undefined) return "R$ 0,00";
  return Number(valor).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
}

function formatDate(isoDate) {
  if (!isoDate) return "";
  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString("pt-BR");
}

// =====================
// DASHBOARD
// =====================

async function carregarDashboard() {
  try {
    const resp = await fetch(`${API_BASE}/dashboard/resumo`);
    if (!resp.ok) throw new Error("Erro ao buscar resumo");

    const data = await resp.json();

    const cardTotal = document.getElementById("cardTotal");
    const cardPendentes = document.getElementById("cardPendentes");
    const cardAtrasadas = document.getElementById("cardAtrasadas");
    const cardEmDia = document.getElementById("cardEmDia");

    if (cardTotal) cardTotal.textContent = formatCurrency(data.total);
    if (cardPendentes) cardPendentes.textContent = formatCurrency(data.pendentes);
    if (cardAtrasadas) cardAtrasadas.textContent = formatCurrency(data.atrasadas);
    if (cardEmDia) cardEmDia.textContent = formatCurrency(data.em_dia);
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar dashboard");
  }
}

// =====================
// FATURAS
// =====================

async function carregarFaturas() {
  try {
    const params = new URLSearchParams();
    if (filtroTransportadora) params.append("transportadora", filtroTransportadora);
    if (filtroVencimento) params.append("ate_vencimento", filtroVencimento);
    if (filtroNumeroFatura) params.append("numero_fatura", filtroNumeroFatura);

    const url = `${API_BASE}/faturas?${params.toString()}`;
    const resp = await fetch(url);
    if (!resp.ok) throw new Error("Erro ao listar faturas");

    const faturas = await resp.json();
    const tbody = document.getElementById("tbodyFaturas");
    if (!tbody) return;

    tbody.innerHTML = "";

    faturas.forEach((f) => {
      const tr = document.createElement("tr");

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
        </td>
      `;

      const menuBtn = tr.querySelector(".menu-btn");
      const dropdown = tr.querySelector(".menu-dropdown");

      if (menuBtn && dropdown) {
        menuBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          document
            .querySelectorAll(".menu-dropdown.ativo")
            .forEach((m) => m.classList.remove("ativo"));
          dropdown.classList.toggle("ativo");
        });

        dropdown.addEventListener("click", async (e) => {
          const acao = e.target.dataset.acao;
          if (!acao) return;

          if (acao === "excluir") {
            await excluirFatura(f.id);
          } else if (acao === "editar") {
            preencherFormularioEdicao(f);
          } else if (acao === "anexos") {
            abrirModalAnexos(f.id);
          }

          dropdown.classList.remove("ativo");
        });
      }

      tbody.appendChild(tr);
    });

    // fecha menus ao clicar fora
    document.addEventListener("click", () => {
      document
        .querySelectorAll(".menu-dropdown.ativo")
        .forEach((m) => m.classList.remove("ativo"));
    });
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar faturas");
  }
}

async function excluirFatura(id) {
  if (!confirm(`Excluir fatura ${id}?`)) return;

  try {
    const resp = await fetch(`${API_BASE}/faturas/${id}`, {
      method: "DELETE",
    });
    if (!resp.ok) throw new Error("Erro ao excluir");

    await carregarFaturas();
    await carregarDashboard();
  } catch (err) {
    console.error(err);
    alert("Erro ao excluir fatura");
  }
}

function preencherFormularioEdicao(f) {
  const form = document.getElementById("formFatura");
  if (!form) return;

  const inputTransportadora = document.getElementById("inputTransportadora");
  const inputNumeroFatura = document.getElementById("inputNumeroFatura");
  const inputValor = document.getElementById("inputValor");
  const inputVencimento = document.getElementById("inputVencimento");
  const inputStatus = document.getElementById("inputStatus");
  const inputObservacao = document.getElementById("inputObservacao");

  if (inputTransportadora) inputTransportadora.value = f.transportadora;
  if (inputNumeroFatura) inputNumeroFatura.value = f.numero_fatura;
  if (inputValor) inputValor.value = f.valor;
  if (inputVencimento) inputVencimento.value = f.data_vencimento;
  if (inputStatus) inputStatus.value = f.status;
  if (inputObservacao) inputObservacao.value = f.observacao ?? "";

  form.dataset.editId = f.id;
}

// =====================
// ANEXOS (MODAL)
// =====================

async function abrirModalAnexos(faturaId) {
  const modal = document.getElementById("modalAnexos");
  const spanId = document.getElementById("modalFaturaId");
  const lista = document.getElementById("listaAnexos");
  if (!modal || !lista || !spanId) return;

  spanId.textContent = faturaId;
  lista.innerHTML = "Carregando...";

  try {
    const resp = await fetch(`${API_BASE}/faturas/${faturaId}/anexos`);
    if (!resp.ok) throw new Error("Erro ao listar anexos");
    const anexos = await resp.json();

    if (anexos.length === 0) {
      lista.innerHTML = "<li>Sem anexos.</li>";
    } else {
      lista.innerHTML = "";
      anexos.forEach((a) => {
        const li = document.createElement("li");
        const link = document.createElement("a");
        link.href = `${API_BASE}/anexos/${a.id}`;
        link.target = "_blank";
        link.textContent = a.original_name;
        li.appendChild(link);
        lista.appendChild(li);
      });
    }
  } catch (err) {
    console.error(err);
    lista.innerHTML = "<li>Erro ao carregar anexos.</li>";
  }

  modal.classList.add("open");
}

// =====================
// FORMULÁRIO (CRIAR / EDITAR)
// =====================

async function salvarFatura(e) {
  e.preventDefault();

  const form = document.getElementById("formFatura");
  if (!form) return;

  const inputTransportadora = document.getElementById("inputTransportadora");
  const inputNumeroFatura = document.getElementById("inputNumeroFatura");
  const inputValor = document.getElementById("inputValor");
  const inputVencimento = document.getElementById("inputVencimento");
  const inputStatus = document.getElementById("inputStatus");
  const inputObservacao = document.getElementById("inputObservacao");
  const inputAnexos = document.getElementById("inputAnexos");

  const payload = {
    transportadora: inputTransportadora?.value || "",
    numero_fatura: inputNumeroFatura?.value || "",
    valor: parseFloat(inputValor?.value || "0"),
    data_vencimento: inputVencimento?.value || "",
    status: inputStatus?.value || "pendente",
    observacao: inputObservacao?.value || null,
  };

  try {
    let resp;
    const editId = form.dataset.editId;

    if (editId) {
      resp = await fetch(`${API_BASE}/faturas/${editId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      resp = await fetch(`${API_BASE}/faturas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }

    if (!resp.ok) throw new Error("Erro ao salvar fatura");
    const fatura = await resp.json();

    // anexos
    if (inputAnexos && inputAnexos.files.length > 0) {
      const fd = new FormData();
      for (const file of inputAnexos.files) {
        fd.append("files", file);
      }
      const respAnexos = await fetch(`${API_BASE}/faturas/${fatura.id}/anexos`, {
        method: "POST",
        body: fd,
      });
      if (!respAnexos.ok) console.error("Erro ao enviar anexos");
    }

    form.reset();
    delete form.dataset.editId;
    await carregarFaturas();
    await carregarDashboard();
  } catch (err) {
    console.error(err);
    alert("Erro ao salvar fatura");
  }
}

// =====================
// ABAS
// =====================

function ativarAba(aba) {
  const dash = document.getElementById("dashboardSection");
  const fat = document.getElementById("faturasSection");
  const tabDash = document.getElementById("tabDashboard");
  const tabFat = document.getElementById("tabFaturas");

  if (!dash || !fat || !tabDash || !tabFat) return;

  if (aba === "dashboard") {
    dash.classList.add("visible");
    fat.classList.remove("visible");
    tabDash.classList.add("active");
    tabFat.classList.remove("active");
  } else {
    fat.classList.add("visible");
    dash.classList.remove("visible");
    tabFat.classList.add("active");
    tabDash.classList.remove("active");
  }
}

// =====================
// INIT
// =====================

document.addEventListener("DOMContentLoaded", () => {
  // abas
  const tabDashboard = document.getElementById("tabDashboard");
  const tabFaturas = document.getElementById("tabFaturas");

  if (tabDashboard) {
    tabDashboard.addEventListener("click", () => ativarAba("dashboard"));
  }
  if (tabFaturas) {
    tabFaturas.addEventListener("click", () => ativarAba("faturas"));
  }

  // botão página inicial
  const btnHome = document.getElementById("btnHome");
  if (btnHome) {
    btnHome.addEventListener("click", () => {
      filtroTransportadora = "";
      filtroVencimento = "";
      filtroNumeroFatura = "";
      const dataInput = document.getElementById("filtroVencimento");
      const buscaNumero = document.getElementById("buscaNumero");
      if (dataInput) dataInput.value = "";
      if (buscaNumero) buscaNumero.value = "";
      ativarAba("dashboard");
      carregarDashboard();
      carregarFaturas();
    });
  }

  // botões de transportadora
  document.querySelectorAll(".transportadora-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      filtroTransportadora = btn.dataset.transportadora || "";
      document
        .querySelectorAll(".transportadora-btn")
        .forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
      ativarAba("faturas");
      carregarFaturas();
    });
  });

  // filtro vencimento
  const filtroVenc = document.getElementById("filtroVencimento");
  if (filtroVenc) {
    filtroVenc.addEventListener("change", (e) => {
      filtroVencimento = e.target.value;
      carregarFaturas();
    });
  }

  // limpar filtros
  const btnLimparFiltros = document.getElementById("btnLimparFiltros");
  if (btnLimparFiltros) {
    btnLimparFiltros.addEventListener("click", () => {
      filtroVencimento = "";
      filtroNumeroFatura = "";
      const dataInput = document.getElementById("filtroVencimento");
      const buscaNumero = document.getElementById("buscaNumero");
      if (dataInput) dataInput.value = "";
      if (buscaNumero) buscaNumero.value = "";
      carregarFaturas();
    });
  }

  // busca por número de fatura
  const buscaNumero = document.getElementById("buscaNumero");
  if (buscaNumero) {
    buscaNumero.addEventListener("input", (e) => {
      filtroNumeroFatura = e.target.value.trim();
      carregarFaturas();
    });
  }

  // botão "Atualizar lista"
  const btnAtualizar = document.getElementById("btnAtualizarFaturas");
  if (btnAtualizar) {
    btnAtualizar.addEventListener("click", carregarFaturas);
  }

  // submit do formulário
  const formFatura = document.getElementById("formFatura");
  if (formFatura) {
    formFatura.addEventListener("submit", salvarFatura);
  }

  // modal anexos
  const modalFechar = document.getElementById("modalFechar");
  const modal = document.getElementById("modalAnexos");
  if (modalFechar && modal) {
    modalFechar.addEventListener("click", () => modal.classList.remove("open"));
    modal.addEventListener("click", (e) => {
      if (e.target.id === "modalAnexos") {
        modal.classList.remove("open");
      }
    });
  }

  // carga inicial
  ativarAba("dashboard");
  carregarDashboard();
  carregarFaturas();
});
