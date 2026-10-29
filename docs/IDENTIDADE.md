# Operação e contrato de identidade

A etapa 2 entrega a API; a interface de identidade/administração será integrada
na etapa 4. O contrato completo está em `docs/openapi.yaml`. Nenhum domínio ou
usuário corporativo é criado automaticamente.

## Preparação

Executar `python infra/bootstrap.py` novamente após atualizar: ele acrescenta
`secrets/identity_key.txt` sem sobrescrever segredos. Preservar essa chave fora do
banco e em backup protegido. Não a regenerar: segredos MFA e mensagens pendentes
existentes deixariam de ser decifráveis. Django/API/worker leem o arquivo montado.

`docker compose up --build --wait --wait-timeout 180` aplica a migração aditiva
0002. O índice único de e-mail ignora endereços vazios legados, mas bloqueia
duplicidades não vazias sem diferenciar maiúsculas. Se houver contas anteriores,
revisar duplicidades antes da migração e confirmar seus e-mails; nenhuma conta
legada ganha acesso automaticamente. Não apagar contas para fazer a migração passar.

## E-mail e primeiro administrador

O worker base não tem credenciais nem saída para SMTP. Para uma integração
autorizada, preparar host/remetente/usuário e arquivo protegido de senha fora do
Git; definir `EMAIL_HOST`, `EMAIL_PORT` (587 por padrão), `EMAIL_HOST_USER`,
`DEFAULT_FROM_EMAIL` e `SMTP_SECRET_PATH`. Não colocar a senha em `.env` ou no
comando. O override `compose.identity-smtp.yaml` monta o segredo apenas no worker
e acrescenta sua rede de saída. STARTTLS e verificação de certificado são
obrigatórios; não há opção de desligá-los na configuração de produção.

Após autorização aplicável para enviar à caixa configurada:

```sh
docker compose -f compose.yaml -f compose.identity-smtp.yaml config --quiet
docker compose -f compose.yaml -f compose.identity-smtp.yaml up -d --wait
docker compose exec api python manage.py bootstrap_admin --email EMAIL_CORPORATIVO --domain DOMINIO_EXATO
```

Substituir os dois argumentos por valores reais autorizados. Em homologação
adicionar também `-f compose.production.yaml` antes do override SMTP. Restringir
egress no host ao provedor configurado. O teste local desta etapa usa servidor
SMTP sintético em loopback; não comprova TLS/aceite do provedor corporativo.

O comando solicita a senha duas vezes sem eco, cadastra o domínio inicial e
recusa execução se já existe administrador. Não cria senha padrão, não marca
e-mail como verificado e não imprime tokens. O código vai à caixa autorizada;
confirmar pelo endpoint e configurar MFA no primeiro login. Se expirar antes
da configuração de SMTP, solicitar novo código em `/auth/resend/`.

## Uso da API

Prefixo comum: `/api/v1`. Obter `GET /auth/csrf/`, preservar o cookie e enviar
o valor `csrfToken` no cabeçalho `X-CSRFToken` em toda mutação. Refazer a leitura
após login/logout, que rotacionam a sessão/CSRF. Cookies são a credencial; não
persistir senha, tokens ou segredo MFA em localStorage. Respostas privadas têm
`Cache-Control: no-store`. Tokens de e-mail vão no corpo JSON, nunca na URL.

| Ação | Endpoint/método | Corpo/resultado |
|---|---|---|
| Cadastro | POST `/auth/register/` | `name`, `email`, `password`; resposta genérica |
| Confirmar cadastro | POST `/auth/confirm/` | `token` do e-mail, uso único |
| Reenviar confirmação | POST `/auth/resend/` | `email`; invalida código anterior |
| Login | POST `/auth/login/` | `email`, `password`; status `authenticated`, `mfa_required` ou `mfa_setup_required` |
| Iniciar MFA | POST `/auth/mfa/setup/` | `{}`; segredo/URI somente após senha validada |
| Confirmar MFA ou recuperar | POST `/auth/mfa/verify/` | `code` TOTP ou código de recuperação; primeira configuração retorna oito códigos |
| Esqueci a senha | POST `/auth/forgot/` | `email`; resposta genérica |
| Redefinir senha | POST `/auth/reset/` | `token`, `password`; revoga sessões, preserva MFA |
| Perfil atual | GET `/auth/me/` | Dados próprios, sem material de autenticação |
| Logout | POST `/auth/logout/` | `{}`; encerra sessão atual |
| Revogar todas | POST `/auth/revoke/` | `{}`; encerra todas as sessões da conta |
| Trocar e-mail | POST `/auth/email/` | `email` novo e `password` atual |
| Confirmar novo e-mail | POST `/auth/confirm-email/` | `token`; troca endereço e revoga sessões |
| Substituir MFA | POST `/auth/mfa/replace/` | `password`; exige login MFA há menos de cinco minutos |
| Confirmar substituição | POST `/auth/mfa/replace/confirm/` | `code` do novo dispositivo; revoga sessões antigas e retorna novos códigos de recuperação |

Senha inválida, conta desativada/não confirmada e usuário ausente não são
diferenciados no login. Campos adicionais de privilégio são rejeitados no
cadastro. Erros usuais: 400 para entrada/token inválido, 403 para sessão/permissão
ou CSRF, 404 para objeto fora do escopo, 429 com Retry-After para limite atingido.
Falha CSRF anterior ao DRF pode retornar HTML; clientes devem tratar pelo status.

## Organização e permissões

Listas paginadas, 25 itens por página, ordenadas por ID. `/users/` lista apenas a
própria conta para colaboradores, técnicos, gestores e privacidade; administrador
pode consultar todas. `GET /users/{id}/` segue o mesmo escopo. O único PATCH de
usuário é administrativo: `role`, `department`, `is_active`, sempre com `reason`.
Não há DELETE, criação privilegiada pública ou edição genérica de senha/MFA.
Para cadastrar técnicos, confirmar a conta de colaborador e depois promovê-la.

`/departments/`: leitura por autenticados; criação/alteração apenas pelo admin.
`/groups/`: admin vê todos; técnico/gestor vê apenas memberships autorizados e
ativos; colaborador não herda grupo por área. `/memberships/`: admin lista/cria
ou remove a relação. Só contas confirmadas de técnico/gestor entram em grupos.
`/settings/domains/`: todas as operações exigem admin; criar/alterar exige motivo.
Domínios não são renomeados: cadastrar o novo e desativar o anterior.

Toda alteração administrativa de conta revoga sessões. Mudança para papel sem
atendimento ou desativação remove memberships. Não é possível remover o último
administrador ativo, inclusive desativando seu domínio. Administração não concede
acesso a conteúdo de tickets; essa autorização será definida na etapa 3.

## Diagnóstico e testes

O worker processa uma mensagem a cada ciclo. Erro SMTP mantém a mensagem cifrada
com retry/backoff até expirar; sucesso remove seu payload. Nunca imprimir o
conteúdo da fila, credenciais ou exceções SMTP que possam repetir dados sensíveis.
Contadores `attempts`, `next_attempt_at`, `sent_at` permitem inspeção operacional.
O painel de notificações da etapa 5 ainda não existe.

```sh
python tests/run_identity.py
```

Esse comando usa `compose.test.yaml` e um PostgreSQL separado em tmpfs. Cria o
banco de testes com o administrador do cluster isolado; os testes usam a role
`pulse`, sem superuser/createdb. Ao terminar, para/remove somente o container
temporário de testes. Não executa testes no banco da aplicação e não remove seus
volumes. O CI executa a mesma suíte depois do build. Os dados são sintéticos.
