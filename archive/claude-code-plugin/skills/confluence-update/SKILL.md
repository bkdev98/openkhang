---
name: confluence-update
description: >-
  This skill should be invoked with "/confluence-update" to create or update
  Confluence pages. Can create new pages, update existing content, or
  append sections to existing pages.
argument-hint: "<page-id|title> [--create] [--space SPACE] [--append]"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
version: 0.1.0
---

# Confluence Update

Create or update Confluence pages.

## Arguments

- `<page-id|title>` — Page ID or title to update
- `--create` — Create a new page
- `--space SPACE` — Target space (default from config)
- `--append` — Append content instead of replacing

## Execution Flow

### Create New Page

```bash
atlassian-cli confluence page create \
  --space SPACE \
  --title "Page Title" \
  --body "<content in HTML>" \
  --parent PARENT_PAGE_ID  # optional
```

### Update Existing Page

1. Fetch current content:
   ```bash
   atlassian-cli confluence page get PAGE_ID --body --json
   ```

2. Modify content (or append if `--append`).

3. Update:
   ```bash
   atlassian-cli confluence page update PAGE_ID \
     --body "<updated HTML content>"
   ```

### Content Format

Confluence uses XHTML storage format. Convert markdown to HTML:
- Headers: `<h1>`, `<h2>`, etc.
- Lists: `<ul>/<ol>` with `<li>`
- Code: `<ac:structured-macro ac:name="code">...</ac:structured-macro>`
- Tables: standard HTML `<table>`

### Interactive Mode

When called without arguments, ask user:
1. Create new or update existing?
2. If update: search for page by title
3. What content to add/change?
4. Confirm before submitting
