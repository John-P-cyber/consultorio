# Publicação de demonstração no Render

O Render fornece uma URL HTTPS `https://<serviço>.onrender.com`; um domínio próprio é opcional. O arquivo `render.yaml` da raiz descreve um serviço Docker gratuito, um PostgreSQL gratuito e gera três segredos independentes.

## Opção recomendada: criar pelo Blueprint

1. Envie o `render.yaml` para o GitHub.
2. No Render, escolha **New > Blueprint** e conecte este repositório.
3. Mantenha a branch `main`, revise os recursos `consultorio` e `consultorio-db` e selecione **Deploy Blueprint**.
4. Aguarde o health check `/health/ready` ficar verde e abra a URL `onrender.com` exibida pelo serviço.
5. Em **Environment**, revele e copie o valor de `CLINIC_PROVISIONING_TOKEN`. Abra `/nova-clinica.html` na URL do serviço e use esse token apenas para criar a primeira clínica e o administrador.

O Render injeta `RENDER_EXTERNAL_URL`. Quando `ALLOWED_ORIGINS` e `RESET_URL` não são definidos explicitamente, a aplicação deriva ambos dessa URL segura. `RENDER_GIT_COMMIT` também identifica a versão nos logs e métricas.

## Corrigir um Web Service já criado manualmente

Se o serviço `consultorio` já existe, crie primeiro um **Render Postgres** na mesma região e adicione estas variáveis na aba **Environment** do Web Service:

| Variável | Valor |
|---|---|
| `APP_ENV` | `production` |
| `DATABASE_URL` | Internal Database URL do PostgreSQL |
| `SECRET_KEY` | segredo aleatório com no mínimo 32 caracteres |
| `MFA_MASTER_KEY` | outro segredo aleatório com no mínimo 32 caracteres |
| `CLINIC_PROVISIONING_TOKEN` | terceiro segredo aleatório |
| `COOKIE_SECURE` | `true` |
| `COOKIE_SAMESITE` | `strict` |
| `RUN_MIGRATIONS_ON_START` | `true` |
| `SMTP_HOST` | host do provedor transacional |
| `SMTP_PORT` | porta alternativa do provedor no plano gratuito, por exemplo `2525` |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | credenciais SMTP |
| `SMTP_FROM` | remetente verificado pelo provedor |
| `SMTP_USE_TLS` | `true` para STARTTLS |
| `WHATSAPP_ACCESS_TOKEN` | token permanente protegido da Meta Business |
| `WHATSAPP_API_VERSION` | versão suportada, por exemplo `v23.0` |
| `COMMUNICATION_WORKER_ENABLED` | `true` em uma única instância |
| `AI_ENABLED` | `true` para habilitar o BotIA |
| `AI_PROVIDER` | `gemini` para usar a API gratuita configurada |
| `GEMINI_API_KEY` | chave secreta criada no Google AI Studio |
| `GEMINI_MODEL` | `gemini-3.6-flash` |
| `GEMINI_TEMPERATURE` | `0.45` para equilibrar naturalidade e previsibilidade |

Não reutilize os três segredos. Depois escolha **Save, rebuild, and deploy**. Não é necessário cadastrar `PORT`, `ALLOWED_ORIGINS` nem `RESET_URL` no Render.

O formatador de logs é carregado sem importar a configuração da aplicação. Assim, se uma variável estiver ausente, o log do próximo deploy mostra diretamente qual variável precisa ser corrigida, em vez da mensagem genérica `Unable to configure formatter 'json'`.

## Limites da modalidade gratuita

A configuração gratuita é adequada apenas para demonstração:

- o Web Service adormece após inatividade e a primeira abertura pode demorar cerca de um minuto;
- o filesystem é efêmero, portanto anexos enviados ao prontuário desaparecem em reinícios e novos deploys;
- o PostgreSQL gratuito expira após 30 dias, tem 1 GB e não possui backup;
- as portas SMTP comuns `25`, `465` e `587` são bloqueadas, então recuperação, confirmações, lembretes e cancelamentos por e-mail exigem um provedor que ofereça outra porta compatível, como `2525`, ou um Web Service pago;
- o worker interno de lembretes depende de a instância estar acordada; o plano gratuito pode atrasar lembretes após períodos de inatividade e serve apenas para demonstração.
- o BotIA em `AI_PROVIDER=gemini` depende da disponibilidade e dos limites da cota gratuita do Google; o conteúdo processado nessa modalidade pode ser utilizado para melhoria dos produtos do provedor;
- `AI_PROVIDER=local` continua disponível sem chave e sem envio a fornecedor externo, porém com compreensão limitada aos fluxos implementados.

Antes de atender clientes reais, migre para Web Service e PostgreSQL pagos, armazenamento de objetos privado para anexos, SMTP/transacional funcional, backup testado, monitoramento e ambientes separados. O guia de produção continua sendo [PRODUCTION.md](PRODUCTION.md).

Referências: [Blueprints](https://render.com/docs/infrastructure-as-code), [variáveis padrão](https://render.com/docs/environment-variables) e [limites gratuitos](https://render.com/docs/free).
