# Pipeline: files to searchable documents

The [ingest service](ingest.md) accepts tenant-scoped uploads, retains original bytes
in encrypted object storage and publishes an atomic outbox through Redis Streams.
Processing that stream belongs to the worker consumer; the CLI path below remains available.

`di extract` is the file-to-text edge of the worker. It reads local PDF, PNG,
JPEG and TIFF files; it does not contact a service or persist a document.
`di analyze` adds page languages, named entities and chunks with exact page offsets.
`di analyze --embed` adds one vector per chunk; results still live only in memory/CLI output.
`di worker run` consumes uploaded originals through the same pipeline; see [worker operations](worker.md).
`di index` runs those stages and stores their output atomically; `di show` and `di search`
read only the requested tenant's rows. Start with the M4 section below for the complete slice.

```mermaid
flowchart LR
    file[File bytes] --> extract[Magic bytes and SHA-256]
    extract --> pdf[PDF text per page]
    extract --> image[Image: first frame]
    pdf --> decision{At least DI_OCR_MIN_CHARS?}
    decision -->|yes| pages[Typed pages]
    decision -->|no| render[Render at DI_OCR_DPI]
    render --> ocr[Tesseract eng + hrv]
    image --> ocr
    ocr --> pages
    pages --> language[Language per page]
    language --> ner[NER within document budget]
    ner --> chunks[Token windows within each page]
    chunks --> document[Document + entities + chunks]
    document -->|--embed| embed[Validate input budget + FastEmbed]
    embed --> vectors[384-dimensional vectors per chunk]
    vectors --> store[One transaction: document + chunks + entities]
    store --> db[(Postgres + pgvector)]
    question[Question + tenant] --> query[Embed question]
    query --> db
    db --> results[Tenant-filtered passages + page + cosine score]
```

`ExtractedDocument` contains `pipeline_version`, `sha256`, `media_type`, `pages`
and a derived `page_count`. Each `Page` has a one-based `number`, `text`,
`source` (`text_layer` or `ocr`) and derived `char_count`.
Both counts appear in JSON and cannot disagree with the current text/pages.
CRLF and CR become LF; surrounding whitespace is removed before counting.
Later chunk offsets must refer to this normalized page text.

The same byte snapshot supplies parsing and SHA-256, preventing a file changed
between two reads from producing text and a digest for different contents.
PDF handles, pages, text pages, bitmaps and Pillow images close explicitly.
The CLI is sequential: PDFium is not thread-safe, and pytesseract's command
setting is process-global. A future queue adapter must respect that constraint.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `DI_OCR_MIN_CHARS` | `20` | Below this many stripped characters, OCR the whole PDF page |
| `DI_OCR_DPI` | `200` | Raster resolution; must be positive |
| `DI_OCR_LANGS` | `eng+hrv` | Installed Tesseract language data |
| `DI_TESSERACT_CMD` | `tesseract` | Binary on PATH, or its full path |

One cached Pydantic-settings object reads the environment on first use.
Change environment values before starting `di`. `PIPELINE_VERSION = "6"` lives
in the extraction contracts; bump it whenever pipeline output changes, including models.
OCR text may vary across Tesseract/language-data versions; tests assert known
words, not byte-identical OCR output. Dependencies and fixture tooling use uv.lock.
Version 2 applies declared EXIF orientation before image OCR and removes the tag;
the sideways-JPEG regression test checks recovered words, not just nonempty output.
PDFium applies PDF rotation metadata when rendering. Unmarked sideways scans,
including images inside PDFs, still need orientation detection, which M1 does not do.

## Structure (M2)

| Model | Fields and meaning |
| --- | --- |
| `Document` | Extraction metadata plus `pages`, `entities`, `chunks`; derived `language` requires more than half the text characters to share a language, otherwise `und` |
| `Page` | Extraction fields plus `language` and `confidence`; extraction alone leaves these at `und` and `0` |
| `Chunk` | `text`, page `language`, one-based `page`, zero-based document-wide `ord`, `char_start`, `char_end`, `token_count` |
| `Entity` | Original `text`, model's `label`, first occurrence's `page`, `char_start`, `char_end`, and document-wide `count` |

Offsets are zero-based Python character positions, with an exclusive end:
`page.text[chunk.char_start:chunk.char_end] == chunk.text`. They are not byte offsets.
Chunks use whole whitespace-delimited words and retain the original whitespace between them. Chunks never cross pages:
citations stay unambiguous, at the cost of splitting sentences that continue on another page.
Each page first passes a Unicode guard. Pages with `Cc` characters other than tab, LF and CR,
or with `Cf`, `Cs`, `Co`, `Zl` or `Zp` characters, retain the original candidate-retokenizing
chunker: normalization can otherwise erase raw-text boundaries. Other pages encode once;
binary searches over token offsets count whole-word windows and overlaps. NBSP (`Zs`) stays
on this fast path. If token starts or ends are not nondecreasing, the page uses the reference
instead. Equivalence tests compare complete chunks against the preserved reference.
`token_count` never exceeds the configured cap.
Overlap includes as many whole words as fit its budget, so it may be smaller than requested.
Empty pages produce no chunks. A single word larger than the budget, such as a long URL or an
OCR run, is cut between its own tokens: the only place a boundary can fall inside a word, and
pieces and windows cut inside that word still re-encode in isolation. The model limit is
still never exceeded. Tiny final chunks remain separate when merging would
exceed the cap. See [ADR-0002](adr/0002-structured-representation.md).

Lingua considers only configured languages, using a prefix of each page. Confidence below
the threshold yields `und`; the measured confidence remains available. Document language uses
character-weighted votes, including unknown text; blank pages have zero weight and ties yield `und`. English and Croatian
pages use their own spaCy NER model; other languages emit a metadata-only skip log.
The NER character budget is consumed cumulatively in page order, including unsupported pages;
only that prefix reaches NER. Language detection and chunking still see every page.
Entities collapse by Unicode NFKC normalization, case folding, collapsed whitespace and label.
The first occurrence keeps its original spelling and offsets; repeats increment its count.
Spans containing a newline are dropped as likely layout artifacts, including some legitimate
wrapped names. Other table-induced mistakes (money amounts, page codes, misclassified headings)
remain possible with the small NER models; these are candidates, not verified facts.
Labels remain model-native (`PERSON` in English, `PER` in Croatian), avoiding a lossy mapping.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `DI_LANGUAGES` | `en,hr,de` | Comma-separated Lingua candidate languages |
| `DI_LANG_SAMPLE_CHARS` | `4000` | Language detection prefix per page |
| `DI_LANG_MIN_CONFIDENCE` | `0.5` | Minimum confidence for a language label |
| `DI_NER_MAX_CHARS` | `100000` | Maximum total page characters considered for NER; zero disables it |
| `DI_NER_MODELS` | `{"en":"en_core_web_sm","hr":"hr_core_news_sm"}` | JSON map of languages to installed spaCy models |
| `DI_CHUNK_TOKENS` | `120` | Maximum content tokens; at most 126 for MiniLM plus two special tokens |
| `DI_CHUNK_OVERLAP` | `24` | Maximum overlap tokens, rounded down to whole words; must be smaller than the window |
| `DI_EMBED_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Fixed profile: only this value is accepted; another model requires a reviewed change |
| `DI_TOKENIZER_REVISION` | `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` | Immutable tokenizer revision; change together with the model and pipeline version |
| `DI_MODEL_CACHE` | `~/.cache/doc-insight/models` | Shared cache independent of the working directory; use an absolute override for containers |

`LanguageDetector`, `NerExtractor` and `Tokenizer` are Protocols in contracts, with real
adapters in worker and fakes in testing. `analyze` composes them without opening files or
loading models itself. The tokenizer contract still returns character spans; the chunker
uses page offsets only after the guard described in [ADR-0002](adr/0002-structured-representation.md#token-counting-from-one-page-encoding).
All model loaders are lazy and cached per configuration for the life of the process.
spaCy's English and Croatian 3.8.0 wheels are exact URLs in the worker's `pyproject.toml`,
compatible with spaCy 3.8; Lingua's models ship inside its package. `uv.lock` pins dependencies.
pip-audit reports the two model wheels as unauditable because they are outside PyPI;
their exact URLs and lockfile hashes fix the artifacts, but do not constitute a vulnerability audit.
The first `di analyze` downloads the pinned tokenizer into `DI_MODEL_CACHE`; later processes
reuse it. No embedding weights are needed in M2.
MiniLM's pinned `sentence_bert_config.json` specifies 128 input tokens. The 120/24 defaults
leave room for special tokens without relying on the underlying BERT's larger position table.
The embedding adapter preserves this limit and rejects overlong inputs rather than truncating them.
Changing the embedding model also changes tokenizer/chunking and requires a pipeline-version bump.
An explicitly relative cache override is resolved from the startup directory; the default is absolute.

## Embeddings (M3)

`Embedder` exposes `embed_passages`, `embed_query`, `dimension` and `model_id`.
`embed_document` copies the structured document, attaching each returned vector to its chunk's
`embedding` and setting document `embed_model`/`embed_dimension`. These fields remain `null`
without `--embed`. It rejects wrong counts/dimensions, nonfinite values and zero vectors.
Text, offsets and the input document stay unchanged. Pipeline version is 5.

FastEmbed runs the quantized ONNX model on CPU, with no PyTorch dependency. Before loading it,
the adapter checks the entire batch against the 126-content-token limit, including queries.
MiniLM uses no prefixes. Its mean-pooled output is normalized to unit length; cosine measures
the angle between vectors and rejects zero/nonfinite or mismatched inputs.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `DI_EMBED_BATCH` | `32` | Number of texts processed per inference batch; must be positive |
| `DI_EMBED_ONNX_REPO` | `Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q` | Fixed profile: only this canonical ONNX repository is accepted |
| `DI_EMBED_REVISION` | `faf4aa4225822f3bc6376869cb1164e8e3feedd0` | Immutable ONNX snapshot revision; changing it requires a version bump |

The model loads once per configuration. Weights and tokenizer share `DI_MODEL_CACHE`.
For offline containers in M4, warm both snapshots there, then set `HF_HUB_OFFLINE=1` before
startup; a commit pin alone does not prevent a network attempt. Future query services must
translate rejection of overlong questions into a clear HTTP 400 response.
The first `--embed` run downloads roughly 0.22 GB; without that flag only the tokenizer is needed.
FastEmbed emits an upstream warning comparing mean pooling to its historical CLS behavior;
the locked runtime intentionally uses mean pooling. Model tests exercise that actual path.

`FakeEmbedder` creates deterministic hash-derived unit vectors. `KeywordEmbedder` hashes
case-folded words into 384 counters and normalizes them; empty lexical input uses a fixed unit
vector. It tests retrieval without a model but cannot recognize paraphrases without shared words.
Both accept another dimension for contract tests; the production profile is deliberately MiniLM-only.

```text
uv run --locked --all-packages di analyze tests/fixtures/text_hr.pdf --embed
uv run --locked --all-packages python scripts/eval_retrieval.py
uv run --locked --all-packages python scripts/eval_retrieval.py --provider fastembed
uv run --locked --all-packages python scripts/eval_retrieval.py --provider fastembed --production
uv run --locked --all-packages python scripts/eval_retrieval.py --language hr --provider all
uv run --locked --all-packages python scripts/eval_retrieval.py --language hr --provider all --production
uv run --locked --all-packages python scripts/make_eval_fixture.py
```

The generated `eval.jsonl` and `eval_hr.jsonl` each contain eight fixed questions over
`text_long.pdf` and `text_long_hr.pdf`, respectively. The two six-page corpora cover distinct
subjects. Each expected answer has at most five words and occurs exactly once in its source.
Evaluation defaults to English; `--language hr` selects Croatian. `--provider all` runs
both providers, while the default keyword run stays offline. Evaluation uses
64/8 windows and reports recall@5 (any expected answer in the first five chunks) and MRR (mean
reciprocal first-answer rank across the full ranking; absent answers score zero).
The offline keyword run uses 30 whitespace-tokenized chunks: recall@5 0.875, MRR 0.745.
The model run uses 42 subword-tokenized chunks: recall@5 1.000, MRR 0.938.
`--production` uses configured chunk sizes (120/24 by default): English MiniLM has 24 chunks,
recall@5 1.000, MRR 0.917; English keyword has 18 chunks, 1.000 and 0.729.
Croatian keyword scores 0.500/0.289 (recall@5/MRR) at 64/8 over 24 chunks, and 0.750/0.388
at 120/24 over 12 chunks. Croatian MiniLM scores 1.000/0.581 over 42 chunks and 0.875/0.896
over 24 chunks, respectively. Its English-translated questions against the Croatian corpus
score 1.000/0.875 at both sizes; these cross-lingual rows are report-only.
Different chunk sets and eight questions per language make this a bilingual regression
fixture, not a general quality claim or a Croatian-to-English evaluation.
See [ADR-0003](adr/0003-embeddings-and-vector-storage.md) for the complete table, upgrade criterion,
e5's tokenizer/input changes, migration cost, and the pgvector decision for M4.

## Storage and search (M4)

```mermaid
erDiagram
    documents ||--o{ chunks : owns
    documents ||--o{ entities : owns
    documents {
        uuid id PK
        text tenant_id "NOT NULL; indexed"
        text sha256 "unique with tenant_id"
        text pipeline_version
        text embed_model
        timestamptz processed_at
    }
    chunks {
        uuid document_id FK
        text tenant_id "NOT NULL; indexed"
        int page
        int char_start
        int char_end
        vector embedding "384 dimensions; HNSW cosine index"
    }
    entities {
        uuid document_id FK
        text tenant_id "NOT NULL; indexed"
        text label
        int count
    }
```

The [migration](../migrations/versions/0001_core_tables.py) lists every column.
Composite foreign keys include `tenant_id`: the database rejects children owned by another tenant.
Every repository read/write still filters by tenant. Migration 0002 also enables and forces
row-level security on all three tables. One policy per table checks `tenant_id` against
`current_setting('app.tenant_id', true)` for reads and writes, normalizing an empty
setting to NULL so pool resets cannot authorize empty tenant rows. The repository binds this
setting with `set_config(..., true)` at the start of every transaction, including its
REPEATABLE READ snapshot. Commit, rollback and pool return clear the tenant context.
Without a tenant, row reads/updates/deletes return nothing and inserts are rejected.
The CLI's caller supplies a trusted tenant until authenticated services arrive.
See [ADR-0005](adr/0005-tenant-row-level-security.md) for the role and trust boundaries.

`upsert_document` writes metadata and replaces all chunks/entities in one transaction.
The unique `(tenant_id, sha256)` conflict locks the row, serializing concurrent replays.
Any failure rolls everything back; readers use one consistent snapshot. Re-indexing preserves
the document ID, creation time and deterministic child IDs, while refreshing `processed_at`.
A new pipeline version replaces the old output. The index CLI still processes each invocation; the consumer skips a completed current-version event.
"effectively once" describes the stored result, not the CPU work. Version 6 adds chunk language.
Standalone child replacement also locks its parent and commits both child sets together.

Search orders tenant-owned chunks by pgvector cosine distance and returns `1 - distance` as
the score (similarity, not confidence). The HNSW index supports approximate search as data grows;
Postgres may choose an exact scan for small datasets. Filtered approximate recall needs a larger
tenant-specific benchmark before tuning. The [query service](query.md) adds full-text
retrieval, RRF fusion and grounded answers; `di search` remains cosine-only.
`di show` returns metadata, chunks and entities; original files and full page text are not stored.
Offsets refer to the normalized extracted page, so retain the original file for page reconstruction.

From the repository root, with Docker running:

```text
make db-up
make migrate
# A fresh Compose volume creates the restricted di_app login automatically
# (deploy/postgres/init-runtime-role.sql). For a volume created before that script
# existed, run the same two statements once, or recreate the volume with `make db-down`
# followed by `docker compose down -v`:
docker compose exec db psql -U di -d di -c "CREATE ROLE di_app LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT PASSWORD 'di_app'"
docker compose exec db psql -U di -d di -c "GRANT USAGE ON SCHEMA public TO di_app; GRANT SELECT, INSERT, UPDATE, DELETE ON documents, chunks, entities TO di_app"
uv run --locked --all-packages di index tests/fixtures/text_hr.pdf --tenant demo
uv run --locked --all-packages di show <document-id> --tenant demo
uv run --locked --all-packages di search "Gdje se nalazi Zagreb?" --tenant demo -k 5
make test-integration
make db-down
```

Index output includes four stage durations, a document UUID and chunk count; search includes
the document UUID, page, cosine score and passage. Repeat indexing: the UUID stays unchanged.
Optional [observability](observability.md) adds stage spans, duration metrics and a document
attempt counter. Leave `DI_OTEL_ENDPOINT` unset to run without exporters.
Search with another tenant returns no passages; showing another tenant's ID exits with an error.
`db-down` keeps the named volume. The Compose service publishes only to the local machine.
Copy `.env.example` to `.env` to change Compose credentials/port; export the Python URLs
separately. These passwords are for local development only. Runtime `DI_DATABASE_URL`
defaults to `postgresql+psycopg://di_app:di_app@localhost:5432/di`.
`DI_MIGRATION_DATABASE_URL` defaults to `postgresql+psycopg://di:di@localhost:5432/di`;
`make migrate` uses only this URL. Compose's `di` is the development migration superuser.
Never give its credentials to a runtime service: superusers and BYPASSRLS roles ignore FORCE.

For deployment, an administrator provisions `di_migrate LOGIN NOSUPERUSER BYPASSRLS`
and `di_app LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT`, with separate managed credentials.
The administrator installs the vector extension and grants `di_migrate` CREATE/USAGE on
`public`. Run migrations as `di_migrate`, which owns the tables; grant `di_app` schema USAGE
and only SELECT/INSERT/UPDATE/DELETE on documents, chunks and entities. Set default table
privileges as `di_migrate` for future migrations. Do not grant `di_app` membership in the
owner role, schema CREATE, TRUNCATE or table ownership. FORCE also protects an owner
without BYPASSRLS, but an owner can alter policies; runtime therefore does not own tables.

If 5432 is occupied, set `POSTGRES_PORT=55432` and match both Python URLs:

```powershell
$env:DI_DATABASE_URL = 'postgresql+psycopg://di_app:di_app@127.0.0.1:55432/di'
$env:DI_MIGRATION_DATABASE_URL = 'postgresql+psycopg://di:di@127.0.0.1:55432/di'
```

On Linux, use `export NAME='value'` for each setting.
`make test-integration` uses `DI_MIGRATION_DATABASE_URL` and needs database/role-creation
permission. Tests create and drop only randomly named databases and restricted runtime
logins, never the configured development database's tables. Repository contracts and
concurrent writers connect as restricted logins; migration checks use the owner. The harness
refuses hosts other than localhost unless `DI_ALLOW_REMOTE_TEST_DB=1` is set, so a shared
server named in `DI_MIGRATION_DATABASE_URL` cannot be touched by accident. Compose and CI pin the
same `pgvector/pgvector` image tag; move both together.

## Run it: WSL2/Linux

- Enable WSL2 and Docker Desktop's WSL integration; clone inside `~/src`, not `/mnt/c`.
- Open that checkout through VS Code's WSL connection.
- Install uv, GNU Make, Go (per [CI setup](ci.md)) and OCR:
  `sudo apt-get update && sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-hrv`.
- Verify `tesseract --list-langs` includes `eng` and `hrv`, then run `make setup`.

## Run it: native Windows

- Install uv, GNU Make and Go and put their executables on PATH.
- Install Tesseract from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki), including English and Croatian language data.
- If it is absent from PATH, set `$env:DI_TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'` in PowerShell.
- Verify `& $env:DI_TESSERACT_CMD --list-langs` (or `tesseract --list-langs` on PATH), then run `make setup`.

Commands work from the repository root in either shell:

```text
uv run --locked --all-packages di extract tests/fixtures/mixed.pdf
uv run --locked --all-packages di extract tests/fixtures/text_hr.pdf --json
uv run --locked --all-packages di extract "inputs/demo-files/DSJ Europe Engineering Salary Guide.pdf"
uv run --locked --all-packages di analyze tests/fixtures/text_hr.pdf --json
uv run --locked --all-packages di analyze "inputs/demo-files/DSJ Europe Engineering Salary Guide.pdf"
uv run --locked --all-packages python scripts/make_fixtures.py
make check
make test-models
```

The mixed fixture prints two pages: first `text_layer`, then `ocr`, with counts
and previews limited to 200 characters per page. JSON includes the full text.
These are explicitly requested CLI outputs, not log records; no document text
is logged. Treat redirected output as document data, and keep it under ignored
`inputs/` or `.cache/`. Missing files, invalid content and OCR failures exit nonzero.
`di analyze` prints document/page languages, confidence, an entity table and chunk size stats;
the Croatian fixture reports `hr`. Its JSON includes full pages, entity positions and chunks.
`make test` uses fakes plus installed Lingua/spaCy models and blocks Python socket connections.
It checks chunk slices, whole-word boundaries, token budgets, weighted language, entity counts and NER limits.
`make test-models` exercises the real tokenizer, embeddings, readable boundaries and the 128-token
limit including special tokens, and enforces model recall@5 ≥ 0.8 for each language at 64/8;
it may download files. `make test` also enforces keyword recall@5 ≥ 0.75 for English and
≥ 0.5 for Croatian without network or database access. The lower Croatian baseline gate
records the measured limit of whitespace hashing on inflected forms, not a model concession.
That small subset disables coverage reporting; the full default suite enforces the 70% floor.

Fixtures use a committed font subset, a fixed PDF creation date and twelve fixed
topics across six pages per long fixture; rerunning the generator recreates all six extraction files.
The Croatian topics have 95–100 words each. Font coverage and extracted text round trips are
tested; the existing English fixtures remain byte-identical after regeneration.
See [font provenance](../scripts/fonts/readme.md) and [ADR-0001](adr/0001-text-extraction.md).

## Not yet

Stream consumer, gateway/JWT and application containers remain later work.
Infrastructure and telemetry have independent Compose profiles.
M2 performance follow-ups are still pending; the bilingual fixtures and real Croatian smoke
test do not replace a representative retrieval-quality benchmark.
Extraction and analysis remain stateless; index/show/search and the query service require a tenant.
Multi-frame TIFF traversal, mixed text/image regions within one page, encrypted
PDF passwords and parallel extraction are not implemented in M1.
