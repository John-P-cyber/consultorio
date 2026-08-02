"""Remove indices redundantes das chaves primarias.

Revision ID: 0008_indices_pk
Revises: 0007_sessoes_mfa
"""

from alembic import op


revision = "0008_indices_pk"
down_revision = "0007_sessoes_mfa"
branch_labels = None
depends_on = None


TABELAS_COM_INDICE_PK_REDUNDANTE = (
    "clinicas",
    "mfa_codigos_recuperacao",
    "prontuario_entradas",
    "anexos_prontuario",
    "prescricoes",
    "itens_prescricao",
    "eventos_prescricao",
    "registros_auditoria",
    "consentimentos",
    "solicitacoes_lgpd",
)


def upgrade() -> None:
    for tabela in TABELAS_COM_INDICE_PK_REDUNDANTE:
        op.drop_index(f"ix_{tabela}_id", table_name=tabela)


def downgrade() -> None:
    for tabela in reversed(TABELAS_COM_INDICE_PK_REDUNDANTE):
        op.create_index(f"ix_{tabela}_id", tabela, ["id"])
