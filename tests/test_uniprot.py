from types import SimpleNamespace

import pytest
import requests

from services import uniprot

ENTRY = {
    "primaryAccession": "P00533",
    "uniProtkbId": "EGFR_HUMAN",
    "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
    "proteinDescription": {
        "recommendedName": {"fullName": {"value": "Epidermal growth factor receptor"}}
    },
    "genes": [{"geneName": {"value": "EGFR"}}],
    "sequence": {"length": 1210},
    "comments": [
        {"commentType": "DISEASE", "disease": {"diseaseId": "Lung cancer"}},
        {"commentType": "FUNCTION", "texts": [{"value": "Receptor tyrosine kinase."}]},
    ],
    "uniProtKBCrossReferences": [
        {"database": "EMBL", "id": "X00588"},
        {
            "database": "PDB",
            "id": "1IVO",
            "properties": [
                {"key": "Method", "value": "X-ray"},
                {"key": "Resolution", "value": "3.30 A"},
            ],
        },
        {
            "database": "PDB",
            "id": "NMR1",
            "properties": [{"key": "Method", "value": "NMR"}, {"key": "Resolution", "value": "-"}],
        },
        {
            "database": "PDB",
            "id": "1M17",
            "properties": [
                {"key": "Method", "value": "X-ray"},
                {"key": "Resolution", "value": "2.60 A"},
            ],
        },
    ],
}


@pytest.mark.parametrize(
    "value", ["P00533", "Q5S007", "A0A024R1R8", "O14788", "A2BC19"]
)
def test_valid_accessions(value):
    assert uniprot.is_valid_accession(value)


@pytest.mark.parametrize(
    "value",
    ["", "p00533", "P0053", "P12345/../x", "1ABC", "P00533?x=1", "../../etc", None, 5],
)
def test_invalid_accessions(value):
    assert not uniprot.is_valid_accession(value)


def test_parse_entry_finds_function_even_when_not_first():
    record = uniprot.parse_entry(ENTRY)
    assert record["function"] == "Receptor tyrosine kinase."
    assert record["diseases"] == ["Lung cancer"]
    assert record["gene"] == "EGFR"
    assert record["length"] == 1210


def test_best_pdb_prefers_highest_resolution():
    assert uniprot.parse_entry(ENTRY)["best_pdb"]["id"] == "1M17"


def test_best_pdb_handles_structures_without_resolution():
    entry = {
        "uniProtKBCrossReferences": [
            {"database": "PDB", "id": "NMR1", "properties": [{"key": "Resolution", "value": "-"}]}
        ]
    }
    best = uniprot.parse_entry(entry)["best_pdb"]
    assert best["id"] == "NMR1"
    assert best["resolution"] is None


def test_parse_entry_tolerates_sparse_data():
    record = uniprot.parse_entry({"primaryAccession": "P00533", "uniProtkbId": "EGFR_HUMAN"})
    assert record["name"] == "EGFR_HUMAN"
    assert record["function"] == ""
    assert record["diseases"] == []
    assert record["best_pdb"] is None


def test_parse_entry_uses_submission_name_for_unreviewed():
    entry = {
        "primaryAccession": "A0A024R1R8",
        "proteinDescription": {"submissionNames": [{"fullName": {"value": "Submitted"}}]},
    }
    assert uniprot.parse_entry(entry)["name"] == "Submitted"


def test_function_text_drops_citations_and_never_cuts_mid_word():
    sentence = "Catalyzes the transfer of a sulfate group to lipids (PubMed:8830034, PubMed:9030544). "
    entry = {"comments": [{"commentType": "FUNCTION", "texts": [{"value": sentence * 30}]}]}
    function = uniprot.parse_entry(entry)["function"]
    assert "PubMed" not in function
    assert len(function) <= uniprot.FUNCTION_CHARS
    assert function.endswith("lipids.")


def test_function_text_without_sentences_ends_with_ellipsis():
    entry = {"comments": [{"commentType": "FUNCTION", "texts": [{"value": "word " * 500}]}]}
    function = uniprot.parse_entry(entry)["function"]
    assert function.endswith("word…")


def test_aliases_include_alternative_names_and_gene_synonyms():
    entry = {
        "proteinDescription": {
            "recommendedName": {"fullName": {"value": "Receptor tyrosine-protein kinase erbB-2"}},
            "alternativeNames": [
                {"fullName": {"value": "Proto-oncogene Neu"}, "shortNames": [{"value": "MLN 19"}]}
            ],
        },
        "genes": [{"geneName": {"value": "ERBB2"}, "synonyms": [{"value": "HER2"}]}],
    }
    aliases = uniprot.parse_entry(entry)["aliases"]
    assert {"Proto-oncogene Neu", "MLN 19", "ERBB2", "HER2"} <= set(aliases)


HER2 = {"aliases": ["Receptor tyrosine-protein kinase erbB-2", "ERBB2", "HER2", "NEU"]}
TAU = {"aliases": ["Microtubule-associated protein tau", "MAPT", "PHF-tau"]}
IDE = {"aliases": ["Insulin-degrading enzyme", "IDE", "Insulysin"]}
INSR = {"aliases": ["Insulin receptor", "IR", "INSR"]}


@pytest.mark.parametrize(
    "name, record",
    [
        ("HER2", HER2),
        ("HER2 (Human Epidermal Growth Factor Receptor 2)", HER2),
        ("HER2 receptor", HER2),
        ("erbB-2", HER2),
        ("Tau protein", TAU),
        ("Microtubule-associated protein tau", TAU),
        ("Insulin Receptor (INSR)", INSR),
    ],
)
def test_names_match_accepts_real_names(name, record):
    assert uniprot.names_match(name, record)


@pytest.mark.parametrize(
    "name, record",
    [
        ("Tau protein", HER2),
        ("Insulin receptor", IDE),
        ("Protein", TAU),
        ("", HER2),
    ],
)
def test_names_match_rejects_other_proteins(name, record):
    assert not uniprot.names_match(name, record)


GCKR = {
    "uniprot_id": "Q14397",
    "taxon_id": 9606,
    "aliases": ["Glucokinase regulatory protein", "GKRP", "GCKR"],
}
GCK = {
    "uniprot_id": "P35557",
    "taxon_id": 9606,
    "aliases": ["Hexokinase-4", "Glucokinase", "GCK"],
}
PSEUDOGENE = {
    "uniprot_id": "Q14568",
    "taxon_id": 9606,
    "aliases": ["Heat shock protein HSP 90-alpha A2", "Heat shock protein HSP 90-alpha A2 pseudogene"],
}


def test_match_strength_separates_exact_from_partial():
    assert uniprot.match_strength("Glucokinase", GCK) == uniprot.MATCH_EXACT
    assert uniprot.match_strength("Glucokinase", GCKR) == uniprot.MATCH_PARTIAL
    assert uniprot.match_strength("Tau protein", TAU) == uniprot.MATCH_PARTIAL
    assert uniprot.match_strength("Tau protein", HER2) == uniprot.MATCH_NONE


def test_partial_match_never_accepts_a_pseudogene():
    assert uniprot.match_strength("Heat shock protein 90 alpha", PSEUDOGENE) == uniprot.MATCH_NONE
    assert uniprot.match_strength("HSP 90-alpha A2 pseudogene", PSEUDOGENE) == uniprot.MATCH_NONE


def test_exact_name_beats_a_partial_match_on_the_given_accession(monkeypatch):
    monkeypatch.setattr(uniprot, "get_protein", lambda accession: GCKR)
    monkeypatch.setattr(uniprot, "search", lambda name, limit=5: [GCKR, GCK])
    record = uniprot.resolve_target({"uniprot_id": "Q14397", "name": "Glucokinase"})
    assert record["uniprot_id"] == "P35557"


def test_partial_match_is_kept_when_nothing_better_exists(monkeypatch):
    tau = {**TAU, "uniprot_id": "P10636", "taxon_id": 9606}
    monkeypatch.setattr(uniprot, "get_protein", lambda accession: tau)
    monkeypatch.setattr(uniprot, "search", lambda name, limit=5: [HER2])
    assert uniprot.resolve_target({"uniprot_id": "P10636", "name": "Tau protein"}) is tau


def test_exact_match_on_the_given_accession_needs_no_search(monkeypatch):
    def fail(name, limit=5):
        raise AssertionError("should not search")

    monkeypatch.setattr(uniprot, "get_protein", lambda accession: GCK)
    monkeypatch.setattr(uniprot, "search", fail)
    assert uniprot.resolve_target({"uniprot_id": "P35557", "name": "Glucokinase"}) is GCK


def test_names_match_without_aliases_is_false():
    assert not uniprot.names_match("HER2", {})


def test_find_by_name_skips_unrelated_hits(monkeypatch):
    monkeypatch.setattr(uniprot, "search", lambda name, limit=5: [IDE, INSR])
    assert uniprot.find_by_name("Insulin receptor") is INSR


def test_find_by_name_survives_outage(monkeypatch):
    def boom(name, limit=5):
        raise uniprot.UpstreamError("down")

    monkeypatch.setattr(uniprot, "search", boom)
    assert uniprot.find_by_name("Insulin receptor") is None


def test_is_human_uses_taxon_id():
    assert uniprot.is_human({"taxon_id": 9606})
    assert not uniprot.is_human({"taxon_id": 10090})
    assert not uniprot.is_human(None)


def test_extract_keywords_removes_stop_words_and_syntax():
    assert uniprot.extract_keywords("Alzheimer's disease protein targets") == ["Alzheimer", "disease"]


def test_extract_keywords_cannot_escape_the_human_filter():
    keywords = uniprot.extract_keywords('tau") OR (organism_id:10090')
    assert keywords == ["tau", "organism", "10090"]


def test_search_relaxes_until_it_finds_results(monkeypatch):
    attempts = []

    def fake_search(terms, reviewed, limit):
        attempts.append((list(terms), reviewed))
        return [ENTRY] if len(terms) == 1 else []

    monkeypatch.setattr(uniprot, "_search_once", fake_search)
    results = uniprot.search("insulin resistance muscle signaling")
    assert results[0]["uniprot_id"] == "P00533"
    assert attempts == [
        (["insulin", "resistance", "muscle", "signaling"], True),
        (["insulin", "resistance"], True),
        (["insulin"], True),
    ]


def test_search_returns_empty_without_keywords():
    assert uniprot.search("???") == []


def test_search_reports_upstream_failure(monkeypatch):
    def boom(terms, reviewed, limit):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(uniprot, "_search_once", boom)
    with pytest.raises(uniprot.UpstreamError):
        uniprot.search("insulin")


def test_failed_lookups_are_not_cached(monkeypatch):
    responses = [
        requests.ConnectionError("down"),
        SimpleNamespace(status_code=200, json=lambda: ENTRY),
    ]

    def fake_get(*args, **kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(uniprot.session, "get", fake_get)
    assert uniprot.get_protein("P00533") is None
    assert uniprot.get_protein("P00533")["gene"] == "EGFR"


def test_invalid_accession_makes_no_request(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("should not be called")

    monkeypatch.setattr(uniprot.session, "get", fail)
    assert uniprot.get_protein("../../etc") is None


def test_unknown_accession_returns_none(monkeypatch):
    monkeypatch.setattr(
        uniprot.session, "get", lambda *a, **k: SimpleNamespace(status_code=404)
    )
    assert uniprot.get_protein("P99999") is None


def test_inactive_entry_returns_none(monkeypatch):
    monkeypatch.setattr(
        uniprot.session,
        "get",
        lambda *a, **k: SimpleNamespace(
            status_code=200, json=lambda: {"entryType": "Inactive", "primaryAccession": "P99999"}
        ),
    )
    assert uniprot.get_protein("P99999") is None


def test_describe_relevance_only_states_facts():
    assert "Lung cancer" in uniprot.describe_relevance({"diseases": ["Lung cancer"]}, "q")
    assert uniprot.describe_relevance({"diseases": []}, "tau") == 'UniProt match for "tau".'
