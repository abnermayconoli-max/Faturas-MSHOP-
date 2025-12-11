// URL base (vazio = mesmo domínio)
const API_BASE = "";

// Estado de filtros globais
let filtroTransportadora = "";
let filtroVencimento = "";
let filtroNumeroFatura = "";
let filtroStatus = "";

// Filtros só da aba Faturas (período)
let filtroDataInicioFaturas = "";
let filtroDataFimFaturas = "";

// Cache da última lista vinda da API
let ultimaListaFaturas = [];

// ============ HELPERS DE DATA / VALOR ============

function formatCurrency(valor) {
  if (valor === null || valor === undefined) return "R$ 0,00";
  const n = Number(valor) || 0;
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
}

// parse "YYYY-MM-DD" sem problema de fuso
function parseISODateLocal(isoDate) {
  if (!isoDate) return null;

  if (/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    const [y, m, d] = isoDate.split("-").map(Number);
    return new Date(y, m - 1, d);
  }

  const d = new Date(isoDate);
  return Number.isNaN(d.getTime()) ? null : d;
}

// hoje sem horário
function hojeSemHora() {
  const agora = new Date();
  return new Date(agora.getFullYear(), agora.getMonth(), agora.getDate());
}

// ============ DASHBOARD + FATURAS (LISTA + RESUMO) ============

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
    if (filtroStatus) {
      params.append("status", filtroStatus);
    }

    const url =
      params.toString().length > 0
        ? `${API_BASE}/faturas?${params.toString()}`
        : `${API_BASE}/faturas`;

    const resp = await fetch(url);
    if (!resp.ok) throw new Error("Erro ao listar faturas");

    const faturas = await resp.json();
    ultimaListaFaturas = faturas;
    renderizarFaturas();
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar faturas");
  }
}

function calcularTotais(lista) {
  let total = 0;
  let pendentes = 0;
  let atrasadas = 0;
  let pagas = 0;

  const hoje = hojeSemHora();
  const hojeTime = hoje.getTime();

  lista.forEach((f) => {
    const valor = Number(f.valor || 0);
    total += valor;

    const status = (f.status || "").toLowerCase();
    const d = parseISODateLocal(f.data_vencimento);
    const vencTime = d ? d.getTime() : null;

    if (status === "pago") {
      pagas += valor;
      return;
    }

    // não pago => pendente
    pendentes += valor;

    if (vencTime !== null && vencTime < hojeTime) {
      // vencido e não pago => atrasado
      atrasadas += valor;
    }
  });

  const emDia = pendentes - atrasadas;

  return {
    total,
    pendentes,
    atrasadas,
    emDia,
    pagas,
  };
}

function calcularResumoPorTransportadora(lista) {
  const hoje = hojeSemHora();
  const hojeTime = hoje.getTime();

  const mapa = new Map();

  lista.forEach((f) => {
    const transportadora = f.transportadora || "—";
    const valor = Number(f.valor || 0);
    const status = (f.status || "").toLowerCase();
    const d = parseISODateLocal(f.data_vencimento);
    const vencTime = d ? d.getTime() : null;

    if (!mapa.has(transportadora)) {
      mapa.set(transportadora, {
        transportadora,
        atrasado: 0,
        emDia: 0,
      });
    }

    const info = mapa.get(transportadora);

    // só considera pendente (não pago) na análise por transportadora
    if (status === "pago") {
      return;
    }

    if (vencTime !== null && vencTime < hojeTime) {
      info.atrasado += valor;
    } else {
      info.emDia += valor;
    }
  });

  const linhas = Array.from(mapa.values()).map((row) => ({
    ...row,
    total: row.atrasado + row.emDia,
  }));

  // total geral
  const totalGeral = linhas.reduce(
    (acc, r) => {
      acc.atrasado += r.atrasado;
      acc.emDia += r.emDia;
      acc.total += r.total;
      return acc;
    },
    { atrasado: 0, emDia: 0, total: 0 }
  );

  return { linhas, totalGeral };
}

function renderizarResumoTransportadora(lista) {
  const tbody = document.getElementById("tbodyResumoTransportadora");
  if (!tbody) return; // se não existir no HTML, ignora

  tbody.innerHTML = "";

  const { linhas, totalGeral } = calcularResumoPorTransportadora(lista);

  if (linhas.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.textContent = "Sem dados para o filtro atual.";
    td.style.textAlign = "center";
    td.style.padding = "12px";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  linhas.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.transportadora}</td>
      <td>${formatCurrency(row.atrasado)}</td>
      <td>${formatCurrency(row.emDia)}</td>
      <td>${formatCurrency(row.total)}</td>
    `;
    tbody.appendChild(tr);
  });

  // linha Total geral
  const trTotal = document.createElement("tr");
  trTotal.classList.add("resumo-total-geral");
  trTotal.innerHTML = `
    <td>Total geral</td>
    <td>${formatCurrency(totalGeral.atrasado)}</td>
    <td>${formatCurrency(totalGeral.emDia)}</td>
    <td>${formatCurrency(totalGeral.total)}</td>
  `;
  tbody.appendChild(trTotal);
}

function renderizarFaturas() {
  const tbody = document.getElementById("tbodyFaturas");
  tbody.innerHTML = "";

  // aplica filtro de período da aba Faturas
  let lista = Array.isArray(ultimaListaFaturas)
    ? [...ultimaListaFaturas]
    : [];

  if (filtroDataInicioFaturas || filtroDataFimFaturas) {
    lista = lista.filter((f) => {
      if (!f.data_vencimento) return false;

      const d = parseISODateLocal(f.data_vencimento);
      if (!d) return false;
      const time = d.getTime();

      if (filtroDataInicioFaturas) {
        const di = parseISODateLocal(filtroDataInicioFaturas);
        if (!di) return false;
        const ti = di.getTime();
        if (time < ti) return false;
      }
      if (filtroDataFimFaturas) {
        const df = parseISODateLocal(filtroDataFimFaturas);
        if (!df) return false;
        const tf = df.getTime();
        if (time > tf) return false;
      }
      return true;
    });
  }

  // ========== RESUMOS (cards) ==========
  const totais = calcularTotais(lista);

  // Cards da aba FATURAS
  const fatTotalEl = document.getElementById("fatTotal");
  const fatPendentesEl = document.getElementById("fatPendentes");
  const fatAtrasadasEl = document.getElementById("fatAtrasadas");
  const fatPagasEl = document.getElementById("fatPagas");

  if (fatTotalEl) fatTotalEl.textContent = formatCurrency(totais.total);
  if (fatPendentesEl)
    fatPendentesEl.textContent = formatCurrency(totais.pendentes);
  if (fatAtrasadasEl)
    fatAtrasadasEl.textContent = formatCurrency(totais.atrasadas);
  if (fatPagasEl) fatPagasEl.textContent = formatCurrency(totais.pagas);

  // Cards do DASHBOARD (usa mesma regra)
  const cardTotalEl = document.getElementById("cardTotal");
  const cardPendentesEl = document.getElementById("cardPendentes");
  const cardAtrasadasEl = document.getElementById("cardAtrasadas");
  const cardEmDiaEl = document.getElementById("cardEmDia");

  if (cardTotalEl) cardTotalEl.textContent = formatCurrency(totais.total);
  if (cardPendentesEl)
    cardPendentesEl.textContent = formatCurrency(totais.pendentes);
  if (cardAtrasadasEl)
    cardAtrasadasEl.textContent = formatCurrency(totais.atrasadas);
  if (cardEmDiaEl) cardEmDiaEl.textContent = formatCurrency(totais.emDia);

  // Resumo por transportadora no dashboard
  renderizarResumoTransportadora(lista);

  // ========== TABELA FATURAS ==========
  if (lista.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 9;
    td.textContent = "Nenhuma fatura encontrada.";
    td.style.textAlign = "center";
    td.style.padding = "12px";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  lista.forEach((f) => {
    const tr = document.createElement("tr");

    tr.innerHTML = `
      <td>${f.id}</td>
      <td>${f.transportadora}</td>
      <td>${f.responsavel ?? ""}</td>
      <td>${f.numero_fatura}</td>
      <td>${formatCurrency(f.valor)}</td>
      <td>${formatarDataBR(f.data_vencimento)}</td>
      <td>${f.status}</td>
      <td>${f.observacao ?? ""}</td>
      <td class="acoes">
        <button type="button" class="menu-btn">⋮</button>
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
      e.preventDefault();
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
}

// helper para exibir data dd/mm/yyyy sem perder 1 dia
function formatarDataBR(isoDate) {
  if (!isoDate) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    const [y, m, d] = isoDate.split("-");
    return `${d}/${m}/${y}`;
  }
  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString("pt-BR");
}

// Fechar menus se clicar fora
document.addEventListener("click", () => {
  document
    .querySelectorAll(".menu-dropdown.ativo")
    .forEach((m) => m.classList.remove("ativo"));
});

// ============ CRUD FATURA (FRONT) ============

async function excluirFatura(id) {
  if (!confirm(`Excluir fatura ${id}?`)) return;

  try {
    const resp = await fetch(`${API_BASE}/faturas/${id}`, {
      method: "DELETE",
    });
    if (!resp.ok) throw new Error("Erro ao excluir");
    await carregarFaturas();
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

  const form = document.getElementById("formFatura");
  form.dataset.editId = f.id;
}

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
      console.log("Status ao salvar:", resp.status);
      throw new Error("Erro ao salvar fatura");
    }

    const fatura = await resp.json();

    // Envio de anexos (se tiver)
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
    ativarAba("faturas");
    await carregarFaturas();
  } catch (err) {
    console.error(err);
    alert("Erro ao salvar fatura");
  }
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

    if (!anexos || anexos.length === 0) {
      lista.innerHTML = "<li>Sem anexos.</li>";
    } else {
      lista.innerHTML = "";
      anexos.forEach((a) => {
        const li = document.createElement("li");

        const link = document.createElement("a");
        link.href = `${API_BASE}/anexos/${a.id}`;
        link.target = "_blank";
        link.textContent = a.original_name;

        const btnDel = document.createElement("button");
        btnDel.textContent = "Excluir";
        btnDel.classList.add("btn-excluir-anexo");
        btnDel.addEventListener("click", async () => {
          if (!confirm(`Excluir anexo "${a.original_name}"?`)) return;
          try {
            const respDel = await fetch(`${API_BASE}/anexos/${a.id}`, {
              method: "DELETE",
            });
            if (!respDel.ok) throw new Error("Erro ao excluir anexo");
            await abrirModalAnexos(faturaId); // recarrega lista
          } catch (err) {
            console.error(err);
            alert("Erro ao excluir anexo");
          }
        });

        li.appendChild(link);
        li.appendChild(btnDel);
        lista.appendChild(li);
      });
    }
  } catch (err) {
    console.error(err);
    lista.innerHTML = "<li>Erro ao carregar anexos.</li>";
  }

  document.getElementById("modalAnexos").classList.add("open");
}

// ============ ABAS / NAVEGAÇÃO ============

function ativarAba(aba) {
  const dash = document.getElementById("dashboardSection");
  const cad = document.getElementById("cadastroSection");
  const fat = document.getElementById("faturasSection");
  const tabDash = document.getElementById("tabDashboard");
  const tabCad = document.getElementById("tabCadastro");
  const tabFat = document.getElementById("tabFaturas");

  [dash, cad, fat].forEach((s) => s.classList.remove("visible"));
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

// ============ EXPORTAR EXCEL (CSV) ============

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

  window.open(url, "_blank");
}

// ============ INIT ============

document.addEventListener("DOMContentLoaded", () => {
  // Abas
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
    filtroStatus = "";
    filtroDataInicioFaturas = "";
    filtroDataFimFaturas = "";

    const filtroVencInput = document.getElementById("filtroVencimento");
    if (filtroVencInput) filtroVencInput.value = "";

    const buscaNumero = document.getElementById("buscaNumero");
    if (buscaNumero) buscaNumero.value = "";

    const ini = document.getElementById("filtroDataInicioFaturas");
    const fim = document.getElementById("filtroDataFimFaturas");
    if (ini) ini.value = "";
    if (fim) fim.value = "";

    const statusSelect = document.getElementById("filtroStatus");
    if (statusSelect) statusSelect.value = "";

    document
      .querySelectorAll(".transportadora-btn")
      .forEach((b) => b.classList.remove("selected"));

    ativarAba("dashboard");
    carregarFaturas();
  });

  // Transportadoras sidebar
  document.querySelectorAll(".transportadora-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      filtroTransportadora = btn.dataset.transportadora || "";
      document
        .querySelectorAll(".transportadora-btn")
        .forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
      carregarFaturas();
    })
  );

  // Filtro por vencimento sidebar
  const filtroVencInput = document.getElementById("filtroVencimento");
  if (filtroVencInput) {
    filtroVencInput.addEventListener("change", (e) => {
      filtroVencimento = e.target.value;
      carregarFaturas();
    });
  }

  const btnLimparFiltros = document.getElementById("btnLimparFiltros");
  if (btnLimparFiltros) {
    btnLimparFiltros.addEventListener("click", () => {
      filtroVencimento = "";
      filtroNumeroFatura = "";
      filtroStatus = "";
      filtroDataInicioFaturas = "";
      filtroDataFimFaturas = "";

      if (filtroVencInput) filtroVencInput.value = "";
      const buscaNumero = document.getElementById("buscaNumero");
      if (buscaNumero) buscaNumero.value = "";

      const ini = document.getElementById("filtroDataInicioFaturas");
      const fim = document.getElementById("filtroDataFimFaturas");
      if (ini) ini.value = "";
      if (fim) fim.value = "";

      const statusSelect = document.getElementById("filtroStatus");
      if (statusSelect) statusSelect.value = "";

      carregarFaturas();
    });
  }

  // Busca nº fatura
  const buscaNumero = document.getElementById("buscaNumero");
  if (buscaNumero) {
    buscaNumero.addEventListener("input", (e) => {
      filtroNumeroFatura = e.target.value.trim();
      carregarFaturas();
    });
  }

  // Filtro por período da aba Faturas
  const ini = document.getElementById("filtroDataInicioFaturas");
  const fim = document.getElementById("filtroDataFimFaturas");
  if (ini) {
    ini.addEventListener("change", (e) => {
      filtroDataInicioFaturas = e.target.value;
      renderizarFaturas();
    });
  }
  if (fim) {
    fim.addEventListener("change", (e) => {
      filtroDataFimFaturas = e.target.value;
      renderizarFaturas();
    });
  }

  // Filtro por STATUS
  const statusSelect = document.getElementById("filtroStatus");
  if (statusSelect) {
    statusSelect.addEventListener("change", (e) => {
      filtroStatus = e.target.value; // "", "pendente", "pago", "atrasado"
      carregarFaturas();
    });
  }

  // Atualizar lista manualmente
  const btnAtualizar = document.getElementById("btnAtualizarFaturas");
  if (btnAtualizar) {
    btnAtualizar.addEventListener("click", (e) => {
      e.preventDefault();
      carregarFaturas();
    });
  }

  // Exportar Excel
  const btnExportar = document.getElementById("btnExportarExcel");
  if (btnExportar) {
    btnExportar.addEventListener("click", exportarExcel);
  }

  // Formulário
  document.getElementById("formFatura").addEventListener("submit", salvarFatura);

  // Modal anexos
  document
    .getElementById("modalFechar")
    .addEventListener("click", () =>
      document.getElementById("modalAnexos").classList.remove("open")
    );
  document.getElementById("modalAnexos").addEventListener("click", (e) => {
    if (e.target.id === "modalAnexos") {
      document.getElementById("modalAnexos").classList.remove("open");
    }
  });

  // Primeira carga
  carregarFaturas();
});
