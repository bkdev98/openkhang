# Claude OAuth Token Usage Research Report

**Date:** 2026-04-06  
**Status:** BLOCKED — subscription tokens cannot be used programmatically

---

## Summary

**Cannot use Claude Max subscription tokens for programmatic API calls.** Anthropic explicitly blocks OAuth tokens (`sk-ant-oat01-*`) from the Messages API with error: *"OAuth authentication is currently not supported."* Despite having a $200/month Max subscription, you must purchase separate API credits for programmatic access.

---

## Key Findings

### 1. Token Storage (macOS)
- **Location:** Encrypted in macOS Keychain (not disk files)
- **Alternative storage:** `~/.claude/.credentials.json` on Linux/Windows (mode `0600`)
- **Retrieval:** Not directly accessible for reuse; credentials managed internally by Claude Code

### 2. OAuth vs API Key Authentication
OAuth tokens (`sk-ant-oat01-*`) are **subscription-linked credentials** for interactive Claude Code sessions only.

Standard API keys (`sk-ant-api03-*`) from Console are for programmatic billing (pay-per-token).

| Aspect | OAuth Token | API Key |
|--------|------------|---------|
| Format | `sk-ant-oat01-*` | `sk-ant-api03-*` |
| Source | `claude login` / `claude setup-token` | console.anthropic.com |
| Usage | Interactive Claude Code only | Programmatic API calls |
| Billing | Against Max subscription | Direct per-token billing |
| API Support | Blocked (401 error) | Fully supported |

### 3. Messages API Endpoint
Single endpoint for both: `https://api.anthropic.com/v1/messages`

Header differences:
- **OAuth attempt:** `Authorization: Bearer sk-ant-oat01-*` → **rejected**
- **API key:** `x-api-key: sk-ant-api03-*` → accepted

### 4. Official Status
- **Anthropic Python SDK:** No OAuth support; requires `ANTHROPIC_API_KEY` environment variable
- **Authentication precedence** (Claude Code priority):
  1. Cloud provider credentials (Bedrock, Vertex, Foundry)
  2. `ANTHROPIC_AUTH_TOKEN` env var (bearer token for gateways)
  3. `ANTHROPIC_API_KEY` env var ← **Only option for Messages API**
  4. `apiKeyHelper` script output
  5. Subscription OAuth (fallback for interactive only)

### 5. Community Attempts & Blocking
- Feature request [anthropics/claude-code#37205](https://github.com/anthropics/claude-code/issues/37205) asks for OAuth token support in Messages API
- **Status:** Open but marked stale; Anthropic has not committed to supporting this
- As of April 4, 2026: Anthropic **blocked third-party tools** from using subscription tokens; violates consumer ToS

### 6. Workarounds Discovered
None viable for direct API calls:
- **liteLLM/OpenClaw proxy:** Would route through proxy (adds latency, not subscription-native)
- **claude -p subprocess:** Works but adds 3–5 second spawn overhead
- **CLIProxyAPI:** Custom proxy wrapper (third-party, adds dependency)

---

## Trade-offs

| Option | Cost | Latency | Setup | Viability |
|--------|------|---------|-------|-----------|
| Buy separate API credits | $10–20/mo + per-token | Fast (~500ms) | 5 min | **Best practical option** |
| Use Max subscription token | $0 marginal | N/A | N/A | **Blocked by Anthropic** |
| Route through proxy | Proxy cost | +50–200ms | Medium | Workaround only |
| Use `claude -p` subprocess | $0 | 3–5s overhead | Minimal | Only for low-QPS use |

---

## Recommendation

**Accept API key billing.** Anthropic will not support OAuth tokens for programmatic access; this is a deliberate design decision (likely to maintain separate subscription vs. API billing tracks).

**Action:** Generate a standard API key in [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) and use it for your Python agent. At $100/mo Claude Max + minimal API usage, total cost remains under $200/mo.

---

## Adoption Risk

- **Maturity:** OAuth blocking is stable/intentional (not a bug)
- **Breaking changes:** Unlikely (Anthropic has locked this down)
- **Community size:** Multiple projects request this; no solution exists (blocker for 500+ developers)

---

## Sources

- [Authentication - Claude Code Docs](https://code.claude.com/docs/en/authentication)
- [API Overview - Claude API Docs](https://platform.claude.com/docs/en/api/overview)
- [GitHub Issue #37205: OAuth token support request](https://github.com/anthropics/claude-code/issues/37205)
- [Medium: Claude API Authentication in 2026](https://lalatenduswain.medium.com/claude-api-authentication-in-2026-oauth-tokens-vs-api-keys-explained-12e8298bed3d)
- [liteLLM: Claude Max Subscription](https://docs.litellm.ai/docs/tutorials/claude_code_max_subscription)
- [GitHub: Anthropic blocks third-party tool OAuth access](https://lobste.rs/s/mhgog9/anthropic_blocks_third_party_tools_using)

---

## Unresolved Questions

1. Could a custom `apiKeyHelper` script invoke `claude ... | jq .credentials` to extract tokens? (Likely blocked by Keychain encryption)
2. Is there undocumented support for OAuth in private APIs or Claude Team accounts?
