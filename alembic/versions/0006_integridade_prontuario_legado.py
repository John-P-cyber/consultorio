"""Recalcula o hash dos prontuários legados após a conversão de timezone.

Revision ID: 0006_integridade_legado
Revises: 0005_prontuario_clinico
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "0006_integridade_legado"
down_revision = "0005_prontuario_clinico"
branch_labels = None
depends_on = None


def _data_canonica(valor: datetime | str | None) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return valor.astimezone(UTC).isoformat(timespec="microseconds")


def _hash_payload(payload: dict) -> str:
    canonico = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _suspender_protecao() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_prontuario_entradas_imutavel ON prontuario_entradas")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_prontuario_entradas_update_imutavel")
        op.execute("DROP TRIGGER IF EXISTS trg_prontuario_entradas_delete_imutavel")


def _restaurar_protecao() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE TRIGGER trg_prontuario_entradas_imutavel "
            "BEFORE UPDATE OR DELETE ON prontuario_entradas "
            "FOR EACH ROW EXECUTE FUNCTION bloquear_mutacao_registro_clinico()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_prontuario_entradas_update_imutavel "
            "BEFORE UPDATE ON prontuario_entradas "
            "BEGIN SELECT RAISE(ABORT, 'registro clínico imutável'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_prontuario_entradas_delete_imutavel "
            "BEFORE DELETE ON prontuario_entradas "
            "BEGIN SELECT RAISE(ABORT, 'registro clínico imutável'); END"
        )


def upgrade() -> None:
    bind = op.get_bind()
    _suspender_protecao()
    try:
        registros = bind.execute(sa.text("""
            SELECT id, clinica_id, serie_id, versao, versao_anterior_id, paciente_id,
                   medico_id, agendamento_id, autor_usuario_id, autor_nome, autor_crm,
                   tipo, conteudo, motivo_retificacao, criado_em, assinado_em,
                   assinatura_tipo, documento_hash
              FROM prontuario_entradas
             WHERE assinatura_tipo = 'migrado_sem_assinatura'
        """)).mappings().all()
        for registro in registros:
            payload = {
                "clinica_id": registro["clinica_id"],
                "serie_id": registro["serie_id"],
                "versao": registro["versao"],
                "versao_anterior_id": registro["versao_anterior_id"],
                "paciente_id": registro["paciente_id"],
                "medico_id": registro["medico_id"],
                "agendamento_id": registro["agendamento_id"],
                "autor_usuario_id": registro["autor_usuario_id"],
                "autor_nome": registro["autor_nome"],
                "autor_crm": registro["autor_crm"],
                "tipo": registro["tipo"],
                "conteudo": registro["conteudo"],
                "motivo_retificacao": registro["motivo_retificacao"],
                "criado_em": _data_canonica(registro["criado_em"]),
                "assinado_em": _data_canonica(registro["assinado_em"]),
                "assinatura_tipo": registro["assinatura_tipo"],
            }
            documento_hash = _hash_payload(payload)
            if documento_hash != registro["documento_hash"]:
                bind.execute(
                    sa.text("UPDATE prontuario_entradas SET documento_hash = :hash WHERE id = :id"),
                    {"hash": documento_hash, "id": registro["id"]},
                )
    finally:
        _restaurar_protecao()


def downgrade() -> None:
    # Correção de integridade é deliberadamente irreversível: restaurar hashes
    # inconsistentes tornaria o histórico legado inválido novamente.
    pass
