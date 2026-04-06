---
phase: 3
title: Dual-Mode Agent Core
status: Pending
priority: P1
effort: 10h
depends_on: [1]
---

# Phase 3: Dual-Mode Agent Core

## Context Links

- Phase 1: [Memory Foundation](phase-01-memory-foundation.md) — memory client required
- Existing agents: `agents/chat-categorizer.md`, `agents/pipeline-fixer.md`
- Existing chat flow: `skills/chat-scan/`, `skills/chat-reply/`, `skills/chat-autopilot/`
- Matrix send API: via `scripts/matrix-listener.py` architecture

## Overview

Build the dual-mode agent — the brain of the digital twin. **Outward mode** acts AS Khanh to colleagues in Google Chat (replies in his voice/style). **Inward mode** acts AS assistant to Khanh via dashboard/CLI (status reports, drafts, takes instructions). Both modes share the same memory but use different system prompts and confidence thresholds.

## Key Insights

- Outward prompt: "You are Khanh Bui, software engineer at MoMo..." — must sound like the real person
- Inward prompt: "You are openkhang, Khanh's digital work twin..." — professional assistant tone
- Style matching requires 50-100 real chat messages as few-shot examples
- Hallucination is the #1 risk: twin must never claim experiences that didn't happen
- RAG grounding: every outward reply must cite memory evidence or decline
- Confidence gating: start ALL spaces in draft mode, graduate per-space after review period
- Three-tier autonomy: T1 (read-only, auto), T2 (reversible/chat replies, confidence-gated), T3 (irreversible/Jira updates, always approval)

## Requirements

### Functional
- F1: Agent pipeline: classify intent → query RAG → load memory → build prompt → LLM → confidence check → act
- F2: Outward mode: generate replies matching Khanh's style, Vietnamese+English
- F3: Inward mode: answer questions about work state, generate reports, take instructions
- F4: Confidence scoring: 0-1 score per generated reply, threshold configurable per space
- F5: Draft queue: replies below confidence threshold go to review queue (stored in Postgres)
- F6: Auto-reply: replies above threshold in graduated spaces send automatically via Matrix API
- F7: Style profile: extracted from real messages, versioned, editable
- F8: Explicit "I don't know" behavior when RAG returns no relevant evidence

### Non-Functional
- NF1: Reply generation <5s end-to-end (including RAG + LLM)
- NF2: Style consistency: human evaluator cannot distinguish twin from real user in 70%+ of cases
- NF3: Zero hallucinated commitments (never promise deadlines, meetings, deliverables without evidence)

## Architecture

```
                    Incoming Event (chat message, user instruction)
                                    │
                                    ▼
                          ┌─────────────────┐
                          │  Mode Classifier │
                          │  (outward/inward)│
                          └────────┬────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                              ▼
          ┌──────────────┐              ┌──────────────┐
          │ Outward Mode │              │ Inward Mode  │
          │              │              │              │
          │ System:      │              │ System:      │
          │ "You are     │              │ "You are     │
          │  Khanh..."   │              │  openkhang..." │
          │              │              │              │
          │ Style: few-  │              │ Style:       │
          │ shot examples│              │ professional │
          └──────┬───────┘              └──────┬───────┘
                 │                              │
                 └──────────────┬───────────────┘
                                ▼
                     ┌────────────────────┐
                     │   Agent Pipeline    │
                     │                    │
                     │ 1. Intent classify │
                     │ 2. RAG query       │
                     │ 3. Memory load     │
                     │ 4. Prompt build    │
                     │ 5. LLM call        │
                     │ 6. Confidence check│
                     │ 7. Route output    │
                     └────────┬───────────┘
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
          Auto-send      Draft Queue     Report/Action
          (high conf)    (low conf)      (inward mode)
```

### Data Flow — Outward Mode

1. Chat message arrives via Redis event bus (from matrix-listener)
2. Mode classifier: sender is colleague → outward mode
3. Intent classifier: question / request / FYI / social → determines response type
4. RAG query: search memory for relevant context (recent conversations, related tickets, etc.)
5. Memory load: get relationship graph for sender (past interactions, shared projects)
6. Prompt build: system prompt (persona) + few-shot style examples + RAG context + message
7. LLM call: Claude API with structured output (reply_text, confidence, evidence_citations)
8. Confidence check: if confidence >= threshold for this space → auto-send via Matrix API
9. If below threshold → store in draft_replies table → surface in dashboard

### Data Flow — Inward Mode

1. User instruction arrives via dashboard or CLI
2. Mode classifier: source is dashboard/CLI → inward mode
3. Intent classifier: status query / instruction / draft review
4. RAG query + memory load (same pipeline)
5. Prompt build: assistant system prompt + relevant context
6. LLM call: generate report/response
7. Return to dashboard/CLI

## Related Code Files

### Create
- `services/agent/__init__.py`
- `services/agent/pipeline.py` — Main agent pipeline (classify → RAG → prompt → LLM → act)
- `services/agent/classifier.py` — Mode + intent classification
- `services/agent/prompt_builder.py` — System prompt assembly with RAG context + few-shot
- `services/agent/confidence.py` — Confidence scoring + threshold management
- `services/agent/style_profile.py` — Extract/store/load style profile from real messages
- `services/agent/outward.py` — Outward mode specifics (persona, style matching)
- `services/agent/inward.py` — Inward mode specifics (assistant behavior)
- `services/agent/draft_queue.py` — Draft reply storage + review operations
- `services/agent/llm_client.py` — Claude API client with Gemini/MiniMax fallback
- `services/agent/matrix_sender.py` — Send replies via Matrix API
- `services/agent/prompts/outward_system.md` — Outward system prompt template
- `services/agent/prompts/inward_system.md` — Inward system prompt template
- `config/persona.yaml` — Khanh's persona definition (name, role, team, style traits)
- `config/confidence_thresholds.yaml` — Per-space confidence thresholds

### Modify
- `docker-compose.yml` — Add agent service

### No Deletes

## Implementation Steps

1. **Create Persona Configuration**
   ```yaml
   # config/persona.yaml
   name: "Khanh Bui"
   role: "Software Engineer"
   company: "MoMo"
   team: "Backend"
   languages: ["Vietnamese", "English"]
   style_traits:
     formality: "casual-professional"
     emoji_usage: "moderate"
     response_length: "concise"
     humor: "occasional"
   never_do:
     - Promise specific deadlines without evidence
     - Claim to have attended meetings you have no record of
     - Share confidential information outside team channels
     - Make technical commitments without checking current code state
   ```

2. **Extract Style Profile from Real Messages**
   - Read gchat-inbox.jsonl, filter to messages sent BY Khanh (own_puppet_prefix)
   - Wait — Khanh's sent messages aren't in inbox (listener skips own puppet).
   - Alternative: use Matrix `/sync` with full history to get sent messages, OR
   - Ask user to export 50-100 representative messages manually
   - Extract: avg length, language distribution, common phrases, emoji frequency, formality markers
   - Store as `config/style_examples.jsonl` — used as few-shot in prompts

3. **Build LLM Client with Fallback**
   ```python
   class LLMClient:
       async def generate(self, messages: list[dict], model: str = "claude") -> LLMResponse:
           # Try Claude API first
           # If rate limited or error → try Gemini
           # If still fails → try MiniMax/OpenAI
           # Return: {text, model_used, tokens_used, latency_ms}
   ```
   - Structured output: reply_text, confidence (0-1), evidence_citations (list of memory IDs)
   - Temperature: 0.3 for outward (consistency), 0.5 for inward (creativity for reports)

4. **Build Agent Pipeline**
   - Entry point: `async def process_event(event: dict) -> AgentResult`
   - Steps:
     a. `classifier.classify_mode(event)` → outward / inward
     b. `classifier.classify_intent(event)` → question / request / fyi / social / instruction / query
     c. `memory_client.search(event.body, agent_id=mode)` → relevant memories (top 10)
     d. `memory_client.get_related(event.sender)` → sender relationship context
     e. `prompt_builder.build(mode, intent, memories, sender_context, event)` → messages list
     f. `llm_client.generate(messages)` → response with confidence
     g. Route based on confidence + mode

5. **Implement Confidence Scoring**
   - Base score from LLM self-assessment (structured output)
   - Modifiers:
     - +0.1 if RAG returned 3+ relevant memories
     - -0.2 if message contains question about timeline/deadline
     - -0.3 if sender is unknown (no prior interactions in memory)
     - -0.1 if message language != persona primary language
   - Per-space thresholds in `confidence_thresholds.yaml`
   - Default threshold: 0.8 (conservative start)
   - Graduate threshold: reviewed 20+ drafts for a space with >90% approval → lower to 0.6

6. **Implement Draft Queue**
   - Postgres table: `draft_replies(id, event_id, room_id, room_name, original_message, draft_text, confidence, evidence, status, created_at, reviewed_at, reviewer_action)`
   - Status: `pending` → `approved` / `rejected` / `edited`
   - On approved: send via Matrix API
   - On edited: send edited version via Matrix API
   - On rejected: discard, optionally feed back to memory as negative example

7. **Implement Matrix Sender**
   - Reuse Matrix API helper from `scripts/matrix-listener.py` (`matrix_api` function)
   - Send text message to room via `PUT /rooms/{roomId}/send/m.room.message/{txnId}`
   - Support thread replies (m.relates_to with m.thread rel_type)
   - Log all sent messages to episodic store

8. **Build System Prompts**
   - Outward: persona + style examples + RAG context + "NEVER claim experiences without evidence" + "Say 'let me check and get back to you' when unsure"
   - Inward: assistant identity + work context + "Be concise, actionable, cite sources"
   - Both: inject relevant memories as `<context>` block, inject current time

9. **Wire to Event Bus**
   - Subscribe to Redis channel `openkhang:events`
   - Filter for `chat_message` events
   - Process through pipeline
   - Publish results to `openkhang:agent_results` channel (dashboard subscribes)

10. **Write Tests**
    - Unit: classifier with sample messages, prompt builder output structure
    - Unit: confidence scoring with various modifier combinations
    - Integration: full pipeline with mocked LLM → verify draft created
    - Style: compare generated replies to real examples (manual review)

## TODO

- [ ] Create `config/persona.yaml`
- [ ] Create style extraction script + `config/style_examples.jsonl`
- [ ] Create `services/agent/llm_client.py` with Claude + fallback
- [ ] Create `services/agent/classifier.py` (mode + intent)
- [ ] Create `services/agent/prompt_builder.py`
- [ ] Create `services/agent/pipeline.py` (main orchestration)
- [ ] Create `services/agent/confidence.py`
- [ ] Create `services/agent/draft_queue.py` (Postgres-backed)
- [ ] Create `services/agent/matrix_sender.py`
- [ ] Create `services/agent/prompts/outward_system.md`
- [ ] Create `services/agent/prompts/inward_system.md`
- [ ] Create `config/confidence_thresholds.yaml`
- [ ] Solve style data problem: get Khanh's sent messages for few-shot examples
- [ ] Wire agent service to Redis event bus
- [ ] Write unit + integration tests

## Success Criteria

1. Outward mode generates reply to a test message that matches Khanh's style (human eval)
2. Inward mode answers "what's my sprint status?" with accurate data from memory
3. Low-confidence replies land in draft queue (not auto-sent)
4. High-confidence replies in graduated spaces auto-send via Matrix
5. Agent never fabricates a commitment or claims unrecorded experience
6. End-to-end latency (message → reply/draft) <5 seconds

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Twin sounds robotic / off-brand | High | High | Extensive style tuning, start with draft-only mode, iterate |
| Hallucinated commitments | Medium | Critical | Hard rules in prompt, RAG grounding required, "let me check" fallback |
| Claude API latency spikes | Medium | Medium | Gemini fallback, async processing, user sees "typing..." indicator |
| Khanh's sent messages unavailable for style | High | High | Manual export, or modify listener to capture own messages separately |
| Confidence scoring too conservative | Medium | Low | Better than too aggressive; tune thresholds down after observation |

## Security Considerations

- Claude/Gemini API keys in `.env` (gitignored)
- Outward mode sends messages AS the user — must never be triggered accidentally
- Draft queue requires authentication to approve/reject
- All outward actions logged in episodic store (audit trail)
- Persona YAML must not contain credentials or private info beyond work identity
- Rate limit outward replies: max 5 auto-replies per minute per space
