# Dell Warranty Check

A Python CLI tool to query Dell server warranty status using the Dell API Gateway.

## Prerequisites

### Dell API Credentials

You need a Dell API Gateway client ID and client secret.

**Option 1: Dell Developer Portal**
1. Go to [developer.dell.com](https://developer.dell.com/)
2. Sign in (create an account if needed)
3. Create an application to get API credentials
4. Request access to the **Asset Entitlements** API

**Option 2: TechDirect**
1. Go to [TechDirect](https://www.dell.com/support/incidents/techdirect)
2. Navigate to API management
3. Generate API credentials

### Provide Credentials to the Script

**Environment variables:**
```bash
export DELL_CLIENT_ID="your_client_id"
export DELL_CLIENT_SECRET="your_client_secret"
```

**Config file:**
Create `~/.dell_api_creds` or `.dell_api_creds` next to the script:
```
DELL_CLIENT_ID=your_client_id
DELL_CLIENT_SECRET=your_client_secret
```

## Usage

```bash
# Single service tag
python3 check_warranty.py ABC123

# Multiple service tags
python3 check_warranty.py ABC123 DEF456 GHI789

# From a file (one tag per line)
python3 check_warranty.py -f service_tags.txt

# JSON output
python3 check_warranty.py -o json ABC123

# Quiet mode (exit code only)
python3 check_warranty.py -q ABC123
```

## Output

**Table format (default):**
```
Service Tag: ABC123
Product:     PowerEdge R750
Model:       210-ABCD

Type                           Name                                               Start        End           Days Status
────────────────────────────── ────────────────────────────────────────────────── ──────────── ──────────── ───── ──────────
Next Business Day              Dell ProSupport NBD                                2023-01-15   2026-01-15    225  ACTIVE
```

**JSON format:**
```json
[
  {
    "service_tag": "ABC123",
    "product": "PowerEdge R750",
    "model": "210-ABCD",
    "warranties": [
      {
        "type": "Next Business Day",
        "name": "Dell ProSupport NBD",
        "status": "ACTIVE",
        "start_date": "2023-01-15",
        "end_date": "2026-01-15",
        "days_remaining": 225,
        "active": true
      }
    ]
  }
]
```

## Exit Codes

| Code | Meaning                    |
|------|----------------------------|
| 0    | All service tags have active warranty coverage |
| 1    | One or more service tags have expired/no coverage |
| 2    | Error (no credentials, invalid tags, API error) |

## API Details

- **Auth Endpoint:** `POST https://apigtwb2c.us.dell.com/auth/oauth/v2/token`
  - OAuth 2.0 client credentials flow
- **Asset API:** `POST https://apigtwb2c.us.dell.com/PROD/sbil/eapi/v5/asset-entitlements`
  - Accepts up to 50 service tags per request
- Requires a Dell API Gateway account

## License

MIT
