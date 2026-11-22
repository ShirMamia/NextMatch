"""Exercise the public sample through the normal Streamlit entry point."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_sample_loads_and_displays_a_match() -> None:
    entry_point = Path(__file__).resolve().parents[1] / "app" / "ui" / "main.py"
    app = AppTest.from_file(str(entry_point), default_timeout=20).run()
    assert not app.exception

    app.sidebar.button(key="load_sample_data").click().run()
    assert not app.exception
    assert app.session_state["candidate_profile"].name == "Alex Example"
    assert len(app.session_state["job_postings"]) == 2

    app.sidebar.radio[0].set_value("Tailoring Studio").run()
    assert not app.exception
    assert app.session_state["match_result"].score_breakdown.overall_score > 0
    assert any("Match: Alex Example" in heading.value for heading in app.subheader)
