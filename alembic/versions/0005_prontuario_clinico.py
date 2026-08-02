"""Separa o prontuário clínico, versões, anexos e prescrições.

Revision ID: 0005_prontuario_clinico
Revises: 0004_lgpd_auditoria
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0005_prontuario_clinico"
down_revision = "0004_lgpd_auditoria"
branch_labels = None
depends_on = None


def _data_canonica(valor: datetime) -> str:
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return valor.astimezone(UTC).isoformat(timespec="microseconds")


def _hash_payload(payload: dict) -> str:
    canonico = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _criar_tabelas() -> None:
    op.create_table(
        "prontuario_entradas",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("serie_id", sa.String(length=36), nullable=False),
        sa.Column("versao", sa.Integer(), nullable=False),
        sa.Column("versao_anterior_id", sa.Integer(), nullable=True),
        sa.Column("paciente_id", sa.Integer(), nullable=False),
        sa.Column("medico_id", sa.Integer(), nullable=False),
        sa.Column("agendamento_id", sa.Integer(), nullable=True),
        sa.Column("autor_usuario_id", sa.Integer(), nullable=True),
        sa.Column("autor_nome", sa.String(length=160), nullable=False),
        sa.Column("autor_crm", sa.String(length=80), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("conteudo", sa.Text(), nullable=False),
        sa.Column("motivo_retificacao", sa.String(length=500), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assinado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assinatura_tipo", sa.String(length=40), nullable=False),
        sa.Column("documento_hash", sa.String(length=64), nullable=False),
        sa.Column("assinatura_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["versao_anterior_id"], ["prontuario_entradas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paciente_id"], ["pacientes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["medico_id"], ["medicos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agendamento_id"], ["agendamentos.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["autor_usuario_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("clinica_id", "serie_id", "versao", name="uq_prontuario_serie_versao"),
        sa.UniqueConstraint("documento_hash", name="uq_prontuario_documento_hash"),
        sa.UniqueConstraint("assinatura_hash", name="uq_prontuario_assinatura_hash"),
        sa.CheckConstraint("versao >= 1", name="ck_prontuario_versao_positiva"),
        sa.CheckConstraint(
            "tipo IN ('evolucao', 'anamnese', 'diagnostico', 'procedimento', 'observacao')",
            name="ck_prontuario_tipo",
        ),
        sa.CheckConstraint(
            "assinatura_tipo IN ('interna_reautenticada', 'migrado_sem_assinatura')",
            name="ck_prontuario_assinatura_tipo",
        ),
    )
    for coluna in ("id", "clinica_id", "serie_id", "paciente_id", "medico_id", "agendamento_id", "autor_usuario_id"):
        op.create_index(f"ix_prontuario_entradas_{coluna}", "prontuario_entradas", [coluna])
    op.create_index("ix_prontuario_paciente_criado", "prontuario_entradas", ["clinica_id", "paciente_id", "criado_em"])

    op.create_table(
        "anexos_prontuario",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("prontuario_id", sa.Integer(), nullable=False),
        sa.Column("enviado_por_usuario_id", sa.Integer(), nullable=True),
        sa.Column("nome_original", sa.String(length=255), nullable=False),
        sa.Column("tipo_mime", sa.String(length=100), nullable=False),
        sa.Column("tamanho_bytes", sa.Integer(), nullable=False),
        sa.Column("arquivo_hash", sa.String(length=64), nullable=False),
        sa.Column("caminho_armazenamento", sa.String(length=500), nullable=False),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column("conferencia", sa.String(length=30), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["prontuario_id"], ["prontuario_entradas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["enviado_por_usuario_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("caminho_armazenamento", name="uq_anexo_caminho"),
        sa.CheckConstraint("tamanho_bytes > 0", name="ck_anexo_tamanho_positivo"),
        sa.CheckConstraint("origem IN ('nato_digital', 'digitalizado')", name="ck_anexo_origem"),
        sa.CheckConstraint("conferencia IN ('original', 'copia_simples', 'copia_conferida')", name="ck_anexo_conferencia"),
    )
    for coluna in ("id", "clinica_id", "prontuario_id"):
        op.create_index(f"ix_anexos_prontuario_{coluna}", "anexos_prontuario", [coluna])

    op.create_table(
        "prescricoes",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("prontuario_id", sa.Integer(), nullable=True),
        sa.Column("paciente_id", sa.Integer(), nullable=False),
        sa.Column("medico_id", sa.Integer(), nullable=False),
        sa.Column("autor_usuario_id", sa.Integer(), nullable=True),
        sa.Column("autor_nome", sa.String(length=160), nullable=False),
        sa.Column("autor_crm", sa.String(length=80), nullable=False),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assinado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assinatura_tipo", sa.String(length=40), nullable=False),
        sa.Column("documento_hash", sa.String(length=64), nullable=False),
        sa.Column("assinatura_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["prontuario_id"], ["prontuario_entradas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paciente_id"], ["pacientes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["medico_id"], ["medicos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["autor_usuario_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("documento_hash", name="uq_prescricao_documento_hash"),
        sa.UniqueConstraint("assinatura_hash", name="uq_prescricao_assinatura_hash"),
        sa.CheckConstraint("assinatura_tipo = 'interna_reautenticada'", name="ck_prescricao_assinatura_tipo"),
    )
    for coluna in ("id", "clinica_id", "prontuario_id", "paciente_id", "medico_id"):
        op.create_index(f"ix_prescricoes_{coluna}", "prescricoes", [coluna])

    op.create_table(
        "itens_prescricao",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("prescricao_id", sa.Integer(), nullable=False),
        sa.Column("medicamento", sa.String(length=200), nullable=False),
        sa.Column("concentracao", sa.String(length=100), nullable=True),
        sa.Column("forma_farmaceutica", sa.String(length=100), nullable=True),
        sa.Column("dose", sa.String(length=200), nullable=False),
        sa.Column("via", sa.String(length=100), nullable=False),
        sa.Column("frequencia", sa.String(length=200), nullable=False),
        sa.Column("duracao", sa.String(length=200), nullable=False),
        sa.Column("orientacoes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["prescricao_id"], ["prescricoes.id"], ondelete="RESTRICT"),
    )
    for coluna in ("id", "clinica_id", "prescricao_id"):
        op.create_index(f"ix_itens_prescricao_{coluna}", "itens_prescricao", [coluna])

    op.create_table(
        "eventos_prescricao",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("prescricao_id", sa.Integer(), nullable=False),
        sa.Column("autor_usuario_id", sa.Integer(), nullable=True),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("motivo", sa.String(length=500), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("documento_hash", sa.String(length=64), nullable=False),
        sa.Column("assinatura_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["prescricao_id"], ["prescricoes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["autor_usuario_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("prescricao_id", "tipo", name="uq_prescricao_evento_tipo"),
        sa.UniqueConstraint("documento_hash", name="uq_evento_prescricao_documento_hash"),
        sa.UniqueConstraint("assinatura_hash", name="uq_evento_prescricao_assinatura_hash"),
        sa.CheckConstraint("tipo = 'cancelamento'", name="ck_evento_prescricao_tipo"),
    )
    for coluna in ("id", "clinica_id", "prescricao_id"):
        op.create_index(f"ix_eventos_prescricao_{coluna}", "eventos_prescricao", [coluna])


def _migrar_evolucoes() -> None:
    bind = op.get_bind()
    registros = bind.execute(sa.text("""
        SELECT av.clinica_id, av.agendamento_id, av.paciente_id, av.medico_id,
               av.nota_paciente, av.comentario_medico, ag.data_hora,
               med.nome AS autor_nome, med.crm AS autor_crm, med.usuario_id AS autor_usuario_id
          FROM avaliacoes av
          JOIN medicos med ON med.id = av.medico_id AND med.clinica_id = av.clinica_id
          LEFT JOIN agendamentos ag ON ag.id = av.agendamento_id AND ag.clinica_id = av.clinica_id
         WHERE av.comentario_medico IS NOT NULL AND TRIM(av.comentario_medico) <> ''
    """)).mappings().all()
    agora = datetime.now(UTC)
    for legado in registros:
        criado_em = legado["data_hora"] or agora
        if isinstance(criado_em, str):
            criado_em = datetime.fromisoformat(criado_em.replace("Z", "+00:00"))
        conteudo = legado["comentario_medico"].strip()
        if legado["nota_paciente"] is not None:
            conteudo += f"\n\n[Dado legado] Indicador de adesão registrado: {legado['nota_paciente']}/5."
        serie_id = str(uuid4())
        payload = {
            "clinica_id": legado["clinica_id"],
            "serie_id": serie_id,
            "versao": 1,
            "versao_anterior_id": None,
            "paciente_id": legado["paciente_id"],
            "medico_id": legado["medico_id"],
            "agendamento_id": legado["agendamento_id"],
            "autor_usuario_id": legado["autor_usuario_id"],
            "autor_nome": legado["autor_nome"],
            "autor_crm": legado["autor_crm"],
            "tipo": "evolucao",
            "conteudo": conteudo,
            "motivo_retificacao": None,
            "criado_em": None,
            "assinado_em": None,
            "assinatura_tipo": "migrado_sem_assinatura",
        }
        hash_temporario = hashlib.sha256(f"migracao:{serie_id}".encode("utf-8")).hexdigest()
        bind.execute(sa.text("""
            INSERT INTO prontuario_entradas
                (clinica_id, serie_id, versao, versao_anterior_id, paciente_id, medico_id,
                 agendamento_id, autor_usuario_id, autor_nome, autor_crm, tipo, conteudo,
                 motivo_retificacao, criado_em, assinado_em, assinatura_tipo, documento_hash, assinatura_hash)
            VALUES
                (:clinica_id, :serie_id, :versao, :versao_anterior_id, :paciente_id, :medico_id,
                 :agendamento_id, :autor_usuario_id, :autor_nome, :autor_crm, :tipo, :conteudo,
                 :motivo_retificacao, :criado_em_db, NULL, :assinatura_tipo, :documento_hash, NULL)
        """), {
            **payload,
            "criado_em_db": criado_em,
            "documento_hash": hash_temporario,
        })
        persistido = bind.execute(
            sa.text("SELECT id, criado_em FROM prontuario_entradas WHERE clinica_id = :clinica_id AND serie_id = :serie_id"),
            {"clinica_id": legado["clinica_id"], "serie_id": serie_id},
        ).mappings().one()
        # O banco pode interpretar timestamps legados sem fuso no timezone da sessão.
        # O hash deve usar o instante efetivamente persistido, não o valor Python anterior ao INSERT.
        payload["criado_em"] = _data_canonica(persistido["criado_em"])
        bind.execute(
            sa.text("UPDATE prontuario_entradas SET documento_hash = :documento_hash WHERE id = :id"),
            {"documento_hash": _hash_payload(payload), "id": persistido["id"]},
        )


def _proteger_imutabilidade() -> None:
    tabelas = ("prontuario_entradas", "anexos_prontuario", "prescricoes", "itens_prescricao", "eventos_prescricao")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION bloquear_mutacao_registro_clinico() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Registros clínicos são imutáveis; crie uma versão ou evento.';
            END;
            $$ LANGUAGE plpgsql
        """)
        for tabela in tabelas:
            op.execute(
                f"CREATE TRIGGER trg_{tabela}_imutavel BEFORE UPDATE OR DELETE ON {tabela} "
                "FOR EACH ROW EXECUTE FUNCTION bloquear_mutacao_registro_clinico()"
            )
    elif op.get_bind().dialect.name == "sqlite":
        for tabela in tabelas:
            op.execute(
                f"CREATE TRIGGER trg_{tabela}_update_imutavel BEFORE UPDATE ON {tabela} "
                "BEGIN SELECT RAISE(ABORT, 'registro clínico imutável'); END"
            )
            op.execute(
                f"CREATE TRIGGER trg_{tabela}_delete_imutavel BEFORE DELETE ON {tabela} "
                "BEGIN SELECT RAISE(ABORT, 'registro clínico imutável'); END"
            )


def upgrade() -> None:
    _criar_tabelas()
    _migrar_evolucoes()
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("avaliacoes", recreate="always") as batch:
            batch.drop_constraint("ck_avaliacoes_nota_paciente", type_="check")
            batch.drop_column("nota_paciente")
            batch.drop_column("comentario_medico")
    else:
        op.drop_constraint("ck_avaliacoes_nota_paciente", "avaliacoes", type_="check")
        op.drop_column("avaliacoes", "nota_paciente")
        op.drop_column("avaliacoes", "comentario_medico")
    _proteger_imutabilidade()


def downgrade() -> None:
    tabelas = ("prontuario_entradas", "anexos_prontuario", "prescricoes", "itens_prescricao", "eventos_prescricao")
    if op.get_bind().dialect.name == "postgresql":
        for tabela in tabelas:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{tabela}_imutavel ON {tabela}")
        op.execute("DROP FUNCTION IF EXISTS bloquear_mutacao_registro_clinico()")
    elif op.get_bind().dialect.name == "sqlite":
        for tabela in tabelas:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{tabela}_update_imutavel")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{tabela}_delete_imutavel")

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("avaliacoes", recreate="always") as batch:
            batch.add_column(sa.Column("nota_paciente", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("comentario_medico", sa.String(), nullable=True))
            batch.create_check_constraint("ck_avaliacoes_nota_paciente", "nota_paciente IS NULL OR (nota_paciente BETWEEN 1 AND 5)")
    else:
        op.add_column("avaliacoes", sa.Column("nota_paciente", sa.Integer(), nullable=True))
        op.add_column("avaliacoes", sa.Column("comentario_medico", sa.String(), nullable=True))
        op.create_check_constraint("ck_avaliacoes_nota_paciente", "avaliacoes", "nota_paciente IS NULL OR (nota_paciente BETWEEN 1 AND 5)")

    op.drop_table("eventos_prescricao")
    op.drop_table("itens_prescricao")
    op.drop_table("prescricoes")
    op.drop_table("anexos_prontuario")
    op.drop_table("prontuario_entradas")
