"""Интерактивный дашборд сна.

    uv run streamlit run streamlit_app.py

Загрузите .zip экспорта Samsung Health (или укажите локальный путь к zip/папке),
настройте параметры в сайдбаре, нажмите «Применить» — и смотрите таблицы, графики,
статистику и корреляции.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from samsung_sleep import (Config, Export, SleepData, all_figures, build_all,
                           build_llm_context)
from samsung_sleep.stats import (SUMMARY_COLS, correlations, master_rows,
                                 pearson, summarize)

st.set_page_config(page_title="Samsung Sleep Tracker", page_icon="😴", layout="wide")

TABLE_HELP = {
    "sleep_sessions": "Одна строка = сессия сна: стадии, оценки, физиология, локальное время.",
    "nights": "Сутки сна (граница в полдень), без дублей объединённых ночей.",
    "daily_sleep": "Сон по календарным дням + флаг качества данных (носились ли часы).",
    "data_gaps": "Разрывы записи: где часы были сняты, а не где «не спал».",
    "sleep_stages": "Гипнограмма: каждый сегмент стадии.",
    "daily_context": "Дневная активность: шаги, тренировки, дневной сон.",
    "watch_off_hours": "Часы, когда часы были сняты с руки (нет пульса).",
}
_NUM_SKIP = {"date", "sleep_date", "session_id", "record_kind", "combined_id",
             "time_offset", "start_local", "end_local", "data_quality", "stage",
             "exercise_types", "main_start_local", "main_end_local",
             "no_sleep_record_from", "no_sleep_record_to", "watch_off_windows",
             "interpretation"}

# короткие подписи для тепловой карты корреляций (без оценки сна)
_SHORT = {
    "total_sleep_min": "сон, мин",
    "main_efficiency_pct": "эффект.,%", "main_latency_min": "засып.,мин",
    "main_deep_pct": "глуб.,%", "main_rem_pct": "REM,%",
    "sessions_count": "сессий", "longest_block_min": "блок,мин",
    "main_hr_min": "пульс мин",
    "main_hrv_rmssd_avg": "RMSSD", "steps": "шаги",
    "exercise_min": "трен.,мин", "nap_min": "днев.сон,мин",
}


def _to_df(rows: list[dict]) -> pd.DataFrame:
    """list[dict] -> DataFrame с числовыми колонками (пустые -> NaN)."""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in df.columns:
        if col not in _NUM_SKIP:  # все строковые колонки перечислены в _NUM_SKIP
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@st.cache_data(show_spinner="Обрабатываю экспорт…")
def _process(payload: bytes | str, config: Config) -> SleepData:
    source = io.BytesIO(payload) if isinstance(payload, bytes) else payload
    with Export(source) as ex:
        return build_all(ex, config)


def _sidebar() -> tuple[object | None, Config, int]:
    st.sidebar.title("😴 Samsung Sleep")
    st.sidebar.caption("Дашборд сна из экспорта Samsung Health")

    up = st.sidebar.file_uploader("Загрузить экспорт (.zip)", type=["zip"])
    path = st.sidebar.text_input(
        "…или путь к .zip / папке на этом компьютере",
        help="Удобно для больших локальных экспортов, чтобы не грузить файл.",
    )

    with st.sidebar.form("params"):
        st.subheader("Параметры обработки")
        st.caption("Измените и нажмите «Применить» — таблицы и графики пересчитаются.")
        boundary = st.slider(
            "Граница «суток сна», час", 0, 23, Config.sleep_day_boundary_hour,
            help="К какой дате относить ночь. 12 = ночь относится к дате вечера засыпания "
                 "(сон с вечера до утра попадёт на дату вечера). Влияет на таблицу nights и "
                 "группировку суток.")
        gap = st.slider(
            "Порог разрыва записи, ч", 8, 36, int(Config.gap_min_hours),
            help="Промежуток без сессий сна длиннее этого попадает в data_gaps как «разрыв». "
                 "Влияет на вкладку «Качество данных».")
        not_worn = st.slider(
            "«Часы не носились» при ≤ N ч пульса/сутки", 0, 12, Config.not_worn_max_hours,
            help="Если в календарных сутках пульс писался ≤ N часов — день помечается "
                 "watch_not_worn (данные неполные). Влияет на цвет столбцов в «Сон по дням» и "
                 "на то, какие дни считаются «полными» в средних.")
        partial = st.slider(
            "«Частичное ношение» при < N ч пульса/сутки", not_worn + 1, 24,
            Config.partial_max_hours,
            help="Между порогом «не носились» и этим — partial_wear; выше — ok.")
        rolling = st.slider(
            "Скользящее среднее, дней", 3, 21, 7,
            help="Окно усреднения для линии тренда на графике «Сон по дням».")
        st.form_submit_button("Применить", use_container_width=True, type="primary")

    config = Config(sleep_day_boundary_hour=boundary, gap_min_hours=float(gap),
                    not_worn_max_hours=not_worn, partial_max_hours=partial)

    payload = None
    if up is not None:
        payload = up.getvalue()
    elif path.strip():
        payload = path.strip()
    return payload, config, rolling


def _overview(data: SleepData, daily: pd.DataFrame, nights: pd.DataFrame) -> None:
    lo, hi = data.date_range
    ok = daily[daily["data_quality"] == "ok"] if not daily.empty else daily
    c = st.columns(4)
    c[0].metric("Период", f"{lo} … {hi}")
    c[1].metric("Суток сна", len(data.nights))
    if not ok.empty:
        c[2].metric("Сон/сутки (полные дни)", f"{ok['recorded_sleep_min'].mean() / 60:.1f} ч")
    scored = nights[pd.to_numeric(nights["main_sleep_score"], errors="coerce").notna()] \
        if not nights.empty else nights
    if not scored.empty:
        c[3].metric("Средняя оценка", f"{pd.to_numeric(scored['main_sleep_score']).mean():.0f}/100")

    frag = summarize(data.nights, ["sessions_count", "longest_block_min"])
    if frag:
        f = st.columns(2)
        if "sessions_count" in frag:
            f[0].metric("Сессий сна/сутки (медиана)", f"{frag['sessions_count']['median']:.0f}",
                        help="Сколько отдельных сессий сна за сутки (как у часов) — "
                             "мера разрывности. Каждая сессия = просыпался и снова засыпал.")
        if "longest_block_min" in frag:
            f[1].metric("Длиннейшая сессия сна (медиана)",
                        f"{frag['longest_block_min']['median'] / 60:.1f} ч",
                        help="Самая длинная непрерывная сессия сна за сутки.")

    p = data.profile
    if p:
        st.caption(f"Профиль: пол {p.get('gender', '?')}, г.р. {p.get('birth_date', '?')}, "
                   f"рост {p.get('height', '?')} см, вес {p.get('weight', '?')} кг")

    n_off = sum(1 for g in data.data_gaps if "не носились" in g["interpretation"])
    if n_off:
        st.info(f"⚠️ Найдено разрывов записи: {len(data.data_gaps)}, из них {n_off} — "
                f"часы были сняты (сон мог быть, но не записан). Подробнее во вкладке "
                f"«Качество данных». Не путайте их с бодрствованием.")


def _corr_heatmap(df: pd.DataFrame, cols: list[str]) -> go.Figure:
    corr = df[cols].corr().round(2)
    labels = [_SHORT.get(c, c) for c in cols]
    fig = go.Figure(go.Heatmap(
        z=corr.values, x=labels, y=labels, zmid=0, zmin=-1, zmax=1,
        colorscale="RdBu", text=corr.values, texttemplate="%{text:.2f}",
        textfont=dict(size=9),
        hovertemplate="%{y} ↔ %{x}: r=%{z:.2f}<extra></extra>",
    ))
    fig.update_layout(template="plotly_white", height=540, margin=dict(t=20, l=90, r=20, b=90))
    fig.update_yaxes(autorange="reversed")
    return fig


def _scatter(df: pd.DataFrame, x: str, y: str) -> go.Figure:
    sub = df[[x, y]].dropna()
    r, n = pearson(sub[x].tolist(), sub[y].tolist())
    rtxt = f"r = {r:+.2f} (n={n})" if r is not None else "мало данных"
    fig = go.Figure(go.Scatter(
        x=sub[x], y=sub[y], mode="markers",
        marker=dict(size=9, color="#3b5bdb", opacity=0.7),
        hovertemplate=f"{x}=%{{x}}<br>{y}=%{{y}}<extra></extra>",
    ))
    fig.update_layout(template="plotly_white", height=440,
                      title=f"{_SHORT.get(x, x)} ↔ {_SHORT.get(y, y)}  ·  {rtxt}",
                      xaxis_title=x, yaxis_title=y, margin=dict(t=60, l=60, r=20, b=50))
    return fig


def _statistics(data: SleepData) -> None:
    st.subheader("Сводные статистики по суткам сна")
    summ = summarize(data.nights, [c for c, _ in SUMMARY_COLS])
    labels = dict(SUMMARY_COLS)
    srows = [{"Метрика": labels[c], "n": s["n"], "среднее": round(s["mean"], 1),
              "медиана": round(s["median"], 1), "разброс (sd)": round(s["sd"], 1),
              "мин": round(s["min"], 1), "макс": round(s["max"], 1)}
             for c, s in ((col, summ.get(col)) for col, _ in SUMMARY_COLS) if s]
    if srows:
        st.dataframe(pd.DataFrame(srows), use_container_width=True, hide_index=True)

    st.subheader("Корреляции «день → ночь»")
    st.caption("Пирсон по совпадающим суткам. |r| ≥ 0.3 — заметная связь; "
               "это корреляция, не доказательство причинности.")
    cors = correlations(data)
    if cors:
        cdf = pd.DataFrame([{"Связь": c["label"], "r": c["r"], "n (суток)": c["n"]}
                            for c in cors])
        st.dataframe(cdf, use_container_width=True, hide_index=True)
    else:
        st.info("Недостаточно совпадающих суток для расчёта корреляций.")

    master = _to_df(master_rows(data))
    heat_cols = [c for c in _SHORT
                 if c in master.columns and master[c].notna().sum() >= 3]
    if len(heat_cols) >= 2:
        st.subheader("Тепловая карта корреляций")
        st.caption("Синий — прямая связь, красный — обратная. Все числовые метрики попарно.")
        st.plotly_chart(_corr_heatmap(master, heat_cols), use_container_width=True)

        st.subheader("Свой график связи")
        st.caption("Выберите любые две метрики и посмотрите облако точек и их корреляцию.")
        opts = heat_cols
        c1, c2 = st.columns(2)
        x = c1.selectbox("Ось X", opts, index=opts.index("total_sleep_min")
                         if "total_sleep_min" in opts else 0,
                         format_func=lambda c: _SHORT.get(c, c))
        y = c2.selectbox("Ось Y", opts, index=opts.index("main_deep_pct")
                         if "main_deep_pct" in opts else min(1, len(opts) - 1),
                         format_func=lambda c: _SHORT.get(c, c))
        st.plotly_chart(_scatter(master, x, y), use_container_width=True)


def main() -> None:
    payload, config, rolling = _sidebar()
    if payload is None:
        st.title("😴 Samsung Sleep Tracker")
        st.markdown(
            "Загрузите `.zip` экспорта Samsung Health в сайдбаре слева "
            "(в приложении: **Настройки → Загрузить личные данные**), либо укажите путь "
            "к нему на этом компьютере.\n\n"
            "Дальше — таблицы, графики, статистика, корреляции и готовый контекст для LLM."
        )
        return

    try:
        data = _process(payload, config)
    except Exception as e:  # noqa: BLE001 — показать пользователю любую ошибку загрузки
        st.error(f"Не удалось обработать экспорт: {e}")
        return

    dfs = {name: _to_df(rows) for name, rows in data.tables().items()}

    tabs = st.tabs(["📋 Обзор", "📈 Графики", "📊 Статистика", "🗂 Таблицы",
                    "⚠️ Качество данных", "🤖 Для LLM"])

    with tabs[0]:
        _overview(data, dfs["daily_sleep"], dfs["nights"])

    with tabs[1]:
        for label, fig in all_figures(data, rolling_days=rolling):
            st.plotly_chart(fig, use_container_width=True)

    with tabs[2]:
        _statistics(data)

    with tabs[3]:
        name = st.selectbox("Таблица", list(dfs), format_func=lambda n: n.replace("_", " "))
        st.caption(TABLE_HELP.get(name, ""))
        df = dfs[name]
        st.dataframe(df, use_container_width=True, height=560)
        st.download_button(f"⬇️ Скачать {name}.csv",
                           df.to_csv(index=False).encode("utf-8"),
                           file_name=f"{name}.csv", mime="text/csv")

    with tabs[4]:
        st.subheader("Почему «дни без сна» — это чаще всего снятые часы")
        st.markdown(
            "Трекер не пишет сон, пока лежит на зарядке. Длинный период без записей — "
            "почти всегда снятые часы, а не реальное бодрствование. Ниже — найденные "
            "разрывы с проверкой по наличию пульса."
        )
        gaps = dfs["data_gaps"]
        if gaps.empty:
            st.success("Разрывов записи не найдено.")
        else:
            st.dataframe(gaps, use_container_width=True)
        st.subheader("Качество данных по дням")
        daily = dfs["daily_sleep"]
        if not daily.empty:
            counts = daily["data_quality"].value_counts()
            cols = st.columns(len(counts))
            for col, (q, n) in zip(cols, counts.items()):
                col.metric(q, n)
            st.dataframe(daily, use_container_width=True, height=360)

    with tabs[5]:
        st.subheader("Контекст для LLM")
        st.markdown(
            "Приложите этот файл к запросу в любую модель вместе с нужными CSV "
            "(обычно `nights.csv` + `daily_context.csv`). В нём — словарь всех колонок, "
            "сводные статистики, корреляции и правила, чтобы модель не выдумывала "
            "«марафоны без сна»."
        )
        md = build_llm_context(data)
        st.download_button("⬇️ llm_context.md", md.encode("utf-8"),
                           file_name="llm_context.md", mime="text/markdown")
        st.download_button("⬇️ Все таблицы одним .zip", _zip_bytes(dfs),
                           file_name="sleep_csv.zip", mime="application/zip")
        with st.expander("Показать llm_context.md"):
            st.markdown(md)


def _zip_bytes(dfs: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in dfs.items():
            z.writestr(f"{name}.csv", df.to_csv(index=False))
    return buf.getvalue()


if __name__ == "__main__":
    main()
