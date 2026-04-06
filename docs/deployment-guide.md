# Deployment Guide: openkhang

## Prerequisites

| Tool | Install | Min Version | Purpose |
|------|---------|-------------|---------|
| Docker + Compose | `brew install docker` | 24.0 | Postgres, Redis, Ollama, Synapse |
| Ollama | `brew install ollama` | 0.1.0 | Local bge-m3 embeddings (native M2) |
| Python | System or `brew install python@3.13` | 3.12+ | Services runtime |
| jira CLI | `brew install ankitpokhrel/jira-cli/jira` | 1.0+ | Jira ingestion |
| glab | `brew install glab` | 1.0+ | GitLab ingestion |
| git | System | 2.30+ | Repository cloning |

**Verify installations:**
```bash
docker --version              # Docker 24.x
ollama --version             # 0.1.x
python3 --version            # 3.12+
jira version                  # 1.x
glab version                  # 1.x
git --version                 # 2.30+
```

## Quick Start (5 minutes)

### 1. Clone and Configure

```bash
# Clone repository
git clone https://github.com/bkdev98/openkhang.git
cd openkhang

# Copy environment template
cp .env.example .env

# Edit .env with your API keys
nano .env
```

**Required in `.env`:**
```bash
# Core services
POSTGRES_DSN=postgresql://openkhang:password@localhost:5433/openkhang
REDIS_URL=redis://localhost:6379
OLLAMA_BASE_URL=http://localhost:11434

# External APIs
MEM0_API_KEY=sk_...          # Get from mem0.ai
CLAUDE_API_KEY=sk-ant-...    # Get from console.anthropic.com
JIRA_API_TOKEN=ATATT...      # Jira API token
JIRA_INSTANCE_URL=https://jira.momo.dev
GITLAB_TOKEN=glpat_...       # GitLab personal access token
GITLAB_INSTANCE_URL=https://gitlab.momo.dev
CONFLUENCE_TOKEN=ATCATT...   # Confluence API token
CONFLUENCE_INSTANCE_URL=https://confluence.momo.dev
GOOGLE_CHAT_API_KEY=...      # (used by bridge)
MATRIX_HOMESERVER=http://localhost:8008

# Application
APP_ENV=development
LOG_LEVEL=INFO
DEBUG=false
```

### 2. Run Onboarding

```bash
# Full setup: bridge, memory, services, dashboard
bash scripts/onboard.sh

# This will:
# 1. Start docker-compose (postgres, redis, ollama)
# 2. Initialize bridge (~/.mautrix-googlechat/docker-compose.yml)
# 3. Create Python venv + install dependencies
# 4. Initialize Postgres schema + Mem0
# 5. Start matrix-listener daemon
# 6. Seed initial knowledge (optional)
```

**Expected output:**
```
✓ Docker services started (postgres:5433, redis:6379, ollama:11434)
✓ Bridge initialized (synapse:8008, bridge:8090)
✓ Python venv created
✓ Postgres schema initialized
✓ Mem0 API connected
✓ matrix-listener started
✓ Ready to go! Start dashboard with: bash scripts/run-dashboard.sh
```

### 3. Start the Dashboard

```bash
# In a new terminal
bash scripts/run-dashboard.sh

# Opens http://localhost:8000
# Shows:
# - Activity feed
# - Draft queue (empty initially)
# - Service health
```

### 4. Start Chat Listener

```bash
# In another terminal (or background)
python3 scripts/matrix-listener.py --daemon

# Or run in foreground for debugging:
python3 scripts/matrix-listener.py --verbose
```

### 5. Seed Initial Knowledge

```bash
# Ingest Jira tickets
services/.venv/bin/python3 scripts/seed-knowledge.py --source jira --limit 50

# Ingest GitLab MRs
services/.venv/bin/python3 scripts/seed-knowledge.py --source gitlab --limit 50

# Ingest Confluence pages
services/.venv/bin/python3 scripts/seed-knowledge.py --source confluence --limit 100

# Ingest source code (3 projects)
services/.venv/bin/python3 scripts/seed-code.py
```

You're now ready to test! Send a message in Google Chat and watch it appear in the dashboard.

## Detailed Setup

### Step 1: Docker Services

```bash
# Start infrastructure (postgres, redis, ollama)
docker-compose up -d

# Verify services
docker ps
# postgres:5433, redis:6379, ollama:11434 should be running

# Check Ollama has bge-m3 model
curl http://localhost:11434/api/models
# Response should include: "name": "bge-m3:latest"

# If bge-m3 not present, pull it:
ollama pull bge-m3
```

**Database Initialization:**
```bash
# Connect to Postgres
psql -h localhost -p 5433 -U openkhang -d openkhang

# Verify schema created
\dt  # Should show: events, draft_replies, sync_state, workflow_instances, audit_log

# If empty, run schema manually:
psql -h localhost -p 5433 -U openkhang -d openkhang < services/memory/schema.sql
```

### Step 2: Bridge Setup

```bash
# Create bridge directory
mkdir -p ~/.mautrix-googlechat
cd ~/.mautrix-googlechat

# Run setup script
bash ../../openkhang/scripts/setup-bridge.sh

# This creates:
# - docker-compose.yml (synapse + mautrix-googlechat)
# - registration.yaml (bridge registration)
# - homeserver.yaml (synapse config)

# Start bridge
docker-compose up -d

# Verify
curl http://localhost:8008/_matrix/client/r0/sync  # Synapse response
curl http://localhost:8090/_matrix/app/v1/ping     # Bridge response
```

### Step 3: Python Environment

```bash
# Create and activate venv
cd openkhang/services
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Verify
python3 -c "import asyncpg, httpx, anthropic, mem0; print('✓ All imports OK')"
```

### Step 4: Memory Service

```bash
# Initialize Mem0 (creates tables automatically)
services/.venv/bin/python3 -c "
import asyncio
from dotenv import load_dotenv
load_dotenv()
from services.memory.config import MemoryConfig
from services.memory.client import MemoryClient

async def init():
    config = MemoryConfig.from_env()
    client = MemoryClient(config)
    await client.connect()
    print('✓ Memory client connected')
    await client.close()

asyncio.run(init())
"

# Test search (should be empty initially)
services/.venv/bin/python3 -c "
import asyncio
from dotenv import load_dotenv
load_dotenv()
from services.memory.config import MemoryConfig
from services.memory.client import MemoryClient

async def test():
    config = MemoryConfig.from_env()
    client = MemoryClient(config)
    await client.connect()
    results = await client.search('transaction history')
    print(f'Found {len(results)} results')
    await client.close()

asyncio.run(test())
"
```

### Step 5: Start Services

```bash
# Terminal 1: Dashboard (foreground for logs)
bash scripts/run-dashboard.sh
# Runs: uvicorn services.dashboard.app:app --reload --port 8000
# Opens: http://localhost:8000

# Terminal 2: Chat Listener (background)
python3 scripts/matrix-listener.py --daemon
# Or foreground for debugging:
python3 scripts/matrix-listener.py --verbose

# Terminal 3: Ingestion Scheduler (optional, for polling)
services/.venv/bin/python3 -c "
from services.ingestion.scheduler import IngestScheduler
import asyncio
scheduler = IngestScheduler()
asyncio.run(scheduler.start())
"
```

### Step 6: Seed Knowledge

```bash
# Option A: Seed recent Jira tickets
services/.venv/bin/python3 scripts/seed-knowledge.py \
  --source jira \
  --project PROJ \
  --limit 50 \
  --since-days 30

# Option B: Seed entire chat history (one-time bulk)
services/.venv/bin/python3 scripts/full-chat-seed.py \
  --export-file chat-export.json \
  --rooms eng-chat,eng-support

# Option C: Seed source code
services/.venv/bin/python3 scripts/seed-code.py \
  --projects momo-app,transactionhistory \
  --force

# Check seeding progress
services/.venv/bin/python3 -c "
import asyncio
from services.memory.client import MemoryClient
from services.memory.config import MemoryConfig

async def check():
    config = MemoryConfig.from_env()
    client = MemoryClient(config)
    await client.connect()
    
    # Count memories
    results = await client.search('', top_k=1000)
    print(f'Total memories: {len(results)}')
    
    await client.close()

asyncio.run(check())
"
```

## Configuration

### Persona (`config/persona.yaml`)

Customize the twin's identity, style, and constraints:

```yaml
name: "Khanh Bui"
role: "Senior Mobile Engineer"
company: "MoMo"

style:
  formality: "casual-professional"      # formal|neutral|casual-professional|casual
  emoji_usage: "moderate"                # none|minimal|moderate|frequent
  response_length: "concise"             # verbose|medium|concise|ultra-concise
  humor: "occasional"                    # none|dry|occasional|frequent
  mix_languages: true                    # Vietnamese + English code-switching

identity_facts:
  - "Works on mobile app platform team at MoMo fintech"
  - "Prefers async communication"

never_do:
  - "Promise specific deadlines without evidence"
  - "Claim to have attended unlogged meetings"
  - "Share confidential information"
  - "Make commitments without checking code state"
  # ... 6 more hard constraints

group_chat_rules:
  auto_reply_only: ["request", "question"]
  ignore_in_group: ["social", "humor", "greeting", "fyi"]
  cautious_titles: ["Manager", "Lead", "Director"]

uncertainty_phrases:
  vietnamese:
    - "mình check lại rồi reply sau nhé"
    - "để mình xem lại rồi confirm"
  english:
    - "let me check and get back to you"
    - "I'll look into it"
```

### Confidence Thresholds (`config/confidence_thresholds.yaml`)

Control which replies auto-send vs go to draft:

```yaml
default_threshold: 0.75       # Global default (0.0 - 1.0)

# After graduation (20+ reviews, >90% approval):
graduated_spaces:
  "!room123:localhost": 0.70  # Lower = more auto-sends in this space
  "!room456:localhost": 0.80
```

Modify at runtime via dashboard Settings (future) or edit and reload.

### Projects (`config/projects.yaml`)

Configure code projects to index:

```yaml
projects:
  momo-app:
    path: ~/Projects/momo-app
    language: kotlin
    description: "MoMo App Platform"
    include_paths:
      - packages/momo-compose/...transaction_history
      - packages/momo-compose/...payment/promotion
    extensions: [".kt"]
    exclude_patterns: ["node_modules", ".gradle", "build"]

  transactionhistory:
    path: ~/Projects/transactionhistory
    language: kotlin/typescript
    include_paths: []              # Index all
    extensions: [".kt", ".ts"]
    exclude_patterns: ["node_modules", "build", "dist"]
```

## Running Services

### Dashboard

```bash
# Development mode (hot reload)
bash scripts/run-dashboard.sh

# Or manually:
cd services
source .venv/bin/activate
uvicorn dashboard.app:app --reload --port 8000 --log-level info
```

Access at: **http://localhost:8000**

**Routes:**
- `/` — Home (activity feed, draft count, health)
- `/drafts` — Draft queue
- `/events` (SSE) — Real-time updates
- `/health` — Service health
- `/twin-chat` — Query agent about memories

### Chat Listener

```bash
# Daemon (background)
python3 scripts/matrix-listener.py --daemon

# Check if running
ps aux | grep matrix-listener

# View logs
tail -f ~/.openkhang/logs/matrix-listener.log

# Foreground (for debugging)
python3 scripts/matrix-listener.py --verbose

# Graceful shutdown
kill $(pgrep -f matrix-listener)
```

### Ingestion Scheduler

```bash
# Run polling ingestors (jira, gitlab, confluence)
services/.venv/bin/python3 -c "
from services.ingestion.scheduler import IngestScheduler
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
scheduler = IngestScheduler()
asyncio.run(scheduler.start())
"

# Or via systemd (optional)
sudo systemctl start openkhang-ingestion
```

## Monitoring

### Service Health

**Via dashboard:**
- Visit http://localhost:8000 → check "Health" panel
- Shows: postgres, redis, ollama, matrix-listener, dashboard uptime

**Via CLI:**
```bash
# Postgres
psql -h localhost -p 5433 -U openkhang -c "SELECT 1;"

# Redis
redis-cli ping

# Ollama
curl http://localhost:11434/api/models

# Matrix
curl http://localhost:8008/_matrix/client/r0/sync

# Dashboard
curl http://localhost:8000/health
```

### Activity Monitoring

```bash
# Check recent events
psql -h localhost -p 5433 -U openkhang -c "
SELECT source, event_type, COUNT(*) as count
FROM events
WHERE created_at > now() - interval '1 hour'
GROUP BY source, event_type
ORDER BY created_at DESC;
"

# Check draft queue
psql -h localhost -p 5433 -U openkhang -c "
SELECT status, COUNT(*) as count FROM draft_replies GROUP BY status;
"

# Check last sync
psql -h localhost -p 5433 -U openkhang -c "
SELECT source, last_synced_at, item_count FROM sync_state;
"
```

### Logs

```bash
# Dashboard logs (running in terminal)
# Appears in stdout where you ran: bash scripts/run-dashboard.sh

# Chat listener logs
tail -f ~/.openkhang/logs/matrix-listener.log

# Docker logs
docker logs openkhang-postgres
docker logs openkhang-redis
docker logs openkhang-ollama

# Bridge logs
cd ~/.mautrix-googlechat
docker logs openkhang-synapse
docker logs openkhang-mautrix
```

## Testing

### Unit Tests

```bash
# Run all tests
services/.venv/bin/python3 -m pytest services/ -v

# Run specific component
services/.venv/bin/python3 -m pytest services/agent/tests/ -v

# With coverage
services/.venv/bin/python3 -m pytest services/ --cov=services --cov-report=html
```

### Manual Testing

**Send a test message:**
1. Open Google Chat
2. Send message in a space where Khanh is a member
3. Check dashboard at http://localhost:8000 — should see draft in queue
4. Approve draft → message sent back

**Query twin chat:**
1. Go to http://localhost:8000 → Twin Chat
2. Ask: "What do we know about transaction history?"
3. Should return relevant memories

**Check health:**
1. Go to http://localhost:8000 → Home
2. Service health panel should show all green

## Troubleshooting

### Postgres Connection Error

```bash
# Check if postgres is running
docker ps | grep postgres

# Restart docker-compose
docker-compose restart postgres

# Verify connection
psql -h localhost -p 5433 -U openkhang -c "SELECT 1;"
```

### Ollama Not Found

```bash
# Check if ollama is running
curl http://localhost:11434/api/models

# Pull bge-m3 model
ollama pull bge-m3

# Verify
ollama ls | grep bge-m3
```

### Matrix/Bridge Not Responding

```bash
# Check bridge logs
cd ~/.mautrix-googlechat
docker-compose logs synapse
docker-compose logs mautrix-googlechat

# Restart bridge
docker-compose restart

# Verify connectivity
curl http://localhost:8008/_matrix/client/r0/sync
```

### Dashboard 404 on `/`

```bash
# Check if dashboard is running
curl http://localhost:8000/health

# Restart dashboard
bash scripts/run-dashboard.sh
```

### No Drafts Appearing

**Checklist:**
1. [ ] Chat listener is running: `ps aux | grep matrix-listener`
2. [ ] Message sent to a room where Khanh is a member
3. [ ] Postgres has events: `psql ... -c "SELECT COUNT(*) FROM events;"`
4. [ ] Dashboard health shows all green
5. [ ] Check logs for errors: `tail -f ~/.openkhang/logs/*.log`

### Confidence Score Always 0

**Check:**
1. Is Claude API key valid? `echo $CLAUDE_API_KEY | head -c 20`
2. Are API calls being made? Check logs for "Calling Claude"
3. Test memory search: `services/.venv/bin/python3 scripts/test-memory.py`

## Production Deployment

### Using Systemd

Create `/etc/systemd/system/openkhang-dashboard.service`:

```ini
[Unit]
Description=openkhang Dashboard
After=network.target docker.service

[Service]
Type=simple
User=khanh
WorkingDirectory=/home/khanh/Projects/openkhang
ExecStart=/home/khanh/Projects/openkhang/services/.venv/bin/python3 \
  -m uvicorn services.dashboard.app:app --port 8000 --workers 4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl enable openkhang-dashboard
sudo systemctl start openkhang-dashboard
sudo systemctl status openkhang-dashboard
```

### Using Docker

Build Docker image (future): `docker build -t openkhang:latest .`

### Monitoring with Uptime Kuma

Register dashboard at monitoring service:

```
GET http://localhost:8000/health
Expected: {"status": "ok"}
Check interval: 5 minutes
```

## Scaling

**Current limits:**
- Single Python process (~500MB heap)
- ~100 messages/min throughput
- ~10GB Postgres storage/year (estimate: 100 msgs/day)

**Future improvements:**
- Separate services into microservices
- Kubernetes deployment
- Worker pool for ingestion
- Webhook integration (real-time instead of polling)

## Backup & Recovery

### Database Backup

```bash
# Backup Postgres
pg_dump -h localhost -p 5433 -U openkhang openkhang > backup.sql

# Restore
psql -h localhost -p 5433 -U openkhang < backup.sql
```

### Configuration Backup

```bash
# Backup config directory
tar -czf config-backup.tar.gz config/

# Backup .env
cp .env .env.backup
```

### Full System Recovery

```bash
# 1. Stop services
docker-compose down
python3 scripts/matrix-listener.py --stop

# 2. Restore config + .env
tar -xzf config-backup.tar.gz
cp .env.backup .env

# 3. Start from scratch (onboarding will recreate everything)
bash scripts/onboard.sh

# 4. Restore database (if you have a backup)
psql -h localhost -p 5433 -U openkhang < backup.sql
```

## Support & Debugging

**Report issues with:**
1. Service health check output
2. Recent logs (last 100 lines)
3. Postgres event count: `SELECT COUNT(*) FROM events;`
4. Redis keys: `redis-cli KEYS "openkhang:*" | head -20`
5. Description of what you were doing when error occurred
