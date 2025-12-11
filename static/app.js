// URL base (vazio = mesmo domínio)
const API_BASE = "";

// Estado de filtros globais
let filtroTransportadora = "";
let filtroVencimento = "";
let filtroNumeroFatura = "";

// Filtros só da aba Faturas
let filtroDataInicioFaturas = "";
let filtroDataFimFaturas = "";
let filtroStatus = "";

// Cache da última lista vinda da API
let ultimaListaFaturas = [];

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

// converte string ISO (yyyy-mm-dd ou data completa) pra Date LOCAL
function parseISODateLocal(isoDate) {
  if (!isoDate) return null;

  if (/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    const [y, m, d] = isoDate.split("-").map(Number);
    return new Date(y, m - 1, d);
  }

  const d = new Date(isoDate);
  return Number.isNaN(d.getTime()) ? null : d;
}

// dd/mm/aaaa
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

// ============ DASHBOARD ============

async function carregarDashboard() {
  try {
    const params = new URLSearchParams();
    if (filtroTransportadora) {
      params.append("transportadora", filtroTransportadora);
    }
    if (filtroVencimento) {
      params.append("ate_vencimento", filtroVencimento);
    }

    // 1) Resumo geral (cards) via API
    const urlResumo =
      params.toString().length > 0
        ? `${API_BASE}/dashboard/resumo?${params.toString()}`
        : `${API_BASE}/dashboard/resumo`;

    const respResumo = await fetch(urlResumo);
    if (!respResumo.ok) throw new Error("Erro ao buscar resumo");

    const dataResumo = await respResumo.json();

    document.getElementById("cardTotal").textContent = formatCurrency(
      dataResumo.total
    );
    document.getElementById("cardPendentes").textContent = formatCurrency(
      dataResumo.pendentes
    );
    document.getElementById("cardAtrasadas").textContent = formatCurrency(
      dataResumo.atrasadas
    );
    document.getElementById("cardEmDia").textContent = formatCurrency(
      dataResumo.em_dia
    );

    // 2) Tabela "Resumo por transportadora" usando a lista de faturas
    let lista = Array.isArray(ultimaListaFaturas)
      ? [...ultimaListaFaturas]
      : [];

    if (lista.length === 0) {
      const urlF =
        params.toString().length > 0
          ? `${API_BASE}/faturas?${params.toString()}`
          : `${API_BASE}/faturas`;
      const respFat = await fetch(urlF);
      if (!respFat.ok) throw new Error("Erro ao buscar faturas");
      lista = await respFat.json();
    }

    renderResumoDashboard(lista);
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar dashboard");
  }
}

// monta tabela horizontal tipo backlog
function renderResumoDashboard(lista) {
  const thead = document.getElementById("theadResumoDashboard");
  const tbody = document.getElementById("tbodyResumoDashboard");
  if (!thead || !tbody) return;

  // Hoje zerado
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);

  // Próxima quarta-feira (getDay: dom=0, seg=1, ter=2, qua=3)
  const weekday = hoje.getDay();
  let diasAteQuarta = (3 - weekday + 7) % 7;
  if (diasAteQuarta === 0) diasAteQuarta = 7;
  const proxQuarta = new Date(hoje);
  proxQuarta.setDate(hoje.getDate() + diasAteQuarta);
  proxQuarta.setHours(0, 0, 0, 0);
  const proxQuartaTime = proxQuarta.getTime();

  // considerar TODAS as datas com faturas em aberto (pendente ou atrasado)
  const datasSet = new Set();
  lista.forEach((f) => {
    const statusLower = (f.status || "").toLowerCase();
    if (
      statusLower !== "pago" && // só abertas
      f.data_vencimento
    ) {
      datasSet.add(f.data_vencimento);
    }
  });

  const datas = Array.from(datasSet).sort(); // ISO já ordena

  // Cabeçalho
  let headerHtml = `
    <tr>
      <th>Transportadora</th>
      <th>Total atrasado</th>
      <th>Total em dia</th>
      <th>Total geral</th>
  `;
  datas.forEach((d) => {
    headerHtml += `<th>${formatDate(d)}</th>`;
  });
  headerHtml += "</tr>";
  thead.innerHTML = headerHtml;

  // Agrupar por transportadora
  const grupos = {};
  lista.forEach((f) => {
    const transp = f.transportadora || "Sem nome";
    if (!grupos[transp]) {
      grupos[transp] = {
        totalAtrasado: 0,
        totalEmDia: 0,
        totalGeral: 0,
        porData: {},
      };
    }

    const valor = Number(f.valor || 0);
    const statusLower = (f.status || "").toLowerCase();

    // Só conta no dashboard se não estiver pago
    if (statusLower === "pago") {
      return;
    }

    grupos[transp].totalGeral += valor;

    const d = parseISODateLocal(f.data_vencimento);
    const vencTime = d ? d.setHours(0, 0, 0, 0) : null;

    if (vencTime !== null) {
      // Regras de classificação:
      // - status "atrasado" => sempre vai pra Total atrasado
      // - status "pendente":
      //      venc < proxQuarta -> atrasado
      //      venc == proxQuarta -> em dia
      if (statusLower === "atrasado") {
        grupos[transp].totalAtrasado += valor;
      } else if (statusLower === "pendente") {
        if (vencTime < proxQuartaTime) {
          grupos[transp].totalAtrasado += valor;
        } else if (vencTime === proxQuartaTime) {
          grupos[transp].totalEmDia += valor;
        }
      }
    }

    const key = f.data_vencimento;
    grupos[transp].porData[key] =
      (grupos[transp].porData[key] || 0) + valor;
  });

  tbody.innerHTML = "";

  let totalGeralAtrasado = 0;
  let totalGeralEmDia = 0;
  let totalGeral = 0;
  const totaisPorData = {};

  Object.entries(grupos).forEach(([transp, g]) => {
    const tr = document.createElement("tr");

    totalGeralAtrasado += g.totalAtrasado;
    totalGeralEmDia += g.totalEmDia;
    totalGeral += g.totalGeral;

    datas.forEach((d) => {
      const v = g.porData[d] || 0;
      totaisPorData[d] = (totaisPorData[d] || 0) + v;
    });

    let html = `
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

  // linha total
  if (Object.keys(grupos).length > 0) {
    const trTotal = document.createElement("tr");
    let html = `
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

// ============ FATURAS (LISTA + RESUMO) ============

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
    if (!resp.ok) throw new Error("Erro ao listar faturas");

    const faturas = await resp.json();
    ultimaListaFaturas = faturas;
    renderizarFaturas();
    // também atualiza dashboard (cards + resumo por transp)
    carregarDashboard();
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar faturas");
  }
}

function renderizarFaturas() {
  const tbody = document.getElementById("tbodyFaturas");
  tbody.innerHTML = "";

  let lista = Array.isArray(ultimaListaFaturas)
    ? [...ultimaListaFaturas]
    : [];

  // Filtro período (apenas aba Faturas)
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

  // Filtro status (aba Faturas)
  if (filtroStatus) {
    const alvo = filtroStatus.toLowerCase();
    lista = lista.filter(
      (f) => (f.status || "").toLowerCase() === alvo
    );
  }

  // RESUMO (cards da aba Faturas) -> aqui continua regra "hoje"
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
      if (vencTime !== null && vencTime < hojeTime) {
        atrasadas += valor;
      } else {
        pendentes += valor;
      }
    } else if (status === "atrasado") {
      atrasadas += valor;
    }
  });

  document.getElementById("fatTotal").textContent = formatCurrency(total);
  document.getElementById("fatPendentes").textContent =
    formatCurrency(pendentes);
  document.getElementById("fatAtrasadas").textContent =
    formatCurrency(atrasadas);
  document.getElementById("fatPagas").textContent = formatCurrency(pagas);

  // TABELA
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
      <td>${formatDate(f.data_vencimento)}</td>
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

// Fechar menus se clicar fora
document.addEventListener("click", () => {
  document
    .querySelectorAll(".menu-dropdown.ativo")
    .forEach((m) => m.classList.remove("ativo"));
});

// ============ EXCLUIR / EDITAR / ANEXOS ============

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
  document.getElementById("formFatura").dataset.editId = f.id;
}

async function abrirModalAnexos(faturaId) {
  document.getElementById("modalFaturaId").textContent = faturaId;
  const lista = document.getElementById("listaAnexos");
  lista.innerHTML = "Carregando...";

  try {
    const resp = await fetch(`${API_BASE}/faturas/${faturaId}/anexos`);
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

    // upload anexos, se houver
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
    filtroDataInicioFaturas = "";
    filtroDataFimFaturas = "";
    filtroStatus = "";

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
      filtroDataInicioFaturas = "";
      filtroDataFimFaturas = "";
      filtroStatus = "";

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

  // Filtro por STATUS (aba faturas)
  const statusSelect = document.getElementById("filtroStatus");
  if (statusSelect) {
    statusSelect.addEventListener("change", (e) => {
      filtroStatus = e.target.value;
      renderizarFaturas();
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
