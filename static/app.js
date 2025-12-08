// URL base (vazio = mesmo domínio)
const API_BASE = "";

// Estado de filtros
let filtroTransportadora = "";
let filtroVencimento = "";
let filtroNumeroFatura = "";

// ============ HELPERS ============

function formatCurrency(valor) {
    if (valor === null || valor === undefined) return "R$ 0,00";
    return valor.toLocaleString("pt-BR", {
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
        const resp = await fetch(`${API_BASE}/dashboard/resumo`);
        if (!resp.ok) throw new Error("Erro ao buscar resumo");

        const data = await resp.json();

        document.getElementById("cardTotal").textContent = formatCurrency(
            data.total
        );
        document.getElementById("cardPendentes").textContent = formatCurrency(
            data.pendentes
        );
        document.getElementById("cardAtrasadas").textContent = formatCurrency(
            data.atrasadas
        );
        document.getElementById("cardEmDia").textContent = formatCurrency(
            data.em_dia
        );
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

    // Só manda a data se tiver valor (evita erro 422)
    if (filtroVencimento && filtroVencimento.trim() !== "") {
      params.append("ate_vencimento", filtroVencimento);
    }

    // Só manda o número de fatura se tiver texto
    if (filtroNumeroFatura && filtroNumeroFatura.trim() !== "") {
      params.append("numero_fatura", filtroNumeroFatura.trim());
    }

    const queryString = params.toString();
    const url = queryString
      ? `${API_BASE}/faturas?${queryString}`
      : `${API_BASE}/faturas`;

    const resp = await fetch(url);
    if (!resp.ok) {
      throw new Error("Erro ao listar faturas");
    }

    const faturas = await resp.json();
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


            // listeners do menu
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
    document.getElementById("inputTransportadora").value = f.transportadora;
    document.getElementById("inputNumeroFatura").value = f.numero_fatura;
    document.getElementById("inputValor").value = f.valor;
    document.getElementById("inputVencimento").value = f.data_vencimento;
    document.getElementById("inputStatus").value = f.status;
    document.getElementById("inputObservacao").value = f.observacao ?? "";

    // guarda o id que está sendo editado
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
            // atualização
            resp = await fetch(`${API_BASE}/faturas/${editId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
        } else {
            // criação
            resp = await fetch(`${API_BASE}/faturas`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
        }

        if (!resp.ok) throw new Error("Erro ao salvar fatura");
        const faturaCriadaOuEditada = await resp.json();

        // upload de anexos se tiver
        const inputAnexos = document.getElementById("inputAnexos");
        if (inputAnexos.files.length > 0) {
            const fd = new FormData();
            for (const file of inputAnexos.files) {
                fd.append("files", file);
            }
            const respAnexos = await fetch(
                `${API_BASE}/faturas/${faturaCriadaOuEditada.id}/anexos`,
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

// ============ ABAS / NAVEGAÇÃO ============

function ativarAba(aba) {
    const dash = document.getElementById("dashboardSection");
    const fat = document.getElementById("faturasSection");
    const tabDash = document.getElementById("tabDashboard");
    const tabFat = document.getElementById("tabFaturas");

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

// ============ INIT ============

document.addEventListener("DOMContentLoaded", () => {
    // abas
    document.getElementById("tabDashboard").addEventListener("click", () =>
        ativarAba("dashboard")
    );
    document.getElementById("tabFaturas").addEventListener("click", () =>
        ativarAba("faturas")
    );

    // botão página inicial (leva para dashboard e limpa filtros)
    document.getElementById("btnHome").addEventListener("click", () => {
        filtroTransportadora = "";
        filtroVencimento = "";
        filtroNumeroFatura = "";
        document.getElementById("filtroVencimento").value = "";
        document.getElementById("buscaNumero").value = "";
        ativarAba("dashboard");
        carregarDashboard();
        carregarFaturas();
    });

    // filtro transportadora (botões da sidebar)
    document
        .querySelectorAll(".transportadora-btn")
        .forEach((btn) =>
            btn.addEventListener("click", () => {
                filtroTransportadora = btn.dataset.transportadora || "";
                // marca visualmente
                document
                    .querySelectorAll(".transportadora-btn")
                    .forEach((b) => b.classList.remove("selected"));
                btn.classList.add("selected");
                ativarAba("faturas");
                carregarFaturas();
            })
        );

    // filtro vencimento
    document
        .getElementById("filtroVencimento")
        .addEventListener("change", (e) => {
            filtroVencimento = e.target.value;
            carregarFaturas();
        });

    document
        .getElementById("btnLimparFiltros")
        .addEventListener("click", () => {
            filtroVencimento = "";
            document.getElementById("filtroVencimento").value = "";
            filtroNumeroFatura = "";
            document.getElementById("buscaNumero").value = "";
            carregarFaturas();
        });

    // busca por número de fatura
    document
        .getElementById("buscaNumero")
        .addEventListener("input", (e) => {
            filtroNumeroFatura = e.target.value.trim();
            carregarFaturas();
        });

    // botão atualizar lista
    document
        .getElementById("btnAtualizarFaturas")
        .addEventListener("click", carregarFaturas);

    // formulário
    document
        .getElementById("formFatura")
        .addEventListener("submit", salvarFatura);

    // modal anexos
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

    // carregamento inicial
    carregarDashboard();
    carregarFaturas();
});
