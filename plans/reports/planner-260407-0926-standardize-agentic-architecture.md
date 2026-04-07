# Planner Report: Standardize Agentic Architecture

**Date:** 2026-04-07 | **Status:** DONE

## Summary

Created 4-phase implementation plan to refactor openkhang pipeline from monolithic 520-LOC orchestrator to standardized agentic architecture: channel adapters, tool registry, skill system, LLM tool-calling.

## Plan Location
`/Users/khanh.bui2/Projects/openkhang/plans/260407-0926-standardize-agentic-architecture/`

## Files Created
- `plan.md` — overview (46 lines)
- `phase-01-channel-adapter-abstraction.md` — CanonicalMessage + adapter interface + 5 new files
- `phase-02-tool-registry-and-conversion.md` — BaseTool + ToolRegistry + 7 tool wrappers + 9 new files
- `phase-03-skill-system.md` — SkillRegistry + 4 extracted skills + pipeline shrinks to <200 LOC
- `phase-04-llm-tool-calling-integration.md` — Claude tool_use for inward mode only + ReAct loop

## Key Decisions

1. **Phases 1 & 2 are parallel-safe** — no file overlap. Phase 3 depends on 2. Phase 4 depends on 2.
2. **Outward mode stays deterministic** — NEVER gets tool_use. Safety-critical (auto-sends AS Khanh).
3. **Skill matching is deterministic** (mode + intent), not LLM-based (~20% success rate per research).
4. **Backward compatibility shim** — CanonicalMessage.to_legacy_dict() during transition; pipeline accepts both dict and CanonicalMessage.
5. **No new pip dependencies** — tools and skills are plain Python wrapping existing code.

## Effort Estimate
| Phase | Effort |
|-------|--------|
| 1: Channel Adapters | 1d |
| 2: Tool Registry | 1.5d |
| 3: Skill System | 1.5d |
| 4: LLM Tool-Calling | 1d |
| **Total** | **5d** |

## New Files Summary
- Phase 1: 5 files (adapters + router)
- Phase 2: 9 files (registry + 7 tools + __init__)
- Phase 3: 6 files (registry + 4 skills + __init__)
- Phase 4: 1 file (tool-calling loop)
- **Total: 21 new files**, all <150 LOC

## Risk Highlights
- **Highest risk:** Phase 3 outward-reply skill missing edge case from pipeline → mitigated by diff test (parallel execution, assert identical results)
- **Critical guard:** Phase 4 must NEVER expose tool_use to outward mode → assertion + test enforcement
- **Meridian unknown:** Meridian tool_use support unverified → test first, fallback to Claude API only

## Research Used
5 research reports analyzed covering OpenClaw, agent skills ecosystem, RAG integration, architecture patterns, and framework comparison. All validated the "stay custom Python" decision.
