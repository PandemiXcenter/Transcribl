# Offline Article review checks

The fixture runs the real extraction, translation orchestration, storage, API and
NiceGUI interface with a deterministic fake translator. It never calls a provider.
All PDFs, rendered pages, runs, review edits, preferences and keys are kept in a
temporary directory removed on normal shutdown. Use Ctrl+C to stop the fixture.
Do not enter real keys; a dummy value can exercise form validation if needed.

```bash
uv run python tests/browser/review_fixture.py --check
uv run python tests/browser/review_fixture.py
```

The default address is `http://127.0.0.1:8768`; `--port` can select another free
loopback port. The fixture prints its synthetic PDF directory for upload checks.
Each launch creates fresh data. No user artifacts or saved workbench settings are
read. PDF export still requires external XeLaTeX; Markdown, text and LaTeX source
downloads do not.

In **Articles**, choose **Review sample A.pdf** or **Review sample B.pdf**. Each
has two readable source pages, edge markers for panning, enough translated text to
scroll, a paragraph spanning the physical page boundary, and one owned footnote.
The spanning paragraph repairs a synthetic page-end `con-` into `continues`;
a small clickable line marks the page shift without interrupting the prose.
The note's owner starts with `😀 Evidence`; its marker belongs at Unicode offset
10. “olde” has two unresolved annotated occurrences and “recorded” has only one.
The two article titles also make stale responses from rapid article switches
visible.

Use a real browser through the Playwright CLI (no additional test runner needed):

```bash
command -v npx
PWCLI="$HOME/.codex/skills/playwright/scripts/playwright_cli.sh"
"$PWCLI" -s=article-review open http://127.0.0.1:8768 --browser webkit --headed
"$PWCLI" -s=article-review snapshot
# Use the current snapshot's references for clicks and inputs.
"$PWCLI" -s=article-review screenshot
"$PWCLI" -s=article-review close
```

Capture useful screenshots/traces under the ignored `output/playwright/` directory.
Repeat relevant checks at desktop width and the minimum supported window size.

## Regression checklist

1. Switch between Translate, Glossaries and Articles; open and close Settings.
   Open article A, then return to the catalog and open article B. Its title,
   translation, source image, progress and export targets must all describe B.
2. On a source page, increase zoom and reach every page corner using the offered
   pan/scroll controls. Reset the view and verify the whole page fits again.
   Scroll the translation across physical page 2 and back. Only the active source
   image should load; zoom must persist and pan must stay bounded for the new page.
3. Scroll the translation with a wheel, keyboard and scrollbar. Check long linked
   paragraphs at the page boundary. Source synchronization must use the physical
   page marker, including a marker inside a joined paragraph. Reopen an article
   and verify its saved physical page position.
4. Edit a body section and the linked paragraph. Navigate within the article and
   interact with other controls before saving. Draft text and caret must survive
   operations that preserve the edit; leaving or discarding must make the loss
   explicit. Save once, inspect its revision and validate the section.
5. Open the uncertainties list. The “olde” group must initially have count 2;
   inspect one highlight and verify both one-occurrence and all-occurrence actions.
   “recorded” must offer only one. Replace an occurrence and confirm the group
   count and highlights update without changing unrelated reviewer-authored text.
6. Edit the starred footnote and its owner/marker position. Check that the emoji
   does not shift the marker by one character. Save and confirm the marker and
   note still pair correctly.
7. Open review menus, uncertainty controls and dialogs using the keyboard. Escape
   should dismiss transient controls, focus should remain visible, and controls
   should remain reachable without horizontal document scrolling at narrow widths.
8. Download reviewed Markdown/text/LaTeX after saving. Confirm edits appear in the
   download and changing the display currency leaves the active draft unchanged.
9. With request throttling or a delayed review response, quickly select two
   different articles. A late response from the first article must not overwrite
   the second article or receive its review-position updates.

These checks validate the local UI, not live provider output or native app builds.
