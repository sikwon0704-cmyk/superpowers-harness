# Learned Rules

This directory contains rules promoted from failure retros.

Each rule file uses frontmatter to scope where it applies:

```yaml
---
paths:
  - "src/api/**/*.ts"
---
```

Rules here are automatically loaded for matching files.
Only the **rule-curator** agent should create or modify files in this directory.
