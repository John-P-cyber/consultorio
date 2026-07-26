"""Initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-07-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
def upgrade():
    op.create_table(
        'usuarios',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('senha_hash', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('reset_version', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('email'),
        sa.Index('ix_usuarios_email', 'email'),
    )
    op.create_table(
        'pacientes',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('cpf', sa.String(), nullable=False),
        sa.Column('telefone', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('data_nascimento', sa.Date(), nullable=False),
        sa.Column('endereco_rua', sa.String(), nullable=False),
        sa.Column('endereco_numero', sa.String(), nullable=False),
        sa.Column('endereco_bairro', sa.String(), nullable=False),
        sa.Column('endereco_cidade', sa.String(), nullable=False),
        sa.Column('endereco_estado', sa.String(), nullable=False),
        sa.Column('endereco_cep', sa.String(), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
        sa.UniqueConstraint('cpf'),
        sa.UniqueConstraint('email'),
        sa.Index('ix_pacientes_cpf', 'cpf'),
        sa.Index('ix_pacientes_email', 'email'),
    )
    op.create_table(
        'medicos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('especialidade', sa.String(), nullable=False),
        sa.Column('duracao_consulta', sa.Integer(), server_default='30', nullable=True),
        sa.Column('crm', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('foto_perfil', sa.String(), nullable=True),
        sa.Column('endereco_rua', sa.String(), nullable=False),
        sa.Column('endereco_numero', sa.String(), nullable=False),
        sa.Column('endereco_bairro', sa.String(), nullable=False),
        sa.Column('endereco_cidade', sa.String(), nullable=False),
        sa.Column('endereco_estado', sa.String(), nullable=False),
        sa.Column('endereco_cep', sa.String(), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('avaliacao_media', sa.Float(), server_default='0.0', nullable=True),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
        sa.UniqueConstraint('crm'),
        sa.UniqueConstraint('email'),
        sa.Index('ix_medicos_crm', 'crm'),
        sa.Index('ix_medicos_email', 'email'),
    )
    op.create_table(
        'agendamentos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('paciente_id', sa.Integer(), nullable=False),
        sa.Column('medico_id', sa.Integer(), nullable=False),
        sa.Column('data_hora', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(), server_default='Confirmado', nullable=True),
        sa.ForeignKeyConstraint(['medico_id'], ['medicos.id'], ),
        sa.ForeignKeyConstraint(['paciente_id'], ['pacientes.id'], ),
    )
    op.create_table(
        'exames',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('paciente_id', sa.Integer(), nullable=False),
        sa.Column('tipo_exame', sa.String(), nullable=False),
        sa.Column('data_hora', sa.DateTime(), nullable=False),
        sa.Column('laboratorio', sa.String(), nullable=False),
        sa.Column('status', sa.String(), server_default='Pendente', nullable=True),
        sa.Column('resultado', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['paciente_id'], ['pacientes.id'], ),
    )
    op.create_table(
        'avaliacoes',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('agendamento_id', sa.Integer(), nullable=False),
        sa.Column('paciente_id', sa.Integer(), nullable=False),
        sa.Column('medico_id', sa.Integer(), nullable=False),
        sa.Column('nota_medico', sa.Integer(), nullable=False),
        sa.Column('comentario_paciente', sa.String(), nullable=True),
        sa.Column('nota_paciente', sa.Integer(), nullable=True),
        sa.Column('comentario_medico', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['agendamento_id'], ['agendamentos.id'], ),
        sa.ForeignKeyConstraint(['medico_id'], ['medicos.id'], ),
        sa.ForeignKeyConstraint(['paciente_id'], ['pacientes.id'], ),
        sa.UniqueConstraint('agendamento_id'),
    )

def downgrade():
    op.drop_table('avaliacoes')
    op.drop_table('exames')
    op.drop_table('agendamentos')
    op.drop_table('medicos')
    op.drop_table('pacientes')
    op.drop_table('usuarios')
