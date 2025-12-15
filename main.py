from datetime import date, datetime, timedelta
import os
import uuid
from typing import List, Optional

import boto3
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
from fastapi.responses import HTMLResponse, Response, StreamingResponse
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
# CONFIG CLOUDFLARE R2
# =========================

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")

def _require_r2():
    missing = []
    if not R2_ACCOUNT_ID: missing.append("R2_ACCOUNT_ID")
    if not R2_ACCESS_KEY: missing.append("R2_ACCESS_KEY")
    if not R2_SECRET_KEY: missing.append("R2_SECRET_KEY")
    if not R2_BUCKET_NAME: missing.append("R2_BUCKET_NAME")
    if missing:
        raise RuntimeError(f"Variáveis R2 faltando: {', '.join(missing)}")

def get_s3_client():
    _require_r2()
    endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        region_name="auto",
    )

def r2_upload_bytes(storage_key: str, content_bytes: bytes, content_type: str):
    s3 = get_s3_client()
    s3.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=storage_key,
        Body=content_bytes,
        ContentType=content_type or "application/octet-stream",
    )

def r2_delete(storage_key: str):
    s3 = get_s3_client()
    s3.delete_object(Bucket=R2_BUCKET_NAME, Key=storage_key)

def r2_get_stream(storage_key: str):
    s3 = get_s3_client()
    obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=storage_key)
    return obj["Body"]  # StreamingBody

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

    # ✅ AGORA: caminho do arquivo no R2
    storage_key = Column(String, nullable=False)

    original_name = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
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

    # ✅ apaga anexos do R2 antes de apagar a fatura
    for anexo in list(fatura.anexos):
        try:
            r2_delete(anexo.storage_key)
        except Exception as e:
            print("ERRO AO APAGAR NO R2:", repr(e), "storage_key=", anexo.storage_key)

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

    anexos_criados: List[AnexoDB] = []

    for file in files:
        # chave no R2 (organizado por fatura)
        storage_key = f"faturas/{fatura_id}/{uuid.uuid4().hex}_{file.filename}"

        content = await file.read()
        if not content:
            continue

        try:
            r2_upload_bytes(storage_key, content, file.content_type or "application/octet-stream")
        except Exception as e:
            print("ERRO UPLOAD R2:", repr(e))
            raise HTTPException(status_code=500, detail="Erro ao enviar anexo")

        anexo_db = AnexoDB(
            fatura_id=fatura_id,
            storage_key=storage_key,
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
    ✅ Download direto (força baixar, não abrir em aba).
    Mantive a mesma rota /anexos/{id} pra não quebrar seu app.js.
    """
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    try:
        stream = r2_get_stream(anexo.storage_key)
    except ClientError:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no storage")
    except Exception as e:
        print("ERRO BAIXAR R2:", repr(e))
        raise HTTPException(status_code=500, detail="Erro ao baixar anexo")

    return StreamingResponse(
        stream,
        media_type=anexo.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{anexo.original_name}"'
        },
    )

@app.delete("/anexos/{anexo_id}")
def deletar_anexo(anexo_id: int, db: Session = Depends(get_db)):
    """
    ✅ Botão Excluir anexo: apaga do R2 e remove do banco
    """
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    try:
        r2_delete(anexo.storage_key)
    except Exception as e:
        print("ERRO AO APAGAR NO R2:", repr(e), "storage_key=", anexo.storage_key)
        # mesmo assim, pode deletar do banco se você preferir:
        # raise HTTPException(500, "Erro ao excluir arquivo no storage")

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

    # próxima quarta-feira (seg=0, ter=1, qua=2)
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
        ["ID", "Transportadora", "Responsável", "Número Fatura", "Valor", "Data Vencimento", "Status", "Observação"]
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
