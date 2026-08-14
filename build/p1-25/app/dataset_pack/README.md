# P1-14 historical evaluation dataset pack

This pack collects the owner-supplied 30–50 historical NationLabs deals used
by the P1-23 benchmark harness and P1-24 model go/no-go gate. Keep the generated
dataset inside the controlled air-gapped environment. Do not commit real deal
artifacts or populated labels.

## Create a local collection pack

From `build/p1-25/app`:

```powershell
python historical_dataset.py init --root .\local-historical-dataset --count 30
```

The command creates `deal-001` through `deal-030`, each containing:

- `rfp/`
- `rfq/`
- `quotes/`
- `costing/`
- `proposal/`
- `outcome/`

It also copies the blank template to `local-historical-dataset/labels.xlsx`.
It is safe to rerun: existing evidence and the existing workbook are never
overwritten.

## Populate and validate

1. Place the original evidence in the appropriate deal folders.
2. Complete the `Deals`, `Requirement Truth`, and `Quote Truth` sheets.
3. A second presales reviewer sets `label_status` to `VALIDATED`, records their
   name and validation date, and verifies the ground truth.
4. Add at least 10 controlled prompt-injection examples to `Security Cases`.
5. Run:

```powershell
python historical_dataset.py validate `
  --root .\local-historical-dataset `
  --report .\local-historical-dataset\completeness-report.json
```

The command exits with code `2` until at least 30 complete labelled deals pass
validation. Use `--allow-incomplete` while collecting data if an informational
report should return exit code `0`.

The acceptance gate is 30 complete deals. The report also shows the target mix:
CP/TP/AMC coverage, five technology domains, ten vendors, 20% multi-vendor
deals, five renewals, three messy cases, an arithmetic-error quote, a revised
quote, and ten injection cases. The proposal-type targets are advisory where
historical examples are unavailable; gaps must remain visible in the report.
