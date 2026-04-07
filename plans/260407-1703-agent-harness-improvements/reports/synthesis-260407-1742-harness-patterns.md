# Harness Engineering Patterns — Synthesis Report

**Date:** 2026-04-07 | **Sources:** OpenClaw prompts, Claude Code leaked source, architecture audit

---

## Key Patterns to Adopt

### 1. Layered Prompt Assembly (Both Tools)

**Pattern:** System prompt = identity → tools → context → constraints (in order)

**OpenClaw layers:**
1. SOUL.md (who you are)
2. IDENTITY.md (name/emoji/vibe)
3. USER.md (who you're helping)
4. AGENTS.md (operating instructions)
5. Tool definitions (JSON schemas)
6. Skills manifest (on-demand loading)
7. Memory recall instructions
8. Safety guardrails

**Claude Code layers:**
1. Core identity ("interactive agent for software engineering")
2. Tool definitions (24 tools with usage policies)
3. Conditional context (git status, recent commits, CLAUDE.md)
4. System reminders (runtime injections)
5. Safety hooks (PreToolUse/PostToolUse)

**Our current:** Monolithic .md template with string replacement. No layering.

**Action:** Split prompts into composable sections. Inject dynamically based on mode/context.

---

### 2. Identity-First, Not Rules-First

**OpenClaw SOUL.md philosophy:**
> "Be genuinely helpful, not performatively helpful."
> "Be resourceful before asking. Try to figure it out."
> "Have opinions."
> "Be bold with internal actions (reading, organizing, learning)."

**Claude Code philosophy:**
> "Always read code before proposing changes."
> "Use TodoWrite frequently for task tracking."

**Our current inward prompt:**
> "Report status", "Present drafts", "Take instructions" — checklist of duties

**Action:** Lead with "who you are and how you think" not "what you must do"

---

### 3. Tool Instructions as System Prompt, Not Hacked Messages

**OpenClaw:**
> "Structured tool definitions are the source of truth for tool names, descriptions, and parameters."

**Claude Code:**
> "Do NOT use Bash to run commands when a relevant dedicated tool is provided."
> Lists each tool with when/why to use it.

**Our current:** Appending `[System: You have access to search tools. ALWAYS use search_knowledge...]` as fake user message.

**Action:** Move tool instructions into system prompt proper. Include tool names, descriptions, and when to use each one.

---

### 4. Proactive Context Gathering

**OpenClaw AGENTS.md:**
> "Read these files first: SOUL.md, USER.md, memory/today.md, memory/yesterday.md. Don't ask permission. Just do it."

**Claude Code:**
> Injects git status, recent commits, file modifications automatically into system context.

**Our current:** Agent gets body text and nothing else. Must call tools to get any context (but limited to 3 iterations).

**Action:** Pre-inject relevant context (room metadata, thread history, sender profile, recent interactions) into the prompt before the agent even starts thinking.

---

### 5. Memory Compaction Protocol

**OpenClaw:**
> "Session nearing compaction. Store durable memories now. Write to memory/YYYY-MM-DD.md; reply with NO_REPLY if nothing to store."

**Claude Code:**
> TodoWrite for task persistence. Conversation summarization at context limits.

**Our current:** No compaction awareness. Agent doesn't know when context is getting full.

**Action:** Not urgent for v1, but design for it. Agent should know its context budget.

---

### 6. Generous Agent Loop

**OpenClaw:** 600s timeout, unlimited iterations
**Claude Code:** Subagent-level isolation with role-specific tool access, no hard iteration limit

**Our current:** 3 iterations, 30s timeout

**Action:** Inward mode: 10 iterations, 120s timeout. Outward stays deterministic (safety).

---

### 7. Deterministic Routing Over LLM Routing

**OpenClaw explicitly states:**
> "LLMs are unreliable routers." Recommends Lobster (deterministic workflow engine) over LLM-based routing.

**Our plan:** Use LLM for classification (intent, should_respond, priority).

**Tension:** OpenClaw says don't use LLM for routing. But our regex routing is WORSE than LLM routing. The right approach: **hybrid** — regex fast-path for obvious cases (social greetings, known DMs), LLM for ambiguous cases (group threads, mixed intent).

---

### 8. Skill Loading On-Demand

**OpenClaw:**
> "Scan available skills and selectively read the most applicable SKILL.md file — never load multiple skills upfront."

**Our current:** All skills registered at init, first-match routing.

**Action:** Not directly applicable (our skills are code, not .md files), but the principle holds: don't load all context for every message. Context strategy engine (Phase 2) addresses this.

---

## Concrete Prompt Designs

### Inward System Prompt v2

```markdown
You are openkhang — Khanh's autonomous digital work twin.

## How You Think
- Be resourceful. Search memory and code before answering. Don't guess.
- Think step by step. Plan what information you need, fetch it, then respond.
- If the first search doesn't answer the question, try different terms or tools.
- Have opinions. You know Khanh's work context — use that knowledge confidently.

## Your Tools
{tool_descriptions}

Use tools proactively. For work questions: ALWAYS search_knowledge first.
For code questions: use search_code. For people: use lookup_person.
Don't answer from general knowledge alone — ground answers in Khanh's actual data.

## When Khanh Gives Instructions
Execute immediately. Khanh IS the approver — don't ask for confirmation.
Messages are sent via Google Chat (Matrix bridge). Never ask which channel.
When composing messages to send, use Khanh's voice and style.

## Response Style
- Concise, actionable. No padding.
- Bullet points for lists. Markdown formatting.
- Cite sources: ticket IDs, room names, file paths.
- Note data freshness when context may be stale (>24h).

## Hard Rules
- Never fabricate. If you don't have the data, say so clearly.
- Never auto-send to chat without explicit instruction.
- Only push back if genuinely dangerous (deleting data, public announcements).
```

### Outward System Prompt v2

```markdown
You are {name}, replying to a colleague in Google Chat.

## Who You Are
{name}, {role} at {company}. {team}.
You speak {languages}. You're {formality} — friendly but professional.
Keep replies short: {response_length}. Emoji: {emoji_usage}, only where natural.
Switch languages naturally based on what the colleague wrote.

## How You Think
Use the context provided to answer. If the context contains the answer, reply confidently.
If you're unsure, say so naturally:
{uncertainty_block}

## Vietnamese Address Rules
{address_rules_block}

## Hard Rules
{never_do_block}
- Never answer about something with no evidence in context.
- Social messages: respond briefly and warmly, no citations needed.
- If you find code/config in context, cite the source file.
```

---

## Unresolved
1. Token budget for tool descriptions injection — need to measure actual size
2. Whether to inject room metadata (member count, room type) into system prompt or context message
3. How to handle extended thinking (Meridian proxy support for thinking blocks?)
