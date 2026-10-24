

"""Spending Analyzer: UI and frontend for the hackathon project.

Pipeline: app.py -> pdf_parser.py -> prompts.py -> gemma_agent.py
-> Gemma 4 -> app.py (display). Run with: streamlit run app.py
"""
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

import streamlit as st


@dataclass(frozen=True)
class AppConfig:
    """Settings for the page, the upload limit and the sample dropdown."""

    title: str = "Spending Analyzer"
    icon: str = "💰"
    max_file_mb: int = 10
    sample_options: tuple = ()


@dataclass(frozen=True)
class UserInput:
    """What the user chose: kind is 'upload' or 'sample'."""

    kind: str
    value: Any


@dataclass(frozen=True)
class PipelineStep:
    """One pipeline step: a label to show and a function to call."""

    label: str
    func: Callable[[Any], Any]


@dataclass(frozen=True)
class PipelineResult:
    """Outcome of a pipeline run: ok flag, final output and error text."""

    ok: bool
    output: Any = None
    error: str = ""


class Pipeline:
    """Runs steps in order, passing each output to the next step.

    Contains no Streamlit code, so it can be tested on its own.
    """

    def __init__(self, steps):
        """Store the list of PipelineStep objects."""
        self.steps = list(steps)

    def run(self, data, on_start=None, on_done=None):
        """Run every step on data and return a PipelineResult.

        on_start and on_done are optional callbacks that receive the
        step label before and after each step.
        """
        for step in self.steps:
            if on_start is not None:
                on_start(step.label)
            try:
                data = step.func(data)
            except Exception as error:
                message = f"{step.label} failed: {error}"
                return PipelineResult(False, error=message)
            if self._is_empty(data):
                message = f"{step.label} returned nothing."
                return PipelineResult(False, error=message)
            if on_done is not None:
                on_done(step.label)
        return PipelineResult(True, output=data)

    @staticmethod
    def _is_empty(data):
        """Return True if data is None or a blank string."""
        return data is None or (isinstance(data, str) and not data.strip())


class DemoSteps:
    """Fake pipeline steps so the UI can be tested before integration."""

    DEMO_JSON = """```json
{
  "summary": "You spent most of your money on eating out this month.",
  "total_spent": 1420,
  "overspent": [
    {"category": "Eating out", "spent": 312, "typical": 200},
    {"category": "Subscriptions", "spent": 64, "typical": 30}
  ],
  "underspent": ["Groceries were lower than usual"],
  "suggestions": [
    "Cap takeaways at 6 a month",
    "Cancel unused subscriptions"
  ]
}
````"""

    @staticmethod
    def parse(source):
        """Pretend to extract text from the statement."""
        time.sleep(1)
        return "fake statement text"

    @staticmethod
    def prompt(text):
        """Pretend to build the prompt."""
        time.sleep(1)
        return "fake prompt"

    @classmethod
    def analyze(cls, prompt):
        """Pretend to ask Gemma 4 and return fenced JSON text."""
        time.sleep(1)
        return cls.DEMO_JSON

    @classmethod
    def build(cls):
        """Return the demo steps as a list of PipelineStep objects."""
        return [
            PipelineStep("Reading the statement", cls.parse),
            PipelineStep("Building the prompt", cls.prompt),
            PipelineStep("Asking Gemma 4", cls.analyze),
        ]


class ResultParser:
    """Converts the model output into Python data."""

    FENCE = "```"

    @classmethod
    def parse(cls, raw):
        """Return a dict or list from JSON text, or the original text."""
        if not isinstance(raw, str):
            return raw
        text = cls._strip_fences(raw.strip())
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return raw

    @classmethod
    def _strip_fences(cls, text):
        """Remove a surrounding ```json fence if the model added one."""
        if not text.startswith(cls.FENCE):
            return text
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith(cls.FENCE):
            lines = lines[:-1]
        return "\n".join(lines).strip()


class ResultStore:
    """Keeps the latest result in session state so reruns do not erase it."""

    KEY = "analysis_result"

    @classmethod
    def save(cls, result):
        """Save a result."""
        st.session_state[cls.KEY] = result

    @classmethod
    def get(cls):
        """Return the saved result, or None."""
        return st.session_state.get(cls.KEY)

    @classmethod
    def clear(cls):
        """Delete the saved result."""
        st.session_state.pop(cls.KEY, None)


class InputPanel:
    """Shows the upload box and, if samples are given, a dropdown."""

    UPLOAD_MODE = "Upload a PDF"
    SAMPLE_MODE = "Pick a sample"

    def __init__(self, max_file_mb, sample_options):
        """Store the file size limit and the list of sample names."""
        self.max_file_mb = max_file_mb
        self.sample_options = list(sample_options)

    def render(self):
        """Draw the input widgets and return a UserInput or None."""
        if self._choose_mode() == self.SAMPLE_MODE:
            return self._render_sample()
        return self._render_upload()

    def _choose_mode(self):
        """Return the chosen mode; uploads only when no samples exist."""
        if not self.sample_options:
            return self.UPLOAD_MODE
        return st.radio(
            "Choose your input",
            [self.UPLOAD_MODE, self.SAMPLE_MODE],
            horizontal=True,
        )

    def _render_sample(self):
        """Draw the sample dropdown and return the choice or None."""
        name = st.selectbox(
            "Sample statement",
            self.sample_options,
            index=None,
            placeholder="Choose a sample statement",
        )
        if name is None:
            return None
        return UserInput("sample", name)

    def _render_upload(self):
        """Draw the PDF uploader and return the file or None."""
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


class ResultView:
    """Turns the model's JSON into a readable page, whatever its shape."""

    METRICS_PER_ROW = 4

    def render(self, raw):
        """Parse the raw output and draw it with a download button."""
        result = ResultParser.parse(raw)
        if self._is_blank(result):
            st.error("The analysis came back empty. Please try again.")
            return
        st.divider()
        st.header("Your spending analysis")
        if isinstance(result, dict):
            self._render_dict(result)
        else:
            self._render_value(result)
        self._render_download(result)

    def _render_dict(self, result):
        """Show top-level text as callouts, numbers as metrics, rest in tabs."""
        scalars = {
            k: v for k, v in result.items()
            if not isinstance(v, (dict, list))
        }
        groups = {
            k: v for k, v in result.items() if isinstance(v, (dict, list))
        }
        self._render_scalars(scalars)
        self._render_groups(groups)

    def _render_scalars(self, scalars):
        """Draw text values as info boxes and numbers as metric tiles."""
        numbers = {k: v for k, v in scalars.items() if self._is_number(v)}
        for key, value in scalars.items():
            if self._is_number(value) or self._is_blank(value):
                continue
            st.info(f"**{self._title(key)}**\n\n{self._safe(value)}")
        items = list(numbers.items())
        for start in range(0, len(items), self.METRICS_PER_ROW):
            row = items[start:start + self.METRICS_PER_ROW]
            for column, (key, value) in zip(st.columns(len(row)), row):
                column.metric(self._title(key), value)

    def _render_groups(self, groups):
        """Draw lists and dicts directly, or in tabs when there are several."""
        if not groups:
            return
        if len(groups) == 1:
            key, value = next(iter(groups.items()))
            st.subheader(self._title(key))
            self._render_value(value)
            return
        tabs = st.tabs([self._title(key) for key in groups])
        for tab, value in zip(tabs, groups.values()):
            with tab:
                self._render_value(value)

    def _render_value(self, value):
        """Draw any value: dicts as headed sections, lists, or plain text."""
        if isinstance(value, dict):
            for key, item in value.items():
                st.markdown(f"**{self._safe(self._title(key))}**")
                self._render_value(item)
        elif isinstance(value, list):
            self._render_list(value)
        elif not self._is_blank(value):
            st.markdown(self._safe(value))

    def _render_list(self, items):
        """Draw a list of dicts as a table, otherwise as bullet points."""
        if items and all(isinstance(item, dict) for item in items):
            st.dataframe(items, hide_index=True)
            return
        for item in items:
            if isinstance(item, (dict, list)):
                self._render_value(item)
            else:
                st.markdown(f"- {self._safe(item)}")

    def _render_download(self, result):
        """Draw a button that downloads the result as JSON or Markdown."""
        if isinstance(result, str):
            data, name, mime = result, "spending_analysis.md", "text/markdown"
        else:
            data = json.dumps(result, indent=2, default=str)
            name, mime = "spending_analysis.json", "application/json"
        st.download_button(
            "Download results", data=data, file_name=name, mime=mime
        )

    @staticmethod
    def _is_blank(value):
        """Return True for None, empty text, empty list or empty dict."""
        return value in (None, "", [], {})

    @staticmethod
    def _is_number(value):
        """Return True for ints and floats, but not booleans."""
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _title(key):
        """Turn a key like 'total_spent' into 'Total Spent'."""
        return str(key).replace("_", " ").strip().title()

    @staticmethod
    def _safe(text):
        """Escape dollar signs so amounts are not shown as maths."""
        return str(text).replace("$", "\\$")


class SpendingApp:
    """Builds the page and connects the input, pipeline and results."""

    def __init__(self, config, pipeline):
        """Create the input panel and result view from the config."""
        self.config = config
        self.pipeline = pipeline
        self.input_panel = InputPanel(
            config.max_file_mb, config.sample_options
        )
        self.result_view = ResultView()

    def run(self):
        """Draw the whole page and handle the Analyze click."""
        self._configure_page()
        self._render_header()
        self._render_sidebar()
        with st.container(border=True):
            user_input = self.input_panel.render()
            clicked = st.button(
                "Analyze my spending",
                type="primary",
                disabled=user_input is None,
            )
        if clicked:
            self._analyze(user_input)
        saved = ResultStore.get()
        if saved is not None:
            self.result_view.render(saved)

    def _configure_page(self):
        """Set the browser tab title and icon; must run first."""
        st.set_page_config(
            page_title=self.config.title,
            page_icon=self.config.icon,
            layout="centered",
        )

    def _render_header(self):
        """Draw the title, tagline and privacy note."""
        st.title(f"{self.config.icon} {self.config.title}")
        st.write(
            "Upload a bank statement and see where you overspent, "
            "where you underspent, and how to cut back."
        )
        st.caption(
            "Powered by Gemma 4, an open-weights model. Statement text is "
            "sent to the Gemini API, so use sample data for demos."
        )

    def _render_sidebar(self):
        """Draw the how-it-works guide in the sidebar."""
        with st.sidebar:
            st.header("How it works")
            st.markdown(
                "1. Upload a PDF or pick a sample\n"
                "2. Click **Analyze**\n"
                "3. Read your results and download them"
            )

    def _analyze(self, user_input):
        """Run the pipeline with live progress, then save or show the result."""
        ResultStore.clear()
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
            ResultStore.save(outcome.output)
        else:
            st.error(outcome.error)


def main():
    """Build the pipeline and start the app.

    To integrate, replace DemoSteps.build() with a list of PipelineStep
    objects that point at the real functions in pdf_parser.py,
    prompts.py and gemma_agent.py.
    """
    pipeline = Pipeline(DemoSteps.build())
    config = AppConfig(
        sample_options=("Sample statement A", "Sample statement B")
    )
    SpendingApp(config, pipeline).run()


if __name__ == "__main__":
    main()



