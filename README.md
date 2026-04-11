# Hybrid AI Coding Agent

A security-first AI coding agent that intelligently routes tasks between local LLMs (Gemma 4) and cloud APIs (Claude) based on task complexity, with full human-in-the-loop controls.

## Architecture

```
User Request → Rule-Based Router → Model Resolver → LLM → Response
                    │                     │
              ┌─────┼─────┐         ┌────┼────┐
              ▼     ▼     ▼         ▼    ▼    ▼
           SIMPLE MEDIUM COMPLEX  E4B  26B  Claude
            │       │       │      │    │     │
            └───────┴───┬───┘      └────┴──┬──┘
                        │                  │
                   No LLM in          Mode-aware
                   routing path       (HYBRID/LOCAL_ONLY)
```

### Key Design Principles

- **Security-first**: Zero-tolerance for security tasks in local-only mode, OWASP LLM Top 10 coverage, three-gate command validation
- **Human-in-the-loop**: Every file write, shell command, and file deletion requires explicit approval
- **Rule-based routing**: No LLM in the routing path — prevents prompt injection from manipulating task classification
- **Defense-in-depth**: Docker sandbox + command allowlist + pattern blocklist + human approval + output sanitization

### Components

| Component | Purpose |
|---|---|
| Rule Router | Classifies tasks into SIMPLE/MEDIUM/COMPLEX tiers using keyword matching |
| Model Resolver | Maps (tier + mode) to target model with disclaimer flags |
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
# Run the test suite (155 tests)
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

#### Simple Task (routes to Gemma 4 E4B)

```
> Format this Python function to follow PEP 8

[Generating... SIMPLE tier, 30s timeout, Ctrl+C to cancel]
[Router: SIMPLE → gemma4:e4b]

Here is the formatted function:
...
```

#### Medium Task (routes to Gemma 4 26B)

```
> Write unit tests for a function that calculates tax

[Generating... MEDIUM tier, 120s timeout, Ctrl+C to cancel]
[Router: MEDIUM → gemma4:26b]

Here are the unit tests:
...
```

#### Security Task in LOCAL_ONLY Mode (shows disclaimer)

```
> Check for SQL injection vulnerabilities

[Generating... COMPLEX tier, 180s timeout, Ctrl+C to cancel]

┌─ Security Disclaimer ─────────────────────────┐
│ ⚠️  SECURITY TASK — LOCAL MODEL ONLY          │
│                                                │
│ This task involves security-sensitive analysis. │
│ Limitations:                                   │
│   • May miss subtle vulnerabilities            │
│   • Should NOT be treated as a security audit  │
│                                                │
│ Recommendation:                                │
│   Re-run in HYBRID mode before production.     │
└────────────────────────────────────────────────┘

Proceed with local analysis? [y/n]: y

[Router: COMPLEX → gemma4:26b]
...

⚠️  This security analysis was performed by a local model.
   Add to pending queue for cloud re-analysis? [y/n]: y
   Queued as a1b2c3. Use '/retry a1b2c3' in HYBRID mode.
```

#### Shell Command Approval Flow

```
> Run the test suite for the payment module

[Agent] Requesting shell execution:

┌─ Shell Execution Request ─────────────────────┐
│ Command:  pytest tests/test_payment.py -v     │
│ Risk:     🟢 LOW                              │
└───────────────────────────────────────────────┘

  approve / deny / edit  → approve

[Executing...]
12 tests passed, 0 failed
```

#### Package Installation with Security Assessment

```
> Install the requests library for HTTP calls

[Agent] Requesting package installation:

┌─ ⚠️  Package Installation Request ────────────┐
│ Command:     pip install requests              │
│ Risk:        🟠 HIGH — package installation    │
│                                                │
│ Assessment:                                    │
│ Name:        requests                          │
│ Reason:      Required for HTTP client          │
│              functionality in the API module.  │
│                                                │
│ Security:    ✅ Well-maintained, widely used,  │
│              active CVE monitoring.            │
│                                                │
│ ⓘ  This assessment is AI-generated. Verify    │
│    security claims independently.              │
└────────────────────────────────────────────────┘

  approve / deny / edit  → approve
```

### CLI Commands

| Command | Description |
|---|---|
| `/mode` | Show current operation mode |
| `/mode hybrid` | Switch to HYBRID mode (local + cloud) |
| `/mode local` | Switch to LOCAL_ONLY mode |
| `/pending` | List all pending tasks |
| `/retry <id>` | Retry a specific pending task |
| `/retry all` | Retry all pending tasks |
| `/pending discard <id>` | Discard a pending task |
| `/pending clear` | Clear all pending tasks |
| `/health` | Show API health status and tier timeouts |
| `/quit` | Exit the agent |
| `Ctrl+C` | Cancel the current request |

### Operation Modes

| Mode | Local Models | Claude API | Security Tasks |
|---|---|---|---|
| **HYBRID** | SIMPLE + MEDIUM tiers | COMPLEX + Security tiers | Full capability |
| **LOCAL_ONLY** | All tiers | Disabled | Local model + disclaimer + optional pending queue |

---

## Docker Sandbox (Production)

For sandboxed execution where the agent runs inside an isolated container.

### Build the Sandbox

```bash
docker compose build
```

### Run with a Project Workspace

```bash
# Set your project path and API key
export PROJECT_PATH=/path/to/your/project
export ANTHROPIC_API_KEY=sk-ant-your-key-here

# Run the agent in sandbox
docker compose run --rm agent
```

### Sandbox Security Controls

The Docker sandbox provides:

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

Every shell command passes through:

1. **Gate 1 (Parser)** — Detects command chaining, subshells, pipes, redirects, and encoding obfuscation
2. **Gate 2 (Policy)** — Checks against command allowlist and blocked patterns. Enhanced approval for `rm` (requires justification) and `pip install` (requires security assessment)
3. **Gate 3 (Human)** — Displays command with risk level and waits for approve/deny/edit

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

### File System Protection

- All paths validated against workspace boundary
- Path traversal (`../`) detected and blocked
- Symlinks resolved and re-validated
- Directory deletion not permitted
- Wildcard deletion (`rm *`) not permitted

---

## Configuration

### Routing Rules (config/routing_rules.yml)

Customize task classification by editing keywords:

```yaml
security_override:
  keywords:
    - "your-custom-security-keyword"

task_keywords:
  SIMPLE:
    phrases:
      - "your custom simple phrase"
  MEDIUM:
    phrases:
      - "your custom medium phrase"

tier_timeouts:
  SIMPLE: 30
  MEDIUM: 120
  COMPLEX: 180
```

### Command Allowlist (config/allowed_commands.yml)

Add or remove permitted shell commands:

```yaml
allowed:
  - python
  - pytest
  - your-custom-tool
```

---

## Troubleshooting

### Ollama Issues

#### Cannot connect to Ollama

```bash
# Check if Ollama is running
curl -s http://localhost:11434/api/version

# If not running, start it
ollama serve

# Or restart via menu bar icon on macOS
```

#### Model not found

```bash
# Check available models
ollama list

# Pull the missing model
ollama pull gemma4:26b
ollama pull gemma4:e4b
```

#### Slow response from Gemma 4 26B

```bash
# Check if model is fully loaded in GPU
ollama ps

# Ensure no other heavy apps are consuming memory
# Close browsers, IDEs with large projects, etc.

# Reduce context window if needed
cat << EOF > Modelfile
FROM gemma4:26b
PARAMETER num_ctx 8192
EOF
ollama create gemma4-custom -f Modelfile
```

#### Ollama listening on 0.0.0.0 (security risk)

```bash
# Fix: Bind to localhost only
export OLLAMA_HOST=127.0.0.1:11434
# Add to ~/.zshrc for persistence

# Restart Ollama and verify
lsof -i :11434
# Should show 127.0.0.1 or localhost
```

### Claude API Issues

#### ANTHROPIC_API_KEY is not set

```bash
# Check your .env file
cat .env | grep ANTHROPIC

# If missing, add it
echo 'ANTHROPIC_API_KEY=sk-ant-your-key-here' >> .env
```

#### Claude API rate limit exceeded

The agent will automatically fall back to local models for non-security tasks. Security tasks will be queued. Wait a few minutes and use `/retry all`.

#### Claude API unavailable

```bash
# Check health status inside the agent CLI:
/health

# The health checker polls every 60 seconds
# You'll be notified when API recovers
```

### Python / Dependency Issues

#### ModuleNotFoundError: No module named 'src'

```bash
# Ensure you're in the project directory with venv activated
cd hybrid-ai-agent
source .venv/bin/activate

# Reinstall in editable mode
pip install -e ".[dev]"
```

#### Test failures after changes

```bash
# Run the full suite
pytest tests/ -v --tb=short

# Run only security tests (most critical)
pytest tests/test_security.py -v

# Run with detailed output on failure
pytest tests/ -v --tb=long
```

### Docker Sandbox Issues

#### docker compose build fails

```bash
# Ensure Docker Desktop is running
docker info

# Build with no cache
docker compose build --no-cache
```

#### Permission denied inside container

The container runs as non-root (`agent:1000`). Only `/workspace` and `/tmp` are writable. This is by design.

#### Cannot connect to Ollama from container

```bash
# Verify host.docker.internal resolves
docker run --rm alpine ping -c 1 host.docker.internal

# Check Ollama is listening on host
curl http://localhost:11434/api/version
```

---

## Testing

```bash
# Run all 155 tests
pytest tests/ -v --tb=short

# Run by category
pytest tests/test_router.py -v        # 40 routing tests
pytest tests/test_sanitizer.py -v     # 22 sanitizer tests
pytest tests/test_permissions.py -v   # 8 permission tests
pytest tests/test_integration.py -v   # 28 integration tests
pytest tests/test_security.py -v      # 57 security attack tests

# Run linter with security rules
ruff check src/ tests/
```

---

## Project Structure

```
hybrid-ai-agent/
├── src/
│   ├── main.py              # CLI entry point
│   ├── router/              # Task classification
│   ├── agent/               # ReAct loop orchestration
│   ├── models/              # LLM clients + health/queue
│   ├── tools/               # Sandboxed file/shell/git ops
│   └── security/            # Permissions, sanitizer, audit
├── config/                  # Routing rules, command policies
├── tests/                   # 155 tests (security-focused)
├── Dockerfile               # Sandbox container definition
├── docker-compose.yml       # Sandbox orchestration
├── BACKLOG.md              # Deferred items for next phase
└── README.md               # This file
```

---

## License

MIT - Use freely, modify as needed, contribute back if you can.

