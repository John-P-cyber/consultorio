# Clínica Inteligente

Sistema web multiempresa para cadastro de pacientes e médicos, agendamentos, exames, prontuário clínico versionado, prescrições e avaliações de atendimento.

## Executar localmente

1. Crie e ative um ambiente virtual.
2. Instale as dependências: `pip install -r requirements.txt`.
3. Copie `.env.example` para `.env` e defina `DATABASE_URL`, `SECRET_KEY`, `MFA_MASTER_KEY` e `CLINIC_PROVISIONING_TOKEN`.
4. Crie o banco PostgreSQL indicado em `DATABASE_URL`.
5. Aplique as migrations: `alembic upgrade head`.
6. Inicie: `uvicorn main:app --reload`.
7. Abra `http://127.0.0.1:8000/`. A documentação da API fica em `/docs`.

O FastAPI serve as páginas HTML e os assets necessários, portanto não é preciso iniciar um segundo servidor para o frontend.

## CSS do frontend

O portal usa um arquivo Tailwind compilado e versionado, sem carregar o Play CDN no navegador. Depois de alterar classes nos arquivos HTML ou JavaScript, regenere o asset de produção:

```bash
npm ci
npm run build:css
```

O CI repete a compilação e falha quando `tailwind.css` não corresponde ao código-fonte.

## Banco existente criado antes do Alembic

Se as tabelas já existiam antes da inclusão do Alembic, faça backup e confira se possuem `exames.resultado` e `usuarios.reset_version`. Depois marque a migration inicial e aplique as seguintes:

```bash
alembic stamp 0001_initial
alembic upgrade head
```

## Multiempresa e primeira clínica

Cada clínica possui um `slug` (código usado no login) e todas as entidades, incluindo prontuários, anexos, prescrições e sessões, carregam um `clinica_id`. As consultas da API sempre são limitadas à clínica presente na sessão autenticada. E-mail, CPF e CRM são únicos dentro de uma clínica, mas podem se repetir em empresas diferentes.

Abra `/nova-clinica.html` para criar um ambiente. O formulário exige o mesmo token definido em `CLINIC_PROVISIONING_TOKEN` e cria, em uma única transação, a clínica e seu primeiro administrador. O cadastro público em `/register.html` cria apenas pacientes e exige o código da clínica.

Administradores adicionais e contas médicas são criados por um administrador autenticado em `/auth/usuarios`. O perfil do médico deve existir com o mesmo e-mail antes da criação do acesso.

Ao aplicar a migration multiempresa sobre uma instalação existente, todos os dados atuais são preservados na clínica `clinica-padrao`. Depois do `alembic upgrade head`, use esse código no login. Altere o nome e o código diretamente no banco antes de disponibilizar a instalação, se necessário.

## Recuperação de senha

O link “Esqueceu sua senha?” cria um token temporário e de uso único. Em desenvolvimento, o link aparece no terminal da API. Em produção, configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS` e `SMTP_USE_SSL` para enviá-lo por e-mail.

Uma redefinição de senha revoga imediatamente todas as sessões ativas do usuário.

## Sessões e autenticação em dois fatores

O portal não grava tokens de autenticação no `localStorage`. Access e refresh tokens são enviados em cookies `HttpOnly`, com `SameSite=Strict` e `Secure` obrigatório em produção. O access token expira em 15 minutos por padrão; o refresh token fica ligado a uma sessão persistida, é rotacionado a cada uso e a reutilização de um token antigo revoga a sessão. Requisições mutáveis autenticadas por cookie também exigem um token CSRF separado.

As sessões podem ser consultadas e revogadas em `/seguranca.html`. Logout, revogação manual, redefinição de senha, anonimização e exclusão de conta invalidam as credenciais no servidor, sem depender apenas da remoção do cookie no navegador.

Médicos e administradores precisam configurar TOTP no primeiro acesso. O segredo é derivado de `MFA_MASTER_KEY` e de um salt aleatório por usuário; não é armazenado em texto puro. Códigos TOTP não podem ser reutilizados, tentativas são limitadas e dez códigos de recuperação com uso único são entregues durante a ativação. Não registre `MFA_MASTER_KEY` no repositório e mantenha uma cópia protegida: perdê-la invalida todos os autenticadores existentes.

Esses controles seguem as recomendações de cookies da [OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html), rotação de refresh token do [RFC 9700](https://www.rfc-editor.org/info/rfc9700/) e algoritmo TOTP do [RFC 6238](https://datatracker.ietf.org/doc/html/rfc6238). TOTP digitado manualmente melhora a segurança, mas não é resistente a phishing; para um nível superior, a evolução recomendada é WebAuthn/passkeys, conforme a distinção feita pelo [NIST SP 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html).

## LGPD, consentimentos e auditoria

O sistema mantém uma trilha append-only para acesso e alteração de dados pessoais, agendamentos, exames e registros clínicos. O log registra metadados — clínica, usuário, perfil, ação, recurso, identificadores, IP, campos afetados e horário — sem copiar CPF, resultados de exames ou texto de evolução clínica. Cada registro recebe HMAC e referência ao hash anterior; administradores podem verificar a cadeia em `GET /auditoria/integridade`.

A Central de Privacidade fica em `/lgpd.html` e oferece:

- histórico versionado de aceite dos Termos de Uso e ciência da Política de Privacidade;
- consentimento opcional e revogável para comunicações não essenciais;
- exportação JSON dos dados do paciente;
- solicitações de correção, anonimização e exclusão;
- análise administrativa e fundamentação da decisão;
- consulta da trilha de auditoria pelos administradores.

Pedidos de anonimização ou exclusão não são executados automaticamente quando houver registro clínico dentro da retenção mínima. `PRONTUARIO_RETENTION_YEARS` tem mínimo técnico de 20 anos, em consonância com a Lei nº 13.787/2018. Quando existe prontuário sujeito a preservação, a conta e os dados cadastrais são anonimizados em vez de apagar o histórico clínico imutável.

Os usuários existentes antes da migration não recebem consentimentos retroativos fabricados. Eles podem registrar os documentos atuais na Central de Privacidade. Ao atualizar o conteúdo jurídico, altere também `TERMOS_VERSAO` e `PRIVACIDADE_VERSAO`.

Antes da comercialização, personalize `termos.html` e `privacidade.html` com razão social, CNPJ, endereço, canal do titular, encarregado quando aplicável, fornecedores, transferências internacionais e a divisão contratual entre controlador e operador. Os textos fornecidos são uma base técnica e devem passar por revisão jurídica.

Referências oficiais: [LGPD — Lei nº 13.709/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm), [guarda de prontuários — Lei nº 13.787/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13787.htm) e [guia de segurança da ANPD](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia-orientativo-sobre-seguranca-da-informacao-para-agentes-de-tratamento-de-pequeno-porte).

## Prontuário clínico

Avaliações de atendimento e dados clínicos são módulos separados. O paciente avalia o médico em `/avaliacoes/`; o profissional registra informações assistenciais em `/prontuarios`.

Cada entrada do prontuário possui autoria e CRM preservados, data, tipo, número e série de versão, hash SHA-256 e assinatura HMAC reautenticada pela senha do profissional. Não há edição nem exclusão: uma correção é criada em `POST /prontuarios/{id}/versoes`, vinculada à versão anterior. As tabelas clínicas também possuem bloqueio de `UPDATE` e `DELETE` no PostgreSQL e no SQLite migrado.

Evoluções existentes no antigo campo de avaliações são preservadas como `migrado_sem_assinatura`: recebem hash verificável, mas não ganham uma assinatura retroativa que nunca existiu. A migration `0006_integridade_legado` normaliza os hashes de instalações que já haviam importado datas sem fuso horário.

Anexos PDF, PNG e JPEG recebem hash próprio, classificação de origem/conferência e auditoria de envio e download. Configure `PRONTUARIO_UPLOAD_DIR` e `PRONTUARIO_MAX_UPLOAD_MB`. Em produção com múltiplas instâncias, substitua o disco local por armazenamento de objetos privado, com criptografia, versionamento, backup e URLs temporárias.

Prescrições e cancelamentos são eventos imutáveis assinados internamente. Essa assinatura registra autoria e integridade dentro da aplicação, mas **não é apresentada como assinatura eletrônica qualificada nem substitui certificado ICP-Brasil** para documentos médicos utilizados fora do sistema. A integração com um provedor adequado continua necessária antes da comercialização desse fluxo externo.

Consultas de prontuário por médicos e administradores exigem `motivo_acesso` (`assistencia_direta`, `assistencia_indireta`, `ensino_pesquisa` ou `judicial`) e geram auditoria por paciente consultado. O titular acessa o próprio prontuário com motivo automático `titular`.

## Agenda profissional

Os horários não são mais definidos por constantes no código. Cada médico possui faixas semanais independentes, com múltiplos períodos por dia para representar almoço e outros intervalos. Administradores e médicos configuram a agenda em `/agenda-config.html`.

Tipos de consulta possuem nome, duração e intervalo posterior próprios. O agendamento preserva esses valores como um snapshot histórico, portanto uma alteração futura no tipo não muda consultas já marcadas. Tipos de retorno exigem uma consulta atendida do mesmo paciente e médico, respeitam o prazo configurado e impedem retornos ativos duplicados para a mesma origem.

Férias e bloqueios podem ser individuais; feriados também podem abranger toda a clínica. O sistema recusa um novo bloqueio que colida com consultas ativas, e os horários disponíveis descontam automaticamente consultas, intervalos, férias, feriados e bloqueios. A política individual do médico define se o paciente pode cancelar online e qual é a antecedência mínima. Cancelamentos registram autor, momento e motivo na consulta e na auditoria.

## Comunicação transacional

Administradores configuram os canais da clínica em `/comunicacao-config.html`. Confirmações são enfileiradas após a criação da consulta, cancelamentos após a atualização de status e lembretes são processados automaticamente dentro da antecedência definida. O histórico registra canal, evento, destinatário mascarado, tentativas, identificador do provedor e erro seguro. A restrição única por consulta, canal e evento torna o processamento idempotente mesmo após reinicializações.

O e-mail usa SMTP com `STARTTLS` ou SSL e também atende a recuperação de senha. Credenciais são exclusivamente variáveis de ambiente; remetente e `Reply-To` podem variar por clínica. Configure `COMMUNICATION_WORKER_ENABLED=true` em somente um processo e ajuste `COMMUNICATION_WORKER_INTERVAL_SECONDS` quando usar o processador interno.

O WhatsApp usa a Cloud API oficial da Meta, nunca automação do WhatsApp Web. `WHATSAPP_ACCESS_TOKEN` fica no ambiente, enquanto cada clínica configura seu `phone_number_id`, número de exibição, código de país, idioma e nomes dos modelos previamente aprovados. Os modelos de confirmação e lembrete recebem seis parâmetros — paciente, clínica, tipo, médico, data e hora — e o modelo de cancelamento recebe também o motivo. A versão da Graph API é controlada por `WHATSAPP_API_VERSION` para permitir atualização sem alterar o código.

No plano gratuito do Render, as portas SMTP 25, 465 e 587 são bloqueadas. Use um provedor que ofereça uma porta alternativa compatível, como 2525, ou migre o serviço para um plano pago antes de ativar e-mail em produção.

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

A suíte usa SQLite isolado e cobre cookies HttpOnly, CSRF, rotação e replay de refresh token, revogação, TOTP, códigos de recuperação, autorização, reset de senha, agenda semanal, intervalos, bloqueios, tipos de consulta, retornos, regras de cancelamento, comunicação idempotente por SMTP e WhatsApp oficial, lembretes, privacidade médico–paciente, avaliações, isolamento entre clínicas, assinatura e versionamento de prontuário, anexos e prescrições.

## Produção

O projeto agora possui imagem Docker sem privilégios, proxy HTTPS, deploy de staging/produção via GitHub Actions, health checks, métricas, alertas, logs JSON centralizados e backup com restauração testada. O guia completo de provisionamento, secrets, CI/CD, monitoramento, rollback e operação está em [docs/PRODUCTION.md](docs/PRODUCTION.md).

Para uma demonstração sem domínio próprio, o repositório também inclui um Blueprint gratuito do Render. Ele cria o serviço web, um PostgreSQL e os segredos iniciais, executa as migrations na inicialização e usa automaticamente a URL HTTPS `onrender.com`. Consulte [docs/RENDER.md](docs/RENDER.md).

Domínio, servidores, banco PostgreSQL gerenciado, bucket externo e credenciais não são criados pelo repositório. Esses recursos devem ser configurados no provedor seguindo o checklist antes da primeira publicação.
