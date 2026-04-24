# Contributing

## Repository Hygiene

- Do not commit credentials, virtual environments, cache directories, or run logs.
- Keep Google Earth Engine credentials in environment variables or a local JSON key ignored by Git.
- Treat `01_data/01_raw/` as source data and `03_results/` as generated analysis output; document any manual edits.
- Update `README.md`, `02_scripts/run_order.yaml`, and `00_admin/CHANGELOG.md` when pipeline behavior changes.

## Validation Before Sharing

Run these checks from the project root:

```bash
python -m py_compile 02_scripts/run_all.py
python 02_scripts/run_all.py --dry-run
python test_eii_public.py
```

The GEE smoke test requires network access and valid credentials. The dry-run must not create files.
