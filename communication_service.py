"""Gateways de comunicação externa.

As credenciais pertencem ao ambiente da aplicação. O banco guarda apenas a
configuração não secreta de cada clínica e o histórico dos envios.
"""
from __future__ import annotations

import json
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from urllib import error, request

from config import (
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_TIMEOUT_SECONDS,
    SMTP_USERNAME,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_API_VERSION,
)


class ProvedorNaoConfigurado(RuntimeError):
    """Indica que o canal ainda não possui credenciais no ambiente."""


class FalhaNoProvedor(RuntimeError):
    """Erro seguro para persistência; não inclui credenciais do provedor."""


@dataclass(frozen=True)
class ResultadoEnvio:
    identificador: str | None = None


def smtp_disponivel() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)


def whatsapp_disponivel() -> bool:
    return bool(WHATSAPP_ACCESS_TOKEN)


def enviar_email(
    *,
    destinatario: str,
    assunto: str,
    texto: str,
    html: str | None = None,
    remetente_nome: str | None = None,
    remetente_email: str | None = None,
    responder_para: str | None = None,
) -> ResultadoEnvio:
    if not smtp_disponivel():
        raise ProvedorNaoConfigurado("O provedor SMTP ainda não foi configurado no servidor.")

    mensagem = EmailMessage()
    mensagem["Message-ID"] = make_msgid(domain=(remetente_email or SMTP_FROM).split("@")[-1])
    mensagem["Subject"] = assunto
    mensagem["From"] = formataddr((remetente_nome or "Clínica Saúde", remetente_email or SMTP_FROM))
    mensagem["To"] = destinatario
    if responder_para:
        mensagem["Reply-To"] = responder_para
    mensagem.set_content(texto)
    if html:
        mensagem.add_alternative(html, subtype="html")

    try:
        classe_smtp = smtplib.SMTP_SSL if SMTP_USE_SSL else smtplib.SMTP
        with classe_smtp(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as servidor:
            if SMTP_USE_TLS:
                servidor.starttls()
            if SMTP_USERNAME and SMTP_PASSWORD:
                servidor.login(SMTP_USERNAME, SMTP_PASSWORD)
            recusados = servidor.send_message(mensagem)
            if recusados:
                raise FalhaNoProvedor("O servidor SMTP recusou o destinatário.")
    except ProvedorNaoConfigurado:
        raise
    except (OSError, smtplib.SMTPException) as exc:
        raise FalhaNoProvedor(f"Falha no envio SMTP ({type(exc).__name__}).") from exc
    return ResultadoEnvio(identificador=mensagem["Message-ID"])


def normalizar_telefone_whatsapp(valor: str, codigo_pais: str) -> str:
    possui_prefixo_internacional = valor.strip().startswith("+")
    telefone = "".join(caractere for caractere in valor if caractere.isdigit())
    pais = "".join(caractere for caractere in codigo_pais if caractere.isdigit())
    if not pais:
        raise ValueError("Código do país inválido para WhatsApp.")
    if len(telefone) <= 11 and not possui_prefixo_internacional:
        telefone = f"{pais}{telefone}"
    if len(telefone) < 10 or len(telefone) > 15:
        raise ValueError("Telefone inválido para WhatsApp; informe país, DDD e número.")
    return telefone


def enviar_template_whatsapp(
    *,
    phone_number_id: str,
    destinatario: str,
    template: str,
    idioma: str,
    parametros: list[str],
    codigo_pais: str,
) -> ResultadoEnvio:
    if not whatsapp_disponivel():
        raise ProvedorNaoConfigurado("O token da API oficial do WhatsApp ainda não foi configurado.")
    if not phone_number_id.strip():
        raise ProvedorNaoConfigurado("A clínica ainda não configurou o identificador do número do WhatsApp.")

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalizar_telefone_whatsapp(destinatario, codigo_pais),
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": idioma},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": str(valor)} for valor in parametros],
            }],
        },
    }
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id.strip()}/messages"
    requisicao = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(requisicao, timeout=20) as resposta:
            conteudo = json.loads(resposta.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise FalhaNoProvedor(f"A API oficial do WhatsApp recusou o envio (HTTP {exc.code}).") from exc
    except (error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise FalhaNoProvedor(f"Falha ao acessar a API oficial do WhatsApp ({type(exc).__name__}).") from exc

    mensagens = conteudo.get("messages") or []
    if not mensagens or not mensagens[0].get("id"):
        raise FalhaNoProvedor("A API oficial do WhatsApp não confirmou o envio.")
    return ResultadoEnvio(identificador=str(mensagens[0]["id"]))
