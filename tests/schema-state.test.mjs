import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { validateSaveInput } from "../runtime/core/schema.mjs";
import { CHECKPOINT_PAYLOAD_LIMIT, SESSION_TTL_MS } from "../runtime/core/constants.mjs";
import {
  completeCompaction,
  freezeCompaction,
  getCheckpoint,
  markEvent,
  recordInjectedCompaction,
  saveCheckpoint,
  startSession,
} from "../runtime/core/state-machine.mjs";
import { sealEnvelope } from "../runtime/core/storage.mjs";
import { binding, capsule, pluginRoot, saveInput, temporaryDirectory } from "./helpers.mjs";

test("checkpoint schema requires the complete five-field stage projection", () => {
  const input = saveInput(0);
  delete input.taskCapsule.stageProjection.resolutionBasis;
  assert.throws(() => validateSaveInput(input), /missing=resolutionBasis/);
});

test("checkpoint schema rejects secrets and unknown authority", () => {
  const secret = saveInput(0);
  secret.taskCapsule.nextAction.value = "Bearer abcdefghijklmnopqrstuvwxyz";
  assert.throws(() => validateSaveInput(secret), { code: "SECRET_DETECTED" });

  const authority = saveInput(0);
  authority.taskCapsule.stage.authorityState = "assumed";
  assert.throws(() => validateSaveInput(authority), { code: "INVALID_AUTHORITY" });
});

test("checkpoint schema rejects a normalized payload over the capacity limit", () => {
  const oversized = saveInput(0);
  oversized.taskCapsule.evidence = Array.from({ length: 40 }, (_, index) => ({
    value: `${index}:`.padEnd(8_192, "x"),
    authorityState: "verified-evidence",
    source: "capacity-test",
  }));
  assert.equal(Buffer.byteLength(JSON.stringify(oversized), "utf8") > CHECKPOINT_PAYLOAD_LIMIT, true);
  assert.throws(() => validateSaveInput(oversized), { code: "PAYLOAD_LIMIT" });
});

test("expired checkpoints fail closed before recovery", () => {
  const temp = temporaryDirectory();
  try {
    const current = binding("codex", "expired-read");
    startSession(temp.directory, current, "0.1.0", "startup", { now: 0 });
    assert.throws(
      () => getCheckpoint(temp.directory, current, { now: SESSION_TTL_MS + 1 }),
      { code: "CHECKPOINT_EXPIRED" },
    );
  } finally {
    temp.cleanup();
  }
});

test("watermarks, idempotency, authority generation, and dirty state are monotonic", () => {
  const temp = temporaryDirectory();
  try {
    const current = binding();
    startSession(temp.directory, current, "0.1.0", "startup", { now: 1_000 });
    markEvent(temp.directory, current, "0.1.0", "prompt:1", { now: 2_000 });
    const first = saveCheckpoint(temp.directory, current, "0.1.0", saveInput(1), { now: 3_000 });
    assert.equal(first.envelope.authorityGeneration, 1);
    assert.equal(first.envelope.dirty, false);
    const duplicate = saveCheckpoint(temp.directory, current, "0.1.0", saveInput(1), { now: 4_000 });
    assert.equal(duplicate.result.idempotent, true);
    assert.equal(duplicate.envelope.authorityGeneration, 1);

    markEvent(temp.directory, current, "0.1.0", "prompt:2", { now: 5_000 });
    assert.throws(
      () =>
        saveCheckpoint(
          temp.directory,
          current,
          "0.1.0",
          saveInput(1, { idempotencyKey: "stale" }),
          { now: 5_500 },
        ),
      { code: "WATERMARK_MISMATCH" },
    );
    const sameCapsule = saveInput(2, { idempotencyKey: "same-capsule" });
    const second = saveCheckpoint(temp.directory, current, "0.1.0", sameCapsule, { now: 6_000 });
    assert.equal(second.envelope.authorityGeneration, 1);

    markEvent(temp.directory, current, "0.1.0", "prompt:3", { now: 7_000 });
    const changed = saveInput(3, {
      idempotencyKey: "changed",
      taskCapsule: capsule({ nextAction: { value: "Commit", authorityState: "user-confirmed", source: "user" } }),
    });
    const third = saveCheckpoint(temp.directory, current, "0.1.0", changed, { now: 8_000 });
    assert.equal(third.envelope.authorityGeneration, 2);
  } finally {
    temp.cleanup();
  }
});

test("corrupt current state falls back only to the previous valid backup", () => {
  const temp = temporaryDirectory();
  try {
    const current = binding();
    startSession(temp.directory, current, "0.1.0", "startup", { now: 1_000 });
    markEvent(temp.directory, current, "0.1.0", "prompt:1", { now: 2_000 });
    saveCheckpoint(temp.directory, current, "0.1.0", saveInput(1), { now: 3_000 });
    markEvent(temp.directory, current, "0.1.0", "prompt:2", { now: 4_000 });
    const directory = path.join(temp.directory, "state", current.host, current.sessionKey);
    fs.writeFileSync(path.join(directory, "current.json"), "corrupt\n", "utf8");
    const recovered = getCheckpoint(temp.directory, current, { now: 5_000 });
    assert.equal(recovered.source, "backup");
    assert.equal(recovered.envelope.eventWatermark, 1);
    assert.equal(recovered.envelope.dirty, false);
  } finally {
    temp.cleanup();
  }
});

test("compaction handshake rejects mismatches and accepts one complete generation", () => {
  const temp = temporaryDirectory();
  try {
    const current = binding();
    startSession(temp.directory, current, "0.1.0", "startup", { now: 1_000 });
    markEvent(temp.directory, current, "0.1.0", "prompt:1", { now: 2_000 });
    saveCheckpoint(temp.directory, current, "0.1.0", saveInput(1), { now: 3_000 });
    freezeCompaction(temp.directory, current, "0.1.0", "manual", { now: 4_000 });
    completeCompaction(temp.directory, current, "0.1.0", "manual", { now: 5_000 });
    const injected = recordInjectedCompaction(temp.directory, current, "0.1.0", { now: 6_000 });
    assert.equal(injected.envelope.compactionHandshake.status, "injected");
    assert.equal(injected.envelope.compactionHandshake.injectedGeneration, 1);
  } finally {
    temp.cleanup();
  }
});

test("control document changes advance authority and invalidate a frozen compaction", () => {
  const temp = temporaryDirectory();
  try {
    const current = binding();
    startSession(temp.directory, current, "0.1.0", "startup", { now: 1_000 });
    markEvent(temp.directory, current, "0.1.0", "prompt:1", { now: 2_000 });
    saveCheckpoint(temp.directory, current, "0.1.0", saveInput(1), { now: 3_000 });
    freezeCompaction(temp.directory, current, "0.1.0", "manual", { now: 4_000 });

    const changedDocuments = saveInput(1, {
      idempotencyKey: "changed-control-documents",
      controlDocuments: [
        {
          path: path.join(pluginRoot, "codex", "AGENTS.global.md"),
          sha256: "b".repeat(64),
          loadState: "needs-reload",
        },
      ],
    });
    const changed = saveCheckpoint(
      temp.directory,
      current,
      "0.1.0",
      changedDocuments,
      { now: 5_000 },
    );
    assert.equal(changed.envelope.authorityGeneration, 2);
    assert.throws(
      () => completeCompaction(temp.directory, current, "0.1.0", "manual", { now: 6_000 }),
      { code: "COMPACTION_HANDSHAKE_MISMATCH" },
    );
  } finally {
    temp.cleanup();
  }
});

test("envelope checksum covers lease and handshake fields", () => {
  const sealed = sealEnvelope({
    schemaVersion: 1,
    scopeBinding: { host: "codex", sessionKey: "a", cwdHash: "b" },
    expiresAt: new Date(Date.now() + 1_000).toISOString(),
    eventWatermark: 0,
    coveredEventWatermark: 0,
    checksum: "",
  });
  const original = sealed.checksum;
  sealed.expiresAt = new Date(Date.now() + 2_000).toISOString();
  assert.notEqual(sealEnvelope(sealed).checksum, original);
});
