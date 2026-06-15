"""Графики (plotly). Каждая функция строит отдельную фигуру из SleepData —
их показывает и Streamlit (по одной), и CLI (склеивает в один HTML).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import plotly.graph_objects as go

from .transform import SleepData

STAGE_COLORS = {"awake": "#f59f00", "light": "#74c0fc", "deep": "#1864ab", "rem": "#9775fa"}
STAGE_RU = {"awake": "бодрствование", "light": "лёгкий", "deep": "глубокий", "rem": "REM"}
OFF_COLOR = "rgba(160,160,160,0.45)"
SLEEP_COLOR = "#3b5bdb"
_DAY_MS = 86400000


def _num(v):
    return float(v) if v not in ("", None) else None


def _dt_sec(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def _dt_min(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def _split_by_midnight(st: datetime, en: datetime):
    """Интервал -> куски (дата, час_начала_дробный, длительность_ч), разрезанные по полуночи."""
    cur = st
    while cur < en:
        day_end = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0)
        stop = min(en, day_end)
        yield cur.date().isoformat(), cur.hour + cur.minute / 60 + cur.second / 3600, \
            (stop - cur).total_seconds() / 3600
        cur = stop


def _date_span(data: SleepData):
    if not data.daily_sleep:
        return None
    x0 = datetime.fromisoformat(data.daily_sleep[0]["date"]) - timedelta(days=1)
    x1 = datetime.fromisoformat(data.daily_sleep[-1]["date"]) + timedelta(days=1)
    return [x0, x1]


def _layout(fig: go.Figure, title: str, height: int, span=None, hovermode=None) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        title=dict(text=title, font_size=15),
        height=height,
        margin=dict(t=64, l=60, r=24, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(size=12),
    )
    if hovermode:
        fig.update_layout(hovermode=hovermode)
    if span:
        fig.update_xaxes(range=span)
    return fig


def _watch_off_bars(fig: go.Figure, data: SleepData) -> None:
    """Серые полосы «часы сняты» для актограмм."""
    in_range = {d["date"] for d in data.daily_sleep}
    xs, bases = [], []
    for r in data.watch_off_hours:
        if r["date"] in in_range:
            xs.append(r["date"])
            bases.append(int(r["hour"]))
    if xs:
        fig.add_trace(go.Bar(
            x=xs, base=bases, y=[1] * len(xs), name="часы сняты",
            marker_color=OFF_COLOR, marker_line_width=0, width=_DAY_MS * 0.95,
            hovertemplate="%{x}<br>%{base}:00 часы сняты<extra></extra>",
        ))


def sleep_actogram(data: SleepData) -> go.Figure:
    """Чистая карта сна: только блоки сна (без фаз), серым — часы сняты с руки.
    Самый наглядный вид «когда и насколько разорван мой сон»."""
    fig = go.Figure()
    _watch_off_bars(fig, data)
    xs, bases, ys, texts = [], [], [], []
    for s in data.sleep_sessions:
        if s["record_kind"] == "part_of_combined":
            continue
        for day, start_h, dur_h in _split_by_midnight(_dt_min(s["start_local"]),
                                                      _dt_min(s["end_local"])):
            xs.append(day)
            bases.append(start_h)
            ys.append(dur_h)
            texts.append(f"{s['start_local'][11:]}–{s['end_local'][11:]}")
    fig.add_trace(go.Bar(
        x=xs, base=bases, y=ys, name="сон", customdata=texts,
        marker_color=SLEEP_COLOR, marker_line_width=0, width=_DAY_MS * 0.95,
        hovertemplate="%{x}<br>%{customdata} · %{y:.1f} ч<extra></extra>",
    ))
    fig.update_layout(barmode="overlay")
    fig.update_yaxes(title_text="час суток", range=[24, 0],
                     tickvals=[0, 4, 8, 12, 16, 20, 24])
    return _layout(fig, "Карта сна: когда и насколько разорван (серый — часы сняты)",
                   460, _date_span(data))


def actogram(data: SleepData) -> go.Figure:
    """Карта сна: ось X - даты, ось Y - час суток. Серым - часы сняты с руки."""
    fig = go.Figure()
    _watch_off_bars(fig, data)
    buckets = {s: {"x": [], "base": [], "y": []} for s in STAGE_COLORS}
    for r in data.sleep_stages:
        if r["stage"] not in buckets:
            continue
        for day, start_h, dur_h in _split_by_midnight(_dt_sec(r["start_local"]),
                                                      _dt_sec(r["end_local"])):
            t = buckets[r["stage"]]
            t["x"].append(day)
            t["base"].append(start_h)
            t["y"].append(dur_h)
    for stage, t in buckets.items():
        fig.add_trace(go.Bar(
            x=t["x"], base=t["base"], y=t["y"], name=STAGE_RU[stage],
            marker_color=STAGE_COLORS[stage], marker_line_width=0, width=_DAY_MS * 0.95,
            hovertemplate="%{x}<br>" + STAGE_RU[stage] + " %{y:.1f} ч<extra></extra>",
        ))
    fig.update_layout(barmode="overlay")
    fig.update_yaxes(title_text="час суток", range=[24, 0],
                     tickvals=[0, 4, 8, 12, 16, 20, 24])
    return _layout(fig, "Актограмма: когда я сплю (цвет — стадия, серый — часы сняты)",
                   520, _date_span(data))


def daily_sleep_chart(data: SleepData, rolling_days: int = 7) -> go.Figure:
    """Сон по календарным дням + скользящее среднее по дням с полными данными."""
    fig = go.Figure()
    xs = [d["date"] for d in data.daily_sleep]
    hrs = [(_num(d["recorded_sleep_min"]) or 0) / 60 for d in data.daily_sleep]
    colors = ["#2f9e44" if d["data_quality"] == "ok" else "#ced4da"
              for d in data.daily_sleep]
    quality = [d["data_quality"] for d in data.daily_sleep]
    fig.add_trace(go.Bar(
        x=xs, y=hrs, marker_color=colors, name="сон за сутки", customdata=quality,
        hovertemplate="%{x}: %{y:.1f} ч (%{customdata})<extra></extra>",
    ))
    ok_idx = [i for i, d in enumerate(data.daily_sleep) if d["data_quality"] == "ok"]
    roll_x, roll_y = [], []
    for j, i in enumerate(ok_idx):
        win = [hrs[k] for k in ok_idx[max(0, j - rolling_days + 1):j + 1]]
        roll_x.append(xs[i])
        roll_y.append(sum(win) / len(win))
    fig.add_trace(go.Scatter(
        x=roll_x, y=roll_y, mode="lines", name=f"среднее {rolling_days} дн",
        line=dict(color="#212529", dash="dash", width=2),
        hovertemplate="%{x}: в среднем %{y:.1f} ч<extra></extra>",
    ))
    fig.add_hline(y=7, line_dash="dot", line_color="#868e96",
                  annotation_text="цель 7 ч", annotation_font_size=10)
    fig.update_yaxes(title_text="часов")
    return _layout(fig, "Сон по календарным дням (серым — дни с неполными данными)",
                   360, _date_span(data), hovermode="x unified")


def score_trend(data: SleepData) -> go.Figure:
    """Оценка сна Samsung по суткам сна."""
    scored = [n for n in data.nights if n["main_sleep_score"]]
    sc = [int(n["main_sleep_score"]) for n in scored]
    fig = go.Figure(go.Scatter(
        x=[n["sleep_date"] for n in scored], y=sc, mode="lines+markers",
        line=dict(color="#e8590c", width=1.5),
        marker=dict(size=7, color=sc, cmin=0, cmax=100,
                    colorscale=[[0, "#fa5252"], [0.6, "#fcc419"], [1, "#40c057"]]),
        hovertemplate="%{x}: %{y}/100<extra></extra>",
    ))
    fig.update_yaxes(title_text="балл", range=[0, 100])
    return _layout(fig, "Оценка сна Samsung (0–100)", 320, _date_span(data),
                   hovermode="x unified")


def architecture_chart(data: SleepData) -> go.Figure:
    """Доли стадий по суткам (% времени в постели), с зоной нормы глубокого сна."""
    fig = go.Figure()
    for col, stage in (("total_deep_min", "deep"), ("total_rem_min", "rem"),
                       ("total_awake_min", "awake")):
        xs, ys = [], []
        for n in data.nights:
            tot = _num(n["total_in_bed_min"]) or 0
            val = _num(n[col])
            if tot > 0 and val is not None:
                xs.append(n["sleep_date"])
                ys.append(100 * val / tot)
        fig.add_trace(go.Bar(
            x=xs, y=ys, name=STAGE_RU[stage], marker_color=STAGE_COLORS[stage],
            hovertemplate="%{x}: " + STAGE_RU[stage] + " %{y:.0f}%<extra></extra>",
        ))
    fig.add_hrect(y0=13, y1=23, fillcolor=STAGE_COLORS["deep"], opacity=0.08, line_width=0)
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text="% времени в постели")
    return _layout(fig, "Архитектура сна: доли стадий (полоса — норма глубокого 13–23%)",
                   340, _date_span(data))


def fragmentation_chart(data: SleepData) -> go.Figure:
    """Разрывность сна по суткам (из сессий Samsung): число сессий сна (бары) и
    длиннейшая непрерывная сессия (линия). Больше сессий + короче блок = рванее сон."""
    from plotly.subplots import make_subplots
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    xs = [n["sleep_date"] for n in data.nights]
    fig.add_trace(go.Bar(
        x=xs, y=[int(n["sessions_count"]) for n in data.nights], name="сессий сна",
        marker_color="#b197fc", marker_line_width=0,
        hovertemplate="%{x}: сессий сна %{y}<extra></extra>",
    ), secondary_y=False)
    lb = [n for n in data.nights if n["longest_block_min"] != ""]
    fig.add_trace(go.Scatter(
        x=[n["sleep_date"] for n in lb],
        y=[float(n["longest_block_min"]) / 60 for n in lb], mode="lines+markers",
        name="длиннейший блок, ч", line=dict(color="#0c8599", width=2), marker=dict(size=5),
        hovertemplate="%{x}: длиннейший блок %{y:.1f} ч<extra></extra>",
    ), secondary_y=True)
    fig.update_yaxes(title_text="сессий сна за сутки", secondary_y=False, rangemode="tozero")
    fig.update_yaxes(title_text="длиннейшая сессия, ч", secondary_y=True, rangemode="tozero")
    return _layout(fig, "Разрывность сна: число сессий и длиннейший непрерывный блок",
                   340, _date_span(data), hovermode="x unified")


def physiology_chart(data: SleepData) -> go.Figure:
    """Минимальный ночной пульс и HRV (RMSSD) — два главных маркера восстановления."""
    from plotly.subplots import make_subplots
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    ph = [n for n in data.nights if n["main_hr_min"]]
    fig.add_trace(go.Scatter(
        x=[n["sleep_date"] for n in ph], y=[float(n["main_hr_min"]) for n in ph],
        mode="lines+markers", name="пульс мин", line=dict(color="#c2255c"),
        marker=dict(size=5), hovertemplate="%{x}: пульс мин %{y:.0f}<extra></extra>",
    ), secondary_y=False)
    hv = [n for n in data.nights if n["main_hrv_rmssd_avg"]]
    fig.add_trace(go.Scatter(
        x=[n["sleep_date"] for n in hv], y=[float(n["main_hrv_rmssd_avg"]) for n in hv],
        mode="lines+markers", name="RMSSD", line=dict(color="#0c8599"),
        marker=dict(size=5), hovertemplate="%{x}: RMSSD %{y:.0f} мс<extra></extra>",
    ), secondary_y=True)
    fig.update_yaxes(title_text="пульс, уд/мин", color="#c2255c", secondary_y=False)
    fig.update_yaxes(title_text="RMSSD, мс", color="#0c8599", secondary_y=True)
    return _layout(fig, "Физиология ночи: мин. пульс и HRV (RMSSD)", 340, _date_span(data),
                   hovermode="x unified")


def onset_histogram(data: SleepData) -> go.Figure:
    """Во сколько начинается сон — показывает сдвинутый/плавающий ритм."""
    onset = defaultdict(int)
    for s in data.sleep_sessions:
        if s["record_kind"] != "part_of_combined":
            onset[_dt_min(s["start_local"]).hour] += 1
    fig = go.Figure(go.Bar(
        x=[f"{h:02d}" for h in range(24)], y=[onset.get(h, 0) for h in range(24)],
        marker_color="#5f3dc4",
        hovertemplate="засыпание в %{x}:xx — %{y} раз<extra></extra>",
    ))
    fig.update_xaxes(title_text="час начала сна")
    fig.update_yaxes(title_text="сессий")
    return _layout(fig, "Во сколько я засыпаю", 300)


# (ключ, заголовок, builder) — порядок на дашборде и в HTML
_CHARTS = [
    ("sleep_actogram", "Карта сна", sleep_actogram),
    ("actogram", "Актограмма (фазы)", actogram),
    ("daily_sleep", "Сон по дням", daily_sleep_chart),
    ("fragmentation", "Разрывность сна", fragmentation_chart),
    ("score", "Оценка сна", score_trend),
    ("architecture", "Архитектура сна", architecture_chart),
    ("physiology", "Физиология", physiology_chart),
    ("onset", "Время засыпания", onset_histogram),
]


def all_figures(data: SleepData, rolling_days: int = 7) -> list[tuple[str, go.Figure]]:
    out = []
    for key, label, fn in _CHARTS:
        fig = fn(data, rolling_days) if fn is daily_sleep_chart else fn(data)
        out.append((label, fig))
    return out


def write_html(data: SleepData, path: str, rolling_days: int = 7) -> None:
    """Все графики в один автономный HTML-файл."""
    lo, hi = data.date_range
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Дневник сна</title>",
        "<style>body{font-family:system-ui,sans-serif;max-width:1400px;margin:0 auto;"
        "padding:16px;background:#fff}h1{font-size:22px}</style></head><body>",
        f"<h1>Дневник сна — {lo} … {hi}</h1>",
    ]
    for i, (_label, fig) in enumerate(all_figures(data, rolling_days)):
        parts.append(fig.to_html(full_html=False,
                                 include_plotlyjs="cdn" if i == 0 else False))
    parts.append("</body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
