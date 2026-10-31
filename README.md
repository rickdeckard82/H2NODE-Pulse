# Pulse Services

Gestão interna de chamados de TI. Backend Django/DRF, frontend React/TypeScript e PostgreSQL, com Docker Compose e acesso de produção por Nginx Proxy Manager.

**Status:** etapas 1 a 4 aprovadas tecnicamente no escopo local: portal, console, administração e anexos privados com ClamAV implementados. Próxima etapa: e-mail e Google Chat (5). Consulte [o registro da etapa 4](docs/validacoes/etapa-04.md). Notificações externas e produção ainda não estão homologadas.

## Documentação

- [Plano e critérios por etapa](docs/PLANO_DE_EXECUCAO.md)
- [Decisões iniciais](docs/decisoes/0001-fundacao.md)
- [Decisões de identidade](docs/decisoes/0002-identidade.md)
- [Operação e API de identidade](docs/IDENTIDADE.md)
- [Portal e anexos privados](docs/PORTAL_ANEXOS.md)
- [Operação e API de tickets](docs/TICKETS.md)
- [Decisões de tickets e auditoria](docs/decisoes/0003-tickets.md)
- [Instruções para Codex e Claude](agent.md), carregadas por `AGENTS.md` e `CLAUDE.md`
- [Contrato OpenAPI inicial](docs/openapi.yaml)
- [Operação e Nginx Proxy Manager](docs/OPERACAO.md)
- [Runner do CI no servidor Docker](infra/ci-runner/README.md)

## Subir localmente

Requisitos: Docker Engine com containers Linux, Compose 2.24.4 ou superior e Python 3.14 para os scripts de preparação. Não precisa instalar Python/Node no host para executar os serviços, apenas para preparação/checks locais. O script de bootstrap usa somente a biblioteca padrão.

```sh
python infra/bootstrap.py
docker compose config --quiet
docker compose up --build --wait --wait-timeout 600
```

Acesse `http://localhost:8080`. O bootstrap cria `.env` de desenvolvimento e cinco arquivos aleatórios em `secrets/`, incluindo a chave de identidade e a senha runtime, sem sobrescrever valores existentes. Execute-o novamente após atualizar para a etapa 3. Esses arquivos são ignorados pelo Git. Não publicar essa configuração de desenvolvimento. O portal oferece acesso, abertura e atendimento de chamados. Configure domínios, administrador inicial, grupos e categorias conforme [Identidade](docs/IDENTIDADE.md). Não há conta ou senha padrão.

Ordem: PostgreSQL saudável → migração única → permissões do banco → API/worker → gateway. Migrações usam a role proprietária `pulse`; API/worker usam `pulse_runtime`, com senha separada e auditoria append-only. A API e o worker compartilham a imagem; não executam migrações concorrentes no startup. Os volumes `postgres_data`, `attachments` e `clamav_data` persistem banco, anexos e definições antimalware. Reserve 4 GiB adicionais para o ClamAV; a primeira inicialização pode levar vários minutos. `docker compose down` preserva o volume; **não usar `down -v` em ambiente com dados a preservar**.

Desenvolvimento com hot reload:

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

Frontend em `http://localhost:5173`, API pelo proxy do Vite. Não use o override dev em produção. Em Linux, assegurar permissão do usuário UID 1000 do container Node na pasta frontend; dependências são instaladas no bind mount local.

## Administrador inicial e configurações

O startup pode provisionar o primeiro administrador via `BOOTSTRAP_ADMIN_*` no
`.env`, sem senha padrão e sem redefinir a senha em reinícios. Depois do MFA,
acesse **Administração → SMTP** e **Domínios de confiança**. Consulte
[as instruções de configuração](docs/CONFIGURACOES.md) e
[a validação incremental](docs/validacoes/ajuste-bootstrap-smtp.md).

## Checks locais

```sh
python -m venv .venv
# Linux/macOS: .venv/bin/python; Windows: .venv\Scripts\python
.venv/bin/python -m pip install --require-hashes -r backend/requirements-dev.txt
.venv/bin/python infra/check_backend.py
cd frontend
npm ci
npm run lint
npm run build
```

Na raiz, com Docker disponível:

```sh
python tests/verify_compose.py
docker compose exec -T api python manage.py migrate --check
docker compose exec -T api python manage.py makemigrations --check --dry-run
python tests/smoke_docker.py
python tests/run_identity.py
# Instalar Chromium uma vez: na pasta frontend, npx playwright install chromium
python tests/run_e2e.py
```

O smoke test reinicia serviços de desenvolvimento e verifica prontidão, migrações, identidade do cluster persistida e runtime sem root. Não executá-lo em produção. A suíte de identidade/tickets usa outro cluster PostgreSQL em tmpfs e testa autenticação, CSRF, permissões, ciclo de atendimento, concorrência, idempotência, rollback, privilégios de banco e SMTP local. Não envia mensagens a pessoas reais. Os testes unitários de saúde simulam a conexão; não substituem esses testes reais.

## Dependências

Python: entradas em `backend/requirements*.in`, locks completos com hashes em `backend/requirements*.txt`. Regenerar com `pip-compile --generate-hashes --allow-unsafe --strip-extras` usando Python 3.14 e revisar a alteração. `--allow-unsafe` inclui também as ferramentas de instalação (pip/setuptools) no lock, necessárias em ambientes limpos. Frontend: versões exatas no `package.json`, árvore em `package-lock.json`, instalação por `npm ci`. Imagens usam tags explícitas; atualização exige novo build, verificação de segurança e smoke test. Não usar `latest`.

Pipeline em `.gitea/workflows/ci.yml`: checks backend, contrato, frontend, topologia Compose, build, migrações reais e persistência. A existência do workflow não comprova execução no Gitea; confirmar resultado antes de aprovar a etapa.

O Gitea Actions está habilitado e possui runner dedicado no servidor Docker, com label `ubuntu-latest`. Consulte o [registro de validação](docs/validacoes/etapa-01.md) para os resultados e a [documentação do Gitea Actions](https://docs.gitea.com/usage/actions/quickstart/) para os requisitos.

O E2E cria o projeto Docker separado `pulse-e2e`, usa banco tmpfs e contas sintéticas
com credenciais temporárias. A porta 8081 deve estar livre. Logs, relatórios e screenshots
ficam em `work/` (ignorado pelo Git); o runner encerra os containers e remove a fixture
de credenciais ao terminar. No CI Linux, instalar Chromium com `--with-deps`.
