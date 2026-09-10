/** Keep bearer tokens off network HTTP; loopback remains usable for local development. */
export function requireSecureTransport(location = globalThis.location) {
    // Browser URLs bracket IPv6; callers that normalize hostnames may omit brackets.
    const loopback = ["localhost", "127.0.0.1", "[::1]", "::1"].includes(location.hostname);
    if (location.protocol === "https:" || (location.protocol === "http:" && loopback))
        return;
    throw new Error("Open this workspace over HTTPS before entering an access token.");
}
