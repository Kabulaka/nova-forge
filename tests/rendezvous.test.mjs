import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import {
  claimSession,
  consumeBinding,
  registerMcpInstance,
  selectHostProcessId,
} from "../runtime/core/rendezvous.mjs";
import { scopeKey } from "../runtime/core/util.mjs";
import { pluginRoot, temporaryDirectory } from "./helpers.mjs";

test("host process selection skips hook shells and finds the owning host", () => {
  const hookAncestry = [
    { pid: 30_003, parentPid: 30_002, command: "node /cache/.claude/plugins/nova/hooks/run.mjs" },
    { pid: 30_002, parentPid: 30_001, command: "/bin/sh -c node hooks/run.mjs" },
    { pid: 30_001, parentPid: 1, command: "/usr/local/bin/claude -p smoke" },
  ];
  const mcpAncestry = [
    { pid: 30_004, parentPid: 30_001, command: "node runtime/mcp/server.mjs" },
    { pid: 30_001, parentPid: 1, command: "/usr/local/bin/claude -p smoke" },
  ];
  assert.equal(selectHostProcessId("claude-code", hookAncestry, 30_002), 30_001);
  assert.equal(selectHostProcessId("claude-code", mcpAncestry, 30_001), 30_001);
  assert.equal(
    selectHostProcessId(
      "codex",
      [{ pid: 40_001, parentPid: 1, command: "/opt/openai/codex app-server" }],
      9,
    ),
    40_001,
  );
  assert.equal(selectHostProcessId("codex", hookAncestry, 30_002), 30_002);
});

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

test("Codex binds one plugin-root MCP instance to one project-root hook claim", () => {
  const temp = temporaryDirectory();
  try {
    const projectRoot = path.join(temp.directory, "project");
    const sessionKey = scopeKey("codex", "portable-plugin-session");
    const registration = registerMcpInstance(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      allowCwdMismatch: true,
      pid: process.pid,
      now: 1_000,
    });
    const claim = claimSession(temp.directory, {
      host: "codex",
      cwd: projectRoot,
      sessionKey,
      now: 1_001,
    });
    assert.equal(registration.outcome.status, "pending");
    assert.equal(claim.status, "pending");

    const binding = consumeBinding(temp.directory, registration, { now: 1_200 });
    assert.equal(binding.sessionKey, sessionKey);
    assert.notEqual(binding.cwdHash, registration.cwdHash);
  } finally {
    temp.cleanup();
  }
});

test("Codex cwd-agnostic rendezvous fails closed with multiple project claims", () => {
  const temp = temporaryDirectory();
  try {
    const registration = registerMcpInstance(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      allowCwdMismatch: true,
      pid: process.pid,
      now: 1_000,
    });
    claimSession(temp.directory, {
      host: "codex",
      cwd: path.join(temp.directory, "project-a"),
      sessionKey: scopeKey("codex", "portable-a"),
      now: 1_010,
    });
    const second = claimSession(temp.directory, {
      host: "codex",
      cwd: path.join(temp.directory, "project-b"),
      sessionKey: scopeKey("codex", "portable-b"),
      now: 1_020,
    });
    assert.equal(second.status, "ambiguous");
    assert.equal(consumeBinding(temp.directory, registration, { now: 1_200 }), null);
  } finally {
    temp.cleanup();
  }
});

test("an unclaimed MCP instance from another live host process does not block Codex binding", () => {
  const temp = temporaryDirectory();
  try {
    registerMcpInstance(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      hostPid: 10_001,
      allowCwdMismatch: true,
      pid: process.pid,
      now: 1_000,
    });
    const registration = registerMcpInstance(temp.directory, {
      host: "codex",
      cwd: pluginRoot,
      hostPid: 10_002,
      allowCwdMismatch: true,
      pid: process.pid,
      now: 1_010,
    });
    const claim = claimSession(temp.directory, {
      host: "codex",
      cwd: path.join(temp.directory, "project"),
      sessionKey: scopeKey("codex", "new-session"),
      hostPid: 10_002,
      now: 1_020,
    });

    assert.equal(claim.status, "pending");
    const binding = consumeBinding(temp.directory, registration, { now: 1_200 });
    assert.equal(binding.sessionKey, scopeKey("codex", "new-session"));
  } finally {
    temp.cleanup();
  }
});

test("concurrent Codex host processes bind only their own claim and MCP instance", () => {
  const temp = temporaryDirectory();
  try {
    const registrations = [20_001, 20_002].map((hostPid, index) => {
      const registration = registerMcpInstance(temp.directory, {
        host: "codex",
        cwd: pluginRoot,
        hostPid,
        allowCwdMismatch: true,
        pid: process.pid,
        now: 1_000 + index,
      });
      claimSession(temp.directory, {
        host: "codex",
        cwd: path.join(temp.directory, `project-${index}`),
        sessionKey: scopeKey("codex", `session-${index}`),
        hostPid,
        now: 1_010 + index,
      });
      return registration;
    });

    for (const [index, registration] of registrations.entries()) {
      const binding = consumeBinding(temp.directory, registration, { now: 1_200 });
      assert.equal(binding.sessionKey, scopeKey("codex", `session-${index}`));
    }
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
