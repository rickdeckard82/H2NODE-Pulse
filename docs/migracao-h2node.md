# Migração: Pulse Services → H2NODE Pulse

O sistema passou a se chamar **H2NODE Pulse** na versão **0.2.0** do frontend. A troca é de
nome, logotipo e textos: banco, anexos, contas, sessões, MFA e chamados continuam os mesmos.

## Servidor

Na pasta do repositório (pode manter o nome antigo, ex.: `pulse-services`):

```sh
git pull
sh infra/migrar-h2node.sh      # mostra o plano e pede confirmação
```

O script:

- acrescenta `VOLUME_PREFIX=pulse-services` ao `.env` (os volumes passaram a ter nome fixo,
  `${VOLUME_PREFIX}_postgres_data`, `_attachments` e `_clamav_data`), mantendo o mesmo banco,
  os mesmos anexos e as definições do ClamAV já baixadas;
- copia o `.env` para `.env.antes-h2node.<data>`;
- derruba os containers do projeto compose antigo (`docker compose -p pulse-services down`,
  **sem** `-v`) e sobe o projeto `h2node-pulse` (com `compose.production.yaml` se você passar
  `--producao`).

O `docker compose` pode avisar que os volumes foram criados por outro projeto: é esperado.
O Proxy Host do NPM não muda (mesmo IP e porta do gateway).

## O que continua com o nome antigo (de propósito)

- Roles e banco PostgreSQL `pulse` / `pulse_runtime` (`POSTGRES_USER=pulse`, `POSTGRES_DB=pulse`):
  renomear exigiria recriar permissões e senhas.
- Cookie `pulse_trusted_device` (dispositivos confiáveis do MFA), chave `pulse-theme` do tema no
  navegador e eventos internos `pulse:*` do frontend: trocar faria todos perderem o dispositivo
  confiável e a preferência de tema.
- Caminho `/var/lib/pulse/attachments`, usuário `pulse` do container e arquivos de heartbeat.
- Contas já cadastradas no autenticador continuam aparecendo como "Pulse Services"; só os
  novos cadastros de MFA aparecem como "H2NODE Pulse". Os códigos funcionam igual.
- Registros antigos (`docs/decisoes/`, auditoria) ficam como foram escritos.
