"""Curated disease-to-protein database, used when the AI is unavailable."""

import copy
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DATABASE_PATH = Path(__file__).resolve().parent.parent / "disease_proteins.json"


def load_database(path=DATABASE_PATH):
    try:
        with open(path, encoding="utf-8") as handle:
            database = json.load(handle)
    except (OSError, ValueError) as error:
        logger.error("Could not load curated database %s: %s", path, error)
        return {}
    logger.info("Loaded curated database with %d diseases", len(database))
    return database


DATABASE = load_database()


def lookup(text, limit=5, database=None):
    """Return curated proteins for every disease named in the text.

    Keys match at the start of a word, so "alzheimer's" and "cancers" match,
    but "pain" does not match "Spain".
    """
    database = DATABASE if database is None else database
    lowered = text.lower()
    proteins = []
    seen = set()
    for disease, entries in database.items():
        if not re.search(rf"\b{re.escape(disease)}", lowered):
            continue
        for entry in entries:
            if entry["uniprot_id"] not in seen:
                seen.add(entry["uniprot_id"])
                proteins.append(copy.deepcopy(entry))
    return proteins[:limit]
