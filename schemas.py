from pydantic import BaseModel, EmailStr
from datetime import datetime, date
from typing import Optional

# --- SCHEMAS DE USUÁRIOS E AUTENTICAÇÃO (NOVO) ---
class UsuarioCreate(BaseModel):
    email: EmailStr
    password: str
    role: str # "admin", "medico", "paciente"

class UsuarioResponse(BaseModel):
    id: int
    email: EmailStr
    role: str

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None

# --- SCHEMAS DE PACIENTES ---
class PacienteCreate(BaseModel):
    nome: str
    cpf: str
    telefone: str
    email: EmailStr
    data_nascimento: date
    endereco_rua: str
    endereco_numero: str
    endereco_bairro: str
    endereco_cidade: str
    endereco_estado: str
    endereco_cep: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class PacienteResponse(PacienteCreate):
    id: int

    class Config:
        from_attributes = True


# --- SCHEMAS DE MÉDICOS ---
class MedicoCreate(BaseModel):
    nome: str
    especialidade: str
    duracao_consulta: int
    crm: str
    email: EmailStr
    foto_perfil: Optional[str] = None
    endereco_rua: str
    endereco_numero: str
    endereco_bairro: str
    endereco_cidade: str
    endereco_estado: str
    endereco_cep: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class MedicoResponse(MedicoCreate):
    id: int
    avaliacao_media: float

    class Config:
        from_attributes = True


# --- SCHEMAS DE AGENDAMENTOS ---
class AgendamentoCreate(BaseModel):
    medico_id: int
    paciente_id: int
    data_hora: datetime

class AgendamentoResponse(AgendamentoCreate):
    id: int
    status: str

    class Config:
        from_attributes = True


# --- SCHEMAS DE EXAMES ---
# --- SCHEMAS DE AVALIAÇÕES ---
class AvaliacaoCreate(BaseModel):
    agendamento_id: int
    paciente_id: int
    medico_id: int
    nota_medico: int
    comentario_paciente: Optional[str] = None
    nota_paciente: Optional[int] = None
    comentario_medico: Optional[str] = None

class AvaliacaoResponse(AvaliacaoCreate):
    id: int

    class Config:
        from_attributes = True

class ExameCreate(BaseModel):
    paciente_id: int
    tipo_exame: str
    laboratorio: str
    data_hora: datetime
    resultado: Optional[str] = None  # Adicionado

class ExameResponse(ExameCreate):
    id: int
    status: str

    class Config:
        from_attributes = True