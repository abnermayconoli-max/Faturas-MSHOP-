from datetime import date, datetime, timedelta
import os
import uuid
from typing import List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    UploadFile,
    File,
    Query,
    Request,
)
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse

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
# CONFIG R2 (S3 compatível)
# =========================

R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_REGION = os.getenv("R2_REGION", "auto")

def get_s3_client():
    if not (R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_ENDPOINT_URL and R2_BUCKET_NAME):
        raise RuntimeError(
            "R2 não configurado. Defina R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL, R2_BUCKET_NAME."
        )

    # assinatura v4 e timeouts bons
    cfg = Config(signature_version="s3v4")

    return boto3.client(
        "s3",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        endpoint_url=R2_ENDPOINT_URL,
        region_name=R2_REGION,
        config=cfg,
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
    filename = Column(String)       # agora é a "key" do objeto no R2
    original_name = Column(String)  # nome enviado
    content_type = Column(String)
    criado_em = Column(Date, default=date.today)

    fatura = relationship("FaturaDB", back_populates="anexos")


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

app = FastAPI(title="Sistema de Faturas Transportadoras", version="0.7.0")

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
def atualizar_fatura(fatura_id: int, dados: FaturaUpdate, db: Session = Depends(get_db)):
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

    # apaga anexos no R2
    s3 = get_s3_client()
    for anexo in fatura.anexos:
        try:
            s3.delete_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
        except ClientError as e:
            print("ERRO AO DELETAR OBJETO NO R2:", e)

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

    s3 = get_s3_client()
    anexos_criados: List[AnexoDB] = []

    for file in files:
        # key no R2: faturas/<id>/<uuid>_<nome>
        key = f"faturas/{fatura_id}/{uuid.uuid4().hex}_{file.filename}"

        data = await file.read()

        try:
            s3.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=key,
                Body=data,
                ContentType=file.content_type or "application/octet-stream",
            )
        except ClientError as e:
            print("ERRO PUT R2:", e)
            raise HTTPException(status_code=500, detail="Erro ao enviar anexo para o R2")

        anexo_db = AnexoDB(
            fatura_id=fatura_id,
            filename=key,  # agora é a key do R2
            original_name=file.filename,
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
    """
    Download direto (sem link do R2).
    O browser baixa porque mandamos Content-Disposition: attachment.
    """
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    s3 = get_s3_client()

    try:
        obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
        stream = obj["Body"]  # streaming file-like
    except ClientError as e:
        print("ERRO GET R2:", e)
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no R2")

    headers = {
        "Content-Disposition": f'attachment; filename="{anexo.original_name}"'
    }

    return StreamingResponse(stream, media_type=anexo.content_type, headers=headers)

@app.delete("/anexos/{anexo_id}")
def excluir_anexo(anexo_id: int, db: Session = Depends(get_db)):
    """
    Exclui o anexo no R2 e remove do banco.
    """
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    s3 = get_s3_client()

    try:
        s3.delete_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
    except ClientError as e:
        print("ERRO DELETE R2:", e)
        # mesmo assim vamos tentar remover do banco? aqui eu prefiro falhar
        raise HTTPException(status_code=500, detail="Erro ao excluir anexo no R2")

    db.delete(anexo)
    db.commit()
    return {"ok": True}

# =========================
# DASHBOARD / EXPORT
# =========================

@app.get("/dashboard/resumo")
def resumo_dashboard(
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    ate_vencimento: Optional[str] = Query(None),
):
    hoje = date.today()

    weekday = hoje.weekday()
    dias_ate_quarta = (2 - weekday) % 7
    if dias_ate_quarta == 0:
        dias_ate_quarta = 7
    prox_quarta = hoje + timedelta(days=dias_ate_quarta)

    query_base = db.query(FaturaDB)

    if transportadora:
        query_base = query_base.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

    if ate_vencimento:
        try:
            filtro_data = datetime.strptime(ate_vencimento, "%Y-%m-%d").date()
            query_base = query_base.filter(FaturaDB.data_vencimento <= filtro_data)
        except ValueError:
            pass

    total = query_base.with_entities(func.coalesce(func.sum(FaturaDB.valor), 0)).scalar()

    pendentes_val = (
        query_base.filter(FaturaDB.status.ilike("pendente"))
        .with_entities(func.coalesce(func.sum(FaturaDB.valor), 0))
        .scalar()
    )

    atrasadas_val = (
        query_base.filter(
            or_(
                FaturaDB.status.ilike("atrasado"),
                and_(
                    FaturaDB.status.ilike("pendente"),
                    FaturaDB.data_vencimento < prox_quarta,
                ),
            )
        )
        .with_entities(func.coalesce(func.sum(FaturaDB.valor), 0))
        .scalar()
    )

    em_dia_val = (
        query_base.filter(
            FaturaDB.status.ilike("pendente"),
            FaturaDB.data_vencimento == prox_quarta,
        )
        .with_entities(func.coalesce(func.sum(FaturaDB.valor), 0))
        .scalar()
    )

    return {
        "total": float(total or 0),
        "pendentes": float(pendentes_val or 0),
        "atrasadas": float(atrasadas_val or 0),
        "em_dia": float(em_dia_val or 0),
    }

@app.get("/faturas/exportar")
def exportar_faturas(
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
):
    import csv
    import io

    query = db.query(FaturaDB)
    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))
    if numero_fatura:
        query = query.filter(FaturaDB.numero_fatura.ilike(f"%{numero_fatura}%"))

    faturas = query.order_by(FaturaDB.id).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    writer.writerow(
        ["ID","Transportadora","Responsável","Número Fatura","Valor","Data Vencimento","Status","Observação"]
    )

    for f in faturas:
        writer.writerow(
            [
                f.id,
                f.transportadora,
                get_responsavel(f.transportadora) or "",
                str(f.numero_fatura),
                float(f.valor or 0),
                f.data_vencimento.strftime("%d/%m/%Y") if f.data_vencimento else "",
                f.status,
                f.observacao or "",
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8-sig")
    headers = {"Content-Disposition": 'attachment; filename="faturas.csv"'}
    return Response(csv_bytes, media_type="text/csv", headers=headers)
