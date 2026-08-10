"""Cliente mínimo e privado para a Responses API da OpenAI.

O módulo não conhece o banco nem regras de autorização. Ele apenas oferece ao
modelo as ferramentas já filtradas pelo servidor e devolve suas solicitações ao
executor local. Dados e ações continuam sob controle da aplicação.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable
from urllib import error, request

from config import (
    AI_ENABLED,
    AI_MAX_OUTPUT_TOKENS,
    AI_MODEL,
    AI_PROVIDER,
    AI_REASONING_EFFORT,
    AI_TIMEOUT_SECONDS,
    GEMINI_API_KEY,
    GEMINI_BASE_URL,
    GEMINI_MODEL,
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
    if not AI_ENABLED:
        return False
    if AI_PROVIDER == "local":
        return True
    if AI_PROVIDER == "gemini":
        return bool(GEMINI_API_KEY)
    return bool(OPENAI_API_KEY)


def modelo_assistente_ativo() -> str | None:
    if not assistente_disponivel():
        return None
    if AI_PROVIDER == "local":
        return "local-gratuito"
    return GEMINI_MODEL if AI_PROVIDER == "gemini" else AI_MODEL


def _normalizar_texto(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(caractere for caractere in texto if not unicodedata.combining(caractere)).lower()


def _data_mencionada(texto: str) -> date | None:
    normalizado = _normalizar_texto(texto)
    hoje = date.today()
    if "depois de amanha" in normalizado:
        return hoje + timedelta(days=2)
    if "amanha" in normalizado:
        return hoje + timedelta(days=1)
    if "hoje" in normalizado:
        return hoje

    padrao_iso = re.search(r"\b(20\d{2})-(0?[1-9]|1[0-2])-([0-2]?\d|3[01])\b", normalizado)
    if padrao_iso:
        try:
            return date(int(padrao_iso.group(1)), int(padrao_iso.group(2)), int(padrao_iso.group(3)))
        except ValueError:
            return None

    padrao_br = re.search(r"\b([0-2]?\d|3[01])/(0?[1-9]|1[0-2])(?:/(20\d{2}))?\b", normalizado)
    if padrao_br:
        ano = int(padrao_br.group(3) or hoje.year)
        try:
            resultado = date(ano, int(padrao_br.group(2)), int(padrao_br.group(1)))
            if not padrao_br.group(3) and resultado < hoje:
                resultado = resultado.replace(year=ano + 1)
            return resultado
        except ValueError:
            return None

    meses = {
        "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
        "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    }
    padrao_extenso = re.search(
        r"\b([0-2]?\d|3[01])\s+de\s+(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)(?:\s+de)?\s+(20\d{2})\b",
        normalizado,
    )
    if padrao_extenso:
        try:
            return date(int(padrao_extenso.group(3)), meses[padrao_extenso.group(2)], int(padrao_extenso.group(1)))
        except ValueError:
            return None
    return None


def _hora_mencionada(texto: str) -> tuple[int, int] | None:
    normalizado = _normalizar_texto(texto)
    encontrada = re.search(r"\b(?:as\s+)?([01]?\d|2[0-3])(?:h|:)([0-5]\d)\b", normalizado)
    if encontrada:
        return int(encontrada.group(1)), int(encontrada.group(2))
    encontrada = re.search(r"\b(?:as\s+)([01]?\d|2[0-3])\s*horas?\b", normalizado)
    if encontrada:
        return int(encontrada.group(1)), 0
    return None


def _quantidade_mencionada(texto: str, unidade: str, padrao: int, limite: int) -> int:
    normalizado = _normalizar_texto(texto)
    encontrada = re.search(rf"\b(\d{{1,2}})\s+{unidade}", normalizado)
    if encontrada:
        return max(1, min(int(encontrada.group(1)), limite))
    palavras = {
        "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
        "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12,
    }
    for palavra, valor in palavras.items():
        if re.search(rf"\b{palavra}\s+{unidade}", normalizado):
            return min(valor, limite)
    return padrao


def _medico_mencionado(texto: str, medicos: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalizado = _normalizar_texto(texto)
    identificador = re.search(r"\b(?:medic[oa]|id)\s*#?\s*(\d+)\b", normalizado)
    if identificador:
        procurado = int(identificador.group(1))
        return next((item for item in medicos if item.get("id") == procurado), None)
    for medico in medicos:
        nome = _normalizar_texto(medico.get("nome"))
        nome_sem_titulo = re.sub(r"\b(dr|dra|doutor|doutora)\.?\s*", "", nome).strip()
        if nome and (nome in normalizado or (nome_sem_titulo and nome_sem_titulo in normalizado)):
            return medico
    return medicos[0] if len(medicos) == 1 else None


def _formatar_medicos(resultado: dict[str, Any]) -> str:
    medicos = resultado.get("medicos") or []
    if not medicos:
        return "Ainda não há médicos cadastrados nesta clínica."
    linhas = ["Estes são os médicos cadastrados na sua clínica:"]
    for medico in medicos:
        tipos = ", ".join(
            f'{tipo.get("nome")} (tipo #{tipo.get("id")}, {tipo.get("duracao_minutos")} min)'
            for tipo in medico.get("tipos_consulta") or []
        ) or "nenhum tipo de consulta ativo"
        linhas.append(
            f'• Médico #{medico.get("id")}: {medico.get("nome")} — {medico.get("especialidade")}. {tipos}.'
        )
    linhas.append("Para ver vagas, diga o nome ou o número do médico e a data desejada.")
    return "\n".join(linhas)


def _formatar_ajuda(resultado: dict[str, Any]) -> str:
    guias = resultado.get("guias") or []
    if not guias:
        return "Não encontrei essa orientação. Tente perguntar sobre acesso, agenda, consultas, segurança ou privacidade."
    if len(guias) == 1:
        return str(guias[0].get("orientacao") or "")
    linhas = ["Posso ajudar nestes assuntos:"]
    for guia in guias[:8]:
        linhas.append(f'• {str(guia.get("topico") or "").title()}: {guia.get("orientacao") or ""}')
    return "\n".join(linhas)


def _executar_assistente_local(
    *,
    historico: list[dict[str, str]],
    ferramentas: list[dict[str, Any]],
    executar_ferramenta: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> ResultadoAssistente:
    """Assistente determinístico: gratuito, privado e limitado às operações conhecidas."""
    mensagem = next(
        (str(item.get("content") or "") for item in reversed(historico) if item.get("role") == "user"),
        "",
    )
    texto = _normalizar_texto(mensagem)
    permitidas = {str(item.get("name")) for item in ferramentas}
    usadas: list[str] = []
    artefatos: list[dict[str, Any]] = []

    def chamar(nome: str, argumentos: dict[str, Any]) -> dict[str, Any]:
        usadas.append(nome)
        resultado = dict(executar_ferramenta(nome, argumentos))
        artefato = resultado.pop("_artefato", None)
        if isinstance(artefato, dict):
            artefatos.append(artefato)
        return resultado

    if any(termo in texto for termo in ("dor no peito", "falta de ar", "suicidio", "emergencia medica")):
        resposta = (
            "Não posso avaliar urgências ou fornecer diagnóstico. Procure imediatamente o serviço de emergência "
            "da sua região ou um profissional de saúde."
        )
        return ResultadoAssistente(resposta, artefatos, usadas)

    if any(termo in texto for termo in ("senha de outro", "prontuario de outro", "dados de outro paciente")):
        return ResultadoAssistente(
            "Não posso consultar credenciais, prontuários ou dados pessoais de outra pessoa.", artefatos, usadas
        )

    if "listar_medicos_da_clinica" in permitidas:
        quer_agendar = any(termo in texto for termo in ("agendar", "marcar consulta", "marque", "quero marcar"))
        quer_horarios = any(termo in texto for termo in ("horario", "disponibilidade", "disponivel", "vaga"))
        quer_consultas = any(termo in texto for termo in ("minhas consultas", "meus agendamentos", "proxima consulta"))

        if quer_consultas and "listar_meus_agendamentos" in permitidas:
            resultado = chamar("listar_meus_agendamentos", {"limite": 10})
            agendamentos = resultado.get("agendamentos") or []
            if not agendamentos:
                resposta = "Você não possui consultas futuras confirmadas."
            else:
                linhas = ["Suas próximas consultas são:"]
                for item in agendamentos:
                    momento = datetime.fromisoformat(item["data_hora"]).strftime("%d/%m/%Y às %H:%M")
                    linhas.append(
                        f'• {momento} — {item.get("medico")}, {item.get("tipo")} ({item.get("status")}).'
                    )
                resposta = "\n".join(linhas)
            return ResultadoAssistente(resposta, artefatos, usadas)

        if quer_agendar or quer_horarios:
            lista = chamar("listar_medicos_da_clinica", {})
            medicos = lista.get("medicos") or []
            medico = _medico_mencionado(mensagem, medicos)
            if not medico:
                return ResultadoAssistente(
                    _formatar_medicos(lista) + "\nHá mais de uma opção; indique qual médico deseja.",
                    artefatos,
                    usadas,
                )
            data_escolhida = _data_mencionada(mensagem)
            if quer_agendar and data_escolhida is None:
                return ResultadoAssistente(
                    f'Informe a data e a hora exatas para marcar com {medico.get("nome")}, por exemplo: '
                    f'"marque com o médico #{medico.get("id")} em 15/08/2026 às 09:00".',
                    artefatos,
                    usadas,
                )
            inicio = data_escolhida or date.today()
            dias = 1 if quer_agendar else _quantidade_mencionada(mensagem, "dias?", 7, 14)
            tipo_id_encontrado = re.search(r"\btipo\s*#?\s*(\d+)\b", texto)
            tipo_id = int(tipo_id_encontrado.group(1)) if tipo_id_encontrado else None
            horarios = chamar("buscar_horarios_disponiveis", {
                "medico_id": medico["id"], "data_inicio": inicio.isoformat(), "dias": dias,
                "tipo_consulta_id": tipo_id,
            })
            if not horarios.get("ok"):
                return ResultadoAssistente(str(horarios.get("erro") or "Não foi possível consultar a agenda."), artefatos, usadas)

            disponibilidade = horarios.get("disponibilidade") or []
            hora = _hora_mencionada(mensagem)
            if quer_agendar:
                if hora is None:
                    return ResultadoAssistente(
                        f'Informe também a hora exata para marcar com {medico.get("nome")}.', artefatos, usadas
                    )
                hora_texto = f"{hora[0]:02d}:{hora[1]:02d}"
                disponiveis_no_dia = next(
                    (item.get("horarios") or [] for item in disponibilidade if item.get("data") == inicio.isoformat()),
                    [],
                )
                if hora_texto not in disponiveis_no_dia:
                    opcoes = ", ".join(disponiveis_no_dia[:12]) or "nenhum horário"
                    return ResultadoAssistente(
                        f"Esse horário não está disponível. Opções em {inicio.strftime('%d/%m/%Y')}: {opcoes}.",
                        artefatos,
                        usadas,
                    )
                marcado = chamar("agendar_minha_consulta", {
                    "medico_id": medico["id"],
                    "data_hora": datetime.combine(inicio, datetime.min.time()).replace(
                        hour=hora[0], minute=hora[1]
                    ).isoformat(timespec="minutes"),
                    "tipo_consulta_id": tipo_id,
                })
                if not marcado.get("ok"):
                    return ResultadoAssistente(str(marcado.get("erro") or "Não foi possível agendar."), artefatos, usadas)
                item = marcado["agendamento"]
                momento = datetime.fromisoformat(item["data_hora"]).strftime("%d/%m/%Y às %H:%M")
                return ResultadoAssistente(
                    f'Sua consulta com {item.get("medico")} foi confirmada para {momento}. O médico será notificado.',
                    artefatos,
                    usadas,
                )

            if not disponibilidade:
                resposta = f'Não encontrei horários livres para {medico.get("nome")} nesse período.'
            else:
                linhas = [f'Horários disponíveis para {medico.get("nome")}:']
                for item in disponibilidade:
                    data_formatada = date.fromisoformat(item["data"]).strftime("%d/%m/%Y")
                    linhas.append(f'• {data_formatada}: {", ".join(item.get("horarios") or [])}')
                linhas.append(
                    f'Para agendar, diga: "marque com o médico #{medico.get("id")} em DD/MM/AAAA às HH:MM".'
                )
                resposta = "\n".join(linhas)
            return ResultadoAssistente(resposta, artefatos, usadas)

        if any(termo in texto for termo in ("medico", "medicos", "especialista", "especialidade")):
            return ResultadoAssistente(_formatar_medicos(chamar("listar_medicos_da_clinica", {})), artefatos, usadas)

    if "gerar_grafico_meus_atendimentos" in permitidas and any(
        termo in texto for termo in ("grafico", "quantidade de pacientes", "pacientes atendidos", "indicadores")
    ):
        meses = _quantidade_mencionada(mensagem, "mes(?:es)?", 6, 12)
        resultado = chamar("gerar_grafico_meus_atendimentos", {"meses": meses})
        total = resultado.get("total_pacientes_no_periodo", 0)
        return ResultadoAssistente(
            f"O gráfico mostra {total} paciente(s) distinto(s) atendido(s) nos últimos {meses} meses.",
            artefatos,
            usadas,
        )

    if "consultar_minha_agenda" in permitidas and any(
        termo in texto for termo in ("minha agenda", "minhas consultas", "meus atendimentos", "agenda de hoje")
    ):
        inicio = _data_mencionada(mensagem) or date.today()
        dias = _quantidade_mencionada(mensagem, "dias?", 7, 31)
        resultado = chamar("consultar_minha_agenda", {"data_inicio": inicio.isoformat(), "dias": dias})
        agenda = resultado.get("agenda") or []
        if not agenda:
            resposta = "Você não possui atendimentos nesse período."
        else:
            linhas = ["Sua agenda no período:"]
            for item in agenda:
                momento = datetime.fromisoformat(item["data_hora"]).strftime("%d/%m/%Y às %H:%M")
                linhas.append(f'• {momento} — {item.get("tipo")} ({item.get("status")}).')
            resposta = "\n".join(linhas)
        return ResultadoAssistente(resposta, artefatos, usadas)

    if "consultar_resumo_operacional" in permitidas and any(
        termo in texto for termo in ("resumo", "indicadores", "estatistica", "quantos pacientes", "quantos medicos")
    ):
        meses = _quantidade_mencionada(mensagem, "mes(?:es)?", 6, 12)
        resultado = chamar("consultar_resumo_operacional", {"meses": meses})
        consultas = resultado.get("consultas") or {}
        resposta = (
            f'Resumo da clínica: {resultado.get("medicos_ativos", 0)} médico(s), '
            f'{resultado.get("pacientes_cadastrados", 0)} paciente(s), '
            f'{consultas.get("Confirmado", 0)} consulta(s) confirmada(s), '
            f'{consultas.get("Atendido", 0)} atendida(s) e {consultas.get("Cancelado", 0)} cancelada(s).'
        )
        return ResultadoAssistente(resposta, artefatos, usadas)

    if "consultar_ajuda_plataforma" in permitidas:
        ajuda = chamar("consultar_ajuda_plataforma", {"topico": mensagem})
        resposta = _formatar_ajuda(ajuda)
        if not any(termo in texto for termo in ("como", "onde", "ajuda", "senha", "agenda", "cadastro", "privacidade", "seguranca")):
            resposta = "Sou o assistente gratuito do portal e respondo sobre o funcionamento do sistema.\n" + resposta
        return ResultadoAssistente(resposta, artefatos, usadas)

    return ResultadoAssistente("Não encontrei uma operação disponível para o seu perfil.", artefatos, usadas)


def _chamar_gemini_chat(payload: dict[str, Any]) -> dict[str, Any]:
    if AI_PROVIDER != "gemini" or not assistente_disponivel():
        raise AssistenteNaoConfigurado(
            "O provedor Gemini ainda não foi ativado. Configure AI_PROVIDER=gemini e GEMINI_API_KEY."
        )
    requisicao = request.Request(
        f"{GEMINI_BASE_URL}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GEMINI_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "consultorio-assistente/1.0",
        },
        method="POST",
    )
    try:
        with request.urlopen(requisicao, timeout=AI_TIMEOUT_SECONDS) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except error.HTTPError as exc:
        if exc.code in {401, 403}:
            mensagem = "A chave do Gemini foi recusada ou não possui permissão para este modelo."
        elif exc.code == 429:
            mensagem = "O limite gratuito do Gemini foi atingido. Tente novamente mais tarde."
        elif exc.code == 400:
            mensagem = "O Gemini recusou a configuração da solicitação. Verifique o modelo e a chave."
        else:
            mensagem = f"O Gemini não concluiu a solicitação (HTTP {exc.code})."
        raise FalhaAssistente(mensagem) from exc
    except (error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise FalhaAssistente("Não foi possível acessar o Gemini neste momento.") from exc


def _schema_compativel_gemini(valor: Any) -> Any:
    if isinstance(valor, list):
        return [_schema_compativel_gemini(item) for item in valor]
    if not isinstance(valor, dict):
        return valor
    convertido = {
        chave: _schema_compativel_gemini(conteudo)
        for chave, conteudo in valor.items()
        if chave != "additionalProperties"
    }
    tipos = convertido.get("type")
    if isinstance(tipos, list) and "null" in tipos:
        restantes = [item for item in tipos if item != "null"]
        convertido["type"] = restantes[0] if len(restantes) == 1 else restantes
        convertido["nullable"] = True
    return convertido


def _ferramentas_compativeis_gemini(ferramentas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "type": "function",
        "function": {
            "name": ferramenta["name"],
            "description": ferramenta.get("description") or "",
            "parameters": _schema_compativel_gemini(ferramenta.get("parameters") or {}),
        },
    } for ferramenta in ferramentas]


def _texto_mensagem_chat(mensagem: dict[str, Any]) -> str:
    conteudo = mensagem.get("content")
    if isinstance(conteudo, str):
        return conteudo.strip()
    if isinstance(conteudo, list):
        return "\n".join(
            str(item.get("text") or "") for item in conteudo
            if isinstance(item, dict) and item.get("text")
        ).strip()
    return ""


def _executar_assistente_gemini(
    *,
    instrucoes: str,
    historico: list[dict[str, str]],
    ferramentas: list[dict[str, Any]],
    executar_ferramenta: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> ResultadoAssistente:
    mensagens: list[dict[str, Any]] = [{"role": "system", "content": instrucoes}]
    mensagens.extend({"role": item["role"], "content": item["content"]} for item in historico)
    ferramentas_gemini = _ferramentas_compativeis_gemini(ferramentas)
    artefatos: list[dict[str, Any]] = []
    usadas: list[str] = []
    total_chamadas = 0

    for _ in range(3):
        esforco = AI_REASONING_EFFORT if AI_REASONING_EFFORT in {"low", "medium", "high"} else "low"
        payload = {
            "model": GEMINI_MODEL,
            "messages": mensagens,
            "tools": ferramentas_gemini,
            "tool_choice": "auto",
            "reasoning_effort": esforco,
            "max_tokens": AI_MAX_OUTPUT_TOKENS,
        }
        resposta = _chamar_gemini_chat(payload)
        escolhas = resposta.get("choices") or []
        if not escolhas or not isinstance(escolhas[0].get("message"), dict):
            raise FalhaAssistente("O Gemini não produziu uma resposta válida.")
        mensagem_modelo = escolhas[0]["message"]
        chamadas = mensagem_modelo.get("tool_calls") or []
        if not chamadas:
            texto = _texto_mensagem_chat(mensagem_modelo)
            if not texto:
                raise FalhaAssistente("O Gemini não produziu uma resposta em texto.")
            return ResultadoAssistente(texto=texto, artefatos=artefatos, ferramentas_usadas=usadas)

        mensagens.append(mensagem_modelo)
        for chamada in chamadas:
            total_chamadas += 1
            if total_chamadas > 6:
                raise FalhaAssistente("A solicitação exigiu operações demais. Divida-a em perguntas menores.")
            funcao = chamada.get("function") or {}
            nome = str(funcao.get("name") or "")
            usadas.append(nome)
            try:
                argumentos = json.loads(funcao.get("arguments") or "{}")
                if not isinstance(argumentos, dict):
                    raise ValueError
                resultado = executar_ferramenta(nome, argumentos)
            except (TypeError, ValueError, json.JSONDecodeError):
                resultado = {"ok": False, "erro": "Os argumentos da ferramenta são inválidos."}
            artefato = resultado.pop("_artefato", None)
            if isinstance(artefato, dict):
                artefatos.append(artefato)
            mensagens.append({
                "role": "tool",
                "tool_call_id": chamada.get("id"),
                "name": nome,
                "content": json.dumps(resultado, ensure_ascii=False, separators=(",", ":")),
            })

    raise FalhaAssistente("O Gemini não conseguiu concluir a solicitação com segurança.")


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
    if AI_PROVIDER != "openai" or not assistente_disponivel():
        raise AssistenteNaoConfigurado(
            "O provedor OpenAI ainda não foi ativado. Configure AI_PROVIDER=openai e OPENAI_API_KEY."
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
    if not assistente_disponivel():
        raise AssistenteNaoConfigurado("O assistente foi desativado pelo administrador da plataforma.")
    if AI_PROVIDER == "local":
        return _executar_assistente_local(
            historico=historico,
            ferramentas=ferramentas,
            executar_ferramenta=executar_ferramenta,
        )
    if AI_PROVIDER == "gemini":
        return _executar_assistente_gemini(
            instrucoes=instrucoes,
            historico=historico,
            ferramentas=ferramentas,
            executar_ferramenta=executar_ferramenta,
        )

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
