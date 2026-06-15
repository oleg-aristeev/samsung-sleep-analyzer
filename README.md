# Samsung Sleep Tracker

Turn a **Samsung Health** data export (Galaxy Watch + Samsung Health app) into:

- 📄 **tidy CSV tables** about your sleep, ready for analysis or a spreadsheet;
- 📊 an **interactive Streamlit dashboard** (tables + charts you can re-run on new exports);
- 🤖 an **LLM-ready context pack** (`llm_context.md`) so you can ask any model a free-form
  question about your sleep and get an answer that isn't fooled by the data's quirks.

The headline feature is **honest data quality**. A wrist tracker doesn't record sleep while
it's on the charger — and a naive reading of the raw files mistakes "watch was off" for
"person was awake for 40 hours." This tool detects those gaps (using heart-rate coverage),
labels them explicitly, and ships those rules inside the LLM context so an AI doesn't
hallucinate "sleepless marathons" that never happened.

> ⚠️ **Not medical advice.** A consumer wearable is not a diagnostic device. This is data
> tooling, not a diagnosis.

---

## Install

Uses [uv](https://docs.astral.sh/uv/). No manual venv needed — `uv run` syncs dependencies
on first use.

```bash
git clone <your-repo-url> samsung-sleep-tracker
cd samsung-sleep-tracker
```

## Get your data

In the **Samsung Health** app: `Settings → Download personal data`. You'll receive a
`samsunghealth_<user>_<id>.zip`. Point the tool at that `.zip` (or at the unzipped folder).

## CLI — export to CSV

```bash
uv run samsung-sleep path/to/samsunghealth_export.zip -o output --html
```

Writes into `output/`:

| File | One row per | Use it for |
|------|-------------|------------|
| `sleep_sessions.csv` | sleep session | full detail: stages, scores, physiology, local times |
| `nights.csv` | "sleep day" (noon-to-noon) | trends + fragmentation (sessions count, longest continuous session), no double-counting |
| `daily_sleep.csv` | calendar day | "how much did I sleep on day X" + data-quality flag |
| `data_gaps.csv` | recording gap (>18 h) | spotting "watch was off" vs real wakefulness |
| `sleep_stages.csv` | hypnogram segment | per-night sleep architecture |
| `daily_context.csv` | calendar day | steps / workouts / naps to correlate with sleep |
| `watch_off_hours.csv` | hour with no data | driving the grey "watch off" band in the actogram |
| `llm_context.md` | — | **attach this to your LLM prompt** (data dictionary + rules) |

`--html` additionally builds `output/sleep_dashboard.html` (open in any browser).

Useful flags: `--rolling-days N`, `--sleep-day-boundary HOUR`, `--gap-min-hours H`.

## Streamlit — interactive dashboard

```bash
uv run streamlit run streamlit_app.py
```

Upload your `.zip` (or paste a local path), then explore tabs: **Overview** (key metrics
incl. sleep fragmentation), **Charts** (clean sleep map, stage actogram, sleep trend,
fragmentation, score, architecture, physiology, sleep-onset histogram), **Statistics**
(summary table, day→night correlations, a correlation heatmap, and a build-your-own
scatter), **Tables** (sortable, downloadable), **Data quality** (the gaps and why they
matter), and **LLM export** (preview + download the context pack and all CSVs).

Tune the processing with the sidebar sliders (sleep-day boundary, gap threshold, wear
thresholds, rolling window) — each one has an inline `?` explaining what it changes — then
hit **Применить / Apply** to recompute.

> **Fragmentation** is read straight from Samsung's own sessions, not reinvented from the
> hypnogram. `sessions_count` is how many separate sleep sessions the watch recorded that
> sleep-day (each one = you woke and fell back asleep), and `longest_block_min` is the
> longest single continuous session. The `awake` segments inside a session are Samsung's
> micro-arousals and are kept as detail only.

## Use with an LLM

Attach `llm_context.md` plus the CSVs you care about (usually `nights.csv` +
`daily_context.csv`, add `sleep_sessions.csv` for detail) and ask anything:
*"How did my sleep change over the period?"*, *"Does exercise correlate with deep sleep?"*,
*"Which nights look physiologically off?"* The context file tells the model what every
column means and which traps to avoid.

## Library API

```python
from samsung_sleep import Export, build_all, write_all, write_html

with Export("export.zip") as ex:      # also accepts a folder path or a file-like zip
    data = build_all(ex)              # -> SleepData (all tables as list[dict])

write_all(data, "output")             # CSVs + llm_context.md
write_html(data, "output/dash.html")  # standalone dashboard
```

## How it works

```
loader.py     read tables/JSON from a .zip or folder (handles the metadata header, BOM)
timeutils.py  UTC → local conversion (the offset lives in a separate column)
vitals.py     heart rate, HRV, breathing, SpO2, skin temperature per time window
transform.py  build_all() → sessions, nights, daily sleep, gaps, stages, context
              (fragmentation = Samsung's own session count + longest continuous session)
stats.py      summary statistics + day→night Pearson correlations (pure Python)
export.py     CSV writer + llm_context.md generator (now ships stats + correlations)
charts.py     plotly figures (shared by the CLI HTML export and Streamlit)
cli.py        the `samsung-sleep` command
```

Processing knobs live in [`config.py`](src/samsung_sleep/config.py) (`Config`).
The reverse-engineered format of the raw export is documented in
[`docs/DATA_GUIDE.md`](docs/DATA_GUIDE.md).

## Privacy

Your health export is personal data. The `.gitignore` keeps exports and all generated
output out of git by default — keep it that way before pushing anywhere public.

## License

MIT — see [LICENSE](LICENSE).
