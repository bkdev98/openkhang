---
name: confluence-knowledge
description: >-
  This skill provides core knowledge for Confluence integration in the
  openkhang plugin. It should be activated when any Confluence-related
  skill runs, or when the user asks about "confluence", "wiki", "docs",
  "documentation search", "knowledge base", or "team docs".
version: 0.1.0
---

# Confluence Knowledge — Core Reference

Confluence integration for documentation search and updates via atlassian-cli.

## CLI Tool: atlassian-cli

```bash
# Auth setup (encrypted config at ~/.atlassian-cli/config.toml)
atlassian-cli auth setup

# Search pages by CQL
atlassian-cli confluence search --cql "text ~ 'API documentation'" --json
atlassian-cli confluence search --cql "space = DEV AND type = page" --json

# List spaces
atlassian-cli confluence space list --json

# Get page content
atlassian-cli confluence page get PAGE_ID --json
atlassian-cli confluence page get PAGE_ID --body  # include HTML body

# Create page
atlassian-cli confluence page create --space DEV --title "New Page" --body "<p>Content</p>"
atlassian-cli confluence page create --space DEV --title "Child" --parent PAGE_ID --body "<p>Content</p>"

# Update page
atlassian-cli confluence page update PAGE_ID --title "Updated Title" --body "<p>New content</p>"

# Attachments
atlassian-cli confluence attachment upload PAGE_ID --file ./doc.pdf
atlassian-cli confluence attachment list PAGE_ID --json
```

## State File

Confluence state in `.claude/openkhang.local.md`:

```yaml
confluence:
  base_url: https://company.atlassian.net/wiki
  default_space: DEV
  recent_pages:
    - id: "12345"
      title: "API Documentation"
      space: DEV
    - id: "12346"
      title: "Architecture Overview"
      space: ARCH
```

## Common CQL Patterns

```
# Search in a specific space
space = DEV AND type = page AND text ~ "keyword"

# Pages modified recently
lastModified >= "2026-03-01" AND space = DEV

# Pages by label
label = "architecture" AND space = DEV

# Pages by creator
creator = currentUser() AND type = page
```

## Additional Resources

- **`references/confluence-cql-reference.md`** — Full CQL syntax reference
