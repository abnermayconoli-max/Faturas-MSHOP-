// Base da API (mesmo host)
const API_BASE = "";

let filtroTransportadoraAtual = null;

// Utilitário simples
function formatarMoeda(valor) {
  valor = Number(valor || 0);
  return valor.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function formatarDataISOParaBR(dataISO) {
  if (!dataISO) return "";
  const d = new Date(dataISO);
  const dia = String(d.getUTCDate()).padStart(2, "0");
  const mes = String(d.getUTCMonth() + 1).padStart(2, "0");
  const ano = d.getUTCFullYear();
  return `${dia}/${mes}/${ano}`;
}

// ======================
// DASHBOARD
// ======================

async function carregarResumo() {
  try {
    const resp = await fetch(`${API_BASE}/dashboard/resumo`);
    if (!resp.ok) return;

    const data = await resp.json();
    document.getElementById("kpi-total").textContent = formatarMoeda(data.total);
    document.getElementById("kpi-pendentes").textContent = formatarMoeda(data.pendentes);
    document.getElementById("kpi-atrasadas").textContent = formatarMoeda(data.atrasadas);
    document.getElementById("kpi-em-dia").textContent = formatarMoeda(data.em_dia);
  } catch (e) {
    console.error("Erro ao carregar resumo:", e);
  }
}

// ======================
// FILTROS
// ======================

function filtrarTransportadora(nomeBase) {
  filtroTransportadoraAtual = nomeBase;
  const badge = document.getElementById("filtro-atual");
  badge.textContent = `Filtro: ${nomeBase}`;
  badge.style.display = "inline-block";
  atualizarListaFaturas();
}

function resetFiltros() {
  filtroTransportadoraAtual = null;
  document.getElementById("filtro-vencimento").value = "";
  const badge = document.getElementById("filtro-atual");
  badge.textContent = "";
  badge.style.display = "none";
  atualizarListaFaturas();
}

// ======================
// CRUD FATURAS
// ======================

async function atualizarListaFaturas() {
  try {
    const params = new URLSearchParams();
    const dataVenc = document.getElementById("filtro-vencimento").value;

    if (filtroTransportadoraAtual) {
      // o back usa ilike, então pode ser só a base
      params.append("transportadora", filtroTransportadoraAtual);
    }

    if (dataVenc) {
      params.append("ate_vencimento", dataVenc);
    }

    const url = `${API_BASE}/faturas` + (params.toString() ? `?${params.toString()}` : "");
    const resp = await fetch(url);
    const faturas = await resp.json();

    const container = document.getElementById("lista-faturas");
    container.innerHTML = "";

    if (!faturas.length) {
      container.innerHTML = `<p class="empty">Nenhuma fatura encontrada.</p>`;
      return;
    }

    faturas.forEach((f) => {
      const card = document.createElement("div");
      card.className = "fatura-card";

      card.innerHTML = `
        <div class="fatura-main">
          <div class="fatura-linha">
            <span class="tag">${f.transportadora}</span>
            <span class="tag-resp">${f.responsavel || ""}</span>
          </div>
          <div class="fatura-linha">
            <strong>NF: ${f.numero_fatura}</strong>
            <span>${formatarMoeda(f.valor)}</span>
          </div>
          <div class="fatura-linha">
            <span>Venc.: ${formatarDataISOParaBR(f.data_vencimento)}</span>
            <span class="status ${f.status === "pendente" ? "status-pendente" : "status-pago"}">
              ${f.status}
            </span>
          </div>
          <div class="fatura-linha obs">
            <span>${f.observacao ? "Obs.: " + f.observacao : ""}</span>
          </div>
        </div>
        <div class="fatura-menu-area">
          <button class="menu-btn" onclick="toggleMenu(${f.id})">⋮</button>
          <div class="menu-opcoes" id="menu-${f.id}">
            <button onclick="editarFatura(${f.id})">Editar fatura</button>
            <button onclick="excluirFatura(${f.id})">Excluir fatura</button>
            <button onclick="mostrarAnexos(${f.id})">Anexos</button>
          </div>
        </div>
      `;

      container.appendChild(card);
    });
  } catch (e) {
    console.error("Erro ao listar faturas:", e);
  }
}

function toggleMenu(id) {
  // fecha todos
  document.querySelectorAll(".menu-opcoes").forEach((m) => (m.style.display = "none"));
  const el = document.getElementById(`menu-${id}`);
  if (el) {
    el.style.display = "block";
  }
}

window.addEventListener("click", (e) => {
  if (!e.target.classList.contains("menu-btn")) {
    document.querySelectorAll(".menu-opcoes").forEach((m) => (m.style.display = "none"));
  }
});

async function criarFatura(event) {
  event.preventDefault();

  const form = document.getElementById("form-fatura");
  const formData = new FormData(form);

  const payload = {
    transportadora: formData.get("transportadora"),
    numero_fatura: formData.get("numero_fatura"),
    valor: parseFloat(formData.get("valor")),
    data_vencimento: formData.get("data_vencimento"),
    status: formData.get("status") || "pendente",
    observacao: formData.get("observacao") || null,
  };

  try {
    // 1) cria fatura
    const resp = await fetch(`${API_BASE}/faturas`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      alert("Erro ao salvar fatura.");
      return;
    }

    const novaFatura = await resp.json();

    // 2) se tiver anexos, envia
    const inputAnexos = document.getElementById("anexos");
    if (inputAnexos.files && inputAnexos.files.length > 0) {
      const fd = new FormData();
      for (const file of inputAnexos.files) {
        fd.append("files", file);
      }

      const respAnexo = await fetch(`${API_BASE}/faturas/${novaFatura.id}/anexos`, {
        method: "POST",
        body: fd,
      });

      if (!respAnexo.ok) {
        console.error("Erro ao enviar anexos.");
      }
    }

    form.reset();
    atualizarListaFaturas();
    carregarResumo();
  } catch (e) {
    console.error("Erro ao criar fatura:", e);
  }
}

async function excluirFatura(id) {
  if (!confirm("Tem certeza que deseja excluir essa fatura e todos os anexos?")) return;

  try {
    const resp = await fetch(`${API_BASE}/faturas/${id}`, {
      method: "DELETE",
    });
    if (!resp.ok) {
      alert("Erro ao excluir fatura.");
      return;
    }
    atualizarListaFaturas();
    carregarResumo();
  } catch (e) {
    console.error("Erro ao excluir fatura:", e);
  }
}

async function editarFatura(id) {
  try {
    const resp = await fetch(`${API_BASE}/faturas/${id}`);
    if (!resp.ok) {
      alert("Fatura não encontrada.");
      return;
    }
    const f = await resp.json();

    const novoStatus = prompt(
      'Status da fatura ("pendente" ou "pago"):',
      f.status || "pendente"
    );
    if (novoStatus === null) return; // cancelou

    const novaObs = prompt("Observação:", f.observacao || "");
    if (novaObs === null) return;

    const payload = {
      status: novoStatus,
      observacao: novaObs,
    };

    const respUpdate = await fetch(`${API_BASE}/faturas/${id}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!respUpdate.ok) {
      alert("Erro ao atualizar fatura.");
      return;
    }

    atualizarListaFaturas();
    carregarResumo();
  } catch (e) {
    console.error("Erro ao editar fatura:", e);
  }
}

async function mostrarAnexos(id) {
  try {
    const resp = await fetch(`${API_BASE}/faturas/${id}/anexos`);
    if (!resp.ok) {
      alert("Erro ao listar anexos.");
      return;
    }

    const anexos = await resp.json();
    if (!anexos.length) {
      alert("Sem anexos para essa fatura.");
      return;
    }

    // monta uma lista simples
    let msg = "Anexos da fatura:\n\n";
    anexos.forEach((a) => {
      const url = `${API_BASE}/anexos/${a.id}`;
      msg += `- ${a.original_name}\n  ${url}\n\n`;
    });

    alert(msg);
  } catch (e) {
    console.error("Erro ao mostrar anexos:", e);
  }
}

// ======================
// INICIALIZAÇÃO
// ======================

window.atualizarListaFaturas = atualizarListaFaturas;
window.filtrarTransportadora = filtrarTransportadora;
window.resetFiltros = resetFiltros;
window.criarFatura = criarFatura;
window.excluirFatura = excluirFatura;
window.editarFatura = editarFatura;
window.mostrarAnexos = mostrarAnexos;

document.addEventListener("DOMContentLoaded", () => {
  carregarResumo();
  atualizarListaFaturas();
});
