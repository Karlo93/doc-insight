# ADR-0003: Embeddings and vector storage

Status: embedding decision implemented in M3; storage decision implemented in M4.

## Decision

Use FastEmbed's CPU ONNX implementation of multilingual MiniLM, producing 384-dimensional
vectors. Keep M2's 120/24 chunks and reject any embedding input above 126 content tokens;
two special tokens complete the published 128-token sentence input. MiniLM requires no
query/passage prefixes. A shared Embedder Protocol keeps inference out of the pure pipeline.

Pin both the original tokenizer revision and the
[quantized ONNX artifact](https://huggingface.co/Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/tree/faf4aa4225822f3bc6376869cb1164e8e3feedd0).
Download the snapshot into `DI_MODEL_CACHE` and pass its directory explicitly to FastEmbed,
so its normal download path cannot choose a different revision. Load once per configuration.
Tests compare both artifacts' tokenizer IDs and verify the input limit with the real model.
FastEmbed 0.8.0 uses mean pooling here and returns unnormalized vectors; the adapter makes
them unit length. Its startup warning refers to older CLS-pooling behavior, which this
pipeline never used. Pipeline version 5 records the new output; `uv.lock` fixes the runtime.

The runtime accepts the selected MiniLM model/repository pairing only, and derives dimension
384 from that choice. An arbitrary model name must not relabel incompatible pinned weights.
Model, tokenizer, weight revisions, prefixes and input budget change together after evaluation.
`DI_EMBED_MODEL` and `DI_EMBED_ONNX_REPO` are a fixed profile, not interchangeable env options.
The canonical `Qdrant` repository ID avoids relying on a redirect; the revision is unchanged.

For the M4 container, warm both tokenizer and ONNX snapshots in the mounted cache, then set
`HF_HUB_OFFLINE=1` before starting the process. A pinned revision alone still allows a network
attempt before cache fallback. The later query service must report overlong questions as a
clear HTTP 400; the adapter's refusal to truncate must not become an HTTP 500.

## Evaluation and upgrade criterion

Eight fixed questions per language target short substrings in separate twelve-topic English
and Croatian fixtures, each with six pages. Croatian topics have 95–100 words and differ
from the English subjects; questions use paraphrases and inflected forms. Tests require
each answer to occur exactly once in the source pages in both languages. The
evaluation embeds once, ranks by cosine, and counts the first chunk containing the answer.
Recall@5 is the fraction of questions answered in the top five; MRR averages the reciprocal
first relevant rank across the full ranking, assigning zero when no chunk contains the answer.
Ties retain input order, and overlapping copies of an answer do not earn extra credit.

| Queries → corpus | Provider | Window/overlap | Chunks | Recall@5 | MRR |
| --- | --- | --- | --- | --- | --- |
| en → en | Keyword | 64/8 | 30 | 0.875 | 0.745 |
| en → en | MiniLM | 64/8 | 42 | 1.000 | 0.938 |
| en → en | Keyword | 120/24 | 18 | 1.000 | 0.729 |
| en → en | MiniLM | 120/24 | 24 | 1.000 | 0.917 |
| hr → hr | Keyword | 64/8 | 24 | 0.500 | 0.289 |
| hr → hr | MiniLM | 64/8 | 42 | 1.000 | 0.581 |
| hr → hr | Keyword | 120/24 | 12 | 0.750 | 0.388 |
| hr → hr | MiniLM | 120/24 | 24 | 0.875 | 0.896 |
| en → hr (translated questions) | MiniLM | 64/8 | 42 | 1.000 | 0.875 |
| en → hr (translated questions) | MiniLM | 120/24 | 24 | 1.000 | 0.875 |

Reproduce with `uv run --locked --all-packages python scripts/eval_retrieval.py --language hr --provider all`;
repeat with `--language en` and add `--production` for the shipped defaults.
The English translations in `eval_hr.jsonl` ask about the same Croatian answers. These
cross-lingual rows are report-only, with no gate. English fixture questions against the
unrelated Croatian subjects, or the reverse, would not measure translation retrieval.

Both languages gate MiniLM recall@5 at 0.8 with 64/8 windows. The English keyword gate
stays at 0.75. The Croatian keyword score of 0.500 is below 0.75, so its explicit gate is
0.5: whitespace hashing cannot match inflected forms or synonyms. This is a baseline
limitation, not a reason to relax the model gate. Production scores are reported separately.

These fixtures now establish a small bilingual retrieval regression check and measure
English-to-Croatian retrieval on eight translated questions. They do not establish general
Croatian accuracy, Croatian-to-English retrieval, or quality on unseen books and OCR.
Keyword and MiniLM use different chunk sets. At production size, top five covers roughly
a fifth of the model corpus; even perfect recall can hide poor ordering. The local book
smoke reported in the PR exercises real input, but is not a representative benchmark.
The bilingual evaluation promised before M4 was completed after M4; pipeline version stays 6
because no stored output changes.

Keep MiniLM while it passes the 0.8 recall@5 gate in both languages. If a separate representative English/Croatian
holdout falls below 0.8, benchmark [multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large)
on the same frozen chunks/questions and measure latency and memory on the target machine.
Adopt it only if it clears the gate within an agreed latency/memory budget. It has 1024
dimensions, a 512-token input limit and query/passage prefixes; those consume input budget too.
It is an upgrade candidate, not an implemented or benchmarked alternative in this PR.

A switch requires new tokenizer/weights, regenerated chunks, and a pipeline-version bump.
After M4 it also needs a vector-column migration from 384 to 1024 dimensions, rebuilding the
vector index and re-embedding every document. Equal dimensions alone do not make model spaces compatible.

## Alternatives

- sentence-transformers/PyTorch: a larger runtime than the selected ONNX inference path needs.
- Hosted embeddings: adds network availability, credentials and document-data transfer to indexing.
- Hash vectors: useful for deterministic contract tests, but have no semantic retrieval quality.
- Hashed keyword vectors: useful offline retrieval baseline, but miss paraphrases without shared words.
- A generative model: useful for the later answer stage; not the retrieval embedding provider.

M4 implements [pgvector](https://github.com/pgvector/pgvector) in Postgres, alongside documents,
entities and chunks. It supports cosine search while sharing transactions and backups with
the relational data. A dedicated vector database would add another service and a consistency
boundary before this workload demonstrates a need for it. See [storage and search](../pipeline.md#storage-and-search-m4)
for the implemented repository and migration; M3 itself added no database dependency or schema.
