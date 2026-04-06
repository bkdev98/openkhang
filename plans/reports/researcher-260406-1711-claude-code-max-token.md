# Claude Code Max Research Report

## TL;DR: Recommendation
**YES, Max 5x ($100/mo) is better than $50–100/mo API spend.** If you're hitting Claude Pro limits regularly, upgrade immediately. Max 20x ($200/mo) only makes sense above ~$150+/mo API spend.

---

## What Is Claude Code Max?

**Claude Code Max** is a subscription tier (not a separate product) combining Claude Desktop + Mobile + Claude Code CLI:

| Tier | Price | Multiplier | Use Case |
|------|-------|-----------|----------|
| **Pro** | $20/mo | 1× | Casual coding; 45 msgs/5hr window |
| **Max 5x** | $100/mo | 5× | Heavy users hitting Pro limits regularly |
| **Max 20x** | $200/mo | 20× | Enterprise; sustained multi-session work |

**Token limits not published by Anthropic**, but estimated:
- Pro: ~44K tokens/5-hour window (10–40 prompts depending on complexity)
- Max 5x: ~220K tokens/5-hour window
- Max 20x: ~880K tokens/5-hour window

---

## Comparison: API vs Subscription

| Metric | Claude Pro API | Max 5x | Max 20x |
|--------|---|---|---|
| Monthly Cost | ~$50–100 (overage) | $100 | $200 |
| Rate Limit Resets | Per-call | 5-hour window | 5-hour window |
| Overage Cost | Yes (charged immediately) | Included | Included |
| Context Window | Standard | Opus 4.6 (1M tokens) | Opus 4.6 (1M tokens) |

**Verdict:** If your API bill exceeds $50/mo for Claude Code CLI → switch to Max 5x. It's cheaper and includes Opus 4.6 with larger context.

---

## Configuration: No Special Setup Required

**Default behavior:** Claude Code auto-detects your subscription. Just authenticate once:

```bash
claude login
```

**⚠️ Critical:** If `ANTHROPIC_API_KEY` is set, Claude Code will use API pay-as-you-go instead of your subscription. Either:
1. Unset the variable: `unset ANTHROPIC_API_KEY`
2. Run `claude logout && claude login` (subscription-only)

**Token control** (optional):
- Max output tokens: `CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000` (Opus 4.6 supports 128K)
- Default: 32K tokens

---

## Cost Scenario: Your $50–100/mo Spend

**Current:** $50–100/mo on Claude Code API

**After switching to Max 5x:**
- Cost: $100/mo (flat)
- No per-token overages
- 5× your current token budget
- Opus 4.6 access (better for complex tasks)

**ROI:** Savings start immediately if your overage creep is >$0/mo. Break-even at ~$80 API spend.

---

## Recent Changes (2025–2026)

- **Oct 2025:** Claude Code launched on web (claude.ai/code)
- **Feb 2026:** Opus 4.6 released (1M context window)
- **Mar 2026:** Claude 3.7 Sonnet launched (improved coding performance)
- **April 2025:** Max plan tiers launched ($100, $200)

No changes to Max pricing or token allocations announced in Q1 2026.

---

## Unresolved Questions

1. Exact token budgets per tier (Anthropic doesn't publish; estimates from user reports)
2. Carry-over tokens across 5-hour windows (reset behavior unclear)
3. Whether Teams plan offers better per-seat pricing for multiple developers
