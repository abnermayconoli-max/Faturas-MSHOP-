// URL base (vazio = mesmo domínio)
const API_BASE = "";

// Estado de filtros globais
let filtroTransportadora = "";
let filtroVencimento = "";
let filtroNumeroFatura = "";

// Filtros só da aba Faturas
let filtroDataInicioFaturas = "";
let filtroDataFimFaturas = "";
let filtroStatus = ""; // novo filtro de status

// Cache da última lista vinda da API
let ultimaListaFaturas = [];

// ============ HELPERS ============

// Converte número em moeda BR
function formatCurrency(valor) {
  if (valor === null || valor === undefined) return "R$ 0,00";
  const n = Number(valor) || 0;
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
}

// Parse de data YYYY-MM-DD como data LOCAL (sem problema de fuso)
function parseISODateLocal(isoDate) {
  if (!isoDate) return null;

  // Formato só data: 2025-12-17
  if (/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    const [y, m, d] = isoDate.split("-").map(Number);
    return new Date(y, m - 1, d); // ano, mês-1, dia (data local)
  }

  const d = new Date(isoDate);
  return Number.isNaN(d.getTime()) ? null : d;
}

// Formata data para dd/mm/aaaa sem perder 1 dia
function formatDate(isoDate) {
  if (!isoDate) return "";

  // Se vier só YYYY-MM-DD, monta manualmente
  if (/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    const [y, m, d] = isoDate.split("-");
    return `${d}/${m}/${y}`;
  }

  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString("pt-BR");
}

// ============ DASHBOARD ============

// Agora o dashboard usa o mesmo resumo calculado em renderizarFaturas.
async function carregarDashboard() {
  // Nada específico: o resumo é atualizado em renderizarFaturas()
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
    renderizarFaturas(); // atualiza tabela + cards + dashboard
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

  // ------- Filtro por período só da aba Faturas -------
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

  // ------- Filtro por STATUS -------
  if (filtroStatus) {
    lista = lista.filter((f) => {
      const st = (f.status || "").toLowerCase();
      return st === filtroStatus;
    });
  }

  // ------- RESUMO (aba Faturas + Dashboard) -------
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
    const dVenc = parseISODateLocal(f.data_vencimento);
    const vencTime =
      dVenc && !Number.isNaN(dVenc.getTime())
        ? dVenc.setHours(0, 0, 0, 0)
        : null;

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

  // ----- Cards da aba FATURAS -----
  document.getElementById("fatTotal").textContent = formatCurrency(total);
  document.getElementById("fatPendentes").textContent = formatCurrency(pendentes);
  document.getElementById("fatAtrasadas").textContent = formatCurrency(atrasadas);
  document.getElementById("fatPagas").textContent = formatCurrency(pagas);

  // ----- Cards do DASHBOARD (mesmos valores) -----
  try {
    const cardTotal = document.getElementById("cardTotal");
    const cardPendentes = document.getElementById("cardPendentes");
    const cardAtrasadas = document.getElementById("cardAtrasadas");
    const cardEmDia = document.getElementById("cardEmDia");

    if (cardTotal && cardPendentes && cardAtrasadas && cardEmDia) {
      cardTotal.textContent = formatCurrency(total);
      cardPendentes.textContent = formatCurrency(pendentes);
      cardAtrasadas.textContent = formatCurrency(atrasadas);

      const emDia = total - atrasadas;
      cardEmDia.textContent = formatCurrency(emDia);
    }
  } catch (e) {
    console.warn("Erro ao atualizar dashboard:", e);
  }

  // ------- TABELA -------
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
  // Vai pra aba Cadastro já com os dados
  ativarAba("cadastro");
  document.getElementById("inputTransportadora").value = f.transportadora;
  document.getElementById("inputNumeroFatura").value = f.numero_fatura;
  document.getElementById("inputValor").value = f.valor;
  document.getElementById("inputVencimento").value = f.data_vencimento;
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

    if (!Array.isArray(anexos) || anexos.length === 0) {
      lista.innerHTML = "<li>Sem anexos.</li>";
    } else {
      lista.innerHTML = "";
      anexos.forEach((a) => {
        const li = document.createElement("li");

        const link = document.createElement("a");
        link.href = `${API_BASE}/anexos/${a.id}`;
        link.target = "_blank";
        link.textContent = a.original_name || `Anexo ${a.id}`;

        const btnDel = document.createElement("button");
        btnDel.textContent = "Excluir";
        btnDel.classList.add("btn-excluir-anexo");

        btnDel.addEventListener("click", async () => {
          if (!confirm(`Excluir anexo "${a.original_name}"?`)) return;
          try {
            const respDel = await fetch(`${API_BASE}/anexos/${a.id}`, {
              method: "DELETE",
            });
            if (!respDel.ok) {
              throw new Error("Erro ao excluir anexo");
            }
            // Recarrega lista após excluir
            await abrirModalAnexos(faturaId);
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
    await carregarFaturas();
    await carregarDashboard();
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

  // Filtro por STATUS
  const statusSelect = document.getElementById("filtroStatus");
  if (statusSelect) {
    statusSelect.addEventListener("change", (e) => {
      filtroStatus = e.target.value; // "", "pendente", "pago", "atrasado"
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
