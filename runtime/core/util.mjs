import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export class NovaError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "NovaError";
    this.code = code;
  }
}

export function isMainModule(moduleUrl, argumentPath) {
  if (!argumentPath) return false;
  const modulePath = fileURLToPath(moduleUrl);
  if (path.resolve(modulePath) === path.resolve(argumentPath)) return true;
  return fs.realpathSync(modulePath) === fs.realpathSync(argumentPath);
}

export function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

export function hmac(secret, value) {
  return crypto.createHmac("sha256", secret).update(value).digest("hex");
}

export function randomId(bytes = 24) {
  return crypto.randomBytes(bytes).toString("hex");
}

export function stableStringify(value) {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  const entries = Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`);
  return `{${entries.join(",")}}`;
}

export function canonicalClone(value) {
  return JSON.parse(stableStringify(value));
}

export function scopeKey(host, sessionId) {
  return sha256(`nova-session-v1\0${host}\0${sessionId}`);
}

export function cwdKey(cwd) {
  return sha256(`nova-cwd-v1\0${path.resolve(cwd)}`);
}

export function utcIso(epochMs) {
  return new Date(epochMs).toISOString();
}

export function parseIso(value, label) {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) {
    throw new NovaError("INVALID_TIMESTAMP", `${label} must be a UTC timestamp`);
  }
  return parsed;
}

export function ensurePrivateDirectory(directory) {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  try {
    fs.chmodSync(directory, 0o700);
  } catch (error) {
    if (process.platform !== "win32") throw error;
  }
}

export function writePrivateFile(file, content) {
  fs.writeFileSync(file, content, { encoding: "utf8", mode: 0o600, flag: "wx" });
  try {
    fs.chmodSync(file, 0o600);
  } catch (error) {
    if (process.platform !== "win32") throw error;
  }
}

export function readJsonFile(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

export function pluginRootFromModule(metaUrl) {
  return path.resolve(path.dirname(fileURLToPath(metaUrl)), "..", "..");
}

export function readPluginVersion(pluginRoot) {
  const value = readJsonFile(path.join(pluginRoot, "package.json")).version;
  if (typeof value !== "string") {
    throw new NovaError("INVALID_PLUGIN_VERSION", "package.json.version is missing");
  }
  return value;
}

export function sleepSync(milliseconds) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
}

export function processIsAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

export function withOwnerLock(
  lockFile,
  callback,
  {
    timeoutMs,
    timeoutCode = "LOCK_TIMEOUT",
    timeoutMessage = "lock timed out",
  },
) {
  ensurePrivateDirectory(path.dirname(lockFile));
  const owner = stableStringify({ pid: process.pid, token: randomId(16) });
  const deadline = Date.now() + timeoutMs;
  while (true) {
    try {
      fs.writeFileSync(lockFile, owner, { encoding: "utf8", mode: 0o600, flag: "wx" });
      break;
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      try {
        const observed = fs.readFileSync(lockFile, "utf8");
        const parsed = JSON.parse(observed);
        if (
          Number.isInteger(parsed.pid) &&
          parsed.pid > 0 &&
          !processIsAlive(parsed.pid) &&
          fs.readFileSync(lockFile, "utf8") === observed
        ) {
          fs.unlinkSync(lockFile);
          continue;
        }
      } catch (lockError) {
        if (lockError?.code === "ENOENT") continue;
      }
      if (Date.now() >= deadline) {
        throw new NovaError(timeoutCode, timeoutMessage);
      }
      sleepSync(10);
    }
  }
  try {
    return callback();
  } finally {
    try {
      if (fs.readFileSync(lockFile, "utf8") !== owner) {
        throw new NovaError("LOCK_OWNERSHIP_LOST", `lock ownership changed: ${lockFile}`);
      }
      fs.unlinkSync(lockFile);
    } catch (error) {
      if (error?.code === "ENOENT") {
        throw new NovaError("LOCK_OWNERSHIP_LOST", `lock ownership disappeared: ${lockFile}`);
      }
      throw error;
    }
  }
}

export function redactError(error) {
  if (error instanceof NovaError) return `${error.code}: ${error.message}`;
  return `INTERNAL_ERROR: ${error instanceof Error ? error.message : String(error)}`;
}
