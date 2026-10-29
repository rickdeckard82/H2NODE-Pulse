# Operação da aplicação

Para bootstrap administrativo, configuração de SMTP de identidade, MFA, domínios
e sessões, consultar [IDENTIDADE.md](IDENTIDADE.md). As interfaces de produto
serão implementadas na etapa 4; estas operações são realizadas pela API/comandos.

## Produção atrás do NPM

Esta é uma preparação de infraestrutura, não autorização para publicação. Concluir as etapas e o aceite antes de disponibilizar aos colaboradores.

1. Preparar VM Linux privada com Docker e Compose >= 2.24.4. Clonar versão revisada.
2. Executar `python infra/bootstrap.py`; substituir `.env` pelo conteúdo ajustado de `.env.production.example`. Usar domínio real, IP privado real e origem HTTPS. Manter `127.0.0.1` entre hosts para healthcheck; manter POSTGRES_USER=pulse.
3. Restringir `secrets/` ao operador e aos containers que precisam dele. Em Linux, o bootstrap cria o diretório com modo 0700 e arquivos 0444: outros usuários do host não atravessam o diretório, enquanto o UID não-root do container lê somente o arquivo montado. Em Windows, validar ACLs da pasta. Compose local monta arquivos, não cifra os segredos no disco; cifrar disco/backups e proteger o host. Não flexibilizar as permissões do diretório. Testar a leitura sem imprimir conteúdo.
4. Validar `docker compose -f compose.yaml -f compose.production.yaml config --quiet`. Iniciar com os mesmos arquivos, `up --build --wait --wait-timeout 180`.
5. No NPM, configurar Proxy Host com domínio público → HTTP → IP privado da VM → porta 8080. Ativar certificado, Force SSL e renovação. Não expor painel administrativo do NPM. Para rede privada não confiável, configurar TLS também no enlace interno antes do uso.
6. Firewall deve aceitar a porta 8080 somente da origem do NPM. Portas publicadas Docker podem contornar regras simplificadas do UFW; validar regras de encaminhamento/DOCKER-USER ou equivalente e testar de outra máquina. Binding privado sozinho não restringe a origem.
7. Testar HTTPS, Host, cookies e CSRF, redirecionamentos, saúde e bloqueio de acesso direto. Não publicar PostgreSQL, API ou worker.

Não passar overrides dev junto de produção. O proxy usa esquema fixo HTTPS em produção: essa configuração depende de acesso restrito pelo NPM. Encaminhamento de IP original ainda não implementado; não confiar no X-Forwarded-For recebido do usuário.

## Saúde e logs

`/api/v1/health/live/` verifica processo; `/api/v1/health/ready/` verifica conexão PostgreSQL, retornando 503 sem detalhes sensíveis quando indisponível. As rotas são intencionalmente públicas e mínimas. Migrações são requisito do startup; não são verificadas a cada probe. `/api/v1/schema/` exige sessão verificada de administrador com MFA; contrato estático em docs/openapi.yaml.

`docker compose ps` e `docker compose logs --tail=100 api worker migrate` auxiliam diagnóstico. Não habilitar logs de corpos de requisição, segredos ou cabeçalhos de autenticação. Logs Docker têm rotação de 10 MB × 3 por serviço. O worker processa desafios de identidade quando SMTP está configurado; heartbeat não comprova entrega. Notificações de tickets continuam na etapa 5.

## Atualização e dados

Backup e teste de restauração são requisitos da homologação futura. Antes de qualquer migração sobre dados reais, criar backup externo cifrado e verificar restauração. Não inventar rollback de schema: voltar imagem só é seguro quando a migração é compatível. `docker compose down` preserva volumes. Não usar `down -v` nem remover volumes sem autorização explícita.

O script de role PostgreSQL roda apenas quando o volume está vazio. Alterar senha no arquivo depois não altera automaticamente a senha armazenada no banco; usar procedimento de rotação autenticado e atualizar consumidores juntos. Nunca reinicializar o volume para trocar senha.

## Limites atuais

O sistema ainda não está pronto para produção. Identidade, papéis e organização
foram validados pela API; tickets, telas integradas, notificações de atendimento,
anexos, retenção e direitos dos titulares pertencem às próximas etapas. Consultar
os registros das etapas 1 e 2 para evidências locais e limites do CI remoto. A
operação do runner dedicado está documentada em `infra/ci-runner/README.md`.
