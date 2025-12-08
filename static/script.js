// ===========================
// Funções auxiliares
// ===========================

function formatarDataISOParaBR(dataISO) {
    if (!dataISO) return "";
    const d = new Date(dataISO);
    const dia = String(d.getDate()).padStart(2, "0");
    const mes = String(d.getMonth() + 1).padStart(2, "0");
    const ano = d.getFullYear();
    return `${dia}/${mes}/${ano}`;
}

function formatarValor(valor) {
    return Number(valor).toLocaleString("pt-BR", {
        style: "currency",
        currency: "BRL",
    });
}

function mostrarMensagem(texto, tipo = "sucesso") {
    const el = document.getElementById("mensagem");
    el.textContent = texto;
    el.className = tipo; // .sucesso ou .erro no CSS
    if (texto) {
        setTimeout(() => {
            el.textContent = "";
            el.className = "";
        }, 4000);
    }
}

// ===========================
// Listar faturas
// ===========================

async function carregarFaturas(filtro = "todas") {
    try {
        let url = "/faturas";

        if (filtro === "atrasadas") {
            url = "/faturas/atrasadas";
        }

        const resp = await fetch(url);
        if (!resp.ok) {
            throw new Error("Erro ao listar faturas");
        }

        let faturas = await resp.json();

        if (filtro === "pendente") {
            faturas = faturas.filter((f) => f.status === "pendente");
        } else if (filtro === "pago") {
            faturas = faturas.filter((f) => f.status === "pago");
        }

        preencherTabela(faturas);
    } catch (e) {
        console.error(e);
        mostrarMensagem("Falha ao carregar faturas", "erro");
    }
}

function preencherTabela(faturas) {
    const tbody = document.querySelector("#tabela-faturas tbody");
    tbody.innerHTML = "";

    if (!faturas.length) {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 7;
        td.textContent = "Nenhuma fatura encontrada.";
        td.style.textAlign = "center";
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
    }

    faturas.forEach((f) => {
        const tr = document.createElement("tr");

        tr.innerHTML = `
            <td>${f.id}</td>
            <td>${f.transportadora}</td>
            <td>${f.numero_fatura}</td>
            <td>${formatarValor(f.valor)}</td>
            <td>${formatarDataISOParaBR(f.data_vencimento)}</td>
            <td>${f.status}</td>
            <td>
                <button class="btn-acao" data-acao="pagar" data-id="${f.id}">Marcar pago</button>
                <button class="btn-acao btn-danger" data-acao="deletar" data-id="${f.id}">Excluir</button>
            </td>
        `;

        tbody.appendChild(tr);
    });
}

// ===========================
// Criar fatura
// ===========================

async function criarFatura(event) {
    event.preventDefault();

    const transportadora = document.getElementById("transportadora").value;
    const numero_fatura = document.getElementById("numero_fatura").value;
    const valor = document.getElementById("valor").value;
    const data_vencimento = document.getElementById("data_vencimento").value;
    const status = document.getElementById("status").value;

    try {
        const resp = await fetch("/faturas", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                transportadora,
                numero_fatura,
                valor: Number(valor),
                data_vencimento,
                status,
            }),
        });

        if (!resp.ok) {
            throw new Error("Erro ao criar fatura");
        }

        await resp.json();
        mostrarMensagem("Fatura criada com sucesso!");
        document.getElementById("form-fatura").reset();
        carregarFaturas();
    } catch (e) {
        console.error(e);
        mostrarMensagem("Falha ao criar fatura", "erro");
    }
}

// ===========================
// Atualizar status / deletar
// ===========================

async function marcarComoPago(id) {
    try {
        const resp = await fetch(`/faturas/${id}/status`, {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ status: "pago" }),
        });

        if (!resp.ok) {
            throw new Error("Erro ao atualizar status");
        }

        mostrarMensagem("Fatura marcada como paga!");
        carregarFaturas();
    } catch (e) {
        console.error(e);
        mostrarMensagem("Falha ao atualizar status", "erro");
    }
}

async function deletarFatura(id) {
    if (!confirm("Tem certeza que deseja excluir esta fatura?")) {
        return;
    }

    try {
        const resp = await fetch(`/faturas/${id}`, {
            method: "DELETE",
        });

        if (!resp.ok) {
            throw new Error("Erro ao deletar fatura");
        }

        mostrarMensagem("Fatura deletada com sucesso!");
        carregarFaturas();
    } catch (e) {
        console.error(e);
        mostrarMensagem("Falha ao deletar fatura", "erro");
    }
}

// ===========================
// Eventos da página
// ===========================

document.addEventListener("DOMContentLoaded", () => {
    // Submit do formulário
    document
        .getElementById("form-fatura")
        .addEventListener("submit", criarFatura);

    // Clique nos botões de ação da tabela
    document
        .querySelector("#tabela-faturas tbody")
        .addEventListener("click", (event) => {
            const btn = event.target;
            if (!btn.classList.contains("btn-acao")) return;

            const id = btn.getAttribute("data-id");
            const acao = btn.getAttribute("data-acao");

            if (acao === "pagar") {
                marcarComoPago(id);
            } else if (acao === "deletar") {
                deletarFatura(id);
            }
        });

    // Filtros
    document.querySelectorAll(".btn-filtro").forEach((btn) => {
        btn.addEventListener("click", () => {
            document
                .querySelectorAll(".btn-filtro")
                .forEach((b) => b.classList.remove("ativo"));

            btn.classList.add("ativo");
            const filtro = btn.getAttribute("data-filtro");
            carregarFaturas(filtro);
        });
    });

    // Carrega inicialmente
    carregarFaturas();
});
