# import pandas as pd

# df = pd.read_json('cuad_phase2.jsonl', lines=True)

# print(df.columns.tolist())
# print(df.head(2))

# # عينة 15% موزعة يدوياً
# frames = []
# for lvl in ['high', 'medium', 'low']:
#     subset = df[df['risk_level'] == lvl].sample(frac=0.15, random_state=42)
#     frames.append(subset)

# sample = pd.concat(frames).sample(frac=1, random_state=42)

# sample[['text', 'clause_type', 'risk_level']].to_csv(
#     'review_sample.csv', index=False
# )
# print(f"عينة للمراجعة: {len(sample)} بند")
# print(sample['risk_level'].value_counts())

import pandas as pd
from plot_utils import RISK_COLORS, save_bar_plot

# قراءة ناتج المرحلة الثانية
df = pd.read_json('cuad_phase2.jsonl', lines=True)

print("قبل الإصلاح:")
print(df['risk_level'].value_counts())

# إصلاح 1: البنود القصيرة جداً (أسماء شركات) → low
df.loc[df['text'].str.len() < 60, 'risk_level'] = 'low'

# إصلاح 2: penalties_damages + "sole/exclusive remedy" → high
mask = (
    df['clause_type'] == 'penalties_damages'
) & df['text'].str.contains(
    r'sole.{0,20}remedy|exclusive.{0,20}remedy',
    case=False, regex=True
)
df.loc[mask, 'risk_level'] = 'high'

# إصلاح 3: payment_financial + minimum order/volume → medium على الأقل
mask2 = (
    df['clause_type'] == 'payment_financial'
) & df['text'].str.contains(
    r'minimum.{0,30}(?:order|volume|purchase|commit)',
    case=False, regex=True
)
df.loc[mask2 & (df['risk_level'] == 'low'), 'risk_level'] = 'medium'

print("\nبعد الإصلاح:")
final_counts = df['risk_level'].value_counts()
print(final_counts)
plot = save_bar_plot(
    final_counts,
    'Final risk level distribution',
    'cuad_risk_levels.png',
    palette=RISK_COLORS,
    order=['high', 'medium', 'low'],
)
print(f"تم حفظ الرسم: {plot}")

# حفظ الناتج النهائي
df.to_json('cuad_phase2_fixed.jsonl', orient='records',
           lines=True, force_ascii=False)
print(f"\n✓ cuad_phase2_fixed.jsonl — {len(df)} بند")
