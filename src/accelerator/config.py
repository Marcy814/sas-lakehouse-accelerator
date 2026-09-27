import os
from datetime import date
from pathlib import Path

ROOT = Path(os.environ.get("ACCELERATOR_ROOT", Path(__file__).resolve().parents[2]))

DATA_DIR = ROOT / "data"
LANDING_DIR = DATA_DIR / "landing"
WAREHOUSE_DIR = ROOT / "warehouse"
DB_PATH = Path(os.environ.get("LAKEHOUSE_DB_PATH", WAREHOUSE_DIR / "lakehouse.duckdb"))

LEGACY_DIR = ROOT / "legacy"
SAS_DIR = LEGACY_DIR / "sas"
LEGACY_OUTPUT_DIR = LEGACY_DIR / "outputs"

DBT_DIR = ROOT / "lakehouse"
AGENT_SANDBOX_DIR = DBT_DIR / "models" / "agent_sandbox"
MIGRATION_CONFIG = ROOT / "migration" / "migration.yml"
REPORTS_DIR = ROOT / "reports"

SOURCE_TABLES = ("clients", "polices", "sinistres", "enquetes")

DATE_REF = date(2026, 6, 30)
RATIO_YEARS = (2023, 2024, 2025)

BATCH_EXTRACT_DATES = {1: date(2026, 5, 31), 2: date(2026, 6, 30)}
