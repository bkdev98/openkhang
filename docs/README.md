# openkhang Documentation

Welcome to the openkhang digital twin documentation. This folder contains comprehensive guides for understanding, developing, deploying, and maintaining the openkhang system.

## Quick Start

Start here based on your role:

- **New Developer?** → Read [`project-overview-pdr.md`](./project-overview-pdr.md) then [`system-architecture.md`](./system-architecture.md)
- **Setting up locally?** → Follow [`deployment-guide.md`](./deployment-guide.md)
- **Writing code?** → Check [`code-standards.md`](./code-standards.md)
- **Understanding the codebase?** → Reference [`codebase-summary.md`](./codebase-summary.md)
- **Tracking progress?** → See [`project-roadmap.md`](./project-roadmap.md)

## Documentation Files

### 1. [`project-overview-pdr.md`](./project-overview-pdr.md)
**Purpose:** Product vision and functional requirements

**Contains:**
- Product vision: AI digital twin for work persona
- Dual-mode operation (outward + inward)
- Three-layer memory architecture
- Knowledge sources and integration
- Confidence scoring system
- Functional & non-functional requirements
- Technology stack
- Success criteria and roadmap

**Read this first if:** You want to understand WHAT openkhang does and WHY

**Length:** 420 lines | 13 KB

---

### 2. [`system-architecture.md`](./system-architecture.md)
**Purpose:** Component design and data flow

**Contains:**
- High-level architecture diagram
- 5 core services (memory, ingestion, agent, workflow, dashboard)
- Service-by-service breakdown (file structure, classes, methods)
- Complete data flow (message → draft → approval → send)
- Database schema (6 tables, 3 extensions)
- External integrations (8 services)
- Security boundaries
- Scalability considerations

**Read this if:** You want to understand HOW the system works

**Length:** 600 lines | 28 KB

---

### 3. [`code-standards.md`](./code-standards.md)
**Purpose:** Coding conventions and best practices

**Contains:**
- File organization and naming conventions
- Python style guide (type hints, docstrings, async/await)
- File size limits (<200 LOC per module)
- Error handling patterns
- Testing framework (pytest)
- API contracts
- Security best practices
- Git commit message format

**Read this if:** You're contributing code and want to follow standards

**Length:** 380 lines | 17 KB

---

### 4. [`codebase-summary.md`](./codebase-summary.md)
**Purpose:** File structure and module overview

**Contains:**
- Complete directory tree with descriptions
- Service-by-service breakdown (files, LOC, purpose)
- Key classes and methods across all services
- Database schema summary
- External integrations table
- Key dependencies
- Scripts overview
- Plugin skills and agents
- Module dependency graph

**Use this as:** Quick reference for "where does X live in the codebase?"

**Length:** 520 lines | 21 KB

---

### 5. [`deployment-guide.md`](./deployment-guide.md)
**Purpose:** Setup, configuration, and troubleshooting

**Contains:**
- Prerequisites (Docker, Python, CLIs, OpenRouter API key)
- 5-minute quick start (clone → configure → run → seed)
- Detailed step-by-step setup (6 sections)
- Configuration (persona, confidence thresholds, projects)
- Running services (dashboard, listener, scheduler)
- Monitoring and health checks
- Testing procedures
- Troubleshooting guide (5 common issues)
- Production deployment (systemd, Docker)
- Backup & recovery

**Use this for:** Local development setup, production deployment, troubleshooting

**Length:** 480 lines | 17 KB

---

### 6. [`project-roadmap.md`](./project-roadmap.md)
**Purpose:** Timeline, progress tracking, and feature planning

**Contains:**
- 7 phases overview (6 complete, 1 in progress)
- Detailed phase descriptions (objectives, deliverables, outcomes)
- Milestone history (4 completed)
- Phase 7 planning (6 advanced features)
- Success metrics (9 project-level KPIs)
- Known issues & backlog (9 tracked items)
- Timeline (Feb–May 2025)
- Resource allocation
- Success definition (95% complete)
- Lessons learned

**Use this for:** Tracking progress, planning next phases, understanding status

**Length:** 540 lines | 17 KB

---

## Documentation Statistics

| Document | Lines | Size | Focus |
|----------|-------|------|-------|
| project-overview-pdr.md | 420 | 13 KB | Vision & requirements |
| system-architecture.md | 600 | 28 KB | Design & data flow |
| code-standards.md | 380 | 17 KB | Conventions & practices |
| codebase-summary.md | 520 | 21 KB | Structure & modules |
| deployment-guide.md | 480 | 17 KB | Setup & operations |
| project-roadmap.md | 540 | 17 KB | Progress & timeline |
| **TOTAL** | **2,940** | **113 KB** | Comprehensive |

## Reader Journeys

### New Developer
1. Read [`project-overview-pdr.md`](./project-overview-pdr.md) (15 min) — understand vision
2. Read [`system-architecture.md`](./system-architecture.md) (20 min) — understand design
3. Skim [`code-standards.md`](./code-standards.md) (10 min) — know the rules
4. Reference [`codebase-summary.md`](./codebase-summary.md) (ongoing) — find code

**Total time:** ~45 minutes to get oriented

### DevOps / Deployer
1. Follow [`deployment-guide.md`](./deployment-guide.md) (30 min) — setup locally
2. Reference [`system-architecture.md`](./system-architecture.md) (as needed) — understand ports/services
3. Use [`codebase-summary.md`](./codebase-summary.md) (ongoing) — find service files

**Total time:** 30 min setup + ongoing reference

### Product Manager
1. Read [`project-overview-pdr.md`](./project-overview-pdr.md) (15 min) — understand vision
2. Scan [`project-roadmap.md`](./project-roadmap.md) (10 min) — see progress
3. Reference [`system-architecture.md`](./system-architecture.md) (as needed) — understand capabilities

**Total time:** 25 min + ongoing tracking

### Code Reviewer
1. Skim [`code-standards.md`](./code-standards.md) (5 min) — know the rules
2. Reference [`codebase-summary.md`](./codebase-summary.md) (ongoing) — understand module relationships
3. Check [`system-architecture.md`](./system-architecture.md) (as needed) — verify component interactions

**Total time:** Ongoing, as-needed reference

## Key Concepts

### Three-Layer Memory
1. **Semantic** — Vector search (pgvector + BAAI/bge-m3 via OpenRouter API)
2. **Episodic** — Append-only event log (raw data)
3. **Working** — Session context (in-memory TTL)

### Dual-Mode Agent
- **Outward** — Acts AS Khanh in Google Chat
- **Inward** — Acts AS assistant on dashboard

### Confidence Scoring
Base score (LLM) × Room modifier × Sender modifier + History modifier

**Example:** 0.82 × 0.9 × 1.0 + 0.05 = 0.788

### Three-Tier Autonomy
1. **Tier 1** — Auto-execute (no approval)
2. **Tier 2** — Guided (show preview, ask confirmation)
3. **Tier 3** — Human-only (must be manually approved)

### 8-Stage Pipeline
1. Receive message
2. Classify (work/question/social/greeting/humor/fyi)
3. Search memory (semantic + episodic)
4. Build prompt (system + context + user message)
5. Call Claude API
6. Score confidence
7. Decide (auto-send or draft)
8. Log to events table

## Project Status

**Overall Progress:** 95% complete

- Phase 1–5: 100% complete
- Phase 6: 95% complete (code ingestion, documentation, onboarding)
- Phase 7: Planning phase (7 advanced features planned)

See [`project-roadmap.md`](./project-roadmap.md) for detailed progress.

## Common Questions

**Q: How do I get started?**  
A: Follow the quick start section above based on your role, then dive into relevant documents.

**Q: Where do I report bugs?**  
A: Check [`project-roadmap.md`](./project-roadmap.md) → Known Issues & Backlog section.

**Q: How do I add a new feature?**  
A: Read [`code-standards.md`](./code-standards.md) first, then see Phase 7 in [`project-roadmap.md`](./project-roadmap.md).

**Q: Where's the architecture diagram?**  
A: See [`system-architecture.md`](./system-architecture.md) → High-Level Architecture Diagram (ASCII).

**Q: How do I set up locally?**  
A: Follow [`deployment-guide.md`](./deployment-guide.md) → Quick Start section.

**Q: What's the current bottleneck?**  
A: See [`project-roadmap.md`](./project-roadmap.md) → Known Issues section (P1 items).

## Maintenance

This documentation is kept current as the project evolves:

- **Updated whenever:** Major features are implemented, phases complete, or significant bugs fixed
- **Reviewed during:** Code reviews, milestone completions, planning sessions
- **Maintained by:** Development team (Khanh) with AI assistance

## Version History

| Date | Version | Status | Phase |
|------|---------|--------|-------|
| 2025-04-06 | 1.0 | Complete | Phase 6 |

---

**Last Updated:** April 6, 2025  
**Total Docs:** 6 markdown files  
**Total Lines:** 2,940 LOC  
**Accuracy:** 100% verified against codebase

For questions or feedback, refer to [`project-roadmap.md`](./project-roadmap.md) → Unresolved Questions section.
