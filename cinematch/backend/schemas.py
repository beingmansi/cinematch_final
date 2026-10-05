import re
from pydantic import BaseModel, Field, field_validator


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=30)

    @field_validator("username")
    @classmethod
    def clean(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", v):
            raise ValueError("username may only contain letters, digits, _ . - (3-30 chars)")
        return v


class RatingIn(BaseModel):
    user_id: int
    movie_id: int
    rating: float = Field(ge=0.5, le=5.0)

    @field_validator("rating")
    @classmethod
    def half_steps(cls, v: float) -> float:
        if (v * 2) != int(v * 2):
            raise ValueError("rating must be in steps of 0.5")
        return v


class ReviewIn(BaseModel):
    user_id: int
    movie_id: int
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("review text cannot be empty")
        return v


class WatchIn(BaseModel):
    user_id: int
    movie_id: int


class TmdbAddIn(BaseModel):
    tmdb_id: int = Field(gt=0)
