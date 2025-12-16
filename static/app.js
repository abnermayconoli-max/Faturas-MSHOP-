// URL base (vazio = mesmo domínio)
const API_BASE = "";

// ============ ESTADO (FILTROS) ============

// Filtros globais (sidebar + busca)
let filtroTransportadora = "";
let filtroNumeroFatura = "";

// Filtros só da aba Faturas
let filtroDataInicioFaturas = "";
let filtroDataFimFaturas = "";
let filtroStatus = "";

// Cache da última lista vinda da API
let ultimaListaFaturas = [];

// ✅ modo do dashboard
let dashboardModo = "pendente"; // "pendente" | "pago"

// ============ HELPERS ============

function formatCurrency(valor) {
  if (valor === null || valor === undefined) return "R$ 0,00";
  const n = Number(valor) || 0;
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
  });
}

// converte string ISO (yyyy-mm-dd ou data completa) pra Date LOCAL
function parseISODateLocal(isoDate) {
  if (!isoDate) return null;

  if (/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    const [y, m, d] = isoDate.split("-").map(Number);
    return new Date(y, m - 1, d);
  }

  const d = new Date(isoDate);
  return Number.isNaN(d.getTime()) ? null : d;
}

// dd/mm/aaaa
function formatDate(isoDate) {
  if (!isoDate) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    const [y, m, d] = isoDate.split("-");
    return `${d}/${m}/${y}`;
  }
  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString("pt-BR");
}

// pega próxima quarta (JS) – dom=0 seg=1 ter=2 qua=3
function getProxQuartaTime() {
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);

  const weekday = hoje.getDay();
  let diasAteQuarta = (3 - weekday + 7) % 7;
  if (diasAteQuarta === 0) diasAteQuarta = 7;

  const proxQuarta = new Date(hoje);
  proxQuarta.setDate(hoje.getDate() + diasAteQuarta);
  proxQuarta.setHours(0, 0, 0, 0);
  return proxQuarta.getTime();
}

// ============ DASHBOARD ============

async function carregarDashboard() {
  try {
    const params = new URLSearchParams();

    if (filtroTransportadora) params.append("transportadora", filtroTransportadora);

    // ✅ usa DE/ATÉ da sidebar
    const de = document.getElementById("filtroVencimentoDe")?.value || "";
    const ate = document.getElementById("filtroVencimentoAte")?.value || "";
    if (de) params.append("de_vencimento", de);
    if (ate) params.append("ate_vencimento", ate);

    // 1) Resumo geral (cards) via API
    const urlResumo =
      params.toString().length > 0
        ? `${API_BASE}/dashboard/resumo?${params.toString()}`
        : `${API_BASE}/dashboard/resumo`;

    const respResumo = await fetch(urlResumo);
    if (!respResumo.ok) throw new Error("Erro ao buscar resumo");
    const dataResumo = await respResumo.json();

    // ✅ ajustado para seu retorno do main.py
    document.getElementById("cardTotal").textContent = formatCurrency(dataResumo.total_geral);
    document.getElementById("cardPendentes").textContent = formatCurrency(dataResumo.total_em_dia);
    document.getElementById("cardAtrasadas").textContent = formatCurrency(dataResumo.total_atrasado);
    document.getElementById("cardEmDia").textContent = formatCurrency(dataResumo.total_pago);

    // 2) Tabela do dashboard usando a lista de faturas
    let lista = Array.isArray(ultimaListaFaturas) ? [...ultimaListaFaturas] : [];

    if (lista.length === 0) {
      const urlF =
        params.toString().length > 0
          ? `${API_BASE}/faturas?${params.toString()}`
          : `${API_BASE}/faturas`;

      const respFat = await fetch(urlF);
      if (!respFat.ok) throw new Error("Erro ao buscar faturas");
      lista = await respFat.json();
    }

    renderResumoDashboard(lista);
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar dashboard");
  }
}

// monta tabela horizontal tipo backlog (Pendente ou Pago)
function renderResumoDashboard(lista) {
  const thead = document.getElementById("theadResumoDashboard");
  const tbody = document.getElementById("tbodyResumoDashboard");
  const titulo = document.getElementById("tituloTabelaDashboard");
  if (!thead || !tbody) return;

  if (titulo) {
    titulo.textContent =
      dashboardModo === "pago"
        ? "Pagas por transportadora"
        : "Resumo por transportadora";
  }

  const proxQuartaTime = getProxQuartaTime();

  // ===== datas do cabeçalho conforme modo =====
  const datasSet = new Set();
  lista.forEach((f) => {
    const statusLower = (f.status || "").toLowerCase();

    const ok =
      dashboardModo === "pago"
        ? statusLower === "pago"
        : statusLower !== "pago";

    if (ok && f.data_vencimento) datasSet.add(f.data_vencimento);
  });

  const datas = Array.from(datasSet).sort();

  // ===== Cabeçalho dinâmico =====
  let headerHtml = `<tr><th>Transportadora</th>`;

  if (dashboardModo === "pago") {
    headerHtml += `<th>Total pago</th>`;
  } else {
    headerHtml += `<th>Total atrasado</th><th>Total em dia</th><th>Total geral</th>`;
  }

  datas.forEach((d) => {
    headerHtml += `<th>${formatDate(d)}</th>`;
  });

  headerHtml += `</tr>`;
  thead.innerHTML = headerHtml;

  // ===== Agrupar por transportadora =====
  const grupos = {};

  function ensure(transp) {
    if (!grupos[transp]) {
      grupos[transp] = {
        totalAtrasado: 0,
        totalEmDia: 0,
        totalGeral: 0,
        totalPago: 0,
        porData: {},
      };
    }
  }

  lista.forEach((f) => {
    const transp = f.transportadora || "Sem nome";
    ensure(transp);

    const valor = Number(f.valor || 0);
    const statusLower = (f.status || "").toLowerCase();
    const ok =
      dashboardModo === "pago"
        ? statusLower === "pago"
        : statusLower !== "pago";

    if (!ok) return;

    const key = f.data_vencimento;
    grupos[transp].porData[key] = (grupos[transp].porData[key] || 0) + valor;

    if (dashboardModo === "pago") {
      grupos[transp].totalPago += valor;
      return;
    }

    // pendente mode
    grupos[transp].totalGeral += valor;

    const d = parseISODateLocal(f.data_vencimento);
    const vencTime = d ? d.setHours(0, 0, 0, 0) : null;

    if (statusLower === "atrasado") {
      grupos[transp].totalAtrasado += valor;
    } else if (statusLower === "pendente") {
      if (vencTime !== null && vencTime < proxQuartaTime) grupos[transp].totalAtrasado += valor;
      else grupos[transp].totalEmDia += valor; // ✅ >= próxima quarta entra em dia
    }
  });

  // ===== Render =====
  tbody.innerHTML = "";

  const ordemPreferida = ["DHL", "Pannan", "Transbritto", "PDA", "GLM", "Garcia", "Excargo"];
  const chaves = Object.keys(grupos);

  chaves.sort((a, b) => {
    const ia = ordemPreferida.indexOf(a);
    const ib = ordemPreferida.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });

  // totais gerais
  let totAtrasado = 0, totEmDia = 0, totGeral = 0, totPago = 0;
  const totaisPorData = {};

  chaves.forEach((transp) => {
    const g = grupos[transp];

    datas.forEach((d) => {
      const v = g.porData[d] || 0;
      totaisPorData[d] = (totaisPorData[d] || 0) + v;
    });

    const tr = document.createElement("tr");
    let html = `<td>${transp}</td>`;

    if (dashboardModo === "pago") {
      totPago += g.totalPago;
      html += `<td>${formatCurrency(g.totalPago)}</td>`;
    } else {
      totAtrasado += g.totalAtrasado;
      totEmDia += g.totalEmDia;
      totGeral += g.totalGeral;

      html += `
        <td>${formatCurrency(g.totalAtrasado)}</td>
        <td>${formatCurrency(g.totalEmDia)}</td>
        <td>${formatCurrency(g.totalGeral)}</td>
      `;
    }

    datas.forEach((d) => {
      const val = g.porData[d] || 0;
      html += `<td>${val ? formatCurrency(val) : "-"}</td>`;
    });

    tr.innerHTML = html;
    tbody.appendChild(tr);

    // ✅ espaço depois da Pannan e GLM
    if (transp === "Pannan" || transp === "GLM") {
      const spacer = document.createElement("tr");
      spacer.className = "spacer-row";
      const td = document.createElement("td");
      td.colSpan = (dashboardModo === "pago" ? (2 + datas.length) : (4 + datas.length));
      td.innerHTML = "&nbsp;";
      spacer.appendChild(td);
      tbody.appendChild(spacer);
    }
  });

  // linha total
  if (chaves.length > 0) {
    const trTotal = document.createElement("tr");

    let html = `<td><strong>Total geral</strong></td>`;

    if (dashboardModo === "pago") {
      html += `<td><strong>${formatCurrency(totPago)}</strong></td>`;
    } else {
      html += `
        <td><strong>${formatCurrency(totAtrasado)}</strong></td>
        <td><strong>${formatCurrency(totEmDia)}</strong></td>
        <td><strong>${formatCurrency(totGeral)}</strong></td>
      `;
    }

    datas.forEach((d) => {
      const v = totaisPorData[d] || 0;
      html += `<td><strong>${v ? formatCurrency(v) : "-"}</strong></td>`;
    });

    trTotal.innerHTML = html;
    tbody.appendChild(trTotal);
  }
}

// ============ FATURAS (LISTA + RESUMO) ============

async function carregarFaturas() {
  try {
    const params = new URLSearchParams();

    if (filtroTransportadora) params.append("transportadora", filtroTransportadora);
    if (filtroNumeroFatura) params.append("numero_fatura", filtroNumeroFatura);

    // ✅ usa DE/ATÉ da sidebar também no /faturas
    const de = document.getElementById("filtroVencimentoDe")?.value || "";
    const ate = document.getElementById("filtroVencimentoAte")?.value || "";
    if (de) params.append("de_vencimento", de);
    if (ate) params.append("ate_vencimento", ate);

    const url =
      params.toString().length > 0
        ? `${API_BASE}/faturas?${params.toString()}`
        : `${API_BASE}/faturas`;

    const resp = await fetch(url);
    if (!resp.ok) throw new Error("Erro ao listar faturas");

    const faturas = await resp.json();
    ultimaListaFaturas = faturas;

    renderizarFaturas();
    carregarDashboard();
  } catch (err) {
    console.error(err);
    alert("Erro ao carregar faturas");
  }
}

function renderizarFaturas() {
  const tbody = document.getElementById("tbodyFaturas");
  if (!tbody) return;

  tbody.innerHTML = "";

  let lista = Array.isArray(ultimaListaFaturas) ? [...ultimaListaFaturas] : [];

  // Filtro período (apenas aba Faturas)
  if (filtroDataInicioFaturas || filtroDataFimFaturas) {
    lista = lista.filter((f) => {
      if (!f.data_vencimento) return false;
      const d = parseISODateLocal(f.data_vencimento);
      if (!d) return false;
      const time = d.setHours(0, 0, 0, 0);

      if (filtroDataInicioFaturas) {
        const dIni = parseISODateLocal(filtroDataInicioFaturas);
        if (!dIni) return false;
        const ini = dIni.setHours(0, 0, 0, 0);
        if (time < ini) return false;
      }

      if (filtroDataFimFaturas) {
        const dFim = parseISODateLocal(filtroDataFimFaturas);
        if (!dFim) return false;
        const fim = dFim.setHours(0, 0, 0, 0);
        if (time > fim) return false;
      }

      return true;
    });
  }

  // Filtro status (aba Faturas)
  if (filtroStatus) {
    const alvo = filtroStatus.toLowerCase();
    lista = lista.filter((f) => (f.status || "").toLowerCase() === alvo);
  }

  // RESUMO (cards da aba Faturas)
  let total = 0;
  let pendentes = 0;
  let atrasadas = 0;
  let pagas = 0;

  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const hojeTime = hoje.getTime();

  lista.forEach((f) => {
    const valor = Number(f.valor || 0);
    total += valor;

    const status = (f.status || "").toLowerCase();
    const d = parseISODateLocal(f.data_vencimento);
    const vencTime = d ? d.setHours(0, 0, 0, 0) : null;

    if (status === "pago") {
      pagas += valor;
    } else if (status === "pendente") {
      if (vencTime !== null && vencTime < hojeTime) atrasadas += valor;
      else pendentes += valor;
    } else if (status === "atrasado") {
      atrasadas += valor;
    }
  });

  const elTotal = document.getElementById("fatTotal");
  const elPend = document.getElementById("fatPendentes");
  const elAtr = document.getElementById("fatAtrasadas");
  const elPag = document.getElementById("fatPagas");
  if (elTotal) elTotal.textContent = formatCurrency(total);
  if (elPend) elPend.textContent = formatCurrency(pendentes);
  if (elAtr) elAtr.textContent = formatCurrency(atrasadas);
  if (elPag) elPag.textContent = formatCurrency(pagas);

  if (lista.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 9;
    td.textContent = "Nenhuma fatura encontrada.";
    td.style.textAlign = "center";
    td.style.padding = "12px";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  lista.forEach((f) => {
    const tr = document.createElement("tr");
    tr.dataset.faturaId = f.id;

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
        <button type="button" class="menu-btn" aria-label="Ações">⋮</button>
        <div class="menu-dropdown">
          <button type="button" data-acao="editar">Editar</button>
          <button type="button" data-acao="excluir">Excluir</button>
          <button type="button" data-acao="anexos">Anexos</button>
        </div>
      </td>
    `;

    tbody.appendChild(tr);
  });
}

// ============ MENU 3 PONTINHOS (DELEGAÇÃO) ============

function fecharTodosMenus() {
  document.querySelectorAll(".menu-dropdown.ativo").forEach((m) => {
    m.classList.remove("ativo");
    m.style.position = "";
    m.style.left = "";
    m.style.top = "";
    m.style.right = "";
    m.style.bottom = "";
    m.style.maxHeight = "";
    m.style.overflowY = "";
  });
}

function setupMenuDelegation() {
  const tbody = document.getElementById("tbodyFaturas");
  if (!tbody) return;

  tbody.addEventListener("click", async (e) => {
    const menuBtn = e.target.closest(".menu-btn");
    const acaoBtn = e.target.closest(".menu-dropdown button[data-acao]");

    if (menuBtn) {
      e.preventDefault();
      e.stopPropagation();

      const acoesCell = menuBtn.closest(".acoes");
      const dropdown = acoesCell ? acoesCell.querySelector(".menu-dropdown") : null;
      const jaAberto = dropdown && dropdown.classList.contains("ativo");

      fecharTodosMenus();
      if (!dropdown || jaAberto) return;

      dropdown.classList.add("ativo");

      const btnRect = menuBtn.getBoundingClientRect();

      dropdown.style.position = "fixed";
      dropdown.style.left = "0px";
      dropdown.style.top = "0px";

      const dropRect = dropdown.getBoundingClientRect();
      const dropH = dropRect.height || 180;

      const margem = 8;
      const spaceBelow = window.innerHeight - btnRect.bottom;
      const spaceAbove = btnRect.top;

      const left = Math.max(margem, btnRect.right - dropRect.width);
      dropdown.style.left = `${left}px`;

      if (spaceBelow >= dropH + margem) {
        dropdown.style.top = `${btnRect.bottom + margem}px`;
      } else if (spaceAbove >= dropH + margem) {
        dropdown.style.top = `${btnRect.top - dropH - margem}px`;
      } else {
        if (spaceBelow >= spaceAbove) {
          dropdown.style.top = `${btnRect.bottom + margem}px`;
          dropdown.style.maxHeight = `${Math.max(120, spaceBelow - 2 * margem)}px`;
        } else {
          dropdown.style.top = `${margem}px`;
          dropdown.style.maxHeight = `${Math.max(120, spaceAbove - 2 * margem)}px`;
        }
        dropdown.style.overflowY = "auto";
      }

      return;
    }

    if (acaoBtn) {
      e.preventDefault();
      e.stopPropagation();

      const acao = acaoBtn.dataset.acao;
      const tr = acaoBtn.closest("tr");
      const id = tr ? tr.dataset.faturaId : null;
      if (!id) return;

      const faturaObj = (ultimaListaFaturas || []).find(
        (f) => String(f.id) === String(id)
      );

      if (acao === "excluir") {
        await excluirFatura(id);
      } else if (acao === "editar") {
        if (faturaObj) preencherFormularioEdicao(faturaObj);
      } else if (acao === "anexos") {
        abrirModalAnexos(id);
      }

      fecharTodosMenus();
    }
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest(".menu-dropdown") || e.target.closest(".menu-btn")) return;
    fecharTodosMenus();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") fecharTodosMenus();
  });
}

// ============ EXCLUIR / EDITAR / ANEXOS ============

async function excluirFatura(id) {
  if (!confirm(`Excluir fatura ${id}?`)) return;

  try {
    const resp = await fetch(`${API_BASE}/faturas/${id}`, { method: "DELETE" });
    if (!resp.ok) throw new Error("Erro ao excluir");
    await carregarFaturas();
  } catch (err) {
    console.error(err);
    alert("Erro ao excluir fatura");
  }
}

function preencherFormularioEdicao(f) {
  ativarAba("cadastro");
  document.getElementById("inputTransportadora").value = f.transportadora;
  document.getElementById("inputNumeroFatura").value = f.numero_fatura;
  document.getElementById("inputValor").value = f.valor;
  document.getElementById("inputVencimento").value = f.data_vencimento;
  document.getElementById("inputStatus").value = f.status;
  document.getElementById("inputObservacao").value = f.observacao ?? "";
  document.getElementById("formFatura").dataset.editId = f.id;
}

// >>>>> MODAL ANEXOS (COM EXCLUIR) <<<<<
async function abrirModalAnexos(faturaId) {
  document.getElementById("modalFaturaId").textContent = faturaId;
  const lista = document.getElementById("listaAnexos");
  lista.innerHTML = "Carregando...";

  try {
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

        const btnExcluir = document.createElement("button");
        btnExcluir.type = "button";
        btnExcluir.className = "btn-excluir-anexo";
        btnExcluir.textContent = "Excluir";

        btnExcluir.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();

          if (!confirm(`Excluir o anexo "${a.original_name}"?`)) return;

          try {
            const respDel = await fetch(`${API_BASE}/anexos/${a.id}`, {
              method: "DELETE",
            });
            if (!respDel.ok) throw new Error("Erro ao excluir anexo");

            abrirModalAnexos(faturaId);
          } catch (err) {
            console.error(err);
            alert("Erro ao excluir anexo");
          }
        });

        li.appendChild(link);
        li.appendChild(btnExcluir);
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

    const inputAnexos = document.getElementById("inputAnexos");
    if (inputAnexos && inputAnexos.files && inputAnexos.files.length > 0) {
      const fd = new FormData();
      for (const file of inputAnexos.files) {
        fd.append("files", file);
      }

      const respAnexos = await fetch(`${API_BASE}/faturas/${fatura.id}/anexos`, {
        method: "POST",
        body: fd,
      });

      if (!respAnexos.ok) {
        let detalhe = "";
        try {
          const ct = respAnexos.headers.get("content-type") || "";
          if (ct.includes("application/json")) {
            const j = await respAnexos.json();
            detalhe = j?.detail ? String(j.detail) : JSON.stringify(j);
          } else {
            detalhe = await respAnexos.text();
          }
        } catch (_) {
          detalhe = "";
        }

        console.error("Erro ao enviar anexos:", respAnexos.status, detalhe);
        alert(
          `A fatura foi salva, mas o upload do anexo FALHOU.\n\nStatus: ${respAnexos.status}\n${detalhe || ""}`
        );
      } else {
        inputAnexos.value = "";
      }
    }

    form.reset();
    delete form.dataset.editId;

    await carregarFaturas();
    ativarAba("faturas");
  } catch (err) {
    console.error(err);
    alert("Erro ao salvar fatura");
  }
}

// ============ ABAS / NAVEGAÇÃO ============

function ativarAba(aba) {
  const dash = document.getElementById("dashboardSection");
  const cad = document.getElementById("cadastroSection");
  const fat = document.getElementById("faturasSection");
  const tabDash = document.getElementById("tabDashboard");
  const tabCad = document.getElementById("tabCadastro");
  const tabFat = document.getElementById("tabFaturas");

  [dash, cad, fat].forEach((s) => s.classList.remove("visible"));
  [tabDash, tabCad, tabFat].forEach((t) => t.classList.remove("active"));

  if (aba === "dashboard") {
    dash.classList.add("visible");
    tabDash.classList.add("active");
  } else if (aba === "cadastro") {
    cad.classList.add("visible");
    tabCad.classList.add("active");
  } else {
    fat.classList.add("visible");
    tabFat.classList.add("active");
  }
}

// ============ EXPORTAR EXCEL (CSV) ============

function exportarExcel() {
  const params = new URLSearchParams();
  if (filtroTransportadora) params.append("transportadora", filtroTransportadora);
  if (filtroNumeroFatura) params.append("numero_fatura", filtroNumeroFatura);

  const url =
    params.toString().length > 0
      ? `${API_BASE}/faturas/exportar?${params.toString()}`
      : `${API_BASE}/faturas/exportar`;

  window.open(url, "_blank");
}

// ============ INIT ============

document.addEventListener("DOMContentLoaded", () => {
  setupMenuDelegation();

  document.getElementById("tabDashboard").addEventListener("click", () => ativarAba("dashboard"));
  document.getElementById("tabCadastro").addEventListener("click", () => ativarAba("cadastro"));
  document.getElementById("tabFaturas").addEventListener("click", () => ativarAba("faturas"));

  // ✅ botões do dashboard
  const btnDashPendente = document.getElementById("btnDashPendente");
  const btnDashPago = document.getElementById("btnDashPago");

  if (btnDashPendente && btnDashPago) {
    btnDashPendente.addEventListener("click", () => {
      dashboardModo = "pendente";
      btnDashPendente.classList.add("active");
      btnDashPago.classList.remove("active");
      renderResumoDashboard(ultimaListaFaturas || []);
    });

    btnDashPago.addEventListener("click", () => {
      dashboardModo = "pago";
      btnDashPago.classList.add("active");
      btnDashPendente.classList.remove("active");
      renderResumoDashboard(ultimaListaFaturas || []);
    });
  }

  // Botão página inicial
  document.getElementById("btnHome").addEventListener("click", () => {
    filtroTransportadora = "";
    filtroNumeroFatura = "";
    filtroDataInicioFaturas = "";
    filtroDataFimFaturas = "";
    filtroStatus = "";

    const de = document.getElementById("filtroVencimentoDe");
    const ate = document.getElementById("filtroVencimentoAte");
    if (de) de.value = "";
    if (ate) ate.value = "";

    const buscaNumero = document.getElementById("buscaNumero");
    if (buscaNumero) buscaNumero.value = "";

    const ini = document.getElementById("filtroDataInicioFaturas");
    const fim = document.getElementById("filtroDataFimFaturas");
    if (ini) ini.value = "";
    if (fim) fim.value = "";

    const statusSelect = document.getElementById("filtroStatus");
    if (statusSelect) statusSelect.value = "";

    document.querySelectorAll(".transportadora-btn").forEach((b) => b.classList.remove("selected"));

    ativarAba("dashboard");
    carregarFaturas();
  });

  // Transportadoras sidebar
  document.querySelectorAll(".transportadora-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      filtroTransportadora = btn.dataset.transportadora || "";
      document.querySelectorAll(".transportadora-btn").forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
      carregarFaturas();
    })
  );

  // ✅ filtro vencimento sidebar (DE/ATÉ)
  const filtroDe = document.getElementById("filtroVencimentoDe");
  const filtroAte = document.getElementById("filtroVencimentoAte");

  if (filtroDe) filtroDe.addEventListener("change", carregarFaturas);
  if (filtroAte) filtroAte.addEventListener("change", carregarFaturas);

  // Limpar filtros (sidebar)
  const btnLimparFiltros = document.getElementById("btnLimparFiltros");
  if (btnLimparFiltros) {
    btnLimparFiltros.addEventListener("click", () => {
      filtroNumeroFatura = "";
      filtroDataInicioFaturas = "";
      filtroDataFimFaturas = "";
      filtroStatus = "";

      if (filtroDe) filtroDe.value = "";
      if (filtroAte) filtroAte.value = "";

      const buscaNumero = document.getElementById("buscaNumero");
      if (buscaNumero) buscaNumero.value = "";

      const ini = document.getElementById("filtroDataInicioFaturas");
      const fim = document.getElementById("filtroDataFimFaturas");
      if (ini) ini.value = "";
      if (fim) fim.value = "";

      const statusSelect = document.getElementById("filtroStatus");
      if (statusSelect) statusSelect.value = "";

      carregarFaturas();
    });
  }

  // Limpar filtro do período (aba Faturas)
  const btnLimparPeriodoFaturas = document.getElementById("btnLimparPeriodoFaturas");
  if (btnLimparPeriodoFaturas) {
    btnLimparPeriodoFaturas.addEventListener("click", () => {
      filtroDataInicioFaturas = "";
      filtroDataFimFaturas = "";

      const ini = document.getElementById("filtroDataInicioFaturas");
      const fim = document.getElementById("filtroDataFimFaturas");
      if (ini) ini.value = "";
      if (fim) fim.value = "";

      renderizarFaturas();
    });
  }

  // Busca nº fatura (pesquisa)
  const buscaNumero = document.getElementById("buscaNumero");
  if (buscaNumero) {
    buscaNumero.addEventListener("input", (e) => {
      filtroNumeroFatura = e.target.value.trim();
      carregarFaturas();
    });
  }

  // Filtro por período da aba Faturas
  const ini = document.getElementById("filtroDataInicioFaturas");
  const fim = document.getElementById("filtroDataFimFaturas");
  if (ini) {
    ini.addEventListener("change", (e) => {
      filtroDataInicioFaturas = e.target.value;
      renderizarFaturas();
    });
  }
  if (fim) {
    fim.addEventListener("change", (e) => {
      filtroDataFimFaturas = e.target.value;
      renderizarFaturas();
    });
  }

  // Filtro por STATUS (aba faturas)
  const statusSelect = document.getElementById("filtroStatus");
  if (statusSelect) {
    statusSelect.addEventListener("change", (e) => {
      filtroStatus = e.target.value;
      renderizarFaturas();
    });
  }

  // Atualizar lista manualmente
  const btnAtualizar = document.getElementById("btnAtualizarFaturas");
  if (btnAtualizar) {
    btnAtualizar.addEventListener("click", (e) => {
      e.preventDefault();
      carregarFaturas();
    });
  }

  // Exportar Excel
  const btnExportar = document.getElementById("btnExportarExcel");
  if (btnExportar) btnExportar.addEventListener("click", exportarExcel);

  // Formulário
  document.getElementById("formFatura").addEventListener("submit", salvarFatura);

  // Modal anexos
  document.getElementById("modalFechar").addEventListener("click", () =>
    document.getElementById("modalAnexos").classList.remove("open")
  );
  document.getElementById("modalAnexos").addEventListener("click", (e) => {
    if (e.target.id === "modalAnexos") {
      document.getElementById("modalAnexos").classList.remove("open");
    }
  });

  carregarFaturas();
});
