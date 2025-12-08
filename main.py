from datetime import date
import os
import io
import csv

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
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
    ForeignKey,
    LargeBinary,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship


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
# MODELOS SQLALCHEMY
# =========================

class FaturaDB(Base):
    __tablename__ = "faturas"

    id = Column(Integer, primary_key=True, index=True)
    transportadora = Column(String, index=True)
    numero_fatura = Column(String, index=True)
    valor = Column(Numeric(10, 2))
    data_vencimento = Column(Date)
    status = Column(String, default="pendente")

    anexos = relationship(
        "AnexoDB",
        back_populates="fatura",
        cascade="all, delete-orphan",
    )


class AnexoDB(Base):
    __tablename__ = "anexos"

    id = Column(Integer, primary_key=True, index=True)
    fatura_id = Column(Integer, ForeignKey("faturas.id", ondelete="CASCADE"))
    filename = Column(String)
    content_type = Column(String)
    data = Column(LargeBinary)

    fatura = relationship("FaturaDB", back_populates="anexos")


# Cria tabelas (inclui a nova tabela de anexos, se ainda não existir)
Base.metadata.create_all(bind=engine)


# =========================
# MODELOS Pydantic
# =========================

class AnexoOut(BaseModel):
    id: int
    filename: str

    class Config:
        orm_mode = True


class FaturaBase(BaseModel):
    transportadora: str
    numero_fatura: str
    valor: float
    data_vencimento: date
    status: str = "pendente"


class FaturaOut(FaturaBase):
    id: int
    anexos: list[AnexoOut] = []

    class Config:
        orm_mode = True


class StatusUpdate(BaseModel):
    status: str


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

# pasta do front-end
app.mount("/static", StaticFiles(directory="static"), name="static")


# =========================
# ROTAS BÁSICAS
# =========================

@app.get("/", response_class=FileResponse)
def read_root():
    # Carrega o front-end (layout bonitão)
    return FileResponse("static/index.html")


@app.get("/health")
def health_check():
    return {"status": "ok"}


# =========================
# ROTAS DE FATURAS (API)
# =========================

@app.post("/api/faturas", response_model=FaturaOut)
async def criar_fatura(
    transportadora: str = Form(...),
    numero_fatura: str = Form(...),
    valor: float = Form(...),
    data_vencimento: date = Form(...),
    status: str = Form("pendente"),
    arquivos: list[UploadFile] = File([]),
    db: Session = Depends(get_db),
):
    """Cria fatura + salva anexos (arquivos)."""
    db_fatura = FaturaDB(
        transportadora=transportadora,
        numero_fatura=numero_fatura,
        valor=valor,
        data_vencimento=data_vencimento,
        status=status,
    )
    db.add(db_fatura)
    db.flush()  # gera o ID da fatura

    # Salvar anexos (se tiver)
    for arquivo in arquivos:
        conteudo = await arquivo.read()
        if not conteudo:
            continue
        anexo = AnexoDB(
            fatura_id=db_fatura.id,
            filename=arquivo.filename,
            content_type=arquivo.content_type or "application/octet-stream",
            data=conteudo,
        )
        db.add(anexo)

    db.commit()
    db.refresh(db_fatura)
    return db_fatura


@app.get("/api/faturas", response_model=list[FaturaOut])
def listar_faturas(
    transportadora: str | None = None,
    db: Session = Depends(get_db),
):
    """Lista faturas, com filtro por transportadora (opcional)."""
    query = db.query(FaturaDB).order_by(FaturaDB.id)
    if transportadora:
        like = f"%{transportadora}%"
        query = query.filter(FaturaDB.transportadora.ilike(like))
    return query.all()


@app.get("/api/faturas/{fatura_id}", response_model=FaturaOut)
def obter_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return fatura


@app.put("/api/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(
    fatura_id: int,
    dados: FaturaBase,
    db: Session = Depends(get_db),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    for campo, valor in dados.dict().items():
        setattr(fatura, campo, valor)

    db.commit()
    db.refresh(fatura)
    return fatura


@app.patch("/api/faturas/{fatura_id}/status", response_model=FaturaOut)
def atualizar_status(
    fatura_id: int,
    body: StatusUpdate,
    db: Session = Depends(get_db),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    fatura.status = body.status
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


# =========================
# ANEXOS
# =========================

@app.get("/api/faturas/{fatura_id}/anexos", response_model=list[AnexoOut])
def listar_anexos(fatura_id: int, db: Session = Depends(get_db)):
    anexos = db.query(AnexoDB).filter(AnexoDB.fatura_id == fatura_id).all()
    return anexos


@app.get("/api/anexos/{anexo_id}/download")
def download_anexo(anexo_id: int, db: Session = Depends(get_db)):
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    return StreamingResponse(
        io.BytesIO(anexo.data),
        media_type=anexo.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{anexo.filename}"'},
    )


# =========================
# DASHBOARD
# =========================

@app.get("/api/dashboard-resumo")
def dashboard_resumo(db: Session = Depends(get_db)):
    faturas = db.query(FaturaDB).all()
    hoje = date.today()

    total_valor = sum(float(f.valor or 0) for f in faturas)
    pendentes = [f for f in faturas if (f.status or "").lower() == "pendente"]
    atrasadas = [
        f for f in faturas
        if (f.status or "").lower() == "atrasada"
        or ((f.status or "").lower() == "pendente"
            and f.data_vencimento
            and f.data_vencimento < hoje)
    ]
    em_dia = [f for f in faturas if f not in atrasadas]

    def resumo(lista):
        return {
            "quantidade": len(lista),
            "valor": sum(float(f.valor or 0) for f in lista),
        }

    return {
        "total": {"quantidade": len(faturas), "valor": total_valor},
        "pendentes": resumo(pendentes),
        "atrasadas": resumo(atrasadas),
        "em_dia": resumo(em_dia),
    }


# =========================
# EXPORTAR PARA "EXCEL" (CSV)
# =========================

@app.get("/api/faturas/exportar")
def exportar_faturas_excel(
    transportadora: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Gera um CSV (que o Excel abre normalmente) com as faturas.
    - Se "transportadora" vier na query, aplica o filtro.
    """
    query = db.query(FaturaDB).order_by(FaturaDB.id)
    if transportadora:
        like = f"%{transportadora}%"
        query = query.filter(FaturaDB.transportadora.ilike(like))
    faturas = query.all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    writer.writerow(
        ["ID", "Transportadora", "Número Fatura", "Valor", "Data Vencimento", "Status"]
    )

    for f in faturas:
        writer.writerow(
            [
                f.id,
                f.transportadora,
                f.numero_fatura,
                float(f.valor or 0),
                f.data_vencimento.strftime("%d/%m/%Y") if f.data_vencimento else "",
                f.status,
            ]
        )

    conteudo = output.getvalue().encode("utf-8-sig")
    output.close()

    return StreamingResponse(
        io.BytesIO(conteudo),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="faturas.csv"'},
    )
