"""Decision tables for rules RevOps owns: engagement triggers, SLAs, cadence timing.

A table is plain YAML that RevOps edits without a deploy:

    engagement_tee_up:
      hit_policy: first            # first match wins; `collect` returns every match
      rules:
        - id: replied
          when: {replied: true}
          then: {action: none, reason: "Reply Desk owns replies"}
        - id: three_opens
          when: {human_opens: ">= 3", has_open_deal: false}
          then: {action: tee_up, pause: true, priority: high, reason: "3+ human opens"}
      default: {action: none}

Cells use the GoRules (zen) unary test syntax, so a table exported from the GoRules editor and a
table written here mean the same thing:

    ">= 3"  "< 5"  "!= lost"       comparisons
    "[1..3]"  "(1..3]"            ranges ([ ] inclusive, ( ) exclusive)
    "a, b"  or  '"a", "b"'        any of
    true / false / null / 3        equality
    "" or "-" or missing           any value

Bare words (`post_meeting`) are read as strings. `then` holds plain values, never expressions.

Two engines, same answers:
  builtin  pure Python, always available, covers the syntax above.
  zen      when `zen-engine` is installed (pip install zen-engine), cells run through zen, and a
           table can instead point at a native GoRules JDM file: {jdm: rules/tee_up.json}.

Every evaluation returns which rule ids matched, so the audit log can say why an action fired.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:  # optional: the GoRules engine
    import zen as _zen  # type: ignore
except Exception:  # pragma: no cover - depends on the install
    _zen = None

ANY = {"", "-"}
_OPS = (">=", "<=", "!=", "==", ">", "<")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-./@ ]*$")
_RANGE = re.compile(r"^([\[\(])\s*(-?\d+(?:\.\d+)?)\s*\.\.\s*(-?\d+(?:\.\d+)?)\s*([\]\)])$")


class RuleError(ValueError):
    """A table or cell that cannot be read. Raised at load time, never during a run."""


def zen_available() -> bool:
    return _zen is not None


# ---------- cells ----------
def _split_any(cell: str) -> list[str]:
    """Split on top-level commas (not inside quotes or brackets)."""
    out, cur, depth, quote = [], "", 0, None
    for ch in cell:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur += ch
        elif ch in "[(":
            depth += 1
            cur += ch
        elif ch in "])":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if quote or depth:
        raise RuleError(f"unbalanced quotes or brackets in {cell!r}")
    out.append(cur.strip())
    return [t for t in out if t]


def _literal(tok: str) -> Any:
    t = tok.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    low = t.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    if _IDENT.match(t):
        return t
    raise RuleError(f"cannot read value {tok!r}")


def _canon_literal(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return json.dumps(str(v))


def canonical(cell: Any) -> str:
    """One spelling for every cell: bare words quoted, YAML scalars turned into zen syntax."""
    if cell is None:
        return ""
    if isinstance(cell, bool) or isinstance(cell, (int, float)):
        return _canon_literal(cell)
    if isinstance(cell, list):
        return ", ".join(_canon_literal(_literal(str(x)) if isinstance(x, str) else x) for x in cell)
    s = str(cell).strip()
    if s in ANY:
        return ""
    parts = []
    for term in _split_any(s):
        if _RANGE.match(term):
            parts.append(term)
            continue
        op = next((o for o in _OPS if term.startswith(o)), None)
        if op:
            parts.append(f"{op} {_canon_literal(_literal(term[len(op):]))}")
        else:
            parts.append(_canon_literal(_literal(term)))
    return ", ".join(parts)


def _num(v: Any) -> float | None:
    """Numbers only: a numeric string stays a string, as it does in zen."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _term_matches(term: str, value: Any) -> bool:
    m = _RANGE.match(term)
    if m:
        n = _num(value)
        if n is None:
            return False
        lo, hi = float(m.group(2)), float(m.group(3))
        ok_lo = n >= lo if m.group(1) == "[" else n > lo
        ok_hi = n <= hi if m.group(4) == "]" else n < hi
        return ok_lo and ok_hi
    op = next((o for o in _OPS if term.startswith(o)), None)
    if op:
        want = _literal(term[len(op):])
        if op in ("==", "!="):
            eq = _equal(value, want)
            return eq if op == "==" else not eq
        a, b = _num(value), _num(want)
        if a is None or b is None:
            return False
        return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]
    return _equal(value, _literal(term))


def _equal(value: Any, want: Any) -> bool:
    if want is None or value is None:
        return value is None and want is None
    if isinstance(want, bool) or isinstance(value, bool):
        return isinstance(value, bool) and isinstance(want, bool) and value == want
    a, b = _num(value), _num(want)
    if a is not None or b is not None:
        return a is not None and b is not None and a == b
    return isinstance(value, str) and isinstance(want, str) and value == want


def cell_matches(cell: str, value: Any, engine: str = "builtin") -> bool:
    """Does `value` satisfy a canonical cell? engine 'zen' defers to zen-engine when installed."""
    if cell == "":
        return True
    if engine == "zen" and _zen is not None:
        try:
            return bool(_zen.evaluate_unary_expression(cell, {"$": value}))
        except Exception:  # zen refuses to compare mismatched types; that is a non-match, as in builtin
            return False
    return any(_term_matches(t, value) for t in _split_any(cell))


# ---------- tables ----------
@dataclass
class Rule:
    id: str
    when: dict[str, str]          # field -> canonical cell
    then: dict[str, Any]


@dataclass
class Table:
    name: str
    rules: list[Rule] = field(default_factory=list)
    hit_policy: str = "first"
    default: dict[str, Any] = field(default_factory=dict)
    jdm: dict | None = None       # a native GoRules decision (zen engine only)
    description: str = ""

    @property
    def inputs(self) -> list[str]:
        seen: list[str] = []
        for r in self.rules:
            for k in r.when:
                if k not in seen:
                    seen.append(k)
        return seen


@dataclass
class Result:
    table: str
    matched: list[str]
    outputs: list[dict]
    engine: str

    @property
    def output(self) -> dict:
        """The first match (or the default) for hit_policy first; the first of several for collect."""
        return self.outputs[0] if self.outputs else {}

    def as_dict(self) -> dict:
        return {"table": self.table, "matched": self.matched, "output": self.output, "engine": self.engine}


def parse_table(name: str, spec: dict, base: Path | None = None) -> Table:
    if not isinstance(spec, dict):
        raise RuleError(f"table {name}: expected a mapping")
    if spec.get("jdm"):
        p = Path(spec["jdm"])
        if base is not None and not p.is_absolute():
            p = base / p
        try:
            jdm = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise RuleError(f"table {name}: cannot read JDM file {p}: {e}") from None
        return Table(name, [], "first", dict(spec.get("default") or {}), jdm, str(spec.get("description", "")))
    policy = str(spec.get("hit_policy", "first")).lower()
    if policy not in ("first", "collect"):
        raise RuleError(f"table {name}: hit_policy must be first or collect, got {policy!r}")
    rules, ids = [], set()
    for i, r in enumerate(spec.get("rules") or []):
        if not isinstance(r, dict) or not isinstance(r.get("then", {}), dict):
            raise RuleError(f"table {name}: rule {i + 1} needs `when` and `then` mappings")
        rid = str(r.get("id") or f"rule_{i + 1}")
        if rid in ids:
            raise RuleError(f"table {name}: duplicate rule id {rid}")
        ids.add(rid)
        try:
            when = {str(k): canonical(v) for k, v in (r.get("when") or {}).items()}
        except RuleError as e:
            raise RuleError(f"table {name}, rule {rid}: {e}") from None
        rules.append(Rule(rid, when, dict(r.get("then") or {})))
    if not rules:
        raise RuleError(f"table {name}: no rules")
    return Table(name, rules, policy, dict(spec.get("default") or {}), None, str(spec.get("description", "")))


def load_tables(path: str | Path) -> dict[str, Table]:
    """Read every table in a YAML file (a top-level `tables:` mapping, or the mapping itself)."""
    p = Path(path)
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        raise RuleError(f"cannot read {p}: {e}") from None
    tables = data.get("tables", data) if isinstance(data, dict) else {}
    return {n: parse_table(n, s, p.parent) for n, s in tables.items()}


def _engine(prefer: str) -> str:
    prefer = (prefer or "auto").lower()
    if prefer == "zen":
        if _zen is None:
            raise RuleError("rules engine 'zen' requested but zen-engine is not installed (pip install zen-engine)")
        return "zen"
    if prefer == "builtin":
        return "builtin"
    return "zen" if _zen is not None else "builtin"


def evaluate(table: Table, facts: dict, prefer: str = "auto") -> Result:
    """Run one table on a dict of facts. Missing facts are None (they only match `null` or an empty cell)."""
    if table.jdm is not None:
        if _zen is None:
            raise RuleError(f"table {table.name} is a GoRules JDM file; install zen-engine to run it")
        out = _zen.ZenEngine().create_decision(json.dumps(table.jdm)).evaluate(facts)
        res = (out or {}).get("result") or {}
        outs = res if isinstance(res, list) else [res]
        return Result(table.name, ["jdm"] if any(outs) else [], [o for o in outs if o] or [table.default], "zen")
    eng = _engine(prefer)
    matched, outputs = [], []
    for r in table.rules:
        if all(cell_matches(cell, facts.get(k), eng) for k, cell in r.when.items()):
            matched.append(r.id)
            outputs.append({**r.then, "rule": r.id})
            if table.hit_policy == "first":
                break
    if not outputs and table.default:
        outputs = [{**table.default, "rule": "default"}]
    return Result(table.name, matched, outputs, eng)


def check(tables: dict[str, Table], prefer: str = "auto") -> list[str]:
    """Problems that would make a table behave differently on the two engines (empty = fine)."""
    issues = []
    if _zen is None:
        return issues
    for t in tables.values():
        for r in t.rules:
            for k, cell in r.when.items():
                if cell == "":
                    continue
                try:
                    _zen.validate_unary_expression(cell)
                except Exception as e:  # pragma: no cover - zen message varies by version
                    issues.append(f"{t.name}.{r.id}.{k}: zen rejects {cell!r}: {e}")
    return issues
