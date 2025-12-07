from datetime import date
import os

from fastapi import FastAPI, HTTPException, Depends
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
    status: str = "pendente"  # pendente, pago, em análise, etc.


class FaturaCreate(FaturaBase):
    pass


class FaturaUpdate(FaturaBase):
    """
    Usado no PUT para atualizar todos os campos da fatura.
    (Poderia ser parcial, mas aqui vamos exigir todos os dados.)
    """
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
# ROTAS DE FATURAS
# =========================

# CREATE
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


# READ - LISTAR TODAS
@app.get("/faturas", response_model=list[FaturaOut])
def listar_faturas(db: Session = Depends(get_db)):
    faturas = db.query(FaturaDB).order_by(FaturaDB.id).all()
    return faturas


# READ - OBTER POR ID
@app.get("/faturas/{fatura_id}", response_model=FaturaOut)
def obter_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return fatura


# UPDATE COMPLETO (PUT)
@app.put("/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(
    fatura_id: int,
    fatura_update: FaturaUpdate,
    db: Session = Depends(get_db),
):
    fatura_db = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura_db:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    fatura_db.transportadora = fatura_update.transportadora
    fatura_db.numero_fatura = fatura_update.numero_fatura
    fatura_db.valor = fatura_update.valor
    fatura_db.data_vencimento = fatura_update.data_vencimento
    fatura_db.status = fatura_update.status

    db.commit()
    db.refresh(fatura_db)
    return fatura_db


# DELETE
@app.delete("/faturas/{fatura_id}")
def deletar_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura_db = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura_db:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    db.delete(fatura_db)
    db.commit()
    return {"mensagem": f"Fatura {fatura_id} deletada com sucesso."}


# PATCH - ATUALIZAR APENAS STATUS
@app.patch("/faturas/{fatura_id}/status", response_model=FaturaOut)
def atualizar_status_fatura(
    fatura_id: int,
    status_update: FaturaStatusUpdate,
    db: Session = Depends(get_db),
):
    fatura_db = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura_db:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    fatura_db.status = status_update.status
    db.commit()
    db.refresh(fatura_db)
    return fatura_db


# GET - FATURAS ATRASADAS
@app.get("/faturas/atrasadas", response_model=list[FaturaOut])
def listar_faturas_atrasadas(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = (
        db.query(FaturaDB)
        .filter(FaturaDB.data_vencimento < hoje)
        .filter(FaturaDB.status != "pago")
        .order_by(FaturaDB.data_vencimento)
        .all()
    )
    return faturas
