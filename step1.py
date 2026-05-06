from datasets import load_dataset
import pandas as pd
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

PLOTS_DIR = Path(__file__).resolve().parent / 'plots'
PLOTS_DIR.mkdir(parents=True, exist_ok=True)


def save_bar_plot(series, title, filename, color='#4C78A8'):
    ax = series.plot(kind='bar', figsize=(10, 5), color=color)
    ax.set_title(title)
    ax.set_xlabel('')
    ax.set_ylabel('Count')
    ax.tick_params(axis='x', rotation=35)
    for container in ax.containers:
        ax.bar_label(container, padding=2, fontsize=8)
    plt.tight_layout()
    out = PLOTS_DIR / filename
    plt.savefig(out, dpi=200, bbox_inches='tight')
    plt.close()
    return out

ds = load_dataset(
    'dvgodoy/CUAD_v1_Contract_Understanding_clause_classification'
)
df = ds['train'].to_pandas()

# ✓ الأعمدة الفعلية
print("أنواع البنود المتاحة:")
label_counts = df['label'].value_counts()
print(label_counts)
plot1 = save_bar_plot(label_counts, 'CUAD label distribution', 'cuad_labels.png')
print(f"تم حفظ الرسم: {plot1}")

# جدول تحويل label → صنف المشروع
CLAUSE_MAPPING = {
    'Minimum Commitment':               'payment_financial',
    'Price Restrictions':               'payment_financial',
    'Revenue/Profit Sharing':           'payment_financial',   # ✓ slash لا dash
    'Expiration Date':                  'duration_expiration',
    'Renewal Term':                     'duration_expiration',
    'Notice Period To Terminate Renewal': 'duration_expiration',
    'Termination For Convenience':      'termination',
    'Change Of Control':                'termination',
    'Liquidated Damages':               'penalties_damages',
    'Cap On Liability':                 'penalties_damages',
    # Dispute Resolution غير موجود
    'Governing Law':                    'dispute_resolution',
    'Document Name':                    'general_provisions',  # ✓ لا Agreement Name
    'Agreement Date':                   'general_provisions',  # ✓ لا Document Date
    'Parties':                          'general_provisions',
    # أضفهما للـ CLAUSE_MAPPING
    'Post-Termination Services': 'party_obligations',  # 411 بند
    'Audit Rights':              'party_obligations',  # 615 بند
}

# تصفية وإعادة تسمية
df_filtered = df[df['label'].isin(CLAUSE_MAPPING.keys())].copy()
df_filtered['clause_type'] = df_filtered['label'].map(CLAUSE_MAPPING)

# استبعاد البنود القصيرة وإزالة المكررات
df_filtered = df_filtered[df_filtered['clause'].str.len() >= 30]
df_filtered = df_filtered.drop_duplicates(subset=['clause'])

# التحقق من توازن الأصناف
dist = df_filtered['clause_type'].value_counts()
total = len(df_filtered)
print(f"\nبعد التصفية: {total} بند\n")
for cls, count in dist.items():
    pct = count / total * 100
    flag = "  ⚠ فوق 35%" if pct > 35 else ""
    print(f"  {cls}: {count} ({pct:.1f}%){flag}")

# بناء الـ DataFrame النهائي
df_final = df_filtered[['clause', 'clause_type']].copy()
df_final = df_final.rename(columns={'clause': 'text'})
df_final['risk_level'] = None
df_final['risk_reason'] = None
df_final['source'] = 'CUAD'
df_final['language'] = 'en'

# حفظ JSONL
df_final.to_json(
    'cuad_phase1.jsonl',
    orient='records',
    lines=True,
    force_ascii=False
)
print(f"\n✓ cuad_phase1.jsonl — {len(df_final)} بند")
