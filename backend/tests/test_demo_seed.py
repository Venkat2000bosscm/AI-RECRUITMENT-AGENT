import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = BACKEND_ROOT / "scripts" / "seed_demo.py"


def test_seed_command_creates_synthetic_data_and_is_idempotent(tmp_path):
    database_path = tmp_path / "demo.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    command = [
        sys.executable,
        str(SEED_SCRIPT),
        "--database-url",
        database_url,
        "--jobs",
        "3",
        "--candidates",
        "9",
    ]

    first_run = subprocess.run(command, cwd=BACKEND_ROOT, check=True, capture_output=True, text=True, timeout=60)
    assert "Seeded demo database: 3 jobs, 9 applications." in first_run.stdout
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM candidates").fetchone()[0] == 9
        assert connection.execute("SELECT count(*) FROM audit_logs").fetchone()[0] > 0

    second_run = subprocess.run(command, cwd=BACKEND_ROOT, check=True, capture_output=True, text=True, timeout=60)
    assert "already exists" in second_run.stdout
