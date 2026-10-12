"""Protocols implemented by infrastructure adapters."""

from transcribl.ports.artifacts import ArtifactRepository
from transcribl.ports.extraction import PageExtractor
from transcribl.ports.translation import (
    PageTranslationRequest,
    PageTranslator,
    ProviderDescriptor,
    ProviderResult,
    TableReconstructionRequest,
    TableReconstructionResult,
)

__all__ = [
    "ArtifactRepository",
    "PageExtractor",
    "PageTranslationRequest",
    "PageTranslator",
    "ProviderDescriptor",
    "ProviderResult",
    "TableReconstructionRequest",
    "TableReconstructionResult",
]
