import fs from "node:fs";
import path from "node:path";
import { LOCK_TIMEOUT_MS, SCOPE_PROOF_TTL_MS, STRING_LIMIT } from "./constants.mjs";
import {
  NovaError,
  parseIso,
  randomId,
  readJsonFile,
  stableStringify,
  utcIso,
  withOwnerLock,
  writePrivateFile,
} from "./util.mjs";

const HOSTS = new Set(["codex", "claude-code"]);
const CHECKPOINT_TOOLS = new Set(["nova_checkpoint_get", "nova_checkpoint_save"]);
const DIGEST = /^[a-f0-9]{64}$/;
const PROOF = /^[a-f0-9]{64}$/;

function requireHost(host) {
  if (!HOSTS.has(host)) {
    throw new NovaError("INVALID_SCOPE_PROOF_HOST", "scope proof host is invalid");
  }
}

function requireString(value, label) {
  if (typeof value !== "string" || value.length === 0 || value.length > STRING_LIMIT) {
    throw new NovaError("INVALID_SCOPE_PROOF", `${label} is invalid`);
  }
}

function requireDigest(value, label) {
  if (typeof value !== "string" || !DIGEST.test(value)) {
    throw new NovaError("INVALID_SCOPE_PROOF", `${label} is invalid`);
  }
}

function requireToolName(toolName) {
  if (!CHECKPOINT_TOOLS.has(toolName)) {
    throw new NovaError("INVALID_SCOPE_PROOF_TOOL", "scope proof tool is invalid");
  }
}

function isWithin(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== "..");
}

function createOrInspectDirectory(directory, label, create) {
  let stat;
  try {
    stat = fs.lstatSync(directory);
  } catch (error) {
    if (error?.code !== "ENOENT" || !create) throw error;
    try {
      fs.mkdirSync(directory, { mode: 0o700 });
    } catch (mkdirError) {
      if (mkdirError?.code !== "EEXIST") throw mkdirError;
    }
    stat = fs.lstatSync(directory);
  }
  if (stat.isSymbolicLink() || !stat.isDirectory()) {
    throw new NovaError(
      "SCOPE_PROOF_PATH_UNSAFE",
      `${label} must be a real directory inside NOVA_HOME`,
    );
  }
}

function ensureProofDirectories(dataRoot, host) {
  if (typeof dataRoot !== "string" || !path.isAbsolute(dataRoot)) {
    throw new NovaError("SCOPE_PROOF_PATH_UNSAFE", "NOVA_HOME must be an absolute directory");
  }
  const normalizedRoot = path.normalize(dataRoot);
  const directories = [
    normalizedRoot,
    path.join(normalizedRoot, "rendezvous"),
    path.join(normalizedRoot, "rendezvous", host),
    path.join(normalizedRoot, "rendezvous", host, "proofs"),
  ];
  directories.forEach((directory, index) => {
    createOrInspectDirectory(directory, index === 0 ? "NOVA_HOME" : "scope proof directory", index > 0);
  });
  const realRoot = fs.realpathSync(normalizedRoot);
  const realProofs = fs.realpathSync(directories.at(-1));
  if (!isWithin(realRoot, realProofs)) {
    throw new NovaError(
      "SCOPE_PROOF_PATH_UNSAFE",
      "scope proof directory must remain inside NOVA_HOME",
    );
  }
  for (const directory of directories) {
    try {
      fs.chmodSync(directory, 0o700);
    } catch (error) {
      if (process.platform !== "win32") throw error;
    }
  }
  return {
    hostRoot: directories.at(-2),
    proofs: directories.at(-1),
  };
}

function proofPaths(dataRoot, host) {
  requireHost(host);
  const { hostRoot, proofs } = ensureProofDirectories(dataRoot, host);
  return {
    proofs,
    lock: path.join(hostRoot, ".proofs.lock"),
  };
}

function proofFile(paths, proof) {
  return path.join(paths.proofs, `${proof}.json`);
}

function removeIfExists(file) {
  try {
    fs.unlinkSync(file);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function validRecord(record) {
  return (
    record?.proofVersion === 1 &&
    HOSTS.has(record.host) &&
    DIGEST.test(record.sessionKey) &&
    DIGEST.test(record.cwdHash) &&
    CHECKPOINT_TOOLS.has(record.toolName) &&
    typeof record.toolUseId === "string" &&
    record.toolUseId.length > 0 &&
    record.toolUseId.length <= STRING_LIMIT &&
    typeof record.issuedAt === "string" &&
    typeof record.expiresAt === "string"
  );
}

function pruneProofs(paths, now) {
  for (const entry of fs.readdirSync(paths.proofs, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
    const file = path.join(paths.proofs, entry.name);
    try {
      const record = readJsonFile(file);
      if (!validRecord(record) || parseIso(record.expiresAt, "scopeProof.expiresAt") <= now) {
        removeIfExists(file);
      }
    } catch {
      removeIfExists(file);
    }
  }
}

function withProofLock(dataRoot, host, callback) {
  const paths = proofPaths(dataRoot, host);
  return withOwnerLock(paths.lock, () => callback(paths), {
    timeoutMs: LOCK_TIMEOUT_MS,
    timeoutCode: "SCOPE_PROOF_LOCK_TIMEOUT",
    timeoutMessage: "scope proof lock timed out",
  });
}

export function issueScopeProof(
  dataRoot,
  { host, sessionKey, cwdHash, toolName, toolUseId },
  { now = Date.now() } = {},
) {
  requireHost(host);
  requireDigest(sessionKey, "scopeProof.sessionKey");
  requireDigest(cwdHash, "scopeProof.cwdHash");
  requireToolName(toolName);
  requireString(toolUseId, "scopeProof.toolUseId");
  if (!Number.isFinite(now)) {
    throw new NovaError("INVALID_SCOPE_PROOF_TIME", "scope proof issue time is invalid");
  }
  return withProofLock(dataRoot, host, (paths) => {
    pruneProofs(paths, now);
    const proof = randomId(32);
    const record = {
      proofVersion: 1,
      host,
      sessionKey,
      cwdHash,
      toolName,
      toolUseId,
      issuedAt: utcIso(now),
      expiresAt: utcIso(now + SCOPE_PROOF_TTL_MS),
    };
    writePrivateFile(proofFile(paths, proof), `${stableStringify(record)}\n`);
    return proof;
  });
}

export function consumeScopeProof(
  dataRoot,
  { host, scopeProof, toolName },
  { now = Date.now() } = {},
) {
  requireHost(host);
  requireToolName(toolName);
  if (typeof scopeProof !== "string" || !PROOF.test(scopeProof)) {
    throw new NovaError("SCOPE_PROOF_REQUIRED", "a valid one-time scope proof is required");
  }
  if (!Number.isFinite(now)) {
    throw new NovaError("INVALID_SCOPE_PROOF_TIME", "scope proof consume time is invalid");
  }
  return withProofLock(dataRoot, host, (paths) => {
    const file = proofFile(paths, scopeProof);
    let record;
    try {
      record = readJsonFile(file);
    } catch (error) {
      if (error?.code === "ENOENT") {
        throw new NovaError("SCOPE_PROOF_INVALID", "scope proof is missing or already consumed");
      }
      removeIfExists(file);
      throw new NovaError("SCOPE_PROOF_INVALID", "scope proof record is invalid");
    }
    removeIfExists(file);
    pruneProofs(paths, now);
    if (!validRecord(record)) {
      throw new NovaError("SCOPE_PROOF_INVALID", "scope proof record is invalid");
    }
    const issuedAt = parseIso(record.issuedAt, "scopeProof.issuedAt");
    const expiresAt = parseIso(record.expiresAt, "scopeProof.expiresAt");
    if (issuedAt > now || expiresAt <= now) {
      throw new NovaError("SCOPE_PROOF_EXPIRED", "scope proof is expired or not yet valid");
    }
    if (record.host !== host || record.toolName !== toolName) {
      throw new NovaError("SCOPE_PROOF_MISMATCH", "scope proof does not match this tool call");
    }
    return {
      host: record.host,
      sessionKey: record.sessionKey,
      cwdHash: record.cwdHash,
    };
  });
}
