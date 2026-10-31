# ADR 0003 — tickets, concorrência e auditoria

Data: 30/10/2026. Escopo: etapa 3, após revisão técnica da etapa 2.

## Modelo e autorização

O módulo Django `tickets` separa o domínio de chamados da identidade. O ticket
possui UUID único para a API e número sequencial público para comunicação. A
sequência pode ter lacunas após rollback; nenhum identificador autoriza acesso.

Categorias determinam grupo e classificação de acesso na abertura. Somente
administradores configuram categorias; usuários abrem para si. Solicitante,
área/nomes históricos, prioridade, datas, estado e versão são definidos no servidor.
Impacto/urgência usam escala 1–3; soma 6 → P1, 5 → P2, 4 → P3, 2–3 → P4.
Essa matriz inicial é técnica e deve ser revisada com a empresa antes de produção.

Solicitantes veem apenas seus chamados. Técnicos/gestores veem os grupos em que
têm membership ativo; chamados restritos exigem `can_view_restricted`. Área
organizacional nunca concede acesso. Administradores/privacidade precisam de
`ReadGrant` explícito por grupo; acesso a notas internas e chamados restritos são
concessões adicionais. Esses grants permitem leitura, não atuação técnica.

Um técnico solicitando ajuda atua como solicitante no próprio ticket: não assume
seu atendimento nem vê notas internas sobre ele. Não há bypass por staff/superuser.
Todos os caminhos de detalhe, lista, pesquisa, comentários e eventos reutilizam
o escopo de autorização. Outbox é interna, sem endpoint público; sua projeção por
destinatário reavalia conta e escopo antes de retornar metadados.

## Transições e histórico

Só o técnico atribuído solicita informação/teste ou resolve. Gestores não ganham
permissão automática para resolver chamados de outros técnicos. Transferência
exige `can_transfer` na origem e acesso ao destino; atribuir apenas a técnico ou
gestor ativo, confirmado e autorizado ao grupo/classificação. Devolução à fila
muda explicitamente para Novo e remove a atribuição. Cancelamento de gestão exige
papel de gestor e `can_cancel` no grupo.

Reabertura de Resolvido é do solicitante. Reabertura de Fechado também pode ser
feita pelo gestor, dentro da janela congelada na abertura. `ReopenPolicy` é
versionada por inserção; nenhuma janela corporativa é inventada: sem política,
ou com zero horas, a reabertura de Fechado fica desabilitada. Fora do prazo,
criar outro ticket vinculado, do mesmo solicitante. Conteúdo restrito não pode ser
vinculado a nova categoria pública. Não existe fechamento automático.

Se o responsável perdeu acesso ou foi desativado, resposta/reabertura não coloca
o ticket em atendimento com atribuição inválida. A TI deve regularizar o destino;
gestor pode escolher outro técnico ao reabrir um Fechado dentro do prazo. Desativar
um grupo suspende a atuação técnica; administrador pode reativá-lo para regularização.

Texto de transição/transferência é público, incluindo motivos e solução. Informação
privada deve usar nota interna. Comentários não têm PATCH/DELETE: correções acrescentam
um comentário referenciando o anterior, do mesmo autor e visibilidade, com novo evento.
Correção não equivale à resposta solicitada e não altera automaticamente o estado.
Timeline é paginada e esconde eventos internos de leitores sem autorização.

Versão/updated_at mudam em toda mutação, inclusive nota interna, para evitar perda
de atualização; isso pode indicar atividade, mas não expõe o conteúdo interno.
Datas de solução/fechamento representam as ocorrências mais recentes, preservadas
na reabertura; ocorrências anteriores permanecem nos eventos. Métricas serão
formalizadas na etapa 6.

## Transações e concorrência

Cada mutação grava ticket, comentário quando houver, evento, auditoria, outbox e
recibo de idempotência na mesma transação. Falha em qualquer inserção reverte tudo.
Auditoria contém IDs, estados e alterações relevantes, sem copiar os textos dos
comentários. Correlação UUID, ator e UTC são gerados no servidor.

`Idempotency-Key` UUID é obrigatório em abertura, claim, comentário, transição e
transferência. A chave é escopada por usuário/operação/ticket; reuso com payload
diferente retorna 409. Replay retorna o recibo original e revalida autorização,
mesmo que a versão atual tenha mudado. O recibo não contém descrição ou notas.

Escritas usam lock compartilhado de identidade para impedir revogação de permissão
durante a mutação; mudanças administrativas usam o lock exclusivo existente.
Um advisory lock por chave serializa retries. Ticket usa lock de linha e versão
otimista obrigatória, retornando 409 ao perdedor. A conta do ator usa
`FOR NO KEY UPDATE`: impede alteração concorrente sem bloquear referências de
chave estrangeira em transferências recíprocas. Tickets independentes podem avançar
em paralelo. Testes concorrentes exercitam conexões PostgreSQL independentes.

## Separação das contas PostgreSQL

- `pulse`: proprietária do schema e das tabelas, utilizada pelo job `migrate`.
- `pulse_runtime`: API/worker, senha própria, sem superuser/createdb/createrole,
  sem propriedade do schema, sem acesso à senha de migração/administração.
- `db-permissions`: job operacional após migrações, com segredo administrativo;
  cria/configura runtime e aplica grants antes de liberar API/worker.

Runtime pode inserir/ler auditoria, eventos e comentários; não pode atualizá-los,
apagá-los ou truncá-los. Políticas de reabertura e recibos também são append-only.
Não pode criar/alterar tabelas, mudar para a role proprietária ou escrever em
django_migrations. `pulse` pode assumir runtime para verificações; o inverso é negado.
Tabelas futuras só recebem grants quando o job é executado, após as migrações.

Isso protege contra alteração pela conta da aplicação. O proprietário/superuser
ainda pode alterar dados: não há alegação de inviolabilidade. Role separada de
retenção e exportação protegida de auditoria permanecem nas etapas 7/8.

## Outbox e limites desta etapa

Uma intenção por evento, garantida por unicidade no banco; só IDs e visibilidade
no payload. Nota interna destina-se apenas ao atendimento autorizado. Não há
envio de notificações de tickets: canais, destinatários, leasing, tentativas e
diagnóstico completos pertencem à etapa 5. A API não depende de SMTP/Chat para
gravar um chamado. Não há garantia de entrega externa exactly-once.

## Referências oficiais consultadas

- [Django: select_for_update e no_key](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update)
- [PostgreSQL 17: GRANT](https://www.postgresql.org/docs/17/sql-grant.html)
- [PostgreSQL 17: propriedade e privilégios](https://www.postgresql.org/docs/17/ddl-priv.html)
