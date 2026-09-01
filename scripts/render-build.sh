#!/usr/bin/env bash
set -euo pipefail

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-autrifix.settings.production}"

# collectstatic imports settings; production requires SECRET_KEY + ALLOWED_HOSTS.
# Render's build step often does not inject runtime secrets, so generate a throwaway key
# for this build only. It is never persisted and never reaches the running service — the
# runtime uses the real SECRET_KEY from the environment.
# Previously this was a hardcoded literal (docs/SECURITY.md SEC-GAP-03).
if [ -z "${SECRET_KEY:-}" ]; then
  export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"
  echo "SECRET_KEY not present at build time; generated an ephemeral key for collectstatic."
fi
export ALLOWED_HOSTS="${ALLOWED_HOSTS:-127.0.0.1,localhost,.onrender.com}"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python manage.py collectstatic --noinput
