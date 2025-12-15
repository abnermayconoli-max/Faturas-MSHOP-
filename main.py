from datetime import date, datetime, timedelta
import os
import uuid
from typing import List, Optional

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    UploadFile,
    File,
    Query,
    Request,
)
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.responses import StreamingResponse
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
    ForeignKey,
    func,
    and_,
    or_,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship

import boto3
from botocore.exceptions import ClientError

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
# CONFIG CLOUDFLARE R2 (S3 compatível)
# =========================

R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
# (opcional) só pra referência — não precisa no client
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")

if not (R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME and R2_ENDPOINT):
    raise RuntimeError(
        "Variáveis do R2 não configuradas. Configure: "
        "R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_ENDPOINT"
    )

# Client S3 apontando pro R2
s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
)

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
    observacao = Column(String, nullable=True)

    anexos = relationship(
        "AnexoDB",
        back_populates="fatura",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AnexoDB(Base):
    __tablename__ = "anexos"

    id = Column(Integer, primary_key=True, index=True)
    fatura_id = Column(Integer, ForeignKey("faturas.id", ondelete="CASCADE"))
    filename = Column(String)       # AGORA = object_key no R2
    original_name = Column(String)  # nome que o usuário enviou
    content_type = Column(String)
    criado_em = Column(Date, default=date.today)

    fatura = relationship("FaturaDB", back_populates="anexos")


# Cria tabelas (se não existirem)
Base.metadata.create_all(bind=engine)

# =========================
# Pydantic
# =========================


class FaturaBase(BaseModel):
    transportadora: str
    numero_fatura: str
    valor: float
    data_vencimento: date
    status: str = "pendente"
    observacao: Optional[str] = None


class FaturaCreate(FaturaBase):
    """Usado no POST /faturas"""
    pass


class FaturaUpdate(BaseModel):
    transportadora: Optional[str] = None
    numero_fatura: Optional[str] = None
    valor: Optional[float] = None
    data_vencimento: Optional[date] = None
    status: Optional[str] = None
    observacao: Optional[str] = None


class AnexoOut(BaseModel):
    id: int
    original_name: str

    class Config:
        orm_mode = True


class FaturaOut(FaturaBase):
    id: int
    responsavel: Optional[str] = None

    class Config:
        orm_mode = True


# =========================
# MAPEAMENTO RESPONSÁVEL
# =========================

RESP_MAP = {
    "DHL": "Gabrielly",
    "Pannan": "Gabrielly",
    "Pannan - Gabrielly": "Gabrielly",
    "DHL - Gabrielly": "Gabrielly",
    "Garcia": "Juliana",
    "Excargo": "Juliana",
    "Garcia - Juliana": "Juliana",
    "Excargo - Juliana": "Juliana",
    "Transbritto": "Larissa",
    "PDA": "Larissa",
    "GLM": "Larissa",
    "Transbritto - Larissa": "Larissa",
    "PDA - Larissa": "Larissa",
    "GLM - Larissa": "Larissa",
}


def get_responsavel(transportadora: str) -> Optional[str]:
    if transportadora in RESP_MAP:
        return RESP_MAP[transportadora]
    base = transportadora.split("-")[0].strip()
    return RESP_MAP.get(base)


def fatura_to_out(f: FaturaDB) -> FaturaOut:
    return FaturaOut(
        id=f.id,
        transportadora=f.transportadora,
        numero_fatura=f.numero_fatura,
        valor=float(f.valor or 0),
        data_vencimento=f.data_vencimento,
        status=f.status,
        observacao=f.observacao,
        responsavel=get_responsavel(f.transportadora),
    )


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
# APP / STATIC / TEMPLATES
# =========================

app = FastAPI(
    title="Sistema de Faturas Transportadoras",
    version="0.6.0",
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
def health_check():
    return {"status": "ok"}


# =========================
# ROTAS DE FATURAS - CRUD
# =========================


@app.post("/faturas", response_model=FaturaOut)
def criar_fatura(fatura: FaturaCreate, db: Session = Depends(get_db)):
    try:
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
        return fatura_to_out(db_fatura)
    except Exception as e:
        print("ERRO AO CRIAR FATURA:", repr(e))
        raise HTTPException(status_code=400, detail="Erro ao criar fatura")


@app.get("/faturas", response_model=List[FaturaOut])
def listar_faturas(
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    ate_vencimento: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
):
    query = db.query(FaturaDB)

    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

    if ate_vencimento:
        try:
            filtro_data = datetime.strptime(ate_vencimento, "%Y-%m-%d").date()
            query = query.filter(FaturaDB.data_vencimento <= filtro_data)
        except ValueError:
            pass

    if numero_fatura:
        query = query.filter(FaturaDB.numero_fatura.ilike(f"%{numero_fatura}%"))

    query = query.order_by(FaturaDB.id)
    faturas_db = query.all()
    return [fatura_to_out(f) for f in faturas_db]


@app.get("/faturas/{fatura_id}", response_model=FaturaOut)
def obter_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return fatura_to_out(fatura)


@app.put("/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(
    fatura_id: int,
    dados: FaturaUpdate,
    db: Session = Depends(get_db),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    data = dados.dict(exclude_unset=True)

    for campo, valor in data.items():
        setattr(fatura, campo, valor)

    db.commit()
    db.refresh(fatura)
    return fatura_to_out(fatura)


@app.delete("/faturas/{fatura_id}")
def deletar_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    # >>> ALTERADO: remove anexos do R2
    for anexo in fatura.anexos:
        try:
            s3.delete_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
        except ClientError as e:
            # não trava exclusão da fatura por causa de anexo já removido
            print("ERRO AO APAGAR NO R2:", repr(e))

    db.delete(fatura)
    db.commit()
    return {"ok": True}


# =========================
# ANEXOS (R2)
# =========================


@app.post("/faturas/{fatura_id}/anexos", response_model=List[AnexoOut])
async def upload_anexos(
    fatura_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    anexos_criados = []

    for file in files:
        original_name = file.filename or "arquivo"
        object_key = f"{uuid.uuid4().hex}_{original_name}"

        try:
            # envia pro R2 (stream)
            s3.upload_fileobj(
                file.file,
                R2_BUCKET_NAME,
                object_key,
                ExtraArgs={"ContentType": file.content_type or "application/octet-stream"},
            )
        except ClientError as e:
            print("ERRO UPLOAD R2:", repr(e))
            raise HTTPException(status_code=400, detail="Erro ao enviar anexo para o R2")

        anexo_db = AnexoDB(
            fatura_id=fatura_id,
            filename=object_key,  # object_key no R2
            original_name=original_name,
            content_type=file.content_type or "application/octet-stream",
        )
        db.add(anexo_db)
        anexos_criados.append(anexo_db)

    db.commit()
    return anexos_criados


@app.get("/faturas/{fatura_id}/anexos", response_model=List[AnexoOut])
def listar_anexos(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return fatura.anexos


@app.get("/anexos/{anexo_id}")
def baixar_anexo(anexo_id: int, db: Session = Depends(get_db)):
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    try:
        obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
        body = obj["Body"]
    except ClientError as e:
        print("ERRO GET R2:", repr(e))
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no R2")

    headers = {
        "Content-Disposition": f'attachment; filename="{anexo.original_name}"'
    }

    return StreamingResponse(
        body,
        media_type=anexo.content_type or "application/octet-stream",
        headers=headers,
    )


# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# >>> EXCLUIR ANEXO (
