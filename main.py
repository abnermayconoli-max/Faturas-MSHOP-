from datetime import date
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
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
    version="0.3.0",
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Servir arquivos estáticos (index.html, css, js se tiver)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# =========================
# ROTAS BÁSICAS
# =========================

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home():
    """
    Se existir o static/index.html, mostra a tela visual.
    Senão, mostra só uma mensagem simples.
    """
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return "<h1>Sistema de Faturas - API</h1><p>Crie o arquivo static/index.html.</p>"


# =========================
# ROTAS DE FATURAS - CRUD
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
def atualizar_fatura(fatura_id: int, dados: FaturaUpdate, db: Session = Depends(get_db)):
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


@app.delete("/faturas/{fatura_id}")
def deletar_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    db.delete(fatura)
    db.commit()
    return {"ok": True}


@app.patch("/faturas/{fatura_id}/status", response_model=FaturaOut)
def atualizar_status_fatura(
    fatura_id: int,
    body: FaturaStatusUpdate,
    db: Session = Depends(get_db),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    fatura.status = body.status
    db.commit()
    db.refresh(fatura)
    return fatura


@app.get("/faturas/atrasadas", response_model=list[FaturaOut])
def listar_faturas_atrasadas(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = (
        db.query(FaturaDB)
        .filter(
            FaturaDB.data_vencimento < hoje,
            FaturaDB.status != "pago",
        )
        .order_by(FaturaDB.data_vencimento)
        .all()
    )
    return faturas
