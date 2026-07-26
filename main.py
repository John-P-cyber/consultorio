import math
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Callable, List
from urllib.parse import urlencode

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.orm import Session

import models
import schemas
from config import (ACCESS_TOKEN_EXPIRE_MINUTES, ALLOWED_ORIGINS, APP_ENV,
                    RESET_TOKEN_EXPIRE_MINUTES, RESET_URL, SECRET_KEY, SMTP_FROM,
                    SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME)
from database import SessionLocal, engine

ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

app = FastAPI(title="Clínica Inteligente - API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
def criar_estrutura_banco() -> None:
    """Cria tabelas novas em desenvolvimento; em produção use Alembic."""
    if APP_ENV == "development":
        models.Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE exames ADD COLUMN IF NOT EXISTS resultado VARCHAR"))
            connection.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS reset_version INTEGER NOT NULL DEFAULT 0"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def senha_hash(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha_pura: str, senha_criptografada: str) -> bool:
    return pwd_context.verify(senha_pura, senha_criptografada)


def criar_token_acesso(dados: dict) -> str:
    payload = dados.copy()
    payload["exp"] = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def criar_token_recuperacao(usuario: models.Usuario) -> str:
    return jwt.encode(
        {"sub": usuario.email, "purpose": "password_reset", "rv": usuario.reset_version, "exp": datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)},
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
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.Usuario:
    credencial_invalida = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        email = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]).get("sub")
    except InvalidTokenError:
        raise credencial_invalida
    if not email:
        raise credencial_invalida
    usuario = db.query(models.Usuario).filter(models.Usuario.email == email).first()
    if not usuario:
        raise credencial_invalida
    return usuario


def exigir_roles(*roles: str) -> Callable:
    def verificar(usuario: models.Usuario = Depends(usuario_atual)) -> models.Usuario:
        if usuario.role not in roles:
            raise HTTPException(status_code=403, detail="Você não tem permissão para esta ação.")
        return usuario

    return verificar


def paciente_do_usuario(usuario: models.Usuario, db: Session) -> models.Paciente:
    paciente = db.query(models.Paciente).filter(models.Paciente.usuario_id == usuario.id).first()
    if not paciente:
        raise HTTPException(status_code=403, detail="Seu usuário não está vinculado a um paciente.")
    return paciente


def medico_do_usuario(usuario: models.Usuario, db: Session) -> models.Medico:
    medico = db.query(models.Medico).filter(models.Medico.usuario_id == usuario.id).first()
    if not medico:
        raise HTTPException(status_code=403, detail="Seu usuário não está vinculado a um médico.")
    return medico


def calcular_distancia(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    if None in (lat1, lon1, lat2, lon2):
        return 9999.0
    raio_terra = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return raio_terra * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.get("/", include_in_schema=False)
def inicio():
    return HTMLResponse('<h1>Clínica Inteligente</h1><p>API disponível em <a href="/docs">/docs</a>.</p>')


@app.post("/pacientes/", response_model=schemas.PacienteResponse, status_code=status.HTTP_201_CREATED)
def criar_paciente(paciente: schemas.PacienteCreate, db: Session = Depends(get_db), _: models.Usuario = Depends(exigir_roles("admin"))):
    if db.query(models.Paciente).filter((models.Paciente.cpf == paciente.cpf) | (models.Paciente.email == paciente.email)).first():
        raise HTTPException(status_code=400, detail="CPF ou e-mail já cadastrado.")
    novo = models.Paciente(**paciente.model_dump())
    db.add(novo); db.commit(); db.refresh(novo)
    return novo


@app.get("/pacientes/", response_model=List[schemas.PacienteResponse])
def listar_pacientes(db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "medico", "paciente"))):
    if usuario.role == "paciente":
        return [paciente_do_usuario(usuario, db)]
    return db.query(models.Paciente).all()


@app.post("/medicos/", response_model=schemas.MedicoResponse, status_code=status.HTTP_201_CREATED)
def criar_medico(medico: schemas.MedicoCreate, db: Session = Depends(get_db), _: models.Usuario = Depends(exigir_roles("admin"))):
    if db.query(models.Medico).filter((models.Medico.crm == medico.crm) | (models.Medico.email == medico.email)).first():
        raise HTTPException(status_code=400, detail="CRM ou e-mail já cadastrado.")
    novo = models.Medico(**medico.model_dump())
    db.add(novo); db.commit(); db.refresh(novo)
    return novo


@app.get("/medicos/", response_model=List[schemas.MedicoResponse])
def listar_medicos(db: Session = Depends(get_db), _: models.Usuario = Depends(exigir_roles("admin", "medico", "paciente"))):
    return db.query(models.Medico).all()


@app.get("/medicos/recomendados")
def recomendar_medicos(latitude_paciente: float, longitude_paciente: float, db: Session = Depends(get_db), _: models.Usuario = Depends(exigir_roles("paciente", "admin"))):
    medicos = db.query(models.Medico).all()
    ordenados = sorted(((medico, calcular_distancia(latitude_paciente, longitude_paciente, medico.latitude, medico.longitude)) for medico in medicos), key=lambda item: (-item[0].avaliacao_media, item[1]))
    return [{"id": medico.id, "nome": medico.nome, "especialidade": medico.especialidade, "crm": medico.crm, "avaliacao_media": medico.avaliacao_media, "distancia_km": round(distancia, 2), "morada": f"{medico.endereco_rua}, {medico.endereco_numero} - {medico.endereco_bairro}"} for medico, distancia in ordenados]


@app.get("/medicos/{medico_id}/horarios-disponiveis")
def listar_horarios_disponiveis(medico_id: int, data: str, db: Session = Depends(get_db), _: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico"))):
    try:
        dia = datetime.strptime(data, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use AAAA-MM-DD.")
    medico = db.get(models.Medico, medico_id)
    if not medico:
        raise HTTPException(status_code=404, detail="Médico não encontrado.")
    possiveis = []
    for inicio, fim in ((8, 12), (13, 18)):
        horario = datetime.combine(dia, datetime.min.time().replace(hour=inicio))
        limite = datetime.combine(dia, datetime.min.time().replace(hour=fim))
        while horario + timedelta(minutes=medico.duracao_consulta) <= limite:
            possiveis.append(horario)
            horario += timedelta(minutes=medico.duracao_consulta)
    ocupados = {agendamento.data_hora for agendamento in db.query(models.Agendamento).filter(models.Agendamento.medico_id == medico_id, models.Agendamento.data_hora >= datetime.combine(dia, datetime.min.time()), models.Agendamento.data_hora < datetime.combine(dia + timedelta(days=1), datetime.min.time()), models.Agendamento.status != "Cancelado").all()}
    return [horario.strftime("%H:%M") for horario in possiveis if horario not in ocupados]


@app.post("/agendamentos/", response_model=schemas.AgendamentoResponse, status_code=status.HTTP_201_CREATED)
def criar_agendamento(agendamento: schemas.AgendamentoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente"))):
    if agendamento.data_hora <= datetime.now():
        raise HTTPException(status_code=400, detail="A consulta deve ser agendada para uma data futura.")
    if usuario.role == "paciente" and paciente_do_usuario(usuario, db).id != agendamento.paciente_id:
        raise HTTPException(status_code=403, detail="Você só pode agendar consultas para si mesmo.")
    if not db.get(models.Medico, agendamento.medico_id) or not db.get(models.Paciente, agendamento.paciente_id):
        raise HTTPException(status_code=404, detail="Médico ou paciente não encontrado.")
    conflito = db.query(models.Agendamento).filter(models.Agendamento.medico_id == agendamento.medico_id, models.Agendamento.data_hora == agendamento.data_hora, models.Agendamento.status != "Cancelado").first()
    if conflito:
        raise HTTPException(status_code=409, detail="Este horário acabou de ser ocupado.")
    novo = models.Agendamento(**agendamento.model_dump())
    db.add(novo); db.commit(); db.refresh(novo)
    return novo


@app.get("/agendamentos/", response_model=List[schemas.AgendamentoResponse])
def listar_agendamentos(db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico"))):
    consulta = db.query(models.Agendamento)
    if usuario.role == "paciente": consulta = consulta.filter(models.Agendamento.paciente_id == paciente_do_usuario(usuario, db).id)
    if usuario.role == "medico": consulta = consulta.filter(models.Agendamento.medico_id == medico_do_usuario(usuario, db).id)
    return consulta.all()


@app.patch("/agendamentos/{agendamento_id}/status", response_model=schemas.AgendamentoResponse)
def atualizar_status_agendamento(agendamento_id: int, status_novo: str, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico"))):
    agendamento = db.get(models.Agendamento, agendamento_id)
    if not agendamento: raise HTTPException(status_code=404, detail="Agendamento não encontrado.")
    permitidos = {"Confirmado", "Atendido", "Cancelado"}
    if status_novo not in permitidos: raise HTTPException(status_code=400, detail="Status inválido.")
    if usuario.role == "paciente" and (agendamento.paciente_id != paciente_do_usuario(usuario, db).id or status_novo != "Cancelado"): raise HTTPException(status_code=403, detail="Paciente só pode cancelar a própria consulta.")
    if usuario.role == "medico" and (agendamento.medico_id != medico_do_usuario(usuario, db).id or status_novo not in {"Confirmado", "Atendido"}): raise HTTPException(status_code=403, detail="Ação não permitida para este médico.")
    agendamento.status = status_novo; db.commit(); db.refresh(agendamento)
    return agendamento


@app.post("/exames/", response_model=schemas.ExameResponse, status_code=status.HTTP_201_CREATED)
def criar_exame(exame: schemas.ExameCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente"))):
    if usuario.role == "paciente" and paciente_do_usuario(usuario, db).id != exame.paciente_id: raise HTTPException(status_code=403, detail="Você só pode solicitar exames para si mesmo.")
    if not db.get(models.Paciente, exame.paciente_id): raise HTTPException(status_code=404, detail="Paciente não encontrado.")
    novo = models.Exame(**exame.model_dump()); db.add(novo); db.commit(); db.refresh(novo)
    return novo


@app.get("/exames/", response_model=List[schemas.ExameResponse])
def listar_exames(db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico"))):
    consulta = db.query(models.Exame)
    if usuario.role == "paciente": consulta = consulta.filter(models.Exame.paciente_id == paciente_do_usuario(usuario, db).id)
    return consulta.all()


@app.patch("/exames/{exame_id}/resultado", response_model=schemas.ExameResponse)
def salvar_resultado_exame(exame_id: int, resultado: dict, db: Session = Depends(get_db), _: models.Usuario = Depends(exigir_roles("admin", "medico"))):
    exame = db.get(models.Exame, exame_id)
    texto_resultado = resultado.get("resultado", "").strip()
    if not exame: raise HTTPException(status_code=404, detail="Exame não encontrado.")
    if not texto_resultado: raise HTTPException(status_code=400, detail="Informe o resultado do exame.")
    exame.resultado, exame.status = texto_resultado, "Concluído"; db.commit(); db.refresh(exame)
    return exame


@app.post("/avaliacoes/", response_model=schemas.AvaliacaoResponse, status_code=status.HTTP_201_CREATED)
def criar_avaliacao(avaliacao: schemas.AvaliacaoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("paciente", "medico"))):
    agendamento = db.get(models.Agendamento, avaliacao.agendamento_id)
    if not agendamento or agendamento.paciente_id != avaliacao.paciente_id or agendamento.medico_id != avaliacao.medico_id: raise HTTPException(status_code=400, detail="Avaliação não corresponde ao agendamento.")
    if usuario.role == "paciente" and paciente_do_usuario(usuario, db).id != avaliacao.paciente_id: raise HTTPException(status_code=403, detail="Você só pode avaliar a própria consulta.")
    if usuario.role == "medico" and medico_do_usuario(usuario, db).id != avaliacao.medico_id: raise HTTPException(status_code=403, detail="Você só pode avaliar suas consultas.")
    existente = db.query(models.Avaliacao).filter(models.Avaliacao.agendamento_id == avaliacao.agendamento_id).first()
    if existente:
        if usuario.role != "medico": raise HTTPException(status_code=409, detail="Esta consulta já foi avaliada.")
        existente.comentario_medico, existente.nota_paciente = avaliacao.comentario_medico, avaliacao.nota_paciente; db.commit(); db.refresh(existente); return existente
    novo = models.Avaliacao(**avaliacao.model_dump()); db.add(novo); db.commit(); db.refresh(novo)
    return novo


@app.get("/avaliacoes/", response_model=List[schemas.AvaliacaoResponse])
def listar_avaliacoes(db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_roles("admin", "paciente", "medico"))):
    consulta = db.query(models.Avaliacao)
    if usuario.role == "paciente": consulta = consulta.filter(models.Avaliacao.paciente_id == paciente_do_usuario(usuario, db).id)
    if usuario.role == "medico": consulta = consulta.filter(models.Avaliacao.medico_id == medico_do_usuario(usuario, db).id)
    return consulta.all()


@app.post("/auth/registrar", response_model=schemas.UsuarioResponse, status_code=status.HTTP_201_CREATED)
def registrar_usuario(usuario: schemas.UsuarioCreate, db: Session = Depends(get_db)):
    if usuario.role == "admin" and db.query(models.Usuario).filter(models.Usuario.role == "admin").first(): raise HTTPException(status_code=403, detail="Administradores só podem ser criados por administração autorizada.")
    if db.query(models.Usuario).filter(models.Usuario.email == usuario.email).first(): raise HTTPException(status_code=400, detail="E-mail já cadastrado.")
    novo = models.Usuario(email=usuario.email, senha_hash=senha_hash(usuario.password), role=usuario.role)
    db.add(novo); db.flush()
    if usuario.role == "paciente":
        perfil = db.query(models.Paciente).filter(models.Paciente.email == usuario.email, models.Paciente.usuario_id.is_(None)).first()
    elif usuario.role == "medico":
        perfil = db.query(models.Medico).filter(models.Medico.email == usuario.email, models.Medico.usuario_id.is_(None)).first()
    else: perfil = None
    if perfil: perfil.usuario_id = novo.id
    db.commit(); db.refresh(novo)
    return novo


@app.post("/auth/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    usuario = db.query(models.Usuario).filter(models.Usuario.email == form_data.username).first()
    if not usuario or not verificar_senha(form_data.password, usuario.senha_hash): raise HTTPException(status_code=400, detail="E-mail ou senha incorretos.")
    return {"access_token": criar_token_acesso({"sub": usuario.email, "role": usuario.role}), "token_type": "bearer", "role": usuario.role}


@app.post("/auth/solicitar-recuperacao", status_code=status.HTTP_202_ACCEPTED)
def solicitar_recuperacao_senha(dados: schemas.RecuperacaoSenhaRequest, db: Session = Depends(get_db)):
    """Sempre responde de forma genérica para não revelar e-mails cadastrados."""
    usuario = db.query(models.Usuario).filter(models.Usuario.email == dados.email).first()
    if usuario:
        try:
            enviar_link_recuperacao(usuario.email, criar_token_recuperacao(usuario))
        except Exception:
            # Não expõe a falha do serviço de e-mail ao solicitante; registre no servidor.
            print("[RECUPERACAO DE SENHA] Não foi possível enviar o e-mail de recuperação.")
    return {"mensagem": "Se o e-mail estiver cadastrado, você receberá as instruções para redefinir sua senha."}


@app.post("/auth/redefinir-senha")
def redefinir_senha(dados: schemas.RedefinirSenhaRequest, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(dados.token, SECRET_KEY, algorithms=[ALGORITHM])
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="O link de recuperação é inválido ou expirou.")
    if payload.get("purpose") != "password_reset" or not payload.get("sub"):
        raise HTTPException(status_code=400, detail="O link de recuperação é inválido.")
    usuario = db.query(models.Usuario).filter(models.Usuario.email == payload["sub"]).first()
    if not usuario or payload.get("rv") != usuario.reset_version:
        raise HTTPException(status_code=400, detail="O link de recuperação é inválido.")
    usuario.senha_hash = senha_hash(dados.nova_senha)
    usuario.reset_version += 1
    db.commit()
    return {"mensagem": "Senha atualizada com sucesso. Faça login com a nova senha."}
