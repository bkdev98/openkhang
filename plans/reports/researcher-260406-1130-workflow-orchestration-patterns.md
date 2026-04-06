# Workflow Orchestration & Integration Patterns for OpenKhang
**Research Report** | Apr 6, 2025 | Status: Complete

---

## Executive Summary

OpenKhang currently operates as **independent tool blocks** (Chat, Jira, GitLab, Confluence) with basic status aggregation. To achieve true "digital twin" autonomy:

1. **Adopt event-driven orchestration** (not polling) with durable execution semantics
2. **Build a unified entity graph** to link Jira tickets → GitLab MRs → Chat threads → Confluence pages
3. **Implement confidence-tiered autonomy** with approval workflows based on action risk
4. **Create a learning persona model** to capture user patterns, communication style, and work preferences

**Recommendation Ranking:**
- **Tier 1 (High Priority):** Event-driven orchestration + entity graph (enables core workflows)
- **Tier 2 (Medium Priority):** Autonomy guardrails + confidence scoring (enables safe autonomous action)
- **Tier 3 (Nice-to-Have):** Digital twin persona learning (enables long-term adaptation)

---

## 1. Workflow Orchestration: Event-Driven vs. Polling vs. Hybrid

### Current State
OpenKhang uses **polling-based monitoring** (`/loop 5m /chat-scan`, `/pipeline-watch` periodic checks). This is adequate for low-frequency updates but has scaling and latency issues.

### Pattern Analysis

#### 1A. Event-Driven Orchestration (Recommended)
**Definition:** Workflows triggered by external events (new chat message, ticket created, pipeline failed), with immediate propagation through message queues.

**Strengths:**
- Low latency: workflows begin milliseconds after event
- Scalable: no continuous polling overhead
- Natural fit for multi-tool workflows (chat message → auto-create Jira → start code session)
- Audit trail: every event is logged immutably

**Weaknesses:**
- Requires event source setup (Jira webhooks, GitLab event streams, Matrix API listeners)
- Higher operational complexity for local deployment
- Must handle retries and delivery guarantees

**Adoption Recommendation for OpenKhang:**
Use **hybrid polling + event-driven**:
- Webhooks for critical events (pipeline fail, ticket created, urgent chat message)
- Polling for lower-urgency aggregation (sprint health, MR list)

---

#### 1B. Durable Execution Pattern
**Definition:** Guarantee workflow completion by replaying event history if a worker crashes.

**Key Players (2025):**
- **Temporal.io**: Stateful cluster model, self-hosted or managed cloud
  - Pros: battle-tested for complex workflows, sophisticated retry/timeout logic
  - Cons: complex setup, steep learning curve, requires infrastructure
  - Deployment: ~30 min for self-hosted development server
  
- **Inngest**: Serverless-first, stateless design, no backend to manage
  - Pros: 5-minute setup, simple event-driven functions, native language primitives
  - Cons: less sophisticated workflow features, newer (adoption risk)
  - Deployment: npm install, works on serverless/containers

**Adoption Recommendation for OpenKhang:**
**Start with Inngest** if prioritizing time-to-value and simplicity. Use **Temporal** if you need sophisticated multi-step workflows with complex retry logic.

For a local "digital twin," **neither may be necessary initially**. OpenKhang can build its own lightweight state machine (see Section 1C) since workflows are typically <5 steps and run on a single machine.

---

#### 1C. State Machine Pattern (OpenKhang-Specific)
Define workflows as directed acyclic graphs (DAGs) with explicit state transitions.

**Example: Chat Message → Jira Ticket → Code Session**
```
State: INITIAL
  Event: chat_message_received (critical)
  Action: extract entities, categorize
  Next: TICKET_DECISION

State: TICKET_DECISION
  Condition: urgent + unassigned
  If YES -> Action: create_jira_ticket
  Next: CODE_SESSION_DECISION
  
State: CODE_SESSION_DECISION
  Condition: dev_available + ticket.is_blocking
  If YES -> Action: start_code_session
  If NO -> Action: notify_user
  Next: FINAL
```

**Benefits for OpenKhang:**
- Lightweight: no external dependency
- Observable: each state transition is logged (audit trail)
- Learnable: user can see and override decisions at each step
- Integrable: works with existing hook system

**Implementation:** YAML-based state machine stored in `.claude/openkhang.workflows.yaml`.

---

### Recommendation

**Immediate (Phase 1):** Implement a state machine layer for common workflows:
1. Chat message → Jira escalation
2. Jira blocker → auto-code-session
3. Pipeline failure → auto-diagnosis

**Medium-term (Phase 2):** Add webhook listeners for real-time triggering (replace polling loops).

**Long-term (Phase 3):** If workflows become complex (5+ steps, many branches), migrate to Inngest.

---

## 2. Cross-System Entity Resolution

### Problem
Each system uses different IDs:
- **Jira:** `PROJ-123`
- **GitLab:** MR `!448`
- **Google Chat:** thread `spaces/SPACE_ID/messages/MSG_ID`
- **Confluence:** page `id:12345`

No system knows that ticket PROJ-123 is linked to MR !448 and chat thread from Alice.

### Entity Graph Pattern

Build a **unified entity graph** that maps relationships:

```
Entity Type: Ticket
  ID: jira:PROJ-123
  Title: "Fix login bug"
  Status: In Progress
  Relationships:
    - mr: gitlab:!448
    - chat_thread: matrix:spaces/eng/messages/msg_xyz
    - confluence_page: confluence:page:98765
    - assignee: user:alice
    - depends_on: jira:PROJ-121

Entity Type: MergeRequest
  ID: gitlab:!448
  Title: "feat: login flow"
  Status: In Review
  Relationships:
    - ticket: jira:PROJ-123
    - pipeline: gitlab:pipeline:78901
    - author: user:alice

Entity Type: ChatThread
  ID: matrix:spaces/eng/messages/xyz
  First_message: "Should we add 2FA to login?"
  Status: Answered
  Relationships:
    - related_ticket: jira:PROJ-123
    - related_mr: gitlab:!448
    - participants: [user:alice, user:bob]
```

### Implementation Approach

**Option A: Simple Mapping Table (Lightweight)**
Store in `.claude/openkhang.entity-map.json`:
```json
{
  "jira:PROJ-123": {
    "gitlab_mr": "!448",
    "chat_thread": "matrix:spaces/eng/messages/xyz",
    "confluence_page": "98765"
  }
}
```
- Pros: Simple, no external DB
- Cons: Doesn't scale to hundreds of entities; no relationship analysis

**Option B: Graph Database (Scalable)**
Use **Neo4j** or **TigerGraph**:
- Strengths: Natural for entity relationships, fast traversal, built-in entity resolution
- Weaknesses: Requires new infrastructure, operational overhead

**Adoption Recommendation for OpenKhang:**
**Start with Option A** (mapping table in JSON). When it reaches 100+ entities, migrate to Neo4j locally (Docker container).

### Linking Process

When a workflow creates a Jira ticket in response to a chat message:

```
1. Extract chat_message_id from incoming event
2. Create ticket in Jira (returns ticket_id)
3. Update entity map: chat_message_id -> ticket_id
4. When MR is created later, link it: ticket_id -> mr_id
5. Future queries can traverse: chat_message -> ticket -> mr -> pipeline
```

### Adoption Recommendation

Implement in Phase 1 alongside state machine. Start with mapping table; upgrade to Neo4j in Phase 2 if needed.

---

## 3. Autonomy & Guardrails Architecture

### Core Problem
You want OpenKhang to:
- Auto-create Jira tickets from urgent chat messages
- Auto-start code sessions for blocking tickets
- Auto-fix simple pipeline failures

But NOT:
- Deploy to production without approval
- Merge code without human review
- Send messages impersonating the user

### Three-Tier Autonomy Model

**Tier 1: Information Retrieval (Full Autonomy)**
- Actions: Fetch sprint data, search Confluence, read chat messages, display dashboard
- Approval: None (read-only)
- Confidence threshold: N/A
- Examples: `/openkhang-status`, `/confluence-search`, `/sprint-board`

**Tier 2: Reversible Actions (High Confidence = Auto, Low = Approval)**
- Actions: Create tickets, start code sessions, post chat replies, update Jira status
- Approval: Required if confidence < 0.8 or user never took similar action
- Confidence factors:
  - Message clarity (0.95 if explicit "create ticket", 0.6 if ambiguous)
  - Matching historical pattern (0.9 if user did this 5+ times, 0.5 if novel)
  - Stakeholder risk (0.8 for own tickets, 0.5 if affects teammates)
- Examples: Auto-create Jira from chat, auto-start code session

**Tier 3: Irreversible/High-Risk Actions (Always Approval)**
- Actions: Merge MRs, deploy to production, delete tickets/pages, change sprint goals
- Approval: Always human-in-the-loop
- Examples: Pipeline auto-fix can commit, but cannot merge/deploy

### Confidence Scoring Implementation

```python
def score_action_confidence(action, context):
    score = 0.5  # base
    
    # Clarity: how explicit was the request?
    score += clarity_score(action.message)      # +0 to 0.3
    
    # Pattern: has user done this before?
    score += pattern_score(action.type, user_history)  # +0 to 0.3
    
    # Risk: who is affected?
    score += risk_score(action.scope)           # +0 to 0.2
    
    # Guardrails: does it violate policy?
    if violates_policy(action):
        score = 0.0
    
    return min(1.0, score)

# Usage:
if score >= 0.8:
    execute_action()  # Autonomous
else:
    request_approval(action, score)  # Human review
```

**Factors to score:**
- Message clarity: NLP confidence that user wants this action
- Historical frequency: how many times did user take this action?
- Stakeholder impact: does it affect only user, team, or organization?
- Policy check: is action within configured boundaries?

### Approval Workflow

When confidence < threshold:

```
1. Draft action with reasoning
2. Show user: "Create PROJ-456 from your chat? [Confidence: 72%]"
3. Options: [Auto-approve this], [Review first], [Never auto-create]
4. If user selects "Never auto-create", add to policy
5. Log action + approval decision → audit trail
```

### Audit Trail (Event Sourcing)

Store every action as an immutable event:

```
{
  "timestamp": "2025-04-06T11:30:00Z",
  "action_id": "uuid",
  "type": "create_jira_ticket",
  "actor": "openkhang-agent",
  "confidence": 0.85,
  "approved": true,
  "approved_by": "user:khanh",
  "source": "chat_message:xyz",
  "result": "ticket_created:PROJ-456",
  "reason": "User marked message as urgent; 3 similar actions in history; no policy violations"
}
```

This enables:
- Full audit trail (compliance)
- Learning from approvals/rejections
- Transparency (user can see why agent acted)

### Adoption Recommendation

**Phase 1:**
- Tier 1 actions: no approval needed (current state)
- Tier 2 actions: **human approval required** (conservative start)

**Phase 2:**
- Introduce confidence scoring
- Auto-approve Tier 2 actions when score > 0.85

**Phase 3:**
- Learn from user approvals/rejections
- Dynamically adjust thresholds per action type

---

## 4. Digital Twin: Work Persona & Learning

### What Is a Digital Twin (Work-Focused)?

A "digital twin" goes beyond a chatbot by:
1. **Learning your work patterns** (who you collaborate with, types of tickets you prefer, communication style)
2. **Operating proactively** (suggests actions before you ask)
3. **Maintaining your persona** (replies in your voice, respects your priorities)
4. **Evolving over time** (gets better at predicting what you want)

### Work Persona Model

Track and learn:

```yaml
Persona:
  name: "Khanh's Work Twin"
  
  Communication:
    language: "English"
    formality: "casual"  # (casual | formal | mixed)
    common_phrases: ["let's ship it", "sounds good", "blocking", "ack"]
    response_time: "immediate"  # vs "batched" or "async"
    
  Work Patterns:
    peak_hours: ["09:00-12:00", "14:00-18:00"]  # when user typically works
    ticket_preference: "backend_heavy"  # (frontend | backend | devops | balanced)
    code_session_avg_duration: 120  # minutes
    preferred_review_style: "detailed"  # vs "quick"
    
  Relationships:
    frequent_collaborators: ["alice", "bob"]
    blockers: ["charlie"]  # people who frequently block tasks
    mentees: ["diana"]  # people you mentor
    
  Priorities:
    urgent_keywords: ["production", "blocker", "down"]
    low_priority_patterns: ["documentation", "refactor"]
    risk_tolerance: 0.7  # (0=conservative, 1=aggressive)
    
  Tools:
    jira_board_preference: "PROJ"
    gitlab_project: "momo-app"
    confluence_favorite_spaces: ["engineering", "runbook"]
```

### Learning Mechanism

**Source 1: Explicit Feedback**
```
User says: "This message shouldn't have been marked urgent"
Action: Update urgency_threshold for that pattern
```

**Source 2: Implicit Signals**
```
User approves action A (confidence: 0.7) at time 10:00
Action: Log approval; when similar pattern appears, lower approval threshold
```

**Source 3: Observation**
```
Over 30 days, observe:
  - User works 9am-12pm and 2pm-6pm (not 6pm-9pm)
  - User prefers MRs with >50 lines of context before reviewing
  - User always responds to Alice within 1 hour, but Bob's messages pile up
Action: Adjust scheduling, context defaults, and notification priorities
```

### Proactive Behavior (vs. Reactive)

**Reactive:** User asks for sprint board → show sprint board

**Proactive:**
```
Time: Monday 9:00am
Observation: User's velocity was 30 SP last sprint, current sprint is 40 SP, only 7 days in
Action: "Heads up: sprint is 33% above your usual velocity. 2 items still in To Do: PROJ-128 (5 SP), PROJ-456 (3 SP). Need to descope?"
```

### Implementation Approach

**Phase 1: Manual Profile**
Create `.claude/openkhang.persona.yaml` with user inputs.

**Phase 2: Auto-Learn**
After 50 actions, start collecting signals:
- Feedback on action suggestions
- Approval patterns
- Response times

**Phase 3: Predictive**
Use learned patterns to:
- Suggest actions before user asks
- Adjust approval thresholds automatically
- Personalize UI (e.g., show only relevant Jira fields)

### Adoption Recommendation

**Phase 1 (MVP):** Manually populate persona YAML with:
- Communication style
- Favorite tools/projects
- Peak work hours

**Phase 2:** Track approval/rejection signals in event log.

**Phase 3:** Build persona-learning agent that updates YAML from event stream.

---

## 5. Architecture Reference: Multi-Tool Integration Patterns

### Context Preservation Across Tools

**Challenge:** When workflow spans Chat → Jira → GitLab → Confluence, how do you maintain context?

**Solution: State Envelope Pattern**

```json
{
  "workflow_id": "uuid",
  "context_envelope": {
    "original_event": {
      "type": "chat_message",
      "content": "Can't login, production is down",
      "sender": "alice",
      "timestamp": "2025-04-06T11:00:00Z"
    },
    "extracted_entities": {
      "severity": "critical",
      "keywords": ["production", "down"],
      "related_tickets": ["PROJ-123"]
    },
    "decisions": [
      {
        "step": "categorize",
        "result": "urgent",
        "confidence": 0.95
      },
      {
        "step": "create_jira",
        "result": "PROJ-999",
        "confidence": 0.88
      }
    ],
    "current_state": "PENDING_CODE_SESSION",
    "next_action": "Start code session on PROJ-999"
  }
}
```

Pass this envelope through every tool, appending decisions. At the end, log it for audit trail.

### Tool Integration Framework Patterns (2025)

**Option A: Model Context Protocol (MCP)**
- Standardized way to connect AI agents to tools
- Supported by Claude, LangChain, CrewAI
- Examples: Jira MCP server, GitHub MCP server
- Best for: LLM-native agent frameworks

**Option B: API Gateway Pattern**
- Wrapper around each tool's API with caching + retry logic
- Maintains request/response history for learning
- Best for: Complex auth + rate limiting

**Option C: Direct SDK Usage** (Current OpenKhang approach)
- Use native CLIs (jira-cli, glab, atlassian-cli)
- Pros: no extra dependencies, direct control
- Cons: limited to CLI capabilities, harder to correlate data

**Adoption Recommendation for OpenKhang:**
**Stay with Option C (direct SDK)** for now. If you integrate with LLM-based decision-making later, add MCP servers for Jira/GitLab (Phase 3+).

---

## 6. Technology Stack Recommendations

| Component | Recommended | Rationale |
|-----------|-------------|-----------|
| **Orchestration** | Custom state machine (YAML) | Lightweight, learnable, no external dep |
| **Durable execution** | None initially; Inngest if 100+ workflows | OpenKhang's workflows are simple |
| **Entity graph** | JSON mapping table → Neo4j | Start simple, scale when needed |
| **Memory/state** | `.claude/openkhang.state.json` | Persistent local state |
| **Audit trail** | Event log (JSON append-only) | Event sourcing pattern |
| **Confidence scoring** | Custom scoring function + ML later | Start rule-based, add ML after 500 events |
| **Persona learning** | YAML config + event-driven updates | Lightweight, human-readable |
| **Tool integration** | Existing CLIs + MCP (Phase 3) | Current approach scales to 5 tools |

---

## 7. Implementation Roadmap

### Phase 1: State Machine + Entity Graph (Months 1-2)
**Goal:** Enable repeatable, observable workflows with entity correlation.

- [ ] Implement state machine executor for YAML workflows
- [ ] Create entity mapping table (JSON)
- [ ] Add state persistence to hooks system
- [ ] Build: Chat → Jira → Code session workflow
- [ ] Output: `/openkhang-workflow-status` command

**Definition of Done:**
- User can trace how a chat message became a Jira ticket (entity map)
- User can see workflow state transitions in logs
- No external dependencies

### Phase 2: Confidence Scoring + Guardrails (Months 3-4)
**Goal:** Enable safe autonomous Tier 2 actions with approval workflows.

- [ ] Implement confidence scoring function
- [ ] Add Tier 2 action guardrails (requires approval if score < 0.8)
- [ ] Integrate with approval workflow (show decision reason)
- [ ] Track approvals in event log
- [ ] Build: Chat autocompletion with confidence display

**Definition of Done:**
- User sees why agent wants to act: "Create PROJ-123? [Confidence: 72%: message clarity=0.9, pattern match=0.7, risk=0.6]"
- User can choose to approve or reject
- All decisions logged for audit trail

### Phase 3: Persona Learning (Months 5-6)
**Goal:** Dynamically adapt to user patterns; enable proactive suggestions.

- [ ] Create persona YAML schema
- [ ] Implement persona-learning agent (reads event log, updates YAML)
- [ ] Build proactive suggestion engine
- [ ] Add communication style matching to chat replies

**Definition of Done:**
- After 50 actions, persona learns 3+ patterns automatically
- Agent proactively suggests actions based on learned schedule
- Agent replies in user's communication style

### Phase 4: Graph Database + Advanced Queries (Months 7-8)
**Goal:** Enable complex entity queries; prepare for multi-tool workflows.

- [ ] Migrate entity map to Neo4j (Docker)
- [ ] Build relationship queries (e.g., "Find all MRs related to tickets I created")
- [ ] Implement conflict detection (e.g., "This MR has 2 branches of the same feature")

**Definition of Done:**
- Complex queries work: "Show me all open tickets blocked by MRs with failing tests"
- Dashboard shows entity relationships visually

---

## 8. Unresolved Questions & Gaps

1. **Persona Privacy:** How do you learn from user behavior without creeping? Should learning be opt-in or automatic? (Design question)

2. **Tool-Specific Logic:** Each tool has unique semantics. How do you abstract workflows that work across tools without losing tool-specific power?

3. **Conflict Resolution:** If Chat says "create ticket" but Jira says "this ticket already exists," which wins? How is conflict detected?

4. **User Override Precedence:** When user says "don't auto-create tickets from Chat", does that override a different rule "auto-create urgent tickets"? Need policy language.

5. **Approval Latency:** If user is offline, how long does OpenKhang wait for approval before timing out? (Currently undefined)

6. **Multi-Account Scenarios:** What if user has multiple Jira projects or GitLab groups? How does scope isolation work?

7. **Entity Deduplication:** Chat message "Production is down" might match existing ticket PROJ-123. Should it auto-link, auto-escalate, or ask user?

8. **Learning Feedback Loop:** If user rejects 3 "auto-create ticket" suggestions, does agent stop suggesting forever, or can it learn a new pattern?

---

## Sources

- [10 AI Orchestration Platform Options Compared for 2026](https://www.domo.com/learn/article/best-ai-orchestration-platforms)
- [Agentic AI Orchestration in 2026: Automating Workflows at Scale](https://onereach.ai/blog/agentic-ai-orchestration-enterprise-workflow-automation/)
- [What are Agentic Workflows? Key Benefits and Challenges in 2026](https://aisera.com/blog/agentic-workflows/)
- [Top AI Agent Orchestration Frameworks for Developers 2025](https://www.kubiya.ai/blog/ai-agent-orchestration-frameworks)
- [Agentic AI Explained: Workflows vs Agents](https://orkes.io/blog/agentic-ai-explained-agents-vs-workflows/)
- [Inngest vs. Temporal: Which one should you choose?](https://akka.io/blog/inngest-vs-temporal)
- [The 10 best Temporal alternatives for enterprise teams](https://akka.io/blog/temporal-alternatives)
- [Temporal: Durable Execution Solutions](https://temporal.io/)
- [Inngest vs Temporal: Durable execution that developers love](https://www.inngest.com/compare-to-temporal)
- [How the Temporal Platform Works](https://temporal.io/how-it-works)
- [The Rise of the Durable Execution Engine (Temporal, Restate) in an Event-driven Architecture](https://www.kai-waehner.de/blog/2025/06/05/the-rise-of-the-durable-execution-engine-temporal-restate-in-an-event-driven-architecture-apache-kafka/)
- [Why Your Data Integration Graph Needs Entity Resolution](https://www.quantexa.com/blog/why-use-entity-resolution-graph/)
- [Entity Resolved Knowledge Graphs: A Tutorial](https://neo4j.com/blog/developer/entity-resolved-knowledge-graphs/)
- [What is Entity Resolution: Techniques, Tools & Use Cases](https://www.puppygraph.com/blog/entity-resolution)
- [How Entity Resolution Improves Graph Database Analytics](https://senzing.com/improve-graph-database-analytics-with-entity-resolution/)
- [Entity Resolution in TigerGraph Real-Time Graph Database](https://www.tigergraph.com/solutions/entity-resolution/)
- [The agent control plane: Architecting guardrails for a new digital workforce](https://www.cio.com/article/4130922/the-agent-control-plane-architecting-guardrails-for-a-new-digital-workforce.html)
- [Adding Guardrails for AI Agents: Policy and Configuration Guide](https://www.reco.ai/hub/guardrails-for-ai-agents)
- [Guardrails for autonomous AI: Governance in an agentic world](https://www.hcltech.com/trends-and-insights/guardrails-autonomous-ai-governance-agentic-world)
- [AI Agent Guardrails: Production Guide for 2026](https://authoritypartners.com/insights/ai-agent-guardrails-production-guide-for-2026/)
- [Agentic AI Guardrails: What They Are and How to Implement Them](https://aembit.io/blog/agentic-ai-guardrails-for-safe-scaling/)
- [State of Agentic AI Security 2025: Adoption, Risks & CISO Insights](https://www.akto.io/blog/state-of-agentic-ai-security-2025)
- [Customer Digital Twin vs AI Persona: Key Differences Explained](https://www.doppeliq.ai/blog/customer-digital-twin-vs-ai-persona)
- [Digital Twins vs Synthetic Users vs Synthetic Data: The Complete Guide](https://medium.com/@jonathan-kahan/digital-twins-vs-synthetic-users-vs-synthetic-data-the-complete-guide-to-ai-powered-customer-b04e8fb3db3d)
- [AI-Generated Digital Twins: Shaping the Future of Business](https://business.columbia.edu/insights/digital-future/ai-agent-digital-twin)
- [Digital Twins: Simulating Humans with Generative AI](https://www.nngroup.com/articles/digital-twins/)
- [AI Digital Twins | The Future of Personal Knowledge Management](https://www.personal.ai/insights/ai-digital-twins-the-future-of-personal-knowledge-management)
- [After Talking with 1,000 Personas: Learning Preference-Aligned Proactive Assistants](https://arxiv.org/html/2602.04000)
- [Event Sourcing Pattern - Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)
- [Understanding Event Sourcing: Key Principles and Benefits](https://www.baytechconsulting.com/blog/event-sourcing-explained-2025)
- [Understanding Event Sourcing and CQRS Pattern](https://mia-platform.eu/blog/understanding-event-sourcing-and-cqrs-pattern/)
- [Audit Trails in CI/CD: Best Practices for AI Agents](https://prefactor.tech/blog/audit-trails-in-ci-cd-best-practices-for-ai-agents)
- [The actor model in 10 minutes](https://www.brianstorti.com/the-actor-model/)
- [Understanding actor concurrency, Part 1: Actors in Erlang](https://www.infoworld.com/article/2178134/understanding-actor-concurrency-part-1-actors-in-erlang.html)
- [Introduction to Actors • Akka core](https://doc.akka.io/libraries/akka-core/current/typed/actors.html)
- [Understanding the Actor Design Pattern: A Practical Guide with Akka in Java](https://dev.to/micromax/understanding-the-actor-design-pattern-a-practical-guide-to-build-actor-systems-with-akka-in-java-p52)
- [State Machines vs Behavior Trees: designing a decision-making architecture for robotics](https://www.polymathrobotics.com/blog/state-machines-vs-behavior-trees)
- [Behavior tree (artificial intelligence, robotics and control) - Wikipedia](https://en.wikipedia.org/wiki/Behavior_tree_(artificial_intelligence,_robotics_and_control))
- [Behavior Trees or Finite State Machines](https://opsive.com/support/documentation/behavior-designer/behavior-trees-or-finite-state-machines/)
- [Game AI: Behavior Trees, State Machines, and Pathfinding](https://developers-heaven.net/blog/game-ai-behavior-trees-state-machines-and-pathfinding/)
- [A survey of Behavior Trees in robotics and AI](https://www.sciencedirect.com/science/article/pii/S0921889022000513)
- [Connecting Jira and GitHub with MCP (Model Context Protocol)](https://medium.com/@shubhambayas7/connecting-jira-and-github-with-mcp-model-context-protocol-4b164df8675c)
- [Top AI Agent Orchestration Frameworks for Developers 2025](https://www.kubiya.ai/blog/ai-agent-orchestration-frameworks)
- [The 2026 Guide to AI Agent Builders (And Why They All Need an Action Layer)](https://composio.dev/blog/best-ai-agent-builders-and-integrations)
- [Google ADK Opens the Door to AI Agents That Work Inside Your DevOps Toolchain](https://devops.com/google-adk-opens-the-door-to-ai-agents-that-work-inside-your-devops-toolchain/)
- [How to Build Slack Apps Using LLM Frameworks: Complete Developer Guide 2025](https://markaicode.com/build-slack-apps-llm-frameworks/)
- [Context Engineering for Personalization - State Management with Long-Term Memory Notes](https://developers.openai.com/cookbook/examples/agents_sdk/context_personalization)
- [Context Engineering - Short-Term Memory Management with Sessions](https://cookbook.openai.com/examples/agents_sdk/session_memory)
- [Beyond the Bubble: How Context-Aware Memory Systems Are Changing the Game in 2025](https://www.tribe.ai/applied-ai/beyond-the-bubble-how-context-aware-memory-systems-are-changing-the-game-in-2025)
- [Amazon Bedrock AgentCore Memory: Building context-aware agents](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/)
- [Memory for AI Agents: A New Paradigm of Context Engineering](https://thenewstack.io/memory-for-ai-agents-a-new-paradigm-of-context-engineering/)
- [Context Window Management: Strategies for Long-Context AI Agents and Chatbots](https://www.getmaxim.ai/articles/context-window-management-strategies-for-long-context-ai-agents-and-chatbots/)

---

**Report Status:** COMPLETE | Next: Planner creates implementation plan based on this research.
