import hmac
import hashlib
import json
import math
import secrets
import smtplib
from uuid import uuid4
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, List
from urllib.parse import urlencode

import jwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

import models
import schemas
from auth_service import (
    gerar_codigo_totp,
    gerar_codigos_recuperacao,
    hash_codigo_recuperacao,
    hash_contexto,
    hash_token,
    novo_salt_mfa,
    segredo_totp,
    uri_totp,
    verificar_codigo_totp,
)
from config import (
    ACCESS_COOKIE_NAME,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALLOWED_ORIGINS,
    APP_ENV,
    CLINIC_PROVISIONING_TOKEN,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    CSRF_COOKIE_NAME,
    MFA_CHALLENGE_EXPIRE_MINUTES,
    MFA_ISSUER,
    MFA_LOCK_MINUTES,
    PREAUTH_COOKIE_NAME,
    PRIVACIDADE_VERSAO,
    PRODUCTION_LIKE,
    PRONTUARIO_MAX_UPLOAD_MB,
    PRONTUARIO_RETENTION_YEARS,
    PRONTUARIO_UPLOAD_DIR,
    REFRESH_COOKIE_NAME,
    REFRESH_TOKEN_EXPIRE_DAYS,
    RESET_TOKEN_EXPIRE_MINUTES,
    RESET_URL,
    SECRET_KEY,
    SESSION_MAX_ACTIVE,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    TERMOS_VERSAO,
)
from database import SessionLocal, engine
from lgpd_service import (
    BASES_LEGAIS_DOCUMENTOS,
    FINALIDADES_DOCUMENTOS,
    criar_consentimentos_obrigatorios,
    dados_requisicao,
    hash_documento,
    registrar_auditoria,
    validar_aceite_documentos,
    verificar_integridade_auditoria,
)
from prontuario_service import (
    ASSINATURA_INTERNA,
    assinar_documento,
    hash_payload,
    payload_evento_prescricao,
    payload_prescricao,
    payload_prontuario,
    verificar_assinatura,
)
from observability import (
    HTTP_DURATION,
    HTTP_IN_PROGRESS,
    HTTP_REQUESTS,
    DATABASE_READY,
    configurar_logging,
    metrics_content_type,
    metrics_payload,
    monotonic_time,
    request_id,
    route_template,
)

ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
DUMMY_PASSWORD_HASH = pwd_context.hash("dummy-password-used-only-for-timing-123")
logger = configurar_logging()
tentativas_login: dict[str, list[datetime]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if APP_ENV == "test":
        models.Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Clínica Inteligente - API",
    lifespan=lifespan,
    docs_url=None if PRODUCTION_LIKE else "/docs",
    redoc_url=None if PRODUCTION_LIKE else "/redoc",
    openapi_url=None if PRODUCTION_LIKE else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def observar_requisicao(request: Request, call_next):
    identificador = request_id(request)
    inicio_requisicao = monotonic_time()
    metodo = request.method.upper()
    request.state.request_id = identificador
    HTTP_IN_PROGRESS.labels(metodo).inc()
    status_resposta = 500
    try:
        resposta = await call_next(request)
        status_resposta = resposta.status_code
        resposta.headers["X-Request-ID"] = identificador
        return resposta
    except Exception as exc:
        logger.error(
            "request_failed",
            extra={
                "event": "http_request_failed",
                "error_type": type(exc).__name__,
                "request_id": identificador,
                "method": metodo,
                "route": route_template(request),
                "status": 500,
            },
        )
        resposta = JSONResponse(
            status_code=500,
            content={"detail": "Erro interno do servidor.", "request_id": identificador},
        )
        resposta.headers["X-Request-ID"] = identificador
        return resposta
    finally:
        duracao = monotonic_time() - inicio_requisicao
        rota = route_template(request)
        HTTP_IN_PROGRESS.labels(metodo).dec()
        HTTP_REQUESTS.labels(metodo, rota, str(status_resposta)).inc()
        HTTP_DURATION.labels(metodo, rota).observe(duracao)
        if rota not in {"/metrics", "/health/live", "/health/ready"}:
            logger.info(
                "http_request",
                extra={
                    "event": "http_request",
                    "request_id": identificador,
                    "method": metodo,
                    "route": rota,
                    "status": status_resposta,
                    "duration_ms": round(duracao * 1000, 2),
                },
            )


ROTAS_CSRF_PUBLICAS = {
    "/auth/login",
    "/auth/registrar",
    "/auth/registrar-clinica",
    "/auth/solicitar-recuperacao",
    "/auth/redefinir-senha",
}


@app.middleware("http")
async def proteger_csrf(request: Request, call_next):
    metodo_mutavel = request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    autenticacao_automatica = any(
        request.cookies.get(nome)
        for nome in (ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME, PREAUTH_COOKIE_NAME)
    )
    usa_bearer_explicito = request.headers.get("Authorization", "").lower().startswith("bearer ")
    if (
        metodo_mutavel
        and autenticacao_automatica
        and not usa_bearer_explicito
        and request.url.path not in ROTAS_CSRF_PUBLICAS
    ):
        cookie_csrf = request.cookies.get(CSRF_COOKIE_NAME, "")
        header_csrf = request.headers.get("X-CSRF-Token", "")
        if not cookie_csrf or not header_csrf or not hmac.compare_digest(cookie_csrf, header_csrf):
            return Response(
                content=json.dumps({"detail": "Validação CSRF ausente ou inválida."}),
                status_code=403,
                media_type="application/json",
            )
    return await call_next(request)


@app.middleware("http")
async def adicionar_cabecalhos_seguranca(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    resposta.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resposta.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
    if request.url.path.startswith("/auth/") or request.cookies.get(ACCESS_COOKIE_NAME):
        resposta.headers["Cache-Control"] = "no-store"
        resposta.headers["Pragma"] = "no-cache"
    return resposta


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def commit_ou_conflito(db: Session, mensagem: str = "Os dados informados já estão em uso.") -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=mensagem)


def flush_ou_conflito(db: Session, mensagem: str = "Os dados informados já estão em uso.") -> None:
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=mensagem)


def senha_hash(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha_pura: str, senha_criptografada: str) -> bool:
    return pwd_context.verify(senha_pura, senha_criptografada)


def _agora_utc() -> datetime:
    return datetime.now(UTC)


def _como_utc(valor: datetime) -> datetime:
    return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor.astimezone(UTC)


def _payload_base_sessao(usuario: models.Usuario, sessao: models.SessaoUsuario) -> dict:
    return {
        "sub": str(usuario.id),
        "cid": usuario.clinica_id,
        "role": usuario.role,
        "rv": usuario.reset_version,
        "sid": sessao.id,
    }


def criar_token_acesso(usuario: models.Usuario, sessao: models.SessaoUsuario) -> str:
    agora = _agora_utc()
    payload = {
        **_payload_base_sessao(usuario, sessao),
        "purpose": "access",
        "jti": str(uuid4()),
        "iat": agora,
        "exp": agora + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def criar_token_refresh(usuario: models.Usuario, sessao: models.SessaoUsuario) -> str:
    agora = _agora_utc()
    payload = {
        **_payload_base_sessao(usuario, sessao),
        "purpose": "refresh",
        "rot": sessao.rotacao,
        "jti": str(uuid4()),
        "iat": agora,
        "exp": _como_utc(sessao.expira_em),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def criar_token_preauth(usuario: models.Usuario, proposito: str) -> str:
    agora = _agora_utc()
    return jwt.encode(
        {
            "sub": str(usuario.id),
            "cid": usuario.clinica_id,
            "rv": usuario.reset_version,
            "purpose": proposito,
            "jti": str(uuid4()),
            "iat": agora,
            "exp": agora + timedelta(minutes=MFA_CHALLENGE_EXPIRE_MINUTES),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def _set_cookie(resposta: Response, nome: str, valor: str, max_age: int, *, httponly: bool) -> None:
    resposta.set_cookie(
        key=nome,
        value=valor,
        max_age=max_age,
        path="/",
        secure=COOKIE_SECURE,
        httponly=httponly,
        samesite=COOKIE_SAMESITE,
    )


def configurar_cookies_sessao(resposta: Response, access_token: str, refresh_token: str) -> None:
    _set_cookie(
        resposta, ACCESS_COOKIE_NAME, access_token,
        ACCESS_TOKEN_EXPIRE_MINUTES * 60, httponly=True,
    )
    _set_cookie(
        resposta, REFRESH_COOKIE_NAME, refresh_token,
        REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60, httponly=True,
    )
    _set_cookie(
        resposta, CSRF_COOKIE_NAME, secrets.token_urlsafe(32),
        REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60, httponly=False,
    )
    resposta.delete_cookie(PREAUTH_COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True)


def configurar_cookie_preauth(resposta: Response, token: str) -> None:
    limpar_cookies_sessao(resposta, incluir_csrf=False)
    _set_cookie(
        resposta, PREAUTH_COOKIE_NAME, token,
        MFA_CHALLENGE_EXPIRE_MINUTES * 60, httponly=True,
    )
    _set_cookie(
        resposta, CSRF_COOKIE_NAME, secrets.token_urlsafe(32),
        MFA_CHALLENGE_EXPIRE_MINUTES * 60, httponly=False,
    )


def limpar_cookies_sessao(resposta: Response, *, incluir_csrf: bool = True) -> None:
    for nome, httponly in (
        (ACCESS_COOKIE_NAME, True),
        (REFRESH_COOKIE_NAME, True),
        (PREAUTH_COOKIE_NAME, True),
    ):
        resposta.delete_cookie(nome, path="/", secure=COOKIE_SECURE, httponly=httponly)
    if incluir_csrf:
        resposta.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=False)


def _dados_requisicao_sessao(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return hash_contexto("ip", ip), hash_contexto("user-agent", user_agent)


def emitir_sessao(
    usuario: models.Usuario,
    request: Request,
    db: Session,
    *,
    mfa_verificada: bool,
) -> tuple[models.SessaoUsuario, str, str]:
    agora = _agora_utc()
    sessoes_ativas = db.query(models.SessaoUsuario).filter(
        models.SessaoUsuario.usuario_id == usuario.id,
        models.SessaoUsuario.clinica_id == usuario.clinica_id,
        models.SessaoUsuario.revogado_em.is_(None),
        models.SessaoUsuario.expira_em > agora,
    ).order_by(models.SessaoUsuario.ultimo_uso_em.asc()).all()
    excedentes = max(0, len(sessoes_ativas) - SESSION_MAX_ACTIVE + 1)
    for antiga in sessoes_ativas[:excedentes]:
        antiga.revogado_em = agora
        antiga.motivo_revogacao = "limite_sessoes"

    ip_hash, user_agent_hash = _dados_requisicao_sessao(request)
    sessao = models.SessaoUsuario(
        id=str(uuid4()),
        clinica_id=usuario.clinica_id,
        usuario_id=usuario.id,
        familia_id=str(uuid4()),
        refresh_token_hash="0" * 64,
        rotacao=0,
        criado_em=agora,
        ultimo_uso_em=agora,
        expira_em=agora + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        ip_criacao_hash=ip_hash,
        ip_ultimo_hash=ip_hash,
        user_agent_hash=user_agent_hash,
        mfa_verificada=mfa_verificada,
    )
    db.add(sessao)
    db.flush()
    access_token = criar_token_acesso(usuario, sessao)
    refresh_token = criar_token_refresh(usuario, sessao)
    sessao.refresh_token_hash = hash_token(refresh_token)
    registrar_auditoria(
        db,
        request=request,
        usuario=usuario,
        acao="CRIACAO",
        recurso="sessao",
        detalhes={"sessao_id": sessao.id, "mfa": mfa_verificada},
    )
    db.commit()
    db.refresh(sessao)
    return sessao, access_token, refresh_token


def revogar_sessoes_usuario(db: Session, usuario_id: int, motivo: str) -> int:
    agora = _agora_utc()
    return db.query(models.SessaoUsuario).filter(
        models.SessaoUsuario.usuario_id == usuario_id,
        models.SessaoUsuario.revogado_em.is_(None),
    ).update(
        {"revogado_em": agora, "motivo_revogacao": motivo},
        synchronize_session=False,
    )


def usuario_do_desafio(
    request: Request,
    db: Session,
    *,
    propositos: set[str],
) -> tuple[models.Usuario, dict]:
    token = request.cookies.get(PREAUTH_COOKIE_NAME)
    try:
        payload = jwt.decode(token or "", SECRET_KEY, algorithms=[ALGORITHM])
        usuario_id = int(payload.get("sub"))
        clinica_id = int(payload.get("cid"))
    except (InvalidTokenError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Desafio de autenticação inválido ou expirado.")
    if payload.get("purpose") not in propositos:
        raise HTTPException(status_code=401, detail="Desafio de autenticação inválido ou expirado.")
    usuario = db.query(models.Usuario).join(models.Clinica).filter(
        models.Usuario.id == usuario_id,
        models.Usuario.clinica_id == clinica_id,
        models.Usuario.ativo.is_(True),
        models.Clinica.ativo.is_(True),
    ).first()
    if not usuario or payload.get("rv") != usuario.reset_version:
        raise HTTPException(status_code=401, detail="Desafio de autenticação inválido ou expirado.")
    return usuario, payload


def criar_token_recuperacao(usuario: models.Usuario) -> str:
    return jwt.encode(
        {
            "sub": str(usuario.id),
            "cid": usuario.clinica_id,
            "purpose": "password_reset",
            "rv": usuario.reset_version,
            "exp": datetime.now(UTC) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def enviar_link_recuperacao(destinatario: str, token: str) -> None:
    link = f"{RESET_URL}?{urlencode({'token': token})}"
    if APP_ENV == "development":
        print(f"[RECUPERACAO DE SENHA] Link para {destinatario}: {link}")
        return
    if not SMTP_HOST:
        raise RuntimeError("SMTP_HOST deve ser configurado em produção para recuperar senhas.")
    mensagem = EmailMessage()
    mensagem["Subject"] = "Redefinição de senha - Clínica Saúde"
    mensagem["From"] = SMTP_FROM
    mensagem["To"] = destinatario
    mensagem.set_content(f"Use este link para criar uma nova senha. Ele expira em {RESET_TOKEN_EXPIRE_MINUTES} minutos: {link}")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as servidor:
        servidor.starttls()
        if SMTP_USERNAME and SMTP_PASSWORD:
            servidor.login(SMTP_USERNAME, SMTP_PASSWORD)
        servidor.send_message(mensagem)


def usuario_atual(
    request: Request,
    token_bearer: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.Usuario:
    credencial_invalida = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = token_bearer or request.cookies.get(ACCESS_COOKIE_NAME)
    try:
        payload = jwt.decode(token or "", SECRET_KEY, algorithms=[ALGORITHM])
        usuario_id = payload.get("sub")
        clinica_id = payload.get("cid")
        sessao_id = payload.get("sid")
    except InvalidTokenError:
        raise credencial_invalida
    if not usuario_id or not clinica_id or not sessao_id or payload.get("purpose") != "access":
        raise credencial_invalida
    try:
        usuario_id = int(usuario_id)
        clinica_id = int(clinica_id)
    except (TypeError, ValueError):
        raise credencial_invalida
    usuario = db.query(models.Usuario).join(models.Clinica).filter(
        models.Usuario.id == usuario_id,
        models.Usuario.clinica_id == clinica_id,
        models.Usuario.ativo.is_(True),
        models.Clinica.ativo.is_(True),
    ).first()
    sessao = db.query(models.SessaoUsuario).filter(
        models.SessaoUsuario.id == str(sessao_id),
        models.SessaoUsuario.usuario_id == usuario_id,
        models.SessaoUsuario.clinica_id == clinica_id,
        models.SessaoUsuario.revogado_em.is_(None),
    ).first()
    if (
        not usuario
        or not sessao
        or _como_utc(sessao.expira_em) <= _agora_utc()
        or payload.get("rv", 0) != usuario.reset_version
        or (usuario.role in {"admin", "medico"} and not sessao.mfa_verificada)
    ):
        raise credencial_invalida
    request.state.sessao = sessao
    request.state.autenticacao_cookie = token_bearer is None
    return usuario


def exigir_roles(*roles: str) -> Callable:
    def verificar(usuario: models.Usuario = Depends(usuario_atual)) -> models.Usuario:
        if usuario.role not in roles:
            raise HTTPException(status_code=403, detail="Você não tem permissão para esta ação.")
        return usuario

    return verificar


def paciente_do_usuario(usuario: models.Usuario, db: Session) -> models.Paciente:
    paciente = db.query(models.Paciente).filter(
        models.Paciente.usuario_id == usuario.id,
        models.Paciente.clinica_id == usuario.clinica_id,
    ).first()
    if not paciente:
        raise HTTPException(status_code=403, detail="Seu usuário não está vinculado a um paciente.")
    return paciente


def medico_do_usuario(usuario: models.Usuario, db: Session) -> models.Medico:
    medico = db.query(models.Medico).filter(
        models.Medico.usuario_id == usuario.id,
        models.Medico.clinica_id == usuario.clinica_id,
    ).first()
    if not medico:
        raise HTTPException(status_code=403, detail="Seu usuário não está vinculado a um médico.")
    return medico


def medico_tem_vinculo_com_paciente(clinica_id: int, medico_id: int, paciente_id: int, db: Session) -> bool:
    return db.query(models.Agendamento.id).filter(
        models.Agendamento.clinica_id == clinica_id,
        models.Agendamento.medico_id == medico_id,
        models.Agendamento.paciente_id == paciente_id,
    ).first() is not None


def reautenticar_assinatura(usuario: models.Usuario, senha: str) -> None:
    if not verificar_senha(senha, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="Senha incorreta. O documento clínico não foi assinado.")


def validar_acesso_prontuario(
    *,
    usuario: models.Usuario,
    paciente_id: int,
    motivo_acesso: str | None,
    db: Session,
) -> str:
    motivos = {"assistencia_direta", "assistencia_indireta", "ensino_pesquisa", "judicial", "titular"}
    if usuario.role == "paciente":
        if paciente_do_usuario(usuario, db).id != paciente_id:
            raise HTTPException(status_code=403, detail="Você só pode acessar o próprio prontuário.")
        return "titular"
    if motivo_acesso not in motivos - {"titular"}:
        raise HTTPException(status_code=400, detail="Informe um motivo válido para consultar o prontuário.")
    if usuario.role == "medico":
        medico = medico_do_usuario(usuario, db)
        if not medico_tem_vinculo_com_paciente(usuario.clinica_id, medico.id, paciente_id, db):
            raise HTTPException(status_code=403, detail="Este médico não possui vínculo assistencial com o paciente.")
    return motivo_acesso


def prontuario_acessivel(
    prontuario_id: int,
    usuario: models.Usuario,
    motivo_acesso: str | None,
    db: Session,
) -> tuple[models.ProntuarioEntrada, str]:
    registro = db.query(models.ProntuarioEntrada).filter(
        models.ProntuarioEntrada.id == prontuario_id,
        models.ProntuarioEntrada.clinica_id == usuario.clinica_id,
    ).first()
    if not registro:
        raise HTTPException(status_code=404, detail="Registro de prontuário não encontrado.")
    motivo = validar_acesso_prontuario(
        usuario=usuario, paciente_id=registro.paciente_id, motivo_acesso=motivo_acesso, db=db
    )
    return registro, motivo


def _payload_do_prontuario(registro: models.ProntuarioEntrada) -> dict:
    return payload_prontuario(
        clinica_id=registro.clinica_id,
        serie_id=registro.serie_id,
        versao=registro.versao,
        versao_anterior_id=registro.versao_anterior_id,
        paciente_id=registro.paciente_id,
        medico_id=registro.medico_id,
        agendamento_id=registro.agendamento_id,
        autor_usuario_id=registro.autor_usuario_id,
        autor_nome=registro.autor_nome,
        autor_crm=registro.autor_crm,
        tipo=registro.tipo,
        conteudo=registro.conteudo,
        motivo_retificacao=registro.motivo_retificacao,
        criado_em=registro.criado_em,
        assinado_em=registro.assinado_em,
        assinatura_tipo=registro.assinatura_tipo,
    )


def auditar_lista(
    db: Session,
    request: Request,
    usuario: models.Usuario,
    recurso: str,
    registros: list,
    paciente_id_getter,
) -> None:
    for registro in registros:
        registrar_auditoria(
            db,
            request=request,
            usuario=usuario,
            acao="ACESSO",
            recurso=recurso,
            registro_id=registro.id,
            paciente_id=paciente_id_getter(registro),
        )
    if registros:
        db.commit()
        for registro in registros:
            if hasattr(registro, "_sa_instance_state"):
                db.refresh(registro)


def ultimo_registro_clinico(paciente: models.Paciente, db: Session) -> datetime | None:
    ultimo_agendamento = db.query(func.max(models.Agendamento.data_hora)).filter(
        models.Agendamento.clinica_id == paciente.clinica_id,
        models.Agendamento.paciente_id == paciente.id,
    ).scalar()
    ultimo_exame = db.query(func.max(models.Exame.data_hora)).filter(
        models.Exame.clinica_id == paciente.clinica_id,
        models.Exame.paciente_id == paciente.id,
    ).scalar()
    ultimo_prontuario = db.query(func.max(models.ProntuarioEntrada.criado_em)).filter(
        models.ProntuarioEntrada.clinica_id == paciente.clinica_id,
        models.ProntuarioEntrada.paciente_id == paciente.id,
    ).scalar()
    ultima_prescricao = db.query(func.max(models.Prescricao.criado_em)).filter(
        models.Prescricao.clinica_id == paciente.clinica_id,
        models.Prescricao.paciente_id == paciente.id,
    ).scalar()
    datas = [valor for valor in (ultimo_agendamento, ultimo_exame, ultimo_prontuario, ultima_prescricao) if valor is not None]
    return max(datas) if datas else None


def retencao_cumprida(paciente: models.Paciente, db: Session) -> tuple[bool, datetime | None]:
    ultimo = ultimo_registro_clinico(paciente, db)
    if ultimo is None:
        return True, None
    limite = datetime.now() - timedelta(days=PRONTUARIO_RETENTION_YEARS * 365.25)
    return ultimo <= limite, ultimo


def anonimizar_dados_paciente(paciente: models.Paciente, db: Session) -> None:
    sufixo = f"{paciente.clinica_id}-{paciente.id}-{secrets.token_hex(5)}"
    email_anonimo = f"anonimizado-{sufixo}@example.invalid"
    paciente.nome = f"Titular anonimizado {paciente.id}"
    paciente.cpf = f"anonimizado-{sufixo}"
    paciente.telefone = "ANONIMIZADO"
    paciente.email = email_anonimo
    paciente.data_nascimento = date(1900, 1, 1)
    paciente.endereco_rua = "ANONIMIZADO"
    paciente.endereco_numero = "S/N"
    paciente.endereco_bairro = "ANONIMIZADO"
    paciente.endereco_cidade = "ANONIMIZADO"
    paciente.endereco_estado = "NA"
    paciente.endereco_cep = "00000000"
    paciente.latitude = None
    paciente.longitude = None
    paciente.anonimizado_em = datetime.now(UTC)
    if paciente.usuario:
        revogar_sessoes_usuario(db, paciente.usuario.id, "anonimizacao_lgpd")
        paciente.usuario.email = email_anonimo
        paciente.usuario.senha_hash = senha_hash(secrets.token_urlsafe(32))
        paciente.usuario.reset_version += 1
        paciente.usuario.ativo = False
    for consentimento in db.query(models.Consentimento).filter(
        models.Consentimento.clinica_id == paciente.clinica_id,
        models.Consentimento.paciente_id == paciente.id,
    ):
        consentimento.endereco_ip = None
        consentimento.user_agent = None


def excluir_dados_paciente(paciente: models.Paciente, db: Session) -> None:
    possui_prontuario = db.query(models.ProntuarioEntrada.id).filter(
        models.ProntuarioEntrada.clinica_id == paciente.clinica_id,
        models.ProntuarioEntrada.paciente_id == paciente.id,
    ).first() is not None
    if possui_prontuario:
        anonimizar_dados_paciente(paciente, db)
        return
    usuario_id = paciente.usuario_id
    db.query(models.Avaliacao).filter(
        models.Avaliacao.clinica_id == paciente.clinica_id,
        models.Avaliacao.paciente_id == paciente.id,
    ).delete(synchronize_session=False)
    db.query(models.Exame).filter(
        models.Exame.clinica_id == paciente.clinica_id,
        models.Exame.paciente_id == paciente.id,
    ).delete(synchronize_session=False)
    db.query(models.Agendamento).filter(
        models.Agendamento.clinica_id == paciente.clinica_id,
        models.Agendamento.paciente_id == paciente.id,
    ).delete(synchronize_session=False)
    db.query(models.Consentimento).filter(
        models.Consentimento.clinica_id == paciente.clinica_id,
        models.Consentimento.paciente_id == paciente.id,
    ).delete(synchronize_session=False)
    db.query(models.SolicitacaoLGPD).filter(
        models.SolicitacaoLGPD.clinica_id == paciente.clinica_id,
        models.SolicitacaoLGPD.paciente_id == paciente.id,
    ).update({models.SolicitacaoLGPD.paciente_id: None}, synchronize_session=False)
    if usuario_id:
        db.query(models.SolicitacaoLGPD).filter(
            models.SolicitacaoLGPD.clinica_id == paciente.clinica_id,
            models.SolicitacaoLGPD.usuario_solicitante_id == usuario_id,
        ).update({models.SolicitacaoLGPD.usuario_solicitante_id: None}, synchronize_session=False)
    usuario = paciente.usuario
    db.delete(paciente)
    db.flush()
    if usuario:
        revogar_sessoes_usuario(db, usuario.id, "exclusao_lgpd")
        usuario.email = f"excluido-{usuario.clinica_id}-{usuario.id}-{secrets.token_hex(5)}@example.invalid"
        usuario.senha_hash = senha_hash(secrets.token_urlsafe(32))
        usuario.reset_version += 1
        usuario.ativo = False


def calcular_distancia(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    if None in (lat1, lon1, lat2, lon2):
        return 9999.0
    raio_terra = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return raio_terra * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def horarios_do_dia(medico: models.Medico, dia) -> list[datetime]:
    horarios: list[datetime] = []
    for inicio, fim in ((8, 12), (13, 18)):
        horario = datetime.combine(dia, datetime.min.time().replace(hour=inicio))
        limite = datetime.combine(dia, datetime.min.time().replace(hour=fim))
        while horario + timedelta(minutes=medico.duracao_consulta) <= limite:
            horarios.append(horario)
            horario += timedelta(minutes=medico.duracao_consulta)
    return horarios


@app.get("/", include_in_schema=False)
def inicio():
    return RedirectResponse("/login.html")


@app.get("/health/live", include_in_schema=False)
def health_live():
    return {"status": "ok"}


def verificar_prontidao(db: Session):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        DATABASE_READY.set(0)
        logger.error("readiness_check_failed", extra={"event": "readiness_check_failed"})
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    DATABASE_READY.set(1)
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
def health_ready(db: Session = Depends(get_db)):
    return verificar_prontidao(db)


@app.get("/health", include_in_schema=False)
def health(db: Session = Depends(get_db)):
    return verificar_prontidao(db)


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(content=metrics_payload(), headers={"Content-Type": metrics_content_type()})


@app.post("/pacientes/", response_model=schemas.PacienteResponse, status_code=status.HTTP_201_CREATED)
def criar_paciente(paciente: schemas.PacienteCreate, request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin"))):
    if db.query(models.Paciente).filter(
        models.Paciente.clinica_id == usuario.clinica_id,
        (models.Paciente.cpf == paciente.cpf) | (models.Paciente.email == paciente.email),
    ).first():
        raise HTTPException(status_code=400, detail="CPF ou e-mail já cadastrado.")
    novo = models.Paciente(clinica_id=usuario.clinica_id, **paciente.model_dump())
    db.add(novo)
    flush_ou_conflito(db, "CPF ou e-mail já cadastrado.")
    registrar_auditoria(db, request=request, usuario=usuario, acao="CRIACAO", recurso="dados_pessoais", registro_id=novo.id, paciente_id=novo.id, campos=list(paciente.model_fields_set))
    commit_ou_conflito(db, "CPF ou e-mail já cadastrado."); db.refresh(novo)
    return novo


@app.patch("/pacientes/{paciente_id}", response_model=schemas.PacienteResponse)
def atualizar_paciente(paciente_id: int, paciente: schemas.PacienteUpdate, request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin"))):
    registro = db.query(models.Paciente).filter(
        models.Paciente.id == paciente_id,
        models.Paciente.clinica_id == usuario.clinica_id,
    ).first()
    if not registro:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")
    if paciente.cpf is not None and paciente.cpf != registro.cpf:
        raise HTTPException(status_code=400, detail="CPF não pode ser alterado.")
    dados = paciente.model_dump(exclude_unset=True, exclude_none=True)
    for campo, valor in dados.items():
        setattr(registro, campo, valor)
    registrar_auditoria(db, request=request, usuario=usuario, acao="ALTERACAO", recurso="dados_pessoais", registro_id=registro.id, paciente_id=registro.id, campos=list(dados))
    commit_ou_conflito(db, "E-mail já cadastrado para outro paciente."); db.refresh(registro)
    return registro


@app.get("/pacientes/")
def listar_pacientes(request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "medico", "paciente"))):
    if usuario.role == "paciente":
        registros = [paciente_do_usuario(usuario, db)]
        auditar_lista(db, request, usuario, "dados_pessoais", registros, lambda item: item.id)
        return registros
    if usuario.role == "medico":
        medico = medico_do_usuario(usuario, db)
        registros = db.query(models.Paciente.id, models.Paciente.nome, models.Paciente.telefone).join(
            models.Agendamento, models.Agendamento.paciente_id == models.Paciente.id
        ).filter(
            models.Paciente.clinica_id == usuario.clinica_id,
            models.Agendamento.clinica_id == usuario.clinica_id,
            models.Agendamento.medico_id == medico.id,
        ).distinct().all()
        auditar_lista(db, request, usuario, "dados_pessoais", registros, lambda item: item.id)
        return [schemas.PacienteResumo.model_validate(registro._mapping) for registro in registros]
    registros = db.query(models.Paciente).filter(models.Paciente.clinica_id == usuario.clinica_id).all()
    auditar_lista(db, request, usuario, "dados_pessoais", registros, lambda item: item.id)
    return registros


@app.post("/medicos/", response_model=schemas.MedicoResponse, status_code=status.HTTP_201_CREATED)
def criar_medico(medico: schemas.MedicoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin"))):
    if db.query(models.Medico).filter(
        models.Medico.clinica_id == usuario.clinica_id,
        (models.Medico.crm == medico.crm) | (models.Medico.email == medico.email),
    ).first():
        raise HTTPException(status_code=400, detail="CRM ou e-mail já cadastrado.")
    novo = models.Medico(clinica_id=usuario.clinica_id, **medico.model_dump())
    db.add(novo); commit_ou_conflito(db, "CRM ou e-mail já cadastrado."); db.refresh(novo)
    return novo


@app.patch("/medicos/{medico_id}", response_model=schemas.MedicoResponse)
def atualizar_medico(medico_id: int, medico: schemas.MedicoUpdate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin"))):
    registro = db.query(models.Medico).filter(
        models.Medico.id == medico_id,
        models.Medico.clinica_id == usuario.clinica_id,
    ).first()
    if not registro:
        raise HTTPException(status_code=404, detail="Médico não encontrado.")
    if medico.crm is not None and medico.crm != registro.crm:
        raise HTTPException(status_code=400, detail="CRM não pode ser alterado.")
    dados = medico.model_dump(exclude_unset=True, exclude_none=True)
    for campo, valor in dados.items():
        setattr(registro, campo, valor)
    commit_ou_conflito(db, "E-mail já cadastrado para outro médico."); db.refresh(registro)
    return registro


@app.get("/medicos/", response_model=List[schemas.MedicoResponse])
def listar_medicos(db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "medico", "paciente"))):
    if usuario.role == "medico":
        return [medico_do_usuario(usuario, db)]
    return db.query(models.Medico).filter(models.Medico.clinica_id == usuario.clinica_id).all()


@app.get("/medicos/recomendados")
def recomendar_medicos(latitude_paciente: float, longitude_paciente: float, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("paciente", "admin"))):
    medicos = db.query(models.Medico).filter(models.Medico.clinica_id == usuario.clinica_id).all()
    ordenados = sorted(((medico, calcular_distancia(latitude_paciente, longitude_paciente, medico.latitude, medico.longitude)) for medico in medicos), key=lambda item: (-item[0].avaliacao_media, item[1]))
    return [{"id": medico.id, "nome": medico.nome, "especialidade": medico.especialidade, "crm": medico.crm, "avaliacao_media": medico.avaliacao_media, "distancia_km": round(distancia, 2), "morada": f"{medico.endereco_rua}, {medico.endereco_numero} - {medico.endereco_bairro}"} for medico, distancia in ordenados]


@app.get("/medicos/{medico_id}/horarios-disponiveis")
def listar_horarios_disponiveis(medico_id: int, data: str, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico"))):
    try:
        dia = datetime.strptime(data, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use AAAA-MM-DD.")
    medico = db.query(models.Medico).filter(
        models.Medico.id == medico_id,
        models.Medico.clinica_id == usuario.clinica_id,
    ).first()
    if not medico:
        raise HTTPException(status_code=404, detail="Médico não encontrado.")
    possiveis = horarios_do_dia(medico, dia)
    ocupados = {agendamento.data_hora for agendamento in db.query(models.Agendamento).filter(models.Agendamento.clinica_id == usuario.clinica_id, models.Agendamento.medico_id == medico_id, models.Agendamento.data_hora >= datetime.combine(dia, datetime.min.time()), models.Agendamento.data_hora < datetime.combine(dia + timedelta(days=1), datetime.min.time()), models.Agendamento.status != "Cancelado").all()}
    agora = datetime.now()
    return [horario.strftime("%H:%M") for horario in possiveis if horario not in ocupados and horario > agora]


@app.post("/agendamentos/", response_model=schemas.AgendamentoResponse, status_code=status.HTTP_201_CREATED)
def criar_agendamento(agendamento: schemas.AgendamentoCreate, request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente"))):
    if agendamento.data_hora <= datetime.now():
        raise HTTPException(status_code=400, detail="A consulta deve ser agendada para uma data futura.")
    if usuario.role == "paciente" and paciente_do_usuario(usuario, db).id != agendamento.paciente_id:
        raise HTTPException(status_code=403, detail="Você só pode agendar consultas para si mesmo.")
    medico = db.query(models.Medico).filter(
        models.Medico.id == agendamento.medico_id,
        models.Medico.clinica_id == usuario.clinica_id,
    ).first()
    paciente = db.query(models.Paciente).filter(
        models.Paciente.id == agendamento.paciente_id,
        models.Paciente.clinica_id == usuario.clinica_id,
    ).first()
    if not medico or not paciente:
        raise HTTPException(status_code=404, detail="Médico ou paciente não encontrado.")
    if agendamento.data_hora not in horarios_do_dia(medico, agendamento.data_hora.date()):
        raise HTTPException(status_code=400, detail="O horário informado não pertence à agenda do médico.")
    conflito = db.query(models.Agendamento).filter(models.Agendamento.clinica_id == usuario.clinica_id, models.Agendamento.medico_id == agendamento.medico_id, models.Agendamento.data_hora == agendamento.data_hora, models.Agendamento.status != "Cancelado").first()
    if conflito:
        raise HTTPException(status_code=409, detail="Este horário acabou de ser ocupado.")
    novo = models.Agendamento(clinica_id=usuario.clinica_id, **agendamento.model_dump())
    db.add(novo)
    try:
        db.flush()
        registrar_auditoria(db, request=request, usuario=usuario, acao="CRIACAO", recurso="agendamento", registro_id=novo.id, paciente_id=novo.paciente_id, campos=["medico_id", "paciente_id", "data_hora"])
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Este horário acabou de ser ocupado.")
    db.refresh(novo)
    return novo


@app.get("/agendamentos/", response_model=List[schemas.AgendamentoResponse])
def listar_agendamentos(request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico"))):
    consulta = db.query(models.Agendamento).filter(models.Agendamento.clinica_id == usuario.clinica_id)
    if usuario.role == "paciente": consulta = consulta.filter(models.Agendamento.paciente_id == paciente_do_usuario(usuario, db).id)
    if usuario.role == "medico": consulta = consulta.filter(models.Agendamento.medico_id == medico_do_usuario(usuario, db).id)
    registros = consulta.all()
    auditar_lista(db, request, usuario, "agendamento", registros, lambda item: item.paciente_id)
    return registros


@app.patch("/agendamentos/{agendamento_id}/status", response_model=schemas.AgendamentoResponse)
def atualizar_status_agendamento(agendamento_id: int, status_novo: str, request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico"))):
    agendamento = db.query(models.Agendamento).filter(
        models.Agendamento.id == agendamento_id,
        models.Agendamento.clinica_id == usuario.clinica_id,
    ).first()
    if not agendamento: raise HTTPException(status_code=404, detail="Agendamento não encontrado.")
    permitidos = {"Confirmado", "Atendido", "Cancelado"}
    if status_novo not in permitidos: raise HTTPException(status_code=400, detail="Status inválido.")
    if usuario.role == "paciente" and (agendamento.paciente_id != paciente_do_usuario(usuario, db).id or status_novo != "Cancelado"): raise HTTPException(status_code=403, detail="Paciente só pode cancelar a própria consulta.")
    if usuario.role == "medico" and (agendamento.medico_id != medico_do_usuario(usuario, db).id or status_novo not in {"Confirmado", "Atendido"}): raise HTTPException(status_code=403, detail="Ação não permitida para este médico.")
    agendamento.status = status_novo
    registrar_auditoria(db, request=request, usuario=usuario, acao="ALTERACAO", recurso="agendamento", registro_id=agendamento.id, paciente_id=agendamento.paciente_id, campos=["status"])
    db.commit(); db.refresh(agendamento)
    return agendamento


@app.post("/exames/", response_model=schemas.ExameResponse, status_code=status.HTTP_201_CREATED)
def criar_exame(exame: schemas.ExameCreate, request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente"))):
    if exame.data_hora <= datetime.now():
        raise HTTPException(status_code=400, detail="O exame deve ser agendado para uma data futura.")
    if usuario.role == "paciente" and paciente_do_usuario(usuario, db).id != exame.paciente_id: raise HTTPException(status_code=403, detail="Você só pode solicitar exames para si mesmo.")
    paciente = db.query(models.Paciente).filter(
        models.Paciente.id == exame.paciente_id,
        models.Paciente.clinica_id == usuario.clinica_id,
    ).first()
    if not paciente: raise HTTPException(status_code=404, detail="Paciente não encontrado.")
    novo = models.Exame(clinica_id=usuario.clinica_id, **exame.model_dump())
    db.add(novo); db.flush()
    registrar_auditoria(db, request=request, usuario=usuario, acao="CRIACAO", recurso="exame", registro_id=novo.id, paciente_id=novo.paciente_id, campos=["tipo_exame", "laboratorio", "data_hora"])
    db.commit(); db.refresh(novo)
    return novo


@app.get("/exames/", response_model=List[schemas.ExameResponse])
def listar_exames(request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico"))):
    consulta = db.query(models.Exame).filter(models.Exame.clinica_id == usuario.clinica_id)
    if usuario.role == "paciente": consulta = consulta.filter(models.Exame.paciente_id == paciente_do_usuario(usuario, db).id)
    if usuario.role == "medico":
        medico = medico_do_usuario(usuario, db)
        pacientes_ids = db.query(models.Agendamento.paciente_id).filter(
            models.Agendamento.clinica_id == usuario.clinica_id,
            models.Agendamento.medico_id == medico.id,
        )
        consulta = consulta.filter(models.Exame.paciente_id.in_(pacientes_ids))
    registros = consulta.all()
    auditar_lista(db, request, usuario, "exame", registros, lambda item: item.paciente_id)
    return registros


@app.patch("/exames/{exame_id}/resultado", response_model=schemas.ExameResponse)
def salvar_resultado_exame(exame_id: int, dados: schemas.ExameResultadoUpdate, request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "medico"))):
    exame = db.query(models.Exame).filter(
        models.Exame.id == exame_id,
        models.Exame.clinica_id == usuario.clinica_id,
    ).first()
    if not exame: raise HTTPException(status_code=404, detail="Exame não encontrado.")
    if usuario.role == "medico":
        medico = medico_do_usuario(usuario, db)
        if not medico_tem_vinculo_com_paciente(usuario.clinica_id, medico.id, exame.paciente_id, db):
            raise HTTPException(status_code=403, detail="Este médico não possui vínculo com o paciente.")
    texto_resultado = dados.resultado.strip()
    if not texto_resultado: raise HTTPException(status_code=400, detail="Informe o resultado do exame.")
    exame.resultado, exame.status = texto_resultado, "Concluído"
    registrar_auditoria(db, request=request, usuario=usuario, acao="ALTERACAO", recurso="exame", registro_id=exame.id, paciente_id=exame.paciente_id, campos=["resultado", "status"])
    db.commit(); db.refresh(exame)
    return exame


@app.post("/avaliacoes/", response_model=schemas.AvaliacaoResponse, status_code=status.HTTP_201_CREATED)
def criar_avaliacao(avaliacao: schemas.AvaliacaoCreate, request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("paciente"))):
    agendamento = db.query(models.Agendamento).filter(
        models.Agendamento.id == avaliacao.agendamento_id,
        models.Agendamento.clinica_id == usuario.clinica_id,
    ).first()
    if not agendamento or agendamento.paciente_id != avaliacao.paciente_id or agendamento.medico_id != avaliacao.medico_id: raise HTTPException(status_code=400, detail="Avaliação não corresponde ao agendamento.")
    if agendamento.status != "Atendido":
        raise HTTPException(status_code=409, detail="A avaliação só pode ser registrada após o atendimento.")
    if paciente_do_usuario(usuario, db).id != avaliacao.paciente_id: raise HTTPException(status_code=403, detail="Você só pode avaliar a própria consulta.")
    existente = db.query(models.Avaliacao).filter(
        models.Avaliacao.clinica_id == usuario.clinica_id,
        models.Avaliacao.agendamento_id == avaliacao.agendamento_id,
    ).first()
    if existente:
        raise HTTPException(status_code=409, detail="Esta consulta já foi avaliada pelo paciente.")
    registro = models.Avaliacao(
        clinica_id=usuario.clinica_id,
        agendamento_id=avaliacao.agendamento_id,
        paciente_id=avaliacao.paciente_id,
        medico_id=avaliacao.medico_id,
        nota_medico=avaliacao.nota_medico,
        comentario_paciente=(avaliacao.comentario_paciente or "").strip() or None,
    )
    db.add(registro)
    db.flush()
    registrar_auditoria(
        db,
        request=request,
        usuario=usuario,
        acao="CRIACAO",
        recurso="avaliacao_atendimento",
        registro_id=registro.id,
        paciente_id=registro.paciente_id,
        campos=["nota_medico", "comentario_paciente"],
    )
    db.commit()
    media = db.query(func.avg(models.Avaliacao.nota_medico)).filter(
        models.Avaliacao.clinica_id == usuario.clinica_id,
        models.Avaliacao.medico_id == avaliacao.medico_id,
        models.Avaliacao.nota_medico.is_not(None),
    ).scalar() or 0.0
    medico = db.query(models.Medico).filter(
        models.Medico.id == avaliacao.medico_id,
        models.Medico.clinica_id == usuario.clinica_id,
    ).first()
    medico.avaliacao_media = round(float(media), 2)
    db.commit()
    db.refresh(registro)
    return registro


@app.get("/avaliacoes/", response_model=List[schemas.AvaliacaoResponse])
def listar_avaliacoes(request: Request, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico"))):
    consulta = db.query(models.Avaliacao).filter(models.Avaliacao.clinica_id == usuario.clinica_id)
    if usuario.role == "paciente": consulta = consulta.filter(models.Avaliacao.paciente_id == paciente_do_usuario(usuario, db).id)
    if usuario.role == "medico": consulta = consulta.filter(models.Avaliacao.medico_id == medico_do_usuario(usuario, db).id)
    registros = consulta.all()
    auditar_lista(db, request, usuario, "avaliacao_atendimento", registros, lambda item: item.paciente_id)
    return registros


@app.post("/prontuarios", response_model=schemas.ProntuarioResponse, status_code=status.HTTP_201_CREATED)
def criar_entrada_prontuario(
    dados: schemas.ProntuarioCreate,
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("medico")),
):
    medico = medico_do_usuario(usuario, db)
    paciente = db.query(models.Paciente).filter(
        models.Paciente.id == dados.paciente_id,
        models.Paciente.clinica_id == usuario.clinica_id,
    ).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")
    if not medico_tem_vinculo_com_paciente(usuario.clinica_id, medico.id, paciente.id, db):
        raise HTTPException(status_code=403, detail="Este médico não possui vínculo assistencial com o paciente.")
    agendamento = None
    if dados.agendamento_id is not None:
        agendamento = db.query(models.Agendamento).filter(
            models.Agendamento.id == dados.agendamento_id,
            models.Agendamento.clinica_id == usuario.clinica_id,
        ).first()
        if not agendamento or agendamento.paciente_id != paciente.id or agendamento.medico_id != medico.id:
            raise HTTPException(status_code=400, detail="O atendimento não corresponde ao médico e ao paciente.")
        if agendamento.status != "Atendido":
            raise HTTPException(status_code=409, detail="Conclua o atendimento antes de registrar a evolução.")
        duplicado = db.query(models.ProntuarioEntrada.id).filter(
            models.ProntuarioEntrada.clinica_id == usuario.clinica_id,
            models.ProntuarioEntrada.agendamento_id == agendamento.id,
            models.ProntuarioEntrada.tipo == dados.tipo,
            models.ProntuarioEntrada.versao == 1,
        ).first()
        if duplicado:
            raise HTTPException(status_code=409, detail="Já existe este tipo de registro para o atendimento. Faça uma retificação no histórico.")
    reautenticar_assinatura(usuario, dados.senha_assinatura)
    agora = datetime.now(UTC)
    serie_id = str(uuid4())
    payload = payload_prontuario(
        clinica_id=usuario.clinica_id,
        serie_id=serie_id,
        versao=1,
        versao_anterior_id=None,
        paciente_id=paciente.id,
        medico_id=medico.id,
        agendamento_id=agendamento.id if agendamento else None,
        autor_usuario_id=usuario.id,
        autor_nome=medico.nome,
        autor_crm=medico.crm,
        tipo=dados.tipo,
        conteudo=dados.conteudo,
        motivo_retificacao=None,
        criado_em=agora,
        assinado_em=agora,
        assinatura_tipo=ASSINATURA_INTERNA,
    )
    documento_hash = hash_payload(payload)
    registro = models.ProntuarioEntrada(
        **{campo: valor for campo, valor in payload.items() if campo not in {"criado_em", "assinado_em"}},
        criado_em=agora,
        assinado_em=agora,
        documento_hash=documento_hash,
        assinatura_hash=assinar_documento(documento_hash, usuario.id, agora),
    )
    db.add(registro)
    flush_ou_conflito(db, "Não foi possível criar o registro clínico.")
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="CRIACAO", recurso="prontuario",
        registro_id=registro.id, paciente_id=paciente.id,
        campos=["tipo", "conteudo", "autoria", "assinatura"],
        detalhes={"versao": 1, "serie_id": serie_id, "assinatura_tipo": ASSINATURA_INTERNA},
    )
    commit_ou_conflito(db, "Não foi possível criar o registro clínico.")
    db.refresh(registro)
    return registro


@app.post("/prontuarios/{prontuario_id}/versoes", response_model=schemas.ProntuarioResponse, status_code=status.HTTP_201_CREATED)
def retificar_entrada_prontuario(
    prontuario_id: int,
    dados: schemas.ProntuarioVersaoCreate,
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("medico")),
):
    anterior = db.query(models.ProntuarioEntrada).filter(
        models.ProntuarioEntrada.id == prontuario_id,
        models.ProntuarioEntrada.clinica_id == usuario.clinica_id,
    ).first()
    if not anterior:
        raise HTTPException(status_code=404, detail="Registro de prontuário não encontrado.")
    medico = medico_do_usuario(usuario, db)
    if anterior.medico_id != medico.id:
        raise HTTPException(status_code=403, detail="Somente o profissional autor pode retificar este registro.")
    mais_recente = db.query(models.ProntuarioEntrada).filter(
        models.ProntuarioEntrada.clinica_id == usuario.clinica_id,
        models.ProntuarioEntrada.serie_id == anterior.serie_id,
    ).order_by(models.ProntuarioEntrada.versao.desc()).first()
    if mais_recente.id != anterior.id:
        raise HTTPException(status_code=409, detail=f"A versão {mais_recente.versao} já é a mais recente. Retifique-a para manter a sequência.")
    reautenticar_assinatura(usuario, dados.senha_assinatura)
    agora = datetime.now(UTC)
    payload = payload_prontuario(
        clinica_id=usuario.clinica_id,
        serie_id=anterior.serie_id,
        versao=anterior.versao + 1,
        versao_anterior_id=anterior.id,
        paciente_id=anterior.paciente_id,
        medico_id=medico.id,
        agendamento_id=anterior.agendamento_id,
        autor_usuario_id=usuario.id,
        autor_nome=medico.nome,
        autor_crm=medico.crm,
        tipo=anterior.tipo,
        conteudo=dados.conteudo,
        motivo_retificacao=dados.motivo_retificacao,
        criado_em=agora,
        assinado_em=agora,
        assinatura_tipo=ASSINATURA_INTERNA,
    )
    documento_hash = hash_payload(payload)
    registro = models.ProntuarioEntrada(
        **{campo: valor for campo, valor in payload.items() if campo not in {"criado_em", "assinado_em"}},
        criado_em=agora,
        assinado_em=agora,
        documento_hash=documento_hash,
        assinatura_hash=assinar_documento(documento_hash, usuario.id, agora),
    )
    db.add(registro)
    flush_ou_conflito(db, "Outra retificação foi criada ao mesmo tempo. Recarregue o histórico.")
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ALTERACAO", recurso="prontuario",
        registro_id=registro.id, paciente_id=registro.paciente_id,
        campos=["conteudo", "motivo_retificacao", "assinatura"],
        detalhes={"serie_id": registro.serie_id, "versao_anterior": anterior.versao, "nova_versao": registro.versao},
    )
    commit_ou_conflito(db, "Outra retificação foi criada ao mesmo tempo. Recarregue o histórico.")
    db.refresh(registro)
    return registro


@app.get("/prontuarios", response_model=List[schemas.ProntuarioResponse])
def listar_prontuario(
    request: Request,
    paciente_id: int | None = None,
    motivo_acesso: str | None = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico")),
):
    if usuario.role == "paciente":
        paciente_id = paciente_do_usuario(usuario, db).id
    if paciente_id is None:
        raise HTTPException(status_code=400, detail="Informe o paciente para consultar o prontuário.")
    paciente = db.query(models.Paciente.id).filter(
        models.Paciente.id == paciente_id,
        models.Paciente.clinica_id == usuario.clinica_id,
    ).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")
    motivo = validar_acesso_prontuario(usuario=usuario, paciente_id=paciente_id, motivo_acesso=motivo_acesso, db=db)
    registros = db.query(models.ProntuarioEntrada).filter(
        models.ProntuarioEntrada.clinica_id == usuario.clinica_id,
        models.ProntuarioEntrada.paciente_id == paciente_id,
    ).order_by(models.ProntuarioEntrada.criado_em.desc(), models.ProntuarioEntrada.id.desc()).all()
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ACESSO", recurso="prontuario",
        registro_id=registros[0].id if registros else None, paciente_id=paciente_id,
        detalhes={"motivo_acesso": motivo, "registros_consultados": len(registros)},
    )
    db.commit()
    return registros


@app.get("/prontuarios/{prontuario_id}/integridade")
def verificar_integridade_prontuario(
    prontuario_id: int,
    request: Request,
    motivo_acesso: str | None = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico")),
):
    registro, motivo = prontuario_acessivel(prontuario_id, usuario, motivo_acesso, db)
    documento_integro = hmac.compare_digest(registro.documento_hash, hash_payload(_payload_do_prontuario(registro)))
    assinatura_integra = verificar_assinatura(
        registro.documento_hash, registro.autor_usuario_id, registro.assinado_em, registro.assinatura_hash
    ) if registro.assinatura_tipo == ASSINATURA_INTERNA else None
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ACESSO", recurso="integridade_prontuario",
        registro_id=registro.id, paciente_id=registro.paciente_id,
        detalhes={"motivo_acesso": motivo, "documento_integro": documento_integro, "assinatura_integra": assinatura_integra},
    )
    db.commit()
    return {
        "documento_integro": documento_integro,
        "assinatura_integra": assinatura_integra,
        "assinatura_tipo": registro.assinatura_tipo,
        "documento_hash": registro.documento_hash,
    }


@app.post("/prontuarios/{prontuario_id}/anexos", response_model=schemas.AnexoProntuarioResponse, status_code=status.HTTP_201_CREATED)
async def anexar_ao_prontuario(
    prontuario_id: int,
    request: Request,
    arquivo: UploadFile = File(...),
    origem: str = Form("nato_digital"),
    conferencia: str = Form("original"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("medico")),
):
    registro = db.query(models.ProntuarioEntrada).filter(
        models.ProntuarioEntrada.id == prontuario_id,
        models.ProntuarioEntrada.clinica_id == usuario.clinica_id,
    ).first()
    if not registro:
        raise HTTPException(status_code=404, detail="Registro de prontuário não encontrado.")
    medico = medico_do_usuario(usuario, db)
    if registro.medico_id != medico.id:
        raise HTTPException(status_code=403, detail="Somente o autor pode complementar este registro com anexos.")
    if origem not in {"nato_digital", "digitalizado"} or conferencia not in {"original", "copia_simples", "copia_conferida"}:
        raise HTTPException(status_code=400, detail="Classificação do anexo inválida.")
    limite = PRONTUARIO_MAX_UPLOAD_MB * 1024 * 1024
    conteudo = await arquivo.read(limite + 1)
    if not conteudo:
        raise HTTPException(status_code=400, detail="O arquivo está vazio.")
    if len(conteudo) > limite:
        raise HTTPException(status_code=413, detail=f"O arquivo excede o limite de {PRONTUARIO_MAX_UPLOAD_MB} MB.")
    assinaturas_permitidas = {
        "application/pdf": (b"%PDF-", ".pdf"),
        "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
        "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    }
    tipo_mime = (arquivo.content_type or "").lower()
    identificador = assinaturas_permitidas.get(tipo_mime)
    if not identificador or not conteudo.startswith(identificador[0]):
        raise HTTPException(status_code=415, detail="Envie somente PDF, PNG ou JPEG válido.")
    nome_original = Path(arquivo.filename or "anexo").name[:255]
    diretorio = (PRONTUARIO_UPLOAD_DIR / str(usuario.clinica_id) / str(registro.paciente_id) / str(registro.id)).resolve()
    diretorio.mkdir(parents=True, exist_ok=True)
    caminho = (diretorio / f"{uuid4().hex}{identificador[1]}").resolve()
    if not caminho.is_relative_to(PRONTUARIO_UPLOAD_DIR):
        raise HTTPException(status_code=400, detail="Caminho de armazenamento inválido.")
    caminho.write_bytes(conteudo)
    anexo = models.AnexoProntuario(
        clinica_id=usuario.clinica_id,
        prontuario_id=registro.id,
        enviado_por_usuario_id=usuario.id,
        nome_original=nome_original,
        tipo_mime=tipo_mime,
        tamanho_bytes=len(conteudo),
        arquivo_hash=hashlib.sha256(conteudo).hexdigest(),
        caminho_armazenamento=str(caminho.relative_to(PRONTUARIO_UPLOAD_DIR)),
        origem=origem,
        conferencia=conferencia,
        criado_em=datetime.now(UTC),
    )
    try:
        db.add(anexo); db.flush()
        registrar_auditoria(
            db, request=request, usuario=usuario, acao="CRIACAO", recurso="anexo_prontuario",
            registro_id=anexo.id, paciente_id=registro.paciente_id,
            campos=["arquivo_hash", "tipo_mime", "tamanho_bytes", "origem", "conferencia"],
            detalhes={"prontuario_id": registro.id},
        )
        db.commit(); db.refresh(anexo)
    except Exception:
        db.rollback()
        caminho.unlink(missing_ok=True)
        raise
    return anexo


@app.get("/prontuarios/anexos/{anexo_id}")
def baixar_anexo_prontuario(
    anexo_id: int,
    request: Request,
    motivo_acesso: str | None = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico")),
):
    anexo = db.query(models.AnexoProntuario).filter(
        models.AnexoProntuario.id == anexo_id,
        models.AnexoProntuario.clinica_id == usuario.clinica_id,
    ).first()
    if not anexo:
        raise HTTPException(status_code=404, detail="Anexo não encontrado.")
    registro, motivo = prontuario_acessivel(anexo.prontuario_id, usuario, motivo_acesso, db)
    caminho = (PRONTUARIO_UPLOAD_DIR / anexo.caminho_armazenamento).resolve()
    if not caminho.is_relative_to(PRONTUARIO_UPLOAD_DIR) or not caminho.is_file():
        raise HTTPException(status_code=404, detail="Arquivo do anexo não encontrado.")
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ACESSO", recurso="anexo_prontuario",
        registro_id=anexo.id, paciente_id=registro.paciente_id,
        detalhes={"motivo_acesso": motivo, "prontuario_id": registro.id},
    )
    db.commit()
    return FileResponse(caminho, media_type=anexo.tipo_mime, filename=anexo.nome_original)


@app.post("/prescricoes", response_model=schemas.PrescricaoResponse, status_code=status.HTTP_201_CREATED)
def criar_prescricao(
    dados: schemas.PrescricaoCreate,
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("medico")),
):
    medico = medico_do_usuario(usuario, db)
    paciente = db.query(models.Paciente).filter(
        models.Paciente.id == dados.paciente_id,
        models.Paciente.clinica_id == usuario.clinica_id,
    ).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")
    if not medico_tem_vinculo_com_paciente(usuario.clinica_id, medico.id, paciente.id, db):
        raise HTTPException(status_code=403, detail="Este médico não possui vínculo assistencial com o paciente.")
    prontuario = None
    if dados.prontuario_id is not None:
        prontuario = db.query(models.ProntuarioEntrada).filter(
            models.ProntuarioEntrada.id == dados.prontuario_id,
            models.ProntuarioEntrada.clinica_id == usuario.clinica_id,
            models.ProntuarioEntrada.paciente_id == paciente.id,
            models.ProntuarioEntrada.medico_id == medico.id,
        ).first()
        if not prontuario:
            raise HTTPException(status_code=400, detail="O registro clínico informado não corresponde ao paciente e ao médico.")
    reautenticar_assinatura(usuario, dados.senha_assinatura)
    agora = datetime.now(UTC)
    itens_payload = [item.model_dump() for item in dados.itens]
    payload = payload_prescricao(
        clinica_id=usuario.clinica_id,
        prontuario_id=prontuario.id if prontuario else None,
        paciente_id=paciente.id,
        medico_id=medico.id,
        autor_usuario_id=usuario.id,
        autor_nome=medico.nome,
        autor_crm=medico.crm,
        observacoes=(dados.observacoes or "").strip() or None,
        itens=itens_payload,
        criado_em=agora,
        assinado_em=agora,
    )
    documento_hash = hash_payload(payload)
    prescricao = models.Prescricao(
        clinica_id=usuario.clinica_id,
        prontuario_id=prontuario.id if prontuario else None,
        paciente_id=paciente.id,
        medico_id=medico.id,
        autor_usuario_id=usuario.id,
        autor_nome=medico.nome,
        autor_crm=medico.crm,
        observacoes=payload["observacoes"],
        criado_em=agora,
        assinado_em=agora,
        assinatura_tipo=ASSINATURA_INTERNA,
        documento_hash=documento_hash,
        assinatura_hash=assinar_documento(documento_hash, usuario.id, agora),
    )
    prescricao.itens = [models.ItemPrescricao(clinica_id=usuario.clinica_id, **item) for item in itens_payload]
    db.add(prescricao); db.flush()
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="CRIACAO", recurso="prescricao",
        registro_id=prescricao.id, paciente_id=paciente.id,
        campos=["itens", "observacoes", "assinatura"],
        detalhes={"quantidade_itens": len(itens_payload), "assinatura_tipo": ASSINATURA_INTERNA},
    )
    commit_ou_conflito(db, "Não foi possível emitir a prescrição.")
    db.refresh(prescricao)
    return prescricao


@app.get("/prescricoes", response_model=List[schemas.PrescricaoResponse])
def listar_prescricoes(
    request: Request,
    paciente_id: int | None = None,
    motivo_acesso: str | None = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico")),
):
    if usuario.role == "paciente":
        paciente_id = paciente_do_usuario(usuario, db).id
    if paciente_id is None:
        raise HTTPException(status_code=400, detail="Informe o paciente para consultar as prescrições.")
    motivo = validar_acesso_prontuario(usuario=usuario, paciente_id=paciente_id, motivo_acesso=motivo_acesso, db=db)
    registros = db.query(models.Prescricao).filter(
        models.Prescricao.clinica_id == usuario.clinica_id,
        models.Prescricao.paciente_id == paciente_id,
    ).order_by(models.Prescricao.criado_em.desc()).all()
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ACESSO", recurso="prescricao",
        registro_id=registros[0].id if registros else None, paciente_id=paciente_id,
        detalhes={"motivo_acesso": motivo, "prescricoes_consultadas": len(registros)},
    )
    db.commit()
    return registros


@app.post("/prescricoes/{prescricao_id}/cancelamentos", response_model=schemas.EventoPrescricaoResponse, status_code=status.HTTP_201_CREATED)
def cancelar_prescricao(
    prescricao_id: int,
    dados: schemas.CancelamentoPrescricaoCreate,
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("medico")),
):
    prescricao = db.query(models.Prescricao).filter(
        models.Prescricao.id == prescricao_id,
        models.Prescricao.clinica_id == usuario.clinica_id,
    ).first()
    if not prescricao:
        raise HTTPException(status_code=404, detail="Prescrição não encontrada.")
    medico = medico_do_usuario(usuario, db)
    if prescricao.medico_id != medico.id:
        raise HTTPException(status_code=403, detail="Somente o profissional emissor pode cancelar a prescrição.")
    if db.query(models.EventoPrescricao.id).filter(
        models.EventoPrescricao.prescricao_id == prescricao.id,
        models.EventoPrescricao.tipo == "cancelamento",
    ).first():
        raise HTTPException(status_code=409, detail="Esta prescrição já foi cancelada.")
    reautenticar_assinatura(usuario, dados.senha_assinatura)
    agora = datetime.now(UTC)
    payload = payload_evento_prescricao(
        clinica_id=usuario.clinica_id,
        prescricao_id=prescricao.id,
        autor_usuario_id=usuario.id,
        tipo="cancelamento",
        motivo=dados.motivo,
        criado_em=agora,
    )
    documento_hash = hash_payload(payload)
    evento = models.EventoPrescricao(
        **{campo: valor for campo, valor in payload.items() if campo != "criado_em"},
        criado_em=agora,
        documento_hash=documento_hash,
        assinatura_hash=assinar_documento(documento_hash, usuario.id, agora),
    )
    db.add(evento); db.flush()
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ALTERACAO", recurso="prescricao",
        registro_id=prescricao.id, paciente_id=prescricao.paciente_id,
        campos=["cancelamento"], detalhes={"evento_id": evento.id},
    )
    commit_ou_conflito(db, "Esta prescrição já foi cancelada.")
    db.refresh(evento)
    return evento


def persistir_usuario(
    novo: models.Usuario,
    perfil,
    db: Session,
    request: Request | None = None,
    registrar_documentos: bool = False,
) -> models.Usuario:
    if perfil is not None and perfil.clinica_id != novo.clinica_id:
        raise HTTPException(status_code=400, detail="O perfil e o usuário devem pertencer à mesma clínica.")
    try:
        db.add(novo)
        db.flush()
        if perfil is not None:
            perfil.usuario_id = novo.id
            db.flush()
        if registrar_documentos:
            db.add_all(criar_consentimentos_obrigatorios(
                clinica_id=novo.clinica_id,
                usuario_id=novo.id,
                paciente_id=perfil.id if isinstance(perfil, models.Paciente) else None,
                request=request,
            ))
            registrar_auditoria(
                db,
                request=request,
                usuario=novo,
                acao="CONSENTIMENTO",
                recurso="documentos_lgpd",
                paciente_id=perfil.id if isinstance(perfil, models.Paciente) else None,
                campos=["termos_uso", "politica_privacidade"],
                detalhes={"termos_versao": TERMOS_VERSAO, "privacidade_versao": PRIVACIDADE_VERSAO},
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="E-mail, CPF ou CRM já cadastrado.")
    db.refresh(novo)
    return novo


@app.post("/auth/registrar-clinica", response_model=schemas.ClinicaResponse, status_code=status.HTTP_201_CREATED)
def registrar_clinica(dados: schemas.ClinicaProvisionamento, request: Request, db: Session = Depends(get_db)):
    if not CLINIC_PROVISIONING_TOKEN:
        raise HTTPException(status_code=503, detail="O provisionamento de clínicas não está configurado neste ambiente.")
    token_valido = bool(
        CLINIC_PROVISIONING_TOKEN
        and hmac.compare_digest(dados.provisioning_token, CLINIC_PROVISIONING_TOKEN)
    )
    if not token_valido:
        raise HTTPException(status_code=403, detail="Token de provisionamento inválido.")
    erro_documentos = validar_aceite_documentos(
        dados.aceita_termos, dados.ciente_privacidade, dados.termos_versao, dados.privacidade_versao
    )
    if erro_documentos:
        raise HTTPException(status_code=409, detail=erro_documentos)
    if db.query(models.Clinica.id).filter(models.Clinica.slug == dados.slug).first():
        raise HTTPException(status_code=409, detail="Este código de clínica já está em uso.")

    clinica = models.Clinica(nome=dados.nome.strip(), slug=dados.slug, ativo=True)
    try:
        db.add(clinica)
        db.flush()
        admin = models.Usuario(
            clinica_id=clinica.id,
            email=str(dados.email_admin).strip().lower(),
            senha_hash=senha_hash(dados.password),
            role="admin",
            ativo=True,
        )
        db.add(admin)
        db.flush()
        db.add_all(criar_consentimentos_obrigatorios(
            clinica_id=clinica.id,
            usuario_id=admin.id,
            paciente_id=None,
            request=request,
        ))
        registrar_auditoria(
            db,
            request=request,
            usuario=admin,
            acao="CONSENTIMENTO",
            recurso="documentos_lgpd",
            campos=["termos_uso", "politica_privacidade"],
            detalhes={"termos_versao": TERMOS_VERSAO, "privacidade_versao": PRIVACIDADE_VERSAO},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Não foi possível criar a clínica com os dados informados.")
    db.refresh(clinica)
    return clinica


@app.get("/clinicas/atual", response_model=schemas.ClinicaResponse)
def obter_clinica_atual(
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "medico", "paciente")),
):
    clinica = db.query(models.Clinica).filter(
        models.Clinica.id == usuario.clinica_id,
        models.Clinica.ativo.is_(True),
    ).first()
    if not clinica:
        raise HTTPException(status_code=404, detail="Clínica não encontrada.")
    return clinica


@app.post("/auth/registrar", response_model=schemas.UsuarioResponse, status_code=status.HTTP_201_CREATED)
def registrar_usuario(usuario: schemas.UsuarioCreate, request: Request, db: Session = Depends(get_db)):
    clinica = db.query(models.Clinica).filter(
        models.Clinica.slug == usuario.clinica_slug,
        models.Clinica.ativo.is_(True),
    ).first()
    if not clinica:
        raise HTTPException(status_code=404, detail="Clínica não encontrada ou inativa.")
    erro_documentos = validar_aceite_documentos(
        usuario.aceita_termos,
        usuario.ciente_privacidade,
        usuario.termos_versao,
        usuario.privacidade_versao,
    )
    if erro_documentos:
        raise HTTPException(status_code=409, detail=erro_documentos)
    email = str(usuario.email).strip().lower()
    if db.query(models.Usuario).filter(
        models.Usuario.clinica_id == clinica.id,
        models.Usuario.email == email,
    ).first():
        raise HTTPException(status_code=409, detail="E-mail já cadastrado.")

    perfil = None
    if usuario.role == "admin":
        raise HTTPException(status_code=403, detail="Administradores são criados no provisionamento da clínica.")
    elif usuario.role == "medico":
        perfil = db.query(models.Medico).filter(
            models.Medico.clinica_id == clinica.id,
            models.Medico.email == email,
            models.Medico.usuario_id.is_(None),
        ).first()
        if not perfil:
            raise HTTPException(status_code=403, detail="O médico deve ser previamente cadastrado pela clínica.")
    else:
        obrigatorios = {
            "nome": usuario.nome, "cpf": usuario.cpf, "telefone": usuario.telefone,
            "data_nascimento": usuario.data_nascimento, "endereco_rua": usuario.endereco_rua,
            "endereco_numero": usuario.endereco_numero, "endereco_bairro": usuario.endereco_bairro,
            "endereco_cidade": usuario.endereco_cidade, "endereco_estado": usuario.endereco_estado,
            "endereco_cep": usuario.endereco_cep,
        }
        faltando = [campo for campo, valor in obrigatorios.items() if valor in (None, "")]
        if faltando:
            raise HTTPException(status_code=400, detail=f"Dados incompletos para paciente. Faltam: {', '.join(faltando)}")
        perfil = db.query(models.Paciente).filter(
            models.Paciente.clinica_id == clinica.id,
            models.Paciente.email == email,
            models.Paciente.usuario_id.is_(None),
        ).first()
        if not perfil:
            perfil = models.Paciente(clinica_id=clinica.id, email=email, **obrigatorios)
            db.add(perfil)

    novo = models.Usuario(clinica_id=clinica.id, email=email, senha_hash=senha_hash(usuario.password), role=usuario.role, ativo=True)
    return persistir_usuario(novo, perfil, db, request=request, registrar_documentos=True)


@app.post("/auth/usuarios", response_model=schemas.UsuarioResponse, status_code=status.HTTP_201_CREATED)
def criar_usuario_por_admin(dados: schemas.UsuarioGerenciadoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin"))):
    email = str(dados.email).strip().lower()
    if db.query(models.Usuario.id).filter(
        models.Usuario.clinica_id == usuario.clinica_id,
        models.Usuario.email == email,
    ).first():
        raise HTTPException(status_code=409, detail="E-mail já cadastrado.")
    perfil = None
    if dados.role == "medico":
        perfil = db.query(models.Medico).filter(
            models.Medico.clinica_id == usuario.clinica_id,
            models.Medico.email == email,
            models.Medico.usuario_id.is_(None),
        ).first()
        if not perfil:
            raise HTTPException(status_code=400, detail="Cadastre o perfil médico com este e-mail antes de criar o acesso.")
    novo = models.Usuario(clinica_id=usuario.clinica_id, email=email, senha_hash=senha_hash(dados.password), role=dados.role, ativo=True)
    return persistir_usuario(novo, perfil, db)


def _dados_login(usuario: models.Usuario, *, autenticado: bool, recovery_codes: list[str] | None = None) -> dict:
    return {
        "autenticado": autenticado,
        "role": usuario.role,
        "clinica_slug": usuario.clinica.slug,
        "clinica_nome": usuario.clinica.nome,
        "mfa_required": False,
        "mfa_setup_required": False,
        "recovery_codes": recovery_codes or [],
    }


def _finalizar_login(
    usuario: models.Usuario,
    request: Request,
    resposta: Response,
    db: Session,
    *,
    mfa_verificada: bool,
    recovery_codes: list[str] | None = None,
) -> dict:
    _, access_token, refresh_token = emitir_sessao(
        usuario, request, db, mfa_verificada=mfa_verificada
    )
    configurar_cookies_sessao(resposta, access_token, refresh_token)
    return _dados_login(usuario, autenticado=True, recovery_codes=recovery_codes)


def _validar_bloqueio_mfa(usuario: models.Usuario) -> None:
    if usuario.mfa_bloqueado_ate and _como_utc(usuario.mfa_bloqueado_ate) > _agora_utc():
        raise HTTPException(status_code=429, detail="Segundo fator temporariamente bloqueado. Tente novamente mais tarde.")


def _falha_mfa(usuario: models.Usuario, db: Session) -> None:
    usuario.mfa_falhas = (usuario.mfa_falhas or 0) + 1
    if usuario.mfa_falhas >= 5:
        usuario.mfa_bloqueado_ate = _agora_utc() + timedelta(minutes=MFA_LOCK_MINUTES)
        usuario.mfa_falhas = 0
    db.commit()
    raise HTTPException(status_code=401, detail="Código de autenticação inválido ou já utilizado.")


def _validar_codigo_mfa(
    usuario: models.Usuario,
    codigo: str,
    db: Session,
    *,
    permitir_recuperacao: bool,
) -> str:
    _validar_bloqueio_mfa(usuario)
    if not usuario.mfa_secret_salt:
        _falha_mfa(usuario, db)
    segredo = segredo_totp(usuario.clinica_id, usuario.id, usuario.mfa_secret_salt)
    contador = verificar_codigo_totp(
        segredo,
        codigo,
        ultimo_contador=usuario.mfa_ultimo_contador,
    )
    if contador is not None:
        usuario.mfa_ultimo_contador = contador
        usuario.mfa_falhas = 0
        usuario.mfa_bloqueado_ate = None
        return "totp"
    if permitir_recuperacao:
        codigo_hash = hash_codigo_recuperacao(usuario.id, codigo)
        recuperacao = db.query(models.MfaCodigoRecuperacao).filter(
            models.MfaCodigoRecuperacao.usuario_id == usuario.id,
            models.MfaCodigoRecuperacao.clinica_id == usuario.clinica_id,
            models.MfaCodigoRecuperacao.codigo_hash == codigo_hash,
            models.MfaCodigoRecuperacao.usado_em.is_(None),
        ).first()
        if recuperacao:
            recuperacao.usado_em = _agora_utc()
            usuario.mfa_falhas = 0
            usuario.mfa_bloqueado_ate = None
            return "recuperacao"
    _falha_mfa(usuario, db)


@app.post("/auth/login", response_model=schemas.LoginResponse)
def login(
    request: Request,
    resposta: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = form_data.username.strip().lower()
    clinica_slug = (form_data.client_id or "").strip().lower()
    if not clinica_slug:
        raise HTTPException(status_code=400, detail="Informe o código da clínica.")
    chave_tentativa = f"{request.client.host if request.client else 'desconhecido'}:{clinica_slug}:{email}"
    agora = datetime.now(UTC)
    limite = agora - timedelta(minutes=15)
    recentes = [tentativa for tentativa in tentativas_login.get(chave_tentativa, []) if tentativa > limite]
    tentativas_login[chave_tentativa] = recentes
    if len(recentes) >= 5:
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos antes de tentar novamente.")
    clinica = db.query(models.Clinica).filter(
        models.Clinica.slug == clinica_slug,
        models.Clinica.ativo.is_(True),
    ).first()
    usuario = None
    if clinica:
        usuario = db.query(models.Usuario).filter(
            models.Usuario.clinica_id == clinica.id,
            models.Usuario.email == email,
            models.Usuario.ativo.is_(True),
        ).first()
    senha_valida = verificar_senha(form_data.password, usuario.senha_hash if usuario else DUMMY_PASSWORD_HASH)
    if not usuario or not senha_valida:
        tentativas_login[chave_tentativa].append(agora)
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.", headers={"WWW-Authenticate": "Bearer"})
    tentativas_login.pop(chave_tentativa, None)
    _validar_bloqueio_mfa(usuario)
    if usuario.role in {"admin", "medico"}:
        if not usuario.mfa_ativo:
            if not usuario.mfa_secret_salt:
                usuario.mfa_secret_salt = novo_salt_mfa()
                db.commit()
            configurar_cookie_preauth(resposta, criar_token_preauth(usuario, "mfa_setup"))
            dados = _dados_login(usuario, autenticado=False)
            dados["mfa_setup_required"] = True
            return dados
        configurar_cookie_preauth(resposta, criar_token_preauth(usuario, "mfa_login"))
        dados = _dados_login(usuario, autenticado=False)
        dados["mfa_required"] = True
        return dados
    return _finalizar_login(usuario, request, resposta, db, mfa_verificada=False)


@app.get("/auth/mfa/setup", response_model=schemas.MfaSetupResponse)
def obter_setup_mfa(request: Request, db: Session = Depends(get_db)):
    usuario, _ = usuario_do_desafio(request, db, propositos={"mfa_setup"})
    if usuario.role not in {"admin", "medico"} or usuario.mfa_ativo or not usuario.mfa_secret_salt:
        raise HTTPException(status_code=409, detail="A configuração do segundo fator não está disponível.")
    segredo = segredo_totp(usuario.clinica_id, usuario.id, usuario.mfa_secret_salt)
    return {
        "segredo": segredo,
        "uri_otpauth": uri_totp(
            segredo,
            clinica_nome=usuario.clinica.nome,
            email=usuario.email,
            emissor=MFA_ISSUER,
        ),
        "emissor": MFA_ISSUER,
        "conta": usuario.email,
    }


@app.post("/auth/mfa/ativar", response_model=schemas.LoginResponse)
def ativar_mfa(
    dados: schemas.MfaCodigoRequest,
    request: Request,
    resposta: Response,
    db: Session = Depends(get_db),
):
    usuario, _ = usuario_do_desafio(request, db, propositos={"mfa_setup"})
    if usuario.role not in {"admin", "medico"} or usuario.mfa_ativo:
        raise HTTPException(status_code=409, detail="O segundo fator já está configurado ou não é aplicável.")
    _validar_codigo_mfa(usuario, dados.codigo, db, permitir_recuperacao=False)
    codigos = gerar_codigos_recuperacao()
    agora = _agora_utc()
    usuario.mfa_ativo = True
    usuario.mfa_ativado_em = agora
    db.add_all([
        models.MfaCodigoRecuperacao(
            clinica_id=usuario.clinica_id,
            usuario_id=usuario.id,
            codigo_hash=hash_codigo_recuperacao(usuario.id, codigo),
            criado_em=agora,
        )
        for codigo in codigos
    ])
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ALTERACAO", recurso="mfa",
        detalhes={"metodo": "totp", "codigos_recuperacao": len(codigos)},
    )
    return _finalizar_login(
        usuario, request, resposta, db, mfa_verificada=True, recovery_codes=codigos
    )


@app.post("/auth/mfa/verificar", response_model=schemas.LoginResponse)
def verificar_mfa_login(
    dados: schemas.MfaCodigoRequest,
    request: Request,
    resposta: Response,
    db: Session = Depends(get_db),
):
    usuario, _ = usuario_do_desafio(request, db, propositos={"mfa_login"})
    if usuario.role not in {"admin", "medico"} or not usuario.mfa_ativo:
        raise HTTPException(status_code=409, detail="O segundo fator não está configurado para este usuário.")
    metodo = _validar_codigo_mfa(usuario, dados.codigo, db, permitir_recuperacao=True)
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ACESSO", recurso="mfa",
        detalhes={"metodo": metodo},
    )
    return _finalizar_login(usuario, request, resposta, db, mfa_verificada=True)


def _erro_refresh(detail: str, status_code: int = 401) -> JSONResponse:
    resposta = JSONResponse({"detail": detail}, status_code=status_code)
    limpar_cookies_sessao(resposta)
    return resposta


@app.post("/auth/refresh")
def renovar_sessao(request: Request, resposta: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    try:
        payload = jwt.decode(token or "", SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("purpose") != "refresh":
            raise InvalidTokenError("purpose")
        usuario_id = int(payload.get("sub"))
        clinica_id = int(payload.get("cid"))
        sessao_id = str(payload.get("sid"))
        rotacao = int(payload.get("rot"))
    except (InvalidTokenError, TypeError, ValueError):
        return _erro_refresh("A sessão não pôde ser renovada.")

    sessao = db.query(models.SessaoUsuario).filter(
        models.SessaoUsuario.id == sessao_id,
        models.SessaoUsuario.usuario_id == usuario_id,
        models.SessaoUsuario.clinica_id == clinica_id,
    ).first()
    agora = _agora_utc()
    if not sessao or sessao.revogado_em or _como_utc(sessao.expira_em) <= agora:
        return _erro_refresh("A sessão expirou ou foi revogada.")
    if rotacao != sessao.rotacao or not hmac.compare_digest(sessao.refresh_token_hash, hash_token(token or "")):
        sessao.revogado_em = agora
        sessao.motivo_revogacao = "reutilizacao_refresh"
        db.commit()
        return _erro_refresh("Reutilização de credencial detectada; a sessão foi revogada.")

    usuario = db.query(models.Usuario).join(models.Clinica).filter(
        models.Usuario.id == usuario_id,
        models.Usuario.clinica_id == clinica_id,
        models.Usuario.ativo.is_(True),
        models.Clinica.ativo.is_(True),
    ).first()
    if (
        not usuario
        or payload.get("rv") != usuario.reset_version
        or (usuario.role in {"admin", "medico"} and not sessao.mfa_verificada)
    ):
        sessao.revogado_em = agora
        sessao.motivo_revogacao = "usuario_invalido"
        db.commit()
        return _erro_refresh("A sessão não pôde ser renovada.")

    sessao.rotacao += 1
    sessao.ultimo_uso_em = agora
    sessao.ip_ultimo_hash = _dados_requisicao_sessao(request)[0]
    access_token = criar_token_acesso(usuario, sessao)
    refresh_token = criar_token_refresh(usuario, sessao)
    sessao.refresh_token_hash = hash_token(refresh_token)
    db.commit()
    configurar_cookies_sessao(resposta, access_token, refresh_token)
    return _dados_login(usuario, autenticado=True)


@app.get("/auth/me", response_model=schemas.SessaoAtualResponse)
def obter_sessao_atual(
    request: Request,
    usuario: models.Usuario = Depends(usuario_atual),
):
    sessao: models.SessaoUsuario = request.state.sessao
    return {
        "usuario_id": usuario.id,
        "email": usuario.email,
        "role": usuario.role,
        "clinica_id": usuario.clinica_id,
        "clinica_slug": usuario.clinica.slug,
        "clinica_nome": usuario.clinica.nome,
        "sessao_id": sessao.id,
        "mfa_ativo": usuario.mfa_ativo,
        "mfa_verificada": sessao.mfa_verificada,
    }


@app.get("/auth/sessoes", response_model=List[schemas.SessaoResponse])
def listar_sessoes(
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(usuario_atual),
):
    agora = _agora_utc()
    atual_id = request.state.sessao.id
    sessoes = db.query(models.SessaoUsuario).filter(
        models.SessaoUsuario.usuario_id == usuario.id,
        models.SessaoUsuario.clinica_id == usuario.clinica_id,
        models.SessaoUsuario.revogado_em.is_(None),
        models.SessaoUsuario.expira_em > agora,
    ).order_by(models.SessaoUsuario.ultimo_uso_em.desc()).all()
    return [
        {
            "id": sessao.id,
            "criado_em": sessao.criado_em,
            "ultimo_uso_em": sessao.ultimo_uso_em,
            "expira_em": sessao.expira_em,
            "mfa_verificada": sessao.mfa_verificada,
            "atual": sessao.id == atual_id,
        }
        for sessao in sessoes
    ]


@app.post("/auth/sessoes/{sessao_id}/revogar", response_model=schemas.MensagemResponse)
def revogar_sessao(
    sessao_id: str,
    request: Request,
    resposta: Response,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(usuario_atual),
):
    sessao = db.query(models.SessaoUsuario).filter(
        models.SessaoUsuario.id == sessao_id,
        models.SessaoUsuario.usuario_id == usuario.id,
        models.SessaoUsuario.clinica_id == usuario.clinica_id,
    ).first()
    if not sessao:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    if not sessao.revogado_em:
        sessao.revogado_em = _agora_utc()
        sessao.motivo_revogacao = "revogada_usuario"
        registrar_auditoria(
            db, request=request, usuario=usuario, acao="REVOGACAO", recurso="sessao",
            detalhes={"sessao_id": sessao.id, "sessao_atual": sessao.id == request.state.sessao.id},
        )
        db.commit()
    if sessao.id == request.state.sessao.id:
        limpar_cookies_sessao(resposta)
    return {"mensagem": "Sessão revogada com sucesso."}


@app.post("/auth/logout", response_model=schemas.MensagemResponse)
def logout(
    request: Request,
    resposta: Response,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(usuario_atual),
):
    sessao: models.SessaoUsuario = request.state.sessao
    if not sessao.revogado_em:
        sessao.revogado_em = _agora_utc()
        sessao.motivo_revogacao = "logout"
        registrar_auditoria(
            db, request=request, usuario=usuario, acao="REVOGACAO", recurso="sessao",
            detalhes={"sessao_id": sessao.id},
        )
        db.commit()
    limpar_cookies_sessao(resposta)
    resposta.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    return {"mensagem": "Sessão encerrada com sucesso."}


@app.post("/auth/logout-all", response_model=schemas.MensagemResponse)
def logout_todas_sessoes(
    request: Request,
    resposta: Response,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(usuario_atual),
):
    quantidade = revogar_sessoes_usuario(db, usuario.id, "logout_todos")
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="REVOGACAO", recurso="sessao",
        detalhes={"todas": True, "quantidade": quantidade},
    )
    db.commit()
    limpar_cookies_sessao(resposta)
    resposta.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    return {"mensagem": "Todas as sessões foram encerradas."}


@app.post("/auth/mfa/codigos-recuperacao", response_model=schemas.MfaCodigosResponse)
def regenerar_codigos_mfa(
    dados: schemas.MfaRegenerarRequest,
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "medico")),
):
    if not usuario.mfa_ativo or not verificar_senha(dados.senha, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="Não foi possível confirmar as credenciais.")
    _validar_codigo_mfa(usuario, dados.codigo, db, permitir_recuperacao=True)
    db.query(models.MfaCodigoRecuperacao).filter(
        models.MfaCodigoRecuperacao.usuario_id == usuario.id,
        models.MfaCodigoRecuperacao.clinica_id == usuario.clinica_id,
    ).delete(synchronize_session=False)
    codigos = gerar_codigos_recuperacao()
    agora = _agora_utc()
    db.add_all([
        models.MfaCodigoRecuperacao(
            clinica_id=usuario.clinica_id,
            usuario_id=usuario.id,
            codigo_hash=hash_codigo_recuperacao(usuario.id, codigo),
            criado_em=agora,
        )
        for codigo in codigos
    ])
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ALTERACAO", recurso="mfa_codigos_recuperacao",
        detalhes={"quantidade": len(codigos)},
    )
    db.commit()
    return {"recovery_codes": codigos}


@app.post("/auth/solicitar-recuperacao", status_code=status.HTTP_202_ACCEPTED)
def solicitar_recuperacao_senha(dados: schemas.RecuperacaoSenhaRequest, db: Session = Depends(get_db)):
    """Sempre responde de forma genérica para não revelar e-mails cadastrados."""
    clinica = db.query(models.Clinica).filter(
        models.Clinica.slug == dados.clinica_slug,
        models.Clinica.ativo.is_(True),
    ).first()
    usuario = None
    if clinica:
        usuario = db.query(models.Usuario).filter(
            models.Usuario.clinica_id == clinica.id,
            models.Usuario.email == str(dados.email).strip().lower(),
            models.Usuario.ativo.is_(True),
        ).first()
    if usuario:
        try:
            enviar_link_recuperacao(usuario.email, criar_token_recuperacao(usuario))
        except Exception:
            logger.exception("Não foi possível enviar o e-mail de recuperação")
    return {"mensagem": "Se o e-mail estiver cadastrado, você receberá as instruções para redefinir sua senha."}


@app.post("/auth/redefinir-senha")
def redefinir_senha(dados: schemas.RedefinirSenhaRequest, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(dados.token, SECRET_KEY, algorithms=[ALGORITHM])
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="O link de recuperação é inválido ou expirou.")
    if payload.get("purpose") != "password_reset" or not payload.get("sub") or not payload.get("cid"):
        raise HTTPException(status_code=400, detail="O link de recuperação é inválido.")
    try:
        usuario_id = int(payload["sub"])
        clinica_id = int(payload["cid"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="O link de recuperação é inválido.")
    usuario = db.query(models.Usuario).join(models.Clinica).filter(
        models.Usuario.id == usuario_id,
        models.Usuario.clinica_id == clinica_id,
        models.Usuario.ativo.is_(True),
        models.Clinica.ativo.is_(True),
    ).first()
    if not usuario or payload.get("rv") != usuario.reset_version:
        raise HTTPException(status_code=400, detail="O link de recuperação é inválido.")
    usuario.senha_hash = senha_hash(dados.nova_senha)
    usuario.reset_version += 1
    revogar_sessoes_usuario(db, usuario.id, "redefinicao_senha")
    db.commit()
    sufixo_email = f":{usuario.clinica.slug}:{usuario.email.lower()}"
    for chave in [chave for chave in tentativas_login if chave.endswith(sufixo_email)]:
        tentativas_login.pop(chave, None)
    return {"mensagem": "Senha atualizada com sucesso. Faça login com a nova senha."}


@app.get("/lgpd/documentos", response_model=schemas.DocumentoLGPDResponse)
def documentos_lgpd():
    return {
        "termos_versao": TERMOS_VERSAO,
        "privacidade_versao": PRIVACIDADE_VERSAO,
        "termos_url": "/termos.html",
        "privacidade_url": "/privacidade.html",
        "retencao_prontuario_anos": PRONTUARIO_RETENTION_YEARS,
        "observacao_retencao": (
            "Prontuários são mantidos pelo prazo mínimo legal contado do último registro. "
            "Pedidos de eliminação são avaliados considerando obrigações legais e regulatórias."
        ),
    }


@app.get("/lgpd/consentimentos", response_model=List[schemas.ConsentimentoResponse])
def listar_consentimentos(
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "medico", "paciente")),
):
    return db.query(models.Consentimento).filter(
        models.Consentimento.clinica_id == usuario.clinica_id,
        models.Consentimento.usuario_id == usuario.id,
    ).order_by(models.Consentimento.aceito_em.desc()).all()


@app.post("/lgpd/documentos/aceitar", response_model=List[schemas.ConsentimentoResponse])
def aceitar_documentos_lgpd(
    dados: schemas.AceiteDocumentosLGPDCreate,
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "medico", "paciente")),
):
    erro = validar_aceite_documentos(
        dados.aceita_termos,
        dados.ciente_privacidade,
        dados.termos_versao,
        dados.privacidade_versao,
    )
    if erro:
        raise HTTPException(status_code=409, detail=erro)
    existentes = db.query(models.Consentimento).filter(
        models.Consentimento.clinica_id == usuario.clinica_id,
        models.Consentimento.usuario_id == usuario.id,
        models.Consentimento.documento_tipo.in_(["termos_uso", "politica_privacidade"]),
    ).all()
    atuais = {
        item.documento_tipo for item in existentes
        if (item.documento_tipo == "termos_uso" and item.versao == TERMOS_VERSAO)
        or (item.documento_tipo == "politica_privacidade" and item.versao == PRIVACIDADE_VERSAO)
    }
    paciente = paciente_do_usuario(usuario, db) if usuario.role == "paciente" else None
    novos = [
        item for item in criar_consentimentos_obrigatorios(
            clinica_id=usuario.clinica_id,
            usuario_id=usuario.id,
            paciente_id=paciente.id if paciente else None,
            request=request,
        )
        if item.documento_tipo not in atuais
    ]
    if novos:
        db.add_all(novos)
        registrar_auditoria(
            db, request=request, usuario=usuario, acao="CONSENTIMENTO", recurso="documentos_lgpd",
            paciente_id=paciente.id if paciente else None,
            campos=[item.documento_tipo for item in novos],
            detalhes={"termos_versao": TERMOS_VERSAO, "privacidade_versao": PRIVACIDADE_VERSAO},
        )
        db.commit()
    return db.query(models.Consentimento).filter(
        models.Consentimento.clinica_id == usuario.clinica_id,
        models.Consentimento.usuario_id == usuario.id,
    ).order_by(models.Consentimento.aceito_em.desc()).all()


@app.post("/lgpd/consentimentos/comunicacoes", response_model=schemas.ConsentimentoResponse, status_code=status.HTTP_201_CREATED)
def aceitar_comunicacoes(
    dados: schemas.ConsentimentoComunicacoesCreate,
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "medico", "paciente")),
):
    existente = db.query(models.Consentimento).filter(
        models.Consentimento.clinica_id == usuario.clinica_id,
        models.Consentimento.usuario_id == usuario.id,
        models.Consentimento.documento_tipo == "comunicacoes",
        models.Consentimento.revogado_em.is_(None),
    ).first()
    if existente:
        raise HTTPException(status_code=409, detail="O consentimento para comunicações já está ativo.")
    paciente = paciente_do_usuario(usuario, db) if usuario.role == "paciente" else None
    endereco_ip, user_agent = dados_requisicao(request)
    consentimento = models.Consentimento(
        clinica_id=usuario.clinica_id,
        usuario_id=usuario.id,
        paciente_id=paciente.id if paciente else None,
        documento_tipo="comunicacoes",
        versao=PRIVACIDADE_VERSAO,
        finalidade=dados.finalidade,
        base_legal=BASES_LEGAIS_DOCUMENTOS["comunicacoes"],
        aceito_em=datetime.now(UTC),
        endereco_ip=endereco_ip,
        user_agent=user_agent,
        documento_hash=hash_documento("comunicacoes", PRIVACIDADE_VERSAO),
    )
    db.add(consentimento); db.flush()
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="CONSENTIMENTO", recurso="consentimento",
        registro_id=consentimento.id, paciente_id=paciente.id if paciente else None,
        campos=["comunicacoes"], detalhes={"versao": PRIVACIDADE_VERSAO},
    )
    db.commit(); db.refresh(consentimento)
    return consentimento


@app.delete("/lgpd/consentimentos/{consentimento_id}/revogar", response_model=schemas.ConsentimentoResponse)
def revogar_consentimento(
    consentimento_id: int,
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "medico", "paciente")),
):
    consentimento = db.query(models.Consentimento).filter(
        models.Consentimento.id == consentimento_id,
        models.Consentimento.clinica_id == usuario.clinica_id,
        models.Consentimento.usuario_id == usuario.id,
    ).first()
    if not consentimento:
        raise HTTPException(status_code=404, detail="Consentimento não encontrado.")
    if consentimento.documento_tipo != "comunicacoes":
        raise HTTPException(status_code=409, detail="Este registro documenta ciência ou execução contratual e não é um consentimento opcional.")
    if consentimento.revogado_em:
        raise HTTPException(status_code=409, detail="Consentimento já revogado.")
    consentimento.revogado_em = datetime.now(UTC)
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="REVOGACAO", recurso="consentimento",
        registro_id=consentimento.id, paciente_id=consentimento.paciente_id, campos=["revogado_em"],
    )
    db.commit(); db.refresh(consentimento)
    return consentimento


@app.get("/auditoria", response_model=List[schemas.RegistroAuditoriaResponse])
def listar_auditoria(
    request: Request,
    acao: str | None = None,
    recurso: str | None = None,
    paciente_id: int | None = None,
    limite: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin")),
):
    consulta = db.query(models.RegistroAuditoria).filter(
        models.RegistroAuditoria.clinica_id == usuario.clinica_id
    )
    if acao:
        consulta = consulta.filter(models.RegistroAuditoria.acao == acao.upper())
    if recurso:
        consulta = consulta.filter(models.RegistroAuditoria.recurso == recurso)
    if paciente_id is not None:
        consulta = consulta.filter(models.RegistroAuditoria.paciente_id == paciente_id)
    registros = consulta.order_by(models.RegistroAuditoria.id.desc()).limit(limite).all()
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ACESSO", recurso="auditoria",
        detalhes={"filtros": {"acao": acao, "recurso": recurso, "paciente_id": paciente_id}, "limite": limite},
    )
    db.commit()
    return registros


@app.get("/auditoria/integridade")
def verificar_auditoria(
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin")),
):
    registros = db.query(models.RegistroAuditoria).filter(
        models.RegistroAuditoria.clinica_id == usuario.clinica_id
    ).order_by(models.RegistroAuditoria.id.asc()).all()
    integra, primeiro_problema = verificar_integridade_auditoria(registros)
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ACESSO", recurso="integridade_auditoria",
        detalhes={"resultado": "integra" if integra else "inconsistente", "registros_verificados": len(registros)},
    )
    db.commit()
    return {"integra": integra, "registros_verificados": len(registros), "primeiro_registro_inconsistente": primeiro_problema}


@app.get("/lgpd/meus-dados/exportar")
def exportar_meus_dados(
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("paciente")),
):
    paciente = paciente_do_usuario(usuario, db)
    agendamentos = db.query(models.Agendamento).filter(
        models.Agendamento.clinica_id == usuario.clinica_id,
        models.Agendamento.paciente_id == paciente.id,
    ).all()
    exames = db.query(models.Exame).filter(
        models.Exame.clinica_id == usuario.clinica_id,
        models.Exame.paciente_id == paciente.id,
    ).all()
    avaliacoes = db.query(models.Avaliacao).filter(
        models.Avaliacao.clinica_id == usuario.clinica_id,
        models.Avaliacao.paciente_id == paciente.id,
    ).all()
    prontuarios = db.query(models.ProntuarioEntrada).filter(
        models.ProntuarioEntrada.clinica_id == usuario.clinica_id,
        models.ProntuarioEntrada.paciente_id == paciente.id,
    ).order_by(models.ProntuarioEntrada.criado_em.asc()).all()
    prescricoes = db.query(models.Prescricao).filter(
        models.Prescricao.clinica_id == usuario.clinica_id,
        models.Prescricao.paciente_id == paciente.id,
    ).order_by(models.Prescricao.criado_em.asc()).all()
    consentimentos = db.query(models.Consentimento).filter(
        models.Consentimento.clinica_id == usuario.clinica_id,
        models.Consentimento.usuario_id == usuario.id,
    ).all()
    solicitacoes = db.query(models.SolicitacaoLGPD).filter(
        models.SolicitacaoLGPD.clinica_id == usuario.clinica_id,
        models.SolicitacaoLGPD.usuario_solicitante_id == usuario.id,
    ).all()
    conteudo = {
        "exportado_em": datetime.now(UTC),
        "clinica": {"id": usuario.clinica.id, "nome": usuario.clinica.nome, "slug": usuario.clinica.slug},
        "usuario": {"id": usuario.id, "email": usuario.email, "role": usuario.role, "ativo": usuario.ativo},
        "dados_pessoais": schemas.PacienteResponse.model_validate(paciente).model_dump(),
        "agendamentos": [schemas.AgendamentoResponse.model_validate(item).model_dump() for item in agendamentos],
        "exames": [schemas.ExameResponse.model_validate(item).model_dump() for item in exames],
        "avaliacoes_de_atendimento": [schemas.AvaliacaoResponse.model_validate(item).model_dump() for item in avaliacoes],
        "prontuario_clinico": [schemas.ProntuarioResponse.model_validate(item).model_dump() for item in prontuarios],
        "prescricoes": [schemas.PrescricaoResponse.model_validate(item).model_dump() for item in prescricoes],
        "consentimentos": [schemas.ConsentimentoResponse.model_validate(item).model_dump() for item in consentimentos],
        "solicitacoes_lgpd": [schemas.SolicitacaoLGPDResponse.model_validate(item).model_dump() for item in solicitacoes],
    }
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="EXPORTACAO", recurso="dados_titular",
        registro_id=paciente.id, paciente_id=paciente.id,
        detalhes={
            "agendamentos": len(agendamentos), "exames": len(exames),
            "avaliacoes": len(avaliacoes), "prontuarios": len(prontuarios), "prescricoes": len(prescricoes),
        },
    )
    db.commit()
    corpo = json.dumps(jsonable_encoder(conteudo), ensure_ascii=False, indent=2)
    return Response(
        content=corpo,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="meus-dados-{paciente.id}.json"'},
    )


@app.post("/lgpd/solicitacoes", response_model=schemas.SolicitacaoLGPDResponse, status_code=status.HTTP_201_CREATED)
def criar_solicitacao_lgpd(
    dados: schemas.SolicitacaoLGPDCreate,
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("paciente")),
):
    paciente = paciente_do_usuario(usuario, db)
    pendente = db.query(models.SolicitacaoLGPD.id).filter(
        models.SolicitacaoLGPD.clinica_id == usuario.clinica_id,
        models.SolicitacaoLGPD.paciente_id == paciente.id,
        models.SolicitacaoLGPD.tipo == dados.tipo,
        models.SolicitacaoLGPD.status == "Pendente",
    ).first()
    if pendente:
        raise HTTPException(status_code=409, detail="Já existe uma solicitação pendente deste tipo.")
    solicitacao = models.SolicitacaoLGPD(
        clinica_id=usuario.clinica_id,
        paciente_id=paciente.id,
        usuario_solicitante_id=usuario.id,
        tipo=dados.tipo,
        status="Pendente",
        justificativa=dados.justificativa,
        solicitado_em=datetime.now(UTC),
    )
    db.add(solicitacao); db.flush()
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="SOLICITACAO", recurso="solicitacao_lgpd",
        registro_id=solicitacao.id, paciente_id=paciente.id, detalhes={"tipo": dados.tipo},
    )
    db.commit(); db.refresh(solicitacao)
    return solicitacao


@app.get("/lgpd/solicitacoes", response_model=List[schemas.SolicitacaoLGPDResponse])
def listar_solicitacoes_lgpd(
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin", "paciente")),
):
    consulta = db.query(models.SolicitacaoLGPD).filter(
        models.SolicitacaoLGPD.clinica_id == usuario.clinica_id
    )
    if usuario.role == "paciente":
        consulta = consulta.filter(models.SolicitacaoLGPD.usuario_solicitante_id == usuario.id)
    return consulta.order_by(models.SolicitacaoLGPD.solicitado_em.desc()).all()


@app.post("/lgpd/solicitacoes/{solicitacao_id}/processar", response_model=schemas.SolicitacaoLGPDResponse)
def processar_solicitacao_lgpd(
    solicitacao_id: int,
    dados: schemas.SolicitacaoLGPDProcessar,
    request: Request,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_roles("admin")),
):
    solicitacao = db.query(models.SolicitacaoLGPD).filter(
        models.SolicitacaoLGPD.id == solicitacao_id,
        models.SolicitacaoLGPD.clinica_id == usuario.clinica_id,
    ).first()
    if not solicitacao:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
    if solicitacao.status != "Pendente":
        raise HTTPException(status_code=409, detail="Esta solicitação já foi processada.")

    if dados.decisao == "rejeitar":
        solicitacao.status = "Rejeitada"
    else:
        paciente = db.query(models.Paciente).filter(
            models.Paciente.id == solicitacao.paciente_id,
            models.Paciente.clinica_id == usuario.clinica_id,
        ).first()
        if not paciente:
            raise HTTPException(status_code=404, detail="Paciente vinculado à solicitação não encontrado.")
        if solicitacao.tipo in {"anonimizacao", "exclusao"}:
            permitido, ultimo = retencao_cumprida(paciente, db)
            if not permitido:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"A solicitação não pode ser concluída antes do prazo mínimo de {PRONTUARIO_RETENTION_YEARS} anos "
                        f"contado do último registro clínico ({ultimo.date().isoformat()}). Registre a rejeição fundamentada."
                    ),
                )
            acao = "ANONIMIZACAO" if solicitacao.tipo == "anonimizacao" else "EXCLUSAO"
            registrar_auditoria(
                db, request=request, usuario=usuario, acao=acao, recurso="dados_titular",
                registro_id=paciente.id, paciente_id=paciente.id,
                campos=["dados_cadastrais", "conta", "dados_clinicos" if acao == "EXCLUSAO" else "identificadores"],
                detalhes={"solicitacao_id": solicitacao.id, "retencao_anos": PRONTUARIO_RETENTION_YEARS},
            )
            if solicitacao.tipo == "anonimizacao":
                anonimizar_dados_paciente(paciente, db)
            else:
                excluir_dados_paciente(paciente, db)
                solicitacao.paciente_id = None
                solicitacao.usuario_solicitante_id = None
        solicitacao.status = "Concluida"

    solicitacao.processado_em = datetime.now(UTC)
    solicitacao.processado_por_id = usuario.id
    solicitacao.decisao_observacao = dados.observacao
    registrar_auditoria(
        db, request=request, usuario=usuario, acao="ALTERACAO", recurso="solicitacao_lgpd",
        registro_id=solicitacao.id, paciente_id=solicitacao.paciente_id,
        campos=["status", "decisao_observacao"], detalhes={"decisao": dados.decisao, "tipo": solicitacao.tipo},
    )
    db.commit(); db.refresh(solicitacao)
    return solicitacao


FRONTEND_DIR = Path(__file__).resolve().parent
for arquivo_frontend in (
    "login.html", "register.html", "recuperar-senha.html", "index.html",
    "paciente.html", "medico.html", "nova-clinica.html", "lgpd.html",
    "seguranca.html", "termos.html", "privacidade.html", "app.css", "app.js",
):
    app.add_api_route(
        f"/{arquivo_frontend}",
        lambda arquivo=arquivo_frontend: FileResponse(FRONTEND_DIR / arquivo),
        methods=["GET"],
        include_in_schema=False,
    )
