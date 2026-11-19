#!/bin/bash
# Backup cifrado do Pulse Services para FTP/FTPS.
#   daemon            agenda um backup diário (BACKUP_AT, UTC)
#   run               faz um backup agora
#   list              lista os conjuntos completos no servidor FTP
#   verify [nome]     baixa, confere SHA-256 e decifra (sem restaurar nada)
#   restore [nome]    restaura banco + anexos e extrai segredos (exige CONFIRM_RESTORE=yes)
# Segredos nunca são impressos. Nada em texto claro é gravado em disco: cada
# artefato passa por gpg (AES-256, integridade MDC) antes de tocar o volume.
set -Eeuo pipefail
umask 077

SRC=${BACKUP_SRC:-/backup-src}
WORK=${BACKUP_WORK:-/work}
ATTACH=${ATTACHMENT_DIR:-/data/attachments}
OUT=${RESTORE_OUT:-/restore-out}
PASS_FILE=${BACKUP_PASSPHRASE_FILE:-/run/secrets/backup_passphrase}
FTP_PASS_FILE=${BACKUP_FTP_PASSWORD_FILE:-/run/secrets/backup_ftp_password}
DB_PASS_FILE=${POSTGRES_PASSWORD_FILE:-/run/secrets/postgres_password}
FTP_DIR=${BACKUP_FTP_DIR:-/pulse-backups}
KEEP=${BACKUP_KEEP:-14}
export GNUPGHOME=/tmp/gnupg
mkdir -p "$GNUPGHOME" "$WORK"
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "ERRO: $*"; exit 1; }

[ -s "$PASS_FILE" ] || die "frase secreta de backup ausente"
[ "$(wc -c <"$PASS_FILE")" -ge 20 ] || die "frase secreta de backup curta demais (mínimo 20 caracteres)"
[[ "$KEEP" =~ ^[0-9]+$ ]] && [ "$KEEP" -ge 1 ] || die "BACKUP_KEEP inválido"

db_env() {
  export PGHOST=${POSTGRES_HOST:-db} PGUSER=${POSTGRES_USER:-pulse} PGDATABASE=${POSTGRES_DB:-pulse}
  PGPASSWORD=$(cat "$DB_PASS_FILE"); export PGPASSWORD
}
encrypt() {
  gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$PASS_FILE" \
    --symmetric --cipher-algo AES256 --s2k-mode 3 --s2k-digest-algo SHA512 \
    --s2k-count 65011712 --compress-algo none --no-symkey-cache -o "$1"
}
decrypt() {
  gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$PASS_FILE" \
    --no-symkey-cache --decrypt "$1"
}
lftp_rc() { # grava o rc com as credenciais em tmpfs (0600), nunca na linha de comando
  local rc=/tmp/lftp.rc user pass
  [ -n "${BACKUP_FTP_HOST:-}" ] && [ -n "${BACKUP_FTP_USER:-}" ] || die "BACKUP_FTP_HOST/BACKUP_FTP_USER ausentes"
  user=${BACKUP_FTP_USER//\\/\\\\}; user=${user//\"/\\\"}
  pass=$(cat "$FTP_PASS_FILE"); pass=${pass//\\/\\\\}; pass=${pass//\"/\\\"}
  {
    echo "set net:max-retries 3; set net:reconnect-interval-base 5; set net:timeout 30"
    echo "set ftp:passive-mode on; set cmd:fail-exit yes"
    if [ "${BACKUP_FTP_TLS:-true}" = true ]; then
      echo "set ftp:ssl-force true; set ftp:ssl-protect-data true; set ftp:ssl-allow true"
      echo "set ssl:verify-certificate ${BACKUP_FTP_VERIFY_CERT:-true}"
    else
      echo "set ftp:ssl-allow false"
    fi
    echo "open -p ${BACKUP_FTP_PORT:-21} ${BACKUP_FTP_HOST}"
    echo "user \"$user\" \"$pass\""
  } >"$rc"
  echo "$rc"
}
ftp() { # ftp 'comandos lftp'
  local rc; rc=$(lftp_rc)
  { cat "$rc"; printf '%s\n' "$1"; } | lftp
  rm -f "$rc"
}
remote_sets() { # conjuntos completos (têm SHA256SUMS), mais antigos primeiro
  local rc name; rc=$(lftp_rc)
  { cat "$rc"; echo "mkdir -p -f \"$FTP_DIR\"; cls -1 \"$FTP_DIR\""; } | lftp \
    | sed 's#/$##; s#.*/##' | grep -E '^pulse-[0-9]{8}T[0-9]{6}Z$' | sort | while read -r name; do
      { cat "$rc"; echo "cls -1 \"$FTP_DIR/$name/SHA256SUMS\""; } | lftp >/dev/null 2>&1 && echo "$name"
    done
  rm -f "$rc"
}

remote_size() { # tamanho via comando SIZE do FTP; cai para a listagem; vazio se o servidor não informar
  local name=$1 f=$2 size
  size=$(ftp "cd \"$FTP_DIR/$name\"; quote SIZE $f" 2>/dev/null | tr -d '\r' | awk '$1 == 213 {print $2; exit}') || true
  if [ -z "$size" ]; then
    size=$(ftp "cd \"$FTP_DIR/$name\"; ls" 2>/dev/null | tr -d '\r' \
      | awk -v f="$f" '$NF == f { print $(NF-4) }' | grep -E '^[0-9]+$' | head -n1) || true
  fi
  echo "$size"
}

do_backup() {
  local ts name dir
  ts=$(date -u +%Y%m%dT%H%M%SZ); name=pulse-$ts; dir=$WORK/$name
  rm -rf "${WORK:?}"/pulse-*; mkdir -p "$dir"
  trap 'rm -rf "'"$dir"'"' RETURN
  db_env
  log "dump do banco $PGDATABASE"
  pg_dump --format=custom --no-owner --no-privileges | encrypt "$dir/db.dump.gpg"
  log "anexos"
  tar -C "$ATTACH" --numeric-owner -cf - . | encrypt "$dir/attachments.tar.gpg"
  log "segredos e configuração"
  local excl=(--exclude='./secrets/backup_*')
  tar -C "$SRC" --numeric-owner "${excl[@]}" -cf - . | encrypt "$dir/config.tar.gpg"
  {
    echo "created_utc=$ts"
    echo "database=$PGDATABASE"
    echo "postgres=$(pg_dump --version)"
    echo "format=1"
  } >"$dir/backup.info"
  (cd "$dir" && sha256sum backup.info db.dump.gpg attachments.tar.gpg config.tar.gpg >SHA256SUMS)
  log "enviando para ftp://$BACKUP_FTP_HOST$FTP_DIR/$name"
  # SHA256SUMS por último: só então o conjunto é considerado completo.
  ftp "mkdir -p -f \"$FTP_DIR/$name\"; cd \"$FTP_DIR/$name\"; lcd \"$dir\"; \
put db.dump.gpg attachments.tar.gpg config.tar.gpg backup.info; put SHA256SUMS"
  log "conferindo tamanhos no servidor"
  local f want got
  for f in db.dump.gpg attachments.tar.gpg config.tar.gpg SHA256SUMS; do
    want=$(stat -c %s "$dir/$f")
    got=$(remote_size "$name" "$f")
    if [ -z "$got" ]; then
      log "AVISO: o servidor FTP não informou o tamanho de $f; rode 'verify' para conferir a integridade"
    elif [ "$got" != "$want" ]; then
      die "tamanho remoto de $f não confere (local $want, remoto $got bytes)"
    fi
  done
  log "backup $name concluído"
  date -u +%s >"$WORK/last_success"
  prune
}
prune() {
  local sets total old
  mapfile -t sets < <(remote_sets)
  total=${#sets[@]}
  [ "$total" -gt "$KEEP" ] || return 0
  for old in "${sets[@]:0:$((total - KEEP))}"; do
    log "removendo conjunto antigo $old"
    ftp "rm -r -f \"$FTP_DIR/$old\""
  done
}
fetch() { # fetch [nome] -> baixa e confere; imprime o diretório local
  local name=${1:-} dir
  if [ -z "$name" ]; then name=$(remote_sets | tail -n1); fi
  [ -n "$name" ] || die "nenhum backup completo no servidor"
  [[ "$name" =~ ^pulse-[0-9]{8}T[0-9]{6}Z$ ]] || die "nome de backup inválido"
  dir=$WORK/restore-$name; rm -rf "$dir"; mkdir -p "$dir"
  log "baixando $name" >&2
  ftp "cd \"$FTP_DIR/$name\"; lcd \"$dir\"; mget SHA256SUMS backup.info db.dump.gpg attachments.tar.gpg config.tar.gpg" >&2
  (cd "$dir" && sha256sum --check --strict SHA256SUMS >&2) || die "SHA-256 não confere: backup corrompido"
  echo "$dir"
}
do_verify() {
  local dir; dir=$(fetch "${1:-}")
  trap 'rm -rf "'"$dir"'"' RETURN
  log "testando a decifragem (frase secreta e integridade)"
  decrypt "$dir/db.dump.gpg" | pg_restore --list >/dev/null || die "dump do banco ilegível"
  decrypt "$dir/attachments.tar.gpg" | tar -tf - >/dev/null || die "anexos ilegíveis"
  decrypt "$dir/config.tar.gpg" | tar -tf - >/dev/null || die "configuração ilegível"
  log "verificação OK: $(grep created_utc "$dir/backup.info")"
}
do_restore() {
  [ "${CONFIRM_RESTORE:-}" = yes ] || die "restauração sobrescreve banco e anexos; defina CONFIRM_RESTORE=yes"
  local dir; dir=$(fetch "${1:-}")
  trap 'rm -rf "'"$dir"'"' RETURN
  db_env
  log "restaurando banco (objetos existentes são substituídos)"
  decrypt "$dir/db.dump.gpg" | pg_restore --clean --if-exists --no-owner --no-privileges \
    --exit-on-error --dbname="$PGDATABASE"
  log "restaurando anexos"
  find "$ATTACH" -mindepth 1 -delete
  decrypt "$dir/attachments.tar.gpg" | tar -C "$ATTACH" --numeric-owner -xf -
  log "extraindo segredos e .env em $OUT (não sobrescreve o ambiente em uso)"
  mkdir -p "$OUT"
  decrypt "$dir/config.tar.gpg" | tar -C "$OUT" --numeric-owner -xf -
  log "restauração concluída. Revise $OUT, instale os segredos e suba os serviços (migrate reaplica as permissões)."
}
secs_until() { # HH:MM UTC
  local now target; now=$(date -u +%s); target=$(date -u -d "today $1" +%s)
  [ "$target" -gt "$now" ] || target=$(date -u -d "tomorrow $1" +%s)
  echo $((target - now))
}
daemon() {
  local at=${BACKUP_AT:-03:00}
  [[ "$at" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || die "BACKUP_AT inválido (HH:MM UTC)"
  while true; do
    log "próximo backup às $at UTC"
    sleep "$(secs_until "$at")"
    ( do_backup ) || { log "backup falhou; nova tentativa em 1 hora"; sleep 3600; ( do_backup ) || log "ERRO: segunda tentativa falhou"; }
  done
}
case "${1:-daemon}" in
  daemon) daemon ;;
  run) do_backup ;;
  list) remote_sets ;;
  verify) do_verify "${2:-}" ;;
  restore) do_restore "${2:-}" ;;
  *) die "uso: daemon|run|list|verify [nome]|restore [nome]" ;;
esac
