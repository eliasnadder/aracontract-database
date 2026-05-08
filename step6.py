"""
AraContract Phase 6 - Syrian Contract Plotting
Generates plots from:
  - arabic_phase3.jsonl (clause-level)
  - manifest.json (contract-level)

Usage:
    python step6.py \
        --input arabic_phase3.jsonl \
        --manifest scrap/contracts_dataset/manifest.json
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from plot_utils import RISK_COLORS, save_bar_plot


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def plot_clause_level(records: list[dict]) -> None:
    if not records:
        print("No clause records found. Skipping clause-level plots.")
        return

    df = pd.DataFrame(records)
    if df.empty:
        print("No clause records found. Skipping clause-level plots.")
        return

    if "type_clause" in df:
        type_counts = df["type_clause"].value_counts()
        if not type_counts.empty:
            save_bar_plot(
                type_counts,
                "Syrian Clauses - Clause Types",
                "syrian_clause_types.png",
            )

    if "risk_level" in df:
        risk_counts = df["risk_level"].value_counts()
        if not risk_counts.empty:
            save_bar_plot(
                risk_counts,
                "Syrian Clauses - Risk Levels",
                "syrian_risk_levels.png",
                palette=RISK_COLORS,
                order=["high", "medium", "low"],
                sort=False,
            )

    categories = []
    for rec in records:
        metadata = rec.get("metadata") or {}
        categories.append(metadata.get("category", "unknown"))

    category_counts = pd.Series(categories).value_counts()
    if not category_counts.empty:
        save_bar_plot(
            category_counts,
            "Syrian Clauses - Categories",
            "syrian_clause_categories.png",
        )


def plot_contract_level(manifest_path: Path | None) -> None:
    if not manifest_path or not manifest_path.exists():
        print("Manifest not found. Skipping contract-level plots.")
        return

    with manifest_path.open(encoding="utf-8") as f:
        manifest = json.load(f)

    categories = manifest.get("categories", {})
    if not categories:
        print("Manifest has no categories. Skipping contract-level plots.")
        return

    filtered = {k: v for k, v in categories.items() if v}
    if not filtered:
        print("Manifest categories are empty. Skipping contract-level plots.")
        return

    category_counts = pd.Series(filtered).sort_values(ascending=False)
    save_bar_plot(
        category_counts,
        "Syrian Contracts - Contracts per Category",
        "syrian_contract_categories.png",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Syrian contract plotting")
    parser.add_argument(
        "--input",
        default="arabic_phase3.jsonl",
        help="Path to arabic_phase3.jsonl",
    )
    parser.add_argument(
        "--manifest",
        default="scrap/contracts_dataset/manifest.json",
        help="Path to manifest.json",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input JSONL not found: {input_path}")

    records = load_jsonl(input_path)
    plot_clause_level(records)
    plot_contract_level(Path(args.manifest) if args.manifest else None)

    print("Done. Plots saved under the plots/ directory.")


if __name__ == "__main__":
    main()
