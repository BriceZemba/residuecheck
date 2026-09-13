"""Rules engine v0: decides the verdict for one crop lot from facts, never from a language model.

Inputs are already-resolved facts (spray applications with substances, origin-label pre-harvest
interval, crop, harvest date) plus the frozen EU snapshot. Output is a verdict with findings, each
finding carrying its evidence and source links, so the explanation layer can only restate them.

Verdict order: RED > CANNOT_VERIFY > AMBER > GREEN. A definite breach is more actionable than a gap,
and a gap blocks a green light.

What this does not do: predict residue levels. A RED for a limit set at the limit of quantification
means "any detectable residue breaches the EU limit", not "this lot will fail a lab test".
"""
import datetime
import enum
from dataclasses import dataclass, field

from residuecheck.eu_data import Snapshot, base_name, parse_date

TRANSIT_DAYS_DEFAULT = 10     # harvest -> placed on the EU market; stated as an assumption on every result
RECENT_CHANGE_DAYS = 365      # an MRL lowered within this window before arrival is flagged
UPCOMING_CHANGE_DAYS = 180    # an MRL lowering within this window after arrival is flagged
SNAPSHOT_STALE_DAYS = 30


class Level(enum.IntEnum):
    INFO = 0
    GREEN = 1
    AMBER = 2
    CANNOT_VERIFY = 3
    RED = 4


@dataclass
class Application:
    product: str
    applied_on: datetime.date
    substances: list[str] = field(default_factory=list)  # empty when the product could not be resolved
    registered_for_crop: bool | None = None  # origin register: True, False, or None when unknown
    dar_days: int | None = None  # pre-harvest interval on the origin label for this crop
    source: str | None = None  # where substances / DAR come from (e.g. ONSSA index URL)

    def __post_init__(self):
        self.applied_on = _as_date(self.applied_on)


@dataclass
class Lot:
    crop_code: str
    harvest_on: datetime.date
    applications: list[Application]
    arrival_on: datetime.date | None = None
    rasff_hits: dict[str, int] = field(default_factory=dict)  # substance -> recent notifications for this crop

    def __post_init__(self):
        self.harvest_on = _as_date(self.harvest_on)
        self.arrival_on = _as_date(self.arrival_on) if self.arrival_on else self.harvest_on + datetime.timedelta(TRANSIT_DAYS_DEFAULT)


@dataclass
class Finding:
    code: str
    level: Level
    message: str
    product: str | None = None
    substance: str | None = None
    sources: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass
class Result:
    verdict: Level
    findings: list[Finding]
    earliest_safe_harvest: datetime.date | None
    assumptions: list[str]

    def codes(self):
        return sorted({f.code for f in self.findings})


def _as_date(value):
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return parse_date(value)


def evaluate(lot: Lot, eu: Snapshot) -> Result:
    findings: list[Finding] = []
    crop = eu.crops.get(lot.crop_code)
    assumptions = [
        f"Destination: EU. Limits from EU Pesticides Database snapshot of {eu.date.isoformat()}.",
        f"Limits checked on arrival date {lot.arrival_on.isoformat()}"
        + (" (harvest + {} days transit, assumed)".format(TRANSIT_DAYS_DEFAULT)
           if lot.arrival_on == lot.harvest_on + datetime.timedelta(TRANSIT_DAYS_DEFAULT) else "") + ".",
        "Rules check legal limits and label intervals; they do not predict measured residue levels.",
    ]
    if crop is None:
        findings.append(Finding("CROP_NOT_SUPPORTED", Level.CANNOT_VERIFY, f"Crop code {lot.crop_code} is not in the snapshot."))
        return Result(Level.CANNOT_VERIFY, findings, None, assumptions)
    if (lot.arrival_on - eu.date).days > SNAPSHOT_STALE_DAYS:
        findings.append(Finding("SNAPSHOT_OLDER_THAN_ARRIVAL", Level.INFO,
                                f"The EU snapshot ({eu.date}) is more than {SNAPSHOT_STALE_DAYS} days before arrival; "
                                "changes published since then are not covered by these rules."))

    earliest_safe = None
    for app in lot.applications:
        if not app.substances:
            # Unknown product: one finding. Label checks would only restate that nothing is known.
            findings.append(Finding("PRODUCT_UNRESOLVED", Level.CANNOT_VERIFY,
                                    f"Active substances of '{app.product}' could not be confirmed from an official source.",
                                    product=app.product))
            continue
        label = _label_findings(app, lot)
        findings += label
        for f in label:
            if f.code == "PHI_NOT_MET":
                safe = f.data["earliest_safe_harvest"]
                earliest_safe = safe if earliest_safe is None else max(earliest_safe, safe)
        for name in app.substances:
            findings += _substance_findings(name, app, lot, crop, eu)

    blocking = [f.level for f in findings if f.level > Level.INFO]
    verdict = max(blocking) if blocking else Level.GREEN
    return Result(verdict, findings, earliest_safe, assumptions)


def _label_findings(app: Application, lot: Lot):
    out = []
    if app.applied_on > lot.harvest_on:
        return [Finding("APPLICATION_AFTER_HARVEST", Level.CANNOT_VERIFY,
                        f"'{app.product}' is dated {app.applied_on}, after the harvest date {lot.harvest_on}. Check the log.",
                        product=app.product)]
    if app.registered_for_crop is False:
        out.append(Finding("NOT_REGISTERED_FOR_CROP", Level.RED,
                           f"'{app.product}' is not registered for this crop in the origin country.",
                           product=app.product, sources=[app.source] if app.source else []))
        return out
    if app.registered_for_crop is None:
        out.append(Finding("REGISTRATION_UNKNOWN", Level.CANNOT_VERIFY,
                           f"Origin registration of '{app.product}' for this crop is not confirmed.", product=app.product))
        return out
    if app.dar_days is None:
        out.append(Finding("PHI_UNKNOWN", Level.CANNOT_VERIFY,
                           f"No pre-harvest interval found for '{app.product}' on this crop.",
                           product=app.product, sources=[app.source] if app.source else []))
        return out
    waited = (lot.harvest_on - app.applied_on).days
    if waited < app.dar_days:
        safe = app.applied_on + datetime.timedelta(app.dar_days)
        out.append(Finding("PHI_NOT_MET", Level.RED,
                           f"'{app.product}' needs {app.dar_days} days before harvest; the plan leaves {waited}. "
                           f"Earliest harvest: {safe.isoformat()}.",
                           product=app.product, sources=[app.source] if app.source else [],
                           data={"waited_days": waited, "dar_days": app.dar_days, "earliest_safe_harvest": safe}))
    return out


def _substance_findings(name, app: Application, lot: Lot, crop_name, eu: Snapshot):
    sub = eu.substance(name)
    if sub is None:
        return [Finding("SUBSTANCE_UNRESOLVED", Level.CANNOT_VERIFY,
                        f"'{name}' (in '{app.product}') does not match an EU active substance name.",
                        product=app.product, substance=name)]
    label = sub["substance_name"]
    residue_ids = eu.residue_ids(sub)
    out = []
    mrls = [m for m in (eu.mrl_on(rid, lot.crop_code, lot.arrival_on) for rid in residue_ids) if m]
    if not mrls:
        return [Finding("NO_MRL_FOR_CROP", Level.CANNOT_VERIFY,
                        f"No EU limit for {label} on {crop_name} in the snapshot.", product=app.product, substance=label,
                        sources=[sub.get("pest_res_mrl_webpage")] if sub.get("pest_res_mrl_webpage") else [])]
    approved = sub["substance_status"] == "Approved"

    for mrl in mrls:
        before = len(out)
        src = [u for u in (mrl.regulation_url, sub.get("pest_res_mrl_webpage")) if u]
        facts = {"mrl": mrl.describe(), "applies_from": mrl.applies_from, "regulation": mrl.regulation,
                 "eu_status": sub["substance_status"], "residue": mrl.residue_name}
        if mrl.no_mrl_required:
            out.append(Finding("NO_MRL_REQUIRED", Level.INFO, f"No EU residue limit is required for {label}.",
                               app.product, label, src, facts))
            continue
        if mrl.at_loq:
            status = "not approved in the EU" if not approved else "approved in the EU but has no limit above quantification for this crop"
            out.append(Finding("MRL_AT_LOQ", Level.RED,
                               f"EU limit for {label} on {crop_name} is {mrl.describe()} since {mrl.applies_from} "
                               f"({mrl.regulation}); {label} is {status}. Any detectable residue breaches it.",
                               app.product, label, src, facts))
        elif not approved:
            out.append(Finding("NOT_APPROVED_IMPORT_TOLERANCE", Level.AMBER,
                               f"{label} is not approved in the EU, but imports may carry up to {mrl.describe()} on {crop_name} "
                               f"({mrl.regulation}). Buyers may apply stricter rules.",
                               app.product, label, src, facts))

        prev = eu.previous(mrl)
        if prev and (lot.arrival_on - mrl.applies_from).days <= RECENT_CHANGE_DAYS and \
                (prev.no_mrl_required or (prev.value is not None and mrl.value < prev.value)):
            out.append(Finding("MRL_RECENTLY_LOWERED", Level.AMBER,
                               f"EU limit for {label} on {crop_name} dropped from {prev.describe()} to {mrl.describe()} "
                               f"on {mrl.applies_from} ({mrl.regulation}). Older advice may be out of date.",
                               app.product, label, src, {**facts, "previous": prev.describe()}))

        for nxt in eu.scheduled_after(mrl.residue_id, lot.crop_code, lot.arrival_on):
            if (nxt.applies_from - lot.arrival_on).days <= UPCOMING_CHANGE_DAYS and nxt.value is not None \
                    and (nxt.value < mrl.value or nxt.at_loq):
                out.append(Finding("MRL_LOWERING_SOON", Level.AMBER,
                                   f"EU limit for {label} on {crop_name} drops to {nxt.describe()} on {nxt.applies_from} "
                                   f"({nxt.regulation}), {(nxt.applies_from - lot.arrival_on).days} days after arrival.",
                                   app.product, label, [nxt.regulation_url] if nxt.regulation_url else src,
                                   {**facts, "next": nxt.describe(), "next_from": nxt.applies_from}))
        for draft in eu.planned(mrl.residue_id, lot.crop_code):
            if draft.value is not None and draft.value < mrl.value:
                out.append(Finding("MRL_CHANGE_PROPOSED", Level.INFO,
                                   f"A draft EU measure ({draft.regulation}) proposes {draft.describe()} for {label} on {crop_name}; "
                                   "no date fixed yet.", app.product, label, [], {**facts, "proposed": draft.describe()}))
        if not any(f.level > Level.INFO for f in out[before:]):
            # Nothing flagged: still record the limit that was checked, so a green result cites its source.
            out.append(Finding("EU_LIMIT_CHECKED", Level.INFO,
                               f"EU limit for {label} on {crop_name}: {mrl.describe()} ({mrl.regulation}, since {mrl.applies_from}).",
                               app.product, label, src, facts))

    if sub.get("candidate_for_substitution") == "Yes":
        out.append(Finding("CANDIDATE_FOR_SUBSTITUTION", Level.INFO,
                           f"{label} is an EU candidate for substitution.", app.product, label))
    hits = lot.rasff_hits.get(base_name(label), 0) or lot.rasff_hits.get(base_name(name), 0)
    if hits:
        out.append(Finding("RECENT_RASFF_NOTIFICATIONS", Level.AMBER,
                           f"{hits} recent RASFF notification(s) for {label} on this crop.", app.product, label,
                           data={"count": hits}))
    return out
