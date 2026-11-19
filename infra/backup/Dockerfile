# pg_dump/pg_restore 17 vêm da mesma imagem do banco; gpg e lftp cuidam de cifra e FTP.
FROM postgres:17.11-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends gnupg lftp ca-certificates tar \
    && rm -rf /var/lib/apt/lists/*
COPY infra/backup/backup.sh /usr/local/bin/pulse-backup
RUN chmod 0755 /usr/local/bin/pulse-backup
ENTRYPOINT ["/usr/local/bin/pulse-backup"]
CMD ["daemon"]
