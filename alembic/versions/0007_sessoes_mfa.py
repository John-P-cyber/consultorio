"""Adiciona sessões revogáveis e autenticação multifator.

Revision ID: 0007_sessoes_mfa
Revises: 0006_integridade_legado
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_sessoes_mfa"
down_revision = "0006_integridade_legado"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("mfa_ativo", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("usuarios", sa.Column("mfa_secret_salt", sa.String(length=64), nullable=True))
    op.add_column("usuarios", sa.Column("mfa_ultimo_contador", sa.Integer(), nullable=True))
    op.add_column("usuarios", sa.Column("mfa_falhas", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("usuarios", sa.Column("mfa_bloqueado_ate", sa.DateTime(timezone=True), nullable=True))
    op.add_column("usuarios", sa.Column("mfa_ativado_em", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "sessoes_usuario",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("familia_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("rotacao", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_uso_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revogado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_revogacao", sa.String(length=80), nullable=True),
        sa.Column("ip_criacao_hash", sa.String(length=64), nullable=True),
        sa.Column("ip_ultimo_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("mfa_verificada", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("refresh_token_hash", name="uq_sessoes_usuario_refresh_token_hash"),
        sa.CheckConstraint("rotacao >= 0", name="ck_sessao_rotacao_nao_negativa"),
    )
    for coluna in ("clinica_id", "usuario_id", "familia_id", "expira_em", "revogado_em"):
        op.create_index(f"ix_sessoes_usuario_{coluna}", "sessoes_usuario", [coluna])
    op.create_index(
        "ix_sessoes_usuario_ativas", "sessoes_usuario",
        ["clinica_id", "usuario_id", "revogado_em", "expira_em"],
    )

    op.create_table(
        "mfa_codigos_recuperacao",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("codigo_hash", sa.String(length=64), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_em", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("codigo_hash", name="uq_mfa_codigos_recuperacao_codigo_hash"),
    )
    for coluna in ("id", "clinica_id", "usuario_id", "usado_em"):
        op.create_index(f"ix_mfa_codigos_recuperacao_{coluna}", "mfa_codigos_recuperacao", [coluna])
    op.create_index(
        "ix_mfa_codigos_usuario_disponiveis", "mfa_codigos_recuperacao",
        ["clinica_id", "usuario_id", "usado_em"],
    )


def downgrade() -> None:
    op.drop_index("ix_mfa_codigos_usuario_disponiveis", table_name="mfa_codigos_recuperacao")
    for coluna in ("usado_em", "usuario_id", "clinica_id", "id"):
        op.drop_index(f"ix_mfa_codigos_recuperacao_{coluna}", table_name="mfa_codigos_recuperacao")
    op.drop_table("mfa_codigos_recuperacao")

    op.drop_index("ix_sessoes_usuario_ativas", table_name="sessoes_usuario")
    for coluna in ("revogado_em", "expira_em", "familia_id", "usuario_id", "clinica_id"):
        op.drop_index(f"ix_sessoes_usuario_{coluna}", table_name="sessoes_usuario")
    op.drop_table("sessoes_usuario")

    for coluna in (
        "mfa_ativado_em", "mfa_bloqueado_ate", "mfa_falhas",
        "mfa_ultimo_contador", "mfa_secret_salt", "mfa_ativo",
    ):
        op.drop_column("usuarios", coluna)
