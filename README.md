# Clínica Inteligente

MVP para cadastro de pacientes e médicos, agendamentos, exames e avaliações.

## Como executar

1. Crie um banco PostgreSQL chamado `consultorio`.
2. Copie `.env.example` para `.env` e preencha `DATABASE_URL` e `SECRET_KEY`.
3. Instale as dependências com `pip install -r requirements.txt`. A API carrega as variáveis do arquivo `.env` automaticamente.
4. Inicie a API: `uvicorn main:app --reload`.
5. Acesse a documentação em `http://127.0.0.1:8000/docs`; sirva os arquivos HTML em um servidor local na porta 5500.

Na primeira execução a API cria as tabelas e adiciona a coluna de resultado aos exames existentes. Para produção, substitua essa migração simples por Alembic.

## Migrações com Alembic

1. Instale dependências: `pip install -r requirements.txt`
2. Gere o arquivo de configuração inicial (já incluído neste repositório) e atualize `alembic.ini` se necessário.
3. Execute a migration inicial:
   ```bash
   alembic upgrade head
   ```
4. Sempre que mudar o modelo, gere uma nova migration:
   ```bash
   alembic revision --autogenerate -m "descrição"
   alembic upgrade head
   ```

## Segurança

Nunca versione `.env`. As rotas de negócio exigem um token Bearer; o primeiro administrador pode ser registrado pelo endpoint `/auth/registrar`, e os demais devem ser criados por um processo administrativo controlado.

## Recuperação de senha

O link “Esqueceu sua senha?” abre `recuperar-senha.html`. Em desenvolvimento, o link temporário aparece no terminal da API. Em produção, configure SMTP no `.env` para entregá-lo por e-mail. O token expira em 15 minutos e a solicitação não revela se o e-mail existe no sistema.
