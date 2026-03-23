---
name: pipeline-watch
description: >-
  This skill should be invoked with "/pipeline-watch" to monitor a GitLab
  CI/CD pipeline, report status changes, and auto-retry or auto-fix failures.
  Can run continuously via "/loop 2m /pipeline-watch".
argument-hint: "[PIPELINE_ID|MR_ID] [--branch BRANCH] [--auto-fix]"
allowed-tools: ["Bash", "Read", "Write", "Edit", "Agent"]
version: 0.1.0
---

# Pipeline Watch

Monitor GitLab pipeline status with auto-retry and auto-fix capabilities.

## Arguments

- `PIPELINE_ID` — Specific pipeline to watch (default: latest on active branch)
- `MR_ID` — Watch pipeline for a specific MR
- `--branch BRANCH` — Watch pipelines on this branch
- `--auto-fix` — Enable auto-fix for failed jobs (default: enabled)

## Execution Flow

### 1. Identify Pipeline

If no ID provided, get from active_session or current branch:

```bash
glab ci status --branch BRANCH --json
# or
glab ci list --branch BRANCH --json | head -1
```

### 2. Check Pipeline Status

```bash
glab ci view PIPELINE_ID --json
```

### 3. Display Status

```
🔄 Pipeline #78901 (fix/PROJ-123-login-bug)
   MR: !456 — "fix(PROJ-123): Fix login bug"

   ✅ build         (2m 15s)
   ✅ test          (5m 30s)
   ✅ lint          (1m 02s)
   🔄 security_scan (running... 3m)
   ⏳ deploy_uat    (pending)
   ⏳ deploy_staging (pending)

   Elapsed: 8m 47s | Estimated remaining: ~12m
```

### 4. Handle Failures

When a job fails:

```bash
# Get job logs
glab ci trace JOB_ID
```

**Auto-retry logic** (try once before fixing):
```bash
glab ci retry PIPELINE_ID
```

If retry also fails, analyze logs and attempt fix:

#### Build Failures
- Parse error messages from logs
- Common fixes: missing dependencies, syntax errors, type errors
- Spawn pipeline-fixer agent with error context

#### Test Failures
- Extract failing test names and error messages
- First retry (flaky test detection)
- If still fails: analyze test code + implementation, fix

#### Lint Failures
- Run linter locally, auto-fix, commit, push
- ```bash
  cd LOCAL_PATH && npm run lint:fix && git add -A && git commit -m "fix: lint errors" && git push
  ```

#### Deploy Failures
- Check infrastructure logs
- Common: timeout, resource limits, config errors
- Notify user if infra issue (can't auto-fix)

### 5. Success Actions

When pipeline passes all stages:

```
✅ Pipeline #78901 PASSED (total: 18m 42s)

   ✅ build          2m 15s
   ✅ test           5m 30s
   ✅ lint           1m 02s
   ✅ security_scan  4m 10s
   ✅ deploy_uat     3m 45s
   ✅ deploy_staging 2m 00s

🎉 UAT deployed! URL: https://uat.app.company.com
📋 MR !456 ready for review
```

Update Jira ticket status if applicable.

### 6. Continuous Mode

With `/loop 2m /pipeline-watch`:
- Poll every 2 minutes
- Only display changes (new job completions/failures)
- Auto-stop loop when pipeline reaches terminal state (passed/failed)

## Pipeline Fixer Agent

For complex failures, delegate to `pipeline-fixer` agent with:
- Failed job name and stage
- Job log output (last 100 lines)
- Project context (language, framework)
- Recent commits on the branch
