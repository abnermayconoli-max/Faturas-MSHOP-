// URL base da API (mesmo domínio do Render)
const API_BASE = "";

// ========= TABS =========

document.addEventListener("DOMContentLoaded", () => {
    const tabButtons = document.querySelectorAll(".tab-button");
    const tabContents = {
        lista: document.getElementById("tab-lista"),
        cadastro: document.getElementById("tab-cadastro"),
        dashboard: document.getElementById("tab-dashboard"),
    };

    tabButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.tab;

            tabButtons.forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");

            Object.keys(tabContents).forEach((key) => {
                tabContents[key].classList.remove("active");
            });
            tabContents[tab].classList.add("active");

            if (tab === "lista") {
                carregarFaturas();
            } else if (tab === "dashboard") {
                carregarDashboard();
            }
        });
    });

    // Eventos da aba LISTA
    document
        .getElementById("btn-filtrar")
        .addEventListener("click", () => carregarFaturas());

    document
        .getElementById("btn-limpar-filtro")
        .addEventListener("click", () => {
            document.getElementById("filtro-transportadora").value = "";
            carregarFaturas();
        });

    document
        .getElementById("btn-exportar-filtro")
        .addEventListener("click", () => exportarFaturas(true));

    document
        .getElementById("btn-exportar-todas")
        .addEventListener("click", () => exportarFaturas(false));

    // Evento da aba CADASTRO
    document
        .getElementById("form-cadastro")
        .addEventListener("submit", enviarCadastro);

    // Botão de export no Dashboard (usa todas as faturas)
    document
        .getElementById("btn-exportar-dashboard")
        .addEventListener("click", () => exportarFaturas(false));

    // Carrega inicial
    carregarFaturas();
    carregarDashboard();
});

// ========= FUNÇÕES LISTA =========

async function carregarFaturas() {
    try {
        const filtro = document.getElementById("filtro-transportadora").value.trim();
        let url = "/faturas";
        if (filtro) {
            url += `?transportadora=${encodeURIComponent(filtro)}`;
        }

        const resp = await fetch(API_BASE + url);
        if (!resp.ok) {
            throw new Error("Erro ao buscar faturas");
        }
        const dados = await resp.json();

        const tbody = document.getElementById("tabela-faturas");
        tbody.innerHTML = "";

        if (dados.length === 0) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = 6;
            td.textContent = "Nenhuma fatura encontrada.";
            tr.appendChild(td);
            tbody.appendChild(tr);
            return;
        }

        dados.forEach((f) => {
            const tr = document.createElement("tr");

            const tdId = document.createElement("td");
            tdId.textContent = f.id;
            tr.appendChild(tdId);

            const tdTransp = document.createElement("td");
            tdTransp.textContent = f.transportadora;
            tr.appendChild(tdTransp);

            const tdNum = document.createElement("td");
            tdNum.textContent = f.numero_fatura;
            tr.appendChild(tdNum);

            const tdValor = document.createElement("td");
            tdValor.textContent = formatarValor(f.valor);
            tr.appendChild(tdValor);

            const tdVenc = document.createElement("td");
            tdVenc.textContent = formatarData(f.data_vencimento);
            tr.appendChild(tdVenc);

            const tdStatus = document.createElement("td");
            tdStatus.textContent = f.status;
            tr.appendChild(tdStatus);

            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error(err);
        alert("Erro ao carregar faturas.");
    }
}

function exportarFaturas(apenasFiltro) {
    const filtro = document.getElementById("filtro-transportadora").value.trim();

    let url = "/faturas/export";
    if (apenasFiltro && filtro) {
        url += `?transportadora=${encodeURIComponent(filtro)}`;
    }

    // abre o download
    window.location.href = API_BASE + url;
}

// ========= FUNÇÕES CADASTRO =========

async function enviarCadastro(event) {
    event.preventDefault();

    const transportadora = document.getElementById("cad-transportadora").value.trim();
    const numero_fatura = document.getElementById("cad-numero").value.trim();
    const valor = parseFloat(document.getElementById("cad-valor").value);
    const data_vencimento = document.getElementById("cad-vencimento").value;
    const status = document.getElementById("cad-status").value;

    if (!transportadora || !numero_fatura || !data_vencimento || isNaN(valor)) {
        alert("Preencha todos os campos corretamente.");
        return;
    }

    const payload = {
        transportadora,
        numero_fatura,
        valor,
        data_vencimento,
        status,
    };

    try {
        const resp = await fetch(API_BASE + "/faturas", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            throw new Error("Erro ao cadastrar fatura");
        }

        document.getElementById("form-cadastro").reset();
        document.getElementById("msg-cadastro").textContent =
            "Fatura cadastrada com sucesso!";
        carregarFaturas();
        carregarDashboard();
    } catch (err) {
        console.error(err);
        alert("Erro ao cadastrar fatura.");
    }
}

// ========= FUNÇÕES DASHBOARD =========

async function carregarDashboard() {
    try {
        const resp = await fetch(API_BASE + "/dashboard/resumo");
        if (!resp.ok) {
            throw new Error("Erro ao buscar resumo");
        }

        const d = await resp.json();

        document.getElementById("dash-total-faturas").textContent =
            d.total_faturas ?? 0;
        document.getElementById("dash-total-valor").textContent =
            formatarValor(d.total_valor);
        document.getElementById("dash-total-pendente").textContent =
            formatarValor(d.total_pendente);
        document.getElementById("dash-total-atrasado").textContent =
            formatarValor(d.total_atrasado);
        document.getElementById("dash-total-em-dia").textContent =
            formatarValor(d.total_em_dia);
    } catch (err) {
        console.error(err);
    }
}

// ========= HELPERS =========

function formatarValor(v) {
    const num = Number(v) || 0;
    return num.toLocaleString("pt-BR", {
        style: "currency",
        currency: "BRL",
    });
}

function formatarData(dataStr) {
    if (!dataStr) return "";
    // normalmente vem "2025-12-08"
    const [ano, mes, dia] = dataStr.split("-");
    if (!ano || !mes || !dia) return dataStr;
    return `${dia}/${mes}/${ano}`;
}
