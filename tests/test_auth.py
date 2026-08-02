import os
from pathlib import Path

import pytest


ARQUIVO_TESTE = Path("test_db.sqlite")
if ARQUIVO_TESTE.exists():
    ARQUIVO_TESTE.unlink()

os.environ["APP_ENV"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-with-at-least-32-characters"
os.environ["MFA_MASTER_KEY"] = "test-mfa-master-key-different-and-at-least-32"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "15"
os.environ["DATABASE_URL"] = "sqlite:///./test_db.sqlite"
os.environ["CLINIC_PROVISIONING_TOKEN"] = "provisionamento-seguro-de-teste"
os.environ["TERMOS_VERSAO"] = "2026-08-01"
os.environ["PRIVACIDADE_VERSAO"] = "2026-08-01"

from fastapi.testclient import TestClient

import main


def test_endpoints_operacionais_e_request_id(client):
    live = client.get("/health/live", headers={"X-Request-ID": "check-123"})
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert live.headers["X-Request-ID"] == "check-123"

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok"}

    invalido = client.get("/health/live", headers={"X-Request-ID": "valor com espaco"})
    assert invalido.status_code == 200
    assert invalido.headers["X-Request-ID"] != "valor com espaco"
    assert len(invalido.headers["X-Request-ID"]) == 32

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "clinica_http_requests_total" in metrics.text
    assert "clinica_build_info" in metrics.text
    assert "clinica_database_ready 1.0" in metrics.text


def test_documentos_lgpd_e_assets_frontend_sao_publicos(client):
    documentos = client.get("/lgpd/documentos")
    assert documentos.status_code == 200
    assert documentos.json()["termos_versao"] == "2026-08-01"
    assert documentos.json()["privacidade_versao"] == "2026-08-01"

    cadastro = client.get("/register.html")
    assert cadastro.status_code == 200
    assert "cdn.tailwindcss.com" not in cadastro.text
    assert 'href="tailwind.css"' in cadastro.text

    estilos = client.get("/tailwind.css")
    assert estilos.status_code == 200
    assert estilos.headers["content-type"].startswith("text/css")


@pytest.fixture()
def client():
    main.models.Base.metadata.drop_all(bind=main.engine)
    main.models.Base.metadata.create_all(bind=main.engine)
    main.tentativas_login.clear()
    with TestClient(main.app) as test_client:
        yield test_client


def paciente_payload(email="paciente@example.com", cpf="52998224725", clinica_slug="clinica-a"):
    return {
        "clinica_slug": clinica_slug,
        "email": email,
        "password": "senha-forte-123",
        "role": "paciente",
        "aceita_termos": True,
        "ciente_privacidade": True,
        "termos_versao": "2026-08-01",
        "privacidade_versao": "2026-08-01",
        "nome": "Maria da Silva",
        "cpf": cpf,
        "telefone": "11999998888",
        "data_nascimento": "1990-01-15",
        "endereco_rua": "Rua das Flores",
        "endereco_numero": "100",
        "endereco_bairro": "Centro",
        "endereco_cidade": "São Paulo",
        "endereco_estado": "SP",
        "endereco_cep": "01000-000",
    }


def provisionar_clinica(client, slug="clinica-a", nome="Clínica A", admin_email="admin@example.com"):
    resposta = client.post("/auth/registrar-clinica", json={
        "nome": nome,
        "slug": slug,
        "email_admin": admin_email,
        "password": "senha-admin-123",
        "provisioning_token": "provisionamento-seguro-de-teste",
        "aceita_termos": True,
        "ciente_privacidade": True,
        "termos_versao": "2026-08-01",
        "privacidade_versao": "2026-08-01",
    })
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def login_bruto(client, email, password, slug="clinica-a"):
    return client.post("/auth/login", data={
        "username": email,
        "password": password,
        "client_id": slug,
    })


def cabecalho_csrf(client):
    return {"X-CSRF-Token": client.cookies.get(main.CSRF_COOKIE_NAME)}


def headers_sessao(client):
    token = client.cookies.get(main.ACCESS_COOKIE_NAME)
    assert token
    return {"Authorization": f"Bearer {token}"}


def login(client, email, password, slug="clinica-a"):
    resposta = login_bruto(client, email, password, slug)
    if resposta.status_code != 200:
        return resposta
    dados = resposta.json()
    if dados.get("mfa_setup_required"):
        setup = client.get("/auth/mfa/setup")
        assert setup.status_code == 200, setup.text
        codigo = main.gerar_codigo_totp(setup.json()["segredo"])
        return client.post("/auth/mfa/ativar", headers=cabecalho_csrf(client), json={"codigo": codigo})
    if dados.get("mfa_required"):
        db = main.SessionLocal()
        try:
            usuario = db.query(main.models.Usuario).join(main.models.Clinica).filter(
                main.models.Usuario.email == email,
                main.models.Clinica.slug == slug,
            ).first()
            segredo = main.segredo_totp(usuario.clinica_id, usuario.id, usuario.mfa_secret_salt)
            codigo = main.gerar_codigo_totp(segredo)
        finally:
            db.close()
        return client.post("/auth/mfa/verificar", headers=cabecalho_csrf(client), json={"codigo": codigo})
    return resposta


def criar_admin(client, slug="clinica-a", nome="Clínica A", email="admin@example.com"):
    provisionar_clinica(client, slug, nome, email)
    resposta = login(client, email, "senha-admin-123", slug)
    assert resposta.status_code == 200, resposta.text
    return headers_sessao(client)


def dados_paciente_perfil(email="p1@example.com", cpf="11144477735", nome="Paciente Um"):
    return {
        "nome": nome, "cpf": cpf, "telefone": "11999999999",
        "email": email, "data_nascimento": "1990-01-01",
        "endereco_rua": "Rua A", "endereco_numero": "1", "endereco_bairro": "Centro",
        "endereco_cidade": "Cidade", "endereco_estado": "SP", "endereco_cep": "01000000",
    }


def dados_medico(email="medica@example.com", crm="CRM123", nome="Dra. Ana"):
    return {
        "nome": nome, "especialidade": "Clínica", "duracao_consulta": 30,
        "crm": crm, "email": email, "endereco_rua": "Rua B",
        "endereco_numero": "2", "endereco_bairro": "Centro", "endereco_cidade": "Cidade",
        "endereco_estado": "SP", "endereco_cep": "01000000",
    }


def preparar_atendimento_medico(client):
    headers_admin = criar_admin(client)
    paciente = client.post("/pacientes/", headers=headers_admin, json=dados_paciente_perfil()).json()
    medico = client.post("/medicos/", headers=headers_admin, json=dados_medico()).json()
    conta = client.post("/auth/usuarios", headers=headers_admin, json={
        "email": "medica@example.com", "password": "senha-medico-123", "role": "medico",
    })
    assert conta.status_code == 201, conta.text
    agendamento = client.post("/agendamentos/", headers=headers_admin, json={
        "paciente_id": paciente["id"], "medico_id": medico["id"], "data_hora": "2099-01-05T08:00:00",
    }).json()
    assert client.patch(
        f"/agendamentos/{agendamento['id']}/status?status_novo=Atendido", headers=headers_admin
    ).status_code == 200
    resposta_login = login(client, "medica@example.com", "senha-medico-123")
    headers_medico = headers_sessao(client)
    return headers_admin, headers_medico, paciente, medico, agendamento


def test_cadastro_e_login_de_paciente(client):
    provisionar_clinica(client)
    resposta = client.post("/auth/registrar", json=paciente_payload())
    assert resposta.status_code == 201, resposta.text
    resposta_login = login(client, "paciente@example.com", "senha-forte-123")
    assert resposta_login.status_code == 200
    assert resposta_login.json()["role"] == "paciente"
    assert resposta_login.json()["clinica_slug"] == "clinica-a"


def test_cadastro_incompleto_de_paciente_e_rejeitado(client):
    provisionar_clinica(client)
    resposta = client.post("/auth/registrar", json={
        "clinica_slug": "clinica-a", "email": "x@example.com",
        "password": "senha-forte-123", "role": "paciente",
        "aceita_termos": True, "ciente_privacidade": True,
        "termos_versao": "2026-08-01", "privacidade_versao": "2026-08-01",
    })
    assert resposta.status_code == 400


def test_provisionamento_exige_token_e_slug_unico(client):
    invalido = client.post("/auth/registrar-clinica", json={
        "nome": "Clínica A", "slug": "clinica-a", "email_admin": "a@example.com",
        "password": "senha-forte-123", "provisioning_token": "errado",
        "aceita_termos": True, "ciente_privacidade": True,
        "termos_versao": "2026-08-01", "privacidade_versao": "2026-08-01",
    })
    assert invalido.status_code == 403
    provisionar_clinica(client)
    duplicado = client.post("/auth/registrar-clinica", json={
        "nome": "Outra", "slug": "clinica-a", "email_admin": "b@example.com",
        "password": "senha-forte-123", "provisioning_token": "provisionamento-seguro-de-teste",
        "aceita_termos": True, "ciente_privacidade": True,
        "termos_versao": "2026-08-01", "privacidade_versao": "2026-08-01",
    })
    assert duplicado.status_code == 409


def test_rotas_clinicas_exigem_token(client):
    assert client.get("/pacientes/").status_code == 401
    assert client.get("/agendamentos/").status_code == 401
    assert client.get("/exames/").status_code == 401


def test_reset_de_senha_invalida_link_apos_primeiro_uso(client):
    provisionar_clinica(client)
    client.post("/auth/registrar", json=paciente_payload())
    assert login(client, "paciente@example.com", "senha-forte-123").status_code == 200
    sessao_antiga = headers_sessao(client)
    db = main.SessionLocal()
    try:
        usuario = db.query(main.models.Usuario).filter_by(email="paciente@example.com").first()
        token = main.criar_token_recuperacao(usuario)
    finally:
        db.close()
    assert client.get("/medicos/", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    dados = {"token": token, "nova_senha": "nova-senha-123"}
    assert client.post("/auth/redefinir-senha", json=dados).status_code == 200
    assert client.post("/auth/redefinir-senha", json=dados).status_code == 400
    assert client.get("/clinicas/atual", headers=sessao_antiga).status_code == 401
    assert login(client, "paciente@example.com", "nova-senha-123").status_code == 200


def test_conflito_de_horario_retorna_409(client):
    headers = criar_admin(client)
    paciente = client.post("/pacientes/", headers=headers, json=dados_paciente_perfil()).json()
    medico = client.post("/medicos/", headers=headers, json=dados_medico()).json()
    dados = {"paciente_id": paciente["id"], "medico_id": medico["id"], "data_hora": "2099-01-05T08:00:00"}
    assert client.post("/agendamentos/", headers=headers, json=dados).status_code == 201
    assert client.post("/agendamentos/", headers=headers, json=dados).status_code == 409


def test_medico_so_acessa_pacientes_e_exames_vinculados(client):
    headers_admin = criar_admin(client)
    p1 = client.post("/pacientes/", headers=headers_admin, json=dados_paciente_perfil(
        "p1@example.com", "52998224725", "Paciente Um"
    )).json()
    p2 = client.post("/pacientes/", headers=headers_admin, json=dados_paciente_perfil(
        "p2@example.com", "11144477735", "Paciente Dois"
    )).json()
    medico = client.post("/medicos/", headers=headers_admin, json=dados_medico(
        "medico@example.com", "CRM999", "Dr. João"
    )).json()
    conta = client.post("/auth/usuarios", headers=headers_admin, json={
        "email": "medico@example.com", "password": "senha-medico-123", "role": "medico",
    })
    assert conta.status_code == 201, conta.text
    client.post("/agendamentos/", headers=headers_admin, json={"paciente_id": p1["id"], "medico_id": medico["id"], "data_hora": "2099-01-05T08:00:00"})
    e1 = client.post("/exames/", headers=headers_admin, json={"paciente_id": p1["id"], "tipo_exame": "Hemograma", "laboratorio": "Lab A", "data_hora": "2099-01-06T09:00:00"}).json()
    e2 = client.post("/exames/", headers=headers_admin, json={"paciente_id": p2["id"], "tipo_exame": "Raio-X", "laboratorio": "Lab B", "data_hora": "2099-01-06T10:00:00"}).json()
    resposta_login = login(client, "medico@example.com", "senha-medico-123")
    headers_medico = headers_sessao(client)
    pacientes = client.get("/pacientes/", headers=headers_medico).json()
    assert [paciente["id"] for paciente in pacientes] == [p1["id"]]
    exames = client.get("/exames/", headers=headers_medico).json()
    assert [exame["id"] for exame in exames] == [e1["id"]]
    assert client.patch(f"/exames/{e2['id']}/resultado", headers=headers_medico, json={"resultado": "indevido"}).status_code == 403


def test_avaliacao_atualiza_media_do_medico(client):
    headers_admin = criar_admin(client)
    cadastro = client.post("/auth/registrar", json=paciente_payload())
    assert cadastro.status_code == 201, cadastro.text
    medico = client.post("/medicos/", headers=headers_admin, json=dados_medico(
        "ana@example.com", "CRM321", "Dra. Ana"
    )).json()
    db = main.SessionLocal()
    try:
        paciente = db.query(main.models.Paciente).filter_by(email="paciente@example.com").first()
        paciente_id = paciente.id
    finally:
        db.close()
    agendamento = client.post("/agendamentos/", headers=headers_admin, json={"paciente_id": paciente_id, "medico_id": medico["id"], "data_hora": "2099-01-05T08:00:00"}).json()
    client.patch(f"/agendamentos/{agendamento['id']}/status?status_novo=Atendido", headers=headers_admin)
    resposta_login = login(client, "paciente@example.com", "senha-forte-123")
    headers_paciente = headers_sessao(client)
    resposta = client.post("/avaliacoes/", headers=headers_paciente, json={"agendamento_id": agendamento["id"], "paciente_id": paciente_id, "medico_id": medico["id"], "nota_medico": 4, "comentario_paciente": "Bom atendimento"})
    assert resposta.status_code == 201, resposta.text
    medicos = client.get("/medicos/", headers=headers_paciente).json()
    assert medicos[0]["avaliacao_media"] == 4.0


def test_dados_sao_isolados_entre_clinicas(client):
    headers_a = criar_admin(client, "clinica-a", "Clínica A", "admin@exemplo.com")
    headers_b = criar_admin(client, "clinica-b", "Clínica B", "admin@exemplo.com")

    paciente_a = client.post("/pacientes/", headers=headers_a, json=dados_paciente_perfil()).json()
    resposta_b = client.post("/pacientes/", headers=headers_b, json=dados_paciente_perfil())
    assert resposta_b.status_code == 201, resposta_b.text
    paciente_b = resposta_b.json()
    medico_a = client.post("/medicos/", headers=headers_a, json=dados_medico()).json()
    resposta_medico_b = client.post("/medicos/", headers=headers_b, json=dados_medico())
    assert resposta_medico_b.status_code == 201, resposta_medico_b.text

    assert [item["id"] for item in client.get("/pacientes/", headers=headers_a).json()] == [paciente_a["id"]]
    assert [item["id"] for item in client.get("/pacientes/", headers=headers_b).json()] == [paciente_b["id"]]
    assert client.patch(f"/pacientes/{paciente_b['id']}", headers=headers_a, json={"nome": "Invasão"}).status_code == 404
    assert client.post("/agendamentos/", headers=headers_a, json={
        "paciente_id": paciente_b["id"], "medico_id": medico_a["id"], "data_hora": "2099-01-05T08:00:00",
    }).status_code == 404
    assert client.get("/clinicas/atual", headers=headers_a).json()["slug"] == "clinica-a"
    assert client.get("/clinicas/atual", headers=headers_b).json()["slug"] == "clinica-b"


def test_consentimentos_obrigatorios_sao_versionados(client):
    provisionar_clinica(client)
    resposta = client.post("/auth/registrar", json=paciente_payload())
    assert resposta.status_code == 201, resposta.text
    resposta_login = login(client, "paciente@example.com", "senha-forte-123")
    headers = headers_sessao(client)
    consentimentos = client.get("/lgpd/consentimentos", headers=headers).json()
    assert {item["documento_tipo"] for item in consentimentos} == {"termos_uso", "politica_privacidade"}
    assert all(item["versao"] == "2026-08-01" for item in consentimentos)


def test_auditoria_registra_consulta_sem_copiar_dados_sensiveis(client):
    headers = criar_admin(client)
    paciente = client.post("/pacientes/", headers=headers, json=dados_paciente_perfil()).json()
    assert client.get("/pacientes/", headers=headers).status_code == 200
    resposta = client.get(f"/auditoria?paciente_id={paciente['id']}", headers=headers)
    assert resposta.status_code == 200, resposta.text
    registros = resposta.json()
    assert any(item["acao"] == "ACESSO" and item["recurso"] == "dados_pessoais" for item in registros)
    assert all("11144477735" not in (item.get("detalhes") or "") for item in registros)
    integridade = client.get("/auditoria/integridade", headers=headers)
    assert integridade.status_code == 200
    assert integridade.json()["integra"] is True


def test_paciente_exporta_os_proprios_dados_e_operacao_e_auditada(client):
    headers_admin = criar_admin(client)
    assert client.post("/auth/registrar", json=paciente_payload()).status_code == 201
    resposta_login = login(client, "paciente@example.com", "senha-forte-123")
    headers_paciente = headers_sessao(client)
    exportacao = client.get("/lgpd/meus-dados/exportar", headers=headers_paciente)
    assert exportacao.status_code == 200, exportacao.text
    assert "attachment" in exportacao.headers["content-disposition"]
    assert exportacao.json()["dados_pessoais"]["cpf"] == "52998224725"
    auditoria = client.get("/auditoria?recurso=dados_titular", headers=headers_admin).json()
    assert any(item["acao"] == "EXPORTACAO" for item in auditoria)


def test_exclusao_sem_prontuario_remove_dados_e_bloqueia_conta(client):
    headers_admin = criar_admin(client)
    assert client.post("/auth/registrar", json=paciente_payload()).status_code == 201
    resposta_login = login(client, "paciente@example.com", "senha-forte-123")
    headers_paciente = headers_sessao(client)
    solicitacao = client.post("/lgpd/solicitacoes", headers=headers_paciente, json={
        "tipo": "exclusao", "justificativa": "Não desejo manter meu cadastro.",
    }).json()
    processamento = client.post(
        f"/lgpd/solicitacoes/{solicitacao['id']}/processar",
        headers=headers_admin,
        json={"decisao": "aprovar", "observacao": "Sem histórico clínico sujeito à retenção."},
    )
    assert processamento.status_code == 200, processamento.text
    assert processamento.json()["status"] == "Concluida"
    assert client.get("/pacientes/", headers=headers_admin).json() == []
    assert client.get("/lgpd/consentimentos", headers=headers_paciente).status_code == 401


def test_retencao_impede_exclusao_de_prontuario_recente(client):
    headers_admin = criar_admin(client)
    assert client.post("/auth/registrar", json=paciente_payload()).status_code == 201
    resposta_login = login(client, "paciente@example.com", "senha-forte-123")
    headers_paciente = headers_sessao(client)
    db = main.SessionLocal()
    try:
        paciente_id = db.query(main.models.Paciente.id).filter_by(email="paciente@example.com").scalar()
    finally:
        db.close()
    medico = client.post("/medicos/", headers=headers_admin, json=dados_medico()).json()
    client.post("/agendamentos/", headers=headers_admin, json={
        "paciente_id": paciente_id, "medico_id": medico["id"], "data_hora": "2099-01-05T08:00:00",
    })
    solicitacao = client.post("/lgpd/solicitacoes", headers=headers_paciente, json={
        "tipo": "anonimizacao", "justificativa": "Solicito análise.",
    }).json()
    resposta = client.post(
        f"/lgpd/solicitacoes/{solicitacao['id']}/processar",
        headers=headers_admin,
        json={"decisao": "aprovar", "observacao": "Análise administrativa da retenção."},
    )
    assert resposta.status_code == 409
    assert "prazo mínimo" in resposta.json()["detail"]


def test_prontuario_exige_reautenticacao_e_preserva_versoes(client):
    _, headers_medico, paciente, _, agendamento = preparar_atendimento_medico(client)
    base = {
        "paciente_id": paciente["id"], "agendamento_id": agendamento["id"],
        "tipo": "evolucao", "conteudo": "Paciente estável. Conduta de acompanhamento clínico.",
    }
    senha_errada = client.post("/prontuarios", headers=headers_medico, json={
        **base, "senha_assinatura": "senha-incorreta",
    })
    assert senha_errada.status_code == 401
    criacao = client.post("/prontuarios", headers=headers_medico, json={
        **base, "senha_assinatura": "senha-medico-123",
    })
    assert criacao.status_code == 201, criacao.text
    versao_1 = criacao.json()
    assert versao_1["versao"] == 1
    assert versao_1["assinatura_tipo"] == "interna_reautenticada"
    assert len(versao_1["documento_hash"]) == 64
    assert len(versao_1["assinatura_hash"]) == 64
    assert "senha_assinatura" not in versao_1

    retificacao = client.post(f"/prontuarios/{versao_1['id']}/versoes", headers=headers_medico, json={
        "conteudo": "Paciente estável. Conduta corrigida: retorno em trinta dias.",
        "motivo_retificacao": "Correção do prazo de retorno.",
        "senha_assinatura": "senha-medico-123",
    })
    assert retificacao.status_code == 201, retificacao.text
    versao_2 = retificacao.json()
    assert versao_2["versao"] == 2
    assert versao_2["versao_anterior_id"] == versao_1["id"]
    assert versao_2["serie_id"] == versao_1["serie_id"]

    assert client.get(f"/prontuarios?paciente_id={paciente['id']}", headers=headers_medico).status_code == 400
    historico = client.get(
        f"/prontuarios?paciente_id={paciente['id']}&motivo_acesso=assistencia_direta",
        headers=headers_medico,
    ).json()
    assert len(historico) == 2
    assert next(item for item in historico if item["versao"] == 1)["conteudo"] == base["conteudo"]
    integridade = client.get(
        f"/prontuarios/{versao_2['id']}/integridade?motivo_acesso=assistencia_direta",
        headers=headers_medico,
    )
    assert integridade.status_code == 200, integridade.text
    assert integridade.json()["documento_integro"] is True
    assert integridade.json()["assinatura_integra"] is True
    assert client.patch(f"/prontuarios/{versao_1['id']}", headers=headers_medico, json={"conteudo": "alterado"}).status_code in {404, 405}
    assert client.delete(f"/prontuarios/{versao_1['id']}", headers=headers_medico).status_code in {404, 405}


def test_anexo_tem_hash_e_acesso_auditado(client):
    _, headers_medico, paciente, _, agendamento = preparar_atendimento_medico(client)
    registro = client.post("/prontuarios", headers=headers_medico, json={
        "paciente_id": paciente["id"], "agendamento_id": agendamento["id"], "tipo": "evolucao",
        "conteudo": "Registro com documento clínico complementar anexado.", "senha_assinatura": "senha-medico-123",
    }).json()
    envio = client.post(
        f"/prontuarios/{registro['id']}/anexos",
        headers=headers_medico,
        files={"arquivo": ("resultado.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"origem": "nato_digital", "conferencia": "original"},
    )
    assert envio.status_code == 201, envio.text
    anexo = envio.json()
    assert anexo["arquivo_hash"] == __import__("hashlib").sha256(b"%PDF-1.4\n%%EOF").hexdigest()
    download = client.get(
        f"/prontuarios/anexos/{anexo['id']}?motivo_acesso=assistencia_direta", headers=headers_medico
    )
    assert download.status_code == 200
    assert download.content == b"%PDF-1.4\n%%EOF"


def test_prescricao_e_cancelamento_sao_eventos_assinados(client):
    _, headers_medico, paciente, _, _ = preparar_atendimento_medico(client)
    emissao = client.post("/prescricoes", headers=headers_medico, json={
        "paciente_id": paciente["id"],
        "observacoes": "Uso conforme orientação clínica.",
        "senha_assinatura": "senha-medico-123",
        "itens": [{
            "medicamento": "Medicamento teste", "concentracao": "500 mg", "forma_farmaceutica": "comprimido",
            "dose": "1 comprimido", "via": "oral", "frequencia": "a cada 8 horas", "duracao": "5 dias",
        }],
    })
    assert emissao.status_code == 201, emissao.text
    prescricao = emissao.json()
    assert prescricao["assinatura_tipo"] == "interna_reautenticada"
    assert len(prescricao["itens"]) == 1
    cancelamento = client.post(f"/prescricoes/{prescricao['id']}/cancelamentos", headers=headers_medico, json={
        "motivo": "Substituição da conduta terapêutica.", "senha_assinatura": "senha-medico-123",
    })
    assert cancelamento.status_code == 201, cancelamento.text
    assert cancelamento.json()["tipo"] == "cancelamento"
    repetido = client.post(f"/prescricoes/{prescricao['id']}/cancelamentos", headers=headers_medico, json={
        "motivo": "Tentativa repetida de cancelamento.", "senha_assinatura": "senha-medico-123",
    })
    assert repetido.status_code == 409
    listagem = client.get(
        f"/prescricoes?paciente_id={paciente['id']}&motivo_acesso=assistencia_direta", headers=headers_medico
    ).json()
    assert len(listagem[0]["eventos"]) == 1


def test_login_usa_cookies_httponly_e_csrf(client):
    provisionar_clinica(client)
    assert client.post("/auth/registrar", json=paciente_payload()).status_code == 201
    resposta = login_bruto(client, "paciente@example.com", "senha-forte-123")
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["autenticado"] is True
    assert "access_token" not in resposta.json()
    cookies = "\n".join(resposta.headers.get_list("set-cookie")).lower()
    assert main.ACCESS_COOKIE_NAME.lower() in cookies
    assert main.REFRESH_COOKIE_NAME.lower() in cookies
    assert "httponly" in cookies
    assert "samesite=strict" in cookies
    assert client.cookies.get(main.ACCESS_COOKIE_NAME)
    assert client.cookies.get(main.REFRESH_COOKIE_NAME)

    sem_csrf = client.post("/lgpd/solicitacoes", json={
        "tipo": "correcao", "justificativa": "Teste de proteção CSRF.",
    })
    assert sem_csrf.status_code == 403
    com_csrf = client.post("/lgpd/solicitacoes", headers=cabecalho_csrf(client), json={
        "tipo": "correcao", "justificativa": "Teste de proteção CSRF.",
    })
    assert com_csrf.status_code == 201, com_csrf.text


def test_refresh_rotaciona_e_reuso_revoga_familia(client):
    provisionar_clinica(client)
    assert client.post("/auth/registrar", json=paciente_payload()).status_code == 201
    assert login_bruto(client, "paciente@example.com", "senha-forte-123").status_code == 200
    refresh_antigo = client.cookies.get(main.REFRESH_COOKIE_NAME)
    csrf_antigo = client.cookies.get(main.CSRF_COOKIE_NAME)

    renovacao = client.post("/auth/refresh", headers=cabecalho_csrf(client))
    assert renovacao.status_code == 200, renovacao.text
    refresh_novo = client.cookies.get(main.REFRESH_COOKIE_NAME)
    assert refresh_novo and refresh_novo != refresh_antigo

    with TestClient(main.app) as replay:
        replay.cookies.set(main.REFRESH_COOKIE_NAME, refresh_antigo)
        replay.cookies.set(main.CSRF_COOKIE_NAME, csrf_antigo)
        reutilizacao = replay.post("/auth/refresh", headers={"X-CSRF-Token": csrf_antigo})
    assert reutilizacao.status_code == 401
    assert "revogada" in reutilizacao.json()["detail"]
    assert client.get("/auth/me").status_code == 401


def test_mfa_e_obrigatorio_e_codigo_recuperacao_e_de_uso_unico(client):
    provisionar_clinica(client)
    primeira_etapa = login_bruto(client, "admin@example.com", "senha-admin-123")
    assert primeira_etapa.status_code == 200
    assert primeira_etapa.json()["mfa_setup_required"] is True
    assert not client.cookies.get(main.ACCESS_COOKIE_NAME)

    setup = client.get("/auth/mfa/setup")
    assert setup.status_code == 200, setup.text
    assert setup.json()["uri_otpauth"].startswith("otpauth://totp/")
    codigo = main.gerar_codigo_totp(setup.json()["segredo"])
    ativacao = client.post("/auth/mfa/ativar", headers=cabecalho_csrf(client), json={"codigo": codigo})
    assert ativacao.status_code == 200, ativacao.text
    assert ativacao.json()["autenticado"] is True
    recuperacao = ativacao.json()["recovery_codes"][0]
    assert len(ativacao.json()["recovery_codes"]) == 10
    assert client.get("/auth/me").json()["mfa_verificada"] is True

    assert client.post("/auth/logout", headers=cabecalho_csrf(client)).status_code == 200
    desafio = login_bruto(client, "admin@example.com", "senha-admin-123")
    assert desafio.json()["mfa_required"] is True
    reutilizar_totp = client.post("/auth/mfa/verificar", headers=cabecalho_csrf(client), json={"codigo": codigo})
    assert reutilizar_totp.status_code == 401
    entrada_recuperacao = client.post(
        "/auth/mfa/verificar", headers=cabecalho_csrf(client), json={"codigo": recuperacao}
    )
    assert entrada_recuperacao.status_code == 200, entrada_recuperacao.text

    assert client.post("/auth/logout", headers=cabecalho_csrf(client)).status_code == 200
    assert login_bruto(client, "admin@example.com", "senha-admin-123").json()["mfa_required"] is True
    repetido = client.post(
        "/auth/mfa/verificar", headers=cabecalho_csrf(client), json={"codigo": recuperacao}
    )
    assert repetido.status_code == 401


def teardown_module():
    main.engine.dispose()
    ARQUIVO_TESTE.unlink(missing_ok=True)
