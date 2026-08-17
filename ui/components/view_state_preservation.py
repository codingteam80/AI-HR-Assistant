"""Application-wide browser view preservation across Streamlit reruns.

Streamlit intentionally reruns the page after widget callbacks and save
actions. This component keeps the browser on the same visible workspace by
remembering scroll position, selected native tabs, and expanded sections for
the signed-in user and current page. It does not write widget keys through the
Session State API, so it cannot trigger duplicate default/session-state
warnings.
"""

from __future__ import annotations

import json

from authentication.current_user import AuthenticatedUser
from ui.components.browser_bridge import render_browser_bridge


def preserve_current_view(
    *,
    current_user: AuthenticatedUser,
    portal_mode: str,
    page: str,
) -> None:
    """Install warning-free post-action view restoration for one portal page."""

    scope = ":".join(
        (
            str(current_user.company_id),
            str(current_user.user_id),
            portal_mode.strip().casefold() or "portal",
            page.strip().casefold() or "page",
        )
    )
    scope_json = json.dumps(scope)

    render_browser_bridge(
        f"""
        <script>
        (() => {{
            const parentWindow = parent.window;
            const parentDocument = parent.document;
            const storageKey = "ai-hr-current-view:" + {scope_json};
            const controllerKey = "__aiHrCurrentViewPreserver";
            if (
                parentWindow[controllerKey]
                && typeof parentWindow[controllerKey].cleanup === "function"
            ) {{
                parentWindow[controllerKey].cleanup();
            }}
            const normalize = (value) => (value || "")
                .replace(/\\s+/g, " ")
                .trim();

            const readState = () => {{
                try {{
                    const parsed = JSON.parse(
                        parentWindow.sessionStorage.getItem(storageKey) || "null"
                    );
                    return parsed && typeof parsed === "object" ? parsed : null;
                }} catch (_) {{
                    return null;
                }}
            }};

            const scrollContainer = () => {{
                const candidates = [
                    parentDocument.querySelector('[data-testid="stMain"]'),
                    parentDocument.querySelector('[data-testid="stAppViewContainer"]'),
                    parentDocument.scrollingElement,
                    parentDocument.documentElement,
                ].filter(Boolean);
                return candidates.find((item) =>
                    item.scrollHeight > item.clientHeight + 4
                ) || parentDocument.scrollingElement || parentDocument.documentElement;
            }};

            const expanderStates = () => {{
                const occurrences = new Map();
                const output = {{}};
                parentDocument
                    .querySelectorAll('[data-testid="stExpander"]')
                    .forEach((container) => {{
                        const details = container.matches("details")
                            ? container
                            : container.querySelector("details");
                        const summary = details
                            ? details.querySelector("summary")
                            : container.querySelector("summary");
                        if (!details || !summary) return;
                        const label = normalize(summary.textContent) || "expander";
                        const occurrence = occurrences.get(label) || 0;
                        occurrences.set(label, occurrence + 1);
                        output[`${{label}}::${{occurrence}}`] = Boolean(details.open);
                    }});
                return output;
            }};

            const activeTabStates = () => {{
                const output = {{}};
                parentDocument
                    .querySelectorAll('[data-testid="stTabs"]')
                    .forEach((container, groupIndex) => {{
                        const tabs = Array.from(
                            container.querySelectorAll('button[role="tab"]')
                        );
                        const selected = tabs.findIndex((tab) =>
                            tab.getAttribute("aria-selected") === "true"
                        );
                        if (selected >= 0) {{
                            output[String(groupIndex)] = {{
                                index: selected,
                                label: normalize(tabs[selected].textContent),
                            }};
                        }}
                    }});
                return output;
            }};

            let restoring = true;
            let writeTimer = null;
            const writeState = (force = false) => {{
                if (restoring && !force) return;
                const scroller = scrollContainer();
                const state = {{
                    scrollTop: Number(scroller.scrollTop || parentWindow.scrollY || 0),
                    tabs: activeTabStates(),
                    expanders: expanderStates(),
                    savedAt: Date.now(),
                }};
                try {{
                    parentWindow.sessionStorage.setItem(
                        storageKey,
                        JSON.stringify(state),
                    );
                }} catch (_) {{
                    // Storage restrictions must never block a save action.
                }}
            }};
            const scheduleWrite = () => {{
                parentWindow.clearTimeout(writeTimer);
                writeTimer = parentWindow.setTimeout(writeState, 60);
            }};

            const saved = readState();
            const restore = () => {{
                if (!saved) return;

                const storedExpanders = saved.expanders || {{}};
                const occurrences = new Map();
                parentDocument
                    .querySelectorAll('[data-testid="stExpander"]')
                    .forEach((container) => {{
                        const details = container.matches("details")
                            ? container
                            : container.querySelector("details");
                        const summary = details
                            ? details.querySelector("summary")
                            : container.querySelector("summary");
                        if (!details || !summary) return;
                        const label = normalize(summary.textContent) || "expander";
                        const occurrence = occurrences.get(label) || 0;
                        occurrences.set(label, occurrence + 1);
                        const key = `${{label}}::${{occurrence}}`;
                        if (
                            Object.prototype.hasOwnProperty.call(storedExpanders, key)
                            && Boolean(details.open) !== Boolean(storedExpanders[key])
                        ) {{
                            summary.click();
                        }}
                    }});

                const storedTabs = saved.tabs || {{}};
                parentDocument
                    .querySelectorAll('[data-testid="stTabs"]')
                    .forEach((container, groupIndex) => {{
                        const requested = storedTabs[String(groupIndex)];
                        if (!requested) return;
                        const tabs = Array.from(
                            container.querySelectorAll('button[role="tab"]')
                        );
                        const current = tabs.findIndex((tab) =>
                            tab.getAttribute("aria-selected") === "true"
                        );
                        let target = tabs.findIndex(
                            (tab) => normalize(tab.textContent) === requested.label
                        );
                        if (target < 0) target = Number(requested.index);
                        if (tabs[target] && target !== current) tabs[target].click();
                    }});

                const scroller = scrollContainer();
                const targetTop = Math.max(0, Number(saved.scrollTop || 0));
                scroller.scrollTo({{ top: targetTop, behavior: "auto" }});
                if (scroller === parentDocument.scrollingElement) {{
                    parentWindow.scrollTo({{ top: targetTop, behavior: "auto" }});
                }}
            }};

            // Capture before a button submit can start the Streamlit rerun.
            const handlePointerDown = () => writeState(true);
            const handleClick = () => scheduleWrite();
            const handleChange = () => scheduleWrite();
            const handleKeyDown = (event) => {{
                if (event.key === "Enter") writeState(true);
            }};
            const handleScroll = () => scheduleWrite();
            const handleBeforeUnload = () => writeState(true);
            parentDocument.addEventListener("pointerdown", handlePointerDown, true);
            parentDocument.addEventListener("click", handleClick, true);
            parentDocument.addEventListener("change", handleChange, true);
            parentDocument.addEventListener("keydown", handleKeyDown, true);
            const scroller = scrollContainer();
            scroller.addEventListener("scroll", handleScroll, {{ passive: true }});
            parentWindow.addEventListener("beforeunload", handleBeforeUnload);

            const observer = new MutationObserver(() => {{
                if (restoring) restore();
            }});
            observer.observe(parentDocument.body, {{ childList: true, subtree: true }});

            const restoreTimers = [40, 120, 280, 520, 850, 1150].map((delay) =>
                parentWindow.setTimeout(restore, delay)
            );
            const finishTimer = parentWindow.setTimeout(() => {{
                restoring = false;
                observer.disconnect();
                writeState();
            }}, 1300);

            parentWindow[controllerKey] = {{
                cleanup: () => {{
                    observer.disconnect();
                    parentWindow.clearTimeout(writeTimer);
                    restoreTimers.forEach((timer) => parentWindow.clearTimeout(timer));
                    parentWindow.clearTimeout(finishTimer);
                    parentDocument.removeEventListener(
                        "pointerdown", handlePointerDown, true
                    );
                    parentDocument.removeEventListener("click", handleClick, true);
                    parentDocument.removeEventListener("change", handleChange, true);
                    parentDocument.removeEventListener("keydown", handleKeyDown, true);
                    scroller.removeEventListener("scroll", handleScroll);
                    parentWindow.removeEventListener(
                        "beforeunload", handleBeforeUnload
                    );
                }},
            }};
        }})();
        </script>
        """
    )
