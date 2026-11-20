#!/bin/sh
# Migra uma instalação "pulse-services" para o projeto compose "h2node-pulse"
# mantendo os mesmos volumes (banco, anexos, ClamAV). Não apaga nada.
# Uso: sh infra/migrar-h2node.sh [--producao]
set -eu
cd "$(dirname "$0")/.."
FILES="-f compose.yaml"
[ "${1:-}" = "--producao" ] && FILES="-f compose.yaml -f compose.production.yaml"
[ -f .env ] || { echo "sem .env nesta pasta" >&2; exit 1; }

echo "Plano:"
grep -q '^VOLUME_PREFIX=' .env && echo "  - .env já tem $(grep '^VOLUME_PREFIX=' .env)" \
  || echo "  - acrescentar VOLUME_PREFIX=pulse-services ao .env (cópia em .env.antes-h2node.*)"
echo "  - docker compose -p pulse-services down   (sem -v: volumes preservados)"
echo "  - docker compose $FILES up -d --build --wait"
printf "Continuar? [s/N] "; read r
case "$r" in s|S|sim) ;; *) echo "nada feito."; exit 0 ;; esac

if ! grep -q '^VOLUME_PREFIX=' .env; then
  cp .env ".env.antes-h2node.$(date +%Y%m%d%H%M%S)"
  printf '\n# Volumes de antes do rebranding (ver docs/migracao-h2node.md)\nVOLUME_PREFIX=pulse-services\n' >> .env
fi
for v in postgres_data attachments; do
  docker volume inspect "pulse-services_$v" >/dev/null 2>&1 || echo "aviso: volume pulse-services_$v não existe"
done
docker compose -p pulse-services down
# shellcheck disable=SC2086
docker compose $FILES up -d --build --wait --wait-timeout 600
echo "Pronto: projeto h2node-pulse no ar com os volumes pulse-services_*."
