# Phase 4: System Prompt Redesign

## Overview
- **Priority:** P2
- **Status:** Complete
- **Effort:** 2h
- **Depends on:** Phase 3 (unified loop determines how prompts are loaded)

Rewrite system prompts to empower autonomous reasoning instead of restricting behavior with rules lists.

## Key Insights
- Current inward prompt is directive: "Report status", "Present drafts", "Take instructions" — tells agent WHAT to do, not HOW to think
- Current outward prompt is rule-heavy: 36 lines of rules, 0 lines about reasoning approach
- OpenClaw/Claude Code pattern: identity → principles → tools → constraints (in that order)
- Tool-use instruction currently hacked as a user message — should be part of system prompt
- Persona config (persona.yaml) already supports hot-reload — prompts should follow same pattern

## Requirements

### Functional
1. Rewrite inward prompt: identity-first, then capabilities, then constraints
2. Rewrite outward prompt: personality-first, then communication style, then guardrails
3. Move tool-use instructions into inward system prompt (replaces [System:] hack)
4. Move behavioral rules to structured sections (not inline prose)
5. Preserve hot-reload support (PromptBuilder re-reads from disk)

### Non-Functional
- Prompts must stay under 2000 tokens each (context budget)
- Must be readable as standalone documents

## Architecture

### Inward Prompt Structure (new — informed by OpenClaw SOUL.md + Claude Code patterns)

**Design principle:** Identity → reasoning approach → tools → style → boundaries.
OpenClaw: "Be resourceful before asking. Try to figure it out."
Claude Code: "Always read code before proposing changes."

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

### Outward Prompt Structure (new — personality-first, minimal rules)

**Design principle:** "You ARE Khanh" → how you write → context awareness → guardrails.
OpenClaw: "You're not a chatbot. You're becoming someone."

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

## Related Code Files

### Modify
- `services/agent/prompts/inward_system.md` — Full rewrite
- `services/agent/prompts/outward_system.md` — Restructure (lighter touch)
- `services/agent/prompt_builder.py` — Inject tool descriptions into inward prompt

### Keep Unchanged
- `config/persona.yaml` — Template variables stay the same
- `services/agent/llm_client.py` — No prompt format changes

## Implementation Steps

1. **Rewrite inward_system.md**
   - Lead with identity and autonomy
   - Add explicit tool-use section: "You have access to these tools: {tool_list}. ALWAYS search memory before answering work questions."
   - Remove rigid "## Your Role" checklist
   - Add reasoning section: "Think about what information you need, fetch it, then answer."
   - Keep hard rules section but make it minimal

2. **Restructure outward_system.md**
   - Lead with "You ARE {name}" (identity, not instructions)
   - Group style rules under "## How You Write" (not "## Communication Style")
   - Simplify hard rules to 3-4 essentials (remove redundant ones)
   - Keep Vietnamese address rules (critical for correctness)

3. **Update PromptBuilder for tool injection**
   - In `_build_inward_system()`: inject tool names/descriptions from registry
   - Format: `## Available Tools\n- search_knowledge: ...\n- search_code: ...`
   - This replaces the [System:] hack with structured prompt content

4. **Test with real messages**
   - Run 10 inward queries through new prompt, compare quality
   - Run 10 outward messages through new prompt, verify style consistency
   - Check token count stays under 2000 per prompt

## Todo

- [x] Rewrite inward_system.md (identity-first structure)
- [x] Restructure outward_system.md (personality-first)
- [x] Add tool descriptions injection to PromptBuilder
- [x] Remove [System:] hack remnant (if not already done in Phase 3)
- [x] Test with 10 real inward queries
- [x] Test with 10 real outward messages
- [x] Verify token budget (<2000 tokens per prompt)

## Success Criteria
- Inward agent uses tools proactively without being forced by [System:] hack
- Outward replies maintain same style quality (no regression in addressing, tone)
- Prompt token count < 2000 each (before context injection)
- Hot-reload still works (edit .md file, next request uses new prompt)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Prompt rewrite changes agent personality | Medium | High | A/B test: run 20 messages through old and new, compare |
| Inward agent over-uses tools (token waste) | Medium | Low | Set tool budget guidance in prompt, monitor via trace |
| Removing rules causes unsafe behavior | Low | High | Keep hard rules section, just restructure around identity-first |
