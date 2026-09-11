import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
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
      claimSession(temp.directory, { host: "codex", cwd: pluginRoot, sessionKey, now: 1_000 }).status,
      "pending",
    );
    const registration = registerMcpInstance(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      now: 1_001,
    });
    assert.equal(registration.outcome.status, "pending");
    assert.throws(
      () =>
        consumeBinding(
          temp.directory,
          { ...registration, capability: "replayed-capability" },
          { now: 1_200 },
        ),
      { code: "BINDING_REPLAY" },
    );
    const binding = consumeBinding(temp.directory, registration, { now: 1_201 });
    assert.equal(binding.sessionKey, sessionKey);
    assert.equal(JSON.stringify(binding).includes("raw-session-id"), false);
    assert.equal(consumeBinding(temp.directory, registration), null);
  } finally {
    temp.cleanup();
  }
});

for (const host of ["codex", "claude-code"]) {
  test(`${host} keeps a live pending rendezvous after the fixed TTL`, () => {
    const temp = temporaryDirectory();
    try {
      const sessionKey = scopeKey(host, `${host}-late-first-tool`);
      const registration = registerMcpInstance(temp.directory, {
        host,
        cwd: pluginRoot,
        pid: process.pid,
        now: 1_000,
      });
      const claim = claimSession(temp.directory, {
        host,
        cwd: pluginRoot,
        sessionKey,
        now: 1_001,
      });
      assert.equal(registration.outcome.status, "pending");
      assert.equal(claim.status, "pending");

      const binding = consumeBinding(temp.directory, registration, { now: 31_002 });
      assert.equal(binding.sessionKey, sessionKey);
    } finally {
      temp.cleanup();
    }
  });
}

test("an expired claim without a live MCP instance is still pruned", () => {
  const temp = temporaryDirectory();
  try {
    const sessionKey = scopeKey("codex", "orphaned-claim");
    claimSession(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      sessionKey,
      now: 1_000,
    });
    const registration = registerMcpInstance(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      now: 31_001,
    });

    assert.equal(registration.outcome.status, "pending");
    assert.equal(consumeBinding(temp.directory, registration, { now: 31_200 }), null);
  } finally {
    temp.cleanup();
  }
});

test("a dead MCP instance is still pruned immediately", () => {
  const temp = temporaryDirectory();
  try {
    const instanceId = "dead-mcp-instance";
    registerMcpInstance(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      instanceId,
      pid: 2_147_483_647,
      now: 1_000,
    });

    const instanceRoot = path.join(temp.directory, "rendezvous", "codex", "instances");
    assert.equal(fs.existsSync(path.join(instanceRoot, `${instanceId}.json`)), false);
    assert.equal(fs.existsSync(path.join(instanceRoot, `${instanceId}.secret`)), false);
  } finally {
    temp.cleanup();
  }
});

test("rendezvous rejects a second instance that arrives inside the settle window", () => {
  const temp = temporaryDirectory();
  try {
    const sessionKey = scopeKey("codex", "two-instances");
    claimSession(temp.directory, { host: "codex", cwd: pluginRoot, sessionKey, now: 1_000 });
    const first = registerMcpInstance(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      now: 1_010,
    });
    const second = registerMcpInstance(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      now: 1_050,
    });
    assert.equal(first.outcome.status, "pending");
    assert.equal(second.outcome.status, "ambiguous");
    assert.equal(consumeBinding(temp.directory, first, { now: 1_200 }), null);
    assert.equal(consumeBinding(temp.directory, second, { now: 1_200 }), null);
  } finally {
    temp.cleanup();
  }
});

test("rendezvous rejects a second claim that arrives inside the settle window", () => {
  const temp = temporaryDirectory();
  try {
    const registration = registerMcpInstance(temp.directory, {
      host: "claude-code",
      cwd: pluginRoot,
      now: 1_000,
    });
    const first = claimSession(temp.directory, {
      host: "claude-code",
      cwd: pluginRoot,
      sessionKey: scopeKey("claude-code", "claim-a"),
      now: 1_010,
    });
    const second = claimSession(temp.directory, {
      host: "claude-code",
      cwd: pluginRoot,
      sessionKey: scopeKey("claude-code", "claim-b"),
      now: 1_050,
    });
    assert.equal(first.status, "pending");
    assert.equal(second.status, "ambiguous");
    assert.equal(consumeBinding(temp.directory, registration, { now: 1_200 }), null);
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
