from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from accelerator import config


@dataclass
class DbtResult:
    success: bool
    output: str

    def tail(self, lines: int = 40) -> str:
        return "\n".join(self.output.strip().splitlines()[-lines:])


def run_dbt(
    args: list[str], db_path: Path = config.DB_PATH, stream: bool = False, extra_env: dict[str, str] | None = None
) -> DbtResult:
    env = os.environ | {"LAKEHOUSE_DB_PATH": str(Path(db_path).resolve()), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    env |= extra_env or {}
    commande = [
        sys.executable, "-c", "from dbt.cli.main import cli; cli()",
        *args,
        "--project-dir", str(config.DBT_DIR),
        "--profiles-dir", str(config.DBT_DIR),
    ]
    if stream:
        processus = subprocess.run(commande, cwd=config.DBT_DIR, env=env)
        return DbtResult(processus.returncode == 0, "")
    commande.append("--no-use-colors")
    processus = subprocess.run(
        commande, cwd=config.DBT_DIR, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return DbtResult(processus.returncode == 0, processus.stdout + processus.stderr)
