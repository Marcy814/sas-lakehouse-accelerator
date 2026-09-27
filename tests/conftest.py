import pytest

from accelerator import config


@pytest.fixture
def lakehouse_available():
    if not config.DB_PATH.exists() or not (config.LEGACY_OUTPUT_DIR / "clients_courants.csv").exists():
        pytest.skip("Entrepôt non construit : exécuter `python pipeline.py run-all` au préalable.")
    return config.DB_PATH
