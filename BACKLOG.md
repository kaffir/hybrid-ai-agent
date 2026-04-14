# Backlog — Hybrid AI Agent

Items deferred for future phases.

---

## Phase 4 Items

| ID | Item | Priority | Description |
|---|---|---|---|
| BL-003 | Docker Sandbox Validation | Medium | Full end-to-end testing of Docker sandbox including network policy enforcement, filesystem isolation verification, and resource limit validation. Required before team deployment. |
| BL-004 | Audit Log Rotation | Low | Add daily rotation with configurable retention. Current log grows unbounded. |
| BL-005 | Unicode Obfuscation Hardening | Low | Add Unicode normalization (NFKC) before pattern matching in sanitizer. |
| BL-006 | Network Egress Filtering | Medium | Container-level network policy or DNS-based filtering for defense-in-depth. Current restriction is application-level only. |
| BL-010 | Patch-Based Workflow for Docker | Low | For production Docker deployment: read-only source mount + staging area. Agent produces patch files instead of direct writes. Safest for multi-user environments. |
| BL-011 | Ollama Concurrent Request Handling | Medium | Current architecture queues requests at Ollama level. Investigate Ollama parallel request support or model-level request batching for better background + foreground performance. |
| EN-003 | Custom Routing Rules UI | Low | Web-based editor for routing_rules.yml. |
| EN-004 | Metrics Dashboard | Medium | Track token usage, routing distribution, approval rates, response times. Export as JSON or connect to monitoring tools. |
| EN-005 | Multi-Agent Collaboration | Low | CrewAI-style multi-agent patterns (planner, coder, reviewer). |
| EN-006 | CLOUD_ONLY Mode | Low | Route all tasks to Claude API. |
| EN-009 | Streaming Response Output | Medium | Stream LLM responses token-by-token to terminal instead of waiting for full response. Improves perceived latency. |
| EN-010 | Project Templates | Low | Pre-configured routing rules and tool configurations for common project types (Python, Node.js, Java). |
| EN-011 | Team Shared Configuration | Medium | Shared config repo for routing rules, command allowlists, and blocked patterns. Enables consistent team deployment. |

---

## Completed

| ID | Item | Phase | Description |
|---|---|---|---|
| BL-007 | ReAct Tool Loop Integration | Phase 2 | Multi-step reason → tool call → observe loop |
| BL-008 | Git Branch Isolation | Phase 2 | Agent file modifications on dedicated branches |
| EN-001 | Conversation Memory | Phase 2 | Sliding window session memory |
| EN-002 | Tool Result Feedback Loop | Phase 2 | Tool results fed back to LLM for reasoning |
| BL-009 | Auto-Approve Workspace Files | Phase 3 | Skip approval for writes/commands with git safety net |
| EN-008 | /scan Command | Phase 3 | Workspace code scanning shortcut |
| BL-001 | Background Tasks (Level 2) | Phase 3 | /bg, /status, /result, /cancel with isolated memory |
| EN-007 | Persistent Conversation Memory | Phase 3 | Save/load sessions across restarts |

---

## Known Issues Resolved

| Issue | Resolution | Phase |
|---|---|---|
| Background tasks can't get approval in sandbox | Background auto-approves writes/commands; rm and pip blocked in background | Phase 3 |
| Sandbox doesn't persist conversation | Separate .agent volume mount in docker-compose.yml | Phase 3 |
| Background output bleeds into foreground | Silent mode for background threads | Phase 3 |
| Foreground timeout during background tasks | Queue-aware timeout extends foreground limits | Phase 3 |
| Agent creates branch on every request | Branch created lazily only on file write/delete | Phase 2 |
| Agent auto-creates git repos | Removed — git-aware vs git-unaware mode detection | Phase 2 |
| Orphaned agent branches on exit | /quit prompts to apply/discard active branch | Phase 2 |

---

## Phase 4 Priority Recommendation

1. **EN-009** (Streaming Responses) — Biggest UX improvement, reduces perceived latency
2. **BL-003** (Docker Sandbox Validation) — Required before team deployment
3. **EN-004** (Metrics Dashboard) — Visibility for POC reporting to leadership
4. **BL-006** (Network Egress Filtering) — Security hardening for production

---

## Project Stats

| Metric | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Source files | 18 | 21 | 24 |
| Test files | 5 | 8 | 12 |
| Tests | 155 | 227 | 283 |
| CLI Commands | 8 | 15 | 25 |

---

Last reviewed: April 14, 2026
