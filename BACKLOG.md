# Backlog — Hybrid AI Agent

Items deferred for future phases.

---

## Phase 4 Items

| ID | Item | Priority | Description |
|---|---|---|---|
| BL-003 | Docker Sandbox Build Validation | Medium | Full end-to-end testing of Docker sandbox including network policy enforcement and filesystem isolation. |
| BL-004 | Audit Log Rotation | Low | Add daily rotation with configurable retention. Current log grows unbounded. |
| BL-005 | Unicode Obfuscation Hardening | Low | Add Unicode normalization (NFKC) before pattern matching in sanitizer. |
| BL-006 | Network Egress Filtering | Medium | Container-level network policy or DNS-based filtering for defense-in-depth. |
| BL-010 | Patch-Based Workflow for Docker | Low | For production Docker deployment: read-only source mount + staging area. Agent produces patch files instead of direct writes. Safest for multi-user environments. |
| BL-011 | Ollama Concurrent Request Handling | Medium | Current architecture queues requests at Ollama level. Investigate Ollama parallel request support or model-level request batching for better background + foreground performance. |

---

## Enhancement Ideas

| ID | Item | Priority | Description |
|---|---|---|---|
| EN-003 | Custom Routing Rules UI | Low | Web-based editor for routing_rules.yml. |
| EN-004 | Metrics Dashboard | Medium | Track token usage, routing distribution, approval rates, response times. Export as JSON or connect to monitoring tools. |
| EN-005 | Multi-Agent Collaboration | Low | CrewAI-style multi-agent patterns (planner, coder, reviewer). |
| EN-006 | CLOUD_ONLY Mode | Low | Route all tasks to Claude API. |
| EN-009 | Streaming Response Output | Medium | Stream LLM responses token-by-token to terminal instead of waiting for full response. Improves perceived latency. |
| EN-010 | Project Templates | Low | Pre-configured routing rules and tool configurations for common project types (Python, Node.js, Java). |
| EN-011 | Team Shared Configuration | Medium | Shared config repo for routing rules, command allowlists, and blocked patterns. Enables consistent team deployment. |

---

## Completed

| ID | Item | Phase |
|---|---|---|
| BL-007 | ReAct Tool Loop Integration | Phase 2 |
| BL-008 | Git Branch Isolation | Phase 2 |
| BL-009 | Auto-Approve Workspace Files | Phase 3 |
| EN-001 | Conversation Memory | Phase 2 |
| EN-002 | Tool Result Feedback Loop | Phase 2 |
| EN-007 | Persistent Conversation Memory | Phase 3 |
| EN-008 | /scan Command | Phase 3 |
| BL-001 | Background Tasks (Level 2) | Phase 3 |

---

## Phase 4 Priority Recommendation

1. **EN-009** (Streaming Responses) — Biggest UX improvement, reduces perceived latency
2. **BL-003** (Docker Sandbox Validation) — Required before team deployment
3. **EN-004** (Metrics Dashboard) — Visibility into agent usage patterns
4. **BL-006** (Network Egress Filtering) — Security hardening for production

---

Last reviewed: April 13, 2026
