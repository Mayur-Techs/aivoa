import re
from datetime import date

from ..schemas import ComplaintForm, RiskAssessment


DATE_PATTERN = r"(20\d{2}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]20\d{2})"


def _first(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip(" .,:;") if match else None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for candidate in (value.replace("/", "-"),):
        try:
            parts = candidate.split("-")
            if len(parts[0]) == 4:
                return date.fromisoformat(candidate)
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
        except ValueError:
            continue
    return None


def rule_extract(text: str) -> ComplaintForm:
    """Conservative fallback: it only fills values explicitly present in text."""
    batch = _first(r"(?:batch|lot)(?:\s*/\s*(?:lot|batch))?(?:\s*(?:number|no\.?|#))?\s*(?:is|:|=)?\s*([A-Z0-9-]{4,})", text)
    quantity = _first(r"(?:affected\s*quantity|quantity)\s*(?:is|:|=)?\s*([\d,.]+\s*(?:capsules?|tablets?|kg|g|mg|ml|l)(?:\s*(?:\([^)]*\)|\d+\s*hdpe\s*drums?))?)", text)
    strength = _first(r"\b(\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|%|iu)|(?:ip|bp|usp)(?:\s*/\s*(?:ip|bp|usp))?)\b", text)
    mfg = _first(r"(?:manufacturing|manufacture|mfg)\s*date\s*(?:is|:|=)?\s*" + DATE_PATTERN, text)
    expiry = _first(r"(?:expiry|expiration|exp)\s*date\s*(?:is|:|=)?\s*" + DATE_PATTERN, text)
    complaint_date = _first(r"(?:complaint|reported)\s*date\s*(?:is|:|=)?\s*" + DATE_PATTERN, text)
    customer = _first(r"(?:customer|reported by|from)\s*(?:is|:|=)?\s*([A-Za-z][A-Za-z .&'-]{2,60})", text)
    if not customer:
        customer = _first(r"^([A-Z][A-Za-z .&'-]{2,60}?)\s+(?:reported|complained|notified)", text)
    # Prefer "complaint for Product" before the more permissive "in Product" pattern.
    # This avoids treating the "in" at the end of a name such as Metformin as a preposition.
    product = _first(r"\b(?:complaint\s+for|for)\s+([A-Z][A-Za-z0-9 ()/-]{2,80}?)(?=\s+(?:\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|%)|grade\b|batch\b|lot\b)|[.,;]|$)", text)
    product = product or _first(r"(?:product(?:\s*name)?\s*(?:is|:|=)?|\bin\s+)([A-Z][A-Za-z0-9 ()/-]{2,80}?)(?=\s+(?:\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|%)|grade\b|batch\b|lot\b)|[.,;]|$)", text)
    lowered = text.lower()
    complaint_type = next((label for term, label in [
        ("discolor", "Product appearance"), ("leak", "Packaging defect"), ("broken", "Packaging defect"),
        ("contamin", "Potential contamination"), ("foreign", "Foreign matter"), ("label", "Labelling issue"),
        ("adverse", "Potential patient safety"), ("dissolv", "Performance issue"),
    ] if term in lowered), None)
    return ComplaintForm(
        customer_source="Document upload" if "subject:" in lowered else None,
        customer_name=customer,
        product_name=product,
        product_strength_grade=strength,
        batch_lot_number=batch,
        manufacturing_date=parse_date(mfg),
        expiry_date=parse_date(expiry),
        affected_quantity=quantity,
        complaint_type=complaint_type,
        complaint_date=parse_date(complaint_date),
        detailed_complaint_description=text.strip() if len(text.strip()) <= 1500 else text.strip()[:1497] + "...",
    )


def merge_complaint(current: ComplaintForm, update: ComplaintForm) -> tuple[ComplaintForm, list[str]]:
    current_data = current.model_dump()
    update_data = update.model_dump(exclude_none=True)
    # Description is intentionally updated only for a new intake/document, not a terse correction.
    if current.detailed_complaint_description and update.detailed_complaint_description and len(update.detailed_complaint_description) < 220:
        update_data.pop("detailed_complaint_description", None)
    current_data.update(update_data)
    merged = ComplaintForm.model_validate(current_data)
    if not merged.customer_source:
        merged.customer_source = "AI chat"
    return merged, sorted(update_data.keys())


def assess(complaint: ComplaintForm) -> RiskAssessment:
    narrative = " ".join(filter(None, [complaint.complaint_type, complaint.detailed_complaint_description])).lower()
    if any(term in narrative for term in ("contamin", "sterile", "microbial", "adverse", "patient safety", "wrong product", "foreign matter")):
        severity, priority = "Critical", "Urgent"
        action = "Quarantine potentially affected stock, notify QA immediately, and open a deviation investigation."
        rationale = "The report may indicate a patient-safety or contamination risk and requires immediate containment."
    elif any(term in narrative for term in ("discolor", "leak", "broken", "defect", "dissolv", "label")):
        severity, priority = "Major", "High"
        action = "Route to QA investigation, retain complaint evidence, and assess replacement or market action."
        rationale = "The report indicates a quality defect that could affect product acceptability or compliance."
    elif narrative.strip():
        severity, priority = "Minor", "Normal"
        action = "Log the complaint, request any missing traceability details, and route for QA triage."
        rationale = "No direct safety signal was identified from the current information."
    else:
        severity, priority = "Pending assessment", "Pending triage"
        action = "Collect complaint details before conducting QA triage."
        rationale = "There is not enough information to classify the complaint."

    required = {
        "Customer": complaint.customer_name,
        "Product": complaint.product_name,
        "Batch / lot": complaint.batch_lot_number,
        "Affected quantity": complaint.affected_quantity,
        "Complaint description": complaint.detailed_complaint_description,
    }
    missing = [name for name, value in required.items() if not value]
    score = round((len(required) - len(missing)) / len(required) * 100)
    root_causes = [
        "Review batch manufacturing and packaging records for the reported lot.",
        "Check retained samples and distribution conditions against the complaint evidence.",
    ]
    capa = "Document the investigation outcome; if confirmed, implement corrective action and trend similar complaints."
    return RiskAssessment(
        severity=severity,
        priority=priority,
        suggested_next_action=action,
        rationale=rationale,
        completeness_score=score,
        missing_fields=missing,
        root_cause_hypotheses=root_causes,
        capa_recommendation=capa,
    )
