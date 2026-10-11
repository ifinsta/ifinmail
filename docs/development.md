# Development quickstart

Prerequisites: Python 3.12, Docker (only for full stack).

```powershell
cp .env.example .env
venv\Scripts\python -m pip install -r requirements/development.txt
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py runserver
```

Open `http://127.0.0.1:8000/accounts/login/`.

Useful targets (`Makefile`):

| Command | What it does |
|---|---|
| `make migrate` / `make run` / `make shell` | Django basics |
| `venv\Scripts\python -m pytest -q` | Full suite (uses `venv`, not system python) |
| `make test TEST_ARGS="-k accounts"` | Filtered suite |
| `make coverage` | `--cov=backend` term + html |
| `make lint` / `make format-check` | `ruff check` / `ruff format --check` |
| `make lint-fix` / `make fmt` | Autofix |
| `make check` | Django system checks |
| `make provision DOMAIN=example.com` | Full production stack (needs `provisioning/.env`) |
| `make up` / `make ps` / `make logs` / `make health` | Compose lifecycle (needs `provisioning/.env`) |

Notes:

* Always use `venv\Scripts\python` — system Python lacks `ninja` and fails
  collection with `ModuleNotFoundError: No module named 'ninja'`.
* `USE_SQLITE=1` (default in `.env.example`) avoids Postgres/Redis locally.
* Windows: `test_provisioning_contract.py:ShellSyntaxTests` skips without bash.
* Before committing: `ruff check backend`, `ruff format --check backend`,
  `pytest -q`.
