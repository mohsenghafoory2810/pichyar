---
name: persian-ui-check
description: Find and fix English text shown in the Pichyar storefront or admin panel (the UI must be fully Persian). Use after changing templates, models, admin classes, forms, settings or dependencies (Django or django-q2 / axes / django-otp / import-export upgrades), when the user reports English words on a page («متن انگلیسی», «جملات انگلیسی»), or when the post-commit hook reports a failed Persian UI check.
---

# Persian UI check

The site and the admin are Persian-only. English leaks in from five places; the check covers all of them.

## Run the check

From the project root (use `.venv/bin/python` on Linux/macOS):

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe manage.py test core.tests.test_translations
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe .claude/skills/persian-ui-check/scan_english.py
```

`scan_english.py` renders, with the test client against the dev database (read-only), every
storefront URL as guest and as a customer, and for every admin model the list, add, change, history,
import and export pages, plus the admin JS catalog. It prints each English string with the pages it
is on and exits 1 if any are found or a page crashes. It is slow on this machine (several minutes):
run it in the background.

The hook in `.claude/settings.json` runs both after every `git commit` (in the background, script
`after_commit.sh`) and wakes Claude only when something fails.

## Fix by source

| What you see | Where it comes from | Fix |
|---|---|---|
| Developer notes as text on a page | multi-line `{# … #}` (only single-line works) | use `{% comment %}…{% endcomment %}` |
| A third-party or new-Django string (`Failed tasks`, `Reset password`, `Select all`, JS widget text) | the package ships no / an outdated `fa` translation | add the exact msgid to `locale/fa/LC_MESSAGES/django.po` (JS strings: `djangojs.po`, keep `msgctxt`/plurals), then `python scripts/compile_po.py` and commit `.po` + `.mo` |
| A model/app name that is not a gettext string (`TOTP devices`, `Axes`, `Otp_Totp`) | plain `verbose_name` in the package | add it to `APP_NAMES` / `MODEL_NAMES` in `core/i18n.py` |
| `Can add …` in the permission picker | permission names Django stores in English | renamed by `core.i18n.persian_permission_names` on `migrate`; run `python manage.py migrate` |
| English in our own code (labels, messages, help texts, templates) | project code | write it in Persian where it is defined |

To find a third-party msgid exactly, search the package source in `.venv/Lib/site-packages/<pkg>`
(the text inside `_("…")` / `{% translate "…" %}`, trailing spaces included); a wrong msgid silently
does nothing.

## Not findings

Data and technical terms stay as they are: slugs (`tobacco`), usernames, django-q task names,
password hash details, SKU / API / SEO / alt / slug / noindex / file formats, brand names, URLs, and
Django's hard-coded icon alt texts (`True` / `False` / `Search`). If the scan reports something like
that, add the word to `ALLOWED_WORDS` (or the string to `ALLOWED_EXACT`) at the top of
`scan_english.py` instead of translating it.

## After fixing

Re-run both commands until they pass. The full suite (`python manage.py test`) must still pass,
then commit the fix.
