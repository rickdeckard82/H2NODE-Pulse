# Chamados

Regras de acesso, ciclo de vida e API dos chamados, para quem integra ou desenvolve. Para
configurar pelo portal, veja o [Guia do administrador](CONFIGURACOES.md). Contrato completo
em [openapi.yaml](openapi.yaml); motivos das escolhas em
[decisoes/0003-tickets.md](decisoes/0003-tickets.md). Contas do banco e migrações estão em
[OPERACAO.md](OPERACAO.md#senhas-do-banco).

## Configuração inicial

Feita por um administrador, pelo menu **Administração** ou pela API (com sessão e CSRF,
conforme [IDENTIDADE.md](IDENTIDADE.md)). Nenhum dado de empresa vem pré-cadastrado.

1. Criar áreas e grupos; atribuir área aos colaboradores, confirmar suas contas e
   promover os técnicos/gestores necessários.
2. Criar memberships em `/api/v1/memberships/`, com `user`, `group` e permissões
   explícitas `can_view_restricted`, `can_transfer`, `can_cancel` (padrão false).
   Só gestores podem receber `can_cancel`. Para alterar uma concessão, remover
   e cadastrar novamente; ambas as ações são auditadas.
3. Criar categorias em `/api/v1/categories/`: `name`, `group`, `restricted`,
   `is_active`. Categoria roteia a abertura ao grupo. Mudanças não reclassificam
   tickets existentes.
4. Para permitir reabrir chamados fechados, POST `/api/v1/settings/reopen-policies/`
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
- Um técnico (perfil Técnico) só responde, escreve nota, pausa, retoma, resolve,
  encerra, reabre, transfere ou devolve à fila se for o responsável ou participante
  do chamado (assumir/participar primeiro); sem isso a API responde 403. Gestores
  e administradores não têm essa restrição. A tela esconde essas ações.
- `request_information` / `request_test`: técnico atribuído, Em atendimento,
  `message` público com pergunta/instruções.
- Resposta pública do solicitante pelo endpoint comments retoma Em atendimento
  quando aguardava informação/teste, mantendo o técnico. Correção de mensagem
  anterior não retoma o atendimento.
- `resolve`: técnico, gestor ou administrador com acesso ao chamado, Em atendimento, `message` público com a solução
  obrigatório (`resolution_class` passou a ser opcional e não aparece no portal).
- `pause`: técnico, gestor ou administrador com acesso ao chamado, Em atendimento → Pausado, com
  `message` público obrigatório (a justificativa fica no histórico). Pausado não conta tempo de
  SLA, como os estados de espera; resposta do solicitante não retoma.
- `resume`: equipe com acesso, Pausado → Em atendimento, sem mensagem obrigatória.
- `confirm`: solicitante, Resolvido → Fechado, com `rating` obrigatório de 1 a 5 estrelas
  (1 = ruim, 5 = ótima); grava `requester_solved = true`. O `close` feito pelo solicitante exige
  `rating` e `solved` (resolvido ou não resolvido, gravado em `requester_solved`); o feito pela
  equipe não aceita esses campos. Reabrir limpa os dois. CSV: colunas `avaliacao` e
  `resolvido_segundo_solicitante`. A nota aparece no detalhe do chamado e na coluna `avaliacao` do CSV.
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

## Testes

`python tests/run_identity.py` executa os testes de identidade e chamados em um PostgreSQL
descartável. Os chamados são testados com a conta restrita `pulse_runtime`, e um teste
confirma que ela não consegue alterar a estrutura do banco. A proteção do log de auditoria
contra alteração não vale para o dono do banco; ela não substitui o backup.

## SLA e relatórios

| Operação | Rota | Quem |
|---|---|---|
| Listar/criar versão de política de SLA | GET/POST `/settings/sla-policies/` | Administrador; versões são imutáveis |
| Resumo do período | GET `/reports/summary/?start=AAAA-MM-DD&end=AAAA-MM-DD` | Gestor: chamados dos seus grupos, com restritos apenas onde pode vê-los; administrador: todos |
| Gerar CSV | POST `/reports/exports/` com `start` e `end` | Mesmos perfis; auditado |
| Baixar CSV | GET `/reports/exports/<id>/` | Só o autor, por 15 minutos |

Cada chamado congela a política vigente na abertura. A quebra por técnico aparece para gestores e administradores.

## Senhas ocultas

Texto no formato `senha: valor` (também `password`/`passwd`, com `:` ou `=`) em descrição,
respostas, notas internas e mensagens de transição é cifrado em `HiddenSecret` e
substituído por `[[oculta:<id>]]` antes de gravar. Histórico, busca, e-mails e exportações
só veem o marcador. `POST /tickets/{id}/secrets/{secret_id}/reveal/` devolve o valor apenas
a quem pode ler aquele texto (nota interna continua restrita à equipe) e informa a própria
senha de acesso; o limite é de 20 tentativas por 15 minutos e cada revelação é auditada
(`ticket.secret_revealed`, sem o valor). A tela esconde o valor de novo após 30 s.
Limitações: só o padrão `senha: valor` é reconhecido (valor de uma palavra, sem espaços);
textos anteriores a esta função não são alterados; anexos não são inspecionados; quem
já viu o valor pode copiá-lo.
