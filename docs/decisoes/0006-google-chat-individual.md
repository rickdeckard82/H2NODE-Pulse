# ADR 0006 — avisos individuais no Google Chat

Data: 04/11/2026.

Cada pessoa recebe avisos numa conversa privada com um app do Google Chat, além
do e-mail. O webhook do espaço geral da TI continua existindo.

O Google recusa a busca da conversa por e-mail com conta de serviço (HTTP 403,
testado em 04/11/2026). Por isso a conversa é aprendida pelos eventos do próprio
app: `ADDED_TO_SPACE` e `MESSAGE` vinculam o e-mail do evento à conta do Pulse, e
`REMOVED_FROM_SPACE` desfaz. A alternativa pelo diretório do Workspace foi
descartada por exigir delegação de um super admin.

Consequências:

- `POST /api/v1/integrations/google-chat/events/` é a primeira rota pública que
  altera dados sem sessão. Só aceita JWT assinado por
  `chat@system.gserviceaccount.com` para o número do projeto configurado.
- A API não tem saída de rede. O worker baixa os certificados públicos do Google
  a cada hora e os guarda em `ChatConfiguration`; a API só verifica localmente.
- Nova dependência: `google-auth[requests]`, para verificar o JWT e obter o token
  da conta de serviço, como o Google recomenda.
- A mensagem traz tipo do evento, número, estado e link, nunca o texto do
  comentário, porque chamados restritos e notas internas também usam este canal.

Risco aberto: a documentação não confirma que o evento traz `user.email`. Sem esse
campo o vínculo não acontece e a API registra `chat_event_without_email`;
seria preciso conectar a conta por código.
