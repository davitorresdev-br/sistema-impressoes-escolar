#!/usr/bin/env bash
# Backup do banco COM O SERVIDOR NO AR.
#
# Usa `sqlite3 .backup`, e não `cp`: desde que o WAL foi ligado, o banco é
# três arquivos (.db, .db-wal, .db-shm) e copiar só o .db pode deixar de
# fora as últimas transações — inclusive os pedidos da manhã. O .backup faz
# a cópia de forma consistente, sem parar o serviço.
#
# Instalar como rotina diária:
#   sudo cp deploy/ubuntu/backup-banco.sh /opt/acalanto/deploy/ubuntu/
#   sudo cp deploy/ubuntu/acalanto-backup.{service,timer} /etc/systemd/system/
#   sudo systemctl daemon-reload && sudo systemctl enable --now acalanto-backup.timer
#
# Conferir: systemctl list-timers acalanto-backup

set -euo pipefail

BANCO="${ACALANTO_DB:-/opt/acalanto/banco_dados/acalanto_print.db}"
DESTINO="${ACALANTO_BACKUP_DIR:-/var/backups/acalanto}"
MANTER_DIAS="${ACALANTO_BACKUP_MANTER:-14}"

if [[ ! -f "$BANCO" ]]; then
    echo "ERRO: banco não encontrado em $BANCO" >&2
    exit 1
fi

mkdir -p "$DESTINO"
carimbo="$(date +%Y-%m-%d_%H%M)"
arquivo="$DESTINO/acalanto_print_$carimbo.db"

# .backup respeita o WAL e não trava o servidor.
sqlite3 "$BANCO" ".backup '$arquivo'"

# Um backup que não abre não é backup: conferimos ANTES de apagar os antigos.
if ! sqlite3 "$arquivo" "PRAGMA integrity_check;" | grep -q '^ok$'; then
    echo "ERRO: a cópia $arquivo não passou no integrity_check — mantendo os backups antigos." >&2
    exit 2
fi

pedidos="$(sqlite3 "$arquivo" "SELECT COUNT(*) FROM pedidos;")"
usuarios="$(sqlite3 "$arquivo" "SELECT COUNT(*) FROM usuarios_locais;")"

gzip -f "$arquivo"
echo "Backup OK: ${arquivo}.gz ($pedidos pedidos, $usuarios usuários)"

# Rotação por idade. -mtime +N apaga o que tem mais de N dias.
find "$DESTINO" -name 'acalanto_print_*.db.gz' -type f -mtime "+$MANTER_DIAS" -delete
echo "Backups mantidos: $(find "$DESTINO" -name 'acalanto_print_*.db.gz' | wc -l) (política: $MANTER_DIAS dias)"
