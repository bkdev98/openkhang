# Code Review: Inward Mode Session History

**Scope:** 5 files, ~64 lines added  
**Focus:** Session cookie handling, history correctness, injection risks, token budget

## Overall Assessment

Clean, well-scoped change. The plumbing from cookie -> session_id -> WorkingMemory -> PromptBuilder is straightforward. A few issues worth addressing before merge.

---

## Critical Issues

### 1. No chat_history role validation — prompt injection risk

**File:** `services/agent/prompt_builder.py:70-71`

`chat_history` entries are extended directly into the messages list without validating that `role` is only `"user"` or `"assistant"`. If any entry has `role: "system"`, it injects a system prompt mid-conversation.

Currently the only caller is `twin_chat.py` which constructs entries correctly, but `process_event()` is a public API — any future caller or a corrupted WorkingMemory entry could inject arbitrary roles.

**Fix:**
```python
if chat_history:
    for turn in chat_history:
        if turn.get("role") in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": str(turn.get("content", ""))})
```

**Severity:** Critical (trust boundary — external input reaches LLM message array unchecked)

---

## High Priority

### 2. `AgentPipeline.from_env()` called per request — connection churn

**File:** `services/dashboard/twin_chat.py:51-55`

Every `ask_twin()` call creates a new `AgentPipeline`, which calls `MemoryClient(config)`, `LLMClient(...)`, `DraftQueue(...)`, `MatrixSender(...)`, then `connect()` and `close()`. This creates a new DB connection pool on every chat message.

This is a pre-existing issue, not introduced by this PR, but the session history feature increases usage frequency (multi-turn = more calls). Worth noting for a follow-up.

**Severity:** High (perf — connection pool per request under multi-turn usage)

### 3. Session cookie missing `secure` flag

**File:** `services/dashboard/app.py:339`

```python
response.set_cookie("twin_session_id", session_id, httponly=True, samesite="lax")
```

No `secure=True`. If dashboard is served over HTTPS (production), cookie transmits over HTTP too. For a local-only dashboard this is acceptable, but if ever exposed externally, session IDs leak in cleartext.

**Severity:** Medium for current use (local dev), High if deployed externally.

---

## Medium Priority

### 4. Enriched question stored in history instead of original

**File:** `services/dashboard/twin_chat.py:79`

```python
chat_history.append({"role": "user", "content": question})
```

This stores the original `question`, but the LLM saw `enriched_question` (with injected DM context). On the next turn, the history won't contain the enrichment context the LLM used when generating its reply. This is actually correct behavior — you don't want accumulated enrichment noise in history. Just noting this is an intentional design choice.

### 5. No periodic purge of WorkingMemory

`_working_memory` is a module-level singleton. Sessions expire via TTL (30min lazy eviction), but `purge_expired()` is never called proactively. Under sustained use, expired sessions accumulate in `_store` until a `get_context()` call happens to hit their key.

For a single-user dashboard this is negligible. If multi-user, add a periodic purge task.

### 6. `chat_history` passed to outward mode is silently dropped

**File:** `services/agent/pipeline.py:246`

```python
chat_history=chat_history if mode == "inward" else None,
```

If a caller passes `chat_history` for an outward event, it's silently ignored. This is fine defensively, but worth a debug log so callers know their history was dropped.

---

## Edge Cases Verified

| Case | Status |
|------|--------|
| First message (empty history) | OK — `get_context` returns `None`, `or []` handles it |
| LLM returns empty reply | OK — history not appended when `reply_text` is falsy |
| Session expired (30min idle) | OK — `get_context` returns `None`, fresh conversation starts |
| History trimming | OK — `[-20:]` slice keeps newest 10 turns |
| Cookie absent on first request | OK — generates UUID, sets cookie |
| Concurrent requests same session | OK — WorkingMemory uses threading Lock; but async calls interleave between `get_context` and `set_context` (TOCTOU) — see below |

### 7. TOCTOU on chat_history (informational)

```
Request A: get_context -> history=[t1,t2]
Request B: get_context -> history=[t1,t2]
Request A: set_context -> history=[t1,t2,t3]
Request B: set_context -> history=[t1,t2,t4]  # overwrites t3
```

Since this is a single-user dashboard and requests are sequential (user waits for response), this is not a practical concern. Just documenting the theoretical race.

---

## Positive Observations

- Token budget is reasonable: 10 turns x ~200 tokens = ~2000 tokens, well within the 4096 max_tokens output limit and model context
- WorkingMemory TTL provides natural session cleanup without needing explicit "clear" UX
- History is only injected for inward mode — outward mode is unaffected
- `httponly=True` on cookie prevents JS access
- `samesite="lax"` provides basic CSRF protection

## Recommended Actions

1. **[Must fix]** Validate `role` field in chat_history entries before injecting into messages
2. **[Should fix]** Add `secure=True` to cookie if HTTPS is used (or make it conditional on env)
3. **[Nice to have]** Log when chat_history is dropped for non-inward mode
4. **[Follow-up]** Consider caching AgentPipeline instance instead of creating per-request

---

**Status:** DONE_WITH_CONCERNS  
**Summary:** Session history implementation is correct and well-bounded. One trust boundary issue (chat_history role validation) should be fixed before merge.  
**Concerns:** Unvalidated chat_history roles could allow system prompt injection via the public `process_event()` API.
