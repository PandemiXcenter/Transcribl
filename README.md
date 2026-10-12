# Transcribl

Transcribl is a local tool for translating and reviewing page-preserving
PDFs. It turns each physical page into matched Markdown and an image, sends a
structured multimodal page-translation request, conditionally follows it with a
dedicated table-reconstruction request, validates both responses with Pydantic,
and compiles the canonical dataset into XeLaTeX source, with Markdown retained as
an additional deterministic projection.

The repository includes the backend pipeline, CLI, and a NiceGUI desktop
workbench for research. The interface provides PDF upload, per-job language
selection, reusable glossaries, provider settings, side-by-side review,
append-only corrections, qualitative uncertainty review, footnote ownership and
marker editing, and reviewed LaTeX, PDF, Markdown, and plain-text downloads. It is
a loopback-only workstation
tool, not a remotely deployed or
multi-user application.

## Pipeline

```text
PDF
  -> split into one-page PDF streams
  -> MarkItDown Markdown + matching rendered PNG per physical page
  -> one provider image+Markdown page-translation request
  -> when tagged: one batched table-reconstruction request for that page
  -> strict structured-output validation and per-pass trusted provenance
  -> canonical runs/<translation-run-id>/output/document.json
  -> primary compiled runs/<translation-run-id>/output/document.tex
  -> additional runs/<translation-run-id>/output/document.md projection
```

MarkItDown does not retain usable page boundaries when converting a complete PDF.
The ingestion adapter therefore splits first and runs MarkItDown once per page.
The rendered image remains the visual source of truth; extracted Markdown is
supplemental context, which matters for scans and pages with weak text layers.

### Segment policy for historical pages

The model returns page regions in reading order rather than treating a page as
one undifferentiated transcription. A table or table-like region is any region
whose meaning depends on two-dimensional row and column alignment, including
unruled schedules, registers, statistical arrays, and aligned date, age, or count
series. The first pass emits each such region as an ordered, text-free tag. If a
page has one or more tags, the pipeline immediately sends one batched structured
follow-up containing the same page PNG, that page's complete MarkItDown/OCR, and
the first-pass segmentation. Only that region is reconstructed: surrounding
prose, headings, captions, and table notes remain separate translated blocks.

The follow-up produces one target-language GitHub-flavored Markdown table per
tag. It may apply bounded structural modernization: infer strongly supported
headers, fill down plainly implied labels, expand ditto marks or shorthand, and
turn sentence-like records into explicit rows. For example, “3 dead, on 3rd of
July” followed by “3, 4th” can become a `Date | Deaths` table. This freedom is
structural only; it must not invent or change facts, names, values, dates, units,
categories, totals, or rows. A reconstructed table has
`segment_handling="table_reconstruction"`, machine GFM Markdown in
`translated_text`, and no claimed `source_text`. Figures remain text-free manual
insertions for a reviewer. Markdown export keeps every table between the exact
surrounding blocks selected by first-pass reading order and prefixes it with an
invisible `table-placement: [H!]` anchor containing its physical page and block
identity. The table remains ordinary inline GFM rather than a floating object.

Footnotes are classified by function, not by font size, position, or share of the
page. A note may be a short marked passage below a rule, an unmarked continuation,
or nearly a whole page. Each note has a stable identity such as `fn-p12-n2`, its
exact printed reference evidence such as `*` or `^11`, and a structured
description of its visible appearance and continuation handling. For a newly
starting note, the model inserts `[[FOOTNOTE:fn-p12-n2]]` at the exact translated
entrypoint. The pipeline removes that control token and stores the trusted owner
block plus its Unicode offset. A next-page fragment reuses the same identity,
links to the prior fragment, inherits its entrypoint, and is merged during export.
LaTeX emits one real `\footnote{...}` at that point and deliberately lets LaTeX
generate the displayed marker; the source's printed reference text is provenance,
not compiled text. Markdown uses the semantic identity for its reference and
definition. If the owner is not established, the note remains a visible review
item until a reviewer assigns it. Running heads, page numbers, digitizer marks,
catchwords, and printer gathering signatures are not footnotes.

### Previous-page continuity context

Both passes can receive finalized machine translations from preceding physical
pages in the same run. `translation.previous_page_context_count` controls the
window from 0 through 10; the checked-in default is 2. The projection contains
page identity and ordered source/translated block content, but no prior page
images, editorial revisions, provider metadata, IDs, hashes, tokens, or
timestamps. It is delimited as untrusted, read-only context, and the model must
return only current-page content.

For body text, the primary model must populate a `paragraph_continuation` state.
On the next physical page it uses the prior projection to decide whether the
first body block continues the preceding page's final body block. A confirmed
continuation receives a pipeline-owned `continues_from_block_id` link. Canonical
blocks remain page-local and independently revisable. The model is instructed to
word the current fragment so a direct join is grammatically seamless. Review
groups the linked fragments into one visual paragraph with fixed inline page
markers and one Save/Validate action, while recording one append-only revision per
physical-page fragment. Markdown, text, and LaTeX exports emit one paragraph; page
comments remain inline at each join. This cannot retroactively rewrite the
preceding machine fragment.

The same context can resolve a word, sentence, heading, footnote, or table
continuation that enters the current page. The main contract is versioned as
`translate-page-v11`; the table contract is `reconstruct-tables-v3`.

## Quick start: desktop application

The project uses `uv` exclusively for Python, environments, dependencies, scripts,
and developer tools.

```bash
uv sync --all-groups
cp config/default.toml config/personal.local.toml
```

After moving or renaming the checkout folder, run `uv sync --all-groups
--reinstall` from its new location to refresh editable imports and script paths.

Start the local interface. The launcher uses `config/personal.local.toml` when it
exists and otherwise uses the complete checked-in `config/default.toml`:

```bash
uv run app
```

The launcher opens a native desktop window through NiceGUI and pywebview. The
main tabs are **Translate**, **Glossaries**, and **Articles**. A gear in the top
right opens **Settings**. Translation options are grouped in a collapsible panel.
Settings saves defaults; Translate can override them for a single job. The editorial workspace
retains its complete document, keyboard controls, drafts, and page synchronization
when switching tabs.

For browser-based development, run `uv run transcribl serve`. Only that command
uses `web.open_browser_on_start`. Both modes bind to the configured loopback
host/port and use the same application services.

- **Translate** selects a laptop PDF and shows the complete per-job choices before
  submission: input/output languages, provider model, translation style, finalized
  previous-page text context, current-page image DPI, and optional simple guidance
  describing how footnotes look in the selected PDF. The fields start from
  TOML defaults; the checked-in language direction is Danish to English.
  **Auto continue** can be switched on or off before submission. When enabled,
  it retries a failed page within the same run up to the TOML-configured limit.
  If a page remains failed, every earlier page checkpoint is retained:
  **Continue** validates and reuses them before another attempt, while **Cancel**
  pauses the screen without deleting those artifacts.
- **Glossaries** manages separate named sets of required source-term translations.
  Create, rename, edit, save, or delete each glossary locally. On **Translate**,
  choose one saved glossary, **Configured defaults** (when the TOML glossary has
  entries), or **No glossary**. A saved glossary replaces the configured terms in
  full. Unsaved edits must be saved before using the selected glossary. Each job
  snapshots the saved terms; later glossary changes never alter that run.
- **Settings** starts with **Default model**, **Default style**, **Default glossary**
  (initially **None**), and **API Keys**. **Save settings** persists non-secret
  preferences atomically in `.settings.toml` under the configured artifact root.
  Defaults survive restarts; existing runs and deliberate per-job overrides are
  unchanged. **Reload saved settings** discards unsaved settings edits.
  **Advanced settings** contains thinking levels for each provider, default
  continuity pages, image DPI, uncertainty marking, and Auto continue. It also
  exposes the verbatim, versioned translation/table instructions and resolved
  default translation settings. Page-specific evidence is appended at execution.
  Built-in style instructions can be edited and reset; **Add style** copies the
  currently displayed instructions into a named custom style for further editing.
  Save settings before selecting that style on Translate. The exact selected
  style text and thinking level are snapshotted for each run and invalidate
  mismatched checkpoints in both translation passes.
  **API Keys** opens a dialog with separate Google (Gemini), OpenAI, and
  Anthropic credentials. Each key can be used for the current window session, or **Save on
  this computer** can store it locally for later sessions. The saved value is
  never returned to or displayed by the interface.
- **Articles** opens with a catalog of every valid completed translation run found
  under the configured artifact root. A stable translation-run ID reopens the
  same canonical artifacts after a browser or server restart. The complete
  translated document is mounted and scrollable; only the active physical
  page's original PNG is fetched and displayed alongside it. The original-page
  zoom control keeps its selected amount while the translated text moves through
  subsequent pages. The last physical
  page visited is stored per run, so the catalog can offer **Continue from page
  X**. Edits create append-only revisions without changing machine output.
  Uncertain terms are visibly marked and can be corrected once or, when multiple
  unresolved model-annotated occurrences exist, all at once. **Uncertain terms**
  opens a complete unresolved list ordered from most to least occurrences and
  can jump to the first marked instance. Each translated section has an editable
  type; footnotes additionally expose their stable identity, printed-reference
  evidence, appearance/handling description, owner-section selector, and exact
  inline marker character position. The owner editor renders that entrypoint as a
  display-only superscript which is excluded from saved editorial text. An
  unfinished article offers **Review**;
  a fully accepted article offers **Read**. The export menu downloads XeLaTeX
  source, Markdown, plain text, or a PDF typeset locally with XeLaTeX. **Delete**
  removes the selected immutable translation run together with its revisions and
  review position; sibling runs for the same source document are preserved.

PDF export requires the `xelatex` executable configured under `[pdf_export]`.
Markdown and plain-text downloads do not require TeX. PDF source is projected
directly from canonical blocks and effective revisions, compiled with shell
escape disabled, and removed with its temporary compilation directory. Bold
GFM spans inside table cells are converted to native LaTeX bold commands rather
than leaving `**` markers in the typeset document.

For each request, the configured provider receives one current-page image and
that page's complete extracted Markdown. A table-bearing page therefore makes a
second request with the same current-page evidence. Requests can also include the
configured read-only projection of prior finalized machine translations. Source
files, canonical translations, and editorial revisions remain in the configured
local artifact directory.

The web server binds only to a configured loopback address. A newly submitted
translation receives a temporary browser job ID; that alias, live progress
record, and the bounded execution queue exist only in the running process.
Completed runs and stopped failed runs are different: the server discovers their
artifacts at startup and exposes them by stable translation-run ID. A failed run
can therefore continue after refresh or restart, but no work proceeds while the
server is stopped. **Cancel** dismisses an already stopped run; it is not active
task interruption. This is filesystem discovery, not a database or durable task
queue. There is no authentication or remote deployment support, so do not expose
the server on a network.

### Translation costs

Selecting a PDF counts its physical pages locally and shows an approximate USD
cost before submission. Changing the model recalculates it without a provider
call. The estimate uses average recorded input/output tokens per completed page,
including table passes, multiplied by the selected model's rates and PDF page
count. It prefers the same model and thinking level, then the same model,
provider, or all-model history. Five matching pages are required before narrowing
the sample; the most recent 1,000 matching pages are used. Both limits live in
`[costs]` in TOML. Newly completed runs improve subsequent estimates automatically.

Finished jobs and the Articles catalog show **Recorded cost**, calculated from
that run's successful main and table requests. Expand the catalog cost for token
totals and pricing details. Existing completed runs are included after restart;
canonical documents and editorial revisions are never rewritten for pricing.
Prices are display projections from the current TOML price table, so updating
that table can change displayed historical costs. This is not a billing ledger.

Rates were checked on October 12, 2026 against the official
[OpenAI](https://developers.openai.com/api/docs/pricing),
[Anthropic](https://platform.claude.com/docs/en/about-claude/pricing), and
[Google](https://ai.google.dev/gemini-api/docs/pricing) price lists. Each configured
rate includes its source and verification date. Gemini introductory rates expire
December 31, 2026; update the table before estimating later runs. The legacy
Gemini 3.6 entry prices old runs only and does not make it selectable.

Costs use standard paid-tier rates, excluding unrecorded retries, cache discounts,
free allowances and taxes. OpenAI uses short-context rates; long-context premiums
are not included. Haiku's prompt-length tier is applied separately to each
request. Older Gemini usage excludes thinking tokens; new Gemini records include
them. Page density, language, image resolution, prompts and thinking settings can
change usage. Missing usage/history/pricing shows **unavailable**, never a
misleading zero. No document content is sent anywhere to calculate either cost.

## Desktop distributions

Builds are owned exclusively by the **Desktop builds** GitHub Actions workflow
in [`.github/workflows/desktop-build.yml`](.github/workflows/desktop-build.yml).
It runs on pull requests, pushes to `main`, version tags, and manual dispatch.
Download the resulting artifact for your platform:

- **macOS ARM64**: `Transcribl-macos-arm64.zip`, containing `Transcribl.app`.
- **Windows x64**: `Transcribl-windows-x64.zip`, containing the complete
  `Transcribl` folder; launch `Transcribl.exe` inside it.

The former `uv run compile --mac/--windows/--linux` build commands are removed.
The pipeline's `transcribl compile <job>` command remains available. Build files
live under `.github/packaging/` and reject local or unsupported build hosts.

Each CI job runs the quality gates, packages NiceGUI, pywebview, prompts, default
configuration, MarkItDown and PDFium, and smoke-tests the packaged CLI,
extraction, and NiceGUI server without a provider. Personal configuration, keys,
source PDFs, and artifacts are excluded. Frozen apps keep their data in the same
per-user directories as before. XeLaTeX remains external for reviewed PDF export.
The packages are unsigned; see [packaging notes](docs/packaging.md) for runtime
requirements and verification limits.

## CLI workflow

To use the CLI instead, copy the secret template and put only the Gemini key in
the ignored local file:

```bash
cp .env.example .env
```

```dotenv
GEMINI_API_KEY=your-key-here
```

Validate the selected non-secret TOML configuration:

```bash
uv run transcribl \
  --config config/personal.local.toml \
  show-config
```

Run the full backend pipeline:

```bash
uv run transcribl \
  --config config/personal.local.toml \
  run data/article.pdf
```

A 95-page PDF makes 95 primary provider requests plus one table request for each
table-bearing page, unless matching checkpoints already exist. Multiple tables
on one page are batched into that page's single follow-up. With Auto continue
enabled, a failed page can make up to `web.auto_continue_attempts` additional
requests. The checked-in default is one automatic attempt and the UI default is
off.

## Staged commands

The full run can be split into independently inspectable stages:

```bash
# No external API call
uv run transcribl --config config/personal.local.toml \
  ingest data/article.pdf

# Uses GEMINI_API_KEY and resumes matching checkpoints
uv run transcribl --config config/personal.local.toml \
  translate <configured-artifacts-dir>/<job-id>

# No external API call; regenerates LaTeX and Markdown from canonical JSON
uv run transcribl --config config/personal.local.toml \
  compile <configured-artifacts-dir>/<job-id>
```

Use `--force` on `ingest`, `translate`, or `run` when intentionally starting from
new prepared inputs or a new immutable translation run. Without it, a checkpoint
produced with different page content, prompt, model, or translation config fails
visibly instead of being reused. A changed configured image DPI is handled
automatically: ingestion publishes newly rendered page artifacts and clears the
active run so translation starts a new immutable run using the new image hashes.

## Configuration

[`config/default.toml`](config/default.toml) is the complete checked-in example and
contains:

- artifact location and page-image DPI;
- provider, default model, selectable-model allowlist, stable API version,
  timeout, bounded attempts, and inline-request size guard;
- source/target languages;
- `faithful`, `balanced`, or `readable` translation style;
- custom translator instructions and glossary;
- name and citation policies, plus an uncertainty level and optional explicit
  review targets;
- finalized previous-page translation context count (0–10, default 2);
- Markdown page-comment and marginalia behavior;
- local XeLaTeX executable and bounded PDF compilation timeout;
- loopback web host/port, upload/page/glossary limits, status polling, and bounded
  local concurrency.

The `[desktop]` section sets initial and minimum window dimensions. Existing
personal TOML files must copy this section from `config/default.toml`.

Personal files should use `config/*.local.toml`, which Git ignores. Unknown keys,
missing settings, invalid enum values, and out-of-range settings fail before work
begins. Relative paths resolve from the selected TOML file's directory. Resolved
translation, provider, and export settings are stored in the job manifest; API
keys are never stored there.

The interface uses TOML values as defaults and limits. Input language, output
language, model, translation style, previous-page text context, page-image DPI,
uncertain-term level, optional uncertainty instructions, footnote appearance, and
glossary selection is an explicit per-job choice; the resolved values are passed
through the same application boundary and persisted as run provenance. The
uncertainty choices are configured by `web.uncertainty_level_choices`; **Off**
retains compatibility by resolving `mark_uncertain_terms=false`. A model can be
selected only when it appears in `provider.<name>.selectable_models`.

`.env` is exclusively for `GEMINI_API_KEY`. Do not add model names, paths,
translation choices, or other non-secret behavior to environment variables. The
Settings checkbox labeled **Save on this computer** writes only this key to the
local `.env`; leaving it unchecked keeps the entered key in browser/process
memory for the current session and job. The API exposes only boolean key-status
flags, never the key value.

### Provider and language choices

The model dropdown includes only Gemini 3.8 Flash (`gemini-3.8-flash`, the default)
from Google; GPT-6 Astra (`gpt-6-astra`), GPT-6.1 Sol (`gpt-6.1-sol`), and
GPT-6 Luna (`gpt-6-luna`) from OpenAI; and Claude Opus 5.5 (`claude-opus-5-5`),
Sonnet 5.5 (`claude-sonnet-5-5`), and Haiku 5.5 (`claude-haiku-5-5`) from Anthropic. Selecting a
model routes both page translation and table reconstruction to its provider.
The **API Keys** dialog in Settings manages all provider keys independently of
the selected model. **Save on this computer** stores
Gemini in the existing ignored `.env`; OpenAI and Anthropic keys are stored
separately in the ignored `.provider-keys` credential cache beside it. These
files use mode 0600 on POSIX. Clearing one key leaves other keys intact.
No key is stored in browser local storage, public API responses, or translation
artifacts. Unchecked keys remain in session memory. CLI users may also supply
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in their process environment. API access
and billing belong to the respective provider account.

Thinking defaults to **Provider default**, which omits an explicit override.
Gemini exposes low/medium/high; OpenAI and Anthropic also expose xhigh/max.
The adapter maps these to Gemini `thinking_config.thinking_level`, OpenAI
`reasoning.effort`, or Anthropic adaptive thinking plus `output_config.effort`.
Choices and defaults come from TOML. Existing personal TOML files need the new
`[workbench]`, `[workbench.style_prompts]`, and provider thinking fields from
`config/default.toml`. The app does not rewrite a personal config.

Model and thinking references: [OpenAI models](https://developers.openai.com/api/docs/models),
[Claude models](https://platform.claude.com/docs/en/models/overview),
[Claude effort](https://platform.claude.com/docs/en/build-with-claude/effort), and
[Gemini thinking](https://ai.google.dev/gemini-api/docs/thinking).

Both language dropdowns use `web.language_choices`, with **Custom** last for a
manually entered language. A configured language outside the list automatically
opens Custom without losing its value.

`[provider.openai]` and `[provider.anthropic]` define model allowlists, bounded
request timeouts/attempts, inline-size guards, and output token caps. CLI users
select the default with `provider.name`. SDK retries equal `request_attempts - 1`.
Model, structured-output contract, and output token cap affect checkpoint identity;
transport timeout/retry/size limits remain operational provenance. Failed-run
recovery restores the original provider and model.

Existing personal TOML files must add the two new provider sections and
`web.language_choices` from `config/default.toml`; add `gemini-3.8-flash` to the
Gemini allowlist to select it. Configuration remains strict rather than silently
changing personal choices. Existing completed translations remain readable.

Model/API references: [OpenAI GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra),
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Claude Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview),
[Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
and [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash).

### Saved glossaries

Saved glossaries live in `<artifacts_dir>/.glossaries.json`, a versioned local
catalog written atomically. Names and source terms must be unique within their
respective scopes; original Unicode text is preserved. `web.max_glossary_entries`
and `web.max_term_characters` limit each glossary, while the new required
`web.max_glossary_name_characters` limits its name (100 in the default TOML).
Add that setting when updating an older personal TOML file.

Revision checks reject stale saves, deletes, and job selections. **Refresh** in
Glossaries loads the latest saved versions; unsaved drafts are protected by a
confirmation before switching or refreshing. The resolved mapping dictionary is
persisted in each run's translation settings and participates in both page and
table checkpoint fingerprints. Renaming or deleting a saved glossary cannot
change the snapshot of a queued, completed, or stopped run. No database or remote
storage is used. The older inline-glossary HTTP input remains supported for local
clients and retains its configured-default merge behavior.

## Canonical data and output artifacts

The active run's `document.json` is the source of truth for the editor. It
preserves the translation-run identity, source page, block type, source text for
translated regions, machine translation or reconstructed table Markdown,
uncertainty notes, hashes, prompt/model provenance, and translation settings.
`document.tex` is the primary compiled source. `document.md` is an additional
derived presentation; both can be regenerated at any time.

```text
<configured-artifacts-dir>/<job-id>/
├── manifest.json
├── prepared/
│   └── <preparation-id>/
│       └── pages/
│           ├── 0001/
│           │   ├── source.md
│           │   └── page.png
│           └── 0002/
│               └── ...
└── runs/
    ├── <translation-run-id>/
    │   ├── pages/
    │   │   ├── 0001/
    │   │   │   ├── translation.json
    │   │   │   └── failure.json   # only while that page has failed
    │   │   └── 0002/
    │   │       └── ...
    │   ├── revisions/
    │   │   └── p0001-b0001/
    │   │       ├── 0001.json      # append-only editorial revision
    │   │       └── 0002.json
    │   ├── review/
    │   │   └── position.json      # mutable last physical page visited
    │   └── output/
    │       ├── document.json      # canonical machine dataset for this run
    │       ├── document.tex       # primary compiled XeLaTeX source
    │       └── document.md        # additional derived export
    └── <older-translation-run-id>/
        └── ...                    # retained immutable machine artifacts
```

`original_page_number` always means the 1-based physical position in the PDF.
`pdf_page_label` is label metadata embedded in the PDF, while
`detected_printed_page_label` is text visibly printed on the page. They are
separate because front matter often uses Roman numerals or no printed number.

Page translations are written atomically within one immutable translation run.
If a first pass tags tables, its validated `translation.json` is written before
the table call. It is an intermediate stage checkpoint until every tagged table
has been reconstructed. If that follow-up fails, `failure.json` records the
`table_reconstruction` stage and a retry repeats only pass two; it does not repay
for or potentially change the first-pass segmentation. If page 43 fails, earlier
finalized page checkpoints remain resumable in the same run. Forced translation
appends a new run instead of overwriting prior successful bytes.

The first-pass fingerprint includes both page hashes, complete resolved
translation settings, provider/model and output-affecting provider semantics,
the exact main prompt and prior-page context, the main/table prompt versions and
table prompt contract hash, and schema version. The table fingerprint also binds
the exact table prompt, first-pass fingerprint, and ordered table targets. Main
and table provider response IDs, token usage, prompt versions, and fingerprints
are persisted separately as bounded provenance. Operational timeout/retry/size
settings remain provenance but do not invalidate successful checkpoints.

Editorial changes are separate from machine output. Each block revision is
created atomically under the active immutable run and includes its expected base
revision, effective text, effective section type, optional footnote owner and
marker offset, review state, and resolved uncertainty IDs. The review projection
combines machine blocks with the latest valid revision. Downloading a reviewed
format projects that effective view without changing the canonical
`document.json` or either machine projection. The interface labels whether each
effective block is still the machine translation, was reviewed unchanged, or is
the result of a manual revision. The run-scoped `review/position.json` sidecar
stores only the current physical-page cursor; it does not alter the translation
or revision history.

New revisions use revision schema 2.0 for effective section type and footnote
placement. Existing revision schema 1.0 text edits remain readable and inherit
their immutable machine block metadata.

Preparation is transactional: extraction uses an immutable temporary snapshot of
the source and publishes a new `<preparation-id>` only after every page pair is
ready. The manifest then switches to that preparation atomically. Older
preparations are retained until a future explicit cleanup policy exists. Forced
preparation preserves the ordered translation-run index but clears the active run
so the next translation receives a new identity.

New core artifacts use schema version 6.0 for cross-page footnote identity,
description, fragment linkage, and structured ownership in addition to
table-reconstruction handling and per-pass provenance. The filesystem reader
validates and upgrades supported schema 2.0 through 5.0 artifacts in memory
without rewriting immutable files. Schema
2.0 translated tables remain explicitly marked legacy translated tables; schema
3.0 manual table placeholders remain explicitly marked legacy manual tables.
Neither compatibility form is silently reinterpreted as a reconstructed table.
Legacy footnotes receive synthetic per-block IDs and an explicit migration
description because their cross-page identity was not recorded. Incoming legacy
continuations are retained as independent review items rather than guessed and
merged. Migrated schema 2–4 footnotes have unknown ownership and require review. A
translated figure is not valid schema 2.0 legacy data. Version
1.0 artifacts predate translation-run identity and remain explicitly rejected
rather than being attached to a guessed run.

## Repository map

```text
.
├── config/default.toml             # every non-secret runtime setting
├── data/README.md                   # location for ignored local source PDFs
├── docs/
│   ├── architecture.md             # boundaries, contracts, artifact lifecycle
│   └── roadmap.md                  # backend, editorial, and UI phases
├── src/transcribl/
│   ├── cli.py                      # command inputs and local app launchers
│   ├── composition.py              # shared adapter/application wiring
│   ├── config/                     # strict TOML sections + resolved defaults
│   ├── domain/                     # Pydantic contracts, editorial views, errors
│   ├── ports/                      # extractor, provider, artifact/revision ports
│   ├── application/                # translation/, jobs/, review/, exporters/
│   ├── adapters/
│   │   ├── extraction/             # MarkItDown + PDFium page pairing
│   │   ├── export/                 # bounded local XeLaTeX compilation
│   │   ├── llm/                    # shared handling + isolated providers/ SDKs
│   │   ├── secrets/                # provider keys + environment resolution
│   │   └── storage/                # artifacts, atomic writes, read-only migrations
│   ├── interfaces/web/             # strict API feature routers + HTTP policy
│   ├── interfaces/desktop/         # composed panels + modular Articles editor
│   └── prompts/                    # versioned prompt resources
└── tests/
    ├── unit/
    ├── integration/                # local adapters; never network
    └── e2e/                        # complete fake-provider pipeline
```

The dependency direction is interface → application → domain/ports, with adapters
implementing the ports. The web interface and CLI share composition and
application services; browser code never calls provider SDKs or MarkItDown directly and
never reconstructs metadata from Markdown.

Architecture tests guard core imports, SDK isolation and acyclic module graphs.
Release smoke checks verify nested editor assets in both desktop builds. Existing
artifact schemas, prompts, provider IDs and saved key locations remain compatible.

See [architecture.md](docs/architecture.md) for the detailed model and
[roadmap.md](docs/roadmap.md) for implemented scope and deliberately deferred
work.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv lock --check
```

Normal tests never contact external providers. They generate synthetic PDFs in temporary
directories, mock provider responses, and use fake providers for end-to-end
execution. Interface tests use an in-process FastAPI client and fake job/provider
boundaries. NiceGUI simulation tests also exercise desktop selections, credentials,
and glossary submission through that API. A future live test must be explicitly marked `live`, require an
opt-in flag as well as a key, and remain excluded from ordinary verification.

Gemini failures retain only a safe HTTP code/status and operator guidance. Raw
provider messages, responses, page content, and keys are not written to failure
artifacts or returned by the interface. For example, `400 INVALID_ARGUMENT`
usually requires checking the entered key and request compatibility, `403
PERMISSION_DENIED` requires checking key restrictions/API access, and `429
RESOURCE_EXHAUSTED` requires checking quota or rate limits.

The adapter supplies Gemini with the Pydantic contract through the SDK's current
JSON Schema field, then validates the returned JSON locally before persistence.

The live Gemini, OpenAI, and Anthropic paths have not been verified by the automated suite.

## Current limitations

- Translation is sequential. Only finalized preceding same-run page translations
  are available as context; no following-page image/text is sent. The next page
  can confirm and link a paragraph continuation, but it cannot rewrite the
  preceding page's already persisted fragment.
- Block boundaries and types are model decisions and may vary between runs.
- Reconstructed tables are model-produced modern GFM structures, not claimed
  cell-for-cell source transcriptions, and still require editorial review.
- Weak OCR/text extraction can still affect output, though the page image is also
  supplied.
- Uncertainty is qualitative because model token probabilities are unavailable;
  no confidence number is fabricated.
- Password-protected PDFs are not supported.
- Markdown preserves logical content and provenance, not exact PDF layout.
- `--force` starts a new immutable translation run; it never overwrites an older
  run's machine checkpoints.
- Queued/running browser aliases, live progress state, and the bounded queue are
  process-local and are lost on restart. Valid completed runs remain available
  through Articles, and failed active manifests are rediscovered for explicit
  continuation from their stable run IDs.
- The interface has no authentication, remote deployment configuration, durable
  task queue, multi-process coordination, or interruption of an active request.
  It is deliberately restricted to loopback use.
- Review keeps cross-page paragraph boundaries immutable while presenting their
  fragments as one paragraph. Arbitrary block split/reorder operations, editor
  identities, and a dedicated revision-history screen remain deferred.
- The live Gemini path requires a real account/key and incurs provider cost; the
  automated suite verifies the adapter boundary without making a live request.
