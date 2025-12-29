from datetime import date, datetime, timedelta
import os
import uuid
import secrets
import hashlib
from typing import List, Optional, Tuple

from zoneinfo import ZoneInfo  # ✅ fuso

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

from pydantic import BaseModel

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Boolean,
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

from passlib.hash import argon2
from jose import jwt, JWTError

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
    return datetime.now(BR_TZ)

def hoje_local_br() -> date:
    return agora_br().date()

# =========================
# 🔐 AUTH / SECURITY CONFIG
# =========================

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET não configurado nas variáveis de ambiente do Render.")

SESSION_COOKIE_NAME = "mshop_session"
CSRF_COOKIE_NAME = "mshop_csrf"

# Troca de senha:
# - primeira troca: 3 meses
# - demais trocas: 6 meses
PWD_MAX_FIRST_DAYS = 90
PWD_MAX_NEXT_DAYS = 180

SESSION_EXPIRE_HOURS = 12  # sessão padrão (relogin depois)
RESET_TOKEN_MINUTES = 30   # link de reset (sem e-mail por enquanto)

def _jwt_encode(payload: dict, exp_seconds: int) -> str:
    data = dict(payload)
    data["exp"] = datetime.utcnow() + timedelta(seconds=exp_seconds)
    return jwt.encode(data, JWT_SECRET, algorithm="HS256")

def _jwt_decode(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])

def _make_csrf() -> str:
    return secrets.token_urlsafe(32)

def _hash_csrf(csrf: str) -> str:
    # hash leve para não ficar carregando token bruto em logs
    return hashlib.sha256(csrf.encode("utf-8")).hexdigest()

def _set_csrf_cookie(resp: Response, csrf: str):
    # CSRF cookie: pode ser não-HttpOnly para double-submit, mas aqui usamos hidden field + cookie
    # e comparamos os dois. Isso evita CSRF em forms.
    resp.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf,
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
        max_age=60 * 60 * 24,  # 1 dia
    )

def _clear_auth_cookies(resp: Response):
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
    resp.delete_cookie(CSRF_COOKIE_NAME, path="/")

def _set_session_cookie(resp: Response, token: str):
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=60 * 60 * SESSION_EXPIRE_HOURS,
    )

def verify_csrf(request: Request, form_csrf: str):
    cookie_csrf = request.cookies.get(CSRF_COOKIE_NAME) or ""
    if not form_csrf or not cookie_csrf or form_csrf != cookie_csrf:
        raise HTTPException(status_code=400, detail="CSRF inválido.")

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

# 🔐 NOVO: Users / Transportadoras (Admin)
class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")  # user | admin
    is_active = Column(Boolean, nullable=False, default=True)

    must_change_password = Column(Boolean, nullable=False, default=True)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)
    password_version = Column(Integer, nullable=False, default=0)  # conta trocas

    created_at = Column(DateTime(timezone=True), nullable=False, default=agora_br)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

class TransportadoraDB(Base):
    __tablename__ = "transportadoras"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, nullable=False, index=True)
    responsavel_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

Base.metadata.create_all(bind=engine)

# =========================
# ✅ MIGRAÇÃO AUTOMÁTICA (Render)
# =========================

def ensure_schema():
    """
    - garante TIMESTAMPTZ nas datas de pagamento
    - cria tabela de histórico
    - cria tabelas users/transportadoras se não existirem
    - adiciona colunas novas caso já exista (sem quebrar)
    """
    with engine.begin() as conn:
        # --- faturas.data_pagamento ---
        conn.execute(text("ALTER TABLE faturas ADD COLUMN IF NOT EXISTS data_pagamento TIMESTAMPTZ;"))
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
        try:
            conn.execute(text("""
                ALTER TABLE historico_pagamentos
                ALTER COLUMN pago_em TYPE TIMESTAMPTZ
                USING (pago_em AT TIME ZONE 'UTC');
            """))
        except Exception as e:
            print("WARN schema: alter historico_pagamentos.pago_em -> timestamptz:", repr(e))

        # --- users ---
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                password_changed_at TIMESTAMPTZ,
                must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
                password_version INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_login_at TIMESTAMPTZ
            );
        """))
        # adiciona colunas se banco já era antigo
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_version INTEGER NOT NULL DEFAULT 0;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT TRUE;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;"))

        # --- transportadoras ---
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS transportadoras (
                id SERIAL PRIMARY KEY,
                nome TEXT UNIQUE NOT NULL,
                responsavel_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transportadoras_nome ON transportadoras(nome);"))

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

def get_responsavel_from_db(db: Session, transportadora: str) -> Optional[str]:
    if not transportadora:
        return None
    tr = db.query(TransportadoraDB).filter(func.lower(TransportadoraDB.nome) == transportadora.lower()).first()
    if not tr or not tr.responsavel_user_id:
        return None
    u = db.query(UserDB).filter(UserDB.id == tr.responsavel_user_id).first()
    if not u:
        return None
    return u.username

def get_responsavel_fallback(transportadora: str) -> Optional[str]:
    if transportadora in RESP_MAP:
        return RESP_MAP[transportadora]
    base = transportadora.split("-")[0].strip()
    return RESP_MAP.get(base)

def fatura_to_out(db: Session, f: FaturaDB) -> FaturaOut:
    resp_db = get_responsavel_from_db(db, f.transportadora)
    resp = resp_db or get_responsavel_fallback(f.transportadora)
    return FaturaOut(
        id=f.id,
        transportadora=f.transportadora,
        numero_fatura=f.numero_fatura,
        valor=float(f.valor or 0),
        data_vencimento=f.data_vencimento,
        status=f.status,
        observacao=f.observacao,
        responsavel=resp,
        data_pagamento=f.data_pagamento,
    )

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

def registrar_pagamento(db: Session, fatura: FaturaDB):
    pago_em = agora_br()
    fatura.data_pagamento = pago_em

    # responsável via DB ou fallback
    resp_db = get_responsavel_from_db(db, fatura.transportadora)
    resp = resp_db or get_responsavel_fallback(fatura.transportadora)

    hist = HistoricoPagamentoDB(
        fatura_id=fatura.id,
        pago_em=pago_em,
        transportadora=fatura.transportadora,
        responsavel=resp,
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
# 🔐 AUTH HELPERS (DB)
# =========================

def _pwd_is_expired(u: UserDB) -> bool:
    if u.must_change_password:
        return True
    if not u.password_changed_at:
        return True

    # 1ª troca = version == 1 => validade 90 dias
    # trocas seguintes => validade 180 dias
    if (u.password_version or 0) <= 1:
        max_days = PWD_MAX_FIRST_DAYS
    else:
        max_days = PWD_MAX_NEXT_DAYS

    return (agora_br() - u.password_changed_at) > timedelta(days=max_days)

def authenticate_user(db: Session, username: str, password: str) -> Optional[UserDB]:
    if not username or not password:
        return None
    u = db.query(UserDB).filter(func.lower(UserDB.username) == username.lower()).first()
    if not u or not u.is_active:
        return None
    try:
        if not argon2.verify(password, u.password_hash):
            return None
    except Exception:
        return None
    return u

def require_user(request: Request, db: Session) -> UserDB:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    try:
        payload = _jwt_decode(token)
        uid = int(payload.get("uid"))
    except Exception:
        raise HTTPException(status_code=401, detail="Sessão inválida.")
    u = db.query(UserDB).filter(UserDB.id == uid).first()
    if not u or not u.is_active:
        raise HTTPException(status_code=401, detail="Usuário inválido.")
    return u

def require_admin(user: UserDB) -> None:
    if (user.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado.")

def _redirect_to_login(next_path: str = "/") -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={next_path}", status_code=303)

# =========================
# ✅ BOOTSTRAP ADMIN (ENV)
# =========================

def bootstrap_admin_if_needed():
    """
    Cria o PRIMEIRO admin automaticamente usando:
      BOOTSTRAP_ADMIN_USER
      BOOTSTRAP_ADMIN_PASSWORD
    Só roda se NÃO existir nenhum usuário no banco.
    """
    admin_user = (os.getenv("BOOTSTRAP_ADMIN_USER") or "").strip()
    admin_pass = (os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or "").strip()

    if not admin_user or not admin_pass:
        # sem env, não cria nada
        return

    db = SessionLocal()
    try:
        total = db.query(UserDB).count()
        if total > 0:
            return

        # cria admin
        pwd_hash = argon2.hash(admin_pass)
        u = UserDB(
            username=admin_user,
            email=None,
            password_hash=pwd_hash,
            role="admin",
            is_active=True,
            must_change_password=True,  # força troca no 1º login
            password_changed_at=None,
            password_version=0,
            created_at=agora_br(),
        )
        db.add(u)
        db.commit()
        print("✅ BOOTSTRAP ADMIN criado:", admin_user)
    except Exception as e:
        print("ERRO BOOTSTRAP ADMIN:", repr(e))
    finally:
        db.close()

# =========================
# APP / STATIC / TEMPLATES
# =========================

app = FastAPI(title="Sistema de Faturas", version="1.0.0")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
def _startup():
    ensure_schema()
    bootstrap_admin_if_needed()

# =========================
# 🔒 MIDDLEWARE: exige login
# =========================

PUBLIC_PATHS_PREFIX = (
    "/static",
)

PUBLIC_EXACT = (
    "/health",
    "/login",
    "/logout",
    "/forgot",
    "/change-password",
)

PUBLIC_STARTS = (
    "/reset",  # /reset?token=...
)

@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path

    if path.startswith(PUBLIC_PATHS_PREFIX):
        return await call_next(request)

    if path in PUBLIC_EXACT or path.startswith(PUBLIC_STARTS):
        return await call_next(request)

    # Tudo que não for público exige sessão válida
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return _redirect_to_login(next_path=path)

    try:
        _ = _jwt_decode(token)
    except Exception:
        resp = _redirect_to_login(next_path=path)
        _clear_auth_cookies(resp)
        return resp

    return await call_next(request)

# =========================
# HOME (protegida)
# =========================

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    # se senha expirada, força troca
    if _pwd_is_expired(u):
        return RedirectResponse("/change-password", status_code=303)

    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
def health_check():
    return {"status": "ok"}

# =========================
# 🔐 LOGIN / LOGOUT / CHANGE / FORGOT / RESET
# =========================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    csrf = _make_csrf()
    resp = templates.TemplateResponse("login.html", {"request": request, "csrf": csrf, "next": next})
    _set_csrf_cookie(resp, csrf)
    return resp

@app.post("/login", response_class=HTMLResponse)
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf)

    u = authenticate_user(db, username, password)
    if not u:
        csrf2 = _make_csrf()
        resp = templates.TemplateResponse(
            "login.html",
            {"request": request, "csrf": csrf2, "next": next, "error": "Usuário ou senha inválidos."},
            status_code=401,
        )
        _set_csrf_cookie(resp, csrf2)
        return resp

    u.last_login_at = agora_br()
    db.commit()

    # se precisa trocar senha
    if _pwd_is_expired(u):
        token = _jwt_encode({"uid": u.id, "role": u.role, "pv": u.password_version}, 60 * 60 * SESSION_EXPIRE_HOURS)
        resp = RedirectResponse("/change-password", status_code=303)
        _set_session_cookie(resp, token)
        csrf2 = _make_csrf()
        _set_csrf_cookie(resp, csrf2)
        return resp

    # login ok
    token = _jwt_encode({"uid": u.id, "role": u.role, "pv": u.password_version}, 60 * 60 * SESSION_EXPIRE_HOURS)
    resp = RedirectResponse(next or "/", status_code=303)
    _set_session_cookie(resp, token)
    csrf2 = _make_csrf()
    _set_csrf_cookie(resp, csrf2)
    return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    _clear_auth_cookies(resp)
    return resp

@app.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    csrf = _make_csrf()
    resp = templates.TemplateResponse("change.html", {"request": request, "csrf": csrf, "user": u.username})
    _set_csrf_cookie(resp, csrf)
    return resp

@app.post("/change-password", response_class=HTMLResponse)
def change_password_post(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    csrf: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf)
    u = require_user(request, db)

    # valida senha atual
    ok = False
    try:
        ok = argon2.verify(current_password, u.password_hash)
    except Exception:
        ok = False

    if not ok:
        csrf2 = _make_csrf()
        resp = templates.TemplateResponse(
            "change.html",
            {"request": request, "csrf": csrf2, "error": "Senha atual inválida."},
            status_code=400,
        )
        _set_csrf_cookie(resp, csrf2)
        return resp

    # regra mínima simples (você pode endurecer depois)
    if len(new_password) < 8:
        csrf2 = _make_csrf()
        resp = templates.TemplateResponse(
            "change.html",
            {"request": request, "csrf": csrf2, "error": "A nova senha deve ter pelo menos 8 caracteres."},
            status_code=400,
        )
        _set_csrf_cookie(resp, csrf2)
        return resp

    # atualiza senha
    u.password_hash = argon2.hash(new_password)
    u.must_change_password = False
    u.password_changed_at = agora_br()
    u.password_version = int(u.password_version or 0) + 1
    db.commit()

    # reemite token com versão nova
    token = _jwt_encode({"uid": u.id, "role": u.role, "pv": u.password_version}, 60 * 60 * SESSION_EXPIRE_HOURS)
    resp = RedirectResponse("/", status_code=303)
    _set_session_cookie(resp, token)

    csrf2 = _make_csrf()
    _set_csrf_cookie(resp, csrf2)
    return resp

@app.get("/forgot", response_class=HTMLResponse)
def forgot_page(request: Request):
    csrf = _make_csrf()
    resp = templates.TemplateResponse("forgot.html", {"request": request, "csrf": csrf})
    _set_csrf_cookie(resp, csrf)
    return resp

@app.post("/forgot", response_class=HTMLResponse)
def forgot_post(
    request: Request,
    username_or_email: str = Form(...),
    csrf: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf)

    q = db.query(UserDB)
    val = (username_or_email or "").strip()
    u = q.filter(or_(func.lower(UserDB.username) == val.lower(), func.lower(UserDB.email) == val.lower())).first()

    csrf2 = _make_csrf()

    if not u or not u.is_active:
        # não revela se usuário existe
        resp = templates.TemplateResponse(
            "forgot.html",
            {"request": request, "csrf": csrf2, "msg": "Se o usuário existir, um link será gerado."},
        )
        _set_csrf_cookie(resp, csrf2)
        return resp

    token = _jwt_encode({"uid": u.id, "purpose": "reset"}, 60 * RESET_TOKEN_MINUTES)
    reset_link = f"/reset?token={token}"

    resp = templates.TemplateResponse(
        "forgot.html",
        {"request": request, "csrf": csrf2, "msg": "Link gerado com sucesso.", "reset_link": reset_link},
    )
    _set_csrf_cookie(resp, csrf2)
    return resp

def _render_reset_html(error: Optional[str] = None, token: str = "") -> HTMLResponse:
    # como você não mandou reset.html, deixei embutido (não quebra o sistema)
    err_html = f'<div style="margin-top:10px;padding:10px 12px;border-radius:10px;font-size:13px;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.25)">{error}</div>' if error else ""
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head>
<meta charset="UTF-8" />
<title>Reset de senha - Faturas MSHOP</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
body{{margin:0;font-family:system-ui;background:#0b1220;color:#e5e7eb;min-height:100vh;display:grid;place-items:center}}
.card{{width:100%;max-width:520px;background:#0f1a2e;border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:22px;box-shadow:0 10px 30px rgba(0,0,0,.35)}}
h1{{margin:0 0 6px;font-size:22px}}
.muted{{color:#94a3b8;font-size:13px;margin:0 0 12px}}
label{{display:block;margin:12px 0 6px;font-size:13px;color:#cbd5e1}}
input{{width:100%;padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.12);background:#0b1426;color:#e5e7eb;outline:none}}
.btn{{margin-top:14px;width:100%;padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.14);background:#1f6feb;color:white;font-weight:700;cursor:pointer}}
.btn:hover{{filter:brightness(1.05)}}
a{{color:#93c5fd;text-decoration:none}} a:hover{{text-decoration:underline}}
</style></head>
<body><div class="card">
<h1>Reset de senha</h1>
<p class="muted">Defina uma nova senha para sua conta.</p>
{err_html}
<form method="post" action="/reset">
  <input type="hidden" name="token" value="{token}"/>
  <label>Nova senha</label>
  <input name="new_password" type="password" autocomplete="new-password" required />
  <button class="btn" type="submit">Atualizar</button>
</form>
<p style="margin-top:14px;"><a href="/login">Voltar ao login</a></p>
</div></body></html>"""
    return HTMLResponse(content=html)

@app.get("/reset", response_class=HTMLResponse)
def reset_page(token: str):
    # valida token
    try:
        payload = _jwt_decode(token)
        if payload.get("purpose") != "reset":
            return _render_reset_html("Token inválido.", token=token)
    except Exception:
        return _render_reset_html("Token expirado ou inválido.", token=token)
    return _render_reset_html(None, token=token)

@app.post("/reset", response_class=HTMLResponse)
def reset_post(token: str = Form(...), new_password: str = Form(...), db: Session = Depends(get_db)):
    try:
        payload = _jwt_decode(token)
        if payload.get("purpose") != "reset":
            return _render_reset_html("Token inválido.", token=token)
        uid = int(payload.get("uid"))
    except Exception:
        return _render_reset_html("Token expirado ou inválido.", token=token)

    u = db.query(UserDB).filter(UserDB.id == uid).first()
    if not u or not u.is_active:
        return _render_reset_html("Usuário inválido.", token=token)

    if len(new_password) < 8:
        return _render_reset_html("A nova senha deve ter pelo menos 8 caracteres.", token=token)

    u.password_hash = argon2.hash(new_password)
    u.must_change_password = False
    u.password_changed_at = agora_br()
    u.password_version = int(u.password_version or 0) + 1
    db.commit()

    resp = RedirectResponse("/login", status_code=303)
    _clear_auth_cookies(resp)
    return resp

# =========================
# 🔐 ADMIN
# =========================

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    u = require_user(request, db)
    if _pwd_is_expired(u):
        return RedirectResponse("/change-password", status_code=303)
    require_admin(u)

    csrf = _make_csrf()

    trs = db.query(TransportadoraDB).order_by(func.lower(TransportadoraDB.nome)).all()
    users = db.query(UserDB).order_by(func.lower(UserDB.username)).all()
    user_map = {x.id: x.username for x in users}

    resp = templates.TemplateResponse(
        "admin.html",
        {"request": request, "csrf": csrf, "admin": u, "trs": trs, "users": users, "user_map": user_map},
    )
    _set_csrf_cookie(resp, csrf)
    return resp

@app.post("/admin/user/create")
def admin_create_user(
    request: Request,
    csrf: str = Form(...),
    username: str = Form(...),
    email: str = Form(""),
    role: str = Form("user"),
    temp_password: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf)
    admin = require_user(request, db)
    require_admin(admin)

    username = (username or "").strip()
    email = (email or "").strip() or None
    role = (role or "user").strip().lower()
    if role not in ("user", "admin"):
        role = "user"

    exists = db.query(UserDB).filter(func.lower(UserDB.username) == username.lower()).first()
    if exists:
        return RedirectResponse("/admin", status_code=303)

    u = UserDB(
        username=username,
        email=email,
        password_hash=argon2.hash(temp_password),
        role=role,
        is_active=True,
        must_change_password=True,  # força troca no primeiro login
        password_changed_at=None,
        password_version=0,
        created_at=agora_br(),
    )
    db.add(u)
    db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/transportadora/create")
def admin_create_transportadora(
    request: Request,
    csrf: str = Form(...),
    nome: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf)
    admin = require_user(request, db)
    require_admin(admin)

    nome = (nome or "").strip()
    if not nome:
        return RedirectResponse("/admin", status_code=303)

    exists = db.query(TransportadoraDB).filter(func.lower(TransportadoraDB.nome) == nome.lower()).first()
    if not exists:
        db.add(TransportadoraDB(nome=nome, responsavel_user_id=None))
        db.commit()

    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/transportadora/assign")
def admin_assign_transportadora(
    request: Request,
    csrf: str = Form(...),
    transportadora_id: int = Form(...),
    responsavel_user_id: str = Form(""),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf)
    admin = require_user(request, db)
    require_admin(admin)

    tr = db.query(TransportadoraDB).filter(TransportadoraDB.id == transportadora_id).first()
    if not tr:
        return RedirectResponse("/admin", status_code=303)

    if responsavel_user_id.strip() == "":
        tr.responsavel_user_id = None
    else:
        try:
            uid = int(responsavel_user_id)
            u = db.query(UserDB).filter(UserDB.id == uid).first()
            tr.responsavel_user_id = u.id if u else None
        except Exception:
            tr.responsavel_user_id = None

    db.commit()
    return RedirectResponse("/admin", status_code=303)

# =========================
# FATURAS
# =========================

@app.post("/faturas", response_model=FaturaOut)
def criar_fatura(fatura: FaturaCreate, request: Request, db: Session = Depends(get_db)):
    # garante login (middleware já barra, mas aqui garante também)
    _ = require_user(request, db)

    try:
        db_fatura = FaturaDB(
            transportadora=fatura.transportadora,
            numero_fatura=fatura.numero_fatura,
            valor=fatura.valor,
            data_vencimento=fatura.data_vencimento,
            status=fatura.status,
            observacao=fatura.observacao,
        )

        if (fatura.status or "").lower() == "pago":
            registrar_pagamento(db, db_fatura)

        db.add(db_fatura)
        db.commit()
        db.refresh(db_fatura)
        return fatura_to_out(db, db_fatura)
    except Exception as e:
        print("ERRO AO CRIAR FATURA:", repr(e))
        raise HTTPException(status_code=400, detail="Erro ao criar fatura")

@app.get("/faturas", response_model=List[FaturaOut])
def listar_faturas(
    request: Request,
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    ate_vencimento: Optional[str] = Query(None),
    de_vencimento: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
):
    _ = require_user(request, db)

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

@app.put("/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(fatura_id: int, dados: FaturaUpdate, request: Request, db: Session = Depends(get_db)):
    _ = require_user(request, db)

    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    status_antigo = (fatura.status or "").lower()

    data = dados.dict(exclude_unset=True)
    for campo, valor in data.items():
        setattr(fatura, campo, valor)

    status_novo = (fatura.status or "").lower()

    if status_antigo != "pago" and status_novo == "pago":
        registrar_pagamento(db, fatura)

    if status_antigo == "pago" and status_novo != "pago":
        remover_historico_pagamento(db, fatura.id)
        fatura.data_pagamento = None

    db.commit()
    db.refresh(fatura)
    return fatura_to_out(db, fatura)

@app.delete("/faturas/{fatura_id}")
def deletar_fatura(fatura_id: int, request: Request, db: Session = Depends(get_db)):
    _ = require_user(request, db)

    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    for anexo in fatura.anexos:
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
    _ = require_user(request, db)

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
def listar_anexos(fatura_id: int, request: Request, db: Session = Depends(get_db)):
    _ = require_user(request, db)

    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return fatura.anexos

@app.get("/anexos/{anexo_id}")
def baixar_anexo(anexo_id: int, request: Request, db: Session = Depends(get_db)):
    _ = require_user(request, db)

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
    _ = require_user(request, db)

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
    _ = require_user(request, db)

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
    request: Request,
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    de: Optional[str] = Query(None),
    ate: Optional[str] = Query(None),
):
    _ = require_user(request, db)

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
            pago_em=i.pago_em,
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
    request: Request,
    db: Session = Depends(get_db),
    transportadora: Optional[str] = Query(None),
    numero_fatura: Optional[str] = Query(None),
):
    _ = require_user(request, db)

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
        pago_em = ""
        if f.data_pagamento:
            try:
                pago_em = f.data_pagamento.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                pago_em = str(f.data_pagamento)

        # responsável via db ou fallback
        resp_db = get_responsavel_from_db(db, f.transportadora)
        resp = resp_db or get_responsavel_fallback(f.transportadora) or ""

        writer.writerow(
            [
                f.id,
                f.transportadora,
                resp,
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
