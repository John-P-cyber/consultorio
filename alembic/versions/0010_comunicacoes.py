"""Adiciona configuração e histórico de comunicações por clínica.

Revision ID: 0010_comunicacoes
Revises: 0009_agenda_profissional
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_comunicacoes"
down_revision = "0009_agenda_profissional"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "configuracoes_comunicacao",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("email_ativo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_remetente_nome", sa.String(length=160), nullable=False),
        sa.Column("email_remetente", sa.String(length=254), nullable=True),
        sa.Column("email_responder_para", sa.String(length=254), nullable=True),
        sa.Column("whatsapp_ativo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("whatsapp_phone_number_id", sa.String(length=80), nullable=True),
        sa.Column("whatsapp_numero_exibicao", sa.String(length=30), nullable=True),
        sa.Column("whatsapp_codigo_pais", sa.String(length=3), nullable=False, server_default="55"),
        sa.Column(
            "whatsapp_template_confirmacao", sa.String(length=100), nullable=False,
            server_default="confirmacao_consulta",
        ),
        sa.Column(
            "whatsapp_template_lembrete", sa.String(length=100), nullable=False,
            server_default="lembrete_consulta",
        ),
        sa.Column(
            "whatsapp_template_cancelamento", sa.String(length=100), nullable=False,
            server_default="cancelamento_consulta",
        ),
        sa.Column("whatsapp_idioma", sa.String(length=12), nullable=False, server_default="pt_BR"),
        sa.Column("enviar_confirmacoes", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enviar_lembretes", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enviar_cancelamentos", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("lembrete_antecedencia_horas", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("atualizado_por_usuario_id", sa.Integer(), nullable=True),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["atualizado_por_usuario_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("clinica_id", name="uq_configuracao_comunicacao_clinica"),
        sa.CheckConstraint(
            "lembrete_antecedencia_horas >= 1 AND lembrete_antecedencia_horas <= 168",
            name="ck_comunicacao_lembrete_antecedencia",
        ),
        sa.CheckConstraint("length(whatsapp_codigo_pais) >= 1", name="ck_comunicacao_codigo_pais"),
    )
    op.create_table(
        "comunicacoes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("agendamento_id", sa.Integer(), nullable=True),
        sa.Column("paciente_id", sa.Integer(), nullable=True),
        sa.Column("canal", sa.String(length=20), nullable=False),
        sa.Column("evento", sa.String(length=30), nullable=False),
        sa.Column("destinatario_hash", sa.String(length=64), nullable=True),
        sa.Column("destinatario_resumo", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pendente"),
        sa.Column("tentativas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provedor_mensagem_id", sa.String(length=200), nullable=True),
        sa.Column("ultimo_erro", sa.String(length=300), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ultima_tentativa_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("enviado_em", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agendamento_id"], ["agendamentos.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["paciente_id"], ["pacientes.id"], ondelete="SET NULL"),
        sa.CheckConstraint("canal IN ('email', 'whatsapp')", name="ck_comunicacoes_canal"),
        sa.CheckConstraint(
            "evento IN ('confirmacao', 'lembrete', 'cancelamento', 'teste')",
            name="ck_comunicacoes_evento",
        ),
        sa.CheckConstraint(
            "status IN ('pendente', 'enviado', 'falhou', 'ignorado')",
            name="ck_comunicacoes_status",
        ),
        sa.CheckConstraint("tentativas >= 0 AND tentativas <= 10", name="ck_comunicacoes_tentativas"),
        sa.UniqueConstraint(
            "clinica_id", "agendamento_id", "canal", "evento",
            name="uq_comunicacao_agendamento_canal_evento",
        ),
    )
    op.create_index("ix_comunicacoes_clinica_id", "comunicacoes", ["clinica_id"])
    op.create_index("ix_comunicacoes_agendamento_id", "comunicacoes", ["agendamento_id"])
    op.create_index("ix_comunicacoes_paciente_id", "comunicacoes", ["paciente_id"])
    op.create_index("ix_comunicacoes_status", "comunicacoes", ["status"])
    op.create_index("ix_comunicacoes_clinica_criado", "comunicacoes", ["clinica_id", "criado_em"])

    op.execute(sa.text("""
        INSERT INTO configuracoes_comunicacao (
            clinica_id, email_ativo, email_remetente_nome, whatsapp_ativo,
            whatsapp_codigo_pais, whatsapp_template_confirmacao, whatsapp_template_lembrete,
            whatsapp_template_cancelamento, whatsapp_idioma,
            enviar_confirmacoes, enviar_lembretes, enviar_cancelamentos,
            lembrete_antecedencia_horas, atualizado_em
        )
        SELECT id, false, nome, false,
               '55', 'confirmacao_consulta', 'lembrete_consulta',
               'cancelamento_consulta', 'pt_BR',
               true, true, true, 24, CURRENT_TIMESTAMP
        FROM clinicas
    """))


def downgrade() -> None:
    op.drop_index("ix_comunicacoes_clinica_criado", table_name="comunicacoes")
    op.drop_index("ix_comunicacoes_status", table_name="comunicacoes")
    op.drop_index("ix_comunicacoes_paciente_id", table_name="comunicacoes")
    op.drop_index("ix_comunicacoes_agendamento_id", table_name="comunicacoes")
    op.drop_index("ix_comunicacoes_clinica_id", table_name="comunicacoes")
    op.drop_table("comunicacoes")
    op.drop_table("configuracoes_comunicacao")
