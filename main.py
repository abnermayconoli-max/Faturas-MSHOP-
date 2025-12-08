from datetime import date
import os
from io import StringIO
import csv

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse

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
    observacao = Column(String, nullable=True)  # <--- NOVO CAMPO
    anexos = Column(String, nullable=True)      # nomes de arquivos separados por ; (opcional)


Base.metadata.create_all(bind=engine)


# =========================
# MODELOS Pydantic
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

class FaturaUpdate(BaseModel):
    transportadora: str | None = None
    numero_fatura: str | None = None
    valor: float | None = None
    data_vencimento: date | None = None
    status: str | None = None
    observacao: str | None = None

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

# CORS para o front em /static
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# servir o front (SPA)
app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.get("/api")
def read_root():
    return {"mensagem": "API de Faturas com banco PostgreSQL no Render!"}


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


# =========================
# ROTAS CRUD DE FATURAS
# =========================

@app.post("/api/faturas", response_model=FaturaOut)
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


@app.get("/api/faturas", response_model=list[FaturaOut])
def listar_faturas(db: Session = Depends(get_db)):
    faturas = db.query(FaturaDB).order_by(FaturaDB.data_vencimento).all()
    return faturas


@app.get("/api/faturas/{fatura_id}", response_model=FaturaOut)
def obter_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return fatura


@app.put("/api/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(fatura_id: int, dados: FaturaUpdate, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    for campo, valor in dados.dict(exclude_unset=True).items():
        setattr(fatura, campo, valor)

    db.commit()
    db.refresh(fatura)
    return fatura


@app.delete("/api/faturas/{fatura_id}")
def deletar_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    db.delete(fatura)
    db.commit()
    return {"ok": True}


@app.patch("/api/faturas/{fatura_id}/status", response_model=FaturaOut)
def atualizar_status_fatura(fatura_id: int, status: str, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    fatura.status = status
    db.commit()
    db.refresh(fatura)
    return fatura


@app.get("/api/faturas/atrasadas", response_model=list[FaturaOut])
def listar_atrasadas(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = (
        db.query(FaturaDB)
        .filter(FaturaDB.data_vencimento < hoje, FaturaDB.status != "pago")
        .order_by(FaturaDB.data_vencimento)
        .all()
    )
    return faturas


# =========================
# DASHBOARD
# =========================

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = db.query(FaturaDB).all()

    total_valor = sum(float(f.valor) for f in faturas) if faturas else 0.0

    pendentes = [f for f in faturas if f.status.lower() == "pendente"]
    atrasadas = [
        f for f in faturas
        if f.status.lower() != "pago" and f.data_vencimento < hoje
    ]
    em_dia = [
        f for f in faturas
        if f.status.lower() == "pago" or f.data_vencimento >= hoje
    ]

    return {
        "total_valor": total_valor,
        "pendentes_qtd": len(pendentes),
        "pendentes_valor": sum(float(f.valor) for f in pendentes) if pendentes else 0.0,
        "atrasadas_qtd": len(atrasadas),
        "atrasadas_valor": sum(float(f.valor) for f in atrasadas) if atrasadas else 0.0,
        "em_dia_qtd": len(em_dia),
        "em_dia_valor": sum(float(f.valor) for f in em_dia) if em_dia else 0.0,
    }


# =========================
# EXPORTAR "EXCEL" (CSV)
# =========================

@app.get("/api/faturas/exportar")
def exportar_faturas(transportadora: str | None = None, db: Session = Depends(get_db)):
    query = db.query(FaturaDB)
    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

    faturas = query.order_by(FaturaDB.data_vencimento).all()

    # CSV em memória (abre no Excel normal)
    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=";")

    writer.writerow(["ID", "Transportadora", "Número Fatura", "Valor", "Vencimento", "Status", "Observação"])

    for f in faturas:
        writer.writerow([
            f.id,
            f.transportadora,
            f.numero_fatura,
            float(f.valor),
            f.data_vencimento.strftime("%d/%m/%Y"),
            f.status,
            f.observacao or "",
        ])

    buffer.seek(0)

    headers = {
        "Content-Disposition": 'attachment; filename="faturas.csv"'
    }

    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers=headers,
    )
