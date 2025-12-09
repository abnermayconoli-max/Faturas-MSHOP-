// =======================
// ESTADO GLOBAL
// =======================

const estado = {
  transportadora: "",
  vencimentoAte: "",
  numeroFaturaBusca: "",
  faturaEmEdicaoId: null,
};

// =======================
// HELPERS
// =======================

function formatarBRL(valor) {
  const n = Number(valor || 0);
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
}

function mostrarErro(mensagem, erro) {
  console.error(mensagem, erro);
  alert(mensagem);
}

// =======================
// ELEMENTOS DO DOM
// =======================

const tabDashboard = document.getElementById("tabDashboard");
const tabFaturas = document.getElementById("tabFaturas");
const dashboardSection = document.getElementById("dashboardSection");
const faturasSection = document.getElementById("faturasSection");

const btnHome = document.getElementById("btnHome");
const botoesTransportadora = document.querySelectorAll(".transportadora-btn");
const inputFiltroVencimento = document.getElementById("filtroVencimento");
const btnLimparFiltros = document.getElementById("btnLimparFiltros");

const cardTotal = document.getElementById("cardTotal");
const cardPendentes = document.getElementById("cardPendentes");
const cardAtrasadas = document.getElementById("cardAtrasadas");
const cardEmDia = document.getElementById("cardEmDia");

const inputBuscaNumero = document.getElementById("buscaNumero");
const btnAtualizarFaturas = document.getElementById("btnAtualizarFaturas");
const tbodyFaturas = document.getElementById("tbodyFaturas");

const formFatura = document.getElementById("formFatura");
const inputTransportadora = document.getElementById("inputTransportadora");
const inputNumeroFatura = document.getElementById("inputNumeroFatura");
const inputValor = document.getElementById("inputValor");
const inputVencimento = document.getElementById("inputVencimento");
const inputStatus = document.getElementById("inputStatus");
const inputObservacao = document.getElementById("inputObservacao");
const inputAnexos = document.getElementById("inputAnexos");

// Modal de anexos
const modalAnexos = document.getElementById("modalAnexos");
const modalFechar = document.getElementById("modalFechar");
const modalFaturaIdSpan = document.getElementById("modalFaturaId");
const listaAnexosUl = document.getElementById("listaAnexos");

// =======================
// TABS
// =======================

function ativarTab(tab) {
  if (tab === "dashboard") {
    tabDashboard.classList.add("active");
    tabFaturas.classList.remove("active");
    dashboardSection.classList.add("visible");
    faturasSection.classList.remove("visible");
  } else {
    tabDashboard.classList.remove("active");
    tabFaturas.classList.add("active");
    dashboardSection.classList.remove("visible");
    faturasSection.classList.add("visible");
  }
}

tabDashboard.addEventListener("click", () => ativarTab("dashboard"));
tabFaturas.addEventListener("click", () => ativarTab("faturas"));

// =======================
// FILTROS LATERAIS
// =======================

btnHome.addEventListener("click", () => {
  estado.transportadora = "";
  estado.vencimentoAte = "";
  estado.numeroFaturaBusca = "";
  estado.faturaEmEdicaoId = null;

  botoesTransportadora.forEach((b) => b.classList.remove("active"));
  // "Todas"
  botoesTransportadora[0]?.classList.add("active");

  inputFiltroVencimento.value = "";
  inputBuscaNumero.value = "";

  carregarDashboard();
  carregarFaturas();
});

botoesTransportadora.forEach((botao) => {
  botao.addEventListener("click", () => {
    botoesTransportadora.forEach((b) => b.classList.remove("active"));
    botao.classList.add("active");

    estado.transportadora = botao.dataset.transportadora || "";

    carregarDashboard();
    carregarFaturas();
  });
});

inputFiltroVencimento.addEventListener("change", () => {
  estado.vencimentoAte = inputFiltroVencimento.value || "";
  carregarFaturas();
});

btnLimparFiltros.addEventListener("click", () => {
  estado.vencimentoAte = "";
  inputFiltroVencimento.value = "";
  carregarFaturas();
});

// =======================
// DASHBOARD
// =======================

async function carregarDashboard() {
  try {
    const params = new URLSearchParams();
    if (estado.transportadora) {
      params.append("transportadora", estado.transportadora);
    }

    const resp = await fetch(`/dashboard/resumo?${params.toString()}`);
    if (!resp.ok) {
      throw new Error(`Status ${resp.status}`);
    }

    const data = await resp.json();

    cardTotal.textContent = formatarBRL(data.total);
    cardPendentes.textContent = formatarBRL(data.pendentes);
    cardAtrasadas.textContent = formatarBRL(data.atrasadas);
    cardEmDia.textContent = formatarBRL(data.em_dia);
  } catch (err) {
    mostrarErro("Erro ao carregar resumo do dashboard", err);
  }
}

// =======================
// LISTAGEM DE FATURAS
// =======================

async function carregarFaturas() {
  try {
    const params = new URLSearchParams();

    if (estado.transportadora) {
      params.append("transportadora", estado.transportadora);
    }
    if (estado.vencimentoAte) {
      params.append("ate_vencimento", estado.vencimentoAte);
    }
    if (estado.numeroFaturaBusca) {
      params.append("numero_fatura", estado.numeroFaturaBusca);
    }

    const resp = await fetch(`/faturas?${params.toString()}`);
    if (!resp.ok) {
      throw new Error(`Status ${resp.status}`);
    }

    const faturas = await resp.json();
    renderizarTabelaFaturas(faturas);
  } catch (err) {
    mostrarErro("Erro ao carregar faturas", err);
  }
}

function renderizarTabelaFaturas(faturas) {
  tbodyFaturas.innerHTML = "";

  if (!faturas || faturas.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="9" style="text-align:center; opacity:0.7;">Nenhuma fatura encontrada.</td>`;
    tbodyFaturas.appendChild(tr);
    return;
  }

  faturas.forEach((f) => {
    const tr = document.createElement("tr");

    const dataVenc =
      f.data_vencimento != null
        ? new Date(f.data_vencimento).toLocaleDateString("pt-BR")
        : "";

    tr.innerHTML = `
      <td>${f.id}</td>
      <td>${f.transportadora}</td>
      <td>${f.responsavel ?? ""}</td>
      <td>${f.numero_fatura}</td>
      <td>${formatarBRL(f.valor)}</td>
      <td>${dataVenc}</td>
      <td>${(f.status || "").charAt(0).toUpperCase() + (f.status || "").slice(1)}</td>
      <td>${f.observacao ?? ""}</td>
      <td class="acoes-cell">
        <button class="acoes-btn">⋮</button>
        <div class="acoes-menu hidden">
          <button data-acao="editar">Editar</button>
          <button data-acao="excluir">Excluir</button>
          <button data-acao="anexos">Anexos</button>
        </div>
      </td>
    `;

    // Eventos dos 3 pontinhos
    const btnAcoes = tr.querySelector(".acoes-btn");
    const menu = tr.querySelector(".acoes-menu");

    btnAcoes.addEventListener("click", (e) => {
      e.stopPropagation();
      document
        .querySelectorAll(".acoes-menu")
        .forEach((m) => m.classList.add("hidden"));
      menu.classList.toggle("hidden");
    });

    // Fechar ao clicar fora
    document.addEventListener("click", () => {
      menu.classList.add("hidden");
    });

    menu.addEventListener("click", async (e) => {
      e.stopPropagation();
      const acao = e.target.dataset.acao;
      if (!acao) return;

      if (acao === "excluir") {
        if (confirm(`Excluir fatura #${f.id}?`)) {
          await excluirFatura(f.id);
        }
      } else if (acao === "editar") {
        entrarModoEdicao(f);
      } else if (acao === "anexos") {
        abrirModalAnexos(f.id);
      }

      menu.classList.add("hidden");
    });

    tbodyFaturas.appendChild(tr);
  });
}

async function excluirFatura(id) {
  try {
    const resp = await fetch(`/faturas/${id}`, { method: "DELETE" });
    if (!resp.ok) {
      throw new Error(`Status ${resp.status}`);
    }
    await carregarDashboard();
    await carregarFaturas();
  } catch (err) {
    mostrarErro("Erro ao excluir fatura", err);
  }
}

function entrarModoEdicao(f) {
  estado.faturaEmEdicaoId = f.id;
  inputTransportadora.value = f.transportadora;
  inputNumeroFatura.value = f.numero_fatura;
  inputValor.value = f.valor;
  inputVencimento.value = f.data_vencimento
    ? f.data_vencimento.slice(0, 10)
    : "";
  inputStatus.value = f.status || "pendente";
  inputObservacao.value = f.observacao ?? "";
  // anexos não dá pra repopular (campo file)
  ativarTab("faturas");
}

// =======================
// BUSCA Nº DE FATURA
// =======================

inputBuscaNumero.addEventListener("input", () => {
  estado.numeroFaturaBusca = inputBuscaNumero.value.trim();
});

btnAtualizarFaturas.addEventListener("click", () => {
  carregarFaturas();
});

// =======================
// FORM DE CADASTRO / EDIÇÃO
// =======================

formFatura.addEventListener("submit", async (e) => {
  e.preventDefault();

  const payload = {
    transportadora: inputTransportadora.value.trim(),
    numero_fatura: inputNumeroFatura.value.trim(),
    valor: Number(inputValor.value),
    data_vencimento: inputVencimento.value,
    status: inputStatus.value,
    observacao: inputObservacao.value.trim() || null,
  };

  if (!payload.transportadora || !payload.numero_fatura || !payload.data_vencimento) {
    alert("Preencha transportadora, nº da fatura e data de vencimento.");
    return;
  }

  try {
    let resp;
    if (estado.faturaEmEdicaoId) {
      // UPDATE
      resp = await fetch(`/faturas/${estado.faturaEmEdicaoId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      // CREATE
      resp = await fetch("/faturas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }

    if (!resp.ok) {
      throw new Error(`Status ${resp.status}`);
    }

    const faturaCriadaOuEditada = await resp.json();

    // Upload de anexos, se houver
    if (inputAnexos.files && inputAnexos.files.length > 0) {
      const formData = new FormData();
      for (const file of inputAnexos.files) {
        formData.append("files", file);
      }

      const rAnexo = await fetch(
        `/faturas/${faturaCriadaOuEditada.id}/anexos`,
        {
          method: "POST",
          body: formData,
        }
      );

      if (!rAnexo.ok) {
        console.error("Falha ao enviar anexos");
      }
    }

    // Limpa formulário
    formFatura.reset();
    estado.faturaEmEdicaoId = null;

    await carregarDashboard();
    await carregarFaturas();
  } catch (err) {
    mostrarErro("Erro ao salvar fatura", err);
  }
});

// =======================
// MODAL DE ANEXOS
// =======================

async function abrirModalAnexos(faturaId) {
  try {
    modalFaturaIdSpan.textContent = `#${faturaId}`;
    listaAnexosUl.innerHTML = "<li>Carregando...</li>";
    modalAnexos.classList.add("aberto");

    const resp = await fetch(`/faturas/${faturaId}/anexos`);
    if (!resp.ok) {
      throw new Error(`Status ${resp.status}`);
    }

    const anexos = await resp.json();
    listaAnexosUl.innerHTML = "";

    if (!anexos || anexos.length === 0) {
      listaAnexosUl.innerHTML =
        "<li style='opacity:0.7;'>Nenhum anexo para esta fatura.</li>";
      return;
    }

    anexos.forEach((a) => {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.href = `/anexos/${a.id}`;
      link.textContent = a.original_name;
      link.target = "_blank";
      li.appendChild(link);
      listaAnexosUl.appendChild(li);
    });
  } catch (err) {
    mostrarErro("Erro ao carregar anexos", err);
  }
}

modalFechar.addEventListener("click", () => {
  modalAnexos.classList.remove("aberto");
});

modalAnexos.addEventListener("click", (e) => {
  if (e.target === modalAnexos) {
    modalAnexos.classList.remove("aberto");
  }
});

// =======================
// INICIALIZAÇÃO
// =======================

(async function init() {
  // marca "Todas" como ativa
  botoesTransportadora.forEach((b) => b.classList.remove("active"));
  botoesTransportadora[0]?.classList.add("active");

  await carregarDashboard();
  await carregarFaturas();
})();
