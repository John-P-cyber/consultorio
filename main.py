import math
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List

import models
import schemas
from database import SessionLocal, engine

from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
import jwt

# Configurações do JWT (Chave secreta para assinar as pulseiras virtuais)
SECRET_KEY = "sua_chave_secreta_super_segura_aqui"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

# Criptografia de senhas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Funções auxiliares de segurança
def obter_senha_criptografada(senha: str) -> str:
    return pwd_context.hash(senha)

def verificar_senha(senha_pura: str, senha_criptografada: str) -> bool:
    return pwd_context.verify(senha_pura, senha_criptografada)

def criar_token_acesso(dados: dict) -> str:
    dados_copia = dados.copy()
    expiracao = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    dados_copia.update({"exp": expiracao})
    return jwt.encode(dados_copia, SECRET_KEY, algorithm=ALGORITHM)

# Cria as tabelas na base de dados automaticamente se não existirem
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Clínica Inteligente - API")

# Configuração de CORS para permitir acesso do Live Server (Portas 5500, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependência para obter a sessão da base de dados
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- FUNÇÃO AUXILIAR: FÓRMULA DE HAVERSINE ---
def calcular_distancia(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula a distância em quilómetros entre duas coordenadas geográficas."""
    if None in (lat1, lon1, lat2, lon2):
        return 9999.0 # Distância padrão elevada caso falte alguma coordenada
    
    R = 6371.0  # Raio da Terra em km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ==========================================
# ROTAS DE PACIENTES
# ==========================================

@app.post("/pacientes/", response_model=schemas.PacienteResponse)
def criar_paciente(paciente: schemas.PacienteCreate, db: Session = Depends(get_db)):
    # Valida CPF único
    db_paciente = db.query(models.Paciente).filter(models.Paciente.cpf == paciente.cpf).first()
    if db_paciente:
        raise HTTPException(status_code=400, detail="CPF já cadastrado no sistema.")
    
    # Valida Email único
    db_email = db.query(models.Paciente).filter(models.Paciente.email == paciente.email).first()
    if db_email:
        raise HTTPException(status_code=400, detail="E-mail já registado no sistema.")

    novo_paciente = models.Paciente(**paciente.dict())
    db.add(novo_paciente)
    db.commit()
    db.refresh(novo_paciente)
    return novo_paciente

@app.get("/pacientes/", response_model=List[schemas.PacienteResponse])
def listar_pacientes(db: Session = Depends(get_db)):
    return db.query(models.Paciente).all()


# ==========================================
# ROTAS DE MÉDICOS
# ==========================================

@app.post("/medicos/", response_model=schemas.MedicoResponse)
def criar_medico(medico: schemas.MedicoCreate, db: Session = Depends(get_db)):
    db_crm = db.query(models.Medico).filter(models.Medico.crm == medico.crm).first()
    if db_crm:
        raise HTTPException(status_code=400, detail="CRM já registado.")

    novo_medico = models.Medico(**medico.dict())
    db.add(novo_medico)
    db.commit()
    db.refresh(novo_medico)
    return novo_medico

@app.get("/medicos/", response_model=List[schemas.MedicoResponse])
def listar_medicos(db: Session = Depends(get_db)):
    return db.query(models.Medico).all()

# NOVA ROTA: Recomendar médicos por Proximidade e Avaliação
@app.get("/medicos/recomendados")
def recomendar_medicos(latitude_paciente: float, longitude_paciente: float, db: Session = Depends(get_db)):
    medicos = db.query(models.Medico).all()
    
    lista_recomendada = []
    for m in medicos:
        distancia = calcular_distancia(latitude_paciente, longitude_paciente, m.latitude, m.longitude)
        lista_recomendada.append((m, distancia))
    
    # Ordena: 1º por melhor avaliação (decrescente), 2º por menor distância (crescente)
    lista_recomendada.sort(key=lambda x: (-x[0].avaliacao_media, x[1]))
    
    resultado = []
    for m, dist in lista_recomendada:
        resultado.append({
            "id": m.id,
            "nome": m.nome,
            "especialidade": m.especialidade,
            "crm": m.crm,
            "avaliacao_media": m.avaliacao_media,
            "distancia_km": round(dist, 2),
            "morada": f"{m.endereco_rua}, {m.endereco_numero} - {m.endereco_bairro}"
        })
    return resultado

# Buscar horários disponíveis de um médico num dia específico
@app.get("/medicos/{medico_id}/horarios-disponiveis")
def listar_horarios_disponiveis(medico_id: int, data: str, db: Session = Depends(get_db)):
    try:
        data_consulta = datetime.strptime(data, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use AAAA-MM-DD.")

    medico = db.query(models.Medico).filter(models.Medico.id == medico_id).first()
    if not medico:
        raise HTTPException(status_code=404, detail="Médico não encontrado.")

    duracao = medico.duracao_consulta
    horarios_possiveis = []

    # Manhã: 08:00 às 12:00
    hora_atual = datetime.combine(data_consulta, datetime.min.time().replace(hour=8))
    fim_manha = datetime.combine(data_consulta, datetime.min.time().replace(hour=12))
    while hora_atual + timedelta(minutes=duracao) <= fim_manha:
        horarios_possiveis.append(hora_atual)
        hora_atual += timedelta(minutes=duracao)

    # Tarde: 13:00 às 18:00
    hora_atual = datetime.combine(data_consulta, datetime.min.time().replace(hour=13))
    fim_tarde = datetime.combine(data_consulta, datetime.min.time().replace(hour=18))
    while hora_atual + timedelta(minutes=duracao) <= fim_tarde:
        horarios_possiveis.append(hora_atual)
        hora_atual += timedelta(minutes=duracao)

    # Agendamentos ocupados no dia (excluindo os cancelados)
    inicio_dia = datetime.combine(data_consulta, datetime.min.time().replace(hour=0, minute=0))
    fim_dia = datetime.combine(data_consulta, datetime.min.time().replace(hour=23, minute=59))
    
    agendamentos_ocupados = db.query(models.Agendamento).filter(
        models.Agendamento.medico_id == medico_id,
        models.Agendamento.data_hora >= inicio_dia,
        models.Agendamento.data_hora <= fim_dia,
        models.Agendamento.status != "Cancelado"
    ).all()

    horas_ocupadas = [ag.data_hora for ag in agendamentos_ocupados]

    horarios_livres = []
    for hp in horarios_possiveis:
        if hp not in horas_ocupadas:
            horarios_livres.append(hp.strftime("%H:%M"))

    return horarios_livres


# ==========================================
# ROTAS DE AGENDAMENTOS
# ==========================================

@app.post("/agendamentos/", response_model=schemas.AgendamentoResponse)
def criar_agendamento(agendamento: schemas.AgendamentoCreate, db: Session = Depends(get_db)):
    medico = db.query(models.Medico).filter(models.Medico.id == agendamento.medico_id).first()
    if not medico:
        raise HTTPException(status_code=404, detail="Médico não encontrado.")

    paciente = db.query(models.Paciente).filter(models.Paciente.id == agendamento.paciente_id).first()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")

    novo_agendamento = models.Agendamento(**agendamento.dict())
    db.add(novo_agendamento)
    db.commit()
    db.refresh(novo_agendamento)
    return novo_agendamento

@app.get("/agendamentos/")
def listar_agendamentos(db: Session = Depends(get_db)):
    return db.query(models.Agendamento).all()

# Atualizar estado de uma consulta (Confirmado, Atendido, Cancelado)
@app.patch("/agendamentos/{agendamento_id}/status", response_model=schemas.AgendamentoResponse)
def atualizar_status_agendamento(agendamento_id: int, status_novo: str, db: Session = Depends(get_db)):
    agendamento = db.query(models.Agendamento).filter(models.Agendamento.id == agendamento_id).first()
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")
    
    if status_novo not in ["Confirmado", "Atendido", "Cancelado"]:
        raise HTTPException(status_code=400, detail="Estado inválido.")
        
    agendamento.status = status_novo
    db.commit()
    db.refresh(agendamento)
    return agendamento

@app.delete("/agendamentos/{agendamento_id}")
def cancelar_agendamento(agendamento_id: int, db: Session = Depends(get_db)):
    agendamento = db.query(models.Agendamento).filter(models.Agendamento.id == agendamento_id).first()
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")
    db.delete(agendamento)
    db.commit()
    return {"mensagem": "Consulta removida com sucesso!"}


# ==========================================
# ROTAS DE EXAMES (NOVO)
# ==========================================

@app.post("/exames/", response_model=schemas.ExameResponse)
def criar_exame(exame: schemas.ExameCreate, db: Session = Depends(get_db)):
    novo_exame = models.Exame(**exame.dict())
    db.add(novo_exame)
    db.commit()
    db.refresh(novo_exame)
    return novo_exame

@app.get("/exames/", response_model=List[schemas.ExameResponse])
def listar_exames(db: Session = Depends(get_db)):
    return db.query(models.Exame).all()

@app.patch("/exames/{exame_id}/status", response_model=schemas.ExameResponse)
def atualizar_status_exame(exame_id: int, status_novo: str, db: Session = Depends(get_db)):
    exame = db.query(models.Exame).filter(models.Exame.id == exame_id).first()
    if not exame:
        raise HTTPException(status_code=404, detail="Exame não encontrado.")
    exame.status = status_novo
    db.commit()
    db.refresh(exame)
    return exame


# ==========================================
# ROTAS DE AVALIAÇÕES (NOVO)
# ==========================================

@app.post("/avaliacoes/", response_model=schemas.AvaliacaoResponse)
def criar_avaliacao(avaliacao: schemas.AvaliacaoCreate, db: Session = Depends(get_db)):
    # 1. Verifica se já existe algum registo para esta consulta específica
    db_avaliacao = db.query(models.Avaliacao).filter(models.Avaliacao.agendamento_id == avaliacao.agendamento_id).first()
    
    if db_avaliacao:
        # 2. Se já existir, o Python FUNDE os dados (atualiza o texto do médico)
        db_avaliacao.comentario_medico = avaliacao.comentario_medico
        db_avaliacao.nota_paciente = avaliacao.nota_paciente
        db.commit()
        db.refresh(db_avaliacao)
        return db_avaliacao
    else:
        # 3. Se a consulta estiver "limpa", cria um registo novo do zero
        nova_avaliacao = models.Avaliacao(**avaliacao.dict())
        db.add(nova_avaliacao)
        db.commit()
        db.refresh(nova_avaliacao)
        return nova_avaliacao


@app.get("/avaliacoes/", response_model=list[schemas.AvaliacaoResponse])
def listar_avaliacoes(db: Session = Depends(get_db)):
    return db.query(models.Avaliacao).all()


# ==========================================
# ROTAS DE AUTENTICAÇÃO (SISTEMA DE LOGIN)
# ==========================================

@app.post("/auth/registrar", response_model=schemas.UsuarioResponse)
def registrar_usuario(usuario: schemas.UsuarioCreate, db: Session = Depends(get_db)):
    # Verifica se o e-mail já existe
    usuario_existente = db.query(models.Usuario).filter(models.Usuario.email == usuario.email).first()
    if usuario_existente:
        raise HTTPException(status_code=400, detail="E-mail já cadastrado.")

    # Criptografa a senha antes de salvar no banco
    senha_segura = obter_senha_criptografada(usuario.password)
    
    novo_usuario = models.Usuario(
        email=usuario.email,
        senha_hash=senha_segura,
        role=usuario.role
    )
    db.add(novo_usuario)
    db.commit()
    db.refresh(novo_usuario)
    return novo_usuario


@app.post("/auth/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # 1. Procura o usuário pelo e-mail (enviado no campo username do form)
    usuario = db.query(models.Usuario).filter(models.Usuario.email == form_data.username).first()
    if not usuario:
        raise HTTPException(status_code=400, detail="E-mail ou senha incorretos.")

    # 2. Verifica se a senha está correta
    if not verificar_senha(form_data.password, usuario.senha_hash):
        raise HTTPException(status_code=400, detail="E-mail ou senha incorretos.")

    # 3. Se estiver tudo certo, gera o Token com os dados dele
    token_acesso = criar_token_acesso(dados={"sub": usuario.email, "role": usuario.role})
    
    return {
        "access_token": token_acesso,
        "token_type": "bearer",
        "role": usuario.role
    }