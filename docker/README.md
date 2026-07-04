# Docker Setup - MongoDB & PostgreSQL with pgvector

Quick setup for running MongoDB and PostgreSQL with pgvector extension using Docker Compose.

## Prerequisites

- Docker and Docker Compose installed
- At least 2GB free disk space

## Quick Start

1. **Copy environment template:**
   ```bash
   cd docker
   cp .env.example .env
   ```

2. **Start the services:**
   ```bash
   docker compose up -d
   ```

3. **Verify services are running:**
   ```bash
   docker compose ps
   ```

## Services

### MongoDB
- **Port:** 27007 (configurable via `MONGO_PORT`)
- **Username:** admin (configurable via `MONGO_INITDB_ROOT_USERNAME`)
- **Password:** admin (configurable via `MONGO_INITDB_ROOT_PASSWORD`)
- **Container:** mongodb

### PostgreSQL with pgvector
- **Port:** 5432 (configurable via `POSTGRES_PORT`)
- **Username:** postgres (configurable via `POSTGRES_USER`)
- **Password:** 0000 (configurable via `POSTGRES_PASSWORD`)
- **Database:** minirag (configurable via `POSTGRES_DB`)
- **Container:** pgvector

## Common Commands

```bash
# Start services in background
docker compose up -d

# View logs
docker compose logs -f

# View logs for specific service
docker compose logs -f mongodb
docker compose logs -f pgvector

# Stop services
docker compose stop

# Stop and remove containers
docker compose down

# Remove with volumes (caution: deletes data)
docker compose down -v
```

## Connecting to Services

### PostgreSQL

```bash
# Using psql
psql -h localhost -U postgres -d minirag -p 5432

# Using Docker exec
docker exec -it pgvector psql -U postgres -d minirag
```

### MongoDB

```bash
# Using mongosh
mongosh "mongodb://admin:admin@localhost:27007"

# Using Docker exec
docker exec -it mongodb mongosh -u admin -p admin
```

## Configuration

Edit `.env` file to customize:

```env
# MongoDB
MONGO_INITDB_ROOT_USERNAME=admin
MONGO_INITDB_ROOT_PASSWORD=admin
MONGO_PORT=27007

# PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=0000
POSTGRES_DB=minirag
POSTGRES_PORT=5432
```

## Health Checks

Both services include health checks that automatically verify connectivity:
- MongoDB: Checks with `mongosh` ping command
- PostgreSQL: Checks with `pg_isready`

View health status:
```bash
docker compose ps

# Output will show health status:
# NAME     STATE             HEALTH
# mongodb  Up 2 minutes      healthy
# pgvector Up 2 minutes      healthy
```

## Troubleshooting

### Port already in use
Change port in `.env`:
```env
MONGO_PORT=27008      # instead of 27007
POSTGRES_PORT=5433    # instead of 5432
```

### Connection refused
Ensure services are healthy:
```bash
docker compose ps
```

If not healthy, check logs:
```bash
docker compose logs mongodb
docker compose logs pgvector
```

### Reset everything
```bash
# Stop and remove everything including volumes
docker compose down -v

# Restart
docker compose up -d
```

## Data Persistence

- MongoDB data stored in: `mongodata` volume
- PostgreSQL data stored in: `pgvector_data` volume

Data persists when containers are stopped. Remove with `docker compose down -v` if needed.
