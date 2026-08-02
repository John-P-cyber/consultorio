"""Integridade dos registros clínicos e assinaturas internas reautenticadas."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from config import SECRET_KEY


ASSINATURA_INTERNA = "interna_reautenticada"


def _data_canonica(valor: datetime | None) -> str | None:
    if valor is None:
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return valor.astimezone(UTC).isoformat(timespec="microseconds")


def hash_payload(payload: dict[str, Any]) -> str:
    canonico = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def assinar_documento(documento_hash: str, autor_usuario_id: int, assinado_em: datetime) -> str:
    mensagem = f"{documento_hash}|usuario:{autor_usuario_id}|{_data_canonica(assinado_em)}"
    return hmac.new(SECRET_KEY.encode("utf-8"), mensagem.encode("utf-8"), hashlib.sha256).hexdigest()


def verificar_assinatura(
    documento_hash: str,
    autor_usuario_id: int | None,
    assinado_em: datetime | None,
    assinatura_hash: str | None,
) -> bool:
    if autor_usuario_id is None or assinado_em is None or not assinatura_hash:
        return False
    esperada = assinar_documento(documento_hash, autor_usuario_id, assinado_em)
    return hmac.compare_digest(assinatura_hash, esperada)


def payload_prontuario(
    *,
    clinica_id: int,
    serie_id: str,
    versao: int,
    versao_anterior_id: int | None,
    paciente_id: int,
    medico_id: int,
    agendamento_id: int | None,
    autor_usuario_id: int | None,
    autor_nome: str,
    autor_crm: str,
    tipo: str,
    conteudo: str,
    motivo_retificacao: str | None,
    criado_em: datetime,
    assinado_em: datetime | None,
    assinatura_tipo: str,
) -> dict[str, Any]:
    return {
        "clinica_id": clinica_id,
        "serie_id": serie_id,
        "versao": versao,
        "versao_anterior_id": versao_anterior_id,
        "paciente_id": paciente_id,
        "medico_id": medico_id,
        "agendamento_id": agendamento_id,
        "autor_usuario_id": autor_usuario_id,
        "autor_nome": autor_nome,
        "autor_crm": autor_crm,
        "tipo": tipo,
        "conteudo": conteudo,
        "motivo_retificacao": motivo_retificacao,
        "criado_em": _data_canonica(criado_em),
        "assinado_em": _data_canonica(assinado_em),
        "assinatura_tipo": assinatura_tipo,
    }


def payload_prescricao(
    *,
    clinica_id: int,
    prontuario_id: int | None,
    paciente_id: int,
    medico_id: int,
    autor_usuario_id: int,
    autor_nome: str,
    autor_crm: str,
    observacoes: str | None,
    itens: list[dict[str, Any]],
    criado_em: datetime,
    assinado_em: datetime,
) -> dict[str, Any]:
    return {
        "clinica_id": clinica_id,
        "prontuario_id": prontuario_id,
        "paciente_id": paciente_id,
        "medico_id": medico_id,
        "autor_usuario_id": autor_usuario_id,
        "autor_nome": autor_nome,
        "autor_crm": autor_crm,
        "observacoes": observacoes,
        "itens": itens,
        "criado_em": _data_canonica(criado_em),
        "assinado_em": _data_canonica(assinado_em),
        "assinatura_tipo": ASSINATURA_INTERNA,
    }


def payload_evento_prescricao(
    *,
    clinica_id: int,
    prescricao_id: int,
    autor_usuario_id: int,
    tipo: str,
    motivo: str,
    criado_em: datetime,
) -> dict[str, Any]:
    return {
        "clinica_id": clinica_id,
        "prescricao_id": prescricao_id,
        "autor_usuario_id": autor_usuario_id,
        "tipo": tipo,
        "motivo": motivo,
        "criado_em": _data_canonica(criado_em),
    }
