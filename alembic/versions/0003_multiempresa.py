"""Adiciona clínicas e isolamento multiempresa.

Revision ID: 0003_multiempresa
Revises: 0002_integridade
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_multiempresa"
down_revision = "0002_integridade"
branch_labels = None
depends_on = None


TABELAS_TENANT = ("usuarios", "pacientes", "medicos", "agendamentos", "exames", "avaliacoes")
NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def _alterar_nullable(tabela: str, nullable: bool) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(tabela, recreate="always") as batch:
            batch.alter_column("clinica_id", existing_type=sa.Integer(), nullable=nullable)
    else:
        op.alter_column(tabela, "clinica_id", existing_type=sa.Integer(), nullable=nullable)


def _trocar_unicos_globais_por_tenant() -> None:
    constraints = {
        "usuarios": (("email",),),
        "pacientes": (("cpf",), ("email",)),
        "medicos": (("crm",), ("email",)),
    }
    dialecto = op.get_bind().dialect.name
    for tabela, grupos in constraints.items():
        if dialecto == "sqlite":
            with op.batch_alter_table(tabela, recreate="always", naming_convention=NAMING_CONVENTION) as batch:
                for (campo,) in grupos:
                    batch.drop_constraint(f"uq_{tabela}_{campo}", type_="unique")
                    batch.create_unique_constraint(f"uq_{tabela}_clinica_{campo}", ["clinica_id", campo])
        else:
            for (campo,) in grupos:
                inspector = sa.inspect(op.get_bind())
                unique_constraint = next(
                    (
                        item for item in inspector.get_unique_constraints(tabela)
                        if item.get("column_names") == [campo]
                    ),
                    None,
                )
                if unique_constraint:
                    op.drop_constraint(unique_constraint["name"], tabela, type_="unique")
                else:
                    unique_index = next(
                        (
                            item for item in inspector.get_indexes(tabela)
                            if item.get("unique") and item.get("column_names") == [campo]
                            and not item.get("duplicates_constraint")
                        ),
                        None,
                    )
                    if unique_index:
                        op.drop_index(unique_index["name"], table_name=tabela)
                        op.create_index(unique_index["name"], tabela, [campo], unique=False)
                op.create_unique_constraint(f"uq_{tabela}_clinica_{campo}", tabela, ["clinica_id", campo])


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "clinicas" not in inspector.get_table_names():
        op.create_table(
            "clinicas",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("nome", sa.String(length=160), nullable=False),
            sa.Column("slug", sa.String(length=80), nullable=False),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.create_index("ix_clinicas_id", "clinicas", ["id"])
        op.create_index("ix_clinicas_slug", "clinicas", ["slug"], unique=True)
    else:
        indices = {item["name"] for item in inspector.get_indexes("clinicas")}
        if "ix_clinicas_id" not in indices:
            op.create_index("ix_clinicas_id", "clinicas", ["id"])
        if "ix_clinicas_slug" not in indices:
            op.create_index("ix_clinicas_slug", "clinicas", ["slug"], unique=True)

    clinica_id = bind.execute(
        sa.text("SELECT id FROM clinicas WHERE slug = :slug"), {"slug": "clinica-padrao"}
    ).scalar()
    if not clinica_id:
        resultado = bind.execute(
            sa.text("INSERT INTO clinicas (nome, slug, ativo) VALUES (:nome, :slug, :ativo)"),
            {"nome": "Clínica Padrão", "slug": "clinica-padrao", "ativo": True},
        )
        clinica_id = resultado.lastrowid
        if not clinica_id:
            clinica_id = bind.execute(
                sa.text("SELECT id FROM clinicas WHERE slug = :slug"), {"slug": "clinica-padrao"}
            ).scalar_one()

    for tabela in TABELAS_TENANT:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(tabela, recreate="always") as batch:
                batch.add_column(sa.Column("clinica_id", sa.Integer(), nullable=True))
                batch.create_foreign_key(
                    f"fk_{tabela}_clinica_id_clinicas", "clinicas", ["clinica_id"], ["id"]
                )
        else:
            op.add_column(tabela, sa.Column("clinica_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                f"fk_{tabela}_clinica_id_clinicas",
                tabela,
                "clinicas",
                ["clinica_id"],
                ["id"],
            )
        bind.execute(sa.text(f"UPDATE {tabela} SET clinica_id = :clinica_id"), {"clinica_id": clinica_id})
        _alterar_nullable(tabela, nullable=False)
        op.create_index(f"ix_{tabela}_clinica_id", tabela, ["clinica_id"])

    _trocar_unicos_globais_por_tenant()
    op.drop_index("uq_agendamento_medico_horario_ativo", table_name="agendamentos")
    op.create_index(
        "uq_agendamento_clinica_medico_horario_ativo",
        "agendamentos",
        ["clinica_id", "medico_id", "data_hora"],
        unique=True,
        postgresql_where=sa.text("status <> 'Cancelado'"),
        sqlite_where=sa.text("status <> 'Cancelado'"),
    )


def downgrade():
    op.drop_index("uq_agendamento_clinica_medico_horario_ativo", table_name="agendamentos")
    op.create_index(
        "uq_agendamento_medico_horario_ativo",
        "agendamentos",
        ["medico_id", "data_hora"],
        unique=True,
        postgresql_where=sa.text("status <> 'Cancelado'"),
        sqlite_where=sa.text("status <> 'Cancelado'"),
    )

    dialecto = op.get_bind().dialect.name
    constraints = {
        "usuarios": (("email",),),
        "pacientes": (("cpf",), ("email",)),
        "medicos": (("crm",), ("email",)),
    }
    for tabela, grupos in constraints.items():
        if dialecto == "sqlite":
            with op.batch_alter_table(tabela, recreate="always", naming_convention=NAMING_CONVENTION) as batch:
                for (campo,) in grupos:
                    batch.drop_constraint(f"uq_{tabela}_clinica_{campo}", type_="unique")
                    batch.create_unique_constraint(f"uq_{tabela}_{campo}", [campo])
        else:
            for (campo,) in grupos:
                op.drop_constraint(f"uq_{tabela}_clinica_{campo}", tabela, type_="unique")
                op.create_unique_constraint(f"{tabela}_{campo}_key", tabela, [campo])

    for tabela in reversed(TABELAS_TENANT):
        op.drop_index(f"ix_{tabela}_clinica_id", table_name=tabela)
        if dialecto == "sqlite":
            with op.batch_alter_table(tabela, recreate="always") as batch:
                batch.drop_constraint(f"fk_{tabela}_clinica_id_clinicas", type_="foreignkey")
                batch.drop_column("clinica_id")
        else:
            op.drop_constraint(f"fk_{tabela}_clinica_id_clinicas", tabela, type_="foreignkey")
            op.drop_column(tabela, "clinica_id")

    op.drop_index("ix_clinicas_slug", table_name="clinicas")
    op.drop_index("ix_clinicas_id", table_name="clinicas")
    op.drop_table("clinicas")
