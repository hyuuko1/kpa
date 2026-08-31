---
name: kernel-patch-analyzer
description: "Linux kernel patch screening, download, and deep technical analysis using the kp tool."
---

# Linux Kernel Patch Analyzer Guide

This skill guides AI agents through screening, downloading, and deeply analyzing Linux kernel patchsets using the `kp` toolkit.

## Workflow Overview

1. **Stage 1 (Screening)**:
   - Read `data/runs/<run_id>/patchsets.json` or `manifest.json`.
   - Score patchsets (0-100) and decide recommendation following `references/screening.md`.
   - Write output to `data/runs/<run_id>/reviews.json`.

2. **Stage 2 (Download & Decomposition)**:
   - Run `kp download --run-id <run_id> -i reviews.json`.
   - Generates direct-read files under `data/runs/<run_id>/patchsets/<sanitized_id>/`:
     - `00-cover-letter.md`
     - `discussions.md`
     - `patches/*.patch`
     - `meta.json`

3. **Stage 3 (Deep Analysis & Reporting)**:
   - When asked to analyze a patchset at `data/runs/<run_id>/patchsets/<sanitized_id>/`:
   - Direct-read `00-cover-letter.md`, `discussions.md`, `patches/*.patch`, and `meta.json`.
   - Perform technical analysis across the 5 core dimensions specified in `references/deep-analysis.md`.
   - **Persist the generated Markdown report directly to**:
     `data/runs/<run_id>/reports/<sanitized_id>.md`

## Progressive Disclosure References

- For patch screening scoring criteria, evaluation dimensions, and `reviews.json` schema, consult [Screening Guide](references/screening.md).
- For deep technical analysis dimensions (Architecture, Concurrency, Memory, Regressions, Community Debates) and report template, consult [Deep Analysis Guide](references/deep-analysis.md).
