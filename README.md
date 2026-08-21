# 3S ERP

Modular-monolith ERP platform. Architecture rules live in `.claude/skills/erp-platform-architecture/SKILL.md`.

## Run locally

Prerequisite: Docker Desktop with Compose enabled.

```powershell
docker compose build
docker compose up
```

Services:

- API: http://localhost:8000 and http://localhost:8000/docs
- RabbitMQ management: http://localhost:15672 (`erp` / `erp`)
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000

Stop the stack with `Ctrl+C`, or run `docker compose down`. Add `-v` only when you intentionally want to delete local database, Redis, and Grafana data.

The application and worker share the same image. Modules remain inside the monolith and must communicate through their public APIs and events; containers provide infrastructure, not module boundaries.