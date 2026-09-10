# ADR-0003: Embeddings and vector storage

Status: embedding decision implemented in M3; storage decision scheduled for M4.

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

Eight fixed questions target short substrings in the twelve-topic English fixture. The
evaluation embeds once, ranks by cosine, and counts the first chunk containing the answer.
Recall@5 is the fraction of questions answered in the top five; MRR averages the reciprocal
first relevant rank across the full ranking, assigning zero when no chunk contains the answer.
Ties retain input order, and overlapping copies of an answer do not earn extra credit.

With 64/8 evaluation windows, the keyword baseline gives recall@5 0.875 and MRR 0.745 over
30 whitespace-tokenized chunks. MiniLM gives 1.000 and 0.938 over 42 subword-tokenized chunks.
These are regression checks, not a controlled comparison or evidence of Croatian retrieval
quality: the chunk sets differ, the corpus is tiny, and questions reuse distinctive words.

At the shipped 120/24 defaults, MiniLM gives recall@5 1.000 and MRR 0.917 over 24 chunks.
Reproduce with `uv run --locked --all-packages python scripts/eval_retrieval.py --provider fastembed --production`.
Top five covers roughly a fifth of this corpus, so this only catches gross regressions.
A separate bilingual-evaluation PR before M4 will add a generated Croatian multi-topic fixture
and questions; the current single-chunk Croatian fixture does not establish retrieval quality.

Keep MiniLM while it passes the 0.8 recall@5 gate. If a separate representative English/Croatian
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

Use [pgvector](https://github.com/pgvector/pgvector) in Postgres in M4, alongside documents,
entities and chunks. It supports cosine search while sharing transactions and backups with
the relational data. A dedicated vector database would add another service and a consistency
boundary before this workload demonstrates a need for it. No database dependency or schema in M3.
