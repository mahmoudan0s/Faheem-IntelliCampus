#this command not work while building the docker image, so we need to run it in entrypoint.sh
#!/bin/bash
set -e

echo "Running database migrations..."
cd /app/models/db_schemes/minirag/
alembic upgrade head
cd /app

# after migrations, execute the command passed to the entrypoint
exec "$@"