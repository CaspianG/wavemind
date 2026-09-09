"""Owned, isolated digital memory; transports bind authenticated principals."""

from .models import BrainError, Principal
from .service import BrainService

__all__ = ["BrainError", "BrainService", "Principal"]
