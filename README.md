# Pulse Services

Gestão interna de chamados de TI. Backend Django/DRF, frontend React/TypeScript e PostgreSQL, com Docker Compose e acesso de produção por Nginx Proxy Manager.

**Status:** etapa 1 — fundação em validação. Ainda não há cadastro corporativo, login de produto, tickets ou notificações implementados. Consulte [a validação](docs/validacoes/etapa-01.md) antes de iniciar a etapa 2.

## Documentação

- [Plano e critérios por etapa](docs/PLANO_DE_EXECUCAO.md)
- [Decisões iniciais](docs/decisoes/0001-fundacao.md)
- [Instruções para Codex e Claude](agent.md), carregadas por `AGENTS.md` e `CLAUDE.md`
- [Contrato OpenAPI inicial](docs/openapi.yaml)
- [Operação e Nginx Proxy Manager](docs/OPERACAO.md)

## Subir localmente

Requisitos: Docker Engine com containers Linux, Compose 2.24.4 ou superior e Python 3.14 para os scripts de preparação. Não precisa instalar Python/Node no host para executar os serviços, apenas para preparação/checks locais. O script de bootstrap usa somente a biblioteca padrão.

```sh
python infra/bootstrap.py
docker compose config --quiet
docker compose up --build --wait --wait-timeout 180
```

Acesse `http://localhost:8080`. O bootstrap cria `.env` de desenvolvimento e três arquivos aleatórios em `secrets/`, sem sobrescrever valores existentes. Esses arquivos são ignorados pelo Git. Não publicar essa configuração de desenvolvimento.

Ordem: PostgreSQL saudável → migração única → API/worker → gateway. A API e o worker compartilham a imagem; não executam migrações concorrentes no startup. O volume `postgres_data` persiste dados. `docker compose down` preserva o volume; **não usar `down -v` em ambiente com dados a preservar**.

Desenvolvimento com hot reload:

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

Frontend em `http://localhost:5173`, API pelo proxy do Vite. Não use o override dev em produção. Em Linux, assegurar permissão do usuário UID 1000 do container Node na pasta frontend; dependências são instaladas no bind mount local.

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
```

O smoke test reinicia serviços de desenvolvimento e verifica prontidão, migrações, identidade do cluster persistida e runtime sem root. Não executá-lo em produção. Os testes unitários de saúde simulam a conexão; não substituem esse teste real.

## Dependências

Python: entradas em `backend/requirements*.in`, locks completos com hashes em `backend/requirements*.txt`. Regenerar com `pip-compile --generate-hashes` usando Python 3.14 e revisar a alteração. Frontend: versões exatas no `package.json`, árvore em `package-lock.json`, instalação por `npm ci`. Imagens usam tags explícitas; atualização exige novo build, verificação de segurança e smoke test. Não usar `latest`.

Pipeline em `.gitea/workflows/ci.yml`: checks backend, contrato, frontend, topologia Compose, build, migrações reais e persistência. A existência do workflow não comprova execução no Gitea; confirmar resultado antes de aprovar a etapa.

O Gitea Actions precisa estar habilitado no reposit?rio, com runner Linux de label `ubuntu-latest`, Docker Engine e Compose acess?veis. A disponibilidade do runner e a execu??o remota ainda n?o foram verificadas. Consulte a [documenta??o do Gitea Actions](https://docs.gitea.com/usage/actions/quickstart/).
