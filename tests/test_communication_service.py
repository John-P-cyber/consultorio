import json
import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_db.sqlite")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-characters")
os.environ.setdefault("MFA_MASTER_KEY", "test-mfa-master-key-different-and-at-least-32")

import communication_service as service


def test_normaliza_telefone_com_codigo_do_pais():
    assert service.normalizar_telefone_whatsapp("(11) 99999-9999", "55") == "5511999999999"
    assert service.normalizar_telefone_whatsapp("(55) 99999-9999", "55") == "5555999999999"
    assert service.normalizar_telefone_whatsapp("+55 11 99999-9999", "55") == "5511999999999"


def test_gateway_smtp_usa_tls_e_autenticacao(monkeypatch):
    eventos = []

    class SMTPFalso:
        def __init__(self, host, port, timeout):
            eventos.append(("conectar", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self):
            eventos.append(("tls",))

        def login(self, usuario, senha):
            eventos.append(("login", usuario, senha))

        def send_message(self, mensagem):
            eventos.append(("enviar", mensagem["To"], mensagem["Subject"]))
            return {}

    monkeypatch.setattr(service, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(service, "SMTP_PORT", 2525)
    monkeypatch.setattr(service, "SMTP_USERNAME", "usuario")
    monkeypatch.setattr(service, "SMTP_PASSWORD", "segredo")
    monkeypatch.setattr(service, "SMTP_FROM", "no-reply@example.com")
    monkeypatch.setattr(service, "SMTP_USE_TLS", True)
    monkeypatch.setattr(service, "SMTP_USE_SSL", False)
    monkeypatch.setattr(service.smtplib, "SMTP", SMTPFalso)

    resultado = service.enviar_email(
        destinatario="paciente@example.com",
        assunto="Consulta confirmada",
        texto="Conteúdo transacional",
        remetente_nome="Clínica A",
    )
    assert resultado.identificador
    assert eventos == [
        ("conectar", "smtp.example.com", 2525, service.SMTP_TIMEOUT_SECONDS),
        ("tls",),
        ("login", "usuario", "segredo"),
        ("enviar", "paciente@example.com", "Consulta confirmada"),
    ]


def test_gateway_whatsapp_usa_cloud_api_e_template(monkeypatch):
    requisicoes = []

    class RespostaFalsa:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"messages":[{"id":"wamid.123"}]}'

    def abrir(requisicao, timeout):
        requisicoes.append((requisicao, timeout))
        return RespostaFalsa()

    monkeypatch.setattr(service, "WHATSAPP_ACCESS_TOKEN", "token-seguro")
    monkeypatch.setattr(service, "WHATSAPP_API_VERSION", "v23.0")
    monkeypatch.setattr(service.request, "urlopen", abrir)
    resultado = service.enviar_template_whatsapp(
        phone_number_id="123456789",
        destinatario="(11) 99999-9999",
        codigo_pais="55",
        template="confirmacao_consulta",
        idioma="pt_BR",
        parametros=["Maria", "Clínica A", "Consulta", "Dra. Ana", "05/01/2099", "08:00"],
    )
    requisicao, timeout = requisicoes[0]
    payload = json.loads(requisicao.data.decode("utf-8"))
    assert requisicao.full_url == "https://graph.facebook.com/v23.0/123456789/messages"
    assert timeout == 20
    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == "5511999999999"
    assert payload["template"]["name"] == "confirmacao_consulta"
    assert resultado.identificador == "wamid.123"
