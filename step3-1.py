"""
fix_risk_reason.py
------------------
Assigns Arabic-style risk_reason to CUAD records based on:
  1. risk_level + clause_type combo (base mapping)
  2. English keyword patterns (more specific override)
"""

import json
import re
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# 1. KEYWORD-BASED SPECIFIC OVERRIDES (checked first)
#    Each entry: (risk_level_match, regex_pattern, arabic_reason)
# ─────────────────────────────────────────────────────────────────────────────
KEYWORD_RULES = [
    # HIGH risk – specific patterns
        ("high", r"\bautomatic(ally)?\b.*\b(terminat|cancel|void|expir)",
         "Automatic termination - high risk"),
    ("high", r"\b(terminat|cancel|void)\b.*\bautomatically\b",
         "Automatic termination - high risk"),
    ("high", r"\bwithout\s+(notice|warning|cure|demand)",
         "Condition without notice - high risk"),
    ("high", r"\bno\s+(notice|cure\s+period|prior\s+notice)",
         "Condition without notice - high risk"),
    ("high", r"\b(insolvency|bankrupt|insolvent|liquidat|receivership)",
         "Insolvency or bankruptcy - high risk"),
    ("high", r"\b(loss|destruction|theft|damage).{0,50}(liable|liability|responsible|bear)",
         "Loss warranty - high risk"),
    ("high", r"\b(bear|assume).{0,50}(risk|loss|damage|destruction)",
         "Loss warranty - high risk"),
    ("high", r"\b(criminal|penal|prosecut|felony|misdemeanor)",
         "Criminal liability - high risk"),
    ("high", r"\bper\s+(day|diem).{0,40}(penalty|fee|charge|liquidated)",
         "Daily penalty - high risk"),
    ("high", r"\bliquidated\s+damages?\b",
         "Daily penalty - high risk"),
    ("high", r"\bchange\s+of\s+control\b",
         "Change of control clause - high risk"),
    ("high", r"\b(unlimited|uncapped)\s+(liabilit|damages?)",
         "Unlimited liability - high risk"),
    ("high", r"\bindemnif",
         "Indemnification obligation - high risk"),
    ("high", r"\b(solely|exclusively)\s+responsible",
         "Sole responsibility - high risk"),

    # MEDIUM risk – specific patterns
    ("medium", r"\b(penalty|penalt|fine|forfeit).{0,40}(paid|pay|amount)",
         "Penalty or compensation - medium risk"),
    ("medium", r"\b(compensat|reimburse|damages?)\b",
         "Penalty or compensation - medium risk"),
    ("medium", r"\b(interest|rate).{0,30}(\d+\s*%|percent)",
         "Financial interest - medium risk"),
    ("medium", r"\b(mortgage|lien|pledge|security\s+interest|collateral|escrow)",
         "Collateral guarantee - medium risk"),
    ("medium", r"\bassign(ment)?\b",
         "Waiver of rights - medium risk"),
    ("medium", r"\b(waive|waiver|relinquish|forfeit)\b",
         "Waiver of rights - medium risk"),
    ("medium", r"\b(due\s+date|maturity|deadline|no\s+later\s+than)",
         "Deadline clause - medium risk"),
    ("medium", r"\b(minimum|floor)\s+(commit|purchase|order|amount|volume)",
         "Minimum commitment - medium risk"),
    ("medium", r"\brevenue\s+shar|profit\s+shar|royalt",
         "Profit sharing - medium risk"),

    # LOW risk – declaratory / procedural
    ("low", r"\b(govern(ing)?\s+law|jurisdiction|dispute\s+resolution|arbitrat)",
         "Dispute resolution clause - low risk"),
    ("low", r"\b(notice|notification).{0,40}(written|email|mail|deliver)",
         "Notice clause - low risk"),
    ("low", r"\b(effective\s+date|commencement\s+date|term\s+of\s+this\s+agreement)",
         "General clause - low risk"),
    ("low", r"\b(entire\s+agreement|merger\s+clause|integration)",
         "Procedural clause - low risk"),
    ("low", r"\b(severab|herein|hereunder|hereof|hereto|whereas)\b",
         "Procedural clause - low risk"),
]

# ─────────────────────────────────────────────────────────────────────────────
# 2. BASE MAPPING: clause_type + risk_level → arabic reason (fallback)
# ─────────────────────────────────────────────────────────────────────────────
BASE_MAP = {
    # penalties_damages
        ("penalties_damages", "high"):   "Penalty or compensation - high risk",
        ("penalties_damages", "medium"): "Penalty or compensation - medium risk",
        ("penalties_damages", "low"):    "General clause - low risk",

    # termination
    ("termination", "high"):   "Automatic termination - high risk",
    ("termination", "medium"): "Conditional termination - medium risk",
    ("termination", "low"):    "Termination clause - low risk",

    # payment_financial
    ("payment_financial", "high"):   "High financial obligation - high risk",
    ("payment_financial", "medium"): "Financial clause - medium risk",
    ("payment_financial", "low"):    "General financial clause - low risk",

    # duration_expiration
    ("duration_expiration", "high"):   "Critical duration clause - high risk",
    ("duration_expiration", "medium"): "Deadline clause - medium risk",
    ("duration_expiration", "low"):    "Contract duration clause - low risk",

    # party_obligations
    ("party_obligations", "high"):   "Strict obligation - high risk",
    ("party_obligations", "medium"): "Conditional obligation - medium risk",
    ("party_obligations", "low"):    "General obligation - low risk",

    # dispute_resolution
    ("dispute_resolution", "high"):   "Unbalanced settlement clause - high risk",
    ("dispute_resolution", "medium"): "Dispute settlement clause - medium risk",
    ("dispute_resolution", "low"):    "Dispute settlement clause - low risk",

    # general_provisions
    ("general_provisions", "high"):   "General clause - high risk",
    ("general_provisions", "medium"): "General clause - medium risk",
    ("general_provisions", "low"):    "Procedural clause - low risk",
}

ULTIMATE_FALLBACK = {
    "high":   "High-risk clause",
    "medium": "Medium-risk clause",
    "low":    "General clause - low risk",
}


def assign_reason(text: str, clause_type: str, risk_level: str) -> str:
    text_lower = text.lower()

    # 1. Try keyword rules (only if risk_level matches)
    for expected_level, pattern, reason in KEYWORD_RULES:
        if expected_level == risk_level:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return reason

    # 2. Base map
    key = (clause_type, risk_level)
    if key in BASE_MAP:
        return BASE_MAP[key]

    # 3. Ultimate fallback
    return ULTIMATE_FALLBACK.get(risk_level, "Normal clause - low risk")


# ─────────────────────────────────────────────────────────────────────────────
# 3. PROCESS FILE
# ─────────────────────────────────────────────────────────────────────────────

def run(input_path: str, output_path: str):
    records = [json.loads(l) for l in open(input_path, encoding="utf-8")]
    print(f"Read {len(records)} records from {input_path}")

    changed = 0
    from collections import Counter
    reason_counter = Counter()

    for r in records:
        reason = assign_reason(r["text"], r["clause_type"], r["risk_level"])
        if r.get("risk_reason") != reason:
            changed += 1
        r["risk_reason"] = reason
        reason_counter[reason] += 1

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Updated {changed}/{len(records)} records")
    print(f"Written to {output_path}\n")

    print("Top risk_reason values:")
    for reason, count in reason_counter.most_common(20):
        print(f"  {count:4d}  {reason}")


if __name__ == "__main__":
    run(
        "cuad_phase2.jsonl",
        "cuad_phase2.jsonl",
    )
