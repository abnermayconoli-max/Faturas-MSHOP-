from datetime import date
from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(
    title="Sistema de Faturas Transportadoras",
    version="0.1.0",
)


# ===== MODELO (Pydantic) =====
class Fatura(BaseModel):
    id: int
    transportadora: str
    numero_fatura: str
    valor: float
    data_vencimento: date
    status: str  # pendente, atrasada, paga, etc.


# ===== DADOS DE EXEMPLO (por enquanto só mock, sem banco) =====
faturas_mock = [
    Fatura(
        id=1,
        transportadora="DHL",
        numero_fatura="DHL-2025-001",
        valor=1520.75,
        data_vencimento=date(2025, 12, 20),
        status="pendente",
    ),
    Fatura(
        id=2,
        transportadora="Transbritto",
        numero_fatura="TB-98765",
        valor=980.40,
        data_vencimento=date(2025, 12, 10),
        status="atrasada",
    ),
    Fatura(
        id=3,
        transportadora="Garcia",
        numero_fatura="GC-12345",
        valor=2500.00,
        data_vencimento=date(2025, 12, 25),
        status="programada",
    ),
]


# ===== ROTAS =====
@app.get("/")
def read_root():
    return {"mensagem": "API de Faturas no ar a partir do Render!"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/faturas", response_model=list[Fatura])
def listar_faturas():
    """
    Lista todas as faturas de exemplo (depois vamos trocar para banco de dados).
    """
    return faturas_mock

