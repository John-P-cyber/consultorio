#!/bin/sh
set -eu

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"

if ! restic snapshots >/dev/null 2>&1; then
  restic init
fi

restic backup /backups /uploads \
  --tag "${APP_ENV:-production}" \
  --host "${RESTIC_HOSTNAME:-consultorio}"

restic forget \
  --keep-daily 14 \
  --keep-weekly 8 \
  --keep-monthly 12 \
  --prune

restic check --read-data-subset=5%
