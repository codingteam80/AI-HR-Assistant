"""v8.8.125 conversation placement and welcome-state regression checks."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHAT_PAGES = (
    "ui/pages/admin/chat_page.py",
    "ui/pages/user/chat_page.py",
)


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_conversation_container_is_reserved_before_chat_input() -> None:
    for relative_path in CHAT_PAGES:
        source = _source(relative_path)
        assert source.index("conversation_area = st.container()") < source.index(
            "question = st.chat_input("
        )
        assert source.count("with conversation_area:") >= 2


def test_first_submission_removes_display_only_welcome_immediately() -> None:
    for relative_path in CHAT_PAGES:
        source = _source(relative_path)
        question_block = source[source.index("        if question:") :]

        assert 'st.markdown("Good day, how can I assist you today?")' in source
        assert "welcome_placeholder = st.empty()" in source
        assert "if welcome_placeholder is not None:" in question_block
        assert "welcome_placeholder.empty()" in question_block
        assert question_block.index("welcome_placeholder.empty()") < question_block.index(
            'with st.chat_message("user"):'
        )


def test_pending_user_and_loading_render_inside_pre_input_area() -> None:
    for relative_path in CHAT_PAGES:
        source = _source(relative_path)
        question_block = source[source.index("        if question:") :]

        assert "with conversation_area:" in question_block
        assert question_block.index("with conversation_area:") < question_block.index(
            'with st.chat_message("user"):'
        )
        assert question_block.index('with st.chat_message("user"):') < question_block.index(
            'with st.chat_message("assistant"):'
        )
        assert "with st.spinner(" in question_block


def test_v88125_checkpoint_is_documented() -> None:
    readme = _source("README.md")

    assert "v8.8.125 — Conversation Above Input and Immediate Welcome Removal" in readme
