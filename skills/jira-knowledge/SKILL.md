---
name: jira-knowledge
description: >-
  This skill provides core knowledge for Jira integration in the openkhang plugin.
  It should be activated when any Jira-related skill or agent runs, or when
  the user asks about "jira", "sprint", "tickets", "backlog", "board",
  "burndown", "story points", or "task priority".
version: 0.1.0
---

# Jira Knowledge — Core Reference

Jira integration for sprint monitoring, task prioritization, and ticket management via CLI tools.

## CLI Tools

Two CLI tools available for Jira:

### jira-cli (ankitpokhrel)
Primary tool for issue and sprint operations.

```bash
# Auth: uses ~/.config/.jira/.config.yml
jira init  # interactive setup

# Issues
jira issue list -s "To Do" -s "In Progress" --assignee "me" --json
jira issue view PROJ-123 --json
jira issue create -t Bug -s "Title" -b "Description" -P PROJ
jira issue move PROJ-123 "In Progress"
jira issue assign PROJ-123 "user@company.com"

# Sprints
jira sprint list --board BOARD_ID --json
jira sprint list --board BOARD_ID --current --json
jira board list --json

# Search (JQL)
jira issue list --jql "sprint in openSprints() AND assignee = currentUser()" --json
```

### atlassian-cli (omar16100)
Unified Atlassian CLI (Rust binary) — also covers Confluence.

```bash
# Auth: ~/.atlassian-cli/config.toml (AES-256-GCM encrypted)
atlassian-cli auth setup

# Jira
atlassian-cli jira issue search --jql "QUERY" --json
atlassian-cli jira issue create --project PROJ --type Bug --summary "Title"
atlassian-cli jira issue transition PROJ-123 --status "Done"
```

## State File

Jira state in `.claude/openkhang.local.md`:

```yaml
jira:
  project: PROJ
  board_id: 123
  current_sprint_id: 456
  my_issues_cache:
    - key: PROJ-123
      summary: "Fix login bug"
      status: "In Progress"
      priority: "High"
      story_points: 3
  last_sprint_check: "2026-03-24T00:00:00+07:00"
```

## Priority Algorithm

Prioritize user's tickets by:
1. **Blockers first** — issues blocking others (check linked issues)
2. **Urgency** — P0/P1 before P2/P3
3. **Sprint deadline proximity** — closer to sprint end = higher
4. **Story points** — smaller tasks first (quick wins) when deadline is far
5. **Dependencies** — do prerequisites before dependents

## Additional Resources

- **`references/jira-cli-commands.md`** — Full CLI command reference
