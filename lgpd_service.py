"""Serviços de privacidade e auditoria sem armazenar conteúdo clínico nos logs."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy.orm import Session

import models
from config import PRIVACIDADE_VERSAO, SECRET_KEY, TERMOS_VERSAO


FINALIDADES_DOCUMENTOS = {
    "termos_uso": "Formalizar as regras de uso e a execução do serviço contratado.",
    "politica_privacidade": "Registrar a ciência sobre o tratamento de dados pessoais e dados de saúde.",
    "comunicacoes": "Receber lembretes e comunicações não essenciais da clínica.",
}

BASES_LEGAIS_DOCUMENTOS = {
    "termos_uso": "execucao_de_contrato",
    "politica_privacidade": "ciencia_transparencia",
    "comunicacoes": "consentimento",
}


def hash_documento(documento_tipo: str, versao: str) -> str:
    conteudo_canonico = f"{documento_tipo}|{versao}|{FINALIDADES_DOCUMENTOS[documento_tipo]}"
    return hashlib.sha256(conteudo_canonico.encode("utf-8")).hexdigest()


def validar_aceite_documentos(
    aceita_termos: bool,
    ciente_privacidade: bool,
    termos_versao: str,
    privacidade_versao: str,
) -> str | None:
    if not aceita_termos or not ciente_privacidade:
        return "É necessário aceitar os Termos de Uso e declarar ciência da Política de Privacidade."
    if termos_versao != TERMOS_VERSAO or privacidade_versao != PRIVACIDADE_VERSAO:
        return "Os documentos jurídicos foram atualizados. Recarregue a página e revise as versões atuais."
    return None


def dados_requisicao(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    endereco_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return endereco_ip, user_agent[:512] if user_agent else None


def _payload_auditoria(
    *,
    clinica_id: int,
    ator_referencia: str,
    ator_role: str,
    acao: str,
    recurso: str,
    registro_id: int | None,
    paciente_id: int | None,
    campos: str | None,
    detalhes: str | None,
    endereco_ip: str | None,
    criado_em: datetime,
    hash_anterior: str | None,
) -> str:
    if criado_em.tzinfo is None:
        criado_em = criado_em.replace(tzinfo=UTC)
    return "|".join(
        str(valor or "")
        for valor in (
            clinica_id,
            ator_referencia,
            ator_role,
            acao,
            recurso,
            registro_id,
            paciente_id,
            campos,
            detalhes,
            endereco_ip,
            criado_em.isoformat(timespec="microseconds"),
            hash_anterior,
        )
    )


def criar_consentimentos_obrigatorios(
    *,
    clinica_id: int,
    usuario_id: int,
    paciente_id: int | None,
    request: Request | None,
) -> list[models.Consentimento]:
    endereco_ip, user_agent = dados_requisicao(request)
    agora = datetime.now(UTC)
    return [
        models.Consentimento(
            clinica_id=clinica_id,
            usuario_id=usuario_id,
            paciente_id=paciente_id,
            documento_tipo=documento_tipo,
            versao=versao,
            finalidade=FINALIDADES_DOCUMENTOS[documento_tipo],
            base_legal=BASES_LEGAIS_DOCUMENTOS[documento_tipo],
            aceito_em=agora,
            endereco_ip=endereco_ip,
            user_agent=user_agent,
            documento_hash=hash_documento(documento_tipo, versao),
        )
        for documento_tipo, versao in (
            ("termos_uso", TERMOS_VERSAO),
            ("politica_privacidade", PRIVACIDADE_VERSAO),
        )
    ]


def registrar_auditoria(
    db: Session,
    *,
    request: Request | None,
    usuario: models.Usuario,
    acao: str,
    recurso: str,
    registro_id: int | None = None,
    paciente_id: int | None = None,
    campos: list[str] | None = None,
    detalhes: dict | None = None,
) -> models.RegistroAuditoria:
    """Acrescenta um log metadado à transação atual; nunca recebe conteúdo clínico."""
    agora = datetime.now(UTC)
    endereco_ip, user_agent = dados_requisicao(request)
    anterior = (
        db.query(models.RegistroAuditoria.assinatura)
        .filter(models.RegistroAuditoria.clinica_id == usuario.clinica_id)
        .order_by(models.RegistroAuditoria.id.desc())
        .first()
    )
    hash_anterior = anterior[0] if anterior else None
    campos_texto = ",".join(sorted(set(campos or []))) or None
    detalhes_texto = json.dumps(detalhes, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if detalhes else None
    ator_referencia = f"usuario:{usuario.id}"
    payload = _payload_auditoria(
        clinica_id=usuario.clinica_id,
        ator_referencia=ator_referencia,
        ator_role=usuario.role,
        acao=acao,
        recurso=recurso,
        registro_id=registro_id,
        paciente_id=paciente_id,
        campos=campos_texto,
        detalhes=detalhes_texto,
        endereco_ip=endereco_ip,
        criado_em=agora,
        hash_anterior=hash_anterior,
    )
    assinatura = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    registro = models.RegistroAuditoria(
        clinica_id=usuario.clinica_id,
        ator_usuario_id=usuario.id,
        ator_referencia=ator_referencia,
        ator_role=usuario.role,
        acao=acao,
        recurso=recurso,
        registro_id=registro_id,
        paciente_id=paciente_id,
        campos=campos_texto,
        detalhes=detalhes_texto,
        endereco_ip=endereco_ip,
        user_agent=user_agent,
        criado_em=agora,
        hash_anterior=hash_anterior,
        assinatura=assinatura,
    )
    db.add(registro)
    return registro


def verificar_integridade_auditoria(registros: list[models.RegistroAuditoria]) -> tuple[bool, int | None]:
    anterior = None
    for registro in registros:
        payload = _payload_auditoria(
            clinica_id=registro.clinica_id,
            ator_referencia=registro.ator_referencia,
            ator_role=registro.ator_role,
            acao=registro.acao,
            recurso=registro.recurso,
            registro_id=registro.registro_id,
            paciente_id=registro.paciente_id,
            campos=registro.campos,
            detalhes=registro.detalhes,
            endereco_ip=registro.endereco_ip,
            criado_em=registro.criado_em,
            hash_anterior=registro.hash_anterior,
        )
        assinatura_esperada = hmac.new(
            SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if registro.hash_anterior != anterior or not hmac.compare_digest(registro.assinatura, assinatura_esperada):
            return False, registro.id
        anterior = registro.assinatura
    return True, None
