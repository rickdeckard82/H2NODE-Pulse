# ADR 0002 — identidade e organização

Data: 29/10/2026. Escopo: etapa 2, após aprovação registrada da fundação.

## Decisões

- Identidade e administração entregues pela API. Telas do portal/console e seus
  testes Playwright permanecem na etapa 4, conforme o plano; o frontend inicial
  continua exibindo a preparação do portal.
- Login por e-mail normalizado, domínio exato e conta confirmada. O username
  herdado do Django é um identificador interno. Cadastro público não aceita
  campos de privilégio. Flags `is_staff`/`is_superuser` não concedem permissões
  na API de produto. Papéis são explícitos e independentes de áreas e grupos.
- Senhas Argon2id; PBKDF2 mantido apenas para leitura de hashes legados. Cookies
  de sessão HttpOnly/SameSite=Lax, Secure em produção, duração de oito horas.
  CSRF também é obrigatório nas ações anônimas, inclusive login e cadastro.
- Uma versão por conta invalida todas as sessões e desafios pendentes após
  recuperação/troca de e-mail, alteração administrativa ou revogação explícita.
  Desativação e remoção de domínio também são verificadas a cada requisição.
- Domínio desativado desativa suas contas e remove memberships; reativar o
  domínio não reativa contas automaticamente. A decisão e o motivo ficam na
  auditoria. Impedir a operação quando bloquearia o último administrador ativo.
- MFA TOTP obrigatório para técnico, gestor, administrador e privacidade. Login
  com senha concede somente desafio de cinco minutos. Configuração exige
  comprovar um código; códigos já consumidos não são aceitos novamente.
  O segredo é cifrado por Fernet com chave externa ao banco e às imagens.
- Oito códigos aleatórios de recuperação, exibidos uma única vez e persistidos
  como HMAC. Recuperação não desliga MFA. A substituição do autenticador exige
  MFA/recuperação realizada nos últimos cinco minutos, senha e código do novo
  dispositivo; revoga sessões antigas e troca todos os códigos de recuperação.
- Token de e-mail aleatório, de uso único, vinculado à finalidade, endereço e
  versão da conta, validade de 30 minutos. Revalidar domínio na confirmação.
  Reenvio invalida o token anterior. Não retornar tokens de e-mail pela API.
- Fila pequena exclusiva para desafios de identidade: payload cifrado, retry
  limitado pela validade, limpeza periódica e remoção do payload após aceite
  SMTP. Respostas genéricas e envio assíncrono reduzem enumeração por resposta
  ou latência SMTP. Esta fila não substitui a outbox de tickets da etapa 3 nem
  a infraestrutura completa de notificações da etapa 5.
- Envio SMTP mantém lock curto de uma mensagem até o resultado, com timeout de
  dez segundos; outros workers usam SKIP LOCKED. Não há garantia exactly-once:
  falha após aceite pode repetir o mesmo código. O consumidor só o aceita uma vez.
- Rate limit persistente e atômico no PostgreSQL: dez tentativas por identidade
  e ação por janela de 15 minutos, mais 500 por origem de conexão. E-mail/origem
  são HMACs na tabela temporária, limpa pelo worker. O limite por origem pode ser
  compartilhado pelo gateway: não confiar em X-Forwarded-For antes da etapa 8.
- Escritas administrativas e resgate de tokens usam advisory lock transacional;
  login/MFA usam locks de linha. A baixa concorrência esperada desta etapa permite
  esse bloqueio mais amplo. Testes concorrentes usam conexões PostgreSQL reais.
- Auditoria de identidade registra UTC, ator, ação, objeto e mudanças/motivo,
  sem senha, token ou segredo MFA. A separação de roles e a proteção append-only
  no banco pertencem à etapa 3; não alegar imutabilidade nesta etapa.

## Dependências e limites

Domínios reais, SMTP e administradores corporativos não foram inventados ou
configurados. O bootstrap administrativo exige senha interativa, e-mail
confirmado e MFA. Sem SMTP configurado, desafios expiram sem envio; não há
fallback que imprima códigos em console ou os devolva ao cliente.

A perda simultânea do autenticador e de todos os códigos não oferece bypass
na API. Exige procedimento operacional com verificação de identidade e registro
do responsável, a definir antes da homologação. Não usar reset de senha para
remover MFA. Backup/rotação da chave de identidade será homologado na etapa 8.

## Referências oficiais consultadas

- [Django: senhas e Argon2](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/)
- [Django: autenticação e sessões](https://docs.djangoproject.com/en/5.2/topics/auth/default/)
- [PyOTP: TOTP, proteção contra replay e rate limit](https://pyauth.github.io/pyotp/)
- [Cryptography: Fernet](https://cryptography.io/en/latest/fernet/)
