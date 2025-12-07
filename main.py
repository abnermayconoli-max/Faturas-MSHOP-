from datetime import date
from typing import List, Optional
import os

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Date, Numeric
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# ==========================
# CONFIGURAÇÃO DO BANCO
# ==========================

# Render: vamos ler a URL do banco da variável de ambiente DATABASE_URL
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./test.db")

# Se for SQLite (local), precisa do connect_args; no Render será Postgres e não entra nesse if
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ==========================
# MODELO ORM (SQLAlchemy)
# ==========================

class FaturaORM(Base):
    __tablename__ = "faturas"

    id = Column(Integer, primary_key=True, index=True)
    transportadora = Column(String, nullable=False)
    numero_fatura = Column(String, nullable=False)
    valor = Column(Numeric(10, 2), nullable=False)
    data_vencimento = Column(Date, nullable=False)
    status = Column(String, nullable=False, default="pendente")


# Cria as tabelas no banco (se ainda não existirem)
Base.metadata.create_all(bind=engine)


# ==========================
# APP FASTAPI
# ==========================

app = FastAPI(
    title="Sistema de Faturas Transportadoras",
    version="0.2.0",
)


# Dependency: abrir e fechar sessão do banco a cada request
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==========================
# MODELOS Pydantic (entrada/saída)
# ==========================

class FaturaBase(BaseModel):
    transportadora: str
    numero_fatura: str
    valor: float
    data_vencimento: date
    status: str = "pendente"


class FaturaCreate(FaturaBase):
    pass


class Fatura(FaturaBase):
    id: int

    class Config:
        orm_mode = True


# ==========================
# ROTAS
# ==========================

@app.get("/")
def read_root():
    return {"mensagem": "API de Faturas com banco de dados!"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/faturas", response_model=Fatura)
def criar_fatura(fatura: FaturaCreate, db: Session = Depends(get_db)):
    """
    Cria uma nova fatura no banco de dados.
    """
    db_fatura = FaturaORM(
        transportadora=fatura.transportadora,
        numero_fatura=fatura.numero_fatura,
        valor=fatura.valor,
        data_vencimento=fatura.data_vencimento,
        status=fatura.status,
    )
    db.add(db_fatura)
    db.commit()
    db.refresh(db_fatura)
    return db_fatura


@app.get("/faturas", response_model=List[Fatura])
def listar_faturas(db: Session = Depends(get_db)):
    """
    Lista todas as faturas cadastradas no banco.
    """
    faturas = db.query(FaturaORM).all()
    return faturas
