"""Adiciona garantias de integridade e permite avaliação médica opcional.

Revision ID: 0002_integridade
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_integridade"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _tem_unique(tabela: str, colunas: list[str]) -> bool:
    return any(
        constraint.get("column_names") == colunas
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(tabela)
    )


def _tem_unique_nome(tabela: str, nome: str) -> bool:
    return any(
        constraint.get("name") == nome
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(tabela)
    )


def _tem_check(tabela: str, nome: str) -> bool:
    return any(
        constraint.get("name") == nome
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(tabela)
    )


def _tem_index(tabela: str, nome: str) -> bool:
    return any(index.get("name") == nome for index in sa.inspect(op.get_bind()).get_indexes(tabela))


def _coluna_nullable(tabela: str, coluna: str) -> bool:
    return next(item["nullable"] for item in sa.inspect(op.get_bind()).get_columns(tabela) if item["name"] == coluna)


def upgrade():
    precisa_paciente_unique = not _tem_unique("pacientes", ["usuario_id"])
    precisa_medico_unique = not _tem_unique("medicos", ["usuario_id"])
    precisa_usuario_check = not _tem_check("usuarios", "ck_usuarios_role")
    precisa_agendamento_check = not _tem_check("agendamentos", "ck_agendamentos_status")
    precisa_exame_check = not _tem_check("exames", "ck_exames_status")
    precisa_nota_medico_check = not _tem_check("avaliacoes", "ck_avaliacoes_nota_medico")
    precisa_nota_paciente_check = not _tem_check("avaliacoes", "ck_avaliacoes_nota_paciente")
    precisa_nota_nullable = not _coluna_nullable("avaliacoes", "nota_medico")

    if op.get_bind().dialect.name == "sqlite":
        if precisa_usuario_check:
            with op.batch_alter_table("usuarios", recreate="always") as batch:
                batch.create_check_constraint("ck_usuarios_role", "role IN ('admin', 'medico', 'paciente')")
        if precisa_paciente_unique:
            with op.batch_alter_table("pacientes", recreate="always") as batch:
                batch.create_unique_constraint("uq_pacientes_usuario_id", ["usuario_id"])
        if precisa_medico_unique:
            with op.batch_alter_table("medicos", recreate="always") as batch:
                batch.create_unique_constraint("uq_medicos_usuario_id", ["usuario_id"])
        if precisa_agendamento_check:
            with op.batch_alter_table("agendamentos", recreate="always") as batch:
                batch.create_check_constraint("ck_agendamentos_status", "status IN ('Confirmado', 'Atendido', 'Cancelado')")
        if precisa_exame_check:
            with op.batch_alter_table("exames", recreate="always") as batch:
                batch.create_check_constraint("ck_exames_status", "status IN ('Pendente', 'Concluído', 'Cancelado')")
        if precisa_nota_nullable or precisa_nota_medico_check or precisa_nota_paciente_check:
            with op.batch_alter_table("avaliacoes", recreate="always") as batch:
                if precisa_nota_nullable:
                    batch.alter_column("nota_medico", existing_type=sa.Integer(), nullable=True)
                if precisa_nota_medico_check:
                    batch.create_check_constraint("ck_avaliacoes_nota_medico", "nota_medico IS NULL OR (nota_medico BETWEEN 1 AND 5)")
                if precisa_nota_paciente_check:
                    batch.create_check_constraint("ck_avaliacoes_nota_paciente", "nota_paciente IS NULL OR (nota_paciente BETWEEN 1 AND 5)")
    else:
        if precisa_nota_nullable:
            op.alter_column("avaliacoes", "nota_medico", existing_type=sa.Integer(), nullable=True)
        if precisa_paciente_unique:
            op.create_unique_constraint("uq_pacientes_usuario_id", "pacientes", ["usuario_id"])
        if precisa_medico_unique:
            op.create_unique_constraint("uq_medicos_usuario_id", "medicos", ["usuario_id"])
        if precisa_usuario_check:
            op.create_check_constraint("ck_usuarios_role", "usuarios", "role IN ('admin', 'medico', 'paciente')")
        if precisa_agendamento_check:
            op.create_check_constraint("ck_agendamentos_status", "agendamentos", "status IN ('Confirmado', 'Atendido', 'Cancelado')")
        if precisa_exame_check:
            op.create_check_constraint("ck_exames_status", "exames", "status IN ('Pendente', 'Concluído', 'Cancelado')")
        if precisa_nota_medico_check:
            op.create_check_constraint("ck_avaliacoes_nota_medico", "avaliacoes", "nota_medico IS NULL OR (nota_medico BETWEEN 1 AND 5)")
        if precisa_nota_paciente_check:
            op.create_check_constraint("ck_avaliacoes_nota_paciente", "avaliacoes", "nota_paciente IS NULL OR (nota_paciente BETWEEN 1 AND 5)")

    if not _tem_index("agendamentos", "uq_agendamento_medico_horario_ativo"):
        op.create_index(
            "uq_agendamento_medico_horario_ativo",
            "agendamentos",
            ["medico_id", "data_hora"],
            unique=True,
            postgresql_where=sa.text("status <> 'Cancelado'"),
            sqlite_where=sa.text("status <> 'Cancelado'"),
        )


def downgrade():
    if _tem_index("agendamentos", "uq_agendamento_medico_horario_ativo"):
        op.drop_index("uq_agendamento_medico_horario_ativo", table_name="agendamentos")
    if op.get_bind().dialect.name == "sqlite":
        if _tem_check("avaliacoes", "ck_avaliacoes_nota_paciente") or _tem_check("avaliacoes", "ck_avaliacoes_nota_medico") or _coluna_nullable("avaliacoes", "nota_medico"):
            with op.batch_alter_table("avaliacoes", recreate="always") as batch:
                if _tem_check("avaliacoes", "ck_avaliacoes_nota_paciente"):
                    batch.drop_constraint("ck_avaliacoes_nota_paciente", type_="check")
                if _tem_check("avaliacoes", "ck_avaliacoes_nota_medico"):
                    batch.drop_constraint("ck_avaliacoes_nota_medico", type_="check")
                if _coluna_nullable("avaliacoes", "nota_medico"):
                    batch.alter_column("nota_medico", existing_type=sa.Integer(), nullable=False)
        if _tem_check("exames", "ck_exames_status"):
            with op.batch_alter_table("exames", recreate="always") as batch:
                batch.drop_constraint("ck_exames_status", type_="check")
        if _tem_check("agendamentos", "ck_agendamentos_status"):
            with op.batch_alter_table("agendamentos", recreate="always") as batch:
                batch.drop_constraint("ck_agendamentos_status", type_="check")
        if _tem_unique_nome("medicos", "uq_medicos_usuario_id"):
            with op.batch_alter_table("medicos", recreate="always") as batch:
                batch.drop_constraint("uq_medicos_usuario_id", type_="unique")
        if _tem_unique_nome("pacientes", "uq_pacientes_usuario_id"):
            with op.batch_alter_table("pacientes", recreate="always") as batch:
                batch.drop_constraint("uq_pacientes_usuario_id", type_="unique")
        if _tem_check("usuarios", "ck_usuarios_role"):
            with op.batch_alter_table("usuarios", recreate="always") as batch:
                batch.drop_constraint("ck_usuarios_role", type_="check")
    else:
        for tabela, nome in (
            ("avaliacoes", "ck_avaliacoes_nota_paciente"),
            ("avaliacoes", "ck_avaliacoes_nota_medico"),
            ("exames", "ck_exames_status"),
            ("agendamentos", "ck_agendamentos_status"),
            ("usuarios", "ck_usuarios_role"),
        ):
            if _tem_check(tabela, nome):
                op.drop_constraint(nome, tabela, type_="check")
        if _tem_unique_nome("medicos", "uq_medicos_usuario_id"):
            op.drop_constraint("uq_medicos_usuario_id", "medicos", type_="unique")
        if _tem_unique_nome("pacientes", "uq_pacientes_usuario_id"):
            op.drop_constraint("uq_pacientes_usuario_id", "pacientes", type_="unique")
        if _coluna_nullable("avaliacoes", "nota_medico"):
            op.alter_column("avaliacoes", "nota_medico", existing_type=sa.Integer(), nullable=False)
