# ADR 0008 — verificação em duas etapas opcional

Data: 05/11/2026. Prevalece sobre as ADRs 0002 e 0005 e sobre o plano onde houver
conflito. Decisão do responsável pelo sistema.

O MFA deixa de ser obrigatório para técnico, gestor e administrador. Qualquer
conta o ativa e desativa em Perfil, e o login só pede código em contas que o têm
ativo. Contas que já usam MFA continuam usando.

## Como funciona

- Ativar exige a senha e o código do novo autenticador, e gera oito códigos de
  recuperação. O login não oferece mais o cadastro do autenticador.
- Desativar em Perfil exige senha e código TOTP ou de recuperação, para que uma
  sessão aberta roubada não retire a proteção.
- O administrador desativa o MFA de qualquer outra conta, uma por vez, com
  justificativa. Ele não usa essa rota na própria conta, o que contornaria a
  exigência de senha e código. Não existe desativação em massa.
- Desativar apaga segredo e códigos, remove dispositivos lembrados, encerra as
  sessões da conta e registra quem fez no log.

## Consequências

- Uma conta privilegiada sem MFA fica protegida só pela senha. Isso inclui
  administradores, que têm acesso a todos os chamados, às credenciais do SMTP e do
  Chat e à política de remoção definitiva. Administradores novos começam sem MFA.
- Uma sessão de administrador roubada pode desativar o MFA dos outros, mas não
  entra nessas contas sem a senha delas. O registro fica no log.
- A pessoa afetada não recebe aviso quando um administrador desativa o seu MFA.
- A exigência "MFA privilegiado" da matriz de segurança do plano não vale mais. Se
  uma política ou auditoria a exigir, será preciso voltar à obrigatoriedade.
