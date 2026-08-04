"""Cliente mínimo e privado para a Responses API da OpenAI.

O módulo não conhece o banco nem regras de autorização. Ele apenas oferece ao
modelo as ferramentas já filtradas pelo servidor e devolve suas solicitações ao
executor local. Dados e ações continuam sob controle da aplicação.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, request

from config import (
    AI_ENABLED,
    AI_MAX_OUTPUT_TOKENS,
    AI_MODEL,
    AI_REASONING_EFFORT,
    AI_TIMEOUT_SECONDS,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
)


class AssistenteNaoConfigurado(RuntimeError):
    """A integração ainda não possui uma chave de projeto no ambiente."""


class FalhaAssistente(RuntimeError):
    """Erro seguro da API externa, sem corpo da resposta nem credenciais."""


@dataclass(frozen=True)
class ResultadoAssistente:
    texto: str
    artefatos: list[dict[str, Any]]
    ferramentas_usadas: list[str]


def assistente_disponivel() -> bool:
    return bool(AI_ENABLED and OPENAI_API_KEY)


def _texto_da_resposta(resposta: dict[str, Any]) -> str:
    partes: list[str] = []
    for item in resposta.get("output") or []:
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        for conteudo in item.get("content") or []:
            if conteudo.get("type") == "output_text" and conteudo.get("text"):
                partes.append(str(conteudo["text"]))
    return "\n".join(partes).strip()


def _chamar_responses_api(payload: dict[str, Any]) -> dict[str, Any]:
    if not assistente_disponivel():
        raise AssistenteNaoConfigurado(
            "O assistente ainda não foi ativado. Configure OPENAI_API_KEY no ambiente do servidor."
        )
    requisicao = request.Request(
        f"{OPENAI_BASE_URL}/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "consultorio-assistente/1.0",
        },
        method="POST",
    )
    try:
        with request.urlopen(requisicao, timeout=AI_TIMEOUT_SECONDS) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except error.HTTPError as exc:
        if exc.code == 401:
            mensagem = "A chave da OpenAI foi recusada pelo provedor."
        elif exc.code == 429:
            mensagem = "O limite temporário do assistente foi atingido. Tente novamente em instantes."
        else:
            mensagem = f"A OpenAI não concluiu a solicitação (HTTP {exc.code})."
        raise FalhaAssistente(mensagem) from exc
    except (error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise FalhaAssistente("Não foi possível acessar o serviço de IA neste momento.") from exc


def executar_assistente(
    *,
    instrucoes: str,
    historico: list[dict[str, str]],
    ferramentas: list[dict[str, Any]],
    executar_ferramenta: Callable[[str, dict[str, Any]], dict[str, Any]],
    identificador_seguranca: str,
) -> ResultadoAssistente:
    """Executa no máximo três rodadas e seis chamadas locais por mensagem."""
    entrada: list[dict[str, Any]] = [dict(item) for item in historico]
    artefatos: list[dict[str, Any]] = []
    usadas: list[str] = []
    total_chamadas = 0

    for _ in range(3):
        payload = {
            "model": AI_MODEL,
            "instructions": instrucoes,
            "input": entrada,
            "tools": ferramentas,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "store": False,
            "reasoning": {"effort": AI_REASONING_EFFORT, "context": "current_turn"},
            "text": {"verbosity": "low"},
            "max_output_tokens": AI_MAX_OUTPUT_TOKENS,
            "safety_identifier": identificador_seguranca,
        }
        resposta = _chamar_responses_api(payload)
        saidas = resposta.get("output") or []
        chamadas = [item for item in saidas if item.get("type") == "function_call"]
        if not chamadas:
            texto = _texto_da_resposta(resposta)
            if not texto:
                raise FalhaAssistente("O assistente não produziu uma resposta válida.")
            return ResultadoAssistente(texto=texto, artefatos=artefatos, ferramentas_usadas=usadas)

        entrada.extend(saidas)
        for chamada in chamadas:
            total_chamadas += 1
            if total_chamadas > 6:
                raise FalhaAssistente("A solicitação exigiu operações demais. Divida-a em perguntas menores.")
            nome = str(chamada.get("name") or "")
            usadas.append(nome)
            try:
                argumentos = json.loads(chamada.get("arguments") or "{}")
                if not isinstance(argumentos, dict):
                    raise ValueError
                resultado = executar_ferramenta(nome, argumentos)
            except (TypeError, ValueError, json.JSONDecodeError):
                resultado = {"ok": False, "erro": "Os argumentos da ferramenta são inválidos."}
            artefato = resultado.pop("_artefato", None)
            if isinstance(artefato, dict):
                artefatos.append(artefato)
            entrada.append({
                "type": "function_call_output",
                "call_id": chamada.get("call_id"),
                "output": json.dumps(resultado, ensure_ascii=False, separators=(",", ":")),
            })

    raise FalhaAssistente("O assistente não conseguiu concluir a solicitação com segurança.")
