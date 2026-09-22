"""Generate the synthetic example results file committed as examples/.

Deterministic — no randomness. Shape it after a real pilot: an invoice-routing
agent on 60 cases, with the low-confidence cases being the ones it got wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

VENDORS = ["Acme Supply", "Borealis Ltd", "Cinder Works", "Delta Freight",
           "Everline", "Fairhaven Co", "Granite Row", "Hollow Point"]

rows = []
wrong = {5, 12, 19, 27, 33, 41, 48, 52, 57}      # 51 of 60 pass; 9 carry low confidence
for i in range(60):
    vendor = VENDORS[i % len(VENDORS)]
    passed = i not in wrong
    output = vendor if passed else VENDORS[(i + 3) % len(VENDORS)]
    detail = "" if passed else "normalized the trading name to its parent entity"
    rows.append({
        "id": f"inv-{i + 1:03d}",
        "passed": passed,
        "confidence": 0.42 if not passed else (0.86 if i % 7 == 0 else 0.97),
        "expected": vendor,
        "output": output,
        "detail": detail,
        "metadata": {"document": f"batch-{(i // 10) + 1}"},
    })

dest = Path(__file__).resolve().parents[1] / "examples" / "invoice_routing.jsonl"
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
print(f"wrote {dest} ({len(rows)} cases, {sum(1 for r in rows if r['passed'])} passed)")