import { $ } from "./dom.js";
import { requireSecureTransport } from "./transport.mjs";
/** Resolve when ingestion accepts the file; processing finishes asynchronously. */
export function uploadFile(file, token, onExpired) {
    return new Promise((resolve, reject) => {
        requireSecureTransport();
        // XHR exposes upload progress; fetch does not provide this browser callback.
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/ingest");
        xhr.timeout = 120000;
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable)
                $("upload-progress").value = (e.loaded / e.total) * 100;
        };
        xhr.onerror = () =>
            reject(new Error("Upload connection failed. Please retry."));
        xhr.ontimeout = () =>
            reject(
                new Error(
                    "Upload timed out. Refresh the library before retrying.",
                ),
            );
        xhr.onload = () => {
            if (xhr.status === 401) {
                onExpired();
                reject(new Error("Access token expired. Connect again."));
            } else if (xhr.status >= 200 && xhr.status < 300) resolve();
            else
                reject(
                    new Error(
                        `Upload failed (${xhr.status}). Supported files: PDF, PNG, JPEG.`,
                    ),
                );
        };
        // Let the browser set Content-Type together with its generated multipart boundary.
        const body = new FormData();
        body.append("file", file);
        xhr.send(body);
    });
}
