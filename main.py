from datetime import date
import os
import io

from fastapi import FastAPI, HTTPException, Depends, Request
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
    status = Column(String, default="pendente")  # pendente / atrasado / em_dia / pago


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
# APP FASTAPI + STATIC + TEMPLATES
# =========================

app = FastAPI(
    title="Sistema de Faturas Transportadoras",
    version="0.3.0",
)

# arquivos estáticos (css, js)
app.mount("/static", StaticFiles(directory="static"), name="static")

# templates HTML
templates = Jinja2Templates(directory="templates")


# =========================
# ROTAS VISUAIS
# =========================

@app.get("/app", response_class=HTMLResponse)
def tela_faturas(request: Request):
    """
    Tela principal do sistema (visual).
    A API continua funcionando em /faturas, /faturas/{id}, etc.
    """
    return templates.TemplateResponse("faturas.html", {"request": request})


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
# ROTAS DE FATURAS (API)
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
def listar_faturas(
    transportadora: str | None = None,
    db: Session = Depends(get_db),
):
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
    fatura_id: int,
    fatura_dados: FaturaUpdate,
    db: Session = Depends(get_db),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    fatura.transportadora = fatura_dados.transportadora
    fatura.numero_fatura = fatura_dados.numero_fatura
    fatura.valor = fatura_dados.valor
    fatura.data_vencimento = fatura_dados.data_vencimento
    fatura.status = fatura_dados.status

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
def atualizar_status_fatura(
    fatura_id: int,
    dados_status: FaturaStatusUpdate,
    db: Session = Depends(get_db),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    fatura.status = dados_status.status
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
# DASHBOARD / RESUMO
# =========================

@app.get("/dashboard/resumo")
def dashboard_resumo(db: Session = Depends(get_db)):
    total_valor = db.query(func.coalesce(func.sum(FaturaDB.valor), 0)).scalar()

    def soma_status(status: str) -> float:
        return (
            db.query(func.coalesce(func.sum(FaturaDB.valor), 0))
            .filter(FaturaDB.status == status)
            .scalar()
        )

    total_pendente = soma_status("pendente")
    total_atrasado = soma_status("atrasado")
    total_em_dia = soma_status("em_dia")

    total_faturas = db.query(func.count(FaturaDB.id)).scalar()

    return {
        "total_faturas": total_faturas,
        "total_valor": float(total_valor or 0),
        "total_pendente": float(total_pendente or 0),
        "total_atrasado": float(total_atrasado or 0),
        "total_em_dia": float(total_em_dia or 0),
    }


# =========================
# EXPORTAÇÃO PARA EXCEL (CSV)
# =========================

@app.get("/faturas/export")
def exportar_faturas_excel(
    transportadora: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Gera um arquivo CSV (abre no Excel) com as faturas.
    Se 'transportadora' vier preenchida, filtra.
    """
    query = db.query(FaturaDB)
    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))
    faturas = query.order_by(FaturaDB.id).all()

    output = io.StringIO()
    # cabeçalho
    output.write("id;transportadora;numero_fatura;valor;data_vencimento;status\n")

    for f in faturas:
        output.write(
            f"{f.id};{f.transportadora};{f.numero_fatura};{float(f.valor):.2f};"
            f"{f.data_vencimento.isoformat()};{f.status}\n"
        )

    output.seek(0)

    headers = {
        "Content-Disposition": "attachment; filename=faturas_mshop.csv"
    }

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers=headers,
    )
