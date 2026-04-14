# AGENTS.md

Guidance for coding agents operating in `/home/cells/school/embedded`.

## 1) Scope and Intent

- This repo contains multiple Python applications for smart material management.
- Primary stacks: `tkinter`, `socket`, `opencv-python (cv2)`, `face_recognition`, `qrcode`, `Pillow`, `RPi.GPIO`.
- There is no centralized packaging config (`pyproject.toml`, `setup.cfg`, `requirements.txt` were not found).
- Prefer minimal, targeted edits; avoid broad refactors unless explicitly requested.

## 2) Rule Files (Cursor/Copilot)

- Checked for Cursor and Copilot rule files:
  - `.cursorrules`: not found
  - `.cursor/rules/`: not found
  - `.github/copilot-instructions.md`: not found
- Therefore, this `AGENTS.md` is the canonical agent instruction file for this repository.

## 3) Repository Map

- `system/`: modular local app + web dashboard
  - `main.py`: Tkinter operator/admin UI
  - `camera_capture.py`, `face_manager.py`, `qr_manager.py`, `hardware_manager.py`, `data_logger.py`
  - `web_dashboard.py`: HTTP dashboard for material log visualization
  - `public_dashboard_ngrok.py`: helper to expose dashboard publicly via ngrok
- `server/`: integrated TCP server + optional Tkinter server UI
  - `integrated_server.py` (main entry)
- `client/`: integrated client + test scripts
  - `smart_client.py` (main entry)

## 4) Environment and Dependencies

- Python used in this repo is currently 3.13 in local conda envs.
- Recommended environment for commands (if available): `ai`.
- Example command prefix:

```bash
conda run -n ai python <script_or_module>
```

- Hardware-related modules (`RPi.GPIO`, `rpicam-still`) may fail on non-Raspberry Pi hosts.
- For non-hardware verification, prefer syntax checks and pure-Python unit tests.

## 5) Build / Run Commands

There is no formal build step; run scripts directly.

### Main runtime commands

```bash
# System modular UI
python system/main.py

# System dashboard
python system/web_dashboard.py --host 0.0.0.0 --port 8080

# Public tunnel wrapper (requires ngrok auth token)
conda run -n ai python system/public_dashboard_ngrok.py --authtoken "<token>"

# Server (UI mode / CLI mode)
python server/integrated_server.py --type ui
python server/integrated_server.py --type cli

# Client
python client/smart_client.py
```

### Quick syntax build-check (recommended after edits)

```bash
python -m py_compile system/*.py client/*.py server/*.py
```

## 6) Lint / Format / Type Commands

No lint/type tools are configured in-repo. If needed, install and run locally.

```bash
# Optional tooling install
python -m pip install ruff black mypy flake8 pytest

# Lint (choose one style)
python -m ruff check system client server
python -m flake8 system client server

# Format
python -m black system client server

# Type-check (best effort; project is partially typed)
python -m mypy system client server
```

Agent rule: do not introduce a mandatory toolchain file unless requested by user.

## 7) Test Commands (with single-test focus)

There is currently no `tests/` directory. Add `pytest` tests for new pure logic when possible.

```bash
# Run all tests
python -m pytest

# Run a single test file
python -m pytest tests/test_web_dashboard.py

# Run one specific test function
python -m pytest tests/test_web_dashboard.py::test_build_dashboard_data_groups_instances

# Run one specific test in class
python -m pytest tests/test_web_dashboard.py::TestAggregation::test_partial_stock_state

# Run tests by keyword
python -m pytest -k "dashboard and partial"

# Stop on first failure
python -m pytest -x
```

If no tests exist for your change, run at least:

```bash
python -m py_compile system/*.py client/*.py server/*.py
```

## 8) Code Style Guidelines

### Imports

- Order imports: standard library -> third-party -> local modules.
- One import per line where practical.
- Avoid wildcard imports.
- Keep side-effect imports explicit (e.g., `RPi.GPIO` usage is hardware-dependent).

### Formatting

- Follow PEP 8 with 4-space indentation.
- Keep lines readable (target <= 100 chars where possible).
- Use blank lines between logical blocks and top-level definitions.
- Prefer f-strings for interpolation.

### Types

- Add type hints for new/modified functions, especially in `system/web_dashboard.py` and utility code.
- Use concrete container types where helpful (`list[str]`, `dict[str, Any]`).
- Keep runtime compatibility in mind; avoid over-complicated typing.

### Naming

- `snake_case`: functions, methods, variables, module-level helpers.
- `PascalCase`: classes.
- `UPPER_SNAKE_CASE`: module constants.
- Preserve existing protocol command literals (`RECOGNIZE`, `REGISTER`, `DATA`, `SYNC_MAT`, etc.).

### Error handling

- Do not silently swallow exceptions.
- Catch specific exceptions when practical; otherwise log actionable context.
- UI paths: show user-safe messages; background paths: log diagnostics.
- Network/file operations should be wrapped with robust error handling and retries where already established.

### Concurrency and UI

- Do not block Tkinter main thread with long operations.
- Use daemon threads for background work.
- Any Tkinter UI mutation from worker threads must be scheduled via `root.after(...)`.
- Keep image references (`PhotoImage`) alive to prevent blank widgets.

### Network protocol and data contracts

- TCP protocol in `server/integrated_server.py` and `client/smart_client.py` is string-command based.
- For image transfers: command includes byte length, then handshake (`ok`), then raw bytes.
- When changing protocol, update both client and server in the same change.
- CSV schema expectation: `Timestamp,Person,Action,Material Info`.

### Hardware and platform safety

- Guard hardware-specific behavior (`RPi.GPIO`, camera shell commands) for non-RPi environments when adding new code.
- Avoid destructive GPIO operations in non-test code paths.
- Ensure cleanup paths call GPIO cleanup where appropriate.

### Web dashboard conventions

- `system/web_dashboard.py` is a single-file server+UI implementation; keep dependencies minimal.
- Preserve UTF-8 CSV reading and JSON responses with `ensure_ascii=False`.
- Keep API endpoints stable unless explicitly asked (`/api/summary`, `/api/material/<key>`).

## 9) Change Workflow for Agents

- Read related files first; mirror existing architecture and naming.
- Make small, reversible edits.
- Validate with syntax checks and targeted runtime checks.
- Do not commit, rewrite history, or delete unrelated files unless user explicitly asks.
- Never revert user-authored unrelated changes.

## 10) Practical Verification Checklist

- Edited files compile with `py_compile`.
- Client/server protocol still round-trips successfully for touched commands.
- Tkinter paths remain responsive (no obvious main-thread blocking).
- Dashboard endpoints return valid JSON after data-model changes.
- Any new tests include at least one single-test invocation example in notes.
