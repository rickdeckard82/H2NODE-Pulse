# Contas, login e MFA

Referência das regras de conta e da API de identidade, para quem integra ou desenvolve. Para
configurar pelo portal, veja o [Guia do administrador](CONFIGURACOES.md). O contrato completo
está em [openapi.yaml](openapi.yaml). Nenhum domínio ou usuário é criado automaticamente.

## Chave de identidade

`secrets/identity_key.txt` cifra no banco os segredos de MFA, a senha do SMTP, o webhook e a
chave do Google Chat e as mensagens na fila de envio. Ela é criada pelo `infra/bootstrap.py`.
**Não a gere de novo nem a perca:** sem ela, esses dados não podem mais ser lidos. Guarde uma
cópia fora do servidor; o backup automático também a inclui.

## E-mail por variáveis de ambiente (alternativa)

O normal é configurar o e-mail pela tela (veja [CONFIGURACOES.md](CONFIGURACOES.md)). Enquanto
nenhuma configuração for salva pela tela, o worker usa as variáveis de ambiente abaixo. Para
isso, prepare o servidor, o remetente, o usuário e um arquivo com a senha fora do Git; definir `EMAIL_HOST`, `EMAIL_PORT` (587 por padrão), `EMAIL_HOST_USER`,
`DEFAULT_FROM_EMAIL` e `SMTP_SECRET_PATH`. Não colocar a senha em `.env` ou no
comando. O override `compose.identity-smtp.yaml` monta o segredo apenas no worker
e acrescenta sua rede de saída. STARTTLS e verificação de certificado são
obrigatórios; não há opção de desligá-los na configuração de produção.

Exemplo, com o comando interativo que cria o primeiro administrador (alternativa ao
`BOOTSTRAP_ADMIN_*` do `.env`):

```sh
docker compose -f compose.yaml -f compose.identity-smtp.yaml config --quiet
docker compose -f compose.yaml -f compose.identity-smtp.yaml up -d --wait
docker compose exec api python manage.py bootstrap_admin --email EMAIL_CORPORATIVO --domain DOMINIO_EXATO
```

Substitua os dois argumentos pelos valores reais. Em produção, inclua também
`-f compose.production.yaml` antes do override SMTP. Se possível, limite a saída de rede do
servidor ao provedor de e-mail.

O comando solicita a senha duas vezes sem eco, cadastra o domínio inicial e
recusa execução se já existe administrador. Não cria senha padrão, não marca
e-mail como verificado e não imprime tokens. O código vai à caixa autorizada;
confirmar pelo endpoint e ativar o MFA em Perfil. Se expirar antes
da configuração de SMTP, solicitar novo código em `/auth/resend/`.

## Uso da API

Prefixo comum: `/api/v1`. Obter `GET /auth/csrf/`, preservar o cookie e enviar
o valor `csrfToken` no cabeçalho `X-CSRFToken` em toda mutação. Refazer a leitura
após login/logout, que rotacionam a sessão/CSRF. Cookies são a credencial; não
persistir senha, tokens ou segredo MFA em localStorage. Respostas privadas têm
`Cache-Control: no-store`. Tokens de e-mail vão no corpo JSON, nunca na URL.

| Ação | Endpoint/método | Corpo/resultado |
|---|---|---|
| Cadastro | POST `/auth/register/` | `name`, `email`; resposta genérica com duração mínima fixa |
| Confirmar cadastro | POST `/auth/confirm/` | `token` do e-mail (uso único) e `password`; a senha só é definida aqui, por quem recebeu o código, e o MFA/dispositivos anteriores são descartados |
| Reenviar confirmação | POST `/auth/resend/` | `email`; invalida código anterior |
| Login | POST `/auth/login/` | `email`, `password`; status `authenticated` ou `mfa_required` |
| Confirmar MFA ou recuperar | POST `/auth/mfa/verify/` | `code` TOTP ou código de recuperação e `remember_device` opcional (false por padrão) |
| Esqueci a senha | POST `/auth/forgot/` | `email`; resposta genérica |
| Redefinir senha | POST `/auth/reset/` | `token`, `password`; revoga sessões, preserva MFA |
| Perfil atual | GET `/auth/me/` | Dados próprios e foto, sem material de autenticação |
| Editar perfil | PATCH `/auth/me/` | `first_name` e/ou `avatar` (data URL JPEG até 100 KB; vazio remove); e-mail não é aceito |
| Logout | POST `/auth/logout/` | `{}`; encerra sessão atual |
| Revogar todas | POST `/auth/revoke/` | `{}`; encerra todas as sessões da conta |
| Alterar senha autenticado | POST `/auth/password/` | `current_password`, `new_password`; revoga sessões e dispositivos lembrados |
| Ativar MFA | POST `/auth/mfa/enable/` | `password`; retorna segredo e URI |
| Confirmar ativação | POST `/auth/mfa/enable/confirm/` | `code` do autenticador; revoga outras sessões e retorna oito códigos de recuperação |
| Desativar MFA | POST `/auth/mfa/disable/` | `password` e `code` TOTP ou de recuperação; revoga outras sessões e dispositivos lembrados |
| Substituir MFA | POST `/auth/mfa/replace/` | `password`; exige login MFA há menos de cinco minutos |
| Confirmar substituição | POST `/auth/mfa/replace/confirm/` | `code` do novo dispositivo; revoga sessões antigas e retorna novos códigos de recuperação |

No portal público, somente **Criar conta** e **Recuperar senha** aparecem como
alternativas ao login. Um cadastro elegível já cria e enfileira o código de
confirmação; ao concluir o formulário, o portal abre diretamente a etapa para
informar esse código e permite reenviá-lo. Da mesma forma, a tela para definir a
nova senha aparece depois de solicitar a recuperação. A troca e a confirmação de
novo e-mail ficam em **Perfil**, exigem sessão e senha atual para iniciar e
revogam as sessões depois da confirmação.

Após o login, o cabeçalho apresenta um avatar circular local com a inicial do
nome e um menu de conta. O menu contém **Alterar senha**, **Perfil** e **Sair**;
**Administração** aparece somente para o papel administrador. Não há mais ação
visual separada para esquecer o dispositivo. A troca de senha revoga também os
dispositivos lembrados e exige novo login.

Senha inválida, conta desativada/não confirmada e usuário ausente não são
diferenciados no login. Campos adicionais de privilégio são rejeitados no
cadastro. Erros usuais: 400 para entrada/token inválido, 403 para sessão/permissão
ou CSRF, 404 para objeto fora do escopo, 429 com Retry-After para limite atingido.
Falha CSRF anterior ao DRF pode retornar HTML; clientes devem tratar pelo status.

## Organização e permissões

Listas paginadas, 25 itens por página, ordenadas por ID. `/users/` lista apenas a
própria conta para colaboradores, técnicos e gestores; administrador
pode consultar todas. `GET /users/{id}/` segue o mesmo escopo. O único PATCH de
usuário é administrativo: `role`, `department`, `is_active`, sempre com `reason`.
Não há DELETE, criação privilegiada pública ou edição genérica de senha/MFA.
O administrador desativa o MFA de outra conta em `POST /users/{id}/disable-mfa/`
(`reason`). O MFA é opcional; ver
[ADR 0008](decisoes/0008-mfa-opcional.md).
Autoinscrição cria o papel **Usuário** (somente wiki; ver ADR 0009). Para liberar chamados, o administrador promove a conta a Colaborador. Para cadastrar técnicos, confirmar a conta e depois promovê-la.

`/departments/`: leitura por autenticados; criação/alteração apenas pelo admin.
`/groups/`: admin vê todos; técnico/gestor vê apenas memberships autorizados e
ativos; colaborador não herda grupo por área. `/memberships/`: admin lista/cria
ou remove a relação. Só contas confirmadas de técnico/gestor entram em grupos.
`/users/`: POST (admin) cria conta de colaborador com `email`, `first_name`, `department` opcional e `reason`; a pessoa recebe convite por e-mail (72 h) e define a senha pelo fluxo de redefinição, que também confirma o e-mail. PATCH altera papel, área e ativação com motivo.

`/settings/domains/`: todas as operações exigem admin; criar, alterar e remover (DELETE com `reason`) exigem motivo. Remover um domínio ativo desativa as contas dele, como a desativação, e é recusado se bloquear o último administrador ativo.
Domínios não são renomeados: cadastrar o novo e desativar o anterior.

Toda alteração administrativa de conta revoga sessões. Mudança para papel sem
atendimento ou desativação remove memberships. Não é possível remover o último
administrador ativo, inclusive desativando seu domínio. O acesso a chamados segue as regras
de [TICKETS.md](TICKETS.md).

## Diagnóstico e testes

O worker processa uma mensagem a cada ciclo. Erro SMTP mantém a mensagem cifrada
com retry/backoff até expirar; sucesso remove seu payload. Nunca imprimir o
conteúdo da fila, credenciais ou exceções SMTP que possam repetir dados sensíveis.
Contadores `attempts`, `next_attempt_at`, `sent_at` permitem inspeção operacional. Os
avisos de chamados aparecem em **Administração → Entregas**.

```sh
python tests/run_identity.py
```

Esse comando usa `compose.test.yaml` e um PostgreSQL separado em tmpfs. Cria o
banco de testes com o administrador do cluster isolado; os testes usam a role
`pulse`, sem superuser/createdb. Ao terminar, para/remove somente o container
temporário de testes. Não executa testes no banco da aplicação e não remove seus
volumes. Os dados são sintéticos.

O provisionamento automático opt-in via `.env` e a exceção auditada de confiança
no e-mail do administrador inicial estão em [CONFIGURACOES.md](CONFIGURACOES.md).
O comando interativo `bootstrap_admin` mantém o comportamento anterior de confirmação.

## QR Code e dispositivo lembrado

O cadastro do autenticador mostra QR Code gerado no navegador e chave manual.
Marque **Lembrar este dispositivo por 30 dias** somente em navegador pessoal.
Após o MFA válido, logins nesse navegador ainda pedem senha, mas dispensam o
código até o prazo original de 30 dias. A validade não se renova ao fazer login.

**Sair** mantém a confiança; **Sair e esquecer dispositivo** encerra a sessão e
remove a confiança atual (`POST /auth/forget-device/`, com CSRF). A revogação
`POST /auth/revoke/` revoga sessões e todos os dispositivos. Trocas de senha/MFA,
alterações de acesso e desativação invalidam o uso da confiança. Nenhuma chave
ou credencial é persistida em localStorage. O cookie é HttpOnly e Secure em produção.

Substituir o autenticador exige MFA recente: um login com dispositivo lembrado
não cumpre esse requisito. Use **Sair e esquecer dispositivo** e faça login com
MFA/recuperação antes da substituição. Não confundir confiança no navegador com
confirmação de domínio corporativo ou recuperação de senha.
