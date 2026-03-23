# jira-cli Reference Guide
**ankitpokhrel/jira-cli — Feature-rich interactive Jira CLI**

GitHub: https://github.com/ankitpokhrel/jira-cli

---

## Installation

### Package Managers
- **macOS (Homebrew)**: `brew tap ankitpokhrel/jira-cli && brew install jira-cli`
- **Windows (Scoop)**: `scoop bucket add extras && scoop install jira-cli`
- **Linux (Nix, FreeBSD pkgsrc)**: Native package support available
- **Go (v1.16+)**: `go install github.com/ankitpokhrel/jira-cli/cmd/jira@latest`
- **Docker**: `docker run -it --rm ghcr.io/ankitpokhrel/jira-cli:latest`

---

## Authentication Setup

### Initial Configuration
```bash
jira init
```
Generates `~/.jira/config.yml` with Jira instance details.

### Cloud Server
1. Generate API token from Atlassian profile
2. Export: `export JIRA_API_TOKEN="your-token"`
3. Run `jira init`, select "Cloud"
4. Provide instance URL and user email

### On-Premise Server
1. **Basic Auth**: Export password as `JIRA_API_TOKEN`
2. **Personal Access Token**: Export token as `JIRA_API_TOKEN`, set `JIRA_AUTH_TYPE=bearer`
3. Run `jira init`, select "Local"
4. Choose auth method (basic/mTLS)

### Alternative Auth Methods
- `.netrc` file with Jira credentials
- System keychain storage
- Multiple config files via `-c/--config` flag or `JIRA_CONFIG_FILE` env var

---

## Core Commands

### Issues

```bash
jira issue list [FLAGS]              # List/search issues (interactive TUI)
jira issue view ISSUE-KEY            # Display issue details
jira issue create                    # Create new issue (interactive)
jira issue edit ISSUE-KEY            # Modify issue
jira issue assign ISSUE-KEY USER     # Assign to user
jira issue move ISSUE-KEY [STATE]    # Transition issue (workflow state)
jira issue comment ISSUE-KEY         # Add comment
jira issue delete ISSUE-KEY          # Delete issue
jira issue link/unlink               # Create/remove relationships
jira issue clone ISSUE-KEY           # Duplicate issue
jira issue worklog ISSUE-KEY         # Track time spent
```

### Sprints

```bash
jira sprint list [FLAGS]             # List sprints (explorer/table view)
jira sprint list --current [FLAGS]   # Issues in active sprint
jira sprint list --prev [FLAGS]      # Issues in previous sprint
jira sprint list --next [FLAGS]      # Issues in next sprint
jira sprint list SPRINT_ID [FLAGS]   # Issues in specific sprint
jira sprint list --state STATE       # Filter by state (future,active,closed)
jira sprint add SPRINT_ID ISSUE...   # Add issues to sprint (up to 50)
```

### Boards & Epics

```bash
jira board list [FLAGS]              # List boards in project
jira epic list [FLAGS]               # List epics
jira epic create                     # Create epic
jira epic add EPIC_KEY ISSUE...      # Add issues to epic
jira epic remove EPIC_KEY ISSUE...   # Remove issues from epic
```

### Utilities

```bash
jira me                              # Show current user details
jira project list                    # List all projects
jira user list                       # List organization users
jira version PROJ_KEY                # Show project versions
```

---

## Issue/Sprint Filter Flags

**POSIX-compliant, combinable in any order:**

| Flag | Purpose | Example |
|------|---------|---------|
| `-s` | Status | `-s"To Do"`, `-s"In Progress"` |
| `-a` | Assignee | `-a$(jira me)`, `-a"john.doe"` |
| `-y` | Priority | `-yHigh`, `-yMedium`, `-yLow` |
| `-t` | Type | `-tBug`, `-tStory`, `-tTask` |
| `-r` | Reporter | `-r"jane.doe"` |
| `-l` | Labels | `-lbackend`, `-lUI,frontend` |
| `-C` | Components | `-C"Core API"` |
| `-R` | Resolution | `-RFixed`, `-RWontFix` |
| `--created` | Date range | `--created month`, `--created -1h` |
| `--updated` | Update date | `--updated week`, `--updated -30m` |
| `-w` | Watching | Shows issues you're watching |
| `-q` | JQL Query | `-q"priority=High AND status='To Do'"` |
| `--order-by` | Sort field | `--order-by rank`, `--order-by created` |
| `--reverse` | Reverse sort | `--order-by rank --reverse` |

**Date Syntax:** Relative (`-1h`, `-30m`, `month`, `week`) or absolute (`2024-01-15`).

---

## Output Formats

```bash
jira issue list              # Default: Interactive TUI
jira issue list --plain      # Plain text mode
jira issue list --raw        # Raw JSON output
jira issue list --csv        # CSV format
jira sprint list --table     # Table view (sprints)
```

---

## Common Examples

```bash
# Issues assigned to you
jira issue list -a$(jira me)

# High priority To-Do items created this month
jira issue list -yHigh -s"To Do" --created month

# Bugs in backend component
jira issue list -tBug -C"Backend"

# Current sprint issues assigned to you
jira sprint list --current -a$(jira me)

# High priority issues in sprint, ordered by rank
jira sprint list SPRINT_ID -yHigh --order-by rank --reverse

# Export current sprint to JSON
jira sprint list --current --raw > sprint.json

# Epics with specific label
jira epic list -lmilestone --table
```

---

## Interactive Navigation

- `j/k` or ↑↓ — Move up/down
- `h/l` or ←→ — Move left/right
- `g`/`G` — Top/bottom
- `v` — View issue details
- `m` — Transition issue (move)
- `Enter` — Open in browser
- `q`/`ESC` — Quit

---

## Key Characteristics

- **No fixed board requirement**: Uses configured board from config; `-p/--project` doesn't override board
- **Default view limit**: Shows ~25 recent sprints when listing
- **Config-driven**: Single config file with multiple project support via `-c` flag
- **Environment variables**: `JIRA_API_TOKEN`, `JIRA_AUTH_TYPE`, `JIRA_CONFIG_FILE`

---

## Sources
- [ankitpokhrel/jira-cli GitHub](https://github.com/ankitpokhrel/jira-cli)
- [Installation Guide](https://github.com/ankitpokhrel/jira-cli/wiki/Installation)
- [README Command Reference](https://github.com/ankitpokhrel/jira-cli/blob/main/README.md)
