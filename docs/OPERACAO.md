# Operação da aplicação

Para bootstrap administrativo, configuração de SMTP de identidade, MFA, domínios
e sessões, consultar [IDENTIDADE.md](IDENTIDADE.md). As interfaces de produto
serão implementadas na etapa 4; estas operações são realizadas pela API/comandos.
Para categorias, permissões de atendimento, reabertura, fluxo dos tickets e
separação das roles PostgreSQL, consultar [TICKETS.md](TICKETS.md).

## Produção atrás do NPM

Esta é uma preparação de infraestrutura, não autorização para publicação. Concluir as etapas e o aceite antes de disponibilizar aos colaboradores.

1. Preparar VM Linux privada com Docker e Compose >= 2.24.4. Clonar versão revisada.
2. Executar `python infra/bootstrap.py`; substituir `.env` pelo conteúdo ajustado de `.env.production.example`. Usar domínio real, IP privado real e origem HTTPS. Manter `127.0.0.1` entre hosts para healthcheck; manter POSTGRES_USER=pulse.
3. Restringir `secrets/` ao operador e aos containers que precisam dele. Em Linux, o bootstrap cria o diretório com modo 0700 e arquivos 0444: outros usuários do host não atravessam o diretório, enquanto o UID não-root do container lê somente o arquivo montado. Em Windows, validar ACLs da pasta. Compose local monta arquivos, não cifra os segredos no disco; cifrar disco/backups e proteger o host. Não flexibilizar as permissões do diretório. Testar a leitura sem imprimir conteúdo.
4. Validar `docker compose -f compose.yaml -f compose.production.yaml config --quiet`. Iniciar com os mesmos arquivos, `up --build --wait --wait-timeout 180`. Atalho: `make up` sobe a produção já com o backup (`compose.backup.yaml`); `make backup`, `make backup-list` e `make backup-verify` operam o backup.
5. No NPM, configurar Proxy Host com domínio público → HTTP → IP privado da VM → porta 8086. Ativar certificado, Force SSL e renovação. Não expor painel administrativo do NPM. Para rede privada não confiável, configurar TLS também no enlace interno antes do uso.
6. Firewall deve aceitar a porta 8086 somente da origem do NPM. Portas publicadas Docker podem contornar regras simplificadas do UFW; validar regras de encaminhamento/DOCKER-USER ou equivalente e testar de outra máquina. Binding privado sozinho não restringe a origem.
7. Testar HTTPS, Host, cookies e CSRF, redirecionamentos, saúde e bloqueio de acesso direto. Não publicar PostgreSQL, API ou worker.

Não passar overrides dev junto de produção. O proxy usa esquema fixo HTTPS em produção: essa configuração depende de acesso restrito pelo NPM. O gateway acrescenta o endereço de quem o contatou ao X-Forwarded-For e a API só usa o IP do cliente (registrado no chamado quando o solicitante autoriza, no limite de tentativas de login/cadastro e no Turnstile) se `TRUSTED_PROXY_COUNT` for definido: `1` com o gateway diretamente exposto, `2` com NPM + gateway (o NPM precisa enviar o X-Forwarded-For). A API conta os proxies confiáveis a partir da direita; valores forjados pelo navegador, à esquerda, são ignorados. Com `0` (padrão) vale o REMOTE_ADDR, que atrás do proxy é o endereço do gateway. Nesse caso todos os usuários dividem um único limite de 500 tentativas de autenticação a cada 15 minutos; em produção, defina o valor correto. Validar de outra máquina após a homologação do NPM.

## Saúde e logs

`/api/v1/health/live/` verifica processo; `/api/v1/health/ready/` verifica conexão PostgreSQL, retornando 503 sem detalhes sensíveis quando indisponível. As rotas são intencionalmente públicas e mínimas. Migrações são requisito do startup; não são verificadas a cada probe. `/api/v1/schema/` exige sessão verificada de administrador; contrato estático em docs/openapi.yaml.

`docker compose ps` e `docker compose logs --tail=100 api worker migrate` auxiliam diagnóstico. Não habilitar logs de corpos de requisição, segredos ou cabeçalhos de autenticação. Logs Docker têm rotação de 10 MB × 3 por serviço. O worker processa desafios de identidade quando SMTP está configurado; heartbeat não comprova entrega. Notificações de tickets continuam na etapa 5.

## Atualização e dados

Backup cifrado via FTP e restauração estão em [BACKUP.md](BACKUP.md). O teste de restauração continua sendo requisito da homologação. Antes de qualquer migração sobre dados reais, criar backup externo cifrado e verificar restauração. Não inventar rollback de schema: voltar imagem só é seguro quando a migração é compatível. `docker compose down` preserva volumes. Não usar `down -v` nem remover volumes sem autorização explícita.

O script inicial da role proprietária `pulse` roda apenas quando o volume está
vazio. Sua senha e a do administrador exigem rotação explícita no PostgreSQL.
A etapa 3 acrescenta `db-permissions`, executado após as migrações: configura a
senha separada de `pulse_runtime` e aplica grants antes de iniciar API/worker.
Somente o job de migração recebe a senha de `pulse`; o job de permissões recebe
o segredo administrativo. API/worker não recebem nenhum desses dois segredos.
Rotacionar runtime de forma coordenada com job e consumidores. Nunca reinicializar
o volume para trocar senha. Migrações devem ser executadas pelo serviço `migrate`;
o runtime não é proprietário do schema e não deve ser promovido para esse fim.

## Limites atuais

O sistema ainda não está pronto para produção. Identidade, papéis, organização
e núcleo de tickets foram validados pela API; portal, console e anexos foram
aprovados no escopo técnico local da etapa 4. Notificações de atendimento,
retenção e direitos dos titulares continuam nas próximas etapas.
Auditoria é append-only para runtime, sem impedir alterações pelo dono do banco.
Consultar os registros das etapas 1 a 4 para evidências locais e limites do CI remoto. A
operação do runner dedicado está documentada em `infra/ci-runner/README.md`.

## Anexos e antimalware

Consulte [Portal e anexos](PORTAL_ANEXOS.md). API/worker montam o volume privado
`attachments`; o gateway não o monta. ClamAV usa rede interna para INSTREAM e
rede de saída separada para atualizar assinaturas, com reserva de 4 GiB. Sem scan
aprovado, o download fica indisponível. Preserve o volume de anexos junto ao banco
e às chaves na estratégia de backup/restauração. Logs e healthcheck do scanner
não substituem o monitoramento da data das definições.
