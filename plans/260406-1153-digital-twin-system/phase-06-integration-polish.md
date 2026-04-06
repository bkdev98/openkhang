---
phase: 6
title: Integration & Polish
status: Pending
priority: P2
effort: 2h
depends_on: [1, 2, 3, 4, 5]
---

# Phase 6: Integration & Polish

## Context Links

- All previous phases
- Existing bridge setup: `scripts/setup-bridge.sh` (separate docker-compose at `~/.mautrix-googlechat/`)
- Existing plugin: `.claude-plugin/plugin.json`, `skills/`, `agents/`, `hooks/`

## Overview

Unify all services into a single `docker compose up` experience. Consolidate configuration, document the system, create onboarding flow, and tune confidence thresholds based on initial draft review data.

## Key Insights

- Currently two Docker stacks: bridge at `~/.mautrix-googlechat/` and new services at project root
- Goal: single compose file that includes everything OR clear two-step setup
- Persona YAML is the main user-facing config — must be easy to customize
- Onboarding flow: first run should guide through persona setup, style extraction, initial sync
- Existing Claude Code plugin (skills/agents/hooks) continues to work alongside new services

## Requirements

### Functional
- F1: Single `docker compose up` starts all services (or documented two-step if bridge must stay separate)
- F2: `.env.example` with all required variables documented
- F3: Persona YAML configuration with validation
- F4: Onboarding script: setup persona, extract style, run initial ingestion
- F5: Health check endpoints for all services
- F6: Graceful shutdown: flush working memory, complete in-flight workflows

### Non-Functional
- NF1: Cold start (all services) <60s
- NF2: Memory usage <2GB total for all services
- NF3: Existing plugin functionality unbroken

## Architecture

```
docker-compose.yml (project root)
├── postgres (pgvector)          :5433
├── redis                        :6379
├── synapse                      :8008
├── mautrix-googlechat           (internal)
├── openkhang-agent              (internal, event-driven)
├── openkhang-ingestion          (internal, scheduled)
├── openkhang-workflow           (internal, event-driven)
├── openkhang-dashboard          :8080
└── matrix-listener              (sidecar, writes events)
```

### Decision: Merge vs Separate Bridge Stack

**Option A: Merge into single compose** — Move Synapse + bridge + bridge-postgres into project docker-compose. Pro: single `up`. Con: must migrate existing bridge data, port conflicts.

**Option B: Keep separate, add dependency** — Bridge stays at `~/.mautrix-googlechat/`. Project compose uses `external_network` to communicate. Pro: no migration. Con: two commands.

**Recommendation: Option B** — bridge is already working, migration risk > convenience gain. Document two-step clearly.

## Related Code Files

### Create
- `docker-compose.yml` — All new services (postgres, redis, agent, ingestion, workflow, dashboard, listener)
- `.env.example` — All environment variables with comments
- `scripts/onboard.sh` — Interactive onboarding: persona setup, style extraction, initial sync
- `config/persona.yaml` — Default persona template (user customizes)
- `config/confidence_thresholds.yaml` — Default thresholds
- `config/workflows/` — Pre-built workflow YAML files

### Modify
- `README.md` — Complete rewrite for digital twin system
- `.claude-plugin/plugin.json` — Update version and description
- `scripts/setup-bridge.sh` — Add network creation for cross-compose communication
- `hooks/hooks.json` — Add hook for dashboard notification on session start

### No Deletes — existing skills/agents/hooks preserved

## Implementation Steps

1. **Create Unified docker-compose.yml**
   ```yaml
   services:
     postgres:
       image: pgvector/pgvector:pg16
       ports: ["5433:5432"]
       volumes: [openkhang-pgdata:/var/lib/postgresql/data]
       environment:
         POSTGRES_DB: openkhang
         POSTGRES_USER: openkhang
         POSTGRES_PASSWORD: ${DB_PASSWORD}
       healthcheck:
         test: pg_isready -U openkhang

     redis:
       image: redis:7-alpine
       ports: ["6379:6379"]
       healthcheck:
         test: redis-cli ping

     matrix-listener:
       build: {context: ., dockerfile: docker/listener/Dockerfile}
       depends_on: [redis]
       env_file: .env
       network_mode: host  # needs access to Synapse on localhost:8008

     openkhang-agent:
       build: {context: ., dockerfile: docker/agent/Dockerfile}
       depends_on: [postgres, redis]
       env_file: .env

     openkhang-ingestion:
       build: {context: ., dockerfile: docker/ingestion/Dockerfile}
       depends_on: [postgres, redis]
       env_file: .env

     openkhang-workflow:
       build: {context: ., dockerfile: docker/workflow/Dockerfile}
       depends_on: [postgres, redis, openkhang-agent]
       env_file: .env

     openkhang-dashboard:
       build: {context: ., dockerfile: docker/dashboard/Dockerfile}
       depends_on: [postgres, redis]
       ports: ["8080:8080"]
       volumes: [/var/run/docker.sock:/var/run/docker.sock:ro]
       env_file: .env

   volumes:
     openkhang-pgdata:
   ```

2. **Create .env.example**
   - Database: `DB_PASSWORD`, `DATABASE_URL`
   - Matrix: `MATRIX_HOMESERVER`, `MATRIX_ACCESS_TOKEN`
   - LLM: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (optional)
   - Embedding: `EMBEDDING_API_URL`, `EMBEDDING_API_KEY`
   - Dashboard: `DASHBOARD_PORT=8080`

3. **Create Onboarding Script**
   ```bash
   #!/bin/bash
   # scripts/onboard.sh
   # 1. Check prerequisites (Docker, CLI tools)
   # 2. Copy .env.example → .env, prompt for API keys
   # 3. Customize persona.yaml (name, role, team)
   # 4. Start bridge (if not running): ./scripts/setup-bridge.sh
   # 5. Start services: docker compose up -d
   # 6. Wait for health checks
   # 7. Run initial ingestion: docker compose exec ingestion python -m services.ingestion.full_sync
   # 8. Extract style profile from chat history
   # 9. Print dashboard URL and next steps
   ```

4. **Add Health Checks to All Services**
   - Each service exposes `/health` HTTP endpoint (or uses container healthcheck)
   - Dashboard aggregates all health statuses
   - docker-compose `depends_on` with `condition: service_healthy`

5. **Graceful Shutdown**
   - Agent: flush working memory to episodic store on SIGTERM
   - Workflow: save state machine state, don't start new workflows
   - Listener: save sync token, close Redis connection
   - Dashboard: close SSE connections gracefully

6. **Update README.md**
   - System overview with architecture diagram
   - Prerequisites (Docker, CLI tools, API keys)
   - Quick start: `./scripts/onboard.sh`
   - Configuration reference (persona.yaml, thresholds)
   - Skill reference (existing + new)
   - Troubleshooting

7. **Confidence Tuning Documentation**
   - How to review drafts effectively
   - When to graduate a space from draft → auto-reply
   - How to revert a space back to draft mode
   - Recommended review period: 2 weeks minimum per space

8. **Write Integration Tests**
   - Full stack: `docker compose up` → health checks pass → send test event → verify flow
   - Regression: existing skills still work with new services running

## TODO

- [ ] Create `docker-compose.yml`
- [ ] Create all Dockerfiles (docker/listener/, docker/agent/, etc.)
- [ ] Create `.env.example`
- [ ] Create `scripts/onboard.sh`
- [ ] Add health checks to all services
- [ ] Implement graceful shutdown handlers
- [ ] Update README.md
- [ ] Update `.claude-plugin/plugin.json`
- [ ] Test full stack startup
- [ ] Test existing plugin skills still work
- [ ] Document confidence tuning workflow

## Success Criteria

1. `docker compose up` starts all services, all health checks pass within 60s
2. `docker compose down` shuts down gracefully (no data loss)
3. Existing `/chat-scan`, `/sprint-board`, `/code-session` skills work unchanged
4. Dashboard accessible at localhost:8080 showing live data
5. New user can go from clone → working system in <15 minutes using onboard.sh
6. Memory usage <2GB for full stack

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Bridge network isolation issues | Medium | Medium | Use host network mode for listener, document network setup |
| Port conflicts with existing bridge | Medium | Low | Use non-standard ports (5433, 8080), document in .env |
| Docker build slow (no cache) | Low | Low | Multi-stage builds, pin base images |
| Onboarding script fails on edge cases | Medium | Low | Test on clean macOS, add error handling + recovery hints |

## Security Considerations

- `.env` contains all secrets — must be in `.gitignore`
- Docker socket access limited to dashboard (read-only)
- No services exposed beyond localhost
- API keys never logged or stored in memory/audit log
- `onboard.sh` never echoes API keys to terminal
