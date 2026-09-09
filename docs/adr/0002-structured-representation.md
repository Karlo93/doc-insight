# ADR-0002: Structured text and model-sized chunks

Status: accepted in M2, pipeline version 4.

## Context

Chunks will become both embedding inputs and citations. Correct character offsets alone
do not guarantee readable chunks or that the embedding represents all the cited text.
The pinned [MiniLM sentence configuration](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/blob/e8f8c211226b894fcb81acc59f3b34ba3efd5f42/sentence_bert_config.json)
sets `max_seq_length` to 128; the underlying BERT's 512 positions are a different limit.
The original 400-token default was inconsistent with that published sentence configuration.

## Decision

- Keep multilingual MiniLM and its pinned tokenizer: 120 content tokens, up to 24 overlap.
  Settings reject more than 126 content tokens, reserving two special tokens within 128.
  M3 must enforce the same input limit without silent truncation; model selection is already
  coupled to tokenization in M2, not a decision that can be postponed until database design.
- Accumulate whole whitespace-delimited words while the actual candidate token count fits.
  Retokenizing each candidate avoids assuming a word's tokenization is independent of context.
  Overlap rounds down to whole words; one word exceeding the cap is cut between its own tokens.
- Never cross pages. Offsets are half-open Python character positions in extracted page text.
  Exact slicing preserves citation text; tests also require readable boundaries and capped counts.
- Detect language per page; weight the document's strict majority by character count.
  Blank pages contribute nothing, unknown text retains its weight, and ties remain `und`.
- Apply one NER character budget cumulatively in page order, including unsupported pages.
  Drop newline-spanning entities as likely layout artifacts; retain other model output as candidates.
- Keep models lazy and cached per process/configuration. Default runtime files live under
  `~/.cache/doc-insight/models`, independent of the working directory; containers set an absolute
  `DI_MODEL_CACHE` pointing at their mounted cache. spaCy models remain installed wheels.

## Consequences and alternatives

- Smaller chunks may lose some local context; overlap and M3 retrieval evaluation measure this trade-off.
- Snapping outward can exceed the input cap; snapping whole words inside it preserves both guarantees.
- Tiny tails remain when folding them would exceed the cap; redistribution adds complexity without
  fixing a correctness problem. A long URL or OCR run is cut between its tokens, so a boundary can
  fall inside that word alone; failing a whole document for one string was rejected.
- Candidate retokenization does more CPU work than slicing precomputed token windows; the bounded
  120-token window keeps this simple implementation practical for the current document workload.
- Page boundaries can split a continuing sentence; crossing pages would complicate citation positions.
- Character weighting favors long pages, which may contain boilerplate; page voting lets blank covers
  erase useful evidence. Neither is a claim about the language of every sentence.
- Newline filtering can discard a real wrapped name. Small spaCy models still misread table headings,
  page codes and salary figures; this heuristic is not an accuracy guarantee or a layout parser.
- E5-large needs its own pinned tokenizer, input/prefix budget, evaluation and version bump.
  Changing models later also requires regenerating chunks and, after M4, re-indexing stored vectors.
- A generative model belongs in the later answer-generation milestone; it does not replace
  a retrieval embedder merely because both expose tokens or hidden states. M2 has no server dependency.

The embedding/storage ADR planned for M3 will be ADR-0003, following creation order.
