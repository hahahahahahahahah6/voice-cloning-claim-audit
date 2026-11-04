# Documentation claim auditor

Check written promises against static Python call patterns. The checker reads
local files and parses source without executing it. It needs Python 3.9 or newer
and has no runtime dependencies.

```sh
python3 -m pip install .
voice-cloning-claim-audit /path/to/project
python3 -m voice_cloning_claim_audit /path/to/project --json
python3 -m voice_cloning_claim_audit --version
```

The input is a directory. Documentation includes the root README.md and Markdown
files with a docs directory component. Fenced blocks are skipped; inline code is
included. Matching uses paragraphs, normalized case, expanded negative
contractions, spaces in place of hyphens, and collapsed whitespace. Negative
matches are removed before affirmative matching.

Source evidence comes from complete named operations or specialized construction
and method pairs within one module. Aliases are resolved and local stubs are
excluded. This heuristic checks call shapes; it cannot establish runtime results
or the quality of generated output.

Symlinked paths are skipped. The fixtures, docs, and examples directories cannot
supply evidence. Test files are considered separately. Invalid syntax provides
no evidence. An affirmative promise without source receives a finding, while a
denial without source passes.

```text
documented-voice-cloning-claim-false HIGH
# MEDIUM when supporting calls appear only in tests
documented-no-voice-cloning-claim-false HIGH
```

Each finding family appears at most once. JSON contains a verdict, findings with
id, severity, and message fields, evidence paths, and inspected paths. A verdict
of FAIL means findings exist, even when their severity is below the exit threshold.

Use --json for structured output and --verbose for inspected paths. Repeat
--ignore with relative path prefixes to exclude them. --fail-on accepts LOW,
MEDIUM, or HIGH and defaults to HIGH. --version prints 0.1.0. Exit codes are 0
below threshold, 2 at or above threshold, and 1 for usage or file access errors.
The checker makes no network requests, sends no telemetry, and writes no files.

```sh
python3 -m unittest discover
python3 -m build
```

Distributed under the MIT license, as a wheel and a source archive.
