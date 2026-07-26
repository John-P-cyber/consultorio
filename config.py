"""Configurações da aplicação carregadas do ambiente."""
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, quote


def carregar_env_local() -> None:
    """Carrega variáveis simples de um .env sem depender de pacote externo."""
    arquivo = Path(__file__).with_name(".env")
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carregar_env_local()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", "15"))
APP_ENV = os.getenv("APP_ENV", "development").lower()
RESET_URL = os.getenv("RESET_URL", "http://127.0.0.1:5500/recuperar-senha.html")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME or "nao-responda@clinica.local")
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500").split(",") if origin.strip()]

if not SECRET_KEY:
    raise RuntimeError("Defina SECRET_KEY no ambiente antes de iniciar a aplicação.")
if not DATABASE_URL:
    raise RuntimeError("Defina DATABASE_URL no ambiente antes de iniciar a aplicação.")

# Se a URL de conexão contiver caracteres não-ASCII na senha (ex: ç, á),
# alguns adaptadores como psycopg2 podem falhar ao decodificar bytes.
# Detectamos e aplicamos percent-encoding (UTF-8) apenas na senha.
if DATABASE_URL:
    try:
        parts = urlsplit(DATABASE_URL)
        netloc = parts.netloc
        if "@" in netloc:
            userinfo, hostinfo = netloc.rsplit("@", 1)
            if ":" in userinfo:
                username, password = userinfo.split(":", 1)
                # detecta caracteres não-ASCII
                if any(ord(ch) > 127 for ch in password):
                    encoded_pw = quote(password, safe="")
                    new_netloc = f"{username}:{encoded_pw}@{hostinfo}"
                    DATABASE_URL = urlunsplit((parts.scheme, new_netloc, parts.path or "", parts.query or "", parts.fragment or ""))
    except Exception:
        # Não falhar aqui; se algo der errado, deixamos a URL original e
        # deixamos que a tentativa de conexão gere erro para diagnóstico.
        pass
