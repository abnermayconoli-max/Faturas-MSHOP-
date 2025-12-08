from datetime import date
import os
import io
import csv

from fastapi import FastAPI, HTTPException, Depends, Request, Response
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
    func,
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
# APP FASTAPI + TEMPLATES
# =========================

app = FastAPI(
    title="Sistema de Faturas Transportadoras",
    version="0.3.0",
)

# Static / templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ---------- ROTAS VISUAIS ----------

@app.get("/", response_class=HTMLResponse)
def pagina_principal(request: Request):
    """
    Tela visual principal: Faturas MSHOP
    """
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
def health_check():
    return {"status": "ok"}


# ---------- ROTAS DE FATURAS (API) ----------

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
def listar_faturas(
    transportadora: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(FaturaDB)

    if transportadora:
        # filtro "contains", ignorando maiúsculas/minúsculas
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

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
    return {"mensagem": "Fatura deletada com sucesso"}


@app.patch("/faturas/{fatura_id}/status", response_model=FaturaOut)
def atualizar_status(
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


@app.get("/faturas/atrasadas", response_model=list[FaturaOut])
def listar_atrasadas(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = (
        db.query(FaturaDB)
        .filter(FaturaDB.data_vencimento < hoje, FaturaDB.status != "paga")
        .order_by(FaturaDB.data_vencimento)
        .all()
    )
    return faturas


# ---------- RESUMO / DASHBOARD ----------

@app.get("/faturas/resumo")
def resumo_faturas(db: Session = Depends(get_db)):
    total_valor = db.query(func.coalesce(func.sum(FaturaDB.valor), 0)).scalar() or 0

    # por status
    por_status_raw = (
        db.query(
            FaturaDB.status,
            func.count(FaturaDB.id),
            func.coalesce(func.sum(FaturaDB.valor), 0),
        )
        .group_by(FaturaDB.status)
        .all()
    )

    por_status = {}
    for status, qtd, valor in por_status_raw:
        por_status[status] = {
            "quantidade": qtd,
            "valor": float(valor or 0),
        }

    return {
        "total_valor": float(total_valor),
        "por_status": por_status,
    }


# ---------- EXPORTAR PARA EXCEL (CSV) ----------

@app.get("/faturas/exportar")
def exportar_faturas(
    transportadora: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(FaturaDB)

    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

    faturas = query.order_by(FaturaDB.id).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    # cabeçalho
    writer.writerow(
        ["ID", "Transportadora", "Número Fatura", "Valor", "Data Vencimento", "Status"]
    )

    for f in faturas:
        writer.writerow(
            [
                f.id,
                f.transportadora,
                f.numero_fatura,
                float(f.valor),
                f.data_vencimento.strftime("%d/%m/%Y"),
                f.status,
            ]
        )

    csv_data = output.getvalue()

    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="faturas_mshop.csv"'
        },
    )
