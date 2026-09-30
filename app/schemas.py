from typing import Literal
from pydantic import BaseModel, Field

class Finding(BaseModel):
    object: str
    location: str
    category: Literal['litter', 'dirt', 'stain', 'standing_water', 'clutter', 'other']
    severity: Literal['low', 'medium', 'high']
    approximate_count: int | None = Field(ge=0)
    evidence: str
    action: str

class ViewAssessment(BaseModel):
    image_index: int = Field(ge=1)
    reference_index: int | None = Field(ge=1)
    comparable: bool
    confidence: float = Field(ge=0, le=1)
    visible_reference_area_percent: float = Field(ge=0, le=100)
    clean_visible_area_percent: float | None = Field(ge=0, le=100)
    litter_free_score: float | None = Field(ge=0, le=100)
    surface_cleanliness_score: float | None = Field(ge=0, le=100)
    orderly_surroundings_score: float | None = Field(ge=0, le=100)
    summary: str
    comparison_evidence: str
    limitations: list[str]
    findings: list[Finding]

class ModelAssessment(BaseModel):
    summary: str
    views: list[ViewAssessment]
    recommendations: list[str]

WEIGHTS = {'litter_free_score': 0.5, 'surface_cleanliness_score': 0.35, 'orderly_surroundings_score': 0.15}

def score_assessment(assessment: ModelAssessment, image_count: int, reference_count: int) -> dict:
    """Validate correspondence and derive scores; never trust a model's overall score."""
    indices = [v.image_index for v in assessment.views]
    if sorted(indices) != list(range(1, image_count + 1)):
        raise ValueError('Model did not assess every submitted image exactly once.')
    views = []
    for view in sorted(assessment.views, key=lambda v: v.image_index):
        if view.reference_index is not None and view.reference_index > reference_count:
            raise ValueError('Model returned an unknown reference image.')
        eligible = (view.comparable and view.reference_index is not None and
                    view.confidence >= .6 and view.visible_reference_area_percent >= 50 and
                    all(getattr(view, key) is not None for key in WEIGHTS))
        score = round(sum(getattr(view, k) * w for k, w in WEIGHTS.items()), 1) if eligible else None
        views.append({**view.model_dump(), 'cleanliness_percent': score,
                      'status': 'scored' if eligible else 'needs_review'})
    # Do not let repeated photos of one clean area outweigh another reference view.
    groups = {}
    for v in views:
        if v['cleanliness_percent'] is not None:
            groups.setdefault(v['reference_index'], []).append(v['cleanliness_percent'])
    covered = sorted(groups)
    complete = len(covered) == reference_count and all(v['status'] == 'scored' for v in views)
    score = round(sum(min(values) for values in groups.values()) / reference_count, 1) if complete else None
    status = 'needs_review' if score is None else 'clean' if score >= 90 else 'mostly_clean' if score >= 75 else 'needs_cleaning'
    return {**assessment.model_dump(), 'views': views, 'cleanliness_percent': score, 'status': status,
            'reference_coverage_percent': round(len(covered) / reference_count * 100),
            'missing_reference_indices': [i for i in range(1, reference_count + 1) if i not in covered],
            'scoring_version': '1.0', 'weights': WEIGHTS}
