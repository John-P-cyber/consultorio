"""Adiciona auditoria, consentimentos e solicitações LGPD.

Revision ID: 0004_lgpd_auditoria
Revises: 0003_multiempresa
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_lgpd_auditoria"
down_revision = "0003_multiempresa"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("usuarios", sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("pacientes", sa.Column("anonimizado_em", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "registros_auditoria",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("ator_usuario_id", sa.Integer(), nullable=True),
        sa.Column("ator_referencia", sa.String(length=80), nullable=False),
        sa.Column("ator_role", sa.String(length=20), nullable=False),
        sa.Column("acao", sa.String(length=30), nullable=False),
        sa.Column("recurso", sa.String(length=40), nullable=False),
        sa.Column("registro_id", sa.Integer(), nullable=True),
        sa.Column("paciente_id", sa.Integer(), nullable=True),
        sa.Column("campos", sa.String(length=1000), nullable=True),
        sa.Column("detalhes", sa.Text(), nullable=True),
        sa.Column("endereco_ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hash_anterior", sa.String(length=64), nullable=True),
        sa.Column("assinatura", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["ator_usuario_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("assinatura", name="uq_registros_auditoria_assinatura"),
        sa.CheckConstraint(
            "acao IN ('ACESSO', 'CRIACAO', 'ALTERACAO', 'EXPORTACAO', 'SOLICITACAO', 'ANONIMIZACAO', 'EXCLUSAO', 'CONSENTIMENTO', 'REVOGACAO')",
            name="ck_auditoria_acao",
        ),
    )
    for coluna in ("id", "clinica_id", "ator_usuario_id", "acao", "recurso", "registro_id", "paciente_id"):
        op.create_index(f"ix_registros_auditoria_{coluna}", "registros_auditoria", [coluna])

    op.create_table(
        "consentimentos",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("paciente_id", sa.Integer(), nullable=True),
        sa.Column("documento_tipo", sa.String(length=40), nullable=False),
        sa.Column("versao", sa.String(length=40), nullable=False),
        sa.Column("finalidade", sa.String(length=500), nullable=False),
        sa.Column("base_legal", sa.String(length=80), nullable=False),
        sa.Column("aceito_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revogado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("endereco_ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("documento_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["paciente_id"], ["pacientes.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "documento_tipo IN ('termos_uso', 'politica_privacidade', 'comunicacoes')",
            name="ck_consentimentos_documento_tipo",
        ),
    )
    for coluna in ("id", "clinica_id", "usuario_id", "paciente_id", "documento_tipo"):
        op.create_index(f"ix_consentimentos_{coluna}", "consentimentos", [coluna])

    op.create_table(
        "solicitacoes_lgpd",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("paciente_id", sa.Integer(), nullable=True),
        sa.Column("usuario_solicitante_id", sa.Integer(), nullable=True),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Pendente"),
        sa.Column("justificativa", sa.String(length=2000), nullable=True),
        sa.Column("solicitado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processado_por_id", sa.Integer(), nullable=True),
        sa.Column("decisao_observacao", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["paciente_id"], ["pacientes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["usuario_solicitante_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["processado_por_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.CheckConstraint("tipo IN ('anonimizacao', 'exclusao', 'correcao')", name="ck_solicitacoes_lgpd_tipo"),
        sa.CheckConstraint("status IN ('Pendente', 'Concluida', 'Rejeitada')", name="ck_solicitacoes_lgpd_status"),
    )
    for coluna in ("id", "clinica_id", "paciente_id", "tipo", "status"):
        op.create_index(f"ix_solicitacoes_lgpd_{coluna}", "solicitacoes_lgpd", [coluna])


def downgrade():
    op.drop_table("solicitacoes_lgpd")
    op.drop_table("consentimentos")
    op.drop_table("registros_auditoria")
    op.drop_column("pacientes", "anonimizado_em")
    op.drop_column("usuarios", "ativo")
