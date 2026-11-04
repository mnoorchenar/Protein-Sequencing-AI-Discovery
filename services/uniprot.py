"""UniProt REST API client: entry lookup, verification and keyword search."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://rest.uniprot.org/uniprotkb"
HUMAN_TAXON_ID = 9606
ENTRY_FIELDS = (
    "accession,id,protein_name,gene_names,organism_name,length,"
    "cc_function,cc_disease,xref_pdb"
)
REQUEST_TIMEOUT = 15
FUNCTION_CHARS = 600

# Official accession format: https://www.uniprot.org/help/accession_numbers
ACCESSION_RE = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})$"
)

STOP_WORDS = {
    "about", "and", "associated", "drug", "drugs", "find", "for", "give", "human",
    "involved", "me", "of", "or", "please", "protein", "proteins", "related",
    "sequence", "show", "target", "targets", "the", "with",
}
QUERY_OPERATORS = {"AND", "OR", "NOT"}

MATCH_NONE, MATCH_PARTIAL, MATCH_EXACT = 0, 1, 2

# Ignored when comparing protein names, because they say nothing about identity.
FILLER_NAME_WORDS = {"human", "of", "protein", "the"}
# Too generic to identify a protein when they're the only word that matches.
GENERIC_NAME_WORDS = FILLER_NAME_WORDS | {
    "alpha", "beta", "factor", "gamma", "kinase", "ligand", "receptor",
}


def build_session():
    retry = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


session = build_session()


class UpstreamError(Exception):
    """An external database could not be reached. Never cached."""


def is_valid_accession(value):
    return isinstance(value, str) and bool(ACCESSION_RE.match(value))


def _protein_name(description, fallback):
    recommended = description.get("recommendedName")
    if recommended:
        return recommended.get("fullName", {}).get("value", fallback)
    submitted = description.get("submissionNames") or [{}]
    return submitted[0].get("fullName", {}).get("value", fallback)


def _name_values(name_block):
    """Collect the full and short names from one UniProt name block."""
    values = [name_block.get("fullName", {}).get("value")]
    values += [short.get("value") for short in name_block.get("shortNames", [])]
    return [value for value in values if value]


def _aliases(entry):
    """Every name UniProt knows this protein by, including gene synonyms."""
    description = entry.get("proteinDescription", {})
    aliases = []
    if description.get("recommendedName"):
        aliases += _name_values(description["recommendedName"])
    for block in description.get("alternativeNames", []) + description.get("submissionNames", []):
        aliases += _name_values(block)
    for gene in entry.get("genes", []):
        names = [gene.get("geneName", {})] + gene.get("synonyms", [])
        aliases += [name["value"] for name in names if name.get("value")]
    return aliases


def _normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def match_strength(name, record):
    """Rate how well a protein name identifies this record.

    A real human accession isn't enough: LLMs often pair a correct explanation
    with the accession of an unrelated protein.

    MATCH_EXACT means the name or a word in it is one of the protein's known names.
    MATCH_PARTIAL means every word appears in one of its names, so "Tau protein"
    matches "Microtubule-associated protein tau". That's weaker, because "Glucokinase"
    also matches "Glucokinase regulatory protein", which is a different protein.
    """
    aliases = record.get("aliases") or []
    if not name or not aliases:
        return MATCH_NONE

    known = {_normalize(alias) for alias in aliases}
    segments = re.split(r"[(),/;]", name)
    if any(_normalize(segment) in known for segment in segments if _normalize(segment)):
        return MATCH_EXACT

    for word in name.split() + list(_tokens(name)):
        normalized = _normalize(word)
        if len(normalized) >= 3 and normalized not in GENERIC_NAME_WORDS and normalized in known:
            return MATCH_EXACT

    # A pseudogene shares its parent's name, but it's rarely the protein that was meant.
    if any("pseudogene" in alias.lower() for alias in aliases):
        return MATCH_NONE

    for segment in segments:
        wanted = _tokens(segment) - FILLER_NAME_WORDS
        if wanted and any(wanted <= _tokens(alias) for alias in aliases):
            return MATCH_PARTIAL
    return MATCH_NONE


def names_match(name, record):
    return match_strength(name, record) != MATCH_NONE


def _summarize_function(text):
    """Remove citations and shorten at a sentence boundary, never mid-word."""
    text = re.sub(r"\s*\((?:PubMed|By similarity)[^)]*\)", "", text).strip()
    if len(text) <= FUNCTION_CHARS:
        return text
    shortened = text[:FUNCTION_CHARS]
    sentence_end = shortened.rfind(". ")
    if sentence_end > FUNCTION_CHARS // 3:
        return shortened[: sentence_end + 1]
    return shortened.rsplit(" ", 1)[0] + "…"


def _best_pdb_entry(cross_references):
    """Pick the highest-resolution experimental structure, if there is one."""
    best = None
    best_resolution = float("inf")
    for reference in cross_references:
        if reference.get("database") != "PDB":
            continue
        properties = {p.get("key"): p.get("value") for p in reference.get("properties", [])}
        match = re.match(r"([\d.]+)", properties.get("Resolution") or "")
        resolution = float(match.group(1)) if match else float("inf")
        if best is None or resolution < best_resolution:
            best = {
                "id": reference.get("id"),
                "method": properties.get("Method"),
                "resolution": properties.get("Resolution")
                if match
                else None,
            }
            best_resolution = resolution
    return best


def parse_entry(entry):
    """Convert a UniProt JSON entry to the flat record used across the app."""
    accession = entry.get("primaryAccession", "")
    comments = entry.get("comments", [])

    function = ""
    for comment in comments:
        if comment.get("commentType") == "FUNCTION" and comment.get("texts"):
            function = _summarize_function(comment["texts"][0].get("value", ""))
            break

    diseases = []
    for comment in comments:
        if comment.get("commentType") == "DISEASE":
            disease_id = comment.get("disease", {}).get("diseaseId")
            if disease_id:
                diseases.append(disease_id)

    genes = entry.get("genes") or [{}]
    return {
        "uniprot_id": accession,
        "name": _protein_name(
            entry.get("proteinDescription", {}),
            entry.get("uniProtkbId", accession),
        ),
        "gene": genes[0].get("geneName", {}).get("value", ""),
        "aliases": _aliases(entry),
        "organism": entry.get("organism", {}).get("scientificName", "Unknown"),
        "taxon_id": entry.get("organism", {}).get("taxonId"),
        "length": entry.get("sequence", {}).get("length", 0),
        "function": function,
        "diseases": diseases,
        "best_pdb": _best_pdb_entry(entry.get("uniProtKBCrossReferences", [])),
    }


@lru_cache(maxsize=512)
def _fetch_entry(accession):
    """Return a record, or None if the accession doesn't exist. Failures raise, so they aren't cached."""
    try:
        response = session.get(
            f"{BASE_URL}/{accession}",
            params={"format": "json", "fields": ENTRY_FIELDS},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        raise UpstreamError(str(error)) from error

    if response.status_code in (400, 404):
        return None
    if response.status_code != 200:
        raise UpstreamError(f"UniProt returned {response.status_code}")

    data = response.json()
    # Obsolete or merged entries have no organism or sequence.
    if data.get("entryType", "").startswith("Inactive"):
        return None
    return parse_entry(data)


def get_protein(accession):
    """Return a UniProt record, or None if it's unknown or UniProt is unreachable."""
    if not is_valid_accession(accession):
        return None
    try:
        return _fetch_entry(accession)
    except UpstreamError as error:
        logger.warning("UniProt lookup failed for %s: %s", accession, error)
        return None


def get_proteins(accessions):
    """Fetch several records in parallel, keeping the input order."""
    if not accessions:
        return []
    with ThreadPoolExecutor(max_workers=min(5, len(accessions))) as pool:
        return list(pool.map(get_protein, accessions))


def is_human(record):
    return bool(record) and record.get("taxon_id") == HUMAN_TAXON_ID


def extract_keywords(query):
    """Reduce free text to search terms, removing anything with query-syntax meaning."""
    text = re.sub(r"['’]s\b", "", query)
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", text)
    words = [w for w in words if w not in QUERY_OPERATORS]
    keywords = [w for w in words if w.lower() not in STOP_WORDS and (len(w) > 2 or w.isdigit())]
    return keywords or words


def _search_once(terms, reviewed, limit):
    clauses = [f"({' '.join(terms)})", f"organism_id:{HUMAN_TAXON_ID}"]
    if reviewed:
        clauses.append("reviewed:true")
    response = session.get(
        f"{BASE_URL}/search",
        params={
            "query": " AND ".join(clauses),
            "fields": ENTRY_FIELDS,
            "format": "json",
            "size": limit,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("results", [])


def search(query, limit=5):
    """Search human proteins, relaxing the query step by step until something matches."""
    keywords = extract_keywords(query)
    if not keywords:
        return []

    # Multi-word terms are ANDed by UniProt, so long queries often match nothing.
    attempts = [(keywords, True)]
    if len(keywords) > 2:
        attempts.append((keywords[:2], True))
    if len(keywords) > 1:
        attempts.append((keywords[:1], True))
    attempts.append((keywords, False))

    for terms, reviewed in attempts:
        try:
            results = _search_once(terms, reviewed, limit)
        except (requests.RequestException, ValueError) as error:
            logger.warning("UniProt search failed: %s", error)
            raise UpstreamError("UniProt search failed") from error
        if results:
            return [parse_entry(entry) for entry in results]
    return []


def find_by_name(name):
    """Find the human protein with this name, preferring exact matches, or None."""
    try:
        results = search(name, limit=5)
    except UpstreamError:
        return None
    if not results:
        return None
    best = max(results, key=lambda record: match_strength(name, record))
    return best if match_strength(name, best) != MATCH_NONE else None


def resolve_target(target):
    """Return the record an AI suggestion really refers to, or None if it can't be confirmed."""
    name = target["name"]
    record = get_protein(target["uniprot_id"])
    strength = match_strength(name, record) if is_human(record) else MATCH_NONE
    if strength == MATCH_EXACT:
        return record

    logger.info("AI accession %s isn't an exact match for '%s'", target["uniprot_id"], name)
    found = find_by_name(name) if name else None
    if found and match_strength(name, found) == MATCH_EXACT:
        return found
    return record if strength == MATCH_PARTIAL else found


def resolve_targets(targets):
    if not targets:
        return []
    with ThreadPoolExecutor(max_workers=min(5, len(targets))) as pool:
        return list(pool.map(resolve_target, targets))


def describe_relevance(record, query):
    """Explain a search hit using facts from the record, not speculation."""
    if record.get("diseases"):
        return "Associated with: " + ", ".join(record["diseases"][:3])
    return f'UniProt match for "{query}".'
