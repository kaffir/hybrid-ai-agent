# Backlog — Hybrid AI Agent

Items deferred during initial implementation for future phases.

---

## Next Phase Items

| ID | Item | Priority | Description |
|---|---|---|---|
| BL-001 | Background Tasks (Level 2) | Medium | Add `/status`, `/result`, `/cancel` commands for long-running requests. Enable parallel work during agent processing. Requires threading and task result store. |
| BL-002 | RDBMS Integration | Medium | Add database tool in `src/tools/db_ops.py` with read-only credentials, query allowlisting, and connection pooling. Supports the reconciliation service use case. |
| BL-003 | Docker Sandbox Build Validation | Low | Full end-to-end testing of the Docker sandbox including network policy enforcement, filesystem isolation verification, and microVM behavior validation. |
| BL-004 | Audit Log Rotation | Low | Current audit log (`/workspace/.agent/audit.log`) grows unbounded. Add daily rotation with configurable retention (e.g., 30 days). Consider structured log shipping for org-wide deployment. |
| BL-005 | Unicode Obfuscation Hardening | Low | Current sanitizer detects ASCII-based prompt injection patterns. Add Unicode normalization (NFKC) before pattern matching to catch homoglyph and encoding-based bypass attempts. |
| BL-006 | Network Egress Filtering | Medium | Current network restriction is application-level (URL allowlist in httpx client). Add container-level network policy or DNS-based filtering for defense-in-depth. Blocked by `cap_drop: ALL` removing `CAP_NET_ADMIN`. Investigate Docker network policies or external proxy. |
| BL-007 | ReAct Tool Loop Integration | **High** | Current agent sends user request directly to LLM without using tools. The LLM cannot read workspace files, execute commands, or interact with the codebase autonomously. Implement full ReAct loop where: (1) LLM decides which tool to call, (2) agent executes the tool through the security pipeline, (3) tool result is fed back to the LLM for next reasoning step. This is required for commands like "scan my code for bugs" or "refactor this module". Includes `/scan` command as an interim solution. |

---

## Enhancement Ideas

| ID | Item | Priority | Description |
|---|---|---|---|
| EN-001 | Conversation Memory | Medium | Maintain multi-turn conversation context within a session. Currently each request is independent. Add sliding window context management. |
| EN-002 | Tool Result Feedback Loop | **High** | After tool execution (file write, shell command), feed the result back to the LLM for follow-up reasoning. Enables true multi-step ReAct loops. Closely related to BL-007. |
| EN-003 | Custom Routing Rules UI | Low | Web-based editor for `routing_rules.yml` so non-technical team members can tune routing without editing YAML. |
| EN-004 | Metrics Dashboard | Low | Track token usage, routing distribution, approval rates, and average response times. Export as JSON or connect to monitoring tools. |
| EN-005 | Multi-Agent Collaboration | Low | Extend to CrewAI-style multi-agent patterns where a "planner" agent delegates subtasks to specialized agents (coder, reviewer, tester). |
| EN-006 | CLOUD_ONLY Mode | Low | Route all tasks to Claude API. Deferred during Phase 1 as unnecessary for POC. Add if stakeholders request maximum quality demos. |

---

## Phase 2 Priority Recommendation

Based on Phase 1 findings, the recommended order for Phase 2:

1. **BL-007 + EN-002** (ReAct Tool Loop) — Without this, the agent cannot interact with the codebase. This is the highest impact item.
2. **EN-001** (Conversation Memory) — Enables multi-turn interactions which are natural for coding workflows.
3. **BL-001** (Background Tasks) — Quality of life for long-running requests.
4. **BL-006** (Network Egress Filtering) — Strengthens security posture.

---

## Review Process

When starting the next phase:

1. Review all items above
2. Re-prioritize based on current needs
3. Select 2-3 items per sprint
4. Create implementation plan for each selected item
5. Follow the same step-by-step, security-first approach used in Phase 1

---

Last reviewed: April 11, 2026
