# Operação

Tarefas do dia a dia de quem mantém o servidor. A instalação está em
[INSTALACAO.md](INSTALACAO.md) e o backup em [BACKUP.md](BACKUP.md).

Os comandos abaixo rodam na pasta do projeto. Em produção, o `make` já passa os arquivos
certos para o Compose. Sem ele, use sempre:

```sh
docker compose -f compose.yaml -f compose.production.yaml -f compose.backup.yaml <comando>
```

Se faltar algum `-f`, o Compose sobe uma configuração diferente: sem o `compose.backup.yaml`,
por exemplo, o backup para sem nenhum aviso.

## Comandos do dia a dia

| Comando | O que faz |
| --- | --- |
| `make up` | Sobe ou atualiza tudo |
| `make down` | Para tudo, mantendo os dados |
| `make ps` | Mostra o estado de cada serviço |
| `make logs` | Acompanha os logs (Ctrl+C para sair) |
| `make backup` | Faz um backup agora |

> **Nunca use `docker compose down -v` nem apague volumes.** O `-v` apaga o banco, os anexos
> e as definições do antivírus.

## Está tudo funcionando?

- `make ps`: todos os serviços `healthy`, menos `migrate` e `db-permissions`, que terminam em
  `Exited (0)` depois de subir.
- `https://SEU-DOMINIO/api/v1/health/live/` responde 200 enquanto a API estiver de pé.
- `https://SEU-DOMINIO/api/v1/health/ready/` responde 200 se a API alcança o banco e 503 se
  não alcança.
- Avisos por e-mail e Chat: **Administração → Entregas** mostra as últimas 200 tentativas e
  o motivo das falhas.

Para investigar um problema:

```sh
docker compose logs --tail=100 api worker migrate
```

Os logs nunca mostram senhas, conteúdo de chamados nem cabeçalhos de autenticação. Cada
serviço guarda até 30 MB de log (3 arquivos de 10 MB).

## Atualizar

```sh
make backup && git pull && make up
```

O serviço `migrate` aplica as mudanças no banco antes de a API subir. Não há desfazer
automático: se a nova versão der problema, volte o código e restaure o backup feito antes.

## Antivírus (ClamAV)

Todo anexo fica em quarentena até o ClamAV aprovar. Se o antivírus parar, o sistema continua
funcionando, mas os anexos novos ficam sem download até ele voltar. Ele baixa definições
novas sozinho, pela internet.

- Estado: `docker compose ps antimalware`.
- A checagem de saúde não avisa quando as definições estão desatualizadas. Confira de vez em
  quando nos logs: `docker compose logs --tail=50 antimalware`.

## Senhas do banco

O PostgreSQL usa três contas, cada uma com sua senha em `secrets/`:

| Conta | Quem usa | Para quê |
| --- | --- | --- |
| administrador (`postgres_admin_password`) | só `db-permissions` | Aplica as permissões depois das migrações |
| `pulse` (`postgres_password`) | `migrate` e `retention` | Dono das tabelas: aplica as migrações e apaga dados vencidos, inclusive o log de auditoria |
| `pulse_runtime` (`postgres_runtime_password`) | `api` e `worker` | Uso normal; não altera a estrutura nem apaga o log de auditoria |

Para trocar a senha do `pulse_runtime`: altere o arquivo em `secrets/`, rode `make up` (o
`db-permissions` grava a senha nova no banco) e reinicie quem a usa:
`docker compose restart api worker`. Entre os dois comandos, a API pode falhar por alguns
segundos.

As senhas das contas `pulse` e administrador são gravadas só quando o banco é criado. Para
trocá-las, altere no PostgreSQL (`ALTER ROLE … PASSWORD …`) e depois o arquivo. **Nunca
apague o volume do banco para "resetar" uma senha.**

Não rode `manage.py migrate` dentro do container `api`: ele usa a conta `pulse_runtime`, que
não pode alterar tabelas. As migrações rodam pelo serviço `migrate` no `make up`.

## Proxy e IP dos usuários

O IP do usuário aparece no chamado (quando ele autoriza) e é usado no limite de tentativas de
login. Para isso, `TRUSTED_PROXY_COUNT` no `.env` deve ser o número de proxies antes da API:

- `2`: proxy reverso + gateway do Pulse (o caso normal);
- `1`: gateway exposto diretamente, sem proxy reverso;
- `0` (padrão): o IP visto é o do gateway. Todos os usuários dividem um único limite de 500
  tentativas de login a cada 15 minutos.

O sistema confia apenas nos IPs adicionados pelos proxies. Um valor inventado pelo navegador
no `X-Forwarded-For` é ignorado.

## Fuso horário

O número dos chamados (`AAAAMM` + sequência) e os relatórios usam o horário de Brasília
(`America/Sao_Paulo`), fixo no código. O SLA usa o fuso informado na política de SLA. O banco
guarda as datas em UTC.
