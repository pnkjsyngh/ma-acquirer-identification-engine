"""Pydantic v2 schemas for Stage 1/Stage 2 structured outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RiskFlag(BaseModel):
    risk: str
    evidence: str


class ConvictionModel(BaseModel):
    level: Literal["High", "Medium", "Low"]
    rationale: str


class PrecedentActivityItem(BaseModel):
    year: int
    target: str
    sector: str
    deal_size_mm: float
    deal_type: str
    ev_ebitda_multiple: float | None = None


class ValuationContext(BaseModel):
    median_ev_ebitda: float | None = None
    median_ev_revenue: float | None = None
    comparable_deal_ids: list[str] = []
    narrative: str = ""


class ExternalSource(BaseModel):
    fact: str
    source_url: str
    kind: Literal["wikipedia"]


class RationaleOutput(BaseModel):
    conviction: ConvictionModel
    acquirer_overview: str
    strategic_fit_thesis: str
    precedent_activity: list[PrecedentActivityItem] = []
    valuation_context: ValuationContext
    risk_flags: list[RiskFlag] = Field(min_length=2)
    external_sources: list[ExternalSource] = []


class Stage1Decision(BaseModel):
    reasoning: str
    used_widen: bool = False
    sectors_widened: list[str] = []
    notes: str = ""
