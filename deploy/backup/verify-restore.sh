#!/bin/sh
set -eu

: "${VERIFY_DATABASE_URL:?VERIFY_DATABASE_URL is required}"
: "${VERIFY_DATABASE_NAME:?VERIFY_DATABASE_NAME is required}"

backup_dir="${BACKUP_DIR:-/backups}"
case "$backup_dir" in
  /backups|/backups/*) ;;
  *) echo "BACKUP_DIR must be /backups or a child directory" >&2; exit 2 ;;
esac

case "$VERIFY_DATABASE_NAME" in
  *_restore_verify) ;;
  *) echo "Refusing to modify a database not ending in _restore_verify" >&2; exit 2 ;;
esac

url_without_query="${VERIFY_DATABASE_URL%%\?*}"
database_in_url="${url_without_query##*/}"
if [ "$database_in_url" != "$VERIFY_DATABASE_NAME" ]; then
  echo "VERIFY_DATABASE_URL and VERIFY_DATABASE_NAME do not match" >&2
  exit 2
fi

latest_dump="$(find "$backup_dir" -maxdepth 1 -type f -name 'consultorio_*.dump' | sort | tail -n 1)"
if [ -z "$latest_dump" ]; then
  echo "No backup found to verify" >&2
  exit 1
fi

checksum_file="$latest_dump.sha256"
if [ ! -f "$checksum_file" ]; then
  echo "Checksum file not found" >&2
  exit 1
fi

(
  cd "$backup_dir"
  sha256sum -c "$(basename "$checksum_file")"
)

psql "$VERIFY_DATABASE_URL" -v ON_ERROR_STOP=1 \
  -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
pg_restore \
  --dbname="$VERIFY_DATABASE_URL" \
  --exit-on-error \
  --no-owner \
  --no-acl \
  "$latest_dump"

psql "$VERIFY_DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF to_regclass('public.alembic_version') IS NULL THEN
    RAISE EXCEPTION 'alembic_version table is missing';
  END IF;
  IF to_regclass('public.usuarios') IS NULL THEN
    RAISE EXCEPTION 'usuarios table is missing';
  END IF;
  IF to_regclass('public.clinicas') IS NULL THEN
    RAISE EXCEPTION 'clinicas table is missing';
  END IF;
END $$;
SELECT version_num FROM alembic_version;
SQL

echo "Restore verification passed: $(basename "$latest_dump")"
