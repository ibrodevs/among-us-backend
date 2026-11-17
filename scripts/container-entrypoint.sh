#!/bin/sh
set -eu
case "${SERVICE_ROLE:-api}" in
  api)
    exec daphne -b 0.0.0.0 -p "${PORT:-8000}" --websocket_timeout 86400 --websocket_connect_timeout 10 --application-close-timeout 15 config.asgi:application
    ;;
  worker) exec python manage.py run_game_worker ;;
  migrate) exec python manage.py migrate_serialized ;;
  *) exec "$@" ;;
esac
