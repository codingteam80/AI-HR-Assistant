"""Regression checks for v8.8.112 announcement previews and width API."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_employee_announcement_moves_text_beside_large_image() -> None:
    source = _source("ui/pages/user/announcements_page.py")

    columns = source.index("image_column, content_column = st.columns(")
    content = source.index("with content_column:", columns)
    title = source.index('st.markdown(f"### {announcement.title}")', content)
    description = source.index("render_announcement_description(", title)
    image = source.index("with image_column:", description)

    assert columns < content < title < description < image
    assert "[1.05, 1.35]" in source
    assert "max_width=1200" in source
    assert "max_height=780" in source
    assert "fill_container=True" in source


def test_admin_preview_uses_the_same_two_column_layout() -> None:
    source = _source("ui/pages/admin/announcements_page.py")
    preview = source.split("def _render_preview(", 1)[1].split(
        "def _selected_index(", 1
    )[0]

    assert "image_column, content_column = st.columns(" in preview
    assert "[1.05, 1.35]" in preview
    assert 'st.markdown(f"### {announcement.title}")' in preview
    assert "render_announcement_description(" in preview
    assert "height=330" in preview
    assert "st.expander(" not in preview
    assert "fill_container=True" in preview


def test_fill_container_preserves_prepared_image_and_stretches_column() -> None:
    source = _source("ui/components/responsive_image.py")

    assert "fill_container: bool = False" in source
    assert "if fill_container:" in source
    assert 'width="stretch"' in source
    assert "prepared.thumbnail(" in source


def test_deprecated_container_width_argument_is_removed_from_runtime() -> None:
    runtime_roots = (
        ROOT / "app.py",
        ROOT / "ui",
        ROOT / "schemas" / "ui",
    )
    remaining = []

    for runtime_root in runtime_roots:
        paths = (
            [runtime_root]
            if runtime_root.is_file()
            else runtime_root.rglob("*.py")
        )
        for path in paths:
            if "use_container_width" in path.read_text(encoding="utf-8"):
                remaining.append(path.relative_to(ROOT).as_posix())

    assert remaining == []


def test_checkpoint_keeps_v88112_release_notes() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert (
        "v8.8.112 — Two-Column Announcement Previews and Width Migration"
        in readme
    )
