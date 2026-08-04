"""Adiciona conversas seguras do assistente de IA.

Revision ID: 0011_assistente_ia
Revises: 0010_comunicacoes
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_assistente_ia"
down_revision = "0010_comunicacoes"
branch_labels = None
depends_on = None


EVENTOS_ANTIGOS = "evento IN ('confirmacao', 'lembrete', 'cancelamento', 'teste')"
EVENTOS_NOVOS = (
    "evento IN ('confirmacao', 'lembrete', 'cancelamento', 'teste', "
    "'novo_agendamento_medico')"
)


def _alterar_eventos_comunicacao(expressao: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("comunicacoes", recreate="always") as batch:
            batch.drop_constraint("ck_comunicacoes_evento", type_="check")
            batch.create_check_constraint("ck_comunicacoes_evento", expressao)
    else:
        op.drop_constraint("ck_comunicacoes_evento", "comunicacoes", type_="check")
        op.create_check_constraint("ck_comunicacoes_evento", "comunicacoes", expressao)


def upgrade() -> None:
    _alterar_eventos_comunicacao(EVENTOS_NOVOS)
    op.create_table(
        "assistente_conversas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("titulo", sa.String(length=120), nullable=False, server_default="Nova conversa"),
        sa.Column("ativa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_assistente_conversas_clinica_id", "assistente_conversas", ["clinica_id"])
    op.create_index("ix_assistente_conversas_usuario_id", "assistente_conversas", ["usuario_id"])
    op.create_index("ix_assistente_conversas_atualizado_em", "assistente_conversas", ["atualizado_em"])
    op.create_index(
        "ix_assistente_conversa_usuario_atualizada",
        "assistente_conversas", ["clinica_id", "usuario_id", "atualizado_em"],
    )

    op.create_table(
        "assistente_mensagens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("conversa_id", sa.Integer(), nullable=False),
        sa.Column("papel", sa.String(length=20), nullable=False),
        sa.Column("conteudo", sa.Text(), nullable=False),
        sa.Column("artefatos_json", sa.Text(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversa_id"], ["assistente_conversas.id"], ondelete="CASCADE"),
        sa.CheckConstraint("papel IN ('user', 'assistant')", name="ck_assistente_mensagem_papel"),
    )
    op.create_index("ix_assistente_mensagens_clinica_id", "assistente_mensagens", ["clinica_id"])
    op.create_index("ix_assistente_mensagens_conversa_id", "assistente_mensagens", ["conversa_id"])
    op.create_index(
        "ix_assistente_mensagem_conversa_criado",
        "assistente_mensagens", ["conversa_id", "criado_em"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistente_mensagem_conversa_criado", table_name="assistente_mensagens")
    op.drop_index("ix_assistente_mensagens_conversa_id", table_name="assistente_mensagens")
    op.drop_index("ix_assistente_mensagens_clinica_id", table_name="assistente_mensagens")
    op.drop_table("assistente_mensagens")
    op.drop_index("ix_assistente_conversa_usuario_atualizada", table_name="assistente_conversas")
    op.drop_index("ix_assistente_conversas_atualizado_em", table_name="assistente_conversas")
    op.drop_index("ix_assistente_conversas_usuario_id", table_name="assistente_conversas")
    op.drop_index("ix_assistente_conversas_clinica_id", table_name="assistente_conversas")
    op.drop_table("assistente_conversas")
    _alterar_eventos_comunicacao(EVENTOS_ANTIGOS)
