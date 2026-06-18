"""Isolation test — happy path.

Mirrors what a model-generated `produce` script does: read the staged input,
compute deterministically, write the output document AND the required
summary.json (the trust seal verified against the source). Run inside the
sandbox with the exact flag set run_sandbox() will generate.
"""

import json
import pathlib

import pandas as pd

OUT = pathlib.Path("/workspace/output")

df = pd.read_csv("/workspace/input/sample.csv")
total = float(df["sales"].sum())

with pd.ExcelWriter(OUT / "report.xlsx", engine="xlsxwriter") as xw:
    df.to_excel(xw, sheet_name="sales", index=False)

# Every key figure the script computed — the verifier checks this against the source.
(OUT / "summary.json").write_text(json.dumps({
    "row_count": int(len(df)),
    "total_sales": total,
    "by_region": df.set_index("region")["sales"].astype(float).to_dict(),
}))

print("wrote report.xlsx + summary.json; total =", total)
