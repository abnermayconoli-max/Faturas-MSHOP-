from datetime import date
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Sistema de Faturas Transportadoras",
    version="0.1.0",
)

# ===== MODELOS (Pydantic) =====

class FaturaBase(BaseModel):
    transportadora: str
    numero_fatura: str
    valor: float
    data_vencimento: date
    status: str = "pendente"  # pendente, paga, atrasada etc.


class Fatura(FaturaBase):
    id: int


# "Banco de dados" em memória (por enquanto)
FATURAS_DB: List[Fatura] = []


# ===== ENDPOINTS BÁSICOS =====

@app.get("/")
def read_root():
    return {"mensagem": "API de Faturas no ar a partir do Render!"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


# ---- Criar fatura ----
@app.post("/faturas", response_model=Fatura)
def criar_fatura(dados: FaturaBase):
    novo_id = len(FATURAS_DB) + 1
    nova_fatura = Fatura(id=novo_id, **dados.dict())
    FATURAS_DB.append(nova_fatura)
    return nova_fatura


# ---- Listar faturas ----
@app.get("/faturas", response_model=List[Fatura])
def listar_faturas(status: Optional[str] = None):
    """
    Lista todas as faturas.
    Se passar ?status=pendente, filtra só por esse status.
    """
    if status:
        return [f for f in FATURAS_DB if f.status == status]
    return FATURAS_DB


# ---- Buscar fatura por ID (opcional mas útil) ----
@app.get("/faturas/{fatura_id}", response_model=Fatura)
def obter_fatura(fatura_id: int):
    for f in FATURAS_DB:
        if f.id == fatura_id:
            return f
    raise HTTPException(status_code=404, detail="Fatura não encontrada")
