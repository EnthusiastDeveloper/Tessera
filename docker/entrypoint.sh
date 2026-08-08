#!/bin/sh
# Apply migrations before serving traffic. Nothing else ran this - see design doc §14.2/
# architecture-plan §6: app.main's lifespan now queries the users table on every boot
# (setup-token issuance, RESET_ADMIN_PASSWORD), which requires the schema to already exist.
set -e
alembic upgrade head
exec python -m app.main
