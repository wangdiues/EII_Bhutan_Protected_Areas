# Security Policy

## Reporting

Please do not open a public issue for suspected secrets, credentials, or data
exposure. Report privately to the repository maintainer.

## Secrets

Do not commit Google Earth Engine service-account keys, `.env` files, access
tokens, or local machine paths. Use:

- `EII_GEE_SERVICE_ACCOUNT`
- `EII_GEE_KEY_PATH`

Real credential JSON files belong outside Git or under
`06_Google_application_credentials/`, which is ignored except for `.gitkeep`
and `fake_service_account.example.json.template`.

## Data Policy

Raw geospatial inputs, processed rasters/vectors, generated manuscript packages,
and submission correspondence are intentionally excluded from Git. Public
releases should use documented regeneration steps or external research-data
archives for large datasets.

## Dependency Security

Dependencies are declared in `requirements.txt`. Before public releases, run:

```powershell
python -m pip install --upgrade pip
python -m pip install pip-audit
python -m pip_audit -r requirements.txt
```

GitHub Dependabot is configured to monitor Python dependencies after push.
