"""Regression tests for safe single/multi-file policy upload state."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    """Read the administrator Policies page source."""

    return (
        PROJECT_ROOT
        / "ui/pages/admin/policies_page.py"
    ).read_text(encoding="utf-8")


def _upload_block() -> str:
    source = _source()
    return source.split(
        "def _render_upload(",
        1,
    )[1].split(
        "def _render_edit_policy_details(",
        1,
    )[0]


def test_upload_uses_generation_specific_multi_file_key() -> None:
    """The uploader remounts after a completed batch and accepts many files."""

    source = _source()
    block = _upload_block()

    assert '_POLICY_UPLOAD_NONCE_STATE_KEY' in source
    assert '_POLICY_UPLOAD_WIDGET_PREFIX' in source
    assert 'def _policy_upload_widget_key(' in source
    assert 'accept_multiple_files=True' in block
    assert (
        'key=_policy_upload_widget_key(\n'
        '            upload_nonce,\n'
        '            "file",'
        in block
    )


def test_all_generated_batch_controls_share_the_nonce() -> None:
    """Every stateful per-file control is generation-scoped and unique."""

    block = _upload_block()

    for name in [
        'f"version_linking_{selection_fingerprint}_{file_index}"',
        'f"title_{fingerprint}"',
        'f"category_{fingerprint}"',
        'f"version_{fingerprint}"',
        'f"date_{fingerprint}"',
        '"submit"',
    ]:
        assert name in block

    assert "upload-history-" in block
    assert "{fingerprint}-{file_index}" in block


def test_batch_processing_is_independent_per_file() -> None:
    """A failed document must not roll back successful files in the batch."""

    block = _upload_block()

    loop_position = block.index("for item in prepared:")
    session_position = block.index("with SessionFactory() as session:", loop_position)
    create_position = block.index("create_policy_from_upload(", session_position)
    validation_position = block.index("except ValidationError as error:", create_position)
    value_error_position = block.index("except ValueError as error:", validation_position)
    generic_position = block.index("except Exception:", value_error_position)

    assert loop_position < session_position < create_position
    assert create_position < validation_position < value_error_position < generic_position
    assert 'failures.append(' in block[validation_position:]
    assert '_POLICY_UPLOAD_RESULT_STATE_KEY' in block


def test_attempted_batch_advances_state_before_rerun() -> None:
    """Completed attempts remount the uploader so successes cannot resubmit."""

    block = _upload_block()

    result_position = block.index(
        "st.session_state[_POLICY_UPLOAD_RESULT_STATE_KEY]"
    )
    advance_position = block.index(
        "_advance_policy_upload_state(upload_nonce)",
        result_position,
    )
    rerun_position = block.index("st.rerun()", advance_position)

    assert result_position < advance_position < rerun_position


def test_old_upload_widget_keys_are_cleaned_before_render() -> None:
    """Previous generations must not accumulate in session state."""

    source = _source()
    block = _upload_block()

    assert "def _cleanup_old_policy_upload_state(" in source
    assert "st.session_state.pop(key, None)" in source

    cleanup_position = block.index(
        "_cleanup_old_policy_upload_state(upload_nonce)"
    )
    uploader_position = block.index("st.file_uploader(")

    assert cleanup_position < uploader_position


def test_upload_empty_state_supports_one_or_more_files() -> None:
    """A fresh multi-file uploader hides previews until files are selected."""

    block = _upload_block()

    assert "if not uploaded_files:" in block
    assert (
        "Choose one or more files to generate titles, category suggestions, "
        in block
    )
    assert "version history" in block
    assert "document previews" in block
