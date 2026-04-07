# HTMX Dashboard Patterns for openkhang (FastAPI + Jinja2 + Tailwind)

**Date:** April 7, 2026  
**Researcher:** Technical Analysis  
**Project:** openkhang digital twin dashboard revamp  
**Target Stack:** FastAPI + HTMX + Jinja2 + Tailwind CSS  

---

## Executive Summary

HTMX + FastAPI is production-ready for openkhang's dashboard. Patterns exist for all 6 priority areas. **Recommendation: Use hx-boost for sidebar navigation (progressive enhancement), hx-swap-oob for chat streaming, SSE for real-time activity feed, vanilla JS for auto-scroll. Avoid WebSockets for MVP — SSE is simpler, HTTP-friendly, and sufficient for current needs.**

Trade-off: SSE has ~1-5s latency vs WebSocket's <100ms. For a dashboard (not a fast-paced game), acceptable.

---

## 1. HTMX Multi-Page Apps with Sidebar Navigation

### Pattern: `hx-boost` + `hx-push-url`

**Problem:** How to make sidebar links feel like a SPA without full page reloads while keeping server-side routing simple.

**Solution:**
```html
<!-- base.html -->
<nav hx-boost="true" hx-target="#main-content" hx-swap="innerHTML swap:1s">
  <a href="/inbox">Inbox</a>
  <a href="/drafts">Drafts</a>
  <a href="/health">Health</a>
  <a href="/settings">Settings</a>
</nav>

<main id="main-content">
  <!-- Swapped content here -->
</main>
```

**Backend (FastAPI):**
```python
@app.get("/inbox")
async def inbox(request: Request):
    # Detect HTMX request via HX-Request header
    if request.headers.get("HX-Request"):
        # Return only the content partial, not full HTML
        return templates.TemplateResponse("partials/inbox.html", {
            "events": await get_recent_events(),
            "request": request
        })
    # Full page load (browser back/refresh, or non-HTMX client)
    return templates.TemplateResponse("pages/inbox.html", {"events": ..., "request": request})
```

**Why it works:**
- `hx-boost="true"` converts all links to AJAX (progressive enhancement — works without JS)
- `hx-push-url` auto-added by `hx-boost`, updates browser address bar
- Server returns partials on `HX-Request`, full pages otherwise
- Bookmarks, back button, shared links all work seamlessly

**Tailwind Integration:**
```html
<!-- Sidebar with glassmorphism on dark theme -->
<aside class="fixed left-0 top-0 h-screen w-64 
             bg-slate-900/50 backdrop-blur-md border-r border-slate-700/20
             flex flex-col gap-2 p-4">
  <a hx-boost="true" href="/inbox" 
     class="px-4 py-2 rounded-lg hover:bg-slate-700/30
             transition-colors duration-200">
    Inbox
  </a>
</aside>

<!-- Main content with smooth transition -->
<main id="main-content" class="ml-64 p-6">
  <!-- Partial content swapped here -->
</main>
```

**Gotchas:**
- Always return `base.html` (wrapper) on first page load; return only `#main-content` div for subsequent HTMX requests
- Use `hx-swap="innerHTML swap:1s"` for smooth CSS transitions
- Check `HX-Request` header to avoid rendering nav twice

---

## 2. SSE (Server-Sent Events) for Real-Time Activity Feed

### Pattern: HTMX SSE Extension + Multiple Connections

**Problem:** openkhang's activity feed (agents sending drafts, messages arriving) needs real-time push without WebSocket complexity.

**Solution:**

```html
<!-- Dashboard with SSE listener -->
<div hx-ext="sse" sse-connect="/events" class="space-y-2">
  <div id="activity-feed" sse-swap="message" hx-swap="beforeend swap:0.3s"></div>
</div>
```

**Backend (FastAPI):**
```python
@app.get("/events")
async def event_stream(request: Request):
    async def generate():
        # Simulate sending events (in real code, pull from Redis pub/sub)
        while True:
            try:
                # Redis subscriber pattern
                event = await redis_queue.get_next_event()
                if event:
                    # SSE format: "event: <name>\ndata: <html>\n\n"
                    yield f"event: message\n"
                    yield f"data: <li class='...'>Draft from {event['actor']}</li>\n\n"
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
    
    return StreamingResponse(generate(), media_type="text/event-stream")
```

**Why SSE over WebSocket:**
- Works through HTTP proxies & firewalls (no special upgrade needed)
- Built-in browser reconnection with exponential backoff
- HTMX extension handles all state (no manual event binding)
- Sufficient latency for drafts/activity (1-5s acceptable)

**Multiple SSE Connections (if needed):**
```html
<!-- Separate streams for different data types -->
<div hx-ext="sse" sse-connect="/events/drafts" id="drafts-feed" 
     sse-swap="draft" hx-swap="beforeend"></div>

<div hx-ext="sse" sse-connect="/events/activity" id="activity-feed" 
     sse-swap="activity" hx-swap="beforeend"></div>
```

**Reconnection (automatic):**
HTMX SSE extension includes exponential backoff — browser auto-reconnects if stream drops. In rare cases, add heartbeat:

```python
yield f"event: ping\ndata: \n\n"  # Every 30s to keep connection alive
```

---

## 3. Chat UI with HTMX + Vanilla JS Auto-Scroll

### Pattern: `hx-swap-oob` for Message Streaming + Vanilla JS for UX

**Problem:** Chat messages stream in; need to append new messages, auto-scroll, avoid full re-render.

**Solution:**

```html
<!-- Chat container -->
<div id="chat-messages" class="flex flex-col gap-2 h-96 overflow-y-auto">
  <!-- Existing messages -->
  <div class="text-sm text-slate-400">Conversation started</div>
</div>

<!-- Send form -->
<form hx-post="/chat" hx-target="none" 
      hx-on::after-request="if(event.detail.xhr.status === 200) document.getElementById('chat-input').value = ''">
  <input id="chat-input" type="text" name="message" placeholder="Message..." />
  <button type="submit">Send</button>
</form>
```

**Backend:**
```python
@app.post("/chat")
async def send_chat(request: Request, message: str):
    # 1. Append user message
    user_html = f"<div class='text-right'>{escape(message)}</div>"
    
    # 2. Get assistant response (streaming or instant)
    assistant_text = await agent.reply(message)
    assistant_html = f"<div class='text-left'>{escape(assistant_text)}</div>"
    
    # Return both messages as OOB swaps (will be appended)
    response = f"""
    {user_html}
    <div hx-swap-oob="beforeend:#chat-messages">{assistant_html}</div>
    """
    return HTMLResponse(response)
```

**Vanilla JS for Auto-Scroll:**
```javascript
// In your base template <script> section
document.addEventListener('htmx:afterSettle', (event) => {
  const chatContainer = document.getElementById('chat-messages');
  if (chatContainer) {
    // Only scroll if user is already near bottom (don't break manual scroll-up)
    const isNearBottom = chatContainer.scrollHeight - chatContainer.scrollTop < 500;
    if (isNearBottom) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }
});
```

**Why NOT full HTMX:**
HTMX is great for form swaps & nav, but chat UX (smooth scroll, scroll lock) benefits from lightweight JS event binding. Keep HTMX for the HTML transfer; let vanilla JS handle the polish.

**Streaming Response (for AI replies):**
If using FastAPI streaming + SSE:
```python
async def generate_response():
    buffer = ""
    async for chunk in agent.stream_reply(message):
        buffer += chunk
        yield f"""event: message_chunk
data: <div hx-swap-oob="innerHTML:#assistant-message">{buffer}</div>

"""
```

---

## 4. Tailwind CSS Dark Theme + Glassmorphism

### Pattern: Utility-First Warm Dark Theme with Frosted Glass

**Color Palette (openkhang brand):**
- **Base**: `slate-900` / `slate-950` (very dark blue)
- **Accent**: `amber-500` / `orange-500` (warm accent)
- **Glass**: `bg-opacity-10` + `backdrop-blur-md`

```html
<!-- Main layout with glassmorphism -->
<body class="bg-slate-950 text-slate-100">
  <!-- Sidebar with frosted glass -->
  <aside class="fixed inset-y-0 left-0 w-64 
               bg-slate-900/30 backdrop-blur-xl border-r border-slate-700/20
               flex flex-col gap-3 p-4">
    <a href="/inbox" class="px-4 py-2 rounded-lg
                          bg-gradient-to-r from-amber-500/10 to-orange-500/10
                          hover:from-amber-500/20 hover:to-orange-500/20
                          border border-amber-500/20
                          transition-all duration-200">
      Inbox
    </a>
  </aside>

  <!-- Main content area -->
  <main class="ml-64 p-6">
    <!-- Card with glassmorphism -->
    <div class="bg-slate-900/40 backdrop-blur-md rounded-xl 
               border border-slate-700/30 p-6 shadow-2xl">
      <h2 class="text-xl font-semibold text-amber-400">Drafts</h2>
      <p class="text-slate-300 mt-2">Your pending replies</p>
    </div>
  </main>
</body>
```

**Glass Effect Best Practices:**
- `backdrop-blur-md` (blur) + `bg-opacity-20` (transparency) = frosted glass
- Add `border border-{color}/30` for subtle edge definition
- Gradient accents via `from-{color}/10 to-{color}/10` (subtle, not garish)
- Tailwind v3.4+ supports `supports` prefix for fallback (e.g., `supports-[backdrop-filter]:backdrop-blur-md`)

**Tailwind Config (if customizing):**
```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        brand: {
          dark: '#0f172a', // slate-950
          accent: '#f59e0b', // amber-500
        }
      },
      backdropBlur: {
        'glass': '12px'
      }
    }
  }
}
```

**Animation + Transition:**
```html
<!-- Smooth swap with fade-in -->
<div hx-target="#main-content" hx-swap="innerHTML swap:0.2s settle:0.5s">
  <!-- HTMX adds class "htmx-swapping" during swap, "htmx-settling" after -->
</div>

<style>
#main-content.htmx-swapping {
  opacity: 0;
  transition: opacity 0.2s ease-out;
}
#main-content.htmx-settling {
  opacity: 1;
  transition: opacity 0.2s ease-in;
}
</style>
```

---

## 5. HTMX Form Patterns: Validation + File Upload

### Pattern A: Real-Time Validation

```html
<form hx-post="/settings" hx-target="#settings-result">
  <div>
    <label>Persona Name</label>
    <input 
      type="text" 
      name="persona_name" 
      hx-post="/validate/persona_name"
      hx-target="next .error"
      hx-trigger="blur" />
    <div class="error text-red-500 text-sm mt-1"></div>
  </div>

  <button type="submit">Save</button>
</form>
```

**Backend Validation:**
```python
@app.post("/validate/persona_name")
async def validate_persona(persona_name: str):
    if not persona_name.strip():
        return HTMLResponse("<p>Name cannot be empty</p>", status_code=400)
    if len(persona_name) > 100:
        return HTMLResponse("<p>Name too long (max 100)</p>", status_code=400)
    return ""  # No error = 200 + empty response
```

### Pattern B: File Upload with Progress

```html
<form hx-post="/upload/config" 
      hx-encoding='multipart/form-data'
      hx-target="#upload-result">
  
  <input type="file" name="file" accept=".yaml" />
  
  <!-- Progress bar -->
  <progress id="upload-progress" value="0" max="100" 
            hx-trigger="htmx:xhr:progress from:body" 
            hx-vals='js:{value: event.loaded}'>
  </progress>
  
  <button type="submit">Upload</button>
</form>

<div id="upload-result"></div>

<script>
document.addEventListener('htmx:xhr:progress', (e) => {
  const percent = (e.detail.loaded / e.detail.total) * 100;
  document.getElementById('upload-progress').value = percent;
});
</script>
```

**Backend:**
```python
@app.post("/upload/config")
async def upload_config(file: UploadFile = File(...)):
    # Validate & process YAML
    content = await file.read()
    config = yaml.safe_load(content)
    
    # Save to database
    await db.save_config(config)
    
    return HTMLResponse(
        "<p class='text-green-500'>Config uploaded successfully</p>"
    )
```

---

## 6. Performance: Keeping Partials Fast

### Optimization Checklist

| Tactic | Impact | Implementation |
|--------|--------|-----------------|
| **Query optimization** | High | Use `SELECT * FROM events WHERE created_at > :since` with indexes |
| **Lazy-load below fold** | Medium | Add `hx-trigger="intersect once"` to off-screen sections |
| **Fragment caching** | High | Cache Jinja2 partials in Redis (60s TTL for activity feed) |
| **Compression** | Low | FastAPI auto-gzips; HTMX payloads usually <5KB |
| **Batch updates** | High | Combine multiple OOB swaps into one response |

**Example: Lazy Loading**

```html
<!-- Inbox with lazy-loaded older messages -->
<div id="inbox">
  <div id="recent-messages"><!-- First 10 messages --></div>
  
  <!-- Lazy load older messages on scroll near bottom -->
  <div hx-get="/inbox/older?before_id=..." 
       hx-trigger="intersect once" 
       hx-swap="beforeend:#inbox">
    Loading...
  </div>
</div>
```

**Example: Fragment Caching (Redis)**

```python
import hashlib

@app.get("/partials/activity-feed")
async def activity_feed():
    cache_key = "activity_feed:html"
    
    # Try cache first
    cached = await redis.get(cache_key)
    if cached:
        return HTMLResponse(cached)
    
    # Render if not cached
    events = await get_recent_events(limit=20)
    html = templates.get_template("partials/activity_feed.html").render(events=events)
    
    # Cache for 60 seconds
    await redis.setex(cache_key, 60, html)
    return HTMLResponse(html)
```

---

## Architectural Fit for openkhang

### Current State
- Dashboard exists (11 files, ~2000 LOC)
- Uses FastAPI + Jinja2 + basic TailwindCSS
- Activity feed via SSE (`/events`)
- Draft approval workflow

### Gaps → Patterns
| Gap | Pattern | Priority |
|-----|---------|----------|
| Sidebar nav is full page reload | hx-boost + hx-push-url | **High** |
| Draft list doesn't live-update | SSE + hx-swap-oob | **High** |
| Twin chat missing auto-scroll | Vanilla JS event binding | **Medium** |
| Dark theme lacks cohesion | Glassmorphism + warm accent | **Medium** |
| Settings form UX brittle | Real-time validation + blur | **Low** |

### Implementation Plan (Phased)

**Phase 1 (Week 1):** hx-boost navigation + activity feed OOB swaps  
**Phase 2 (Week 2):** Chat UI with streaming + auto-scroll  
**Phase 3 (Week 3):** Tailwind polish + glassmorphism  
**Phase 4 (Week 4):** Forms + validation  

---

## Code Snippet Reference

### Minimal Viable hx-boost Setup
```python
# app.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/")
def home(request: Request):
    return templates.TemplateResponse("base.html", {"request": request})

@app.get("/inbox")
def inbox(request: Request):
    is_htmx = request.headers.get("hx-request") == "true"
    if is_htmx:
        return templates.TemplateResponse("partials/inbox.html", {
            "request": request, 
            "drafts": get_drafts()
        })
    return templates.TemplateResponse("pages/inbox.html", {
        "request": request, 
        "drafts": get_drafts()
    })
```

```html
<!-- base.html -->
<!DOCTYPE html>
<html>
<head>
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
  <script src="https://unpkg.com/htmx.org@1.9.10/dist/ext/sse.js"></script>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100">
  <nav hx-boost="true" hx-target="#content" hx-swap="innerHTML">
    <a href="/">Home</a>
    <a href="/inbox">Inbox</a>
  </nav>
  
  <main id="content">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

---

## Adoption Risk

**Low risk:**
- HTMX is stable (1.9+), used in production (Dropbox, GitHub, Stripe)
- FastAPI + Jinja2 battle-tested
- No vendor lock-in (pure HTML/CSS/JS)
- Graceful degradation (hx-boost works without JS)

**Medium risk:**
- Team skill: Requires thinking in "partials" vs "full pages"
- SSE limitations: ~1-5s latency (not real-time)
- Debugging: HTMX events in browser DevTools take practice

**Mitigation:**
- Write docs for partial-response pattern (check HX-Request header)
- Use browser DevTools HTMX extension
- Keep vanilla JS minimal; use HTMX for 90% of interactions

---

## Unresolved Questions

1. **File upload size limits?** FastAPI default is 25MB; adjust in config if needed.
2. **Multi-user draft conflicts?** Current schema has no optimistic locking; add version field if concurrent edits needed.
3. **Chat history pagination?** How many messages to load initially (10, 100, infinite)?
4. **SSE browser compatibility?** IE11 not supported; is that acceptable?
5. **Tailwind customization scope?** Should custom theme be in `tailwind.config.js` or inline utilities?

---

## Sources

- [HTMX hx-push-url](https://htmx.org/attributes/hx-push-url/)
- [HTMX hx-boost](https://htmx.org/attributes/hx-boost/)
- [HTMX SSE Extension](https://htmx.org/extensions/sse/)
- [HTMX Out-of-Band Swaps](https://htmx.org/attributes/hx-swap-oob/)
- [FastAPI + HTMX Guide — TestDriven.io](https://testdriven.io/blog/fastapi-htmx/)
- [FastAPI as a Hypermedia Driven App — Medium](https://medium.com/@strasbourgwebsolutions/fastapi-as-a-hypermedia-driven-application-w-htmx-jinja2templates-644c3bfa51d1/)
- [Glassmorphism with Tailwind CSS](https://flyonui.com/blog/glassmorphism-with-tailwind-css/)
- [HTMX Streaming Chat](https://www.adrianlyjak.com/p/htmx-chat/)
- [FastAPI-HTMX Extension — PyPI](https://pypi.org/project/fastapi-htmx/)
- [HTMX File Upload Example](https://htmx.org/examples/file-upload/)
- [Out-of-Band Updates with SSE — Medium](https://medium.com/@adam.giacom/pushing-the-limits-of-htmx-out-of-band-updates-via-sse-f7ca48ce711a)
