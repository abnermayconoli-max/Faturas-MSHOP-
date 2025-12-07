from datetime import date
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="Sistema de Faturas Transportadoras",
    version="0.2.0",
)

# ==== MODELOS (Pydantic) ====

class FaturaBase(BaseModel):
    transportadora: str
    valor: float
    data_vencimento: date
    status: str = "pendente"  # pendente, paga, atrasada etc.


class Fatura(FaturaBase):
    id: int


# ==== "BANCO" EM MEMÓRIA TEMPORÁRIO ====

_faturas_db: List[Fatura] = []
_proximo_id: int = 1


# ==== ROTAS PRINCIPAIS ====

@app.get("/")
def read_root():
    return {"mensagem": "API de Faturas no ar a partir do Render!"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/faturas", response_model=List[Fatura])
def listar_faturas():
    """Lista todas as faturas (por enquanto só em memória)."""
    return _faturas_db


@app.post("/faturas", response_model=Fatura)
def criar_fatura(fatura: FaturaBase):
    """Cria uma nova fatura (ainda sem banco de dados real)."""
    global _proximo_id

    nova_fatura = Fatura(id=_proximo_id, **fatura.dict())
    _proximo_id += 1
    _faturas_db.append(nova_fatura)
    return nova_fatura
