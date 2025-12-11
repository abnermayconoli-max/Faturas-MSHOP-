from datetime import date, datetime
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
    LargeBinary,  # <- NOVO
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

# Pasta para anexos (não usamos mais para salvar, mas pode ficar se quiser)
ANEXOS_DIR = "anexos"
os.makedirs(ANEXOS_DIR, exist_ok=True)

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
    # filename mantido por compatibilidade, mas não é mais usado
    filename = Column(String, nullable=True)
    original_name = Column(String)  # nome que o usuário enviou
    content_type = Column(String)
    # dados binários do arquivo, guardados no Postgres
    dados = Column(LargeBinary, nullable=False)  # NOVO
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
    # primeiro tenta o nome exato, depois só a primeira parte antes do "-"
    if transportadora in RESP_MAP:
        return RESP_MAP[transportadora]
    base = transportadora.split("-")[0].strip()
    return RESP_MAP.get(base)


# helper para transformar FaturaDB -> FaturaOut
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

# /static -> arquivos estáticos (css/js)
app.mount("/static", StaticFiles(directory="static"), name="static")

# / -> template Jinja
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
    """
    Cria uma fatura.
    """
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
    ate_vencimento: Optional[str] = Query(None),  # string yyyy-mm-dd
    numero_fatura: Optional[str] = Query(None),
):
    """
    Lista faturas com filtros opcionais.
    """
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

    # anexos serão apagados automaticamente pelo cascade/ON DELETE CASCADE
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
    """
    Salva anexos diretamente no banco (campo bytea).
    """
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    anexos_criados: List[AnexoDB] = []

    for file in files:
        conteudo = await file.read()

        anexo_db = AnexoDB(
            fatura_id=fatura_id,
            filename=None,
            original_name=file.filename,
            content_type=file.content_type or "application/octet-stream",
            dados=conteudo,
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
    Retorna o arquivo salvo no banco.
    """
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    if not anexo.dados:
        raise HTTPException(status_code=404, detail="Arquivo físico não encontrado")

    headers = {
        "Content-Disposition": f'attachment; filename="{anexo.original_name}"'
    }
    return Response(anexo.dados, media_type=anexo.content_type, headers=headers)


@app.delete("/anexos/{anexo_id}")
def deletar_anexo(anexo_id: int, db: Session = Depends(get_db)):
    """
    Exclui um anexo específico (usado no modal).
    """
    anexo = db.query(AnexoDB).filter(AnexoDB.id == anexo_id).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

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
    """
    Resumo (total/pendentes/atrasadas/em dia).
    Se vier transportadora/ate_vencimento, aplica filtro como no /faturas.
    """
    hoje = date.today()
    query_base = db.query(FaturaDB)

    if transportadora:
        query_base = query_base.filter(
            FaturaDB.transportadora.ilike(f"%{transportadora}%")
        )

    if ate_vencimento:
        try:
            filtro_data = datetime.strptime(ate_vencimento, "%Y-%m-%d").date()
            query_base = query_base.filter(FaturaDB.data_vencimento <= filtro_data)
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
            FaturaDB.status.ilike("pendente"),
            FaturaDB.data_vencimento < hoje,
        )
        .with_entities(func.coalesce(func.sum(FaturaDB.valor), 0))
        .scalar()
    )

    em_dia_val = (
        query_base.filter(
            FaturaDB.status.ilike("pendente"),
            FaturaDB.data_vencimento >= hoje,
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
