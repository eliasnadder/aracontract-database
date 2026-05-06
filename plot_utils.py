from pathlib import Path
import os
import textwrap

PROJECT_DIR = Path(__file__).resolve().parent
MPLCONFIG_DIR = PROJECT_DIR / '.matplotlib'
MPLCONFIG_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR', str(MPLCONFIG_DIR))

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


PLOTS_DIR = PROJECT_DIR / 'plots'
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_COLOR = '#35618F'
RISK_COLORS = {
    'high': '#C44E52',
    'medium': '#DD8452',
    'low': '#55A868',
}


def _ordered_series(series, order=None, sort=True):
    values = series.dropna()
    if order:
        ordered_index = [item for item in order if item in values.index]
        ordered = values.loc[ordered_index]
        rest = values.drop(index=ordered_index, errors='ignore')
        if sort:
            rest = rest.sort_values(ascending=False)
        return values.loc[list(ordered.index) + list(rest.index)]
    if sort:
        return values.sort_values(ascending=False)
    return values


def _wrapped_labels(labels, width=22):
    return [
        '\n'.join(textwrap.wrap(str(label).replace('_', ' '), width=width))
        for label in labels
    ]


def _colors_for(labels, color, palette):
    if not palette:
        return color
    return [palette.get(str(label), color) for label in labels]


def save_bar_plot(
    series,
    title,
    filename,
    color=DEFAULT_COLOR,
    palette=None,
    order=None,
    sort=True,
    ylabel='Count',
):
    values = _ordered_series(series, order=order, sort=sort)
    total = values.sum()
    labels = list(values.index)
    use_horizontal = len(labels) > 7 or any(len(str(label)) > 18 for label in labels)
    colors = _colors_for(labels, color=color, palette=palette)

    if use_horizontal:
        fig_height = max(4.2, min(12, 1.1 + len(values) * 0.52))
        fig, ax = plt.subplots(figsize=(11, fig_height))
        bars = ax.barh(
            _wrapped_labels(labels),
            values.values,
            color=colors,
            edgecolor='white',
            linewidth=0.8,
        )
        ax.invert_yaxis()
        ax.set_xlabel(ylabel)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(axis='x', color='#E6E8EB', linewidth=0.9)

        max_value = values.max() if len(values) else 0
        ax.set_xlim(0, max_value * 1.18 if max_value else 1)
        for bar, value in zip(bars, values.values):
            pct = value / total * 100 if total else 0
            ax.text(
                value + max(max_value * 0.015, 0.3),
                bar.get_y() + bar.get_height() / 2,
                f'{value:,.0f} ({pct:.1f}%)',
                va='center',
                ha='left',
                fontsize=9,
                color='#333333',
            )
    else:
        fig_width = max(7.5, min(13, 4.5 + len(values) * 0.75))
        fig, ax = plt.subplots(figsize=(fig_width, 5.2))
        bars = ax.bar(
            _wrapped_labels(labels, width=14),
            values.values,
            color=colors,
            edgecolor='white',
            linewidth=0.8,
        )
        ax.set_ylabel(ylabel)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(axis='y', color='#E6E8EB', linewidth=0.9)
        ax.margins(y=0.18)

        for bar, value in zip(bars, values.values):
            pct = value / total * 100 if total else 0
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f'{value:,.0f}\n{pct:.1f}%',
                va='bottom',
                ha='center',
                fontsize=9,
                color='#333333',
            )

    ax.set_title(title, loc='left', fontsize=14, fontweight='bold', pad=14)
    ax.set_axisbelow(True)
    ax.tick_params(axis='both', labelsize=9, colors='#333333')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#D1D5DB')
    ax.spines['bottom'].set_color('#D1D5DB')
    fig.patch.set_facecolor('white')
    ax.set_facecolor('#FAFAFA')
    fig.tight_layout()

    out = PLOTS_DIR / filename
    fig.savefig(out, dpi=220, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return out
