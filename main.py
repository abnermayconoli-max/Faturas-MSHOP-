from datetime import date, datetime, timedelta
import os
import uuid
import secrets
import time
from typing import List, Optional, Dict, Any

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
    Numeric,
    ForeignKey,
    func,
    and_,
    or_,
    text,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

# ===== AUTH / SEGURANÇA (NOVO) =====
from passlib.context import CryptContext
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
# ===== AUTH CONFIG (NOVO)
# =========================

COOKIE_NAME = "mshop_session"
COOKIE_MAX_AGE_SECONDS = int(os.getenv("COOKIE_MAX_AGE_SECONDS", "43200"))  # 12h

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    # 🔒 obrigatório (pra “quase impossível hackear” não pode ser fraco/ausente)
    raise RuntimeError("JWT_SECRET não configurada nas variáveis de ambiente do Render.")

JWT_ALG = "HS256"

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
)

# Rate limit simples (memória) — suficiente pra frear brute force básico
_RATE_BUCKET: Dict[str, List[float]] = {}  # key -> timestamps
RATE_LIMIT_WINDOW = 60.0  # 60s
RATE_LIMIT_MAX = 10       # 10 tentativas por minuto por IP/rota

def rate_limit(request: Request, key_suffix: str):
    ip = request.client.host if request.client else "unknown"
    k = f"{ip}:{key_suffix}"
    now = time.time()
    arr = _RATE_BUCKET.get(k, [])
    arr = [t for t in arr if (now - t) <= RATE_LIMIT_WINDOW]
    if len(arr) >= RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 1 minuto e tente novamente.")
    arr.append(now)
    _RATE_BUCKET[k] = arr

def hash_password(pw: str) -> str:
    return pwd_context.hash(pw)

def verify_password(pw: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(pw, hashed)
    except Exception:
        return False

def make_jwt(payload: Dict[str, Any], expires_delta: timedelta):
    now = datetime.utcnow()
    exp = now + expires_delta
    to_encode = dict(payload)
    to_encode.update({"exp": exp, "iat": now})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)

def decode_jwt(token: str) -> Dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])

# =========================
# MODELOS (EXISTENTES + NOVOS)
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

# ===== NOVO: usuários (login) =====
class UserDB(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")  # user | admin
    is_active = Column(Boolean, default=True)

    # expiração de senha
    password_changed_at = Column(DateTime(timezone=True), nullable=True)
    password_change_count = Column(Integer, default=0)  # 0 = nunca trocou
    password_cycle_days = Column(Integer, default=90)   # 1ª troca: 90 dias, depois 180
    must_change_password = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(BR_TZ))
    last_login_at = Column(DateTime(timezone=True), nullable=True)

# ===== NOVO: Transportadoras cadastráveis + responsável =====
class TransportadoraDB(Base):
    __tablename__ = "transportadoras"
    __table_args__ = (UniqueConstraint("nome", name="uq_transportadoras_nome"),)

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False, index=True)
    responsavel = Column(String, nullable=True)
    ativa = Column(Boolean, default=True)
    criada_em = Column(DateTime(timezone=True), default=lambda: datetime.now(BR_TZ))

# cria tabelas básicas
Base.metadata.create_all(bind=engine)

# =========================
# ✅ MIGRAÇÃO AUTOMÁTICA (Render)
# =========================

def ensure_schema():
    """
    - garante TIMESTAMPTZ nas datas de pagamento
    - cria tabela historico_pagamentos se não existir
    - cria tabelas users e transportadoras
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
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                password_changed_at TIMESTAMPTZ,
                password_change_count INTEGER NOT NULL DEFAULT 0,
                password_cycle_days INTEGER NOT NULL DEFAULT 90,
                must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_login_at TIMESTAMPTZ
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);"))

        # --- transportadoras ---
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS transportadoras (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL UNIQUE,
                responsavel TEXT,
                ativa BOOLEAN NOT NULL DEFAULT TRUE,
                criada_em TIMESTAMPTZ DEFAULT NOW()
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transportadoras_nome ON transportadoras(nome);"))

ensure_schema()

# =========================
# Pydantic (EXISTENTES + NOVOS)
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

# ===== NOVO: transportadora admin =====
class TransportadoraCreate(BaseModel):
    nome: str
    responsavel: Optional[str] = None

class TransportadoraUpdate(BaseModel):
    responsavel: Optional[str] = None
    ativa: Optional[bool] = None

class TransportadoraOut(BaseModel):
    id: int
    nome: str
    responsavel: Optional[str] = None
    ativa: bool
    class Config:
        from_attributes = True

# =========================
# RESPONSÁVEL (mantém seu map, mas permite override por DB)
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

def get_responsavel_db(db: Session, transportadora: str) -> Optional[str]:
    # 1) tenta buscar no cadastro dinâmico
    t = db.query(TransportadoraDB).filter(TransportadoraDB.nome == transportadora).first()
    if t and t.responsavel:
        return t.responsavel

    # 2) fallback: seu mapeamento fixo
    if transportadora in RESP_MAP:
        return RESP_MAP[transportadora]
    base = transportadora.split("-")[0].strip()
    return RESP_MAP.get(base)

def fatura_to_out(db: Session, f: FaturaDB) -> FaturaOut:
    return FaturaOut(
        id=f.id,
        transportadora=f.transportadora,
        numero_fatura=f.numero_fatura,
        valor=float(f.valor or 0),
        data_vencimento=f.data_vencimento,
        status=f.status,
        observacao=f.observacao,
        responsavel=get_responsavel_db(db, f.transportadora),
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

    hist = HistoricoPagamentoDB(
        fatura_id=fatura.id,
        pago_em=pago_em,
        transportadora=fatura.transportadora,
        responsavel=get_responsavel_db(db, fatura.transportadora),
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
# ===== AUTH HELPERS (NOVO)
# =========================

def get_token_from_cookie(request: Request) -> Optional[str]:
    return request.cookies.get(COOKIE_NAME)

def get_current_user(request: Request, db: Session) -> UserDB:
    token = get_token_from_cookie(request)
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    try:
        payload = decode_jwt(token)
        user_id = int(payload.get("sub"))
    except (JWTError, Exception):
        raise HTTPException(status_code=401, detail="Sessão inválida.")
    user = db.query(UserDB).filter(UserDB.id == user_id, UserDB.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuário inválido.")
    return user

def require_user(request: Request, db: Session = Depends(get_db)) -> UserDB:
    return get_current_user(request, db)

def require_admin(request: Request, db: Session = Depends(get_db)) -> UserDB:
    u = get_current_user(request, db)
    if (u.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado.")
    return u

def password_needs_change(user: UserDB) -> bool:
    if user.must_change_password:
        return True
    if not user.password_changed_at:
        return True
    # expiração por ciclo
    cycle = int(user.password_cycle_days or 90)
    expira_em = user.password_changed_at + timedelta(days=cycle)
    # comparar em UTC-aware: nosso campo é timestamptz, então vem aware; mas garantimos:
    now = datetime.now(BR_TZ)
    try:
        # converte pra BR para comparar (sem risco)
        expira_em_br = user.password_changed_at.astimezone(BR_TZ)
    except Exception:
        expira_em_br = user.password_changed_at
    return now > expira_em_br

# =========================
# APP / STATIC / TEMPLATES
# =========================

app = FastAPI(title="Sistema de Faturas", version="1.0.0")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# =========================
# ===== PROTEÇÃO DE ROTAS (NOVO)
# =========================

PUBLIC_PATHS_PREFIX = (
    "/static",
    "/login",
    "/logout",
    "/health",
    "/forgot",
    "/reset",
    "/change-password",
)

@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path or "/"

    # libera públicos
    if path == "/" or path.startswith(PUBLIC_PATHS_PREFIX):
        # "/" vamos tratar no handler, pra redirecionar se não logado
        return await call_next(request)

    # APIs e telas protegidas:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return RedirectResponse("/login", status_code=302)

    try:
        decode_jwt(token)
    except Exception:
        resp = RedirectResponse("/login", status_code=302)
        resp.delete_cookie(COOKIE_NAME)
        return resp

    return await call_next(request)

# =========================
# ROTAS BÁSICAS
# =========================

@app.get("/health")
def health_check():
    return {"status": "ok"}

# =========================
# HOME (Agora exige login)
# =========================

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    # se não logado -> login
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return RedirectResponse("/login", status_code=302)

    # valida token + pega user
    try:
        user = get_current_user(request, db)
    except Exception:
        resp = RedirectResponse("/login", status_code=302)
        resp.delete_cookie(COOKIE_NAME)
        return resp

    # se precisa trocar senha -> força
    if password_needs_change(user):
        return RedirectResponse("/change-password", status_code=302)

    return templates.TemplateResponse("index.html", {"request": request})

# =========================
# ===== LOGIN / LOGOUT (NOVO)
# =========================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: Optional[str] = Query(None)):
    # next permitido: "/" ou "/admin"
    nxt = (next or "/").strip()
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if nxt not in ("/", "/admin"):
        nxt = "/"

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None, "next": nxt},
    )

@app.post("/login")
def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    rate_limit(request, "login")

    nxt = (next or "/").strip()
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if nxt not in ("/", "/admin"):
        nxt = "/"

    user = db.query(UserDB).filter(UserDB.username == username, UserDB.is_active == True).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Usuário ou senha inválidos.", "next": nxt},
        )

    user.last_login_at = datetime.now(BR_TZ)
    db.commit()

    token = make_jwt({"sub": str(user.id)}, expires_delta=timedelta(seconds=COOKIE_MAX_AGE_SECONDS))

    # se senha expirada/forçada
    if password_needs_change(user):
        redirect_to = "/change-password"
    else:
        if nxt == "/admin" and (user.role or "").lower() != "admin":
            redirect_to = "/"
        else:
            redirect_to = nxt

    resp = RedirectResponse(redirect_to, status_code=302)
    resp.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=COOKIE_MAX_AGE_SECONDS,
    )
    return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp

# =========================
# ===== ALTERAR SENHA (NOVO)
# =========================

@app.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request, db: Session = Depends(get_db)):
    # precisa estar logado
    try:
        user = get_current_user(request, db)
    except Exception:
        return RedirectResponse("/login", status_code=302)

    return templates.TemplateResponse(
        "change_password.html",
        {"request": request, "error": None, "username": user.username},
    )

@app.post("/change-password")
def change_password_action(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    rate_limit(request, "change_password")

    try:
        user = get_current_user(request, db)
    except Exception:
        return RedirectResponse("/login", status_code=302)

    if new_password != confirm_password:
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "error": "Confirmação não confere.", "username": user.username},
        )

    # regras mínimas de força (você pode endurecer depois)
    if len(new_password) < 10:
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "error": "Senha muito curta (mínimo 10 caracteres).", "username": user.username},
        )
    if new_password.lower() == user.username.lower():
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "error": "A senha não pode ser igual ao usuário.", "username": user.username},
        )

    if not verify_password(current_password, user.password_hash):
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "error": "Senha atual inválida.", "username": user.username},
        )

    # atualiza senha
    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(BR_TZ)
    user.must_change_password = False

    # ✅ sua regra:
    # - primeira senha que o usuário alterar dura 3 meses
    # - as demais 6 meses
    user.password_change_count = int(user.password_change_count or 0) + 1
    if user.password_change_count == 1:
        user.password_cycle_days = 90
    else:
        user.password_cycle_days = 180

    db.commit()

    return RedirectResponse("/", status_code=302)

# =========================
# ===== ESQUECI SENHA (NOVO - versão segura sem e-mail)
# =========================
# Observação:
# - aqui não “revela” usuário existente
# - reset real: recomendado fazer via Admin (endpoint abaixo)
# - Eu deixei essa tela apenas informativa (pra você evoluir depois)

@app.get("/forgot", response_class=HTMLResponse)
def forgot_page(request: Request):
    return templates.TemplateResponse("forgot.html", {"request": request, "msg": None})

@app.post("/forgot", response_class=HTMLResponse)
def forgot_action(request: Request, username: str = Form(...)):
    # não revela se existe ou não
    msg = "Se o usuário existir, peça para um Admin gerar um link de redefinição."
    return templates.TemplateResponse("forgot.html", {"request": request, "msg": msg})

# =========================
# ===== ADMIN (NOVO)
# =========================

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    return templates.TemplateResponse("admin.html", {"request": request, "username": user.username})

# ---- Admin API: transportadoras ----

@app.get("/admin/transportadoras", response_model=List[TransportadoraOut])
def admin_listar_transportadoras(db: Session = Depends(get_db), user: UserDB = Depends(require_admin)):
    itens = db.query(TransportadoraDB).order_by(TransportadoraDB.nome.asc()).all()
    return itens

@app.post("/admin/transportadoras", response_model=TransportadoraOut)
def admin_criar_transportadora(
    payload: TransportadoraCreate,
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_admin),
):
    nome = (payload.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome obrigatório.")
    existe = db.query(TransportadoraDB).filter(TransportadoraDB.nome == nome).first()
    if existe:
        raise HTTPException(status_code=400, detail="Transportadora já existe.")

    t = TransportadoraDB(nome=nome, responsavel=(payload.responsavel or None), ativa=True)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t

@app.put("/admin/transportadoras/{tid}", response_model=TransportadoraOut)
def admin_atualizar_transportadora(
    tid: int,
    payload: TransportadoraUpdate,
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_admin),
):
    t = db.query(TransportadoraDB).filter(TransportadoraDB.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="Transportadora não encontrada.")

    if payload.responsavel is not None:
        t.responsavel = payload.responsavel or None
    if payload.ativa is not None:
        t.ativa = bool(payload.ativa)

    db.commit()
    db.refresh(t)
    return t

# ---- Admin API: criar usuário e resetar senha (sem e-mail) ----

@app.post("/admin/users/criar")
def admin_criar_usuario(
    request: Request,
    username: str = Form(...),
    role: str = Form("user"),
    temp_password: str = Form(...),
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_admin),
):
    u = (username or "").strip()
    if not u:
        raise HTTPException(status_code=400, detail="Usuário obrigatório.")
    if len(temp_password) < 10:
        raise HTTPException(status_code=400, detail="Senha temporária deve ter no mínimo 10 caracteres.")
    role = (role or "user").strip().lower()
    if role not in ("user", "admin"):
        role = "user"

    existe = db.query(UserDB).filter(UserDB.username == u).first()
    if existe:
        raise HTTPException(status_code=400, detail="Usuário já existe.")

    novo = UserDB(
        username=u,
        password_hash=hash_password(temp_password),
        role=role,
        is_active=True,
        password_changed_at=datetime.now(BR_TZ),
        password_change_count=0,
        password_cycle_days=90,
        must_change_password=True,
        created_at=datetime.now(BR_TZ),
    )
    db.add(novo)
    db.commit()
    return {"ok": True}

@app.post("/admin/users/{uid}/reset")
def admin_reset_senha(
    uid: int,
    temp_password: str = Form(...),
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_admin),
):
    if len(temp_password) < 10:
        raise HTTPException(status_code=400, detail="Senha temporária deve ter no mínimo 10 caracteres.")
    alvo = db.query(UserDB).filter(UserDB.id == uid).first()
    if not alvo:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    alvo.password_hash = hash_password(temp_password)
    alvo.password_changed_at = datetime.now(BR_TZ)
    alvo.must_change_password = True
    alvo.password_change_count = int(alvo.password_change_count or 0)  # não conta como troca do usuário
    alvo.password_cycle_days = 90
    db.commit()
    return {"ok": True}

# =========================
# =========================
# FATURAS (EXISTENTE)
# =========================
# =========================

@app.post("/faturas", response_model=FaturaOut)
def criar_fatura(fatura: FaturaCreate, db: Session = Depends(get_db), user: UserDB = Depends(require_user)):
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
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_user),
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
    return [fatura_to_out(db, f) for f in faturas_db]

@app.put("/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(
    fatura_id: int,
    dados: FaturaUpdate,
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_user),
):
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
def deletar_fatura(
    fatura_id: int,
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_user),
):
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
# ANEXOS (EXISTENTE)
# =========================

@app.post("/faturas/{fatura_id}/anexos", response_model=List[AnexoOut])
async def upload_anexos(
    fatura_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_user),
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
def listar_anexos(
    fatura_id: int,
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_user),
):
    fatura = db.query(FaturaDB).filter(FaturaDB.id == fatura_id).first()
    if not fatura:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return fatura.anexos

@app.get("/anexos/{anexo_id}")
def baixar_anexo(
    anexo_id: int,
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_user),
):
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
def deletar_anexo(
    anexo_id: int,
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_user),
):
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
# DASHBOARD (EXISTENTE)
# =========================

@app.get("/dashboard/resumo")
def resumo_dashboard(
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_user),
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
# HISTÓRICO (EXISTENTE)
# =========================

@app.get("/historico_pagamentos", response_model=List[HistoricoPagamentoOut])
def listar_historico_pagamentos(
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_user),
    transportadora: Optional[str] = Query(None),
    de: Optional[str] = Query(None),
    ate: Optional[str] = Query(None),
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
# EXPORT CSV (EXISTENTE)
# =========================

@app.get("/faturas/exportar")
def exportar_faturas(
    db: Session = Depends(get_db),
    user: UserDB = Depends(require_user),
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
                get_responsavel_db(db, f.transportadora) or "",
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

# =========================
# BOOTSTRAP ADMIN INICIAL (NOVO)
# =========================
# Você define no Render:
#   BOOTSTRAP_ADMIN_USER=abner
#   BOOTSTRAP_ADMIN_PASS=SenhaForteAqui! (min 10)
#
# Ele cria somente se ainda NÃO existir nenhum admin.
def bootstrap_admin():
    admin_user = os.getenv("BOOTSTRAP_ADMIN_USER")
    admin_pass = os.getenv("BOOTSTRAP_ADMIN_PASS")

    if not admin_user or not admin_pass:
        return

    if len(admin_pass) < 10:
        print("WARN bootstrap: BOOTSTRAP_ADMIN_PASS muito curta (mín 10).")
        return

    db = SessionLocal()
    try:
        existe_admin = db.query(UserDB).filter(UserDB.role == "admin").first()
        if existe_admin:
            return

        existe_user = db.query(UserDB).filter(UserDB.username == admin_user).first()
        if existe_user:
            # promove para admin
            existe_user.role = "admin"
            existe_user.is_active = True
            db.commit()
            print("BOOTSTRAP: usuário existente promovido para admin.")
            return

        novo = UserDB(
            username=admin_user.strip(),
            password_hash=hash_password(admin_pass),
            role="admin",
            is_active=True,
            password_changed_at=datetime.now(BR_TZ),
            password_change_count=0,
            password_cycle_days=90,
            must_change_password=True,  # força trocar no primeiro login
            created_at=datetime.now(BR_TZ),
        )
        db.add(novo)
        db.commit()
        print("BOOTSTRAP: admin inicial criado com sucesso.")
    except Exception as e:
        print("ERRO bootstrap_admin:", repr(e))
    finally:
        db.close()

bootstrap_admin()
