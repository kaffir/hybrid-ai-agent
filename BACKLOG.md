# Backlog — Hybrid AI Agent

Items deferred for future phases.

---

## Phase 3 Items

| ID | Item | Priority | Description |
|---|---|---|---|
| BL-001 | Background Tasks (Level 2) | Medium | Add /status, /result, /cancel for long-running requests. Requires threading and task result store. |
| BL-003 | Docker Sandbox Build Validation | Low | Full end-to-end testing of Docker sandbox including network policy enforcement and filesystem isolation. |
| BL-004 | Audit Log Rotation | Low | Add daily rotation with configurable retention. Current log grows unbounded. |
| BL-005 | Unicode Obfuscation Hardening | Low | Add Unicode normalization (NFKC) before pattern matching in sanitizer. |
| BL-006 | Network Egress Filtering | Medium | Container-level network policy or DNS-based filtering for defense-in-depth. |
| BL-009 | Auto-Approve for Workspace Files | Medium | Configurable flag to skip approval for file read/write within workspace. Git branch isolation as safety net. Shell/delete still require approval. Disabled by default. |
| BL-010 | Patch-Based Workflow for Docker | Low | For production Docker deployment: read-only source mount + staging area. Agent produces patch files instead of direct writes. Safest option for multi-user environments. |

---

## Enhancement Ideas

| ID | Item | Priority | Description |
|---|---|---|---|
| EN-003 | Custom Routing Rules UI | Low | Web-based editor for routing_rules.yml. |
| EN-004 | Metrics Dashboard | Low | Track token usage, routing distribution, approval rates. |
| EN-005 | Multi-Agent Collaboration | Low | CrewAI-style multi-agent patterns (planner, coder, reviewer). |
| EN-006 | CLOUD_ONLY Mode | Low | Route all tasks to Claude API. |
| EN-007 | Persistent Conversation Memory | Medium | Save conversation history to disk. Resume sessions across restarts. |
| EN-008 | /scan Command | Medium | Shortcut to read all files in workspace and send to LLM for analysis. Interim solution before full autonomous exploration. |

---

## Completed (Phase 1 + Phase 2)

| ID | Item | Completed |
|---|---|---|
| BL-007 | ReAct Tool Loop Integration | Phase 2 |
| BL-008 | Git Branch Isolation | Phase 2 |
| EN-001 | Conversation Memory | Phase 2 |
| EN-002 | Tool Result Feedback Loop | Phase 2 |

---

## Phase 3 Priority Recommendation

1. **BL-009** (Auto-Approve Workspace Files) — Biggest productivity gain with git branch safety net
2. **BL-001** (Background Tasks) — Quality of life for long-running requests
3. **EN-007** (Persistent Memory) — Resume sessions across restarts
4. **BL-006** (Network Egress Filtering) — Security hardening

---

Last reviewed: April 12, 2026
