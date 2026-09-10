/** Keep bearer tokens off network HTTP; loopback remains usable for local development. */
export function requireSecureTransport(location = globalThis.location) {
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
    if (location.protocol === "https:" || (location.protocol === "http:" && loopback))
        return;
    throw new Error("Open this workspace over HTTPS before entering an access token.");
}
