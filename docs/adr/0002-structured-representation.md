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
  Count tokens from page offsets only after the Unicode guard below; guarded pages retain
  candidate retokenization.
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
- Candidate retokenization remains the fallback for guarded pages. Other pages use one encoding
  and binary searches over sorted token spans; see the measurement and guard below.
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

## Token counting from one page encoding

Whitespace pre-splitting alone was a false premise for counting raw-text windows from page
offsets. The pinned tokenizer normalizes before splitting and can delete separators. For
`"a\x0b. b"` at 2/1, Python treats the vertical tab as a word boundary while the tokenizer
normalizes it to `"a. b"`. Unguarded counting emits `". b"` with a reported count of two;
encoding that chunk alone produces three tokens. The 256-page demo book exposed this on
page 239. See the [journal](../journal.md#guarded-page-token-counting) for the changed offsets.

Choose the path once per page. Any `Cc` code point except tab, LF and CR, or any `Cf`, `Cs`,
`Co`, `Zl` or `Zp` code point, selects the preserved reference chunker for the entire page.
This conservative guard avoids reproducing the tokenizer's normalizer. NBSP is `Zs` and
stays on the fast path. Other pages encode once and count whole-word windows and overlaps
using binary searches over token starts and ends. Both offset sequences must be nondecreasing;
a once-per-page check selects the reference if either moves backwards. Equal and overlapping
spans remain valid when both sequences are ordered. Oversized words still split between their
tokens, and pieces or candidate windows cut inside those words re-encode in isolation.

Equivalence tests retain the old function, compare every chunk field, and exercise guarded
characters, NBSP, fixtures, window sizes and oversized words with the pinned tokenizer.
The guard is tied to this tokenizer profile and must be reviewed when the model changes.
Extraction, stored chunks, the Tokenizer Protocol and pipeline version 6 are unchanged.

Median chunk-stage seconds over three runs at 120/24, including the offset-order check,
with the tokenizer loaded before timing (Windows, Python 3.12; extraction and equality
assertions excluded from chunk timing):

| Input | Reference | Guarded chunker | Guarded pages |
| --- | ---: | ---: | ---: |
| `text_long.pdf` (6 pages) | 0.374 | 0.014 | 0/6 |
| 256-page demo book | 24.615 | 23.039 | 242/256 |
| 659-page demo book | 65.225 | 49.444 | 400/659 |

Full chunk equality passed on all three inputs in every run. The guard is common in these
books, not exceptional: the mathematics text contains control and private-use characters,
and 400 pages of the other book contain U+0002. Their guarded chunking costs 52.69 and
31.98 times a single page-encoding pass, so the original within-2-times target is not met on
the books. The plain fixture is within that target (2.00 times, rounded). The conservative
page fallback trades those remaining costs for unchanged output; narrowing it needs separate
evidence. Reproduce with `scripts/benchmark_chunker.py`; demo inputs are not committed.
