from pydantic import BaseModel, validator
from typing import Optional


class InstanceUpdate(BaseModel):
    status: str  # 'available' | 'in_use'
    used_by: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    notes: Optional[str] = None
    password: Optional[str] = None

    @validator("status")
    def validate_status(cls, v):
        if v not in ("available", "in_use", "maintenance"):
            raise ValueError("status must be 'available', 'in_use' or 'maintenance'")
        return v


class InstanceFree(BaseModel):
    pass
