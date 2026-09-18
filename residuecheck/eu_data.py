"""Read-only access to a frozen EU Pesticides Database snapshot (see scripts/eu_snapshot.py).

Answers two questions deterministically:
  - What is the status of active substance X in the EU?
  - Which MRL applied to residue R on crop C on date D, and what changes are scheduled after D?

MRL versions: each (residue id, product code) has one row per regulation, with an application date.
The value in force on date D is the row with the latest application date on or before D. When two
versions share an application date, the one the database flags "Applicable" wins (12 such pairs in
the 2026-09-13 snapshot).
"""
import datetime
import gzip
import json
import pathlib
import re
import unicodedata
from dataclasses import dataclass

SNAPSHOT_ROOT = pathlib.Path(__file__).resolve().parents[1] / "data" / "eu_snapshot"
_MARKERS = re.compile(r"\((?:f|r|a|\+|\+\+)\)", re.I)  # footnote markers: (F) (R) (A) (+) (++)
_PARENTHETICAL = re.compile(r"\s+\(.*$")  # needs a space before "(", so "(Z)-9-tetradecen-1-ol" keeps its name
_APPLICABILITY_RANK = {"No longer applicable": 0, "Not yet applicable": 0, "Applicable": 1}
# French pesticide names often add a final "e" to the English ISO name (accents are already stripped by norm_residue).
_FR_ENDINGS = [(r"ide$", "id"), (r"ane$", "an"), (r"ene$", "en"), (r"ine$", "in"), (r"ole$", "ol"), (r"ate$", "at")]
_ALIASES = json.loads((pathlib.Path(__file__).resolve().parents[1] / "data" / "substance_aliases.json")
                      .read_text(encoding="utf-8"))["aliases"]


DEFAULT_MRL_TEXT = "Art 18(1)(b)"
DEFAULT_MRL_VALUE = 0.01


def norm_residue(name):
    """Normalise residue/substance names: drop (F)/(R)/(A) markers, accents, case and extra spaces."""
    name = _MARKERS.sub(" ", name or "")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", name).strip().lower()


def base_name(name):
    """'abamectin (aka avermectin)' -> 'abamectin'."""
    return _PARENTHETICAL.sub("", norm_residue(name)).strip()


def parse_date(value):
    """Accepts a date, an ISO string (YYYY-MM-DD) or the EU database format (DD/MM/YYYY)."""
    if isinstance(value, datetime.date):
        return value
    if re.match(r"\d{4}-\d{2}-\d{2}$", value):
        return datetime.date.fromisoformat(value)
    return datetime.datetime.strptime(value, "%d/%m/%Y").date()


@dataclass(frozen=True)
class Mrl:
    residue_id: int
    residue_name: str
    crop_code: str
    crop_name: str
    value: float | None  # None when no MRL is required (Annex IV)
    no_mrl_required: bool
    at_loq: bool  # value marked "*": set at the limit of quantification, so any detectable residue breaches it
    applies_from: datetime.date | None  # None for draft regulations
    applicability: str  # database flag as of the snapshot date
    regulation: str
    regulation_url: str

    @classmethod
    def from_row(cls, row):
        exempt = row["mrl_value_only"] == "No MRL required"
        return cls(
            residue_id=row["pesticide_residue_id"], residue_name=row["pesticide_residue_name"].strip(),
            crop_code=row["product_code"], crop_name=row["product_name"],
            value=None if exempt else float(row["mrl_value_only"]), no_mrl_required=exempt,
            at_loq=(row.get("mrl_lod") or "").strip() == "*",
            applies_from=parse_date(row["application_date"]) if row.get("application_date") else None,
            applicability=row.get("applicability_text") or "",
            regulation=row["regulation_number"], regulation_url=row.get("regulation_url") or "",
        )

    def describe(self):
        if self.no_mrl_required:
            return "no MRL required"
        return f"{self.value:g} mg/kg" + (" (limit of quantification)" if self.at_loq else "")


class Snapshot:
    def __init__(self, date=None, root=SNAPSHOT_ROOT):
        folders = sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []
        if not folders:
            raise FileNotFoundError(f"no EU snapshot under {root}; run scripts/eu_snapshot.py")
        folder = root / date if date else folders[-1]
        self.folder = folder
        self.manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.date = datetime.date.fromisoformat(self.manifest["snapshot_date"])
        self.crops = json.loads((folder / "crops.json").read_text(encoding="utf-8"))
        with gzip.open(folder / "products.json.gz", "rt", encoding="utf-8") as f:
            self.products = json.load(f)  # code -> {parent, type, EN, FR, synonyms}
        with gzip.open(folder / "substances.json.gz", "rt", encoding="utf-8") as f:
            self.substances = json.load(f)
        with gzip.open(folder / "residue_names.json.gz", "rt", encoding="utf-8") as f:
            self.residue_names = json.load(f)

        self._versions = {}  # (residue_id, crop_code) -> [Mrl sorted by applies_from]
        self._planned = {}  # draft regulations ("PLAN/...") with no application date yet
        self.skipped_rows = 0  # rows without any value
        self._residue_ids_by_name = {}
        with gzip.open(folder / "mrls.jsonl.gz", "rt", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row.get("mrl_value_only") in (None, ""):
                    self.skipped_rows += 1
                    continue
                m = Mrl.from_row(row)
                target = self._versions if m.applies_from else self._planned
                target.setdefault((m.residue_id, m.crop_code), []).append(m)
                self._residue_ids_by_name.setdefault(norm_residue(m.residue_name), set()).add(m.residue_id)
        self._known_residue_ids = {rid for rid, _ in self._versions} | {rid for rid, _ in self._planned}
        self._successors = {}
        for rid, v in self.residue_names.items():
            if v.get("replaces"):
                self._successors.setdefault(v["replaces"], set()).add(int(rid))
        for versions in self._versions.values():
            versions.sort(key=lambda m: (m.applies_from, _APPLICABILITY_RANK.get(m.applicability, 0)))

        self._by_key = {}
        for s in self.substances:
            self._add_key(norm_residue(s["substance_name"]), s)
            for residue in s["pesticide_residues_linked"]:
                self._add_key(norm_residue(residue), s)
        # Base names (text before a parenthesis) only where unambiguous.
        base = {}
        for key, s in list(self._by_key.items()):
            if s is not None:
                base.setdefault(base_name(key), set()).add(s["substance_id"])
        by_id = {s["substance_id"]: s for s in self.substances}
        for key, ids in base.items():
            if len(ids) == 1:
                self._add_key(key, by_id[next(iter(ids))])
        self._by_cas = {s["cas_number"]: s for s in self.substances if s.get("cas_number") and s["cas_number"][0].isdigit()}
        # FR residue names, for national registers written in French (e.g. ONSSA).
        self._fr_to_en = {}
        for v in self.residue_names.values():
            if v.get("FR") and v.get("EN"):
                self._fr_to_en[norm_residue(v["FR"])] = v["EN"]
                self._fr_to_en.setdefault(base_name(v["FR"]), v["EN"])

    def _add_key(self, key, substance):
        if not key:
            return
        existing = self._by_key.get(key, substance)
        # Keep None as a marker for keys that point to different substances: those never resolve.
        self._by_key[key] = substance if existing is not None and existing["substance_id"] == substance["substance_id"] else None

    def lineage(self, code):
        """The code and all its parent group codes, e.g. Oranges -> [0110020, 0110000, 0100000]."""
        chain = []
        while code and code not in chain:
            chain.append(code)
            code = (self.products.get(code) or {}).get("parent")
        return chain

    # Substances

    def substance(self, name=None, cas=None):
        """Exact normalised match on EN name, linked residue, unambiguous base name, FR residue name, CAS,
        a sourced alias, or a French -> English ending (boscalide -> boscalid, pyridabène -> pyridaben).
        Every step is an exact match on a real EU name; no fuzzy matching. Unknown or ambiguous names return None."""
        if cas and cas in self._by_cas:
            return self._by_cas[cas]
        hit = self._exact(name)
        if hit:
            return hit
        alias = _ALIASES.get(norm_residue(name))
        if alias:
            return self._exact(alias["eu"])
        key = norm_residue(name)
        for pattern, repl in _FR_ENDINGS:
            if re.search(pattern, key):
                hit = self._exact(re.sub(pattern, repl, key))
                if hit:
                    return hit
        return None

    def _exact(self, name):
        for key in (norm_residue(name), base_name(name)):
            if self._by_key.get(key):
                return self._by_key[key]
        for key in (norm_residue(name), base_name(name)):
            en = self._fr_to_en.get(key)
            if en:
                hit = self._by_key.get(norm_residue(en)) or self._by_key.get(base_name(en))
                if hit:
                    return hit
        return None

    def residue_ids(self, substance):
        """Residue definitions whose limits apply to a substance, limited to those with rows in the snapshot.

        Three joins, combined: the residue ids the EU database links to the substance, every later version of
        those ids (the EU redefines residues, e.g. fosetyl-Al 317 -> phosphonic acid 3430), and exact name matches
        of the linked residue names and of the substance name itself, with and without its parenthetical
        ('Cadusafos (aka ebufos)' -> residue 'Cadusafos').
        """
        ids = set(substance.get("pesticide_residue_ids") or [])
        frontier = set(ids)
        while frontier:  # follow redefinitions forward
            nxt = set()
            for rid in frontier:
                nxt |= self._successors.get(rid, set())
            frontier = nxt - ids
            ids |= nxt
        for residue in list(substance["pesticide_residues_linked"]) + [substance["substance_name"]]:
            ids |= self._residue_ids_by_name.get(norm_residue(residue), set())
        ids |= self._residue_ids_by_name.get(base_name(substance["substance_name"]), set())
        return sorted(i for i in ids if i in self._known_residue_ids)

    @staticmethod
    def default_limit_only(substance):
        """True when the EU database links the substance to the default limit of Reg. 396/2005 Art. 18(1)(b)
        (0.01 mg/kg) rather than to a residue definition of its own."""
        linked = substance.get("pesticide_residues_linked") or []
        return bool(linked) and all(DEFAULT_MRL_TEXT in r for r in linked)

    # MRLs

    def mrl_versions(self, residue_id, crop_code):
        return list(self._versions.get((residue_id, crop_code), []))

    def mrl_on(self, residue_id, crop_code, on_date):
        """MRL in force on a date, or None if the snapshot has no value for this residue and crop."""
        on_date = parse_date(on_date)
        current = None
        for m in self._versions.get((residue_id, crop_code), []):
            if m.applies_from <= on_date:
                current = m
        return current

    def scheduled_after(self, residue_id, crop_code, on_date):
        on_date = parse_date(on_date)
        return [m for m in self._versions.get((residue_id, crop_code), []) if m.applies_from > on_date]

    def planned(self, residue_id, crop_code):
        """Proposed MRLs from draft regulations, date not yet fixed."""
        return list(self._planned.get((residue_id, crop_code), []))

    def previous(self, mrl):
        earlier = [m for m in self._versions.get((mrl.residue_id, mrl.crop_code), [])
                   if m.applies_from < mrl.applies_from and m.value != mrl.value]
        return earlier[-1] if earlier else None
