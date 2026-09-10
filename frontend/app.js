import { uploadFile } from "./upload.js";
// No persistent browser storage: credentials and document content die with this page.
import { $ } from "./dom.js";
import { renderDocuments, renderAnswer } from "./views.js";
let token = "",
    offset = 0,
    documents = [],
    poll = null,
    refreshFailed = false,
    generation = 0;
const notice = (message = "") => {
    refreshFailed = false;
    $("notice").textContent = message;
};
const showRefreshFailure = (error) => {
    notice(error.message);
    refreshFailed = true;
};
/** Clear page-held credentials/content and invalidate pending successful responses. */
function disconnect() {
    token = "";
    // A completed fetch can outlive sign-out; generation guards prevent repainting it.
    generation++;
    clearInterval(poll);
    documents = [];
    $("auth").hidden = false;
    $("connected").hidden = true;
    $("signout").hidden = true;
    $("documents").replaceChildren();
    $("answer").replaceChildren();
    $("token").value = "";
    $("question").value = "";
    $("file").value = "";
    $("upload-button").disabled = true;
}
/** Call the same-origin gateway with the current token and safe user-facing errors. */
async function api(path, options = {}) {
    const response = await fetch(`/api${path}`, {
        ...options,
        headers: { Authorization: `Bearer ${token}`, ...options.headers },
        signal: AbortSignal.timeout(45000),
    });
    if (response.status === 401) {
        disconnect();
        throw new Error(
            "Your access token has expired or is invalid. Connect again with a fresh token.",
        );
    }
    if (response.status === 403)
        throw new Error("This tenant is not provisioned for the workspace.");
    if (response.status === 429)
        throw new Error(
            "Too many requests. Please wait a moment and try again.",
        );
    if (!response.ok)
        throw new Error(
            `Request failed (${response.status}). Check your input and try again.`,
        );
    return response.json();
}
/** Refresh library metadata and usage together, discarding a disconnected session. */
async function refresh() {
    const current = generation;
    const [data, usage] = await Promise.all([
        api(`/documents?limit=20&offset=${offset}`),
        api("/usage"),
    ]);
    if (current !== generation || !token) return;
    if (refreshFailed) notice();
    documents = data.items;
    renderDocuments(documents);
    $("document-count").textContent =
        `${offset + documents.length}${documents.length === 20 ? "+" : ""} documents`;
    $("usage-count").textContent =
        `${usage.charged_tokens.toLocaleString()} / ${usage.daily_limit.toLocaleString()} tokens`;
    $("usage-detail").textContent =
        `${usage.requests} generation attempts · ${usage.reserved_tokens.toLocaleString()} tokens reserved`;
    $("prev").disabled = offset === 0;
    $("next").disabled = documents.length < 20;
    $("page-number").textContent = `Page ${offset / 20 + 1}`;
}
$("auth-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    token = $("token").value.trim();
    notice();
    offset = 0;
    try {
        await refresh();
        if (!token) return;
        $("auth").hidden = true;
        $("connected").hidden = false;
        $("signout").hidden = false;
        $("token").value = "";
        poll = setInterval(() => {
            // Background tabs need no polling; the next visible interval catches up.
            if (token && !document.hidden)
                refresh().catch(showRefreshFailure);
        }, 6000);
    } catch (error) {
        token = "";
        notice(error.message);
    }
});
$("signout").addEventListener("click", () => {
    disconnect();
    notice("Disconnected. Your session has been cleared.");
});
$("refresh").addEventListener("click", () => {
    notice();
    refresh().catch(showRefreshFailure);
});
for (const [id, delta] of [
    ["prev", -20],
    ["next", 20],
])
    $(id).addEventListener("click", () => {
        offset += delta;
        refresh().catch(showRefreshFailure);
    });
$("file").addEventListener("change", () => {
    $("upload-button").disabled = !$("file").files.length;
});
$("upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = $("file").files[0];
    if (!file || file.size > 50 * 1024 * 1024) {
        notice("Choose a PDF or image no larger than 50 MiB.");
        return;
    }
    const current = generation;
    $("upload-button").disabled = true;
    $("upload-progress").hidden = false;
    notice();
    try {
        await uploadFile(file, token, disconnect);
        if (current !== generation) return;
        $("file").value = "";
        offset = 0;
        notice("Document uploaded. Processing continues in the background.");
        await refresh();
    } catch (error) {
        notice(error.message);
    } finally {
        $("upload-progress").hidden = true;
        $("upload-button").disabled = !$("file").files.length;
    }
});
$("query-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    notice();
    const current = generation;
    $("ask-button").disabled = true;
    $("ask-button").textContent = "Reading your sources…";
    const filter = {};
    if ($("scope").value) filter.document_ids = [$("scope").value];
    if ($("language").value) filter.language = $("language").value;
    try {
        const data = await api("/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                question: $("question").value.trim(),
                top_k: 5,
                filter,
            }),
        });
        if (current === generation && token) {
            renderAnswer(data, documents);
            await refresh();
        }
    } catch (error) {
        notice(error.message);
    } finally {
        $("ask-button").disabled = false;
        $("ask-button").textContent = "Find an answer ↗";
    }
});
