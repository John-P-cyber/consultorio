from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import event
from sqlalchemy.orm import relationship

from database import Base


class Clinica(Base):
    __tablename__ = "clinicas"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(160), nullable=False)
    slug = Column(String(80), nullable=False, unique=True, index=True)
    ativo = Column(Boolean, nullable=False, default=True)

    usuarios = relationship("Usuario", back_populates="clinica")
    pacientes = relationship("Paciente", back_populates="clinica")
    medicos = relationship("Medico", back_populates="clinica")
    agendamentos = relationship("Agendamento", back_populates="clinica")
    exames = relationship("Exame", back_populates="clinica")
    avaliacoes = relationship("Avaliacao", back_populates="clinica")
    prontuarios = relationship("ProntuarioEntrada", back_populates="clinica")
    anexos_prontuario = relationship("AnexoProntuario", back_populates="clinica")
    prescricoes = relationship("Prescricao", back_populates="clinica")
    registros_auditoria = relationship("RegistroAuditoria", back_populates="clinica")
    consentimentos = relationship("Consentimento", back_populates="clinica")
    solicitacoes_lgpd = relationship("SolicitacaoLGPD", back_populates="clinica")
    sessoes = relationship("SessaoUsuario", back_populates="clinica")
    codigos_recuperacao_mfa = relationship("MfaCodigoRecuperacao", back_populates="clinica")


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    email = Column(String, index=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin", "medico", "paciente"
    reset_version = Column(Integer, nullable=False, default=0)
    ativo = Column(Boolean, nullable=False, default=True)
    mfa_ativo = Column(Boolean, nullable=False, default=False)
    mfa_secret_salt = Column(String(64), nullable=True)
    mfa_ultimo_contador = Column(Integer, nullable=True)
    mfa_falhas = Column(Integer, nullable=False, default=0)
    mfa_bloqueado_ate = Column(DateTime(timezone=True), nullable=True)
    mfa_ativado_em = Column(DateTime(timezone=True), nullable=True)

    clinica = relationship("Clinica", back_populates="usuarios")
    paciente = relationship("Paciente", back_populates="usuario", uselist=False)
    medico = relationship("Medico", back_populates="usuario", uselist=False)
    consentimentos = relationship("Consentimento", back_populates="usuario")
    sessoes = relationship("SessaoUsuario", back_populates="usuario", cascade="all, delete-orphan")
    codigos_recuperacao_mfa = relationship(
        "MfaCodigoRecuperacao", back_populates="usuario", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'medico', 'paciente')", name="ck_usuarios_role"),
        UniqueConstraint("clinica_id", "email", name="uq_usuarios_clinica_email"),
    )


class SessaoUsuario(Base):
    __tablename__ = "sessoes_usuario"

    id = Column(String(36), primary_key=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    familia_id = Column(String(36), nullable=False, index=True)
    refresh_token_hash = Column(String(64), nullable=False, unique=True)
    rotacao = Column(Integer, nullable=False, default=0)
    criado_em = Column(DateTime(timezone=True), nullable=False)
    ultimo_uso_em = Column(DateTime(timezone=True), nullable=False)
    expira_em = Column(DateTime(timezone=True), nullable=False, index=True)
    revogado_em = Column(DateTime(timezone=True), nullable=True, index=True)
    motivo_revogacao = Column(String(80), nullable=True)
    ip_criacao_hash = Column(String(64), nullable=True)
    ip_ultimo_hash = Column(String(64), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
    mfa_verificada = Column(Boolean, nullable=False, default=False)

    clinica = relationship("Clinica", back_populates="sessoes")
    usuario = relationship("Usuario", back_populates="sessoes")

    __table_args__ = (
        Index("ix_sessoes_usuario_ativas", "clinica_id", "usuario_id", "revogado_em", "expira_em"),
        CheckConstraint("rotacao >= 0", name="ck_sessao_rotacao_nao_negativa"),
    )


class MfaCodigoRecuperacao(Base):
    __tablename__ = "mfa_codigos_recuperacao"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    codigo_hash = Column(String(64), nullable=False, unique=True)
    criado_em = Column(DateTime(timezone=True), nullable=False)
    usado_em = Column(DateTime(timezone=True), nullable=True, index=True)

    clinica = relationship("Clinica", back_populates="codigos_recuperacao_mfa")
    usuario = relationship("Usuario", back_populates="codigos_recuperacao_mfa")

    __table_args__ = (
        Index("ix_mfa_codigos_usuario_disponiveis", "clinica_id", "usuario_id", "usado_em"),
    )


class Paciente(Base):
    __tablename__ = "pacientes"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), unique=True, nullable=True)
    nome = Column(String, nullable=False)
    cpf = Column(String, index=True, nullable=False)
    telefone = Column(String, nullable=False)
    email = Column(String, index=True, nullable=False)
    data_nascimento = Column(Date, nullable=False)

    endereco_rua = Column(String, nullable=False)
    endereco_numero = Column(String, nullable=False)
    endereco_bairro = Column(String, nullable=False)
    endereco_cidade = Column(String, nullable=False)
    endereco_estado = Column(String, nullable=False)
    endereco_cep = Column(String, nullable=False)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    anonimizado_em = Column(DateTime(timezone=True), nullable=True)

    clinica = relationship("Clinica", back_populates="pacientes")
    usuario = relationship("Usuario", back_populates="paciente")
    agendamentos = relationship("Agendamento", back_populates="paciente")
    exames = relationship("Exame", back_populates="paciente")
    avaliacoes = relationship("Avaliacao", back_populates="paciente")
    prontuarios = relationship("ProntuarioEntrada", back_populates="paciente")
    prescricoes = relationship("Prescricao", back_populates="paciente")
    consentimentos = relationship("Consentimento", back_populates="paciente")
    solicitacoes_lgpd = relationship("SolicitacaoLGPD", back_populates="paciente")

    __table_args__ = (
        UniqueConstraint("clinica_id", "cpf", name="uq_pacientes_clinica_cpf"),
        UniqueConstraint("clinica_id", "email", name="uq_pacientes_clinica_email"),
    )


class Medico(Base):
    __tablename__ = "medicos"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), unique=True, nullable=True)
    nome = Column(String, nullable=False)
    especialidade = Column(String, nullable=False)
    duracao_consulta = Column(Integer, default=30)
    crm = Column(String, index=True, nullable=False)
    email = Column(String, index=True, nullable=False)
    foto_perfil = Column(String, nullable=True)

    endereco_rua = Column(String, nullable=False)
    endereco_numero = Column(String, nullable=False)
    endereco_bairro = Column(String, nullable=False)
    endereco_cidade = Column(String, nullable=False)
    endereco_estado = Column(String, nullable=False)
    endereco_cep = Column(String, nullable=False)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    avaliacao_media = Column(Float, default=0.0)

    clinica = relationship("Clinica", back_populates="medicos")
    usuario = relationship("Usuario", back_populates="medico")
    agendamentos = relationship("Agendamento", back_populates="medico")
    avaliacoes = relationship("Avaliacao", back_populates="medico")
    prontuarios = relationship("ProntuarioEntrada", back_populates="medico")
    prescricoes = relationship("Prescricao", back_populates="medico")

    __table_args__ = (
        UniqueConstraint("clinica_id", "crm", name="uq_medicos_clinica_crm"),
        UniqueConstraint("clinica_id", "email", name="uq_medicos_clinica_email"),
    )


class Agendamento(Base):
    __tablename__ = "agendamentos"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    medico_id = Column(Integer, ForeignKey("medicos.id"), nullable=False)
    data_hora = Column(DateTime, nullable=False)
    status = Column(String, default="Confirmado")

    clinica = relationship("Clinica", back_populates="agendamentos")
    paciente = relationship("Paciente", back_populates="agendamentos")
    medico = relationship("Medico", back_populates="agendamentos")
    avaliacao = relationship("Avaliacao", uselist=False, back_populates="agendamento")
    prontuarios = relationship("ProntuarioEntrada", back_populates="agendamento")

    __table_args__ = (
        CheckConstraint("status IN ('Confirmado', 'Atendido', 'Cancelado')", name="ck_agendamentos_status"),
        Index(
            "uq_agendamento_clinica_medico_horario_ativo",
            "clinica_id",
            "medico_id",
            "data_hora",
            unique=True,
            postgresql_where=text("status <> 'Cancelado'"),
            sqlite_where=text("status <> 'Cancelado'"),
        ),
    )


class Exame(Base):
    __tablename__ = "exames"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    tipo_exame = Column(String, nullable=False)
    data_hora = Column(DateTime, nullable=False)
    laboratorio = Column(String, nullable=False)
    status = Column(String, default="Pendente")
    resultado = Column(String, nullable=True)

    clinica = relationship("Clinica", back_populates="exames")
    paciente = relationship("Paciente", back_populates="exames")

    __table_args__ = (CheckConstraint("status IN ('Pendente', 'Concluído', 'Cancelado')", name="ck_exames_status"),)


class Avaliacao(Base):
    __tablename__ = "avaliacoes"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    agendamento_id = Column(Integer, ForeignKey("agendamentos.id"), unique=True, nullable=False)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    medico_id = Column(Integer, ForeignKey("medicos.id"), nullable=False)

    nota_medico = Column(Integer, nullable=True)
    comentario_paciente = Column(String, nullable=True)

    clinica = relationship("Clinica", back_populates="avaliacoes")
    agendamento = relationship("Agendamento", back_populates="avaliacao")
    paciente = relationship("Paciente", back_populates="avaliacoes")
    medico = relationship("Medico", back_populates="avaliacoes")

    __table_args__ = (
        CheckConstraint("nota_medico IS NULL OR (nota_medico BETWEEN 1 AND 5)", name="ck_avaliacoes_nota_medico"),
    )


class ProntuarioEntrada(Base):
    """Versão clínica assinada e imutável; retificações criam uma nova linha."""

    __tablename__ = "prontuario_entradas"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    serie_id = Column(String(36), nullable=False, index=True)
    versao = Column(Integer, nullable=False)
    versao_anterior_id = Column(Integer, ForeignKey("prontuario_entradas.id", ondelete="RESTRICT"), nullable=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id", ondelete="RESTRICT"), nullable=False, index=True)
    medico_id = Column(Integer, ForeignKey("medicos.id", ondelete="RESTRICT"), nullable=False, index=True)
    agendamento_id = Column(Integer, ForeignKey("agendamentos.id", ondelete="SET NULL"), nullable=True, index=True)
    autor_usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    autor_nome = Column(String(160), nullable=False)
    autor_crm = Column(String(80), nullable=False)
    tipo = Column(String(30), nullable=False)
    conteudo = Column(Text, nullable=False)
    motivo_retificacao = Column(String(500), nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False)
    assinado_em = Column(DateTime(timezone=True), nullable=True)
    assinatura_tipo = Column(String(40), nullable=False)
    documento_hash = Column(String(64), nullable=False, unique=True)
    assinatura_hash = Column(String(64), nullable=True, unique=True)

    clinica = relationship("Clinica", back_populates="prontuarios")
    paciente = relationship("Paciente", back_populates="prontuarios")
    medico = relationship("Medico", back_populates="prontuarios")
    agendamento = relationship("Agendamento", back_populates="prontuarios")
    versao_anterior = relationship("ProntuarioEntrada", remote_side=[id], uselist=False)
    anexos = relationship("AnexoProntuario", back_populates="prontuario", order_by="AnexoProntuario.id")
    prescricoes = relationship("Prescricao", back_populates="prontuario", order_by="Prescricao.id")

    __table_args__ = (
        UniqueConstraint("clinica_id", "serie_id", "versao", name="uq_prontuario_serie_versao"),
        CheckConstraint("versao >= 1", name="ck_prontuario_versao_positiva"),
        CheckConstraint(
            "tipo IN ('evolucao', 'anamnese', 'diagnostico', 'procedimento', 'observacao')",
            name="ck_prontuario_tipo",
        ),
        CheckConstraint(
            "assinatura_tipo IN ('interna_reautenticada', 'migrado_sem_assinatura')",
            name="ck_prontuario_assinatura_tipo",
        ),
        Index("ix_prontuario_paciente_criado", "clinica_id", "paciente_id", "criado_em"),
    )


class AnexoProntuario(Base):
    __tablename__ = "anexos_prontuario"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    prontuario_id = Column(Integer, ForeignKey("prontuario_entradas.id", ondelete="RESTRICT"), nullable=False, index=True)
    enviado_por_usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    nome_original = Column(String(255), nullable=False)
    tipo_mime = Column(String(100), nullable=False)
    tamanho_bytes = Column(Integer, nullable=False)
    arquivo_hash = Column(String(64), nullable=False)
    caminho_armazenamento = Column(String(500), nullable=False, unique=True)
    origem = Column(String(20), nullable=False)
    conferencia = Column(String(30), nullable=False)
    criado_em = Column(DateTime(timezone=True), nullable=False)

    clinica = relationship("Clinica", back_populates="anexos_prontuario")
    prontuario = relationship("ProntuarioEntrada", back_populates="anexos")

    __table_args__ = (
        CheckConstraint("tamanho_bytes > 0", name="ck_anexo_tamanho_positivo"),
        CheckConstraint("origem IN ('nato_digital', 'digitalizado')", name="ck_anexo_origem"),
        CheckConstraint(
            "conferencia IN ('original', 'copia_simples', 'copia_conferida')",
            name="ck_anexo_conferencia",
        ),
    )


class Prescricao(Base):
    __tablename__ = "prescricoes"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    prontuario_id = Column(Integer, ForeignKey("prontuario_entradas.id", ondelete="RESTRICT"), nullable=True, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id", ondelete="RESTRICT"), nullable=False, index=True)
    medico_id = Column(Integer, ForeignKey("medicos.id", ondelete="RESTRICT"), nullable=False, index=True)
    autor_usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    autor_nome = Column(String(160), nullable=False)
    autor_crm = Column(String(80), nullable=False)
    observacoes = Column(Text, nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False)
    assinado_em = Column(DateTime(timezone=True), nullable=False)
    assinatura_tipo = Column(String(40), nullable=False, default="interna_reautenticada")
    documento_hash = Column(String(64), nullable=False, unique=True)
    assinatura_hash = Column(String(64), nullable=False, unique=True)

    clinica = relationship("Clinica", back_populates="prescricoes")
    prontuario = relationship("ProntuarioEntrada", back_populates="prescricoes")
    paciente = relationship("Paciente", back_populates="prescricoes")
    medico = relationship("Medico", back_populates="prescricoes")
    itens = relationship("ItemPrescricao", back_populates="prescricao", order_by="ItemPrescricao.id")
    eventos = relationship("EventoPrescricao", back_populates="prescricao", order_by="EventoPrescricao.id")

    __table_args__ = (
        CheckConstraint("assinatura_tipo = 'interna_reautenticada'", name="ck_prescricao_assinatura_tipo"),
    )


class ItemPrescricao(Base):
    __tablename__ = "itens_prescricao"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    prescricao_id = Column(Integer, ForeignKey("prescricoes.id", ondelete="RESTRICT"), nullable=False, index=True)
    medicamento = Column(String(200), nullable=False)
    concentracao = Column(String(100), nullable=True)
    forma_farmaceutica = Column(String(100), nullable=True)
    dose = Column(String(200), nullable=False)
    via = Column(String(100), nullable=False)
    frequencia = Column(String(200), nullable=False)
    duracao = Column(String(200), nullable=False)
    orientacoes = Column(Text, nullable=True)

    prescricao = relationship("Prescricao", back_populates="itens")


class EventoPrescricao(Base):
    __tablename__ = "eventos_prescricao"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    prescricao_id = Column(Integer, ForeignKey("prescricoes.id", ondelete="RESTRICT"), nullable=False, index=True)
    autor_usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    tipo = Column(String(30), nullable=False)
    motivo = Column(String(500), nullable=False)
    criado_em = Column(DateTime(timezone=True), nullable=False)
    documento_hash = Column(String(64), nullable=False, unique=True)
    assinatura_hash = Column(String(64), nullable=False, unique=True)

    prescricao = relationship("Prescricao", back_populates="eventos")

    __table_args__ = (
        CheckConstraint("tipo = 'cancelamento'", name="ck_evento_prescricao_tipo"),
        UniqueConstraint("prescricao_id", "tipo", name="uq_prescricao_evento_tipo"),
    )


class RegistroAuditoria(Base):
    __tablename__ = "registros_auditoria"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    ator_usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    ator_referencia = Column(String(80), nullable=False)
    ator_role = Column(String(20), nullable=False)
    acao = Column(String(30), nullable=False, index=True)
    recurso = Column(String(40), nullable=False, index=True)
    registro_id = Column(Integer, nullable=True, index=True)
    paciente_id = Column(Integer, nullable=True, index=True)
    campos = Column(String(1000), nullable=True)
    detalhes = Column(Text, nullable=True)
    endereco_ip = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False)
    hash_anterior = Column(String(64), nullable=True)
    assinatura = Column(String(64), nullable=False, unique=True)

    clinica = relationship("Clinica", back_populates="registros_auditoria")

    __table_args__ = (
        CheckConstraint(
            "acao IN ('ACESSO', 'CRIACAO', 'ALTERACAO', 'EXPORTACAO', 'SOLICITACAO', 'ANONIMIZACAO', 'EXCLUSAO', 'CONSENTIMENTO', 'REVOGACAO')",
            name="ck_auditoria_acao",
        ),
    )


class Consentimento(Base):
    __tablename__ = "consentimentos"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id", ondelete="CASCADE"), nullable=True, index=True)
    documento_tipo = Column(String(40), nullable=False, index=True)
    versao = Column(String(40), nullable=False)
    finalidade = Column(String(500), nullable=False)
    base_legal = Column(String(80), nullable=False)
    aceito_em = Column(DateTime(timezone=True), nullable=False)
    revogado_em = Column(DateTime(timezone=True), nullable=True)
    endereco_ip = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    documento_hash = Column(String(64), nullable=False)

    clinica = relationship("Clinica", back_populates="consentimentos")
    usuario = relationship("Usuario", back_populates="consentimentos")
    paciente = relationship("Paciente", back_populates="consentimentos")

    __table_args__ = (
        CheckConstraint(
            "documento_tipo IN ('termos_uso', 'politica_privacidade', 'comunicacoes')",
            name="ck_consentimentos_documento_tipo",
        ),
    )


class SolicitacaoLGPD(Base):
    __tablename__ = "solicitacoes_lgpd"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, ForeignKey("clinicas.id"), nullable=False, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id", ondelete="SET NULL"), nullable=True, index=True)
    usuario_solicitante_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    tipo = Column(String(30), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="Pendente", index=True)
    justificativa = Column(String(2000), nullable=True)
    solicitado_em = Column(DateTime(timezone=True), nullable=False)
    processado_em = Column(DateTime(timezone=True), nullable=True)
    processado_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    decisao_observacao = Column(String(2000), nullable=True)

    clinica = relationship("Clinica", back_populates="solicitacoes_lgpd")
    paciente = relationship("Paciente", back_populates="solicitacoes_lgpd")

    __table_args__ = (
        CheckConstraint("tipo IN ('anonimizacao', 'exclusao', 'correcao')", name="ck_solicitacoes_lgpd_tipo"),
        CheckConstraint("status IN ('Pendente', 'Concluida', 'Rejeitada')", name="ck_solicitacoes_lgpd_status"),
    )


def _impedir_mutacao_registro_clinico(_mapper, _connection, alvo) -> None:
    raise ValueError(
        f"{type(alvo).__name__} é imutável. Registre uma nova versão ou evento em vez de alterar/excluir."
    )


for _modelo_imutavel in (ProntuarioEntrada, AnexoProntuario, Prescricao, ItemPrescricao, EventoPrescricao):
    event.listen(_modelo_imutavel, "before_update", _impedir_mutacao_registro_clinico)
    event.listen(_modelo_imutavel, "before_delete", _impedir_mutacao_registro_clinico)
