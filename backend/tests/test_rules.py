from app.schemas import ComplaintForm
from app.services.rules import assess, merge_complaint, rule_extract


def test_extracts_basic_complaint_from_natural_language() -> None:
    result = rule_extract("Apollo Pharmacy reported discolored capsules in Amoxicillin capsules 500 mg.")
    assert result.customer_name == "Apollo Pharmacy"
    assert result.product_name == "Amoxicillin capsules"
    assert result.product_strength_grade == "500 mg"
    assert result.complaint_type == "Product appearance"


def test_correction_preserves_existing_values() -> None:
    current = ComplaintForm(product_name="Amoxicillin capsules", product_strength_grade="500 mg")
    update = rule_extract("Sorry, the batch number is BMX24602 and the affected quantity is 48 capsules.")
    merged, fields = merge_complaint(current, update)
    assert merged.product_name == "Amoxicillin capsules"
    assert merged.batch_lot_number == "BMX24602"
    assert merged.affected_quantity == "48 capsules"
    assert "batch_lot_number" in fields


def test_discoloration_is_major() -> None:
    assessment = assess(ComplaintForm(detailed_complaint_description="Customer reports discolored capsules."))
    assert assessment.severity == "Major"
    assert assessment.priority == "High"


def test_extracts_month_year_dates_without_inventing_a_day() -> None:
    result = rule_extract(
        "Apollo Pharmacy reported discolored capsules in Amoxicillin Capsules 500 mg. "
        "Batch number AMX240602. Manufacturing date March 2026. Expiry date February 2028."
    )
    assert result.product_name == "Amoxicillin Capsules"
    assert result.batch_lot_number == "AMX240602"
    assert result.manufacturing_date == "March 2026"
    assert result.expiry_date == "February 2028"
