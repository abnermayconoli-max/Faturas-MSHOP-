// URL base da API (em produção, como tudo está no mesmo domínio, deixe vazio)
const API_BASE = "";

// Estado de filtros
let filtroTransportadora = "";
let filtroVencimentoSidebar = "";
let filtroNumeroFatura = "";
let periodoInicio = "";
let periodoFim = "";

// ============ HELPERS ============

function formatCurrency(valor) {
  if (valor === null || valor === undefined) return "R$ 0,00";
  const num = Number(valor) || 0;
  return num.toLocaleString("pt-BR", {
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

// Converte "dd/mm/aaaa" -> "aaaa-mm-dd"
function brToIsoDate(str) {
  if (!str) return "";
  const partes = str.split("/");
  if (partes.length !== 3) return "";
  const [dia, mes, ano] = partes;
  if (!dia || !mes || !ano) return "";
  return `${ano}-${mes.padStart(2, "0")}-${dia.padStart(2, "0")}`;
}

// ============ DASHBOARD ============

async function carregarDashboard() {
  try {
    const params = new URLSearchParams();

    if (filtroTransportadora) {
      params.append("transportadora", filtroTransportadora);
    }

    // período de vencimento (do / até) nos cards
    if (periodoFim) {
      params.append("ate_vencimento", periodoFim);
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

    // pagas = total - pendentes
    const pagas = (data.total || 0) - (data.pendentes || 0);
    document.getElementById("cardPagas").textContent = formatCurrency(pagas);
  } catch (err) {
    console.error(err);
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

    // filtro da sidebar (ate_vencimento único)
    if (filtroVencimentoSidebar) {
      params.append("ate_vencimento", filtroVencimentoSidebar);
    }

    if (filtroNumeroFatura) {
      params.append("numero_fatura", filtroNumeroFatura);
    }

    const url =
      params.toString().length > 0
        ? `${API_BASE}/faturas?${params.toString()}`
        : `${API_BASE}/faturas`;

    const resp = await fetch(url);
    if (!resp.ok) throw new Error("Erro ao listar faturas");

    const faturas = await resp.json();
    const tbody = document.getElementById("tbodyFaturas");
    tbody.innerHTML = "";

    faturas.forEach((f) => {
      const tr = document.createElement("tr");

      // Guardar dados no dataset para edição/status depois
      tr.dataset.id = f.id;
      tr.dataset.transportadora = f.transportadora;
      tr.dataset.numeroFatura = f.numero_fatura;
      tr.dataset.valor = f.valor;
      tr.dataset.vencimento = f.data_vencimento;
      tr.dataset.status = f.status;
      tr.dataset.observacao = f.observacao || "";

      tr.innerHTML = `
        <td>${f.id}</td>
        <td>${f.transportadora}</td>
        <td>${f.responsavel ?? ""}</td>
        <td>${f.numero_fatura}</td>
        <td>${formatCurrency(f.valor)}</td>
        <td>${formatDate(f.data_vencimento)}</td>
        <td>${f.status}</td>
        <td>${f.observacao ?? ""}</td>
      `;

      // célula de ações
      const tdAcoes = document.createElement("td");
      tdAcoes.classList.add("acoes");
      tdAcoes.innerHTML = `
        <button type="button" class="menu-btn">⋮</button>
        <div class="menu-dropdown">
          <button type="button" data-acao="editar">Editar</button>
          <button type="button" data-acao="status">Alterar status</button>
          <button type="button" data-acao="anexos">Anexos</button>
          <button type="button" data-acao="excluir">Excluir</button>
        </div>
      `;
      tr.appendChild(tdAcoes);

      tbody.appendChild(tr);
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

async function alterarStatus(id, statusAtual) {
  const novo = prompt(
    "Novo status (pendente, pago, atrasado):",
    statusAtual || "pendente"
  );
  if (!novo || novo === statusAtual) return;

  try {
    const resp = await fetch(`${API_BASE}/faturas/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: novo }),
    });
    if (!resp.ok) throw new Error("Erro ao alterar status");
    await carregarFaturas();
    await carregarDashboard();
  } catch (err) {
    console.error(err);
    alert("Erro ao alterar status");
  }
}

function preencherFormularioEdicaoDataset(ds) {
  const form = document.getElementById("formFatura");
  form.dataset.editId = ds.id;

  document.getElementById("inputTransportadora").value = ds.transportadora;
  document.getElementById("inputNumeroFatura").value = ds.numeroFatura;
  document.getElementById("inputValor").value = ds.valor;
  document.getElementById("inputVencimento").value = ds.vencimento;
  document.getElementById("inputStatus").value = ds.status;
  document.getElementById("inputObservacao").value = ds.observacao || "";
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

    if (!resp.ok) {
      console.error("Status ao salvar:", resp.status);
      throw new Error("Erro ao salvar fatura");
    }

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
    await carregarFaturas();
    await carregarDashboard();
  } catch (err) {
    console.error(err);
    alert("Erro ao salvar fatura");
  }
}

// ============ EXPORTAR EXCEL ============

function exportarExcel() {
  const params = new URLSearchParams();
  if (filtroTransportadora) {
    params.append("transportadora", filtroTransportadora);
  }
  if (filtroNumeroFatura) {
    params.append("numero_fatura", filtroNumeroFatura);
  }
  const url =
    params.toString().length > 0
      ? `${API_BASE}/faturas/exportar?${params.toString()}`
      : `${API_BASE}/faturas/exportar`;

  window.location.href = url;
}

// ============ ABAS / NAVEGAÇÃO / EVENTOS ============

function ativarAba(aba) {
  const dash = document.getElementById("dashboardSection");
  const cad = document.getElementById("cadastroSection");
  const fat = document.getElementById("faturasSection");

  const tabDash = document.getElementById("tabDashboard");
  const tabCad = document.getElementById("tabCadastro");
  const tabFat = document.getElementById("tabFaturas");

  dash.classList.remove("visible");
  cad.classList.remove("visible");
  fat.classList.remove("visible");
  tabDash.classList.remove("active");
  tabCad.classList.remove("active");
  tabFat.classList.remove("active");

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

// Fechar todos os dropdowns
function fecharTodosMenus() {
  document
    .querySelectorAll(".menu-dropdown.ativo")
    .forEach((m) => m.classList.remove("ativo"));
}

document.addEventListener("DOMContentLoaded", () => {
  // abas
  document.getElementById("tabDashboard").addEventListener("click", () =>
    ativarAba("dashboard")
  );
  document.getElementById("tabCadastro").addEventListener("click", () =>
    ativarAba("cadastro")
  );
  document.getElementById("tabFaturas").addEventListener("click", () =>
    ativarAba("faturas")
  );

  // botão Página inicial
  document.getElementById("btnHome").addEventListener("click", () => {
    filtroTransportadora = "";
    filtroVencimentoSidebar = "";
    filtroNumeroFatura = "";
    periodoInicio = "";
    periodoFim = "";

    const filtroVencInput = document.getElementById("filtroVencimento");
    if (filtroVencInput) filtroVencInput.value = "";

    const buscaNumero = document.getElementById("buscaNumero");
    if (buscaNumero) buscaNumero.value = "";

    const ini = document.getElementById("periodoInicio");
    const fim = document.getElementById("periodoFim");
    if (ini) ini.value = "";
    if (fim) fim.value = "";

    ativarAba("dashboard");
    carregarDashboard();
    carregarFaturas();
  });

  // filtros de transportadora (sidebar)
  document.querySelectorAll(".transportadora-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      filtroTransportadora = btn.dataset.transportadora || "";
      document
        .querySelectorAll(".transportadora-btn")
        .forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
      carregarDashboard();
      carregarFaturas();
    })
  );

  // filtro vencimento lateral
  const filtroVencInput = document.getElementById("filtroVencimento");
  if (filtroVencInput) {
    filtroVencInput.addEventListener("change", (e) => {
      filtroVencimentoSidebar = e.target.value;
      carregarDashboard();
      carregarFaturas();
    });
  }

  // limpar filtros laterais
  const btnLimparFiltros = document.getElementById("btnLimparFiltros");
  if (btnLimparFiltros) {
    btnLimparFiltros.addEventListener("click", () => {
      filtroVencimentoSidebar = "";
      filtroNumeroFatura = "";
      if (filtroVencInput) filtroVencInput.value = "";
      const buscaNumero = document.getElementById("buscaNumero");
      if (buscaNumero) buscaNumero.value = "";
      carregarDashboard();
      carregarFaturas();
    });
  }

  // busca por número de fatura (topo da aba faturas)
  const buscaNumero = document.getElementById("buscaNumero");
  if (buscaNumero) {
    buscaNumero.addEventListener("input", (e) => {
      filtroNumeroFatura = e.target.value.trim();
      carregarFaturas();
    });
  }

  // período de vencimento (cards + tabela)
  const ini = document.getElementById("periodoInicio");
  const fim = document.getElementById("periodoFim");
  if (ini) {
    ini.addEventListener("change", (e) => {
      periodoInicio = e.target.value;
      carregarDashboard();
      carregarFaturas();
    });
  }
  if (fim) {
    fim.addEventListener("change", (e) => {
      periodoFim = e.target.value;
      carregarDashboard();
      carregarFaturas();
    });
  }

  // botão Atualizar lista
  const btnAtualizar = document.getElementById("btnAtualizarFaturas");
  if (btnAtualizar) {
    btnAtualizar.addEventListener("click", () => {
      carregarDashboard();
      carregarFaturas();
    });
  }

  // botão Exportar Excel
  const btnExportar = document.getElementById("btnExportarExcel");
  if (btnExportar) {
    btnExportar.addEventListener("click", exportarExcel);
  }

  // submit do formulário
  document.getElementById("formFatura").addEventListener("submit", salvarFatura);

  // modal anexos
  document.getElementById("modalFechar").addEventListener("click", () =>
    document.getElementById("modalAnexos").classList.remove("open")
  );
  document.getElementById("modalAnexos").addEventListener("click", (e) => {
    if (e.target.id === "modalAnexos") {
      document.getElementById("modalAnexos").classList.remove("open");
    }
  });

  // Delegação de eventos do menu de ações (resolve o problema do clique)
  const tbody = document.getElementById("tbodyFaturas");

  tbody.addEventListener("click", async (e) => {
    const btnMenu = e.target.closest(".menu-btn");
    if (btnMenu) {
      e.stopPropagation();
      const cell = btnMenu.closest(".acoes");
      const menu = cell.querySelector(".menu-dropdown");
      const aberto = menu.classList.contains("ativo");
      fecharTodosMenus();
      if (!aberto) {
        menu.classList.add("ativo");
      }
      return;
    }

    const itemMenu = e.target.closest(".menu-dropdown button");
    if (itemMenu) {
      e.stopPropagation();
      const acao = itemMenu.dataset.acao;
      const tr = itemMenu.closest("tr");
      const ds = tr.dataset;

      if (acao === "excluir") {
        await excluirFatura(ds.id);
      } else if (acao === "editar") {
        preencherFormularioEdicaoDataset(ds);
        ativarAba("cadastro");
      } else if (acao === "status") {
        await alterarStatus(ds.id, ds.status);
      } else if (acao === "anexos") {
        abrirModalAnexos(ds.id);
      }

      fecharTodosMenus();
    }
  });

  // Fecha dropdown se clicar fora
  document.addEventListener("click", () => {
    fecharTodosMenus();
  });

  // carga inicial
  ativarAba("dashboard");
  carregarDashboard();
  carregarFaturas();
});
