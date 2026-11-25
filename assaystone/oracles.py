"""Generic oracle primitives.

The core knows only these primitives. A domain — Java/Maven, a refund
workflow, a pricing pipeline — is a manifest that binds criteria to them.
Nothing here knows what ``mvn`` is; it is a command payload.

Every primitive fails closed: a missing command, an unreachable host, an
absent database, or a missing driver produces ``escalate``, never ``pass``.
The ``http`` and ``sql`` primitives are read-only by construction; a mutating
call needs an explicit opt-in in the manifest.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import shlex
import sqlite3
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ORACLE_TYPES = (
    "command",
    "file",
    "git",
    "human",
    "http",
    "sql",
    "shadow",
    "transcript",
)
READ_ONLY_HTTP = ("GET", "HEAD", "OPTIONS")
SQL_TIMEOUT_SECONDS = 15
SQL_MAX_ROWS = 1000
HTTP_MAX_BYTES = 262144

SQL_WRITE = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|replace|truncate"
    r"|attach|detach|grant|revoke|vacuum|pragma|begin|commit|rollback)\b",
    re.IGNORECASE,
)


class OracleError(ValueError):
    """An oracle payload cannot be used."""


@dataclass
class OracleSpec:
    id: str
    type: str
    description: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    ref: str = ""
    version: int | None = None
    fingerprint: str = ""


@dataclass
class OracleResult:
    oracle: str
    type: str
    outcome: str
    reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    output: str = ""
    digest: str = ""
    ref: str = ""
    version: int | None = None
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "oracle": self.oracle,
            "type": self.type,
            "outcome": self.outcome,
            "reasons": list(self.reasons),
            "evidence": list(self.evidence),
            "digest": self.digest,
        }
        if self.ref:
            data["ref"] = self.ref
        if self.version is not None:
            data["version"] = self.version
        if self.fingerprint:
            data["fingerprint"] = self.fingerprint
        return data


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def oracle_fingerprint(type_: str, payload: dict[str, Any]) -> str:
    """Stable identity for an oracle definition: type plus payload."""
    digest = hashlib.sha256(
        canonical_json({"type": type_, "payload": payload}).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest[:16]}"


def result_digest(
    spec: OracleSpec,
    outcome: str,
    reasons: list[str],
    evidence: list[str],
    output: str,
) -> str:
    """Digest of what was observed, for the audit trail.

    The trail stores the digest, not the evidence: evidence can contain paths,
    query results, or response bodies that do not belong in a long-lived log.
    """
    body = canonical_json(
        {
            "oracle": spec.id,
            "type": spec.type,
            "outcome": outcome,
            "reasons": list(reasons),
            "evidence": list(evidence),
            "output": output,
        }
    )
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _result(
    spec: OracleSpec,
    outcome: str,
    reasons: list[str] | None = None,
    evidence: list[str] | None = None,
    output: str = "",
) -> OracleResult:
    return OracleResult(
        oracle=spec.id,
        type=spec.type,
        outcome=outcome,
        reasons=list(reasons or []),
        evidence=list(evidence or []),
        output=output,
        ref=spec.ref,
        version=spec.version,
        fingerprint=spec.fingerprint,
    )


def _tail(text: str, limit: int = 800) -> str:
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


def _inside(root: Path, value: str | Path) -> Path | None:
    target = (root / value).resolve()
    return target if target.is_relative_to(root) else None


# ---------------------------------------------------------------------------
# command / file / git / human
# ---------------------------------------------------------------------------


def _command(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    command = payload.get("command")
    if not command:
        return _result(spec, "escalate", ["command payload is empty"])
    if isinstance(command, str):
        command = shlex.split(command)
    cwd = root
    if payload.get("cwd"):
        resolved = _inside(root, str(payload["cwd"]))
        if resolved is None:
            return _result(spec, "escalate", ["cwd escapes the root"])
        cwd = resolved
    timeout = float(payload.get("timeout", 600))
    expected = int(payload.get("expect_exit", 0))
    try:
        proc = subprocess.run(
            [str(part) for part in command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return _result(spec, "escalate", [f"command not found: {command[0]}"])
    except subprocess.TimeoutExpired:
        return _result(spec, "escalate", ["command timed out"])
    output = (proc.stdout or "") + (proc.stderr or "")
    evidence = [f"exit={proc.returncode}"]
    if output.strip():
        evidence.append(_tail(output))
    if proc.returncode == expected:
        return _result(spec, "pass", [], evidence, output)
    return _result(
        spec,
        "fail",
        [f"exit {proc.returncode} != expected {expected}"],
        evidence,
        output,
    )


def _file(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    path = payload.get("path")
    if not path:
        return _result(spec, "escalate", ["file payload has no path"])
    target = _inside(root, str(path))
    if target is None:
        return _result(spec, "escalate", ["path escapes the root"])
    mode = str(payload.get("mode") or "exists")
    if mode == "exists":
        if target.exists():
            return _result(spec, "pass", [], [str(path)])
        return _result(spec, "fail", [f"missing: {path}"])
    try:
        text = target.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return _result(spec, "fail", [f"cannot read: {path}"])
    if mode == "json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            return _result(spec, "fail", [f"invalid JSON: {exc}"], [str(path)], text)
        return _result(spec, "pass", [], [str(path)], text)
    if mode == "contains":
        needle = str(payload.get("needle") or "")
        if needle and needle in text:
            return _result(spec, "pass", [], [str(path)], text)
        return _result(spec, "fail", [f"does not contain {needle!r}"], [], text)
    if mode == "regex":
        pattern = str(payload.get("pattern") or "")
        if pattern and re.search(pattern, text):
            return _result(spec, "pass", [], [str(path)], text)
        return _result(spec, "fail", [f"does not match {pattern!r}"], [], text)
    return _result(spec, "escalate", [f"unknown file mode: {mode!r}"])


def _git(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    mode = str(payload.get("mode") or "clean")
    try:
        inside = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return _result(spec, "escalate", ["git is not available"])
    if inside.returncode != 0:
        return _result(spec, "escalate", ["not a git repository"])
    if mode == "clean":
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if status.returncode != 0:
            return _result(spec, "escalate", ["git status failed"])
        if status.stdout.strip():
            return _result(
                spec,
                "fail",
                ["working tree is not clean"],
                [_tail(status.stdout, 400)],
                status.stdout,
            )
        return _result(spec, "pass", [], ["clean"], "")
    if mode == "branch":
        current = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        name = current.stdout.strip()
        expected = str(payload.get("expected") or "")
        if expected and (name == expected or name.startswith(expected)):
            return _result(spec, "pass", [], [name], name)
        return _result(spec, "fail", [f"branch {name!r} != {expected!r}"], [], name)
    return _result(spec, "escalate", [f"unknown git mode: {mode!r}"])


def _human(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    action = str(payload.get("action") or "")
    record = _inside(root, str(payload.get("record") or "approvals.json"))
    if record is None:
        return _result(spec, "escalate", ["record path escapes the root"])
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _result(spec, "escalate", [f"no approval record: {record.name}"])
    except json.JSONDecodeError as exc:
        return _result(spec, "escalate", [f"invalid approval record: {exc}"])
    approvals = data.get("approvals") if isinstance(data, dict) else data
    if not isinstance(approvals, list):
        return _result(spec, "escalate", ["approvals must be a list"])
    signing_env = payload.get("hmac_env")
    if signing_env:
        key = os.environ.get(str(signing_env))
        if not key:
            return _result(
                spec,
                "escalate",
                [f"missing approval signing key: {signing_env}"],
            )
        signature = data.get("signature") if isinstance(data, dict) else None
        if not signature:
            return _result(spec, "fail", ["approval record is not signed"])
        body = canonical_json({"approvals": approvals}).encode("utf-8")
        expected = hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(str(signature).lower(), expected):
            return _result(
                spec, "fail", ["approval signature does not verify"]
            )
    for item in approvals:
        if not isinstance(item, dict) or item.get("action") != action:
            continue
        if item.get("approved"):
            approver = str(item.get("approver") or "unknown approver")
            return _result(spec, "pass", [], [approver], approver)
        return _result(spec, "fail", [f"{action}: approval denied"])
    return _result(spec, "escalate", [f"{action}: no approval recorded"])


# ---------------------------------------------------------------------------
# http
# ---------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects: a redirect can move a request (and its
    credentials) to a host the manifest never named."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _resolve_secret(value: str) -> tuple[str | None, str | None]:
    if value.startswith("env:"):
        name = value[4:]
        got = os.environ.get(name)
        if got is None:
            return None, f"missing environment variable {name}"
        return got, None
    return value, None


def _json_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                raise KeyError(path)
            current = current[index]
        else:
            raise KeyError(path)
    return current


def _http(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    url = str(payload.get("url") or "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return _result(spec, "escalate", ["http payload needs an http(s) url"])
    method = str(payload.get("method") or "GET").upper()
    if method not in READ_ONLY_HTTP and not payload.get("allow_write"):
        return _result(
            spec,
            "escalate",
            [f"{method} mutates state; set allow_write to opt in"],
        )
    headers: dict[str, str] = {}
    for name, raw in (payload.get("headers") or {}).items():
        value, error = _resolve_secret(str(raw))
        if error:
            return _result(spec, "escalate", [error])
        headers[str(name)] = str(value)
    timeout = min(float(payload.get("timeout", 15)), 120)
    max_bytes = int(payload.get("max_bytes", HTTP_MAX_BYTES))
    data = None
    if method not in READ_ONLY_HTTP and "body" in payload:
        data = json.dumps(payload["body"]).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    handlers: list[urllib.request.BaseHandler] = [_NoRedirect]
    if _is_loopback(parsed.hostname or ""):
        # A local staging service must not be routed through an env proxy;
        # that turns "connection refused" into a proxy error page.
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
            body = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return _result(
                spec, "escalate", [f"redirect not followed (status {exc.code})"]
            )
        status = exc.code
        body = exc.read(max_bytes + 1) or b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return _result(spec, "escalate", [f"http request failed: {reason}"])
    if len(body) > max_bytes:
        return _result(
            spec,
            "escalate",
            [f"response exceeds max_bytes ({max_bytes})"],
        )
    text = body.decode("utf-8", errors="replace")
    body_digest = "sha256:" + hashlib.sha256(body).hexdigest()[:16]
    evidence = [f"status={status}", f"body={body_digest}"]

    expected = payload.get("expect_status")
    if expected is None:
        if not 200 <= status < 300:
            return _result(
                spec, "fail", [f"status {status} is not 2xx"], evidence, text
            )
    else:
        allowed = expected if isinstance(expected, list) else [expected]
        if status not in {int(item) for item in allowed}:
            return _result(
                spec,
                "fail",
                [f"status {status} not in {allowed}"],
                evidence,
                text,
            )

    json_path = payload.get("json_path")
    if json_path:
        try:
            value = _json_path(json.loads(text), str(json_path))
        except json.JSONDecodeError:
            return _result(spec, "fail", ["response is not JSON"], evidence, text)
        except KeyError:
            return _result(
                spec, "fail", [f"json path {json_path!r} is absent"], evidence, text
            )
        evidence.append(f"{json_path}={_tail(str(value), 120)}")
        matchers = [key for key in ("equals", "contains", "regex") if key in payload]
        for key in matchers:
            expected_value = payload[key]
            if key == "equals" and value != expected_value:
                return _result(
                    spec,
                    "fail",
                    [f"{json_path} = {value!r} != {expected_value!r}"],
                    evidence,
                    text,
                )
            if key == "contains" and str(expected_value) not in str(value):
                return _result(
                    spec,
                    "fail",
                    [f"{json_path} does not contain {expected_value!r}"],
                    evidence,
                    text,
                )
            if key == "regex" and not re.search(str(expected_value), str(value)):
                return _result(
                    spec,
                    "fail",
                    [f"{json_path} does not match {expected_value!r}"],
                    evidence,
                    text,
                )
    return _result(spec, "pass", [], evidence, text)


# ---------------------------------------------------------------------------
# sql (read-only)
# ---------------------------------------------------------------------------


def check_read_only_sql(query: str) -> str | None:
    """Return an error message if the query is not a single read-only SELECT."""
    if not query.strip():
        return "query is empty"
    cleaned = re.sub(r"--[^\n]*", " ", query)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"'(?:''|[^'])*'", "''", cleaned)
    cleaned = re.sub(r'"(?:""|[^"])*"', '""', cleaned)
    body = cleaned.strip()
    if not re.match(r"(?is)^(select|with)\b", body):
        return "only SELECT / WITH queries are allowed"
    if ";" in body.rstrip().rstrip(";"):
        return "only a single statement is allowed"
    write = SQL_WRITE.search(body)
    if write:
        return f"write keyword {write.group(0)!r} is not allowed"
    return None


def _sqlite_connect(path: Path) -> sqlite3.Connection:
    quoted = urllib.parse.quote(path.as_posix())
    connection = sqlite3.connect(
        f"file:{quoted}?mode=ro", uri=True, timeout=5
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _mysql_connect(payload: dict[str, Any]) -> tuple[Any, str | None]:
    env_name = str(payload.get("dsn_env") or "ASSAYSTONE_SQL_DSN")
    dsn = os.environ.get(env_name)
    if not dsn:
        return None, f"missing environment variable {env_name}"
    try:
        import pymysql  # type: ignore[import-not-found]
    except ImportError:
        return None, "mysql adapter is not installed (pip install pymysql)"
    parsed = urllib.parse.urlsplit(dsn)
    try:
        port = parsed.port or 3306
        connection = pymysql.connect(
            host=parsed.hostname or "localhost",
            port=port,
            user=urllib.parse.unquote(parsed.username or ""),
            password=urllib.parse.unquote(parsed.password or ""),
            database=parsed.path.lstrip("/") or None,
            connect_timeout=5,
            read_timeout=SQL_TIMEOUT_SECONDS,
            cursorclass=pymysql.cursors.DictCursor,
        )
    except Exception as exc:  # noqa: BLE001 - driver errors vary
        return None, f"mysql connection failed: {exc}"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
    except Exception:  # noqa: BLE001
        connection.close()
        return None, "mysql refused a read-only session"
    return connection, None


def _query_rows(
    spec: OracleSpec, root: Path
) -> tuple[list[dict[str, Any]], str | None]:
    payload = spec.payload
    driver = str(payload.get("driver") or "sqlite")
    query = str(payload.get("query") or "")
    error = check_read_only_sql(query)
    if error:
        return [], error
    if driver == "sqlite":
        database = payload.get("database")
        if not database:
            return [], "sql payload has no database"
        target = _inside(root, str(database))
        if target is None:
            return [], "database escapes the root"
        if not target.exists():
            return [], f"database not found: {database}"
        try:
            connection = _sqlite_connect(target)
        except sqlite3.Error as exc:
            return [], f"sqlite connection failed: {exc}"
        try:
            cursor = connection.execute(query)
            rows = [dict(row) for row in cursor.fetchmany(SQL_MAX_ROWS + 1)]
        except sqlite3.Error as exc:
            return [], f"query failed: {exc}"
        finally:
            connection.close()
    elif driver == "mysql":
        connection, error = _mysql_connect(payload)
        if connection is None:
            return [], error
        try:
            with connection.cursor() as cursor:
                cursor.execute(query)
                rows = list(cursor.fetchmany(SQL_MAX_ROWS + 1))
        except Exception as exc:  # noqa: BLE001
            return [], f"query failed: {exc}"
        finally:
            connection.close()
    else:
        return [], f"unknown sql driver: {driver!r}"
    if len(rows) > SQL_MAX_ROWS:
        return [], f"result exceeds {SQL_MAX_ROWS} rows"
    return rows, None


def _same_scalar(left: Any, right: Any, tolerance: float) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= tolerance
    return str(left) == str(right)


def _row_mismatch(
    rows: list[dict[str, Any]],
    expected: list[Any],
    ignore: list[str],
    tolerance: float,
) -> str:
    if len(rows) != len(expected):
        return f"{len(rows)} rows != expected {len(expected)}"
    for index, (row, want) in enumerate(zip(rows, expected, strict=False)):
        if not isinstance(want, dict):
            return f"row {index}: expected object, got {type(want).__name__}"
        for key, value in want.items():
            if key in ignore:
                continue
            if key not in row:
                return f"row {index}: missing column {key!r}"
            if not _same_scalar(row[key], value, tolerance):
                return (
                    f"row {index}.{key}: {row[key]!r} != {value!r}"
                )
        for key in row:
            if key not in want and key not in ignore:
                return f"row {index}: unexpected column {key!r}"
    return ""


def _sql(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    rows, error = _query_rows(spec, root)
    if error:
        return _result(spec, "escalate", [error])
    rows_json = canonical_json(rows)
    evidence = [f"rows={len(rows)}", f"result=sha256:{hashlib.sha256(rows_json.encode()).hexdigest()[:16]}"]
    expect = payload.get("expect")
    if expect is None:
        return _result(spec, "pass", [], evidence, rows_json)
    if not isinstance(expect, dict):
        return _result(spec, "escalate", ["expect must be an object"])
    mode = str(expect.get("mode") or "rows")
    tolerance = float(expect.get("tolerance", 0.0))
    ignore = [str(item) for item in expect.get("ignore") or []]
    if mode == "empty":
        if rows:
            return _result(
                spec, "fail", [f"expected no rows, got {len(rows)}"], evidence, rows_json
            )
        return _result(spec, "pass", [], evidence, rows_json)
    if mode == "scalar":
        if "equals" not in expect:
            return _result(spec, "escalate", ["scalar expectation needs equals"])
        if not rows:
            return _result(
                spec, "fail", ["expected one row, got none"], evidence, rows_json
            )
        if len(rows[0]) != 1:
            return _result(
                spec,
                "escalate",
                [f"scalar expectation needs one column, got {len(rows[0])}"],
            )
        actual = next(iter(rows[0].values()))
        if _same_scalar(actual, expect["equals"], tolerance):
            return _result(spec, "pass", [], evidence, rows_json)
        return _result(
            spec,
            "fail",
            [f"scalar {actual!r} != {expect['equals']!r}"],
            evidence,
            rows_json,
        )
    if mode == "rows":
        expected = expect.get("equals")
        if expected is None and expect.get("baseline"):
            baseline = _inside(root, str(expect["baseline"]))
            if baseline is None:
                return _result(spec, "escalate", ["baseline escapes the root"])
            try:
                raw = json.loads(baseline.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return _result(spec, "escalate", [f"cannot read baseline: {exc}"])
            expected = raw.get("rows") if isinstance(raw, dict) else raw
        if not isinstance(expected, list):
            return _result(
                spec, "escalate", ["rows expectation needs equals or baseline"]
            )
        mismatch = _row_mismatch(rows, expected, ignore, tolerance)
        if mismatch:
            return _result(spec, "fail", [mismatch], evidence, rows_json)
        return _result(spec, "pass", [], evidence, rows_json)
    return _result(spec, "escalate", [f"unknown sql expectation: {mode!r}"])


# ---------------------------------------------------------------------------
# shadow: same input, old implementation vs new implementation
# ---------------------------------------------------------------------------


def _normalize_text(text: str, compare: dict[str, Any]) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for pattern in compare.get("ignore") or []:
        normalized = re.sub(str(pattern), "", normalized)
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    if compare.get("collapse_whitespace", True):
        lines = [re.sub(r"[ \t]+", " ", line) for line in lines]
    return "\n".join(lines)


def _float_places(tolerance: float) -> int:
    if tolerance <= 0:
        return 9
    return max(0, math.ceil(-math.log10(tolerance)))


def _normalize_json(value: Any, ignore: list[str], places: int, prefix="") -> Any:
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in ignore or path in ignore:
                continue
            normalized[key] = _normalize_json(item, ignore, places, path)
        return normalized
    if isinstance(value, list):
        return [_normalize_json(item, ignore, places, f"{prefix}[]") for item in value]
    if isinstance(value, float):
        return round(value, places)
    return value


def _first_json_diff(left: Any, right: Any, path: str = "") -> str:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left:
                return f"{path}{key}: missing on old side"
            if key not in right:
                return f"{path}{key}: missing on new side"
            diff = _first_json_diff(left[key], right[key], f"{path}{key}.")
            if diff:
                return diff
        return ""
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            label = path.rstrip(".") or "[]"
            return f"{label}: length {len(left)} != {len(right)}"
        for index, (a, b) in enumerate(zip(left, right, strict=False)):
            diff = _first_json_diff(a, b, f"{path}{index}.")
            if diff:
                return diff
        return ""
    if left != right:
        label = path.rstrip(".") or "value"
        return f"{label}: {left!r} != {right!r}"
    return ""


def _nested_spec(item: dict[str, Any], name: str) -> OracleSpec:
    type_ = str(item.get("type") or "")
    if type_ == "shadow":
        raise OracleError(f"{name}: shadow cannot nest inside shadow")
    if type_ not in ORACLE_TYPES:
        raise OracleError(f"{name}: unknown oracle type {type_!r}")
    payload = item.get("payload") or {}
    if not isinstance(payload, dict):
        raise OracleError(f"{name}: payload must be an object")
    return OracleSpec(id=name, type=type_, payload=payload)


def _shadow(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    raw_old = payload.get("old")
    raw_new = payload.get("new")
    if not isinstance(raw_old, dict) or not isinstance(raw_new, dict):
        return _result(spec, "escalate", ["shadow needs old and new specifications"])
    try:
        old_spec = _nested_spec(raw_old, f"{spec.id}:old")
        new_spec = _nested_spec(raw_new, f"{spec.id}:new")
    except OracleError as exc:
        return _result(spec, "escalate", [str(exc)])
    old_result = run_oracle(old_spec, root)
    new_result = run_oracle(new_spec, root)
    evidence = [
        f"old={old_result.outcome}",
        f"new={new_result.outcome}",
    ]
    if old_result.outcome == "escalate":
        return _result(
            spec,
            "escalate",
            [f"old side could not decide: {old_result.reasons[0] if old_result.reasons else 'unknown'}"],
            evidence,
        )
    if new_result.outcome == "escalate":
        return _result(
            spec,
            "escalate",
            [f"new side could not decide: {new_result.reasons[0] if new_result.reasons else 'unknown'}"],
            evidence,
        )
    if old_result.outcome != new_result.outcome:
        return _result(
            spec,
            "fail",
            [f"outcome changed: old={old_result.outcome} new={new_result.outcome}"],
            evidence,
        )
    if old_result.outcome == "fail":
        return _result(
            spec,
            "escalate",
            ["both sides failed; shadow needs a working baseline"],
            evidence,
        )
    compare = payload.get("compare") or {}
    if not isinstance(compare, dict):
        return _result(spec, "escalate", ["compare must be an object"])
    mode = str(compare.get("mode") or "text")
    if mode == "text":
        left = _normalize_text(old_result.output, compare)
        right = _normalize_text(new_result.output, compare)
        if left == right:
            return _result(spec, "pass", [], evidence, left)
        return _result(
            spec,
            "fail",
            ["text output diverged (old vs new)"],
            evidence,
            f"old:\n{_tail(left, 400)}\nnew:\n{_tail(right, 400)}",
        )
    if mode == "json":
        try:
            left_raw = json.loads(old_result.output)
            right_raw = json.loads(new_result.output)
        except json.JSONDecodeError:
            return _result(spec, "escalate", ["shadow json mode needs JSON output"])
        ignore = [str(item) for item in compare.get("ignore") or []]
        places = _float_places(float(compare.get("tolerance", 0.0)))
        left = _normalize_json(left_raw, ignore, places)
        right = _normalize_json(right_raw, ignore, places)
        if left == right:
            return _result(spec, "pass", [], evidence, canonical_json(left))
        diff = _first_json_diff(left, right)
        return _result(
            spec,
            "fail",
            [f"json output diverged: {diff}"],
            evidence,
            canonical_json({"old": left, "new": right}),
        )
    return _result(spec, "escalate", [f"unknown shadow mode: {mode!r}"])


# ---------------------------------------------------------------------------
# transcript: audit what the agent actually did
# ---------------------------------------------------------------------------


def _transcript(spec: OracleSpec, root: Path) -> OracleResult:
    """Run the session audit over an agent transcript.

    This is the bridge from the runtime layer to the gate: the acceptance
    decision can depend on the agent's recorded trajectory, not only on the
    files it left behind. Findings inherit the kernel's provenance rules, so a
    failure that rests on agent-written testimony arrives as an escalation,
    not as a decision.
    """
    from .audit import (
        AuditError,
        audit_traces,
        build_audit_contract,
        load_audit_traces,
    )
    from .model import ESCALATE

    payload = spec.payload
    source = payload.get("transcript")
    if not source:
        return _result(spec, "escalate", ["transcript payload has no source"])
    target = _inside(root, str(source))
    if target is None:
        return _result(spec, "escalate", ["transcript escapes the root"])
    if not target.exists():
        return _result(spec, "escalate", [f"transcript not found: {source}"])
    baseline = _inside(root, str(payload.get("baseline") or "."))
    if baseline is None:
        return _result(spec, "escalate", ["baseline escapes the root"])
    try:
        traces = load_audit_traces(
            target,
            baseline=baseline,
            git_repo=root if payload.get("git_preimage") else None,
            workspace=bool(payload.get("workspace", False)),
        )
    except AuditError as exc:
        return _result(spec, "escalate", [str(exc)])
    if not traces:
        return _result(spec, "escalate", ["no traces found in the transcript"])
    try:
        contract = build_audit_contract(
            baseline, run_tests=bool(payload.get("run_tests", False))
        )
        report = audit_traces(contract, traces, baseline)
    except Exception as exc:  # noqa: BLE001 - the audit is untrusted input
        return _result(spec, "escalate", [f"audit failed: {exc}"])
    counts = report.severity_counts()
    findings = report.findings
    evidence = [
        f"traces={len(traces)}",
        f"findings={len(findings)}",
        "severities="
        + ",".join(f"{name}:{counts[name]}" for name in counts if counts[name]),
    ]
    for finding in findings[:8]:
        evidence.append(f"{finding.verifier}({finding.severity})")
    output = canonical_json(
        {
            "findings": [
                {
                    "verifier": item.verifier,
                    "severity": item.severity,
                    "outcome": item.outcome,
                    "reasons": item.reasons,
                }
                for item in findings
            ]
        }
    )
    rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    fail_on = str(payload.get("fail_on") or "high").lower()
    if fail_on not in {"any", "high", "medium", "low", "none"}:
        return _result(
            spec,
            "escalate",
            [f"unknown fail_on: {fail_on!r}"],
            evidence,
            output,
        )
    threshold = 0 if fail_on == "any" else rank.get(fail_on, 3)
    if fail_on == "none":
        threshold = len(rank) + 1
    failing = [
        item for item in findings if rank.get(item.severity, 2) >= threshold
    ]
    if failing:
        reasons = [
            f"{item.verifier} ({item.severity}): "
            f"{item.reasons[0] if item.reasons else 'no reason'}"
            for item in failing[:3]
        ]
        return _result(spec, "fail", reasons, evidence, output)
    unresolved = [item for item in findings if item.outcome == ESCALATE]
    if unresolved:
        reasons = [
            f"{item.verifier}: {item.reasons[0] if item.reasons else 'unresolved'}"
            for item in unresolved[:3]
        ]
        return _result(spec, "escalate", reasons, evidence, output)
    return _result(spec, "pass", [], evidence, output)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleDefinition:
    id: str
    type: str
    payload: dict[str, Any]
    description: str = ""
    version: int = 1
    owner: str = ""

    @property
    def fingerprint(self) -> str:
        return oracle_fingerprint(self.type, self.payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "version": self.version,
            "owner": self.owner,
            "description": self.description,
            "payload": self.payload,
            "fingerprint": self.fingerprint,
        }


class OracleRegistry:
    """Versioned, reusable oracle definitions owned by a platform team."""

    def __init__(self, definitions: dict[str, OracleDefinition], source: str = ""):
        self.definitions = definitions
        self.source = source

    @classmethod
    def load(cls, path: str | Path) -> "OracleRegistry":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise OracleError(f"registry not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise OracleError(f"invalid registry JSON in {path}: {exc}") from exc
        return cls.from_dict(data, source=str(path))

    @classmethod
    def from_dict(cls, data: Any, source: str = "registry") -> "OracleRegistry":
        if not isinstance(data, dict):
            raise OracleError(f"registry must be an object: {source}")
        definitions: dict[str, OracleDefinition] = {}
        for item in data.get("oracles") or []:
            if not isinstance(item, dict):
                raise OracleError("registry oracle must be an object")
            oracle_id = str(item.get("id") or "")
            if not oracle_id:
                raise OracleError("registry oracle has an empty id")
            if oracle_id in definitions:
                raise OracleError(f"duplicate registry oracle: {oracle_id}")
            type_ = str(item.get("type") or "")
            if type_ not in ORACLE_TYPES:
                raise OracleError(
                    f"registry oracle {oracle_id}: unknown type {type_!r}"
                )
            payload = item.get("payload") or {}
            if not isinstance(payload, dict):
                raise OracleError(
                    f"registry oracle {oracle_id}: payload must be an object"
                )
            version_raw = item.get("version", 1)
            if not isinstance(version_raw, int) or version_raw < 1:
                raise OracleError(
                    f"registry oracle {oracle_id}: version must be a positive int"
                )
            definitions[oracle_id] = OracleDefinition(
                id=oracle_id,
                type=type_,
                payload=payload,
                description=str(item.get("description") or ""),
                version=version_raw,
                owner=str(item.get("owner") or ""),
            )
        return cls(definitions, source=source)

    def resolve(self, ref: str, version: int | None = None) -> OracleDefinition:
        definition = self.definitions.get(ref)
        if definition is None:
            raise OracleError(f"oracle ref {ref!r} is not in the registry")
        if version is not None and int(version) != definition.version:
            raise OracleError(
                f"oracle ref {ref!r} is pinned to v{version}, "
                f"registry has v{definition.version}"
            )
        return definition

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "oracles": [
                self.definitions[key].to_dict() for key in sorted(self.definitions)
            ],
        }


def _dispatch(spec: OracleSpec, root: Path) -> OracleResult:
    if spec.type == "command":
        outcome = _command(spec, root)
    elif spec.type == "file":
        outcome = _file(spec, root)
    elif spec.type == "git":
        outcome = _git(spec, root)
    elif spec.type == "human":
        outcome = _human(spec, root)
    elif spec.type == "http":
        outcome = _http(spec, root)
    elif spec.type == "sql":
        outcome = _sql(spec, root)
    elif spec.type == "shadow":
        outcome = _shadow(spec, root)
    elif spec.type == "transcript":
        outcome = _transcript(spec, root)
    else:
        return _result(spec, "escalate", [f"unknown oracle type: {spec.type!r}"])
    return outcome


def run_oracle(spec: OracleSpec, root: str | Path) -> OracleResult:
    root = Path(root).resolve()
    try:
        outcome = _dispatch(spec, root)
    except Exception as exc:  # noqa: BLE001 - a gate must never crash
        outcome = _result(
            spec,
            "escalate",
            [f"oracle error: {type(exc).__name__}: {exc}"],
        )
    outcome.digest = result_digest(
        spec, outcome.outcome, outcome.reasons, outcome.evidence, outcome.output
    )
    return outcome
