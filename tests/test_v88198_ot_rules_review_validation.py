"""v8.8.198 OT/Shifting rules review-confirmation guard checks."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ATTENDANCE_UI = ROOT / "ui" / "pages" / "admin" / "attendance_dashboard.py"


def _source() -> str:
    return ATTENDANCE_UI.read_text(encoding="utf-8")


def test_ot_rules_require_review_before_save() -> None:
    source = _source()
    assert "from ui.components.confirmation_guard import (" in source
    assert "invalidate_confirmation_on_change," in source
    assert "clear_confirmation_tracking," in source
    assert '"I reviewed and validated the OT & Shifting Credits rules."' in source
    assert "disabled=not confirm_ot_rules" in source
    assert "if save_ot_rules:" in source
    assert "clear_confirmation_tracking(confirmation_key)" in source


def test_ot_rules_confirmation_tracks_every_editable_rule() -> None:
    source = _source()
    expected_dependencies = (
        '"shifting_credits_enabled": shifting_enabled_value',
        '"dinner_break_deduction_hours": dinner_deduction_value',
        '"shifting_credit_block_hours": shifting_block_value',
        '"shifting_credit_required_blocks": int(required_blocks_value)',
        '"shifting_credit_cutoff_day": int(cutoff_day_value)',
        '"additional_vl_threshold_hours": vl_threshold_value',
        '"additional_vl_days": additional_vl_value',
        '"excluded_positions": tuple(',
    )
    for dependency in expected_dependencies:
        assert dependency in source

    # The reusable guard must run before the checkbox is instantiated so it
    # can safely reset an already-checked review when any dependency changes.
    guard_index = source.index("invalidate_confirmation_on_change(", source.index("OT & Shifting Credits Rules"))
    checkbox_index = source.index('"I reviewed and validated the OT & Shifting Credits rules."')
    assert guard_index < checkbox_index


def test_ot_rules_review_checkbox_avoids_streamlit_default_state_collision() -> None:
    source = _source()
    checkbox_label = '"I reviewed and validated the OT & Shifting Credits rules."'
    start = source.index(checkbox_label)
    block = source[start : source.index("save_ot_rules = st.button", start)]
    assert "value=" not in block
    assert "key=confirmation_key" in block
    assert "Any change to the OT or Shifting Credits settings" in block


def test_confirmation_guard_actually_unchecks_when_a_rule_changes(monkeypatch) -> None:
    import importlib.util
    import sys
    from types import ModuleType

    fake_streamlit = ModuleType("streamlit")
    fake_streamlit.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    guard_path = ROOT / "ui" / "components" / "confirmation_guard.py"
    spec = importlib.util.spec_from_file_location("v88198_confirmation_guard", guard_path)
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)

    confirmation_key = "company_ot_shifting_rules_1_reviewed"
    original = {
        "shifting_credits_enabled": True,
        "dinner_break_deduction_hours": 0.75,
        "shifting_credit_block_hours": 4.0,
        "shifting_credit_required_blocks": 2,
        "shifting_credit_cutoff_day": 15,
        "additional_vl_threshold_hours": 8.0,
        "additional_vl_days": 0.5,
        "excluded_positions": ("DE1", "DE2", "Trainee"),
    }

    assert not guard.invalidate_confirmation_on_change(
        confirmation_key=confirmation_key,
        dependencies=original,
    )
    fake_streamlit.session_state[confirmation_key] = True

    assert not guard.invalidate_confirmation_on_change(
        confirmation_key=confirmation_key,
        dependencies=dict(original),
    )
    assert fake_streamlit.session_state[confirmation_key] is True

    changed = dict(original)
    changed["dinner_break_deduction_hours"] = 0.5
    assert guard.invalidate_confirmation_on_change(
        confirmation_key=confirmation_key,
        dependencies=changed,
    )
    assert fake_streamlit.session_state[confirmation_key] is False


def test_v88198_version_marker() -> None:
    settings = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
    assert 'app_version: str = "0.8.8.198"' in settings
