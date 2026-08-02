"""Primitivas de sessão, TOTP e códigos de recuperação.

Este módulo não acessa o banco nem conhece HTTP. Segredos TOTP são derivados de
uma chave mestra e de um salt aleatório por usuário, evitando armazenar a chave
OATH em texto puro na base de dados.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

from config import MFA_MASTER_KEY


PASSO_TOTP_SEGUNDOS = 30
DIGITOS_TOTP = 6


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_contexto(tipo: str, valor: str | None) -> str | None:
    if not valor:
        return None
    mensagem = f"{tipo}:{valor}".encode("utf-8", errors="replace")
    return hmac.new(MFA_MASTER_KEY.encode("utf-8"), mensagem, hashlib.sha256).hexdigest()


def novo_salt_mfa() -> str:
    return secrets.token_hex(32)


def segredo_totp(clinica_id: int, usuario_id: int, salt: str) -> str:
    mensagem = f"totp:v1:{clinica_id}:{usuario_id}:{salt}".encode("utf-8")
    chave = hmac.new(MFA_MASTER_KEY.encode("utf-8"), mensagem, hashlib.sha256).digest()[:20]
    return base64.b32encode(chave).decode("ascii").rstrip("=")


def _decodificar_base32(segredo: str) -> bytes:
    normalizado = segredo.strip().replace(" ", "").upper()
    normalizado += "=" * ((8 - len(normalizado) % 8) % 8)
    return base64.b32decode(normalizado, casefold=True)


def codigo_totp(segredo: str, contador: int) -> str:
    digest = hmac.new(_decodificar_base32(segredo), struct.pack(">Q", contador), hashlib.sha1).digest()
    deslocamento = digest[-1] & 0x0F
    binario = struct.unpack(">I", digest[deslocamento:deslocamento + 4])[0] & 0x7FFFFFFF
    return str(binario % (10 ** DIGITOS_TOTP)).zfill(DIGITOS_TOTP)


def gerar_codigo_totp(segredo: str, quando: datetime | None = None) -> str:
    instante = quando or datetime.now(UTC)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=UTC)
    contador = int(instante.timestamp()) // PASSO_TOTP_SEGUNDOS
    return codigo_totp(segredo, contador)


def verificar_codigo_totp(
    segredo: str,
    codigo: str,
    *,
    ultimo_contador: int | None = None,
    quando: datetime | None = None,
    janela: int = 1,
) -> int | None:
    codigo = codigo.strip().replace(" ", "")
    if len(codigo) != DIGITOS_TOTP or not codigo.isdigit():
        return None
    instante = quando or datetime.now(UTC)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=UTC)
    atual = int(instante.timestamp()) // PASSO_TOTP_SEGUNDOS
    for deslocamento in (0, -1, 1):
        if abs(deslocamento) > janela:
            continue
        contador = atual + deslocamento
        if ultimo_contador is not None and contador <= ultimo_contador:
            continue
        if hmac.compare_digest(codigo_totp(segredo, contador), codigo):
            return contador
    return None


def uri_totp(segredo: str, *, clinica_nome: str, email: str, emissor: str) -> str:
    rotulo = quote(f"{clinica_nome}:{email}", safe="")
    parametros = urlencode({
        "secret": segredo,
        "issuer": emissor,
        "algorithm": "SHA1",
        "digits": DIGITOS_TOTP,
        "period": PASSO_TOTP_SEGUNDOS,
    })
    return f"otpauth://totp/{rotulo}?{parametros}"


def gerar_codigos_recuperacao(quantidade: int = 10) -> list[str]:
    codigos: list[str] = []
    for _ in range(quantidade):
        bruto = base64.b32encode(secrets.token_bytes(10)).decode("ascii").rstrip("=")
        codigos.append("-".join(bruto[indice:indice + 4] for indice in range(0, len(bruto), 4)))
    return codigos


def normalizar_codigo_recuperacao(codigo: str) -> str:
    return "".join(caractere for caractere in codigo.upper() if caractere.isalnum())


def hash_codigo_recuperacao(usuario_id: int, codigo: str) -> str:
    normalizado = normalizar_codigo_recuperacao(codigo)
    mensagem = f"recuperacao:v1:{usuario_id}:{normalizado}".encode("utf-8")
    return hmac.new(MFA_MASTER_KEY.encode("utf-8"), mensagem, hashlib.sha256).hexdigest()
