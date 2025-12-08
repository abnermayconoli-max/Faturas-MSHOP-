from datetime import date
import os
from io import BytesIO
from decimal import Decimal

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import FileResponse, StreamingResponse, Response
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

    # relação com anexos
    anexos = relationship("AnexoDB", back_populates="fatura", cascade="all, delete-orphan")


class AnexoDB(Base):
    __tablename__ = "anexos"

    id = Column(Integer, primary_key=True, index=True)
    fatura_id = Column(Integer, ForeignKey("faturas.id", ondelete="CASCADE"))
    nome_arquivo = Column(String)
    content_type = Column(String)
    dados = Column(LargeBinary)

    fatura = relationship("FaturaDB", back_populates="anexos")


# cria tabela de faturas (se ainda não existir) e tabela de anexos
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

# pasta de arquivos estáticos (nosso front)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def read_root():
    # abre a tela visual
    return FileResponse("static/index.html")


@app.get("/health")
def health_check():
    return {"status": "ok"}


# =========================
# FUNÇÕES AUXILIARES
# =========================

def decimal_to_float(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


# =========================
# ROTAS DE FATURAS
# =========================

@app.post("/faturas", response_model=FaturaOut)
async def criar_fatura(
    transportadora: str = Form(...),
    numero_fatura: str = Form(...),
    valor: float = Form(...),
    data_vencimento: date = Form(...),
    status: str = Form("pendente"),
    arquivo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    db_fatura = FaturaDB(
        transportadora=transportadora,
        numero_fatura=numero_fatura,
        valor=valor,
        data_vencimento=data_vencimento,
        status=status,
    )
    db.add(db_fatura)
    db.commit()
    db.refresh(db_fatura)

    # se veio arquivo, salva como anexo
    if arquivo is not None:
        conteudo = await arquivo.read()
        anexo = AnexoDB(
            fatura_id=db_fatura.id,
            nome_arquivo=arquivo.filename,
            content_type=arquivo.content_type or "application/octet-stream",
            dados=conteudo,
        )
        db.add(anexo)
        db.commit()

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
async def atualizar_fatura(
    fatura_id: int,
    transportadora: str = Form(...),
    numero_fatura: str = Form(...),
    valor: float = Form(...),
    data_vencimento: date = Form(...),
    status: str = Form(...),
    arquivo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    fatura.transportadora = transportadora
    fatura.numero_fatura = numero_fatura
    fatura.valor = valor
    fatura.data_vencimento = data_vencimento
    fatura.status = status
    db.commit()
    db.refresh(fatura)

    if arquivo is not None:
        conteudo = await arquivo.read()
        # remove anexos antigos e cadastra o novo
        db.query(AnexoDB).filter(AnexoDB.fatura_id == fatura_id).delete()
        anexo = AnexoDB(
            fatura_id=fatura_id,
            nome_arquivo=arquivo.filename,
            content_type=arquivo.content_type or "application/octet-stream",
            dados=conteudo,
        )
        db.add(anexo)
        db.commit()

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
    return {"mensagem": "Fatura deletada com sucesso"}


# =========================
# ANEXOS
# =========================

@app.get("/faturas/{fatura_id}/anexo")
def baixar_anexo(fatura_id: int, db: Session = Depends(get_db)):
    anexo = db.query(AnexoDB).filter(AnexoDB.fatura_id == fatura_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    headers = {
        "Content-Disposition": f'attachment; filename="{anexo.nome_arquivo}"'
    }
    return Response(anexo.dados, media_type=anexo.content_type, headers=headers)


# =========================
# DASHBOARD / RESUMO
# =========================

@app.get("/faturas/resumo")
def resumo_faturas(db: Session = Depends(get_db)):
    hoje = date.today()
    faturas = db.query(FaturaDB).all()

    total_valor = sum(decimal_to_float(f.valor) for f in faturas)
    pendentes = [f for f in faturas if f.status.lower() == "pendente"]
    atrasadas = [f for f in pendentes if f.data_vencimento < hoje]
    em_dia = [f for f in pendentes if f.data_vencimento >= hoje]

    def aggregate(lista):
        return {
            "quantidade": len(lista),
            "valor": sum(decimal_to_float(f.valor) for f in lista),
        }

    return {
        "total": {"quantidade": len(faturas), "valor": total_valor},
        "pendentes": aggregate(pendentes),
        "atrasadas": aggregate(atrasadas),
        "em_dia": aggregate(em_dia),
    }


# =========================
# EXPORTAR EXCEL
# =========================

@app.get("/faturas/exportar")
def exportar_faturas(
    transportadora: str | None = None,
    db: Session = Depends(get_db),
):
    # import aqui dentro para só carregar quando usar a rota
    from openpyxl import Workbook

    query = db.query(FaturaDB)
    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))
    faturas = query.order_by(FaturaDB.id).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Faturas"

    ws.append(["ID", "Transportadora", "Número Fatura", "Valor", "Vencimento", "Status"])

    for f in faturas:
        ws.append(
            [
                f.id,
                f.transportadora,
                f.numero_fatura,
                float(f.valor),
                f.data_vencimento.strftime("%d/%m/%Y"),
                f.status,
            ]
        )

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    filename = "faturas.xlsx"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
