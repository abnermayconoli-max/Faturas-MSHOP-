// ============================
// CONFIG / ESTADO
// ============================

const API_BASE = "";

let filtroTransportadora = "";
let filtroVencimento = "";
let filtroNumeroFatura = "";

// Helpers DOM
const $ = (id) => document.getElementById(id);
const on = (id, evt, handler) => {
  const el = $(id);
  if (el) el.addEventListener(evt, handler);
};

// ============================
// HELPERS
// ============================

function formatCurrency(valor) {
  if (valor === null || valor === undefined || valor === "") return "R$ 0,00";
  const num = Number(valor);
  if (Number.isNaN(num)) return "R$ 0,00";
  return num.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function formatDate(isoDate) {
  if (!isoDate) return "";
  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString("pt-BR");
}

// ============================
// DASHBOARD
// ============================

async function carregarDashboard() {
  try {
    const resp = await fetch(`${API_BASE}/dashboard/resumo`);
    if (!resp.ok) throw new Error("Erro ao buscar resumo");

    const data = await resp.json();
    const total = data.total ?? 0;
    const pendentes = data.pendentes ?? 0;
    const atrasadas = data.atrasadas ?? 0;
    const emDia = data.em_dia ?? 0;

    const cardTotal = $("cardTotal");
    const cardPendentes = $("cardPendentes");
    const cardAtrasadas = $("cardAtrasadas");
    const cardEmDia = $("cardEmDia");

    if (cardTotal) cardTotal.textContent = formatCurrency(total);
    if (cardPendentes) cardPendentes.textContent = formatCurrency(pendentes);
    if (cardAtrasadas) cardAtrasadas.textContent = formatCurrency(atrasadas);
    if (cardEmDia) cardEmDia.textContent = formatCurrency(emDia);
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar dashboard");
  }
}

// ============================
// FATURAS
// ============================

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
    const tbody = $("tbodyFaturas");
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
    const resp = await fetch(`${API_BASE}/faturas/${id}`, { method: "DELETE" });
    if (!resp.ok) throw new Error("Erro ao excluir");
    await carregarFaturas();
    await carregarDashboard();
  } catch (err) {
    console.error(err);
    alert("Erro ao excluir fatura");
  }
}

function preencherFormularioEdicao(f) {
  const form = $("formFatura");
  if (!form) return;

  $("inputTransportadora") && ( $("inputTransportadora").value = f.transportadora );
  $("inputNumeroFatura") && ( $("inputNumeroFatura").value = f.numero_fatura );
  $("inputValor") && ( $("inputValor").value = f.valor );
  $("inputVencimento") && ( $("inputVencimento").value = f.data_vencimento );
  $("inputStatus") && ( $("inputStatus").value = f.status );
  $("inputObservacao") && ( $("inputObservacao").value = f.observacao ?? "" );

  form.dataset.editId = f.id;
}

// ============================
// ANEXOS (MODAL)
// ============================

async function abrirModalAnexos(faturaId) {
  const modal = $("modalAnexos");
  const lista = $("listaAnexos");
  const spanId = $("modalFaturaId");
  if (!modal || !lista || !spanId) return;

  spanId.textContent = faturaId;
  lista.innerHTML = "Carregando...";

  try:
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

  modal.classList.add("open");
}

// ============================
// FORMULÁRIO
// ============================

async function salvarFatura(e) {
  e.preventDefault();
  const form = $("formFatura");
  if (!form) return;

  const editId = form.dataset.editId || null;

  const payload = {
    transportadora: $("inputTransportadora")?.value || "",
    numero_fatura: $("inputNumeroFatura")?.value || "",
    valor: parseFloat($("inputValor")?.value || "0"),
    data_vencimento: $("inputVencimento")?.value || "",
    status: $("inputStatus")?.value || "pendente",
    observacao: $("inputObservacao")?.value || null,
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

    // anexos
    const inputAnexos = $("inputAnexos");
    if (inputAnexos && inputAnexos.files.length > 0) {
      const fd = new FormData();
      for (const file of inputAnexos.files) {
        fd.append("files", file);
      }
      const respAnexo = await fetch(`${API_BASE}/faturas/${fatura.id}/anexos`, {
        method: "POST",
        body: fd,
      });
      if (!respAnexo.ok) console.error("Erro ao enviar anexos");
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

// ============================
// ABAS / NAVEGAÇÃO
// ============================

function ativarAba(aba) {
  const dash = $("dashboardSection");
  const fat = $("faturasSection");
  const tabDash = $("tabDashboard");
  const tabFat = $("tabFaturas");

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

// ============================
// INICIALIZAÇÃO
// ============================

document.addEventListener("DOMContentLoaded", () => {
  try {
    // abas
    on("tabDashboard", "click", () => ativarAba("dashboard"));
    on("tabFaturas", "click", () => ativarAba("faturas"));

    // botões principais
    on("btnHome", "click", () => {
      filtroTransportadora = "";
      filtroVencimento = "";
      filtroNumeroFatura = "";
      if ($("filtroVencimento")) $("filtroVencimento").value = "";
      if ($("buscaNumero")) $("buscaNumero").value = "";
      ativarAba("dashboard");
      carregarDashboard();
      carregarFaturas();
    });

    // transportadoras na sidebar
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
    on("filtroVencimento", "change", (e) => {
      filtroVencimento = e.target.value;
      carregarFaturas();
    });

    on("btnLimparFiltros", "click", () => {
      filtroVencimento = "";
      filtroNumeroFatura = "";
      if ($("filtroVencimento")) $("filtroVencimento").value = "";
      if ($("buscaNumero")) $("buscaNumero").value = "";
      carregarFaturas();
    });

    // busca nº fatura
    on("buscaNumero", "input", (e) => {
      filtroNumeroFatura = e.target.value.trim();
      carregarFaturas();
    });

    // atualizar lista
    on("btnAtualizarFaturas", "click", carregarFaturas);

    // formulário
    const form = $("formFatura");
    if (form) form.addEventListener("submit", salvarFatura);

    // modal
    on("modalFechar", "click", () => {
      const modal = $("modalAnexos");
      if (modal) modal.classList.remove("open");
    });
    const modal = $("modalAnexos");
    if (modal) {
      modal.addEventListener("click", (e) => {
        if (e.target.id === "modalAnexos") {
          modal.classList.remove("open");
        }
      });
    }

    // carga inicial
    carregarDashboard();
    carregarFaturas();
  } catch (e) {
    console.error("Erro na inicialização do app:", e);
    alert("Erro ao iniciar a página (JavaScript). Veja o console para detalhes.");
  }
});
