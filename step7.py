"""
AraContract Phase 7 - Final Dataset Plotting
Generates plots from Step 5 outputs (merged dataset and splits).

Usage:
    python step7.py --input-dir claude
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


def load_split_counts(input_dir: Path) -> pd.Series | None:
    split_files = {
        "train": input_dir / "aracontract_train.jsonl",
        "val": input_dir / "aracontract_val.jsonl",
        "test": input_dir / "aracontract_test.jsonl",
    }

    counts = {}
    for name, path in split_files.items():
        if path.exists():
            counts[name] = sum(1 for line in path.open(encoding="utf-8") if line.strip())

    if not counts:
        return None

    return pd.Series(counts).reindex(["train", "val", "test"])


def plot_merged(records: list[dict]) -> None:
    if not records:
        print("No records found in merged dataset.")
        return

    df = pd.DataFrame(records)
    if df.empty:
        print("Merged dataset is empty.")
        return

    if "type_clause" in df:
        type_counts = df["type_clause"].value_counts()
        if not type_counts.empty:
            save_bar_plot(
                type_counts,
                "AraContract - Clause Types",
                "aracontract_clause_types.png",
            )

    if "risk_level" in df:
        risk_counts = df["risk_level"].value_counts()
        if not risk_counts.empty:
            save_bar_plot(
                risk_counts,
                "AraContract - Risk Levels",
                "aracontract_risk_levels.png",
                palette=RISK_COLORS,
                order=["high", "medium", "low"],
                sort=False,
            )

    if "language" in df:
        lang_counts = df["language"].value_counts()
        if not lang_counts.empty:
            save_bar_plot(
                lang_counts,
                "AraContract - Languages",
                "aracontract_languages.png",
            )

    if "source" in df:
        source_counts = df["source"].value_counts()
        if not source_counts.empty:
            save_bar_plot(
                source_counts,
                "AraContract - Sources",
                "aracontract_sources.png",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="AraContract plotting")
    parser.add_argument(
        "--input-dir",
        default="claude",
        help="Directory with Step 5 outputs",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    final_path = input_dir / "aracontract_final.jsonl"

    if not final_path.exists():
        raise FileNotFoundError(f"Missing merged dataset: {final_path}")

    records = load_jsonl(final_path)
    plot_merged(records)

    split_counts = load_split_counts(input_dir)
    if split_counts is not None:
        save_bar_plot(
            split_counts,
            "AraContract - Split Sizes",
            "aracontract_split_sizes.png",
            order=["train", "val", "test"],
            sort=False,
        )

    print("Done. Plots saved under the plots/ directory.")


if __name__ == "__main__":
    main()
