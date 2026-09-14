"""Does an ONSSA registration cover an EU crop code, and with which pre-harvest interval?

ONSSA usages name crops in French ("Agrumes", "Tomate (sous serre)", "Pommes"); EU limits use Annex I
product codes. data/crop_map_onssa.json maps each ONSSA name to EU codes with a kind that says how
much the match can be trusted. This module applies that map to one ONSSA product record.
"""
import json
import pathlib
from dataclasses import dataclass, field

MAP_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "crop_map_onssa.json"
FIELD_KINDS = {"exact", "group", "narrower"}


def load_map(path=MAP_PATH):
    return json.loads(path.read_text(encoding="utf-8"))["map"]


@dataclass
class Registration:
    status: str  # registered | registered_narrower | ambiguous | not_registered | unknown
    registered_for_crop: bool | None  # the value the rules engine takes
    dar_days: int | None
    matched_usages: list[dict] = field(default_factory=list)
    note: str | None = None


def covers(entry, crop_code, eu):
    lineage = eu.lineage(crop_code)
    if any(code in lineage for code in entry.get("except_codes", [])):
        return False
    return any(code in lineage for code in entry["codes"])


def registration(record, crop_code, eu, crop_map=None):
    """Classify an ONSSA product record (from spikes/s3_onssa.py) against one EU crop code.

    registered           an exact or group usage covers the crop
    registered_narrower  only a narrower usage covers it (e.g. 'Agrumes: Navel' for Oranges); counts, with a note
    ambiguous            only ambiguous usage names could cover it; not confirmed
    not_registered       every usage crop name is mapped and none covers field use on this crop
    unknown              no usages, or some usage names are not in the map
    """
    crop_map = crop_map if crop_map is not None else load_map()
    usages = record.get("usages") or []
    if not usages:
        return Registration("unknown", None, None, note="No usages in the record.")

    field_hits, narrower_hits, ambiguous_hits, unmapped = [], [], [], []
    for use in usages:
        entry = crop_map.get(use.get("crop_fr"))
        if entry is None:
            unmapped.append(use.get("crop_fr"))
            continue
        if not covers(entry, crop_code, eu):
            continue
        if entry["kind"] in ("exact", "group"):
            field_hits.append(use)
        elif entry["kind"] == "narrower":
            narrower_hits.append((use, entry))
        elif entry["kind"] == "ambiguous":
            ambiguous_hits.append(use)
        # nursery and post_harvest usages cover the commodity but not field spraying: ignored here

    def strictest_dar(uses):
        # Several usages on one crop (different pests) can carry different intervals; the longest one is safe for all.
        days = [u["dar_days"] for u in uses if isinstance(u.get("dar_days"), int)]
        return max(days) if days else None

    if field_hits:
        return Registration("registered", True, strictest_dar(field_hits + [u for u, _ in narrower_hits]),
                            field_hits + [u for u, _ in narrower_hits])
    if narrower_hits:
        uses = [u for u, _ in narrower_hits]
        names = sorted({u["crop_fr"] for u in uses})
        return Registration("registered_narrower", True, strictest_dar(uses), uses,
                            note=f"Registered for {', '.join(names)} only: {narrower_hits[0][1].get('note', '')}".strip(": "))
    if ambiguous_hits:
        names = sorted({u["crop_fr"] for u in ambiguous_hits})
        return Registration("ambiguous", None, None, ambiguous_hits,
                            note=f"Usage name(s) {', '.join(names)} may or may not mean this crop.")
    if unmapped:
        return Registration("unknown", None, None, note=f"Unmapped usage crop names: {', '.join(sorted(set(unmapped)))}.")
    return Registration("not_registered", False, None)
