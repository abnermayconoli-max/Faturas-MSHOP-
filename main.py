from datetime import date
import os
import io
import csv

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
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
    raise RuntimeError("DATABASE_URL não configurada nas variáveis de ambiente do Render.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# =========================
# MODELO SQLALCHEMY (TABELA)
# (MANTENDO O ESQUEMA ORIGINAL: SEM OBSERVAÇÃO/A NEXOS AINDA)
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


class FaturaOut(FaturaBase):
    id: int

    class Config:
        orm_mode = True


class DashboardOut(BaseModel):
    total: float
    pendentes: float
    atrasadas: float
    em_dia: float


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
# APP FASTAPI + STATIC
# =========================

app = FastAPI(
    title="Faturas MSHOP",
    version="1.0.0",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Garante que a pasta exista (não quebra o Render)
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=FileResponse)
def read_root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=500, detail="Arquivo index.html não encontrado.")
    return FileResponse(index_path)


@app.get("/health")
def health_check():
    return {"status": "ok"}


# =========================
# ROTAS DE FATURAS (API)
# =========================

@app.post("/api/faturas", response_model=FaturaOut)
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


@app.get("/api/faturas", response_model=list[FaturaOut])
def listar_faturas(
    transportadora: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(FaturaDB)
    if transportadora:
        query = query.filter(FaturaDB.transportadora == transportadora)
    faturas = query.order_by(FaturaDB.id).all()
    return faturas


# =========================
# DASHBOARD
# =========================

@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = db.query(FaturaDB).all()

    total = sum(float(f.valor) for f in faturas) if faturas else 0.0
    pendentes = sum(
        float(f.valor)
        for f in faturas
        if f.status.lower() == "pendente"
    )
    atrasadas = sum(
        float(f.valor)
        for f in faturas
        if f.data_vencimento is not None
        and f.data_vencimento < hoje
        and f.status.lower() != "pago"
    )
    em_dia = total - atrasadas

    return DashboardOut(
        total=round(total, 2),
        pendentes=round(pendentes, 2),
        atrasadas=round(atrasadas, 2),
        em_dia=round(em_dia, 2),
    )


# =========================
# EXPORTAÇÃO CSV (abre no Excel)
# =========================

@app.get("/api/exportar")
def exportar_csv(
    transportadora: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Gera um CSV (Excel abre de boa) com:
    - todas as faturas, ou
    - apenas da transportadora passada no filtro.
    """
    query = db.query(FaturaDB)
    if transportadora:
        query = query.filter(FaturaDB.transportadora == transportadora)
    faturas = query.order_by(FaturaDB.id).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    # Cabeçalho
    writer.writerow(
        ["ID", "Transportadora", "Número da Fatura", "Valor", "Data Vencimento", "Status"]
    )

    for f in faturas:
        writer.writerow(
            [
                f.id,
                f.transportadora,
                f.numero_fatura,
                float(f.valor),
                f.data_vencimento.isoformat() if f.data_vencimento else "",
                f.status,
            ]
        )

    output.seek(0)
    headers = {
        "Content-Disposition": "attachment; filename=faturas.csv"
    }
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers=headers,
    )
