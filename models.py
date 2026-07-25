from sqlalchemy import Column, Integer, String, Float, DateTime, Date, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin", "medico", "paciente"

    # Relacionamentos de via única (1 para 1)
    paciente = relationship("Paciente", back_populates="usuario", uselist=False)
    medico = relationship("Medico", back_populates="usuario", uselist=False)


class Paciente(Base):
    __tablename__ = "pacientes"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), unique=True, nullable=True)
    nome = Column(String, nullable=False)
    cpf = Column(String, unique=True, index=True, nullable=False)
    telefone = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    data_nascimento = Column(Date, nullable=False)
    
    # Endereço
    endereco_rua = Column(String, nullable=False)
    endereco_numero = Column(String, nullable=False)
    endereco_bairro = Column(String, nullable=False)
    endereco_cidade = Column(String, nullable=False)
    endereco_estado = Column(String, nullable=False)
    endereco_cep = Column(String, nullable=False)
    
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Relacionamentos
    usuario = relationship("Usuario", back_populates="paciente")
    agendamentos = relationship("Agendamento", back_populates="paciente")
    exames = relationship("Exame", back_populates="paciente")
    avaliacoes = relationship("Avaliacao", back_populates="paciente")


class Medico(Base):
    __tablename__ = "medicos"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), unique=True, nullable=True)
    nome = Column(String, nullable=False)
    especialidade = Column(String, nullable=False)
    duracao_consulta = Column(Integer, default=30)
    crm = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    foto_perfil = Column(String, nullable=True)

    # Endereço do Consultório
    endereco_rua = Column(String, nullable=False)
    endereco_numero = Column(String, nullable=False)
    endereco_bairro = Column(String, nullable=False)
    endereco_cidade = Column(String, nullable=False)
    endereco_estado = Column(String, nullable=False)
    endereco_cep = Column(String, nullable=False)
    
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    
    avaliacao_media = Column(Float, default=0.0)

    # Relacionamentos
    usuario = relationship("Usuario", back_populates="medico")
    agendamentos = relationship("Agendamento", back_populates="medico")
    avaliacoes = relationship("Avaliacao", back_populates="medico")


class Agendamento(Base):
    __tablename__ = "agendamentos"

    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    medico_id = Column(Integer, ForeignKey("medicos.id"), nullable=False)
    data_hora = Column(DateTime, nullable=False)
    status = Column(String, default="Confirmado") # Confirmado, Atendido, Cancelado

    paciente = relationship("Paciente", back_populates="agendamentos")
    medico = relationship("Medico", back_populates="agendamentos")
    avaliacao = relationship("Avaliacao", uselist=False, back_populates="agendamento")


class Exame(Base):
    __tablename__ = "exames"

    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    tipo_exame = Column(String, nullable=False)
    data_hora = Column(DateTime, nullable=False)
    laboratorio = Column(String, nullable=False)
    status = Column(String, default="Pendente")

    paciente = relationship("Paciente", back_populates="exames")


class Avaliacao(Base):
    __tablename__ = "avaliacoes"

    id = Column(Integer, primary_key=True, index=True)
    agendamento_id = Column(Integer, ForeignKey("agendamentos.id"), unique=True, nullable=False)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    medico_id = Column(Integer, ForeignKey("medicos.id"), nullable=False)
    
    nota_medico = Column(Integer, nullable=False)
    comentario_paciente = Column(String, nullable=True)
    
    nota_paciente = Column(Integer, nullable=True)
    comentario_medico = Column(String, nullable=True)

    agendamento = relationship("Agendamento", back_populates="avaliacao")
    paciente = relationship("Paciente", back_populates="avaliacoes")
    medico = relationship("Medico", back_populates="avaliacoes")
