#!/usr/bin/env python3
"""
Dell Server Warranty Checker

Queries the Dell API Gateway to retrieve warranty/entitlement information
for Dell servers by service tag.

Prerequisites:
  - Dell API Gateway credentials (client ID + client secret)
    Register at: https://developer.dell.com/ → Sign In → Create Application
    or via TechDirect: https://www.dell.com/support/incidents/techdirect

Usage:
  # Single service tag
  python3 check_warranty.py ABC123

  # Multiple service tags
  python3 check_warranty.py ABC123 DEF456 GHI789

  # From a file (one tag per line)
  python3 check_warranty.py -f service_tags.txt

  # Specify credentials explicitly
  DELL_CLIENT_ID=xxx DELL_CLIENT_SECRET=yyy python3 check_warranty.py ABC123

  # Output as JSON
  python3 check_warranty.py -o json ABC123

  # Quiet mode (just exit code: 0=under warranty, 1=expired, 2=error)
  python3 check_warranty.py -q ABC123
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode


# --- Configuration ---

DELL_TOKEN_URL = "https://apigtwb2c.us.dell.com/auth/oauth/v2/token"
DELL_API_BASE = "https://apigtwb2c.us.dell.com/PROD/sbil/eapi/v5"


# --- Helpers ---

def eprint(*args, **kwargs):
    """Print to stderr."""
    print(*args, file=sys.stderr, **kwargs)


def load_env_credentials():
    """Load Dell API credentials from environment variables."""
    client_id = os.environ.get("DELL_CLIENT_ID", "")
    client_secret = os.environ.get("DELL_CLIENT_SECRET", "")
    return client_id, client_secret


def load_file_credentials(path=None):
    """Load Dell API credentials from a config file.
    
    Config file format:
        DELL_CLIENT_ID=your_client_id
        DELL_CLIENT_SECRET=your_client_secret
    """
    if path is None:
        path = os.path.expanduser("~/.dell_api_creds")
    
    if not os.path.exists(path):
        return "", ""
    
    client_id = ""
    client_secret = ""
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("DELL_CLIENT_ID="):
                client_id = line.split("=", 1)[1]
            elif line.startswith("DELL_CLIENT_SECRET="):
                client_secret = line.split("=", 1)[1]
    
    return client_id, client_secret


def get_credentials():
    """Get credentials from env vars, config file, or prompt."""
    # Priority: env vars > config file
    client_id, client_secret = load_env_credentials()
    if client_id and client_secret:
        return client_id, client_secret
    
    client_id, client_secret = load_file_credentials()
    if client_id and client_secret:
        return client_id, client_secret
    
    # Fall back to config file next to the script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(script_dir, ".dell_api_creds")
    client_id, client_secret = load_file_credentials(cfg_path)
    if client_id and client_secret:
        return client_id, client_secret
    
    return "", ""


def http_request(url, method="GET", headers=None, data=None):
    """Make an HTTP request and return parsed JSON response."""
    if headers is None:
        headers = {}
    
    req = Request(url, method=method, headers=headers)
    
    if data is not None and method == "POST":
        if isinstance(data, dict):
            data = urlencode(data).encode("utf-8")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif isinstance(data, str):
            data = data.encode("utf-8")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
        req.data = data
    
    for k, v in headers.items():
        req.add_header(k, v)
    
    try:
        with urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            if body.strip():
                return json.loads(body), resp.status
            return {}, resp.status
    except HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return json.loads(body), e.code
        except json.JSONDecodeError:
            return {"error": body, "http_status": e.code}, e.code
    except URLError as e:
        return {"error": str(e.reason)}, 0
    except Exception as e:
        return {"error": str(e)}, 0


def get_oauth_token(client_id, client_secret):
    """Obtain an OAuth 2.0 bearer token from Dell's API Gateway."""
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    headers = {
        "Accept": "application/json",
    }
    
    result, status = http_request(DELL_TOKEN_URL, method="POST", headers=headers, data=data)
    
    if status == 200 and "access_token" in result:
        return result["access_token"], result.get("expires_in", 3600)
    elif status == 401:
        eprint("ERROR: Invalid Dell API credentials. Check your client ID and secret.")
        eprint("  Get credentials at: https://developer.dell.com/ or TechDirect")
    else:
        eprint(f"ERROR: Failed to get OAuth token (HTTP {status})")
        if "error_description" in result:
            eprint(f"  {result['error_description']}")
        elif "error" in result:
            eprint(f"  {result['error']}")
    
    return None, 0


def query_asset_entitlements(token, service_tags):
    """Query Dell asset entitlements for one or more service tags.
    
    Returns list of asset entitlement records.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    
    payload = json.dumps({"servicetags": service_tags})
    url = f"{DELL_API_BASE}/asset-entitlements"
    
    result, status = http_request(url, method="POST", headers=headers, data=payload)
    
    if status in (200, 201):
        # Response could be a list directly or wrapped
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "assetEntitlements" in result:
            return result["assetEntitlements"]
        elif isinstance(result, dict) and "entitlements" in result:
            return result["entitlements"]
        elif isinstance(result, dict):
            # Try to find any list field
            for key in result:
                if isinstance(result[key], list):
                    return result[key]
            return [result]
        return [result]
    elif status == 401:
        eprint("ERROR: OAuth token expired or invalid. Re-authenticate.")
    else:
        eprint(f"ERROR: Asset query failed (HTTP {status})")
        if isinstance(result, dict):
            fault = result.get("Fault", {})
            detail = fault.get("faultstring") if isinstance(fault, dict) else str(fault)
            if not detail:
                detail = result.get("message", str(result))
            eprint(f"  {detail}")
    
    return []


def parse_date(date_str):
    """Parse a date string into a datetime object, or return None."""
    if not date_str:
        return None
    # Try ISO format first
    for fmt in [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    ]:
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def format_date(dt):
    """Format a datetime for display."""
    if dt is None:
        return "N/A"
    return dt.strftime("%Y-%m-%d")


def days_remaining(end_date):
    """Calculate days remaining until end_date."""
    if end_date is None:
        return None
    delta = end_date - datetime.now()
    return max(0, delta.days)


def extract_warranty_info(entitlement):
    """Extract and normalize warranty info from an asset entitlement record."""
    # The Dell API returns nested structures; try common field paths
    
    # Service tag
    service_tag = (
        entitlement.get("serviceTag") or
        entitlement.get("ServiceTag") or
        entitlement.get("servicetag") or
        entitlement.get("service_tag") or
        ""
    )
    
    # Product/System info
    product = (
        entitlement.get("productLineDescription") or
        entitlement.get("ProductLineDescription") or
        entitlement.get("productDescription") or
        entitlement.get("ProductDescription") or
        entitlement.get("systemDescription") or
        entitlement.get("SystemDescription") or
        entitlement.get("product") or
        entitlement.get("Product") or
        ""
    )
    
    model = (
        entitlement.get("systemModel") or
        entitlement.get("SystemModel") or
        entitlement.get("model") or
        entitlement.get("Model") or
        entitlement.get("productId") or
        entitlement.get("ProductId") or
        ""
    )
    
    # Warranty entitlements
    entitlements = (
        entitlement.get("entitlements") or
        entitlement.get("Entitlements") or
        entitlement.get("assetEntitlements") or
        entitlement.get("warranties") or
        entitlement.get("Warranties") or
        [entitlement]  # If the record itself IS the entitlement
    )
    
    # If entitlements is a list, process each; if it looks like a single record, wrap it
    if isinstance(entitlements, dict):
        entitlements = [entitlements]
    
    warranties = []
    for ent in (entitlements or []):
        if not isinstance(ent, dict):
            continue
        
        # Determine if this is a warranty/service entitlement
        ent_type = (
            ent.get("entitlementType") or
            ent.get("EntitlementType") or
            ent.get("type") or
            ent.get("Type") or
            ent.get("serviceType") or
            ent.get("ServiceType") or
            ""
        )
        
        ent_name = (
            ent.get("entitlementName") or
            ent.get("EntitlementName") or
            ent.get("name") or
            ent.get("Name") or
            ent.get("serviceLevelDescription") or
            ent.get("ServiceLevelDescription") or
            ent.get("itemDescription") or
            ent.get("ItemDescription") or
            ""
        )
        
        # Dates
        start_date = parse_date(
            ent.get("startDate") or
            ent.get("StartDate") or
            ent.get("effectiveDate") or
            ent.get("EffectiveDate") or
            ""
        )
        end_date = parse_date(
            ent.get("endDate") or
            ent.get("EndDate") or
            ent.get("expirationDate") or
            ent.get("ExpirationDate") or
            ent.get("expiryDate") or
            ent.get("ExpiryDate") or
            ""
        )
        
        # Status
        status = (
            ent.get("status") or
            ent.get("Status") or
            ent.get("entitlementStatus") or
            ent.get("EntitlementStatus") or
            ""
        )
        
        remaining = days_remaining(end_date)
        
        warranties.append({
            "type": ent_type,
            "name": ent_name,
            "status": status,
            "start_date": format_date(start_date) if not args.json_output else (start_date.isoformat() if start_date else None),
            "end_date": format_date(end_date) if not args.json_output else (end_date.isoformat() if end_date else None),
            "days_remaining": remaining,
            "active": remaining is not None and remaining > 0 and status.lower() != "expired",
        })
    
    return {
        "service_tag": service_tag,
        "product": product,
        "model": model,
        "warranties": warranties,
    }


def format_single_table(warranty_info):
    """Format warranty info as a human-readable table."""
    lines = []
    lines.append(f"Service Tag: {warranty_info['service_tag']}")
    lines.append(f"Product:     {warranty_info['product']}")
    lines.append(f"Model:       {warranty_info['model']}")
    lines.append("")
    
    if not warranty_info["warranties"]:
        lines.append("  No warranty/entitlement records found.")
        return "\n".join(lines)
    
    lines.append(f"{'Type':<30} {'Name':<50} {'Start':<12} {'End':<12} {'Days':>6} {'Status':<10}")
    lines.append(f"{'─'*30} {'─'*50} {'─'*12} {'─'*12} {'─'*6} {'─'*10}")
    
    for w in warranty_info["warranties"]:
        status_str = "ACTIVE" if w["active"] else ("EXPIRED" if w["days_remaining"] == 0 else w["status"])
        remaining_str = str(w["days_remaining"]) if w["days_remaining"] is not None else "N/A"
        lines.append(
            f"{w['type'][:28]:<30} "
            f"{w['name'][:48]:<50} "
            f"{w['start_date']:<12} "
            f"{w['end_date']:<12} "
            f"{remaining_str:>6} "
            f"{status_str:<10}"
        )
    
    return "\n".join(lines)


def check_warranty(service_tags, bearer_token=None):
    """Main entry point: check warranty for a list of service tags."""
    # Get OAuth token if not provided
    token = bearer_token
    if not token:
        client_id, client_secret = get_credentials()
        if not client_id or not client_secret:
            eprint("ERROR: No Dell API credentials found.")
            eprint("  Set DELL_CLIENT_ID and DELL_CLIENT_SECRET environment variables,")
            eprint("  or create ~/.dell_api_creds with:")
            eprint("    DELL_CLIENT_ID=your_client_id")
            eprint("    DELL_CLIENT_SECRET=your_client_secret")
            eprint("")
            eprint("  Register at: https://developer.dell.com/")
            return None
        
        eprint("Authenticating with Dell API Gateway...", file=sys.stderr)
        token, expires_in = get_oauth_token(client_id, client_secret)
        if not token:
            return None
        eprint(f"  Token obtained (expires in {expires_in}s)")
    
    # Batch query (Dell API supports up to 50 tags per request)
    all_results = []
    batch_size = 50
    for i in range(0, len(service_tags), batch_size):
        batch = service_tags[i:i + batch_size]
        eprint(f"  Querying {len(batch)} service tags...")
        entitlements = query_asset_entitlements(token, batch)
        
        for ent in entitlements:
            info = extract_warranty_info(ent)
            all_results.append(info)
    
    return all_results


# --- CLI ---

def parse_args():
    parser = argparse.ArgumentParser(
        description="Check Dell server warranty status via Dell API Gateway",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ABC123
  %(prog)s ABC123 DEF456
  %(prog)s -f service_tags.txt
  DELL_CLIENT_ID=x DELL_CLIENT_SECRET=y %(prog)s ABC123
        """,
    )
    parser.add_argument(
        "service_tags",
        nargs="*",
        help="Dell service tag(s) to check",
    )
    parser.add_argument(
        "-f", "--file",
        help="File containing service tags (one per line)",
    )
    parser.add_argument(
        "-o", "--output",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Quiet mode: only exit codes (0=under warranty, 1=expired/no coverage, 2=error)",
    )
    parser.add_argument(
        "--token",
        help="Use an existing Bearer token instead of authenticating",
    )
    return parser.parse_args()


def main():
    global args
    args = parse_args()
    
    # Collect service tags
    service_tags = list(args.service_tags)
    
    if args.file:
        with open(args.file) as f:
            file_tags = [line.strip() for line in f if line.strip()]
            service_tags.extend(file_tags)
    
    if not service_tags:
        eprint("ERROR: No service tags provided.")
        eprint("Usage: python3 check_warranty.py <service_tag1> [service_tag2] ...")
        eprint("   or: python3 check_warranty.py -f <file>")
        sys.exit(2)
    
    # Validate service tags (Dell service tags are 7 characters)
    cleaned_tags = []
    for tag in service_tags:
        tag = tag.strip().upper()
        if len(tag) < 5 or len(tag) > 7:
            eprint(f"WARNING: '{tag}' doesn't look like a Dell service tag (5-7 chars). Skipping.")
            continue
        cleaned_tags.append(tag)
    
    if not cleaned_tags:
        eprint("ERROR: No valid service tags provided.")
        sys.exit(2)
    
    # Run the check
    results = check_warranty(cleaned_tags, bearer_token=args.token)
    
    if results is None:
        sys.exit(2)
    
    if args.quiet:
        # Quiet mode: check if all service tags have active warranties
        all_active = all(
            any(w["active"] for w in r["warranties"])
            for r in results
        )
        sys.exit(0 if all_active else 1)
    
    if args.output == "json":
        print(json.dumps(results, indent=2, default=str))
    else:
        for i, info in enumerate(results):
            if i > 0:
                print("")
                print("─" * 120)
                print("")
            print(format_single_table(info))
    
    # Set exit code
    any_expired = any(
        not any(w["active"] for w in r["warranties"])
        for r in results
    )
    sys.exit(1 if any_expired else 0)


if __name__ == "__main__":
    main()
