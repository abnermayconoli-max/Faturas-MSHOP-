from datetime import date
from io import BytesIO
import os

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
from openpyxl import Workbook


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


class ResumoGrupo(BaseModel):
    qtd: int
    valor: float


class ResumoDashboard(BaseModel):
    valor_total: float
    pendentes: ResumoGrupo
    atrasadas: ResumoGrupo
    em_dia: ResumoGrupo


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# pasta de arquivos estáticos (HTML/JS/CSS)
if not os.path.exists("static"):
    os.makedirs("static", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
def serve_frontend():
    """
    Entrega o arquivo static/index.html como página principal.
    """
    index_path = os.path.join("static", "index.html")
    return FileResponse(index_path)


@app.get("/health")
def health_check():
    return {"status": "ok"}


# =========================
# ROTAS DE FATURAS (CRUD)
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
    query = db.query(FaturaDB).order_by(FaturaDB.id)

    if transportadora:
        # filtro simples por nome (contém)
        like_value = f"%{transportadora}%"
        query = query.filter(FaturaDB.transportadora.ilike(like_value))

    return query.all()


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


@app.patch("/faturas/{fatura_id}/status", response_model=FaturaOut)
def atualizar_status_fatura(
    fatura_id: int,
    dados: FaturaStatusUpdate,
    db: Session = Depends(get_db),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

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


@app.get("/faturas/atrasadas", response_model=list[FaturaOut])
def listar_atrasadas(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = (
        db.query(FaturaDB)
        .filter(FaturaDB.status == "pendente")
        .filter(FaturaDB.data_vencimento < hoje)
        .order_by(FaturaDB.data_vencimento)
        .all()
    )
    return faturas


# =========================
# ROTAS DE DASHBOARD
# =========================

@app.get("/dashboard/resumo", response_model=ResumoDashboard)
def obter_resumo_dashboard(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = db.query(FaturaDB).all()

    def soma_valor(lista):
        return sum(float(f.valor or 0) for f in lista)

    valor_total = soma_valor(faturas)

    pendentes = [f for f in faturas if f.status == "pendente"]
    atrasadas = [f for f in pendentes if f.data_vencimento and f.data_vencimento < hoje]
    em_dia = [f for f in pendentes if f.data_vencimento and f.data_vencimento >= hoje]

    resumo_pendentes = ResumoGrupo(qtd=len(pendentes), valor=soma_valor(pendentes))
    resumo_atrasadas = ResumoGrupo(qtd=len(atrasadas), valor=soma_valor(atrasadas))
    resumo_em_dia = ResumoGrupo(qtd=len(em_dia), valor=soma_valor(em_dia))

    return ResumoDashboard(
        valor_total=valor_total,
        pendentes=resumo_pendentes,
        atrasadas=resumo_atrasadas,
        em_dia=resumo_em_dia,
    )


# =========================
# EXPORTAÇÃO EXCEL
# =========================

@app.get("/faturas/exportar-excel")
def exportar_excel(db: Session = Depends(get_db)):
    """
    Exporta TODAS as faturas em um arquivo Excel (.xlsx).
    """
    faturas = db.query(FaturaDB).order_by(FaturaDB.id).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Faturas"

    # Cabeçalho
    ws.append(["ID", "Transportadora", "Número da Fatura", "Valor", "Data Vencimento", "Status"])

    # Linhas
    for f in faturas:
        ws.append([
            f.id,
            f.transportadora,
            f.numero_fatura,
            float(f.valor or 0),
            f.data_vencimento.isoformat() if f.data_vencimento else "",
            f.status,
        ])

    # Salva em memória
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    headers = {
        "Content-Disposition": 'attachment; filename="faturas_mshop.xlsx"'
    }

    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
