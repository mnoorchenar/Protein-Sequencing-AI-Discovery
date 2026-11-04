import pytest

from services import knowledge, uniprot


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Alzheimer's disease targets", "P05067"),
        ("BREAST CANCERS", "P00533"),
        ("back pain relief", "P35354"),
    ],
)
def test_lookup_matches_disease_terms(text, expected):
    accessions = [p["uniprot_id"] for p in knowledge.lookup(text)]
    assert expected in accessions


@pytest.mark.parametrize("text", ["travel in Spain", "the sheart", "", "unrelated query"])
def test_lookup_ignores_matches_inside_words(text):
    assert knowledge.lookup(text) == []


def test_lookup_combines_diseases_without_duplicates_and_respects_limit():
    results = knowledge.lookup("psoriasis arthritis crohn", limit=5)
    accessions = [p["uniprot_id"] for p in results]
    assert len(accessions) == len(set(accessions))
    assert 1 < len(accessions) <= 5


def test_lookup_returns_copies():
    first = knowledge.lookup("alzheimer")
    first[0]["name"] = "changed"
    assert knowledge.lookup("alzheimer")[0]["name"] != "changed"


def test_database_is_loaded_and_well_formed():
    assert knowledge.DATABASE
    for disease, entries in knowledge.DATABASE.items():
        assert disease == disease.lower()
        assert entries
        for entry in entries:
            assert uniprot.is_valid_accession(entry["uniprot_id"]), entry
            for field in ("name", "relevance", "function", "drugs"):
                assert entry[field].strip(), (disease, field)


def test_missing_database_file_is_survivable(tmp_path):
    assert knowledge.load_database(tmp_path / "missing.json") == {}


def test_invalid_database_file_is_survivable(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    assert knowledge.load_database(path) == {}
