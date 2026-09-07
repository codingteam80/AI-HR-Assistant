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


# ---------------------------------------------------------------------------
# Free-text multi-search chips
# ---------------------------------------------------------------------------

_MULTI_SEARCH_HTML = """
<div class="hr-multi-search">
  <label for="hr-multi-search-input"></label>
  <div class="hr-multi-search-control" role="group">
    <div class="hr-multi-search-chips"></div>
    <input
      id="hr-multi-search-input"
      type="text"
      autocomplete="off"
      spellcheck="false"
    />
    <button
      class="hr-multi-search-clear-all"
      type="button"
      aria-label="Clear all search terms"
      title="Clear all search terms"
    >×</button>
  </div>
  <div class="hr-multi-search-hint"></div>
</div>
"""


_MULTI_SEARCH_CSS = """
:host {
  display: block;
  width: 100%;
  color: var(--st-text-color, #111827);
  font-family: var(--st-font, "Source Sans Pro", sans-serif);
}

.hr-multi-search {
  width: 100%;
}

.hr-multi-search label {
  display: block;
  margin: 0 0 0.36rem 0;
  color: var(--st-text-color, #111827);
  font-size: 0.875rem;
  font-weight: 600;
  line-height: 1.25rem;
}

.hr-multi-search-control {
  box-sizing: border-box;
  display: flex;
  width: 100%;
  min-height: 2.5rem;
  align-items: center;
  gap: 0.34rem;
  padding: 0.31rem 2.35rem 0.31rem 0.42rem;
  border: 1px solid #3b3d49;
  border-radius: 0.65rem;
  background: #252630;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  position: relative;
  overflow: hidden;
}

.hr-multi-search-control:hover {
  border-color: #676a78;
}

.hr-multi-search-control:focus-within {
  border-color: var(--st-primary-color, #2f740b);
  box-shadow: 0 0 0 1px var(--st-primary-color, #2f740b);
}

.hr-multi-search-chips {
  display: flex;
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  align-items: center;
  gap: 0.28rem;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}

.hr-multi-search-chip {
  display: inline-flex;
  flex: 0 0 auto;
  max-width: 22rem;
  min-height: 1.72rem;
  align-items: center;
  gap: 0.22rem;
  padding: 0.16rem 0.28rem 0.16rem 0.50rem;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 0.44rem;
  background: var(--st-primary-color, #2f740b);
  color: #ffffff;
  font-size: 0.82rem;
  font-weight: 600;
  line-height: 1.15rem;
}

.hr-multi-search-chip-text {
  display: block;
  max-width: 18rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hr-multi-search-chip-remove {
  display: grid;
  width: 1.25rem;
  height: 1.25rem;
  flex: 0 0 1.25rem;
  padding: 0;
  place-items: center;
  border: 0;
  border-radius: 0.3rem;
  background: transparent;
  color: #ffffff;
  cursor: pointer;
  font: inherit;
  font-size: 1rem;
  line-height: 1;
}

.hr-multi-search-chip-remove:hover,
.hr-multi-search-chip-remove:focus-visible {
  background: rgba(255, 255, 255, 0.18);
  outline: none;
}

.hr-multi-search input {
  box-sizing: border-box;
  flex: 1 1 9rem;
  min-width: 8rem;
  height: 1.8rem;
  padding: 0.12rem 0.28rem;
  border: 0;
  outline: none;
  background: transparent;
  color: #ffffff;
  font: inherit;
  font-size: 0.875rem;
  line-height: 1.25rem;
}

.hr-multi-search input::placeholder {
  color: #aeb2c0;
  opacity: 1;
}

.hr-multi-search-clear-all {
  position: absolute;
  top: 50%;
  right: 0.42rem;
  display: grid;
  width: 1.72rem;
  height: 1.72rem;
  padding: 0;
  transform: translateY(-50%);
  place-items: center;
  border: 0;
  border-radius: 0.42rem;
  background: transparent;
  color: #ffffff;
  cursor: pointer;
  font: inherit;
  font-size: 1.12rem;
  line-height: 1;
}

.hr-multi-search-clear-all:hover,
.hr-multi-search-clear-all:focus-visible {
  background: rgba(255, 255, 255, 0.12);
  outline: none;
}

.hr-multi-search-clear-all[hidden] {
  display: none;
}

.hr-multi-search-hint {
  min-height: 0.9rem;
  margin-top: 0.18rem;
  color: #8f95a5;
  font-size: 0.72rem;
  line-height: 0.9rem;
}
"""


_MULTI_SEARCH_JS = """
export default function(component) {
  const { data, parentElement, setStateValue } = component;
  const label = parentElement.querySelector('label');
  const control = parentElement.querySelector('.hr-multi-search-control');
  const chipHost = parentElement.querySelector('.hr-multi-search-chips');
  const input = parentElement.querySelector('input');
  const clearAll = parentElement.querySelector('.hr-multi-search-clear-all');
  const hint = parentElement.querySelector('.hr-multi-search-hint');

  const maxTerms = Math.max(1, Math.min(Number(data.max_terms ?? 24), 50));
  let terms = Array.isArray(data.terms)
    ? data.terms.map((value) => String(value).trim()).filter(Boolean).slice(0, maxTerms)
    : [];

  label.textContent = data.label ?? 'Search';
  label.title = data.help ?? '';
  input.placeholder = data.placeholder ?? 'Type a search term, then press Enter';
  input.setAttribute('aria-label', data.label ?? 'Search');
  control.setAttribute('aria-label', data.label ?? 'Search');
  hint.textContent = data.hint ?? 'Press Enter or comma to add another term. Results match any chip.';

  const normalize = (value) => String(value ?? '').trim().toLocaleLowerCase();
  const uniqueTerms = (items) => {
    const seen = new Set();
    const output = [];
    for (const raw of items) {
      const text = String(raw ?? '').trim();
      const normalized = normalize(text);
      if (!text || seen.has(normalized)) continue;
      seen.add(normalized);
      output.push(text);
      if (output.length >= maxTerms) break;
    }
    return output;
  };
  terms = uniqueTerms(terms);

  const commitTerms = (nextTerms) => {
    terms = uniqueTerms(nextTerms);
    setStateValue('terms', terms);
    renderChips();
  };

  const addDraft = () => {
    const draft = input.value.trim();
    if (!draft) return false;
    const pieces = draft
      .split(/[\\n,]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!pieces.length) return false;
    commitTerms([...terms, ...pieces]);
    input.value = '';
    return true;
  };

  const removeTerm = (index) => {
    const next = [...terms];
    next.splice(index, 1);
    commitTerms(next);
    input.focus();
  };

  function renderChips() {
    chipHost.replaceChildren();
    terms.forEach((term, index) => {
      const chip = document.createElement('span');
      chip.className = 'hr-multi-search-chip';
      chip.title = term;

      const text = document.createElement('span');
      text.className = 'hr-multi-search-chip-text';
      text.textContent = term;

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'hr-multi-search-chip-remove';
      remove.textContent = '×';
      remove.setAttribute('aria-label', `Remove search term ${term}`);
      remove.title = `Remove ${term}`;
      remove.onclick = (event) => {
        event.preventDefault();
        event.stopPropagation();
        removeTerm(index);
      };

      chip.append(text, remove);
      chipHost.appendChild(chip);
    });
    clearAll.hidden = terms.length === 0;
  }

  input.onkeydown = (event) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault();
      addDraft();
      return;
    }
    if (event.key === 'Backspace' && !input.value && terms.length) {
      event.preventDefault();
      removeTerm(terms.length - 1);
      return;
    }
    if (event.key === 'Escape' && input.value) {
      event.preventDefault();
      input.value = '';
    }
  };

  input.onpaste = () => {
    window.setTimeout(() => {
      if (/[\\n,]/.test(input.value)) addDraft();
    }, 0);
  };

  input.onblur = () => {
    addDraft();
  };

  control.onclick = (event) => {
    if (event.target === control || event.target === chipHost) input.focus();
  };

  clearAll.onclick = (event) => {
    event.preventDefault();
    event.stopPropagation();
    input.value = '';
    commitTerms([]);
    input.focus();
  };

  renderChips();
}
"""


_multi_search_component = (
    _components_v2.component(
        "hr_portal_multi_search",
        html=_MULTI_SEARCH_HTML,
        css=_MULTI_SEARCH_CSS,
        js=_MULTI_SEARCH_JS,
    )
    if _components_v2 is not None
    else None
)


def _multi_component_state_key(key: str) -> str:
    """Return a component-safe unique Session State key."""

    return f"multi_search_component_{key.replace('__', '_')}"


def clear_multi_search(key: str) -> None:
    """Clear every committed term for one multi-search control."""

    if _multi_search_component is None:
        st.session_state[key] = ""
        return
    component_key = _multi_component_state_key(key)
    saved_state = st.session_state.get(component_key)
    if isinstance(saved_state, dict):
        saved_state["terms"] = []
    else:
        st.session_state[component_key] = {"terms": []}


def multi_search_input(
    label: str,
    *,
    key: str,
    placeholder: str = "",
    max_terms: int = 24,
    help: str | None = None,
    hint: str = "Press Enter or comma to add another term. Results match any chip.",
) -> tuple[str, ...]:
    """Return committed free-text search terms as removable chips.

    Terms are manually typed; the control intentionally has no dropdown or
    selection list. Each committed chip is an independent OR search term.
    """

    if _multi_search_component is None:
        raw_value = st.text_input(
            label,
            key=key,
            placeholder=(
                placeholder
                or "Type comma-separated search terms, then press Enter"
            ),
            help=help,
        )
        return tuple(
            dict.fromkeys(
                part.strip()
                for part in str(raw_value or "").split(",")
                if part.strip()
            )
        )

    component_key = _multi_component_state_key(key)
    saved_state = st.session_state.get(component_key, {})
    current_terms = (
        list(saved_state.get("terms") or [])
        if isinstance(saved_state, dict)
        else []
    )
    current_terms = [str(value).strip() for value in current_terms if str(value).strip()]

    result = _multi_search_component(
        data={
            "label": label,
            "placeholder": placeholder,
            "help": help or "",
            "hint": hint,
            "terms": current_terms,
            "max_terms": max(1, min(int(max_terms), 50)),
        },
        default={"terms": current_terms},
        key=component_key,
        on_terms_change=_no_op,
        width="stretch",
        height="content",
    )
    terms = getattr(result, "terms", current_terms)
    if not isinstance(terms, (list, tuple)):
        return tuple(current_terms)

    output: list[str] = []
    seen: set[str] = set()
    for value in terms:
        text = str(value or "").strip()
        normalized = text.casefold()
        if not text or normalized in seen:
            continue
        seen.add(normalized)
        output.append(text)
    return tuple(output[: max(1, min(int(max_terms), 50))])
