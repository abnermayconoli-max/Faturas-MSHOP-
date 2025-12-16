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
from fastapi.responses import StreamingResponse  # <<< NOVO (para baixar do R2)
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

import boto3  # <<< NOVO (R2)
from botocore.exceptions import ClientError  # <<< NOVO (R2)
from botocore.config import Config  # <<< NOVO (R2)  ✅ ALTERAÇÃO

# =========================
# CONFIG BANCO DE DADOS
# =========================

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não configurada nas variáveis de ambiente do Render.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Pasta para anexos (no disco do container) - mantida por compatibilidade
ANEXOS_DIR = "anexos"
os.makedirs(ANEXOS_DIR, exist_ok=True)

# =========================
# CONFIG R2 (Cloudflare)
# =========================
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")

if not all([R2_ENDPOINT, R2_BUCKET_NAME, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
    raise RuntimeError(
        "R2 não configurado. Verifique as env vars: "
        "R2_ENDPOINT, R2_BUCKET_NAME, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY"
    )

# ✅ ALTERAÇÃO: força S3v4 + path style (mais compatível com R2)
s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
    ),
)

def _r2_key(fatura_id: int, original_filename: str) -> str:
    safe_name = (original_filename or "arquivo").replace("/", "_").replace("\\", "_")
    return f"anexos/{fatura_id}/{uuid.uuid4().hex}_{safe_name}"

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
    filename = Column(String)       # <<< agora guarda a KEY do R2
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
    de_vencimento: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
):
    query = db.query(FaturaDB)

    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

    # Filtro por vencimento (DE / ATÉ)
    if de_vencimento:
        try:
            data_de = datetime.strptime(de_vencimento, "%Y-%m-%d").date()
            query = query.filter(FaturaDB.data_vencimento >= data_de)
        except ValueError:
            pass

    if ate_vencimento:
        try:
            data_ate = datetime.strptime(ate_vencimento, "%Y-%m-%d").date()
            query = query.filter(FaturaDB.data_vencimento <= data_ate)
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

    # Remove arquivos do R2 (em vez do disco)
    for anexo in fatura.anexos:
        try:
            s3.delete_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
        except ClientError as e:
            print("ERRO AO APAGAR NO R2:", repr(e))

    db.delete(fatura)
    db.commit()
    return {"ok": True}

# =========================
# ANEXOS
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
        key = _r2_key(fatura_id, file.filename)

        try:
            content = await file.read()
            s3.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=key,
                Body=content,
                ContentType=file.content_type or "application/octet-stream",
            )

        # ✅ ALTERAÇÃO: mostra o erro real (Code/Message)
        except ClientError as e:
            err = getattr(e, "response", {}) or {}
            code = (((err.get("Error") or {}).get("Code")) or "")
            msg = (((err.get("Error") or {}).get("Message")) or "")
            print("ERRO UPLOAD R2:", repr(e), "CODE=", code, "MSG=", msg)

            raise HTTPException(
                status_code=400,
                detail=f"Erro ao enviar anexo para o R2: {code} - {msg}".strip(" -")
            )
        finally:
            await file.close()

        anexo_db = AnexoDB(
            fatura_id=fatura_id,
            filename=key,  # <<< salva a KEY do R2
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
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    try:
        obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
        body = obj["Body"]
        content_type = obj.get("ContentType") or anexo.content_type or "application/octet-stream"
    except ClientError as e:
        print("ERRO DOWNLOAD R2:", repr(e))
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no R2")

    headers = {
        "Content-Disposition": f'attachment; filename="{anexo.original_name}"'
    }
    return StreamingResponse(body, media_type=content_type, headers=headers)

@app.delete("/anexos/{anexo_id}")
def deletar_anexo(anexo_id: int, db: Session = Depends(get_db)):
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    # apaga do R2
    try:
        s3.delete_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
    except ClientError as e:
        print("ERRO AO APAGAR NO R2:", repr(e))

    # apaga do banco
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
    de_vencimento: Optional[str] = Query(None),
):
    """
    Regra ajustada para bater com o Dashboard (tabela):

    - TOTAL       = soma de todos os valores filtrados
    - PENDENTES   = todas as faturas com status 'pendente'
    - ATRASADAS   = faturas com:
        * status 'atrasado'
          OU
        * status 'pendente' e vencimento < próxima quarta
    - EM DIA      = faturas com status 'pendente' e vencimento == próxima quarta
    """

    hoje = date.today()

    # ✅ ALTERAÇÃO AQUI:
    # Próxima quarta COM CORTE:
    # se faltar 0, 1 ou 2 dias pra quarta, pula para a próxima (+7)
    weekday = hoje.weekday()  # seg=0, ter=1, qua=2...
    dias_ate_quarta = (2 - weekday) % 7
    prox_quarta = hoje + timedelta(days=dias_ate_quarta)

    if (prox_quarta - hoje).days <= 2:
        prox_quarta = prox_quarta + timedelta(days=7)

    query_base = db.query(FaturaDB)

    if transportadora:
        query_base = query_base.filter(
            FaturaDB.transportadora.ilike(f"%{transportadora}%")
        )

    # Filtro por vencimento (DE / ATÉ)
    if de_vencimento:
        try:
            data_de = datetime.strptime(de_vencimento, "%Y-%m-%d").date()
            query_base = query_base.filter(FaturaDB.data_vencimento >= data_de)
        except ValueError:
            pass

    if ate_vencimento:
        try:
            data_ate = datetime.strptime(ate_vencimento, "%Y-%m-%d").date()
            query_base = query_base.filter(FaturaDB.data_vencimento <= data_ate)
        except ValueError:
            pass

    total = query_base.with_entities(
        func.coalesce(func.sum(FaturaDB.valor), 0)
    ).scalar()

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
    """
    Exporta CSV (Excel abre normal).
    """
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
        [
            "ID",
            "Transportadora",
            "Responsável",
            "Número Fatura",
            "Valor",
            "Data Vencimento",
            "Status",
            "Observação",
        ]
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
    headers = {
        "Content-Disposition": 'attachment; filename="faturas.csv"'
    }
    return Response(csv_bytes, media_type="text/csv", headers=headers)
