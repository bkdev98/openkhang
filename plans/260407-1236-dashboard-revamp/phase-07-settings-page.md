# Phase 7: Settings Page

**Priority:** Medium
**Status:** Complete

## Overview

Configuration UI: persona, confidence thresholds, project repos, integration tokens, auto-reply.

## Related Code Files

**Modify:**
- `services/dashboard/app.py` — add settings endpoints

**Create:**
- `services/dashboard/settings_services.py` — read/write YAML config files
- `services/dashboard/templates/pages/settings.html` — all settings forms

## Implementation Steps

1. Create settings_services.py:
   - `get_persona()` — read config/persona.yaml
   - `save_persona(data)` — write to config/persona.yaml
   - `get_confidence()` — read config/confidence_thresholds.yaml
   - `save_confidence(data)` — write to config/confidence_thresholds.yaml
   - `get_projects()` — read config/projects.yaml
   - `save_projects(data)` — write to config/projects.yaml
   - `test_connection(service, url, token)` — test Jira/GitLab/Confluence connectivity

2. Add API endpoints:
   - `GET /api/settings/{section}` — get settings for section
   - `POST /api/settings/{section}` — save settings for section
   - `POST /api/settings/test-connection` — test integration connectivity

3. Create settings.html: sectioned form with:
   - Persona: name, tone, language fields
   - Confidence: default threshold slider, per-room overrides table
   - Projects: repo list with add/remove
   - Integrations: Jira/GitLab/Confluence URL + token fields + test buttons
   - Auto-reply: toggle with behavior description
   - Save button per section

4. HTMX form submission: `hx-post` with inline success/error feedback

## Todo

- [x] Create settings_services.py with YAML read/write
- [x] Add /api/settings/* endpoints to app.py
- [x] Create settings.html page with all form sections
- [x] Implement connection test buttons
- [x] Add inline save feedback (success/error)
- [x] Verify YAML write-back works correctly

## Success Criteria

- All settings load correctly from YAML files
- Edits save back to YAML files
- Connection test shows success/error inline
- Auto-reply toggle works
- Invalid input shows validation errors
