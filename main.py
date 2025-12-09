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
)
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
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

# Pasta para anexos
ANEXOS_DIR = "anexos"
os.makedirs(ANEXOS_DIR, exist_ok=True)

# =========================
# MODELO SQLALCHEMY
# =========================


class FaturaDB(Base):
    __tablename__ = "faturas"

    id = Column(Integer, primary_key=True, index=True)
    transportadora = Column(String, index=True)
    numero_fatura = Column(String, index=True)
    valor = Column(Numeric(10, 2))
    data_vencimento = Column(Date)
    status = Column(String, default="pendente")
    responsavel = Column(String, nullable=True)
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
    filename = Column(String)       # nome salvo no disco
    original_name = Column(String)  # nome do arquivo que o usuário enviou
    content_type = Column(String)
    criado_em = Column(Date, default=date.today)

    fatura = relationship("FaturaDB", back_populates="anexos")


# Cria tabelas (se não existirem)
Base.metadata.create_all(bind=engine)


# =========================
# Pydantic
# =========================
# IMPORTANTE:
# Aqui está a mudança principal para evitar o erro ao listar faturas
# que possuem campos nulos no banco.


class FaturaBase(BaseModel):
    # Para leitura, deixamos opcional para não quebrar se houver nulos no banco
    transportadora: Optional[str] = None
    numero_fatura: Optional[str] = None
    valor: Optional[float] = None
    data_vencimento: Optional[date] = None
    status: Optional[str] = "pendente"
    observacao: Optional[str] = None


class FaturaCreate(BaseModel):
    # Para criação, continuamos exigindo os campos obrigatórios
    transportadora: str
    numero_fatura: str
    valor: float
    data_vencimento: date
    status: str = "pendente"
    observacao: Optional[str] = None


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
    # Tenta bater nome exato, depois só primeira parte
    if transportadora in RESP_MAP:
        return RESP_MAP[transportadora]
    base = transportadora.split("-")[0].strip()
    return RESP_MAP.get(base)


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
    version="0.4.1",
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
    responsavel = get_responsavel(fatura.transportadora)

    db_fatura = FaturaDB(
        transportadora=fatura.transportadora,
        numero_fatura=fatura.numero_fatura,
        valor=fatura.valor,
        data_vencimento=fatura.data_vencimento,
        status=fatura.status,
        observacao=fatura.observacao,
        responsavel=responsavel,
    )
    db.add(db_fatura)
    db.commit()
    db.refresh(db_fatura)
    return db_fatura


@app.get("/faturas", response_model=List[FaturaOut])
def listar_faturas(
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    ate_vencimento: Optional[str] = Query(None),  # string vinda da URL
    numero_fatura: Optional[str] = Query(None),
):
    """
    Lista faturas com filtros opcionais:
    - transportadora (contains)
    - ate_vencimento (data vencimento <=, se informado no formato AAAA-MM-DD)
    - numero_fatura (contains)
    """
    query = db.query(FaturaDB)

    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

    # trata a data manualmente para evitar erro 422
    if ate_vencimento:
        try:
            filtro_data = datetime.strptime(ate_vencimento, "%Y-%m-%d").date()
            query = query.filter(FaturaDB.data_vencimento <= filtro_data)
        except ValueError:
            # se a data vier em formato estranho, simplesmente ignora o filtro
            pass

    if numero_fatura:
        query = query.filter(FaturaDB.numero_fatura.ilike(f"%{numero_fatura}%"))

    query = query.order_by(FaturaDB.id)
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

    data = dados.dict(exclude_unset=True)

    for campo, valor in data.items():
        setattr(fatura, campo, valor)

    # Se mudar transportadora, recalcula responsável
    if "transportadora" in data:
        fatura.responsavel = get_responsavel(fatura.transportadora)

    db.commit()
    db.refresh(fatura)
    return fatura


@app.delete("/faturas/{fatura_id}")
def deletar_fatura(fatura_id: int, db: Session = Depends(get_db)):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    # Remove arquivos do disco
    for anexo in fatura.anexos:
        caminho = os.path.join(ANEXOS_DIR, anexo.filename)
        if os.path.exists(caminho):
            os.remove(caminho)

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
        unique_name = f"{uuid.uuid4().hex}_{file.filename}"
        caminho = os.path.join(ANEXOS_DIR, unique_name)

        with open(caminho, "wb") as f:
            f.write(await file.read())

        anexo_db = AnexoDB(
            fatura_id=fatura_id,
            filename=unique_name,
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

    caminho = os.path.join(ANEXOS_DIR, anexo.filename)
    if not os.path.exists(caminho):
        raise HTTPException(status_code=404, detail="Arquivo físico não encontrado")

    return FileResponse(
        caminho,
        media_type=anexo.content_type,
        filename=anexo.original_name,
    )


# =========================
# DASHBOARD / EXPORT
# =========================

@app.get("/dashboard/resumo")
def resumo_dashboard(
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
):
    """
    Se receber ?transportadora=DHL, calcula só daquela transportadora.
    Sem parâmetro, calcula geral.
    """
    hoje = date.today()
    query = db.query(FaturaDB)

    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))

    total = query.with_entities(
        func.coalesce(func.sum(FaturaDB.valor), 0)
    ).scalar()

    pendentes_val = (
        query.session.query(func.coalesce(func.sum(FaturaDB.valor), 0))
        .filter(FaturaDB.status.ilike("pendente"))
        .scalar()
    )

    atrasadas_val = (
        query.session.query(func.coalesce(func.sum(FaturaDB.valor), 0))
        .filter(FaturaDB.status.ilike("pendente"), FaturaDB.data_vencimento < hoje)
        .scalar()
    )

    em_dia_val = (
        query.session.query(func.coalesce(func.sum(FaturaDB.valor), 0))
        .filter(FaturaDB.status.ilike("pendente"), FaturaDB.data_vencimento >= hoje)
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
                f.responsavel or "",
                str(f.numero_fatura) if f.numero_fatura is not None else "",
                float(f.valor or 0),
                f.data_vencimento.strftime("%d/%m/%Y") if f.data_vencimento else "",
                f.status or "",
                f.observacao or "",
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8-sig")
    headers = {
        "Content-Disposition": 'attachment; filename="faturas.csv"'
    }
    return Response(csv_bytes, media_type="text/csv", headers=headers)
