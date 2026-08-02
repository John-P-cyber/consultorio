# Infraestrutura de produção

Este repositório inclui uma base operacional para produção e homologação. Ela não cria contas em provedores: domínio, servidor, PostgreSQL gerenciado, bucket S3 e credenciais precisam ser contratados e configurados antes do primeiro deploy.

## Arquitetura entregue

- imagem Docker multi-stage, dependências fixadas e processo sem privilégios;
- Caddy como único serviço público, com HTTPS e renovação automática de certificado;
- API e métricas em rede interna, filesystem somente leitura e volume persistente para anexos;
- PostgreSQL externo/gerenciado, com pool de conexões e migrations executadas antes do deploy;
- GitHub Actions com testes, build, SBOM, publicação no GHCR, teste real de migrations, backup/restauração e deploy protegido por ambiente;
- Prometheus, Alertmanager, Grafana, Loki e Grafana Alloy para métricas, alertas e logs centralizados;
- backup lógico diário, checksum, restauração automática em banco descartável e cópia externa criptografada com Restic;
- ambientes `staging` e `production` com domínios, bancos, chaves e servidores independentes.

## 1. Recursos externos obrigatórios

Crie dois ambientes separados. O recomendado é usar contas/projetos ou, no mínimo, servidores e bancos distintos:

| Recurso | Homologação | Produção |
|---|---|---|
| DNS | `staging.clinica.exemplo.com.br` | `clinica.exemplo.com.br` |
| Linux/Docker | servidor de staging | servidor de produção |
| PostgreSQL | banco e usuário exclusivos | banco e usuário exclusivos |
| Objetos/backup | prefixo ou bucket exclusivo | bucket exclusivo, versionado |
| Chaves e SMTP | credenciais de sandbox | credenciais reais exclusivas |

No PostgreSQL gerenciado, ative TLS, backups automáticos do provedor e recuperação point-in-time (PITR). Defina e registre RPO/RTO; uma meta inicial razoável precisa ser aprovada pelo negócio, por exemplo RPO de 15 minutos e RTO de 4 horas. O `pg_dump` deste projeto é uma segunda camada e não substitui o WAL/PITR do provedor.

Direcione o DNS para o IP público do servidor e libere TCP 80/443 e UDP 443. O Caddy só consegue emitir o certificado público quando o domínio resolve para o servidor e as portas estão acessíveis.

## 2. Segredos e configuração do servidor

Copie os exemplos de `deploy/env` para `/etc/consultorio`, remova o sufixo `.example` e restrinja as permissões a `0600`. Nunca coloque os arquivos reais no Git.

Arquivos mínimos por ambiente:

- `/etc/consultorio/production.env` ou `staging.env`: aplicação e banco;
- `/etc/consultorio/production.compose.env` ou `staging.compose.env`: domínio, imagem e caminhos;
- `/etc/consultorio/backup-production.env`: repositório Restic/S3;
- `/etc/consultorio/observability.env`: administrador do Grafana;
- `/etc/consultorio/alertmanager.yml`: canal real de alerta.

Gere `SECRET_KEY`, `MFA_MASTER_KEY`, `CLINIC_PROVISIONING_TOKEN`, senha do Grafana e `RESTIC_PASSWORD` separadamente, com um gerenciador de segredos. Não reutilize valores entre staging e produção. Guarde também uma cópia protegida de `MFA_MASTER_KEY` e `RESTIC_PASSWORD`; perdê-las impede, respectivamente, validar os autenticadores atuais e restaurar o backup externo.

## 3. Primeiro deploy manual

No servidor, instale Docker Engine com Compose v2, crie o usuário `deploy` no grupo autorizado a operar Docker e copie a pasta `deploy` para `/opt/consultorio/deploy`.

```bash
export APP_IMAGE=ghcr.io/organizacao/consultorio-api:sha-commit
export COMPOSE_ENV_FILE=/etc/consultorio/production.compose.env
sh /opt/consultorio/deploy/deploy.sh production
```

O script baixa uma tag imutável, executa `alembic upgrade head`, inicia aplicação, proxy e observabilidade, aguarda o health check e restaura a imagem anterior se a aplicação não ficar saudável. Migrations devem continuar compatíveis com a versão anterior durante um rollback; alterações destrutivas de schema exigem uma implantação em duas etapas.

Endpoints operacionais:

- `/health/live`: processo ativo, usado pelo Docker;
- `/health/ready`: conexão com o banco disponível, usado pelo Caddy antes de encaminhar tráfego;
- `/metrics`: Prometheus; bloqueado pelo Caddy e acessível apenas pela rede interna.

## 4. CI/CD no GitHub

Crie os GitHub Environments `staging` e `production`. Configure aprovação obrigatória para produção e restrinja as branches permitidas. Em cada ambiente, cadastre:

Secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`, `GHCR_USER`, `GHCR_TOKEN` (somente `read:packages`).

Variables: `DEPLOY_PATH=/opt/consultorio` e `COMPOSE_ENV_FILE=/etc/consultorio/<ambiente>.compose.env`.

O push em `main` implanta staging depois de todos os testes. Produção é iniciada manualmente no workflow **Build and deploy** e deve aguardar a aprovação do ambiente. O workflow gera SBOM e publica a imagem no GHCR com a tag imutável `sha-<commit>`.

## 5. Backups e teste de restauração

Antes de automatizar, execute um ciclo e confirme o resultado:

```bash
COMPOSE_ENV_FILE=/etc/consultorio/production.compose.env \
  sh /opt/consultorio/deploy/backup-cycle.sh production
```

O ciclo faz `pg_dump` em formato custom, valida o arquivo, confere SHA-256, restaura em `consultorio_restore_verify`, verifica tabelas essenciais e envia banco e anexos para o repositório Restic. O banco de verificação é isolado e o script recusa qualquer nome que não termine em `_restore_verify`.

Para agendar diariamente, instale as units de `deploy/systemd`, recarregue o systemd e habilite:

```bash
sudo systemctl enable --now consultorio-backup@production.timer
sudo systemctl list-timers consultorio-backup@production.timer
```

Configure alerta para falha da unit e faça, no mínimo trimestralmente, um exercício documentado de recuperação em infraestrutura separada. Teste também o PITR do provedor e a restauração dos anexos; “backup concluído” sem restauração comprovada não atende o objetivo.

## 6. Monitoramento e logs

Grafana, Prometheus e Alertmanager escutam apenas em `127.0.0.1` no servidor. Acesse por VPN ou túnel SSH, nunca expondo as portas diretamente:

```bash
ssh -L 3000:127.0.0.1:3000 deploy@servidor
```

Copie `deploy/observability/alertmanager-email.yml.example` para `/etc/consultorio/alertmanager.yml`, substitua o SMTP e valide a entrega de alertas. As regras iniciais cobrem indisponibilidade, taxa de 5xx e latência p95.

A aplicação escreve JSON em stdout com `request_id`, template da rota, status, duração, ambiente e versão. Não grava corpo, token, conteúdo clínico ou IP no log operacional. O Caddy remove URI e headers e mascara IPs antes de enviar os acessos ao Loki. A retenção local do Loki é de 31 dias; ajuste-a à política formal de retenção e envie telemetria para um serviço externo se precisar diagnosticar a perda completa do servidor.

O acesso ao socket Docker dá ao Alloy visibilidade elevada sobre o host. Restrinja quem altera essa configuração e, em uma operação madura, execute o coletor no host ou use um backend gerenciado com credenciais de escrita limitadas.

## 7. Checklist de entrada em produção

- [ ] DNS e HTTPS validados externamente, inclusive renovação do certificado;
- [ ] staging e produção em servidores, bancos, buckets e chaves separados;
- [ ] PostgreSQL com TLS, alta disponibilidade, PITR e janela de retenção contratada;
- [ ] migrations, backup/restauração e rollback executados em staging;
- [ ] timer de backup ativo e alerta de falha testado;
- [ ] alerta real recebido por plantonista/responsável;
- [ ] dashboards e logs acessíveis somente por VPN/SSH;
- [ ] capacidade, RPO, RTO, responsáveis e runbook de incidente documentados;
- [ ] atualização periódica de imagens/dependências e varredura de vulnerabilidades definida;
- [ ] anexos migrados para objeto privado ou protegidos pelo backup Restic testado.

Referências oficiais: [Docker para Python](https://docs.docker.com/guides/python/), [HTTPS automático do Caddy](https://caddyserver.com/docs/automatic-https), [GitHub Environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments), [backup e PITR do PostgreSQL](https://www.postgresql.org/docs/18/backup.html), [Alertmanager](https://prometheus.io/docs/alerting/latest/configuration/) e [Grafana Alloy](https://grafana.com/docs/alloy/latest/introduction/how-alloy-works/).
