#!/usr/bin/env bash
set -euo pipefail

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-autrifix.settings.production}"

# collectstatic imports settings; production requires SECRET_KEY + ALLOWED_HOSTS.
# Render "build" often does not inject full runtime secrets, so we provide safe build-only defaults.
export SECRET_KEY="${SECRET_KEY:-build-only-secret-key-must-be-replaced-in-runtime-000000000000}"
export ALLOWED_HOSTS="${ALLOWED_HOSTS:-127.0.0.1,localhost,.onrender.com}"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python manage.py collectstatic --noinput
