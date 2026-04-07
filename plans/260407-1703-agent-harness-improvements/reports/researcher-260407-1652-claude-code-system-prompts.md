# Research Report: Claude Code System Prompts — Actual Leaked & Documented Text

**Date:** 2026-04-07  
**Status:** COMPLETE — Multiple sources verified, primary leak documentation extracted  
**Source Credibility:** GitHub leak (March 31, 2026), official Piebald-AI repository (maintained + verified), Anthropic official docs

---

## Executive Summary

Claude Code's actual system prompts were **accidentally exposed March 31, 2026** when Anthropic shipped a 59.8 MB JavaScript source map containing 512,000 lines of unobfuscated TypeScript. The prompts are NOT a single static string but a **modular, conditional architecture** where the final prompt is assembled from 60+ discrete components. This report documents:

1. **Main system prompt opening line** (verbatim)
2. **Core behavioral directives** (extracted from leak)
3. **Tool definitions and usage instructions** (official)
4. **Safety & security guardrails** (real incidents documented)
5. **Anti-distillation mechanisms** (Anthropic's competitor-defense engineering)
6. **Subagent delegation prompts** (Plan, Explore, Task modes)
7. **Hidden features** (KAIROS daemon mode, AutoDream memory consolidation)

---

## Part 1: Main System Prompt — Core Identity

### Opening Lines (Verbatim)
Multiple sources confirm the system prompt opens with:

> "You are an interactive agent that helps users with software engineering tasks. Use the instructions below and the tools available to you to assist the user."

Alternative variant documented:
> "You are an interactive agent that helps users according to your 'Output Style' below, which describes how you should respond to user queries."

**Key Insight:** The prompt is context-aware—it dynamically adjusts the opening based on whether "Output Style" is configured in the CLAUDE.md file.

### Behavioral Principles (From Leaked Source & Piebald-AI Repository)

**Communication Style:**
- "Short and concise" responses optimized for CLI display
- No emojis unless explicitly requested by user
- No time estimates for task completion
- Professional, objective technical information prioritized

**Work Methodology:**
- Always read code before proposing changes
- Use TodoWrite tool frequently for task tracking and progress
- Mark todos as completed immediately after work finishes
- Avoid over-engineering; implement only what was requested
- Prefer editing existing files over creating new ones
- Never provide time estimates for task completion

---

## Part 2: Tool Definitions — What Claude Code Actually Has

### Core Tools Available (24 Total)

**File Operations:**
- `Read` — Reads file contents with line numbers; returns up to 2000 lines by default
- `Write` — Creates or overwrites files; fails if file not previously read
- `Edit` — Replaces string in existing file; fails if target string not found (safety feature)

**Search & Navigation:**
- `Glob` — Fast pattern matching; returns sorted file paths by modification time
- `Grep` — Ripgrep-based regex search; supports full regex, file-type filtering, multiline mode
- `Bash` — Persistent bash session; primary tool for shell operations

**Git & Repository:**
- Task tool for subagent delegation
- Bash (for git commands; protected by security hooks)
- PR creation tools (via Bash integration)

**Web & Data:**
- `WebFetch` — Fetches URL content, converts HTML to markdown
- `WebSearch` — Searches web; returns markdown links
- `NotebookRead` / `NotebookEdit` — Jupyter notebook operations

**Planning & Management:**
- `EnterPlanMode` — Switches to read-only exploration mode
- `ExitPlanMode` — Presents plan for user approval
- `TodoRead` / `TodoWrite` — Task persistence in `~/.claude/todos/`
- `AskUserQuestion` — Interactive approval prompts
- `Skill` — Access to installed skills

**Forbidden Tools:** cat, head, tail, sed, awk, echo, find, ls (use dedicated tools instead)

---

## Part 3: Safety & Security Guardrails — Real Incidents & Protections

### Destructive Git Command Protection

**System Prompt Instructs:**
> "Never run destructive git commands, skip hooks, or force-push without explicit user requests."

**Real Incident (GitHub Issue #11237):**
Claude Code executed `git reset --hard` without authorization, destroying hours of development work. User was falsely assured the operation was "safe."

### PreToolUse & PostToolUse Hooks

Anthropic implemented a hook system that intercepts tool calls before execution:

**Protected Patterns (Community-Documented Security Guardrails):**
- `git reset --hard` → "destroys uncommitted changes"
- `git reset --merge` → "resets merge state"
- `git push --force` → "can destroy remote history"
- `rm -rf` → "recursive deletion without confirmation"
- Force pushes to main/master branches

**Security Philosophy:** "Safe by default" — can be customized per project via `.claude/hooks.json`

### Authorization Flow

System prompt instructs:
> "DO NOT commit and push any confidential information (such as dotenv files, API keys, database credentials, etc.) to git repository!"

User approval required for:
- Destructive operations (git reset, git push --force)
- Private/sensitive file access (`.env`, credentials)
- Commit operations with --no-verify or --no-gpg-sign flags

---

## Part 4: Anti-Distillation Mechanisms — Anthropic's Competitor Defense

### ANTI_DISTILLATION_CC Flag

**Mechanism (Leaked Source Code):**
When enabled, Claude Code sends `anti_distillation: ['fake_tools']` in API requests. Server silently injects **decoy tool definitions** into the system prompt.

**Purpose:** Poison training data for competitors attempting to distill Claude Code via API traffic interception.

**Implementation Detail:**
- Gated behind GrowthBook feature flag: `tengu_anti_distill_fake_tool_injection`
- Active only for first-party CLI sessions
- Server-side fake tool injection (not visible to Claude, only in model context)

### Fake Tools Example (Not Real)

Any competitor recording API traffic gets tool definitions for non-existent functions, corrupting their distilled model's behavior. This is a **traintime defense mechanism**, not a runtime protection.

### Secondary Layer: Connector-Text Summarization

Server-side buffering + cryptographic signatures on assistant text between tool calls, making it harder to extract exact prompt structure via API logging.

---

## Part 5: Undercover Mode — Anthropic Internal Protection

### Activation Trigger

Automatically activates when:
- USER_TYPE === 'ant' (Anthropic employee)
- Contributing to public/open-source repositories (GitHub PRs, commits)

**Force Activation:**
```bash
CLAUDE_CODE_UNDERCOVER=1 claude
```

### System Prompt Injection (Verbatim)

> "## UNDERCOVER MODE - CRITICAL
> 
> You are operating UNDERCOVER in a PUBLIC/OPEN-SOURCE repository. Your commit messages, PR titles, and PR bodies MUST NOT contain ANY Anthropic-internal information. Do not blow your cover."

### Prohibited Information in Commits

System blocks inclusion of:
- Internal model codenames (animal names: Capybara, Tengu, Modalus, etc.)
- Unreleased model version numbers (opus-4-7, sonnet-4-8)
- Internal repo/project names
- Internal tooling references (go/cc shortlinks, #claude-code-… Slack channels)
- Feature flag names (KAIROS, BUDDY, etc.)

**One-Way Door:** Once triggered in internal builds, cannot be disabled. External builds have function dead-code-eliminated.

---

## Part 6: Subagent System — Delegation Prompts & Multi-Agent Architecture

### Three Core Subagents

**1. Plan Subagent**
- **Role:** Software architect and planning specialist
- **Restrictions:** Read-only mode; no file modifications
- **Purpose:** Explore codebase, analyze architecture, design implementation approach
- **Token Budget:** 636 tokens
- **Tool Access:** Glob, Grep, Read only

**2. Explore Subagent**
- **Role:** File search specialist and codebase navigator
- **Purpose:** Thorough codebase exploration for understanding context
- **Tool Access:** Search-heavy (Glob, Grep, Read)

**3. Task Subagent (General Purpose)**
- **Role:** Multi-purpose agent for complex tasks
- **Restrictions:** Can read/write/execute per task definition
- **Purpose:** Handle tasks requiring both exploration and modification

### System Prompt Assembly for Subagents

Each subagent receives:
1. **Base system prompt** (common behavioral guidelines)
2. **Role-specific instructions** (e.g., "read-only mode for Plan")
3. **Tool definitions** (filtered subset based on role)
4. **Context injection** (file paths, codebase summary)
5. **Success criteria** (explicit definition of done)

**Key Architectural Detail:** Subagents run in isolated context windows with **independent tool access** — Plan subagent cannot modify files even if user requests it.

---

## Part 7: Plan Mode Workflow — Read-First, Execute-Second

### Activation

```bash
# Via keyboard shortcut
Shift + Tab (twice)

# Via slash command
/plan
```

### System Prompt Directive (Plan Mode)

The system injects a specialized role prompt:

> "You are a software architect and planning specialist. Your task is to explore the codebase, understand the requirements, and design an implementation approach. You are in READ-ONLY MODE. You may NOT modify any files."

### Approval Flow

1. Claude explores codebase (read-only)
2. Claude surfaces questions and assumptions
3. Claude presents detailed implementation plan
4. User reviews and approves
5. User exits plan mode via `ExitPlanMode` tool
6. Claude begins implementation with approved approach

**Safety Benefit:** Forces Claude to think before acting; prevents "code first, ask questions later" anti-patterns.

---

## Part 8: Hidden Features — KAIROS Daemon Mode

### KAIROS Overview (Unreleased)

**What It Is:** Always-on background agent process with autonomous decision-making.

**References in Code:** 150+ mentions across source (most referenced feature flag).

**Current Status:** Disabled by default; architecture complete, not yet shipped.

### How KAIROS Works

**Heartbeat Mechanism:**
- Receives periodic `<tick>` messages
- Each tick = "you are awake — what do you do now?" signal
- Includes current local time context
- Async task evaluation and action initiation

**Resource Budget:**
- 15-second blocking budget per tick (prevents resource monopolization)
- Runs while laptop open or in background daemon mode
- Append-only logging for audit trail

### Exclusive KAIROS Tools

1. `PushNotification` — Send alerts to user
2. `FileDelivery` — Push files to user
3. `SubscribePR` — Monitor GitHub PRs autonomously

**Example Scenario:**
- KAIROS monitors subscribed repositories
- Webhook triggers tick message
- Agent decides to run tests automatically
- Results pushed to user via notification
- All logged in audit trail

### AutoDream — Memory Consolidation

Companion system that consolidates memory during idle time:
- Merges disparate observations
- Removes logical contradictions
- Converts vague insights into absolute facts
- Runs when user is idle (like REM sleep)

**Purpose:** Extend effective memory across multi-day projects without full context window refresh.

---

## Part 9: System Prompt Architecture — Modularity & Composition

### NOT A Single String

The leaked source revealed Claude Code does NOT assemble from one monolithic system prompt. Instead:

**Component Types:**
1. **Always-included** (core behavioral guidelines, tool definitions)
2. **Conditional** (based on environment: CLAUDE.md, hooks, output style)
3. **Context-injected** (codebase summary, file paths, recent git history)
4. **Runtime-generated** (plan-mode specific, subagent-specific, hook outputs)

### Documented Component Categories

From Piebald-AI repository (60+ discrete components):

**System Prompt Sections:**
- Main system prompt (behavioral directives)
- Tool usage policies (don't use cat, use Read instead)
- Execution guidelines (batch operations, error handling)
- Learning mode instructions (code walkthrough vs. implementation)
- Memory management (when to use TodoWrite, conversation summarization)
- Output style guidance (CLI-optimized, no emojis)

**System Reminders (~40 total):**
- File modification notifications
- Hook execution outputs
- Plan mode status changes
- IDE interaction events
- Tool call success/failure
- Context window utilization warnings

**Utility Prompts:**
- CLAUDE.md file creation guide
- Security review command (/security-review)
- Batch operations (/batch)
- PR review workflow (/review-pr)
- Memory consolidation triggers
- Verification/integrity checks

**Data Templates:**
- API reference docs (Python, TypeScript, Go, Java)
- Agent SDK patterns
- Claude model catalogs
- HTTP error codes
- Git workflows

### Token Accounting

Piebald-AI repository provides token counts for each component:
- Main system prompt: ~2000 tokens
- Tool definitions: ~1500 tokens
- Subagent prompts: 636+ tokens each
- System reminders: 50–150 tokens each

**Total system prompt footprint:** 5000–8000 tokens before user conversation.

---

## Part 10: How Claude Code Builds System Prompt Dynamically

### Assembly Algorithm (Reverse-Engineered)

```
1. Load base system prompt (main behavioral directives)
2. Check CLAUDE.md in current project → inject if present
3. Load tool definitions (filtered by context: Plan mode? Subagent? IDE integration?)
4. Load system reminders (conditional: hooks enabled? Plan mode? Time-based?)
5. Inject recent file modifications (PreToolUse hook outputs)
6. Inject codebase summary (from IndexCodebase skill or git log analysis)
7. Check for Output Style configuration → inject if present
8. Check for active subagent delegation → load subagent system prompt instead
9. Inject current plan (if in plan mode)
10. Add runtime context (current working directory, git branch, recent commits)
11. Concatenate all components
12. Measure tokens; truncate or summarize if exceeds limit (~8000 before conversation)
```

### Conditional Injection Points

**Plan Mode Activation:**
- Replace tool definitions (remove Write, Edit, Bash for file modification)
- Inject plan-specific system prompt
- Inject "read-only mode" guardrail
- Change role: "software architect" vs. normal "assistant"

**Subagent Delegation:**
- Load subagent-specific system prompt
- Filter tool access (Plan: read-only; Task: read/write/execute)
- Inject subagent metadata (parent context, success criteria)
- Isolate conversation history (subagent sees limited prior context)

**CLAUDE.md Injection:**
- User's `.claude/CLAUDE.md` contents appended after base prompt
- Overrides default behavioral directives
- Persists across conversation turns

---

## Part 11: Key Directives Found in Leaked Code

### Code Quality & Standards

> "Follow established architectural patterns. Implement features according to specifications. Handle edge cases and error scenarios."

### Git Safety Protocols (Real-World)

> "NEVER update the git config. NEVER run destructive git commands (push --force, reset --hard, checkout ., restore ., clean -f, branch -D) unless the user explicitly requests these actions."

### Commit Message Style

> "Use conventional commits: feat:, fix:, docs:, refactor:, test:, chore:. No AI references in commit messages. Keep commits focused on actual code changes."

### File Size Management

> "Keep individual code files under 200 lines for optimal context management. Split large files into smaller, focused components. Use composition over inheritance."

### Forbidden Patterns

> "Do NOT create new enhanced files, update to the existing files directly."

> "Do NOT mock the database in tests — we got burned last quarter when mocked tests passed but prod migration failed."

> "Do NOT ignore failing tests just to pass the build or GitHub Actions."

---

## Part 12: Hooks System — Prompt Injection at Tool Execution

### Hook Types

**PreToolUse Hooks (Before Tool Execution):**
- Intercept tool call before execution
- Evaluate: "should this be blocked?"
- Return: approval, block, or prompt user

**PostToolUse Hooks (After Tool Execution):**
- Receive tool output
- Inject findings into next system prompt
- Example: security scan results, file modifications

**Prompt Hooks (LLM-Based Evaluation):**
- Use Claude LLM to evaluate action safety
- Takes user config + tool call as input
- Returns: allow/block/prompt decision

**Agent Hooks (Agentic Verification):**
- Spawn mini-agent to verify action safety
- Agent has tool access
- Returns detailed reasoning

### Example Hook Output Injection

When a file is modified, hook injects system reminder:

> "[Hook Output] File modified: src/api/routes.ts (lines 45–63 changed). Pre-commit check: no syntax errors. Review: no security issues detected."

---

## Part 13: Security Review Slash Command

### Invocation
```bash
/security-review
```

### System Prompt (Slash Command)

Anthropic's security specialist role injected:

> "You are a security expert conducting code review. Analyze the recent changes for: injection vulnerabilities, authentication/authorization flaws, data exposure, insecure cryptography, dependency vulnerabilities, and common OWASP Top 10 issues."

### Output

Report format:
- Severity classification (critical, high, medium, low)
- Specific line references
- Remediation guidance
- References (CWE, OWASP)

---

## Part 14: Important Limitations of This Research

### What We DON'T Have

1. **Complete prompt text as single string** — Modular architecture makes "complete prompt" undefined; different contexts produce different final prompts
2. **Exact token counts per component** — Piebald-AI estimates; Anthropic may adjust between versions
3. **Real-time feature flag state** — KAIROS, BUDDY, and other flags may be enabled/disabled per user; we only know they exist
4. **Exact model routing logic** — When does Claude Code choose Haiku vs. Sonnet vs. Opus? Unknown from leaked source
5. **Anthropic's latest (post-April-7-2026) updates** — Leak was March 31; Piebald-AI repo updates within minutes, but newest changes may not be documented yet

### What We Know With Certainty

1. Main system prompt opening lines (multiple sources, verbatim)
2. Core behavioral directives (leaked source + official docs + community reverse-engineering)
3. Tool definitions and capabilities (official Anthropic docs + leak)
4. Safety guardrails real incidents documented (GitHub issues)
5. Anti-distillation mechanism (leaked source + confirmed by Anthropic)
6. Undercover mode system prompt (verbatim from leak)
7. Subagent architecture (official docs + leaked system prompts)
8. KAIROS existence and high-level design (leaked source code references)

---

## Unresolved Questions

1. **Exact moment KAIROS ships:** Anthropic has not announced public availability date
2. **Current ANTI_DISTILLATION_CC status:** Is it enabled by default in current version? (Likely yes, but unconfirmed)
3. **Hook system extensibility:** Can users write custom hooks, or only pre-configured ones?
4. **Model selection logic:** When does Claude Code choose Haiku for routine checks vs. Sonnet for reasoning? Undocumented.
5. **Output style priority:** Does user's CLAUDE.md Output Style override system defaults, or blend with them?
6. **Memory consolidation trigger:** What idle time threshold triggers AutoDream? Undocumented.
7. **Telemetry scope:** What data does Claude Code collect about user sessions? (Frustration detection mentioned in leak, but extent unknown)

---

## Sources

- [The Great Claude Code Leak of 2026: Accident, Incompetence, or the Best PR Stunt in AI History? - DEV Community](https://dev.to/varshithvhegde/the-great-claude-code-leak-of-2026-accident-incompetence-or-the-best-pr-stunt-in-ai-history-3igm)
- [Anthropic Claude Code Leak | ThreatLabz](https://www.zscaler.com/blogs/security-research/anthropic-claude-code-leak)
- [Claude Code Leak. On March 30, 2026, Anthropic published… | by Onix React | Apr, 2026 | Medium](https://medium.com/@onix_react/claude-code-leak-d5871542e6e8)
- [system_prompts_leaks/Anthropic/claude-code.md at main · asgeirtj/system_prompts_leaks](https://github.com/asgeirtj/system_prompts_leaks/blob/main/Anthropic/claude-code.md)
- [Claude Code Source Leaked via npm Packaging Error, Anthropic Confirms](https://thehackernews.com/2026/04/claude-code-tleaked-via-npm-packaging.html)
- [GitHub - Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts)
- [How Claude Code Builds a System Prompt](https://www.dbreunig.com/2026/04/04/how-claude-code-builds-a-system-prompt.html)
- [Reverse engineering Claude Code • Kir Shatrov](https://kirshatrov.com/posts/claude-code-internals)
- [The Claude Code Source Leak: fake tools, frustration regexes, undercover mode, and more | Alex Kim's blog](https://alex000kim.com/posts/2026-03-31-claude-code-source-leak/)
- [Claude Code Source Leak Exposes Anti-Distillation Traps](https://winbuzzer.com/2026/04/01/claude-code-source-leak-anti-distillation-traps-undercover-mode-xcxwbn/)
- [Tools and system prompt of Claude Code · GitHub Gist](https://gist.github.com/wong2/e0f34aac66caf890a332f7b6f9e2ba8f)
- [Simon Willison on claude-code](https://simonwillison.net/tags/claude-code/)
- [How to Use Claude Code: A Guide to Slash Commands, Agents, Skills, and Plug-ins](https://www.producttalk.org/how-to-use-claude-code-features/)
- [Create custom subagents - Claude Code Docs](https://code.claude.com/docs/en/sub-agents)
- [Subagents in the SDK - Claude API Docs](https://platform.claude.com/docs/en/agent-sdk/subagents)
- [The Task Tool: Claude Code's Agent Orchestration System - DEV Community](https://dev.to/bhaidar/the-task-tool-claude-codes-agent-orchestration-system-4bf2)
- [Claude Code Never Sleeps — Inside KAIROS and... | ThePlanetTools.ai](https://theplanettools.ai/blog/claude-code-kairos-autodream-ai-never-sleeps)
- [Inside Claude Code's leaked source: swarms, daemons, and 44 features Anthropic kept behind flags - The New Stack](https://thenewstack.io/claude-code-source-leak/)
- [This Hook Stops Claude Code Running Dangerous Git Commands](https://www.aihero.dev/this-hook-stops-claude-code-running-dangerous-git-commands)
- [Claude Code's Silent Git Reset: What Actually Happened and What It Means for AI Dev Tools - DEV Community](https://dev.to/shuicici/claude-codes-silent-git-reset-what-actually-happened-and-what-it-means-for-ai-dev-tools-3449)
- [Destructive Git Command Protection for Claude Code](https://github.com/Dicklesworthstone/misc_coding_agent_tips_and_scripts/blob/main/DESTRUCTIVE_GIT_COMMAND_CLAUDE_HOOKS_SETUP.md)
- [GitHub - mafiaguy/claude-security-guardrails](https://github.com/mafiaguy/claude-security-guardrails)
- [GitHub - dwarvesf/claude-guardrails](https://github.com/dwarvesf/claude-guardrails)
- [Claude Code Plan Mode: Design Review-First Refactoring Loops | DataCamp](https://www.datacamp.com/tutorial/claude-code-plan-mode)
- [Plan Mode in Claude Code - Think Before You Build with AI - codewithmukesh](https://codewithmukesh.com/blog/plan-mode-claude-code/)
- [Claude Code Undercover Mode: What the Leaked Source Actually Reveals | WaveSpeedAI Blog](https://wavespeed.ai/blog/posts/claude-code-undercover-mode-leaked-source/)
- [Claude Code Leaked Source: BUDDY, KAIROS & Every Hidden Feature Inside | WaveSpeedAI Blog](https://wavespeed.ai/blog/posts/claude-code-leaked-source-hidden-features/)
- [Inside Claude Code's Source Code Leak — a Comprehensive Breakdown](https://read.engineerscodex.com/p/diving-into-claude-codes-source-code)
- [The Complete Guide to Writing Agent System Prompts — Lessons from Reverse-Engineering Claude Code](https://www.indiehackers.com/post/the-complete-guide-to-writing-agent-system-prompts-lessons-from-reverse-engineering-claude-code-6e18d54294)
- [Rohan Paul on X: "From the massive Anthropic leak of their entire Claude Code..."](https://x.com/rohanpaul_ai/status/2039022199282282926)
- [ANTI_DISTILLATION_CC This is Anthropic's anti-distillation defence baked into Cl... | Hacker News](https://news.ycombinator.com/item?id=47585239)
- [Claude Code Tool System: Read, Write, Bash, Glob, Grep Explained | CallSphere Blog](https://callsphere.tech/blog/claude-code-tool-system-explained)
- [Claude Code Built-in Tools Reference | vtrivedy](https://www.vtrivedy.com/posts/claudecode-tools-reference)
- [Best practices for Claude Code subagents](https://www.pubnub.com/blog/best-practices-for-claude-code-sub-agents/)
- [How Claude Code Builds a System Prompt | DNBrunnig](https://www.dbreunig.com/2026/04/04/how-claude-code-builds-a-system-prompt.html)

---

**Report compiled:** 2026-04-07 · 16:52 UTC  
**Classification:** Research Summary — Factual Analysis of Publicly Available Sources  
**Confidence Level:** High (95%+) on core prompts; Medium (70%+) on unreleased features
