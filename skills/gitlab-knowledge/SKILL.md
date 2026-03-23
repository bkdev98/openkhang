---
name: gitlab-knowledge
description: >-
  This skill provides core knowledge for GitLab integration in the openkhang
  plugin. It should be activated when any GitLab-related skill or agent runs,
  or when the user asks about "gitlab", "merge request", "MR", "pipeline",
  "CI/CD", "glab", "code session", or "deploy".
version: 0.1.0
---

# GitLab Knowledge — Core Reference

GitLab integration for code sessions, MR management, and pipeline watching via `glab` CLI.

## CLI Tool: glab

```bash
# Auth
glab auth login  # interactive browser auth
glab auth status  # check auth

# Merge Requests
glab mr create --title "Title" --description "Desc" -s feature-branch -t main --json
glab mr list --assignee=@me --json
glab mr view MR_ID --json
glab mr approve MR_ID
glab mr merge MR_ID --squash
glab mr note MR_ID --message "Comment"
glab mr diff MR_ID

# Pipelines
glab ci list --json
glab ci view PIPELINE_ID --json
glab ci status  # current branch pipeline
glab ci retry PIPELINE_ID
glab ci get JOB_ID --json
glab ci trace JOB_ID  # stream job logs

# Trigger pipeline with variables
glab ci trigger --branch BRANCH --variables "KEY=VALUE"

# Repo
glab repo clone GROUP/PROJECT
glab repo view --json
```

## State File

GitLab state in `.claude/openkhang.local.md`:

```yaml
gitlab:
  projects:
    - name: "backend-api"
      repo: "group/backend-api"
      local_path: "/Users/quocs/Projects/backend-api"
      default_branch: "main"
      uat_trigger: "deploy_uat"  # pipeline job name
      stag_trigger: "deploy_staging"
    - name: "frontend-app"
      repo: "group/frontend-app"
      local_path: "/Users/quocs/Projects/frontend-app"
      default_branch: "develop"
  active_session:
    project: "backend-api"
    branch: "fix/PROJ-123-login-bug"
    mr_id: 456
    jira_ticket: "PROJ-123"
    pipeline_id: 78901
    status: "pipeline_running"
```

## Pipeline Stages (typical)

```
build → test → lint → security_scan → deploy_uat → deploy_staging → deploy_prod
```

Auto-retry logic:
- `build` failures: check logs, likely code error → fix and push
- `test` failures: check test logs, could be flaky → retry once, then fix
- `lint` failures: auto-fixable → run linter locally, push fix
- `security_scan` failures: review findings, may need code changes
- `deploy_*` failures: check infra logs, may need retry

## Additional Resources

- **`references/glab-commands.md`** — Full glab CLI command reference
