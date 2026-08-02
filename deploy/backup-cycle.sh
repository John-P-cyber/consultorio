#!/bin/sh
set -eu

environment="${1:-production}"
case "$environment" in
  production|staging) ;;
  *) echo "Environment must be production or staging" >&2; exit 2 ;;
esac

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
project_root="$(dirname "$script_dir")"
compose_env="${COMPOSE_ENV_FILE:-/etc/consultorio/${environment}.compose.env}"

if [ ! -r "$compose_env" ]; then
  echo "Compose environment file not found: $compose_env" >&2
  exit 1
fi

run_compose() {
  docker compose --env-file "$compose_env" -f "$script_dir/compose.yml" "$@"
}

run_compose run --rm backup
run_compose run --rm verify-backup
run_compose rm --force --stop backup-verifier-db

if grep -Eq '^BACKUP_OFFSITE_ENABLED=(1|true|yes)$' "$compose_env"; then
  run_compose run --rm backup-offsite
else
  echo "Off-site backup disabled; set BACKUP_OFFSITE_ENABLED=true after configuring Restic."
fi

echo "Backup cycle completed for $environment"
