# Confluence CLI Reference for Claude Code Plugin

**Research Date:** 2026-03-24
**Status:** Active & Maintained
**Primary Tool:** atlassian-cli (Omar Shabab) - Rust-based unified CLI
**Alternative:** atlassian-python-api - Python library wrapper

---

## 1. Installation

### atlassian-cli (Recommended)

**Homebrew:**
```bash
brew install omar16100/atlassian-cli/atlassian-cli
```

**Cargo:**
```bash
cargo install --locked atlassian-cli
```

**Direct Download:**
```bash
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/omar16100/atlassian-cli/releases/download/v0.3.1/atlassian-cli-installer.sh | sh
```

### atlassian-python-api (Alternative)

```bash
pip install atlassian-python-api
```

---

## 2. Authentication

### atlassian-cli Setup

**Generate API Token:**
1. Login to Atlassian account settings
2. Select "Create API token"
3. Give it descriptive name
4. Set expiration (1-365 days)
5. Copy & save securely

**Configure Auth Profile:**
```bash
echo YOUR_API_TOKEN | atlassian-cli auth login \
  --site mysite.atlassian.net \
  --email user@example.com \
  --token
```

**Store Encrypted:**
- Credentials stored with AES-256-GCM encryption
- Located in `~/.atlassian-cli/config.toml`
- Supports multiple auth profiles for different instances

### atlassian-python-api Setup

```python
from atlassian import Confluence

confluence = Confluence(
    url='https://mysite.atlassian.net/wiki',
    username='user@example.com',
    password='API_TOKEN'  # Use API token, not password
)
```

---

## 3. Confluence Commands (atlassian-cli)

### Search Pages

```bash
# CQL search
atlassian-cli confluence page search \
  --cql "space = TEST AND text ~ 'keyword'" \
  --output json

# List space pages
atlassian-cli confluence space list-pages --key TEST
```

### Read Page Content

```bash
# Get page by ID
atlassian-cli confluence page get --id 123456

# Get with content body
atlassian-cli confluence page get --id 123456 --include body
```

### Create Page

```bash
atlassian-cli confluence page create \
  --space TEST \
  --title "New Page" \
  --body "Page content in HTML" \
  --parent-id 123456  # Optional parent
```

### Update Page

```bash
atlassian-cli confluence page update \
  --id 123456 \
  --title "Updated Title" \
  --body "Updated HTML content"
```

### Bulk Operations

```bash
# Export pages from space
atlassian-cli confluence space export \
  --key TEST \
  --output json

# Bulk update with concurrent execution
atlassian-cli confluence page update \
  --batch-file updates.csv \
  --concurrent 5
```

### Output Formats

Supported: `table`, `json`, `csv`, `yaml`, `quiet` (via `--output` flag)

---

## 4. Jira Commands (atlassian-cli)

### Search Issues

```bash
atlassian-cli jira issue search \
  --jql "project = TEST AND status = Open" \
  --output json
```

### Create Issue

```bash
atlassian-cli jira issue create \
  --project TEST \
  --type Story \
  --title "Task title" \
  --description "Description"
```

### Update Issue

```bash
atlassian-cli jira issue update \
  --key TEST-123 \
  --status "In Progress"
```

### Bulk Operations

```bash
atlassian-cli jira issue bulk-transition \
  --jql "status = Open" \
  --transition "Ready for Dev"
```

---

## 5. Advanced Features

### Dry-Run Mode
```bash
atlassian-cli confluence page create \
  --space TEST \
  --title "Test" \
  --dry-run  # Preview without executing
```

### Attachments
```bash
# Upload
atlassian-cli confluence attachment upload \
  --page-id 123456 \
  --file document.pdf

# Download
atlassian-cli confluence attachment download \
  --attachment-id 789 \
  --output-file document.pdf
```

### Service Desk (JSM)
- Manage requests and queues
- Track SLA metrics
- Bulk operations on tickets

### Bitbucket Integration
- Repository management
- Pull request workflows
- Pipeline operations

---

## 6. Configuration & Environment

**Config File Location:** `~/.atlassian-cli/config.toml`

**Environment Variables:**
```bash
export ATLASSIAN_SITE=mysite.atlassian.net
export ATLASSIAN_EMAIL=user@example.com
export ATLASSIAN_TOKEN=your_token_here
```

**CI/CD Integration:**
Use bot account with API token for automation pipelines

---

## 7. Plugin Integration Strategy

### For Claude Code Plugin

1. **Shell execution layer:** Wrap atlassian-cli commands via bash
2. **JSON parsing:** Output results with `--output json` for structured data
3. **Error handling:** Capture exit codes and stderr
4. **Dry-run by default:** Offer preview before mutations
5. **Credential management:** Use env vars or stored auth profiles

### Key Command Pattern

```bash
atlassian-cli [product] [resource] [action] [options] --output json
```

---

## 8. Comparison: atlassian-cli vs Alternatives

| Feature | atlassian-cli | atlassian-python-api | Direct REST API |
|---------|------|------------|---------|
| **Language** | Rust CLI | Python lib | curl/HTTP |
| **Installation** | Binary/Homebrew | pip | None |
| **Ease** | Easy | Moderate | Complex |
| **Bulk ops** | Native | Via loops | Manual |
| **Confluence** | Yes | Yes | Yes |
| **Jira** | Yes | Yes | Yes |
| **Bitbucket** | Yes | No | Yes |
| **Encryption** | AES-256-GCM | No | No |

---

## Unresolved Questions

1. **Confluence Cloud vs Server:** Does atlassian-cli support Confluence Data Center (self-hosted)? Docs mention Cloud focus.
2. **Rate limits:** What are API rate limits for bulk operations?
3. **Pagination:** How to handle large result sets in searches?
4. **Page templates:** Can atlassian-cli use Confluence page templates for creation?
5. **Permissions:** How to handle permission errors gracefully in plugin flow?

---

## Sources

- [Omar Shabab atlassian-cli GitHub](https://github.com/omar16100/atlassian-cli)
- [atlassiancli.com Official Docs](https://atlassiancli.com/)
- [atlassian-python-api GitHub](https://github.com/atlassian-api/atlassian-python-api)
- [Atlassian API Token Management](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/)
- [Atlassian CLI Official Reference](https://developer.atlassian.com/cloud/acli/guides/how-to-get-started/)
- [Confluence REST API Examples](https://developer.atlassian.com/server/confluence/confluence-rest-api-examples/)
