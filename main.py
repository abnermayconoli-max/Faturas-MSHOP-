from datetime import date, datetime, timedelta
import os
import uuid
import base64
import json
import hmac
import hashlib
import secrets
import time
from typing import List, Optional, Tuple, Dict

from zoneinfo import ZoneInfo
from pathlib import Path

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    UploadFile,
    File,
    Query,
    Request,
    Form,
)
from fastapi.responses import (
    HTMLResponse,
    Response,
    StreamingResponse,
    RedirectResponse,
)
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

# ======================================================
# CONFIG BANCO
# ======================================================

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não configurada.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ======================================================
# STATIC / TEMPLATES
# ======================================================

def pick_dir(*names):
    for n in names:
        if Path(n).exists():
            return n
    return names[0]

STATIC_DIR = pick_dir("static", "estatico", "estático")
TEMPLATES_DIR = pick_dir("templates", "modelos")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ======================================================
# AUTH CONFIG
# ======================================================

DEBUG = os.getenv("DEBUG", "0") == "1"

SESSION_SECRET = os.getenv("SESSION_SECRET", "DEV_SECRET_CHANGE_ME")

COOKIE_NAME = "mshop_session"
CSRF_COOKIE = "mshop_csrf"
COOKIE_MAX_AGE = 60 * 60 * 12
CSRF_MAX_AGE = COOKIE_MAX_AGE
COOKIE_SECURE = not DEBUG

PBKDF2_ITERS = 260000
HASH_ALGO = "sha256"

BR_TZ = ZoneInfo("America/Sao_Paulo")

def agora_br():
    return datetime.now(BR_TZ)

# ======================================================
# MODELOS
# ======================================================

class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    email = Column(String)
    role = Column(String, default="user")

    pwd_salt = Column(String)
    pwd_hash = Column(String)

    must_change_password = Column(Integer, default=1)
    password_expires_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), default=agora_br)
    last_login_at = Column(DateTime(timezone=True))

class TransportadoraDB(Base):
    __tablename__ = "transportadoras"

    id = Column(Integer, primary_key=True)
    nome = Column(String, unique=True, index=True)
    responsavel_user_id = Column(Integer, ForeignKey("users.id"))

class FaturaDB(Base):
    __tablename__ = "faturas"

    id = Column(Integer, primary_key=True)
    transportadora = Column(String, index=True)
    numero_fatura = Column(String, index=True)
    valor = Column(Numeric(10, 2))
    data_vencimento = Column(Date)
    status = Column(String, default="pendente")
    observacao = Column(String)
    data_pagamento = Column(DateTime(timezone=True))

class HistoricoPagamentoDB(Base):
    __tablename__ = "historico_pagamentos"

    id = Column(Integer, primary_key=True)
    fatura_id = Column(Integer)
    pago_em = Column(DateTime(timezone=True))
    transportadora = Column(String)
    responsavel = Column(String)
    numero_fatura = Column(String)
    valor = Column(Numeric(10, 2))
    data_vencimento = Column(Date)

Base.metadata.create_all(bind=engine)

# ======================================================
# HELPERS
# ======================================================

def hash_password(password: str, salt: Optional[str] = None):
    if not salt:
        salt = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode()
    dk = hashlib.pbkdf2_hmac(
        HASH_ALGO,
        password.encode(),
        salt.encode(),
        PBKDF2_ITERS,
    )
    return salt, base64.urlsafe_b64encode(dk).decode()

def verify_password(password, salt, hash_):
    _, calc = hash_password(password, salt)
    return hmac.compare_digest(calc, hash_)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ======================================================
# PERFORMANCE FIX 1️⃣
# throttle update automático (5 minutos)
# ======================================================

_LAST_AUTO_UPDATE = 0
AUTO_UPDATE_INTERVAL = 300  # 5 minutos

def atualizar_status_automatico(db: Session):
    global _LAST_AUTO_UPDATE

    now = time.time()
    if now - _LAST_AUTO_UPDATE < AUTO_UPDATE_INTERVAL:
        return

    hoje = date.today()
    corte = hoje - timedelta(days=hoje.weekday() - 2)

    db.query(FaturaDB).filter(
        FaturaDB.status == "pendente",
        FaturaDB.data_vencimento <= corte,
    ).update(
        {FaturaDB.status: "atrasado"},
        synchronize_session=False,
    )
    db.commit()
    _LAST_AUTO_UPDATE = now

# ======================================================
# PERFORMANCE FIX 2️⃣
# cache de responsáveis (evita N+1)
# ======================================================

def carregar_responsaveis(db: Session) -> Dict[str, str]:
    data = (
        db.query(TransportadoraDB.nome, UserDB.username)
        .join(UserDB, TransportadoraDB.responsavel_user_id == UserDB.id)
        .all()
    )
    return {nome: user for nome, user in data}

# ======================================================
# APP
# ======================================================

app = FastAPI(title="Faturas MSHOP", version="2.1.0")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ======================================================
# ROTAS
# ======================================================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ======================================================
# API FATURAS
# ======================================================

class FaturaOut(BaseModel):
    id: int
    transportadora: str
    numero_fatura: str
    valor: float
    data_vencimento: date
    status: str
    responsavel: Optional[str]

@app.get("/faturas", response_model=List[FaturaOut])
def listar_faturas(
    request: Request,
    db: Session = Depends(get_db),
):
    atualizar_status_automatico(db)

    responsaveis = carregar_responsaveis(db)

    faturas = db.query(FaturaDB).order_by(FaturaDB.id).all()

    retorno = []
    for f in faturas:
        base = f.transportadora.split("-")[0].strip()
        retorno.append(
            {
                "id": f.id,
                "transportadora": f.transportadora,
                "numero_fatura": f.numero_fatura,
                "valor": float(f.valor or 0),
                "data_vencimento": f.data_vencimento,
                "status": f.status,
                "responsavel": responsaveis.get(base),
            }
        )

    return retorno

# ======================================================
# HISTÓRICO
# ======================================================

@app.get("/historico", response_model=List[dict])
def listar_historico(db: Session = Depends(get_db)):
    return db.query(HistoricoPagamentoDB).order_by(
        HistoricoPagamentoDB.pago_em.desc()
    ).all()

# ======================================================
# HEALTH
# ======================================================

@app.get("/health")
def health():
    return {"status": "ok"}
