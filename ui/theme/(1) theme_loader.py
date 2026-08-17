"""Apply the centralized light or dark UI theme.

Purpose:
- Convert shared design tokens into global CSS variables.
- Keep the Streamlit sidebar permanently expanded.
- Ensure text, labels, inputs, forms, alerts, and buttons remain readable
  in both light and dark modes.

Debugging note:
When a Streamlit upgrade changes widget appearance, inspect the browser's
data-testid attributes and update only the widget selector section below.
"""

import streamlit as st

from ui.components.browser_bridge import render_browser_bridge
from ui.theme.design_tokens import DARK_THEME, LIGHT_THEME
from ui.theme.theme_state import get_active_theme


# Fallback values protect the UI when a future theme dictionary is missing
# one or more optional tokens.
_REQUIRED_DEFAULTS: dict[str, str] = {
    "background": "#F7F9FC",
    "surface": "#FFFFFF",
    "surface_secondary": "#F3F5FA",
    "text_primary": "#10172A",
    "text_secondary": "#5C6680",
    "primary": "#4338E8",
    "primary_hover": "#372FD0",
    "primary_soft": "#EEF0FF",
    "border": "#E3E7F0",
    "success": "#18B66A",
    "warning": "#F5A623",
    "danger": "#E05252",
    "shadow": "0 8px 30px rgba(24, 36, 74, 0.08)",
}


def _get_theme_tokens() -> dict[str, str]:
    """Return a complete token set for the active theme."""

    selected_theme = (
        DARK_THEME
        if get_active_theme() == "dark"
        else LIGHT_THEME
    )

    # Selected values override defaults while missing keys remain safe.
    return {
        **_REQUIRED_DEFAULTS,
        **selected_theme,
    }




def _synchronize_theme_with_browser(
    active_theme: str,
) -> None:
    """Synchronize URL theme state with browser localStorage.

    The browser stores only the value ``light`` or ``dark``. No account,
    password, company, or employee information is written to localStorage.
    """

    # A template replacement avoids Python f-string conflicts with
    # JavaScript braces.
    script = """
        <script>
        (() => {
            const storageKey = "ai_hr_assistant_theme";
            const activeTheme = "__ACTIVE_THEME__";
            const validThemes = new Set(["light", "dark"]);
            const parentWindow = window.parent;
            const currentUrl = new URL(parentWindow.location.href);
            const urlTheme = currentUrl.searchParams.get("theme");

            let savedTheme = null;

            try {
                savedTheme = parentWindow.localStorage.getItem(
                    storageKey
                );
            } catch (error) {
                // URL persistence still works when storage is disabled.
            }

            if (validThemes.has(urlTheme)) {
                try {
                    parentWindow.localStorage.setItem(
                        storageKey,
                        urlTheme
                    );
                } catch (error) {
                    // Safe to ignore blocked browser storage.
                }
                return;
            }

            if (
                validThemes.has(savedTheme)
                && savedTheme !== activeTheme
            ) {
                currentUrl.searchParams.set("theme", savedTheme);

                // Reload once so Python receives the restored theme.
                parentWindow.location.replace(
                    currentUrl.toString()
                );
                return;
            }

            try {
                parentWindow.localStorage.setItem(
                    storageKey,
                    activeTheme
                );
            } catch (error) {
                // The query parameter remains the fallback.
            }

            currentUrl.searchParams.set("theme", activeTheme);

            // Update the address without triggering another rerun.
            parentWindow.history.replaceState(
                null,
                "",
                currentUrl.toString()
            );
        })();
        </script>
    """.replace("__ACTIVE_THEME__", active_theme)

    render_browser_bridge(script)

def _enforce_input_value_contrast() -> None:
    """Force white input values after Streamlit/BaseWeb finishes rendering.

    Why this exists:
    Streamlit uses runtime-generated BaseWeb/Emotion classes. In some
    versions, those classes are inserted after custom CSS and override
    input text colors. The MutationObserver reapplies only visual styles
    to input elements and does not read or transmit their values.
    """

    render_browser_bridge(
        """
        <script>
        (() => {
            const parentDocument = window.parent.document;

            const styleInputs = () => {
                const selectors = [
                    '[data-testid="stTextInput"] input',
                    '[data-testid="stNumberInput"] input',
                    'input[aria-label="Company Code"]',
                    'input[aria-label="Username or Email"]',
                    'input[aria-label="Password"]',
                    'input[aria-label="Current Password"]',
                    'input[aria-label="New Password"]',
                    'input[aria-label="Confirm New Password"]'
                ];

                parentDocument
                    .querySelectorAll(selectors.join(','))
                    .forEach((input) => {
                        input.style.setProperty(
                            'color',
                            '#FFFFFF',
                            'important'
                        );
                        input.style.setProperty(
                            '-webkit-text-fill-color',
                            '#FFFFFF',
                            'important'
                        );
                        input.style.setProperty(
                            'caret-color',
                            '#FFFFFF',
                            'important'
                        );
                        input.style.setProperty(
                            'background-color',
                            'transparent',
                            'important'
                        );
                        input.style.setProperty(
                            'color-scheme',
                            'dark',
                            'important'
                        );
                        input.style.setProperty(
                            'text-shadow',
                            'none',
                            'important'
                        );

                        const container = input.closest(
                            '[data-baseweb="input"],'
                            + '[data-baseweb="base-input"]'
                        );

                        if (container) {
                            container.style.setProperty(
                                'background-color',
                                '#252630',
                                'important'
                            );
                            container.style.setProperty(
                                'color-scheme',
                                'dark',
                                'important'
                            );
                        }
                    });
            };

            styleInputs();

            const observer = new MutationObserver(styleInputs);

            observer.observe(
                parentDocument.body,
                {
                    childList: true,
                    subtree: true,
                    attributes: true,
                    attributeFilter: ['class', 'style', 'value']
                }
            );

            parentDocument.addEventListener(
                'focusin',
                styleInputs,
                true
            );
            parentDocument.addEventListener(
                'input',
                styleInputs,
                true
            );
        })();
        </script>
        """
    )

def apply_theme() -> None:
    """Inject global CSS for layout, widgets, and theme contrast."""

    tokens = _get_theme_tokens()

    css = f"""
    <style>
    /* =========================================================
       SHARED DESIGN VARIABLES
    ========================================================= */
    :root {{
        --hr-bg: {tokens["background"]};
        --hr-surface: {tokens["surface"]};
        --hr-surface-secondary: {tokens["surface_secondary"]};
        --hr-text-primary: {tokens["text_primary"]};
        --hr-text-secondary: {tokens["text_secondary"]};
        --hr-primary: {tokens["primary"]};
        --hr-primary-hover: {tokens["primary_hover"]};
        --hr-primary-soft: {tokens["primary_soft"]};
        --hr-border: {tokens["border"]};
        --hr-success: {tokens["success"]};
        --hr-warning: {tokens["warning"]};
        --hr-danger: {tokens["danger"]};
        --hr-shadow: {tokens["shadow"]};
    }}

    /* =========================================================
       APPLICATION BACKGROUND AND DEFAULT TEXT
    ========================================================= */
    html,
    body,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {{
        background: var(--hr-bg) !important;
        color: var(--hr-text-primary) !important;
    }}

    [data-testid="stHeader"] {{
        background: transparent !important;
    }}

    /* Headings and normal markdown must follow the current theme. */
    h1,
    h2,
    h3,
    h4,
    h5,
    h6,
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stCaptionContainer"] {{
        color: var(--hr-text-primary);
    }}

    /* =========================================================
       PERMANENT SIDEBAR
    ========================================================= */
    section[data-testid="stSidebar"] {{
        position: fixed !important;
        inset: 0 auto 0 0 !important;

        width: 285px !important;
        min-width: 285px !important;
        max-width: 285px !important;
        height: 100vh !important;

        margin-left: 0 !important;
        transform: translateX(0) !important;
        visibility: visible !important;

        background: var(--hr-surface) !important;
        border-right: 1px solid var(--hr-border) !important;

        overflow-y: auto !important;
        overflow-x: hidden !important;

        z-index: 999 !important;
        transition: none !important;
    }}

    section[data-testid="stSidebar"][aria-expanded="false"],
    section[data-testid="stSidebar"][aria-expanded="true"] {{
        left: 0 !important;
        margin-left: 0 !important;
        transform: translateX(0) !important;

        width: 285px !important;
        min-width: 285px !important;
        max-width: 285px !important;
    }}

    section[data-testid="stSidebar"] > div,
    [data-testid="stSidebarContent"] {{
        width: 285px !important;
        min-width: 285px !important;
        max-width: 285px !important;
    }}

    /* Hide collapse/open controls across supported Streamlit versions. */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarHeader"] button,
    button[data-testid="stBaseButton-headerNoPadding"],
    button[kind="header"],
    button[aria-label="Close sidebar"],
    button[aria-label="Open sidebar"],
    button[title="Close sidebar"],
    button[title="Open sidebar"] {{
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;

        width: 0 !important;
        min-width: 0 !important;
        max-width: 0 !important;
        height: 0 !important;
        min-height: 0 !important;

        padding: 0 !important;
        margin: 0 !important;
        pointer-events: none !important;
    }}

    /* Keep the main application beside the fixed sidebar. */
    [data-testid="stAppViewContainer"] > .main,
    [data-testid="stMain"] {{
        margin-left: 285px !important;
        width: calc(100% - 285px) !important;
        max-width: calc(100% - 285px) !important;
    }}

    .block-container {{
        max-width: 1500px;
        padding: 1.2rem 2rem 2rem;
    }}

    /* =========================================================
       FORM AND INPUT CONTRAST
       These rules fix invisible labels in light mode.
    ========================================================= */

    /* Streamlit widget labels, including text-input labels. */
    [data-testid="stWidgetLabel"],
    [data-testid="stWidgetLabel"] p,
    [data-testid="stTextInput"] label,
    [data-testid="stTextInput"] label p,
    [data-testid="stSelectbox"] label,
    [data-testid="stSelectbox"] label p,
    [data-testid="stTextArea"] label,
    [data-testid="stTextArea"] label p,
    [data-testid="stNumberInput"] label,
    [data-testid="stNumberInput"] label p {{
        color: var(--hr-text-primary) !important;
        opacity: 1 !important;
        font-weight: 600 !important;
    }}

    /*
       Text, password, number, select, and textarea surfaces.

       Streamlit versions may use either data-baseweb="input" or
       data-baseweb="base-input". Both are targeted so the light theme
       cannot retain Streamlit's dark default input surface.
    */
    [data-testid="stTextInput"] div[data-baseweb="input"],
    [data-testid="stTextInput"] div[data-baseweb="base-input"],
    [data-testid="stNumberInput"] div[data-baseweb="input"],
    [data-testid="stNumberInput"] div[data-baseweb="base-input"],
    [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
    [data-testid="stTextArea"] div[data-baseweb="textarea"],
    [data-testid="stTextArea"] textarea {{
        color: var(--hr-text-primary) !important;
        background-color: var(--hr-surface) !important;
        background: var(--hr-surface) !important;
        border-color: var(--hr-border) !important;
        border-radius: 10px !important;
        color-scheme: {"dark" if get_active_theme() == "dark" else "light"};
    }}

    /*
       Force the editable value to use the active theme color.
       The generic form selector is intentional because some Streamlit
       releases place the input outside the expected data-baseweb wrapper.
    */
    [data-testid="stTextInput"] input,
    [data-testid="stTextInput"] input[type="text"],
    [data-testid="stTextInput"] input[type="password"],
    [data-testid="stNumberInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stForm"] input,
    [data-testid="stForm"] textarea {{
        color: var(--hr-text-primary) !important;
        background-color: transparent !important;
        background: transparent !important;
        caret-color: var(--hr-primary) !important;
        -webkit-text-fill-color: var(--hr-text-primary) !important;
        opacity: 1 !important;
    }}

    /* Browser autofill can otherwise restore a dark background or text. */
    [data-testid="stTextInput"] input:-webkit-autofill,
    [data-testid="stTextInput"] input:-webkit-autofill:hover,
    [data-testid="stTextInput"] input:-webkit-autofill:focus,
    [data-testid="stForm"] input:-webkit-autofill {{
        -webkit-text-fill-color: var(--hr-text-primary) !important;
        -webkit-box-shadow: 0 0 0 1000px var(--hr-surface) inset !important;
        box-shadow: 0 0 0 1000px var(--hr-surface) inset !important;
        caret-color: var(--hr-primary) !important;
    }}

    [data-testid="stTextInput"] input::placeholder,
    [data-testid="stNumberInput"] input::placeholder,
    [data-testid="stTextArea"] textarea::placeholder,
    [data-testid="stForm"] input::placeholder {{
        color: var(--hr-text-secondary) !important;
        opacity: 0.75 !important;
        -webkit-text-fill-color: var(--hr-text-secondary) !important;
    }}

    /* Password visibility and help icons must be visible in both modes. */
    [data-testid="stTextInput"] button,
    [data-testid="stTooltipIcon"],
    [data-testid="stTooltipIcon"] svg,
    [data-baseweb="input"] svg {{
        color: var(--hr-text-secondary) !important;
        fill: currentColor !important;
    }}

    /* Focus state uses the shared primary color instead of default red. */
    [data-testid="stTextInput"] div[data-baseweb="input"]:focus-within,
    [data-testid="stNumberInput"] div[data-baseweb="input"]:focus-within,
    [data-testid="stTextArea"] textarea:focus,
    [data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within {{
        border-color: var(--hr-primary) !important;
        box-shadow: 0 0 0 1px var(--hr-primary) !important;
    }}

    /* Give Streamlit forms a theme-aware card surface. */
    [data-testid="stForm"] {{
        color: var(--hr-text-primary) !important;
        background: var(--hr-surface) !important;
        border: 1px solid var(--hr-border) !important;
        border-radius: 14px !important;
        box-shadow: var(--hr-shadow) !important;
    }}

    /* =========================================================
       ALERTS
       Prevent pale warning text from disappearing in light mode.
    ========================================================= */
    [data-testid="stAlert"],
    [data-testid="stAlert"] *,
    [data-testid="stNotification"],
    [data-testid="stNotification"] * {{
        color: var(--hr-text-primary) !important;
    }}

    /* =========================================================
       SHARED HR COMPONENTS
    ========================================================= */
    .hr-topbar {{
        display: flex;
        align-items: center;
        justify-content: space-between;

        margin-bottom: 20px;
        padding: 16px 20px;

        background: var(--hr-surface);
        border: 1px solid var(--hr-border);
        border-radius: 18px;
        box-shadow: var(--hr-shadow);
    }}

    .hr-card {{
        min-height: 112px;
        padding: 18px;

        background: var(--hr-surface);
        border: 1px solid var(--hr-border);
        border-radius: 14px;
        box-shadow: var(--hr-shadow);
    }}

    .hr-placeholder {{
        padding: 34px;

        color: var(--hr-text-secondary);
        text-align: center;

        background: var(--hr-surface);
        border: 1px dashed var(--hr-border);
        border-radius: 18px;
        box-shadow: var(--hr-shadow);
    }}

    .hr-brand {{
        color: var(--hr-primary);
        font-size: 1.25rem;
        font-weight: 750;
    }}

    .hr-card-title,
    .hr-title {{
        margin-bottom: 8px;
        color: var(--hr-text-primary);
        font-weight: 700;
    }}

    .hr-card-text,
    .hr-muted {{
        color: var(--hr-text-secondary);
    }}

    /* =========================================================
       BUTTONS
    ========================================================= */

    /* Standard secondary buttons. */
    div.stButton > button {{
        color: var(--hr-text-primary);
        background: var(--hr-surface);
        border: 1px solid var(--hr-border);
        border-radius: 12px;
    }}

    div.stButton > button:hover {{
        color: var(--hr-primary);
        border-color: var(--hr-primary);
    }}

    /* Primary and form-submit buttons use the project accent color. */
    button[kind="primary"],
    [data-testid="stFormSubmitButton"] button {{
        color: #FFFFFF !important;
        background: var(--hr-primary) !important;
        border-color: var(--hr-primary) !important;
        border-radius: 10px !important;
    }}

    /* Streamlit places button text inside nested paragraph/span elements. */
    button[kind="primary"] *,
    [data-testid="stFormSubmitButton"] button * {{
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }}

    button[kind="primary"]:hover,
    [data-testid="stFormSubmitButton"] button:hover {{
        color: #FFFFFF !important;
        background: var(--hr-primary-hover) !important;
        border-color: var(--hr-primary-hover) !important;
    }}

    div[data-testid="stChatInput"] {{
        background: var(--hr-surface);
        border-radius: 16px;
    }}

    /* =========================================================
       RESPONSIVE WIDTH
    ========================================================= */
    @media (max-width: 900px) {{
        section[data-testid="stSidebar"],
        section[data-testid="stSidebar"] > div,
        [data-testid="stSidebarContent"] {{
            width: 250px !important;
            min-width: 250px !important;
            max-width: 250px !important;
        }}

        [data-testid="stAppViewContainer"] > .main,
        [data-testid="stMain"] {{
            margin-left: 250px !important;
            width: calc(100% - 250px) !important;
            max-width: calc(100% - 250px) !important;
        }}
    }}



    /* =========================================================
       FINAL INPUT VALUE OVERRIDE — v5.4
       Purpose:
       Keep input surfaces dark and entered values white in both
       themes, including focus, selection, and autofill states.
    ========================================================= */

    [data-testid="stTextInput"] div[data-baseweb="input"],
    [data-testid="stTextInput"] div[data-baseweb="base-input"],
    [data-testid="stNumberInput"] div[data-baseweb="input"],
    [data-testid="stNumberInput"] div[data-baseweb="base-input"] {{
        background: #252630 !important;
        background-color: #252630 !important;
        color-scheme: dark !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }}

    [data-testid="stTextInput"] input,
    [data-testid="stTextInput"] input:focus,
    [data-testid="stTextInput"] input:active,
    [data-testid="stTextInput"] input:hover,
    [data-testid="stTextInput"] input:valid,
    [data-testid="stTextInput"] input:invalid,
    [data-testid="stTextInput"] input:read-only,
    [data-testid="stNumberInput"] input,
    [data-testid="stNumberInput"] input:focus,
    input[aria-label="Company Code"],
    input[aria-label="Username or Email"],
    input[aria-label="Password"],
    input[aria-label="Current Password"],
    input[aria-label="New Password"],
    input[aria-label="Confirm New Password"] {{
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
        caret-color: #FFFFFF !important;
        background: transparent !important;
        background-color: transparent !important;
        color-scheme: dark !important;
        opacity: 1 !important;
        text-shadow: none !important;
        font-weight: 500 !important;
    }}

    /* Selected text must also remain white while the field is focused. */
    [data-testid="stTextInput"] input::selection,
    [data-testid="stNumberInput"] input::selection,
    input[aria-label="Company Code"]::selection,
    input[aria-label="Username or Email"]::selection {{
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
        background: #5148E5 !important;
    }}

    [data-testid="stTextInput"] input::placeholder,
    [data-testid="stNumberInput"] input::placeholder {{
        color: #B9BED0 !important;
        -webkit-text-fill-color: #B9BED0 !important;
        opacity: 0.85 !important;
    }}

    [data-testid="stTextInput"] input:-webkit-autofill,
    [data-testid="stTextInput"] input:-webkit-autofill:hover,
    [data-testid="stTextInput"] input:-webkit-autofill:focus,
    [data-testid="stTextInput"] input:-webkit-autofill:active {{
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
        caret-color: #FFFFFF !important;
        box-shadow: 0 0 0 1000px #252630 inset !important;
        -webkit-box-shadow: 0 0 0 1000px #252630 inset !important;
        transition: background-color 9999s ease-out 0s !important;
    }}

    [data-testid="stTextInput"] button,
    [data-testid="stTextInput"] button svg,
    [data-testid="stTextInput"] div[data-baseweb="input"] svg,
    [data-testid="stTextInput"] div[data-baseweb="base-input"] svg {{
        color: #C7CCDA !important;
        fill: currentColor !important;
    }}

    </style>
    """

    st.markdown(css, unsafe_allow_html=True)

    # Restore and save the browser's last theme selection.
    _synchronize_theme_with_browser(get_active_theme())

    # Apply a browser-level fallback after the CSS is injected.
    _enforce_input_value_contrast()
