import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { verifyEnvelope } from "./storage.mjs";
import {
  NovaError,
  ensurePrivateDirectory,
  randomId,
  sha256,
  stableStringify,
  withOwnerLock,
  writePrivateFile,
} from "./util.mjs";

const HOSTS = new Set(["codex", "claude-code"]);
const MIGRATION_VERSION = 1;
const MIGRATION_PENDING_FILE = ".migration-pending.json";

function syncDirectory(directory) {
  if (process.platform === "win32") return;
  const descriptor = fs.openSync(directory, "r");
  try {
    fs.fsyncSync(descriptor);
  } finally {
    fs.closeSync(descriptor);
  }
}

function normalizeAbsolute(value, label) {
  if (typeof value !== "string" || value.length === 0 || !path.isAbsolute(value)) {
    throw new NovaError(
      "NOVA_HOME_INVALID",
      `${label} must be a non-empty absolute path; set NOVA_HOME to a writable absolute path`,
    );
  }
  return path.normalize(value);
}

export function resolveNovaHome(
  environment = process.env,
  { homeDirectory = os.homedir() } = {},
) {
  if (Object.hasOwn(environment, "NOVA_HOME")) {
    return normalizeAbsolute(environment.NOVA_HOME, "NOVA_HOME");
  }
  const home = normalizeAbsolute(homeDirectory, "user home directory");
  return path.join(home, ".nova");
}

export function legacyDataRoots(environment = process.env, host) {
  if (!HOSTS.has(host)) {
    throw new NovaError("HOST_UNAVAILABLE", "host must be codex or claude-code");
  }
  const names =
    host === "codex"
      ? ["NOVA_LEGACY_PLUGIN_DATA", "NOVA_PLUGIN_DATA", "PLUGIN_DATA"]
      : ["NOVA_LEGACY_PLUGIN_DATA", "NOVA_PLUGIN_DATA", "CLAUDE_PLUGIN_DATA"];
  const roots = [];
  for (const name of names) {
    const value = environment[name];
    if (value === undefined || value === "") continue;
    if (!path.isAbsolute(value)) {
      throw new NovaError(
        "LEGACY_DATA_ROOT_INVALID",
        `${name} must be an absolute path when provided: ${value}`,
      );
    }
    const normalized = path.normalize(value);
    if (!roots.includes(normalized)) roots.push(normalized);
  }
  return roots;
}

function rejectDirectorySymlink(directory, label = "state root") {
  try {
    if (fs.lstatSync(directory).isSymbolicLink()) {
      throw new NovaError("STATE_ROOT_SYMLINK", `${label} must not be a symlink: ${directory}`);
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function writeProbe(dataRoot, faultInjector) {
  const temporary = path.join(dataRoot, `.bootstrap.${process.pid}.${randomId(8)}.tmp`);
  const committed = `${temporary}.ready`;
  try {
    faultInjector?.("probe-create");
    const descriptor = fs.openSync(temporary, "wx", 0o600);
    try {
      fs.writeFileSync(descriptor, "nova-state-root-probe\n", "utf8");
      faultInjector?.("probe-sync-file");
      fs.fsyncSync(descriptor);
    } finally {
      fs.closeSync(descriptor);
    }
    faultInjector?.("probe-replace");
    fs.renameSync(temporary, committed);
    faultInjector?.("probe-sync-directory");
    syncDirectory(dataRoot);
    faultInjector?.("probe-delete");
    fs.unlinkSync(committed);
    syncDirectory(dataRoot);
  } finally {
    for (const file of [temporary, committed]) {
      try {
        fs.unlinkSync(file);
      } catch (error) {
        if (error?.code !== "ENOENT") throw error;
      }
    }
  }
}

function bootstrapDirectories(dataRoot, host, faultInjector) {
  rejectDirectorySymlink(dataRoot);
  ensurePrivateDirectory(dataRoot);
  const directories = [
    path.join(dataRoot, "state"),
    path.join(dataRoot, "state", host),
    path.join(dataRoot, "rendezvous"),
    path.join(dataRoot, "rendezvous", host),
    path.join(dataRoot, "migrations"),
    path.join(dataRoot, "migrations", host),
  ];
  for (const directory of directories) {
    rejectDirectorySymlink(directory);
    ensurePrivateDirectory(directory);
  }
  writeProbe(dataRoot, faultInjector);
}

function migrationChecksum(record) {
  const value = { ...record };
  delete value.checksum;
  return sha256(stableStringify(value));
}

function verifyMigrationRecord(record, { host, sourceRoot, dataRoot }) {
  if (
    record === null ||
    typeof record !== "object" ||
    Array.isArray(record) ||
    record.version !== MIGRATION_VERSION ||
    record.host !== host ||
    record.sourceRootHash !== sha256(sourceRoot) ||
    record.targetRootHash !== sha256(dataRoot) ||
    record.state !== "completed" ||
    !Array.isArray(record.scopes) ||
    record.scopes.some((value) => typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) ||
    record.checksum !== migrationChecksum(record)
  ) {
    throw new NovaError("MIGRATION_RECORD_INVALID", `invalid migration record for ${host}`);
  }
  return record;
}

function readValidScope(directory, host, scopeKey, now) {
  const values = new Map();
  let checkpointFiles = 0;
  for (const name of ["current.json", "backup.json"]) {
    const file = path.join(directory, name);
    if (!fs.existsSync(file)) continue;
    checkpointFiles += 1;
    try {
      const envelope = JSON.parse(fs.readFileSync(file, "utf8"));
      const binding = envelope?.scopeBinding;
      if (
        binding?.host !== host ||
        binding?.sessionKey !== scopeKey ||
        typeof binding?.cwdHash !== "string"
      ) {
        throw new NovaError("SCOPE_MISMATCH", "legacy checkpoint path does not match its scope");
      }
      verifyEnvelope(envelope, binding, now);
      values.set(name, envelope);
    } catch {
      // A valid sibling may still be the runtime's recoverable envelope.
    }
  }
  if (checkpointFiles > 0 && values.size === 0) {
    throw new NovaError(
      "LEGACY_CHECKPOINT_INVALID",
      `legacy checkpoint has no valid envelope: ${directory}`,
    );
  }
  return values;
}

function serializedScope(values) {
  return new Map(
    [...values].map(([name, envelope]) => [name, `${stableStringify(envelope)}\n`]),
  );
}

function targetMatches(directory, expected, host, scopeKey, now) {
  if (!fs.existsSync(directory)) return false;
  const actual = readValidScope(directory, host, scopeKey, now);
  const serialized = serializedScope(actual);
  if (serialized.size !== expected.size) return false;
  return [...expected].every(([name, content]) => serialized.get(name) === content);
}

function publishScope(dataRoot, host, scopeKey, sourceHash, files, now, faultInjector) {
  const hostRoot = path.join(dataRoot, "state", host);
  const target = path.join(hostRoot, scopeKey);
  const staging = path.join(hostRoot, `.${scopeKey}.migration.${process.pid}.${randomId(8)}`);
  try {
    ensurePrivateDirectory(staging);
    for (const [name, content] of files) {
      faultInjector?.("migration-write", scopeKey, name);
      const file = path.join(staging, name);
      writePrivateFile(file, content);
      const descriptor = fs.openSync(file, "r+");
      try {
        fs.fsyncSync(descriptor);
      } finally {
        fs.closeSync(descriptor);
      }
    }
    const marker = path.join(staging, MIGRATION_PENDING_FILE);
    writePrivateFile(
      marker,
      `${stableStringify({ version: MIGRATION_VERSION, host, scopeKey, sourceHash })}\n`,
    );
    const markerDescriptor = fs.openSync(marker, "r+");
    try {
      fs.fsyncSync(markerDescriptor);
    } finally {
      fs.closeSync(markerDescriptor);
    }
    syncDirectory(staging);
    if (!targetMatches(staging, files, host, scopeKey, now)) {
      throw new NovaError(
        "MIGRATION_STAGING_INVALID",
        `staged checkpoint verification failed for ${staging}`,
      );
    }
    faultInjector?.("migration-publish", scopeKey);
    fs.renameSync(staging, target);
    syncDirectory(hostRoot);
  } finally {
    fs.rmSync(staging, { recursive: true, force: true });
  }
}

function clearMigrationMarkers(dataRoot, host, sourceHash, scopes, now, faultInjector) {
  for (const scopeKey of scopes) {
    const directory = path.join(dataRoot, "state", host, scopeKey);
    const marker = path.join(directory, MIGRATION_PENDING_FILE);
    try {
      const pending = JSON.parse(fs.readFileSync(marker, "utf8"));
      if (
        pending.version !== MIGRATION_VERSION ||
        pending.host !== host ||
        pending.scopeKey !== scopeKey ||
        pending.sourceHash !== sourceHash ||
        readValidScope(directory, host, scopeKey, now).size === 0
      ) {
        throw new NovaError(
          "MIGRATION_TARGET_INVALID",
          `completed migration target is incomplete or invalid: ${directory}`,
        );
      }
      faultInjector?.("migration-clear", scopeKey);
      fs.unlinkSync(marker);
      syncDirectory(directory);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
}

function writeMigrationRecord(file, record, faultInjector) {
  const temporary = `${file}.${process.pid}.${randomId(8)}.tmp`;
  const sealed = { ...record, checksum: migrationChecksum(record) };
  try {
    faultInjector?.("migration-record");
    writePrivateFile(temporary, `${stableStringify(sealed)}\n`);
    const descriptor = fs.openSync(temporary, "r+");
    try {
      fs.fsyncSync(descriptor);
    } finally {
      fs.closeSync(descriptor);
    }
    fs.renameSync(temporary, file);
    syncDirectory(path.dirname(file));
  } finally {
    try {
      fs.unlinkSync(temporary);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
}

export function migrateLegacyRoot(
  dataRoot,
  host,
  sourceRoot,
  { now = Date.now(), faultInjector } = {},
) {
  if (!HOSTS.has(host)) throw new NovaError("HOST_UNAVAILABLE", "unsupported migration host");
  sourceRoot = normalizeAbsolute(sourceRoot, "legacy plugin data root");
  if (sourceRoot === dataRoot || !fs.existsSync(sourceRoot)) {
    return { status: "skipped", scopes: [] };
  }
  const sourceHostRoot = path.join(sourceRoot, "state", host);
  if (!fs.existsSync(sourceHostRoot)) return { status: "skipped", scopes: [] };

  const migrationRoot = path.join(dataRoot, "migrations", host);
  const sourceHash = sha256(sourceRoot);
  const recordFile = path.join(migrationRoot, `${sourceHash}.json`);
  return withOwnerLock(
    path.join(migrationRoot, ".lock"),
    () => {
      if (fs.existsSync(recordFile)) {
        const record = JSON.parse(fs.readFileSync(recordFile, "utf8"));
        verifyMigrationRecord(record, { host, sourceRoot, dataRoot });
        clearMigrationMarkers(
          dataRoot,
          host,
          sourceHash,
          record.scopes,
          now,
          faultInjector,
        );
        return { status: "completed", scopes: record.scopes, idempotent: true };
      }

      const candidates = [];
      for (const entry of fs.readdirSync(sourceHostRoot, { withFileTypes: true })) {
        if (!entry.isDirectory() || !/^[a-f0-9]{64}$/.test(entry.name)) continue;
        const sourceDirectory = path.join(sourceHostRoot, entry.name);
        const values = readValidScope(sourceDirectory, host, entry.name, now);
        if (values.size === 0) continue;
        const files = serializedScope(values);
        const target = path.join(dataRoot, "state", host, entry.name);
        rejectDirectorySymlink(target, "migration target");
        if (fs.existsSync(target) && !targetMatches(target, files, host, entry.name, now)) {
          throw new NovaError(
            "MIGRATION_TARGET_CONFLICT",
            `different valid checkpoint already exists at ${target}`,
          );
        }
        candidates.push({ scopeKey: entry.name, target, files });
      }

      if (candidates.length === 0) return { status: "skipped", scopes: [] };

      for (const candidate of candidates) {
        if (!fs.existsSync(candidate.target)) {
          publishScope(
            dataRoot,
            host,
            candidate.scopeKey,
            sourceHash,
            candidate.files,
            now,
            faultInjector,
          );
        }
      }
      const scopes = candidates.map((value) => value.scopeKey).sort();
      writeMigrationRecord(
        recordFile,
        {
          version: MIGRATION_VERSION,
          host,
          sourceRootHash: sourceHash,
          targetRootHash: sha256(dataRoot),
          state: "completed",
          scopes,
        },
        faultInjector,
      );
      clearMigrationMarkers(dataRoot, host, sourceHash, scopes, now, faultInjector);
      return { status: "completed", scopes, idempotent: false };
    },
    {
      timeoutMs: 2_000,
      timeoutCode: "MIGRATION_LOCK_TIMEOUT",
      timeoutMessage: `legacy checkpoint migration lock timed out for ${host}`,
    },
  );
}

export function bootstrapStateRoot({
  environment = process.env,
  host,
  dataRoot,
  legacyRoots,
  homeDirectory,
  now = Date.now(),
  faultInjector,
} = {}) {
  if (!HOSTS.has(host)) {
    throw new NovaError("HOST_UNAVAILABLE", "host must be codex or claude-code");
  }
  if (dataRoot === undefined) dataRoot = resolveNovaHome(environment, { homeDirectory });
  if (legacyRoots === undefined) legacyRoots = legacyDataRoots(environment, host);
  dataRoot = normalizeAbsolute(dataRoot, "Nova state root");
  try {
    bootstrapDirectories(dataRoot, host, faultInjector);
    const migrations = [];
    for (const sourceRoot of legacyRoots) {
      if (path.normalize(sourceRoot) === dataRoot) continue;
      migrations.push(
        migrateLegacyRoot(dataRoot, host, sourceRoot, { now, faultInjector }),
      );
    }
    return { dataRoot, migrations };
  } catch (error) {
    if (error?.code === "NOVA_HOME_INVALID" || error?.code === "HOST_UNAVAILABLE") throw error;
    const detail = error instanceof Error ? error.message : String(error);
    throw new NovaError(
      "STATE_ROOT_UNAVAILABLE",
      `Nova state root ${dataRoot} is unavailable: ${detail}; set NOVA_HOME to a writable absolute path`,
    );
  }
}
