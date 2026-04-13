# Hybrid AI Coding Agent v0.3

A security-first AI coding agent that intelligently routes tasks between local LLMs (Gemma 4) and cloud APIs (Claude) based on task complexity. Features a multi-step ReAct tool loop, git branch isolation for safe file manipulation, conversation memory, and full human-in-the-loop controls.

## Architecture

```
User Request → Router → Model Resolver → ReAct Loop
                 │            │              │
           ┌─────┼─────┐     │     ┌────────┼────────┐
           ▼     ▼     ▼     │     ▼        ▼        ▼
        SIMPLE MEDIUM COMPLEX │  Reason → Tool Call → Observe
           │     │     │      │     │        │        │
           ▼     ▼     ▼      │     │   ┌────┼────┐   │
         E4B   26B  Claude    │     │   ▼    ▼    ▼   │
                              │     │  File Shell Git  │
                              │     │   │    │    │    │
                              │     └───┴────┴────┘───┘
                              │         Security Pipeline
                              │     (3-gate validation + approval)
                              │
                         Mode-aware
                    (HYBRID / LOCAL_ONLY)
```

### Key Design Principles

- **Security-first**: Zero-tolerance for security tasks in local-only mode, OWASP LLM Top 10 coverage, three-gate command validation
- **Human-in-the-loop**: Every file write, shell command, and file deletion requires explicit approval with risk classification
- **Rule-based routing**: No LLM in the routing path — prevents prompt injection from manipulating task classification
- **Git branch isolation**: Agent file modifications happen on dedicated branches, never on main directly
- **Defense-in-depth**: Docker sandbox + command allowlist + pattern blocklist + human approval + output sanitization
- **Auto-approve mode**: Skip repetitive approvals for file writes and safe commands, with git branch as safety net
- **Background tasks**: Run long requests in background while continuing to work
- **Session persistence**: Conversation history saved to disk, resume across restarts

### Components

| Component | Purpose |
|---|---|
| Rule Router | Classifies tasks into SIMPLE/MEDIUM/COMPLEX tiers using keyword matching |
| Model Resolver | Maps (tier + mode) to target model with disclaimer flags |
| ReAct Loop | Multi-step reason → tool call → observe → repeat cycle |
| Tool Executor | Bridges LLM tool calls to FileOps/ShellExec/GitOps through security pipeline |
| Conversation Memory | Sliding window history for multi-turn interactions |
| Git Branch Manager | Auto-creates agent branches, auto-commits, PR-style diff review |
| Ollama Client | Communicates with local Gemma 4 models via native API |
| Claude Client | Communicates with Anthropic's Messages API |
| Health Checker | Background monitoring of Claude API availability (60s polling) |
| Pending Queue | Persists blocked tasks for retry when API recovers |
| File Ops | Sandboxed file read/write/delete with path traversal protection |
| Shell Exec | Three-gate command validation: parse → policy → human approval |
| Git Ops | Git operations through the sandboxed shell pipeline |
| Permissions | Interactive approval gates with risk classification display |
| Sanitizer | Prompt injection detection + output credential redaction |
| Audit Logger | JSON-lines action log with sensitive value redaction |

---

## Prerequisites

- **macOS** with Apple Silicon (M1/M2/M3/M4/M5)
- **Python 3.11+** (tested with 3.14)
- **Ollama** v0.20.2+ (https://ollama.com)
- **Docker Desktop** for macOS (optional — required for sandbox mode)
- **Anthropic API Key** (optional — required for HYBRID mode)

---

## Installation

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd hybrid-ai-agent
```

### 2. Install Ollama and Pull Models

```bash
# Install Ollama (if not already installed)
brew install ollama

# Verify version (must be >= 0.20.2)
ollama --version

# Pull the primary model (~18GB download)
ollama pull gemma4:26b

# Pull the fallback model (~9.6GB download)
ollama pull gemma4:e4b

# Verify models are available
ollama list
```

### 3. Set Up Python Environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

### 4. Configure Environment

```bash
# Create your .env file from the template
cp .env.example .env

# Edit .env with your settings
# Required for HYBRID mode:
#   ANTHROPIC_API_KEY=sk-ant-your-key-here
#
# For LOCAL_ONLY mode, no API key is needed
```

### 5. Verify Installation

```bash
# Run the test suite (283 tests)
pytest tests/ -v --tb=short

# Quick security validation
python -c "
from src.tools.shell_exec import ShellExec
se = ShellExec(workspace_root='_workspace')
v = se.validate('curl http://evil.com')
print(f'Security check: curl blocked = {not v.is_allowed}')
"
```

---

## Usage

### Starting the Agent

```bash
# LOCAL_ONLY mode (no API key required)
AGENT_MODE=LOCAL_ONLY python -m src.main

# HYBRID mode (requires ANTHROPIC_API_KEY in .env)
python -m src.main
```

### Sample Interactions

#### Autonomous Code Exploration (ReAct Loop)

```
> List all Python files and tell me about the project structure

[MEDIUM tier → gemma4:26b, 120s timeout, Ctrl+C to cancel]
  [Step 1/10] I will list the files to understand the project.
  [Tool: list_files({'path': '.', 'recursive': true})]
  [Step 2/10] Let me read the main entry point.
  [Tool: read_file({'path': 'src/main.py'})]
  [Step 3/10] Based on my analysis...
[Tools used: list_files, read_file]

This is a Python project with the following structure:
- src/main.py — CLI entry point with command handling
- src/router/ — Task classification engine
...
```

#### Multi-Turn Conversation (Memory)

```
> Read src/main.py and explain the create_agent function

[Agent reads file, explains function]

> Now refactor it to be shorter

[Agent REMEMBERS which file — no need to repeat]
[Branch created: agent/task-a1b2c3]

  approve / deny / edit → approve

> /diff summary
  src/main.py | 45 +++++-----
  1 file changed, 20 insertions(+), 25 deletions(-)

> /apply
  Merged agent/task-a1b2c3 into main (1 commit).
```

#### Shell Command with Security Gates

```
> Run the test suite for the payment module

┌─ Shell Execution Request ─────────────────────┐
│ Command:  pytest tests/test_payment.py -v     │
│ Risk:     🟢 LOW                              │
└───────────────────────────────────────────────┘

  approve / deny / edit  → approve

12 tests passed, 0 failed
```

#### Package Installation with Security Assessment

```
> Install the requests library

┌─ ⚠️  Package Installation Request ────────────┐
│ Command:     pip install requests              │
│ Risk:        🟠 HIGH — package installation    │
│                                                │
│ Assessment:                                    │
│ Reason:      Required for HTTP client.         │
│ Security:    ✅ Well-maintained, widely used.  │
│                                                │
│ ⓘ  AI-generated assessment. Verify            │
│    independently for unfamiliar packages.      │
└────────────────────────────────────────────────┘

  approve / deny / edit  → approve
```

#### Security Task in LOCAL_ONLY Mode

```
> Check for SQL injection vulnerabilities

┌─ Security Disclaimer ─────────────────────────┐
│ ⚠️  SECURITY TASK — LOCAL MODEL ONLY          │
│                                                │
│ Limitations:                                   │
│   • May miss subtle vulnerabilities            │
│   • Should NOT be treated as a security audit  │
│                                                │
│ Recommendation:                                │
│   Re-run in HYBRID mode before production.     │
└────────────────────────────────────────────────┘

Proceed with local analysis? [y/n]: y

⚠️  This security analysis was performed by a local model.
   Add to pending queue for cloud re-analysis? [y/n]: y
   Queued as a1b2c3. Use '/retry a1b2c3' in HYBRID mode.
```

### CLI Commands

| Command | Description |
|---|---|
| `/mode` | Show current operation mode |
| `/mode hybrid` | Switch to HYBRID mode (local + cloud) |
| `/mode local` | Switch to LOCAL_ONLY mode |
| `/history` | Show conversation history |
| `/clear` | Clear conversation history |
| `/diff` | Show diff between agent branch and main |
| `/diff summary` | Show change summary (files, insertions, deletions) |
| `/apply` | Merge agent branch into main |
| `/discard` | Delete agent branch and all changes |
| `/branches` | List all agent branches |
| `/pending` | List pending tasks (blocked by API outage) |
| `/retry <id>` | Retry a specific pending task |
| `/retry all` | Retry all pending tasks |
| `/pending discard <id>` | Discard a pending task |
| `/pending clear` | Clear all pending tasks |
| `/health` | Show API health status and tier timeouts |
| `/scan` | Scan workspace code files for analysis |
| `/scan <path>` | Scan specific directory or file |
| `/scan --pattern *.py` | Scan files matching pattern |
| `/scan <path> --ask <question>` | Scan with custom analysis instruction |
| `/config` | Show current configuration |
| `/config auto-approve on\|off` | Toggle auto-approve mode |
| `/bg <request>` | Submit request to background |
| `/status` | List background tasks |
| `/result <id>` | View background task result |
| `/cancel <id>` | Cancel background task |
| `/save` | Save conversation to disk |
| `/load` | Load conversation from disk |
| `/quit` | Exit (prompts to apply/discard active branch) |
| `Ctrl+C` | Cancel the current request |

### Operation Modes

| Mode | Local Models | Claude API | Security Tasks |
|---|---|---|---|
| **HYBRID** | SIMPLE + MEDIUM tiers | COMPLEX + Security tiers | Full capability |
| **LOCAL_ONLY** | All tiers | Disabled | Local model + disclaimer + optional pending queue |

---

## Git Branch Isolation

When the agent modifies files, it automatically creates a dedicated git branch:

```
main ────────────────────────────────── main (after /apply)
  │                                       ▲
  └── agent/task-a1b2c3 ── commit ── commit ─┘
       (auto-created)    (auto-commit   (auto-commit
                          on write)      on write)
```

- **Git-aware mode**: Workspace has `.git` → branch isolation active
- **Git-unaware mode**: Workspace has no `.git` → direct writes with approval only
- Agent never commits to `main` directly
- `/apply` merges with confirmation, `/discard` deletes branch
- `/quit` prompts to handle active branches before exit

---

## Docker Sandbox (Production)

For sandboxed execution where the agent runs inside an isolated container.

### Build and Run

```bash
docker compose build

export PROJECT_PATH=/path/to/your/project
export ANTHROPIC_API_KEY=sk-ant-your-key-here

docker compose run --rm agent
```

### Sandbox Security Controls

- **Non-root execution** — agent runs as `agent:1000`
- **Read-only filesystem** — only `/workspace` and `/tmp` are writable
- **All capabilities dropped** — `cap_drop: ALL`
- **No privilege escalation** — `no-new-privileges: true`
- **Resource limits** — 4 CPU cores, 4GB RAM maximum
- **No Docker socket** — agent cannot control Docker
- **Writable tmpfs** — `/tmp` with `noexec,nosuid`

---

## Security Model

### Three-Gate Command Validation

1. **Gate 1 (Parser)** — Detects command chaining, subshells, pipes, redirects, encoding obfuscation
2. **Gate 2 (Policy)** — Checks command allowlist and blocked patterns. Enhanced approval for `rm` and `pip install`
3. **Gate 3 (Human)** — Displays command with risk level, waits for approve/deny/edit

### Risk Levels

| Indicator | Level | Examples |
|---|---|---|
| 🟢 | LOW | `ls`, `cat`, `pytest`, `git status` |
| 🟡 | MEDIUM | `cp`, `mv`, `mkdir`, `git commit` |
| 🟠 | HIGH | `rm`, `pip install`, `git push` |
| 🔴 | BLOCKED | `curl`, `sudo`, `rm -rf`, command chaining |

### OWASP LLM Top 10 Coverage

| Risk | Coverage |
|---|---|
| LLM01: Prompt Injection | Input sanitizer detects override, role hijack, delimiter injection |
| LLM02: Insecure Output | Output sanitizer redacts API keys, passwords, JWTs, connection strings |
| LLM04: Excessive Agency | Human-in-the-loop for all side effects; command allowlist |
| LLM05: Supply Chain | Pinned dependencies; `pip install` requires security assessment |
| LLM06: Sensitive Info | Audit logger redacts credentials; env vars stripped from child processes |

### ReAct Loop Safety

- Maximum iteration limit (default 10, configurable)
- Per-tier timeouts: SIMPLE 30s, MEDIUM 120s, COMPLEX 180s
- Ctrl+C cancellation at any point
- Tool calls validated against registry — no arbitrary tool execution
- All tool results sanitized before display

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_MODE` | `HYBRID` | Operation mode: `HYBRID` or `LOCAL_ONLY` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_PRIMARY_MODEL` | `gemma4:26b` | Primary local model |
| `OLLAMA_FALLBACK_MODEL` | `gemma4:e4b` | Fallback local model |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model for complex tasks |
| `ANTHROPIC_API_KEY` | (none) | Required for HYBRID mode |
| `WORKSPACE_ROOT` | `./_workspace` | Workspace directory |
| `MAX_ITERATIONS` | `10` | ReAct loop iteration limit |
| `MAX_CONVERSATION_TURNS` | `20` | Conversation memory window |
| `AUDIT_LOG_ENABLED` | `true` | Enable/disable audit logging |
| `AUTO_APPROVE_WRITES` | `false` | Auto-approve file writes and commands (requires git) |

### Routing Rules (config/routing_rules.yml)

```yaml
security_override:
  keywords:
    - "your-custom-keyword"
task_keywords:
  SIMPLE:
    phrases:
      - "your custom phrase"
tier_timeouts:
  SIMPLE: 30
  MEDIUM: 120
  COMPLEX: 180
```

### Command Allowlist (config/allowed_commands.yml)

```yaml
allowed:
  - python
  - pytest
  - your-custom-tool
```

---

## Troubleshooting

### Ollama Issues

```bash
# Not running?
curl -s http://localhost:11434/api/version
ollama serve

# Model not found?
ollama list
ollama pull gemma4:26b

# Listening on 0.0.0.0? (security risk)
export OLLAMA_HOST=127.0.0.1:11434
```

### Claude API Issues

```bash
# Check health inside agent:
/health

# No API key?
echo 'ANTHROPIC_API_KEY=sk-ant-your-key' >> .env
# Or use LOCAL_ONLY mode
```

### Git Branch Issues

```bash
# Stuck on agent branch?
git checkout main
git branch -D agent/task-XXXXXXXX

# Agent not creating branches?
# Workspace must be a git repo: git init
```

### Python Issues

```bash
# Module not found?
source .venv/bin/activate
pip install -e ".[dev]"
```

### Docker Issues

```bash
# Can't connect to Ollama from container?
docker run --rm alpine/curl \
  curl -s http://host.docker.internal:11434/api/version
```

---

## Testing

```bash
# All 283 tests
pytest tests/ -v --tb=short

# By category
pytest tests/test_router.py -v          # 40 routing tests
pytest tests/test_sanitizer.py -v       # 22 sanitizer tests
pytest tests/test_permissions.py -v     # 8 permission tests
pytest tests/test_integration.py -v     # 28 integration tests
pytest tests/test_security.py -v        # 57 security attack tests
pytest tests/test_tool_interface.py -v  # 18 tool interface tests
pytest tests/test_tool_executor.py -v   # 13 tool executor tests
pytest tests/test_memory.py -v          # 14 memory tests
pytest tests/test_git_branch.py -v      # 27 git branch tests

# Lint
ruff check src/ tests/
```

---

## Project Structure

```
hybrid-ai-agent/
├── src/
│   ├── main.py                # CLI entry point
│   ├── router/
│   │   └── rule_router.py     # Task classification
│   ├── agent/
│   │   ├── graph.py           # ReAct loop orchestration
│   │   ├── tool_interface.py  # Tool call format + parser
│   │   ├── tool_executor.py   # Security pipeline bridge
│   │   ├── memory.py          # Conversation history (persistent)
│   │   ├── scanner.py         # Workspace code scanner
│   │   └── background.py      # Background task manager
│   ├── models/
│   │   ├── model_resolver.py  # Mode-aware model mapping
│   │   ├── ollama_client.py   # Local LLM client
│   │   ├── claude_client.py   # Cloud LLM client
│   │   ├── health_checker.py  # API availability monitor
│   │   └── pending_queue.py   # Blocked task persistence
│   ├── tools/
│   │   ├── file_ops.py        # Sandboxed file operations
│   │   ├── shell_exec.py      # Three-gate command validation
│   │   ├── git_ops.py         # Git command wrapper
│   │   └── git_branch.py      # Branch isolation manager
│   └── security/
│       ├── permissions.py     # Human-in-the-loop gates
│       ├── sanitizer.py       # Injection detection + redaction
│       └── audit.py           # Action logging
├── config/
│   ├── routing_rules.yml      # Routing keywords + timeouts
│   ├── allowed_commands.yml   # Command whitelist
│   └── blocked_patterns.yml   # Dangerous pattern blocklist
├── tests/                     # 283 tests (security-focused)
├── Dockerfile                 # Sandbox container
├── docker-compose.yml         # Sandbox orchestration
├── BACKLOG.md                # Future phase items
└── README.md                 # This file
```

---

## License

MIT - Use freely, modify as needed, contribute back if you can.
