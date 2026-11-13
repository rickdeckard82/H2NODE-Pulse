# Operação e API de tickets

Etapa 3: núcleo e API, sem telas de atendimento ou anexos. Contrato completo em
`docs/openapi.yaml` (0.3.0); decisões em `docs/decisoes/0003-tickets.md`.

## Atualização local e contas do banco

```sh
python infra/bootstrap.py
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 180
```

O bootstrap acrescenta `secrets/postgres_runtime_password.txt` sem substituir os
segredos anteriores. A senha antiga da aplicação passa a ser exclusiva de migração.
Ordem: banco saudável → migrate (`pulse`) → db-permissions → API/worker
(`pulse_runtime`) → gateway. Nenhum volume é recriado.

`db-permissions` usa o administrador somente em job operacional, configura a senha
runtime a partir do arquivo protegido e aplica grants no banco configurado. Não
montar a senha administrativa ou de migração em API/worker. Não executar
`manage.py migrate` no container API; para migrações, usar o serviço `migrate`.
`migrate --check` e `makemigrations --check --dry-run` são consultas e continuam
disponíveis na API. Ao alterar migrações, executar novamente o fluxo completo.

Rotação da senha runtime exige atualizar o arquivo protegido, executar o job de
permissões e recriar consumidores em uma janela coordenada. Senhas administrativas
e da role `pulse` continuam exigindo rotação explícita no PostgreSQL. Não apagar
volumes nem substituir arquivos aleatórios para tentar recuperar uma senha.

## Configuração inicial

Usar administrador com e-mail confirmado/MFA. Nenhum dado corporativo foi criado
por esta entrega. Os passos são realizados pela API, preservando sessão e CSRF
conforme `IDENTIDADE.md`:

1. Criar áreas e grupos; atribuir área aos colaboradores, confirmar suas contas e
   promover os técnicos/gestores necessários.
2. Criar memberships em `/api/v1/memberships/`, com `user`, `group` e permissões
   explícitas `can_view_restricted`, `can_transfer`, `can_cancel` (padrão false).
   Só gestores podem receber `can_cancel`. Para alterar uma concessão, remover
   e cadastrar novamente; ambas as ações são auditadas.
3. Criar categorias em `/api/v1/categories/`: `name`, `group`, `restricted`,
   `is_active`. Categoria roteia a abertura ao grupo. Mudanças não reclassificam
   tickets existentes.
4. Quando a empresa definir uma janela, POST `/api/v1/settings/reopen-policies/`
   com `hours` (0–8760) e `reason`. A versão mais recente aplica-se a novas
   aberturas; zero ou ausência de política desabilita reabertura de Fechado.

## Leituras

Prefixo `/api/v1`. `{id}` é o UUID retornado em `ticket_id`, não o número público.

Número público: `AAAAMM` + sequência mensal de 6 dígitos (ex.: `202611000001`),
gerado sob lock consultivo por mês. Chamados anteriores ao ajuste mantêm o número antigo.

| Endpoint | Conteúdo |
|---|---|
| GET `/tickets/` | Chamados próprios; técnicos veem a fila de chamados não restritos de grupos ativos; gestores, os dos seus grupos; restritos só com `can_view_restricted` no grupo; administrador vê todos |
| GET `/tickets/{id}/` | Detalhe autorizado, prioridade, área histórica e versão |
| GET `/tickets/{id}/comments/` | Comentários visíveis, incluindo correções por acréscimo |
| GET `/tickets/{id}/events/` | Timeline visível, ator, instante, transição e correlação |
| GET `/categories/` | Categorias ativas para abertura; admin também vê inativas |
| GET/PATCH `/notifications/`, POST `/notifications/clear/`, POST `/notifications/{id}/read/` | Sino do portal: até 20 eventos de outras pessoas em chamados que o usuário abriu, assumiu ou participa (técnicos, gestores e administradores também recebem chamados novos), respeitando notas internas; `muted` deixa o contador cinza; limpar descarta os eventos até agora; clicar num item marca só ele como lido para o próprio usuário (tabela `NotificationRead`, apagada junto com o chamado pela retenção) |

Listas paginadas em 25 itens. Filtros da fila: `state`, `priority`, `department`,
`group`, `assignee`, `number`, `search`; `ordering` aceita `created_at`,
`-created_at`, `priority`, `-priority`. Número desempata a ordenação. Campos e
valores não permitidos retornam 400. Pesquisa considera somente assunto/descrição
dos tickets autorizados; não pesquisa textos de notas. Área não concede acesso
a chamados de colegas. Objeto fora do escopo retorna 404.

## Escritas e retries

Enviar cookie de sessão, `X-CSRFToken`, JSON e `Idempotency-Key` com UUID novo
por intenção. Em timeout, repetir a mesma chave e o mesmo corpo. Não trocar a
chave automaticamente para contornar 409. `Idempotent-Replayed: true` identifica
recibo reutilizado; a autorização é conferida novamente antes de devolvê-lo.

Todas as mutações de ticket existente exigem `expected_version` igual à versão
obtida no último detalhe. O recibo retorna `ticket_id`, `number`, `event_id`,
`version`, `state`, `correlation_id`. Buscar o detalhe para atualizar a tela.

| Ação | Endpoint POST | Campos além de expected_version |
|---|---|---|
| Abrir para si | `/tickets/` | `category`, `subject`, `description`; `priority` (1–4) e `related_ticket` opcionais; sem `priority`, vale a da categoria; sem expected_version |
| Assumir | `/tickets/{id}/claim/` | Nenhum; exige Novo e técnico autorizado |
| Participar | `/tickets/{id}/join/` | Nenhum; técnico entra como participante em Em atendimento/Aguardando |
| Comentar | `/tickets/{id}/comments/` | `body`, `visibility` (`public`/`internal`), `corrects` opcional |
| Transição | `/tickets/{id}/transitions/` | `action`, `message` quando exigida, campos específicos abaixo |
| Transferir | `/tickets/{id}/transfer/` | `group`, `assignee`, `message` público obrigatório |

Transições:

- Participantes agem como o técnico atribuído nas transições abaixo; transferir e
  cancelar continuam exigindo vínculo ao grupo com `can_transfer`/`can_cancel`.
  Devolver à fila remove os participantes.
- `request_information` / `request_test`: técnico atribuído, Em atendimento,
  `message` público com pergunta/instruções.
- Resposta pública do solicitante pelo endpoint comments retoma Em atendimento
  quando aguardava informação/teste, mantendo o técnico. Correção de mensagem
  anterior não retoma o atendimento.
- `resolve`: técnico, gestor ou administrador com acesso ao chamado, Em atendimento, `message` público com a solução
  obrigatório (`resolution_class` passou a ser opcional e não aparece no portal).
- `confirm`: solicitante, Resolvido → Fechado, com `rating` obrigatório de 1 a 5 estrelas
  (1 = ruim, 5 = ótima). A nota aparece no detalhe do chamado e na coluna `avaliacao` do CSV.
- `close`: solicitante encerra a qualquer momento após o atendimento começar
  (Em atendimento ou Aguardando) → Fechado; `message` obrigatório.
  Em Novo, o solicitante usa `cancel`; em Resolvido, `confirm`. Técnico, gestor e
  administrador com acesso ao chamado também encerram, inclusive em Resolvido.
- `reopen`: motivo em `message`; solicitante, técnico, gestor ou administrador com
  acesso ao chamado, em Resolvido ou em Fechado dentro da janela congelada.
  Gestor e administrador podem informar `assignee` válido ao regularizar a
  atribuição.
- `cancel`: solicitante apenas em Novo; gestor com `can_cancel` nos estados não
  terminais. `message` obrigatório.
- `return_queue`: técnico/gestor com `can_transfer`, estado não terminal diferente
  de Novo, `message` obrigatório. Retorna a Novo sem técnico.

Para registrar informação privada, usar nota interna; motivos de transição e
transferência são públicos. Correções exigem mesmo autor e visibilidade e não
apagam o original. Não existem PATCH/DELETE genéricos de ticket/comentário.
Não enviar senhas, tokens ou dados sensíveis desnecessários no conteúdo.

## IP e sistema operacional (opcional)

Ao abrir o chamado, o solicitante pode marcar a autorização para registrar o IP
público e o sistema operacional. `share_device_info=true` faz o servidor gravar o
IP (calculado no servidor, nunca enviado pelo cliente) e o `client_os` informado
pelo navegador. Sem autorização, ambos ficam vazios e o `client_os` enviado é
descartado. O evento `created` registra apenas `device_info_shared`. Os campos
seguem a retenção do chamado. IP local (WebRTC) não é coletado.

## Validação e pendências

`python tests/run_identity.py` agora executa identidade e tickets no cluster
descartável, migra como proprietário, configura grants e exercita tickets sob
`pulse_runtime`. Um teste autentica uma conexão separada como runtime para provar
que ela não consegue assumir a role proprietária nem alterar o schema.

A outbox persiste intenções, sem enviar notificações de tickets. Telas/anexos
pertencem à etapa 4; SMTP/Chat, retries e painel operacional à etapa 5; SLA à
etapa 6. Políticas de retenção/eliminação e suas roles privilegiadas serão definidas
na etapa 7. A proteção append-only não impede alterações por administradores do
banco e não substitui backup/arquivo protegido de auditoria.

## SLA e relatórios

| Operação | Rota | Quem |
|---|---|---|
| Listar/criar versão de política de SLA | GET/POST `/settings/sla-policies/` | Administrador; versões são imutáveis |
| Resumo do período | GET `/reports/summary/?start=AAAA-MM-DD&end=AAAA-MM-DD` | Gestor: chamados dos seus grupos, com restritos apenas onde pode vê-los; administrador: todos |
| Gerar CSV | POST `/reports/exports/` com `start` e `end` | Mesmos perfis; auditado |
| Baixar CSV | GET `/reports/exports/<id>/` | Só o autor, por 15 minutos |

Cada chamado congela a política vigente na abertura. As definições de primeira
resposta, pausas, reabertura, coorte do período e denominadores estão em
`docs/validacoes/etapa-06.md`. A quebra por técnico aparece para gestores e administradores.
