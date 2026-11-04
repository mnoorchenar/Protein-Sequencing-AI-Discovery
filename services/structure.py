"""Fetch 3D structures from AlphaFold DB and RCSB PDB."""

import logging
from functools import lru_cache

import requests

from .uniprot import UpstreamError, session

logger = logging.getLogger(__name__)

ALPHAFOLD_API = "https://alphafold.ebi.ac.uk/api/prediction"
RCSB_FILES = "https://files.rcsb.org/download"
REQUEST_TIMEOUT = 20


def _is_pdb_text(text):
    return "ATOM  " in text


@lru_cache(maxsize=32)
def _fetch_alphafold(accession):
    """Use the prediction API, because file URLs change with each model version."""
    try:
        response = session.get(f"{ALPHAFOLD_API}/{accession}", timeout=REQUEST_TIMEOUT)
        if response.status_code in (400, 404, 422):
            return None
        response.raise_for_status()
        predictions = response.json()
        if not predictions:
            return None

        prediction = predictions[0]
        pdb_response = session.get(prediction["pdbUrl"], timeout=REQUEST_TIMEOUT)
        pdb_response.raise_for_status()
    except (requests.RequestException, KeyError, ValueError) as error:
        raise UpstreamError(f"AlphaFold request failed: {error}") from error

    if not _is_pdb_text(pdb_response.text):
        return None
    return {
        "source": "alphafold",
        "label": f"AlphaFold prediction (v{prediction.get('latestVersion', '?')})",
        "pdb_data": pdb_response.text,
        "mean_plddt": prediction.get("globalMetricValue"),
        "pdb_id": None,
    }


@lru_cache(maxsize=32)
def _fetch_experimental(pdb_id, method, resolution):
    try:
        response = session.get(f"{RCSB_FILES}/{pdb_id}.pdb", timeout=REQUEST_TIMEOUT)
        # Very large complexes are only published as mmCIF.
        if response.status_code == 404:
            return None
        response.raise_for_status()
    except requests.RequestException as error:
        raise UpstreamError(f"RCSB request failed: {error}") from error

    if not _is_pdb_text(response.text):
        return None
    details = ", ".join(part for part in (method, resolution) if part)
    return {
        "source": "pdb",
        "label": f"Experimental PDB {pdb_id}" + (f" ({details})" if details else ""),
        "pdb_data": response.text,
        "mean_plddt": None,
        "pdb_id": pdb_id,
    }


def _try(fetch, *args):
    try:
        return fetch(*args)
    except UpstreamError as error:
        logger.warning("Structure lookup failed: %s", error)
        return None


def get_structure(record, preferred="auto"):
    """Return structure data for a UniProt record, or None if nothing is available.

    There is deliberately no synthetic fallback: a made-up model must never be
    shown as if it were this protein.
    """
    accession = record["uniprot_id"]
    best_pdb = record.get("best_pdb")

    def experimental():
        if not best_pdb:
            return None
        return _try(
            _fetch_experimental,
            best_pdb["id"],
            best_pdb.get("method"),
            best_pdb.get("resolution"),
        )

    def alphafold():
        return _try(_fetch_alphafold, accession)

    order = (experimental, alphafold) if preferred == "pdb" else (alphafold, experimental)
    for fetch in order:
        result = fetch()
        if result:
            return result
    return None
