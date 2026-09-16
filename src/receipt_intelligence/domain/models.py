"""Canonical, model-independent output models for receipt processing."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    """Shared behavior for stable API-facing domain models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldStatus(str, Enum):
    """State of a requested field after extraction."""

    EXTRACTED = "extracted"
    NOT_PRESENT = "not_present"
    UNCERTAIN = "uncertain"
    UNREADABLE = "unreadable"
    NOT_ANNOTATED = "not_annotated"


class ValidationSeverity(str, Enum):
    """Impact of a validation finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ReviewReason(str, Enum):
    """Stable reasons why a receipt requires human review."""

    MISSING_CRITICAL_FIELD = "missing_critical_field"
    VALIDATION_ERROR = "validation_error"
    LOW_CONFIDENCE = "low_confidence"
    UNREADABLE_CONTENT = "unreadable_content"


class BoundingBox(DomainModel):
    """Axis-aligned source region in image pixel coordinates."""

    left: int = Field(ge=0)
    top: int = Field(ge=0)
    right: int = Field(gt=0)
    bottom: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_geometry(self) -> BoundingBox:
        if self.right <= self.left:
            raise ValueError("right must be greater than left")
        if self.bottom <= self.top:
            raise ValueError("bottom must be greater than top")
        return self


class Evidence(DomainModel):
    """Location and text supporting an extracted value."""

    page: int = Field(default=1, ge=1)
    text: str = Field(min_length=1)
    bounding_box: BoundingBox | None = None


ValueT = TypeVar("ValueT")


class ExtractedField(DomainModel, Generic[ValueT]):
    """A value together with provenance and extraction state."""

    value: ValueT | None
    raw_text: str | None = None
    status: FieldStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_value_matches_status(self) -> ExtractedField[ValueT]:
        if self.status is FieldStatus.EXTRACTED and self.value is None:
            raise ValueError("an extracted field must contain a value")

        if self.status in {
            FieldStatus.NOT_PRESENT,
            FieldStatus.UNREADABLE,
            FieldStatus.NOT_ANNOTATED,
        }:
            if self.value is not None:
                raise ValueError(f"a {self.status.value} field cannot contain a value")

        return self


TextField = ExtractedField[str]
NumberField = ExtractedField[Decimal]
MoneyField = ExtractedField[Decimal]


class LineItem(DomainModel):
    """One normalized receipt position."""

    description: TextField
    quantity: NumberField
    unit_price: MoneyField
    line_total: MoneyField


class ReceiptExtraction(DomainModel):
    """Canonical data produced after adapting a model response."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    document_id: str = Field(min_length=1)
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: MoneyField
    tax: MoneyField
    total: MoneyField
    currency: TextField

    @model_validator(mode="after")
    def validate_currency_format(self) -> ReceiptExtraction:
        currency = self.currency
        if currency.status is FieldStatus.EXTRACTED:
            assert currency.value is not None
            if len(currency.value) != 3 or not currency.value.isalpha():
                raise ValueError("currency must be a three-letter ISO code")
            if currency.value != currency.value.upper():
                raise ValueError("currency must use uppercase letters")
        return self


class ValidationIssue(DomainModel):
    """One deterministic finding produced after extraction."""

    code: str = Field(min_length=1)
    severity: ValidationSeverity
    field_paths: list[str] = Field(default_factory=list)
    message: str = Field(min_length=1)


class ProcessingDecision(DomainModel):
    """Policy decision about whether human review is required."""

    requires_review: bool
    reasons: list[ReviewReason] = Field(default_factory=list)
    policy_version: Literal["0.1.0"] = "0.1.0"

    @model_validator(mode="after")
    def validate_review_reasons(self) -> ProcessingDecision:
        if self.requires_review and not self.reasons:
            raise ValueError("a review decision must contain at least one reason")
        if not self.requires_review and self.reasons:
            raise ValueError("an accepted receipt cannot contain review reasons")
        return self


class ReceiptResult(DomainModel):
    """Complete system result exposed to downstream consumers."""

    extraction: ReceiptExtraction
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    decision: ProcessingDecision
