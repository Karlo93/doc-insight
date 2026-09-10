# Cost estimate

Planning estimate checked 2026-09-10; USD before tax. OCR, language detection, NER
and embeddings run locally, so uploading 1,000 documents incurs **$0 in OpenAI
ingestion fees**. CPU, storage, electricity and operations still have a cost.

The configured `gpt-4.1-mini-2025-04-14` costs $0.40 per million input tokens,
$0.10 per million cached input tokens and $1.60 per million output tokens.
Source: [OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

Assume 1,500 input tokens (instructions, question and retrieved passages) and 300
output tokens per answer, with no cache discount. One answer costs
`(1500 × 0.40 + 300 × 1.60) / 1,000,000 = $0.00108`.

| Average questions per document | Answers per 1,000 documents | OpenAI estimate |
| --- | --- | --- |
| 0, or extractive answers only | 0 hosted | $0.00 |
| 1 | 1,000 | $1.08 |
| 5 | 5,000 | $5.40 |
| 20 | 20,000 | $21.60 |

For an illustrative $30 monthly infrastructure allocation serving 10,000 documents
per month, add `$30 / 10,000 × 1,000 = $3` per 1,000 documents. Five questions per
document would therefore total **about $8.40 per 1,000 documents**. The $30 is a
planning assumption, not a server quote or measured operating bill. For an existing
private server, use measured incremental power, storage and hardware allocation.

At 5 MiB per original, 1,000 documents require about 4.88 GiB before extracted text,
vectors, indexes, replicas and backups. Page count and scanned-page proportion drive
CPU time; document count alone cannot predict ingestion cost or capacity. Operator
time, taxes and network/backup charges are excluded from the example.

Replace the token assumptions with observed provider usage before budgeting a
deployment. Longer passages, retries and longer answers increase cost. The default
250,000-token daily tenant budget cannot serve the example's 9 million tokens in
one day; budget and provider quota changes are separate operator decisions.
