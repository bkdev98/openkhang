# Agent Skills Ecosystem Research Report

**Date:** 2026-04-07  
**Focus:** AgentSkills.io + Claude Code skills system + marketplace patterns  
**Scope:** Skill definition, registration, triggering, and Python agent implementation patterns

---

## Executive Summary

Agent skills are **prompt-based packaged expertise** that tell agents *how* to think about problems, distinct from **tools** which provide execution capability. The Claude Code skills ecosystem uses markdown-based SKILL.md files with YAML frontmatter for metadata and progressive disclosure (only ~100 tokens loaded initially; full instructions load on-demand). Skills are triggered via **pure LLM-based description matching**—no algorithmic routing. For Python agents, skills should focus on procedural knowledge, context, and workflow orchestration rather than simple API execution.

---

## 1. Skill Definition & Differentiation from Tools

| Aspect | Tool | Skill |
|--------|------|-------|
| **Purpose** | Execute actions (API calls, DB queries, OS commands) | Shape agent reasoning via context & instructions |
| **Complexity** | Narrow scope, deterministic input/output | Broad workflows, multi-step processes |
| **Implementation** | Structured schemas (JSON), explicit inputs/outputs | Natural language instructions (markdown) |
| **Token Cost** | High (~500+ tokens per tool in MCP) | Low (~100 tokens per skill, frontmatter only) |
| **When Correct Approach Fails** | Action execution fails (e.g., API down) | Agent misapplies knowledge (reasoning fails) |

**Key Insight:** Tools solve "execution" problems; skills solve "process & context" problems. If you model everything as tools, agents work in demos but fail in production because they lack *when* and *why* guidance.

---

## 2. Claude Code Skill Structure

### SKILL.md File Format

**Part 1: YAML Frontmatter (Metadata)**
```yaml
---
name: ck:skill-name                    # Required. Format: ck:{kebab-case}
description: "What this skill does..."  # Critical. ~50-100 words. Claude uses only this to match intent
argument-hint: "[topic]"                # Optional. Shows parameter hint in UI
metadata:
  author: author-name
  version: "1.0.0"
license: MIT                           # Optional
---
```

**Part 2: Markdown Instructions**  
Natural language workflow. Claude receives this only after skill is triggered.

### Registration & Discovery

- **No central registry.** Skills live in `~/.claude/skills/{skill-name}/SKILL.md`
- **Dynamic aggregation.** At runtime, Claude loads all available skill names + descriptions
- **Progressive disclosure:** Only frontmatter (30–50 tokens/skill) loads at inference start. Full instructions (can be 5k+ tokens) load only when skill is triggered.

### Triggering Mechanism (Description-Based Matching)

1. Claude receives aggregated list of all skill names + descriptions in its system prompt
2. **Pure LLM reasoning** matches user intent against descriptions—no algorithmic routing
3. When match occurs, Claude invokes skill: `/ck:skill-name [args]`
4. Full SKILL.md instructions load and execute

**Reliability Note:** Scott Spence's testing found ~20% success rate on 200+ prompts. Quality depends entirely on clear, specific descriptions. Ambiguous descriptions cause misactivation.

---

## 3. Skill Marketplace Patterns (Block Engineering)

Block's internal skills marketplace (100+ skills) follows these patterns:

**Organization:**
- **Curated bundles** group related skills by role/team (frontend, Android, iOS, etc.)
- **Discoverability** via metadata: author, version, license, description clarity

**Design Patterns for Workflow:**
1. **Pipeline Pattern** — Sequential workflows with hard checkpoints. Instructions define the workflow.
2. **Tool Wrapper Pattern** — Skill orchestrates multiple tools into a higher-level abstraction
3. **Generator Pattern** — Skill generates artifacts (code, docs, configs)
4. **Reviewer Pattern** — Skill validates outputs and provides feedback loops

**Sharing:**
- Skills are folders (containing SKILL.md + optional scripts/references)
- Share as ZIP, Git repo, or publish to marketplace
- Open standard (Anthropic-originated, adopted by Claude, Gemini CLI, others)

---

## 4. Best Practices for Python Agent Skills

### Don't Build
- ❌ Simple API wrappers (use tools instead)
- ❌ Single-action sequences (use tool chains)
- ❌ Generic instructions (too broad to trigger reliably)

### Do Build
- ✅ **Domain expertise packages** (e.g., "Security audit best practices")
- ✅ **Multi-step workflows** that require judgment calls
- ✅ **Context-heavy procedures** (e.g., "Code review for legacy systems")
- ✅ **Role-based reasoning** (e.g., "Senior architect refactoring decision tree")

### Implementation Structure
```
skills/
├── security-audit-pro/
│   ├── SKILL.md                    # Frontmatter + markdown instructions
│   ├── scripts/
│   │   ├── check-dependencies.py
│   │   └── audit-report.py
│   └── references/
│       ├── owasp-checklist.md
│       └── cwe-mappings.json
```

### Critical Success Factors
1. **Description clarity** — 50–100 words, action-oriented, unambiguous
2. **Workflow focus** — Guide multi-step processes, not single actions
3. **Progressive disclosure** — Reference external docs in SKILL.md, load only when needed
4. **Testability** — Include `argument-hint` so users understand what to pass

---

## 5. Skill vs. Tool Decision Matrix for Python Agents

**Choose a TOOL if:**
- Single, deterministic API call → REST endpoint, database query, shell command
- Clear input schema → Defined parameters
- Execution is the bottleneck → "Agent can't make the API call"

**Choose a SKILL if:**
- Multi-step workflow → Requires decisions at each step
- Context-dependent logic → "Should I even attempt this?" 
- Knowledge-heavy task → "How do senior engineers approach this?"
- Orchestrates other tools → "Call tool X, then conditionally call tool Y"

**Example:** 
- **Tool:** `fetch_github_repo(owner, repo)` → Returns JSON
- **Skill:** `ck:code-review-with-context` → Uses fetch_github_repo + linter + semantic analysis + produces narrative review

---

## 6. Key Takeaways for openkhang Project

1. **Skill activation is probabilistic** (~20% baseline success). Description quality matters enormously.
2. **Token efficiency matters.** Frontmatter-only loading (100 tokens) vs. 50k+ tokens for MCP schemas justifies skills for complex workflows.
3. **Progressive disclosure scales.** 100+ skills with only 10k tokens frontmatter overhead vs. impossibly large tool schemas.
4. **No "skill vs. tool" purity.** Production systems use both: tools for execution, skills for orchestration and reasoning.
5. **Standardization is young.** Marketplace patterns (Block) are internal; public ClawHub emerging but not mature ecosystem yet.

---

## Unresolved Questions

1. How should Python agent skills integrate with LangChain's tool/agent abstractions? (LangChain has its own skill concept)
2. What's the maturity timeline for ClawHub as a marketplace? (Currently accessible but adoption unclear)
3. How do skills handle authentication/secrets at scale? (SKILL.md examples are generic)
4. Best practice for skill versioning when dependencies change? (Anthropic docs are silent)

---

## Sources

- [Extend Claude with skills - Claude Code Docs](https://code.claude.com/docs/en/skills)
- [Claude Skills Explained](https://www.analyticsvidhya.com/blog/2026/03/claude-skills-custom-skills-on-claude-code/)
- [Claude Agent Skills: A First Principles Deep Dive](https://leehanchung.github.io/blogs/2025/10/26/claude-skills-deep-dive/)
- [Skills vs Tools for AI Agents: Production Guide](https://www.arcade.dev/blog/what-are-agent-skills-and-tools/)
- [Skills vs MCP tools for agents](https://www.llamaindex.ai/blog/skills-vs-mcp-tools-for-agents-when-to-use-what)
- [Agent Skills - Microsoft Learn](https://learn.microsoft.com/en-us/agent-framework/agents/skills)
- [Spring AI Agentic Patterns](https://spring.io/blog/2026/01/13/spring-ai-generic-agent-skills/)
- [GitHub - Anthropic Skills Repository](https://github.com/anthropics/skills)
- [3 Principles for Designing Agent Skills - Block Engineering](https://engineering.block.xyz/blog/3-principles-for-designing-agent-skills)
- [Agent Skills - Claude API Docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
