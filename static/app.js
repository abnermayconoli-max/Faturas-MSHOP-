// --------- Troca de abas ---------
const tabButtons = document.querySelectorAll(".tab-btn");
const tabContents = document.querySelectorAll(".tab-content");

tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;

        tabContents.forEach((sec) => sec.classList.remove("ativo"));
        document.getElementById(`tab-${tab}`).classList.add("ativo");
    });
});

// --------- Lista de faturas ---------
const tabelaFaturas = document.getElementById("tabelaFaturas");
const filtroTransportadora = document.getElementById("filtroTransportadora");
const btnFiltrar = document.getElementById("btnFiltrar");
const btnLimpar = document.getElementById("btnLimpar");
const btnExportarFiltro = document.getElementById("btnExportarFiltro");
const btnExportarTodas = document.getElementById("btnExportarTodas");

async function carregarFaturas() {
    let url = "/faturas";

    const transportadora = filtroTransportadora.value.trim();
    if (transportadora) {
        const params = new URLSearchParams({ transportadora });
        url += "?" + params.toString();
    }

    const resp = await fetch(url);
    const dados = await resp.json();

    tabelaFaturas.innerHTML = "";

    dados.forEach((f) => {
        const tr = document.createElement("tr");

        const venc = new Date(f.data_vencimento + "T00:00:00");
        const vencStr = venc.toLocaleDateString("pt-BR");

        tr.innerHTML = `
            <td>${f.id}</td>
            <td>${f.transportadora}</td>
            <td>${f.numero_fatura}</td>
            <td>R$ ${f.valor.toFixed(2).replace(".", ",")}</td>
            <td>${vencStr}</td>
            <td>${f.status}</td>
        `;

        tabelaFaturas.appendChild(tr);
    });
}

btnFiltrar.addEventListener("click", () => carregarFaturas());
btnLimpar.addEventListener("click", () => {
    filtroTransportadora.value = "";
    carregarFaturas();
});

btnExportarFiltro.addEventListener("click", () => {
    const transportadora = filtroTransportadora.value.trim();
    let url = "/faturas/exportar";
    if (transportadora) {
        const params = new URLSearchParams({ transportadora });
        url += "?" + params.toString();
    }
    window.location.href = url;
});

btnExportarTodas.addEventListener("click", () => {
    window.location.href = "/faturas/exportar";
});

// --------- Cadastro ---------
const formCadastro = document.getElementById("formCadastro");
const msgCadastro = document.getElementById("msgCadastro");

formCadastro.addEventListener("submit", async (e) => {
    e.preventDefault();
    msgCadastro.textContent = "";

    const formData = new FormData(formCadastro);

    const payload = {
        transportadora: formData.get("transportadora"),
        numero_fatura: formData.get("numero_fatura"),
        valor: parseFloat(formData.get("valor")),
        data_vencimento: formData.get("data_vencimento"),
        status: formData.get("status"),
    };

    const resp = await fetch("/faturas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });

    if (!resp.ok) {
        msgCadastro.textContent = "Erro ao salvar fatura.";
        msgCadastro.style.color = "red";
        return;
    }

    msgCadastro.textContent = "Fatura salva com sucesso!";
    msgCadastro.style.color = "green";
    formCadastro.reset();

    // atualiza lista
    carregarFaturas();
    atualizarDashboard();
});

// --------- Dashboard ---------
const dashTotalValor = document.getElementById("dashTotalValor");
const dashPendentes = document.getElementById("dashPendentes");
const dashAtrasadas = document.getElementById("dashAtrasadas");
const dashEmDia = document.getElementById("dashEmDia");
const btnAtualizarDashboard = document.getElementById("btnAtualizarDashboard");
const btnExportarTodasDash = document.getElementById("btnExportarTodasDash");

btnAtualizarDashboard.addEventListener("click", atualizarDashboard);
btnExportarTodasDash.addEventListener("click", () => {
    window.location.href = "/faturas/exportar";
});

async function atualizarDashboard() {
    const resp = await fetch("/faturas/resumo");
    const dados = await resp.json();

    const total = dados.total_valor || 0;
    dashTotalValor.textContent = `R$ ${total.toFixed(2).replace(".", ",")}`;

    const porStatus = dados.por_status || {};

    function textoStatus(status) {
        const info = porStatus[status] || { quantidade: 0, valor: 0 };
        return `${info.quantidade} (R$ ${info.valor.toFixed(2).replace(".", ",")})`;
    }

    dashPendentes.textContent = textoStatus("pendente");
    dashAtrasadas.textContent = textoStatus("atrasada");
    dashEmDia.textContent = textoStatus("em dia");
}

// --------- Inicialização ---------
carregarFaturas();
atualizarDashboard();
