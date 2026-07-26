from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime, date
from typing import Optional

# --- SCHEMAS DE USUÁRIOS E AUTENTICAÇÃO (NOVO) ---
class UsuarioCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str # "admin", "medico", "paciente"

    @field_validator("role")
    @classmethod
    def validar_role(cls, value: str) -> str:
        if value not in {"admin", "medico", "paciente"}:
            raise ValueError("Perfil inválido.")
        return value

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

class RecuperacaoSenhaRequest(BaseModel):
    email: EmailStr

class RedefinirSenhaRequest(BaseModel):
    token: str = Field(min_length=20)
    nova_senha: str = Field(min_length=8, max_length=128)

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

    @field_validator("cpf")
    @classmethod
    def validar_cpf(cls, value: str) -> str:
        cpf = "".join(char for char in value if char.isdigit())
        if len(cpf) != 11 or len(set(cpf)) == 1:
            raise ValueError("CPF inválido.")
        return cpf

class PacienteResponse(PacienteCreate):
    id: int

    class Config:
        from_attributes = True


# --- SCHEMAS DE MÉDICOS ---
class MedicoCreate(BaseModel):
    nome: str
    especialidade: str
    duracao_consulta: int = Field(ge=10, le=240)
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
    nota_medico: int = Field(ge=1, le=5)
    comentario_paciente: Optional[str] = None
    nota_paciente: Optional[int] = Field(default=None, ge=1, le=5)
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
