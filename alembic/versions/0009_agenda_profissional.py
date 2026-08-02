"""Adiciona agenda profissional configurável por médico.

Revision ID: 0009_agenda_profissional
Revises: 0008_indices_pk
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_agenda_profissional"
down_revision = "0008_indices_pk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("medicos") as batch:
        batch.add_column(sa.Column(
            "permite_cancelamento_paciente", sa.Boolean(), nullable=False, server_default=sa.true()
        ))
        batch.add_column(sa.Column(
            "antecedencia_cancelamento_horas", sa.Integer(), nullable=False, server_default="24"
        ))
        batch.create_check_constraint(
            "ck_medicos_antecedencia_cancelamento",
            "antecedencia_cancelamento_horas >= 0 AND antecedencia_cancelamento_horas <= 720",
        )

    op.create_table(
        "disponibilidades_agenda",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("medico_id", sa.Integer(), nullable=False),
        sa.Column("dia_semana", sa.Integer(), nullable=False),
        sa.Column("hora_inicio", sa.Time(), nullable=False),
        sa.Column("hora_fim", sa.Time(), nullable=False),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["medico_id"], ["medicos.id"], ondelete="CASCADE"),
        sa.CheckConstraint("dia_semana >= 0 AND dia_semana <= 6", name="ck_disponibilidade_dia_semana"),
        sa.CheckConstraint("hora_fim > hora_inicio", name="ck_disponibilidade_intervalo"),
        sa.UniqueConstraint(
            "clinica_id", "medico_id", "dia_semana", "hora_inicio", "hora_fim",
            name="uq_disponibilidade_medico_faixa",
        ),
    )
    op.create_index("ix_disponibilidades_agenda_clinica_id", "disponibilidades_agenda", ["clinica_id"])
    op.create_index("ix_disponibilidades_agenda_medico_id", "disponibilidades_agenda", ["medico_id"])
    op.create_index(
        "ix_disponibilidade_medico_dia", "disponibilidades_agenda", ["clinica_id", "medico_id", "dia_semana"]
    )

    op.create_table(
        "tipos_consulta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("medico_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=100), nullable=False),
        sa.Column("duracao_minutos", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("intervalo_minutos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("e_retorno", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("prazo_retorno_dias", sa.Integer(), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["medico_id"], ["medicos.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("clinica_id", "medico_id", "nome", name="uq_tipo_consulta_medico_nome"),
        sa.CheckConstraint("duracao_minutos >= 10 AND duracao_minutos <= 240", name="ck_tipo_consulta_duracao"),
        sa.CheckConstraint("intervalo_minutos >= 0 AND intervalo_minutos <= 120", name="ck_tipo_consulta_intervalo"),
        sa.CheckConstraint(
            "prazo_retorno_dias IS NULL OR (prazo_retorno_dias >= 1 AND prazo_retorno_dias <= 365)",
            name="ck_tipo_consulta_prazo_retorno",
        ),
    )
    op.create_index("ix_tipos_consulta_clinica_id", "tipos_consulta", ["clinica_id"])
    op.create_index("ix_tipos_consulta_medico_id", "tipos_consulta", ["medico_id"])

    op.create_table(
        "indisponibilidades_agenda",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinica_id", sa.Integer(), nullable=False),
        sa.Column("medico_id", sa.Integer(), nullable=True),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("inicio", sa.DateTime(), nullable=False),
        sa.Column("fim", sa.DateTime(), nullable=False),
        sa.Column("motivo", sa.String(length=300), nullable=False),
        sa.Column("criado_por_usuario_id", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["clinica_id"], ["clinicas.id"]),
        sa.ForeignKeyConstraint(["medico_id"], ["medicos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["criado_por_usuario_id"], ["usuarios.id"]),
        sa.CheckConstraint("tipo IN ('ferias', 'feriado', 'bloqueio')", name="ck_indisponibilidade_tipo"),
        sa.CheckConstraint("fim > inicio", name="ck_indisponibilidade_intervalo"),
    )
    op.create_index("ix_indisponibilidades_agenda_clinica_id", "indisponibilidades_agenda", ["clinica_id"])
    op.create_index("ix_indisponibilidades_agenda_medico_id", "indisponibilidades_agenda", ["medico_id"])
    op.create_index(
        "ix_indisponibilidade_periodo", "indisponibilidades_agenda",
        ["clinica_id", "medico_id", "inicio", "fim"],
    )

    op.execute(
        """
        INSERT INTO tipos_consulta
            (clinica_id, medico_id, nome, duracao_minutos, intervalo_minutos, e_retorno, prazo_retorno_dias, ativo)
        SELECT clinica_id, id, 'Consulta', COALESCE(duracao_consulta, 30), 0, FALSE, NULL, TRUE
          FROM medicos
        """
    )
    op.execute(
        """
        INSERT INTO tipos_consulta
            (clinica_id, medico_id, nome, duracao_minutos, intervalo_minutos, e_retorno, prazo_retorno_dias, ativo)
        SELECT clinica_id, id, 'Retorno', COALESCE(duracao_consulta, 30), 0, TRUE, 30, TRUE
          FROM medicos
        """
    )
    for dia_semana in range(5):
        for inicio, fim in (("08:00:00", "12:00:00"), ("13:00:00", "18:00:00")):
            op.execute(
                f"""
                INSERT INTO disponibilidades_agenda
                    (clinica_id, medico_id, dia_semana, hora_inicio, hora_fim)
                SELECT clinica_id, id, {dia_semana}, '{inicio}', '{fim}' FROM medicos
                """
            )

    with op.batch_alter_table("agendamentos") as batch:
        batch.add_column(sa.Column("tipo_consulta_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column(
            "tipo_consulta_nome", sa.String(length=100), nullable=False, server_default="Consulta"
        ))
        batch.add_column(sa.Column("duracao_minutos", sa.Integer(), nullable=False, server_default="30"))
        batch.add_column(sa.Column("intervalo_minutos", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("retorno_de_agendamento_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cancelado_em", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancelado_por_usuario_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("motivo_cancelamento", sa.String(length=500), nullable=True))
        batch.create_foreign_key("fk_agendamento_tipo_consulta", "tipos_consulta", ["tipo_consulta_id"], ["id"])
        batch.create_foreign_key(
            "fk_agendamento_retorno_origem", "agendamentos", ["retorno_de_agendamento_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_agendamento_cancelado_por", "usuarios", ["cancelado_por_usuario_id"], ["id"]
        )
        batch.create_check_constraint(
            "ck_agendamento_duracao", "duracao_minutos >= 10 AND duracao_minutos <= 240"
        )
        batch.create_check_constraint(
            "ck_agendamento_intervalo", "intervalo_minutos >= 0 AND intervalo_minutos <= 120"
        )
    op.create_index("ix_agendamentos_tipo_consulta_id", "agendamentos", ["tipo_consulta_id"])
    op.create_index("ix_agendamentos_retorno_de_agendamento_id", "agendamentos", ["retorno_de_agendamento_id"])
    op.execute(
        """
        UPDATE agendamentos
           SET tipo_consulta_id = (
                   SELECT MIN(t.id)
                     FROM tipos_consulta t
                    WHERE t.clinica_id = agendamentos.clinica_id
                      AND t.medico_id = agendamentos.medico_id
                      AND t.nome = 'Consulta'
               ),
               duracao_minutos = COALESCE((
                   SELECT m.duracao_consulta FROM medicos m WHERE m.id = agendamentos.medico_id
               ), 30)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_agendamentos_retorno_de_agendamento_id", table_name="agendamentos")
    op.drop_index("ix_agendamentos_tipo_consulta_id", table_name="agendamentos")
    with op.batch_alter_table("agendamentos") as batch:
        batch.drop_constraint("fk_agendamento_cancelado_por", type_="foreignkey")
        batch.drop_constraint("fk_agendamento_retorno_origem", type_="foreignkey")
        batch.drop_constraint("fk_agendamento_tipo_consulta", type_="foreignkey")
        batch.drop_constraint("ck_agendamento_intervalo", type_="check")
        batch.drop_constraint("ck_agendamento_duracao", type_="check")
        batch.drop_column("motivo_cancelamento")
        batch.drop_column("cancelado_por_usuario_id")
        batch.drop_column("cancelado_em")
        batch.drop_column("retorno_de_agendamento_id")
        batch.drop_column("intervalo_minutos")
        batch.drop_column("duracao_minutos")
        batch.drop_column("tipo_consulta_nome")
        batch.drop_column("tipo_consulta_id")

    op.drop_table("indisponibilidades_agenda")
    op.drop_table("disponibilidades_agenda")
    op.drop_table("tipos_consulta")
    with op.batch_alter_table("medicos") as batch:
        batch.drop_constraint("ck_medicos_antecedencia_cancelamento", type_="check")
        batch.drop_column("antecedencia_cancelamento_horas")
        batch.drop_column("permite_cancelamento_paciente")
