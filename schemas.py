from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def normalizar_cpf(value: str) -> str:
    cpf = "".join(char for char in value if char.isdigit())
    if len(cpf) != 11 or len(set(cpf)) == 1:
        raise ValueError("CPF inválido.")
    for tamanho in (9, 10):
        soma = sum(int(cpf[indice]) * (tamanho + 1 - indice) for indice in range(tamanho))
        digito = (soma * 10 % 11) % 10
        if digito != int(cpf[tamanho]):
            raise ValueError("CPF inválido.")
    return cpf


def validar_senha_forte(value: str) -> str:
    if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
        raise ValueError("A senha deve conter letras e números.")
    return value


def normalizar_slug(value: str) -> str:
    slug = value.strip().lower()
    if not slug or len(slug) > 80:
        raise ValueError("O código da clínica deve ter entre 1 e 80 caracteres.")
    if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in slug):
        raise ValueError("Use apenas letras minúsculas, números e hífen no código da clínica.")
    if slug.startswith("-") or slug.endswith("-") or "--" in slug:
        raise ValueError("Código de clínica inválido.")
    return slug


class ClinicaProvisionamento(BaseModel):
    nome: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=1, max_length=80)
    email_admin: EmailStr
    password: str = Field(min_length=8, max_length=128)
    provisioning_token: str = Field(min_length=1, max_length=512)
    aceita_termos: bool
    ciente_privacidade: bool
    termos_versao: str = Field(min_length=1, max_length=40)
    privacidade_versao: str = Field(min_length=1, max_length=40)

    @field_validator("slug")
    @classmethod
    def validar_slug(cls, value: str) -> str:
        return normalizar_slug(value)

    @field_validator("password")
    @classmethod
    def senha_forte(cls, value: str) -> str:
        return validar_senha_forte(value)


class ClinicaResponse(BaseModel):
    id: int
    nome: str
    slug: str
    ativo: bool

    model_config = ConfigDict(from_attributes=True)


class UsuarioCreate(BaseModel):
    clinica_slug: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str
    aceita_termos: bool
    ciente_privacidade: bool
    termos_versao: str = Field(min_length=1, max_length=40)
    privacidade_versao: str = Field(min_length=1, max_length=40)
    nome: Optional[str] = None
    cpf: Optional[str] = None
    telefone: Optional[str] = None
    data_nascimento: Optional[date] = None
    endereco_rua: Optional[str] = None
    endereco_numero: Optional[str] = None
    endereco_bairro: Optional[str] = None
    endereco_cidade: Optional[str] = None
    endereco_estado: Optional[str] = None
    endereco_cep: Optional[str] = None
    especialidade: Optional[str] = None
    duracao_consulta: Optional[int] = Field(default=None, ge=10, le=240)
    crm: Optional[str] = None

    @field_validator("clinica_slug")
    @classmethod
    def validar_clinica_slug(cls, value: str) -> str:
        return normalizar_slug(value)

    @field_validator("role")
    @classmethod
    def validar_role(cls, value: str) -> str:
        if value not in {"admin", "medico", "paciente"}:
            raise ValueError("Perfil inválido.")
        return value

    @field_validator("password")
    @classmethod
    def senha_forte(cls, value: str) -> str:
        return validar_senha_forte(value)

    @field_validator("cpf")
    @classmethod
    def validar_cpf(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return normalizar_cpf(value)


class UsuarioResponse(BaseModel):
    id: int
    email: EmailStr
    role: str

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    autenticado: bool
    role: str
    clinica_slug: str
    clinica_nome: str
    mfa_required: bool = False
    mfa_setup_required: bool = False
    recovery_codes: list[str] = Field(default_factory=list)


class SessaoAtualResponse(BaseModel):
    usuario_id: int
    email: EmailStr
    role: str
    clinica_id: int
    clinica_slug: str
    clinica_nome: str
    sessao_id: str
    mfa_ativo: bool
    mfa_verificada: bool


class MfaCodigoRequest(BaseModel):
    codigo: str = Field(min_length=6, max_length=32)


class MfaSetupResponse(BaseModel):
    segredo: str
    uri_otpauth: str
    emissor: str
    conta: str


class MfaRegenerarRequest(MfaCodigoRequest):
    senha: str = Field(min_length=1, max_length=128)


class MfaCodigosResponse(BaseModel):
    recovery_codes: list[str]


class SessaoResponse(BaseModel):
    id: str
    criado_em: datetime
    ultimo_uso_em: datetime
    expira_em: datetime
    mfa_verificada: bool
    atual: bool


class MensagemResponse(BaseModel):
    mensagem: str


class TokenData(BaseModel):
    usuario_id: Optional[int] = None
    clinica_id: Optional[int] = None
    role: Optional[str] = None


class UsuarioGerenciadoCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str

    @field_validator("role")
    @classmethod
    def validar_role(cls, value: str) -> str:
        if value not in {"admin", "medico"}:
            raise ValueError("A administração só pode criar contas administrativas ou médicas.")
        return value

    @field_validator("password")
    @classmethod
    def senha_forte(cls, value: str) -> str:
        return validar_senha_forte(value)


class RecuperacaoSenhaRequest(BaseModel):
    clinica_slug: str
    email: EmailStr

    @field_validator("clinica_slug")
    @classmethod
    def validar_clinica_slug(cls, value: str) -> str:
        return normalizar_slug(value)


class RedefinirSenhaRequest(BaseModel):
    token: str = Field(min_length=20)
    nova_senha: str = Field(min_length=8, max_length=128)

    @field_validator("nova_senha")
    @classmethod
    def senha_forte(cls, value: str) -> str:
        return validar_senha_forte(value)


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
        return normalizar_cpf(value)


class PacienteResponse(PacienteCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class PacienteResumo(BaseModel):
    id: int
    nome: str
    telefone: str

    model_config = ConfigDict(from_attributes=True)


class PacienteUpdate(BaseModel):
    nome: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[EmailStr] = None
    data_nascimento: Optional[date] = None
    endereco_rua: Optional[str] = None
    endereco_numero: Optional[str] = None
    endereco_bairro: Optional[str] = None
    endereco_cidade: Optional[str] = None
    endereco_estado: Optional[str] = None
    endereco_cep: Optional[str] = None
    cpf: Optional[str] = None

    @field_validator("cpf")
    @classmethod
    def validar_cpf(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return normalizar_cpf(value)


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

    model_config = ConfigDict(from_attributes=True)


class MedicoUpdate(BaseModel):
    nome: Optional[str] = None
    especialidade: Optional[str] = None
    duracao_consulta: Optional[int] = Field(default=None, ge=10, le=240)
    email: Optional[EmailStr] = None
    foto_perfil: Optional[str] = None
    endereco_rua: Optional[str] = None
    endereco_numero: Optional[str] = None
    endereco_bairro: Optional[str] = None
    endereco_cidade: Optional[str] = None
    endereco_estado: Optional[str] = None
    endereco_cep: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    crm: Optional[str] = None


class AgendamentoCreate(BaseModel):
    medico_id: int
    paciente_id: int
    data_hora: datetime


class AgendamentoResponse(AgendamentoCreate):
    id: int
    status: str

    model_config = ConfigDict(from_attributes=True)


class AvaliacaoCreate(BaseModel):
    agendamento_id: int
    paciente_id: int
    medico_id: int
    nota_medico: int = Field(ge=1, le=5)
    comentario_paciente: Optional[str] = Field(default=None, max_length=2000)


class AvaliacaoResponse(AvaliacaoCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


TIPOS_PRONTUARIO = {"evolucao", "anamnese", "diagnostico", "procedimento", "observacao"}


class ProntuarioCreate(BaseModel):
    paciente_id: int
    agendamento_id: Optional[int] = None
    tipo: str = "evolucao"
    conteudo: str = Field(min_length=10, max_length=100000)
    senha_assinatura: str = Field(min_length=1, max_length=128)

    @field_validator("tipo")
    @classmethod
    def validar_tipo(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in TIPOS_PRONTUARIO:
            raise ValueError("Tipo de registro clínico inválido.")
        return value

    @field_validator("conteudo")
    @classmethod
    def normalizar_conteudo(cls, value: str) -> str:
        return value.strip()


class ProntuarioVersaoCreate(BaseModel):
    conteudo: str = Field(min_length=10, max_length=100000)
    motivo_retificacao: str = Field(min_length=5, max_length=500)
    senha_assinatura: str = Field(min_length=1, max_length=128)

    @field_validator("conteudo", "motivo_retificacao")
    @classmethod
    def normalizar_texto(cls, value: str) -> str:
        return value.strip()


class AnexoProntuarioResponse(BaseModel):
    id: int
    prontuario_id: int
    nome_original: str
    tipo_mime: str
    tamanho_bytes: int
    arquivo_hash: str
    origem: str
    conferencia: str
    criado_em: datetime

    model_config = ConfigDict(from_attributes=True)


class ProntuarioResponse(BaseModel):
    id: int
    serie_id: str
    versao: int
    versao_anterior_id: Optional[int] = None
    paciente_id: int
    medico_id: int
    agendamento_id: Optional[int] = None
    autor_nome: str
    autor_crm: str
    tipo: str
    conteudo: str
    motivo_retificacao: Optional[str] = None
    criado_em: datetime
    assinado_em: Optional[datetime] = None
    assinatura_tipo: str
    documento_hash: str
    assinatura_hash: Optional[str] = None
    anexos: list[AnexoProntuarioResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ItemPrescricaoCreate(BaseModel):
    medicamento: str = Field(min_length=2, max_length=200)
    concentracao: Optional[str] = Field(default=None, max_length=100)
    forma_farmaceutica: Optional[str] = Field(default=None, max_length=100)
    dose: str = Field(min_length=1, max_length=200)
    via: str = Field(min_length=1, max_length=100)
    frequencia: str = Field(min_length=1, max_length=200)
    duracao: str = Field(min_length=1, max_length=200)
    orientacoes: Optional[str] = Field(default=None, max_length=5000)


class ItemPrescricaoResponse(ItemPrescricaoCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class EventoPrescricaoResponse(BaseModel):
    id: int
    tipo: str
    motivo: str
    criado_em: datetime
    documento_hash: str
    assinatura_hash: str

    model_config = ConfigDict(from_attributes=True)


class PrescricaoCreate(BaseModel):
    paciente_id: int
    prontuario_id: Optional[int] = None
    observacoes: Optional[str] = Field(default=None, max_length=5000)
    itens: list[ItemPrescricaoCreate] = Field(min_length=1, max_length=20)
    senha_assinatura: str = Field(min_length=1, max_length=128)


class PrescricaoResponse(BaseModel):
    id: int
    prontuario_id: Optional[int] = None
    paciente_id: int
    medico_id: int
    autor_nome: str
    autor_crm: str
    observacoes: Optional[str] = None
    criado_em: datetime
    assinado_em: datetime
    assinatura_tipo: str
    documento_hash: str
    assinatura_hash: str
    itens: list[ItemPrescricaoResponse]
    eventos: list[EventoPrescricaoResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class CancelamentoPrescricaoCreate(BaseModel):
    motivo: str = Field(min_length=5, max_length=500)
    senha_assinatura: str = Field(min_length=1, max_length=128)

    @field_validator("motivo")
    @classmethod
    def normalizar_motivo(cls, value: str) -> str:
        return value.strip()


class ExameCreate(BaseModel):
    paciente_id: int
    tipo_exame: str
    laboratorio: str
    data_hora: datetime


class ExameResponse(ExameCreate):
    id: int
    status: str
    resultado: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ExameResultadoUpdate(BaseModel):
    resultado: str = Field(min_length=1, max_length=20000)


class DocumentoLGPDResponse(BaseModel):
    termos_versao: str
    privacidade_versao: str
    termos_url: str
    privacidade_url: str
    retencao_prontuario_anos: int
    observacao_retencao: str


class AceiteDocumentosLGPDCreate(BaseModel):
    aceita_termos: bool
    ciente_privacidade: bool
    termos_versao: str = Field(min_length=1, max_length=40)
    privacidade_versao: str = Field(min_length=1, max_length=40)


class ConsentimentoComunicacoesCreate(BaseModel):
    finalidade: str = Field(
        default="Receber lembretes e comunicações não essenciais da clínica.",
        min_length=10,
        max_length=500,
    )


class ConsentimentoResponse(BaseModel):
    id: int
    documento_tipo: str
    versao: str
    finalidade: str
    base_legal: str
    aceito_em: datetime
    revogado_em: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class RegistroAuditoriaResponse(BaseModel):
    id: int
    ator_usuario_id: Optional[int] = None
    ator_referencia: str
    ator_role: str
    acao: str
    recurso: str
    registro_id: Optional[int] = None
    paciente_id: Optional[int] = None
    campos: Optional[str] = None
    detalhes: Optional[str] = None
    endereco_ip: Optional[str] = None
    criado_em: datetime
    assinatura: str

    model_config = ConfigDict(from_attributes=True)


class SolicitacaoLGPDCreate(BaseModel):
    tipo: str
    justificativa: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("tipo")
    @classmethod
    def validar_tipo(cls, value: str) -> str:
        if value not in {"anonimizacao", "exclusao", "correcao"}:
            raise ValueError("Tipo de solicitação inválido.")
        return value


class SolicitacaoLGPDProcessar(BaseModel):
    decisao: str
    observacao: str = Field(min_length=5, max_length=2000)

    @field_validator("decisao")
    @classmethod
    def validar_decisao(cls, value: str) -> str:
        if value not in {"aprovar", "rejeitar"}:
            raise ValueError("A decisão deve ser aprovar ou rejeitar.")
        return value


class SolicitacaoLGPDResponse(BaseModel):
    id: int
    paciente_id: Optional[int] = None
    tipo: str
    status: str
    justificativa: Optional[str] = None
    solicitado_em: datetime
    processado_em: Optional[datetime] = None
    decisao_observacao: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
