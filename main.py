from datetime import date, datetime, timedelta
import os
import uuid
import base64
import json
import hmac
import hashlib
import secrets
from typing import List, Optional, Tuple

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
from fastapi.responses import HTMLResponse, Response, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware  # ✅ NOVO (opcional)

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
# ✅ DETECTA PASTAS (static/templates vs estático/modelos)
# =========================

def pick_dir(*candidates: str) -> str:
    for c in candidates:
        if Path(c).exists() and Path(c).is_dir():
            return c
    return candidates[0]

STATIC_DIR = pick_dir("static", "estático", "estatico")
TEMPLATES_DIR = pick_dir("templates", "modelos")

def pick_tpl(*candidates: str) -> str:
    for c in candidates:
        if (Path(TEMPLATES_DIR) / c).exists():
            return c
    return candidates[0]

TPL_LOGIN  = pick_tpl("login.html")
TPL_INDEX  = pick_tpl("index.html")
TPL_ADMIN  = pick_tpl("admin.html")
TPL_CHANGE = pick_tpl("change.html", "alterar_senha.html", "change_password.html", "alterar_senha.html")
TPL_FORGOT = pick_tpl("forgot.html", "esqueci.html", "esqueci.html")
TPL_RESET  = pick_tpl("reset.html")

# =========================
# CONFIG AUTH / SEGURANÇA
# =========================

DEBUG = os.getenv("DEBUG", "0").strip() == "1"

SESSION_SECRET = os.getenv("SESSION_SECRET") or os.getenv("JWT_SECRET")
if not SESSION_SECRET:
    print("WARN: SESSION_SECRET/JWT_SECRET não configurado. Configure no Render para login funcionar com segurança.")
    SESSION_SECRET = "DEV_ONLY_CHANGE_ME"

COOKIE_NAME = "mshop_session"
CSRF_COOKIE = "mshop_csrf"
COOKIE_MAX_AGE_SECONDS = 60 * 60 * 12
CSRF_MAX_AGE_SECONDS = 60 * 60 * 12

PBKDF2_ITERS = int(os.getenv("PBKDF2_ITERS", "260000"))
HASH_ALGO = "sha256"

PWD_EXP_FIRST_DAYS = 90
PWD_EXP_NEXT_DAYS = 180

BOOTSTRAP_ADMIN_USER = os.getenv("BOOTSTRAP_ADMIN_USER", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip() or None

COOKIE_SECURE = False if DEBUG else True

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
    return datetime.now(BR_TZ)

def hoje_local_br() -> date:
    return agora_br().date()

# =========================
# MODELOS FATURAS
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

    pago_em = Column(DateTime(timezone=True), nullable=False)

    transportadora = Column(String, nullable=False)
    responsavel = Column(String, nullable=True)
    numero_fatura = Column(String, nullable=False)
    valor = Column(Numeric(10, 2), nullable=False)
    data_vencimento = Column(Date, nullable=False)

# =========================
# MODELOS AUTH / ADMIN
# =========================

class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, nullable=True)

    role = Column(String, default="user")  # admin/user

    pwd_salt = Column(String, nullable=True)
    pwd_hash = Column(String, nullable=True)

    must_change_password = Column(Integer, default=1)
    first_password_changed_at = Column(DateTime(timezone=True), nullable=True)
    last_password_changed_at = Column(DateTime(timezone=True), nullable=True)
    password_expires_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=agora_br)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

class TransportadoraDB(Base):
    __tablename__ = "transportadoras"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, index=True, nullable=False)

    responsavel_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    responsavel = relationship("UserDB", foreign_keys=[responsavel_user_id])

class PasswordResetDB(Base):
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

Base.metadata.create_all(bind=engine)

# =========================
# ✅ MIGRAÇÃO AUTOMÁTICA (Render)
# =========================

def ensure_schema():
    with engine.begin() as conn:
        # --- faturas
        conn.execute(text("ALTER TABLE faturas ADD COLUMN IF NOT EXISTS observacao TEXT;"))
        conn.execute(text("ALTER TABLE faturas ADD COLUMN IF NOT EXISTS data_pagamento TIMESTAMPTZ;"))
        try:
            conn.execute(text("""
                ALTER TABLE faturas
                ALTER COLUMN data_pagamento TYPE TIMESTAMPTZ
                USING (data_pagamento AT TIME ZONE 'UTC');
            """))
        except Exception as e:
            print("WARN schema: alter faturas.data_pagamento -> timestamptz:", repr(e))

        # --- anexos
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS anexos (
                id SERIAL PRIMARY KEY,
                fatura_id INTEGER REFERENCES faturas(id) ON DELETE CASCADE,
                filename TEXT,
                original_name TEXT,
                content_type TEXT,
                criado_em DATE DEFAULT CURRENT_DATE
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_anexos_fatura_id ON anexos(fatura_id);"))

        # --- historico_pagamentos
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
        try:
            conn.execute(text("""
                ALTER TABLE historico_pagamentos
                ALTER COLUMN pago_em TYPE TIMESTAMPTZ
                USING (pago_em AT TIME ZONE 'UTC');
            """))
        except Exception as e:
            print("WARN schema: alter historico_pagamentos.pago_em -> timestamptz:", repr(e))

        # --- users (garante existência e colunas)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);"))

        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'user';"))

        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pwd_salt TEXT;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pwd_hash TEXT;"))

        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER DEFAULT 1;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_password_changed_at TIMESTAMPTZ;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_password_changed_at TIMESTAMPTZ;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_expires_at TIMESTAMPTZ;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;"))

        # --- transportadoras (CRIA e também ALTERA se já existia sem coluna)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS transportadoras (
                id SERIAL PRIMARY KEY,
                nome TEXT UNIQUE NOT NULL
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transportadoras_nome ON transportadoras(nome);"))

        # ✅ CORREÇÃO DO ERRO (coluna não existia)
        conn.execute(text("ALTER TABLE transportadoras ADD COLUMN IF NOT EXISTS responsavel_user_id INTEGER;"))

        # tenta criar FK (se já existir, ignora)
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'transportadoras_responsavel_user_id_fkey'
                    ) THEN
                        ALTER TABLE transportadoras
                        ADD CONSTRAINT transportadoras_responsavel_user_id_fkey
                        FOREIGN KEY (responsavel_user_id) REFERENCES users(id);
                    END IF;
                END $$;
            """))
        except Exception as e:
            print("WARN schema: FK transportadoras.responsavel_user_id -> users(id):", repr(e))

        # --- password_resets
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS password_resets (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                used_at TIMESTAMPTZ
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_password_resets_token_hash ON password_resets(token_hash);"))

ensure_schema()

# =========================
# RESPONSÁVEL (fallback antigo)
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

def get_responsavel_fallback(transportadora: str) -> Optional[str]:
    if not transportadora:
        return None
    if transportadora in RESP_MAP:
        return RESP_MAP[transportadora]
    base = transportadora.split("-")[0].strip()
    return RESP_MAP.get(base)

# =========================
# AUTH HELPERS
# =========================

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))

def sign_data(payload: dict, secret: str) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return f"{_b64url(raw)}.{_b64url(sig)}"

def verify_signed(token: str, secret: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        raw = _b64url_decode(parts[0])
        sig = _b64url_decode(parts[1])
        exp_sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, exp_sig):
            return None
        payload = json.loads(raw.decode("utf-8"))
        return payload
    except Exception:
        return None

def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    if salt is None:
        salt_bytes = secrets.token_bytes(16)
        salt = _b64url(salt_bytes)
    else:
        salt_bytes = _b64url_decode(salt)

    dk = hashlib.pbkdf2_hmac(
        HASH_ALGO,
        password.encode("utf-8"),
        salt_bytes,
        PBKDF2_ITERS,
    )
    return salt, _b64url(dk)

def verify_password(password: str, salt: Optional[str], pwd_hash: Optional[str]) -> bool:
    if not salt or not pwd_hash:
        return False
    _, calc = hash_password(password, salt=salt)
    return hmac.compare_digest(calc, pwd_hash)

def compute_expiry(is_first_after_temp: bool) -> datetime:
    days = PWD_EXP_FIRST_DAYS if is_first_after_temp else PWD_EXP_NEXT_DAYS
    return agora_br() + timedelta(days=days)

def needs_password_change(user: UserDB) -> bool:
    if user.must_change_password:
        return True
    if user.password_expires_at and agora_br() > user.password_expires_at:
        return True
    return False

def make_csrf_token() -> str:
    return secrets.token_urlsafe(32)

def set_auth_cookies(resp: Response, user_id: int):
    now = agora_br()
    csrf = make_csrf_token()

    session_payload = {
        "uid": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=COOKIE_MAX_AGE_SECONDS)).timestamp()),
        "csrf": csrf,
    }
    sess = sign_data(session_payload, SESSION_SECRET)

    resp.set_cookie(
        COOKIE_NAME,
        sess,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    resp.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=CSRF_MAX_AGE_SECONDS,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )

def clear_auth_cookies(resp: Response):
    resp.delete_cookie(COOKIE_NAME, path="/")
    resp.delete_cookie(CSRF_COOKIE, path="/")

def get_current_user(request: Request, db: Session) -> Optional[UserDB]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = verify_signed(token, SESSION_SECRET)
    if not payload:
        return None
    exp = payload.get("exp")
    uid = payload.get("uid")
    if not exp or not uid:
        return None
    if int(exp) < int(agora_br().timestamp()):
        return None

    user = db.query(UserDB).filter(UserDB.id == int(uid)).first()
    return user

def get_session_csrf(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = verify_signed(token, SESSION_SECRET)
    if not payload:
        return None
    return payload.get("csrf")

def validate_csrf(request: Request, csrf_form_value: Optional[str]) -> bool:
    if not csrf_form_value:
        csrf_form_value = request.cookies.get(CSRF_COOKIE)

    if not csrf_form_value:
        return False

    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf_session = get_session_csrf(request)

    if not csrf_cookie:
        return False

    if not csrf_session:
        return hmac.compare_digest(csrf_form_value, csrf_cookie)

    return hmac.compare_digest(csrf_form_value, csrf_cookie) and hmac.compare_digest(csrf_form_value, csrf_session)

# =========================
# Pydantic (Faturas)
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
    data_pagamento: Optional[datetime] = None

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

# ✅ NOVO: retorno de transportadoras (pra sidebar / UI)
class TransportadoraOut(BaseModel):
    id: int
    nome: str
    responsavel: Optional[str] = None

    class Config:
        from_attributes = True

# =========================
# HELPERS FATURAS
# =========================

def get_responsavel(db: Session, transportadora: str) -> Optional[str]:
    if transportadora:
        nome_base = transportadora.split("-")[0].strip()
        tr = db.query(TransportadoraDB).filter(TransportadoraDB.nome.ilike(nome_base)).first()
        if tr and tr.responsavel_user_id:
            u = db.query(UserDB).filter(UserDB.id == tr.responsavel_user_id).first()
            if u:
                return u.username
    return get_responsavel_fallback(transportadora)

def fatura_to_out(db: Session, f: FaturaDB) -> FaturaOut:
    return FaturaOut(
        id=f.id,
        transportadora=f.transportadora,
        numero_fatura=f.numero_fatura,
        valor=float(f.valor or 0),
        data_vencimento=f.data_vencimento,
        status=f.status,
        observacao=f.observacao,
        responsavel=get_responsavel(db, f.transportadora),
        data_pagamento=f.data_pagamento,
    )

def transportadora_to_out(db: Session, tr: TransportadoraDB) -> TransportadoraOut:
    resp = None
    if tr.responsavel_user_id:
        u = db.query(UserDB).filter(UserDB.id == tr.responsavel_user_id).first()
        if u:
            resp = u.username
    return TransportadoraOut(id=tr.id, nome=tr.nome, responsavel=resp)

# =========================
# ✅ REGRA AUTOMÁTICA (atraso)
# =========================

def quarta_da_semana_atual(hoje: date) -> date:
    monday = hoje - timedelta(days=hoje.weekday())
    return monday + timedelta(days=2)

def atualizar_status_automatico(db: Session):
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

def registrar_pagamento(db: Session, fatura: FaturaDB, responsavel_nome: Optional[str]):
    pago_em = agora_br()
    fatura.data_pagamento = pago_em

    hist = HistoricoPagamentoDB(
        fatura_id=fatura.id,
        pago_em=pago_em,
        transportadora=fatura.transportadora,
        responsavel=responsavel_nome,
        numero_fatura=fatura.numero_fatura,
        valor=fatura.valor or 0,
        data_vencimento=fatura.data_vencimento,
    )
    db.add(hist)

def remover_historico_pagamento(db: Session, fatura_id: int):
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

app = FastAPI(title="Sistema de Faturas", version="2.0.3")

# ✅ NOVO (opcional): CORS por ENV
# Ex: CORS_ORIGINS=https://seu-front.com,https://outro.com
cors_origins = [o.strip() for o in (os.getenv("CORS_ORIGINS", "").strip()).split(",") if o.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# =========================
# BOOTSTRAP ADMIN (ENV)
# =========================

def bootstrap_admin(db: Session):
    if not BOOTSTRAP_ADMIN_USER or not BOOTSTRAP_ADMIN_PASSWORD:
        return

    user = db.query(UserDB).filter(UserDB.username == BOOTSTRAP_ADMIN_USER).first()

    salt, pwd_hash = hash_password(BOOTSTRAP_ADMIN_PASSWORD)
    now = agora_br()

    if not user:
        user = UserDB(
            username=BOOTSTRAP_ADMIN_USER,
            email=BOOTSTRAP_ADMIN_EMAIL,
            role="admin",
            pwd_salt=salt,
            pwd_hash=pwd_hash,
            must_change_password=1,
            password_expires_at=now,  # força troca
            created_at=now,
        )
        db.add(user)
        db.commit()
        print(f"BOOTSTRAP: admin criado: {BOOTSTRAP_ADMIN_USER}")
        return

    if not getattr(user, "pwd_salt", None) or not getattr(user, "pwd_hash", None):
        user.pwd_salt = salt
        user.pwd_hash = pwd_hash
        user.role = "admin"
        user.email = user.email or BOOTSTRAP_ADMIN_EMAIL
        user.must_change_password = 1
        user.password_expires_at = now
        db.commit()
        print(f"BOOTSTRAP: admin EXISTENTE corrigido/atualizado: {BOOTSTRAP_ADMIN_USER}")

@app.on_event("startup")
def on_startup():
    db = SessionLocal()
    try:
        bootstrap_admin(db)
    finally:
        db.close()

# =========================
# AUTH ROUTES / PAGES
# =========================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf = csrf_cookie or make_csrf_token()

    resp = templates.TemplateResponse(TPL_LOGIN, {"request": request, "csrf": csrf, "next": next})
    if not csrf_cookie:
        resp.set_cookie(
            CSRF_COOKIE,
            csrf,
            max_age=CSRF_MAX_AGE_SECONDS,
            httponly=False,
            secure=COOKIE_SECURE,
            samesite="lax",
            path="/",
        )
    return resp

@app.post("/login", response_class=HTMLResponse)
def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: Optional[str] = Form(None),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf):
        csrf_cookie = request.cookies.get(CSRF_COOKIE) or make_csrf_token()
        resp = templates.TemplateResponse(
            TPL_LOGIN,
            {"request": request, "csrf": csrf_cookie, "next": next, "error": "Sessão expirada. Recarregue a página e tente novamente."},
            status_code=400,
        )
        if not request.cookies.get(CSRF_COOKIE):
            resp.set_cookie(CSRF_COOKIE, csrf_cookie, max_age=CSRF_MAX_AGE_SECONDS, httponly=False, secure=COOKIE_SECURE, samesite="lax", path="/")
        return resp

    user = db.query(UserDB).filter(UserDB.username == username.strip()).first()
    if not user or not verify_password(password, getattr(user, "pwd_salt", None), getattr(user, "pwd_hash", None)):
        csrf_cookie = request.cookies.get(CSRF_COOKIE) or make_csrf_token()
        resp = templates.TemplateResponse(
            TPL_LOGIN,
            {"request": request, "csrf": csrf_cookie, "next": next, "error": "Usuário ou senha inválidos."},
            status_code=401,
        )
        if not request.cookies.get(CSRF_COOKIE):
            resp.set_cookie(CSRF_COOKIE, csrf_cookie, max_age=CSRF_MAX_AGE_SECONDS, httponly=False, secure=COOKIE_SECURE, samesite="lax", path="/")
        return resp

    user.last_login_at = agora_br()
    db.commit()

    resp = RedirectResponse(url=next or "/", status_code=302)
    set_auth_cookies(resp, user.id)

    if needs_password_change(user):
        resp = RedirectResponse(url="/change-password", status_code=302)
        set_auth_cookies(resp, user.id)
        return resp

    return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    clear_auth_cookies(resp)
    return resp

@app.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/change-password", status_code=302)

    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf = csrf_cookie or make_csrf_token()

    resp = templates.TemplateResponse(TPL_CHANGE, {"request": request, "csrf": csrf})
    if not csrf_cookie:
        resp.set_cookie(CSRF_COOKIE, csrf, max_age=CSRF_MAX_AGE_SECONDS, httponly=False, secure=COOKIE_SECURE, samesite="lax", path="/")
    return resp

@app.post("/change-password", response_class=HTMLResponse)
def change_password_action(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    csrf: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/change-password", status_code=302)

    if not validate_csrf(request, csrf):
        return templates.TemplateResponse(
            TPL_CHANGE,
            {"request": request, "csrf": request.cookies.get(CSRF_COOKIE) or make_csrf_token(), "error": "Sessão expirada. Recarregue a página e tente novamente."},
            status_code=400,
        )

    if not verify_password(current_password, getattr(user, "pwd_salt", None), getattr(user, "pwd_hash", None)):
        return templates.TemplateResponse(
            TPL_CHANGE,
            {"request": request, "csrf": request.cookies.get(CSRF_COOKIE) or make_csrf_token(), "error": "Senha atual incorreta."},
            status_code=400,
        )

    if len(new_password) < 8:
        return templates.TemplateResponse(
            TPL_CHANGE,
            {"request": request, "csrf": request.cookies.get(CSRF_COOKIE) or make_csrf_token(), "error": "A nova senha deve ter pelo menos 8 caracteres."},
            status_code=400,
        )

    salt, pwd_hash = hash_password(new_password)
    user.pwd_salt = salt
    user.pwd_hash = pwd_hash

    is_first = user.first_password_changed_at is None
    now = agora_br()

    if is_first:
        user.first_password_changed_at = now

    user.last_password_changed_at = now
    user.must_change_password = 0
    user.password_expires_at = compute_expiry(is_first_after_temp=is_first)

    db.commit()
    return RedirectResponse(url="/", status_code=302)

@app.get("/forgot", response_class=HTMLResponse)
def forgot_page(request: Request):
    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf = csrf_cookie or make_csrf_token()

    resp = templates.TemplateResponse(TPL_FORGOT, {"request": request, "csrf": csrf})
    if not csrf_cookie:
        resp.set_cookie(CSRF_COOKIE, csrf, max_age=CSRF_MAX_AGE_SECONDS, httponly=False, secure=COOKIE_SECURE, samesite="lax", path="/")
    return resp

@app.post("/forgot", response_class=HTMLResponse)
def forgot_action(
    request: Request,
    username_or_email: str = Form(...),
    csrf: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf):
        return templates.TemplateResponse(
            TPL_FORGOT,
            {"request": request, "csrf": request.cookies.get(CSRF_COOKIE) or make_csrf_token(), "msg": "Sessão expirada. Recarregue e tente novamente."},
            status_code=400,
        )

    val = username_or_email.strip()
    user = db.query(UserDB).filter(UserDB.username == val).first()
    if not user and val:
        user = db.query(UserDB).filter(UserDB.email == val).first()

    if not user:
        return templates.TemplateResponse(
            TPL_FORGOT,
            {"request": request, "csrf": request.cookies.get(CSRF_COOKIE) or make_csrf_token(), "msg": "Se existir, um link de redefinição foi gerado."},
        )

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    reset = PasswordResetDB(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=agora_br() + timedelta(minutes=30),
        used_at=None,
    )
    db.add(reset)
    db.commit()

    base_url = str(request.base_url).rstrip("/")
    reset_link = f"{base_url}/reset?token={token}"

    return templates.TemplateResponse(
        TPL_FORGOT,
        {"request": request, "csrf": request.cookies.get(CSRF_COOKIE) or make_csrf_token(), "msg": "Link gerado.", "reset_link": reset_link},
    )

@app.get("/reset", response_class=HTMLResponse)
def reset_page(request: Request, token: str):
    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf = csrf_cookie or make_csrf_token()

    resp = templates.TemplateResponse(TPL_RESET, {"request": request, "csrf": csrf, "token": token})
    if not csrf_cookie:
        resp.set_cookie(CSRF_COOKIE, csrf, max_age=CSRF_MAX_AGE_SECONDS, httponly=False, secure=COOKIE_SECURE, samesite="lax", path="/")
    return resp

@app.post("/reset", response_class=HTMLResponse)
def reset_action(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    csrf: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf):
        return templates.TemplateResponse(
            TPL_RESET,
            {"request": request, "csrf": request.cookies.get(CSRF_COOKIE) or make_csrf_token(), "token": token, "error": "Sessão expirada. Recarregue e tente novamente."},
            status_code=400,
        )

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    pr = db.query(PasswordResetDB).filter(PasswordResetDB.token_hash == token_hash).first()
    if not pr or pr.used_at is not None or pr.expires_at < agora_br():
        return templates.TemplateResponse(
            TPL_RESET,
            {"request": request, "csrf": request.cookies.get(CSRF_COOKIE) or make_csrf_token(), "token": token, "error": "Link inválido ou expirado."},
            status_code=400,
        )

    user = db.query(UserDB).filter(UserDB.id == pr.user_id).first()
    if not user:
        return templates.TemplateResponse(
            TPL_RESET,
            {"request": request, "csrf": request.cookies.get(CSRF_COOKIE) or make_csrf_token(), "token": token, "error": "Usuário não encontrado."},
            status_code=400,
        )

    if len(new_password) < 8:
        return templates.TemplateResponse(
            TPL_RESET,
            {"request": request, "csrf": request.cookies.get(CSRF_COOKIE) or make_csrf_token(), "token": token, "error": "A nova senha deve ter pelo menos 8 caracteres."},
            status_code=400,
        )

    salt, pwd_hash = hash_password(new_password)
    user.pwd_salt = salt
    user.pwd_hash = pwd_hash
    user.must_change_password = 0
    now = agora_br()
    if user.first_password_changed_at is None:
        user.first_password_changed_at = now
    user.last_password_changed_at = now
    user.password_expires_at = compute_expiry(is_first_after_temp=False)

    pr.used_at = now
    db.commit()

    return RedirectResponse(url="/login", status_code=302)

# =========================
# PAGES PROTEGIDAS (HTML)
# =========================

def redirect_to_login(next_path: str) -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={next_path}", status_code=302)

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return redirect_to_login("/")

    if needs_password_change(user):
        return RedirectResponse(url="/change-password", status_code=302)

    return templates.TemplateResponse(TPL_INDEX, {"request": request})

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return redirect_to_login("/admin")
    if needs_password_change(user):
        return RedirectResponse(url="/change-password", status_code=302)
    if (user.role or "").lower() != "admin":
        return RedirectResponse(url="/", status_code=302)

    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf = csrf_cookie or make_csrf_token()

    users = db.query(UserDB).order_by(UserDB.username.asc()).all()
    trs = db.query(TransportadoraDB).order_by(TransportadoraDB.nome.asc()).all()
    user_map = {u.id: u.username for u in users}

    resp = templates.TemplateResponse(
        TPL_ADMIN,
        {"request": request, "csrf": csrf, "admin": user, "users": users, "trs": trs, "user_map": user_map},
    )
    if not csrf_cookie:
        resp.set_cookie(CSRF_COOKIE, csrf, max_age=CSRF_MAX_AGE_SECONDS, httponly=False, secure=COOKIE_SECURE, samesite="lax", path="/")
    return resp

@app.post("/admin/user/create", response_class=HTMLResponse)
def admin_create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(""),
    role: str = Form("user"),
    temp_password: str = Form(...),
    csrf: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    admin = get_current_user(request, db)
    if not admin:
        return redirect_to_login("/admin")
    if (admin.role or "").lower() != "admin":
        return RedirectResponse(url="/", status_code=302)
    if not validate_csrf(request, csrf):
        return RedirectResponse(url="/admin", status_code=302)

    username = username.strip()
    if not username:
        return RedirectResponse(url="/admin", status_code=302)

    exists = db.query(UserDB).filter(UserDB.username == username).first()
    if exists:
        return RedirectResponse(url="/admin", status_code=302)

    salt, pwd_hash = hash_password(temp_password)

    u = UserDB(
        username=username,
        email=(email.strip() or None),
        role=("admin" if role == "admin" else "user"),
        pwd_salt=salt,
        pwd_hash=pwd_hash,
        must_change_password=1,
        password_expires_at=agora_br(),
        created_at=agora_br(),
    )
    db.add(u)
    db.commit()
    return RedirectResponse(url="/admin", status_code=302)

@app.post("/admin/transportadora/create", response_class=HTMLResponse)
def admin_create_transportadora(
    request: Request,
    nome: str = Form(...),
    csrf: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    admin = get_current_user(request, db)
    if not admin:
        return redirect_to_login("/admin")
    if (admin.role or "").lower() != "admin":
        return RedirectResponse(url="/", status_code=302)
    if not validate_csrf(request, csrf):
        return RedirectResponse(url="/admin", status_code=302)

    nome = nome.strip()
    if not nome:
        return RedirectResponse(url="/admin", status_code=302)

    exists = db.query(TransportadoraDB).filter(TransportadoraDB.nome.ilike(nome)).first()
    if not exists:
        db.add(TransportadoraDB(nome=nome))
        db.commit()

    return RedirectResponse(url="/admin", status_code=302)

@app.post("/admin/transportadora/assign", response_class=HTMLResponse)
def admin_assign_transportadora(
    request: Request,
    transportadora_id: int = Form(...),
    responsavel_user_id: str = Form(""),
    csrf: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    admin = get_current_user(request, db)
    if not admin:
        return redirect_to_login("/admin")
    if (admin.role or "").lower() != "admin":
        return RedirectResponse(url="/", status_code=302)
    if not validate_csrf(request, csrf):
        return RedirectResponse(url="/admin", status_code=302)

    tr = db.query(TransportadoraDB).filter(TransportadoraDB.id == transportadora_id).first()
    if not tr:
        return RedirectResponse(url="/admin", status_code=302)

    if responsavel_user_id.strip() == "":
        tr.responsavel_user_id = None
    else:
        try:
            uid = int(responsavel_user_id)
            u = db.query(UserDB).filter(UserDB.id == uid).first()
            if u:
                tr.responsavel_user_id = u.id
        except Exception:
            pass

    db.commit()
    return RedirectResponse(url="/admin", status_code=302)

# =========================
# HEALTH
# =========================

@app.get("/health")
def health_check():
    return {"status": "ok", "static_dir": STATIC_DIR, "templates_dir": TEMPLATES_DIR, "debug": DEBUG}

# =========================
# API AUTH
# =========================

def api_require_auth(request: Request, db: Session) -> UserDB:
    u = get_current_user(request, db)
    if not u:
        raise HTTPException(status_code=401, detail="Não autenticado")
    if needs_password_change(u):
        raise HTTPException(status_code=403, detail="Troca de senha necessária")
    return u

@app.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    u = api_require_auth(request, db)
    return {"id": u.id, "username": u.username, "email": u.email, "role": u.role}

# ✅ NOVO: lista transportadoras (pra sidebar / filtros)
@app.get("/transportadoras", response_model=List[TransportadoraOut])
def listar_transportadoras_api(request: Request, db: Session = Depends(get_db)):
    api_require_auth(request, db)
    trs = db.query(TransportadoraDB).order_by(TransportadoraDB.nome.asc()).all()
    return [transportadora_to_out(db, tr) for tr in trs]

# =========================
# FATURAS (API)
# =========================

@app.post("/faturas", response_model=FaturaOut)
def criar_fatura(fatura: FaturaCreate, request: Request, db: Session = Depends(get_db)):
    api_require_auth(request, db)

    db_fatura = FaturaDB(
        transportadora=fatura.transportadora,
        numero_fatura=fatura.numero_fatura,
        valor=fatura.valor,
        data_vencimento=fatura.data_vencimento,
        status=fatura.status,
        observacao=fatura.observacao,
    )

    db.add(db_fatura)
    db.flush()  # garante ID antes de registrar histórico

    if (fatura.status or "").lower() == "pago":
        resp_nome = get_responsavel(db, db_fatura.transportadora)
        registrar_pagamento(db, db_fatura, resp_nome)

    db.commit()
    db.refresh(db_fatura)
    return fatura_to_out(db, db_fatura)

@app.get("/faturas", response_model=List[FaturaOut])
def listar_faturas(
    request: Request,
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    ate_vencimento: Optional[str] = Query(None),
    de_vencimento: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
):
    api_require_auth(request, db)
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

    faturas_db = query.order_by(FaturaDB.id.desc()).all()
    return [fatura_to_out(db, f) for f in faturas_db]

@app.put("/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(fatura_id: int, dados: FaturaUpdate, request: Request, db: Session = Depends(get_db)):
    api_require_auth(request, db)

    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    status_antigo = (fatura.status or "").lower()

    data = dados.dict(exclude_unset=True)
    for campo, valor in data.items():
        setattr(fatura, campo, valor)

    status_novo = (fatura.status or "").lower()

    if status_antigo != "pago" and status_novo == "pago":
        resp_nome = get_responsavel(db, fatura.transportadora)
        registrar_pagamento(db, fatura, resp_nome)

    if status_antigo == "pago" and status_novo != "pago":
        remover_historico_pagamento(db, fatura.id)
        fatura.data_pagamento = None

    db.commit()
    db.refresh(fatura)
    return fatura_to_out(db, fatura)

@app.delete("/faturas/{fatura_id}")
def deletar_fatura(fatura_id: int, request: Request, db: Session = Depends(get_db)):
    api_require_auth(request, db)

    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    for anexo in list(fatura.anexos or []):
        try:
            s3.delete_object(Bucket=R2_BUCKET_NAME, Key=anexo.filename)
        except ClientError as e:
            print("ERRO AO APAGAR NO R2:", repr(e))

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
    request: Request,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    api_require_auth(request, db)

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
            try:
                await file.close()
            except Exception:
                pass

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
def listar_anexos(fatura_id: int, request: Request, db: Session = Depends(get_db)):
    api_require_auth(request, db)

    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return fatura.anexos

@app.get("/anexos/{anexo_id}")
def baixar_anexo(anexo_id: int, request: Request, db: Session = Depends(get_db)):
    api_require_auth(request, db)

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
def deletar_anexo(anexo_id: int, request: Request, db: Session = Depends(get_db)):
    api_require_auth(request, db)

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
    request: Request,
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    ate_vencimento: Optional[str] = Query(None),
    de_vencimento: Optional[str] = Query(None),
):
    api_require_auth(request, db)
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

    # ✅ NOVO: total pendente (em dia + atrasado)
    total_pendente = float(total_em_dia or 0) + float(total_atrasado or 0)

    # ✅ NOVO: contagens (pra cards na aba Faturas/Dashboard)
    qtd_total = query_base.with_entities(func.count(FaturaDB.id)).scalar() or 0
    qtd_pago = query_base.filter(FaturaDB.status.ilike("pago")).with_entities(func.count(FaturaDB.id)).scalar() or 0
    qtd_atrasado = query_base.filter(FaturaDB.status.ilike("atrasado")).with_entities(func.count(FaturaDB.id)).scalar() or 0
    qtd_pendente = query_base.filter(FaturaDB.status.ilike("pendente")).with_entities(func.count(FaturaDB.id)).scalar() or 0

    return {
        "total_geral": float(total_geral),
        "total_pendente": float(total_pendente),
        "total_em_dia": float(total_em_dia or 0),
        "total_atrasado": float(total_atrasado or 0),
        "total_pago": float(total_pago or 0),
        "qtd_total": int(qtd_total),
        "qtd_pendente": int(qtd_pendente),
        "qtd_atrasado": int(qtd_atrasado),
        "qtd_pago": int(qtd_pago),
    }

# =========================
# HISTÓRICO (API)
# =========================

@app.get("/historico", response_model=List[HistoricoPagamentoOut])
def listar_historico(
    request: Request,
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    de: Optional[str] = Query(None),   # yyyy-mm-dd
    ate: Optional[str] = Query(None),  # yyyy-mm-dd
    numero_fatura: Optional[str] = Query(None),
):
    api_require_auth(request, db)

    q = db.query(HistoricoPagamentoDB)

    if transportadora:
        q = q.filter(HistoricoPagamentoDB.transportadora.ilike(f"%{transportadora}%"))

    if numero_fatura:
        q = q.filter(HistoricoPagamentoDB.numero_fatura.ilike(f"%{numero_fatura}%"))

    if de:
        try:
            d1 = datetime.strptime(de, "%Y-%m-%d").date()
            q = q.filter(func.date(HistoricoPagamentoDB.pago_em) >= d1)
        except ValueError:
            pass

    if ate:
        try:
            d2 = datetime.strptime(ate, "%Y-%m-%d").date()
            q = q.filter(func.date(HistoricoPagamentoDB.pago_em) <= d2)
        except ValueError:
            pass

    itens = q.order_by(HistoricoPagamentoDB.pago_em.desc()).all()
    return itens

# ✅ ALIAS para seu app.js (ele chama /historico_pagamentos)
@app.get("/historico_pagamentos", response_model=List[HistoricoPagamentoOut])
def listar_historico_alias(
    request: Request,
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    de: Optional[str] = Query(None),
    ate: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
):
    return listar_historico(
        request=request,
        db=db,
        transportadora=transportadora,
        de=de,
        ate=ate,
        numero_fatura=numero_fatura,
    )

# =========================
# EXPORT CSV
# =========================

@app.get("/faturas/exportar")
def exportar_faturas(
    request: Request,
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
    de_vencimento: Optional[str] = Query(None),
    ate_vencimento: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    api_require_auth(request, db)
    atualizar_status_automatico(db)

    import csv
    import io

    query = db.query(FaturaDB)
    if transportadora:
        query = query.filter(FaturaDB.transportadora.ilike(f"%{transportadora}%"))
    if numero_fatura:
        query = query.filter(FaturaDB.numero_fatura.ilike(f"%{numero_fatura}%"))
    if status:
        query = query.filter(FaturaDB.status.ilike(status.strip()))
    if de_vencimento:
        try:
            d1 = datetime.strptime(de_vencimento, "%Y-%m-%d").date()
            query = query.filter(FaturaDB.data_vencimento >= d1)
        except ValueError:
            pass
    if ate_vencimento:
        try:
            d2 = datetime.strptime(ate_vencimento, "%Y-%m-%d").date()
            query = query.filter(FaturaDB.data_vencimento <= d2)
        except ValueError:
            pass

    faturas = query.order_by(FaturaDB.id.desc()).all()

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
                get_responsavel(db, f.transportadora) or "",
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

@app.get("/historico/exportar")
def exportar_historico(
    request: Request,
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    de: Optional[str] = Query(None),
    ate: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
):
    api_require_auth(request, db)

    import csv
    import io

    q = db.query(HistoricoPagamentoDB)
    if transportadora:
        q = q.filter(HistoricoPagamentoDB.transportadora.ilike(f"%{transportadora}%"))
    if numero_fatura:
        q = q.filter(HistoricoPagamentoDB.numero_fatura.ilike(f"%{numero_fatura}%"))

    if de:
        try:
            d1 = datetime.strptime(de, "%Y-%m-%d").date()
            q = q.filter(func.date(HistoricoPagamentoDB.pago_em) >= d1)
        except ValueError:
            pass

    if ate:
        try:
            d2 = datetime.strptime(ate, "%Y-%m-%d").date()
            q = q.filter(func.date(HistoricoPagamentoDB.pago_em) <= d2)
        except ValueError:
            pass

    itens = q.order_by(HistoricoPagamentoDB.pago_em.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    writer.writerow(["ID Hist", "ID Fatura", "Transportadora", "Responsável", "Número Fatura", "Valor", "Vencimento", "Pago em (BR)"])

    for it in itens:
        pago_em = ""
        try:
            pago_em = it.pago_em.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
        except Exception:
            pago_em = str(it.pago_em)

        writer.writerow([
            it.id,
            it.fatura_id,
            it.transportadora,
            it.responsavel or "",
            it.numero_fatura,
            float(it.valor or 0),
            it.data_vencimento.strftime("%d/%m/%Y") if it.data_vencimento else "",
            pago_em
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    headers = {"Content-Disposition": 'attachment; filename="historico_pagamentos.csv"'}
    return Response(csv_bytes, media_type="text/csv", headers=headers)

# ✅ alias do export, se seu JS chamar isso
@app.get("/historico_pagamentos/exportar")
def exportar_historico_alias(
    request: Request,
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    de: Optional[str] = Query(None),
    ate: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
):
    return exportar_historico(
        request=request,
        db=db,
        transportadora=transportadora,
        de=de,
        ate=ate,
        numero_fatura=numero_fatura,
    )
