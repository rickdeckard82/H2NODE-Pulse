# ADR 0009 — perfil "Usuário" (somente wiki)

Data: 12/11/2026. Decisão do responsável pelo sistema.

Novo papel `user` ("Usuário"), abaixo de Colaborador. Toda conta criada por
autoinscrição nasce com ele, e é também o padrão do modelo (menor privilégio).
Convites feitos pelo administrador continuam criando Colaborador.

## Escopo

O papel acessa a wiki (leitura), além de login, perfil, senha, MFA e a identificação
da empresa no cabeçalho. Não abre nem vê chamados, anexos, categorias,
notificações, relatórios nem listas administrativas. Não edita a wiki.

## Aplicação

- Servidor: `VerifiedSessionAuthentication` recusa com 403 qualquer rota fora de
  `/api/v1/auth/`, `/api/v1/wiki/` e `GET /api/v1/settings/company/` para esse papel,
  independentemente das permissões da view; rotas novas ficam fechadas por padrão.
- Interface: só o botão Wiki, sem notificações e com ajuda reduzida; a API continua
  sendo a barreira real.
- Promoção: o administrador altera o papel em Contas e perfis, com motivo; isso
  revoga as sessões. Contas que já eram Colaborador não foram alteradas.
- Promover um usuário sem e-mail confirmado só é permitido para Usuário ou
  Colaborador; privilégios de TI continuam exigindo e-mail confirmado.
