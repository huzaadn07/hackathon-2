"""Spending Analyzer: dashboard UI and frontend for the hackathon project.

Pipeline: app.py -> pdf_parser.py -> prompts.py -> gemma_agent.py
-> Gemma 4 -> app.py (display). Run with: python app.py
"""


import os
import csv
import io
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, cast

import streamlit as st
from streamlit import runtime




@dataclass(frozen=True)
class AppConfig:

    title: str = "Spending Analyzer"
    icon: str = "💰"
    max_file_mb: int = 10
    sample_options: tuple[str, ...] = ()
    currencies: tuple[str, ...] = ("£", "$", "€")




@dataclass(frozen=True)
class UserInput:

    kind: str
    value: Any

    @property
    def name(self) -> str:
        """Return the file name or the sample name."""
        if self.kind == "upload":
            return str(getattr(self.value, "name", "statement"))
        return str(self.value)




@dataclass(frozen=True)
class StepTiming:

    label: str
    seconds: float




@dataclass(frozen=True)
class PipelineStep:

    label: str
    func: Callable[[Any], Any]




@dataclass(frozen=True)
class PipelineResult:

    ok: bool
    output: Any = None
    error: str = ""
    timings: tuple[StepTiming, ...] = ()




class Pipeline:

    def __init__(self, steps: Iterable[PipelineStep]) -> None:
        
        self.steps: list[PipelineStep] = list(steps)


    def run(
        self,
        data: Any,
        on_start: Optional[Callable[[str], None]] = None,
        on_done: Optional[Callable[[str], None]] = None,
    ) -> PipelineResult:
        
        timings: list[StepTiming] = []
        for step in self.steps:
            if on_start is not None:
                on_start(step.label)
            started = time.perf_counter()
            try:
                data = step.func(data)
            except Exception as error:
                message = f"{step.label} failed: {error}"
                return PipelineResult(
                    False, error=message, timings=tuple(timings)
                )
            if self._is_empty(data):
                message = f"{step.label} returned nothing."
                return PipelineResult(
                    False, error=message, timings=tuple(timings)
                )
            timings.append(StepTiming(step.label, time.perf_counter() - started))
            if on_done is not None:
                on_done(step.label)
        return PipelineResult(True, output=data, timings=tuple(timings))


    @staticmethod
    def _is_empty(data: Any) -> bool:
        
        return data is None or (isinstance(data, str) and not data.strip())




class DemoSteps:
    # Build the path relative to this file or the current working directory
    file_path = os.path.join(os.path.dirname(__file__), "example_output.json") if "__file__" in locals() else "example_output.json"
    
    with open("example_output.json", "r", encoding="utf-8") as _file:
        DEMO_JSON = _file.read()


    @staticmethod
    def parse(source: Any) -> str:
        
        time.sleep(1)
        return "fake statement text"


    @staticmethod
    def prompt(text: str) -> str:
        
        time.sleep(1)
        return "fake prompt"


    @classmethod
    def analyze(cls, prompt: str) -> str:
        
        time.sleep(1)
        return cls.DEMO_JSON


    @classmethod
    def build(cls) -> list[PipelineStep]:
        
        return [
            PipelineStep("Reading the statement", cls.parse),
            PipelineStep("Building the prompt", cls.prompt),
            PipelineStep("Asking Gemma 4", cls.analyze),
        ]




class ResultParser:
    
    FENCE = "```"

    @classmethod
    def parse(cls, raw: Any) -> Any:
        
        if not isinstance(raw, str):
            return raw
        text = cls._strip_fences(raw.strip())
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return raw


    @classmethod
    def _strip_fences(cls, text: str) -> str:
        
        if not text.startswith(cls.FENCE):
            return text
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith(cls.FENCE):
            lines = lines[:-1]
        return "\n".join(lines).strip()




class Numbers:
    
    PATTERN = re.compile(
        r"^[£$€\s]*(-?[\d,]*\.?\d+)\s*(?:GBP|USD|EUR)?$", re.IGNORECASE
    )

    @classmethod
    def to_float(cls, value: Any) -> Optional[float]:
        
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = cls.PATTERN.match(value.strip())
            if match is None:
                return None
            return float(match.group(1).replace(",", ""))
        return None




@dataclass(frozen=True)
class CategoryRow:
    
    category: str
    spent: Optional[float] = None
    typical: Optional[float] = None
    note: str = ""


    @property
    def difference(self) -> Optional[float]:
        
        if self.spent is None or self.typical is None:
            return None
        return self.spent - self.typical


    @property
    def percent(self) -> Optional[float]:
        
        diff = self.difference
        if diff is None or not self.typical:
            return None
        return diff / self.typical * 100




@dataclass(frozen=True)
class Report:

    summary: str = ""
    total_spent: Optional[float] = None
    overspent: tuple[CategoryRow, ...] = ()
    underspent: tuple[CategoryRow, ...] = ()
    suggestions: tuple[str, ...] = ()
    extras: dict[str, Any] = field(default_factory=dict)


    @property
    def potential_savings(self) -> float:
        
        gaps = [row.difference for row in self.overspent]
        return float(sum(gap for gap in gaps if gap is not None and gap > 0))




class RowParser:
    
    NAME = ("category", "name", "label", "item", "area", "merchant")
    SPENT = ("spent", "amount", "actual", "total", "value", "current")
    TYPICAL = (
        "typical", "budget", "average", "expected", "baseline", "usual", "limit"
    )
    NOTE = ("note", "reason", "comment", "details", "explanation")


    @classmethod
    def parse(cls, value: Any) -> tuple[CategoryRow, ...]:
        
        if isinstance(value, list):
            items = cast(list[Any], value)
            return tuple(cls._row(None, item) for item in items)
        if isinstance(value, dict):
            mapping = cast(dict[Any, Any], value)
            return tuple(
                cls._row(str(key), item) for key, item in mapping.items()
            )
        if isinstance(value, str) and value.strip():
            return (CategoryRow(category=value.strip()),)
        return ()


    @classmethod
    def _row(cls, default_name: Optional[str], item: Any) -> CategoryRow:
        
        if isinstance(item, dict):
            raw = cast(dict[Any, Any], item)
            fields = {str(key).lower(): val for key, val in raw.items()}
            name = cls._first(fields, cls.NAME)
            return CategoryRow(
                category=str(name) if name else (default_name or "Unknown"),
                spent=Numbers.to_float(cls._first(fields, cls.SPENT)),
                typical=Numbers.to_float(cls._first(fields, cls.TYPICAL)),
                note=str(cls._first(fields, cls.NOTE) or ""),
            )
        number = Numbers.to_float(item)
        if number is not None and default_name:
            return CategoryRow(category=default_name, spent=number)
        text = str(item).strip()
        if default_name:
            return CategoryRow(category=default_name, note=text)
        return CategoryRow(category=text)


    @staticmethod
    def _first(fields: dict[str, Any], aliases: tuple[str, ...]) -> Any:
        
        for alias in aliases:
            if fields.get(alias) not in (None, ""):
                return fields[alias]
        return None




class ReportBuilder:
    
    SUMMARY = ("summary", "overview", "analysis")
    TOTAL = ("total_spent", "total", "total_spending")
    OVER = ("overspent", "overspending", "overspend", "over_budget", "categories")
    UNDER = ("underspent", "underspending", "underspend", "under_budget", "subscriptions")
    TIPS = ("suggestions", "recommendations", "cutbacks", "tips", "advice")


    @classmethod
    def build(cls, raw: Any) -> Report:
        
        data = ResultParser.parse(raw)
        if isinstance(data, str):
            return Report(summary=data.strip())
        if not isinstance(data, dict):
            return Report(extras={"result": data}) if data else Report()
        mapping = cast(dict[str, Any], data)
        used: set[str] = set()
        
        summary_val = cls._take(mapping, cls.SUMMARY, used)
        if isinstance(summary_val, dict):
            total = summary_val.get("total_spent")
            summary_text = f"Period: {summary_val.get('period', '')} | Total Income: {summary_val.get('total_income', 0)}"
        else:
            summary_text = str(summary_val).strip() if summary_val else ""
            total = cls._take(mapping, cls.TOTAL, used)

        over = cls._take(mapping, cls.OVER, used)
        under = cls._take(mapping, cls.UNDER, used)
        tips = cls._take(mapping, cls.TIPS, used)
        
        if not tips and isinstance(over, list):
            extracted_tips = []
            for item in over:
                if isinstance(item, dict) and "tips" in item:
                    extracted_tips.extend(item["tips"])
            if extracted_tips:
                tips = extracted_tips

        return Report(
            summary=summary_text,
            total_spent=Numbers.to_float(total) if total is not None else (summary_val.get("total_spent") if isinstance(summary_val, dict) else None),
            overspent=RowParser.parse(over),
            underspent=RowParser.parse(under),
            suggestions=cls._tips(tips),
            extras={k: v for k, v in mapping.items() if k not in used},
        )


    @staticmethod
    def _take(
        mapping: dict[str, Any], aliases: tuple[str, ...], used: set[str]
    ) -> Any:
        
        for key, value in mapping.items():
            if key.lower() in aliases and key not in used:
                used.add(key)
                return value
        return None


    @classmethod
    def _tips(cls, value: Any) -> tuple[str, ...]:
        
        if isinstance(value, str):
            return (value.strip(),) if value.strip() else ()
        if isinstance(value, list):
            items = cast(list[Any], value)
            texts = (cls._tip_text(item) for item in items)
            return tuple(text for text in texts if text)
        return ()


    @staticmethod
    def _tip_text(item: Any) -> str:
        
        if isinstance(item, dict):
            raw = cast(dict[Any, Any], item)
            parts = [
                str(v) for v in raw.values() if isinstance(v, (str, int, float))
            ]
            return " - ".join(parts)
        return str(item).strip()




@dataclass(frozen=True)
class Settings:
    
    currency: str
    sort_by: str
    flag_pct: int




@dataclass(frozen=True)
class RunRecord:
    
    run_id: int
    name: str
    finished_at: str
    seconds: float
    result: Any
    timings: tuple[StepTiming, ...]




class RunHistory:
    
    KEY = "run_history"
    COUNTER = "run_counter"
    SELECTED = "selected_run"


    @classmethod
    def all(cls) -> list[RunRecord]:
        
        return cast(list[RunRecord], st.session_state.setdefault(cls.KEY, []))


    @classmethod
    def add(
        cls, name: str, result: Any, timings: tuple[StepTiming, ...]
    ) -> RunRecord:
        
        run_id = int(st.session_state.get(cls.COUNTER, 0)) + 1
        st.session_state[cls.COUNTER] = run_id
        record = RunRecord(
            run_id=run_id,
            name=name,
            finished_at=datetime.now().strftime("%H:%M:%S"),
            seconds=sum(timing.seconds for timing in timings),
            result=result,
            timings=timings,
        )
        cls.all().append(record)
        st.session_state[cls.SELECTED] = run_id
        return record


    @classmethod
    def get(cls, run_id: Optional[int]) -> Optional[RunRecord]:
        
        for record in cls.all():
            if record.run_id == run_id:
                return record
        return None


    @classmethod
    def label(cls, run_id: Any) -> str:
        
        record = cls.get(run_id)
        if record is None:
            return str(run_id)
        return f"#{record.run_id} · {record.name} · {record.finished_at}"


    @classmethod
    def clear(cls) -> None:
        
        st.session_state.pop(cls.KEY, None)
        st.session_state.pop(cls.SELECTED, None)




class Sorter:
    
    MODES = ("Largest spend", "Largest difference", "Name")

    @classmethod
    def sort(cls, rows: Sequence[CategoryRow], mode: str) -> list[CategoryRow]:
        
        if mode == "Name":
            return sorted(rows, key=lambda row: row.category.lower())
        if mode == "Largest difference":
            return sorted(
                rows, key=lambda row: abs(row.difference or 0.0), reverse=True
            )
        return sorted(rows, key=lambda row: row.spent or 0.0, reverse=True)




class TableBuilder:
    
    CATEGORY = "Category"

    @classmethod
    def build(
        cls,
        rows: Sequence[CategoryRow],
        symbol: str,
        under: bool,
        flag_pct: int,
    ) -> list[dict[str, Any]]:
        
        label = "Under by" if under else "Over by"
        table: list[dict[str, Any]] = []
        for row in rows:
            diff = row.difference
            percent = row.percent
            entry: dict[str, Any] = {
                cls.CATEGORY: row.category,
                f"Spent ({symbol})": row.spent,
                f"Typical ({symbol})": row.typical,
                f"{label} ({symbol})": None if diff is None else round(abs(diff), 2),
                f"{label} %": None if percent is None else round(abs(percent), 1),
                "Note": row.note or None,
            }
            if not under and percent is not None:
                entry["Flag"] = "High" if percent >= flag_pct else "Watch"
            table.append(entry)
        return cls._drop_empty(table)


    @staticmethod
    def _drop_empty(table: list[dict[str, Any]]) -> list[dict[str, Any]]:
        
        columns = list(dict.fromkeys(key for entry in table for key in entry))
        keep = [
            column for column in columns
            if any(entry.get(column) is not None for entry in table)
        ]
        return [{column: entry.get(column) for column in keep} for entry in table]




class ChartBuilder:
    
    @classmethod
    def build(
        cls, rows: Sequence[CategoryRow], symbol: str
    ) -> Optional[dict[str, list[Any]]]:
        
        usable = [row for row in rows if row.spent is not None]
        if not usable:
            return None
        data: dict[str, list[Any]] = {
            TableBuilder.CATEGORY: [row.category for row in usable],
            f"Spent ({symbol})": [row.spent for row in usable],
        }
        if all(row.typical is not None for row in usable):
            data[f"Typical ({symbol})"] = [row.typical for row in usable]
        return data




class ReportExporter:
    
    @classmethod
    def markdown(cls, report: Report, symbol: str) -> str:
        
        lines = ["# Spending analysis", ""]
        if report.summary:
            lines += [report.summary, ""]
        if report.total_spent is not None:
            lines += [f"Total spent: {symbol}{report.total_spent:,.2f}", ""]
        lines += cls._section("Overspent", report.overspent, symbol)
        lines += cls._section("Underspent", report.underspent, symbol)
        if report.suggestions:
            lines += ["## Suggestions", ""]
            lines += [
                f"{index}. {tip}"
                for index, tip in enumerate(report.suggestions, start=1)
            ]
        return "\n".join(lines) + "\n"


    @classmethod
    def _section(
        cls, title: str, rows: Sequence[CategoryRow], symbol: str
    ) -> list[str]:
        
        if not rows:
            return []
        lines = [f"## {title}", ""]
        for row in rows:
            parts = [f"- {row.category}"]
            if row.spent is not None:
                parts.append(f"spent {symbol}{row.spent:,.2f}")
            if row.typical is not None:
                parts.append(f"typical {symbol}{row.typical:,.2f}")
            if row.note:
                parts.append(row.note)
            lines.append(": ".join(parts[:1]) + " " + ", ".join(parts[1:]))
        return lines + [""]


    @staticmethod
    def csv_text(report: Report) -> str:
        
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["type", "category", "spent", "typical", "difference", "note"]
        )
        groups = (("overspent", report.overspent), ("underspent", report.underspent))
        for kind, rows in groups:
            for row in rows:
                writer.writerow(
                    [kind, row.category, row.spent, row.typical,
                     row.difference, row.note]
                )
        return buffer.getvalue()




class InputPanel:
    
    UPLOAD_MODE = "Upload a PDF"
    SAMPLE_MODE = "Pick a sample"

    def __init__(
        self, max_file_mb: int, sample_options: Iterable[str]
    ) -> None:
        
        self.max_file_mb = max_file_mb
        self.sample_options: list[str] = list(sample_options)


    def render(self) -> Optional[UserInput]:
        
        if self._choose_mode() == self.SAMPLE_MODE:
            return self._render_sample()
        return self._render_upload()


    def _choose_mode(self) -> Optional[str]:
        
        if not self.sample_options:
            return self.UPLOAD_MODE
        return st.radio(
            "Choose your input",
            [self.UPLOAD_MODE, self.SAMPLE_MODE],
            horizontal=True,
        )


    def _render_sample(self) -> Optional[UserInput]:
        
        name = st.selectbox(
            "Sample statement",
            self.sample_options,
            index=None,
            placeholder="Choose a sample statement",
        )
        if name is None:
            return None
        return UserInput("sample", name)


    def _render_upload(self) -> Optional[UserInput]:
        
        file = st.file_uploader(
            "Upload your bank statement (PDF)", type=["pdf"]
        )
        if file is None:
            return None
        size_mb = file.size / (1024 * 1024)
        if size_mb > self.max_file_mb:
            st.error(
                f"That file is {size_mb:.1f} MB. "
                f"Please use one under {self.max_file_mb} MB."
            )
            return None
        st.success(f"Uploaded: {file.name} ({size_mb:.2f} MB)")
        return UserInput("upload", file)




class SettingsPanel:
    
    def __init__(self, currencies: tuple[str, ...]) -> None:
        
        self.currencies = currencies


    def render(self) -> Settings:
        
        with st.sidebar:
            st.header("Settings")
            currency = st.selectbox("Currency", list(self.currencies))
            sort_by = st.selectbox("Sort tables by", list(Sorter.MODES))
            flag_pct = st.slider("Flag overspending above (%)", 0, 100, 25)
        return Settings(
            currency=currency or self.currencies[0],
            sort_by=sort_by or Sorter.MODES[0],
            flag_pct=flag_pct,
        )




class HistoryPanel:
    
    @staticmethod
    def render() -> Optional[RunRecord]:
        
        records = RunHistory.all()
        if not records:
            return None
        with st.sidebar:
            st.header("Run history")
            ids = [record.run_id for record in reversed(records)]
            chosen = st.selectbox(
                "Open a run",
                ids,
                key=RunHistory.SELECTED,
                format_func=RunHistory.label,
            )
            st.button("Clear history", on_click=RunHistory.clear)
        return RunHistory.get(chosen)




class Dashboard:
    
    TABS = ["Overview", "Overspent", "Underspent", "Action plan", "Export and data"]

    def __init__(self, settings: Settings) -> None:
        
        self.settings = settings

    def render(self, record: RunRecord) -> None:
        
        report = ReportBuilder.build(record.result)
        if report == Report():
            st.error("The analysis came back empty. Please try again.")
            return
        st.divider()
        st.header("Your spending analysis")
        st.caption(
            f"Run #{record.run_id} · {self._safe(record.name)} · "
            f"{record.finished_at} · {record.seconds:.1f}s"
        )
        tabs = st.tabs(self.TABS)
        with tabs[0]:
            self._render_overview(report)
        with tabs[1]:
            self._render_rows(report.overspent, under=False)
        with tabs[2]:
            self._render_rows(report.underspent, under=True)
        with tabs[3]:
            self._render_plan(report, record.run_id)
        with tabs[4]:
            self._render_export(report, record)


    def _render_overview(self, report: Report) -> None:
        
        if report.summary:
            st.info(self._safe(report.summary))
        self._render_kpis(report)
        chart = ChartBuilder.build(report.overspent, self.settings.currency)
        if chart is not None:
            st.subheader("Spent vs typical: overspent categories")
            self._draw_chart(chart)

    def _render_kpis(self, report: Report) -> None:
        
        high = self._high_risk(report)
        savings = report.potential_savings
        first, second, third, fourth = st.columns(4)
        first.metric("Total spent", self._money(report.total_spent))
        second.metric(
            "Overspent categories",
            len(report.overspent),
            delta=f"{high} above {self.settings.flag_pct}%" if high else None,
            delta_color="inverse",
        )
        third.metric(
            "Potential savings", self._money(savings if savings > 0 else None)
        )
        fourth.metric("Suggestions", len(report.suggestions))


    def _render_rows(self, rows: Sequence[CategoryRow], under: bool) -> None:
        
        if not rows:
            st.info("Nothing was reported in this section.")
            return
        ordered = Sorter.sort(rows, self.settings.sort_by)
        chart = ChartBuilder.build(ordered, self.settings.currency)
        if chart is not None:
            self._draw_chart(chart)
        self._draw_table(
            TableBuilder.build(
                ordered, self.settings.currency, under, self.settings.flag_pct
            )
        )


    def _render_plan(self, report: Report, run_id: int) -> None:
        
        if not report.suggestions:
            st.info("No suggestions were returned.")
            return
        progress_slot = st.container()
        done = 0
        for index, tip in enumerate(report.suggestions):
            if st.checkbox(self._safe(tip), key=f"tip_{run_id}_{index}"):
                done += 1
        total = len(report.suggestions)
        with progress_slot:
            st.progress(done / total, text=f"{done} of {total} actions completed")


    def _render_export(self, report: Report, record: RunRecord) -> None:
        
        symbol = self.settings.currency
        has_rows = bool(report.overspent or report.underspent)
        first, second, third = st.columns(3)
        first.download_button(
            "Report (.md)",
            ReportExporter.markdown(report, symbol),
            file_name="spending_report.md",
            mime="text/markdown",
            key=f"md_{record.run_id}",
        )
        second.download_button(
            "Table (.csv)",
            ReportExporter.csv_text(report),
            file_name="spending_table.csv",
            mime="text/csv",
            disabled=not has_rows,
            key=f"csv_{record.run_id}",
        )
        third.download_button(
            "Raw (.json)",
            json.dumps(ResultParser.parse(record.result), indent=2, default=str),
            file_name="spending_raw.json",
            mime="application/json",
            key=f"json_{record.run_id}",
        )
        if report.extras:
            with st.expander("Other fields from the model", expanded=True):
                st.json(report.extras)
        with st.expander("Raw model output"):
            st.json(ResultParser.parse(record.result))
        with st.expander("Pipeline log"):
            for timing in record.timings:
                st.write(f"{timing.label}: {timing.seconds:.2f}s")


    def _draw_chart(self, data: dict[str, list[Any]]) -> None:
        
        value_columns = [name for name in data if name != TableBuilder.CATEGORY]
        st.bar_chart(  # pyright: ignore[reportUnknownMemberType]
            data, x=TableBuilder.CATEGORY, y=value_columns
        )


    def _draw_table(self, table: list[dict[str, Any]]) -> None:
        
        st.dataframe(  # pyright: ignore[reportUnknownMemberType]
            table, hide_index=True
        )


    def _high_risk(self, report: Report) -> int:
        
        percents = [row.percent for row in report.overspent]
        return sum(
            1 for pct in percents
            if pct is not None and pct >= self.settings.flag_pct
        )


    def _money(self, value: Optional[float]) -> str:
        
        if value is None:
            return "—"
        return f"{self.settings.currency}{value:,.2f}"


    @staticmethod
    def _safe(text: Any) -> str:
        
        return str(text).replace("$", "\\$")




class SpendingApp:

    def __init__(self, config: AppConfig, pipeline: Pipeline) -> None:
        
        self.config = config
        self.pipeline = pipeline
        self.input_panel = InputPanel(
            config.max_file_mb, config.sample_options
        )
        self.settings_panel = SettingsPanel(config.currencies)


    def run(self) -> None:
        
        self._configure_page()
        self._render_header()
        self._render_guide()
        settings = self.settings_panel.render()
        with st.container(border=True):
            user_input = self.input_panel.render()
            clicked = st.button(
                "Analyze my spending",
                type="primary",
                disabled=user_input is None,
            )
        if clicked and user_input is not None:
            self._analyze(user_input)
        record = HistoryPanel.render()
        if record is not None:
            Dashboard(settings).render(record)


    def _configure_page(self) -> None:
        
        st.set_page_config(
            page_title=self.config.title,
            page_icon=self.config.icon,
            layout="wide",
        )


    def _render_header(self) -> None:
        
        st.title(f"{self.config.icon} {self.config.title}")
        st.write(
            "Upload a bank statement and see where you overspent, "
            "where you underspent, and how to cut back."
        )
        st.caption(
            "Powered by Gemma 4, an open-weights model. Statement text is "
            "sent to the Gemini API, so use sample data for demos."
        )


    def _render_guide(self) -> None:
        
        with st.sidebar:
            st.header("How it works")
            st.markdown(
                "1. Upload a PDF or pick a sample\n"
                "2. Click **Analyze**\n"
                "3. Explore the tabs, tick off actions, export a report"
            )


    def _analyze(self, user_input: UserInput) -> None:
        
        with st.status("Running analysis...", expanded=True) as status:
            outcome = self.pipeline.run(
                user_input.value,
                on_start=lambda label: st.write(f"⏳ {label}..."),
                on_done=lambda label: st.write(f"✅ {label}"),
            )
            if outcome.ok:
                status.update(
                    label="Analysis complete", state="complete", expanded=False
                )
            else:
                status.update(label=outcome.error, state="error")
        if outcome.ok:
            RunHistory.add(user_input.name, outcome.output, outcome.timings)
        else:
            st.error(outcome.error)




class Launcher:
    
    @staticmethod
    def is_streamlit_running() -> bool:
        
        return runtime.exists()


    @staticmethod
    def relaunch() -> None:
        
        script = str(Path(__file__).resolve())
        command = [sys.executable, "-m", "streamlit", "run", script]
        try:
            subprocess.run(command, check=False)
        except KeyboardInterrupt:
            sys.exit(0)




def main() -> None:
    
    pipeline = Pipeline(DemoSteps.build())
    config = AppConfig(
        sample_options=("Sample statement A", "Sample statement B")
    )
    SpendingApp(config, pipeline).run()


if __name__ == "__main__":

    if Launcher.is_streamlit_running():
        main()
    else:
        Launcher.relaunch()

