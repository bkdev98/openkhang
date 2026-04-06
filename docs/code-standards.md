# Code Standards & Conventions

## File Organization

```
openkhang/
├── services/
│   ├── .venv/                 # Shared Python virtual environment
│   ├── requirements.txt        # All dependencies (shared)
│   ├── __init__.py             # services is a package
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── client.py          # Public API: MemoryClient class
│   │   ├── config.py          # Config loading from .env
│   │   ├── episodic.py        # Episodic event store
│   │   ├── working.py         # Working memory (in-memory TTL)
│   │   ├── schema.sql         # Postgres schema
│   │   └── ingest-chat-history.py  # One-off ingestion script
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── base.py            # BaseIngestor abstract class
│   │   ├── chat.py            # ChatIngestor
│   │   ├── jira.py            # JiraIngestor
│   │   ├── gitlab.py          # GitLabIngestor
│   │   ├── confluence.py       # ConfluenceIngestor
│   │   ├── code.py            # CodeIngestor
│   │   ├── chunker.py         # SemanticChunker utility
│   │   ├── entity.py          # Entity dataclass
│   │   ├── scheduler.py       # IngestScheduler orchestrator
│   │   ├── sync_state.py      # SyncState tracker
│   │   └── tests/             # Unit tests
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── pipeline.py        # Main orchestrator (300+ LOC, consider split)
│   │   ├── classifier.py      # MessageClassifier
│   │   ├── confidence.py      # ConfidenceScorer
│   │   ├── prompt_builder.py  # PromptBuilder
│   │   ├── llm_client.py      # LLMClient (Claude API)
│   │   ├── draft_queue.py     # DraftQueue manager
│   │   ├── matrix_sender.py   # MatrixSender
│   │   ├── prompts/           # Prompt templates
│   │   │   ├── outward_system.md
│   │   │   └── inward_system.md
│   │   └── tests/
│   ├── workflow/
│   │   ├── __init__.py
│   │   ├── state_machine.py   # StateMachine parser
│   │   ├── action_executor.py # ActionExecutor
│   │   ├── workflow_engine.py # WorkflowEngine orchestrator
│   │   ├── workflow_persistence.py  # Postgres integration
│   │   └── audit_log.py       # AuditLog
│   └── dashboard/
│       ├── __init__.py
│       ├── app.py             # FastAPI main app
│       ├── dashboard_services.py  # High-level service logic
│       ├── inbox_relay.py     # Inbox consolidation
│       ├── agent_relay.py     # Agent direct communication
│       ├── health_checker.py  # Service health probing
│       ├── twin_chat.py       # Twin chat interface
│       └── templates/
│           ├── base.html
│           ├── index.html
│           └── partials/      # HTMX components
├── config/
│   ├── persona.yaml           # Identity, style, constraints
│   ├── confidence_thresholds.yaml  # Per-room thresholds
│   ├── projects.yaml          # Code projects config
│   ├── style_examples.jsonl   # Chat examples for tuning
│   └── workflows/
│       ├── chat-to-jira.yaml
│       └── pipeline-failure.yaml
├── scripts/
│   ├── onboard.sh             # Setup everything
│   ├── setup-bridge.sh        # Bridge + Synapse setup
│   ├── setup-memory.sh        # Memory service setup
│   ├── run-dashboard.sh       # Start dashboard
│   ├── matrix-listener.py     # Chat listener daemon
│   ├── seed-knowledge.py      # Ingest initial knowledge
│   ├── seed-code.py           # Ingest source code
│   └── full-chat-seed.py      # Bulk chat history import
├── agents/
│   ├── bug-investigator.md    # Claude Code agent
│   ├── chat-categorizer.md
│   ├── sprint-monitor.md
│   └── pipeline-fixer.md
├── skills/
│   ├── chat-autopilot/
│   ├── jira-knowledge/
│   ├── gitlab-knowledge/
│   ├── confluence-search/
│   └── openkhang-status/
├── docker-compose.yml         # Postgres, Redis
├── .env.example               # Configuration template
├── .gitignore
└── README.md
```

## Python Code Style

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Module | `snake_case.py` | `message_classifier.py` |
| Class | `PascalCase` | `MessageClassifier`, `MemoryClient` |
| Function | `snake_case` | `classify_message()`, `add_memory()` |
| Variable | `snake_case` | `sender_role`, `confidence_score` |
| Constant | `UPPER_SNAKE_CASE` | `DEFAULT_THRESHOLD`, `MAX_RETRIES` |
| Private | `_leading_underscore` | `_internal_helper()`, `_cache` |
| Protected | (rare) `_name` | Avoid; use public or private |

### Type Hints (Mandatory)

All functions must have type hints for parameters and returns:

```python
from typing import Optional, List, Dict, AsyncIterator
from dataclasses import dataclass

@dataclass
class Message:
    text: str
    sender: str
    timestamp: str
    room_id: str

async def classify_message(msg: Message) -> str:
    """Classify message into: work, question, social, humor, greeting, fyi"""
    return "work"

async def search_memory(
    query: str,
    top_k: int = 5,
    min_score: float = 0.5
) -> List[Dict[str, Any]]:
    """Search semantic memory; return ranked results"""
    return []

def get_confidence_modifier(
    room_id: str,
    sender_role: Optional[str] = None
) -> float:
    """Calculate confidence modifier based on room type and sender"""
    return 1.0
```

### Docstrings (Triple-Quoted)

Use Google-style docstrings for public APIs:

```python
async def add_memory(
    self,
    memory_text: str,
    metadata: Optional[Dict[str, Any]] = None,
    source: str = "chat"
) -> str:
    """Add a memory to the semantic store and episodic log.
    
    Args:
        memory_text: The text to store (will be embedded).
        metadata: Optional dict with context (e.g., room_id, sender).
        source: Source identifier ('chat', 'jira', 'gitlab', 'confluence', 'code').
    
    Returns:
        UUID of the created memory record.
    
    Raises:
        ValueError: If memory_text is empty.
        ConnectionError: If Postgres connection fails.
    
    Example:
        >>> client = MemoryClient(config)
        >>> await client.connect()
        >>> memory_id = await client.add_memory(
        ...     "Discussed API redesign for transactions",
        ...     metadata={"room_id": "!abc:localhost"},
        ...     source="chat"
        ... )
    """
```

### Error Handling

Use try/except with specific exception types:

```python
async def fetch_jira_issue(issue_id: str) -> Dict[str, Any]:
    """Fetch issue from Jira; retry on transient errors."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = httpx.get(
                f"https://jira.momo.dev/rest/api/3/issues/{issue_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue
            raise ConnectionError(f"Jira timeout after {max_retries} retries") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:  # Rate limit
                await asyncio.sleep(10)
                continue
            raise ValueError(f"Jira API error: {e.response.text}") from e
```

### Async/Await (Required for I/O)

All I/O operations must be async:

```python
async def process_chat_message(msg: Message) -> Optional[str]:
    """Process message; return draft reply or None."""
    # Call memory (I/O)
    context = await self.memory.search(msg.text, top_k=5)
    
    # Call LLM (I/O)
    response = await self.llm_client.generate(
        system_prompt=self.build_system_prompt(),
        user_message=msg.text,
        context=context
    )
    
    # Compute confidence (CPU-bound, still async for coordination)
    confidence = await self.confidence_scorer.score(
        response=response,
        msg=msg,
        context=context
    )
    
    return response if confidence > self.threshold else None
```

### File Size Limit (< 200 LOC)

If a module exceeds 200 lines, split it:

**Before (too large):**
```python
# pipeline.py (450 lines)
class Pipeline:
    def classify(self): ...
    def search_memory(self): ...
    def build_prompt(self): ...
    def call_llm(self): ...
    def score_confidence(self): ...
    def queue_draft(self): ...
    def send_reply(self): ...
```

**After (split):**
```python
# pipeline.py (120 lines)
class Pipeline:
    def __init__(self, classifier, memory, llm, confidence, draft_queue):
        self.classifier = classifier
        self.memory = memory
        self.llm = llm
        self.confidence = confidence
        self.draft_queue = draft_queue
    
    async def process(self, msg: Message) -> Optional[str]:
        classification = self.classifier.classify(msg)
        context = await self.memory.search(msg.text)
        response = await self.llm.generate(...context...)
        score = await self.confidence.score(...response...)
        
        if score >= self.confidence.threshold:
            await self.draft_queue.enqueue(...)
        return response

# classifier.py (80 lines) - extracted
# memory.py (100 lines) - reused from memory service
# confidence.py (120 lines) - extracted
```

### Imports

Organize imports in this order:

```python
# Standard library
import asyncio
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

# Third-party
import httpx
import psycopg
from pydantic import BaseModel, Field

# Local
from services.memory.client import MemoryClient
from services.memory.config import MemoryConfig
from . import utils  # Relative import within package
```

## Configuration Management

### Environment Variables (`.env`)

```bash
# Core services
POSTGRES_DSN=postgresql://openkhang:password@localhost:5433/openkhang
REDIS_URL=redis://localhost:6379
EMBEDDING_API_KEY=sk-or-...
EMBEDDING_API_URL=https://openrouter.ai/api/v1

# External APIs
MEM0_API_KEY=sk_...
CLAUDE_API_KEY=sk-ant-...
JIRA_API_TOKEN=ATATT...
GITLAB_TOKEN=glpat_...
CONFLUENCE_TOKEN=ATCATT...
GOOGLE_CHAT_API_KEY=...
MATRIX_HOMESERVER=http://localhost:8008

# Application
APP_ENV=development  # or production
LOG_LEVEL=INFO
DEBUG=false
```

### YAML Configuration (`config/`)

**Never use env vars for defaults; use YAML:**

```yaml
# config/persona.yaml
name: "Khanh Bui"
role: "Senior Mobile Engineer"
style:
  formality: "casual-professional"
  emoji_usage: "moderate"
  response_length: "concise"

# Load in Python:
import yaml

with open("config/persona.yaml") as f:
    config = yaml.safe_load(f)
```

## Testing

### Unit Tests

Place tests in `services/{component}/tests/`:

```python
# services/agent/tests/test_classifier.py
import pytest
from services.agent.classifier import MessageClassifier
from services.memory.config import MemoryConfig

@pytest.fixture
def classifier():
    return MessageClassifier()

@pytest.mark.asyncio
async def test_classify_work_request(classifier):
    msg = "Can you review the transaction history PR?"
    classification = await classifier.classify(msg)
    assert classification == "request"

@pytest.mark.asyncio
async def test_classify_social(classifier):
    msg = "Nice catch on that bug! 🎉"
    classification = await classifier.classify(msg)
    assert classification == "social"

@pytest.mark.asyncio
async def test_classify_greeting(classifier):
    msg = "Good morning everyone!"
    classification = await classifier.classify(msg)
    assert classification == "greeting"
```

### Run Tests

```bash
# From openkhang root
services/.venv/bin/python3 -m pytest services/agent/tests/ -v

# With coverage
services/.venv/bin/python3 -m pytest services/agent/tests/ --cov=services.agent --cov-report=html
```

## Logging

Use Python's `logging` module; configure centrally:

```python
import logging

logger = logging.getLogger(__name__)

async def process_message(msg: Message) -> None:
    logger.debug(f"Received message from {msg.sender}: {msg.text[:50]}...")
    
    try:
        result = await classify(msg)
        logger.info(f"Classified as: {result}")
    except Exception as e:
        logger.error(f"Classification failed: {e}", exc_info=True)
        raise
```

**Log Levels:**
- `DEBUG` — Detailed flow (for development)
- `INFO` — Significant events (service startup, message received)
- `WARNING` — Unexpected but recoverable (API retry, missing field)
- `ERROR` — Failures that need attention (API down, DB error)
- `CRITICAL` — System-level failures (out of memory, security breach)

## Dependencies & Requirements

All Python dependencies in single `services/requirements.txt`:

```
# Core
python-dotenv==1.0.0
pydantic==2.5.0
asyncio-contextmanager==1.0.0

# Database
psycopg[binary]==3.1.12
pgvector==0.2.4
asyncpg==0.29.0

# HTTP
httpx==0.25.2
aiohttp==3.9.1

# LLM
anthropic==0.25.0
openai==1.3.0  # For embeddings if needed

# CLI tools (optional, for scripts)
jira-cli==1.0.0
glab==1.0.0

# Testing
pytest==7.4.3
pytest-asyncio==0.23.1
pytest-cov==4.1.0

# Utilities
pyyaml==6.0
redis==5.0.1
```

Install with:
```bash
cd services
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## API Contracts

### Return Types (Standardized)

**Success response:**
```python
{
    "status": "success",
    "data": {...},
    "timestamp": "2025-04-06T14:30:00Z"
}
```

**Error response:**
```python
{
    "status": "error",
    "error": "invalid_request",
    "message": "Message text cannot be empty",
    "code": 400,
    "timestamp": "2025-04-06T14:30:00Z"
}
```

### Database Models

Use Pydantic for schemas:

```python
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class DraftReply(BaseModel):
    id: str = Field(..., description="UUID")
    room_id: str
    original_message: str
    draft_text: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = Field(..., pattern="^(pending|approved|rejected|edited)$")
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "uuid-...",
                "room_id": "!abc123:localhost",
                "original_message": "Can you review the PR?",
                "draft_text": "I'll take a look shortly.",
                "confidence": 0.85,
                "evidence": [{"source": "chat_history", "score": 0.9}],
                "status": "pending",
                "created_at": "2025-04-06T14:30:00Z"
            }
        }
```

## Security Best Practices

1. **Never log secrets:** No API keys, tokens, passwords in logs
   ```python
   # ❌ Bad
   logger.info(f"Connecting to Jira with token {api_key}")
   
   # ✓ Good
   logger.info(f"Connecting to Jira (token length: {len(api_key)})")
   ```

2. **Validate all inputs:** Type hints + runtime checks
   ```python
   if not isinstance(confidence, float) or not (0.0 <= confidence <= 1.0):
       raise ValueError(f"Invalid confidence: {confidence}")
   ```

3. **Use timeouts on external calls:**
   ```python
   response = httpx.get(..., timeout=10.0)
   ```

4. **Sanitize before logging/display:**
   ```python
   safe_message = message.text[:100] + ("..." if len(message.text) > 100 else "")
   ```

## Git Commit Messages

Use Conventional Commits format:

```
feat: add memory search with confidence scoring
  
Implement semantic search in MemoryClient using pgvector.
Add confidence modifier for room type (DM vs group).

Closes #15

fix: retry Jira API calls on timeout
chore: update requirements.txt dependencies
docs: clarify confidence scoring algorithm
refactor: extract PromptBuilder into separate module
test: add unit tests for confidence scoring
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

## Checklist Before Committing Code

- [ ] All functions have type hints and docstrings
- [ ] File size < 200 LOC (or split into modules)
- [ ] All I/O is async (httpx, postgres, redis)
- [ ] Error handling for external API calls (retry, timeout, specific exception)
- [ ] No hardcoded secrets in code or logs
- [ ] Tests pass locally: `pytest services/{component}/tests/ -v`
- [ ] Linting passes: `python3 -m flake8 services/ --ignore=E501,W503`
- [ ] Commit message follows Conventional Commits format
- [ ] Imports organized: stdlib, third-party, local
