# OpenClaw AI Framework Architecture Research Report

**Date:** 2026-04-07  
**Status:** Complete  
**Scope:** Agent architecture, tool routing, channel separation, RAG integration, plugin system

---

## Executive Summary

OpenClaw uses a **gateway-based hub-and-spoke orchestration** with three-layer dispatch (Channel → Gateway → Agent Runtime → Skills). The framework excels at cleanly separating messaging concerns from agent logic via bindings/routing and implements elegant **on-demand skill loading** to manage context windows. Key innovation: dynamically-assembled system prompts that inject only contextually-relevant tools per turn, avoiding prompt bloat.

---

## 1. Agent & Tool Architecture

**Multi-agent isolation:** Each agent runs in its own Docker container with independent sandboxes, auth profiles, and session state. Inbound messages route via (channel, accountId, peer, guild/team) bindings to specific agentId, enabling work/personal/experimental scenario isolation.

**Tool dispatch via ReAct loop:** Agents use Reason + Act cycle—LLM produces text reply OR structured tool calls. Runtime intercepts tool requests, executes, refeds results. This prevents direct LLM exposure to user input and enables safe tool execution.

**Three-layer system:**
1. **Channel Layer**: WhatsApp, Telegram, Slack, Discord, Signal, etc.
2. **Gateway (WebSocket server)**: Single control plane for routing, sessions, auth, events
3. **Agent Runtime**: LLM reasoning with selectively-injected skills

---

## 2. Tool Routing Mechanism (Core Strength)

**Composable system prompt architecture** avoids injecting every tool upfront. Instead:
- Base Pi Agent instructions + workspace configs (AGENTS.md, SOUL.md, TOOLS.md)
- **Dynamically selected skills** matching current request
- Auto-generated tool definitions
- Memory search results (RAG)

**Policy precedence (nested override):** Tool Profile → Provider Profile → Global Policy → Provider Policy → Agent Policy → Group Policy → Sandbox Policy. Session type + sandbox progressively restrict access—DMs/groups have narrower permissions than primary sessions.

**Skill-on-demand loading (elegant):** Compact skill reference list in base prompt, model actively retrieves full SKILL.md when needed. Keeps prompt lean (~10KB reference) while enabling 100+ prebuilt skills without bloat.

---

## 3. Channel-Agent Separation

**Bindings decouple messaging from reasoning:** A single agent receives routed messages from multiple channels simultaneously. No channel-specific logic in the agent—bindings translate platform-specific events to unified Gateway events.

**Each agent's configuration:**
- `~/.openclaw/agents/<agentId>/auth-profiles.json` (per-agent auth secrets)
- `SOUL.md` (personality/constraints)
- `TOOLS.md` (tool usage conventions)
- Independent Docker sandbox + memory database

This design enables agents to operate identically across platforms without platform-specific code paths.

---

## 4. RAG & Memory Integration

**Hybrid semantic + keyword search** via SQLite + vector embeddings:
- Vector similarity for semantic matching
- BM25 for exact token matching

**Memory sources:**
- `MEMORY.md` - Curated long-term facts (private sessions only)
- `memory/YYYY-MM-DD.md` - Daily activity logs
- Session transcripts (optional)

**Embedding auto-fallback:** Local → OpenAI → Gemini → disabled. System auto-reindexes when memory files change, detects embedding model switches.

Memory search results are injected into base prompt dynamically, making RAG transparent to the LLM—the agent sees remembered context as part of system instructions.

---

## 5. Plugin/Extension System

**Discovery-based architecture** in `extensions/` folder—no core modifications needed.

**Four plugin types:**
1. Channel plugins (new messaging platforms)
2. Memory plugins (alternative storage backends)
3. Tool plugins (custom capabilities)
4. Provider plugins (custom LLM providers, self-hosted models)

**Registration:** Plugin loader scans workspace `package.json` for `openclaw.extensions` field, validates against schema, hot-loads. Tools register via simple API: `api.registerTool(toolName, toolDefinition)`.

---

## Lessons for openkhang Digital Twin Project

| Pattern | Application |
|---------|-------------|
| **Composable prompts** | Inject only relevant context per request; avoid bloat with dynamic memory + skill selection |
| **Skill-on-demand** | Use SKILL.md docs + lazy-load. Keeps base agent prompt <10KB reference; full skill docs loaded when needed |
| **Policy precedence nesting** | Build hierarchical tool/memory access controls (sandbox → group → session → agent → global) |
| **Agent per sandbox** | Isolate digital twin environments in separate containers with per-environment auth/config |
| **Binding-based routing** | Separate channel concerns (Telegram, API calls, webhooks) from agent logic via routing layer |
| **Hybrid RAG search** | Combine semantic + keyword matching for digital twin state retrieval (vector + BM25 fallback) |
| **Hot-loadable plugins** | Design skill system to support runtime addition of new digital twin capabilities without restart |

---

## Credibility & Limitations

**Sources:** Official OpenClaw docs (search 2026), Medium deep-dives by framework contributors, GitHub architecture docs.  
**Limitations:** Unable to access docs.openclaw.ai directly (DNS failure). Research based on secondary sources and third-party analysis. Plugin system details inferred from GitHub references; detailed schema validation not examined.

**Unresolved Questions:**
- How does OpenClaw handle tool conflicts (same tool name, different implementations)?
- What is the actual SKILL.md schema/format?
- How does embedding cost scale with memory growth?
- Rate-limiting strategy for multi-agent concurrent tool execution?
