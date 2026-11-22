# Produção com backup diário para FTP (docs/OPERACAO.md e docs/BACKUP.md).
# Nunca usar "down -v": apaga banco e anexos.
C := docker compose -f compose.yaml -f compose.production.yaml -f compose.backup.yaml

.PHONY: up down ps logs backup backup-list backup-verify

up:
	$(C) config --quiet
	$(C) up -d --build --wait --wait-timeout 600

down:
	$(C) down

ps:
	$(C) ps

logs:
	$(C) logs --tail=100 -f

backup:
	$(C) run --rm backup-tools run

backup-list:
	$(C) run --rm backup-tools list

backup-verify:
	$(C) run --rm backup-tools verify
