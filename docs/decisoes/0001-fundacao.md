# ADR 0001 — fundação

Data: 29/10/2026. Decisão: Django confirmado pelo usuário; iniciar somente a etapa 1.

O plano anterior foi copiado para `docs/PLANO_DE_EXECUCAO.md`, agora canônico neste repositório. Os três arquivos de instruções da raiz apontam para ele. As etapas seguintes permanecem bloqueadas até a validação da fundação.

- Django 5.2 LTS, DRF e PostgreSQL: monólito modular com API e worker separados. React com TypeScript e Vite para frontend independente.
- Banco obrigatório PostgreSQL, inclusive nas integrações de teste. Nenhum fallback SQLite.
- Modelo User derivado de AbstractUser desde a primeira migração, apenas como âncora de identidade; evita trocar AUTH_USER_MODEL depois. Fluxos de autenticação, e-mail obrigatório/verificado, papéis e MFA pertencem à etapa 2; não expor admin ou cadastro nesta etapa.
- Role PostgreSQL `pulse`, sem superuser/createdb/createrole, dona do banco de aplicação para as migrações iniciais. Segredo do administrador restrito ao serviço db. Separar role de migração e runtime quando a auditoria append-only for implementada na etapa 3. Nome da role fixo nesta fundação; POSTGRES_USER deve permanecer pulse.
- Worker inicial mantém heartbeat e verifica conexão; não processa notificações. Outbox e handlers serão implementados nas etapas 3/5. Egress externo não é necessário ainda; a rede privada é interna.
- API não publica porta. Gateway define o protocolo encaminhado por configuração fixa e descarta cabeçalhos do cliente. Por enquanto não preservar IP original em auditoria; adicionar cadeia confiável NPM→gateway somente após conhecer as redes autorizadas.
- Sem anexos e antimalware nesta etapa; volumes e ClamAV serão adicionados na etapa 4 junto com a quarentena. Não implantar um serviço sem fluxo validado que o utilize.
- Ambiente padrão Compose usa loopback. Produção exige override, hosts/origens HTTPS reais e firewall permitindo apenas NPM. Publicação e decisões corporativas não fazem parte desta etapa.
- Domínios corporativos, retenção, SLA, Chat e SMTP permanecem pendentes para suas etapas; não impedem a fundação local.

Referências: https://www.djangoproject.com/download/ ; https://www.django-rest-framework.org/ ; https://vite.dev/guide/ . Versões efetivas estão nos lockfiles, não devem ser inferidas a partir deste texto.
