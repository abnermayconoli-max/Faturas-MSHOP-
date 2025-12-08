document.addEventListener("DOMContentLoaded", () => {
    const API_BASE = ""; // mesma origem

    // Resumo
    const spanTotal = document.getElementById("resumo-total");
    const spanPendentes = document.getElementById("resumo-pendentes");
    const spanAtrasadas = document.getElementById("resumo-atrasadas");
    const spanEmDia = document.getElementById("resumo-em-dia");

    // Filtros
    const filtroTransportadoras = document.getElementById("filtro-transportadoras");
    const inputVencimento = document.getElementById("filtro-vencimento");
    const btnAplicarVenc = document.getElementById("btn-aplicar-venc");
    const btnLimparVenc = document.getElementById("btn-limpar-venc");

    // Tabela
    const tbodyFaturas = document.getElementById("tbody-faturas");

    // Abas
    const tabs = document.querySelectorAll(".tab");
    const tabContents = document.querySelectorAll(".tab-content");

    // Cadastro
    const formCadastro = document.getElementById("form-cadastro");
    const cadTransportadora = document.getElementById("cad-transportadora");
    const cadNumero = document.getElementById("cad-numero");
    const cadValor = document.getElementById("cad-valor");
    const cadVencimento = document.getElementById("cad-vencimento");
    const cadStatus = document.getElementById("cad-status");
    const cadObs = document.getElementById("cad-observacao");
    const cadAnexos = document.getElementById("cad-anexos");

    // Modal editar
    const modalEditar = document.getElementById("modal-editar");
    const formEditar = document.getElementById("form-editar");
    const editId = document.getElementById("edit-id");
    const editTransportadora = document.getElementById("edit-transportadora");
    const editNumero = document.getElementById("edit-numero");
    const editValor = document.getElementById("edit-valor");
    const editVencimento = document.getElementById("edit-vencimento");
    const editStatus = document.getElementById("edit-status");
    const editObs = document.getElementById("edit-observacao");
    const editAnexos = document.getElementById("edit-anexos");

    // Modal anexos
    const modalAnexos = document.getElementById("modal-anexos");
    const listaAnexos = document.getElementById("lista-anexos");

    let filtroTransportadoraAtual = "";
    let filtroVencimentoAtual = "";

    // ========= Helpers =========

    function formatCurrency(value) {
        const num = Number(value || 0);
        return num.toLocaleString("pt-BR", {
            style: "currency",
            currency: "BRL",
        });
    }

    function formatDate(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        return d.toLocaleDateString("pt-BR");
    }

    function isoFromInputDate(value) {
        // value: yyyy-mm-dd
        return value || "";
    }

    function openModal(modal) {
        modal.classList.add("show");
    }

    function closeModal(modal) {
        modal.classList.remove("show");
    }

    document.querySelectorAll("[data-close-modal]").forEach(btn => {
        btn.addEventListener("click", () => {
            closeModal(modalEditar);
            closeModal(modalAnexos);
        });
    });

    window.addEventListener("click", (ev) => {
        if (ev.target === modalEditar) closeModal(modalEditar);
        if (ev.target === modalAnexos) closeModal(modalAnexos);
    });

    // ========= Resumo =========

    async function carregarResumo() {
        try {
            const resp = await fetch(`${API_BASE}/dashboard/resumo`);
            if (!resp.ok) throw new Error("Erro ao carregar resumo");
            const data = await resp.json();
            spanTotal.textContent = formatCurrency(data.total);
            spanPendentes.textContent = formatCurrency(data.pendentes);
            spanAtrasadas.textContent = formatCurrency(data.atrasadas);
            spanEmDia.textContent = formatCurrency(data.em_dia);
        } catch (e) {
            console.error(e);
        }
    }

    // ========= Faturas =========

    async function carregarFaturas() {
        try {
            const params = new URLSearchParams();
            if (filtroTransportadoraAtual) {
                params.append("transportadora", filtroTransportadoraAtual);
            }
            if (filtroVencimentoAtual) {
                params.append("ate_vencimento", filtroVencimentoAtual);
            }

            const url = `${API_BASE}/faturas?${params.toString()}`;
            const resp = await fetch(url);
            if (!resp.ok) throw new Error("Erro ao listar faturas");
            const data = await resp.json();
            renderizarFaturas(data);
        } catch (e) {
            console.error(e);
        }
    }

    function renderizarFaturas(faturas) {
        tbodyFaturas.innerHTML = "";

        if (!faturas || faturas.length === 0) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = 9;
            td.textContent = "Nenhuma fatura encontrada.";
            td.classList.add("empty");
            tr.appendChild(td);
            tbodyFaturas.appendChild(tr);
            return;
        }

        for (const f of faturas) {
            const tr = document.createElement("tr");

            tr.innerHTML = `
                <td>${f.id}</td>
                <td>${f.transportadora}</td>
                <td>${f.responsavel || ""}</td>
                <td>${f.numero_fatura}</td>
                <td>${formatCurrency(f.valor)}</td>
                <td>${formatDate(f.data_vencimento)}</td>
                <td>${f.status}</td>
                <td class="obs-col" title="${f.observacao || ""}">
                    ${f.observacao ? f.observacao.substring(0, 30) + (f.observacao.length > 30 ? "..." : "") : ""}
                </td>
                <td>
                    <div class="menu-container">
                        <button class="menu-btn" data-menu="btn">⋮</button>
                        <div class="menu-dropdown">
                            <button data-acao="editar">Editar</button>
                            <button data-acao="anexos">Anexos</button>
                            <button data-acao="excluir" class="danger">Excluir</button>
                        </div>
                    </div>
                </td>
            `;

            const menuContainer = tr.querySelector(".menu-container");
            const btnMenu = tr.querySelector(".menu-btn");
            const dropdown = tr.querySelector(".menu-dropdown");

            btnMenu.addEventListener("click", (ev) => {
                ev.stopPropagation();
                // fecha outros dropdowns
                document.querySelectorAll(".menu-dropdown.show").forEach(el => {
                    if (el !== dropdown) el.classList.remove("show");
                });
                dropdown.classList.toggle("show");
            });

            document.addEventListener("click", () => {
                dropdown.classList.remove("show");
            });

            dropdown.addEventListener("click", async (ev) => {
                ev.stopPropagation();
                const acao = ev.target.getAttribute("data-acao");
                if (!acao) return;

                if (acao === "editar") {
                    abrirModalEditar(f);
                } else if (acao === "excluir") {
                    excluirFatura(f.id);
                } else if (acao === "anexos") {
                    abrirModalAnexos(f.id);
                }

                dropdown.classList.remove("show");
            });

            tbodyFaturas.appendChild(tr);
        }
    }

    async function excluirFatura(id) {
        if (!confirm(`Deseja realmente excluir a fatura ${id}?`)) return;
        try {
            const resp = await fetch(`${API_BASE}/faturas/${id}`, {
                method: "DELETE",
            });
            if (!resp.ok) {
                alert("Erro ao excluir fatura");
                return;
            }
            await carregarResumo();
            await carregarFaturas();
        } catch (e) {
            console.error(e);
            alert("Erro ao excluir fatura");
        }
    }

    function abrirModalEditar(f) {
        editId.value = f.id;
        editTransportadora.value = f.transportadora;
        editNumero.value = f.numero_fatura;
        editValor.value = f.valor;
        editVencimento.value = f.data_vencimento;
        editStatus.value = f.status;
        editObs.value = f.observacao || "";
        editAnexos.value = null;
        openModal(modalEditar);
    }

    async function abrirModalAnexos(faturaId) {
        listaAnexos.innerHTML = "<li>Carregando...</li>";
        openModal(modalAnexos);

        try {
            const resp = await fetch(`${API_BASE}/faturas/${faturaId}/anexos`);
            if (!resp.ok) throw new Error("Erro ao buscar anexos");
            const data = await resp.json();

            listaAnexos.innerHTML = "";
            if (!data || data.length === 0) {
                listaAnexos.innerHTML = "<li>Não há anexos para esta fatura.</li>";
                return;
            }

            for (const anexo of data) {
                const li = document.createElement("li");
                const link = document.createElement("a");
                link.href = `${API_BASE}/anexos/${anexo.id}`;
                link.textContent = anexo.original_name;
                link.target = "_blank";
                li.appendChild(link);
                listaAnexos.appendChild(li);
            }
        } catch (e) {
            console.error(e);
            listaAnexos.innerHTML = "<li>Erro ao carregar anexos.</li>";
        }
    }

    // ========= Cadastro =========

    formCadastro.addEventListener("submit", async (ev) => {
        ev.preventDefault();

        const payload = {
            transportadora: cadTransportadora.value,
            numero_fatura: cadNumero.value,
            valor: parseFloat(cadValor.value || "0"),
            data_vencimento: cadVencimento.value,
            status: cadStatus.value,
            observacao: cadObs.value.trim() || null,
        };

        try {
            const resp = await fetch(`${API_BASE}/faturas`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            });

            if (!resp.ok) {
                const txt = await resp.text();
                console.error(txt);
                alert("Erro ao salvar fatura");
                return;
            }

            const faturaCriada = await resp.json();

            // Upload de anexos se tiver
            if (cadAnexos.files.length > 0) {
                await enviarAnexos(faturaCriada.id, cadAnexos.files);
            }

            formCadastro.reset();
            await carregarResumo();
            await carregarFaturas();

            // volta para aba faturas
            ativarAba("faturas");
        } catch (e) {
            console.error(e);
            alert("Erro ao salvar fatura");
        }
    });

    async function enviarAnexos(faturaId, fileList) {
        const formData = new FormData();
        for (const file of fileList) {
            formData.append("files", file);
        }

        const resp = await fetch(`${API_BASE}/faturas/${faturaId}/anexos`, {
            method: "POST",
            body: formData,
        });

        if (!resp.ok) {
            console.error(await resp.text());
            alert("Erro ao enviar anexos");
        }
    }

    // ========= Edição =========

    formEditar.addEventListener("submit", async (ev) => {
        ev.preventDefault();

        const id = editId.value;

        const payload = {
            transportadora: editTransportadora.value,
            numero_fatura: editNumero.value,
            valor: parseFloat(editValor.value || "0"),
            data_vencimento: editVencimento.value,
            status: editStatus.value,
            observacao: editObs.value.trim() || null,
        };

        try {
            const resp = await fetch(`${API_BASE}/faturas/${id}`, {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            });

            if (!resp.ok) {
                console.error(await resp.text());
                alert("Erro ao atualizar fatura");
                return;
            }

            // se tiver novos anexos, envia
            if (editAnexos.files.length > 0) {
                await enviarAnexos(id, editAnexos.files);
            }

            closeModal(modalEditar);
            await carregarResumo();
            await carregarFaturas();
        } catch (e) {
            console.error(e);
            alert("Erro ao atualizar fatura");
        }
    });

    // ========= Filtros =========

    filtroTransportadoras.addEventListener("click", (ev) => {
        const btn = ev.target.closest("button[data-transportadora]");
        if (!btn) return;

        filtroTransportadoraAtual = btn.getAttribute("data-transportadora") || "";

        filtroTransportadoras
            .querySelectorAll("button[data-transportadora]")
            .forEach(b => b.classList.remove("active"));
        btn.classList.add("active");

        carregarFaturas();
    });

    btnAplicarVenc.addEventListener("click", () => {
        filtroVencimentoAtual = isoFromInputDate(inputVencimento.value);
        carregarFaturas();
    });

    btnLimparVenc.addEventListener("click", () => {
        filtroVencimentoAtual = "";
        inputVencimento.value = "";
        carregarFaturas();
    });

    // ========= Abas =========

    function ativarAba(nome) {
        tabs.forEach(tab => {
            const tabName = tab.getAttribute("data-tab");
            tab.classList.toggle("active", tabName === nome);
        });

        tabContents.forEach(content => {
            content.classList.toggle("active", content.id === `tab-${nome}`);
        });
    }

    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            const nome = tab.getAttribute("data-tab");
            ativarAba(nome);
        });
    });

    // ========= Inicialização =========

    carregarResumo();
    carregarFaturas();
});
