# Agent Framework Architecture Research Report
**Date:** 2026-04-07 | **Scope:** Tool routing, channel abstraction, skill composition patterns

---

## Executive Summary

Open-source AI agent frameworks (LangGraph, CrewAI, AutoGen, Semantic Kernel) converge on **three core patterns**: (1) LLM-native tool calling dominates routing decisions, (2) layered channel abstraction via adapter plugins enables multi-platform support, and (3) registry + plugin architecture decouples tools/skills from core logic. Event-driven message pipelines are emerging as the scalability standard for real-time agent systems.

---

## 1. Tool Routing Approaches

### LLM-Native Tool Calling (Industry Standard)
**Status:** Dominant pattern across all frameworks
- **How it works:** Agent receives tool descriptions, LLM evaluates context & chooses tool via structured output (Claude `tool_use`, OpenAI function calling)
- **Advantages:** LLM handles context awareness; no explicit routing rules needed; works with any tool set
- **Adoption:** OpenAI Agents SDK (released March 2025) is now production-recommended; all major frameworks support this
- **Cost:** ~100-500 tokens per skill disclosure (Semantic Kernel's "Advertise" stage)

### Rule-Based Routing (Legacy)
- Explicit if-then mappings; still used in specific domains but falling out of favor
- Requires maintenance as tool sets grow; doesn't scale to 20+ tools

### Hybrid: Description-Based Matching + LLM
- Some frameworks (CrewAI) use tool descriptions as fallback when LLM confidence is low
- Adds robustness but increases latency slightly

**Recommendation:** Adopt LLM-native tool calling. It's now the proven standard.

---

## 2. Channel Abstraction Architecture

### Three-Layer Pattern (OpenClaw, Vercel Chat SDK)
```
Layer 1: Agent/LLM Core      (channel-agnostic logic)
  ↓
Layer 2: Channel Adapter      (message normalization)
  ↓
Layer 3: Platform API Layer   (Telegram Bot API, Slack Bolt SDK, etc.)
```

**Adapter Responsibilities:**
- Normalize incoming messages (user_id, text, attachments) to canonical format
- Format outbound responses per platform rules (Slack threading, Telegram formatting)
- Handle platform-specific events (reactions, file uploads, group vs DM)
- Route errors/fallbacks per channel UX

**Implementation Pattern:**
- Define abstract `Channel` interface with `send()`, `receive()`, `format_response()`
- Each platform gets a plugin implementation (TelegramChannel, SlackChannel, etc.)
- Core agent never imports platform-specific code
- Gateway pattern: single outbound connection point to all services

**Benefits:**
- Add new channels without touching agent logic (OPEN-CLOSED principle)
- Test agent independently of Telegram/Slack quirks
- Reuse same agent across 20+ platforms (Vercel SDK ships with 7+)

---

## 3. Tool vs Skill Distinction

### Tools
- **Atomic operations:** search, send_message, query_db, read_file
- **LLM-callable:** Can be invoked by agent in a single turn
- **Fast execution:** <5s typical
- **Examples:** CrewAI built-in tools (web search, code execution), Semantic Kernel Function Calling

### Skills
- **Composed workflows:** (code search = embed query → vector search → rerank → format)
- **Multi-step logic:** May involve multiple tools + reasoning between steps
- **Slower execution:** Can be 30s+, may loop internally
- **Semantic Kernel pattern:** Load skills on-demand when matched to task, then read supplementary resources

**Progressive Disclosure (Semantic Kernel):**
1. **Advertise** (~100 tokens): Inject skill names/descriptions into system prompt
2. **Load** (<5000 tokens): Fetch full skill interface when task matches
3. **Read Resources** (as-needed): Agent calls `read_skill_resource()` to fetch docs/examples

---

## 4. Scalable Agent Patterns

### Registry Pattern (All Frameworks)
```
ToolRegistry {
  register("web_search", Tool)
  register("database_query", Tool)
  list_all() → LLM for decision
  get(key) → route to executor
}
```
- CrewAI: Built-in tools via `crewai-tools` package; custom tools extend `BaseTool`
- Semantic Kernel: Plugin system with progressive disclosure
- LangGraph: Tools as graph nodes with state management

**Scalability:** Handles 20-50 tools; beyond that, use progressive disclosure

### Event-Driven Pipeline (Emerging Best Practice)
**For high-throughput, multi-agent systems:**
- **Message Broker:** Kafka/RabbitMQ for event ordering & reliability
- **Stream Processor:** Flink or similar for stateful, low-latency reactions
- **Agent Coordination:** Agents emit events (task-completed, error, request-help); other agents subscribe
- **Advantage:** Agents decouple; teams can develop in parallel; natural workflow emergence from event semantics

**2025 Trend:** Combined Kafka + Flink + agentic AI = new standard for enterprise scale (Microsoft multi-agent reference architecture endorses this)

### Middleware/Interceptor Pipeline
- Pre-processing: Validate input, extract context, apply rate limits
- Post-processing: Format output, log decisions, emit events
- Used by LangGraph (state middleware), CrewAI (task interceptors)
- Enables cross-cutting concerns (logging, cost tracking, audit) without modifying agent core

---

## 5. Framework Maturity & Recommendation

| Framework | Tool Routing | Channel Support | Skill Composition | Production Ready |
|-----------|--------------|-----------------|------------------|------------------|
| **LangGraph** | LLM + state graph | Via adapters | Graph-based workflows | ✅ Yes |
| **CrewAI** | LLM + role-based | Limited | Tool-based | ✅ Yes |
| **AutoGen** | Conversational | Via plugins | Ad-hoc | ✅ Experimental |
| **Semantic Kernel** | LLM + progressive disclosure | Via plugins | Plugin architecture | ✅ Yes (Microsoft) |
| **Vercel AI SDK** | LLM native | Chat SDK layers | Tool composition | ✅ Yes |
| **Mastra** | LLM native (on AI SDK) | Via Vercel SDK | Tool registry | ✅ Growing |

---

## Architectural Fit for openkhang

Based on your agent memory context, recommend:

1. **Tool Routing:** Adopt LLM-native (Claude `tool_use`) — already in use, proven low-latency
2. **Channel Abstraction:** Implement adapter layer for future Telegram/Web expansion
   - Define `MessageAdapter` interface; implement `TelegramAdapter`, `WebAdapter`
   - Keep agent core channel-agnostic
3. **Tool Registry:** Start with simple registry (`Map<string, Tool>`); upgrade to progressive disclosure if tool count >15
4. **Skill Composition:** Use event-driven pipeline if multi-agent coordination needed; otherwise keep linear task execution

---

## Unresolved Questions

1. **Tool versioning:** How do frameworks handle breaking changes to tool signatures during agent execution? (Not clearly documented)
2. **Cost optimization:** Semantic Kernel's progressive disclosure saves tokens—but what's the latency trade-off when loading large skill sets? (No benchmarks found)
3. **Gateway deployment:** OpenClaw references a "Gateway" component but docs sparse on deployment topology & high-availability
4. **Channel-specific streaming:** How to handle platform-specific rate limits (Telegram 30 msgs/sec) in adapter layer? (Assumed responsibility of adapter, not standard pattern)

---

## Sources

- [How Tools Are Called in AI Agents: Complete 2025 Guide](https://medium.com/@sayalisureshkumbhar/how-tools-are-called-in-ai-agents-complete-2025-guide-with-examples-42dcdfe6ba38)
- [Agentic Framework Big Bang — 3 Paths in Autonomous AI](https://blog.pebblous.ai/blog/agentic-framework-explosion/en/)
- [Top 5 Open-Source Agentic AI Frameworks in 2026](https://aimultiple.com/agentic-frameworks)
- [Agent: Function calling - BentoML](https://docs.bentoml.com/en/latest/examples/function-calling.html)
- [Agentic AI Frameworks: Complete Enterprise Guide for 2026](https://www.spaceo.ai/blog/agentic-ai-frameworks/)
- [Inside OpenClaw: The Channel & Messaging System](https://avasdream.com/blog/openclaw-channels-messaging-deep-dive)
- [Multi-Channel AI Agent Deployment: Slack, Teams & Beyond](https://www.mindstudio.ai/blog/multi-channel-ai-agent-deployment-slack-teams)
- [Chat SDK brings agents to your users - Vercel](https://vercel.com/blog/chat-sdk-brings-agents-to-your-users)
- [LangGraph vs CrewAI vs AutoGen: Complete AI Agent Framework Comparison 2025](https://latenode.com/blog/platform-comparisons-alternatives/automation-platform-comparisons/langgraph-vs-autogen-vs-crewai-complete-ai-agent-framework-comparison-architecture-analysis-2025)
- [Semantic Kernel Agent Framework - Microsoft Learn](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/)
- [Semantic Kernel Agent Architecture - Microsoft Learn](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-architecture)
- [Building Production-Ready AI Agents with Semantic Kernel](https://dev.to/sebastiandevelops/building-production-ready-ai-agents-with-semantic-kernel-and-clean-net-architecture-4oeg)
- [How Apache Kafka and Flink Power Event-Driven Agentic AI](https://www.kai-waehner.de/blog/2025/04/14/how-apache-kafka-and-flink-power-event-driven-agentic-ai-in-real-time/)
- [Event Driven Architecture Done Right: How to Scale Systems with Quality in 2025](https://www.growin.com/blog/event-driven-architecture-scale-systems-2025/)
- [The Benefits of Event-Driven Architecture for AI Agent Communication](https://www.hivemq.com/blog/benefits-of-event-driven-architecture-scale-agentic-ai-collaboration-part-2/)
- [Message-driven - Multi-agent Reference Architecture](https://microsoft.github.io/multi-agent-reference-architecture/docs/agents-communication/Message-Driven.html)
- [Using Vercel AI SDK | Mastra Docs](https://mastra.ai/docs/frameworks/agentic-uis/ai-sdk)
- [Using Vercel's AI SDK with Mastra - Mastra Blog](https://mastra.ai/blog/using-ai-sdk-with-mastra)
- [Advanced Tool Usage | Mastra Docs](https://mastra.ai/en/docs/tools-mcp/advanced-usage)
- [Mastra AI: Complete TypeScript Agent Framework Guide](https://www.generative.inc/mastra-ai-the-complete-guide-to-the-typescript-agent-framework-2026)
- [AI SDK 6 - Vercel](https://vercel.com/blog/ai-sdk-6)
- [Mastra Tutorial: How to Build AI Agents in TypeScript](https://www.firecrawl.dev/blog/mastra-tutorial)
