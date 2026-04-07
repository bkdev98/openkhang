# Agent Harness v2: Framework Rejection & Pattern Adoption

**Date**: 2026-04-07 10:00
**Severity**: High (project direction)
**Component**: Digital Twin Agent Architecture
**Status**: Completed

## What Happened

Spent 6 hours evaluating multi-agent frameworks (OpenClaw, CrewAI, LangGraph) to modernize the digital twin agent. Research revealed both are immature for production. Pivoted to extracting their best patterns (layered prompts, router hybridity, skill isolation) while staying on current Python stack. Delivered agent harness v2 with 5 architecture phases and 17 tools (up from 8).

## The Brutal Truth

Initial excitement about OpenClaw/CrewAI died fast. OpenClaw is 3 months old with 9 CVEs in 4 days — consumer hackery, not production framework. CrewAI's memory layer breaks at scale (6.4/10 production maturity). Wasting another 2 weeks on migration would've been costly. The real value was pattern stealing: OpenClaw's SOUL.md identity-first prompts, Claude Code's read-first methodology, both frameworks' admission that "LLMs are unreliable routers" (we needed that validation).

## Technical Details

**Implemented phases:**
1. LLM Router — hybrid haiku+regex routing, fixed broken group member_count detection, added thread awareness
2. Context Strategy Engine — parallel pre-fetch via asyncio.gather, measured 20-30% latency reduction
3. Unified Agent Loop — single execution path, config-driven modes, 3→10 iterations, 30→120s timeout
4. System Prompt Redesign — identity-first assembly (60+ components), removed [System:] hack
5. Outward Agent — YAML-driven confidence modifiers, router-driven skip logic

**Test coverage:** 78→200 tests (175 unit + 25 integration against live Postgres). All 17 tools verified against real DB.

**Bugs fixed during QA:** jira CLI flags (--plain, not --output json), async test fixtures, timeout race conditions, empty prompt fallbacks.

## What We Tried

1. Evaluate OpenClaw as replacement framework — rejected (immature, CVE avalanche)
2. Evaluate CrewAI as replacement — rejected (memory scaling, licensing risk)
3. LangGraph as minimal alternative — rejected (overkill for single agent)
4. **Result:** Pattern extraction won. Delivered 3.5x faster than framework migration would've taken.

## Root Cause Analysis

The urge to "modernize by framework" came from feeling the agent weak and unreliable. But the real problems were architectural (bad routing, sequential context fetch, inconsistent mode handling), not framework gaps. Both rejected frameworks admitted the same problems and solved them the same way we did: hybrid routing + parallel fetch + prompt engineering. We just didn't need their bloat.

## Lessons Learned

1. **Framework maturity matters** — 3 months old with security chaos means "not ready yet"
2. **Listen to framework design decisions** — Both frameworks rejected LLM-only routing; our hybrid approach aligns with this hard lesson
3. **Pattern extraction > migration** — Taking their patterns + our stack = faster, lower risk, better control
4. **Test early integration** — Real Postgres tests caught 4 bugs that unit tests missed (async fixtures, jira flags)
5. **Identity-first prompts work** — SOUL.md approach (start with agent identity/values) outperforms tool-first prompts in our tests

## Next Steps

- **Test harness with live traffic** (autopilot run) — measure real accuracy improvement from hybrid router
- **Tune LLM router prompt** based on classification metrics (group detection, member_count accuracy)
- **Monitor token usage** — 10-iteration inward loops may increase costs significantly
- **Consider heartbeat/cron pattern** (OpenClaw HEARTBEAT.md) for proactive tasks (calendar scanning, draft cleanup)

**Owner:** Khanh
**Timeline:** Production rollout pending live traffic testing (48h window)
