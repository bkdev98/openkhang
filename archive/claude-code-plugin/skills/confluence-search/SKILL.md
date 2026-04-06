---
name: confluence-search
description: >-
  This skill should be invoked with "/confluence-search" to search Confluence
  pages by keywords, space, or CQL query. Returns matching pages with
  snippets and links.
argument-hint: "<query> [--space SPACE] [--cql]"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 0.1.0
---

# Confluence Search

Search Confluence documentation.

## Arguments

- `<query>` — Search keywords or CQL query
- `--space SPACE` — Limit to specific space (default: all)
- `--cql` — Treat query as raw CQL instead of keyword search

## Execution Flow

### 1. Build Search Query

If `--cql` flag: use query as-is.
Otherwise: build CQL from keywords:
```
text ~ "query keywords" AND type = page
```

Add space filter if `--space` provided:
```
space = SPACE AND text ~ "query keywords" AND type = page
```

### 2. Execute Search

```bash
atlassian-cli confluence search --cql "QUERY" --json
```

### 3. Display Results

```
🔍 Confluence Search: "API authentication"

Found 5 pages:

1. 📄 API Authentication Guide (DEV space)
   Last modified: Mar 20, 2026 by Alice
   Snippet: "...OAuth2 authentication flow for external API consumers..."
   URL: https://company.atlassian.net/wiki/spaces/DEV/pages/12345

2. 📄 Security Architecture (ARCH space)
   Last modified: Mar 15, 2026 by Bob
   Snippet: "...token-based authentication using JWT with refresh tokens..."
   URL: https://company.atlassian.net/wiki/spaces/ARCH/pages/12346

...
```

### 4. Read Page Content

If user asks to read a specific result, fetch full content:
```bash
atlassian-cli confluence page get PAGE_ID --body --json
```

Display as readable markdown (convert HTML to plain text).
