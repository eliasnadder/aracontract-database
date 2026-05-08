"""
AraContract Phase 4 - Final Dataset Merge
Combines:
  - cuad_phase2_fixed.jsonl  (4,777 English clauses, CUAD + UNFAIR-ToS risk)
  - arabic_phase3.jsonl       (731 Arabic clauses, Syrian contracts)

Outputs:
  - aracontract_final.jsonl        (all records, normalized schema)
  - aracontract_train.jsonl
  - aracontract_val.jsonl
  - aracontract_test.jsonl
  - aracontract_stats.json

Usage:
    python phase4_merge.py \
        --cuad   claude/cuad_phase2_fixed.jsonl \
        --arabic arabic_phase3.jsonl \
        --outdir claude/
"""

import json
import random
import argparse
import hashlib
from pathlib import Path
from collections import Counter

# ─── Config ──────────────────────────────────────────────────────────────────
SPLIT_RATIOS = (0.70, 0.15, 0.15)   # train / val / test
MAX_CLASS_PCT = 0.35                  # hard cap per class
MIN_TEXT_LEN = 30                    # chars
JACCARD_THRESH = 0.85                  # dedup threshold
SEED = 42

VALID_TYPES = {
    "payment_financial", "duration_expiration", "termination",
    "penalties_damages", "dispute_resolution",
    "general_provisions", "party_obligations"
}
VALID_RISKS = {"high", "medium", "low"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def uid(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def shingles(text: str, k: int = 4) -> set:
    t = text.replace(" ", "")
    return {t[i:i+k] for i in range(len(t) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def normalize_cuad(rec: dict) -> dict | None:
    # Try all possible text field names
    text = (rec.get("text") or rec.get("clause") or
            rec.get("text_clause") or "").strip()
    if len(text) < MIN_TEXT_LEN:
        return None

    # Try all possible type field names
    ctype = (rec.get("type_clause") or rec.get("label") or
             rec.get("clause_type") or "")
    if ctype not in VALID_TYPES:
        return None

    risk = rec.get("risk_level", "low")
    if risk not in VALID_RISKS:
        risk = "low"

    return {
        "text":        text,
        "type_clause": ctype,
        "risk_level":  risk,
        "risk_reason": rec.get("risk_reason", ""),
        "source":      rec.get("source", "cuad"),
        "language":    rec.get("language", "en"),
    }


def normalize_arabic(rec: dict) -> dict | None:
    """Normalize an Arabic Phase-3 record to AraContract schema."""
    text = str(rec.get("text", "")).strip()
    if len(text) < MIN_TEXT_LEN:
        return None

    ctype = rec.get("type_clause", "")
    if ctype not in VALID_TYPES:
        return None

    risk = rec.get("risk_level", "low")
    if risk not in VALID_RISKS:
        risk = "low"

    return {
        "text":         text,
        "type_clause":  ctype,
        "risk_level":   risk,
        "risk_reason":  rec.get("risk_reason", ""),
        "source":       rec.get("source", "syrian-lawyer"),
        "language":     "ar",
    }


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


# ─── Deduplication ───────────────────────────────────────────────────────────

def deduplicate(records: list[dict]) -> list[dict]:
    """Exact hash dedup first, then Jaccard near-dedup."""
    print("  Running deduplication...")

    # 1. Exact dedup
    seen_hash = set()
    unique = []
    for r in records:
        h = uid(r["text"])
        if h not in seen_hash:
            seen_hash.add(h)
            unique.append(r)

    removed_exact = len(records) - len(unique)

    # 2. Jaccard near-dedup (bucket by language to avoid cross-lang false positives)
    # Group into buckets of ~200 for efficiency
    final = []
    shingle_cache = []

    for r in unique:
        s = shingles(r["text"])
        duplicate = False
        # Only compare against last 300 (sliding window)
        for prev_s in shingle_cache[-300:]:
            if jaccard(s, prev_s) >= JACCARD_THRESH:
                duplicate = True
                break
        if not duplicate:
            final.append(r)
            shingle_cache.append(s)

    removed_jaccard = len(unique) - len(final)
    print(f"  Removed exact duplicates : {removed_exact}")
    print(f"  Removed near-duplicates  : {removed_jaccard}")
    return final


# ─── Class Balance Check ─────────────────────────────────────────────────────

def balance_report(records: list[dict], label: str = ""):
    total = len(records)
    type_counts = Counter(r["type_clause"] for r in records)
    risk_counts = Counter(r["risk_level"] for r in records)
    lang_counts = Counter(r["language"] for r in records)

    print(f"\n{'─'*52}")
    print(f"  {label}  ({total} records)")
    print(f"{'─'*52}")

    print("  Clause types:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        bar = "█" * int(30 * c / total)
        flag = " ⚠ OVER CAP" if c/total > MAX_CLASS_PCT else ""
        print(f"    {t:<30} {c:>5}  {100*c/total:>5.1f}%  {bar}{flag}")

    print("\n  Risk levels:")
    for t, c in risk_counts.most_common():
        print(f"    {t:<10} {c:>5}  ({100*c/total:.1f}%)")

    print("\n  Languages:")
    for t, c in lang_counts.most_common():
        print(f"    {t:<6} {c:>5}  ({100*c/total:.1f}%)")

    return type_counts, risk_counts


# ─── Stratified Split ────────────────────────────────────────────────────────

def stratified_split(records: list[dict], ratios: tuple) -> tuple:
    """
    Split preserving type_clause × language distribution.
    Returns (train, val, test).
    """
    from collections import defaultdict
    rng = random.Random(SEED)

    # Group by (type_clause, language)
    groups = defaultdict(list)
    for r in records:
        key = (r["type_clause"], r["language"])
        groups[key].append(r)

    train, val, test = [], [], []
    tr, vr, ter = ratios

    for key, items in groups.items():
        rng.shuffle(items)
        n = len(items)
        n_train = max(1, int(n * tr))
        n_val = max(0, int(n * vr))
        # rest goes to test

        train += items[:n_train]
        val += items[n_train:n_train + n_val]
        test += items[n_train + n_val:]

    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)

    return train, val, test


# ─── Write JSONL ─────────────────────────────────────────────────────────────

def write_jsonl(records: list[dict], path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  ✓ Written: {path}  ({len(records)} records)")


# ─── Main ────────────────────────────────────────────────────────────────────

def main(cuad_path: str, arabic_path: str, outdir: str):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 52)
    print("AraContract Phase 4 — Final Merge")
    print("=" * 52)

    # ── Load & normalize ──────────────────────────────────
    print(f"\n[1/5] Loading CUAD data: {cuad_path}")
    cuad_raw = load_jsonl(cuad_path)
    cuad_records = [normalize_cuad(r) for r in cuad_raw]
    cuad_records = [r for r in cuad_records if r is not None]
    print(
        f"  Loaded {len(cuad_raw)} → kept {len(cuad_records)} after normalization")

    print(f"\n[2/5] Loading Arabic data: {arabic_path}")
    arabic_raw = load_jsonl(arabic_path)
    arabic_records = [normalize_arabic(r) for r in arabic_raw]
    arabic_records = [r for r in arabic_records if r is not None]
    print(
        f"  Loaded {len(arabic_raw)} → kept {len(arabic_records)} after normalization")

    # ── Merge ─────────────────────────────────────────────
    print(f"\n[3/5] Merging datasets")
    all_records = cuad_records + arabic_records
    print(f"  Total before dedup: {len(all_records)}")
    all_records = deduplicate(all_records)
    print(f"  Total after dedup : {len(all_records)}")

    balance_report(all_records, "MERGED DATASET")

    # ── Write full dataset ─────────────────────────────────
    print(f"\n[4/5] Writing final dataset")
    write_jsonl(all_records, outdir / "aracontract_final.jsonl")

    # ── Split ─────────────────────────────────────────────
    print(f"\n[5/5] Stratified 70/15/15 split")
    train, val, test = stratified_split(all_records, SPLIT_RATIOS)

    write_jsonl(train, outdir / "aracontract_train.jsonl")
    write_jsonl(val,   outdir / "aracontract_val.jsonl")
    write_jsonl(test,  outdir / "aracontract_test.jsonl")

    # ── Summary stats ─────────────────────────────────────
    type_counts, risk_counts = balance_report(train, "TRAIN SPLIT")

    stats = {
        "total":   len(all_records),
        "train":   len(train),
        "val":     len(val),
        "test":    len(test),
        "splits":  {"train": 0.70, "val": 0.15, "test": 0.15},
        # "languages": dict(Counter(r["language"] for r in all_records)),
        "clause_types": dict(Counter(r["type_clause"] for r in all_records)),
        "risk_levels": dict(Counter(r["risk_level"] for r in all_records)),
        # "sources": {
        #     "cuad_en": len(cuad_records),
        #     "syrian_ar": len(arabic_records),
        # },
    }

    stats_path = outdir / "aracontract_stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n  ✓ Stats written: {stats_path}")

    print("\n" + "=" * 52)
    print("  Phase 4 complete.")
    print(f"  Final corpus: {stats['total']} clauses")
    print(
        f"  Train: {stats['train']}  Val: {stats['val']}  Test: {stats['test']}")
    print("=" * 52)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cuad",    required=True,
                        help="Path to cuad_phase2.jsonl")
    parser.add_argument("--arabic",  required=True,
                        help="Path to arabic_phase3.jsonl")
    parser.add_argument("--outdir",  default="dataset/",
                        help="Output directory")
    args = parser.parse_args()

    main(args.cuad, args.arabic, args.outdir)
