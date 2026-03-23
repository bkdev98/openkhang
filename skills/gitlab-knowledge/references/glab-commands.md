# glab CLI Reference - GitLab Official Command-Line Tool

**Date:** 2026-03-24 | **Scope:** Installation, authentication, MR management, pipeline/CI/CD, repo operations

## Installation

```bash
# macOS (Homebrew)
brew install glab

# Linux
# See: https://docs.gitlab.com/cli/ for distro-specific instructions

# Verify installation
glab version
```

## Authentication

### Quick Setup
```bash
glab auth login                              # Interactive (auto-detects remotes)
glab auth login --hostname gitlab.example.org  # Specify GitLab instance
glab auth login --token glpat-xxx           # Token-based (non-interactive)
glab auth login --stdin < token.txt         # Read token from stdin
glab auth login --web                       # OAuth/web-based login
glab auth login --use-keyring               # Store token in OS keyring
```

### Token Requirements
- Minimum scopes: `api`, `write_repository`
- Env var precedence: `GITLAB_TOKEN` → `GITLAB_ACCESS_TOKEN` → `OAUTH_TOKEN`
- Config storage: `~/.config/glab-cli/config.yml`

---

## Merge Requests (MR)

### Create MR
```bash
glab mr create
glab mr create -t "Fix bug" -d "Description"
glab mr create -f --draft --label RFC         # Auto-fill + draft
glab mr create -s source-branch -b main       # Explicit branches
glab mr create -a user1 --reviewer user2      # Assign & request review
glab mr create --push --fill --web            # Push + create + open browser
glab mr create --remove-source-branch --squash-before-merge
```

**Key Flags:**
- `-t, --title` - MR title
- `-d, --description` - Description (use "-" for editor)
- `-s, --source-branch` - Source branch
- `-b, --target-branch` - Target/base branch
- `-a, --assignee` - Assign users (repeatable)
- `--reviewer` - Request review (repeatable)
- `-l, --label` - Add labels (repeatable)
- `-f, --fill` - Auto-populate from commits
- `--draft, --wip` - Mark as draft
- `--auto-merge` - Merge when checks pass
- `--squash-before-merge` - Squash commits
- `--remove-source-branch` - Delete branch after merge
- `-y, --yes` - Skip confirmation

### List MRs
```bash
glab mr list
glab mr list --all --merged --order updated_at --sort desc
glab mr list --assignee me --label bug
glab mr list --source-branch feature-* --created-after 2026-03-01
glab mr list --search "keyword" --output json | jq .
```

**Filter Flags:**
- `--all/-A` - All MRs (default: open only)
- `--closed/-c` - Closed only
- `--merged/-M` - Merged only
- `--draft/-d` - Draft MRs
- `--assignee/-a` - By assignee
- `--reviewer/-r` - By reviewer
- `--author` - By creator
- `--label/-l` - By label
- `--source-branch/-s` - Source branch filter
- `--target-branch/-t` - Target branch filter
- `--search` - Text search (title + description)
- `--created-after/--created-before` - Date range (ISO 8601)
- `--order/-o` - Sort by: created_at, updated_at, merged_at, title, priority
- `--sort/-S` - Direction: asc/desc
- `--output/-F` - Format: text or json

### Approve MR
```bash
glab mr approve 235
glab mr approve 123 345                      # Multiple MRs
glab mr approve --sha abc123def              # Verify SHA
```

**Flags:**
- `-s, --sha` - HEAD commit SHA validation
- `-R, --repo` - Alternate repo (OWNER/REPO or GROUP/NAMESPACE/REPO)

### Merge MR
```bash
glab mr merge 235
glab mr merge --rebase --squash --remove-source-branch
glab mr merge -m "Custom message" --sha abc123
glab mr merge -y                             # Skip confirmation
```

**Flags:**
- `--auto-merge` - Enable auto-merge (default: true)
- `-r, --rebase` - Rebase onto base branch
- `-s, --squash` - Squash commits
- `--squash-message` - Custom squash message
- `-d, --remove-source-branch` - Delete source branch
- `-m, --message` - Custom merge commit message
- `--sha` - Only merge if HEAD matches SHA
- `-y, --yes` - Skip confirmation

---

## Pipelines & CI/CD

### View Pipeline (Interactive)
```bash
glab ci view                                 # Current branch
glab ci view main                            # Specific branch
glab ci view -b main                         # Explicit branch flag
glab ci view -p 12345                        # Specific pipeline ID
glab ci view -w                              # Open in browser
glab ci view -R owner/repo                   # Alternate repository
```

**Interactive Controls:**
- `↑↓ / j k` - Navigate jobs
- `Enter` - Toggle job logs or show child pipeline
- `Ctrl+R / Ctrl+P` - Run/retry job
- `Ctrl+D` - Cancel job
- `Ctrl+Q` - Exit view
- `Ctrl+Space` - Suspend & view logs
- `Esc / q` - Close logs

**Flags:**
- `-b, --branch STRING` - Branch or tag
- `-p, --pipelineid INT` - Pipeline ID
- `-w, --web` - Open in browser
- `-R, --repo OWNER/REPO` - Alternate repo

### List Pipelines
```bash
glab pipeline list
glab pipeline list --status success
glab pipeline list --order updated_at --sort desc
glab pipeline list --output json | jq '.[] | .id'
```

### Trigger Pipeline
```bash
glab pipeline run
glab pipeline run -b main                    # Specific branch
glab pipeline run --variables KEY1:val1 --variables KEY2:val2
```

### View/Trace Job Logs
```bash
glab ci trace                                # Interactive job selection
glab ci trace 224356863                      # By job ID
glab ci trace lint                           # By job name
glab ci trace --web                          # Open in browser
```

### Retry Job
```bash
glab ci retry 224356863                      # By ID
glab ci play job-name                        # Interactive
```

### Cancel Job
```bash
# From interactive CI view (glab ci view):
# Press Ctrl+D to cancel selected job
```

---

## Repository Operations

### Clone Repository
```bash
glab repo clone repo-name
glab repo clone namespace/repo-name
glab repo clone org/group/repo-name
glab repo clone --preserve-namespace group/  # Clone entire group
glab repo clone -g my-group --paginate       # Clone group (all pages)
glab repo clone repo -- --branch main        # Pass git flags after --
```

**Flags:**
- `-g, --group` - Clone group repositories
- `-p, --preserve-namespace` - Keep namespace in directory structure
- `-a, --archived` - Include archived repos
- `-v, --visibility` - Filter: public, internal, private
- `-m, --mine` - Only user's projects
- `--paginate` - Fetch all pages
- `-M, --with-mr-enabled` - MR feature enabled
- `-I, --with-issues-enabled` - Issues feature enabled

### View Repository
```bash
glab repo view owner/repo
glab repo view                               # Current repo (from .git/config)
```

### Browse Repository
```bash
glab repo browse owner/repo                  # Open in default browser
glab repo browse -w -b main                  # Specific branch
```

---

## Generic API Access

For custom GitLab API calls and automation:

```bash
glab api projects/:fullpath/releases
glab api issues --output json | jq .
glab api --paginate 'projects?membership=true' --output ndjson | jq 'select(.archived==false)'
glab api users/me
glab api groups/:id/projects
```

**Flags:**
- `--output json` - Pretty JSON
- `--output ndjson` - Newline-delimited JSON (streaming, memory-efficient)
- `--paginate` - Fetch all pages
- `-X, --method POST/PATCH/PUT` - HTTP method
- `-F, --field key:value` - Add parameter (infers type)
- `-H, --header` - Custom HTTP header
- `--repo OWNER/REPO` - Alternate repository context

---

## Common Automation Patterns

```bash
# List all open MRs as JSON for scripting
glab mr list --all --output json > mrs.json

# Approve all MRs assigned to me
glab mr list --assignee me --output json | jq -r '.[] | .iid' | xargs -I {} glab mr approve {}

# Retry failed pipeline jobs
glab pipeline list --status failed --output json | jq '.[0].id' | xargs -I {} glab ci view -p {}

# Clone all group repos with specific visibility
glab repo clone -g mygroup -v private --paginate

# Stream API results with jq
glab api --paginate 'projects' --output ndjson | jq 'select(.star_count > 100)'
```

---

## Key Automation Flags

| Flag | Usage | Example |
|------|-------|---------|
| `--output json` | JSON parsing | `glab mr list --output json \| jq` |
| `--output ndjson` | Stream large datasets | `glab api --paginate ... --output ndjson \| jq` |
| `-R, --repo` | Alternate repo context | `glab mr create -R owner/repo` |
| `-y, --yes` | Skip confirmations | `glab mr merge 123 -y` |
| `-w, --web` | Open in browser | `glab mr create -w` |
| `--paginate` | Fetch all pages | `glab api --paginate users` |
| `-b, --branch` | Specify branch | `glab ci view -b develop` |

---

## Configuration & Troubleshooting

```bash
glab config set editor vim
glab config get core.pager
glab auth status                             # Show authenticated instances
glab auth logout --hostname gitlab.example.org
```

---

## Sources

- [GitLab CLI Official Docs](https://docs.gitlab.com/cli/)
- [glab auth login](https://docs.gitlab.com/cli/auth/login/)
- [glab mr create](https://docs.gitlab.com/cli/mr/create/)
- [glab mr list](https://docs.gitlab.com/cli/mr/list/)
- [glab mr approve](https://docs.gitlab.com/cli/mr/approve/)
- [glab mr merge](https://docs.gitlab.com/cli/mr/merge/)
- [glab ci view](https://docs.gitlab.com/cli/ci/view/)
- [glab api](https://docs.gitlab.com/cli/api/)
- [glab repo clone](https://docs.gitlab.com/cli/repo/clone/)
