import { $, element } from "./dom.js";
export function renderDocuments(items) {
    const box = $("documents");
    box.replaceChildren();
    if (!items.length)
        box.append(
            element(
                "p",
                "Your library is ready for its first document.",
                "muted",
            ),
        );
    for (const doc of items) {
        const row = element("article", "", "document");
        row.append(element("strong", doc.filename));
        const meta = element("div", "", "document-meta");
        meta.append(
            element(
                "span",
                `${(doc.size_bytes / 1024).toFixed(0)} KiB · ${doc.language || "Detecting language"}${doc.page_count ? ` · ${doc.page_count} pages` : ""}`,
            ),
        );
        meta.append(element("span", doc.status, `status ${doc.status}`));
        row.append(meta);
        if (doc.error)
            row.append(
                element(
                    "small",
                    "Processing failed. Try a different file or contact the administrator.",
                ),
            );
        box.append(row);
    }
    const selected = $("scope").value;
    $("scope").replaceChildren(new Option("All documents", ""));
    for (const doc of items.filter((d) => d.status === "processed"))
        $("scope").append(new Option(doc.filename, doc.id));
    if ([...$("scope").options].some((option) => option.value === selected))
        $("scope").value = selected;
}
export function renderAnswer(data, documents) {
    const box = $("answer");
    box.replaceChildren();
    const header = element("div", "", "answer-header");
    header.append(
        element(
            "h2",
            data.abstained ? "No supported answer" : "From your documents",
        ),
    );
    header.append(
        element(
            "small",
            `${Math.round(data.confidence * 100)}% evidence score · ${(data.latency_ms / 1000).toFixed(1)}s`,
        ),
    );
    box.append(header);
    box.append(
        element(
            "div",
            data.answer ||
                "The available sources do not support an answer. Try a more specific question or add another document.",
            "answer-text",
        ),
    );
    const info = data.generation;
    box.append(
        element(
            "small",
            info.provider === "openai"
                ? `OpenAI · ${info.model} · ${(info.usage?.input_tokens || 0) + (info.usage?.output_tokens || 0)} tokens`
                : `Extractive answer · ${info.fallback_reason || "local generation"}`,
        ),
    );
    if (data.sources.length) box.append(element("h3", "Source passages"));
    data.sources.forEach((source, i) => {
        const details = element("details", "", "source");
        const name =
            documents.find((d) => d.id === source.document_id)?.filename ||
            source.document_id;
        details.append(
            element("summary", `[${i + 1}] ${name} · page ${source.page}`),
        );
        details.append(element("p", source.text));
        box.append(details);
    });
    if (data.entities.length) {
        const entities = element("div", "", "entities");
        data.entities
            .slice(0, 20)
            .forEach((entity) =>
                entities.append(
                    element(
                        "span",
                        `${entity.text} · ${entity.label}`,
                        "entity",
                    ),
                ),
            );
        box.append(entities);
    }
}
