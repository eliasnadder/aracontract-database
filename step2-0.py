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

ds = load_dataset('lex_glue', 'unfair_tos')
df = ds['train'].to_pandas()

print(f"الحجم: {len(df)}")
print(f"الأعمدة: {df.columns.tolist()}")
print("\nتوزيع الـ labels:")
label_counts = df.iloc[:, -1].value_counts()  # آخر عمود غالباً هو الـ label
print(label_counts)
plot = save_bar_plot(label_counts, 'Unfair TOS label distribution', 'unfair_tos_labels.png')
print(f"تم حفظ الرسم: {plot}")

HIGH_RISK = {0, 1, 2}
MED_RISK = {3, 4, 7}


def assign_risk(labels):
    if len(labels) == 0:
        return 'low'
    label_set = set(labels)
    if label_set & HIGH_RISK:
        return 'high'
    if label_set & MED_RISK:
        return 'medium'
    return 'low'


df['risk_level'] = df['labels'].apply(assign_risk)

print(df['risk_level'].value_counts())
print(f"\nمثال high:\n{df[df['risk_level'] == 'high']['text'].iloc[0][:200]}")
print(
    f"\nمثال medium:\n{df[df['risk_level'] == 'medium']['text'].iloc[0][:200]}")
print(f"\nمثال low:\n{df[df['risk_level'] == 'low']['text'].iloc[0][:200]}")
