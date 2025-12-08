from datetime import date
import os
import io

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Request,
)
from fastapi.responses import HTMLResponse, StreamingResponse
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


class FaturaUpdate(BaseModel):
    transportadora: str | None = None
    numero_fatura: str | None = None
    valor: float | None = None
    data_vencimento: date | None = None
    status: str | None = None


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
# APP FASTAPI + FRONT-END
# =========================

app = FastAPI(
    title="Faturas MSHOP",
    version="0.3.0",
)

# arquivos estáticos (CSS / JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# templates HTML
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Tela principal (Dashboard / Faturas / Cadastro)."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/info")
def info():
    return {"mensagem": "API de Faturas com banco PostgreSQL no Render!"}


# =========================
# ROTAS CRUD DE FATURAS
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
def listar_faturas(transportadora: str | None = None, db: Session = Depends(get_db)):
    query = db.query(FaturaDB)

    if transportadora:
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
    fatura_id: int, dados: FaturaUpdate, db: Session = Depends(get_db)
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    for campo, valor in dados.dict(exclude_unset=True).items():
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
    return {"mensagem": "Fatura removida com sucesso"}


@app.patch("/faturas/{fatura_id}/status", response_model=FaturaOut)
def atualizar_status_fatura(
    fatura_id: int, body: FaturaStatusUpdate, db: Session = Depends(get_db)
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


# =========================
# DASHBOARD
# =========================

@app.get("/dashboard-resumo")
def dashboard_resumo(db: Session = Depends(get_db)):
    hoje = date.today()

    def _safe_float(value):
        if value is None:
            return 0.0
        return float(value)

    total_valor = db.query(func.coalesce(func.sum(FaturaDB.valor), 0)).scalar()
    total_qtd = db.query(func.count(FaturaDB.id)).scalar()

    pendentes_q = db.query(FaturaDB).filter(FaturaDB.status == "pendente")
    pendentes_valor = pendentes_q.with_entities(
        func.coalesce(func.sum(FaturaDB.valor), 0)
    ).scalar()
    pendentes_qtd = pendentes_q.count()

    atrasadas_q = db.query(FaturaDB).filter(
        FaturaDB.data_vencimento < hoje,
        FaturaDB.status != "pago",
    )
    atrasadas_valor = atrasadas_q.with_entities(
        func.coalesce(func.sum(FaturaDB.valor), 0)
    ).scalar()
    atrasadas_qtd = atrasadas_q.count()

    em_dia_q = db.query(FaturaDB).filter(
        FaturaDB.data_vencimento >= hoje,
        FaturaDB.status != "pago",
    )
    em_dia_valor = em_dia_q.with_entities(
        func.coalesce(func.sum(FaturaDB.valor), 0)
    ).scalar()
    em_dia_qtd = em_dia_q.count()

    return {
        "total": {
            "quantidade": total_qtd,
            "valor": _safe_float(total_valor),
        },
        "pendentes": {
            "quantidade": pendentes_qtd,
            "valor": _safe_float(pendentes_valor),
        },
        "atrasadas": {
            "quantidade": atrasadas_qtd,
            "valor": _safe_float(atrasadas_valor),
        },
        "em_dia": {
            "quantidade": em_dia_qtd,
            "valor": _safe_float(em_dia_valor),
        },
    }


# =========================
# EXPORTAÇÃO EXCEL
# =========================

@app.get("/faturas/exportar")
def exportar_faturas_excel(db: Session = Depends(get_db)):
    import pandas as pd  # usa o pandas do requirements

    faturas = db.query(FaturaDB).order_by(FaturaDB.id).all()

    dados = []
    for f in faturas:
        dados.append(
            {
                "ID": f.id,
                "Transportadora": f.transportadora,
                "Número da Fatura": f.numero_fatura,
                "Valor": float(f.valor),
                "Vencimento": f.data_vencimento.strftime("%d/%m/%Y"),
                "Status": f.status,
            }
        )

    df = pd.DataFrame(dados)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Faturas")

    output.seek(0)

    headers = {
        "Content-Disposition": 'attachment; filename="faturas_mshop.xlsx"'
    }

    return StreamingResponse(
        output,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers=headers,
    )
