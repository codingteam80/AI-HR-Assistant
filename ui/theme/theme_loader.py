"""Apply the centralized fixed Light Mode UI theme.

Purpose:
- Convert shared design tokens into global CSS variables.
- Keep the Streamlit sidebar permanently expanded.
- Ensure text, labels, text inputs, date inputs, selectboxes, forms,
  alerts, inputs, and buttons remain readable in Light Mode.

Debugging note:
When a Streamlit upgrade changes widget appearance, inspect the browser's
data-testid attributes and update only the widget selector section below.
"""

import base64
from pathlib import Path

import streamlit as st

from ui.components.browser_bridge import render_browser_bridge
from ui.theme.color_palette import build_accent_palette
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

def _get_theme_tokens(
    primary_color: str | None = None,
) -> dict[str, str]:
    """Return complete Light Mode tokens with a company accent."""

    selected_theme = (
        DARK_THEME
        if get_active_theme() == "dark"
        else LIGHT_THEME
    )

    # Selected values override defaults while missing keys remain safe.
    tokens = {
        **_REQUIRED_DEFAULTS,
        **selected_theme,
    }
    tokens.update(
        build_accent_palette(
            primary_color
            or tokens["primary"]
        )
    )

    return tokens




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
            const validThemes = new Set(["light"]);
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


def _enforce_input_value_contrast(
    tokens: dict[str, str],
) -> None:
    """Keep every form value readable on proper Light Mode controls.

    Streamlit uses runtime-generated BaseWeb/Emotion classes that may be
    inserted after custom CSS. The MutationObserver reapplies visual styles
    only; it never reads, stores, or transmits form values.
    """

    script = """
        <script>
        (() => {
            const parentDocument = window.parent.document;

            const inputBackground = '#252630';
            const inputHoverBackground = '#2D2F3A';
            const inputText = '#FFFFFF';
            const mutedText = '#B9BED0';
            const borderColor = '#3A3D4A';
            const hoverBorder = '__PRIMARY__';
            const primaryColor = '__PRIMARY__';
            const iconColor = '#C7CCDA';
            const softPrimary = '__PRIMARY_SOFT__';
            const onPrimary = '__ON_PRIMARY__';
            const primaryRgb = '__PRIMARY_RGB__';

            const setImportant = (
                element,
                property,
                value
            ) => {
                if (!element) {
                    return;
                }

                element.style.setProperty(
                    property,
                    value,
                    'important'
                );
            };

            const applyControlState = (control) => {
                if (!control) {
                    return;
                }

                const focused = control.contains(
                    parentDocument.activeElement
                );
                const hovered = control.matches(':hover');

                setImportant(
                    control,
                    'background',
                    hovered && !focused
                        ? inputHoverBackground
                        : inputBackground
                );
                setImportant(
                    control,
                    'background-color',
                    hovered && !focused
                        ? inputHoverBackground
                        : inputBackground
                );
                setImportant(
                    control,
                    'border-color',
                    focused
                        ? primaryColor
                        : hovered
                            ? hoverBorder
                            : borderColor
                );
                setImportant(
                    control,
                    'box-shadow',
                    focused
                        ? `0 0 0 1px ${primaryColor}`
                        : 'none'
                );
                setImportant(
                    control,
                    'color-scheme',
                    'dark'
                );
            };

            const bindControlEvents = (control) => {
                if (
                    !control
                    || control.dataset.hrLightControlBound
                ) {
                    return;
                }

                control.dataset.hrLightControlBound = 'true';

                [
                    'mouseenter',
                    'mouseleave',
                    'focusin',
                    'focusout'
                ].forEach((eventName) => {
                    control.addEventListener(
                        eventName,
                        () => applyControlState(control)
                    );
                });
            };

            const styleEditableFields = () => {
                const fieldSelectors = [
                    '[data-testid="stTextInput"] input',
                    '[data-testid="stNumberInput"] input',
                    '[data-testid="stDateInput"] input',
                    '[data-testid="stTimeInput"] input',
                    '[data-testid="stTextArea"] textarea',
                    'input[aria-label="Company Code"]',
                    'input[aria-label="Username or Email"]',
                    'input[aria-label="Password"]',
                    'input[aria-label="Current Password"]',
                    'input[aria-label="New Password"]',
                    'input[aria-label="Confirm New Password"]'
                ];

                parentDocument
                    .querySelectorAll(fieldSelectors.join(','))
                    .forEach((field) => {
                        const fieldText = field.disabled
                            ? mutedText
                            : inputText;

                        setImportant(field, 'color', fieldText);
                        setImportant(
                            field,
                            '-webkit-text-fill-color',
                            fieldText
                        );
                        setImportant(
                            field,
                            'caret-color',
                            primaryColor
                        );
                        setImportant(
                            field,
                            'background-color',
                            'transparent'
                        );
                        setImportant(
                            field,
                            'color-scheme',
                            'dark'
                        );
                        setImportant(
                            field,
                            'text-shadow',
                            'none'
                        );
                        setImportant(field, 'opacity', '1');

                        const control = field.closest(
                            '[data-baseweb="input"],'
                            + '[data-baseweb="base-input"],'
                            + '[data-baseweb="textarea"]'
                        );

                        if (!control) {
                            return;
                        }

                        bindControlEvents(control);
                        applyControlState(control);

                        control
                            .querySelectorAll(
                                'input, textarea, span'
                            )
                            .forEach((child) => {
                                setImportant(
                                    child,
                                    'color',
                                    fieldText
                                );
                                setImportant(
                                    child,
                                    '-webkit-text-fill-color',
                                    fieldText
                                );
                            });

                        control
                            .querySelectorAll('svg')
                            .forEach((icon) => {
                                setImportant(
                                    icon,
                                    'color',
                                    iconColor
                                );
                                setImportant(
                                    icon,
                                    'fill',
                                    'currentColor'
                                );
                            });
                    });
            };

            const styleSelectBoxes = () => {
                parentDocument
                    .querySelectorAll(
                        '[data-baseweb="select"]'
                    )
                    .forEach((selectRoot) => {
                        const control =
                            selectRoot.firstElementChild;

                        bindControlEvents(control);
                        applyControlState(control);

                        setImportant(
                            selectRoot,
                            'color',
                            inputText
                        );
                        setImportant(
                            selectRoot,
                            '-webkit-text-fill-color',
                            inputText
                        );

                        selectRoot
                            .querySelectorAll('*')
                            .forEach((element) => {
                                if (element.tagName === 'SVG') {
                                    setImportant(
                                        element,
                                        'color',
                                        iconColor
                                    );
                                    setImportant(
                                        element,
                                        'fill',
                                        'currentColor'
                                    );
                                    return;
                                }

                                setImportant(
                                    element,
                                    'color',
                                    inputText
                                );
                                setImportant(
                                    element,
                                    '-webkit-text-fill-color',
                                    inputText
                                );
                                setImportant(
                                    element,
                                    'opacity',
                                    '1'
                                );

                                if (element.tagName === 'INPUT') {
                                    setImportant(
                                        element,
                                        'caret-color',
                                        primaryColor
                                    );
                                    setImportant(
                                        element,
                                        'background-color',
                                        'transparent'
                                    );
                                }
                            });
                    });
            };

            const styleDropdownMenus = () => {
                const surfaces = parentDocument.querySelectorAll(
                    '[data-baseweb="popover"] '
                    + '[role="listbox"],'
                    + '[data-baseweb="menu"],'
                    + '[data-baseweb="calendar"]'
                );

                surfaces.forEach((surface) => {
                    const isCalendar = surface.matches(
                        '[data-baseweb="calendar"]'
                    );
                    const surfaceBackground = isCalendar
                        ? '#FFFFFF'
                        : inputBackground;
                    const surfaceText = isCalendar
                        ? '#172033'
                        : inputText;
                    const surfaceBorder = isCalendar
                        ? '#D7DEE8'
                        : borderColor;

                    setImportant(
                        surface,
                        'background',
                        surfaceBackground
                    );
                    setImportant(
                        surface,
                        'background-color',
                        surfaceBackground
                    );
                    setImportant(
                        surface,
                        'color',
                        surfaceText
                    );
                    setImportant(
                        surface,
                        'border-color',
                        surfaceBorder
                    );
                    setImportant(
                        surface,
                        'color-scheme',
                        'light'
                    );

                    surface
                        .querySelectorAll('*')
                        .forEach((element) => {
                            const selectedCalendarItem = (
                                isCalendar
                                && (
                                    element.matches(
                                        '[aria-selected="true"],'
                                        + '[data-selected="true"]'
                                    )
                                    || element.closest(
                                        '[aria-selected="true"],'
                                        + '[data-selected="true"]'
                                    )
                                )
                            );
                            const disabledCalendarItem = (
                                isCalendar
                                && (
                                    element.matches('[aria-disabled="true"]')
                                    || element.closest('[aria-disabled="true"]')
                                )
                            );
                            const elementColor = selectedCalendarItem
                                ? '#FFFFFF'
                                : disabledCalendarItem
                                    ? '#98A2B3'
                                    : surfaceText;

                            if (element.tagName === 'SVG') {
                                setImportant(
                                    element,
                                    'color',
                                    isCalendar
                                        ? elementColor
                                        : iconColor
                                );
                                setImportant(
                                    element,
                                    'fill',
                                    'currentColor'
                                );
                                return;
                            }

                            setImportant(
                                element,
                                'color',
                                elementColor
                            );
                            setImportant(
                                element,
                                '-webkit-text-fill-color',
                                elementColor
                            );
                        });
                });

                parentDocument
                    .querySelectorAll(
                        '[data-baseweb="popover"] '
                        + '[role="option"],'
                        + '[data-baseweb="menu"] '
                        + '[role="option"]'
                    )
                    .forEach((option) => {
                        if (
                            !option.dataset.hrLightOptionBound
                        ) {
                            option.dataset.hrLightOptionBound = 'true';

                            option.addEventListener(
                                'mouseenter',
                                () => {
                                    setImportant(
                                        option,
                                        'background',
                                        softPrimary
                                    );
                                }
                            );
                            option.addEventListener(
                                'mouseleave',
                                () => {
                                    setImportant(
                                        option,
                                        'background',
                                        'transparent'
                                    );
                                }
                            );
                        }
                    });
            };

const styleTooltips = () => {
    const tooltipSelectors = [
        '[role="tooltip"]',
        '[data-baseweb="tooltip"]',
        '[data-testid="stTooltipContent"]'
    ];

    parentDocument
        .querySelectorAll(
            tooltipSelectors.join(',')
        )
        .forEach((tooltip) => {
            setImportant(
                tooltip,
                'color',
                '#FFFFFF'
            );
            setImportant(
                tooltip,
                '-webkit-text-fill-color',
                '#FFFFFF'
            );
            setImportant(
                tooltip,
                'background',
                '#252630'
            );
            setImportant(
                tooltip,
                'background-color',
                '#252630'
            );
            setImportant(
                tooltip,
                'border',
                '1px solid #3A3D4A'
            );
            setImportant(
                tooltip,
                'box-shadow',
                '0 8px 24px rgba(0, 0, 0, 0.28)'
            );
            setImportant(
                tooltip,
                'color-scheme',
                'dark'
            );

            tooltip
                .querySelectorAll('*')
                .forEach((element) => {
                    setImportant(
                        element,
                        'color',
                        '#FFFFFF'
                    );
                    setImportant(
                        element,
                        '-webkit-text-fill-color',
                        '#FFFFFF'
                    );

                    if (element.tagName === 'SVG') {
                        setImportant(
                            element,
                            'fill',
                            'currentColor'
                        );
                    }
                });
        });
};


const styleDownloadButtons = () => {
    const selectors = [
        '[data-testid="stDownloadButton"] > a',
        '[data-testid="stDownloadButton"] > button',
        '[data-testid="stDownloadButton"] '
            + 'a[data-testid^="stBaseButton"]',
        '[data-testid="stDownloadButton"] '
            + 'button[data-testid^="stBaseButton"]'
    ];

    parentDocument
        .querySelectorAll(selectors.join(','))
        .forEach((action) => {
            const disabled = (
                action.matches(':disabled')
                || action.getAttribute(
                    'aria-disabled'
                ) === 'true'
            );
            const focused = (
                action.matches(':focus-visible')
                || parentDocument.activeElement === action
            );
            const hovered = action.matches(':hover');
            const activeSurface = hovered || focused;

            const foreground = disabled
                ? '#8A93A8'
                : activeSurface
                    ? onPrimary
                    : '#10172A';
            const background = disabled
                ? '#EEF1F6'
                : activeSurface
                    ? primaryColor
                    : '#FFFFFF';
            const border = disabled
                ? '#E0E4EC'
                : activeSurface
                    ? primaryColor
                    : '#D8DEEA';

            setImportant(action, 'color', foreground);
            setImportant(
                action,
                '-webkit-text-fill-color',
                foreground
            );
            setImportant(action, 'background', background);
            setImportant(
                action,
                'background-color',
                background
            );
            setImportant(action, 'border-color', border);
            setImportant(
                action,
                'box-shadow',
                focused
                    ? `0 0 0 3px rgba(${primaryRgb}, 0.22)`
                    : 'none'
            );
            setImportant(
                action,
                'text-decoration',
                'none'
            );

            action
                .querySelectorAll('*')
                .forEach((child) => {
                    setImportant(
                        child,
                        'color',
                        foreground
                    );
                    setImportant(
                        child,
                        '-webkit-text-fill-color',
                        foreground
                    );

                    if (child.tagName === 'SVG') {
                        setImportant(
                            child,
                            'fill',
                            'currentColor'
                        );
                    }
                });

            if (!action.dataset.hrDownloadHoverBound) {
                action.dataset.hrDownloadHoverBound = 'true';

                [
                    'mouseenter',
                    'mouseleave',
                    'focus',
                    'blur'
                ].forEach((eventName) => {
                    action.addEventListener(
                        eventName,
                        scheduleApply
                    );
                });
            }
        });
};


const styleToasts = () => {
    const toastSelectors = [
        '[data-testid="stToast"]',
        '[data-baseweb="toast"]'
    ];

    parentDocument
        .querySelectorAll(toastSelectors.join(','))
        .forEach((toast) => {
            const hovered = toast.matches(':hover');
            const surface = hovered
                ? '#2D2F3A'
                : '#252630';

            setImportant(toast, 'color', '#FFFFFF');
            setImportant(
                toast,
                '-webkit-text-fill-color',
                '#FFFFFF'
            );
            setImportant(toast, 'background', surface);
            setImportant(
                toast,
                'background-color',
                surface
            );
            setImportant(
                toast,
                'border',
                '1px solid #3A3D4A'
            );
            setImportant(
                toast,
                'box-shadow',
                '0 10px 28px rgba(0, 0, 0, 0.34)'
            );
            setImportant(
                toast,
                'color-scheme',
                'dark'
            );

            toast
                .querySelectorAll(
                    'p, span, div, strong, em'
                )
                .forEach((element) => {
                    setImportant(
                        element,
                        'color',
                        '#FFFFFF'
                    );
                    setImportant(
                        element,
                        '-webkit-text-fill-color',
                        '#FFFFFF'
                    );
                    setImportant(element, 'opacity', '1');
                    setImportant(
                        element,
                        'text-shadow',
                        'none'
                    );
                });

            toast
                .querySelectorAll('svg')
                .forEach((icon) => {
                    setImportant(
                        icon,
                        'color',
                        '#31C77A'
                    );
                    setImportant(
                        icon,
                        'fill',
                        'currentColor'
                    );
                });

            toast
                .querySelectorAll('button')
                .forEach((button) => {
                    setImportant(
                        button,
                        'color',
                        '#C7CCDA'
                    );
                    setImportant(
                        button,
                        '-webkit-text-fill-color',
                        '#C7CCDA'
                    );
                    setImportant(
                        button,
                        'background',
                        'transparent'
                    );
                    setImportant(
                        button,
                        'background-color',
                        'transparent'
                    );
                    setImportant(
                        button,
                        'border-color',
                        'transparent'
                    );

                    button
                        .querySelectorAll('svg')
                        .forEach((icon) => {
                            setImportant(
                                icon,
                                'color',
                                '#C7CCDA'
                            );
                            setImportant(
                                icon,
                                'fill',
                                'currentColor'
                            );
                        });
                });

            if (!toast.dataset.hrToastHoverBound) {
                toast.dataset.hrToastHoverBound = 'true';

                [
                    'mouseenter',
                    'mouseleave'
                ].forEach((eventName) => {
                    toast.addEventListener(
                        eventName,
                        scheduleApply
                    );
                });
            }
        });
};


const styleNotificationButton = () => {
    /*
       Find the actual bell popover by its visible label. This avoids
       depending on Streamlit's internal wrapper structure.
    */
    parentDocument
        .querySelectorAll(
            '[data-testid="stPopover"] > button'
        )
        .forEach((button) => {
            const label = (
                button.innerText
                || button.textContent
                || ''
            ).trim();

            if (!label.includes('🔔')) {
                return;
            }

            const hovered = button.matches(':hover');
            const focused = (
                button === parentDocument.activeElement
                || button.contains(
                    parentDocument.activeElement
                )
            );
            const expanded = (
                button.getAttribute('aria-expanded')
                === 'true'
            );
            const active = (
                hovered
                || focused
                || expanded
            );
            const background = active
                ? softPrimary
                : '#FFFFFF';
            const foreground = primaryColor;

            setImportant(
                button,
                'background',
                background
            );
            setImportant(
                button,
                'background-color',
                background
            );
            setImportant(
                button,
                'color',
                foreground
            );
            setImportant(
                button,
                '-webkit-text-fill-color',
                foreground
            );
            setImportant(
                button,
                'border',
                `1px solid ${primaryColor}`
            );
            setImportant(
                button,
                'border-color',
                primaryColor
            );
            setImportant(
                button,
                'box-shadow',
                active
                    ? `0 0 0 3px rgba(${primaryRgb}, 0.16)`
                    : `0 6px 16px rgba(${primaryRgb}, 0.12)`
            );
            setImportant(
                button,
                'opacity',
                '1'
            );

            button
                .querySelectorAll(
                    '*'
                )
                .forEach((element) => {
                    setImportant(
                        element,
                        'color',
                        foreground
                    );
                    setImportant(
                        element,
                        '-webkit-text-fill-color',
                        foreground
                    );
                    setImportant(
                        element,
                        'opacity',
                        '1'
                    );

                    if (element.tagName === 'SVG') {
                        setImportant(
                            element,
                            'fill',
                            'currentColor'
                        );
                        setImportant(
                            element,
                            'stroke',
                            'currentColor'
                        );
                    }
                });

            if (
                !button.dataset
                    .hrNotificationVisibilityBound
            ) {
                button.dataset
                    .hrNotificationVisibilityBound = 'true';

                [
                    'mouseenter',
                    'mouseleave',
                    'focus',
                    'blur',
                    'click'
                ].forEach((eventName) => {
                    button.addEventListener(
                        eventName,
                        scheduleApply
                    );
                });
            }
        });
};



const positionNotificationDropdown = () => {
    const button = parentDocument.querySelector(
        '.st-key-global_notification_button button'
    );
    const panel = parentDocument.querySelector(
        '.st-key-notification_dropdown_panel'
    );

    if (!button || !panel) {
        return;
    }

    const viewportWidth = (
        parentDocument.defaultView.innerWidth
        || parentDocument.documentElement.clientWidth
    );
    const viewportHeight = (
        parentDocument.defaultView.innerHeight
        || parentDocument.documentElement.clientHeight
    );
    const panelWidth = Math.min(
        460,
        Math.max(280, viewportWidth - 32)
    );
    const buttonRect = button.getBoundingClientRect();
    const left = Math.min(
        Math.max(16, buttonRect.right - panelWidth),
        Math.max(16, viewportWidth - panelWidth - 16)
    );
    const top = Math.max(16, buttonRect.bottom + 8);
    const maximumHeight = Math.max(
        240,
        viewportHeight - top - 16
    );

    setImportant(panel, 'position', 'fixed');
    setImportant(panel, 'left', `${left}px`);
    setImportant(panel, 'right', 'auto');
    setImportant(panel, 'top', `${top}px`);
    setImportant(panel, 'width', `${panelWidth}px`);
    setImportant(panel, 'min-width', `${panelWidth}px`);
    setImportant(panel, 'max-width', `${panelWidth}px`);
    setImportant(panel, 'max-height', `${maximumHeight}px`);
};



const styleReadableContent = () => {
    const containers = parentDocument.querySelectorAll(
        '[class*="st-key-hr_assistant_message_"] '
        + '[data-testid="stMarkdownContainer"],'
        + '[data-testid="stChatMessage"] '
        + '[data-testid="stMarkdownContainer"],'
        + '[data-testid="stExpander"] '
        + '[data-testid="stMarkdownContainer"],'
        + '[data-testid="stAlert"] '
        + '[data-testid="stMarkdownContainer"],'
        + '[class*="st-key-employee_policy_content_"] '
        + '[data-testid="stMarkdownContainer"],'
        + '.st-key-employee_policy_assistant_answer '
        + '[data-testid="stMarkdownContainer"],'
        + '[data-testid="stExpander"] '
        + '[data-testid="stText"]'
    );

    containers.forEach((container) => {
        const readableElements = container.querySelectorAll(
            'p,li,ul,ol,strong,b,em,i,span,pre,'
            + 'h1,h2,h3,h4,h5,h6,blockquote,'
            + 'table,thead,tbody,tr,th,td,'
            + '.hr-employee-policy-content'
        );

        setImportant(
            container,
            'color',
            '__TEXT_PRIMARY__'
        );
        setImportant(
            container,
            '-webkit-text-fill-color',
            '__TEXT_PRIMARY__'
        );
        setImportant(
            container,
            'opacity',
            '1'
        );

        readableElements.forEach((element) => {
            setImportant(
                element,
                'color',
                '__TEXT_PRIMARY__'
            );
            setImportant(
                element,
                '-webkit-text-fill-color',
                '__TEXT_PRIMARY__'
            );
            setImportant(
                element,
                'opacity',
                '1'
            );
        });

        container.querySelectorAll('a').forEach((link) => {
            setImportant(
                link,
                'color',
                primaryColor
            );
            setImportant(
                link,
                '-webkit-text-fill-color',
                primaryColor
            );
        });

        container.querySelectorAll('code').forEach((code) => {
            setImportant(
                code,
                'color',
                '__TEXT_PRIMARY__'
            );
            setImportant(
                code,
                '-webkit-text-fill-color',
                '__TEXT_PRIMARY__'
            );
            setImportant(
                code,
                'background-color',
                softPrimary
            );
        });
    });

    parentDocument.querySelectorAll(
        '[data-testid="stMain"] '
        + '[data-testid="stMarkdownContainer"] li'
    ).forEach((item) => {
        setImportant(
            item,
            'color',
            '__TEXT_PRIMARY__'
        );
        setImportant(
            item,
            '-webkit-text-fill-color',
            '__TEXT_PRIMARY__'
        );
        setImportant(
            item,
            'opacity',
            '1'
        );

        item.querySelectorAll('*').forEach((child) => {
            setImportant(
                child,
                'color',
                '__TEXT_PRIMARY__'
            );
            setImportant(
                child,
                '-webkit-text-fill-color',
                '__TEXT_PRIMARY__'
            );
            setImportant(
                child,
                'opacity',
                '1'
            );
        });
    });
};


let frameRequested = false;

const applyLightControls = () => {
    frameRequested = false;
    styleEditableFields();
    styleSelectBoxes();
    styleDropdownMenus();
    styleTooltips();
    styleDownloadButtons();
    styleToasts();
    styleNotificationButton();
    positionNotificationDropdown();
    styleReadableContent();
};

            const scheduleApply = () => {
                if (frameRequested) {
                    return;
                }

                frameRequested = true;
                parentDocument.defaultView.requestAnimationFrame(
                    applyLightControls
                );
            };

            scheduleApply();

            const observer = new MutationObserver(scheduleApply);

            observer.observe(
                parentDocument.documentElement,
                {
                    childList: true,
                    subtree: true,
                    attributes: true,
                    attributeFilter: [
                        'class',
                        'style',
                        'aria-expanded'
                    ]
                }
            );
        })();
        </script>
        """

    script = (
        script
        .replace("__PRIMARY__", tokens["primary"])
        .replace("__PRIMARY_SOFT__", tokens["primary_soft"])
        .replace("__PRIMARY_RGB__", tokens["primary_rgb"])
        .replace("__ON_PRIMARY__", tokens["on_primary"])
        .replace("__TEXT_PRIMARY__", tokens["text_primary"])
    )

    render_browser_bridge(script)



def _install_native_copy_shortcut_guard() -> None:
    """Keep Ctrl/Cmd+C as browser Copy instead of Streamlit Clear caches.

    ``stopImmediatePropagation`` blocks Streamlit's global ``c`` shortcut.
    The handler never calls ``preventDefault``, so the browser still copies
    the current selection or focused input value normally.
    """

    script = """
        <script>
        (() => {
            const parentWindow = window.parent;
            const marker = "__aiHrNativeCopyGuardInstalled";

            if (parentWindow[marker]) {
                return;
            }

            const preserveCopy = (event) => {
                const key = String(event.key || "").toLowerCase();
                const isCopy = (
                    (event.ctrlKey || event.metaKey)
                    && key === "c"
                );

                if (!isCopy) {
                    return;
                }

                // Block Streamlit's Clear-cache hotkey listener only.
                // Do not prevent the browser's native Copy default action.
                event.stopImmediatePropagation();
            };

            parentWindow.addEventListener(
                "keydown",
                preserveCopy,
                true
            );
            parentWindow[marker] = true;
        })();
        </script>
    """

    render_browser_bridge(script)

def apply_theme(
    primary_color: str | None = None,
) -> None:
    """Inject Light Mode CSS using the company accent color."""

    tokens = _get_theme_tokens(primary_color)

    # Reuse the approved login artwork at low intensity in portal pages.
    background_path = (
        Path(__file__).resolve().parents[2]
        / "assets"
        / "backgrounds"
        / "login_wave_background.png"
    )
    portal_background_data = base64.b64encode(
        background_path.read_bytes()
    ).decode("ascii")

    is_dark_theme = get_active_theme() == "dark"
    # Keep the artwork visible at roughly 25–30% intensity while
    # preserving readable portal content surfaces.
    portal_overlay = (
        "rgba(12, 18, 32, 0.72)"
        if is_dark_theme
        else "rgba(247, 249, 252, 0.70)"
    )

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
        --hr-primary-text: {tokens["primary_text"]};
        --hr-on-primary: {tokens["on_primary"]};
        --hr-on-primary-hover: {tokens["on_primary_hover"]};
        --hr-primary-rgb: {tokens["primary_rgb"]};
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
    body {{
        background: var(--hr-bg) !important;
        color: var(--hr-text-primary) !important;
    }}

    /* Stronger multi-wave portal artwork behind the working canvas. */
    [data-testid="stAppViewContainer"] {{
        background-color: var(--hr-bg) !important;
        background-image:
            linear-gradient({portal_overlay}, {portal_overlay}),
            url("data:image/png;base64,{portal_background_data}"),
            url("data:image/png;base64,{portal_background_data}"),
            url("data:image/png;base64,{portal_background_data}") !important;
        background-size:
            cover,
            118% auto,
            94% auto,
            78% auto !important;
        background-position:
            center center,
            center center,
            -16% 18%,
            116% 78% !important;
        background-repeat:
            no-repeat,
            no-repeat,
            no-repeat,
            no-repeat !important;
        background-attachment:
            fixed,
            fixed,
            fixed,
            fixed !important;
        color: var(--hr-text-primary) !important;
    }}

    [data-testid="stMain"],
    [data-testid="stAppViewContainer"] > .main {{
        background: transparent !important;
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

    [data-testid="stSidebarHeader"] {{
        display: none !important;
        width: 0 !important;
        min-width: 0 !important;
        height: 0 !important;
        min-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
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
        caret-color: var(--hr-primary-text) !important;
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
        caret-color: var(--hr-primary-text) !important;
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
        border-color: var(--hr-primary-text) !important;
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

/* =========================================================
   COMPANY LOGO — v8.8.7
   Larger transparent logo area with consistent aspect-ratio-safe sizing.
========================================================= */
[data-testid="stSidebarUserContent"] {{
    min-height: 100vh !important;
    min-height: 100dvh !important;
    padding-top: 2.00rem !important;
    padding-bottom: 0.75rem !important;

    display: flex !important;
    flex-direction: column !important;
    box-sizing: border-box !important;
}}

[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {{
    width: 100% !important;
    margin-top: auto !important;
    margin-bottom: auto !important;
    gap: 0.55rem !important;
}}

.hr-sidebar-logo-shell {{
    width: 100%;
    height: 132px;
    min-height: 132px;
    max-height: 132px;
    margin: 0 0 2px 0;
    padding: 0;

    display: flex;
    align-items: center;
    justify-content: center;

    overflow: hidden;
    box-sizing: border-box;
    background: transparent;
    border: none;
    border-radius: 0;
    box-shadow: none;
}}

.hr-sidebar-logo-shell img {{
    display: block;
    width: 100% !important;
    height: 100% !important;
    max-width: 100% !important;
    max-height: 128px !important;
    margin: auto;
    object-fit: contain !important;
    object-position: center !important;
    background: transparent !important;
}}

.hr-sidebar-logo-placeholder {{
    width: 100%;
    min-height: 90px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--hr-text-muted);
    font-size: 0.78rem;
    font-weight: 650;
    letter-spacing: 0.03em;
    text-align: center;
    border: none;
    border-radius: 0;
    background: transparent;
}}

    .hr-brand {{
        color: var(--hr-primary-text);
        font-size: 1.38rem;
        line-height: 1.2;
        font-weight: 780;
        text-align: center;
        margin: 0.1rem 0 0.25rem;
    }}

    .hr-admin-nav-spacer,
    .hr-employee-nav-spacer {{
        width: 100%;
        height: 28px;
        min-height: 28px;
        pointer-events: none;
    }}

    section[data-testid="stSidebar"] div.stButton > button {{
        box-shadow:
            0 3px 8px rgba(30, 41, 59, 0.09),
            0 1px 2px rgba(30, 41, 59, 0.06) !important;
    }}

    section[data-testid="stSidebar"] div.stButton > button:hover {{
        box-shadow:
            0 5px 12px rgba(30, 41, 59, 0.12),
            0 2px 4px rgba(30, 41, 59, 0.07) !important;
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

    /* Standard secondary buttons use a soft accent hover. */
    div.stButton > button {{
        color: var(--hr-text-primary);
        background: var(--hr-surface);
        border: 1px solid var(--hr-border);
        border-radius: 12px;
        box-shadow: none;
        transition:
            color 0.16s ease,
            background-color 0.16s ease,
            border-color 0.16s ease,
            box-shadow 0.16s ease;
    }}

    div.stButton > button:not(:disabled):hover {{
        color: var(--hr-primary-text) !important;
        background: var(--hr-primary-soft) !important;
        border-color: var(--hr-primary-text) !important;
        box-shadow: 0 0 0 2px var(--hr-primary-soft) !important;
    }}

    div.stButton > button:not(:disabled):hover * {{
        color: var(--hr-primary-text) !important;
        -webkit-text-fill-color: var(--hr-primary-text) !important;
    }}

    div.stButton > button:not(:disabled):active {{
        color: var(--hr-primary-text) !important;
        background: var(--hr-surface-secondary) !important;
        border-color: var(--hr-primary-text) !important;
        box-shadow: none !important;
    }}

    div.stButton > button:disabled {{
        cursor: not-allowed;
        opacity: 0.58;
    }}

    /* Primary and form-submit buttons use the project accent color. */
    button[kind="primary"],
    [data-testid="stFormSubmitButton"] button {{
        color: #FFFFFF !important;
        background: var(--hr-primary) !important;
        border-color: var(--hr-primary-text) !important;
        border-radius: 10px !important;
        box-shadow: none !important;
        transition:
            background-color 0.16s ease,
            border-color 0.16s ease,
            box-shadow 0.16s ease;
    }}

    /* Streamlit places button text inside nested paragraph/span elements. */
    button[kind="primary"] *,
    [data-testid="stFormSubmitButton"] button * {{
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }}

    button[kind="primary"]:not(:disabled):hover,
    [data-testid="stFormSubmitButton"] button:not(:disabled):hover {{
        color: #FFFFFF !important;
        background: var(--hr-primary-hover) !important;
        border-color: var(--hr-primary-hover) !important;
        box-shadow: 0 0 0 3px var(--hr-primary-soft) !important;
    }}

    button[kind="primary"]:not(:disabled):hover *,
    [data-testid="stFormSubmitButton"] button:not(:disabled):hover * {{
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }}

    button[kind="primary"]:not(:disabled):active,
    [data-testid="stFormSubmitButton"] button:not(:disabled):active {{
        background: var(--hr-primary) !important;
        border-color: var(--hr-primary-text) !important;
        box-shadow: none !important;
    }}

    /* =========================================================
       TABS
    ========================================================= */

    [data-testid="stTabs"] [data-baseweb="tab-list"] {{
        gap: 6px;
        background: transparent;
    }}

    [data-testid="stTabs"] button[role="tab"] {{
        min-height: 42px;
        padding: 8px 14px;
        color: var(--hr-text-secondary) !important;
        background: transparent !important;
        border-radius: 10px 10px 0 0;
        transition:
            color 0.16s ease,
            background-color 0.16s ease;
    }}

    [data-testid="stTabs"] button[role="tab"] * {{
        color: inherit !important;
        -webkit-text-fill-color: currentColor !important;
    }}

    [data-testid="stTabs"] button[role="tab"]:hover {{
        color: var(--hr-primary-text) !important;
        background: var(--hr-primary-soft) !important;
    }}

    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
        color: var(--hr-primary-text) !important;
        background: var(--hr-primary-soft) !important;
        font-weight: 700;
    }}

    [data-testid="stTabs"] [data-baseweb="tab-highlight"] {{
        background-color: var(--hr-primary-text) !important;
    }}

    /* =========================================================
       EXPANDERS — LIGHT SURFACE CONTRAST v8.4.1
       Expander headers are actions, not dark input controls.
    ========================================================= */

    [data-testid="stExpander"] {{
        color: var(--hr-text-primary) !important;
        background: #FFFFFF !important;
        background-color: #FFFFFF !important;
        border: 1px solid #D8DEEA !important;
        border-radius: 12px !important;
        overflow: hidden !important;
        box-shadow: none !important;
    }}

    [data-testid="stExpander"] details {{
        color: var(--hr-text-primary) !important;
        background: #FFFFFF !important;
        background-color: #FFFFFF !important;
    }}

    [data-testid="stExpander"] details > summary {{
        min-height: 46px !important;
        padding: 10px 14px !important;
        color: #10172A !important;
        -webkit-text-fill-color: #10172A !important;
        background: #FFFFFF !important;
        background-color: #FFFFFF !important;
        border-radius: 11px !important;
        cursor: pointer !important;
        transition:
            color 0.16s ease,
            background-color 0.16s ease,
            border-color 0.16s ease,
            box-shadow 0.16s ease !important;
    }}

    /* Force every nested label/span to remain visible before hover. */
    [data-testid="stExpander"] details > summary *,
    [data-testid="stExpander"] details > summary p,
    [data-testid="stExpander"] details > summary span {{
        color: #10172A !important;
        -webkit-text-fill-color: #10172A !important;
        opacity: 1 !important;
        text-shadow: none !important;
    }}

    [data-testid="stExpander"] details > summary svg {{
        color: #68738C !important;
        fill: currentColor !important;
        -webkit-text-fill-color: currentColor !important;
    }}

    [data-testid="stExpander"] details > summary:hover,
    [data-testid="stExpander"] details > summary:focus-visible {{
        color: var(--hr-primary-text) !important;
        -webkit-text-fill-color: var(--hr-primary-text) !important;
        background: var(--hr-primary-soft) !important;
        background-color: var(--hr-primary-soft) !important;
        box-shadow: inset 0 0 0 1px rgba(var(--hr-primary-rgb), 0.18) !important;
        outline: none !important;
    }}

    [data-testid="stExpander"] details > summary:hover *,
    [data-testid="stExpander"] details > summary:focus-visible * {{
        color: var(--hr-primary-text) !important;
        -webkit-text-fill-color: var(--hr-primary-text) !important;
    }}

    [data-testid="stExpander"] details > summary:hover svg,
    [data-testid="stExpander"] details > summary:focus-visible svg {{
        color: var(--hr-primary-text) !important;
        fill: currentColor !important;
    }}

    /* Keep the expanded header readable even when the pointer leaves. */
    [data-testid="stExpander"] details[open] > summary {{
        color: var(--hr-primary-text) !important;
        -webkit-text-fill-color: var(--hr-primary-text) !important;
        background: var(--hr-primary-soft) !important;
        background-color: var(--hr-primary-soft) !important;
        border-radius: 11px 11px 0 0 !important;
        border-bottom: 1px solid #D8DEEA !important;
    }}

    [data-testid="stExpander"] details[open] > summary *,
    [data-testid="stExpander"] details[open] > summary p,
    [data-testid="stExpander"] details[open] > summary span,
    [data-testid="stExpander"] details[open] > summary svg {{
        color: var(--hr-primary-text) !important;
        -webkit-text-fill-color: var(--hr-primary-text) !important;
    }}

    [data-testid="stExpander"] details > div {{
        color: var(--hr-text-primary) !important;
        background: #FFFFFF !important;
        background-color: #FFFFFF !important;
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
   LIGHT PAGE + DARK FORM CONTROLS — v8.3.12
   Dark controls use white values while the page remains Light Mode.
========================================================= */

[data-testid="stTextInput"] div[data-baseweb="input"],
[data-testid="stTextInput"] div[data-baseweb="base-input"],
[data-testid="stNumberInput"] div[data-baseweb="input"],
[data-testid="stNumberInput"] div[data-baseweb="base-input"],
[data-testid="stDateInput"] div[data-baseweb="input"],
[data-testid="stDateInput"] div[data-baseweb="base-input"],
[data-testid="stTimeInput"] div[data-baseweb="input"],
[data-testid="stTimeInput"] div[data-baseweb="base-input"],
[data-testid="stTextArea"] div[data-baseweb="textarea"],
[data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div,
div[data-baseweb="select"],
div[data-baseweb="select"] > div {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
    border-color: #3A3D4A !important;
    border-radius: 10px !important;
    color-scheme: dark !important;
    transition:
        background-color 0.16s ease,
        border-color 0.16s ease,
        box-shadow 0.16s ease;
}}

[data-testid="stTextInput"] div[data-baseweb="input"]:hover,
[data-testid="stTextInput"] div[data-baseweb="base-input"]:hover,
[data-testid="stNumberInput"] div[data-baseweb="input"]:hover,
[data-testid="stNumberInput"] div[data-baseweb="base-input"]:hover,
[data-testid="stDateInput"] div[data-baseweb="input"]:hover,
[data-testid="stDateInput"] div[data-baseweb="base-input"]:hover,
[data-testid="stTimeInput"] div[data-baseweb="input"]:hover,
[data-testid="stTimeInput"] div[data-baseweb="base-input"]:hover,
[data-testid="stTextArea"] div[data-baseweb="textarea"]:hover,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:hover,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div:hover {{
    background: #2D2F3A !important;
    background-color: #2D2F3A !important;
    border-color: var(--hr-primary) !important;
}}

[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within,
[data-testid="stTextInput"] div[data-baseweb="base-input"]:focus-within,
[data-testid="stNumberInput"] div[data-baseweb="input"]:focus-within,
[data-testid="stNumberInput"] div[data-baseweb="base-input"]:focus-within,
[data-testid="stDateInput"] div[data-baseweb="input"]:focus-within,
[data-testid="stDateInput"] div[data-baseweb="base-input"]:focus-within,
[data-testid="stTimeInput"] div[data-baseweb="input"]:focus-within,
[data-testid="stTimeInput"] div[data-baseweb="base-input"]:focus-within,
[data-testid="stTextArea"] div[data-baseweb="textarea"]:focus-within,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div:focus-within {{
    background: #252630 !important;
    background-color: #252630 !important;
    border-color: var(--hr-primary-text) !important;
    box-shadow: 0 0 0 1px var(--hr-primary) !important;
}}

[data-testid="stAppViewContainer"]
input:not([type="checkbox"]):not([type="radio"]),
[data-testid="stAppViewContainer"] textarea,
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input,
[data-testid="stTimeInput"] input,
[data-testid="stTextArea"] textarea,
div[data-baseweb="select"] input {{
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

[data-testid="stTextInput"] input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stDateInput"] input::placeholder,
[data-testid="stTimeInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder,
[data-testid="stSelectbox"] input::placeholder,
[data-testid="stMultiSelect"] input::placeholder,
div[data-baseweb="select"] input::placeholder {{
    color: #B9BED0 !important;
    -webkit-text-fill-color: #B9BED0 !important;
    opacity: 0.86 !important;
}}

[data-testid="stTextInput"] input::selection,
[data-testid="stNumberInput"] input::selection,
[data-testid="stDateInput"] input::selection,
[data-testid="stTimeInput"] input::selection,
[data-testid="stTextArea"] textarea::selection {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: var(--hr-primary) !important;
}}

[data-testid="stTextInput"] input:-webkit-autofill,
[data-testid="stTextInput"] input:-webkit-autofill:hover,
[data-testid="stTextInput"] input:-webkit-autofill:focus,
[data-testid="stDateInput"] input:-webkit-autofill,
[data-testid="stTimeInput"] input:-webkit-autofill {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    caret-color: #FFFFFF !important;
    box-shadow: 0 0 0 1000px #252630 inset !important;
    -webkit-box-shadow: 0 0 0 1000px #252630 inset !important;
    transition: background-color 9999s ease-out 0s !important;
}}

div[data-baseweb="select"] div,
div[data-baseweb="select"] span,
div[data-baseweb="select"] p,
div[data-baseweb="select"] label,
div[data-baseweb="select"] input,
div[data-baseweb="select"] [role="combobox"],
div[data-baseweb="select"] [aria-selected],
div[data-baseweb="select"] [data-baseweb="tag"] {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    opacity: 1 !important;
    text-shadow: none !important;
}}

[data-testid="stTextInput"] button,
[data-testid="stTextInput"] button svg,
[data-testid="stDateInput"] button,
[data-testid="stDateInput"] button svg,
[data-testid="stTimeInput"] button,
[data-testid="stTimeInput"] button svg,
div[data-baseweb="select"] svg {{
    color: #C7CCDA !important;
    fill: currentColor !important;
    -webkit-text-fill-color: currentColor !important;
}}

[data-testid="stTextInput"] input:disabled,
[data-testid="stNumberInput"] input:disabled,
[data-testid="stDateInput"] input:disabled,
[data-testid="stTimeInput"] input:disabled,
[data-testid="stTextArea"] textarea:disabled {{
    color: #D6D9E3 !important;
    -webkit-text-fill-color: #D6D9E3 !important;
    opacity: 1 !important;
}}

[data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] [role="menu"],
[data-baseweb="menu"] {{
    color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
    border: 1px solid #3A3D4A !important;
    color-scheme: dark !important;
    box-shadow: 0 12px 32px rgba(24, 36, 74, 0.22) !important;
}}

[data-baseweb="popover"] [role="listbox"] *,
[data-baseweb="popover"] [role="menu"] *,
[data-baseweb="menu"] * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}

[data-baseweb="popover"] [role="option"]:hover,
[data-baseweb="menu"] [role="option"]:hover,
[data-baseweb="popover"] [role="option"][aria-selected="true"],
[data-baseweb="menu"] [role="option"][aria-selected="true"] {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
}}

/* The date picker is a light, high-contrast surface even though its closed
   input intentionally keeps the approved dark-control appearance. */
[data-baseweb="calendar"] {{
    color: #172033 !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid #D7DEE8 !important;
    color-scheme: light !important;
    box-shadow: 0 16px 36px rgba(24, 36, 74, 0.20) !important;
}}

[data-baseweb="calendar"] * {{
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}}

[data-baseweb="calendar"] [role="columnheader"],
[data-baseweb="calendar"] [role="columnheader"] * {{
    color: #667085 !important;
    -webkit-text-fill-color: #667085 !important;
    font-weight: 700 !important;
}}

[data-baseweb="calendar"] button {{
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
    background-color: transparent !important;
    border-radius: 8px !important;
}}

[data-baseweb="calendar"] button:hover {{
    color: var(--hr-primary-text) !important;
    -webkit-text-fill-color: var(--hr-primary-text) !important;
    background: var(--hr-primary-soft) !important;
    background-color: var(--hr-primary-soft) !important;
}}

[data-baseweb="calendar"] [aria-selected="true"],
[data-baseweb="calendar"] [aria-selected="true"] *,
[data-baseweb="calendar"] [data-selected="true"],
[data-baseweb="calendar"] [data-selected="true"] * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
}}

[data-baseweb="calendar"] [aria-disabled="true"],
[data-baseweb="calendar"] [aria-disabled="true"] * {{
    color: #98A2B3 !important;
    -webkit-text-fill-color: #98A2B3 !important;
    opacity: 1 !important;
}}

/* Labels are outside dark controls, so they remain dark on the light page. */
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
[data-testid="stTextInput"] label,
[data-testid="stTextInput"] label p,
[data-testid="stNumberInput"] label,
[data-testid="stNumberInput"] label p,
[data-testid="stDateInput"] label,
[data-testid="stDateInput"] label p,
[data-testid="stTimeInput"] label,
[data-testid="stTimeInput"] label p,
[data-testid="stTextArea"] label,
[data-testid="stTextArea"] label p,
[data-testid="stSelectbox"] label,
[data-testid="stSelectbox"] label p,
[data-testid="stMultiSelect"] label,
[data-testid="stMultiSelect"] label p {{
    color: var(--hr-text-primary) !important;
    -webkit-text-fill-color: var(--hr-text-primary) !important;
    opacity: 1 !important;
}}


/* =========================================================
   NATIVE STREAMLIT CONTROL HOVER — v8.3.13
   File uploader and checkbox controls do not inherit normal
   st.button/input hover rules, so they are scoped separately.
========================================================= */

/* File uploader dropzone */
[data-testid="stFileUploaderDropzone"] {{
    color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
    border: 1px dashed #3A3D4A !important;
    border-radius: 10px !important;
    transition:
        background-color 0.16s ease,
        border-color 0.16s ease,
        box-shadow 0.16s ease !important;
}}

[data-testid="stFileUploaderDropzone"]:hover,
[data-testid="stFileUploaderDropzone"]:focus-within {{
    background: #2D2F3A !important;
    background-color: #2D2F3A !important;
    border-color: var(--hr-primary) !important;
    box-shadow: 0 0 0 2px rgba(var(--hr-primary-rgb), 0.18) !important;
}}

/* Uploader text, helper text, and icons */
[data-testid="stFileUploaderDropzone"] p,
[data-testid="stFileUploaderDropzone"] span,
[data-testid="stFileUploaderDropzone"] small,
[data-testid="stFileUploaderDropzone"] div {{
    color: #D6D9E3 !important;
    -webkit-text-fill-color: #D6D9E3 !important;
}}

[data-testid="stFileUploaderDropzone"] svg {{
    color: #C7CCDA !important;
    fill: currentColor !important;
}}

/* Streamlit Upload/Browse button inside the dropzone */
[data-testid="stFileUploaderDropzone"] button,
[data-testid="stFileUploaderDropzone"] button[kind="secondary"],
[data-testid="stFileUploaderDropzone"] button[data-testid] {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: #343644 !important;
    background-color: #343644 !important;
    border: 1px solid #565A6D !important;
    border-radius: 8px !important;
    box-shadow: none !important;
    transition:
        color 0.16s ease,
        background-color 0.16s ease,
        border-color 0.16s ease,
        box-shadow 0.16s ease !important;
}}

[data-testid="stFileUploaderDropzone"] button *,
[data-testid="stFileUploaderDropzone"] button p,
[data-testid="stFileUploaderDropzone"] button span {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}

[data-testid="stFileUploaderDropzone"] button:hover,
[data-testid="stFileUploaderDropzone"] button:focus-visible {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border-color: var(--hr-primary) !important;
    box-shadow: 0 0 0 3px rgba(var(--hr-primary-rgb), 0.22) !important;
}}

[data-testid="stFileUploaderDropzone"] button:hover *,
[data-testid="stFileUploaderDropzone"] button:focus-visible * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}

[data-testid="stFileUploaderDropzone"] button:active {{
    background: var(--hr-primary-hover) !important;
    background-color: var(--hr-primary-hover) !important;
    border-color: var(--hr-primary-hover) !important;
    box-shadow: none !important;
}}

/* Uploaded file rows */
[data-testid="stFileUploaderFile"],
[data-testid="stFileUploaderFileData"] {{
    color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
    border: 1px solid #3A3D4A !important;
    border-radius: 8px !important;
    transition:
        background-color 0.16s ease,
        border-color 0.16s ease !important;
}}

[data-testid="stFileUploaderFile"]:hover,
[data-testid="stFileUploaderFileData"]:hover {{
    background: #2D2F3A !important;
    background-color: #2D2F3A !important;
    border-color: var(--hr-primary) !important;
}}

[data-testid="stFileUploaderFile"] *,
[data-testid="stFileUploaderFileData"] * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}

/* Remove-file icon */
[data-testid="stFileUploaderDeleteBtn"] button,
[data-testid="stFileUploaderDeleteBtn"] button * {{
    color: #C7CCDA !important;
    -webkit-text-fill-color: #C7CCDA !important;
}}

[data-testid="stFileUploaderDeleteBtn"] button:hover,
[data-testid="stFileUploaderDeleteBtn"] button:hover * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: #E05252 !important;
    background-color: #E05252 !important;
    border-color: #E05252 !important;
}}

/* Checkbox hover: label is on the light form surface */
[data-testid="stCheckbox"] label {{
    padding: 5px 8px !important;
    border-radius: 8px !important;
    transition:
        color 0.16s ease,
        background-color 0.16s ease !important;
}}

[data-testid="stCheckbox"] label:hover {{
    color: var(--hr-primary-text) !important;
    background: var(--hr-primary-soft) !important;
    background-color: var(--hr-primary-soft) !important;
}}

[data-testid="stCheckbox"] label:hover p,
[data-testid="stCheckbox"] label:hover span {{
    color: var(--hr-primary-text) !important;
    -webkit-text-fill-color: var(--hr-primary-text) !important;
}}

/* Checkbox square/indicator */
[data-testid="stCheckbox"] [role="checkbox"] {{
    border-color: #68738C !important;
    transition:
        background-color 0.16s ease,
        border-color 0.16s ease,
        box-shadow 0.16s ease !important;
}}

[data-testid="stCheckbox"] label:hover [role="checkbox"] {{
    border-color: var(--hr-primary-text) !important;
    box-shadow: 0 0 0 2px var(--hr-primary-soft) !important;
}}

[data-testid="stCheckbox"] [role="checkbox"][aria-checked="true"] {{
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary-text) !important;
    border-color: var(--hr-primary-text) !important;
}}

[data-testid="stCheckbox"]
[role="checkbox"][aria-checked="true"] svg {{
    color: #FFFFFF !important;
    fill: currentColor !important;
}}

/* =========================================================
   TOOLTIP CONTRAST — v8.3.14
   Help text appears on a dark floating surface, so every nested
   text node must remain white regardless of Light Mode page rules.
========================================================= */

[role="tooltip"],
[data-baseweb="tooltip"],
[data-testid="stTooltipContent"] {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
    border: 1px solid #3A3D4A !important;
    border-radius: 8px !important;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28) !important;
    color-scheme: dark !important;
}}

[role="tooltip"] > div,
[data-baseweb="tooltip"] > div,
[data-testid="stTooltipContent"] > div {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
}}

[role="tooltip"] *,
[data-baseweb="tooltip"] *,
[data-testid="stTooltipContent"] * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    opacity: 1 !important;
    text-shadow: none !important;
}}

[role="tooltip"] svg,
[data-baseweb="tooltip"] svg,
[data-testid="stTooltipContent"] svg {{
    color: #D6D9E3 !important;
    fill: currentColor !important;
    -webkit-text-fill-color: currentColor !important;
}}

/* Help icon remains visible on the light page before hover. */
[data-testid="stTooltipIcon"],
[data-testid="stTooltipIcon"] button,
[data-testid="stTooltipIcon"] svg {{
    color: #68738C !important;
    fill: currentColor !important;
    transition:
        color 0.16s ease,
        background-color 0.16s ease !important;
}}

[data-testid="stTooltipIcon"]:hover,
[data-testid="stTooltipIcon"] button:hover {{
    color: var(--hr-primary-text) !important;
    background: var(--hr-primary-soft) !important;
    border-radius: 50% !important;
}}

[data-testid="stTooltipIcon"]:hover svg,
[data-testid="stTooltipIcon"] button:hover svg {{
    color: var(--hr-primary-text) !important;
    fill: currentColor !important;
}}

/* =========================================================
   DOWNLOAD ACTION CONTRAST — v8.3.15
   Download controls render as anchors in some Streamlit versions
   and buttons in others, so both structures are covered.
========================================================= */

[data-testid="stDownloadButton"] {{
    background: transparent !important;
}}

[data-testid="stDownloadButton"] > a,
[data-testid="stDownloadButton"] > button,
[data-testid="stDownloadButton"]
a[data-testid^="stBaseButton"],
[data-testid="stDownloadButton"]
button[data-testid^="stBaseButton"] {{
    width: 100% !important;
    min-height: 40px !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid #D8DEEA !important;
    border-radius: 10px !important;
    box-shadow: none !important;
    text-decoration: none !important;
    transition:
        color 0.16s ease,
        background-color 0.16s ease,
        border-color 0.16s ease,
        box-shadow 0.16s ease !important;
}}

[data-testid="stDownloadButton"] > a *,
[data-testid="stDownloadButton"] > button *,
[data-testid="stDownloadButton"]
a[data-testid^="stBaseButton"] *,
[data-testid="stDownloadButton"]
button[data-testid^="stBaseButton"] * {{
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
}}

[data-testid="stDownloadButton"] svg {{
    color: #68738C !important;
    fill: currentColor !important;
}}

[data-testid="stDownloadButton"] > a:hover,
[data-testid="stDownloadButton"] > button:hover,
[data-testid="stDownloadButton"] > a:focus-visible,
[data-testid="stDownloadButton"] > button:focus-visible,
[data-testid="stDownloadButton"]
a[data-testid^="stBaseButton"]:hover,
[data-testid="stDownloadButton"]
button[data-testid^="stBaseButton"]:hover,
[data-testid="stDownloadButton"]
a[data-testid^="stBaseButton"]:focus-visible,
[data-testid="stDownloadButton"]
button[data-testid^="stBaseButton"]:focus-visible {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border-color: var(--hr-primary) !important;
    box-shadow: 0 0 0 3px rgba(var(--hr-primary-rgb), 0.22) !important;
    text-decoration: none !important;
}}

[data-testid="stDownloadButton"] > a:hover *,
[data-testid="stDownloadButton"] > button:hover *,
[data-testid="stDownloadButton"] > a:focus-visible *,
[data-testid="stDownloadButton"] > button:focus-visible *,
[data-testid="stDownloadButton"]
a[data-testid^="stBaseButton"]:hover *,
[data-testid="stDownloadButton"]
button[data-testid^="stBaseButton"]:hover *,
[data-testid="stDownloadButton"]
a[data-testid^="stBaseButton"]:focus-visible *,
[data-testid="stDownloadButton"]
button[data-testid^="stBaseButton"]:focus-visible * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}

[data-testid="stDownloadButton"] > a:active,
[data-testid="stDownloadButton"] > button:active,
[data-testid="stDownloadButton"]
a[data-testid^="stBaseButton"]:active,
[data-testid="stDownloadButton"]
button[data-testid^="stBaseButton"]:active {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: var(--hr-primary-hover) !important;
    background-color: var(--hr-primary-hover) !important;
    border-color: var(--hr-primary-hover) !important;
    box-shadow: none !important;
}}

[data-testid="stDownloadButton"] > a[aria-disabled="true"],
[data-testid="stDownloadButton"] > button:disabled,
[data-testid="stDownloadButton"]
a[data-testid^="stBaseButton"][aria-disabled="true"],
[data-testid="stDownloadButton"]
button[data-testid^="stBaseButton"]:disabled {{
    color: #8A93A8 !important;
    -webkit-text-fill-color: #8A93A8 !important;
    background: #EEF1F6 !important;
    background-color: #EEF1F6 !important;
    border-color: #E0E4EC !important;
    box-shadow: none !important;
    cursor: not-allowed !important;
    opacity: 1 !important;
}}

[data-testid="stDownloadButton"] > a[aria-disabled="true"] *,
[data-testid="stDownloadButton"] > button:disabled *,
[data-testid="stDownloadButton"]
a[data-testid^="stBaseButton"][aria-disabled="true"] *,
[data-testid="stDownloadButton"]
button[data-testid^="stBaseButton"]:disabled * {{
    color: #8A93A8 !important;
    -webkit-text-fill-color: #8A93A8 !important;
}}

/* =========================================================
   TOAST CONTRAST — v8.4.2
   Toasts are dark floating surfaces and must not inherit the
   Light Mode page's dark body text.
========================================================= */

[data-testid="stToast"],
[data-baseweb="toast"] {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
    border: 1px solid #3A3D4A !important;
    border-radius: 10px !important;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.34) !important;
    color-scheme: dark !important;
    transition:
        background-color 0.16s ease,
        border-color 0.16s ease,
        box-shadow 0.16s ease !important;
}}

[data-testid="stToast"]:hover,
[data-baseweb="toast"]:hover {{
    background: #2D2F3A !important;
    background-color: #2D2F3A !important;
    border-color: #565A6D !important;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.38) !important;
}}

[data-testid="stToast"] *,
[data-baseweb="toast"] * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    opacity: 1 !important;
    text-shadow: none !important;
}}

/* Success/status icon */
[data-testid="stToast"] svg,
[data-baseweb="toast"] svg {{
    color: #31C77A !important;
    fill: currentColor !important;
    -webkit-text-fill-color: currentColor !important;
}}

/* Close button must stay readable but visually secondary. */
[data-testid="stToast"] button,
[data-baseweb="toast"] button {{
    color: #C7CCDA !important;
    -webkit-text-fill-color: #C7CCDA !important;
    background: transparent !important;
    background-color: transparent !important;
    border-color: transparent !important;
    border-radius: 7px !important;
    box-shadow: none !important;
}}

[data-testid="stToast"] button *,
[data-baseweb="toast"] button *,
[data-testid="stToast"] button svg,
[data-baseweb="toast"] button svg {{
    color: #C7CCDA !important;
    -webkit-text-fill-color: #C7CCDA !important;
    fill: currentColor !important;
}}

[data-testid="stToast"] button:hover,
[data-baseweb="toast"] button:hover {{
    color: #FFFFFF !important;
    background: #3A3D4A !important;
    background-color: #3A3D4A !important;
}}

[data-testid="stToast"] button:hover *,
[data-baseweb="toast"] button:hover * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}

/* =========================================================
   POLICY TEXT READABILITY — v8.4.6
   Compact line spacing while keeping long policy text readable.
========================================================= */

[data-testid="stTextArea"] textarea {{
    line-height: 1.30 !important;
    font-size: 0.90rem !important;
    letter-spacing: 0 !important;
    padding: 12px 14px !important;
    tab-size: 4 !important;
    white-space: pre-wrap !important;
    overflow-wrap: anywhere !important;
}}

[data-testid="stTextArea"] label {{
    margin-bottom: 4px !important;
}}

/* =========================================================
   POLICY PREVIEW SCROLL BOXES — v8.8.18
   Complete content stays available without stretching the page.
========================================================= */

.hr-policy-headings-preview {{
    background: #F8F9FC !important;
    border: 1px solid #D8DEEA !important;
    border-radius: 10px !important;
    padding: 12px 14px !important;
    margin: 5px 0 4px 0 !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
}}

.hr-policy-headings-title {{
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    font-weight: 700 !important;
    margin-bottom: 6px !important;
}}

.hr-policy-headings-scroll {{
    max-height: 170px !important;
    overflow-y: scroll !important;
    overflow-x: hidden !important;
    scrollbar-gutter: stable !important;
    padding-right: 8px !important;
}}

.hr-policy-headings-scroll ol {{
    margin: 0 !important;
    padding-left: 22px !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    line-height: 1.28 !important;
}}

.hr-policy-headings-scroll li {{
    margin: 0 0 3px 0 !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    line-height: 1.28 !important;
    overflow-wrap: anywhere !important;
}}

/* =========================================================
   VISIBLE POLICY SCROLLBARS — v8.8.20
   Fixed-height policy boxes keep a visible scrollbar track and thumb.
========================================================= */

.hr-policy-headings-scroll,
.hr-policy-section-preview,
div[class*="st-key-policy_section_results_"],
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlockBorderWrapper"],
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlock"],
div[class*="st-key-policy_content_"] textarea,
div[class*="st-key-editable_policy_content_"] textarea {{
    scrollbar-width: auto !important;
    scrollbar-color: var(--hr-primary) #E5EAF2 !important;
    scrollbar-gutter: stable !important;
}}

/* Force the native bounded Searchable Sections container to reserve
   its vertical scrollbar instead of relying on an overlay scrollbar. */
div[class*="st-key-policy_section_results_"][data-testid="stVerticalBlockBorderWrapper"],
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlockBorderWrapper"],
div[class*="st-key-policy_section_results_"] {{
    overflow-y: scroll !important;
}}

/* The complete extracted content and editable content are also fixed
   height, so their scrollbars remain visibly available. */
div[class*="st-key-policy_content_"] textarea,
div[class*="st-key-editable_policy_content_"] textarea {{
    overflow-y: scroll !important;
}}

.hr-policy-headings-scroll::-webkit-scrollbar,
.hr-policy-section-preview::-webkit-scrollbar,
div[class*="st-key-policy_section_results_"]::-webkit-scrollbar,
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlockBorderWrapper"]::-webkit-scrollbar,
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlock"]::-webkit-scrollbar,
div[class*="st-key-policy_content_"] textarea::-webkit-scrollbar,
div[class*="st-key-editable_policy_content_"] textarea::-webkit-scrollbar {{
    width: 12px !important;
    height: 12px !important;
}}

.hr-policy-headings-scroll::-webkit-scrollbar-track,
.hr-policy-section-preview::-webkit-scrollbar-track,
div[class*="st-key-policy_section_results_"]::-webkit-scrollbar-track,
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlockBorderWrapper"]::-webkit-scrollbar-track,
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlock"]::-webkit-scrollbar-track,
div[class*="st-key-policy_content_"] textarea::-webkit-scrollbar-track,
div[class*="st-key-editable_policy_content_"] textarea::-webkit-scrollbar-track {{
    background: #E5EAF2 !important;
    border-radius: 999px !important;
}}

.hr-policy-headings-scroll::-webkit-scrollbar-thumb,
.hr-policy-section-preview::-webkit-scrollbar-thumb,
div[class*="st-key-policy_section_results_"]::-webkit-scrollbar-thumb,
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlockBorderWrapper"]::-webkit-scrollbar-thumb,
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb,
div[class*="st-key-policy_content_"] textarea::-webkit-scrollbar-thumb,
div[class*="st-key-editable_policy_content_"] textarea::-webkit-scrollbar-thumb {{
    min-height: 44px !important;
    background: var(--hr-primary) !important;
    border: 2px solid #E5EAF2 !important;
    border-radius: 999px !important;
}}

.hr-policy-headings-scroll::-webkit-scrollbar-thumb:hover,
.hr-policy-section-preview::-webkit-scrollbar-thumb:hover,
div[class*="st-key-policy_section_results_"]::-webkit-scrollbar-thumb:hover,
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlockBorderWrapper"]::-webkit-scrollbar-thumb:hover,
div[class*="st-key-policy_section_results_"]
[data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb:hover,
div[class*="st-key-policy_content_"] textarea::-webkit-scrollbar-thumb:hover,
div[class*="st-key-editable_policy_content_"] textarea::-webkit-scrollbar-thumb:hover {{
    background: var(--hr-primary-hover) !important;
}}

.hr-policy-headings-scroll::-webkit-scrollbar-corner,
.hr-policy-section-preview::-webkit-scrollbar-corner,
div[class*="st-key-policy_section_results_"]::-webkit-scrollbar-corner,
div[class*="st-key-policy_content_"] textarea::-webkit-scrollbar-corner,
div[class*="st-key-editable_policy_content_"] textarea::-webkit-scrollbar-corner {{
    background: #E5EAF2 !important;
}}

/* =========================================================
   POLICY SECTION HEADING/CONTENT LAYOUT — v8.4.7
   Separator → heading → content → next separator.
========================================================= */

.hr-policy-section-preview {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
    border: 1px solid #3A3D4A !important;
    border-radius: 10px !important;
    padding: 5px 14px 7px 14px !important;
    margin: 4px 0 10px 0 !important;
    font-family: inherit !important;
    letter-spacing: 0 !important;
    max-height: 420px !important;
    overflow-y: scroll !important;
    overflow-x: hidden !important;
    scrollbar-gutter: stable !important;
}}

.hr-policy-preview-section {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    border-top: 1px solid #666B7C !important;
    padding: 8px 0 9px 0 !important;
    margin: 0 !important;
}}

.hr-policy-preview-heading {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    font-size: 0.90rem !important;
    font-weight: 700 !important;
    line-height: 1.24 !important;
    margin: 0 0 4px 0 !important;
    overflow-wrap: anywhere !important;
    word-break: break-word !important;
    opacity: 1 !important;
    text-shadow: none !important;
}}

.hr-policy-preview-content {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    font-size: 0.87rem !important;
    font-weight: 500 !important;
    line-height: 1.26 !important;
    margin: 0 !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    word-break: break-word !important;
    opacity: 1 !important;
    text-shadow: none !important;
}}

.hr-policy-preview-heading *,
.hr-policy-preview-content * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    opacity: 1 !important;
    text-shadow: none !important;
}}

.hr-policy-preview-final-line {{
    border-top: 1px solid #666B7C !important;
    height: 1px !important;
    margin: 0 !important;
}}

/* =========================================================
   GLOBAL NOTIFICATION CENTER — v8.7.1
========================================================= */

/* Compact top-bar bell. */
[data-testid="stPopover"] > button {{
    width: auto !important;
    min-width: 58px !important;
    min-height: 44px !important;
    padding: 0.55rem 0.85rem !important;
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border: 1px solid var(--hr-primary) !important;
    border-radius: 12px !important;
    font-weight: 800 !important;
    font-variant-numeric: tabular-nums !important;
    letter-spacing: 0.01em !important;
    box-shadow: var(--hr-shadow) !important;
}}

[data-testid="stPopover"] > button *,
[data-testid="stPopover"] > button p {{
    color: inherit !important;
    -webkit-text-fill-color: inherit !important;
}}

[data-testid="stPopover"] > button:hover,
[data-testid="stPopover"] > button:focus,
[data-testid="stPopover"] > button:focus-visible,
[data-testid="stPopover"] > button:active,
[data-testid="stPopover"] > button[aria-expanded="true"] {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border-color: var(--hr-primary) !important;
    box-shadow:
        0 0 0 4px rgba(var(--hr-primary-rgb), 0.18),
        0 8px 20px rgba(var(--hr-primary-rgb), 0.22) !important;
}}

/* Scope popover styling only when it contains our notification panel.
   Selectboxes and date pickers keep their existing dark menu styling. */
[data-baseweb="popover"]:has(.hr-notification-panel) > div,
[data-testid="stPopoverBody"]:has(.hr-notification-panel) {{
    width: min(390px, calc(100vw - 32px)) !important;
    min-width: min(390px, calc(100vw - 32px)) !important;
    max-width: min(390px, calc(100vw - 32px)) !important;
    max-height: 520px !important;
    overflow-y: auto !important;
    padding: 12px !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid #D8DEEA !important;
    border-radius: 16px !important;
    box-shadow: 0 18px 46px rgba(16, 23, 42, 0.20) !important;
    color-scheme: light !important;
}}

[data-baseweb="popover"]:has(.hr-notification-panel)
[data-testid="stMarkdownContainer"],
[data-testid="stPopoverBody"]:has(.hr-notification-panel)
[data-testid="stMarkdownContainer"] {{
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
}}

.hr-notification-panel,
.hr-notification-panel *,
.hr-notification-card,
.hr-notification-card *,
.hr-notification-empty,
.hr-notification-empty *,
.hr-notification-list {{
    display: block !important;
    width: 100% !important;
}}

.hr-notification-list-label {{
    box-sizing: border-box !important;
    opacity: 1 !important;
    text-shadow: none !important;
}}

.hr-notification-header {{
    display: flex !important;
    align-items: flex-start !important;
    justify-content: space-between !important;
    gap: 12px !important;
    padding: 4px 2px 12px 2px !important;
    border-bottom: 1px solid #E4E8F1 !important;
}}

.hr-notification-heading {{
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    font-size: 1rem !important;
    font-weight: 800 !important;
    line-height: 1.25 !important;
}}

.hr-notification-subheading {{
    margin-top: 3px !important;
    color: #65708A !important;
    -webkit-text-fill-color: #65708A !important;
    font-size: 0.77rem !important;
    font-weight: 550 !important;
    line-height: 1.3 !important;
}}

.hr-notification-count {{
    flex: 0 0 auto !important;
    padding: 4px 9px !important;
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border: 1px solid var(--hr-primary) !important;
    border-radius: 999px !important;
    font-size: 0.72rem !important;
    font-weight: 800 !important;
    font-variant-numeric: tabular-nums !important;
    line-height: 1.1 !important;
}}

.hr-notification-list-label {{
    margin: 10px 2px 7px 2px !important;
    color: #65708A !important;
    -webkit-text-fill-color: #65708A !important;
    font-size: 0.72rem !important;
    font-weight: 750 !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}}

.hr-notification-card {{
    display: grid !important;
    grid-template-columns: 38px minmax(0, 1fr) !important;
    gap: 10px !important;
    margin: 0 0 8px 0 !important;
    padding: 11px !important;
    border: 1px solid #E2E7F0 !important;
    border-radius: 12px !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
}}

.hr-notification-card-unread {{
    background: var(--hr-primary-soft) !important;
    background-color: var(--hr-primary-soft) !important;
    border-color: rgba(var(--hr-primary-rgb), 0.24) !important;
}}

.hr-notification-card-read {{
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
}}

.hr-notification-card-icon {{
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 38px !important;
    height: 38px !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    background: #F1F4F9 !important;
    border: 1px solid #E2E7F0 !important;
    border-radius: 10px !important;
    font-size: 1rem !important;
    line-height: 1 !important;
}}

.hr-notification-card-unread
.hr-notification-card-icon {{
    background: #FFFFFF !important;
    border-color: rgba(var(--hr-primary-rgb), 0.20) !important;
}}

.hr-notification-card-content {{
    min-width: 0 !important;
}}

.hr-notification-card-meta {{
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    min-height: 14px !important;
    gap: 8px !important;
}}

.hr-notification-category {{
    color: var(--hr-primary-text) !important;
    -webkit-text-fill-color: var(--hr-primary-text) !important;
    font-size: 0.68rem !important;
    font-weight: 800 !important;
    line-height: 1.1 !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}}

.hr-notification-unread-dot {{
    display: inline-block !important;
    width: 8px !important;
    height: 8px !important;
    flex: 0 0 8px !important;
    background: var(--hr-primary) !important;
    border-radius: 999px !important;
    box-shadow: 0 0 0 3px rgba(var(--hr-primary-rgb), 0.12) !important;
}}

.hr-notification-title {{
    margin-top: 4px !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    font-size: 0.88rem !important;
    font-weight: 780 !important;
    line-height: 1.28 !important;
    overflow-wrap: anywhere !important;
}}

.hr-notification-message {{
    margin-top: 4px !important;
    color: #46516B !important;
    -webkit-text-fill-color: #46516B !important;
    font-size: 0.79rem !important;
    font-weight: 520 !important;
    line-height: 1.38 !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
}}

.hr-notification-time {{
    margin-top: 6px !important;
    color: #778198 !important;
    -webkit-text-fill-color: #778198 !important;
    font-size: 0.69rem !important;
    font-weight: 600 !important;
    line-height: 1.2 !important;
}}

.hr-notification-empty {{
    padding: 24px 16px !important;
    text-align: center !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    background: #F8FAFD !important;
    background-color: #F8FAFD !important;
    border: 1px dashed #CFD6E3 !important;
    border-radius: 12px !important;
}}

.hr-notification-empty-icon {{
    font-size: 1.35rem !important;
    line-height: 1 !important;
}}

.hr-notification-empty-title {{
    margin-top: 8px !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    font-size: 0.9rem !important;
    font-weight: 780 !important;
}}

.hr-notification-empty-message {{
    margin: 5px auto 0 auto !important;
    max-width: 300px !important;
    color: #65708A !important;
    -webkit-text-fill-color: #65708A !important;
    font-size: 0.76rem !important;
    font-weight: 520 !important;
    line-height: 1.4 !important;
}}

/* Keep the action inside the notification popover readable. */
[data-baseweb="popover"]:has(.hr-notification-panel)
[data-testid="stButton"] button,
[data-testid="stPopoverBody"]:has(.hr-notification-panel)
[data-testid="stButton"] button {{
    margin-top: 4px !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid #CBD3E1 !important;
    border-radius: 10px !important;
    font-weight: 720 !important;
}}

[data-baseweb="popover"]:has(.hr-notification-panel)
[data-testid="stButton"] button:hover,
[data-baseweb="popover"]:has(.hr-notification-panel)
[data-testid="stButton"] button:focus-visible,
[data-testid="stPopoverBody"]:has(.hr-notification-panel)
[data-testid="stButton"] button:hover,
[data-testid="stPopoverBody"]:has(.hr-notification-panel)
[data-testid="stButton"] button:focus-visible {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border-color: var(--hr-primary) !important;
}}

/* =========================================================
   COMPANY ACCENT CONTRAST — v8.5.1
========================================================= */

button[kind="primary"],
button[kind="primary"] *,
[data-testid="stFormSubmitButton"] button,
[data-testid="stFormSubmitButton"] button *,
section[data-testid="stSidebar"] button[kind="primary"],
section[data-testid="stSidebar"] button[kind="primary"] *,
[data-testid="stFileUploaderDropzone"] button:hover,
[data-testid="stFileUploaderDropzone"] button:hover *,
[data-testid="stFileUploaderDropzone"] button:focus-visible,
[data-testid="stFileUploaderDropzone"] button:focus-visible *,
[data-testid="stDownloadButton"] > a:hover,
[data-testid="stDownloadButton"] > a:hover *,
[data-testid="stDownloadButton"] > button:hover,
[data-testid="stDownloadButton"] > button:hover *,
[data-testid="stDownloadButton"] > a:focus-visible,
[data-testid="stDownloadButton"] > a:focus-visible *,
[data-testid="stDownloadButton"] > button:focus-visible,
[data-testid="stDownloadButton"] > button:focus-visible *,
[data-baseweb="popover"] [role="option"][aria-selected="true"],
[data-baseweb="menu"] [role="option"][aria-selected="true"] {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
}}

[data-testid="stCheckbox"]
[role="checkbox"][aria-checked="true"] svg {{
    color: var(--hr-on-primary) !important;
    fill: currentColor !important;
}}

[data-testid="stColorPicker"] button {{
    border-color: var(--hr-border) !important;
    border-radius: 10px !important;
}}

[data-testid="stColorPicker"] button:hover,
[data-testid="stColorPicker"] button:focus-visible {{
    border-color: var(--hr-primary) !important;
    box-shadow: 0 0 0 2px var(--hr-primary-soft) !important;
}}

/* =========================================================
   NOTIFICATION TRIGGER COMPANY THEME — v8.7.1
   This comes after every generic accent/button rule.
========================================================= */

div[data-testid="stPopover"] > button,
div[data-testid="stPopover"] > button:hover,
div[data-testid="stPopover"] > button:focus,
div[data-testid="stPopover"] > button:focus-visible,
div[data-testid="stPopover"] > button:active,
div[data-testid="stPopover"] > button[aria-expanded="true"] {{
    min-width: 58px !important;
    min-height: 44px !important;
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border: 1px solid var(--hr-primary) !important;
    border-radius: 12px !important;
    font-weight: 800 !important;
    font-variant-numeric: tabular-nums !important;
    opacity: 1 !important;
}}

div[data-testid="stPopover"] > button:hover,
div[data-testid="stPopover"] > button:focus,
div[data-testid="stPopover"] > button:focus-visible,
div[data-testid="stPopover"] > button:active,
div[data-testid="stPopover"] > button[aria-expanded="true"] {{
    box-shadow:
        0 0 0 4px rgba(var(--hr-primary-rgb), 0.18),
        0 8px 20px rgba(var(--hr-primary-rgb), 0.22) !important;
}}

div[data-testid="stPopover"] > button *,
div[data-testid="stPopover"] > button:hover *,
div[data-testid="stPopover"] > button:focus *,
div[data-testid="stPopover"] > button:focus-visible *,
div[data-testid="stPopover"] > button:active *,
div[data-testid="stPopover"] > button[aria-expanded="true"] * {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    opacity: 1 !important;
}}

div[data-testid="stPopover"] > button svg,
div[data-testid="stPopover"] > button:hover svg,
div[data-testid="stPopover"] > button:focus svg,
div[data-testid="stPopover"] > button:focus-visible svg,
div[data-testid="stPopover"] > button:active svg,
div[data-testid="stPopover"] > button[aria-expanded="true"] svg {{
    color: var(--hr-on-primary) !important;
    fill: currentColor !important;
    stroke: currentColor !important;
    opacity: 1 !important;
}}


/* =========================================================
   NOTIFICATION UNREAD COMPANY THEME — v8.7.2
   The marker is rendered directly before the Streamlit popover.
========================================================= */

.hr-notification-state-marker {{
    display: none !important;
}}

/* No unread notification:
   white surface, company-color bell/arrow, and subtle company border. */
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) + div[data-testid="stPopover"] > button,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) + div[data-testid="stPopover"] > button:hover,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) + div[data-testid="stPopover"] > button:focus,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) + div[data-testid="stPopover"] > button:focus-visible,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) + div[data-testid="stPopover"] > button:active {{
    color: var(--hr-primary) !important;
    -webkit-text-fill-color: var(--hr-primary) !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid rgba(var(--hr-primary-rgb), 0.38) !important;
}}

/* Unread notification:
   full company-color button with automatic accessible text contrast. */
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) + div[data-testid="stPopover"] > button,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) + div[data-testid="stPopover"] > button:hover,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) + div[data-testid="stPopover"] > button:focus,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) + div[data-testid="stPopover"] > button:focus-visible,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) + div[data-testid="stPopover"] > button:active {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border: 1px solid var(--hr-primary) !important;
    box-shadow:
        0 0 0 3px rgba(var(--hr-primary-rgb), 0.16),
        var(--hr-shadow) !important;
}}

/* Keep all nested text, icon, count, and arrow visible. */
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) + div[data-testid="stPopover"] > button *,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) + div[data-testid="stPopover"] > button svg {{
    color: var(--hr-primary) !important;
    -webkit-text-fill-color: var(--hr-primary) !important;
    fill: currentColor !important;
    stroke: currentColor !important;
    opacity: 1 !important;
}}

div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) + div[data-testid="stPopover"] > button *,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) + div[data-testid="stPopover"] > button svg {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    fill: currentColor !important;
    stroke: currentColor !important;
    opacity: 1 !important;
}}

/* Open state remains readable and company-themed. */
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) + div[data-testid="stPopover"] > button[aria-expanded="true"] {{
    color: var(--hr-primary-text) !important;
    -webkit-text-fill-color: var(--hr-primary-text) !important;
    background: var(--hr-primary-soft) !important;
    background-color: var(--hr-primary-soft) !important;
    border-color: var(--hr-primary) !important;
}}

div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) + div[data-testid="stPopover"] > button[aria-expanded="true"] *,
div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) + div[data-testid="stPopover"] > button[aria-expanded="true"] svg {{
    color: var(--hr-primary-text) !important;
    -webkit-text-fill-color: var(--hr-primary-text) !important;
    fill: currentColor !important;
    stroke: currentColor !important;
    opacity: 1 !important;
}}

div[data-testid="stMarkdownContainer"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) + div[data-testid="stPopover"] > button[aria-expanded="true"] {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border-color: var(--hr-primary) !important;
}}

/* Fallback for Streamlit DOM variants where the marker and popover are
   wrapped in the same vertical block. */
div[data-testid="stVerticalBlock"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) div[data-testid="stPopover"] > button {{
    color: var(--hr-primary) !important;
    -webkit-text-fill-color: var(--hr-primary) !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border-color: rgba(var(--hr-primary-rgb), 0.38) !important;
}}

div[data-testid="stVerticalBlock"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) div[data-testid="stPopover"] > button {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border-color: var(--hr-primary) !important;
}}

div[data-testid="stVerticalBlock"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) div[data-testid="stPopover"] > button *,
div[data-testid="stVerticalBlock"]:has(
    .hr-notification-state-marker[data-notification-state="empty"]
) div[data-testid="stPopover"] > button svg {{
    color: var(--hr-primary) !important;
    -webkit-text-fill-color: var(--hr-primary) !important;
    fill: currentColor !important;
    stroke: currentColor !important;
}}

div[data-testid="stVerticalBlock"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) div[data-testid="stPopover"] > button *,
div[data-testid="stVerticalBlock"]:has(
    .hr-notification-state-marker[data-notification-state="unread"]
) div[data-testid="stPopover"] > button svg {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    fill: currentColor !important;
    stroke: currentColor !important;
}}


/* =========================================================
   NOTIFICATION DIRECT COMPANY THEME — v8.7.3
   Stable keyed wrapper; does not depend on Streamlit siblings.
========================================================= */

.st-key-notification_bell_container {{
    width: auto !important;
    min-width: 0 !important;
}}

.st-key-notification_bell_container
[data-testid="stVerticalBlock"] {{
    gap: 0 !important;
}}

.st-key-notification_bell_container
.hr-notification-state-marker {{
    display: none !important;
}}

/* Always use the active company primary color. */
.st-key-notification_bell_container
[data-testid="stPopover"] > button,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:hover,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus-visible,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:active,
.st-key-notification_bell_container
[data-testid="stPopover"] > button[aria-expanded="true"] {{
    min-width: 54px !important;
    min-height: 44px !important;
    padding: 0.55rem 0.82rem !important;
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border: 1px solid var(--hr-primary) !important;
    border-radius: 12px !important;
    font-weight: 800 !important;
    box-shadow:
        0 7px 18px rgba(var(--hr-primary-rgb), 0.20),
        var(--hr-shadow) !important;
    opacity: 1 !important;
}}

/* Force emoji/text/count/arrow to remain readable. */
.st-key-notification_bell_container
[data-testid="stPopover"] > button *,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:hover *,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus *,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus-visible *,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:active *,
.st-key-notification_bell_container
[data-testid="stPopover"] > button[aria-expanded="true"] * {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    opacity: 1 !important;
}}

.st-key-notification_bell_container
[data-testid="stPopover"] > button svg,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:hover svg,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus svg,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus-visible svg,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:active svg,
.st-key-notification_bell_container
[data-testid="stPopover"] > button[aria-expanded="true"] svg {{
    color: var(--hr-on-primary) !important;
    fill: currentColor !important;
    stroke: currentColor !important;
    opacity: 1 !important;
}}

/* Hover/open remains company-themed but visually responsive. */
.st-key-notification_bell_container
[data-testid="stPopover"] > button:hover,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus-visible,
.st-key-notification_bell_container
[data-testid="stPopover"] > button[aria-expanded="true"] {{
    filter: brightness(0.92) !important;
    box-shadow:
        0 0 0 4px rgba(var(--hr-primary-rgb), 0.18),
        0 9px 22px rgba(var(--hr-primary-rgb), 0.24) !important;
}}

/* Additional fallback for Streamlit versions that expose the key on
   an ancestor rather than the immediate container. */
div[class*="st-key-notification_bell_container"]
[data-testid="stPopover"] > button,
div[class*="st-key-notification_bell_container"]
[data-testid="stPopover"] > button:hover,
div[class*="st-key-notification_bell_container"]
[data-testid="stPopover"] > button:focus,
div[class*="st-key-notification_bell_container"]
[data-testid="stPopover"] > button:focus-visible,
div[class*="st-key-notification_bell_container"]
[data-testid="stPopover"] > button:active,
div[class*="st-key-notification_bell_container"]
[data-testid="stPopover"] > button[aria-expanded="true"] {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border-color: var(--hr-primary) !important;
}}

div[class*="st-key-notification_bell_container"]
[data-testid="stPopover"] > button *,
div[class*="st-key-notification_bell_container"]
[data-testid="stPopover"] > button svg {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    fill: currentColor !important;
    stroke: currentColor !important;
    opacity: 1 !important;
}}


/* =========================================================
   NOTIFICATION DEFAULT VISIBILITY — v8.7.4
========================================================= */

.st-key-notification_bell_container
[data-testid="stPopover"] > button {{
    color: var(--hr-primary) !important;
    -webkit-text-fill-color: var(--hr-primary) !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid var(--hr-primary) !important;
    opacity: 1 !important;
}}

.st-key-notification_bell_container
[data-testid="stPopover"] > button:hover,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus-visible,
.st-key-notification_bell_container
[data-testid="stPopover"] > button[aria-expanded="true"] {{
    color: var(--hr-primary) !important;
    -webkit-text-fill-color: var(--hr-primary) !important;
    background: var(--hr-primary-soft) !important;
    background-color: var(--hr-primary-soft) !important;
    border-color: var(--hr-primary) !important;
}}

.st-key-notification_bell_container
[data-testid="stPopover"] > button *,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:hover *,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus *,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus-visible *,
.st-key-notification_bell_container
[data-testid="stPopover"] > button[aria-expanded="true"] * {{
    color: var(--hr-primary) !important;
    -webkit-text-fill-color: var(--hr-primary) !important;
    opacity: 1 !important;
}}

.st-key-notification_bell_container
[data-testid="stPopover"] > button svg,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:hover svg,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus svg,
.st-key-notification_bell_container
[data-testid="stPopover"] > button:focus-visible svg,
.st-key-notification_bell_container
[data-testid="stPopover"] > button[aria-expanded="true"] svg {{
    color: var(--hr-primary) !important;
    fill: currentColor !important;
    stroke: currentColor !important;
    opacity: 1 !important;
}}


/* =========================================================
   STABLE NOTIFICATION BUTTON AND DIALOG — v8.7.5
========================================================= */

.st-key-global_notification_button button,
.st-key-global_notification_button button:hover,
.st-key-global_notification_button button:focus,
.st-key-global_notification_button button:focus-visible,
.st-key-global_notification_button button:active {{
    min-width: 68px !important;
    min-height: 44px !important;
    padding: 0.55rem 0.85rem !important;
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border: 1px solid var(--hr-primary) !important;
    border-radius: 12px !important;
    font-weight: 850 !important;
    font-variant-numeric: tabular-nums !important;
    opacity: 1 !important;
    box-shadow:
        0 6px 16px rgba(var(--hr-primary-rgb), 0.18) !important;
}}

.st-key-global_notification_button button *,
.st-key-global_notification_button button:hover *,
.st-key-global_notification_button button:focus *,
.st-key-global_notification_button button:focus-visible *,
.st-key-global_notification_button button:active * {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    opacity: 1 !important;
}}

.st-key-global_notification_button button:hover,
.st-key-global_notification_button button:focus-visible {{
    background: var(--hr-primary-hover) !important;
    background-color: var(--hr-primary-hover) !important;
    border-color: var(--hr-primary-hover) !important;
    box-shadow:
        0 0 0 4px rgba(var(--hr-primary-rgb), 0.16),
        0 8px 18px rgba(var(--hr-primary-rgb), 0.20) !important;
}}

[data-testid="stDialog"] {{
    color: #10172A !important;
}}

[data-testid="stDialog"] > div {{
    background: #FFFFFF !important;
    border-radius: 18px !important;
}}

[data-testid="stDialog"] h1,
[data-testid="stDialog"] h2,
[data-testid="stDialog"] h3,
[data-testid="stDialog"] h4,
[data-testid="stDialog"] p,
[data-testid="stDialog"] label,
[data-testid="stDialog"] [data-testid="stCaptionContainer"],
[data-testid="stDialog"] [data-testid="stMarkdownContainer"] {{
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
}}

[data-testid="stDialog"] .hr-notification-panel,
[data-testid="stDialog"] .hr-notification-list,
[data-testid="stDialog"] .hr-notification-card,
[data-testid="stDialog"] .hr-notification-empty {{
    color: #10172A !important;
}}


/* =========================================================
   ANCHORED NOTIFICATION DROPDOWN — v8.7.6
========================================================= */

.st-key-notification_menu_wrapper {{
    position: relative !important;
    width: 100% !important;
    overflow: visible !important;
    z-index: 10020 !important;
}}

[data-testid="stColumn"]:has(
    .st-key-notification_menu_wrapper
) {{
    position: relative !important;
    overflow: visible !important;
    z-index: 10020 !important;
}}

.st-key-notification_dropdown_panel {{
    position: absolute !important;
    top: calc(100% + 8px) !important;
    right: 0 !important;
    width: min(390px, calc(100vw - 32px)) !important;
    max-height: min(540px, calc(100vh - 140px)) !important;
    overflow-y: auto !important;
    padding: 12px !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid #D8DEEA !important;
    border-radius: 16px !important;
    box-shadow: 0 18px 46px rgba(16, 23, 42, 0.22) !important;
    z-index: 10030 !important;
}}

.st-key-notification_dropdown_panel
[data-testid="stVerticalBlock"] {{
    gap: 0.55rem !important;
}}

.st-key-notification_dropdown_panel
[data-testid="stMarkdownContainer"],
.st-key-notification_dropdown_panel
[data-testid="stMarkdownContainer"] * {{
    opacity: 1 !important;
}}

.st-key-notification_dropdown_panel
[data-testid="stButton"] button {{
    min-height: 38px !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid #CBD3E1 !important;
    border-radius: 10px !important;
    font-weight: 720 !important;
}}

.st-key-notification_dropdown_panel
[data-testid="stButton"] button:hover,
.st-key-notification_dropdown_panel
[data-testid="stButton"] button:focus-visible {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border-color: var(--hr-primary) !important;
}}

/* Keep the bell button visible in its normal/default state. */
.st-key-global_notification_button button,
.st-key-global_notification_button button:hover,
.st-key-global_notification_button button:focus,
.st-key-global_notification_button button:focus-visible,
.st-key-global_notification_button button:active {{
    min-width: 68px !important;
    min-height: 44px !important;
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    background: var(--hr-primary) !important;
    background-color: var(--hr-primary) !important;
    border-color: var(--hr-primary) !important;
    font-weight: 850 !important;
    font-variant-numeric: tabular-nums !important;
    opacity: 1 !important;
}}

.st-key-global_notification_button button *,
.st-key-global_notification_button button:hover *,
.st-key-global_notification_button button:focus *,
.st-key-global_notification_button button:focus-visible *,
.st-key-global_notification_button button:active * {{
    color: var(--hr-on-primary) !important;
    -webkit-text-fill-color: var(--hr-on-primary) !important;
    opacity: 1 !important;
}}


/* =========================================================
   WIDE CLICKABLE NOTIFICATIONS — v8.7.7
========================================================= */

.st-key-notification_dropdown_panel {{
    position: fixed !important;
    top: 128px !important;
    right: 24px !important;
    width: min(460px, calc(100vw - 32px)) !important;
    min-width: min(460px, calc(100vw - 32px)) !important;
    max-width: min(460px, calc(100vw - 32px)) !important;
    max-height: min(620px, calc(100vh - 150px)) !important;
    overflow: hidden !important;
    z-index: 10030 !important;
}}

.st-key-notification_scroll_area {{
    width: 100% !important;
    max-height: min(430px, calc(100vh - 300px)) !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    padding-right: 4px !important;
    scrollbar-gutter: stable !important;
}}

.st-key-notification_action_footer {{
    position: relative !important;
    z-index: 4 !important;
    flex: 0 0 auto !important;
    width: 100% !important;
    margin-top: 2px !important;
    padding-top: 10px !important;
    background: #FFFFFF !important;
    border-top: 1px solid #E2E7EF !important;
    box-shadow: 0 -8px 14px rgba(255, 255, 255, 0.92) !important;
}}

.st-key-notification_action_footer
[data-testid="stVerticalBlock"] {{
    gap: 0 !important;
}}

/* Clickable notification cards. */
.st-key-notification_dropdown_panel
div[class*="st-key-notification_item_"] {{
    width: 100% !important;
    margin: 0 0 9px 0 !important;
}}

.st-key-notification_dropdown_panel
div[class*="st-key-notification_item_"]
[data-testid="stButton"] button {{
    display: flex !important;
    align-items: flex-start !important;
    justify-content: flex-start !important;
    width: 100% !important;
    min-height: 104px !important;
    height: auto !important;
    padding: 12px 14px !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    border: 1px solid #DCE2EC !important;
    border-radius: 12px !important;
    box-shadow: none !important;
    text-align: left !important;
}}

.st-key-notification_dropdown_panel
div[class*="st-key-notification_item_unread_"]
[data-testid="stButton"] button {{
    background: var(--hr-primary-soft) !important;
    background-color: var(--hr-primary-soft) !important;
    border-color: rgba(var(--hr-primary-rgb), 0.28) !important;
    box-shadow: inset 4px 0 0 var(--hr-primary) !important;
}}

.st-key-notification_dropdown_panel
div[class*="st-key-notification_item_"]
[data-testid="stButton"] button:hover,
.st-key-notification_dropdown_panel
div[class*="st-key-notification_item_"]
[data-testid="stButton"] button:focus-visible {{
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    background: var(--hr-primary-soft) !important;
    background-color: var(--hr-primary-soft) !important;
    border-color: var(--hr-primary) !important;
    box-shadow: 0 0 0 3px rgba(var(--hr-primary-rgb), 0.13) !important;
}}

.st-key-notification_dropdown_panel
div[class*="st-key-notification_item_"]
[data-testid="stButton"] button p {{
    width: 100% !important;
    margin: 0 !important;
    color: #10172A !important;
    -webkit-text-fill-color: #10172A !important;
    white-space: pre-wrap !important;
    overflow-wrap: anywhere !important;
    word-break: normal !important;
    text-align: left !important;
    font-size: 0.79rem !important;
    font-weight: 560 !important;
    line-height: 1.42 !important;
}}

.st-key-notification_dropdown_panel
.hr-notification-header {{
    position: relative !important;
    top: auto !important;
    z-index: 2 !important;
    padding-top: 12px !important;
    background: #FFFFFF !important;
}}

@media (max-width: 760px) {{
    .st-key-notification_dropdown_panel {{
        top: 118px !important;
        right: 16px !important;
        left: 16px !important;
        width: auto !important;
        min-width: 0 !important;
        max-width: none !important;
    }}
}}


/* =========================================================
   READ-ONLY CONTENT CONTRAST — v8.8.1
========================================================= */

div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"],
div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"] p,
div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"] li,
div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"] li *,
div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"] strong,
div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"] span,
div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"] blockquote,
div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"] th,
div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"] td {{
    color: var(--hr-text-primary) !important;
    -webkit-text-fill-color: var(--hr-text-primary) !important;
    opacity: 1 !important;
}}

[data-testid="stChatMessage"]
[data-testid="stMarkdownContainer"] li,
[data-testid="stChatMessage"]
[data-testid="stMarkdownContainer"] li *,
[data-testid="stMain"]
[data-testid="stMarkdownContainer"] li,
[data-testid="stMain"]
[data-testid="stMarkdownContainer"] li *,
[data-testid="stExpander"]
[data-testid="stMarkdownContainer"] li,
[data-testid="stExpander"]
[data-testid="stMarkdownContainer"] li *,
[data-testid="stAlert"]
[data-testid="stMarkdownContainer"] li,
[data-testid="stAlert"]
[data-testid="stMarkdownContainer"] li * {{
    color: var(--hr-text-primary) !important;
    -webkit-text-fill-color: var(--hr-text-primary) !important;
    opacity: 1 !important;
}}

div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"] a {{
    color: var(--hr-primary-text) !important;
    -webkit-text-fill-color: var(--hr-primary-text) !important;
}}

div[class*="st-key-hr_assistant_message_"]
[data-testid="stMarkdownContainer"] code {{
    color: var(--hr-text-primary) !important;
    -webkit-text-fill-color: var(--hr-text-primary) !important;
    background: var(--hr-primary-soft) !important;
    border: 1px solid rgba(var(--hr-primary-rgb), 0.16) !important;
    border-radius: 5px !important;
}}


/* =========================================================
   EMPLOYEE POLICY CONTENT CONTRAST — v8.8.2
========================================================= */

/* Exact extracted policy source text. */
.hr-employee-policy-content,
.hr-employee-policy-content * {{
    color: var(--hr-text-primary) !important;
    -webkit-text-fill-color: var(--hr-text-primary) !important;
    opacity: 1 !important;
}}

.hr-employee-policy-content {{
    display: block !important;
    width: 100% !important;
    padding: 8px 0 12px 0 !important;
    font-family: inherit !important;
    font-size: 0.94rem !important;
    font-weight: 500 !important;
    line-height: 1.62 !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    word-break: normal !important;
    background: transparent !important;
}}

/* Stable keyed policy wrappers. */
div[class*="st-key-employee_policy_content_"]
[data-testid="stMarkdownContainer"],
div[class*="st-key-employee_policy_content_"]
[data-testid="stMarkdownContainer"] *,
.st-key-employee_policy_assistant_answer
[data-testid="stMarkdownContainer"],
.st-key-employee_policy_assistant_answer
[data-testid="stMarkdownContainer"] * {{
    color: var(--hr-text-primary) !important;
    -webkit-text-fill-color: var(--hr-text-primary) !important;
    opacity: 1 !important;
}}

/* Fallback for current or future read-only st.text/pre output inside
   policy expanders. This does not target text inputs or text areas. */
[data-testid="stExpander"] [data-testid="stText"],
[data-testid="stExpander"] [data-testid="stText"] *,
[data-testid="stExpander"] pre,
[data-testid="stExpander"] pre * {{
    color: var(--hr-text-primary) !important;
    -webkit-text-fill-color: var(--hr-text-primary) !important;
    font-family: inherit !important;
    white-space: pre-wrap !important;
    overflow-wrap: anywhere !important;
    opacity: 1 !important;
}}

/* Policy summaries, headings, and numbered/list content. */
[data-testid="stExpander"]
[data-testid="stMarkdownContainer"] p,
[data-testid="stExpander"]
[data-testid="stMarkdownContainer"] strong,
[data-testid="stExpander"]
[data-testid="stMarkdownContainer"] span,
[data-testid="stExpander"]
[data-testid="stMarkdownContainer"] ol,
[data-testid="stExpander"]
[data-testid="stMarkdownContainer"] ul,
[data-testid="stExpander"]
[data-testid="stMarkdownContainer"] li,
[data-testid="stExpander"]
[data-testid="stMarkdownContainer"] li * {{
    color: var(--hr-text-primary) !important;
    -webkit-text-fill-color: var(--hr-text-primary) !important;
    opacity: 1 !important;
}}

/* =========================================================
   STREAMLIT 1.61 INPUT SURFACE COMPATIBILITY — v8.8.90
   Restore the approved dark controls after internal wrapper changes.
========================================================= */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input,
[data-testid="stTimeInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] [role="combobox"],
[data-testid="stMultiSelect"] [role="combobox"] {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    caret-color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
    border-color: #3A3D4A !important;
    border-radius: 10px !important;
    color-scheme: dark !important;
    opacity: 1 !important;
}}

[data-testid="stTextInput"] div:has(> input),
[data-testid="stNumberInput"] div:has(> input),
[data-testid="stDateInput"] div:has(> input),
[data-testid="stTimeInput"] div:has(> input),
[data-testid="stTextArea"] div:has(> textarea),
[data-testid="stSelectbox"] div:has(> [role="combobox"]),
[data-testid="stMultiSelect"] div:has(> [role="combobox"]) {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
    border-color: #3A3D4A !important;
    border-radius: 10px !important;
    color-scheme: dark !important;
}}

[data-testid="stSelectbox"] [role="combobox"] *,
[data-testid="stMultiSelect"] [role="combobox"] *,
[data-testid="stSelectbox"] div:has(> [role="combobox"]) *,
[data-testid="stMultiSelect"] div:has(> [role="combobox"]) * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    opacity: 1 !important;
}}

[data-testid="stTextInput"] input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stDateInput"] input::placeholder,
[data-testid="stTimeInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder,
[data-testid="stSelectbox"] [role="combobox"]::placeholder,
[data-testid="stMultiSelect"] [role="combobox"]::placeholder {{
    color: #B9BED0 !important;
    -webkit-text-fill-color: #B9BED0 !important;
    opacity: 0.86 !important;
}}

[data-testid="stTextInput"] input:disabled,
[data-testid="stNumberInput"] input:disabled,
[data-testid="stDateInput"] input:disabled,
[data-testid="stTimeInput"] input:disabled,
[data-testid="stTextArea"] textarea:disabled,
[data-testid="stSelectbox"] [aria-disabled="true"],
[data-testid="stMultiSelect"] [aria-disabled="true"] {{
    color: #D6D9E3 !important;
    -webkit-text-fill-color: #D6D9E3 !important;
    background: #252630 !important;
    background-color: #252630 !important;
    opacity: 1 !important;
}}

[data-testid="stTextInput"] div:has(> input):hover,
[data-testid="stNumberInput"] div:has(> input):hover,
[data-testid="stDateInput"] div:has(> input):hover,
[data-testid="stTimeInput"] div:has(> input):hover,
[data-testid="stTextArea"] div:has(> textarea):hover,
[data-testid="stSelectbox"] div:has(> [role="combobox"]):hover,
[data-testid="stMultiSelect"] div:has(> [role="combobox"]):hover {{
    background: #2D2F3A !important;
    background-color: #2D2F3A !important;
    border-color: var(--hr-primary) !important;
}}

[data-testid="stTextInput"] div:has(> input):focus-within,
[data-testid="stNumberInput"] div:has(> input):focus-within,
[data-testid="stDateInput"] div:has(> input):focus-within,
[data-testid="stTimeInput"] div:has(> input):focus-within,
[data-testid="stTextArea"] div:has(> textarea):focus-within,
[data-testid="stSelectbox"] div:has(> [role="combobox"]):focus-within,
[data-testid="stMultiSelect"] div:has(> [role="combobox"]):focus-within {{
    background: #252630 !important;
    background-color: #252630 !important;
    border-color: var(--hr-primary-text) !important;
    box-shadow: 0 0 0 1px var(--hr-primary) !important;
}}

/* =========================================================
   NATIVE-LOOK PERSISTENT ADMIN TABS — v8.8.85
   Keep session-backed navigation while matching the former st.tabs look.
========================================================= */
.st-key-company_profile_active_tab [data-testid="stSegmentedControl"],
.st-key-employees_active_tab [data-testid="stSegmentedControl"],
.st-key-policies_active_tab [data-testid="stSegmentedControl"],
.st-key-company_forms_active_tab [data-testid="stSegmentedControl"] {{
    width: max-content !important;
    max-width: 100% !important;
    padding: 0 !important;
    background: transparent !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}}

.st-key-company_profile_active_tab [data-testid="stSegmentedControl"] button,
.st-key-employees_active_tab [data-testid="stSegmentedControl"] button,
.st-key-policies_active_tab [data-testid="stSegmentedControl"] button,
.st-key-company_forms_active_tab [data-testid="stSegmentedControl"] button {{
    min-height: 42px !important;
    padding: 0.55rem 0.9rem !important;
    color: var(--hr-text-primary) !important;
    -webkit-text-fill-color: var(--hr-text-primary) !important;
    background: transparent !important;
    background-color: transparent !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-shadow: inset 0 -1px 0 var(--hr-border) !important;
    font-weight: 500 !important;
}}

.st-key-company_profile_active_tab [data-testid="stSegmentedControl"] button:hover,
.st-key-employees_active_tab [data-testid="stSegmentedControl"] button:hover,
.st-key-policies_active_tab [data-testid="stSegmentedControl"] button:hover,
.st-key-company_forms_active_tab [data-testid="stSegmentedControl"] button:hover {{
    color: var(--hr-primary-text) !important;
    -webkit-text-fill-color: var(--hr-primary-text) !important;
    background: transparent !important;
    box-shadow: inset 0 -2px 0 rgba(var(--hr-primary-rgb), 0.42) !important;
}}

.st-key-company_profile_active_tab [data-testid="stSegmentedControl"] button[aria-pressed="true"],
.st-key-company_profile_active_tab [data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-employees_active_tab [data-testid="stSegmentedControl"] button[aria-pressed="true"],
.st-key-employees_active_tab [data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-policies_active_tab [data-testid="stSegmentedControl"] button[aria-pressed="true"],
.st-key-policies_active_tab [data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-company_forms_active_tab [data-testid="stSegmentedControl"] button[aria-pressed="true"],
.st-key-company_forms_active_tab [data-testid="stSegmentedControl"] button[aria-checked="true"] {{
    color: var(--hr-primary-text) !important;
    -webkit-text-fill-color: var(--hr-primary-text) !important;
    background: transparent !important;
    background-color: transparent !important;
    box-shadow: inset 0 -3px 0 var(--hr-primary) !important;
    font-weight: 650 !important;
}}

/* Streamlit 1.50 renders segmented controls through BaseWeb button groups. */
:is(
    .st-key-company_profile_active_tab,
    .st-key-employees_active_tab,
    .st-key-policies_active_tab,
    .st-key-company_forms_active_tab
) [data-baseweb="button-group"] {{
    width: max-content !important;
    max-width: 100% !important;
    gap: 0 !important;
    padding: 0 !important;
    background: transparent !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}}

:is(
    .st-key-company_profile_active_tab,
    .st-key-employees_active_tab,
    .st-key-policies_active_tab,
    .st-key-company_forms_active_tab
) [data-baseweb="button-group"] button {{
    min-height: 42px !important;
    padding: 0.55rem 0.9rem !important;
    color: var(--hr-text-primary) !important;
    -webkit-text-fill-color: var(--hr-text-primary) !important;
    background: transparent !important;
    background-color: transparent !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-shadow: inset 0 -1px 0 var(--hr-border) !important;
    font-weight: 500 !important;
}}

:is(
    .st-key-company_profile_active_tab,
    .st-key-employees_active_tab,
    .st-key-policies_active_tab,
    .st-key-company_forms_active_tab
) [data-baseweb="button-group"] button * {{
    color: inherit !important;
    -webkit-text-fill-color: inherit !important;
}}

:is(
    .st-key-company_profile_active_tab,
    .st-key-employees_active_tab,
    .st-key-policies_active_tab,
    .st-key-company_forms_active_tab
) [data-baseweb="button-group"] button:hover {{
    color: var(--hr-primary-text) !important;
    -webkit-text-fill-color: var(--hr-primary-text) !important;
    background: transparent !important;
    box-shadow: inset 0 -2px 0 rgba(var(--hr-primary-rgb), 0.42) !important;
}}

:is(
    .st-key-company_profile_active_tab,
    .st-key-employees_active_tab,
    .st-key-policies_active_tab,
    .st-key-company_forms_active_tab
) [data-baseweb="button-group"] button[aria-pressed="true"],
:is(
    .st-key-company_profile_active_tab,
    .st-key-employees_active_tab,
    .st-key-policies_active_tab,
    .st-key-company_forms_active_tab
) [data-baseweb="button-group"] button[aria-checked="true"] {{
    color: var(--hr-primary-text) !important;
    -webkit-text-fill-color: var(--hr-primary-text) !important;
    background: transparent !important;
    background-color: transparent !important;
    box-shadow: inset 0 -3px 0 var(--hr-primary) !important;
    font-weight: 650 !important;
}}

/* =========================================================
   CHAT ASSISTANT ALIGNMENT + INPUT CONTRAST — v8.8.120
   Keep assistant responses on the left and move each signed-in user's
   question to the right without changing message behavior.
========================================================= */

[data-testid="stChatMessage"]:has(
    [data-testid="stChatMessageAvatarUser"]
) {{
    width: fit-content !important;
    max-width: min(72%, 760px) !important;
    margin-left: auto !important;
    margin-right: 0 !important;
    flex-direction: row-reverse !important;
}}

[data-testid="stChatMessage"]:has(
    [data-testid="stChatMessageAvatarUser"]
) [data-testid="stMarkdownContainer"] {{
    text-align: right !important;
}}

/*
   Render the whole Chat Assistant input as one dark rounded field. The keyed
   Streamlit element wrapper must remain transparent so no white outer panel
   appears around the native chat input.
*/
div[class*="st-key-admin_hr_assistant_chat_input__"],
div[class*="st-key-hr_assistant_chat_input__"] {{
    padding: 0 !important;
    background: transparent !important;
    background-color: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
}}

[data-testid="stChatInput"] {{
    color-scheme: dark !important;
    color: #FFFFFF !important;
    background: #252630 !important;
    background-color: #252630 !important;
    border: 1px solid #252630 !important;
    border-radius: 10px !important;
    box-shadow: none !important;
    overflow: hidden !important;
    padding: 0 5px 0 12px !important;
}}

[data-testid="stChatInput"] > div,
[data-testid="stChatInput"] div[data-baseweb="textarea"],
[data-testid="stChatInput"] div[data-baseweb="base-input"] {{
    background: transparent !important;
    background-color: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
}}

[data-testid="stChatInput"] div[data-baseweb="textarea"],
[data-testid="stChatInput"] textarea {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: transparent !important;
    background-color: transparent !important;
    caret-color: #FFFFFF !important;
    border: 0 !important;
    box-shadow: none !important;
}}

[data-testid="stChatInput"] textarea::placeholder {{
    color: rgba(255, 255, 255, 0.76) !important;
    -webkit-text-fill-color: rgba(255, 255, 255, 0.76) !important;
    opacity: 1 !important;
}}

[data-testid="stChatInput"] button {{
    width: 34px !important;
    min-width: 34px !important;
    height: 34px !important;
    min-height: 34px !important;
    padding: 0 !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: #101116 !important;
    background-color: #101116 !important;
    border: 1px solid #101116 !important;
    border-radius: 8px !important;
    box-shadow: none !important;
    opacity: 1 !important;
}}

[data-testid="stChatInput"] button:hover,
[data-testid="stChatInput"] button:focus,
[data-testid="stChatInput"] button:disabled {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: #101116 !important;
    background-color: #101116 !important;
    border-color: #101116 !important;
    opacity: 1 !important;
}}

[data-testid="stChatInput"] button > * {{
    display: flex !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    opacity: 1 !important;
}}

[data-testid="stChatInput"] button::before {{
    content: none !important;
    display: none !important;
}}

/* Keep Streamlit's original send-arrow shape; only its color is controlled. */
[data-testid="stChatInput"] button svg {{
    display: block !important;
    color: #FFFFFF !important;
    opacity: 1 !important;
}}

/* Compact Quick Action title/subtitle rhythm in both portal side panels. */
div[class*="st-key-admin_quick_action_card_"] [data-testid="stVerticalBlock"],
div[class*="st-key-employee_quick_action_card_"] [data-testid="stVerticalBlock"] {{
    gap: 0.42rem !important;
}}

div[class*="st-key-admin_quick_action_card_"] [data-testid="stMarkdownContainer"] p,
div[class*="st-key-employee_quick_action_card_"] [data-testid="stMarkdownContainer"] p {{
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}}

@media (max-width: 760px) {{
    [data-testid="stChatMessage"]:has(
        [data-testid="stChatMessageAvatarUser"]
    ) {{
        max-width: 88% !important;
    }}
}}

    </style>
    """

    st.markdown(css, unsafe_allow_html=True)

    # Restore and save the browser's last theme selection.
    _synchronize_theme_with_browser(get_active_theme())

    # Apply browser-level behavior after the CSS is injected.
    _enforce_input_value_contrast(tokens)
    _install_native_copy_shortcut_guard()
