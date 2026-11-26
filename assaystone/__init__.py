"""Assaystone — the assay stone for AI agents."""

__version__ = "0.23.0"

from . import packs as _packs  # noqa: F401  (registers built-in domain packs)
from .contract import Contract
from .model import Artifact, Label, Step, Trace, Verdict
from .runner import run_contract
from .verifiers import REGISTRY, Verifier, load_external_verifiers, register

load_external_verifiers()

__all__ = [
    "Artifact",
    "Contract",
    "Label",
    "REGISTRY",
    "Step",
    "Trace",
    "Verdict",
    "Verifier",
    "register",
    "run_contract",
]
