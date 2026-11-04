import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from services import ratelimit, structure, uniprot  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    """Caches and rate-limit counters must not leak between tests."""
    uniprot._fetch_entry.cache_clear()
    structure._fetch_alphafold.cache_clear()
    structure._fetch_experimental.cache_clear()
    ratelimit.reset()
    yield


@pytest.fixture
def client():
    app = create_app({"TESTING": False, "LLM_RATE_LIMIT_PER_MINUTE": 0})
    return app.test_client()


def make_record(accession="P00533", taxon_id=9606, organism="Homo sapiens", **overrides):
    record = {
        "uniprot_id": accession,
        "name": "Epidermal growth factor receptor",
        "gene": "EGFR",
        "organism": organism,
        "taxon_id": taxon_id,
        "length": 1210,
        "function": "Receptor tyrosine kinase.",
        "diseases": ["Lung cancer"],
        "aliases": ["Epidermal growth factor receptor", "EGFR", "ERBB1", "HER1"],
        "best_pdb": {"id": "1M17", "method": "X-ray", "resolution": "2.60 A"},
    }
    record.update(overrides)
    return record
