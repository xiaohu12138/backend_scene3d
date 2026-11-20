from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Parameters(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    dataset_id: Literal['nanjing'] = 'nanjing'
    temperature: float = Field(20, ge=-20, le=80)
    tension_ratio: float = Field(0.45, ge=0.15, le=0.5)
    maximum_wind_line: bool = False
    sample_height: float = Field(60, ge=1, le=4500)
    components: list[Literal['transverse', 'vertical', 'longitudinal']] = Field(
        default_factory=lambda: ['transverse', 'vertical', 'longitudinal'], max_length=3)

class Submission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: str = Field(pattern=r'^s3p_[0-9a-f]{32}$')
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
