# Backup cifrado via FTP

Serviço opt-in (`compose.backup.yaml`, código em `infra/backup/`). Cada backup é um
conjunto em `FTP_DIR/pulse-AAAAMMDDTHHMMSSZ/` com:

| Arquivo | Conteúdo |
| --- | --- |
| `db.dump.gpg` | `pg_dump` (formato custom) do banco |
| `attachments.tar.gpg` | volume `attachments` (anexos de chamados e arquivos da wiki, inclusive logo/avatares) |
| `config.tar.gpg` | `secrets/` (inclui `identity_key`, sem os segredos de backup) e `.env` |
| `backup.info`, `SHA256SUMS` | metadados e hashes. `SHA256SUMS` é enviado por último: só então o conjunto vale como completo |

**Sem a `identity_key` o SMTP e o webhook cifrados no banco não são recuperáveis;** por isso
`secrets/` entra no backup. Todos os artefatos passam por `gpg --symmetric` (AES-256, S2K
SHA-512, integridade MDC) em fluxo contínuo: nenhum dado em texto claro é gravado no volume
de trabalho. O FTP só recebe dados cifrados; use FTPS (padrão) para proteger também as credenciais.

## Configuração

1. Gerar os segredos (não são versionados):
   ```bash
   openssl rand -base64 48 > secrets/backup_passphrase.txt
   printf '%s' 'SENHA_DO_FTP' > secrets/backup_ftp_password.txt
   chmod 0444 secrets/backup_*.txt
   ```
   **Guarde `backup_passphrase.txt` fora do servidor** (cofre/offline). Sem ela os backups
   são irrecuperáveis, e ela não é incluída no próprio backup.
2. No `.env`: `BACKUP_FTP_HOST`, `BACKUP_FTP_USER` e, se quiser, `BACKUP_FTP_PORT` (21),
   `BACKUP_FTP_DIR` (`/pulse-backups`), `BACKUP_FTP_TLS` (`true`, FTPS explícito),
   `BACKUP_FTP_VERIFY_CERT` (`true`; use `false` só com certificado autoassinado, ciente do risco),
   `BACKUP_KEEP` (14 conjuntos), `BACKUP_AT` (`03:00`, UTC).
3. Subir (mesmos `-f` do deploy):
   ```bash
   docker compose -f compose.yaml -f compose.production.yaml -f compose.backup.yaml up -d --build backup
   docker compose -f compose.yaml -f compose.production.yaml -f compose.backup.yaml logs backup
   ```
   O serviço faz um backup por dia e remove os mais antigos além de `BACKUP_KEEP`.
   O servidor FTP precisa de modo passivo liberado para o IP do servidor do Pulse.

## Operação

Com o `make`: `make backup` (backup agora), `make backup-list` e `make backup-verify`. Sem ele:

```bash
C="docker compose -f compose.yaml -f compose.production.yaml -f compose.backup.yaml"
$C run --rm backup-tools run            # backup agora
$C run --rm backup-tools list           # conjuntos completos no FTP
$C run --rm backup-tools verify         # baixa o último, confere SHA-256 e decifra (não altera nada)
$C run --rm backup-tools verify pulse-20261119T030000Z
```

Rode `verify` periodicamente e após mudar a frase secreta; um backup nunca testado não é backup.

## Restauração

1. Em servidor novo: clonar o repositório, criar `secrets/backup_passphrase.txt` (do cofre) e
   `backup_ftp_password.txt`, e preencher o `.env` com os dados do FTP e `POSTGRES_DB`.
   `python infra/bootstrap.py` cria segredos novos: **não** o use se for reaproveitar os do backup.
2. Parar a aplicação e subir só o banco: `$C stop api worker retention gateway; $C up -d db`
   (em servidor novo, os segredos de banco precisam existir; o init do volume vazio cria as roles).
3. Restaurar (destrutivo, exige confirmação):
   ```bash
   mkdir -p work/restore
   CONFIRM_RESTORE=yes $C run --rm backup-tools restore            # último
   CONFIRM_RESTORE=yes $C run --rm backup-tools restore pulse-20261119T030000Z
   ```
   Substitui as tabelas do dump, esvazia e repõe o volume de anexos e extrai `secrets/` e `.env`
   do backup em `work/restore/` (sem sobrescrever os arquivos em uso). Objetos que não existem no
   dump (ex.: tabelas criadas depois) não são removidos: restaure sobre banco vazio ou recém-migrado.
4. Instalar os segredos: copie `work/restore/secrets/*` para `secrets/` (modo 0444, diretório 0700)
   e revise `work/restore/.env`. A `identity_key` restaurada **deve** ser a mesma do backup.
5. Subir tudo: `$C up -d --build`. O `migrate` aplica migrações pendentes e o `db-permissions`
   reaplica os grants (o dump é feito sem donos e privilégios). Validar login, um anexo e a wiki.

## Limites

- Backup lógico diário: o RPO é de até 24 h; use `run` antes de mudanças arriscadas.
- Backups em FTP não têm imutabilidade: um acesso indevido ao FTP pode apagá-los. Mantenha uma
  cópia fora dele se o risco for relevante.
- A chave do `.env` de produção é copiada para o backup cifrado; proteja a frase secreta como tal.
- Direito ao esquecimento (LGPD): dados eliminados permanecem nos backups até a rotação (`BACKUP_KEEP`).
