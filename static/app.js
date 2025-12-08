// ---- Navegação entre abas ----
const pages = {
    dashboard: document.getElementById("page-dashboard"),
    faturas: document.getElementById("page-faturas"),
    cadastro: document.getElementById("page-cadastro"),
};

document.querySelectorAll(".menu-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
        const page = btn.dataset.page;

        document.querySelectorAll(".menu-btn").forEach((b) =>
            b.classList.remove("active")
        );
        btn.classList.add("active");

        Object.entries(pages).forEach(([name, el]) => {
            el.classList.toggle("visible", name === page);
        });

        if (page === "dashboard") {
            carregarDashboard();
        } else if (page === "faturas") {
            carregarFaturas();
        }
    });
});

// ---- Util ----
function formatarValor(valor) {
    return valor.toLocaleString("pt-BR", {
        style: "currency",
        currency: "BRL",
        minimumFractionDigits: 2,
    });
}

function formatarDataISOparaBR(dataIso) {
    if (!dataIso) return "";
    const [ano, mes, dia] = dataIso.split("-");
    return `${dia}/${mes}/${ano}`;
}

// ---- Dashboard ----

async function carregarDashboard() {
    try {
        const resp = await fetch("/dashboard-resumo");
        if (!resp.ok) throw new Error("Erro ao buscar resumo");
        const data = await resp.json();

        document.getElementById("total-valor").textContent = formatarValor(
            data.total.valor || 0
        );
        document.getElementById(
            "total-qtd"
        ).textContent = `${data.total.quantidade || 0} faturas`;

        document.getElementById("pendentes-qtd").textContent =
            data.pendentes.quantidade || 0;
        document.getElementById("pendentes-valor").textContent = formatarValor(
            data.pendentes.valor || 0
        );

        document.getElementById("atrasadas-qtd").textContent =
            data.atrasadas.quantidade || 0;
        document.getElementById("atrasadas-valor").textContent = formatarValor(
            data.atrasadas.valor || 0
        );

        document.getElementById("emdia-qtd").textContent =
            data.em_dia.quantidade || 0;
        document.getElementById("emdia-valor").textContent = formatarValor(
            data.em_dia.valor || 0
        );
    } catch (e) {
        console.error(e);
        alert("Erro ao carregar dashboard.");
    }
}

document
    .getElementById("btn-atualizar-dashboard")
    .addEventListener("click", carregarDashboard);

document
    .getElementById("btn-exportar-excel-dashboard")
    .addEventListener("click", () => {
        window.location.href = "/faturas/exportar";
    });

// ---- Lista de faturas ----

async function carregarFaturas() {
    const filtro = document.getElementById("filtro-transportadora").value.trim();
    let url = "/faturas";
    if (filtro) {
        const params = new URLSearchParams({ transportadora: filtro });
        url += `?${params.toString()}`;
    }

    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error("Erro ao buscar faturas");
        const lista = await resp.json();

        const tbody = document.querySelector("#tabela-faturas tbody");
        tbody.innerHTML = "";

        if (!lista.length) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = 6;
            td.textContent = "Nenhuma fatura encontrada.";
            tbody.appendChild(tr);
            tr.appendChild(td);
            return;
        }

        lista.forEach((f) => {
            const tr = document.createElement("tr");

            tr.innerHTML = `
                <td>${f.id}</td>
                <td>${f.transportadora}</td>
                <td>${f.numero_fatura}</td>
                <td>${formatarValor(f.valor)}</td>
                <td>${formatarDataISOparaBR(f.data_vencimento)}</td>
                <td>${f.status}</td>
            `;

            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error(e);
        alert("Erro ao carregar faturas.");
    }
}

document.getElementById("btn-filtrar").addEventListener("click", carregarFaturas);
document
    .getElementById("btn-limpar-filtro")
    .addEventListener("click", () => {
        document.getElementById("filtro-transportadora").value = "";
        carregarFaturas();
    });

document
    .getElementById("btn-exportar-excel")
    .addEventListener("click", () => {
        window.location.href = "/faturas/exportar";
    });

// ---- Cadastro ----

document
    .getElementById("form-cadastro")
    .addEventListener("submit", async (event) => {
        event.preventDefault();

        const form = event.target;
        const dados = {
            transportadora: form.transportadora.value.trim(),
            numero_fatura: form.numero_fatura.value.trim(),
            valor: parseFloat(form.valor.value),
            data_vencimento: form.data_vencimento.value,
            status: form.status.value,
        };

        try {
            const resp = await fetch("/faturas", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(dados),
            });

            if (!resp.ok) {
                const erro = await resp.json().catch(() => ({}));
                throw new Error(
                    erro.detail || "Erro ao salvar fatura. Verifique os dados."
                );
            }

            form.reset();
            document.getElementById("mensagem-cadastro").textContent =
                "Fatura cadastrada com sucesso!";

            // Atualiza dashboard e lista
            carregarDashboard();
            carregarFaturas();
        } catch (e) {
            console.error(e);
            alert(e.message);
        }
    });

// ---- Inicialização da tela ----

carregarDashboard();
