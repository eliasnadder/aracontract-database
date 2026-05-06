from sklearn.model_selection import train_test_split
from datasets import load_dataset
import pandas as pd
from sklearn.utils import resample
from sklearn.linear_model import LogisticRegression
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report
from plot_utils import RISK_COLORS, save_bar_plot

# ── تحضير البيانات ──────────────────────────────────────
ds = load_dataset('lex_glue', 'unfair_tos')
df = ds['train'].to_pandas()

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

# ── موازنة الأصناف (الهدف: 400 لكل صنف) ─────────────────
TARGET = 400

df_high = resample(df[df['risk_level'] == 'high'],
                   n_samples=TARGET, random_state=42)
df_medium = resample(df[df['risk_level'] == 'medium'],
                     n_samples=TARGET, random_state=42, replace=True)
df_low = resample(df[df['risk_level'] == 'low'],
                  n_samples=TARGET, random_state=42)

df_balanced = pd.concat([df_high, df_medium, df_low]
                        ).sample(frac=1, random_state=42)
print(df_balanced['risk_level'].value_counts())

# ── تدريب TF-IDF + Logistic Regression ──────────────────
vectorizer = TfidfVectorizer(max_features=10000, ngram_range=(1, 2))
X = vectorizer.fit_transform(df_balanced['text'])
y = df_balanced['risk_level']

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42)

clf = LogisticRegression(max_iter=1000, class_weight='balanced')
clf.fit(X_train, y_train)

print("\nتقرير الجودة على Test set:")
print(classification_report(y_test, clf.predict(X_test)))

# ── تطبيق النموذج على CUAD ──────────────────────────────
cuad = pd.read_json('cuad_phase1.jsonl', lines=True)
X_cuad = vectorizer.transform(cuad['text'])
cuad['risk_level'] = clf.predict(X_cuad)

print("\nتوزيع risk_level على CUAD:")
cuad_counts = cuad['risk_level'].value_counts()
print(cuad_counts)
plot2 = save_bar_plot(
    cuad_counts,
    'CUAD risk level distribution',
    'cuad_phase2_risk_levels.png',
    palette=RISK_COLORS,
    order=['high', 'medium', 'low'],
)
print(f"تم حفظ الرسم: {plot2}")

# ── حفظ الناتج ──────────────────────────────────────────
cuad.to_json('cuad_phase2.jsonl', orient='records',
             lines=True, force_ascii=False)
print(f"\n✓ cuad_phase2.jsonl — {len(cuad)} بند")
