# openkhang

Work autopilot plugin for Claude Code — integrates Google Chat, Jira, Confluence, and GitLab into autonomous workflows.

## Blocks

### Google Chat (mautrix bridge + Matrix)
- Real-time message monitoring via mautrix-googlechat bridge, AI categorize, auto-reply
- Commands: `/chat-scan`, `/chat-reply`, `/chat-spaces`
- Agent: `chat-categorizer` — classifies messages and drafts replies
- Continuous mode: `/loop 5m /chat-scan`

### Jira (`jira-cli` + `atlassian-cli`)
- Sprint board with burndown and health indicators
- Auto-prioritize tickets by urgency, blockers, dependencies
- Commands: `/sprint-board`, `/sprint-prioritize`
- Agent: `sprint-monitor` — velocity analysis and risk alerts

### Confluence (`atlassian-cli`)
- Search and read documentation pages
- Create and update pages
- Commands: `/confluence-search`, `/confluence-update`

### GitLab (`glab`)
- Full code session workflow: ticket → branch → implement → MR → pipeline
- Pipeline monitoring with auto-retry and auto-fix
- MR management (list, approve, merge)
- Commands: `/code-session`, `/pipeline-watch`, `/mr-manage`
- Agents: `pipeline-fixer` (auto-fix CI failures), `bug-investigator` (triage urgent bugs)

### Orchestrator
- Unified status dashboard: `/openkhang-status`
- Urgent ticket detection hook (auto-triggers bug investigation)
- Cross-block integration: chat → jira → code-session → pipeline

## Prerequisites

| Tool | Install | Purpose |
|------|---------|---------|
| Docker | `brew install docker` | Synapse + mautrix bridge for Google Chat |
| `jira` | `brew install ankitpokhrel/jira-cli/jira` | Jira issues/sprints |
| `atlassian-cli` | `brew install atlassian-cli` | Confluence + Jira |
| `glab` | `brew install glab` | GitLab MRs/pipelines |

## Installation

### From marketplace

```bash
/plugin marketplace add bkdev98/openkhang
/plugin install openkhang@openkhang
```

### For development

```bash
claude --plugin-dir /path/to/openkhang
```

## Quick Start

```bash
# First-time setup for each block
/chat-scan --setup        # Configure Google Chat account + learn tone
/sprint-board             # Configure Jira project + board
/confluence-search test   # Configure Confluence (auto on first use)
/code-session --project   # Configure GitLab project

# Daily workflow
/openkhang-status         # See everything at a glance
/loop 5m /chat-scan       # Start chat monitoring
/sprint-prioritize        # Plan your work order
/code-session PROJ-123    # Start coding a ticket
/pipeline-watch           # Monitor the build
```

## Configuration

All state stored in `.claude/openkhang.local.md` (auto-created, gitignored).

## Components

| Type | Count | Items |
|------|-------|-------|
| Skills (knowledge) | 4 | chat-autopilot, jira-knowledge, confluence-knowledge, gitlab-knowledge |
| Skills (commands) | 7 | chat-scan, chat-reply, chat-spaces, sprint-board, sprint-prioritize, confluence-search, confluence-update |
| Skills (gitlab) | 3 | code-session, pipeline-watch, mr-manage |
| Skills (orchestrator) | 1 | openkhang-status |
| Agents | 4 | chat-categorizer, sprint-monitor, pipeline-fixer, bug-investigator |
| Hooks | 2 | SessionStart (pending drafts), UserPromptSubmit (urgent ticket detection) |
