from datetime import date, datetime, timedelta
import os
import uuid
from typing import List, Optional

from zoneinfo import ZoneInfo  # ✅ fuso

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
    DateTime,
    Numeric,
    ForeignKey,
    func,
    and_,
    or_,
    text,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

# =========================
# CONFIG BANCO
# =========================

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não configurada nas variáveis de ambiente do Render.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# =========================
# CONFIG R2
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
# FUSO HORÁRIO (BR)
# =========================

BR_TZ = ZoneInfo(os.getenv("APP_TZ", "America/Sao_Paulo"))

def agora_br() -> datetime:
    # datetime com timezone (aware)
    return datetime.now(BR_TZ)

def hoje_local_br() -> date:
    return agora_br().date()

# =========================
# MODELOS
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

    # ✅ salva a data/hora do pagamento com fuso (TIMESTAMPTZ no Postgres)
    data_pagamento = Column(DateTime(timezone=True), nullable=True)

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
    filename = Column(String)       # KEY do R2
    original_name = Column(String)  # nome original
    content_type = Column(String)
    criado_em = Column(Date, default=date.today)

    fatura = relationship("FaturaDB", back_populates="anexos")

class HistoricoPagamentoDB(Base):
    __tablename__ = "historico_pagamentos"

    id = Column(Integer, primary_key=True, index=True)
    fatura_id = Column(Integer, ForeignKey("faturas.id", ondelete="CASCADE"), index=True)

    # ✅ TIMESTAMPTZ
    pago_em = Column(DateTime(timezone=True), nullable=False)

    transportadora = Column(String, nullable=False)
    responsavel = Column(String, nullable=True)
    numero_fatura = Column(String, nullable=False)
    valor = Column(Numeric(10, 2), nullable=False)
    data_vencimento = Column(Date, nullable=False)

# cria tabelas básicas (não resolve alteração de tipo, por isso tem ensure_schema abaixo)
Base.metadata.create_all(bind=engine)

# =========================
# ✅ MIGRAÇÃO AUTOMÁTICA (Render)
#   - garante TIMESTAMPTZ nas colunas
#   - cria tabela de histórico
#   - evita erro "UndefinedColumn"
# =========================

def ensure_schema():
    """
    Garante TIMESTAMPTZ (com fuso) nas datas de pagamento.
    Também converte coluna antiga TIMESTAMP (sem fuso) assumindo UTC.
    """
    with engine.begin() as conn:
        # --- faturas.data_pagamento ---
        conn.execute(text("ALTER TABLE faturas ADD COLUMN IF NOT EXISTS data_pagamento TIMESTAMPTZ;"))
        # se já existia como TIMESTAMP sem fuso, converte assumindo UTC
        try:
            conn.execute(text("""
                ALTER TABLE faturas
                ALTER COLUMN data_pagamento TYPE TIMESTAMPTZ
                USING (data_pagamento AT TIME ZONE 'UTC');
            """))
        except Exception as e:
            print("WARN schema: alter faturas.data_pagamento -> timestamptz:", repr(e))

        # --- historico_pagamentos ---
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS historico_pagamentos (
                id SERIAL PRIMARY KEY,
                fatura_id INTEGER NOT NULL REFERENCES faturas(id) ON DELETE CASCADE,
                pago_em TIMESTAMPTZ NOT NULL,
                transportadora TEXT NOT NULL,
                responsavel TEXT,
                numero_fatura TEXT NOT NULL,
                valor NUMERIC(10,2) NOT NULL,
                data_vencimento DATE NOT NULL
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_historico_pagamentos_fatura_id ON historico_pagamentos(fatura_id);"))

        # se a tabela existia com TIMESTAMP sem fuso, converte assumindo UTC
        try:
            conn.execute(text("""
                ALTER TABLE historico_pagamentos
                ALTER COLUMN pago_em TYPE TIMESTAMPTZ
                USING (pago_em AT TIME ZONE 'UTC');
            """))
        except Exception as e:
            print("WARN schema: alter historico_pagamentos.pago_em -> timestamptz:", repr(e))

# roda a migração ao subir
ensure_schema()

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
        from_attributes = True

class FaturaOut(FaturaBase):
    id: int
    responsavel: Optional[str] = None
    data_pagamento: Optional[datetime] = None  # ✅ retorna pro front se quiser

    class Config:
        from_attributes = True

class HistoricoPagamentoOut(BaseModel):
    id: int
    fatura_id: int
    pago_em: datetime
    transportadora: str
    responsavel: Optional[str] = None
    numero_fatura: str
    valor: float
    data_vencimento: date

    class Config:
        from_attributes = True

# =========================
# RESPONSÁVEL
# =========================

RESP_MAP = {
    "DHL": "Gabrielly",
    "Pannan": "Gabrielly",
    "Garcia": "Juliana",
    "Excargo": "Juliana",
    "Transbritto": "Larissa",
    "PDA": "Larissa",
    "GLM": "Larissa",
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
        data_pagamento=f.data_pagamento,
    )

# =========================
# ✅ REGRA AUTOMÁTICA (atraso)
#   Corte = QUARTA-FEIRA da semana atual (semana começa SEG)
# =========================

def quarta_da_semana_atual(hoje: date) -> date:
    monday = hoje - timedelta(days=hoje.weekday())
    return monday + timedelta(days=2)

def atualizar_status_automatico(db: Session):
    """
    Atualiza:
      pendente -> atrasado
    Regra:
      se data_vencimento <= quarta_da_semana_atual
    """
    hoje = hoje_local_br()
    corte = quarta_da_semana_atual(hoje)

    q = (
        db.query(FaturaDB)
        .filter(FaturaDB.status.ilike("pendente"))
        .filter(FaturaDB.data_vencimento <= corte)
    )

    alteradas = q.update({FaturaDB.status: "atrasado"}, synchronize_session=False)
    if alteradas:
        db.commit()

# =========================
# ✅ HISTÓRICO DE PAGAMENTO
# =========================

def registrar_pagamento(db: Session, fatura: FaturaDB):
    """
    Quando a fatura vira PAGO:
      - define data_pagamento = agora_br()
      - cria um registro no historico_pagamentos
    """
    pago_em = agora_br()
    fatura.data_pagamento = pago_em

    hist = HistoricoPagamentoDB(
        fatura_id=fatura.id,
        pago_em=pago_em,
        transportadora=fatura.transportadora,
        responsavel=get_responsavel(fatura.transportadora),
        numero_fatura=fatura.numero_fatura,
        valor=fatura.valor or 0,
        data_vencimento=fatura.data_vencimento,
    )
    db.add(hist)

def remover_historico_pagamento(db: Session, fatura_id: int):
    """
    Se alguém voltar status de PAGO para PENDENTE/ATRASADO,
    remove todos os registros do histórico dessa fatura e limpa data_pagamento.
    """
    db.query(HistoricoPagamentoDB).filter(HistoricoPagamentoDB.fatura_id == fatura_id).delete(synchronize_session=False)

# =========================
# DEPENDÊNCIA DB
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

app = FastAPI(title="Sistema de Faturas", version="1.0.0")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
def health_check():
    return {"status": "ok"}

# =========================
# FATURAS
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

        # se já cria como pago, registra
        if (fatura.status or "").lower() == "pago":
            registrar_pagamento(db, db_fatura)

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
    atualizar_status_automatico(db)

    query = db.query(FaturaDB)

    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

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

    faturas_db = query.order_by(FaturaDB.id).all()
    return [fatura_to_out(f) for f in faturas_db]

@app.put("/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(fatura_id: int, dados: FaturaUpdate, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    status_antigo = (fatura.status or "").lower()

    data = dados.dict(exclude_unset=True)
    for campo, valor in data.items():
        setattr(fatura, campo, valor)

    status_novo = (fatura.status or "").lower()

    # ✅ se virou pago agora, registra histórico e grava data/hora
    if status_antigo != "pago" and status_novo == "pago":
        registrar_pagamento(db, fatura)

    # ✅ se era pago e deixou de ser pago, remove histórico e limpa data_pagamento
    if status_antigo == "pago" and status_novo != "pago":
        remover_historico_pagamento(db, fatura.id)
        fatura.data_pagamento = None

    db.commit()
    db.refresh(fatura)
    return fatura_to_out(fatura)

@app.delete("/faturas/{fatura_id}")
def deletar_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    for anexo in fatura.anexos:
        try:
            s3.delete_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
        except ClientError as e:
            print("ERRO AO APAGAR NO R2:", repr(e))

    # remove histórico também (FK cascade normalmente já remove, mas garante)
    remover_historico_pagamento(db, fatura.id)

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
            filename=key,
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

    headers = {"Content-Disposition": f'attachment; filename="{anexo.original_name}"'}
    return StreamingResponse(body, media_type=content_type, headers=headers)

@app.delete("/anexos/{anexo_id}")
def deletar_anexo(anexo_id: int, db: Session = Depends(get_db)):
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    try:
        s3.delete_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
    except ClientError as e:
        print("ERRO AO APAGAR NO R2:", repr(e))

    db.delete(anexo)
    db.commit()
    return {"ok": True}

# =========================
# DASHBOARD
# =========================

@app.get("/dashboard/resumo")
def resumo_dashboard(
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    ate_vencimento: Optional[str] = Query(None),
    de_vencimento: Optional[str] = Query(None),
):
    atualizar_status_automatico(db)

    hoje = hoje_local_br()
    corte = quarta_da_semana_atual(hoje)

    query_base = db.query(FaturaDB)

    if transportadora:
        query_base = query_base.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

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

    total_pago = (
        query_base.filter(FaturaDB.status.ilike("pago"))
        .with_entities(func.coalesce(func.sum(FaturaDB.valor), 0))
        .scalar()
    )

    # atrasado = (status atrasado) + (pendente com venc <= corte)
    total_atrasado = (
        query_base.filter(
            or_(
                FaturaDB.status.ilike("atrasado"),
                and_(
                    FaturaDB.status.ilike("pendente"),
                    FaturaDB.data_vencimento <= corte,
                ),
            )
        )
        .with_entities(func.coalesce(func.sum(FaturaDB.valor), 0))
        .scalar()
    )

    # em dia = pendente com venc > corte
    total_em_dia = (
        query_base.filter(
            and_(
                FaturaDB.status.ilike("pendente"),
                FaturaDB.data_vencimento > corte,
            )
        )
        .with_entities(func.coalesce(func.sum(FaturaDB.valor), 0))
        .scalar()
    )

    total_geral = float(total_atrasado or 0) + float(total_em_dia or 0)

    return {
        "total_geral": float(total_geral),
        "total_em_dia": float(total_em_dia or 0),
        "total_atrasado": float(total_atrasado or 0),
        "total_pago": float(total_pago or 0),
    }

# =========================
# HISTÓRICO (API)
# =========================

@app.get("/historico_pagamentos", response_model=List[HistoricoPagamentoOut])
def listar_historico_pagamentos(
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    de: Optional[str] = Query(None),   # yyyy-mm-dd
    ate: Optional[str] = Query(None),  # yyyy-mm-dd
):
    q = db.query(HistoricoPagamentoDB)

    if transportadora:
        q = q.filter(HistoricoPagamentoDB.transportadora.ilike(f"%{transportadora}%"))

    if de:
        try:
            dt = datetime.strptime(de, "%Y-%m-%d").date()
            q = q.filter(func.date(HistoricoPagamentoDB.pago_em) >= dt)
        except ValueError:
            pass

    if ate:
        try:
            dt = datetime.strptime(ate, "%Y-%m-%d").date()
            q = q.filter(func.date(HistoricoPagamentoDB.pago_em) <= dt)
        except ValueError:
            pass

    itens = q.order_by(HistoricoPagamentoDB.pago_em.desc()).all()
    return [
        HistoricoPagamentoOut(
            id=i.id,
            fatura_id=i.fatura_id,
            pago_em=i.pago_em,  # ✅ vem com fuso correto do Postgres
            transportadora=i.transportadora,
            responsavel=i.responsavel,
            numero_fatura=i.numero_fatura,
            valor=float(i.valor or 0),
            data_vencimento=i.data_vencimento,
        )
        for i in itens
    ]

# =========================
# EXPORT CSV
# =========================

@app.get("/faturas/exportar")
def exportar_faturas(
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
):
    atualizar_status_automatico(db)

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
            "Data Pagamento (BR)",
            "Observação",
        ]
    )

    for f in faturas:
        # se vier timezone do DB, mantém e converte BR (por garantia)
        pago_em = ""
        if f.data_pagamento:
            try:
                pago_em = f.data_pagamento.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                pago_em = str(f.data_pagamento)

        writer.writerow(
            [
                f.id,
                f.transportadora,
                get_responsavel(f.transportadora) or "",
                str(f.numero_fatura),
                float(f.valor or 0),
                f.data_vencimento.strftime("%d/%m/%Y") if f.data_vencimento else "",
                f.status,
                pago_em,
                f.observacao or "",
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8-sig")
    headers = {"Content-Disposition": 'attachment; filename="faturas.csv"'}
    return Response(csv_bytes, media_type="text/csv", headers=headers)
