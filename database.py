from sqlalchemy import create_engine
from sqlalchemy.engine import URL # Adicione esta linha
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Construa a URL de forma segura (Substitua os dados abaixo pelos seus)
url_banco = URL.create(
    drivername="postgresql",
    username="postgres",
    password="260205",  # Pode colocar a senha com @, #, etc., sem problemas aqui
    host="localhost",
    port=5432,
    database="consultorio"
)

# Use a variável url_banco no lugar da string
engine = create_engine(url_banco)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()