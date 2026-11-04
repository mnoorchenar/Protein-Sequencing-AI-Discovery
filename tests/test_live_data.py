"""Checks against the real public APIs. Run with: pytest -m network"""

import pytest

from services import knowledge, structure, uniprot

pytestmark = pytest.mark.network


def test_curated_accessions_are_human_uniprot_entries():
    accessions = sorted(
        {entry["uniprot_id"] for entries in knowledge.DATABASE.values() for entry in entries}
    )
    records = dict(zip(accessions, uniprot.get_proteins(accessions), strict=True))
    wrong = [accession for accession, record in records.items() if not uniprot.is_human(record)]
    assert wrong == []


def test_curated_names_match_their_uniprot_entries():
    """Proves the name check works on real records, and catches mislabelled curated data."""
    names = {
        entry["uniprot_id"]: entry["name"]
        for entries in knowledge.DATABASE.values()
        for entry in entries
    }
    mismatched = [
        (accession, name)
        for accession, name in names.items()
        if not uniprot.names_match(name, uniprot.get_protein(accession))
    ]
    assert mismatched == []


def test_ai_style_wrong_accession_is_corrected():
    # Q99999 is a real human protein (GAL3ST1), but it isn't tau.
    record = uniprot.resolve_target({"uniprot_id": "Q99999", "name": "Tau protein"})
    assert record["uniprot_id"] == "P10636"


def test_exact_name_wins_over_a_partial_match():
    # Q14397 is the glucokinase regulatory protein, not glucokinase itself.
    record = uniprot.resolve_target({"uniprot_id": "Q14397", "name": "Glucokinase"})
    assert record["gene"] == "GCK"


def test_uniprot_search_returns_human_proteins():
    results = uniprot.search("EGFR lung cancer")
    assert results
    assert all(record["taxon_id"] == uniprot.HUMAN_TAXON_ID for record in results)


def test_alphafold_structure_is_downloadable():
    record = uniprot.get_protein("P05067")
    result = structure.get_structure(record)
    assert result["source"] == "alphafold"
    assert "ATOM  " in result["pdb_data"]
    assert result["mean_plddt"] > 0


def test_experimental_structure_is_downloadable():
    record = uniprot.get_protein("P00533")
    result = structure.get_structure(record, "pdb")
    assert result["source"] == "pdb"
    assert "ATOM  " in result["pdb_data"]
