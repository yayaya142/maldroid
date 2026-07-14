# Knowledge and Playbooks

MalDroid searches three local layers: installed built-in knowledge, user knowledge under
`~/.config/maldroid/knowledge`, and case knowledge under `<case>/.maldroid/knowledge`. Markdown is
indexed with SQLite FTS5. Full playbooks are never inserted into the system prompt.

Optional front matter:

```yaml
---
title: React Native Metro Bundle Investigation
profile: react-native
tags: [metro, javascript, bundle]
last_verified: 2026-07-14
---
```

Use headings for when to use, required artifacts, detection indicators, workflow, recommended
tools, failure modes, alternatives, suspicious patterns, expected outputs, references, and last
verified. Clearly label version-dependent behavior, exact parsing, heuristics, and unsupported
formats.

Add and index user knowledge:

```bash
maldroid knowledge add ./notes.md --profile react-native --copy
maldroid knowledge reindex
maldroid knowledge list
```

Update the source Markdown and reindex. Playbooks remain static-only and must not instruct MalDroid
to execute samples, use dynamic instrumentation, upload artifacts, or access a network.

