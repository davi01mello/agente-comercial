"""Conexão com o banco (SQLAlchemy). SQLite no dev, Postgres em produção."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _ligar_chaves_estrangeiras(dbapi_conexao, _registro):
        """O SQLite ignora FOREIGN KEY por padrão (o Postgres não). Ligamos para o dev se comportar como a produção:
        uma relação apontando para um insight que não existe passa a dar erro aqui também, não só no deploy."""
        cursor = dbapi_conexao.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependência do FastAPI: abre uma sessão por requisição e fecha no final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
