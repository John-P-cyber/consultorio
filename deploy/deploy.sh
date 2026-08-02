#!/bin/sh
set -eu

environment="${1:-}"
case "$environment" in
  production|staging) ;;
  *) echo "Usage: deploy.sh production|staging" >&2; exit 2 ;;
esac

: "${APP_IMAGE:?APP_IMAGE must be an immutable image tag}"

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
compose_env="${COMPOSE_ENV_FILE:-/etc/consultorio/${environment}.compose.env}"
if [ ! -r "$compose_env" ]; then
  echo "Compose environment file not found: $compose_env" >&2
  exit 1
fi

run_compose() {
  docker compose \
    --env-file "$compose_env" \
    -f "$script_dir/compose.yml" \
    -f "$script_dir/compose.observability.yml" \
    "$@"
}

current_container="$(run_compose ps -q app 2>/dev/null || true)"
previous_image=""
if [ -n "$current_container" ]; then
  previous_image="$(docker inspect --format '{{.Image}}' "$current_container" 2>/dev/null || true)"
fi

docker pull "$APP_IMAGE"
run_compose run --rm --no-deps migrate
run_compose up -d --remove-orphans

app_container="$(run_compose ps -q app)"
healthy=false
attempt=1
while [ "$attempt" -le 30 ]; do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$app_container")"
  if [ "$health" = "healthy" ]; then
    healthy=true
    break
  fi
  if [ "$health" = "unhealthy" ] || [ "$health" = "exited" ] || [ "$health" = "dead" ]; then
    break
  fi
  sleep 3
  attempt=$((attempt + 1))
done

ready=false
if [ "$healthy" = "true" ] && run_compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5)"; then
  ready=true
fi

if [ "$healthy" != "true" ] || [ "$ready" != "true" ]; then
  echo "Deployment liveness/readiness check failed" >&2
  run_compose logs --tail=100 app >&2 || true
  if [ -n "$previous_image" ]; then
    echo "Rolling the application container back to the previous image" >&2
    APP_IMAGE="$previous_image" run_compose up -d --no-deps app
  else
    run_compose stop app
  fi
  exit 1
fi

echo "Deployment completed: $environment ($APP_IMAGE)"
