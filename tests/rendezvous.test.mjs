import assert from "node:assert/strict";
import test from "node:test";
import {
  claimSession,
  consumeBinding,
  registerMcpInstance,
} from "../runtime/core/rendezvous.mjs";
import { scopeKey } from "../runtime/core/util.mjs";
import { pluginRoot, temporaryDirectory } from "./helpers.mjs";

test("one hook claim binds exactly one MCP instance without exposing session id", () => {
  const temp = temporaryDirectory();
  try {
    const sessionKey = scopeKey("codex", "raw-session-id");
    assert.equal(
      claimSession(temp.directory, { host: "codex", cwd: pluginRoot, sessionKey }).status,
      "pending",
    );
    const registration = registerMcpInstance(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
    });
    assert.equal(registration.outcome.status, "bound");
    assert.throws(
      () => consumeBinding(temp.directory, { ...registration, capability: "replayed-capability" }),
      { code: "BINDING_REPLAY" },
    );
    const binding = consumeBinding(temp.directory, registration);
    assert.equal(binding.sessionKey, sessionKey);
    assert.equal(JSON.stringify(binding).includes("raw-session-id"), false);
    assert.equal(consumeBinding(temp.directory, registration), null);
  } finally {
    temp.cleanup();
  }
});

test("concurrent same-directory claims fail closed as ambiguous", () => {
  const temp = temporaryDirectory();
  try {
    claimSession(temp.directory, {
      host: "claude-code",
      cwd: pluginRoot,
      sessionKey: scopeKey("claude-code", "session-a"),
    });
    const second = claimSession(temp.directory, {
      host: "claude-code",
      cwd: pluginRoot,
      sessionKey: scopeKey("claude-code", "session-b"),
    });
    assert.equal(second.status, "ambiguous");
    const registration = registerMcpInstance(temp.directory, {
      host: "claude-code",
      cwd: pluginRoot,
    });
    assert.equal(registration.outcome.status, "ambiguous");
    assert.equal(consumeBinding(temp.directory, registration), null);
  } finally {
    temp.cleanup();
  }
});

test("host and cwd are part of the rendezvous isolation key", () => {
  const temp = temporaryDirectory();
  try {
    claimSession(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      sessionKey: scopeKey("codex", "session-a"),
    });
    const registration = registerMcpInstance(temp.directory, {
      host: "claude-code",
      cwd: pluginRoot,
    });
    assert.equal(registration.outcome.status, "pending");
  } finally {
    temp.cleanup();
  }
});
