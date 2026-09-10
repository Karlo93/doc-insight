import test from "node:test";
import assert from "node:assert/strict";
import { requireSecureTransport } from "../../frontend/transport.mjs";

test("TLS and explicit loopback development origins are allowed", () => {
    for (const origin of ["https://workspace.example", "http://localhost:5080", "http://127.0.0.1", "http://[::1]"])
        assert.doesNotThrow(() => requireSecureTransport(new URL(origin)));
    assert.doesNotThrow(() => requireSecureTransport({ protocol: "http:", hostname: "::1" }));
});

test("network HTTP and lookalike loopback hosts cannot carry credentials", () => {
    // A suffix match would incorrectly trust an attacker-controlled hostname.
    for (const origin of ["http://workspace.example", "http://127.0.0.1.example", "http://localhost.example", "file:///app"])
        assert.throws(() => requireSecureTransport(new URL(origin)), /HTTPS/);
});
