---
name: code-session
description: >-
  This skill should be invoked with "/code-session" to start an autonomous
  coding session. Configures a project repo, spawns Claude Code to implement
  a Jira ticket, creates a merge request, triggers UAT/staging builds, and
  watches the pipeline. Auto-fixes pipeline failures when possible.
argument-hint: "<ticket-id> [--project PROJECT] [--repo REPO] [--path LOCAL_PATH]"
allowed-tools: ["Bash", "Read", "Write", "Edit", "Agent"]
version: 0.1.0
---

# Code Session

Start an autonomous coding session for a Jira ticket.

## Arguments

- `<ticket-id>` — Jira ticket key (e.g., PROJ-123)
- `--project PROJECT` — Project name from config (skip setup if configured)
- `--repo REPO` — GitLab repo path (e.g., group/backend-api)
- `--path LOCAL_PATH` — Local clone path

## Execution Flow

### 1. Load or Configure Project

Read `.claude/openkhang.local.md` for project config.

If project not configured or `--repo` provided, run **Project Setup**:
1. Ask for GitLab repo path
2. Ask for local clone path (or clone if not exists)
3. Ask for default branch name
4. Ask for UAT/staging pipeline job names
5. Save to state file

### 2. Fetch Ticket Context

```bash
jira issue view TICKET_ID --json
```

Extract: summary, description, acceptance criteria, linked issues, comments.

If ticket has Confluence links, fetch those pages for additional context.

### 3. Create Feature Branch

```bash
cd LOCAL_PATH
git checkout DEFAULT_BRANCH && git pull
git checkout -b fix/TICKET_ID-short-description
```

Branch naming: `fix/PROJ-123-login-bug` or `feat/PROJ-456-new-api`.

### 4. Spawn Implementation Session

Launch a Claude Code session in the project directory:

```bash
cd LOCAL_PATH
claude --print "Implement TICKET_ID: SUMMARY\n\nDescription: DESCRIPTION\n\nAcceptance criteria: CRITERIA\n\nBranch: BRANCH_NAME\n\nInstructions: Implement this ticket. Run tests. Commit changes."
```

Alternatively, provide the ticket context and let the current session implement directly in the local path.

### 5. Create Merge Request

After implementation is committed:

```bash
cd LOCAL_PATH
git push -u origin BRANCH_NAME
glab mr create \
  --title "fix(PROJ-123): Short description" \
  --description "$(cat <<'EOF'
## Summary
[Auto-generated from ticket description]

## Jira Ticket
TICKET_ID: SUMMARY

## Changes
[List of changes from commits]

## Testing
- [ ] Unit tests pass
- [ ] UAT deployment verified
EOF
)" \
  --source-branch BRANCH_NAME \
  --target-branch DEFAULT_BRANCH \
  --json
```

Extract MR ID and save to active_session state.

### 6. Trigger UAT/Staging Build

```bash
# Trigger UAT deployment
glab ci trigger --branch BRANCH_NAME --variables "DEPLOY_ENV=uat"

# Or if pipeline auto-triggers, just watch it
glab ci status --branch BRANCH_NAME --json
```

### 7. Watch Pipeline

Delegate to `/pipeline-watch` skill to monitor the pipeline.
Save pipeline ID to active_session state.

### 8. Update Jira Ticket

Move ticket to "In Review":
```bash
jira issue move TICKET_ID "In Review"
jira issue comment add TICKET_ID --body "MR created: MR_URL. Pipeline: PIPELINE_URL"
```

## Error Handling

- **Clone fails**: check SSH keys / access
- **Branch exists**: ask user to reuse or create new
- **MR creation fails**: check for existing MR on same branch
- **Pipeline trigger fails**: fall back to manual trigger instructions

## Integration with Chat

When bug-investigator agent determines a bug is fixable:
1. Auto-create code-session with the ticket
2. Notify user via chat: "Starting code session for PROJ-123"
3. Send MR link when ready
