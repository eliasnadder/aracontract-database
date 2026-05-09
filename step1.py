from datasets import load_dataset
import pandas as pd
from plot_utils import save_bar_plot

ds = load_dataset(
    'dvgodoy/CUAD_v1_Contract_Understanding_clause_classification'
)
df = ds['train'].to_pandas()

# ✓ الأعمدة الفعلية
print("Available clauses:")
label_counts = df['label'].value_counts()
print(label_counts)
plot1 = save_bar_plot(
    label_counts, 'CUAD label distribution', 'cuad_labels.png')
print(f"Plot saved: {plot1}")

# جدول تحويل label → صنف المشروع
CLAUSE_MAPPING = {
    'Minimum Commitment':               'payment_financial',
    'Price Restrictions':               'payment_financial',
    'Revenue/Profit Sharing':           'payment_financial',
    'Expiration Date':                  'duration_expiration',
    'Renewal Term':                     'duration_expiration',
    'Notice Period To Terminate Renewal': 'duration_expiration',
    'Termination For Convenience':      'termination',
    'Change Of Control':                'termination',
    'Liquidated Damages':               'penalties_damages',
    'Cap On Liability':                 'penalties_damages',
    'Governing Law':                    'dispute_resolution',
    'Document Name':                    'general_provisions',
    'Agreement Date':                   'general_provisions',
    'Parties':                          'general_provisions',
    'Post-Termination Services': 'party_obligations',
    'Audit Rights':              'party_obligations',
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
print(f"\nAfter filtering: {total} clauses\n")
for cls, count in dist.items():
    pct = count / total * 100
    flag = "  ⚠ above 35%" if pct > 35 else ""
    print(f"  {cls}: {count} ({pct:.1f}%){flag}")
plot2 = save_bar_plot(dist, 'Filtered CUAD clause type distribution',
                      'cuad_clause_types.png', color='#4C78A8')
print(f"Plot saved: {plot2}")

# بناء الـ DataFrame النهائي
df_final = df_filtered[['clause', 'clause_type', 'file_name', 'start_at']].copy()
df_final = df_final.rename(columns={'clause': 'text'})

# ترتيب البنود لحساب موقع البند ضمن العقد
df_final = df_final.sort_values(['file_name', 'start_at'])

# حساب clause_position و total_clauses
df_final['clause_position'] = df_final.groupby('file_name').cumcount() + 1
df_final['total_clauses'] = df_final.groupby('file_name')['file_name'].transform('count')

# إعادة تسمية file_name إلى contract_id وإزالة start_at
df_final = df_final.rename(columns={'file_name': 'contract_id'})
df_final = df_final.drop(columns=['start_at'])

df_final['risk_level'] = None
df_final['risk_reason'] = None
# df_final['source'] = 'CUAD'
# df_final['language'] = 'en'

# حفظ JSONL
df_final.to_json(
    'cuad_phase1.jsonl',
    orient='records',
    lines=True,
    force_ascii=False
)
print(f"\n✓ cuad_phase1.jsonl — {len(df_final)} clauses")
