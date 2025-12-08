const API_BASE = ""; // mesma origem

let filtroTransportadora = "";
let filtroVencimento = "";
let faturaEmEdicao = null;

// Helpers
function formatarValor(valor) {
  if (valor == null) return "R$ 0,00";
  const n = Number(valor);
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
}

function formatarDataISO(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("pt-BR");
}

function exibirErro(msg) {
  alert(msg || "Ocorreu um erro");
}

// ==========================
// TABS
// ==========================

function configurarTabs() {
  const buttons = document.querySelectorAll(".tab-button");
  const tabs = document.querySelectorAll(".tab-content");

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;

      buttons.forEach((b) => b.classList.remove("active"));
      tabs.forEach((t) => t.classList.remove("active"));

      btn.classList.add("active");
      document.getElementById(target).classList.add("active");

      if (target === "tab-dashboard") {
        carregarDashboard();
      }
    });
  });
}

// ==========================
// SIDEBAR
// ==========================

function configurarSidebar() {
  const itens = document.querySelectorAll(".sidebar-item");
  const btnFiltrar = document.getElementById("btn-filtrar-sidebar");
  const inputVencimento = document.getElementById("filtro-vencimento");

  itens.forEach((item) => {
    item.addEventListener("click", () => {
      itens.forEach((i) => i.classList.remove("active"));
      item.classList.add("active");

      filtroTransportadora = item.dataset.transportadora || "";
      carregarFaturas();
    });
  });

  btnFiltrar.addEventListener("click", () => {
    filtroVencimento = inputVencimento.value || "";
    carregarFaturas();
  });
}

// ==========================
// FORM CADASTRO / EDIÇÃO
// ==========================

function limparFormulario() {
  document.getElementById("transportadora").value = "";
  document.getElementById("numero-fatura").value = "";
  document.getElementById("valor").value = "";
  document.getElementById("data-vencimento").value = "";
  document.getElementById("status").value = "pendente";
  document.getElementById("observacao").value = "";
  document.getElementById("anexos").value = "";
  faturaEmEdicao = null;
  document.getElementById("form-titulo").innerText = "Cadastrar fatura";
  document.getElementById("form-subtitulo").innerText =
    "Preencha os dados para criar uma nova fatura.";
  document.getElementById("btn-salvar-fatura").innerText = "Cadastrar";
}

function preencherFormularioParaEdicao(fatura) {
  faturaEmEdicao = fatura;

  document.getElementById("transportadora").value = fatura.transportadora || "";
  document.getElementById("numero-fatura").value = fatura.numero_fatura || "";
  document.getElementById("valor").value = fatura.valor;
  document.getElementById("data-vencimento").value = fatura.data_vencimento;
  document.getElementById("status").value = fatura.status || "pendente";
  document.getElementById("observacao").value = fatura.observacao || "";

  document.getElementById("form-titulo").innerText = `Editar fatura #${fatura.id}`;
  document.getElementById("form-subtitulo").innerText =
    "Altere os campos desejados e clique em salvar.";
  document.getElementById("btn-salvar-fatura").innerText = "Salvar alterações";
}

function configurarFormulario() {
  const form = document.getElementById("form-fatura");
  const btnCancelar = document.getElementById("btn-cancelar-edicao");
  const btnLimparFiltros = document.getElementById("btn-limpar-filtros");
  const filtroNumero = document.getElementById("filtro-numero");
  const filtroStatus = document.getElementById("filtro-status");
  const btnExportar = document.getElementById("btn-exportar");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    try {
      const payload = {
        transportadora: document.getElementById("transportadora").value,
        numero_fatura: document.getElementById("numero-fatura").value,
        valor: parseFloat(document.getElementById("valor").value || "0"),
        data_vencimento: document.getElementById("data-vencimento").value,
        status: document.getElementById("status").value,
        observacao: document.getElementById("observacao").value || null,
      };

      let resp;
      if (faturaEmEdicao) {
        resp = await fetch(`${API_BASE}/faturas/${faturaEmEdicao.id}`, {
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
        console.error(await resp.text());
        return exibirErro("Erro ao salvar fatura");
      }

      const fatura = await resp.json();

      // Upload de anexos se houver
      const arquivos = document.getElementById("anexos").files;
      if (arquivos && arquivos.length > 0) {
        const formData = new FormData();
        for (const file of arquivos) {
          formData.append("files", file);
        }

        const respAnexo = await fetch(
          `${API_BASE}/faturas/${fatura.id}/anexos`,
          {
            method: "POST",
            body: formData,
          }
        );

        if (!respAnexo.ok) {
          console.error(await respAnexo.text());
          exibirErro("Fatura salva, mas houve erro ao enviar anexos");
        }
      }

      limparFormulario();
      await carregarFaturas();
    } catch (err) {
      console.error(err);
      exibirErro("Erro inesperado ao salvar fatura");
    }
  });

  btnCancelar.addEventListener("click", () => {
    limparFormulario();
  });

  btnLimparFiltros.addEventListener("click", () => {
    document.getElementById("filtro-numero").value = "";
    document.getElementById("filtro-status").value = "";
    filtroVencimento = "";
    document.getElementById("filtro-vencimento").value = "";
    carregarFaturas();
  });

  // pesquisa por número de fatura em tempo real (leve)
  let timeoutPesquisa = null;
  filtroNumero.addEventListener("input", () => {
    clearTimeout(timeoutPesquisa);
    timeoutPesquisa = setTimeout(() => {
      carregarFaturas();
    }, 400);
  });

  filtroStatus.addEventListener("change", () => {
    carregarFaturas();
  });

  btnExportar.addEventListener("click", () => {
    const params = new URLSearchParams();
    if (filtroTransportadora) {
      params.append("transportadora", filtroTransportadora);
    }

    const url =
      `${API_BASE}/faturas/exportar` +
      (params.toString() ? `?${params.toString()}` : "");
    window.open(url, "_blank");
  });
}

// ==========================
// LISTAGEM
// ==========================

async function carregarFaturas() {
  const tbody = document.getElementById("tbody-faturas");
  tbody.innerHTML = `<tr><td colspan="9">Carregando...</td></tr>`;

  const params = new URLSearchParams();

  if (filtroTransportadora) {
    params.append("transportadora", filtroTransportadora);
  }

  if (filtroVencimento) {
    params.append("ate_vencimento", filtroVencimento);
  }

  const numero = document.getElementById("filtro-numero").value.trim();
  if (numero) {
    params.append("numero_fatura", numero);
  }

  const status = document.getElementById("filtro-status").value;
  // status é aplicado apenas no front para não mexer no back agora

  const url =
    `${API_BASE}/faturas` + (params.toString() ? `?${params.toString()}` : "");

  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      console.error(await resp.text());
      return exibirErro("Erro ao carregar faturas");
    }

    let faturas = await resp.json();

    if (status) {
      faturas = faturas.filter((f) =>
        (f.status || "").toLowerCase().includes(status.toLowerCase())
      );
    }

    renderizarFaturas(faturas);
    atualizarLegendaFiltro(faturas.length);
  } catch (err) {
    console.error(err);
    exibirErro("Erro ao carregar faturas");
  }
}

function atualizarLegendaFiltro(qtd) {
  const legenda = document.getElementById("filtro-legenda");
  const partes = [];

  if (filtroTransportadora) {
    partes.push(`Transportadora: ${filtroTransportadora}`);
  }
  if (filtroVencimento) {
    partes.push(
      `Até vencimento: ${new Date(filtroVencimento).toLocaleDateString("pt-BR")}`
    );
  }
  const numero = document.getElementById("filtro-numero").value.trim();
  if (numero) {
    partes.push(`Nº fatura contendo "${numero}"`);
  }

  const textoFiltro = partes.length
    ? partes.join(" • ")
    : "Sem filtros aplicados";

  legenda.textContent = `${qtd} fatura(s) • ${textoFiltro}`;
}

function badgeStatus(status) {
  const s = (status || "").toLowerCase();
  if (s === "pago") {
    return `<span class="badge badge-pago">Pago</span>`;
  }
  if (s === "aguardando") {
    return `<span class="badge badge-aguardando">Aguardando</span>`;
  }
  return `<span class="badge badge-pendente">Pendente</span>`;
}

function renderizarFaturas(faturas) {
  const tbody = document.getElementById("tbody-faturas");
  tbody.innerHTML = "";

  if (!faturas.length) {
    tbody.innerHTML = `<tr><td colspan="9">Nenhuma fatura encontrada.</td></tr>`;
    return;
  }

  for (const f of faturas) {
    const tr = document.createElement("tr");

    tr.innerHTML = `
      <td>${f.id}</td>
      <td>${f.transportadora || ""}</td>
      <td>${f.responsavel || ""}</td>
      <td>${f.numero_fatura || ""}</td>
      <td>${formatarValor(f.valor)}</td>
      <td>${formatarDataISO(f.data_vencimento)}</td>
      <td>${badgeStatus(f.status)}</td>
      <td>${f.observacao || ""}</td>
      <td class="row-actions">
        <button class="action-button" type="button">⋮</button>
        <div class="actions-menu">
          <button type="button" data-acao="editar">Editar</button>
          <button type="button" data-acao="anexos">Anexos</button>
          <button type="button" data-acao="excluir" class="danger">Excluir</button>
        </div>
      </td>
    `;

    const btn = tr.querySelector(".action-button");
    const menu = tr.querySelector(".actions-menu");

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      document
        .querySelectorAll(".actions-menu.open")
        .forEach((m) => m.classList.remove("open"));
      menu.classList.toggle("open");
    });

    menu.addEventListener("click", (e) => {
      e.stopPropagation();
      const acao = e.target.dataset.acao;
      if (!acao) return;

      if (acao === "editar") {
        preencherFormularioParaEdicao(f);
        menu.classList.remove("open");
      } else if (acao === "excluir") {
        excluirFatura(f.id);
        menu.classList.remove("open");
      } else if (acao === "anexos") {
        gerenciarAnexos(f.id);
        menu.classList.remove("open");
      }
    });

    tbody.appendChild(tr);
  }

  // Fecha menus ao clicar fora
  document.addEventListener(
    "click",
    () => {
      document
        .querySelectorAll(".actions-menu.open")
        .forEach((m) => m.classList.remove("open"));
    },
    { once: true }
  );
}

async function excluirFatura(id) {
  if (!confirm(`Deseja realmente excluir a fatura #${id}?`)) return;

  try {
    const resp = await fetch(`${API_BASE}/faturas/${id}`, {
      method: "DELETE",
    });

    if (!resp.ok) {
      console.error(await resp.text());
      return exibirErro("Erro ao excluir fatura");
    }

    if (faturaEmEdicao && faturaEmEdicao.id === id) {
      limparFormulario();
    }

    await carregarFaturas();
  } catch (err) {
    console.error(err);
    exibirErro("Erro ao excluir fatura");
  }
}

async function gerenciarAnexos(id) {
  try {
    const resp = await fetch(`${API_BASE}/faturas/${id}/anexos`);
    if (!resp.ok) {
      console.error(await resp.text());
      return exibirErro("Erro ao listar anexos");
    }

    const anexos = await resp.json();

    if (!anexos.length) {
      if (!confirm("Nenhum anexo cadastrado. Deseja enviar arquivos agora?")) {
        return;
      }
    } else {
      const nomes = anexos
        .map((a) => `• ${a.original_name} (ID ${a.id})`)
        .join("\n");
      const abrir = confirm(
        `Anexos da fatura #${id}:\n\n${nomes}\n\nDeseja abrir todos em novas abas?`
      );
      if (abrir) {
        anexos.forEach((a) => {
          window.open(`${API_BASE}/anexos/${a.id}`, "_blank");
        });
      }
    }

    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.style.display = "none";

    input.addEventListener("change", async () => {
      const arquivos = input.files;
      if (!arquivos || arquivos.length === 0) return;

      const formData = new FormData();
      for (const file of arquivos) {
        formData.append("files", file);
      }

      try {
        const respUp = await fetch(`${API_BASE}/faturas/${id}/anexos`, {
          method: "POST",
          body: formData,
        });

        if (!respUp.ok) {
          console.error(await respUp.text());
          return exibirErro("Erro ao enviar anexos");
        }
        alert("Anexos enviados com sucesso!");
      } catch (err) {
        console.error(err);
        exibirErro("Erro ao enviar anexos");
      } finally {
        input.remove();
      }
    });

    document.body.appendChild(input);
    input.click();
  } catch (err) {
    console.error(err);
    exibirErro("Erro ao gerenciar anexos");
  }
}

// ==========================
// DASHBOARD
// ==========================

async function carregarDashboard() {
  try {
    const resp = await fetch(`${API_BASE}/dashboard/resumo`);
    if (!resp.ok) {
      console.error(await resp.text());
      return;
    }
    const dados = await resp.json();

    document.getElementById("kpi-total").innerText = formatarValor(dados.total);
    document.getElementById("kpi-pendentes").innerText = formatarValor(
      dados.pendentes
    );
    document.getElementById("kpi-atrasadas").innerText = formatarValor(
      dados.atrasadas
    );
    document.getElementById("kpi-em-dia").innerText = formatarValor(
      dados.em_dia
    );
  } catch (err) {
    console.error(err);
  }
}

// ==========================
// INIT
// ==========================

document.addEventListener("DOMContentLoaded", () => {
  configurarTabs();
  configurarSidebar();
  configurarFormulario();
  limparFormulario();
  carregarFaturas();
  carregarDashboard();
});
