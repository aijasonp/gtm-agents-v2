#!/usr/bin/env python3
"""
Greenhouse Harvest API client — stdlib only (urllib, json, base64).
Covers common recruiting operations via Greenhouse's REST API.
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://harvest.greenhouse.io/v1"


def load_api_key():
    """Read Greenhouse API key from env var."""
    key = os.environ.get("GREENHOUSE_API_KEY")
    if key:
        return key
    print(
        "Error: No Greenhouse API key. Set GREENHOUSE_API_KEY env var.",
        file=sys.stderr,
    )
    sys.exit(1)


def _auth_header():
    """Build Basic Auth header: base64(token + ':')."""
    token = load_api_key()
    encoded = base64.b64encode(f"{token}:".encode()).decode()
    return f"Basic {encoded}"


def _parse_link_header(header):
    """Parse Link header and return the 'next' URL if present."""
    if not header:
        return None
    for part in header.split(","):
        match = re.match(r'\s*<([^>]+)>\s*;\s*rel="next"', part.strip())
        if match:
            return match.group(1)
    return None


def api_request(method, path, body=None, params=None, _retries=3):
    """Make a single API request. Returns (data, response_headers)."""
    if path.startswith("http"):
        url = path
    else:
        url = f"{BASE_URL}/{path.lstrip('/')}"

    if params:
        filtered = {k: v for k, v in params.items() if v is not None}
        if filtered:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(filtered)

    headers = {
        "Authorization": _auth_header(),
        "Content-Type": "application/json",
    }

    data_bytes = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)

    for attempt in range(_retries):
        try:
            with urllib.request.urlopen(req) as resp:
                resp_headers = resp.headers
                raw = resp.read()
                result = json.loads(raw) if raw else None
                return result, resp_headers
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < _retries - 1:
                wait = int(e.headers.get("Retry-After", 2 ** (attempt + 1)))
                print(f"Rate limited, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            body_text = e.read().decode()
            print(f"HTTP {e.code}: {body_text}", file=sys.stderr)
            sys.exit(1)


def api_get(path, params=None):
    """GET request, return (data, headers)."""
    return api_request("GET", path, params=params)


def api_post(path, body):
    """POST request, return (data, headers)."""
    return api_request("POST", path, body=body)


def api_patch(path, body):
    """PATCH request, return (data, headers)."""
    return api_request("PATCH", path, body=body)


def api_get_all(path, params=None):
    """GET with auto-pagination following Link: next headers. Returns all results."""
    all_results = []
    data, headers = api_get(path, params=params)
    if isinstance(data, list):
        all_results.extend(data)
    else:
        return data  # single object, no pagination

    while True:
        next_url = _parse_link_header(headers.get("Link"))
        if not next_url:
            break
        data, headers = api_get(next_url)
        if isinstance(data, list):
            all_results.extend(data)
        else:
            break
    return all_results


def api_get_paged(path, params=None, fetch_all=False):
    """GET with optional auto-pagination. Returns data (list or object)."""
    if fetch_all:
        return api_get_all(path, params=params)
    data, _ = api_get(path, params=params)
    return data


def out(data, pretty=False):
    """Print JSON output."""
    print(json.dumps(data, indent=2) if pretty else json.dumps(data))


# ---------------------------------------------------------------------------
# Read Commands
# ---------------------------------------------------------------------------


def cmd_jobs(args):
    params = {"per_page": args.limit or 100}
    if args.status:
        params["status"] = args.status
    if args.department_id:
        params["department_id"] = args.department_id
    data = api_get_paged("jobs", params=params, fetch_all=args.all)
    out(data, args.pretty)


def cmd_job(args):
    data, _ = api_get(f"jobs/{args.id}")
    out(data, args.pretty)


def cmd_candidates(args):
    params = {"per_page": args.limit or 100}
    if args.job_id:
        params["job_id"] = args.job_id
    if args.created_after:
        params["created_after"] = args.created_after
    if args.updated_after:
        params["updated_after"] = args.updated_after
    data = api_get_paged("candidates", params=params, fetch_all=args.all)
    out(data, args.pretty)


def cmd_candidate(args):
    data, _ = api_get(f"candidates/{args.id}")
    out(data, args.pretty)


def cmd_applications(args):
    params = {"per_page": args.limit or 100}
    if args.job_id:
        params["job_id"] = args.job_id
    if args.status:
        params["status"] = args.status
    if args.created_after:
        params["created_after"] = args.created_after
    if args.updated_after:
        params["updated_after"] = args.updated_after
    data = api_get_paged("applications", params=params, fetch_all=args.all)
    out(data, args.pretty)


def cmd_application(args):
    data, _ = api_get(f"applications/{args.id}")
    out(data, args.pretty)


def cmd_stages(args):
    data, _ = api_get(f"jobs/{args.job_id}/stages")
    out(data, args.pretty)


def cmd_scorecards(args):
    data = api_get_paged(
        f"applications/{args.application_id}/scorecards", fetch_all=args.all
    )
    out(data, args.pretty)


def cmd_offers(args):
    data = api_get_paged(
        f"applications/{args.application_id}/offers", fetch_all=args.all
    )
    out(data, args.pretty)


def cmd_departments(args):
    data = api_get_paged("departments", fetch_all=args.all)
    out(data, args.pretty)


def cmd_offices(args):
    data = api_get_paged("offices", fetch_all=args.all)
    out(data, args.pretty)


def cmd_users(args):
    params = {"per_page": args.limit or 100}
    data = api_get_paged("users", params=params, fetch_all=args.all)
    out(data, args.pretty)


def cmd_user(args):
    data, _ = api_get(f"users/{args.id}")
    out(data, args.pretty)


def cmd_sources(args):
    data = api_get_paged("sources", fetch_all=args.all)
    out(data, args.pretty)


def cmd_rejection_reasons(args):
    data = api_get_paged("rejection_reasons", fetch_all=args.all)
    out(data, args.pretty)


def cmd_activity(args):
    data, _ = api_get(f"candidates/{args.candidate_id}/activity_feed")
    out(data, args.pretty)


def cmd_scheduled_interviews(args):
    data = api_get_paged(
        f"applications/{args.application_id}/scheduled_interviews", fetch_all=args.all
    )
    out(data, args.pretty)


def cmd_attachments(args):
    """List attachments for a candidate (resumes, cover letters, admin uploads, etc.)."""
    data, _ = api_get(f"candidates/{args.candidate_id}")
    attachments = data.get("attachments", [])
    out(attachments, args.pretty)


def cmd_download_attachment(args):
    """Download an attachment by URL to a local file."""
    url = args.url
    # Pre-signed S3 URLs already have auth — don't add our own
    req_headers = {}
    if "X-Amz-Signature" not in url and "X-Amz-Algorithm" not in url:
        req_headers["Authorization"] = _auth_header()
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            # Determine filename
            filename = args.output
            if not filename:
                # Try Content-Disposition header
                cd = resp.headers.get("Content-Disposition", "")
                match = re.search(r'filename="?([^";\n]+)', cd)
                if match:
                    filename = match.group(1).strip()
                else:
                    # Extract from URL path
                    filename = url.split("/")[-1].split("?")[0] or "attachment"
            with open(filename, "wb") as f:
                f.write(content)
            print(json.dumps({"downloaded": filename, "size_bytes": len(content)}))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"HTTP {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)


def cmd_custom_fields(args):
    """List custom fields defined in the Greenhouse account."""
    params = {}
    if args.field_type:
        params["field_type"] = args.field_type
    data = api_get_paged("custom_fields", params=params, fetch_all=True)
    out(data, args.pretty)


def cmd_application_detail(args):
    """Get full application detail including answers to custom questions and attachments.
    
    Combines application data, candidate attachments, and candidate data into one view.
    """
    # Get the application
    app_data, _ = api_get(f"applications/{args.id}")
    
    # The application object includes answers to custom questions in the 'answers' field
    # and keyed_custom_fields. Get candidate for attachments.
    candidate_id = app_data.get("candidate_id")
    result = {
        "application": app_data,
    }
    
    if candidate_id:
        cand_data, _ = api_get(f"candidates/{candidate_id}")
        result["candidate"] = cand_data
        result["attachments"] = cand_data.get("attachments", [])
    
    out(result, args.pretty)


# ---------------------------------------------------------------------------
# Write Commands
# ---------------------------------------------------------------------------


def cmd_add_note(args):
    body = {"user_id": int(args.user_id), "body": args.body}
    data, _ = api_post(f"candidates/{args.candidate_id}/activity_feed/notes", body)
    out(data, args.pretty)


def cmd_add_candidate(args):
    candidate = {
        "first_name": args.first_name,
        "last_name": args.last_name,
    }
    if args.company:
        candidate["company"] = args.company
    if args.title:
        candidate["title"] = args.title
    if args.tags:
        candidate["tags"] = args.tags

    phone_numbers = []
    if args.phone:
        phone_numbers.append({"value": args.phone, "type": "mobile"})
    email_addresses = []
    if args.email:
        email_addresses.append({"value": args.email, "type": "personal"})
    website_addresses = []
    if args.website:
        website_addresses.append({"value": args.website, "type": "personal"})
    social_media_addresses = []
    if args.social:
        social_media_addresses.append({"value": args.social})

    if phone_numbers:
        candidate["phone_numbers"] = phone_numbers
    if email_addresses:
        candidate["email_addresses"] = email_addresses
    if website_addresses:
        candidate["website_addresses"] = website_addresses
    if social_media_addresses:
        candidate["social_media_addresses"] = social_media_addresses

    data, _ = api_post("candidates", candidate)
    out(data, args.pretty)


def cmd_advance(args):
    # Greenhouse requires from_stage_id; infer it from the application's current stage.
    app_data, _ = api_get(f"applications/{args.application_id}")
    current_stage = (app_data or {}).get("current_stage") or {}
    from_stage_id = current_stage.get("id")
    if not from_stage_id:
        print(
            "Error: could not determine current stage id for application.",
            file=sys.stderr,
        )
        sys.exit(1)

    body = {"from_stage_id": int(from_stage_id)}

    # Need custom request for On-Behalf-Of header
    url = f"{BASE_URL}/applications/{args.application_id}/advance"
    req_headers = {
        "Authorization": _auth_header(),
        "Content-Type": "application/json",
        "On-Behalf-Of": str(args.user_id),
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers=req_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            data = json.loads(raw) if raw else {"success": True}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"HTTP {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)
    out(data, args.pretty)


def cmd_reject(args):
    body = {}
    if args.rejection_reason_id:
        body["rejection_reason_id"] = int(args.rejection_reason_id)
    if args.notes:
        body["notes"] = args.notes

    url = f"{BASE_URL}/applications/{args.application_id}/reject"
    req_headers = {
        "Authorization": _auth_header(),
        "Content-Type": "application/json",
        "On-Behalf-Of": str(args.user_id),
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers=req_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            data = json.loads(raw) if raw else {"success": True}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"HTTP {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)
    out(data, args.pretty)


def cmd_update_candidate(args):
    body = {}
    if args.first_name:
        body["first_name"] = args.first_name
    if args.last_name:
        body["last_name"] = args.last_name
    if args.company:
        body["company"] = args.company
    if args.title:
        body["title"] = args.title
    if args.tags:
        body["tags"] = args.tags

    if not body:
        print("Error: provide at least one field to update.", file=sys.stderr)
        sys.exit(1)

    data, _ = api_patch(f"candidates/{args.id}", body)
    out(data, args.pretty)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Greenhouse Harvest API client (stdlib, no deps)"
    )
    parser.add_argument(
        "--pretty", "-p", action="store_true", help="Pretty-print JSON"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Helper to add --all flag to list commands
    def add_all_flag(p):
        p.add_argument(
            "--all", action="store_true",
            help="Auto-paginate and return all results",
        )
        return p

    # -- Read commands --
    p = add_all_flag(sub.add_parser("jobs", help="List jobs"))
    p.add_argument("--status", choices=["open", "closed", "draft"])
    p.add_argument("--department-id", type=int)
    p.add_argument("--limit", "-l", type=int)

    p = sub.add_parser("job", help="Get single job details")
    p.add_argument("id", type=int, help="Job ID")

    p = add_all_flag(sub.add_parser("candidates", help="List candidates"))
    p.add_argument("--job-id", type=int)
    p.add_argument("--created-after", help="ISO 8601 datetime")
    p.add_argument("--updated-after", help="ISO 8601 datetime")
    p.add_argument("--limit", "-l", type=int)

    p = sub.add_parser("candidate", help="Get single candidate")
    p.add_argument("id", type=int, help="Candidate ID")

    p = add_all_flag(sub.add_parser("applications", help="List applications"))
    p.add_argument("--job-id", type=int)
    p.add_argument("--status", choices=["active", "rejected", "hired"])
    p.add_argument("--created-after", help="ISO 8601 datetime")
    p.add_argument("--updated-after", help="ISO 8601 datetime")
    p.add_argument("--limit", "-l", type=int)

    p = sub.add_parser("application", help="Get single application")
    p.add_argument("id", type=int, help="Application ID")

    p = sub.add_parser("stages", help="List stages for a job")
    p.add_argument("job_id", type=int, help="Job ID")

    p = add_all_flag(sub.add_parser("scorecards", help="List scorecards for an application"))
    p.add_argument("application_id", type=int, help="Application ID")

    p = add_all_flag(sub.add_parser("offers", help="List offers for an application"))
    p.add_argument("application_id", type=int, help="Application ID")

    add_all_flag(sub.add_parser("departments", help="List departments"))
    add_all_flag(sub.add_parser("offices", help="List offices"))

    p = add_all_flag(sub.add_parser("users", help="List users"))
    p.add_argument("--limit", "-l", type=int)

    p = sub.add_parser("user", help="Get single user")
    p.add_argument("id", type=int, help="User ID")

    add_all_flag(sub.add_parser("sources", help="List sources"))
    add_all_flag(sub.add_parser("rejection-reasons", help="List rejection reasons"))

    p = sub.add_parser("activity", help="Get activity feed for candidate")
    p.add_argument("candidate_id", type=int, help="Candidate ID")

    p = add_all_flag(sub.add_parser("scheduled-interviews", help="List scheduled interviews"))
    p.add_argument("application_id", type=int, help="Application ID")

    p = sub.add_parser("attachments", help="List attachments (resumes, etc.) for a candidate")
    p.add_argument("candidate_id", type=int, help="Candidate ID")

    p = sub.add_parser("download-attachment", help="Download an attachment file by URL")
    p.add_argument("url", help="Attachment URL from Greenhouse")
    p.add_argument("--output", "-o", help="Output filename (auto-detected if omitted)")

    p = sub.add_parser("custom-fields", help="List custom fields")
    p.add_argument("--field-type", choices=["application", "offer", "candidate", "job", "opening"])

    p = sub.add_parser("application-detail", help="Full application with candidate, attachments, and custom question answers")
    p.add_argument("id", type=int, help="Application ID")

    # -- Write commands --
    p = sub.add_parser("add-note", help="Add note to candidate")
    p.add_argument("--candidate-id", required=True, type=int)
    p.add_argument("--body", "-b", required=True, help="Note body")
    p.add_argument("--user-id", required=True, type=int, help="Acting user ID")

    p = sub.add_parser("add-candidate", help="Add a new candidate")
    p.add_argument("--first-name", required=True)
    p.add_argument("--last-name", required=True)
    p.add_argument("--company")
    p.add_argument("--title")
    p.add_argument("--phone")
    p.add_argument("--email")
    p.add_argument("--website")
    p.add_argument("--social")
    p.add_argument("--tags", nargs="+")

    p = sub.add_parser("advance", help="Advance application to next stage")
    p.add_argument("--application-id", required=True, type=int)
    p.add_argument("--user-id", required=True, type=int, help="On-Behalf-Of user ID")

    p = sub.add_parser("reject", help="Reject an application")
    p.add_argument("--application-id", required=True, type=int)
    p.add_argument("--user-id", required=True, type=int, help="On-Behalf-Of user ID")
    p.add_argument("--rejection-reason-id", type=int)
    p.add_argument("--notes")

    p = sub.add_parser("update-candidate", help="Update a candidate")
    p.add_argument("id", type=int, help="Candidate ID")
    p.add_argument("--first-name")
    p.add_argument("--last-name")
    p.add_argument("--company")
    p.add_argument("--title")
    p.add_argument("--tags", nargs="+")

    args = parser.parse_args()

    cmd_map = {
        "jobs": cmd_jobs,
        "job": cmd_job,
        "candidates": cmd_candidates,
        "candidate": cmd_candidate,
        "applications": cmd_applications,
        "application": cmd_application,
        "stages": cmd_stages,
        "scorecards": cmd_scorecards,
        "offers": cmd_offers,
        "departments": cmd_departments,
        "offices": cmd_offices,
        "users": cmd_users,
        "user": cmd_user,
        "sources": cmd_sources,
        "rejection-reasons": cmd_rejection_reasons,
        "activity": cmd_activity,
        "scheduled-interviews": cmd_scheduled_interviews,
        "attachments": cmd_attachments,
        "download-attachment": cmd_download_attachment,
        "custom-fields": cmd_custom_fields,
        "application-detail": cmd_application_detail,
        "add-note": cmd_add_note,
        "add-candidate": cmd_add_candidate,
        "advance": cmd_advance,
        "reject": cmd_reject,
        "update-candidate": cmd_update_candidate,
    }
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
