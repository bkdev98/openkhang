---
title: "Digital Twin System for Software Engineer Work Persona"
description: "Transform openkhang from a Claude Code plugin into a full digital twin that acts as Khanh in Google Chat and assists via dashboard"
status: done
priority: P1
effort: 40h
branch: main
tags: [digital-twin, mem0, fastapi, htmx, dual-mode-agent, docker]
created: 2026-04-06
---

# Digital Twin System — Implementation Plan

## Architecture Summary

```
Google Chat ←→ mautrix bridge ←→ Synapse ←→ matrix-listener.py
                                                    │
                                              Event Bus (Redis)
                                                    │
              ┌─────────────────┬───────────────────┼───────────────────┐
              ▼                 ▼                   ▼                   ▼
        Knowledge         Mem0 + pgvector     Dual-Mode Agent     Dashboard
        Ingestion         (Memory Layer)      (Outward/Inward)    (FastAPI+HTMX)
        Pipeline               │                   │                   │
   Jira/GitLab/Confluence      └───────┬───────────┘                   │
   → chunk → embed → store             ▼                               │
                              Workflow Engine ──────────────────────────┘
                              (YAML state machines, audit log)
```

## Phases

| # | Phase | Effort | Status | Depends On | Files |
|---|-------|--------|--------|------------|-------|
| 1 | [Memory Foundation](phase-01-memory-foundation.md) | 8h | **Done** | — | services/memory/ |
| 2 | [Knowledge Ingestion](phase-02-knowledge-ingestion.md) | 8h | **Done** | Phase 1 | services/ingestion/ |
| 3 | [Dual-Mode Agent](phase-03-dual-mode-agent.md) | 10h | **Done** | Phase 1 | services/agent/ |
| 4 | [Workflow Engine](phase-04-workflow-engine.md) | 6h | **Done** | Phase 3 | services/workflow/ |
| 5 | [Dashboard](phase-05-dashboard.md) | 6h | **Done** | Phase 3 | services/dashboard/ |
| 6 | [Integration & Polish](phase-06-integration-polish.md) | 2h | **Done** | All | docker-compose.yml |

## Dependency Graph

```
Phase 1 (Memory) ──→ Phase 2 (Ingestion)
       │
       └──→ Phase 3 (Agent) ──→ Phase 4 (Workflow)
                    │
                    └──→ Phase 5 (Dashboard)
                                    │
All ──────────────────────────────→ Phase 6 (Integration)
```

## Key Constraints

- No GPU — all embeddings via API (bge-m3)
- No local LLM — Claude API primary, Gemini/MiniMax fallback
- Must preserve existing plugin (skills/, agents/, hooks/) — new code in services/
- Single `docker compose up` for entire stack
- Vietnamese + English mixed content throughout

## Rollback Strategy

Each phase is an additive Docker service. Rollback = remove service from compose + delete its volume. Existing plugin remains functional at all times since services/ is independent.

## Global Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Twin hallucinates experiences | Critical | Confidence gating + RAG grounding + "I don't know" behavior |
| bge-m3 API latency | Medium | Cache embeddings locally, async pipeline |
| Mem0 self-hosted instability | Medium | Postgres as fallback store, data in pgvector survives |
| Style mismatch in outward mode | High | 50-100 real examples, human review in draft mode first |
