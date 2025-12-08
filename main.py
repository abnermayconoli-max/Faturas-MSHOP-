from datetime import date, datetime
import os

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Date,
    Numeric,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# =========================
# CONFIG BANCO DE DADOS
# =========================

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # Isso ajuda a ver erro nos logs do Render se a variável não estiver setada
    raise RuntimeError("DATABASE_URL não configurada nas variáveis de ambiente do Render.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# =========================
# MODELO SQLALCHEMY (TABELA)
# =========================

class FaturaDB(Base):
    __tablename__ = "faturas"

    id = Column(Integer, primary_key=True, index=True)
    transportadora = Column(String, index=True)
    numero_fatura = Column(String, index=True)
    valor = Column(Numeric(10, 2))
    data_vencimento = Column(Date)
    status = Column(String, default="pendente")


# Cria a tabela se ainda não existir
Base.metadata.create_all(bind=engine)

# =========================
# MODELOS Pydantic (entrada/saída)
# =========================

class FaturaBase(BaseModel):
    transportadora: str
    numero_fatura: str
    valor: float
    data_vencimento: date
    status: str = "pendente"


class FaturaCreate(FaturaBase):
    pass


class FaturaUpdate(FaturaBase):
    pass


class FaturaStatusUpdate(BaseModel):
    status: str


class FaturaOut(FaturaBase):
    id: int

    class Config:
        orm_mode = True


# =========================
# DEPENDÊNCIA DO BANCO
# =========================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================
# APP FASTAPI
# =========================

app = FastAPI(
    title="Sistema de Faturas Transportadoras",
    version="0.2.0",
)

# CORS (caso queira acessar de outro lugar depois)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# ROTAS BÁSICAS
# =========================

@app.get("/")
def read_root():
    return {"mensagem": "API de Faturas com banco PostgreSQL no Render!"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


# =========================
# ROTAS DE FATURAS (CRUD)
# =========================

@app.post("/faturas", response_model=FaturaOut)
def criar_fatura(fatura: FaturaCreate, db: Session = Depends(get_db)):
    db_fatura = FaturaDB(
        transportadora=fatura.transportadora,
        numero_fatura=fatura.numero_fatura,
        valor=fatura.valor,
        data_vencimento=fatura.data_vencimento,
        status=fatura.status,
    )
    db.add(db_fatura)
    db.commit()
    db.refresh(db_fatura)
    return db_fatura


@app.get("/faturas", response_model=list[FaturaOut])
def listar_faturas(db: Session = Depends(get_db)):
    faturas = db.query(FaturaDB).order_by(FaturaDB.id).all()
    return faturas


@app.get("/faturas/{fatura_id}", response_model=FaturaOut)
def obter_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return fatura


@app.put("/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(fatura_id: int, fatura: FaturaUpdate, db: Session = Depends(get_db)):
    db_fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not db_fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    db_fatura.transportadora = fatura.transportadora
    db_fatura.numero_fatura = fatura.numero_fatura
    db_fatura.valor = fatura.valor
    db_fatura.data_vencimento = fatura.data_vencimento
    db_fatura.status = fatura.status

    db.commit()
    db.refresh(db_fatura)
    return db_fatura


@app.patch("/faturas/{fatura_id}/status", response_model=FaturaOut)
def atualizar_status_fatura(
    fatura_id: int,
    payload: FaturaStatusUpdate,
    db: Session = Depends(get_db),
):
    db_fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not db_fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    db_fatura.status = payload.status
    db.commit()
    db.refresh(db_fatura)
    return db_fatura


@app.delete("/faturas/{fatura_id}", status_code=204)
def deletar_fatura(fatura_id: int, db: Session = Depends(get_db)):
    db_fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not db_fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    db.delete(db_fatura)
    db.commit()
    return


@app.get("/faturas/atrasadas", response_model=list[FaturaOut])
def listar_faturas_atrasadas(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = (
        db.query(FaturaDB)
        .filter(FaturaDB.data_vencimento < hoje)
        .filter(FaturaDB.status != "paga")
        .order_by(FaturaDB.data_vencimento)
        .all()
    )
    return faturas


# =========================
# HTML DA APLICAÇÃO (TELA VISUAL)
# =========================

HTML_PAGE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Faturas MSHOP</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <!-- Bootstrap somente para reset básico, mas o visual principal é nosso -->
    <link
      href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
      rel="stylesheet"
      integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"
      crossorigin="anonymous"
    >

    <!-- SheetJS para exportar Excel -->
    <script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>

    <style>
        :root {
            --verde-main: #21a86a;   /* verde médio */
            --verde-escuro: #158652;
            --verde-claro: #e8f7f0;
            --cinza-fundo: #f3f4f6;
        }

        body {
            background-color: var(--cinza-fundo);
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        .topbar {
            background-color: var(--verde-main);
            color: white;
            padding: 16px 32px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        }

        .topbar h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 700;
        }

        .topbar .menu a {
            color: white;
            margin-left: 16px;
            text-decoration: none;
            font-weight: 500;
            padding: 6px 14px;
            border-radius: 999px;
        }

        .topbar .menu a.active,
        .topbar .menu a:hover {
            background-color: var(--verde-escuro);
        }

        .content {
            max-width: 1200px;
            margin: 32px auto;
            padding: 0 16px 48px;
        }

        .card-soft {
            background-color: white;
            border-radius: 18px;
            padding: 20px 22px;
            box-shadow: 0 3px 10px rgba(0,0,0,0.05);
            margin-bottom: 20px;
        }

        .card-soft h2 {
            font-size: 22px;
            font-weight: 600;
            margin-bottom: 12px;
        }

        .tag {
            display: inline-flex;
            align-items: center;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 500;
            background-color: var(--verde-claro);
            color: var(--verde-escuro);
        }

        .btn-pill {
            border-radius: 999px !important;
            padding: 8px 18px;
            font-weight: 500;
            border: none;
        }

        .btn-verde {
            background-color: var(--verde-main);
            color: white;
        }

        .btn-verde:hover {
            background-color: var(--verde-escuro);
            color: white;
        }

        .btn-outline-verde {
            border: 1px solid var(--verde-main);
            color: var(--verde-main);
            background-color: white;
        }

        .btn-outline-verde:hover {
            background-color: var(--verde-main);
            color: white;
        }

        .badge-status {
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 12px;
            font-weight: 600;
        }

        .badge-pendente {
            background-color: #fff4d6;
            color: #c78a07;
        }

        .badge-atrasada {
            background-color: #ffe1e1;
            color: #c0392b;
        }

        .badge-em-dia {
            background-color: #e6f7ff;
            color: #2980b9;
        }

        table thead {
            background-color: var(--verde-claro);
        }

        table thead th {
            border-bottom: none;
            font-size: 14px;
        }

        table tbody td {
            font-size: 14px;
            vertical-align: middle;
        }

        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 16px;
        }

        .dashboard-card {
            background-color: #f7fcfa;
            border-radius: 16px;
            padding: 16px 18px;
            border: 1px solid #dbf1e5;
        }

        .dashboard-card .label {
            font-size: 13px;
            color: #6b7280;
            margin-bottom: 4px;
        }

        .dashboard-card .valor {
            font-size: 20px;
            font-weight: 600;
        }

        .dashboard-card .quantidade {
            font-size: 13px;
            color: #6b7280;
        }

        @media (max-width: 992px) {
            .dashboard-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 640px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
            }
            .topbar {
                flex-direction: column;
                align-items: flex-start;
                gap: 8px;
            }
        }
    </style>
</head>
<body>
    <header class="topbar">
        <h1>Faturas MSHOP</h1>
        <nav class="menu">
            <a href="#" id="tab-faturas" class="active" onclick="mostrarSecao('faturas'); return false;">Faturas</a>
            <a href="#" id="tab-cadastro" onclick="mostrarSecao('cadastro'); return false;">Cadastro</a>
            <a href="#" id="tab-dashboard" onclick="mostrarSecao('dashboard'); return false;">Dashboard</a>
        </nav>
    </header>

    <main class="content">

        <!-- SEÇÃO LISTA DE FATURAS -->
        <section id="secao-faturas" class="card-soft">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <h2>Lista de Faturas</h2>
                <span class="tag">Visualizar e filtrar por transportadora</span>
            </div>

            <div class="row g-2 align-items-end mb-3">
                <div class="col-sm-4">
                    <label for="filtro-transportadora" class="form-label mb-1">Transportadora</label>
                    <input type="text" id="filtro-transportadora" class="form-control form-control-sm" placeholder="Ex: DHL">
                </div>
                <div class="col-sm-8 d-flex flex-wrap gap-2">
                    <button class="btn btn-verde btn-pill" onclick="aplicarFiltro()">Aplicar filtro</button>
                    <button class="btn btn-outline-verde btn-pill" onclick="limparFiltro()">Limpar</button>
                    <button class="btn btn-outline-verde btn-pill" onclick="exportarExcelFiltro()">Exportar Excel (filtro)</button>
                    <button class="btn btn-outline-verde btn-pill" onclick="exportarExcelTodas()">Exportar Excel (todas)</button>
                </div>
            </div>

            <div class="table-responsive">
                <table class="table table-sm align-middle" id="tabela-faturas">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Transportadora</th>
                            <th>Nº Fatura</th>
                            <th>Valor</th>
                            <th>Vencimento</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody id="tbody-faturas">
                        <!-- linhas preenchidas via JS -->
                    </tbody>
                </table>
            </div>
        </section>

        <!-- SEÇÃO CADASTRO -->
        <section id="secao-cadastro" class="card-soft" style="display:none;">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <h2>Cadastro de Fatura</h2>
                <span class="tag">Inserir nova fatura no sistema</span>
            </div>

            <form onsubmit="salvarFatura(event)">
                <div class="row g-3 mb-3">
                    <div class="col-md-4">
                        <label class="form-label mb-1">Transportadora</label>
                        <input type="text" id="cad-transportadora" class="form-control" required>
                    </div>
                    <div class="col-md-4">
                        <label class="form-label mb-1">Número da Fatura</label>
                        <input type="text" id="cad-numero" class="form-control" required>
                    </div>
                    <div class="col-md-4">
                        <label class="form-label mb-1">Valor</label>
                        <input type="number" step="0.01" id="cad-valor" class="form-control" required>
                    </div>
                </div>

                <div class="row g-3 mb-3">
                    <div class="col-md-4">
                        <label class="form-label mb-1">Data de Vencimento</label>
                        <input type="date" id="cad-vencimento" class="form-control" required>
                    </div>
                    <div class="col-md-4">
                        <label class="form-label mb-1">Status</label>
                        <select id="cad-status" class="form-select">
                            <option value="pendente">Pendente</option>
                            <option value="paga">Paga</option>
                            <option value="atrasada">Atrasada</option>
                            <option value="em dia">Em dia</option>
                        </select>
                    </div>
                </div>

                <button class="btn btn-verde btn-pill" type="submit">Salvar Fatura</button>
            </form>
        </section>

        <!-- SEÇÃO DASHBOARD -->
        <section id="secao-dashboard" class="card-soft" style="display:none;">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <h2>Dashboard</h2>
                <span class="tag">Resumo das faturas por status</span>
            </div>

            <div class="dashboard-grid mb-3">
                <div class="dashboard-card">
                    <div class="label">Valor total</div>
                    <div class="valor" id="dash-total-valor">R$ 0,00</div>
                    <div class="quantidade" id="dash-total-qtd">0 faturas</div>
                </div>

                <div class="dashboard-card">
                    <div class="label">Pendentes</div>
                    <div class="valor" id="dash-pendentes-valor">R$ 0,00</div>
                    <div class="quantidade" id="dash-pendentes-qtd">0 faturas</div>
                </div>

                <div class="dashboard-card">
                    <div class="label">Atrasadas</div>
                    <div class="valor" id="dash-atrasadas-valor">R$ 0,00</div>
                    <div class="quantidade" id="dash-atrasadas-qtd">0 faturas</div>
                </div>

                <div class="dashboard-card">
                    <div class="label">Em dia</div>
                    <div class="valor" id="dash-em-dia-valor">R$ 0,00</div>
                    <div class="quantidade" id="dash-em-dia-qtd">0 faturas</div>
                </div>
            </div>

            <div class="d-flex flex-wrap gap-2">
                <button class="btn btn-verde btn-pill" onclick="atualizarDashboard()">Atualizar Dashboard</button>
                <button class="btn btn-outline-verde btn-pill" onclick="exportarExcelTodas()">Exportar Excel (todas as faturas)</button>
            </div>
        </section>
    </main>

    <script>
        // Cache das faturas carregadas da API
        let faturasCache = [];

        function formatarValor(valor) {
            if (valor === null || valor === undefined) return "R$ 0,00";
            const numero = Number(valor);
            if (isNaN(numero)) return "R$ 0,00";
            return numero.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
        }

        function formatarData(iso) {
            if (!iso) return "";
            const d = new Date(iso);
            if (isNaN(d.getTime())) return iso;
            return d.toLocaleDateString("pt-BR");
        }

        function badgeStatus(status) {
            if (!status) return "";
            const s = status.toLowerCase();
            if (s === "pendente") {
                return '<span class="badge-status badge-pendente">Pendente</span>';
            } else if (s === "atrasada") {
                return '<span class="badge-status badge-atrasada">Atrasada</span>';
            } else if (s === "em dia") {
                return '<span class="badge-status badge-em-dia">Em dia</span>';
            } else if (s === "paga") {
                return '<span class="badge-status badge-em-dia">Paga</span>';
            }
            return '<span class="badge-status badge-pendente">' + status + '</span>';
        }

        async function carregarFaturas() {
            const resp = await fetch("/faturas");
            if (!resp.ok) {
                alert("Erro ao carregar faturas");
                return;
            }
            faturasCache = await resp.json();
            renderizarTabela(faturasCache);
        }

        function renderizarTabela(lista) {
            const tbody = document.getElementById("tbody-faturas");
            tbody.innerHTML = "";

            for (const f of lista) {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td>${f.id}</td>
                    <td>${f.transportadora}</td>
                    <td>${f.numero_fatura}</td>
                    <td>${formatarValor(f.valor)}</td>
                    <td>${formatarData(f.data_vencimento)}</td>
                    <td>${badgeStatus(f.status)}</td>
                `;
                tbody.appendChild(tr);
            }
        }

        function aplicarFiltro() {
            const filtro = document.getElementById("filtro-transportadora").value.trim().toLowerCase();
            if (!filtro) {
                renderizarTabela(faturasCache);
                return;
            }
            const filtradas = faturasCache.filter(f =>
                f.transportadora && f.transportadora.toLowerCase().includes(filtro)
            );
            renderizarTabela(filtradas);
        }

        function limparFiltro() {
            document.getElementById("filtro-transportadora").value = "";
            renderizarTabela(faturasCache);
        }

        async function salvarFatura(event) {
            event.preventDefault();

            const payload = {
                transportadora: document.getElementById("cad-transportadora").value,
                numero_fatura: document.getElementById("cad-numero").value,
                valor: parseFloat(document.getElementById("cad-valor").value),
                data_vencimento: document.getElementById("cad-vencimento").value,
                status: document.getElementById("cad-status").value
            };

            const resp = await fetch("/faturas", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!resp.ok) {
                alert("Erro ao salvar fatura");
                return;
            }

            // limpa formulário
            document.getElementById("cad-transportadora").value = "";
            document.getElementById("cad-numero").value = "";
            document.getElementById("cad-valor").value = "";
            document.getElementById("cad-vencimento").value = "";
            document.getElementById("cad-status").value = "pendente";

            await carregarFaturas();
            atualizarDashboard();
            alert("Fatura salva com sucesso!");
        }

        function atualizarDashboard() {
            const hoje = new Date();
            let totalValor = 0;
            let totalQtd = 0;

            let pendentesValor = 0;
            let pendentesQtd = 0;

            let atrasadasValor = 0;
            let atrasadasQtd = 0;

            let emDiaValor = 0;
            let emDiaQtd = 0;

            for (const f of faturasCache) {
                const valor = Number(f.valor) || 0;
                totalValor += valor;
                totalQtd++;

                const status = (f.status || "").toLowerCase();
                const venc = new Date(f.data_vencimento);

                if (status === "pendente") {
                    pendentesValor += valor;
                    pendentesQtd++;
                }

                if (!isNaN(venc.getTime())) {
                    if (venc < hoje && status !== "paga") {
                        atrasadasValor += valor;
                        atrasadasQtd++;
                    } else if (venc >= hoje && status !== "paga") {
                        emDiaValor += valor;
                        emDiaQtd++;
                    }
                }
            }

            document.getElementById("dash-total-valor").innerText = formatarValor(totalValor);
            document.getElementById("dash-total-qtd").innerText = totalQtd + " faturas";

            document.getElementById("dash-pendentes-valor").innerText = formatarValor(pendentesValor);
            document.getElementById("dash-pendentes-qtd").innerText = pendentesQtd + " faturas";

            document.getElementById("dash-atrasadas-valor").innerText = formatarValor(atrasadasValor);
            document.getElementById("dash-atrasadas-qtd").innerText = atrasadasQtd + " faturas";

            document.getElementById("dash-em-dia-valor").innerText = formatarValor(emDiaValor);
            document.getElementById("dash-em-dia-qtd").innerText = emDiaQtd + " faturas";
        }

        function exportarExcelFiltro() {
            if (typeof XLSX === "undefined") {
                alert("Biblioteca de Excel não carregada.");
                return;
            }
            const table = document.getElementById("tabela-faturas");
            const wb = XLSX.utils.table_to_book(table, { sheet: "Faturas (filtro)" });
            XLSX.writeFile(wb, "faturas_filtro.xlsx");
        }

        function exportarExcelTodas() {
            if (typeof XLSX === "undefined") {
                alert("Biblioteca de Excel não carregada.");
                return;
            }
            const dados = faturasCache.map(f => ({
                ID: f.id,
                Transportadora: f.transportadora,
                "Nº Fatura": f.numero_fatura,
                Valor: Number(f.valor) || 0,
                Vencimento: f.data_vencimento,
                Status: f.status
            }));
            const ws = XLSX.utils.json_to_sheet(dados);
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, "Faturas");
            XLSX.writeFile(wb, "faturas_todas.xlsx");
        }

        function mostrarSecao(secao) {
            document.getElementById("secao-faturas").style.display = (secao === "faturas") ? "block" : "none";
            document.getElementById("secao-cadastro").style.display = (secao === "cadastro") ? "block" : "none";
            document.getElementById("secao-dashboard").style.display = (secao === "dashboard") ? "block" : "none";

            document.getElementById("tab-faturas").classList.toggle("active", secao === "faturas");
            document.getElementById("tab-cadastro").classList.toggle("active", secao === "cadastro");
            document.getElementById("tab-dashboard").classList.toggle("active", secao === "dashboard");
        }

        // Ao carregar a página
        window.addEventListener("DOMContentLoaded", async () => {
            await carregarFaturas();
            atualizarDashboard();
        });
    </script>
</body>
</html>
"""

# ROTA PARA SERVIR A TELA
@app.get("/app", response_class=HTMLResponse)
def tela_faturas():
    return HTML_PAGE
