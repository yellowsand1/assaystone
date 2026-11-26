"""The acceptance plane: capability manifests, generic oracles, and gates.

The core knows only nine oracle primitives: ``command``, ``file``, ``git``,
``human``, ``http``, ``sql``, ``shadow``, ``transcript``, and ``verifier``. A domain — Java/Maven, a refund
workflow, a pricing pipeline — is a manifest that binds criteria to those
primitives. Nothing here knows what ``mvn`` is; it is a command payload.

Oracles can be declared inline or referenced from a versioned registry, so a
platform team owns the definitions and capability authors pin them.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .oracles import (  # noqa: F401 - re-exported for compatibility
    ORACLE_TYPES,
    OracleDefinition,
    OracleError,
    OracleRegistry,
    OracleResult,
    OracleSpec,
    canonical_json,
    check_read_only_sql,
    oracle_fingerprint,
    result_digest,
    run_oracle,
)

RISKS = ("low", "medium", "high", "critical")
STAGES = ("design", "shadow", "canary", "production", "incident", "retired")
OUTCOMES = ("pass", "fail", "escalate")
GATING_SEVERITIES = ("critical",)
PRIMARY_SEVERITIES = ("critical", "high")


class PlaneError(ValueError):
    """The manifest cannot be used."""


@dataclass
class StagePolicy:
    require: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    allow_merge: bool = False
    allow_deploy: bool = False
    rollback_required: bool = False
    rollback: str = ""
    after: str = ""
    budget_usd: float | None = None


@dataclass
class ManifestCriterion:
    id: str
    kind: str
    statement: str
    oracle: str
    severity: str = "high"


@dataclass
class CapabilityManifest:
    capability: str
    owner: str
    systems: list[str]
    data_classes: list[str]
    irreversible_actions: list[str]
    risk: str
    lifecycle: str
    oracles: list[OracleSpec]
    policies: dict[str, StagePolicy]
    criteria: list[ManifestCriterion] = field(default_factory=list)
    retention: str = ""
    registry: str = ""
    registry_fingerprint: str = ""
    manifest_approval: bool = False
    waivers: bool = False
    source: str = ""

    @classmethod
    def load(
        cls,
        path: str | Path,
        registry: OracleRegistry | None = None,
    ) -> "CapabilityManifest":
        file_path = Path(path).resolve()
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PlaneError(f"manifest not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise PlaneError(f"invalid manifest JSON in {path}: {exc}") from exc
        if registry is None and isinstance(data, dict) and data.get("registry"):
            try:
                registry = OracleRegistry.load(file_path.parent / data["registry"])
            except OracleError as exc:
                raise PlaneError(str(exc)) from exc
        return cls.from_dict(data, source=str(file_path), registry=registry)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        source: str = "capability",
        registry: OracleRegistry | None = None,
    ) -> "CapabilityManifest":
        if not isinstance(data, dict):
            raise PlaneError(f"manifest must be an object: {source}")
        declared_registry = str(data.get("registry") or "")
        if registry is None and declared_registry:
            raise PlaneError(
                "manifest declares a registry but none was loaded; use "
                "CapabilityManifest.load() or pass a registry"
            )
        oracles = [_oracle_spec(item, registry) for item in data.get("oracles") or []]
        policies = {
            str(name): StagePolicy(
                require=[str(item) for item in (value.get("require") or [])],
                approvals=[str(item) for item in (value.get("approvals") or [])],
                allow_merge=bool(value.get("allow_merge", False)),
                allow_deploy=bool(value.get("allow_deploy", False)),
                rollback_required=bool(value.get("rollback_required", False)),
                rollback=str(value.get("rollback") or ""),
                after=str(value.get("after") or ""),
                budget_usd=(
                    float(value["budget_usd"])
                    if isinstance(value.get("budget_usd"), (int, float))
                    else None
                ),
            )
            for name, value in (data.get("policies") or {}).items()
        }
        criteria = [
            ManifestCriterion(
                id=str(item["id"]),
                kind=str(item["kind"]),
                statement=str(item["statement"]),
                oracle=str(item["oracle"]),
                severity=str(item.get("severity") or "high"),
            )
            for item in data.get("criteria") or []
        ]
        fingerprint = ""
        if registry is not None:
            body = canonical_json(registry.to_dict()).encode("utf-8")
            fingerprint = "sha256:" + hashlib.sha256(body).hexdigest()[:16]
        manifest = cls(
            capability=str(data.get("capability") or ""),
            owner=str(data.get("owner") or ""),
            systems=[str(item) for item in data.get("systems") or []],
            data_classes=[str(item) for item in data.get("data_classes") or []],
            irreversible_actions=[
                str(item) for item in data.get("irreversible_actions") or []
            ],
            risk=str(data.get("risk") or ""),
            lifecycle=str(data.get("lifecycle") or ""),
            oracles=oracles,
            policies=policies,
            criteria=criteria,
            retention=str(data.get("retention") or ""),
            registry=declared_registry or (registry.source if registry else ""),
            registry_fingerprint=fingerprint,
            manifest_approval=bool(data.get("manifest_approval", False)),
            waivers=bool(data.get("waivers", False)),
            source=source,
        )
        errors = manifest.validate()
        if errors:
            raise PlaneError("; ".join(errors))
        return manifest

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.capability.strip():
            errors.append("capability is empty")
        if not self.owner.strip():
            errors.append("owner is empty")
        if self.risk not in RISKS:
            errors.append(f"risk {self.risk!r} is not one of {', '.join(RISKS)}")
        if self.lifecycle not in STAGES:
            errors.append(
                f"lifecycle {self.lifecycle!r} is not one of {', '.join(STAGES)}"
            )
        oracle_ids = [item.id for item in self.oracles]
        if len(set(oracle_ids)) != len(oracle_ids):
            errors.append("duplicate oracle id")
        for oracle in self.oracles:
            if not oracle.id.strip():
                errors.append("oracle id is empty")
            if oracle.type not in ORACLE_TYPES:
                errors.append(f"oracle {oracle.id}: unknown type {oracle.type!r}")
        criterion_ids = [item.id for item in self.criteria]
        if len(set(criterion_ids)) != len(criterion_ids):
            errors.append("duplicate criterion id")
        for criterion in self.criteria:
            if not criterion.statement.strip():
                errors.append(f"criterion {criterion.id}: empty statement")
            if criterion.oracle not in oracle_ids:
                errors.append(
                    f"criterion {criterion.id}: unknown oracle {criterion.oracle!r}"
                )
            if criterion.kind not in (
                "precondition",
                "invariant",
                "postcondition",
                "forbidden_action",
                "evidence",
            ):
                errors.append(
                    f"criterion {criterion.id}: unknown kind {criterion.kind!r}"
                )
        cycle = _policy_cycle(self.policies)
        if cycle:
            errors.append("policy chain is circular: " + " -> ".join(cycle))
        for stage, policy in self.policies.items():
            if stage not in STAGES:
                errors.append(f"policy stage {stage!r} is unknown")
            for oracle_id in policy.require + policy.approvals:
                if oracle_id not in oracle_ids:
                    errors.append(f"policy {stage}: unknown oracle {oracle_id!r}")
            if policy.rollback and policy.rollback not in oracle_ids:
                errors.append(
                    f"policy {stage}: unknown rollback oracle "
                    f"{policy.rollback!r}"
                )
            if policy.budget_usd is not None and policy.budget_usd < 0:
                errors.append(f"policy {stage}: budget_usd is negative")
            if policy.rollback_required and not policy.rollback:
                errors.append(
                    f"policy {stage}: rollback_required needs a rollback oracle"
                )
            if policy.after:
                if policy.after not in STAGES:
                    errors.append(
                        f"policy {stage}: unknown previous stage {policy.after!r}"
                    )
                elif policy.after == stage:
                    errors.append(f"policy {stage}: after cannot be itself")
                elif policy.after not in self.policies:
                    errors.append(
                        f"policy {stage}: after {policy.after!r} has no policy"
                    )
        return errors

    def uncovered_criteria(self) -> list[ManifestCriterion]:
        """Criteria no lifecycle stage gates at all.

        A per-stage gap is reported by ``evaluate_gate``; this is the stronger
        static case: the manifest declares a criterion and never binds it to an
        oracle in any policy.
        """
        gated: set[str] = set()
        for policy in self.policies.values():
            gated.update(policy.require)
            gated.update(policy.approvals)
            if policy.rollback:
                gated.add(policy.rollback)
        return [item for item in self.criteria if item.oracle not in gated]

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "capability": self.capability,
            "owner": self.owner,
            "systems": list(self.systems),
            "data_classes": list(self.data_classes),
            "irreversible_actions": list(self.irreversible_actions),
            "risk": self.risk,
            "lifecycle": self.lifecycle,
            "retention": self.retention,
            "manifest_approval": self.manifest_approval,
            "waivers": self.waivers,
            "criteria": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "statement": item.statement,
                    "oracle": item.oracle,
                    "severity": item.severity,
                }
                for item in self.criteria
            ],
            "oracles": [
                {
                    "id": item.id,
                    "type": item.type,
                    "description": item.description,
                    "payload": item.payload,
                    "ref": item.ref,
                    "version": item.version,
                    "fingerprint": item.fingerprint,
                }
                for item in self.oracles
            ],
            "policies": {
                name: _policy_view(policy)
                for name, policy in sorted(self.policies.items())
            },
        }
        if self.registry:
            data["registry"] = self.registry
            data["registry_fingerprint"] = self.registry_fingerprint
        return data


def _oracle_spec(
    item: Any, registry: OracleRegistry | None
) -> OracleSpec:
    if not isinstance(item, dict):
        raise PlaneError("oracle must be an object")
    ref = str(item.get("ref") or "")
    oracle_id = str(item.get("id") or ref or "")
    if not oracle_id:
        raise PlaneError("oracle has an empty id")
    if ref:
        if item.get("type") or item.get("payload"):
            raise PlaneError(
                f"oracle {oracle_id}: a ref cannot also declare type or payload; "
                "the registry owns the definition"
            )
        if registry is None:
            raise PlaneError(
                f"oracle {oracle_id}: ref {ref!r} needs an oracle registry"
            )
        try:
            definition = registry.resolve(ref, item.get("version"))
        except OracleError as exc:
            raise PlaneError(str(exc)) from exc
        return OracleSpec(
            id=oracle_id,
            type=definition.type,
            description=str(item.get("description") or definition.description),
            payload=definition.payload,
            ref=ref,
            version=definition.version,
            fingerprint=definition.fingerprint,
        )
    return OracleSpec(
        id=oracle_id,
        type=str(item.get("type") or ""),
        description=str(item.get("description") or ""),
        payload=dict(item.get("payload") or {}),
        version=item.get("version") if isinstance(item.get("version"), int) else None,
        fingerprint=oracle_fingerprint(
            str(item.get("type") or ""), dict(item.get("payload") or {})
        ),
    )


def _policy_view(policy: StagePolicy) -> dict[str, Any]:
    """The serialised policy that the owner's digest covers.

    The shape is frozen: keys that existed when approvals were first issued stay
    present even when empty, and a field added later is emitted only when it is
    set. A tool upgrade must not invalidate an approval.
    """
    view: dict[str, Any] = {
        "require": list(policy.require),
        "approvals": list(policy.approvals),
        "allow_merge": policy.allow_merge,
        "allow_deploy": policy.allow_deploy,
        "rollback_required": policy.rollback_required,
        "rollback": policy.rollback,
        "after": policy.after,
    }
    if policy.budget_usd is not None:
        view["budget_usd"] = policy.budget_usd
    return view


def manifest_digest(manifest: CapabilityManifest) -> str:
    """Identity of the acceptance rules, stable across machines.

    The registry path is excluded (it can be absolute) but the registry
    fingerprint stays, so a changed shared oracle changes the digest.
    """
    data = manifest.to_dict()
    data.pop("registry", None)
    body = canonical_json(data).encode("utf-8")
    return "sha256:" + hashlib.sha256(body).hexdigest()


@dataclass
class GateResult:
    capability: str
    stage: str
    outcome: str
    results: list[OracleResult] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    merge_allowed: bool = False
    deploy_allowed: bool = False
    gap: list[dict[str, Any]] = field(default_factory=list)
    strict: bool = False
    rollback_required: bool = False
    rollback: str = ""
    manifest_lifecycle: str = ""
    manifest_digest: str = ""
    commit: str = ""
    manifest_approval: dict[str, Any] = field(default_factory=dict)
    waived: list[dict[str, Any]] = field(default_factory=list)
    revoked: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False
    cost_usd: float = 0.0
    prior: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "stage": self.stage,
            "outcome": self.outcome,
            "results": [item.to_dict() for item in self.results],
            "missing": list(self.missing),
            "reasons": list(self.reasons),
            "merge_allowed": self.merge_allowed,
            "deploy_allowed": self.deploy_allowed,
            "gap": list(self.gap),
            "strict": self.strict,
            "rollback_required": self.rollback_required,
            "rollback": self.rollback,
            "manifest_lifecycle": self.manifest_lifecycle,
            "manifest_digest": self.manifest_digest,
            "commit": self.commit,
            "manifest_approval": dict(self.manifest_approval),
            "waived": list(self.waived),
            "revoked": list(self.revoked),
            "dry_run": self.dry_run,
            "cost_usd": round(self.cost_usd, 6),
            "prior": dict(self.prior),
        }


def _policy_cycle(policies: dict[str, StagePolicy]) -> list[str] | None:
    for start in policies:
        seen: list[str] = []
        current = start
        while current:
            if current in seen:
                return seen[seen.index(current) :] + [current]
            seen.append(current)
            policy = policies.get(current)
            current = policy.after if policy else ""
    return None


def oracle_cost(spec: OracleSpec) -> float:
    value = spec.payload.get("cost_usd", 0)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _assurance_gap(
    manifest: CapabilityManifest, policy: StagePolicy
) -> list[dict[str, Any]]:
    gated = set(policy.require) | set(policy.approvals)
    if policy.rollback:
        gated.add(policy.rollback)
    return [
        {
            "criterion": item.id,
            "severity": item.severity,
            "oracle": item.oracle,
            "statement": item.statement,
        }
        for item in manifest.criteria
        if item.oracle not in gated
    ]


def _head_commit(root: str | Path) -> str:
    """The commit the gate is deciding about, or "" outside a repository."""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def repo_head_commit(start: str | Path) -> str:
    """HEAD of the repository containing ``start``, or "" outside a repo."""
    path = Path(start)
    if not path.is_dir():
        path = path.parent
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return _head_commit(candidate)
    return ""


def _chain_check(
    manifest: CapabilityManifest,
    stage: str,
    policy: StagePolicy,
    trail_path: str | Path | None,
    commit: str = "",
) -> tuple[str, dict[str, Any]]:
    """A stage can require a recorded pass of an earlier stage on the trail.

    The chain is scoped to the capability, the manifest digest, and the commit.
    A pass under different acceptance rules does not count, and neither does a
    pass on different code: a canary that ran on one commit cannot authorise a
    different one.
    """
    if not policy.after:
        return "", {}
    if trail_path is None:
        return (
            f"{stage} requires a recorded {policy.after} pass; pass the trail "
            "with --audit",
            {},
        )
    from .trail import TrailError
    from .trail import read as read_trail
    from .trail import verify as verify_trail

    check = verify_trail(trail_path)
    if not check.ok:
        detail = check.errors[0] if check.errors else "unknown error"
        return f"the trail does not verify: {detail}", {}
    try:
        entries = read_trail(trail_path)
    except TrailError as exc:
        return f"cannot read the trail: {exc}", {}
    prior = None
    for entry in entries:
        if (
            entry.get("capability") == manifest.capability
            and entry.get("stage") == policy.after
        ):
            prior = entry
    if prior is None:
        return (
            f"no recorded {policy.after} gate for {manifest.capability}",
            {},
        )
    info = {
        "stage": policy.after,
        "seq": prior.get("seq"),
        "hash": prior.get("hash"),
        "outcome": prior.get("outcome"),
    }
    if prior.get("outcome") != "pass":
        return (
            f"the last {policy.after} gate did not pass: "
            f"{prior.get('outcome')!r}",
            info,
        )
    if not prior.get("manifest_digest"):
        return (
            f"the {policy.after} entry has no manifest digest; cannot chain",
            info,
        )
    prior_commit = str(prior.get("commit") or "")
    info["commit"] = prior_commit
    if not prior_commit:
        return (
            f"the {policy.after} entry has no commit; cannot chain to code",
            info,
        )
    if commit and prior_commit != commit:
        return (
            f"the {policy.after} pass was recorded for commit "
            f"{prior_commit[:12]}, not {commit[:12]}; re-run {policy.after} "
            "on this code",
            info,
        )
    if prior.get("manifest_digest") != manifest_digest(manifest):
        return (
            f"acceptance rules changed since {policy.after}; "
            "re-run that stage first",
            info,
        )
    return "", info


def _manifest_approval_check(
    manifest: CapabilityManifest,
    approval_path: str | Path | None,
    owner_key: str,
    owner_public_key: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
    if not manifest.manifest_approval:
        return "", {}
    from .approval import (
        ApprovalError,
        approval_path_for,
        load_approval,
        verify_approval,
    )

    path = approval_path
    if path is None:
        path = approval_path_for(manifest)
        if path is None:
            return (
                "the manifest requires owner approval but has no path; "
                "run capability accept",
                {},
            )
    try:
        data = load_approval(path)
    except ApprovalError as exc:
        return str(exc), {}
    check = verify_approval(
        data,
        owner_key,
        manifest,
        public_key_path=owner_public_key,
    )
    if not check.ok:
        return "; ".join(check.errors), check.info
    return "", check.info


def evaluate_gate(
    manifest: CapabilityManifest,
    stage: str,
    root: str | Path,
    strict: bool = False,
    trail_path: str | Path | None = None,
    approval_path: str | Path | None = None,
    owner_key: str = "",
    owner_public_key: str | Path | None = None,
    waivers_path: str | Path | None = None,
    revocations_path: str | Path | None = None,
    dry_run: bool = False,
    budget_usd: float | None = None,
) -> GateResult:
    if stage not in STAGES:
        raise PlaneError(f"unknown stage: {stage!r}")
    policy = manifest.policies.get(stage)
    if policy is None:
        return GateResult(
            capability=manifest.capability,
            stage=stage,
            outcome="escalate",
            reasons=[f"no policy for stage {stage!r}"],
            strict=strict,
            manifest_lifecycle=manifest.lifecycle,
            manifest_digest=manifest_digest(manifest),
            commit=_head_commit(root),
            dry_run=dry_run,
        )
    commit = _head_commit(root)
    approval_error, approval_info = _manifest_approval_check(
        manifest, approval_path, owner_key, owner_public_key
    )
    if approval_error:
        return GateResult(
            capability=manifest.capability,
            stage=stage,
            outcome="escalate",
            reasons=[approval_error],
            gap=_assurance_gap(manifest, policy),
            strict=strict,
            manifest_lifecycle=manifest.lifecycle,
            manifest_digest=manifest_digest(manifest),
            commit=commit,
            manifest_approval=approval_info,
            dry_run=dry_run,
            rollback_required=policy.rollback_required,
            rollback=policy.rollback,
        )
    chain_error, prior = _chain_check(
        manifest, stage, policy, trail_path, commit
    )
    if chain_error:
        return GateResult(
            capability=manifest.capability,
            stage=stage,
            outcome="escalate",
            reasons=[chain_error],
            gap=_assurance_gap(manifest, policy),
            strict=strict,
            manifest_lifecycle=manifest.lifecycle,
            manifest_digest=manifest_digest(manifest),
            commit=commit,
            rollback_required=policy.rollback_required,
            rollback=policy.rollback,
            prior=prior,
        )
    by_id = {item.id: item for item in manifest.oracles}
    required = list(
        dict.fromkeys(
            policy.require + policy.approvals + ([policy.rollback] if policy.rollback else [])
        )
    )
    results: list[OracleResult] = []
    missing: list[str] = []
    spent = 0.0
    budget = policy.budget_usd if policy.budget_usd is not None else budget_usd
    budget_exhausted = ""
    for oracle_id in required:
        spec = by_id.get(oracle_id)
        if spec is None:
            missing.append(oracle_id)
            continue
        cost = oracle_cost(spec)
        if budget is not None and spent + cost > budget:
            budget_exhausted = (
                f"verification budget ${budget:.4f} would be exceeded before "
                f"`{oracle_id}` (${cost:.4f}); spent ${spent:.4f}"
            )
            break
        spent += cost
        if dry_run and spec.payload.get("mutates"):
            results.append(
                OracleResult(
                    oracle=spec.id,
                    type=spec.type,
                    outcome="escalate",
                    reasons=[
                        "not executed: a dry run does not perform an oracle "
                        "that declares it mutates state"
                    ],
                    ref=spec.ref,
                    version=spec.version,
                    fingerprint=spec.fingerprint,
                )
            )
            continue
        results.append(run_oracle(spec, root))

    gap = _assurance_gap(manifest, policy)
    blocking_gap = [
        item
        for item in gap
        if item["severity"] in GATING_SEVERITIES and stage not in ("design",)
    ]
    waived: list[dict[str, Any]] = []
    waived_oracles: set[str] = set()
    waiver_notes: list[str] = []
    if manifest.waivers and any(item.outcome == "fail" for item in results):
        if not owner_key and not owner_public_key:
            return GateResult(
                capability=manifest.capability,
                stage=stage,
                outcome="escalate",
                results=results,
                missing=missing,
                reasons=[
                    "waivers are enabled but no owner key or public key is "
                    "available"
                ],
                gap=gap,
                strict=strict,
                manifest_lifecycle=manifest.lifecycle,
                manifest_digest=manifest_digest(manifest),
                manifest_approval=approval_info,
                rollback_required=policy.rollback_required,
                rollback=policy.rollback,
                prior=prior,
            )
        from .waiver import WaiverError, load_waivers, verify_waivers, waiver_path_for

        path = waivers_path or waiver_path_for(manifest)
        valid: dict[str, dict[str, Any]] = {}
        if path is not None and Path(path).exists():
            try:
                data = load_waivers(path)
            except WaiverError as exc:
                waiver_notes.append(str(exc))
            else:
                check = verify_waivers(
                    data,
                    owner_key,
                    manifest,
                    public_key_path=owner_public_key,
                )
                if check.ok:
                    valid = check.valid
                else:
                    waiver_notes.extend(check.errors)
        for item in results:
            if item.outcome != "fail":
                continue
            bound = [
                criterion
                for criterion in manifest.criteria
                if criterion.oracle == item.oracle
            ]
            if bound and all(criterion.id in valid for criterion in bound):
                for criterion in bound:
                    waived.append(
                        {"oracle": item.oracle, **valid[criterion.id]}
                    )
                waived_oracles.add(item.oracle)
    revoked: list[dict[str, Any]] = []
    revocation_error = ""
    if manifest.manifest_approval or manifest.waivers:
        from .revocation import read_revocations, revocation_path_for

        path = revocations_path or revocation_path_for(manifest.source or None)
        revocations = read_revocations(path)
        if not revocations.ok:
            revocation_error = "; ".join(revocations.errors)
        else:
            candidates = []
            if approval_info.get("key_id"):
                candidates.append(("owner approval", approval_info["key_id"]))
            for item in waived:
                if item.get("key_id"):
                    candidates.append(
                        (f"waiver for `{item['criterion']}`", item["key_id"])
                    )
            for label, key_id in candidates:
                hit = revocations.is_revoked(key_id)
                if hit:
                    revoked.append({**hit, "artifact": label})
    if revoked:
        return GateResult(
            capability=manifest.capability,
            stage=stage,
            outcome="escalate",
            results=results,
            missing=missing,
            reasons=[
                f"{item['artifact']} was signed by a revoked key "
                f"{item['key_id']} ({item.get('reason')}); re-decide under a "
                "current key"
                for item in revoked
            ],
            gap=gap,
            strict=strict,
            manifest_lifecycle=manifest.lifecycle,
            manifest_digest=manifest_digest(manifest),
            commit=commit,
            manifest_approval=approval_info,
            waived=waived,
            revoked=revoked,
            dry_run=dry_run,
            prior=prior,
            rollback_required=policy.rollback_required,
            rollback=policy.rollback,
        )
    if revocation_error:
        return GateResult(
            capability=manifest.capability,
            stage=stage,
            outcome="escalate",
            results=results,
            missing=missing,
            reasons=[f"revocation list does not read: {revocation_error}"],
            gap=gap,
            strict=strict,
            manifest_lifecycle=manifest.lifecycle,
            manifest_digest=manifest_digest(manifest),
            commit=commit,
            manifest_approval=approval_info,
            waived=waived,
            dry_run=dry_run,
            prior=prior,
            rollback_required=policy.rollback_required,
            rollback=policy.rollback,
        )
    effective_fail = any(
        item.outcome == "fail" and item.oracle not in waived_oracles
        for item in results
    )
    if budget_exhausted:
        outcome = "escalate"
    elif effective_fail and not dry_run:
        outcome = "fail"
    elif dry_run:
        outcome = "escalate"
    elif missing or any(item.outcome == "escalate" for item in results):
        outcome = "escalate"
    elif strict and blocking_gap:
        outcome = "escalate"
    else:
        outcome = "pass"

    reasons = [f"{stage} requires: {', '.join(required) or 'nothing'}"]
    for item in waived:
        reasons.append(
            f"waived by {item.get('approved_by')}: `{item['criterion']}` "
            f"until {item.get('expires_at')}"
        )
    reasons.extend(waiver_notes)
    if budget_exhausted:
        reasons.append(budget_exhausted)
    if dry_run:
        reasons.append(
            "dry run: this is not a decision; mutating oracles were not "
            "executed"
        )
    if policy.after:
        reasons.append(f"chained after a recorded {policy.after} pass")
    for oracle_id in missing:
        reasons.append(f"missing oracle: {oracle_id}")
    if gap:
        reasons.append(
            f"{len(gap)} declared criteria are not gated at {stage}"
        )
    if strict:
        for item in blocking_gap:
            reasons.append(
                f"strict: {item['severity']} criterion {item['criterion']!r} "
                f"is not gated at {stage}"
            )
    if policy.rollback_required:
        reasons.append(f"rollback evidence: {policy.rollback}")
    return GateResult(
        capability=manifest.capability,
        stage=stage,
        outcome=outcome,
        results=results,
        missing=missing,
        reasons=reasons,
        merge_allowed=policy.allow_merge and outcome == "pass",
        deploy_allowed=policy.allow_deploy and outcome == "pass",
        gap=gap,
        strict=strict,
        rollback_required=policy.rollback_required,
        rollback=policy.rollback,
        manifest_lifecycle=manifest.lifecycle,
        manifest_digest=manifest_digest(manifest),
        commit=commit,
        manifest_approval=approval_info,
        waived=waived,
        revoked=revoked,
        dry_run=dry_run,
        cost_usd=spent,
        prior=prior,
    )


def render_gate(result: GateResult) -> str:
    lines = [
        f"capability: {result.capability}",
        f"stage: {result.stage}",
        f"outcome: {result.outcome}",
        f"dry run: {'yes' if getattr(result, 'dry_run', False) else 'no'}",
        f"cost: ${getattr(result, 'cost_usd', 0.0):.4f}",
        f"merge allowed: {'yes' if result.merge_allowed else 'no'}",
        f"deploy allowed: {'yes' if result.deploy_allowed else 'no'}",
        "",
        f"{'oracle':<20} {'type':<9} {'outcome':<10} reason",
    ]
    for item in result.results:
        reason = item.reasons[0] if item.reasons else ""
        if len(reason) > 80:
            reason = reason[:77] + "..."
        lines.append(
            f"{item.oracle:<20} {item.type:<9} {item.outcome:<10} {reason}"
        )
    for oracle_id in result.missing:
        lines.append(f"{oracle_id:<20} {'-':<9} {'missing':<10} not in manifest")
    if result.gap:
        lines.append("")
        lines.append("assurance gap (declared, not gated at this stage):")
        for item in result.gap:
            lines.append(
                f"  {item['criterion']:<24} {item['severity']:<9} {item['statement']}"
            )
    lines.append("")
    for reason in result.reasons:
        lines.append(f"  {reason}")
    return "\n".join(lines)
