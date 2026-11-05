# ADR 0004 — prioridade definida pela categoria

Data: 04/11/2026. Substitui a matriz de impacto/urgência da ADR 0003.

Cada categoria tem uma prioridade de P1 a P4, escolhida pelo administrador e
auditada. Na abertura, ela vem selecionada e o solicitante pode trocá-la. Sem
`priority` na requisição, vale a da categoria.

Impacto e urgência saíram do formulário e da API de abertura. As colunas ficam
nulas nos novos tickets e preservam o histórico dos anteriores. Categorias
existentes recebem P3 na migração.

Consequência: a prioridade passa a ser informada pelo solicitante, que pode
escolher P1 e acionar o SLA mais curto. A escolha fica registrada no evento
`created`; não há aprovação nem restrição por perfil.
