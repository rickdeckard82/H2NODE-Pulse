# ADR 0005 — papéis simplificados

Data: 04/11/2026. Prevalece sobre a ADR 0003 e sobre o plano onde houver conflito.

Restam quatro papéis: Colaborador, Técnico, Gestor e Administrador.

- **Colaborador:** abre, responde e encerra os próprios chamados.
- **Técnico:** vê a fila de chamados não restritos e atua neles, atribuídos a ele
  ou não, inclusive encerrando e reabrindo.
- **Gestor:** faz o mesmo apenas nos chamados dos seus grupos e vê os relatórios
  desses grupos.
- **Administrador:** acesso total, incluindo notas internas, chamados restritos,
  relatórios e ações de atendimento.

Mantido: chamados restritos continuam exigindo `can_view_restricted` para técnico
e gestor; `can_transfer` e `can_cancel` seguem valendo; quem abriu o chamado atua
nele como solicitante, sem assumi-lo nem ver notas internas, mesmo sendo
administrador; a janela de `ReopenPolicy` vale para todos; MFA segue obrigatório
para técnico, gestor e administrador.

"Responsável por privacidade" foi retirado. Contas com esse papel viram
Colaborador na migração, e suas sessões são encerradas.

As concessões de leitura deixam de ter uso e saem da API e da interface. A tabela
`tickets_readgrant` permanece, sem leitura, para não exigir migração destrutiva.

Consequências: a leitura de notas internas por administradores não depende mais de
concessão nem gera registro de acesso. O tratamento de direitos de titulares e de
retenção previsto na etapa 7 precisa de um responsável definido pela empresa, sem
papel próprio no sistema.
