// =============================
// FORMATAÇÃO
// =============================
function formatarValor(v) {
    return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

// =============================
// CARREGAR DASHBOARD GERAL
// =============================
async function carregarResumoGeral() {
    try {
        const r = await fetch("/dashboard/resumo");
        const d = await r.json();

        document.getElementById("dash-total").innerText = formatarValor(d.total);
        document.getElementById("dash-pendentes").innerText = formatarValor(d.pendentes);
        document.getElementById("dash-atrasadas").innerText = formatarValor(d.atrasadas);
        document.getElementById("dash-em-dia").innerText = formatarValor(d.em_dia);

    } catch (e) {
        console.error("Erro ao carregar resumo geral", e);
    }
}

// =============================
// CARREGAR RESUMO FILTRADO
// =============================
async function carregarResumoTransportadora(nome) {
    try {
        const r = await fetch(`/dashboard/resumo_por_transportadora?transportadora=${encodeURIComponent(nome)}`);
        const d = await r.json();

        document.getElementById("dash-total").innerText = formatarValor(d.total);
        document.getElementById("dash-pendentes").innerText = formatarValor(d.pendentes);
        document.getElementById("dash-atrasadas").innerText = formatarValor(d.atrasadas);
        document.getElementById("dash-em-dia").innerText = formatarValor(d.em_dia);

    } catch (e) {
        console.error("Erro ao carregar resumo transportadora", e);
    }
}

// =============================
// AÇÕES AO CLICAR NOS BOTÕES DO MENU LATERAL
// =============================
document.querySelectorAll(".item-transportadora").forEach(btn => {
    btn.addEventListener("click", () => {
        const nome = btn.innerText.trim();

        document.querySelectorAll(".item-transportadora")
            .forEach(i => i.classList.remove("selecionado"));

        btn.classList.add("selecionado");

        if (nome === "Todas") {
            carregarResumoGeral();
        } else {
            carregarResumoTransportadora(nome);
        }
    });
});

// =============================
// INICIAR TELA
// =============================
carregarResumoGeral();
