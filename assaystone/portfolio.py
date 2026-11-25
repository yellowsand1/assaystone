"""A registry view across capability manifests in a workspace.

A capability lives next to its evidence: ``.assaystone/`` contains
``capability.json``, ``trail.jsonl``, ``receipt.json``, the owner approval, and
the waivers. Any nested ``.assaystone`` directory is another capability.

The portfolio is a read-only table with a strict mode. It does not create a
second source of truth: every cell comes from the capability card.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .card import StatusCard, build_card
from .plane import CapabilityManifest, PlaneError

SKIP_PARTS = {
    ".git",
    "node_modules",
    "build",
    "dist",
    "target",
    ".venv",
    "venv",
    "__pycache__",
}


def discover(root: str | Path) -> list[Path]:
    root = Path(root).resolve()
    found: list[Path] = []
    for path in root.rglob("capability.json"):
        if ".assaystone" not in path.parts:
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        found.append(path)
    return sorted(found)


@dataclass
class PortfolioEntry:
    path: Path
    card: StatusCard | None = None
    error: str = ""
    critical: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "error": self.error,
            "critical": list(self.critical),
            "card": self.card.to_dict() if self.card else None,
        }


@dataclass
class Portfolio:
    root: Path
    entries: list[PortfolioEntry] = field(default_factory=list)

    def critical_count(self) -> int:
        return sum(1 for entry in self.entries if entry.critical)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "capabilities": [entry.to_dict() for entry in self.entries],
            "critical": self.critical_count(),
        }


def _critical(card: StatusCard) -> list[str]:
    issues: list[str] = []
    for item in card.never_gated:
        if item["severity"] == "critical":
            issues.append(
                f"criterion `{item['criterion']}` is gated by no stage"
            )
    # A criterion that is gated by a later stage is not a portfolio defect at
    # the current lifecycle stage. The per-stage gap stays on the card as
    # information; strict mode only requires that every declared stage has a
    # passing decision and that every critical criterion is gated somewhere.
    if card.approval.get("required") and not card.approval.get("ok"):
        issues.append("owner approval is not valid")
    if card.trail.get("present") and not card.trail.get("ok"):
        issues.append("trail does not verify")
    if card.receipt.get("present") and not card.receipt.get("ok"):
        issues.append("receipt does not verify")
    if card.waivers.get("present") and not card.waivers.get("ok"):
        issues.append("waiver file does not verify")
    if card.revocations.get("revoked_artifacts"):
        issues.append("an artifact was signed by a revoked key")
    if card.revocations.get("present") and not card.revocations.get("ok"):
        issues.append("the revocation list does not read")
    if not card.trail.get("present"):
        issues.append("no trail evidence")
    else:
        last = card.trail.get("last", {})
        current = last.get(card.lifecycle)
        if current is None:
            issues.append(
                f"no recorded `{card.lifecycle}` gate for the current lifecycle"
            )
        elif current.get("outcome") != "pass":
            issues.append(
                f"the last `{card.lifecycle}` gate was "
                f"`{current.get('outcome')}`"
            )
        for stage, entry in last.items():
            if stage == card.lifecycle:
                continue
            if entry.get("outcome") != "pass":
                issues.append(
                    f"the last `{stage}` gate was `{entry.get('outcome')}`"
                )
    return issues


def build_portfolio(
    root: str | Path,
    owner_key: str = "",
    receipt_key: str = "",
    owner_public_key: str | Path | None = None,
) -> Portfolio:
    root = Path(root).resolve()
    portfolio = Portfolio(root=root)
    for path in discover(root):
        try:
            manifest = CapabilityManifest.load(path)
        except PlaneError as exc:
            entry = PortfolioEntry(path=path, error=str(exc))
            entry.critical = [f"manifest is invalid: {exc}"]
            portfolio.entries.append(entry)
            continue
        directory = path.parent

        def sidecar(
            name: str, directory: Path = directory
        ) -> Path | None:
            candidate = directory / name
            return candidate if candidate.exists() else None

        card = build_card(
            manifest,
            trail_path=sidecar("trail.jsonl"),
            receipt_path=sidecar("receipt.json"),
            approval_path=sidecar("capability.approval.json"),
            waivers_path=sidecar("capability.waivers.json"),
            revocations_path=sidecar("capability.revocations.json"),
            owner_key=owner_key,
            owner_public_key=owner_public_key,
            receipt_key=receipt_key,
        )
        portfolio.entries.append(
            PortfolioEntry(path=path, card=card, critical=_critical(card))
        )
    return portfolio


def _last(card: StatusCard) -> str:
    last = card.trail.get("last") or {}
    if not last:
        return "-"
    return ", ".join(
        f"{stage}:{entry.get('outcome')}"
        for stage, entry in sorted(last.items())
    )


def render_portfolio(portfolio: Portfolio) -> str:
    if not portfolio.entries:
        return (
            f"No capabilities found under {portfolio.root}. "
            "A capability is a `.assaystone/capability.json`."
        )
    rows = [
        f"{'capability':<24} {'owner':<16} {'risk':<8} {'lifecycle':<10} "
        f"{'criteria':<9} {'last':<28} {'approval':<9} {'receipt':<8} "
        f"{'critical':>8}"
    ]
    for entry in portfolio.entries:
        if entry.card is None:
            rows.append(
                f"{entry.path.parent.name:<24} {'-':<16} {'-':<8} "
                f"{'-':<10} {'-':<9} {'-':<28} {'-':<9} {'-':<8} "
                f"{len(entry.critical):>8}"
            )
            continue
        card = entry.card
        approval = (
            "-"
            if not card.approval.get("required")
            else ("ok" if card.approval.get("ok") else "invalid")
        )
        receipt = (
            "-"
            if not card.receipt.get("present")
            else ("ok" if card.receipt.get("ok") else "invalid")
        )
        rows.append(
            f"{card.capability:<24} {card.owner:<16} {card.risk:<8} "
            f"{card.lifecycle:<10} "
            f"{card.gated_by_some_stage}/{card.criteria:<7} "
            f"{_last(card):<28} {approval:<9} {receipt:<8} "
            f"{len(entry.critical):>8}"
        )
    rows.append("")
    rows.append(
        f"{len(portfolio.entries)} capabilities, "
        f"{portfolio.critical_count()} with critical risks"
    )
    for entry in portfolio.entries:
        label = entry.card.capability if entry.card else str(entry.path)
        for issue in entry.critical:
            rows.append(f"  {label}: {issue}")
    return "\n".join(rows)
