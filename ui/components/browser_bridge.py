"""Invisible Streamlit 1.61 iframe bridge for trusted browser-side scripts.

The project uses small, code-owned JavaScript helpers for refresh-safe auth,
theme compatibility, document printing, and notification tab routing.  This
module keeps those helpers out of the visible page layout while using the
supported ``st.iframe`` API instead of deprecated V1 components.
"""

import streamlit as st


_HIDDEN_FRAME_BOOTSTRAP = """
<style>
html, body {
    width: 0 !important;
    height: 0 !important;
    min-width: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
    background: transparent !important;
}
</style>
<script>
(() => {
    const frame = window.frameElement;
    if (!frame) {
        return;
    }

    frame.setAttribute('aria-hidden', 'true');
    frame.setAttribute('tabindex', '-1');

    const elementContainer = frame.closest(
        '[data-testid="stElementContainer"]'
    );
    const hiddenTarget = elementContainer || frame;
    hiddenTarget.style.setProperty('display', 'none', 'important');
    hiddenTarget.style.setProperty('width', '0', 'important');
    hiddenTarget.style.setProperty('height', '0', 'important');
    hiddenTarget.style.setProperty('margin', '0', 'important');
    hiddenTarget.style.setProperty('padding', '0', 'important');
})();
</script>
"""


def render_browser_bridge(trusted_html: str) -> None:
    """Execute trusted internal HTML/JS without adding visible page space.

    Streamlit 1.61 requires positive numeric iframe dimensions. A temporary
    1×1 frame is therefore used, then its complete Streamlit element container
    is hidden immediately by the bootstrap above. This preserves the previous
    zero-height component behavior and the approved project layout.
    """

    if not trusted_html.strip():
        return

    st.iframe(
        _HIDDEN_FRAME_BOOTSTRAP + trusted_html,
        width=1,
        height=1,
        tab_index=-1,
    )
