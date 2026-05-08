from datasets import load_dataset
import pandas as pd
from plot_utils import RISK_COLORS, save_bar_plot

ds = load_dataset('lex_glue', 'unfair_tos')
df = ds['train'].to_pandas()

print(f"Size: {len(df)}")
print(f"Columns: {df.columns.tolist()}")
print("\nLabel distribution:")
label_counts = df.iloc[:, -1].value_counts()  # Last column is usually the label
print(label_counts)
plot = save_bar_plot(label_counts, 'Unfair TOS label distribution', 'unfair_tos_labels.png')
print(f"Plot saved: {plot}")

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

risk_counts = df['risk_level'].value_counts()
print(risk_counts)
risk_plot = save_bar_plot(
    risk_counts,
    'Unfair TOS risk level distribution',
    'unfair_tos_risk_levels.png',
    palette=RISK_COLORS,
    order=['high', 'medium', 'low'],
)
print(f"Plot saved: {risk_plot}")
print(f"\nExample high:\n{df[df['risk_level'] == 'high']['text'].iloc[0][:200]}")
print(
    f"\nExample medium:\n{df[df['risk_level'] == 'medium']['text'].iloc[0][:200]}")
print(f"\nExample low:\n{df[df['risk_level'] == 'low']['text'].iloc[0][:200]}")
