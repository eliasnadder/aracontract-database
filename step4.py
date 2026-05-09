"""
AraContract Phase 3 - Arabic Contract Clause Extractor & Classifier
Processes scraped Syrian legal contracts → JSONL in AraContract schema

Usage:
    python phase3_arabic_extractor.py \
        --input scrap/contracts_dataset \
        --output claude/arabic_phase3.jsonl \
        --manifest scrap/contracts_dataset/manifest.json
"""

import os
import re
import json
import hashlib
import argparse
import unicodedata
from pathlib import Path
from collections import Counter


# ─────────────────────────────────────────────────────────────────────────────
# 1.  CLAUSE TYPE RULES
#     Each type has keyword sets. We score and pick the best match.
# ─────────────────────────────────────────────────────────────────────────────

CLAUSE_RULES = {
    "payment_financial": {
        "keywords": [
            "ثمن", "مبلغ", "دفع", "سداد", "قسط", "أقساط", "دفعة", "رصيد",
            "قبض", "نقدي", "ليرة", "أجر", "أتعاب", "تعويض", "غرامة مالية",
            "فائدة", "عوض", "ربح", "خسارة", "كلفة", "نفقة", "رسم", "ضريبة",
            "إيراد", "واردات", "مصاريف", "استوفى", "أبرأ ذمته", "براءة ذمة",
            "مخالصة", "دخل دائم", "مرتب", "إيجار", "أجارة", "بدل",
        ],
        "weight": 1.0,
    },
    "duration_expiration": {
        "keywords": [
            "مدة", "سنة", "شهر", "يوم", "اعتباراً من", "لغاية", "ينتهي",
            "انقضاء", "أجل", "موعد", "تاريخ", "فترة", "استحقاق", "بتاريخ",
            "طيلة", "حتى", "بغاية", "مستحق", "حلول أجل", "مدة العقد",
            "التجديد", "قابلة للتجديد",
        ],
        "weight": 1.0,
    },
    "termination": {
        "keywords": [
            "فسخ", "إنهاء", "إقالة", "إلغاء", "مفسوخ", "انتهاء", "حل",
            "استرداد", "رد", "استعادة", "تنهي", "تنتهي", "إبطال",
            "اعتبار العقد مفسوخاً", "اعتزال", "تنازل", "خروج", "رجوع عن",
            "الرجوع", "استباحة الفسخ", "طائلة الفسخ",
        ],
        "weight": 1.0,
    },
    "penalties_damages": {
        "keywords": [
            "غرامة", "تعويض", "ضرر", "خسارة", "تأخير", "جزاء", "عقوبة",
            "مسؤولية", "يلزم", "التزم بتعويض", "تبعة", "إهمال", "ضمان",
            "هلاك", "تلف", "عطب", "فقد", "سرقة", "إساءة ائتمان",
            "يكون مسؤولاً", "يتحمل", "يعوض", "طائلة",
        ],
        "weight": 1.0,
    },
    "dispute_resolution": {
        "keywords": [
            "محكمة", "قضاء", "تحكيم", "نزاع", "خلاف", "اختصاص", "دعوى",
            "تنفيذ", "دائرة التنفيذ", "حكم", "استئناف", "نقض", "طعن",
            "قاضي", "موطن مختار", "مختصة", "اتفاق التحكيم", "محاكم مدينة",
            "الحصول على حكم قضائي", "مراجعة القضاء",
        ],
        "weight": 1.0,
    },
    "general_provisions": {
        "keywords": [
            "مقدمة هذا العقد جزءاً", "تعتبر مقدمة", "نظم هذا العقد",
            "نسختين", "احتفظ", "قرئت عليه", "الأهلية", "شرعاً وقانوناً",
            "موطن مختار", "التبليغ", "إخطار", "بريد", "توقيع", "بكامل الأهلية",
            "اتخذ", "موطناً مختاراً", "تفهم مندرجاتها", "إثباتاً لذلك",
        ],
        "weight": 0.8,
    },
    "party_obligations": {
        "keywords": [
            "التزم", "يلتزم", "تعهد", "يتعهد", "على عاتق", "واجب",
            "يجب", "مكلف", "مسؤول", "حق", "حقوق", "صلاحية", "يحق",
            "أقر", "إقرار", "يقر", "ضمن", "كفل", "قبل", "وكّل",
            "تفويض", "أحل محله", "شروط", "بند", "فريق",
        ],
        "weight": 0.9,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# 2.  RISK RULES (applied after clause type classification)
# ─────────────────────────────────────────────────────────────────────────────

RISK_RULES = [
    # HIGH risk patterns
    ("high", r"(مفسوخ|فسخ العقد|يعتبر مفسوخاً)", "فسخ تلقائي - مخاطرة عالية"),
    ("high", r"(ضمان.*هلاك|مسؤول.*هلاك)", "ضمان الهلاك - مخاطرة عالية"),
    # FIX: مدين was matching مدينة (city). Use word-boundary-aware patterns.
    ("high", r"(إفلاس|إعسار)", "حالة إفلاس أو إعسار - مخاطرة عالية"),
    ("high", r"(?<!\bال)مدين(?!ة|ي|ا)", "مديونية - مخاطرة عالية"),
    ("high", r"(حجز.*أموال|تنفيذ.*جبري)", "تنفيذ جبري - مخاطرة عالية"),
    ("high", r"(دونما حاجة.*حكم قضائي|بلا.*أعذار)", "شرط دون إنذار - مخاطرة عالية"),
    ("high", r"(مسؤولية.*جزائية|ملاحقة.*جزائية)", "مسؤولية جزائية - مخاطرة عالية"),
    ("high", r"(إساءة ائتمان)", "إساءة ائتمان - مخاطرة عالية"),
    ("high", r"(تعويض.*عن كل يوم تأخير)", "غرامة يومية - مخاطرة عالية"),

    # MEDIUM risk patterns
    ("medium", r"(غرامة|تعويض|يلتزم.*بدفع)", "غرامة أو تعويض - مخاطرة متوسطة"),
    ("medium", r"(أجل|استحقاق|موعد.*دفع)", "شرط أجل - مخاطرة متوسطة"),
    ("medium", r"(رهن|تأمين.*عقاري|ضمان عيني)", "ضمان عيني - مخاطرة متوسطة"),
    ("medium", r"(إشارة.*تأمين|حجز احتياطي)", "حجز احتياطي - مخاطرة متوسطة"),
    ("medium", r"(فائدة.*%|نسبة.*فائدة)", "فائدة مالية - مخاطرة متوسطة"),
    ("medium", r"(تنازل.*حق|إسقاط.*حق)", "تنازل عن حق - مخاطرة متوسطة"),
    ("medium", r"(اشتراط|شرط.*فاسخ)", "شرط خاص - مخاطرة متوسطة"),

    # LOW risk (default for short/declaratory clauses)
    ("low", r"(مقدمة|نظم هذا العقد|احتفظ كل)", "بند إجرائي - مخاطرة منخفضة"),
    ("low", r"(أقر.*بكامل الأهلية|شرعاً وقانوناً)", "إقرار أهلية - مخاطرة منخفضة"),
    ("low", r"(قرئت عليه|نسختين|موطناً مختاراً)", "بند شكلي - مخاطرة منخفضة"),
    ("low", r"(وكالة|تفويض|توكيل)", "وكالة عادية - مخاطرة منخفضة"),
]

DEFAULT_RISK = ("low", "بند عام - مخاطرة منخفضة")


# ─────────────────────────────────────────────────────────────────────────────
# 3.  CATEGORY → CLAUSE TYPE BIAS
#     Certain contract categories strongly suggest specific clause types.
# ─────────────────────────────────────────────────────────────────────────────

CATEGORY_BIAS = {
    "القرض": {"payment_financial": 2.0, "duration_expiration": 1.5},
    "الإيجار": {"payment_financial": 2.0, "duration_expiration": 2.0, "termination": 1.5},
    "الكفالة": {"party_obligations": 2.0, "payment_financial": 1.5},
    "الصلح": {"dispute_resolution": 2.0, "termination": 1.5},
    "الحراسة": {"party_obligations": 2.0, "duration_expiration": 1.5},
    "الهبة": {"party_obligations": 1.5, "termination": 1.5},
    "الوديعة": {"party_obligations": 2.0, "penalties_damages": 1.5},
    "الوكالة": {"party_obligations": 2.0, "general_provisions": 1.5},
    "المقايضة": {"payment_financial": 1.5, "party_obligations": 1.5},
    "الدخل الدائم": {"payment_financial": 2.0, "duration_expiration": 2.0},
    "المرتب مدى الحياة": {"payment_financial": 2.0, "duration_expiration": 2.0},
    "البيوع العقارية": {"payment_financial": 2.0, "termination": 1.5},
    "بيع المنقولات": {"payment_financial": 2.0, "party_obligations": 1.5},
    "بيع التركة": {"party_obligations": 2.0, "payment_financial": 1.5},
    "القسمة والملكية الشائعة": {"party_obligations": 2.0, "duration_expiration": 1.5},
}


# ─────────────────────────────────────────────────────────────────────────────
# 4.  TEXT NORMALIZATION & CLEANING
# ─────────────────────────────────────────────────────────────────────────────

def normalize_arabic(text: str) -> str:
    """Normalize Arabic text: remove diacritics, unify hamza/alef forms."""
    text = unicodedata.normalize("NFKC", text)
    # Remove harakat (tashkeel)
    text = re.sub(r'[\u064B-\u065F\u0670]', '', text)
    # Normalize alef variants → bare alef
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    # Normalize yaa/alef maqsura
    text = text.replace('ى', 'ي')
    return text


def clean_clause_text(text: str) -> str:
    """Remove Markdown formatting artifacts from clause text."""
    # Remove Markdown links: [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove standalone URLs
    text = re.sub(r'https?://\S+', '', text)
    # Remove bold/italic markers
    text = re.sub(r'\*{1,2}([^*]*)\*{1,2}', r'\1', text)
    # Remove heading markers at line start
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove decorative lines (dashes, em-dashes)
    text = re.sub(r'[—–\-]{5,}', '', text)
    # Collapse multiple whitespace (but preserve single newlines for structure)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 5.  CORE EXTRACTION LOGIC
# ─────────────────────────────────────────────────────────────────────────────

# Pattern to detect the start of a new contract template within a single file
_CONTRACT_BOUNDARY = re.compile(
    r'^#{1,2}\s+\*{0,2}\s*(?:عقد|صيغة|نموذج|إنذار)',
    re.MULTILINE | re.UNICODE
)

# Pattern to detect article headers: المادة N
_ARTICLE_PATTERN = re.compile(
    r'(?:المادة\s*[\d١٢٣٤٥٦٧٨٩٠]+\s*[-–—]?\s*)',
    re.UNICODE
)


def _extract_articles_single(text: str) -> list[dict]:
    """
    Extract individual articles (المادة N) from a single contract.
    Returns list of {article_num, text}.
    """
    matches = list(_ARTICLE_PATTERN.finditer(text))
    if not matches:
        return []

    articles = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        article_text = text[start:end].strip()
        # Get article number
        num_match = re.search(r'[\d١٢٣٤٥٦٧٨٩٠]+', m.group())
        num = num_match.group() if num_match else str(i + 1)
        articles.append({"article_num": num, "text": article_text})

    return articles


def extract_articles(text: str) -> list[dict]:
    """
    Extract individual articles from a contract file.
    Handles files containing multiple contract templates by first
    splitting on contract boundaries (# عقد..., # صيغة..., etc.),
    then extracting المادة N from each sub-contract.
    """
    # Split on contract boundaries (headings like "# عقد إعارة شيء منقول")
    boundary_matches = list(_CONTRACT_BOUNDARY.finditer(text))

    if len(boundary_matches) > 1:
        # Multiple contracts in one file — split and extract from each
        all_articles = []
        for i, bm in enumerate(boundary_matches):
            start = bm.start()
            end = boundary_matches[i + 1].start() if i + 1 < len(boundary_matches) else len(text)
            sub_text = text[start:end]
            all_articles.extend(_extract_articles_single(sub_text))

        # Also extract from text before the first boundary (preamble contract)
        if boundary_matches[0].start() > 0:
            preamble = text[:boundary_matches[0].start()]
            all_articles = _extract_articles_single(preamble) + all_articles

        return all_articles

    # Single contract or no boundary headings — extract directly
    return _extract_articles_single(text)


def get_clause_category(text: str, contract_category: str = "") -> tuple[str, float]:
    """
    Score each clause type, applying category bias.
    Returns (best_type, confidence).
    """
    # Normalize text for keyword matching
    normalized = normalize_arabic(text)

    # Get bias for this contract category
    leaf_cat = contract_category.split(
        "/")[-1] if "/" in contract_category else contract_category
    bias = CATEGORY_BIAS.get(leaf_cat, {})

    scores = {}
    for ctype, info in CLAUSE_RULES.items():
        score = 0
        for kw in info["keywords"]:
            # Match keyword against normalized text
            kw_norm = normalize_arabic(kw)
            if kw_norm in normalized:
                score += 1
        score *= info["weight"]
        score *= bias.get(ctype, 1.0)
        scores[ctype] = score

    best = max(scores, key=scores.get)
    total = sum(scores.values())
    confidence = scores[best] / total if total > 0 else 0.0

    # Fallback: very short or generic text → general_provisions
    if total == 0 or len(text.strip()) < 50:
        return "general_provisions", 0.5

    return best, round(confidence, 3)


def get_risk(text: str) -> tuple[str, str]:
    """
    Rule-based risk assessment. Returns (level, reason).
    """
    for level, pattern, reason in RISK_RULES:
        if re.search(pattern, text, re.UNICODE):
            return level, reason

    # Length heuristic: very short clauses are usually low risk
    if len(text.strip()) < 60:
        return "low", "بند قصير - مخاطرة منخفضة"

    return DEFAULT_RISK


def get_category_from_path(filepath: str, base_dir: str) -> str:
    """Extract category path relative to base dir."""
    rel = os.path.relpath(filepath, base_dir)
    parts = Path(rel).parts
    # Remove filename, join the directory parts
    if len(parts) > 1:
        return "/".join(parts[:-1])
    return "عام"


def uid(text: str) -> str:
    """Generate a unique ID for text using SHA-256 (16 hex chars = 64 bits)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# 6.  MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def make_contract_id(filepath: str, sub_index: int = 0) -> str:
    """
    Generate a stable contract ID from file path + sub-contract index.
    Used for grouping clauses (not as a training feature).
    """
    base = hashlib.sha256(filepath.encode("utf-8")).hexdigest()[:10]
    return f"ctr_{base}_{sub_index}"


def process_dataset(input_dir: str, output_path: str, manifest_path: str = None):
    input_dir = Path(input_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load manifest for metadata (optional)
    manifest_items = {}
    if manifest_path and Path(manifest_path).exists():
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        for item in manifest.get("items", []):
            manifest_items[item["path"]] = item

    md_files = sorted(input_dir.rglob("*.md"))
    print(f"Found {len(md_files)} contract files")

    records = []
    skipped = 0
    seen_hashes = set()

    # ── Pass 1: Extract all clauses with contract grouping ────────────
    # We collect clauses grouped by contract_id, then enrich with
    # total_clauses in a second pass.
    contract_clauses: dict[str, list[dict]] = {}

    for filepath in md_files:
        try:
            text = filepath.read_text(encoding="utf-8")
        except Exception as e:
            print(f"  ⚠ Could not read {filepath}: {e}")
            continue

        category = get_category_from_path(str(filepath), str(input_dir))
        rel_path = str(Path(filepath).relative_to(input_dir))
        meta = manifest_items.get(rel_path, {})

        # Split into sub-contracts (multi-contract files)
        boundary_matches = list(_CONTRACT_BOUNDARY.finditer(text))

        if len(boundary_matches) > 1:
            # Multiple contracts in one file
            sub_texts = []
            # Text before first boundary
            if boundary_matches[0].start() > 0:
                sub_texts.append(text[:boundary_matches[0].start()])
            for i, bm in enumerate(boundary_matches):
                end = boundary_matches[i + 1].start() if i + 1 < len(boundary_matches) else len(text)
                sub_texts.append(text[bm.start():end])
        else:
            sub_texts = [text]

        for sub_idx, sub_text in enumerate(sub_texts):
            contract_id = make_contract_id(rel_path, sub_idx)

            # Extract articles from this sub-contract
            articles = _extract_articles_single(sub_text)

            # If no articles found, treat as paragraphs
            if not articles:
                paragraphs = [p.strip()
                              for p in sub_text.split("\n\n") if len(p.strip()) > 60]
                articles = [{"article_num": str(i+1), "text": p}
                            for i, p in enumerate(paragraphs)]

            clause_position = 0
            for art in articles:
                art_text = clean_clause_text(art["text"].strip())

                if len(art_text) < 50:
                    skipped += 1
                    continue

                h = uid(art_text)
                if h in seen_hashes:
                    skipped += 1
                    continue
                seen_hashes.add(h)

                clause_position += 1
                clause_type, confidence = get_clause_category(art_text, category)
                risk_level, risk_reason = get_risk(art_text)

                record = {
                    "text": art_text,
                    "type_clause": clause_type,
                    "risk_level": risk_level,
                    "risk_reason": risk_reason,
                    "contract_id": contract_id,
                    "clause_position": clause_position,
                    "total_clauses": 0,  # filled in pass 2
                }

                contract_clauses.setdefault(contract_id, []).append(record)

    # ── Pass 2: Enrich with total_clauses per contract ────────────────
    for cid, clauses in contract_clauses.items():
        total = len(clauses)
        for rec in clauses:
            rec["total_clauses"] = total
            records.append(rec)

    # Write JSONL
    with open(output_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Stats
    n_contracts = len(contract_clauses)
    avg_clauses = len(records) / n_contracts if n_contracts else 0
    print(f"\n{'='*50}")
    print(f"Total contracts         : {n_contracts}")
    print(f"Total clauses extracted : {len(records)}")
    print(f"Avg clauses/contract    : {avg_clauses:.1f}")
    print(f"Skipped (short/dup)     : {skipped}")
    print(f"Output written to       : {output_path}")
    print()

    # Distribution
    type_counts = Counter(r["type_clause"] for r in records)
    risk_counts = Counter(r["risk_level"] for r in records)

    print("Clause type distribution:")
    for k, v in type_counts.most_common():
        pct = 100 * v / len(records)
        print(f"  {k:<30} {v:>5}  ({pct:.1f}%)")

    print("\nRisk level distribution:")
    for k, v in risk_counts.most_common():
        pct = 100 * v / len(records)
        print(f"  {k:<10} {v:>5}  ({pct:.1f}%)")

    return records


# ─────────────────────────────────────────────────────────────────────────────
# 7.  POST-PROCESSING: balance & quality checks
# ─────────────────────────────────────────────────────────────────────────────

def check_balance(records: list[dict], max_pct: float = 0.35):
    """Flag over-represented classes."""
    type_counts = Counter(r["type_clause"] for r in records)
    total = len(records)
    issues = []
    for t, c in type_counts.items():
        if c / total > max_pct:
            issues.append(
                f"  ⚠ '{t}' is {100*c/total:.1f}% of dataset (threshold: {100*max_pct:.0f}%)")
    if issues:
        print("\nBalance warnings:")
        for i in issues:
            print(i)
    else:
        print("\n✓ Class balance is within acceptable limits")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AraContract Phase 3 Extractor")
    parser.add_argument("--input",    default="scrap/contracts_dataset",
                        help="Root directory of scraped contracts")
    parser.add_argument("--output",   default="arabic_phase3.jsonl",
                        help="Output JSONL path")
    parser.add_argument("--manifest", default="scrap/contracts_dataset/manifest.json",
                        help="Manifest JSON from scraper")
    args = parser.parse_args()

    records = process_dataset(args.input, args.output, args.manifest)
    check_balance(records)
    print("\nDone. Proceed to phase4_merge.py to integrate with CUAD data.")
