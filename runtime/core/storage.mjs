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
  randomId,
  sha256,
  stableStringify,
  utcIso,
  withOwnerLock,
  writePrivateFile,
} from "./util.mjs";

const UNCOVERED_STOP_NOTICE_FILE = ".uncovered-stop-notice.json";
const MIGRATION_PENDING_FILE = ".migration-pending.json";
const STOP_NOTICE_FILE = ".stop-notice.json";

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
  if (fs.existsSync(path.join(directory, MIGRATION_PENDING_FILE))) {
    throw new NovaError(
      "MIGRATION_NOT_COMMITTED",
      "checkpoint scope belongs to an incomplete legacy migration",
    );
  }
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

function transactionFiles(directory) {
  return {
    temporary: path.join(directory, ".current-next.tmp"),
    stagedCurrent: path.join(directory, ".current-old.tmp"),
    stagedBackup: path.join(directory, ".backup-old.tmp"),
  };
}

function recoverStateWrite(directory) {
  const currentFile = path.join(directory, "current.json");
  const backupFile = path.join(directory, "backup.json");
  const { temporary, stagedCurrent, stagedBackup } = transactionFiles(directory);
  let changed = false;

  if (fs.existsSync(stagedCurrent)) {
    if (fs.existsSync(currentFile)) tryRemove(stagedCurrent);
    else fs.renameSync(stagedCurrent, currentFile);
    changed = true;
  }
  if (fs.existsSync(stagedBackup)) {
    if (fs.existsSync(currentFile)) {
      if (fs.existsSync(backupFile)) tryRemove(stagedBackup);
      else fs.renameSync(stagedBackup, backupFile);
    } else if (fs.existsSync(backupFile)) {
      fs.renameSync(backupFile, currentFile);
      fs.renameSync(stagedBackup, backupFile);
    } else {
      fs.renameSync(stagedBackup, backupFile);
    }
    changed = true;
  }
  if (fs.existsSync(temporary)) {
    tryRemove(temporary);
    changed = true;
  }
  if (changed) syncDirectory(directory);
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

function quotaUsageFile(dataRoot) {
  return path.join(dataRoot, "state", ".quota-usage.json");
}

function quotaScopeKey(binding) {
  return `${binding.host}/${binding.sessionKey}`;
}

function isValidQuotaEntry(key, entry) {
  return (
    entry !== null &&
    typeof entry === "object" &&
    !Array.isArray(entry) &&
    (entry.host === "codex" || entry.host === "claude-code") &&
    typeof entry.sessionKey === "string" &&
    /^[a-f0-9]{64}$/.test(entry.sessionKey) &&
    key === quotaScopeKey(entry) &&
    Number.isSafeInteger(entry.bytes) &&
    entry.bytes >= 0 &&
    typeof entry.pending === "boolean"
  );
}

function scopeBytes(dataRoot, binding) {
  const directory = stateDirectory(dataRoot, binding);
  return (
    fileSize(path.join(directory, "current.json")) +
    fileSize(path.join(directory, "backup.json"))
  );
}

function rebuildQuotaUsage(dataRoot, observer) {
  observer?.("rebuild");
  const stateRoot = path.join(dataRoot, "state");
  const usage = { version: 1, scopes: {} };
  if (!fs.existsSync(stateRoot)) return usage;
  for (const hostEntry of fs.readdirSync(stateRoot, { withFileTypes: true })) {
    if (
      !hostEntry.isDirectory() ||
      (hostEntry.name !== "codex" && hostEntry.name !== "claude-code")
    ) {
      continue;
    }
    const hostRoot = path.join(stateRoot, hostEntry.name);
    for (const scopeEntry of fs.readdirSync(hostRoot, { withFileTypes: true })) {
      if (!scopeEntry.isDirectory() || !/^[a-f0-9]{64}$/.test(scopeEntry.name)) continue;
      const binding = { host: hostEntry.name, sessionKey: scopeEntry.name };
      recoverStateWrite(stateDirectory(dataRoot, binding));
      const bytes = scopeBytes(dataRoot, binding);
      if (bytes > 0) {
        usage.scopes[quotaScopeKey(binding)] = {
          host: binding.host,
          sessionKey: binding.sessionKey,
          bytes,
          pending: false,
        };
      }
    }
  }
  return usage;
}

function loadQuotaUsage(dataRoot, observer) {
  let usage;
  try {
    usage = JSON.parse(fs.readFileSync(quotaUsageFile(dataRoot), "utf8"));
    if (
      usage?.version !== 1 ||
      usage.scopes === null ||
      typeof usage.scopes !== "object" ||
      Array.isArray(usage.scopes) ||
      Object.entries(usage.scopes).some(([key, entry]) => !isValidQuotaEntry(key, entry))
    ) {
      throw new NovaError("INVALID_QUOTA_LEDGER", "quota usage ledger is invalid");
    }
  } catch (error) {
    if (
      error?.code !== "ENOENT" &&
      !(error instanceof SyntaxError) &&
      error?.code !== "INVALID_QUOTA_LEDGER"
    ) {
      throw error;
    }
    usage = rebuildQuotaUsage(dataRoot, observer);
  }
  for (const [key, entry] of Object.entries(usage.scopes)) {
    if (!entry?.pending) continue;
    recoverStateWrite(stateDirectory(dataRoot, entry));
    const bytes = scopeBytes(dataRoot, entry);
    if (bytes === 0) delete usage.scopes[key];
    else usage.scopes[key] = { ...entry, bytes, pending: false };
  }
  return usage;
}

function writeQuotaUsage(dataRoot, usage) {
  const stateRoot = path.join(dataRoot, "state");
  ensurePrivateDirectory(stateRoot);
  const file = quotaUsageFile(dataRoot);
  const temporary = path.join(stateRoot, `.quota-usage.${process.pid}.${randomId(8)}.tmp`);
  try {
    const descriptor = fs.openSync(temporary, "wx", 0o600);
    try {
      fs.writeFileSync(descriptor, `${stableStringify(usage)}\n`, "utf8");
      fs.fsyncSync(descriptor);
    } finally {
      fs.closeSync(descriptor);
    }
    fs.renameSync(temporary, file);
    syncDirectory(stateRoot);
  } finally {
    tryRemove(temporary);
  }
}

function quotaTotals(usage) {
  const totals = { globalBytes: 0, hosts: {} };
  for (const entry of Object.values(usage.scopes)) {
    if (!Number.isSafeInteger(entry.bytes) || entry.bytes < 0 || typeof entry.host !== "string") {
      throw new NovaError("INVALID_QUOTA_LEDGER", "quota usage ledger entry is invalid");
    }
    totals.globalBytes += entry.bytes;
    const host = (totals.hosts[entry.host] ??= { bytes: 0, sessions: 0 });
    host.bytes += entry.bytes;
    if (entry.bytes > 0) host.sessions += 1;
  }
  return totals;
}

function withQuotaLock(dataRoot, callback) {
  const stateRoot = path.join(dataRoot, "state");
  ensurePrivateDirectory(stateRoot);
  const lock = path.join(stateRoot, ".quota.lock");
  return withOwnerLock(lock, callback, {
    timeoutMs: LOCK_TIMEOUT_MS,
    timeoutCode: "QUOTA_LOCK_TIMEOUT",
    timeoutMessage: "checkpoint quota lock timed out",
  });
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
      if (fs.existsSync(path.join(directory, MIGRATION_PENDING_FILE))) continue;
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
        if (fs.existsSync(path.join(candidate.directory, MIGRATION_PENDING_FILE))) return;
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
          if (
            entry.isFile() &&
            [".current-next.tmp", ".current-old.tmp", ".backup-old.tmp"].includes(entry.name)
          ) {
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

function quotaProjection(dataRoot, usage, binding, newBytes, rotateCurrentToBackup) {
  const scopeDirectory = stateDirectory(dataRoot, binding);
  const currentFile = path.join(scopeDirectory, "current.json");
  const backupFile = path.join(scopeDirectory, "backup.json");
  const currentBytes = fileSize(currentFile);
  const backupBytes = fileSize(backupFile);
  const key = quotaScopeKey(binding);
  const actualBytes = currentBytes + backupBytes;
  if (actualBytes === 0) delete usage.scopes[key];
  else {
    usage.scopes[key] = {
      host: binding.host,
      sessionKey: binding.sessionKey,
      bytes: actualBytes,
      pending: false,
    };
  }
  const finalBytes = newBytes + (rotateCurrentToBackup ? currentBytes : backupBytes);
  const totals = quotaTotals(usage);
  const host = totals.hosts[binding.host] ?? { bytes: 0, sessions: 0 };
  return {
    key,
    finalBytes,
    projectedHostBytes: host.bytes - actualBytes + finalBytes,
    projectedGlobalBytes: totals.globalBytes - actualBytes + finalBytes,
    projectedHostSessions: host.sessions - (actualBytes > 0 ? 1 : 0) + (finalBytes > 0 ? 1 : 0),
  };
}

function quotaError(projection, limits) {
  if (projection.projectedHostSessions > limits.hostSessions) {
    return new NovaError("SESSION_QUOTA", `host session quota ${limits.hostSessions} reached`);
  }
  if (projection.projectedHostBytes > limits.hostBytes) {
    return new NovaError("HOST_QUOTA", `host checkpoint quota ${limits.hostBytes} bytes exceeded`);
  }
  if (projection.projectedGlobalBytes > limits.globalBytes) {
    return new NovaError("GLOBAL_QUOTA", `global checkpoint quota ${limits.globalBytes} bytes exceeded`);
  }
  return null;
}

function reserveQuota(
  dataRoot,
  binding,
  newBytes,
  rotateCurrentToBackup,
  limits,
  now,
  observer,
) {
  let usage = loadQuotaUsage(dataRoot, observer);
  let projection = quotaProjection(dataRoot, usage, binding, newBytes, rotateCurrentToBackup);
  if (quotaError(projection, limits)) {
    cleanupExpiredScopes(dataRoot, { now, excludeBinding: binding });
    usage = rebuildQuotaUsage(dataRoot, observer);
    projection = quotaProjection(dataRoot, usage, binding, newBytes, rotateCurrentToBackup);
  }
  const error = quotaError(projection, limits);
  if (error) throw error;
  usage.scopes[projection.key] = {
    host: binding.host,
    sessionKey: binding.sessionKey,
    bytes: projection.finalBytes,
    pending: true,
  };
  writeQuotaUsage(dataRoot, usage);
  return { usage, key: projection.key };
}

function settleQuota(dataRoot, reservation, binding) {
  const bytes = scopeBytes(dataRoot, binding);
  if (bytes === 0) delete reservation.usage.scopes[reservation.key];
  else {
    reservation.usage.scopes[reservation.key] = {
      host: binding.host,
      sessionKey: binding.sessionKey,
      bytes,
      pending: false,
    };
  }
  try {
    writeQuotaUsage(dataRoot, reservation.usage);
  } catch {
    // The durable pending reservation is reconciled against actual files by the next writer.
  }
}

function rollbackStateWrite(
  directory,
  { currentFile, backupFile, temporary, stagedCurrent, stagedBackup, installed, promoted },
) {
  try {
    if (installed) tryRemove(currentFile);
    if (promoted && fs.existsSync(backupFile)) fs.renameSync(backupFile, currentFile);
    else if (fs.existsSync(stagedCurrent)) {
      if (fs.existsSync(currentFile)) tryRemove(stagedCurrent);
      else fs.renameSync(stagedCurrent, currentFile);
    }
    if (fs.existsSync(stagedBackup)) fs.renameSync(stagedBackup, backupFile);
    tryRemove(temporary);
    syncDirectory(directory);
  } catch (error) {
    throw new NovaError("ATOMIC_ROLLBACK_FAILED", `checkpoint rollback failed: ${error.message}`);
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
    faultInjector,
    quotaObserver,
  } = {},
) {
  const directory = stateDirectory(dataRoot, binding);
  ensurePrivateDirectory(directory);
  const currentFile = path.join(directory, "current.json");
  const backupFile = path.join(directory, "backup.json");
  const { temporary, stagedCurrent, stagedBackup } = transactionFiles(directory);
  const sealed = sealEnvelope(envelope);
  const serialized = `${stableStringify(sealed)}\n`;
  return withQuotaLock(dataRoot, () => {
    recoverStateWrite(directory);
    const reservation = reserveQuota(
      dataRoot,
      binding,
      Buffer.byteLength(serialized, "utf8"),
      rotateCurrentToBackup,
      limits,
      now,
      quotaObserver,
    );
    const state = {
      currentFile,
      backupFile,
      temporary,
      stagedCurrent,
      stagedBackup,
      installed: false,
      promoted: false,
    };
    try {
      faultInjector?.("write-temp");
      fs.writeFileSync(temporary, serialized, { encoding: "utf8", mode: 0o600, flag: "wx" });
      const descriptor = fs.openSync(temporary, "r+");
      try {
        faultInjector?.("fsync-temp");
        fs.fsyncSync(descriptor);
      } finally {
        fs.closeSync(descriptor);
      }
      if (rotateCurrentToBackup && fs.existsSync(backupFile)) {
        faultInjector?.("stage-backup");
        fs.renameSync(backupFile, stagedBackup);
      }
      if (fs.existsSync(currentFile)) {
        faultInjector?.("stage-current");
        if (rotateCurrentToBackup) {
          fs.renameSync(currentFile, backupFile);
          state.promoted = true;
        } else {
          fs.linkSync(currentFile, stagedCurrent);
          syncDirectory(directory);
        }
      }
      faultInjector?.("install-current");
      fs.renameSync(temporary, currentFile);
      state.installed = true;
      faultInjector?.("fsync-directory");
      syncDirectory(directory);
    } catch (error) {
      let failure = error;
      try {
        rollbackStateWrite(directory, state);
      } catch (rollbackError) {
        failure = rollbackError;
      }
      settleQuota(dataRoot, reservation, binding);
      throw failure;
    }
    for (const file of [stagedCurrent, stagedBackup, temporary]) {
      try {
        tryRemove(file);
      } catch {
        // The authoritative current/backup pair is already committed and directory-synced.
      }
    }
    try {
      syncDirectory(directory);
    } catch {
      // The authoritative current/backup pair was already synced before cleanup.
    }
    settleQuota(dataRoot, reservation, binding);
    return sealed;
  });
}

export function withScopeLock(dataRoot, binding, callback, timeoutMs = LOCK_TIMEOUT_MS) {
  const directory = stateDirectory(dataRoot, binding);
  ensurePrivateDirectory(directory);
  const lock = path.join(directory, ".lock");
  return withOwnerLock(lock, callback, {
    timeoutMs,
    timeoutCode: "LOCK_TIMEOUT",
    timeoutMessage: "checkpoint scope lock timed out",
  });
}

export function claimUncoveredStopNotice(dataRoot, binding, envelope, now = Date.now()) {
  return withScopeLock(dataRoot, binding, () => {
    const directory = stateDirectory(dataRoot, binding);
    const noticeFile = path.join(directory, UNCOVERED_STOP_NOTICE_FILE);
    const fingerprint = {
      authorityGeneration: envelope.authorityGeneration,
      coveredEventWatermark: envelope.coveredEventWatermark,
    };
    try {
      const existing = JSON.parse(fs.readFileSync(noticeFile, "utf8"));
      if (
        existing.authorityGeneration === fingerprint.authorityGeneration &&
        existing.coveredEventWatermark === fingerprint.coveredEventWatermark
      ) {
        return false;
      }
    } catch {
      // A missing or malformed diagnostic notice must not affect checkpoint authority.
    }

    const temporary = path.join(
      directory,
      `.uncovered-stop-notice-${randomId(8)}.tmp`,
    );
    writePrivateFile(
      temporary,
      `${stableStringify({ ...fingerprint, reportedAt: utcIso(now) })}\n`,
    );
    try {
      if (process.platform === "win32") tryRemove(noticeFile);
      fs.renameSync(temporary, noticeFile);
    } finally {
      tryRemove(temporary);
    }
    return true;
  });
}

export function claimStopDiagnostic(dataRoot, binding, error, now = Date.now()) {
  return withScopeLock(dataRoot, binding, () => {
    const directory = stateDirectory(dataRoot, binding);
    const noticeFile = path.join(directory, STOP_NOTICE_FILE);
    const fingerprint = sha256(
      stableStringify({
        code: typeof error?.code === "string" ? error.code : "INTERNAL_ERROR",
        message: error instanceof Error ? error.message : String(error),
      }),
    );
    try {
      const existing = JSON.parse(fs.readFileSync(noticeFile, "utf8"));
      if (existing.fingerprint === fingerprint) return false;
    } catch {
      // Diagnostics are best effort and never affect checkpoint authority.
    }
    const temporary = path.join(directory, `.stop-notice-${randomId(8)}.tmp`);
    writePrivateFile(temporary, `${stableStringify({ fingerprint, reportedAt: utcIso(now) })}\n`);
    try {
      if (process.platform === "win32") tryRemove(noticeFile);
      fs.renameSync(temporary, noticeFile);
    } finally {
      tryRemove(temporary);
    }
    return true;
  });
}

export function clearStopDiagnostics(dataRoot, binding) {
  return withScopeLock(dataRoot, binding, () => {
    const directory = stateDirectory(dataRoot, binding);
    tryRemove(path.join(directory, STOP_NOTICE_FILE));
    tryRemove(path.join(directory, UNCOVERED_STOP_NOTICE_FILE));
  });
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
  { now = Date.now(), create = true, limits, allowBackupMutation = false } = {},
) {
  return withScopeLock(dataRoot, binding, () => {
    const loaded = readEnvelope(dataRoot, binding, { now, allowMissing: create });
    if (loaded?.source === "backup" && loaded.currentValid === false && !allowBackupMutation) {
      throw new NovaError(
        "CHECKPOINT_RECOVERED_FROM_BACKUP",
        "current checkpoint is invalid; backup is preserved but is not current authority",
      );
    }
    const before = loaded?.envelope ?? initialEnvelope(binding, pluginVersion, now);
    const draft = canonicalClone(before);
    if (loaded?.source === "backup" && loaded.currentValid === false) draft.dirty = true;
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
    if (fs.existsSync(path.join(directory, MIGRATION_PENDING_FILE))) {
      throw new NovaError(
        "MIGRATION_NOT_COMMITTED",
        "cannot reset a checkpoint scope while its legacy migration is incomplete",
      );
    }
    tryRemove(path.join(directory, "current.json"));
    tryRemove(path.join(directory, "backup.json"));
    tryRemove(path.join(directory, UNCOVERED_STOP_NOTICE_FILE));
    tryRemove(path.join(directory, STOP_NOTICE_FILE));
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
