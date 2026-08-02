#!/bin/sh
set -eu
umask 077

: "${DATABASE_URL:?DATABASE_URL is required}"

backup_dir="${BACKUP_DIR:-/backups}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"

case "$backup_dir" in
  /backups|/backups/*) ;;
  *) echo "BACKUP_DIR must be /backups or a child directory" >&2; exit 2 ;;
esac

case "$retention_days" in
  ''|*[!0-9]*) echo "BACKUP_RETENTION_DAYS must be an integer" >&2; exit 2 ;;
esac

case "$DATABASE_URL" in
  postgresql+psycopg2://*) pg_url="postgresql://${DATABASE_URL#postgresql+psycopg2://}" ;;
  postgresql://*) pg_url="$DATABASE_URL" ;;
  *) echo "DATABASE_URL must point to PostgreSQL" >&2; exit 2 ;;
esac

mkdir -p "$backup_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
environment="${APP_ENV:-unknown}"
final_file="$backup_dir/consultorio_${environment}_${timestamp}.dump"
temporary_file="$final_file.partial"
checksum_file="$final_file.sha256"

cleanup() {
  rm -f "$temporary_file" "$checksum_file.partial"
}
trap cleanup EXIT INT TERM

pg_dump \
  --dbname="$pg_url" \
  --format=custom \
  --compress=6 \
  --no-owner \
  --no-acl \
  --file="$temporary_file"

pg_restore --list "$temporary_file" >/dev/null
digest="$(sha256sum "$temporary_file" | awk '{print $1}')"
printf '%s  %s\n' "$digest" "$(basename "$final_file")" > "$checksum_file.partial"
mv "$temporary_file" "$final_file"
mv "$checksum_file.partial" "$checksum_file"
trap - EXIT INT TERM

find "$backup_dir" -maxdepth 1 -type f \
  \( -name 'consultorio_*.dump' -o -name 'consultorio_*.dump.sha256' \) \
  -mtime "+$retention_days" -delete

echo "Backup created and structurally validated: $(basename "$final_file")"
