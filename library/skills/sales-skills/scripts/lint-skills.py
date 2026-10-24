#!/usr/bin/env python3
"""
Static linter for the sales skills corpus.

Checks every skill in skills/ against the mechanical rules in
memory/skill-standards.md, and extracts the API "research date" so skills
can be ranked by how likely they are to be out of date with their API.

This pass is deterministic and free — no LLM, no network. It catches the
bulk of best-practice violations and produces a prioritized worklist for
the two expensive passes (semantic quality + live API currency).

Usage:
    python3 scripts/lint-skills.py                # full report to stdout
    python3 scripts/lint-skills.py --json OUT     # also write JSON report
    python3 scripts/lint-skills.py --errors-only  # only show ERROR rows

Output severities:
    ERROR  — hard rule violation (must fix)
    WARN   — soft / heuristic issue (review)
    INFO   — informational (staleness, non-standard fields)
"""
import argparse
import json
import os
import re
import subprocess
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
TODAY = date(2026, 6, 13)  # pinned: no Date.now in this env's harness; update on run

DESC_MAX = 1024
BODY_MAX_DEFAULT = 200
BODY_MAX_ROUTER = 500
ROUTERS = {"sales-do", "sales-third-party", "sales-request-skill"}  # meta skills allowed to be long
STD_FIELDS = {"name", "description", "argument-hint", "license", "version", "tags", "github"}
REQUIRED_FIELDS = ["name", "description", "argument-hint", "license", "version", "tags"]

# Every skill folder that exists — used to validate /sales-* cross-references.
ALL_SLUGS = {d for d in os.listdir(SKILLS)
             if d.startswith("sales-") and os.path.isdir(os.path.join(SKILLS, d))}
# Real skills that live in OTHER repos but are legitimately referenced by name
# (e.g. the third-party catalog). Not dead routes despite having no local folder.
EXTERNAL_SLUGS = {"sales-enablement"}
# Catalog/browser skills intentionally list external skills — skip cross-ref there.
CATALOG_SKILLS = {"sales-third-party"}


def forbidden_token_rules():
    """Build (rule, compiled_regex) pairs for tokens that must never appear in any
    skill file.

    Two universal rules:
      * author  — no self-attribution. Scoped PRECISELY to attribution forms
        (a YAML `author:` key, an `Author:` label line, an `## Author` heading,
        a `Created/Written/Maintained by <Proper Name>` byline). It deliberately
        does NOT match third-party API field names (`"author":` in JSON, Ghost's
        `/authors/` endpoint, "co-author", "content author" role) — those are
        accurate platform docs and removing them would corrupt the references.
      * pii     — the user's real name/email/company must never appear. Patterns
        are supplied OUT OF BAND so the literal identifiers are never written into
        this committed script (which would itself violate the rule):
            SKILL_LINT_PII       comma-separated literals, OR
            SKILL_LINT_PII_FILE  path (ideally outside the repo) of regexes, 1/line
        If neither is set, the PII scan is skipped (see api note in main())."""
    author = re.compile(
        r"""^\s*(?:                       # line start (allow indent)
              \#{1,6}\s+authors?\s*:?\s*$  #   '## Author' heading (alone, not 'Author Finder')
            | [*_]{0,2}\s*authors?\s*[*_]{0,2}\s*:   # 'Author:' / '**Author:**' label / yaml key
        )""", re.I | re.X)
    rules = [("author", author)]

    pii = set()
    for extra in os.environ.get("SKILL_LINT_PII", "").split(","):
        extra = extra.strip()
        if extra:
            pii.add(re.escape(extra))
    pf = os.environ.get("SKILL_LINT_PII_FILE", "")
    if pf and os.path.isfile(pf):
        with open(pf, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    pii.add(line)
    if pii:
        rules.append(("pii", re.compile("|".join(sorted(pii)), re.I)))
    return rules


FORBIDDEN = forbidden_token_rules()
PII_ENABLED = any(r == "pii" for r, _ in FORBIDDEN)


def parse_frontmatter(text):
    """Return (frontmatter_dict_raw_lines, body_text). Minimal, dependency-free.
    Only top-level `key:` lines are captured; values kept as raw strings."""
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return None, text
    fm = {}
    body_start = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body_start = i + 1
            break
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s?(.*)$", lines[i])
        if m:
            fm[m.group(1)] = m.group(2)
    if body_start is None:
        return None, text
    body = "\n".join(lines[body_start:])
    return fm, body


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    return v


def latest_date_in(text):
    """Largest YYYY-MM-DD or YYYY-MM found in text, as a date (day defaults to 01)."""
    best = None
    for m in re.finditer(r"(20\d{2})-(\d{2})(?:-(\d{2}))?", text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
        try:
            dt = date(y, min(mo, 12), min(max(d, 1), 28))
        except ValueError:
            continue
        if best is None or dt > best:
            best = dt
    return best


def months_between(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month)


def lint_skill(slug, path):
    issues = []  # (severity, rule, message)

    def err(rule, msg):
        issues.append(("ERROR", rule, msg))

    def warn(rule, msg):
        issues.append(("WARN", rule, msg))

    def info(rule, msg):
        issues.append(("INFO", rule, msg))

    skill_md = os.path.join(path, "SKILL.md")
    if not os.path.isfile(skill_md):
        err("structure", "SKILL.md missing")
        return issues, {}

    with open(skill_md, encoding="utf-8") as fh:
        raw = fh.read()
    fm, body = parse_frontmatter(raw)
    body_lines = raw.count("\n") + 1
    meta = {"slug": slug, "lines": body_lines, "research_date": None, "stale_months": None}

    # --- frontmatter presence ---
    if fm is None:
        err("frontmatter", "no parseable YAML frontmatter (--- delimiters)")
        return issues, meta

    for f in REQUIRED_FIELDS:
        if f not in fm:
            err("frontmatter", f"missing required field: {f}")

    extra = [k for k in fm if k not in STD_FIELDS]
    if "author" in fm:
        err("frontmatter", "forbidden field: author")
    nonstd = [k for k in extra if k != "author"]
    if nonstd:
        info("frontmatter", f"non-standard field(s): {', '.join(nonstd)}")

    # --- UNIVERSAL RULES: forbidden tokens must not appear anywhere in a skill ---
    # "author" (any attribution) and the user's PII (name/email/company). Scans
    # frontmatter, body, evals, and every reference file.
    scan_files = [skill_md]
    evals_p = os.path.join(path, "evals", "evals.json")
    if os.path.isfile(evals_p):
        scan_files.append(evals_p)
    refs_dir = os.path.join(path, "references")
    if os.path.isdir(refs_dir):
        for dp, _, fns in os.walk(refs_dir):
            for fn in fns:
                scan_files.append(os.path.join(dp, fn))
    for fp in scan_files:
        try:
            with open(fp, encoding="utf-8") as fh:
                for ln, line in enumerate(fh, 1):
                    for rule, rx in FORBIDDEN:
                        if rx.search(line):
                            rel = os.path.relpath(fp, path)
                            label = "personal info" if rule == "pii" else "'author'"
                            err(rule, f"{rel}:{ln} contains {label}")
        except (OSError, UnicodeDecodeError):
            pass

    # --- name ---
    name = unquote(fm.get("name", ""))
    if name != slug:
        err("name", f"name '{name}' != folder '{slug}'")
    if not re.fullmatch(r"[a-z0-9-]+", name or ""):
        err("name", f"name not kebab-case: '{name}'")
    if "claude" in name or "anthropic" in name:
        err("name", "name contains reserved 'claude'/'anthropic'")

    # --- description ---
    desc = unquote(fm.get("description", ""))
    dlen = len(desc)
    meta["desc_len"] = dlen
    if dlen > DESC_MAX:
        err("description", f"length {dlen} > {DESC_MAX}")
    if dlen and not re.search(r"do\s*not\s*use|don'?t\s*use", desc, re.I):
        warn("description", "no negative trigger ('Do NOT use for ...')")
    if re.search(r"</?[a-zA-Z][^>]*>", desc):  # real XML-like tag, not '<24h'/'>40%'
        warn("description", "contains an XML-like tag")
    if re.search(r"\$\d", desc):
        warn("description", "contains pricing ($N) — time-sensitive")
    if re.search(r"\b20\d{2}\b", desc):
        warn("description", "contains a year — time-sensitive")

    # --- argument-hint ---
    if "argument-hint" in fm and not unquote(fm["argument-hint"]).strip():
        warn("argument-hint", "empty")

    # --- license / version / tags ---
    if "license" in fm and unquote(fm["license"]) != "MIT":
        warn("license", f"license is '{unquote(fm['license'])}' (expected MIT)")
    ver = unquote(fm.get("version", ""))
    if ver and not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        warn("version", f"version not semver: '{ver}'")
    tags = fm.get("tags", "")
    if tags and not tags.strip().startswith("["):
        warn("tags", "tags not an array")

    # --- body size & sections ---
    # Routers and cross-platform STRATEGY skills (those carrying references/platforms.md)
    # legitimately run long — they coordinate many tools. Give them the 500-line cap.
    is_strategy = os.path.isfile(os.path.join(path, "references", "platforms.md"))
    is_router = slug in ROUTERS or is_strategy
    meta["kind"] = "router" if slug in ROUTERS else ("strategy" if is_strategy else "platform")
    cap = BODY_MAX_ROUTER if is_router else BODY_MAX_DEFAULT
    if body_lines > cap:
        sev = warn if body_lines <= cap * 1.5 else err
        sev("body-size", f"{body_lines} lines > {cap} cap")

    # Match by heading KEYWORD, not a literal '## Related' — skills legitimately use
    # numbered headings like '## Step 5 — Related skills' (caught FP in pilot).
    headings = [l.lower() for l in body.splitlines() if l.lstrip().startswith("#")]

    def has_heading(*kw):
        return any(any(k in h for k in kw) for h in headings)

    if not has_heading("example"):
        warn("sections", "no Examples heading")
    if not has_heading("troubleshoot", "gotcha"):
        warn("sections", "no Troubleshooting/Gotchas heading")
    if not has_heading("related"):
        warn("sections", "no Related-skills heading")

    # --- dead-route check: every /sales-* reference must name a real skill folder ---
    # Lookbehind excludes file paths (skills/sales-foo) — only real route mentions match.
    # Skip catalog/browser skills, which intentionally reference external skills.
    if slug not in CATALOG_SKILLS:
        for ref in sorted(set(re.findall(r"(?<![\w/])/sales-[a-z0-9][a-z0-9-]*", raw))):
            if ref[1:] not in ALL_SLUGS and ref[1:] not in EXTERNAL_SLUGS:
                warn("cross-ref", f"dead route {ref} (no skill folder)")

    # --- evals ---
    evals_path = os.path.join(path, "evals", "evals.json")
    if not os.path.isfile(evals_path):
        err("evals", "evals/evals.json missing")
    else:
        try:
            with open(evals_path, encoding="utf-8") as fh:
                ev = json.load(fh)
            if isinstance(ev, list):
                cases = ev
            else:
                cases = ev.get("evals", [])
                if ev.get("skill_name") not in (slug, name):
                    warn("evals", f"skill_name '{ev.get('skill_name')}' != '{slug}'")
            if len(cases) < 3:
                err("evals", f"only {len(cases)} eval cases (need >=3)")
            for i, c in enumerate(cases):
                a = c.get("assertions", [])
                if not (2 <= len(a) <= 4):
                    warn("evals", f"case {i}: {len(a)} assertions (want 2-4)")
                if not c.get("prompt"):
                    warn("evals", f"case {i}: no prompt")
        except (json.JSONDecodeError, OSError) as e:
            err("evals", f"evals.json unreadable: {e}")

    # --- references ---
    refs = os.path.join(path, "references")
    learnings = os.path.join(refs, "learnings.md")
    if os.path.isdir(refs):
        if not os.path.isfile(learnings) and not is_router:
            warn("references", "no references/learnings.md")
        # nested-deep check (router catalog/ is the sanctioned exception)
        for entry in os.listdir(refs):
            sub = os.path.join(refs, entry)
            if os.path.isdir(sub) and not is_router:
                warn("references", f"nested references dir: references/{entry}/")
        # api-reference presence for API-calling skills
        has_api_ref = any(f.endswith("api-reference.md") for f in os.listdir(refs))
        meta["has_api_ref"] = has_api_ref
    else:
        if not is_router:
            warn("references", "no references/ dir")
        meta["has_api_ref"] = False

    # --- API research date / staleness ---
    rd = None
    m = re.search(r"research\s*\(?\s*(20\d{2})-(\d{2})", raw, re.I)
    if m:
        rd = date(int(m.group(1)), int(m.group(2)), 1)
    if os.path.isfile(learnings):
        with open(learnings, encoding="utf-8") as fh:
            ld = latest_date_in(fh.read())
        if ld and (rd is None or ld > rd):
            rd = ld
    if rd:
        meta["research_date"] = rd.isoformat()
        meta["stale_months"] = months_between(rd, TODAY)

    # An API-calling skill (description mentions API/webhook/endpoint) with no
    # api-reference file is an API-coverage gap.
    calls_api = bool(re.search(r"\bAPI\b|webhook|endpoint|REST", desc, re.I))
    meta["calls_api"] = calls_api
    if calls_api and os.path.isdir(refs) and not meta.get("has_api_ref"):
        info("api-coverage", "description mentions API but no *-api-reference.md")

    return issues, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write full JSON report to this path")
    ap.add_argument("--errors-only", action="store_true")
    args = ap.parse_args()

    slugs = sorted(
        d for d in os.listdir(SKILLS)
        if d.startswith("sales-") and os.path.isdir(os.path.join(SKILLS, d))
    )

    report = []
    rule_counts = {}
    sev_counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for slug in slugs:
        issues, meta = lint_skill(slug, os.path.join(SKILLS, slug))
        for sev, rule, msg in issues:
            sev_counts[sev] += 1
            rule_counts[(sev, rule)] = rule_counts.get((sev, rule), 0) + 1
        report.append({"slug": slug, "meta": meta,
                       "issues": [{"sev": s, "rule": r, "msg": m} for s, r, m in issues]})

    # ---- console summary ----
    print(f"Linted {len(slugs)} skills  |  "
          f"ERROR={sev_counts['ERROR']}  WARN={sev_counts['WARN']}  INFO={sev_counts['INFO']}")
    print(f"PII scan: {'ON' if PII_ENABLED else 'OFF (set SKILL_LINT_PII or SKILL_LINT_PII_FILE)'}\n")

    print("Issues by rule (severity / rule / count):")
    for (sev, rule), n in sorted(rule_counts.items(), key=lambda x: (-x[1], x[0][1])):
        print(f"  {sev:5}  {rule:14}  {n}")
    print()

    # skills with ERRORs
    err_skills = [r for r in report if any(i["sev"] == "ERROR" for i in r["issues"])]
    print(f"Skills with ERRORs: {len(err_skills)}")
    for r in err_skills:
        errs = [i for i in r["issues"] if i["sev"] == "ERROR"]
        print(f"  {r['slug']}")
        for i in errs:
            print(f"      [{i['rule']}] {i['msg']}")
    print()

    if not args.errors_only:
        # staleness ranking (API-calling skills, oldest first)
        stale = [r for r in report
                 if r["meta"].get("calls_api") and r["meta"].get("stale_months") is not None]
        stale.sort(key=lambda r: -r["meta"]["stale_months"])
        print(f"Top 25 stalest API-calling skills (months since research):")
        for r in stale[:25]:
            print(f"  {r['meta']['stale_months']:3}mo  {r['meta']['research_date']}  {r['slug']}")
        undated = [r for r in report
                   if r["meta"].get("calls_api") and r["meta"].get("stale_months") is None]
        print(f"\nAPI-calling skills with NO datable research stamp: {len(undated)}")
        print("  " + ", ".join(r["slug"] for r in undated[:30])
              + (" ..." if len(undated) > 30 else ""))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"today": TODAY.isoformat(), "sev_counts": sev_counts,
                       "rule_counts": {f"{s}/{r}": n for (s, r), n in rule_counts.items()},
                       "skills": report}, fh, indent=2)
        print(f"\nWrote JSON report: {args.json}")


if __name__ == "__main__":
    main()
