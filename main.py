from datetime import date, datetime, timedelta
import os
import uuid
import base64
import json
import hmac
import hashlib
import secrets
import traceback
from typing import List, Optional, Tuple

raise RuntimeError("🔥 ESTE É O MAIN CERTO 🔥")


from zoneinfo import ZoneInfo

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
from fastapi.responses import HTMLResponse, Response, StreamingResponse, RedirectResponse, PlainTextResponse
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
# CONFIG / FLAGS
# =========================

DEBUG = os.getenv("DEBUG", "0").strip() == "1"

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
# CONFIG AUTH / SEGURANÇA
# =========================

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

# =========================
# CONFIG R2 (OPCIONAL)
# =========================

R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")

R2_ENABLED = all([R2_ENDPOINT, R2_BUCKET_NAME, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY])

s3 = None
if R2_ENABLED:
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
else:
    print("WARN: R2 NÃO configurado. Anexos (upload/download) ficarão desativados até configurar as env vars do R2.")

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

    pwd_salt = Column(String, nullable=False)
    pwd_hash = Column(String, nullable=False)

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
# ✅ MIGRAÇÃO AUTOMÁTICA
# =========================

def ensure_schema():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE faturas ADD COLUMN IF NOT EXISTS data_pagamento TIMESTAMPTZ;"))
        try:
            conn.execute(text("""
                ALTER TABLE faturas
                ALTER COLUMN data_pagamento TYPE TIMESTAMPTZ
                USING (data_pagamento AT TIME ZONE 'UTC');
            """))
        except Exception as e:
            print("WARN schema: alter faturas.data_pagamento -> timestamptz:", repr(e))

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

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS transportadoras (
                id SERIAL PRIMARY KEY,
                nome TEXT UNIQUE NOT NULL,
                responsavel_user_id INTEGER REFERENCES users(id)
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transportadoras_nome ON transportadoras(nome);"))

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
# RESPONSÁVEL (fallback)
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
        secure=True,
        samesite="lax",
        path="/",
    )
    resp.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=CSRF_MAX_AGE_SECONDS,
        httponly=False,
        secure=True,
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
        return False
    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf_session = get_session_csrf(request)
    if not csrf_cookie or not csrf_session:
        return False
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

# =========================
# STATUS AUTOMÁTICO
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
# HISTÓRICO PAGAMENTO
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
# DB DEPENDENCY
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

print("### MAIN.PY CARREGADO - VERSAO 2.0.1 AUTH OK ###")


# middleware para mostrar erro real quando DEBUG=1
@app.middleware("http")
async def debug_error_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        tb = traceback.format_exc()
        print("INTERNAL ERROR:\n", tb)
        if DEBUG:
            return PlainTextResponse(tb, status_code=500)
        return PlainTextResponse("Erro do Servidor Interno", status_code=500)

# monta static/templates sem quebrar o boot se faltar pasta
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    print("WARN: pasta 'static/' não encontrada. Front pode quebrar se templates referenciam arquivos estáticos.")

templates = Jinja2Templates(directory="templates") if os.path.isdir("templates") else None
if templates is None:
    print("WARN: pasta 'templates/' não encontrada. Rotas HTML irão falhar até você subir a pasta templates no GitHub.")

# =========================
# BOOTSTRAP ADMIN
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
            password_expires_at=now,
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
# AUTH ROUTES
# =========================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if templates is None:
        return PlainTextResponse("Templates não encontrados no deploy. Suba a pasta /templates no GitHub.", status_code=500)
    csrf_fake = secrets.token_urlsafe(16)
    return templates.TemplateResponse("login.html", {"request": request, "csrf": csrf_fake, "next": next})

@app.post("/login", response_class=HTMLResponse)
def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: Optional[str] = Form(None),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    if templates is None:
        return PlainTextResponse("Templates não encontrados no deploy. Suba a pasta /templates no GitHub.", status_code=500)

    user = db.query(UserDB).filter(UserDB.username == username.strip()).first()
    if not user or not verify_password(password, getattr(user, "pwd_salt", None), getattr(user, "pwd_hash", None)):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "csrf": secrets.token_urlsafe(16), "next": next, "error": "Usuário ou senha inválidos."},
            status_code=401,
        )

    user.last_login_at = agora_br()
    db.commit()

    if needs_password_change(user):
        resp = RedirectResponse(url="/change-password", status_code=302)
        set_auth_cookies(resp, user.id)
        return resp

    resp = RedirectResponse(url=next or "/", status_code=302)
    set_auth_cookies(resp, user.id)
    return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    clear_auth_cookies(resp)
    return resp

# =========================
# HEALTH
# =========================

@app.get("/health")
def health_check():
    return {"status": "ok", "r2_enabled": bool(R2_ENABLED), "debug": bool(DEBUG)}

# =========================
# AUTH GUARD API
# =========================

def api_require_auth(request: Request, db: Session):
    u = get_current_user(request, db)
    if not u:
        raise HTTPException(status_code=401, detail="Não autenticado")
    if needs_password_change(u):
        raise HTTPException(status_code=403, detail="Troca de senha necessária")
    return u

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

    faturas_db = query.order_by(FaturaDB.id).all()
    return [fatura_to_out(db, f) for f in faturas_db]

# =========================
# ANEXOS (com bloqueio se R2 não estiver configurado)
# =========================

@app.post("/faturas/{fatura_id}/anexos", response_model=List[AnexoOut])
async def upload_anexos(
    fatura_id: int,
    request: Request,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    api_require_auth(request, db)

    if not R2_ENABLED or s3 is None:
        raise HTTPException(status_code=503, detail="R2 não configurado no Render. Configure R2_* nas variáveis de ambiente.")

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
