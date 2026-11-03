"""Strict schema definition for Appendix A — Permitted Intake Field Schedule.

Governed by: HAYAT_Guardrail_Document_v1.docx — Version 1.0 (Appendix A, HB-2, DP-1).
This is an exhaustive field allowlist.
Any field outside this schedule is strictly prohibited from structured intake.
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


# The 20 exhaustive permitted field names
PERMITTED_FIELD_NAMES: tuple[str, ...] = (
    "service_procedure_category",
    "trip_type",
    "preferred_destination",
    "travel_dates_flexibility",
    "total_budget_range",
    "travellers_count_relationship",
    "visa_requirement_needs",
    "concierge_requirements",
    "flight_ticket_requirements",
    "hotel_accommodation_requirements",
    "transfer_requirements",
    "translation_service_needs",
    "guide_requirements",
    "car_rental_requirements",
    "air_ambulance_requirement",
    "urgency_waiting_time_context",
    "insurance_coverage_status",
    "value_priority",
    "preferred_language",
    "contact_channel_preference",
)

# Explicitly prohibited clinical categories under HB-2 and DP-5
PROHIBITED_CLINICAL_CATEGORIES: tuple[str, ...] = (
    "symptom_description",
    "diagnosis_or_suspected_diagnosis",
    "test_lab_imaging_results",
    "medication_names_or_dosages",
    "past_treatment_history",
    "clinical_notes",
    "vitals_or_body_measurements",
    "genetic_or_family_medical_history",
    "mental_health_details",
)


class AppendixAIntakePayload(BaseModel):
    """Exhaustive, strictly validated Appendix A structured intake data."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # 1. Administrative: Service/procedure category (name only, e.g. 'IVF', 'knee replacement')
    service_procedure_category: str | None = Field(
        default=None,
        description="Name of service or procedure category only — a routing label, never a clinical description.",
    )

    # 2. Administrative: Trip type
    trip_type: Literal[
        "medical", "wellness", "business", "family", "sports", "other"
    ] | None = Field(
        default=None,
        description="Trip category: medical, wellness, business, family, sports, or other.",
    )

    # 3. Logistics: Preferred destination
    preferred_destination: str | None = Field(
        default=None,
        description="Preferred country or city destination.",
    )

    # 4. Logistics: Travel dates / flexibility
    travel_dates_flexibility: str | None = Field(
        default=None,
        description="Earliest/latest acceptable window or timing flexibility.",
    )

    # 5. Administrative: Total budget range
    total_budget_range: str | None = Field(
        default=None,
        description="Total budget band or range (not exact financial figures).",
    )

    # 6. Logistics: Number of travellers and relationship
    travellers_count_relationship: str | None = Field(
        default=None,
        description="e.g. 'patient + 1 companion' or traveller count and relationship.",
    )

    # 7. Logistics: Visa requirement needs
    visa_requirement_needs: str | None = Field(
        default=None,
        description="Whether visa coordination support is needed (never document numbers).",
    )

    # 8. Logistics: Concierge requirements
    concierge_requirements: str | None = Field(
        default=None,
        description="General concierge preference (VIP, fast-track, basic).",
    )

    # 9. Logistics: Flight/ticket requirements
    flight_ticket_requirements: str | None = Field(
        default=None,
        description="Cabin class, routing preference (no payment or booking detail).",
    )

    # 10. Logistics: Hotel/accommodation requirements
    hotel_accommodation_requirements: str | None = Field(
        default=None,
        description="Accommodation category, location preference.",
    )

    # 11. Logistics: Transfer requirements
    transfer_requirements: str | None = Field(
        default=None,
        description="Airport/hotel/clinic ground transport needs.",
    )

    # 12. Logistics: Translation service needs
    translation_service_needs: str | None = Field(
        default=None,
        description="Required language pair for interpretation.",
    )

    # 13. Logistics: Guide requirements
    guide_requirements: str | None = Field(
        default=None,
        description="Guide requirement and context (wellness/business/cultural).",
    )

    # 14. Logistics: Car rental requirements
    car_rental_requirements: str | None = Field(
        default=None,
        description="Vehicle rental requirement and vehicle type.",
    )

    # 15. Logistics: Air ambulance requirement (flag only)
    air_ambulance_requirement: bool | None = Field(
        default=None,
        description="Logistics flag only; any clinical reasons are strictly redacted per DP-5.",
    )

    # 16. Administrative: Urgency / waiting-time context
    urgency_waiting_time_context: str | None = Field(
        default=None,
        description="Administrative urgency fact (e.g. 'currently on public waiting list'), not a clinical justification.",
    )

    # 17. Administrative: Insurance coverage status
    insurance_coverage_status: Literal["covered", "not_covered"] | None = Field(
        default=None,
        description="Binary insurance coverage status only; no policy, card, or claim numbers.",
    )

    # 18. Preference: Value priority
    value_priority: Literal[
        "cost-effectiveness", "comfort", "best-available service", "speed"
    ] | None = Field(
        default=None,
        description="Traveller value priority: cost-effectiveness, comfort, best-available service, or speed.",
    )

    # 19. Preference: Preferred language
    preferred_language: str | None = Field(
        default=None,
        description="Preferred language for conversation and ongoing coordination.",
    )

    # 20. Preference: Contact channel preference
    contact_channel_preference: Literal[
        "email", "phone", "whatsapp", "in-app"
    ] | None = Field(
        default=None,
        description="Preferred channel for follow-up by human coordinator.",
    )


def validate_permitted_field_name(name: str) -> bool:
    """Validate whether a field name belongs to the Appendix A exhaustive allowlist."""
    return name in PERMITTED_FIELD_NAMES


def is_prohibited_clinical_field(name: str) -> bool:
    """Check if a field name matches any prohibited clinical PHI category."""
    lower = name.lower().strip()
    # Check exact match or normalized match
    normalized = lower.replace(" ", "_")
    if normalized in PROHIBITED_CLINICAL_CATEGORIES:
        return True
    prohibited_clinical_keywords = (
        "symptom", "diagnosis", "prescription", "dosage", "medication",
        "vital", "vitals", "blood_pressure", "blood_sugar", "lab_result", "imaging_result",
        "past_treatment", "clinical_note", "family_medical_history", "mental_health"
    )
    return any(kw in lower for kw in prohibited_clinical_keywords)
