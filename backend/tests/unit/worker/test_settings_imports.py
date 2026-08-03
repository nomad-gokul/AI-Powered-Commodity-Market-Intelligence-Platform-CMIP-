"""Regression test for a real bug caught by running the actual
docker-compose stack (not by pytest, which shares one process across
many test files and so already has every module's models imported by
the time any worker test runs - masking this exact failure mode).

A standalone `arq app.worker.settings.WorkerSettings` process only
imports what app.worker.settings' import chain pulls in. Document.
uploaded_by is a ForeignKey("users.id"), so SQLAlchemy needs
app.modules.auth.models registered on Base.metadata before any query
touching Document runs, or FK resolution fails at runtime with
"could not find table 'users'". This is only reproducible in a fresh
Python process, so this test spawns one via subprocess rather than
importing app.worker.settings in-process.
"""

import subprocess
import sys


def test_importing_worker_settings_registers_every_fk_referenced_table() -> None:
    script = (
        "from app.worker import settings\n"
        "from app.core.database import Base\n"
        "tables = set(Base.metadata.tables)\n"
        "assert 'users' in tables, f'users table missing from metadata: {tables}'\n"
        "assert 'documents' in tables, f'documents table missing from metadata: {tables}'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout
