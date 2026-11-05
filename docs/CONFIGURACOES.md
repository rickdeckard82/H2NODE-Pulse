# Administrador inicial, SMTP e domínios de confiança

## Primeiro acesso pelo Docker

Configure no `.env` local, ignorado pelo Git. Os valores abaixo são exemplos;
substitua o e-mail e preencha uma senha forte antes de criar um banco novo:

```dotenv
BOOTSTRAP_ADMIN_ENABLED=true
BOOTSTRAP_ADMIN_EMAIL=administrador@empresa.example
BOOTSTRAP_ADMIN_NAME=Administrador
BOOTSTRAP_ADMIN_PASSWORD=
BOOTSTRAP_ADMIN_TRUST_EMAIL=true
```

Suba com `docker compose up --build -d --wait --wait-timeout 600`.
O job `migrate` aplica migrações e executa `initialize_admin` antes de liberar
os grants e o startup de API/worker. O bootstrap é serializado pelo lock de
identidade, usa a política normal de senha e registra auditoria.

`BOOTSTRAP_ADMIN_TRUST_EMAIL=true` é uma declaração explícita do operador sobre
a identidade inicial: permite configurar SMTP após entrar, sem depender de um
e-mail que ainda não pode ser enviado. O MFA é opcional, mas recomendado ao
administrador: depois de entrar, ative em **Perfil**, escaneie o QR Code ou cadastre
a chave no autenticador, informe o código e guarde os códigos de recuperação. Essa
opção não confirma cadastros comuns.

Com `TRUST_EMAIL=false`, o administrador precisa confirmar o código recebido por
SMTP. Sem `BOOTSTRAP_ADMIN_ENABLED=true`, o startup não provisiona ninguém.
O comando interativo `bootstrap_admin` permanece disponível e exige confirmação.

Reiniciar não redefine senha, MFA, papel ou domínio. Se outro administrador já
existe, nenhuma conta adicional é criada. Conta comum nunca é promovida por esse
mecanismo. Conta ou domínio desativado não é reativado. A senha do `.env` pode ser
removida após a primeira criação; só é obrigatória para criar uma conta nova.
Para recuperação de senha de uma conta existente, use o fluxo de recuperação.

Uma conta inicial criada pelo comando operacional anterior, ainda não confirmada,
pode receber a confiança explícita do operador quando o e-mail coincide e há
evento `bootstrap.admin_created`. Isso invalida desafios/sessões anteriores,
preserva a senha e registra `bootstrap.email_trusted`. Não se aplica a contas
criadas por cadastro comum ou com MFA já habilitado.

O `.env` não deve ser versionado. Compose pode expor seu conteúdo ao operador em
`docker compose config`/inspect; não cole essa saída em chamados. API e worker
sobrescrevem a senha de bootstrap com vazio e deixam o bootstrap desativado.
O segredo inicial é consumido apenas pelo job de provisionamento.

## SMTP pela interface

Em **Administração → SMTP**, informe servidor DNS, porta, STARTTLS ou TLS
implícito, usuário, senha, remetente e justificativa. Portas permitidas: 25, 465,
587 e 2525. Normalmente use STARTTLS/587 ou TLS implícito/465, conforme o provedor.
Não há opção de transmissão sem TLS ou de desativar validação de certificado.

A senha é cifrada no banco com a chave externa `IDENTITY_KEY`; GET nunca devolve
senha ou ciphertext, apenas `password_configured`. Campo vazio mantém a senha;
o checkbox de remoção a apaga. Usuário e senha vazios permitem relay autorizado
sem autenticação, mas ainda com TLS. Mudanças exigem sessão de administrador com
MFA e CSRF e registram os nomes dos campos alterados, nunca seus segredos.

Marcar **Ativar envio de e-mails de confirmação e recuperação** habilita o worker.
Salvar não dispara teste de e-mail nem mensagem avulsa; o worker processa a fila
de identidade pendente. Solicite novo código no portal se o anterior expirou.
A configuração é recarregada a cada envio, sem reiniciar containers.

Quando existe registro no painel, ele prevalece sobre o ambiente, inclusive
quando desativado. Antes do primeiro salvamento, a configuração SMTP de ambiente
continua como fallback. O painel indica essa situação; variáveis exclusivas do
worker não são expostas pela API.

O worker base usa `mail_egress`. Na infraestrutura corporativa, limite a saída ao
SMTP autorizado. `SMTP_ALLOWED_HOSTS` pode restringir os nomes DNS exatos aceitos,
separados por vírgula. URLs, portas de serviços HTTP e destinos DNS que resolvam
para loopback/link-local/multicast são recusados. Servidor corporativo em rede
privada é permitido por nome DNS. Erro de DNS/TLS/autenticação mantém a mensagem
na fila com backoff até sua expiração; detalhes potencialmente sensíveis não são
registrados nos logs.

API: `GET/PATCH /api/v1/settings/smtp/`. PATCH inclui `reason`; campos permitidos:
`enabled`, `host`, `port`, `security` (`starttls`/`ssl`), `username`, `password`,
`clear_password` e `from_email`. Contrato completo em `openapi.yaml`.

## Domínios de confiança

Em **Administração → Domínios de confiança**, cadastre o domínio exato e informe
a justificativa. O domínio do administrador inicial é cadastrado no bootstrap.
Confiar no domínio permite solicitar cadastro; a conta comum ainda precisa
confirmar posse do e-mail. Subdomínios não herdam confiança automaticamente.
Desativar um domínio bloqueia as contas afetadas e revoga sessões; a API impede
bloquear o último administrador ativo.

O SMTP também envia notificações de chamados (etapa 5). Homologação com
provedores reais e produção continuam pendentes.

## Empresa

Em **Administração → Empresa**, informe nome, CNPJ, responsável pelas informações,
e-mail do responsável, site e logo em PNG de até 256 KB. Com site cadastrado, o
logo da barra superior abre o site em outra aba. O CNPJ aceita o formato numérico e o alfanumérico, e
os dígitos verificadores são conferidos. O nome e o logo aparecem na barra
superior para todos os usuários logados. CNPJ, responsável e e-mail ficam visíveis
só a administradores. API: `GET/PATCH /api/v1/settings/company/`.

## Log do sistema

Em **Administração → Log do sistema**, veja data e hora, usuário e ação, com filtros
por usuário e por período. O log junta os registros de identidade e configuração e
os de chamados, e é somente leitura. Registra entradas, saídas e logins recusados;
e-mails não cadastrados não são guardados. Consultas a chamados não geram registro.
API: `GET /api/v1/settings/audit/?user=&start=&end=&page=`.

## Retenção de dados

Em **Administração → Retenção de dados**, informe os dias de guarda de chamados
encerrados, usuários, grupos, categorias e áreas desativados, e logs. **Depois do
prazo, os dados são apagados definitivamente**, inclusive os arquivos de anexos.

Use 0 para não remover aquela classe, ou pelo menos 30 dias. Para ativar, digite
REMOVER. Toda alteração reinicia uma carência de 24 horas, e a remoção roda no
máximo uma vez por dia, no serviço `retention`. Desmarcar **Ativar** suspende tudo.

O que ainda é usado por outros dados aguarda: um usuário com chamados ou logs
permanece até eles expirarem. Backups não são alterados, e uma restauração traz os
dados de volta. Decisão e justificativa estão na ADR 0007.

## Quem recebe avisos

E-mail e Chat vão aos membros do grupo do chamado, ao técnico atribuído, aos
participantes e ao solicitante, quando outra pessoa faz uma ação pública. O autor
da ação não recebe. Cadastre os membros em **Administração → Membros dos grupos**.

## Google Chat e diagnóstico de entregas

Em **Administração → Google Chat**, cole o webhook do espaço da TI
(`https://chat.googleapis.com/v1/spaces/…/messages?key=…&token=…`), informe a
justificativa e ative. O webhook é cifrado com `IDENTITY_KEY`, nunca é devolvido
pela API e só é aceito com esse formato. O espaço recebe apenas número, estado
e link de eventos públicos de chamados não restritos.

### App do Google Chat (mensagens individuais)

Cada pessoa recebe os avisos numa conversa privada com o app. O Google não informa
essa conversa a partir do e-mail, então ela é aprendida quando a pessoa instala o
app ou escreve para ele.

1. No Google Cloud, em **Google Chat API → Configuração**, use o URL do endpoint
   `https://SEU-DOMINIO/api/v1/integrations/google-chat/events/` e **Número do
   projeto** como público de autenticação. Em **Visibilidade**, libere os usuários.
2. Em **Administração → Google Chat**, informe o número do projeto e cole a chave
   JSON da conta de serviço. A chave é cifrada e nunca é devolvida pela API.
3. Aguarde o worker baixar os certificados do Google (a tela indica) e instale o
   app no Chat. O app responde confirmando. Quem instalou antes deve mandar
   qualquer mensagem a ele.

O e-mail da conta no Chat precisa ser igual ao do Pulse. A mensagem traz apenas
tipo do evento, número, estado e link, nunca o texto do comentário. Quem não
instalar continua recebendo só e-mail. A rota de eventos é pública e aceita apenas
requisições assinadas pelo Google para o número do projeto configurado.

Em **Administração → Entregas**, veja as últimas 200 entregas com destinatário
mascarado e código de erro sanitizado. **Reenviar** recoloca na fila uma entrega
com falha. **Testar e-mail/Testar Google Chat** enfileiram um teste que o worker
executa (a API não tem saída de rede); o e-mail vai só ao administrador que pediu.
Todas as ações exigem justificativa e são auditadas. Defina `APP_BASE_URL` com a
URL pública do portal para os links das mensagens.

API: `GET/PATCH /api/v1/settings/chat/`, `GET /api/v1/settings/notifications/`,
`POST /api/v1/settings/notifications/{id}/retry/` e
`GET/POST /api/v1/settings/notifications/test/`.

A opção **Lembrar este dispositivo por 30 dias** dispensa o código nos próximos
logins com senha nesse navegador, até expirar ou ser revogada. Consulte
[IDENTIDADE.md](IDENTIDADE.md#qr-code-e-dispositivo-lembrado).
