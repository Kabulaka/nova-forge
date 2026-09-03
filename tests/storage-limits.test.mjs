import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { SESSION_TTL_MS } from "../runtime/core/constants.mjs";
import {
  cleanupExpiredScopes,
  initialEnvelope,
  writeEnvelope,
} from "../runtime/core/storage.mjs";
import { binding, temporaryDirectory } from "./helpers.mjs";

function stateDirectory(root, current) {
  return path.join(root, "state", current.host, current.sessionKey);
}

function permissiveLimits(overrides = {}) {
  return {
    hostBytes: 1024 * 1024,
    globalBytes: 1024 * 1024,
    hostSessions: 10,
    ...overrides,
  };
}

test("expired scopes are cleaned oldest-first only after a nonblocking lock and lease reread", () => {
  const temp = temporaryDirectory();
  try {
    const expired = binding("codex", "expired-session");
    writeEnvelope(temp.directory, expired, initialEnvelope(expired, "0.1.0", 0), {
      rotateCurrentToBackup: false,
      now: 0,
    });
    const directory = stateDirectory(temp.directory, expired);
    fs.mkdirSync(path.join(directory, ".lock"));

    const skipped = cleanupExpiredScopes(temp.directory, { now: SESSION_TTL_MS + 1 });
    assert.equal(skipped.removed, 0);
    assert.equal(fs.existsSync(path.join(directory, "current.json")), true);

    fs.rmdirSync(path.join(directory, ".lock"));
    const cleaned = cleanupExpiredScopes(temp.directory, { now: SESSION_TTL_MS + 1 });
    assert.equal(cleaned.removed, 1);
    assert.equal(cleaned.reclaimedBytes > 0, true);
    assert.equal(fs.existsSync(directory), false);
  } finally {
    temp.cleanup();
  }
});

test("quota projection replaces current bytes instead of double-counting them", () => {
  const temp = temporaryDirectory();
  try {
    const current = binding("codex", "replacement-session");
    const envelope = initialEnvelope(current, "0.1.0", 1_000);
    writeEnvelope(temp.directory, current, envelope, {
      rotateCurrentToBackup: false,
      now: 1_000,
    });
    const currentFile = path.join(stateDirectory(temp.directory, current), "current.json");
    const existingBytes = fs.statSync(currentFile).size;
    envelope.leaseVersion += 1;
    envelope.lastActivityAt = new Date(2_000).toISOString();
    envelope.expiresAt = new Date(2_000 + SESSION_TTL_MS).toISOString();

    assert.doesNotThrow(() =>
      writeEnvelope(temp.directory, current, envelope, {
        rotateCurrentToBackup: false,
        limits: permissiveLimits({
          hostBytes: existingBytes + 128,
          globalBytes: existingBytes + 128,
        }),
        now: 2_000,
      }),
    );
    assert.equal(
      fs.readdirSync(stateDirectory(temp.directory, current)).some((name) => name.endsWith(".tmp")),
      false,
    );
  } finally {
    temp.cleanup();
  }
});

test("quota enforcement reclaims expired scopes before rejecting a new session", () => {
  const temp = temporaryDirectory();
  try {
    const expired = binding("codex", "expired-for-quota");
    writeEnvelope(temp.directory, expired, initialEnvelope(expired, "0.1.0", 0), {
      rotateCurrentToBackup: false,
      now: 0,
    });
    const expiredFile = path.join(stateDirectory(temp.directory, expired), "current.json");
    const oneEnvelopeBytes = fs.statSync(expiredFile).size;
    const active = binding("codex", "new-after-cleanup");
    const now = SESSION_TTL_MS + 1;

    assert.doesNotThrow(() =>
      writeEnvelope(temp.directory, active, initialEnvelope(active, "0.1.0", now), {
        rotateCurrentToBackup: false,
        limits: permissiveLimits({
          hostBytes: oneEnvelopeBytes + 256,
          globalBytes: oneEnvelopeBytes + 256,
        }),
        now,
      }),
    );
    assert.equal(fs.existsSync(stateDirectory(temp.directory, expired)), false);
    assert.equal(fs.existsSync(stateDirectory(temp.directory, active)), true);
  } finally {
    temp.cleanup();
  }
});

test("quota failures leave the previous envelope intact and create no temporary file", () => {
  const temp = temporaryDirectory();
  try {
    const current = binding("codex", "quota-failure");
    const envelope = initialEnvelope(current, "0.1.0", 1_000);
    writeEnvelope(temp.directory, current, envelope, {
      rotateCurrentToBackup: false,
      now: 1_000,
    });
    const directory = stateDirectory(temp.directory, current);
    const before = fs.readFileSync(path.join(directory, "current.json"), "utf8");
    envelope.leaseVersion += 1;

    assert.throws(
      () =>
        writeEnvelope(temp.directory, current, envelope, {
          rotateCurrentToBackup: false,
          limits: permissiveLimits({ hostBytes: 1, globalBytes: 1 }),
          now: 2_000,
        }),
      { code: "HOST_QUOTA" },
    );
    assert.equal(fs.readFileSync(path.join(directory, "current.json"), "utf8"), before);
    assert.equal(fs.readdirSync(directory).some((name) => name.endsWith(".tmp")), false);
  } finally {
    temp.cleanup();
  }
});

test("failed new scopes do not consume the exact host session quota", () => {
  const temp = temporaryDirectory();
  try {
    const rejected = binding("codex", "rejected-session");
    assert.throws(
      () =>
        writeEnvelope(temp.directory, rejected, initialEnvelope(rejected, "0.1.0", 1_000), {
          rotateCurrentToBackup: false,
          limits: permissiveLimits({ hostBytes: 1, globalBytes: 1, hostSessions: 1 }),
          now: 1_000,
        }),
      { code: "HOST_QUOTA" },
    );

    const accepted = binding("codex", "accepted-session");
    assert.doesNotThrow(() =>
      writeEnvelope(temp.directory, accepted, initialEnvelope(accepted, "0.1.0", 2_000), {
        rotateCurrentToBackup: false,
        limits: permissiveLimits({ hostSessions: 1 }),
        now: 2_000,
      }),
    );

    const overLimit = binding("codex", "over-limit-session");
    assert.throws(
      () =>
        writeEnvelope(temp.directory, overLimit, initialEnvelope(overLimit, "0.1.0", 3_000), {
          rotateCurrentToBackup: false,
          limits: permissiveLimits({ hostSessions: 1 }),
          now: 3_000,
        }),
      { code: "SESSION_QUOTA" },
    );
  } finally {
    temp.cleanup();
  }
});
