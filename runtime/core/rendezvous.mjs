import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import {
  LOCK_TIMEOUT_MS,
  RENDEZVOUS_SETTLE_MS,
  RENDEZVOUS_TTL_MS,
} from "./constants.mjs";
import {
  NovaError,
  cwdKey,
  ensurePrivateDirectory,
  hmac,
  processIsAlive,
  randomId,
  readJsonFile,
  sha256,
  sleepSync,
  stableStringify,
  withOwnerLock,
  writePrivateFile,
} from "./util.mjs";

function hostCommandMatches(host, command) {
  if (typeof command !== "string") return false;
  const normalized = command.toLowerCase().replaceAll("\\", "/");
  if (host === "claude-code" && normalized.includes("@anthropic-ai/claude-code")) return true;
  const expected = host === "claude-code" ? "claude" : "codex";
  const tokens = normalized.match(/"[^"]*"|'[^']*'|\S+/g) || [];
  return tokens.some((token) => {
    const basename = path.posix.basename(token.replace(/^['"]|['"]$/g, ""));
    return basename === expected || basename === `${expected}.exe` || basename === `${expected}.cmd`;
  });
}

function linuxAncestry(startPid) {
  const records = [];
  let pid = startPid;
  for (let depth = 0; depth < 12 && Number.isInteger(pid) && pid > 1; depth += 1) {
    try {
      const stat = fs.readFileSync(`/proc/${pid}/stat`, "utf8");
      const close = stat.lastIndexOf(")");
      const fields = stat.slice(close + 2).split(" ");
      const parentPid = Number(fields[1]);
      const command = fs.readFileSync(`/proc/${pid}/cmdline`).toString("utf8").replaceAll("\0", " ");
      records.push({ pid, parentPid, command });
      pid = parentPid;
    } catch {
      break;
    }
  }
  return records;
}

function posixAncestry(startPid) {
  const result = spawnSync("ps", ["-axo", "pid=,ppid=,command="], {
    encoding: "utf8",
    maxBuffer: 4 * 1024 * 1024,
    timeout: 2_000,
    windowsHide: true,
  });
  if (result.status !== 0) return [];
  const processes = new Map();
  for (const line of result.stdout.split("\n")) {
    const match = line.trim().match(/^(\d+)\s+(\d+)\s+(.*)$/);
    if (match) {
      processes.set(Number(match[1]), {
        pid: Number(match[1]),
        parentPid: Number(match[2]),
        command: match[3],
      });
    }
  }
  const records = [];
  let pid = startPid;
  for (let depth = 0; depth < 12 && processes.has(pid); depth += 1) {
    const record = processes.get(pid);
    records.push(record);
    pid = record.parentPid;
  }
  return records;
}

function windowsAncestry(startPid) {
  const script = [
    `$p=${startPid}`,
    "$rows=@()",
    "for($i=0;$i -lt 12 -and $p -gt 0;$i++){",
    "$x=Get-CimInstance Win32_Process -Filter \"ProcessId=$p\" -ErrorAction SilentlyContinue",
    "if($null -eq $x){break}",
    "$rows+=@{pid=[int]$x.ProcessId;parentPid=[int]$x.ParentProcessId;command=[string]$x.CommandLine}",
    "$p=[int]$x.ParentProcessId",
    "}",
    "$rows|ConvertTo-Json -Compress",
  ].join(";");
  for (const executable of ["powershell.exe", "pwsh.exe"]) {
    const result = spawnSync(
      executable,
      ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
      {
        encoding: "utf8",
        maxBuffer: 1024 * 1024,
        timeout: 4_000,
        windowsHide: true,
      },
    );
    if (result.status !== 0) continue;
    try {
      const payload = JSON.parse(result.stdout || "[]");
      return (Array.isArray(payload) ? payload : [payload]).filter(
        (record) => Number.isInteger(record.pid) && Number.isInteger(record.parentPid),
      );
    } catch {
      // Try the next PowerShell executable.
    }
  }
  return [];
}

export function selectHostProcessId(host, ancestry, fallbackPid) {
  const match = ancestry.find((record) => hostCommandMatches(host, record.command));
  return match?.pid || fallbackPid;
}

export function resolveHostProcessId(
  host,
  { parentPid = process.ppid, platform = process.platform } = {},
) {
  let ancestry = [];
  if (platform === "linux") ancestry = linuxAncestry(parentPid);
  else if (platform === "win32") ancestry = windowsAncestry(parentPid);
  else ancestry = posixAncestry(parentPid);
  return selectHostProcessId(host, ancestry, parentPid);
}

export function resolveHostProcessIdentity(
  hostPid,
  { platform = process.platform } = {},
) {
  if (!Number.isInteger(hostPid) || hostPid <= 0) {
    throw new NovaError("HOST_PROCESS_UNAVAILABLE", "trusted host process id is unavailable");
  }
  let identity;
  if (platform === "linux") {
    try {
      const stat = fs.readFileSync(`/proc/${hostPid}/stat`, "utf8");
      const close = stat.lastIndexOf(")");
      const fields = stat.slice(close + 2).split(" ");
      const startTime = fields[19];
      const executable = fs.readlinkSync(`/proc/${hostPid}/exe`);
      identity = `${hostPid}\0${startTime}\0${executable}`;
    } catch {
      // Report one stable fail-closed error below.
    }
  } else if (platform === "win32") {
    const script = [
      `$x=Get-CimInstance Win32_Process -Filter "ProcessId=${hostPid}" -ErrorAction SilentlyContinue`,
      "if($null -ne $x){@{created=[string]$x.CreationDate;exe=[string]$x.ExecutablePath}|ConvertTo-Json -Compress}",
    ].join(";");
    for (const executable of ["powershell.exe", "pwsh.exe"]) {
      const result = spawnSync(
        executable,
        ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        { encoding: "utf8", timeout: 4_000, windowsHide: true },
      );
      if (result.status === 0 && result.stdout.trim()) {
        identity = `${hostPid}\0${result.stdout.trim()}`;
        break;
      }
    }
  } else {
    const result = spawnSync("ps", ["-p", String(hostPid), "-o", "lstart=", "-o", "command="], {
      encoding: "utf8",
      timeout: 2_000,
      windowsHide: true,
    });
    if (result.status === 0 && result.stdout.trim()) identity = `${hostPid}\0${result.stdout.trim()}`;
  }
  if (!identity) {
    throw new NovaError(
      "HOST_PROCESS_UNAVAILABLE",
      `cannot verify trusted host process identity for pid ${hostPid}`,
    );
  }
  return sha256(identity);
}

function roots(dataRoot, host) {
  const root = path.join(dataRoot, "rendezvous", host);
  return {
    root,
    claims: path.join(root, "claims"),
    instances: path.join(root, "instances"),
    bindings: path.join(root, "bindings"),
    active: path.join(root, "active"),
    owners: path.join(root, "owners"),
    lock: path.join(root, ".lock"),
  };
}

function initialize(dataRoot, host) {
  const value = roots(dataRoot, host);
  ensurePrivateDirectory(value.root);
  for (const directory of [
    value.claims,
    value.instances,
    value.bindings,
    value.active,
    value.owners,
  ]) {
    ensurePrivateDirectory(directory);
  }
  return value;
}

function removeIfExists(file) {
  try {
    fs.unlinkSync(file);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function withLock(dataRoot, host, callback) {
  const value = initialize(dataRoot, host);
  return withOwnerLock(value.lock, () => callback(value), {
    timeoutMs: LOCK_TIMEOUT_MS,
    timeoutCode: "RENDEZVOUS_LOCK_TIMEOUT",
    timeoutMessage: "session rendezvous lock timed out",
  });
}

function listJson(directory) {
  return fs
    .readdirSync(directory, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
    .map((entry) => path.join(directory, entry.name));
}

function rendezvousKey(record) {
  if (typeof record?.host !== "string" || typeof record?.cwdHash !== "string") return null;
  const hostPid = Number.isInteger(record.hostPid) ? record.hostPid : "legacy";
  return `${record.host}\0${hostPid}\0${record.cwdHash}`;
}

function liveInstanceKeys(value) {
  const keys = new Set();
  const cwdAgnosticHostProcesses = new Set();
  for (const file of listJson(value.instances)) {
    try {
      const record = readJsonFile(file);
      const key = rendezvousKey(record);
      if (key && Number.isInteger(record.pid) && processIsAlive(record.pid)) {
        keys.add(key);
        if (record.allowCwdMismatch === true && Number.isInteger(record.hostPid)) {
          cwdAgnosticHostProcesses.add(`${record.host}\0${record.hostPid}`);
        }
      }
    } catch {
      // The main prune pass removes malformed records.
    }
  }
  return { keys, cwdAgnosticHostProcesses };
}

function prune(value, now) {
  const liveInstances = liveInstanceKeys(value);
  for (const directory of [value.claims, value.instances, value.bindings, value.active]) {
    for (const file of listJson(directory)) {
      try {
        const record = readJsonFile(file);
        const alive = Number.isInteger(record.pid) && processIsAlive(record.pid);
        const claimedByLiveInstance =
          directory === value.claims &&
          (liveInstances.keys.has(rendezvousKey(record)) ||
            liveInstances.cwdAgnosticHostProcesses.has(`${record.host}\0${record.hostPid}`));
        const old =
          directory !== value.active &&
          (!Number.isFinite(record.createdAt) || now - record.createdAt > RENDEZVOUS_TTL_MS);
        const dead = Number.isInteger(record.pid) && !alive;
        if ((old && !alive && !claimedByLiveInstance) || dead) {
          removeIfExists(file);
          if (record.instanceId) removeIfExists(path.join(value.instances, `${record.instanceId}.secret`));
        }
      } catch {
        removeIfExists(file);
      }
    }
  }
}

function writeJsonExclusive(file, value) {
  writePrivateFile(file, `${stableStringify(value)}\n`);
}

function replaceJson(file, value) {
  const temporary = `${file}.${process.pid}.${randomId(8)}.tmp`;
  try {
    writeJsonExclusive(temporary, value);
    if (process.platform === "win32") removeIfExists(file);
    fs.renameSync(temporary, file);
  } finally {
    removeIfExists(temporary);
  }
}

function ownerFile(value, hostPid) {
  return path.join(value.owners, `${hostPid}.json`);
}

function revocationFile(value, hostPid, processIdentity) {
  return path.join(value.owners, `${hostPid}.${processIdentity}.revoked.json`);
}

function readOwner(value, hostPid, processIdentity) {
  if (processIdentity) {
    const tombstone = revocationFile(value, hostPid, processIdentity);
    if (fs.existsSync(tombstone)) return readJsonFile(tombstone);
  }
  const file = ownerFile(value, hostPid);
  return fs.existsSync(file) ? readJsonFile(file) : null;
}

function removeHostRecords(value, hostPid) {
  for (const directory of [value.claims, value.instances, value.bindings, value.active]) {
    for (const file of listJson(directory)) {
      const record = readJsonFile(file);
      if (record.hostPid !== hostPid) continue;
      removeIfExists(file);
      if (record.instanceId) {
        removeIfExists(path.join(value.instances, `${record.instanceId}.secret`));
      }
    }
  }
}

function revokeOwner(value, owner, reason, now) {
  const revoked = {
    ...owner,
    status: "revoked",
    revokedAt: now,
    revokeReason: reason,
  };
  const tombstone = revocationFile(value, owner.hostPid, owner.processIdentity);
  if (!fs.existsSync(tombstone)) {
    writeJsonExclusive(tombstone, revoked);
    const descriptor = fs.openSync(tombstone, "r+");
    try {
      fs.fsyncSync(descriptor);
    } finally {
      fs.closeSync(descriptor);
    }
  }
  replaceJson(ownerFile(value, owner.hostPid), revoked);
  for (const directory of [value.bindings, value.active]) {
    for (const file of listJson(directory)) {
      const record = readJsonFile(file);
      if (record.hostPid === owner.hostPid) removeIfExists(file);
    }
  }
  return revoked;
}

function establishOwner(value, { host, hostPid, processIdentity, sessionKey, cwdHash, now }) {
  let owner = readOwner(value, hostPid, processIdentity);
  if (owner && owner.processIdentity !== processIdentity) {
    removeHostRecords(value, hostPid);
    removeIfExists(ownerFile(value, hostPid));
    owner = null;
  }
  if (!owner) {
    owner = {
      ownerToken: randomId(16),
      capability: randomId(32),
      host,
      hostPid,
      processIdentity,
      sessionKey,
      cwdHash,
      status: "active",
      createdAt: now,
    };
    writeJsonExclusive(ownerFile(value, hostPid), owner);
    return owner;
  }
  if (owner.status !== "active") return owner;
  if (
    owner.host !== host ||
    owner.sessionKey !== sessionKey ||
    owner.cwdHash !== cwdHash
  ) {
    return revokeOwner(value, owner, "MULTIPLE_HOST_SESSIONS", now);
  }
  return owner;
}

function pair(value, host, cwdHash, hostPid, processIdentity, now) {
  prune(value, now);
  let owner = readOwner(value, hostPid, processIdentity);
  if (
    !owner ||
    owner.host !== host ||
    owner.processIdentity !== processIdentity ||
    owner.status !== "active"
  ) {
    return { status: owner?.status === "revoked" ? "revoked" : "pending", instances: 0, claims: 0 };
  }
  const hostInstances = listJson(value.instances)
    .map((file) => ({ file, record: readJsonFile(file) }))
    .filter(
      ({ record }) =>
        record.host === host &&
        record.hostPid === hostPid &&
        record.processIdentity === processIdentity,
    );
  const hostClaims = listJson(value.claims)
    .map((file) => ({ file, record: readJsonFile(file) }))
    .filter(
      ({ record }) =>
        record.host === host &&
        record.hostPid === hostPid &&
        record.ownerToken === owner.ownerToken,
    );
  if (hostInstances.length > 1 || hostClaims.length > 1) {
    owner = revokeOwner(value, owner, "AMBIGUOUS_RENDEZVOUS", now);
    return {
      status: owner.status,
      instances: hostInstances.length,
      claims: hostClaims.length,
    };
  }
  if (hostInstances.length !== 1 || hostClaims.length !== 1) {
    return { status: "pending", instances: hostInstances.length, claims: hostClaims.length };
  }
  const instance = hostInstances[0];
  const claim = hostClaims[0];
  const cwdMatches = instance.record.cwdHash === claim.record.cwdHash;
  if (
    claim.record.sessionKey !== owner.sessionKey ||
    claim.record.cwdHash !== owner.cwdHash ||
    (!cwdMatches && instance.record.allowCwdMismatch !== true)
  ) {
    revokeOwner(value, owner, "RENDEZVOUS_SCOPE_MISMATCH", now);
    return { status: "revoked", instances: 1, claims: 1 };
  }
  const newestArrival = Math.max(instance.record.createdAt, claim.record.createdAt);
  if (!Number.isFinite(newestArrival) || now - newestArrival < RENDEZVOUS_SETTLE_MS) {
    return { status: "pending", instances: 1, claims: 1, settling: true };
  }
  const secretFile = path.join(value.instances, `${instance.record.instanceId}.secret`);
  const secret = fs.readFileSync(secretFile, "utf8");
  const proofPayload = {
    instanceId: instance.record.instanceId,
    claimId: claim.record.claimId,
    host,
    hostPid,
    processIdentity,
    ownerToken: owner.ownerToken,
    cwdHash: claim.record.cwdHash,
    instanceCwdHash: instance.record.cwdHash,
    sessionKey: claim.record.sessionKey,
  };
  const binding = {
    ...proofPayload,
    pid: instance.record.pid,
    createdAt: now,
    proof: hmac(`${secret}\0${owner.capability}`, stableStringify(proofPayload)),
  };
  writeJsonExclusive(path.join(value.bindings, `${instance.record.instanceId}.json`), binding);
  removeIfExists(instance.file);
  removeIfExists(claim.file);
  return { status: "bound", instanceId: instance.record.instanceId };
}

export function claimSession(
  dataRoot,
  {
    host,
    cwd,
    sessionKey,
    hostPid = process.ppid,
    hostIdentity,
    now = Date.now(),
  },
) {
  const cwdHash = cwdKey(cwd);
  const processIdentity = hostIdentity || resolveHostProcessIdentity(hostPid);
  return withLock(dataRoot, host, (value) => {
    prune(value, now);
    const owner = establishOwner(value, {
      host,
      hostPid,
      processIdentity,
      sessionKey,
      cwdHash,
      now,
    });
    if (owner.status !== "active") {
      return { status: "revoked", instances: 0, claims: 0 };
    }
    const activeRecords = listJson(value.active)
      .map((file) => readJsonFile(file))
      .filter(
        (record) =>
          record.host === host && record.hostPid === hostPid && processIsAlive(record.pid),
      );
    const active = activeRecords.find(
        (record) =>
          record.ownerToken === owner.ownerToken &&
          record.cwdHash === cwdHash &&
          record.sessionKey === sessionKey,
      );
    if (active) return { status: "active", instanceId: active.instanceId };
    if (activeRecords.length > 0) {
      revokeOwner(value, owner, "MULTIPLE_ACTIVE_BINDINGS", now);
      return { status: "revoked", instances: activeRecords.length, claims: 0 };
    }

    const existing = listJson(value.claims)
      .map((file) => ({ file, record: readJsonFile(file) }))
      .find(
        ({ record }) =>
          record.host === host &&
          record.hostPid === hostPid &&
          record.ownerToken === owner.ownerToken &&
          record.cwdHash === cwdHash &&
          record.sessionKey === sessionKey,
      );
    if (!existing) {
      const claimId = randomId(16);
      writeJsonExclusive(path.join(value.claims, `${claimId}.json`), {
        claimId,
        ownerToken: owner.ownerToken,
        host,
        hostPid,
        processIdentity,
        cwdHash,
        sessionKey,
        createdAt: now,
      });
    }
    return pair(value, host, cwdHash, hostPid, processIdentity, now);
  });
}

export function registerMcpInstance(
  dataRoot,
  {
    host,
    cwd,
    instanceId = randomId(16),
    capability = randomId(32),
    pid = process.pid,
    hostPid = process.ppid,
    hostIdentity,
    now = Date.now(),
    allowCwdMismatch = false,
  },
) {
  const cwdHash = cwdKey(cwd);
  const processIdentity = hostIdentity || resolveHostProcessIdentity(hostPid);
  const outcome = withLock(dataRoot, host, (value) => {
    prune(value, now);
    let owner = readOwner(value, hostPid, processIdentity);
    if (owner && owner.processIdentity !== processIdentity) {
      removeHostRecords(value, hostPid);
      removeIfExists(ownerFile(value, hostPid));
      owner = null;
    }
    const liveInstances = listJson(value.instances)
      .map((file) => readJsonFile(file))
      .filter(
        (record) =>
          record.hostPid === hostPid &&
          record.processIdentity === processIdentity &&
          processIsAlive(record.pid),
      );
    const activeBindings = listJson(value.active)
      .map((file) => readJsonFile(file))
      .filter(
        (record) =>
          record.hostPid === hostPid && record.processIdentity === processIdentity,
      );
    if (liveInstances.length > 0 || activeBindings.length > 0) {
      if (!owner) {
        owner = {
          ownerToken: randomId(16),
          capability: randomId(32),
          host,
          hostPid,
          processIdentity,
          sessionKey: null,
          cwdHash: null,
          status: "revoked",
          createdAt: now,
          revokedAt: now,
          revokeReason: "MULTIPLE_MCP_INSTANCES",
        };
        writeJsonExclusive(ownerFile(value, hostPid), owner);
      } else if (owner.status === "active") {
        revokeOwner(value, owner, "MULTIPLE_MCP_INSTANCES", now);
      }
      return { status: "revoked", instances: liveInstances.length + 1, claims: 0 };
    }
    if (owner?.status === "revoked") {
      return { status: "revoked", instances: 0, claims: 0 };
    }
    writeJsonExclusive(path.join(value.instances, `${instanceId}.json`), {
      instanceId,
      host,
      hostPid,
      processIdentity,
      cwdHash,
      pid,
      createdAt: now,
      allowCwdMismatch,
    });
    writePrivateFile(path.join(value.instances, `${instanceId}.secret`), capability);
    return pair(value, host, cwdHash, hostPid, processIdentity, now);
  });
  return {
    instanceId,
    capability,
    cwdHash,
    host,
    hostPid,
    processIdentity,
    pid,
    allowCwdMismatch,
    outcome,
  };
}

export function consumeBinding(
  dataRoot,
  registration,
  { now = Date.now() } = {},
) {
  return withLock(dataRoot, registration.host, (value) => {
    const file = path.join(value.bindings, `${registration.instanceId}.json`);
    if (!fs.existsSync(file)) {
      pair(
        value,
        registration.host,
        registration.cwdHash,
        registration.hostPid,
        registration.processIdentity,
        now,
      );
    }
    if (!fs.existsSync(file)) return null;
    const binding = readJsonFile(file);
    const owner = readOwner(value, registration.hostPid, registration.processIdentity);
    const payload = {
      instanceId: binding.instanceId,
      claimId: binding.claimId,
      host: binding.host,
      hostPid: binding.hostPid,
      processIdentity: binding.processIdentity,
      ownerToken: binding.ownerToken,
      cwdHash: binding.cwdHash,
      instanceCwdHash: binding.instanceCwdHash,
      sessionKey: binding.sessionKey,
    };
    if (
      binding.instanceId !== registration.instanceId ||
      binding.host !== registration.host ||
      binding.hostPid !== registration.hostPid ||
      binding.processIdentity !== registration.processIdentity ||
      binding.instanceCwdHash !== registration.cwdHash ||
      binding.pid !== registration.pid ||
      !owner ||
      owner.status !== "active" ||
      owner.ownerToken !== binding.ownerToken ||
      owner.sessionKey !== binding.sessionKey ||
      binding.proof !==
        hmac(`${registration.capability}\0${owner.capability}`, stableStringify(payload))
    ) {
      throw new NovaError("BINDING_REPLAY", "session binding proof is invalid or replayed");
    }
    removeIfExists(file);
    removeIfExists(path.join(value.instances, `${registration.instanceId}.secret`));
    const activePayload = {
      instanceId: registration.instanceId,
      host: binding.host,
      hostPid: binding.hostPid,
      processIdentity: binding.processIdentity,
      ownerToken: binding.ownerToken,
      cwdHash: binding.cwdHash,
      instanceCwdHash: binding.instanceCwdHash,
      sessionKey: binding.sessionKey,
      pid: registration.pid,
    };
    const active = {
      ...activePayload,
      createdAt: now,
      proof: hmac(owner.capability, stableStringify(activePayload)),
    };
    const activeFile = path.join(value.active, `${registration.instanceId}.json`);
    removeIfExists(activeFile);
    writeJsonExclusive(activeFile, active);
    return {
      host: binding.host,
      cwdHash: binding.cwdHash,
      sessionKey: binding.sessionKey,
    };
  });
}

export function validateActiveBinding(
  dataRoot,
  registration,
  binding,
  { hostIdentity } = {},
) {
  const currentProcessIdentity =
    hostIdentity || resolveHostProcessIdentity(registration.hostPid);
  return withLock(dataRoot, registration.host, (value) => {
    const owner = readOwner(value, registration.hostPid, currentProcessIdentity);
    const activeFile = path.join(value.active, `${registration.instanceId}.json`);
    const active = fs.existsSync(activeFile) ? readJsonFile(activeFile) : null;
    const activePayload = active
      ? {
          instanceId: active.instanceId,
          host: active.host,
          hostPid: active.hostPid,
          processIdentity: active.processIdentity,
          ownerToken: active.ownerToken,
          cwdHash: active.cwdHash,
          instanceCwdHash: active.instanceCwdHash,
          sessionKey: active.sessionKey,
          pid: active.pid,
        }
      : null;
    if (
      !owner ||
      owner.status !== "active" ||
      currentProcessIdentity !== registration.processIdentity ||
      owner.processIdentity !== registration.processIdentity ||
      owner.host !== registration.host ||
      owner.hostPid !== registration.hostPid ||
      owner.sessionKey !== binding.sessionKey ||
      owner.cwdHash !== binding.cwdHash ||
      !active ||
      active.instanceId !== registration.instanceId ||
      active.host !== registration.host ||
      active.hostPid !== registration.hostPid ||
      active.ownerToken !== owner.ownerToken ||
      active.processIdentity !== registration.processIdentity ||
      active.cwdHash !== binding.cwdHash ||
      active.instanceCwdHash !== registration.cwdHash ||
      active.sessionKey !== binding.sessionKey ||
      active.pid !== registration.pid ||
      active.proof !== hmac(owner.capability, stableStringify(activePayload)) ||
      !processIsAlive(registration.pid)
    ) {
      throw new NovaError(
        "BINDING_REVOKED",
        "MCP binding is no longer owned by one trusted host session",
      );
    }
    return true;
  });
}

export function waitForBinding(dataRoot, registration, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() <= deadline) {
    const binding = consumeBinding(dataRoot, registration);
    if (binding) return binding;
    sleepSync(25);
  }
  return null;
}
