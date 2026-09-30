import plotly.graph_objects as go

from ficc import ui


def test_hover_numeric_precision_preserves_custom_data(monkeypatch):
    monkeypatch.setattr(ui.st, 'markdown', lambda *a, **kw: None)
    monkeypatch.setattr(ui.st, 'plotly_chart', lambda *a, **kw: None)
    fig = go.Figure(go.Scatter(x=[1], y=[.257451788], customdata=['+0.257'],
                              hovertemplate='%{y:+.3f}; %{customdata}; %{x:.1f}'))
    ui.chart(fig)
    assert fig.data[0].hovertemplate == '%{y:.3f}; %{customdata}; %{x:.1f}'
    assert list(fig.data[0].customdata) == ['+0.257']
