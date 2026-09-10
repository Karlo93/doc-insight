# ADR-0013: Separate lexical overlap from hosted-answer support

Status: accepted, 2026-09-10. Amends the confidence decision in ADR-0008.

## Context

Real-document testing found useful OpenAI paraphrases hidden by a 0.6 lexical
overlap threshold. Whole-question conjunction search missed diagram labels, while
a requirements document outranked a diagram explicitly named in the question.
Strict integer citations could still refer to passages that were never supplied.

## Decision

Use content-term OR search alongside dense retrieval. Resolve distinctive filename
words within the tenant snapshot, accepting spelling similarity at least 0.86;
explicit document filters take precedence. Read IDs and filenames only for this
step. Neither filenames nor tenant metadata are sent to the hosted model.

Keep lexical confidence as an API diagnostic and an extractive-answer threshold.
For hosted answers require a nonempty answer, explicit model support and valid
citations. A per-request enum constrains generated citation IDs, with parser and
service validation retained. Display passage counts instead of a misleading
percentage in the browser. Unsupported requests still abstain.

## Consequences and alternatives

Model support plus valid citations is not a proof that each claim follows from
the source. A separate entailment model could improve this boundary but adds cost,
latency and calibration requirements. Lowering the overlap threshold would retain
the same failure for synonyms and translations; forcing verbatim answers would
prevent useful explanations. Requiring every user to select a document manually
would avoid name inference but leave ordinary document-referencing questions weak.

Filename resolution scans tenant metadata per query and can infer an unintended
scope from an ambiguous name. Explicit filters remain the override. Before serving
large catalogs, benchmark this path and replace the scan with indexed title search
if it materially affects latency. Revisit with a varied, labeled answer-quality
set covering paraphrases, misspellings, diagrams and unsupported questions. Earlier
capacity measurements remain evidence for their recorded release, not this change.
