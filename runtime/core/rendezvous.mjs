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

function roots(dataRoot, host) {
  const root = path.join(dataRoot, "rendezvous", host);
  return {
    root,
    claims: path.join(root, "claims"),
    instances: path.join(root, "instances"),
    bindings: path.join(root, "bindings"),
    active: path.join(root, "active"),
    lock: path.join(root, ".lock"),
  };
}

function initialize(dataRoot, host) {
  const value = roots(dataRoot, host);
  ensurePrivateDirectory(value.root);
  for (const directory of [value.claims, value.instances, value.bindings, value.active]) {
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

function pair(value, host, cwdHash, hostPid, now) {
  prune(value, now);
  const hostInstances = listJson(value.instances)
    .map((file) => ({ file, record: readJsonFile(file) }))
    .filter(({ record }) => record.host === host && record.hostPid === hostPid);
  const hostClaims = listJson(value.claims)
    .map((file) => ({ file, record: readJsonFile(file) }))
    .filter(({ record }) => record.host === host && record.hostPid === hostPid);
  let instances = hostInstances.filter(({ record }) => record.cwdHash === cwdHash);
  let claims = hostClaims.filter(({ record }) => record.cwdHash === cwdHash);
  const hasCwdAgnosticInstance = hostInstances.some(
    ({ record }) => record.allowCwdMismatch === true,
  );

  if (
    (instances.length !== 1 || claims.length !== 1) &&
    hasCwdAgnosticInstance
  ) {
    if (hostInstances.length > 1 || hostClaims.length > 1) {
      return {
        status: "ambiguous",
        instances: hostInstances.length,
        claims: hostClaims.length,
      };
    }
    if (
      hostInstances.length === 1 &&
      hostClaims.length === 1 &&
      hostInstances[0].record.allowCwdMismatch === true
    ) {
      instances = hostInstances;
      claims = hostClaims;
    }
  }
  if (instances.length > 1 || claims.length > 1) {
    return { status: "ambiguous", instances: instances.length, claims: claims.length };
  }
  if (instances.length !== 1 || claims.length !== 1) {
    return { status: "pending", instances: instances.length, claims: claims.length };
  }
  const instance = instances[0];
  const claim = claims[0];
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
    cwdHash: claim.record.cwdHash,
    instanceCwdHash: instance.record.cwdHash,
    sessionKey: claim.record.sessionKey,
  };
  const binding = {
    ...proofPayload,
    pid: instance.record.pid,
    createdAt: now,
    proof: hmac(secret, stableStringify(proofPayload)),
  };
  writeJsonExclusive(path.join(value.bindings, `${instance.record.instanceId}.json`), binding);
  removeIfExists(instance.file);
  removeIfExists(claim.file);
  return { status: "bound", instanceId: instance.record.instanceId };
}

export function claimSession(
  dataRoot,
  { host, cwd, sessionKey, hostPid = process.ppid, now = Date.now() },
) {
  const cwdHash = cwdKey(cwd);
  return withLock(dataRoot, host, (value) => {
    prune(value, now);
    const active = listJson(value.active)
      .map((file) => readJsonFile(file))
      .find(
        (record) =>
          record.host === host &&
          record.hostPid === hostPid &&
          record.cwdHash === cwdHash &&
          record.sessionKey === sessionKey &&
          processIsAlive(record.pid),
      );
    if (active) return { status: "active", instanceId: active.instanceId };

    const existing = listJson(value.claims)
      .map((file) => ({ file, record: readJsonFile(file) }))
      .find(
        ({ record }) =>
          record.host === host &&
          record.hostPid === hostPid &&
          record.cwdHash === cwdHash &&
          record.sessionKey === sessionKey,
      );
    if (!existing) {
      const claimId = randomId(16);
      writeJsonExclusive(path.join(value.claims, `${claimId}.json`), {
        claimId,
        host,
        hostPid,
        cwdHash,
        sessionKey,
        createdAt: now,
      });
    }
    return pair(value, host, cwdHash, hostPid, now);
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
    now = Date.now(),
    allowCwdMismatch = false,
  },
) {
  const cwdHash = cwdKey(cwd);
  const outcome = withLock(dataRoot, host, (value) => {
    prune(value, now);
    writeJsonExclusive(path.join(value.instances, `${instanceId}.json`), {
      instanceId,
      host,
      hostPid,
      cwdHash,
      pid,
      createdAt: now,
      allowCwdMismatch,
    });
    writePrivateFile(path.join(value.instances, `${instanceId}.secret`), capability);
    return pair(value, host, cwdHash, hostPid, now);
  });
  return { instanceId, capability, cwdHash, host, hostPid, pid, allowCwdMismatch, outcome };
}

export function consumeBinding(
  dataRoot,
  registration,
  { now = Date.now() } = {},
) {
  return withLock(dataRoot, registration.host, (value) => {
    const file = path.join(value.bindings, `${registration.instanceId}.json`);
    if (!fs.existsSync(file)) {
      pair(value, registration.host, registration.cwdHash, registration.hostPid, now);
    }
    if (!fs.existsSync(file)) return null;
    const binding = readJsonFile(file);
    const payload = {
      instanceId: binding.instanceId,
      claimId: binding.claimId,
      host: binding.host,
      hostPid: binding.hostPid,
      cwdHash: binding.cwdHash,
      instanceCwdHash: binding.instanceCwdHash,
      sessionKey: binding.sessionKey,
    };
    if (
      binding.instanceId !== registration.instanceId ||
      binding.host !== registration.host ||
      binding.hostPid !== registration.hostPid ||
      binding.instanceCwdHash !== registration.cwdHash ||
      binding.pid !== registration.pid ||
      binding.proof !== hmac(registration.capability, stableStringify(payload))
    ) {
      throw new NovaError("BINDING_REPLAY", "session binding proof is invalid or replayed");
    }
    removeIfExists(file);
    removeIfExists(path.join(value.instances, `${registration.instanceId}.secret`));
    const active = {
      instanceId: registration.instanceId,
      host: binding.host,
      hostPid: binding.hostPid,
      cwdHash: binding.cwdHash,
      sessionKey: binding.sessionKey,
      pid: registration.pid,
      createdAt: now,
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

export function waitForBinding(dataRoot, registration, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() <= deadline) {
    const binding = consumeBinding(dataRoot, registration);
    if (binding) return binding;
    sleepSync(25);
  }
  return null;
}
