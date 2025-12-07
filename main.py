from datetime import date
import os

from fastapi import FastAPI, HTTPException, Depends, Query
from pydantic import BaseModel, Field
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
    transportadora: str = Field(..., description="Nome da transportadora")
    numero_fatura: str = Field(..., description="Número da fatura (ex: NF, boleto, etc)")
    valor: float = Field(..., gt=0, description="Valor da fatura")
    data_vencimento: date = Field(..., description="Data de vencimento da fatura")
    status: str = Field(
        "pendente",
        description="Status da fatura (ex: pendente, pago, atrasado, cancelado)"
    )


class FaturaCreate(FaturaBase):
    pass


class FaturaUpdate(BaseModel):
    """
    Atualização completa (PUT) – todos os campos obrigatórios.
    """
    transportadora: str
    numero_fatura: str
    valor: float
    data_vencimento: date
    status: str


class FaturaStatusUpdate(BaseModel):
    """
    Atualização parcial só do status (PATCH).
    """
    status: str = Field(..., description="Novo status da fatura")


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
    version="0.3.0",
)


@app.get("/")
def read_root():
    return {"mensagem": "API de Faturas com banco PostgreSQL no Render!"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


# =========================
# ROTAS DE FATURAS
# =========================

@app.post("/faturas", response_model=FaturaOut)
def criar_fatura(fatura: FaturaCreate, db: Session = Depends(get_db)):
    # (Opcional) Verificar se já existe fatura com mesmo número + transportadora
    existente = (
        db.query(FaturaDB)
        .filter(
            FaturaDB.numero_fatura == fatura.numero_fatura,
            FaturaDB.transportadora == fatura.transportadora,
        )
        .first()
    )
    if existente:
        raise HTTPException(
            status_code=400,
            detail="Já existe uma fatura com esse número para essa transportadora.",
        )

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
def listar_faturas(
    status: str | None = Query(None, description="Filtrar por status"),
    transportadora: str | None = Query(None, description="Filtrar por transportadora"),
    vencimento_ate: date | None = Query(
        None,
        description="Listar faturas com vencimento até essa data (inclusive)",
    ),
    db: Session = Depends(get_db),
):
    """
    Lista faturas com filtros opcionais:
    - status (pendente, pago, atrasado, etc)
    - transportadora
    - vencimento_ate (data)
    """
    query = db.query(FaturaDB)

    if status:
        query = query.filter(FaturaDB.status == status)

    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

    if vencimento_ate:
        query = query.filter(FaturaDB.data_vencimento <= vencimento_ate)

    faturas = query.order_by(FaturaDB.data_vencimento, FaturaDB.id).all()
    return faturas


@app.get("/faturas/{fatura_id}", response_model=FaturaOut)
def obter_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return fatura


@app.put("/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(
    fatura_id: int,
    dados: FaturaUpdate,
    db: Session = Depends(get_db),
):
    """
    Atualização completa de uma fatura (substitui todos os campos).
    """
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    fatura.transportadora = dados.transportadora
    fatura.numero_fatura = dados.numero_fatura
    fatura.valor = dados.valor
    fatura.data_vencimento = dados.data_vencimento
    fatura.status = dados.status

    db.commit()
    db.refresh(fatura)
    return fatura


@app.patch("/faturas/{fatura_id}/status", response_model=FaturaOut)
def atualizar_status_fatura(
    fatura_id: int,
    dados: FaturaStatusUpdate,
    db: Session = Depends(get_db),
):
    """
    Atualiza apenas o status da fatura (ex: pendente -> pago).
    """
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    fatura.status = dados.status
    db.commit()
    db.refresh(fatura)
    return fatura


@app.delete("/faturas/{fatura_id}", status_code=204)
def deletar_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    db.delete(fatura)
    db.commit()
    # 204 -> sem conteúdo no body
    return


@app.get("/faturas/atrasadas", response_model=list[FaturaOut])
def listar_faturas_atrasadas(
    data_referencia: date | None = Query(
        None,
        description="Data de referência para considerar atraso (default = hoje)",
    ),
    db: Session = Depends(get_db),
):
    """
    Lista faturas vencidas (data_vencimento < data_referencia)
    e que NÃO estão com status 'pago'.
    """
    if data_referencia is None:
        data_referencia = date.today()

    faturas = (
        db.query(FaturaDB)
        .filter(
            FaturaDB.data_vencimento < data_referencia,
            FaturaDB.status != "pago",
        )
        .order_by(FaturaDB.data_vencimento, FaturaDB.id)
        .all()
    )
    return faturas
