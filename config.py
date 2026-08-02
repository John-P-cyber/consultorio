"""Configurações da aplicação carregadas do ambiente."""
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, quote


def carregar_env_local() -> None:
    """Carrega variáveis simples de um .env sem depender de pacote externo."""
    if os.getenv("RENDER", "").lower() == "true":
        return
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
APP_ENV = os.getenv("APP_ENV", "development").lower()
PRODUCTION_LIKE = APP_ENV in {"staging", "production"}
SERVICE_NAME = os.getenv("SERVICE_NAME", "consultorio-api")
RELEASE_SHA = os.getenv("RELEASE_SHA") or os.getenv("RENDER_GIT_COMMIT", "local")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
DB_POOL_TIMEOUT_SECONDS = int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "10"))
DB_POOL_RECYCLE_SECONDS = int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800"))
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))
MFA_CHALLENGE_EXPIRE_MINUTES = int(os.getenv("MFA_CHALLENGE_EXPIRE_MINUTES", "5"))
MFA_LOCK_MINUTES = int(os.getenv("MFA_LOCK_MINUTES", "15"))
SESSION_MAX_ACTIVE = int(os.getenv("SESSION_MAX_ACTIVE", "10"))
RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", "15"))
MFA_MASTER_KEY = os.getenv("MFA_MASTER_KEY") or (SECRET_KEY if not PRODUCTION_LIKE else None)
MFA_ISSUER = os.getenv("MFA_ISSUER", "Clinica Saude")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true" if PRODUCTION_LIKE else "false").lower() in {"1", "true", "yes", "sim"}
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "strict").lower()
ACCESS_COOKIE_NAME = "__Host-clinica_access" if COOKIE_SECURE else "clinica_access"
REFRESH_COOKIE_NAME = "__Host-clinica_refresh" if COOKIE_SECURE else "clinica_refresh"
PREAUTH_COOKIE_NAME = "__Host-clinica_preauth" if COOKIE_SECURE else "clinica_preauth"
CSRF_COOKIE_NAME = "__Host-clinica_csrf" if COOKIE_SECURE else "clinica_csrf"
RESET_URL = os.getenv(
    "RESET_URL",
    f"{RENDER_EXTERNAL_URL}/recuperar-senha.html"
    if RENDER_EXTERNAL_URL
    else "http://127.0.0.1:8000/recuperar-senha.html",
)
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME or "nao-responda@clinica.local")
ADMIN_BOOTSTRAP_TOKEN = os.getenv("ADMIN_BOOTSTRAP_TOKEN")
CLINIC_PROVISIONING_TOKEN = os.getenv("CLINIC_PROVISIONING_TOKEN", ADMIN_BOOTSTRAP_TOKEN)
TERMOS_VERSAO = os.getenv("TERMOS_VERSAO", "2026-08-01")
PRIVACIDADE_VERSAO = os.getenv("PRIVACIDADE_VERSAO", "2026-08-01-v2")
PRONTUARIO_RETENTION_YEARS = int(os.getenv("PRONTUARIO_RETENTION_YEARS", "20"))
PRONTUARIO_UPLOAD_DIR = Path(
    os.getenv("PRONTUARIO_UPLOAD_DIR", str(Path(__file__).with_name("uploads") / "prontuarios"))
).resolve()
PRONTUARIO_MAX_UPLOAD_MB = int(os.getenv("PRONTUARIO_MAX_UPLOAD_MB", "10"))
ALLOWED_ORIGINS_DEFAULT = RENDER_EXTERNAL_URL or "http://127.0.0.1:5500,http://localhost:5500"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", ALLOWED_ORIGINS_DEFAULT).split(",")
    if origin.strip()
]

if not SECRET_KEY:
    raise RuntimeError("Defina SECRET_KEY no ambiente antes de iniciar a aplicação.")
if len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY deve ter pelo menos 32 caracteres.")
if not MFA_MASTER_KEY or len(MFA_MASTER_KEY) < 32:
    raise RuntimeError("MFA_MASTER_KEY deve ter pelo menos 32 caracteres.")
if not DATABASE_URL:
    raise RuntimeError("Defina DATABASE_URL no ambiente antes de iniciar a aplicação.")
if APP_ENV not in {"development", "test", "staging", "production"}:
    raise RuntimeError("APP_ENV deve ser development, test, staging ou production.")
if PRODUCTION_LIKE and "*" in ALLOWED_ORIGINS:
    raise RuntimeError("ALLOWED_ORIGINS não pode conter '*' em staging ou produção.")
if PRODUCTION_LIKE and not ALLOWED_ORIGINS:
    raise RuntimeError("Defina ALLOWED_ORIGINS em staging e produção.")
if PRODUCTION_LIKE and any(not origin.startswith("https://") for origin in ALLOWED_ORIGINS):
    raise RuntimeError("ALLOWED_ORIGINS deve conter apenas origens HTTPS em staging e produção.")
if PRODUCTION_LIKE and not CLINIC_PROVISIONING_TOKEN:
    raise RuntimeError("Defina CLINIC_PROVISIONING_TOKEN em staging e produção.")
if PRODUCTION_LIKE and MFA_MASTER_KEY == SECRET_KEY:
    raise RuntimeError("MFA_MASTER_KEY deve ser diferente de SECRET_KEY em staging e produção.")
if PRODUCTION_LIKE and not COOKIE_SECURE:
    raise RuntimeError("COOKIE_SECURE deve permanecer habilitado em staging e produção.")
if PRODUCTION_LIKE and not RESET_URL.startswith("https://"):
    raise RuntimeError("RESET_URL deve usar HTTPS em staging e produção.")
if LOG_LEVEL not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
    raise RuntimeError("LOG_LEVEL inválido.")
if DB_POOL_SIZE < 1 or DB_POOL_SIZE > 50:
    raise RuntimeError("DB_POOL_SIZE deve estar entre 1 e 50.")
if DB_MAX_OVERFLOW < 0 or DB_MAX_OVERFLOW > 100:
    raise RuntimeError("DB_MAX_OVERFLOW deve estar entre 0 e 100.")
if DB_POOL_TIMEOUT_SECONDS < 1 or DB_POOL_TIMEOUT_SECONDS > 120:
    raise RuntimeError("DB_POOL_TIMEOUT_SECONDS deve estar entre 1 e 120.")
if DB_POOL_RECYCLE_SECONDS < 60 or DB_POOL_RECYCLE_SECONDS > 86400:
    raise RuntimeError("DB_POOL_RECYCLE_SECONDS deve estar entre 60 e 86400.")
if COOKIE_SAMESITE not in {"strict", "lax"}:
    raise RuntimeError("COOKIE_SAMESITE deve ser 'strict' ou 'lax'.")
if ACCESS_TOKEN_EXPIRE_MINUTES < 5 or ACCESS_TOKEN_EXPIRE_MINUTES > 30:
    raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES deve estar entre 5 e 30 minutos.")
if REFRESH_TOKEN_EXPIRE_DAYS < 1 or REFRESH_TOKEN_EXPIRE_DAYS > 90:
    raise RuntimeError("REFRESH_TOKEN_EXPIRE_DAYS deve estar entre 1 e 90 dias.")
if MFA_CHALLENGE_EXPIRE_MINUTES < 2 or MFA_CHALLENGE_EXPIRE_MINUTES > 15:
    raise RuntimeError("MFA_CHALLENGE_EXPIRE_MINUTES deve estar entre 2 e 15 minutos.")
if MFA_LOCK_MINUTES < 5 or MFA_LOCK_MINUTES > 120:
    raise RuntimeError("MFA_LOCK_MINUTES deve estar entre 5 e 120 minutos.")
if SESSION_MAX_ACTIVE < 1 or SESSION_MAX_ACTIVE > 50:
    raise RuntimeError("SESSION_MAX_ACTIVE deve estar entre 1 e 50.")
if PRONTUARIO_RETENTION_YEARS < 20:
    raise RuntimeError("PRONTUARIO_RETENTION_YEARS não pode ser inferior a 20 anos.")
if PRONTUARIO_MAX_UPLOAD_MB < 1 or PRONTUARIO_MAX_UPLOAD_MB > 50:
    raise RuntimeError("PRONTUARIO_MAX_UPLOAD_MB deve estar entre 1 e 50.")

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
