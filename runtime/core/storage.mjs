import fs from "node:fs";
import path from "node:path";
import {
  GLOBAL_QUOTA_BYTES,
  HOST_QUOTA_BYTES,
  HOST_SESSION_LIMIT,
  LOCK_TIMEOUT_MS,
  SCHEMA_VERSION,
  SESSION_TTL_MS,
} from "./constants.mjs";
import {
  NovaError,
  canonicalClone,
  ensurePrivateDirectory,
  parseIso,
  sha256,
  sleepSync,
  stableStringify,
  utcIso,
} from "./util.mjs";

function stateDirectory(dataRoot, binding) {
  return path.join(dataRoot, "state", binding.host, binding.sessionKey);
}

function envelopeChecksum(envelope) {
  const copy = { ...envelope };
  delete copy.checksum;
  return sha256(stableStringify(copy));
}

export function sealEnvelope(envelope) {
  const sealed = canonicalClone({ ...envelope, checksum: "" });
  sealed.checksum = envelopeChecksum(sealed);
  return canonicalClone(sealed);
}

export function verifyEnvelope(
  envelope,
  binding,
  now = Date.now(),
  { allowExpired = false } = {},
) {
  if (envelope === null || typeof envelope !== "object" || Array.isArray(envelope)) {
    throw new NovaError("INVALID_ENVELOPE", "checkpoint envelope must be an object");
  }
  if (envelope.schemaVersion !== SCHEMA_VERSION) {
    throw new NovaError("SCHEMA_INCOMPATIBLE", `unsupported schemaVersion ${envelope.schemaVersion}`);
  }
  if (
    envelope.scopeBinding?.host !== binding.host ||
    envelope.scopeBinding?.sessionKey !== binding.sessionKey ||
    envelope.scopeBinding?.cwdHash !== binding.cwdHash
  ) {
    throw new NovaError("SCOPE_MISMATCH", "checkpoint scope does not match current binding");
  }
  if (typeof envelope.checksum !== "string" || envelope.checksum !== envelopeChecksum(envelope)) {
    throw new NovaError("CHECKSUM_MISMATCH", "checkpoint checksum mismatch");
  }
  const lastActivityAt = parseIso(envelope.lastActivityAt, "lastActivityAt");
  const expiresAt = parseIso(envelope.expiresAt, "expiresAt");
  if (!allowExpired && expiresAt <= now) {
    throw new NovaError("CHECKPOINT_EXPIRED", "checkpoint has expired");
  }
  if (
    !Number.isSafeInteger(envelope.authorityGeneration) ||
    envelope.authorityGeneration < 0 ||
    !Number.isSafeInteger(envelope.leaseVersion) ||
    envelope.leaseVersion < 1 ||
    typeof envelope.dirty !== "boolean" ||
    expiresAt <= lastActivityAt
  ) {
    throw new NovaError("INVALID_ENVELOPE", "checkpoint generation, lease, or timestamps are invalid");
  }
  if (
    !Number.isSafeInteger(envelope.eventWatermark) ||
    !Number.isSafeInteger(envelope.coveredEventWatermark) ||
    envelope.eventWatermark < 0 ||
    envelope.coveredEventWatermark < 0 ||
    envelope.coveredEventWatermark > envelope.eventWatermark
  ) {
    throw new NovaError("INVALID_ENVELOPE", "checkpoint watermarks are invalid");
  }
  return envelope;
}

function readCandidate(file, binding, now) {
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8"));
    return { value: verifyEnvelope(value, binding, now), error: null };
  } catch (error) {
    return { value: null, error };
  }
}

export function readEnvelope(dataRoot, binding, { now = Date.now(), allowMissing = false } = {}) {
  const directory = stateDirectory(dataRoot, binding);
  const currentFile = path.join(directory, "current.json");
  const backupFile = path.join(directory, "backup.json");
  if (fs.existsSync(currentFile)) {
    const current = readCandidate(currentFile, binding, now);
    if (current.value) return { envelope: current.value, source: "current", currentValid: true };
    if (fs.existsSync(backupFile)) {
      const backup = readCandidate(backupFile, binding, now);
      if (backup.value) return { envelope: backup.value, source: "backup", currentValid: false };
    }
    throw current.error;
  }
  if (fs.existsSync(backupFile)) {
    const backup = readCandidate(backupFile, binding, now);
    if (backup.value) return { envelope: backup.value, source: "backup", currentValid: false };
    throw backup.error;
  }
  if (allowMissing) return null;
  throw new NovaError("CHECKPOINT_MISSING", "no checkpoint exists for the current session");
}

function tryRemove(file) {
  try {
    fs.unlinkSync(file);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function syncDirectory(directory) {
  if (process.platform === "win32") return;
  const descriptor = fs.openSync(directory, "r");
  try {
    fs.fsyncSync(descriptor);
  } finally {
    fs.closeSync(descriptor);
  }
}

function directorySize(directory) {
  if (!fs.existsSync(directory)) return 0;
  let size = 0;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) size += directorySize(file);
    else if (entry.isFile()) size += fs.statSync(file).size;
  }
  return size;
}

function fileSize(file) {
  try {
    return fs.statSync(file).size;
  } catch (error) {
    if (error?.code === "ENOENT") return 0;
    throw error;
  }
}

function sessionCount(dataRoot, host) {
  const root = path.join(dataRoot, "state", host);
  if (!fs.existsSync(root)) return 0;
  return fs.readdirSync(root, { withFileTypes: true }).filter((entry) => entry.isDirectory()).length;
}

function withQuotaLock(dataRoot, callback) {
  const stateRoot = path.join(dataRoot, "state");
  ensurePrivateDirectory(stateRoot);
  const lock = path.join(stateRoot, ".quota.lock");
  const deadline = Date.now() + LOCK_TIMEOUT_MS;
  while (true) {
    try {
      fs.mkdirSync(lock, { mode: 0o700 });
      break;
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      try {
        if (Date.now() - fs.statSync(lock).mtimeMs > LOCK_TIMEOUT_MS * 5) fs.rmdirSync(lock);
      } catch (statError) {
        if (statError?.code !== "ENOENT" && statError?.code !== "ENOTEMPTY") throw statError;
      }
      if (Date.now() >= deadline) {
        throw new NovaError("QUOTA_LOCK_TIMEOUT", "checkpoint quota lock timed out");
      }
      sleepSync(10);
    }
  }
  try {
    return callback();
  } finally {
    try {
      fs.rmdirSync(lock);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
}

function cleanupSnapshot(directory, expectedBinding) {
  const records = [];
  for (const name of ["current.json", "backup.json"]) {
    const file = path.join(directory, name);
    if (!fs.existsSync(file)) continue;
    try {
      const value = JSON.parse(fs.readFileSync(file, "utf8"));
      const binding = expectedBinding ?? value.scopeBinding;
      if (
        binding === null ||
        typeof binding !== "object" ||
        typeof binding.host !== "string" ||
        typeof binding.sessionKey !== "string" ||
        typeof binding.cwdHash !== "string"
      ) {
        return null;
      }
      verifyEnvelope(value, binding, Number.NEGATIVE_INFINITY, { allowExpired: true });
      records.push({
        name,
        binding,
        leaseVersion: value.leaseVersion,
        expiresAt: parseIso(value.expiresAt, "expiresAt"),
      });
    } catch {
      return null;
    }
  }
  if (records.length === 0) return null;
  const binding = records[0].binding;
  if (
    records.some(
      (record) =>
        record.binding.host !== binding.host ||
        record.binding.sessionKey !== binding.sessionKey ||
        record.binding.cwdHash !== binding.cwdHash,
    )
  ) {
    return null;
  }
  return { binding, records };
}

function sameCleanupSnapshot(left, right) {
  if (!left || !right || left.records.length !== right.records.length) return false;
  return left.records.every((record, index) => {
    const other = right.records[index];
    return (
      record.name === other.name &&
      record.leaseVersion === other.leaseVersion &&
      record.expiresAt === other.expiresAt
    );
  });
}

export function cleanupExpiredScopes(
  dataRoot,
  { now = Date.now(), excludeBinding = null } = {},
) {
  const stateRoot = path.join(dataRoot, "state");
  if (!fs.existsSync(stateRoot)) return { removed: 0, reclaimedBytes: 0 };
  const candidates = [];
  for (const hostEntry of fs.readdirSync(stateRoot, { withFileTypes: true })) {
    if (!hostEntry.isDirectory()) continue;
    const hostRoot = path.join(stateRoot, hostEntry.name);
    for (const scopeEntry of fs.readdirSync(hostRoot, { withFileTypes: true })) {
      if (!scopeEntry.isDirectory()) continue;
      const directory = path.join(hostRoot, scopeEntry.name);
      const snapshot = cleanupSnapshot(directory);
      if (!snapshot) continue;
      const { binding } = snapshot;
      if (binding.host !== hostEntry.name || binding.sessionKey !== scopeEntry.name) continue;
      if (
        excludeBinding &&
        binding.host === excludeBinding.host &&
        binding.sessionKey === excludeBinding.sessionKey
      ) {
        continue;
      }
      if (snapshot.records.every((record) => record.expiresAt <= now)) {
        candidates.push({
          directory,
          snapshot,
          expiresAt: Math.max(...snapshot.records.map((record) => record.expiresAt)),
        });
      }
    }
  }
  candidates.sort((left, right) => left.expiresAt - right.expiresAt);
  let removed = 0;
  let reclaimedBytes = 0;
  for (const candidate of candidates) {
    const beforeBytes = directorySize(candidate.directory);
    let didRemove = false;
    try {
      withScopeLock(dataRoot, candidate.snapshot.binding, () => {
        const current = cleanupSnapshot(candidate.directory, candidate.snapshot.binding);
        if (
          !sameCleanupSnapshot(candidate.snapshot, current) ||
          current.records.some((record) => record.expiresAt > now)
        ) {
          return;
        }
        for (const name of ["current.json", "backup.json"]) {
          tryRemove(path.join(candidate.directory, name));
        }
        for (const entry of fs.readdirSync(candidate.directory, { withFileTypes: true })) {
          if (entry.isFile() && /^\.current\..+\.tmp$/.test(entry.name)) {
            tryRemove(path.join(candidate.directory, entry.name));
          }
        }
        didRemove = true;
      }, 0);
    } catch (error) {
      if (error?.code !== "LOCK_TIMEOUT") throw error;
    }
    if (!didRemove) continue;
    try {
      fs.rmdirSync(candidate.directory);
    } catch (error) {
      if (error?.code !== "ENOENT" && error?.code !== "ENOTEMPTY") throw error;
    }
    removed += 1;
    reclaimedBytes += beforeBytes;
  }
  return { removed, reclaimedBytes };
}

function enforceQuota(dataRoot, binding, newBytes, rotateCurrentToBackup, limits, now) {
  cleanupExpiredScopes(dataRoot, { now, excludeBinding: binding });
  const hostRoot = path.join(dataRoot, "state", binding.host);
  const globalRoot = path.join(dataRoot, "state");
  const scopeDirectory = stateDirectory(dataRoot, binding);
  const currentFile = path.join(scopeDirectory, "current.json");
  const backupFile = path.join(scopeDirectory, "backup.json");
  const currentBytes = fileSize(currentFile);
  const backupBytes = fileSize(backupFile);
  const scopeHasState = currentBytes > 0 || backupBytes > 0;
  if (!scopeHasState && sessionCount(dataRoot, binding.host) > limits.hostSessions) {
    throw new NovaError("SESSION_QUOTA", `host session quota ${limits.hostSessions} reached`);
  }
  const replacedBytes = rotateCurrentToBackup ? backupBytes : currentBytes;
  const projectedDelta = newBytes - replacedBytes;
  if (directorySize(hostRoot) + projectedDelta > limits.hostBytes) {
    throw new NovaError("HOST_QUOTA", `host checkpoint quota ${limits.hostBytes} bytes exceeded`);
  }
  if (directorySize(globalRoot) + projectedDelta > limits.globalBytes) {
    throw new NovaError("GLOBAL_QUOTA", `global checkpoint quota ${limits.globalBytes} bytes exceeded`);
  }
}

export function writeEnvelope(
  dataRoot,
  binding,
  envelope,
  {
    rotateCurrentToBackup = true,
    limits = {
      hostBytes: HOST_QUOTA_BYTES,
      globalBytes: GLOBAL_QUOTA_BYTES,
      hostSessions: HOST_SESSION_LIMIT,
    },
    now = Date.now(),
  } = {},
) {
  const directory = stateDirectory(dataRoot, binding);
  ensurePrivateDirectory(directory);
  const currentFile = path.join(directory, "current.json");
  const backupFile = path.join(directory, "backup.json");
  const temporary = path.join(directory, `.current.${process.pid}.${Date.now()}.tmp`);
  const sealed = sealEnvelope(envelope);
  const serialized = `${stableStringify(sealed)}\n`;
  withQuotaLock(dataRoot, () => {
    enforceQuota(
      dataRoot,
      binding,
      Buffer.byteLength(serialized, "utf8"),
      rotateCurrentToBackup,
      limits,
      now,
    );
    fs.writeFileSync(temporary, serialized, { encoding: "utf8", mode: 0o600, flag: "wx" });
    const descriptor = fs.openSync(temporary, "r");
    try {
      fs.fsyncSync(descriptor);
    } finally {
      fs.closeSync(descriptor);
    }
    try {
      if (fs.existsSync(currentFile) && rotateCurrentToBackup) {
        tryRemove(backupFile);
        fs.renameSync(currentFile, backupFile);
      } else if (fs.existsSync(currentFile)) {
        tryRemove(currentFile);
      }
      fs.renameSync(temporary, currentFile);
      syncDirectory(directory);
    } catch (error) {
      tryRemove(temporary);
      if (!fs.existsSync(currentFile) && fs.existsSync(backupFile)) {
        fs.copyFileSync(backupFile, currentFile, fs.constants.COPYFILE_EXCL);
      }
      throw error;
    }
  });
  return sealed;
}

export function withScopeLock(dataRoot, binding, callback, timeoutMs = LOCK_TIMEOUT_MS) {
  const directory = stateDirectory(dataRoot, binding);
  ensurePrivateDirectory(directory);
  const lock = path.join(directory, ".lock");
  const deadline = Date.now() + timeoutMs;
  const staleAfterMs = Math.max(timeoutMs, LOCK_TIMEOUT_MS) * 5;
  while (true) {
    try {
      fs.mkdirSync(lock, { mode: 0o700 });
      break;
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      try {
        if (Date.now() - fs.statSync(lock).mtimeMs > staleAfterMs) fs.rmdirSync(lock);
      } catch (statError) {
        if (statError?.code !== "ENOENT" && statError?.code !== "ENOTEMPTY") throw statError;
      }
      if (Date.now() >= deadline) {
        throw new NovaError("LOCK_TIMEOUT", "checkpoint scope lock timed out");
      }
      sleepSync(10);
    }
  }
  try {
    return callback();
  } finally {
    try {
      fs.rmdirSync(lock);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
}

function isCoveredAuthority(envelope) {
  return (
    envelope.taskCapsule !== null &&
    envelope.dirty === false &&
    envelope.coveredEventWatermark === envelope.eventWatermark
  );
}

export function initialEnvelope(binding, pluginVersion, now = Date.now()) {
  const timestamp = utcIso(now);
  return {
    schemaVersion: SCHEMA_VERSION,
    pluginVersion,
    scopeBinding: canonicalClone(binding),
    eventWatermark: 0,
    coveredEventWatermark: 0,
    dirty: false,
    authorityGeneration: 0,
    leaseVersion: 1,
    lastActivityAt: timestamp,
    expiresAt: utcIso(now + SESSION_TTL_MS),
    taskCapsule: null,
    controlDocuments: [],
    recentEventIds: [],
    recentWrites: [],
    compactionHandshake: { status: "idle" },
    checksum: "",
  };
}

export function mutateEnvelope(
  dataRoot,
  binding,
  pluginVersion,
  mutator,
  { now = Date.now(), create = true, limits } = {},
) {
  return withScopeLock(dataRoot, binding, () => {
    const loaded = readEnvelope(dataRoot, binding, { now, allowMissing: create });
    const before = loaded?.envelope ?? initialEnvelope(binding, pluginVersion, now);
    const draft = canonicalClone(before);
    const result = mutator(draft, before);
    const envelope = writeEnvelope(dataRoot, binding, draft, {
      rotateCurrentToBackup:
        loaded?.source === "current" && isCoveredAuthority(loaded.envelope),
      limits,
      now,
    });
    return { envelope, result, recoveredFrom: loaded?.source === "backup" ? "backup" : null };
  });
}

export function resetEnvelope(dataRoot, binding, pluginVersion, now = Date.now()) {
  return withScopeLock(dataRoot, binding, () => {
    const directory = stateDirectory(dataRoot, binding);
    tryRemove(path.join(directory, "current.json"));
    tryRemove(path.join(directory, "backup.json"));
    const envelope = writeEnvelope(dataRoot, binding, initialEnvelope(binding, pluginVersion, now), {
      rotateCurrentToBackup: false,
      now,
    });
    return envelope;
  });
}

export function refreshLease(envelope, now = Date.now()) {
  const previous = parseIso(envelope.lastActivityAt, "lastActivityAt");
  const activity = Math.max(previous, now);
  envelope.leaseVersion += 1;
  envelope.lastActivityAt = utcIso(activity);
  envelope.expiresAt = utcIso(activity + SESSION_TTL_MS);
}
