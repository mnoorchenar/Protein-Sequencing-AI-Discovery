from types import SimpleNamespace

import requests

from services import structure
from tests.conftest import make_record

PDB_TEXT = "HEADER\nATOM      1  CA  ALA A   1      0.0  0.0  0.0\nEND\n"
AF_URL = "https://alphafold.ebi.ac.uk/files/AF-P00533-F1-model_v6.pdb"


def response(status=200, text="", json_data=None):
    def raise_for_status():
        if status >= 400:
            raise requests.HTTPError(str(status))

    return SimpleNamespace(
        status_code=status,
        text=text,
        json=lambda: json_data,
        raise_for_status=raise_for_status,
    )


def router(monkeypatch, routes):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        for prefix, result in routes.items():
            if url.startswith(prefix):
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(structure.session, "get", fake_get)
    return calls


PREDICTION = [{"pdbUrl": AF_URL, "latestVersion": 6, "globalMetricValue": 75.9}]


def test_alphafold_file_url_comes_from_the_api(monkeypatch):
    calls = router(
        monkeypatch,
        {
            structure.ALPHAFOLD_API: response(json_data=PREDICTION),
            AF_URL: response(text=PDB_TEXT),
        },
    )
    result = structure.get_structure(make_record())
    assert result["source"] == "alphafold"
    assert result["mean_plddt"] == 75.9
    assert "v6" in result["label"]
    assert AF_URL in calls


def test_falls_back_to_experimental_structure(monkeypatch):
    router(
        monkeypatch,
        {
            structure.ALPHAFOLD_API: response(status=404),
            structure.RCSB_FILES: response(text=PDB_TEXT),
        },
    )
    result = structure.get_structure(make_record())
    assert result["source"] == "pdb"
    assert result["pdb_id"] == "1M17"
    assert "2.60 A" in result["label"]


def test_can_prefer_experimental(monkeypatch):
    calls = router(monkeypatch, {structure.RCSB_FILES: response(text=PDB_TEXT)})
    result = structure.get_structure(make_record(), "pdb")
    assert result["source"] == "pdb"
    assert len(calls) == 1


def test_preferring_experimental_falls_back_to_alphafold(monkeypatch):
    router(
        monkeypatch,
        {
            structure.RCSB_FILES: response(status=404),
            structure.ALPHAFOLD_API: response(json_data=PREDICTION),
            AF_URL: response(text=PDB_TEXT),
        },
    )
    assert structure.get_structure(make_record(), "pdb")["source"] == "alphafold"


def test_no_structure_returns_none_and_never_invents_one(monkeypatch):
    router(monkeypatch, {structure.ALPHAFOLD_API: response(status=404)})
    assert structure.get_structure(make_record(best_pdb=None)) is None


def test_network_failure_returns_none(monkeypatch):
    router(monkeypatch, {structure.ALPHAFOLD_API: requests.ConnectionError("down")})
    assert structure.get_structure(make_record(best_pdb=None)) is None


def test_non_pdb_body_is_rejected(monkeypatch):
    router(
        monkeypatch,
        {
            structure.ALPHAFOLD_API: response(json_data=PREDICTION),
            AF_URL: response(text="<html>error page</html>"),
        },
    )
    assert structure.get_structure(make_record(best_pdb=None)) is None
