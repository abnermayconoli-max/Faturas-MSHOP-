// URL base (vazio = mesmo domínio)
const API_BASE = "";

// Estado de filtros
let filtroTransportadora = "";
let filtroVencimento = "";
let filtroNumeroFatura = "";

// ============ HELPERS ============

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

// ============ DASHBOARD ============

async function carregarDashboard() {
  try {
    const params = new URLSearchParams();
    if (filtroTransportadora) {
      params.append("transportadora", filtroTransportadora);
    }

    const url =
      params.toString().length > 0
        ? `${API_BASE}/dashboard/resumo?${params.toString()}`
        : `${API_BASE}/dashboard/resumo`;

    const resp = await fetch(url);
    if (!resp.ok) throw new Error("Erro ao buscar resumo");

    const data = await resp.json();

    document.getElementById("cardTotal").textContent = formatCurrency(data.total);
    document.getElementById("cardPendentes").textContent = formatCurrency(
      data.pendentes
    );
    document.getElementById("cardAtrasadas").textContent = formatCurrency(
      data.atrasadas
    );
    document.getElementById("cardEmDia").textContent = formatCurrency(data.em_dia);
  } catch (err) {
    console.error("Erro ao carregar dashboard:", err);
    alert("Erro ao carregar dashboard");
  }
}

// ============ FATURAS ============

async function carregarFaturas() {
  try {
    const params = new URLSearchParams();
    if (filtroTransportadora) {
      params.append("transportadora", filtroTransportadora);
    }
    if (filtroVencimento) {
      params.append("ate_vencimento", filtroVencimento);
    }
    if (filtroNumeroFatura) {
      params.append("numero_fatura", filtroNumeroFatura);
    }

    const url =
      params.toString().length > 0
        ? `${API_BASE}/faturas?${params.toString()}`
        : `${API_BASE}/faturas`;

    const resp = await fetch(url);
    if (!resp.ok) {
      const texto = await resp.text();
      console.error("Erro HTTP ao listar faturas:", resp.status, texto);
      throw new Error("Erro ao listar faturas");
    }

    const faturas = await resp.json();
    console.log("Faturas recebidas:", faturas);

    const tbody = document.getElementById("tbodyFaturas");
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

      tbody.appendChild(tr);
    });

    // Fecha menus se clicar fora
    document.addEventListener("click", () => {
      document
        .querySelectorAll(".menu-dropdown.ativo")
        .forEach((m) => m.classList.remove("ativo"));
    });
  } catch (err) {
    console.error("Erro ao carregar faturas:", err);
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
  // muda para aba de cadastro para editar
  ativarAba("cadastro");

  document.getElementById("inputTransportadora").value = f.transportadora;
  document.getElementById("inputNumeroFatura").value = f.numero_fatura;
  document.getElementById("inputValor").value = f.valor;
  document.getElementById("inputVencimento").value = f.data_vencimento
    ? String(f.data_vencimento).slice(0, 10)
    : "";
  document.getElementById("inputStatus").value = f.status;
  document.getElementById("inputObservacao").value = f.observacao ?? "";

  document.getElementById("formFatura").dataset.editId = f.id;
}

// ============ ANEXOS (MODAL) ============

async function abrirModalAnexos(faturaId) {
  document.getElementById("modalFaturaId").textContent = faturaId;
  const lista = document.getElementById("listaAnexos");
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

    const inputAnexos = document.getElementById("inputAnexos");
    if (inputAnexos.files.length > 0) {
      const fd = new FormData();
      for (const file of inputAnexos.files) {
        fd.append("files", file);
      }
      const respAnexos = await fetch(
        `${API_BASE}/faturas/${fatura.id}/anexos`,
        {
          method: "POST",
          body: fd,
        }
      );
      if (!respAnexos.ok) {
        console.error("Erro ao enviar anexos");
      }
    }

    form.reset();
    delete form.dataset.editId;

    // depois de salvar, vai pra aba Faturas para visualizar
    ativarAba("faturas");

    await carregarFaturas();
    await carregarDashboard();
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

  const tabDash = document.getElementById("tabDashboard");
  const tabCad = document.getElementById("tabCadastro");
  const tabFat = document.getElementById("tabFaturas");

  // esconde todas
  [dash, cad, fat].forEach((sec) => sec.classList.remove("visible"));
  [tabDash, tabCad, tabFat].forEach((t) => t.classList.remove("active"));

  if (aba === "dashboard") {
    dash.classList.add("visible");
    tabDash.classList.add("active");
  } else if (aba === "cadastro") {
    cad.classList.add("visible");
    tabCad.classList.add("active");
  } else {
    fat.classList.add("visible");
    tabFat.classList.add("active");
  }
}

// ============ INIT ============

document.addEventListener("DOMContentLoaded", () => {
  // Tabs
  document.getElementById("tabDashboard").addEventListener("click", () =>
    ativarAba("dashboard")
  );
  document.getElementById("tabCadastro").addEventListener("click", () =>
    ativarAba("cadastro")
  );
  document.getElementById("tabFaturas").addEventListener("click", () =>
    ativarAba("faturas")
  );

  // Botão página inicial
  document.getElementById("btnHome").addEventListener("click", () => {
    filtroTransportadora = "";
    filtroVencimento = "";
    filtroNumeroFatura = "";
    const filtroVencInput = document.getElementById("filtroVencimento");
    if (filtroVencInput) filtroVencInput.value = "";
    const buscaNumero = document.getElementById("buscaNumero");
    if (buscaNumero) buscaNumero.value = "";

    ativarAba("dashboard");
    carregarDashboard();
    carregarFaturas();
  });

  // Botões de transportadora
  document.querySelectorAll(".transportadora-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      filtroTransportadora = btn.dataset.transportadora || "";
      document
        .querySelectorAll(".transportadora-btn")
        .forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
      // Atualiza tanto dashboard quanto faturas
      carregarDashboard();
      carregarFaturas();
    })
  );

  const filtroVencInput = document.getElementById("filtroVencimento");
  if (filtroVencInput) {
    filtroVencInput.addEventListener("change", (e) => {
      filtroVencimento = e.target.value;
      carregarFaturas();
      carregarDashboard();
    });
  }

  const btnLimparFiltros = document.getElementById("btnLimparFiltros");
  if (btnLimparFiltros) {
    btnLimparFiltros.addEventListener("click", () => {
      filtroVencimento = "";
      filtroNumeroFatura = "";
      if (filtroVencInput) filtroVencInput.value = "";
      const buscaNumero = document.getElementById("buscaNumero");
      if (buscaNumero) buscaNumero.value = "";
      carregarFaturas();
      carregarDashboard();
    });
  }

  const buscaNumero = document.getElementById("buscaNumero");
  if (buscaNumero) {
    buscaNumero.addEventListener("input", (e) => {
      filtroNumeroFatura = e.target.value.trim();
      carregarFaturas();
    });
  }

  const btnAtualizar = document.getElementById("btnAtualizarFaturas");
  if (btnAtualizar) {
    btnAtualizar.addEventListener("click", carregarFaturas);
  }

  document
    .getElementById("formFatura")
    .addEventListener("submit", salvarFatura);

  document
    .getElementById("modalFechar")
    .addEventListener("click", () =>
      document.getElementById("modalAnexos").classList.remove("open")
    );
  document
    .getElementById("modalAnexos")
    .addEventListener("click", (e) => {
      if (e.target.id === "modalAnexos") {
        document.getElementById("modalAnexos").classList.remove("open");
      }
    });

  // Aba inicial
  ativarAba("dashboard");
  carregarDashboard();
  carregarFaturas();
});
