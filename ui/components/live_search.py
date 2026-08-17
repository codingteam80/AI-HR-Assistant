"""Reusable debounced search input for instant portal filtering.

Native ``st.text_input`` commits its value on Enter or focus loss. Search
fields need a different interaction: update while the user types, preserve
focus, show optional suggestions, and clear immediately. Streamlit Components
v2 supplies that bidirectional state without an external JavaScript package.
"""

from __future__ import annotations

from collections.abc import Iterable

import streamlit as st


_LIVE_SEARCH_HTML = """
<div class="hr-live-search">
  <label for="hr-live-search-input"></label>
  <div class="hr-live-search-control">
    <input
      id="hr-live-search-input"
      type="text"
      autocomplete="off"
      spellcheck="false"
      list="hr-live-search-suggestions"
    />
    <button type="button" aria-label="Clear search" title="Clear search">×</button>
    <datalist id="hr-live-search-suggestions"></datalist>
  </div>
</div>
"""


_LIVE_SEARCH_CSS = """
:host {
  display: block;
  width: 100%;
  color: var(--st-text-color, #111827);
  font-family: var(--st-font, "Source Sans Pro", sans-serif);
}

.hr-live-search {
  width: 100%;
}

.hr-live-search label {
  display: block;
  margin: 0 0 0.36rem 0;
  color: var(--st-text-color, #111827);
  font-size: 0.875rem;
  font-weight: 600;
  line-height: 1.25rem;
}

.hr-live-search-control {
  position: relative;
  width: 100%;
}

.hr-live-search input {
  box-sizing: border-box;
  width: 100%;
  min-height: 2.5rem;
  padding: 0.55rem 2.55rem 0.55rem 0.75rem;
  border: 1px solid #3b3d49;
  border-radius: 0.65rem;
  outline: none;
  background: #252630;
  color: #ffffff;
  font: inherit;
  font-size: 0.875rem;
  line-height: 1.25rem;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.hr-live-search input::placeholder {
  color: #aeb2c0;
  opacity: 1;
}

.hr-live-search input:hover {
  border-color: #676a78;
}

.hr-live-search input:focus {
  border-color: var(--st-primary-color, #2f740b);
  box-shadow: 0 0 0 1px var(--st-primary-color, #2f740b);
}

.hr-live-search button {
  position: absolute;
  top: 50%;
  right: 0.45rem;
  display: grid;
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
  transform: translateY(-50%);
  place-items: center;
  border: 0;
  border-radius: 0.42rem;
  background: transparent;
  color: #ffffff;
  font: inherit;
  font-size: 1.15rem;
  line-height: 1;
  cursor: pointer;
}

.hr-live-search button:hover,
.hr-live-search button:focus-visible {
  background: rgba(255, 255, 255, 0.12);
  outline: none;
}

.hr-live-search button[hidden] {
  display: none;
}
"""


_LIVE_SEARCH_JS = """
export default function(component) {
  const { data, parentElement, setStateValue } = component;
  const label = parentElement.querySelector('label');
  const input = parentElement.querySelector('input');
  const clearButton = parentElement.querySelector('button');
  const datalist = parentElement.querySelector('datalist');
  let debounceTimer = null;

  label.textContent = data.label ?? 'Search';
  label.title = data.help ?? '';
  input.placeholder = data.placeholder ?? '';
  input.setAttribute('aria-label', data.label ?? 'Search');

  // Keep the caret/focus while a debounced search reruns the Python script.
  // Programmatic values are synchronized whenever the field is not active.
  const activeElement = parentElement.activeElement ?? document.activeElement;
  if (activeElement !== input && input.value !== (data.value ?? '')) {
    input.value = data.value ?? '';
  }

  datalist.replaceChildren();
  (data.suggestions ?? []).forEach((suggestion) => {
    const option = document.createElement('option');
    option.value = String(suggestion);
    datalist.appendChild(option);
  });

  const updateClearButton = () => {
    clearButton.hidden = input.value.length === 0;
  };

  const commit = () => {
    setStateValue('value', input.value);
  };

  input.oninput = () => {
    updateClearButton();
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(
      commit,
      Number(data.debounce_ms ?? 220),
    );
  };

  input.onkeydown = (event) => {
    if (event.key === 'Escape' && input.value) {
      event.preventDefault();
      window.clearTimeout(debounceTimer);
      input.value = '';
      updateClearButton();
      commit();
    }
  };

  clearButton.onclick = () => {
    window.clearTimeout(debounceTimer);
    input.value = '';
    updateClearButton();
    input.focus();
    commit();
  };

  updateClearButton();

  return () => {
    window.clearTimeout(debounceTimer);
  };
}
"""


def _no_op() -> None:
    """Provide the stable callback required by a default component state."""


_components_v2 = getattr(
    getattr(st, "components", None),
    "v2",
    None,
)
_live_search_component = (
    _components_v2.component(
        "hr_portal_live_search",
        html=_LIVE_SEARCH_HTML,
        css=_LIVE_SEARCH_CSS,
        js=_LIVE_SEARCH_JS,
    )
    if _components_v2 is not None
    else None
)


def _component_state_key(key: str) -> str:
    # Components v2 reserves ``__`` as its internal event-ID delimiter.
    return f"live_search_component_{key.replace('__', '_')}"


def clear_live_search(key: str) -> None:
    """Clear one live-search value before its next render."""

    if _live_search_component is None:
        st.session_state[key] = ""
        return
    component_key = _component_state_key(key)
    saved_state = st.session_state.get(component_key)
    if isinstance(saved_state, dict):
        saved_state["value"] = ""
    else:
        st.session_state[component_key] = {"value": ""}


def live_search_input(
    label: str,
    *,
    key: str,
    placeholder: str = "",
    suggestions: Iterable[object] = (),
    debounce_ms: int = 220,
    help: str | None = None,
) -> str:
    """Return a case-preserving search value updated while the user types."""

    if _live_search_component is None:
        # Compatibility fallback for an older environment. The project
        # requirements use Streamlit 1.61+, where Components v2 is available.
        return st.text_input(
            label,
            key=key,
            placeholder=placeholder,
            help=help,
        )

    component_key = _component_state_key(key)
    saved_state = st.session_state.get(component_key, {})
    current_value = (
        str(saved_state.get("value") or "")
        if isinstance(saved_state, dict)
        else ""
    )
    normalized_suggestions = list(
        dict.fromkeys(
            str(item).strip()
            for item in suggestions
            if item is not None and str(item).strip()
        )
    )[:250]

    result = _live_search_component(
        data={
            "label": label,
            "placeholder": placeholder,
            "help": help or "",
            "value": current_value,
            "suggestions": normalized_suggestions,
            "debounce_ms": max(100, min(int(debounce_ms), 1000)),
        },
        default={"value": current_value},
        key=component_key,
        on_value_change=_no_op,
        width="stretch",
        height="content",
    )
    value = getattr(result, "value", current_value)
    return str(value or "")
