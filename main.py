from datetime import date
import os

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Date,
    Numeric,
    Text,
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
    observacao = Column(Text, nullable=True)  # novo campo


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
    observacao: str | None = None


class FaturaCreate(FaturaBase):
    pass


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

# ---- static e templates ----
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# =========================
# ROTAS HTML (TELA)
# =========================

@app.get("/", response_class=HTMLResponse)
def tela_principal(request: Request):
    """
    Renderiza a tela 'Faturas MSHOP' com layout bonito.
    """
    return templates.TemplateResponse("index.html", {"request": request})


# =========================
# ROTAS DE FATURAS (API)
# =========================

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/faturas", response_model=FaturaOut)
def criar_fatura(fatura: FaturaCreate, db: Session = Depends(get_db)):
    db_fatura = FaturaDB(
        transportadora=fatura.transportadora,
        numero_fatura=fatura.numero_fatura,
        valor=fatura.valor,
        data_vencimento=fatura.data_vencimento,
        status=fatura.status,
        observacao=fatura.observacao,
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
def atualizar_fatura(fatura_id: int, dados: FaturaCreate, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    for campo, valor in dados.dict().items():
        setattr(fatura, campo, valor)

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


# =========================
# ROTA SIMPLES DE DASHBOARD (JSON)
# =========================

@app.get("/dashboard-resumo")
def dashboard_resumo(db: Session = Depends(get_db)):
    """
    Retorna um resumo simples para o dashboard:
    total, pendentes, atrasadas, em dia.
    """
    faturas = db.query(FaturaDB).all()

    total_valor = sum(float(f.valor) for f in faturas) if faturas else 0.0
    pendentes = [f for f in faturas if f.status.lower() == "pendente"]
    atrasadas = [f for f in faturas if f.status.lower() == "atrasada"]
    em_dia = [f for f in faturas if f.status.lower() == "em dia"]

    return {
        "total_valor": total_valor,
        "pendentes_qtd": len(pendentes),
        "atrasadas_qtd": len(atrasadas),
        "em_dia_qtd": len(em_dia),
        "pendentes_valor": sum(float(f.valor) for f in pendentes) if pendentes else 0.0,
        "atrasadas_valor": sum(float(f.valor) for f in atrasadas) if atrasadas else 0.0,
        "em_dia_valor": sum(float(f.valor) for f in em_dia) if em_dia else 0.0,
    }
