const API_BASE = "";

// -----------------------------
// Helpers
// -----------------------------
function formatMoney(valor) {
  const n = Number(valor || 0);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function formatDateISOToBR(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("pt-BR");
}

// -----------------------------
// Carregar FATURAS
// -----------------------------
async function carregarFaturas() {
  const tbody = document.querySelector("#tabela-faturas tbody");
  tbody.innerHTML = "<tr><td colspan='9'>Carregando...</td></tr>";

  const tp = document.querySelector("#filtro-transportadora").value.trim();
  const vencFiltro = document.querySelector("#filtro-vencimento").value;

  const params = new URLSearchParams();
  if (tp) params.append("transportadora", tp);
  if (vencFiltro) params.append("ate_vencimento", vencFiltro);

  const resp = await fetch(`/faturas?${params.toString()}`);
  if (!resp.ok) {
    tbody.innerHTML = "<tr><td colspan='9'>Erro ao carregar faturas.</td></tr>";
    return;
  }

  const dados = await resp.json();
  if (!dados.length) {
    tbody.innerHTML = "<tr><td colspan='9'>Nenhuma fatura encontrada.</td></tr>";
    return;
  }

  tbody.innerHTML = "";

  dados.forEach((fat) => {
    const tr = document.createElement("tr");

    tr.innerHTML = `
      <td>${fat.id}</td>
      <td>${fat.transportadora}</td>
      <td>${fat.responsavel || ""}</td>
      <td>${fat.numero_fatura}</td>
      <td>${formatMoney(fat.valor)}</td>
      <td>${formatDateISOToBR(fat.data_vencimento)}</td>
      <td>${fat.status}</td>
      <td class="col-obs" title="${fat.observacao || ""}">
        ${(fat.observacao || "").slice(0, 25)}${(fat.observacao || "").length > 25 ? "..." : ""}
      </td>
      <td class="col-acoes">
        <div class="menu-container">
          <button class="menu-btn">⋮</button>
          <div class="menu-dropdown" hidden>
            <button class="menu-item" data-acao="editar">Editar</button>
            <button class="menu-item" data-acao="excluir">Excluir</button>
            <button class="menu-item" data-acao="anexos">Anexos</button>
          </div>
        </div>
      </td>
    `;

    // Eventos do menu
    const menuBtn = tr.querySelector(".menu-btn");
    const dropdown = tr.querySelector(".menu-dropdown");

    menuBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      document
        .querySelectorAll(".menu-dropdown")
        .forEach((m) => (m.hidden = true));
      dropdown.hidden = !dropdown.hidden;
    });

    dropdown.addEventListener("click", (ev) => {
      const acao = ev.target.dataset.acao;
      if (!acao) return;
      dropdown.hidden = true;
      if (acao === "editar") {
        preencherFormularioEdicao(fat);
      } else if (acao === "excluir") {
        excluirFatura(fat.id);
      } else if (acao === "anexos") {
        mostrarAnexosDaFatura(fat.id);
      }
    });

    tbody.appendChild(tr);
  });

  // Fecha menus clicando fora
  document.addEventListener("click", () => {
    document
      .querySelectorAll(".menu-dropdown")
      .forEach((m) => (m.hidden = true));
  }, { once: true });
}

// -----------------------------
// Excluir fatura
// -----------------------------
async function excluirFatura(id) {
  if (!confirm("Tem certeza que deseja excluir esta fatura?")) return;

  const resp = await fetch(`/faturas/${id}`, { method: "DELETE" });
  if (!resp.ok) {
    alert("Erro ao excluir fatura.");
    return;
  }
  await carregarFaturas();
  await carregarDashboard();
}

// -----------------------------
// Anexos
// -----------------------------
async function mostrarAnexosDaFatura(id) {
  const resp = await fetch(`/faturas/${id}/anexos`);
  if (!resp.ok) {
    alert("Erro ao buscar anexos.");
    return;
  }

  const anexos = await resp.json();
  if (!anexos.length) {
    alert("Esta fatura não possui anexos.");
    return;
  }

  // Cria um mini popup simples com links
  const lista = anexos
    .map(
      (a) =>
        `<li><a href="/anexos/${a.id}" target="_blank" rel="noopener noreferrer">${a.original_name}</a></li>`
    )
    .join("");

  const html = `
    <div class="anexos-popup-backdrop">
      <div class="anexos-popup">
        <h3>Anexos da fatura ${id}</h3>
        <ul>${lista}</ul>
        <button id="btn-fechar-anexos" class="btn btn-secondary">Fechar</button>
      </div>
    </div>
  `;

  const wrapper = document.createElement("div");
  wrapper.innerHTML = html;
  document.body.appendChild(wrapper);

  document
    .getElementById("btn-fechar-anexos")
    .addEventListener("click", () => wrapper.remove());
}

// -----------------------------
// Formulário - salvar / editar
// -----------------------------
function limparFormulario() {
  document.getElementById("form-cadastro").reset();
  document.getElementById("cad-id-edicao").value = "";
  document.getElementById("btn-salvar-fatura").textContent = "Salvar Fatura";
}

function preencherFormularioEdicao(fat) {
  document.getElementById("cad-id-edicao").value = fat.id;
  document.getElementById("cad-transportadora").value =
    fat.transportadora || "";
  document.getElementById("cad-numero").value = fat.numero_fatura || "";
  document.getElementById("cad-valor").value = fat.valor || "";
  document.getElementById("cad-vencimento").value = fat.data_vencimento || "";
  document.getElementById("cad-status").value = fat.status || "pendente";
  document.getElementById("cad-observacao").value = fat.observacao || "";

  document.getElementById("btn-salvar-fatura").textContent = "Atualizar Fatura";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function salvarFatura(ev) {
  ev.preventDefault();

  const idEdicao = document.getElementById("cad-id-edicao").value || null;
  const transportadora = document
    .getElementById("cad-transportadora")
    .value.trim();
  const numero = document.getElementById("cad-numero").value.trim();
  const valor = parseFloat(
    document.getElementById("cad-valor").value.replace(",", ".") || "0"
  );
  const vencimento = document.getElementById("cad-vencimento").value;
  const status = document.getElementById("cad-status").value;
  const observacao = document.getElementById("cad-observacao").value.trim();

  if (!transportadora || !numero || !vencimento) {
    alert("Preencha transportadora, número e vencimento.");
    return;
  }

  const payload = {
    transportadora,
    numero_fatura: numero,
    valor,
    data_vencimento: vencimento,
    status,
    observacao,
  };

  const metodo = idEdicao ? "PUT" : "POST";
  const url = idEdicao ? `/faturas/${idEdicao}` : "/faturas";

  const resp = await fetch(url, {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    const erro = await resp.text();
    console.error(erro);
    alert("Erro ao salvar fatura.");
    return;
  }

  const faturaSalva = await resp.json();

  // Agora envia os anexos (se tiver)
  const inputFiles = document.getElementById("cad-anexos");
  if (inputFiles.files.length) {
    const fd = new FormData();
    for (const file of inputFiles.files) {
      fd.append("files", file);
    }
    const upResp = await fetch(`/faturas/${faturaSalva.id}/anexos`, {
      method: "POST",
      body: fd,
    });
    if (!upResp.ok) {
      alert("Fatura salva, mas houve erro ao enviar anexos.");
    }
  }

  limparFormulario();
  await carregarFaturas();
  await carregarDashboard();
}

// -----------------------------
// Dashboard
// -----------------------------
async function carregarDashboard() {
  const resp = await fetch("/dashboard/resumo");
  if (!resp.ok) return;

  const d = await resp.json();
  document.getElementById("dash-total").textContent = formatMoney(d.total);
  document.getElementById("dash-pendentes").textContent = formatMoney(
    d.pendentes
  );
  document.getElementById("dash-atrasadas").textContent = formatMoney(
    d.atrasadas
  );
  document.getElementById("dash-em-dia").textContent = formatMoney(d.em_dia);
}

// -----------------------------
// Exportar CSV
// -----------------------------
function exportarFaturas(soFiltro) {
  const tp = soFiltro
    ? document.querySelector("#filtro-transportadora").value.trim()
    : "";
  const params = new URLSearchParams();
  if (tp) params.append("transportadora", tp);

  const url = `/faturas/exportar?${params.toString()}`;
  window.open(url, "_blank");
}

// -----------------------------
// Sidebar / filtros rápidos
// -----------------------------
function setupSidebar() {
  // Botão Página inicial -> rola pro topo
  document
    .querySelector('[data-action="home"]')
    .addEventListener("click", () =>
      window.scrollTo({ top: 0, behavior: "smooth" })
    );

  // Botões por transportadora
  document
    .querySelectorAll("[data-filter-transportadora]")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        const tp = btn.dataset.filterTransportadora;
        document.querySelector("#filtro-transportadora").value = tp;
        carregarFaturas();
      });
    });

  // Filtro por vencimento (lateral)
  document
    .getElementById("btn-aplicar-vencimento")
    .addEventListener("click", () => {
      carregarFaturas();
    });

  document
    .getElementById("btn-limpar-vencimento")
    .addEventListener("click", () => {
      document.getElementById("filtro-vencimento").value = "";
      carregarFaturas();
    });
}

// -----------------------------
// Inicialização
// -----------------------------
document.addEventListener("DOMContentLoaded", () => {
  // Filtros em cima da tabela
  document
    .getElementById("btn-aplicar-filtro")
    .addEventListener("click", carregarFaturas);
  document.getElementById("btn-limpar-filtro").addEventListener("click", () => {
    document.getElementById("filtro-transportadora").value = "";
    carregarFaturas();
  });

  // Exportação
  document
    .getElementById("btn-exportar-filtrado")
    .addEventListener("click", () => exportarFaturas(true));
  document
    .getElementById("btn-exportar-todas")
    .addEventListener("click", () => exportarFaturas(false));

  // Formulário
  document
    .getElementById("form-cadastro")
    .addEventListener("submit", salvarFatura);
  document
    .getElementById("btn-cancelar-edicao")
    .addEventListener("click", limparFormulario);

  setupSidebar();
  carregarFaturas();
  carregarDashboard();
});
