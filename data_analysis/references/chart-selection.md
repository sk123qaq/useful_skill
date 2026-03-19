# Chart Selection

## Chart Mapping

- one numeric distribution: histogram, KDE, box plot
- category vs numeric: bar chart, box plot, violin plot
- two numeric variables: scatter plot
- many numeric variables: correlation heatmap or scatter matrix
- time-series trend: line chart
- funnel: horizontal bar chart or step chart
- contribution mix: stacked bar or treemap

## Chinese Display

Prefer a CJK-capable font, for example:

- `Noto Sans CJK SC`
- `Source Han Sans SC`
- `PingFang SC`
- `Microsoft YaHei`

Also set:

- `axes.unicode_minus = False`

If no plotting backend exists, save a chart plan JSON and say which chart should be rendered later.

## Storytelling Order

Prefer:

1. context chart
2. main finding chart
3. diagnostic chart
4. risk or uncertainty chart

## Formal Report Governance

- For formal report正文, chart selection should be audience-first, not file-first.
- Prefer raw business fields over one-hot derived features.
- Treat PDP, score distributions, and similar technical views as diagnostic by default unless they clearly improve the intended reader's decision quality.
- Allow session-to-session diversity only inside a governed candidate pool with explicit constraints.
