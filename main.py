from datetime import date
import os
from io import BytesIO

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Date, Numeric
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from openpyxl import Workbook


# =========================
# CONFIG BANCO DE DADOS
# =========================

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Ajuda a ver erro nos logs do Render se a variável não estiver setada
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

# CORS liberado (ajuda se um dia você abrir o HTML separado)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir arquivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")


# ROTA QUE SERVE O LAYOUT (index.html)
@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse("static/index.html")


@app.get("/health")
def health_check():
    return {"status": "ok"}


# =========================
# ROTAS DE FATURAS
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


# =========================
# DASHBOARD
# =========================

@app.get("/dashboard-resumo")
def dashboard_resumo(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = db.query(FaturaDB).all()

    total_valor = 0.0
    pendentes_qtd = pendentes_valor = 0.0
    atrasadas_qtd = atrasadas_valor = 0.0
    em_dia_qtd = em_dia_valor = 0.0

    for f in faturas:
        valor = float(f.valor or 0)
        total_valor += valor
        status = (f.status or "").lower()

        if status == "pendente":
            # pendente vencida -> atrasada
            if f.data_vencimento and f.data_vencimento < hoje:
                atrasadas_qtd += 1
                atrasadas_valor += valor
            else:
                pendentes_qtd += 1
                pendentes_valor += valor
        else:
            em_dia_qtd += 1
            em_dia_valor += valor

    return {
        "total_valor": round(total_valor, 2),
        "pendentes": {
            "quantidade": int(pendentes_qtd),
            "valor": round(pendentes_valor, 2),
        },
        "atrasadas": {
            "quantidade": int(atrasadas_qtd),
            "valor": round(atrasadas_valor, 2),
        },
        "em_dia": {
            "quantidade": int(em_dia_qtd),
            "valor": round(em_dia_valor, 2),
        },
    }


# =========================
# EXPORTAR EXCEL
# =========================

@app.get("/faturas/exportar")
def exportar_faturas_excel(
    transportadora: str | None = None, db: Session = Depends(get_db)
):
    query = db.query(FaturaDB)
    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))
    faturas = query.order_by(FaturaDB.id).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Faturas"

    headers = ["ID", "Transportadora", "Número", "Valor", "Vencimento", "Status"]
    ws.append(headers)

    for f in faturas:
        ws.append(
            [
                f.id,
                f.transportadora,
                f.numero_fatura,
                float(f.valor or 0),
                f.data_vencimento.isoformat() if f.data_vencimento else "",
                f.status,
            ]
        )

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="faturas.xlsx"'},
    )
