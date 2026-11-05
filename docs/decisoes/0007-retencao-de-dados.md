# ADR 0007 — retenção e remoção definitiva de dados

Data: 05/11/2026. Antecipa parte da etapa 7.

O administrador define prazos para chamados encerrados, usuários, grupos,
categorias e áreas desativados, e logs. Depois do prazo, os dados são apagados
definitivamente, inclusive arquivos de anexos.

## Como funciona

- A conta `pulse_runtime` continua sem poder apagar auditoria, comentários e
  histórico. A remoção roda no serviço separado `retention`, sem saída para a
  internet, com a credencial que já era usada só nas migrações. Isso evita um
  segredo novo no deploy, mas dá a esse serviço mais poder que o necessário; um
  papel próprio de banco é a evolução natural.
- A data de desativação é mantida por gatilho no banco, derivada de `is_active`,
  para valer em qualquer caminho de código. Registros já inativos começam a contar
  na migração, pois a data real é desconhecida.
- A ordem é logs, chamados, usuários, categorias, grupos e áreas. O que ainda é
  referenciado aguarda: um usuário com chamados ou logs permanece até eles
  expirarem. Assim, o prazo efetivo de um usuário é o maior entre os relacionados.
- Contas de sistema (`system:`) nunca são removidas. Políticas de SLA e de
  reabertura guardam quem as criou, então esses administradores não são removidos.

## Travas

Desligado por padrão; zero desativa cada classe; mínimo de 30 dias; prévia de
quantidades; confirmação digitada; carência de 24 horas após qualquer alteração;
execução no máximo diária. Desligar a política funciona como suspensão geral.

## Consequências

- Backups não são alterados: dados removidos continuam neles até expirarem, e uma
  restauração os traz de volta. O prazo dos backups é responsabilidade da operação.
- Não existe legal hold por chamado, previsto no plano. Enquanto não existir, uma
  obrigação de preservar exige desligar a política inteira.
- Apagar logs reduz a capacidade de investigar incidentes. Prazos dependem de
  decisão jurídica; o sistema não os define nem garante conformidade.
- O registro da execução guarda apenas quantidades.
