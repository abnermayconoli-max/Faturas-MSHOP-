from datetime import date
import os
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
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

import io
import csv

# =========================
# CONFIG BANCO DE DADOS
# =========================

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL não configurada nas variáveis de ambiente do Render."
    )

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
    observacao = Column(String, nullable=True)


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
    observacao: Optional[str] = None


class FaturaCreate(FaturaBase):
    pass


class FaturaUpdate(BaseModel):
    transportadora: Optional[str] = None
    numero_fatura: Optional[str] = None
    valor: Optional[float] = None
    data_vencimento: Optional[date] = None
    status: Optional[str] = None
    observacao: Optional[str] = None


class FaturaOut(FaturaBase):
    id: int

    class Config:
        orm_mode = True


class DashboardOut(BaseModel):
    valor_total: float
    pendentes_qtd: int
    pendentes_valor: float
    atrasadas_qtd: int
    atrasadas_valor: float
    em_dia_qtd: int
    em_dia_valor: float


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
    title="Faturas MSHOP",
    version="0.3.0",
)

# CORS (para o front conseguir chamar a API sem problema)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# servir arquivos estáticos (index.html, css, js)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
def serve_front():
    """
    Quando acessar a raiz, abre o front (index.html).
    """
    return FileResponse("static/index.html")


@app.get("/health")
def health_check():
    return {"status": "ok"}


# =========================
# ROTAS DE FATURAS
# =========================

# >>>>>>> ESSA É A ROTA QUE ESTAVA FALTANDO <<<<<<<<
@app.post("/faturas", response_model=FaturaOut)
def criar_fatura(fatura: FaturaCreate, db: Session = Depends(get_db)):
    """
    Criar nova fatura.
    Chamado pelo botão 'Salvar Fatura' do front.
    """
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


@app.get("/faturas", response_model=List[FaturaOut])
def listar_faturas(transportadora: Optional[str] = None,
                   db: Session = Depends(get_db)):
    """
    Lista faturas. Se vier ?transportadora=DHL filtra por ela.
    """
    query = db.query(FaturaDB)
    if transportadora:
        query = query.filter(FaturaDB.transportadora == transportadora)
    faturas = query.order_by(FaturaDB.id).all()
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
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    for campo, valor in dados.dict(exclude_unset=True).items():
        setattr(fatura, campo, valor)

    db.commit()
    db.refresh(fatura)
    return fatura


@app.patch("/faturas/{fatura_id}/status", response_model=FaturaOut)
def atualizar_status_fatura(
    fatura_id: int,
    status: str,
    db: Session = Depends(get_db),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    fatura.status = status
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
# DASHBOARD
# =========================

@app.get("/dashboard", response_model=DashboardOut)
def obter_dashboard(db: Session = Depends(get_db)):
    faturas = db.query(FaturaDB).all()

    valor_total = sum(float(f.valor) for f in faturas)

    pendentes = [f for f in faturas if f.status.lower() == "pendente"]
    atrasadas = [f for f in faturas if f.status.lower() == "atrasada"]
    em_dia = [f for f in faturas if f.status.lower() == "em dia"]

    pendentes_valor = sum(float(f.valor) for f in pendentes)
    atrasadas_valor = sum(float(f.valor) for f in atrasadas)
    em_dia_valor = sum(float(f.valor) for f in em_dia)

    return DashboardOut(
        valor_total=valor_total,
        pendentes_qtd=len(pendentes),
        pendentes_valor=pendentes_valor,
        atrasadas_qtd=len(atrasadas),
        atrasadas_valor=atrasadas_valor,
        em_dia_qtd=len(em_dia),
        em_dia_valor=em_dia_valor,
    )


# =========================
# EXPORTAÇÃO EXCEL (CSV)
# =========================

@app.get("/faturas/exportar")
def exportar_faturas(transportadora: Optional[str] = None,
                     db: Session = Depends(get_db)):
    """
    Exporta faturas (todas ou filtradas por transportadora) em CSV.
    """
    query = db.query(FaturaDB)
    if transportadora:
        query = query.filter(FaturaDB.transportadora == transportadora)

    faturas = query.order_by(FaturaDB.id).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    writer.writerow([
        "ID",
        "Transportadora",
        "Número Fatura",
        "Valor",
        "Data Vencimento",
        "Status",
        "Observação",
    ])

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

    output.seek(0)
    headers = {
        "Content-Disposition": 'attachment; filename="faturas.csv"'
    }
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers=headers,
    )
