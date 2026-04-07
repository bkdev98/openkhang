---
title: "Agent Harness Improvements — Context Quality & Unified Pipeline"
description: "Replace regex classifier with LLM router, unify agent execution paths, improve context gathering"
status: complete
priority: P1
effort: 16h
branch: kai/feat/agent-harness-v2
tags: [agent, pipeline, classifier, context, prompts]
created: 2026-04-07
---

# Agent Harness Improvements

## Goal
Improve context quality across all agent processes: smarter routing, right context at the right time, unified execution, empowering prompts.

## Phases

| # | Phase | Effort | Status | Dependencies |
|---|-------|--------|--------|--------------|
| 1 | [LLM-based Message Router](phase-01-llm-message-router.md) | 4h | Complete | None |
| 2 | [Context Strategy Engine](phase-02-context-strategy-engine.md) | 3h | Complete | Phase 1 |
| 3 | [Unified Agent Loop](phase-03-unified-agent-loop.md) | 4h | Complete | Phase 2 |
| 4 | [System Prompt Redesign](phase-04-system-prompt-redesign.md) | 2h | Complete | Phase 3 |
| 5 | [Outward Agent Improvements](phase-05-outward-agent-improvements.md) | 3h | Complete | Phase 1, 2 |

## Data Flow (Current vs Target)

**Current:** `event → regex classify → skill match → ad-hoc context gather → LLM → route`
**Target:** `event → LLM router (fast) → context strategy (parallel fetch) → unified loop → route`

## Key Constraints
- Meridian proxy is primary LLM provider (Max subscription, $0 marginal cost)
- Must preserve draft queue safety net (never auto-send without confidence)
- Hot-reload for prompts and persona config must survive refactor
- Matrix bridge is source of truth for room metadata (mautrix)

## Research Completed
- [OpenClaw Framework Analysis](../reports/researcher-260407-1611-openclaw-framework.md)
- [Multi-Agent Alternatives Comparison](../reports/researcher-260407-1612-multi-agent-alternatives.md)
- [CrewAI Production Readiness](../reports/researcher-260407-1632-crewai-production-readiness.md)
- [OpenClaw Production Maturity](../reports/researcher-260407-1632-openclaw-production-maturity.md)
- [OpenClaw Prompts (SOUL.md, system prompt, tools)](reports/researcher-260407-1652-openclaw-prompts.md)
- [Claude Code Prompts (leaked source, modular architecture)](reports/researcher-260407-1652-claude-code-system-prompts.md)
- [Harness Patterns Synthesis](reports/synthesis-260407-1742-harness-patterns.md)

**Decision:** Stay on current Python stack. Adopt harness engineering patterns from OpenClaw/Claude Code. No framework migration needed.

## Rollback
Each phase is independently deployable. Revert = `git revert` the phase's commits. Phase 1 keeps regex as fast-path fallback, so partial rollback is safe.
