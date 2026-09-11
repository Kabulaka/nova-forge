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
  return `${record.host}\0${record.cwdHash}`;
}

function liveInstanceKeys(value) {
  const keys = new Set();
  const cwdAgnosticHosts = new Set();
  for (const file of listJson(value.instances)) {
    try {
      const record = readJsonFile(file);
      const key = rendezvousKey(record);
      if (key && Number.isInteger(record.pid) && processIsAlive(record.pid)) {
        keys.add(key);
        if (record.allowCwdMismatch === true) cwdAgnosticHosts.add(record.host);
      }
    } catch {
      // The main prune pass removes malformed records.
    }
  }
  return { keys, cwdAgnosticHosts };
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
            liveInstances.cwdAgnosticHosts.has(record.host));
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

function pair(value, host, cwdHash, now) {
  prune(value, now);
  const hostInstances = listJson(value.instances)
    .map((file) => ({ file, record: readJsonFile(file) }))
    .filter(({ record }) => record.host === host);
  const hostClaims = listJson(value.claims)
    .map((file) => ({ file, record: readJsonFile(file) }))
    .filter(({ record }) => record.host === host);
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

export function claimSession(dataRoot, { host, cwd, sessionKey, now = Date.now() }) {
  const cwdHash = cwdKey(cwd);
  return withLock(dataRoot, host, (value) => {
    prune(value, now);
    const active = listJson(value.active)
      .map((file) => readJsonFile(file))
      .find(
        (record) =>
          record.host === host &&
          record.cwdHash === cwdHash &&
          record.sessionKey === sessionKey &&
          processIsAlive(record.pid),
      );
    if (active) return { status: "active", instanceId: active.instanceId };

    const existing = listJson(value.claims)
      .map((file) => ({ file, record: readJsonFile(file) }))
      .find(
        ({ record }) =>
          record.host === host && record.cwdHash === cwdHash && record.sessionKey === sessionKey,
      );
    if (!existing) {
      const claimId = randomId(16);
      writeJsonExclusive(path.join(value.claims, `${claimId}.json`), {
        claimId,
        host,
        cwdHash,
        sessionKey,
        createdAt: now,
      });
    }
    return pair(value, host, cwdHash, now);
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
      cwdHash,
      pid,
      createdAt: now,
      allowCwdMismatch,
    });
    writePrivateFile(path.join(value.instances, `${instanceId}.secret`), capability);
    return pair(value, host, cwdHash, now);
  });
  return { instanceId, capability, cwdHash, host, pid, allowCwdMismatch, outcome };
}

export function consumeBinding(
  dataRoot,
  registration,
  { now = Date.now() } = {},
) {
  return withLock(dataRoot, registration.host, (value) => {
    const file = path.join(value.bindings, `${registration.instanceId}.json`);
    if (!fs.existsSync(file)) pair(value, registration.host, registration.cwdHash, now);
    if (!fs.existsSync(file)) return null;
    const binding = readJsonFile(file);
    const payload = {
      instanceId: binding.instanceId,
      claimId: binding.claimId,
      host: binding.host,
      cwdHash: binding.cwdHash,
      instanceCwdHash: binding.instanceCwdHash,
      sessionKey: binding.sessionKey,
    };
    if (
      binding.instanceId !== registration.instanceId ||
      binding.host !== registration.host ||
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
