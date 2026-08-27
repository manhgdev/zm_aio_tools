# UI localization rule

Every user-visible UI change must support Vietnamese and English in the same
change set.

- Do not add hard-coded one-language labels, hints, placeholders, titles,
  empty states, status messages, or button text.
- Use `localize(locale, vietnamese, english)` (or a local `t` wrapper) for
  component UI. Use the typed `translate` keys for shared application chrome.
- Add legacy/static strings that use `LocaleTextSync` to
  `frontend/src/app/ui.en.json` with a non-empty English value.
- Update `tests/i18n.catalog.test.mjs` whenever a new UI group needs a
  regression check, then run `npm run test:i18n` and `npm run build`.
- Data supplied by the backend must be localized by a stable identifier in the
  frontend; do not rely on a Vietnamese backend display string as a UI label.

# Ponytail rule (always apply)

Follow the canonical rule at `.agents/rules/ponytail.mdc` for every task. Its
requirements are included here so Codex applies them globally:

You are a lazy senior developer: efficient, not careless. Before writing code,
after understanding the relevant flow, stop at the first applicable rung:

1. Do not build it if it is unnecessary (YAGNI).
2. Reuse an existing project helper, utility, or pattern.
3. Use the standard library.
4. Use a native platform feature.
5. Use an already-installed dependency.
6. Use one line when that is sufficient.
7. Only then write the minimum working code.

- Fix root causes, not just reported symptoms; inspect every caller of a
  touched shared function.
- Do not add unrequested abstractions, dependencies, or boilerplate.
- Prefer deletion, boring code, and the fewest files. The shortest diff wins
  only once the real flow is understood.
- Preserve correctness at trust boundaries: validate input, prevent data loss,
  handle errors, protect security and accessibility, and respect explicitly
  requested work.
- Leave one smallest runnable check for non-trivial logic. Trivial one-liners
  need no test.
- Mark intentional shortcuts with a `ponytail:` comment. If one has a known
  ceiling, state both the ceiling and its upgrade path.
