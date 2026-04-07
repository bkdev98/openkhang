---
title: "Standardize Agentic Architecture"
description: "Refactor openkhang pipeline to channel adapters, tool registry, skill system, and LLM tool-calling"
status: complete
priority: P1
effort: 5d
branch: kai/refactor/standardize-agentic-architecture
tags: [refactoring, architecture, agent, tools, skills]
created: 2026-04-07
completed: 2026-04-07
---

# Standardize Agentic Architecture

Refactor the openkhang digital twin's plumbing (NOT identity) to a standardized agentic pattern: channel adapters, tool registry, skill system, LLM tool-calling. All 78 tests must pass after each phase. Zero new external dependencies.

## Decision Record

- **Stay custom Python** — validated by research (OpenClaw and Nanobot both custom runtimes)
- **Claude tool_use** for inward mode; **deterministic pipeline** for outward mode (safety-critical)
- **No LangGraph/CrewAI** — persona agent pattern doesn't fit framework metaphors

## Phases

| # | Phase | Effort | Status | Blocker |
|---|-------|--------|--------|---------|
| 1 | [Channel Adapter Abstraction](phase-01-channel-adapter-abstraction.md) | 1d | Done | None |
| 2 | [Tool Registry + Conversion](phase-02-tool-registry-and-conversion.md) | 1.5d | Done | None |
| 3 | [Skill System](phase-03-skill-system.md) | 1.5d | Done | Phase 2 |
| 4 | [LLM Tool-Calling Integration](phase-04-llm-tool-calling-integration.md) | 1d | Done | Phase 2 |

Phases 1 and 2 are independent (parallel-safe). Phase 3 depends on Phase 2 (skills orchestrate tools). Phase 4 depends on Phase 2 (LLM calls tools).

## Invariants (All Phases)

- 78 existing tests pass
- persona.yaml, style_examples, xung ho, confidence scoring, draft queue, behavioral rules unchanged
- No new pip dependencies
- File size <200 LOC; kebab-case naming
- RAG ingestion pipeline untouched (separate concern)
- Matrix bridge infra (listener, synapse, mautrix) untouched

## Research References

- [OpenClaw Architecture](../reports/researcher-260407-0854-openclaw-architecture.md)
- [Agent Skills Ecosystem](../reports/researcher-260407-0854-agent-skills-ecosystem.md)
- [RAG Agent Integration](../reports/researcher-260407-0854-rag-agent-integration-architecture.md)
- [Agent Architecture Patterns](../reports/researcher-260407-0854-agent-architecture-patterns.md)
- [Framework Comparison](../reports/researcher-260407-0913-agent-framework-comparison.md)
