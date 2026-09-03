import { validateSaveInput, validateTaskCapsule } from "./schema.mjs";
import {
  mutateEnvelope,
  readEnvelope,
  refreshLease,
  resetEnvelope,
} from "./storage.mjs";
import { NovaError, canonicalClone, randomId, sha256, stableStringify, utcIso } from "./util.mjs";

const MAX_RECENT_IDS = 128;

function remember(values, value) {
  const next = values.filter((entry) => entry !== value);
  next.push(value);
  return next.slice(-MAX_RECENT_IDS);
}

export function startSession(
  dataRoot,
  binding,
  pluginVersion,
  source,
  { now = Date.now() } = {},
) {
  if (source === "clear") {
    return { envelope: resetEnvelope(dataRoot, binding, pluginVersion, now), reset: true };
  }
  const result = mutateEnvelope(
    dataRoot,
    binding,
    pluginVersion,
    (draft, before) => {
      if (before.leaseVersion > 0) refreshLease(draft, now);
      draft.pluginVersion = pluginVersion;
    },
    { now, create: true },
  );
  return { ...result, reset: false };
}

export function markEvent(
  dataRoot,
  binding,
  pluginVersion,
  eventId,
  { now = Date.now() } = {},
) {
  if (typeof eventId !== "string" || eventId.length === 0) {
    throw new NovaError("INVALID_EVENT_ID", "trusted hook event id is required");
  }
  return mutateEnvelope(
    dataRoot,
    binding,
    pluginVersion,
    (draft) => {
      if (draft.recentEventIds.includes(eventId)) return { duplicate: true };
      draft.eventWatermark += 1;
      draft.dirty = true;
      draft.recentEventIds = remember(draft.recentEventIds, eventId);
      return { duplicate: false, eventWatermark: draft.eventWatermark };
    },
    { now, create: true },
  );
}

export function saveCheckpoint(
  dataRoot,
  binding,
  pluginVersion,
  input,
  { now = Date.now(), limits } = {},
) {
  const normalized = validateSaveInput(input);
  const payloadHash = sha256(stableStringify(normalized));
  return mutateEnvelope(
    dataRoot,
    binding,
    pluginVersion,
    (draft) => {
      const existing = draft.recentWrites.find((entry) => entry.idempotencyKey === normalized.idempotencyKey);
      if (existing) {
        if (
          existing.payloadHash !== payloadHash ||
          existing.coveredEventWatermark !== normalized.coveredEventWatermark
        ) {
          throw new NovaError("IDEMPOTENCY_CONFLICT", "idempotencyKey was already used for different content");
        }
        return { idempotent: true, authorityGeneration: existing.authorityGeneration };
      }
      if (normalized.coveredEventWatermark !== draft.eventWatermark) {
        const relation = normalized.coveredEventWatermark < draft.eventWatermark ? "stale" : "future";
        throw new NovaError(
          "WATERMARK_MISMATCH",
          `${relation} coveredEventWatermark ${normalized.coveredEventWatermark}; current is ${draft.eventWatermark}`,
        );
      }
      const capsuleChanged = stableStringify(draft.taskCapsule) !== stableStringify(normalized.taskCapsule);
      if (capsuleChanged) draft.authorityGeneration += 1;
      draft.pluginVersion = pluginVersion;
      draft.taskCapsule = canonicalClone(normalized.taskCapsule);
      draft.controlDocuments = canonicalClone(normalized.controlDocuments);
      draft.coveredEventWatermark = normalized.coveredEventWatermark;
      draft.dirty = false;
      refreshLease(draft, now);
      draft.recentWrites.push({
        idempotencyKey: normalized.idempotencyKey,
        payloadHash,
        coveredEventWatermark: normalized.coveredEventWatermark,
        authorityGeneration: draft.authorityGeneration,
      });
      draft.recentWrites = draft.recentWrites.slice(-MAX_RECENT_IDS);
      return { idempotent: false, authorityGeneration: draft.authorityGeneration };
    },
    { now, create: false, limits },
  );
}

export function getCheckpoint(dataRoot, binding, { now = Date.now() } = {}) {
  const loaded = readEnvelope(dataRoot, binding, { now, allowMissing: false });
  if (loaded.envelope.taskCapsule !== null) validateTaskCapsule(loaded.envelope.taskCapsule);
  return loaded;
}

export function assertCovered(envelope) {
  if (
    envelope.dirty ||
    envelope.taskCapsule === null ||
    envelope.coveredEventWatermark !== envelope.eventWatermark
  ) {
    throw new NovaError(
      "CHECKPOINT_NOT_COVERED",
      `checkpoint does not cover current event watermark ${envelope.eventWatermark}`,
    );
  }
}

export function freezeCompaction(
  dataRoot,
  binding,
  pluginVersion,
  trigger,
  { now = Date.now() } = {},
) {
  return mutateEnvelope(
    dataRoot,
    binding,
    pluginVersion,
    (draft) => {
      assertCovered(draft);
      const current = draft.compactionHandshake;
      if (
        current.status === "frozen" &&
        current.frozenGeneration === draft.authorityGeneration &&
        current.frozenWatermark === draft.eventWatermark &&
        current.trigger === trigger
      ) {
        return { attemptId: current.attemptId, idempotent: true };
      }
      const attemptId = randomId(16);
      draft.compactionHandshake = {
        status: "frozen",
        attemptId,
        trigger,
        frozenGeneration: draft.authorityGeneration,
        frozenWatermark: draft.eventWatermark,
        frozenAt: utcIso(now),
      };
      return { attemptId, idempotent: false };
    },
    { now, create: false },
  );
}

export function completeCompaction(
  dataRoot,
  binding,
  pluginVersion,
  trigger,
  { now = Date.now() } = {},
) {
  const outcome = mutateEnvelope(
    dataRoot,
    binding,
    pluginVersion,
    (draft) => {
      const handshake = draft.compactionHandshake;
      if (handshake.status === "completed" && handshake.trigger === trigger) {
        return { attemptId: handshake.attemptId, idempotent: true };
      }
      if (
        handshake.status !== "frozen" ||
        handshake.trigger !== trigger ||
        handshake.frozenGeneration !== draft.authorityGeneration ||
        handshake.frozenWatermark !== draft.eventWatermark
      ) {
        draft.compactionHandshake = {
          status: "failed",
          failureCode: "COMPACTION_HANDSHAKE_MISMATCH",
          failedAt: utcIso(now),
        };
        return { failed: true };
      }
      draft.compactionHandshake = {
        ...handshake,
        status: "completed",
        completedGeneration: draft.authorityGeneration,
        completedWatermark: draft.eventWatermark,
        completedAt: utcIso(now),
      };
      return { attemptId: handshake.attemptId, idempotent: false };
    },
    { now, create: false },
  );
  if (outcome.result?.failed) {
    throw new NovaError("COMPACTION_HANDSHAKE_MISMATCH", "PostCompact does not match a frozen checkpoint");
  }
  return outcome;
}

export function recordResumeInjection(
  dataRoot,
  binding,
  pluginVersion,
  { now = Date.now() } = {},
) {
  return mutateEnvelope(
    dataRoot,
    binding,
    pluginVersion,
    (draft) => {
      assertCovered(draft);
      draft.resumeInjection = {
        injectedGeneration: draft.authorityGeneration,
        injectedAt: utcIso(now),
      };
      refreshLease(draft, now);
      return { authorityGeneration: draft.authorityGeneration };
    },
    { now, create: false },
  );
}

export function recordInjectedCompaction(
  dataRoot,
  binding,
  pluginVersion,
  { now = Date.now() } = {},
) {
  return mutateEnvelope(
    dataRoot,
    binding,
    pluginVersion,
    (draft) => {
      assertCovered(draft);
      const handshake = draft.compactionHandshake;
      if (
        handshake.status !== "completed" ||
        handshake.completedGeneration !== draft.authorityGeneration ||
        handshake.completedWatermark !== draft.eventWatermark
      ) {
        throw new NovaError("COMPACTION_HANDSHAKE_MISMATCH", "SessionStart(compact) has no matching completed checkpoint");
      }
      draft.compactionHandshake = {
        ...handshake,
        status: "injected",
        injectedGeneration: draft.authorityGeneration,
        injectedAt: utcIso(now),
      };
      refreshLease(draft, now);
      return { authorityGeneration: draft.authorityGeneration };
    },
    { now, create: false },
  );
}
