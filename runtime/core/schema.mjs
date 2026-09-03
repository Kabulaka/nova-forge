import path from "node:path";
import {
  ARRAY_LIMIT,
  AUTHORITY_STATES,
  CAPSULE_ARRAY_FIELDS,
  CHECKPOINT_PAYLOAD_LIMIT,
  NESTING_LIMIT,
  STAGE_PROJECTION_FIELDS,
  STRING_LIMIT,
} from "./constants.mjs";
import { NovaError, canonicalClone, stableStringify } from "./util.mjs";

const AUTHORITY_KEYS = new Set(["value", "authorityState", "source"]);
const CAPSULE_KEYS = new Set([
  "objective",
  "stage",
  "confirmedDecisions",
  "exclusions",
  "delegatedScope",
  "currentQuestion",
  "unresolvedDeltas",
  "stageProjection",
  "activeDeliveryScope",
  "evidence",
  "fileState",
  "commitState",
  "nextAction",
]);
const SAVE_KEYS = new Set([
  "idempotencyKey",
  "coveredEventWatermark",
  "taskCapsule",
  "controlDocuments",
]);
const CONTROL_DOCUMENT_KEYS = new Set(["path", "sha256", "loadState"]);
const LOAD_STATES = new Set(["loaded", "needs-reload", "unavailable"]);

function assertPlainObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new NovaError("INVALID_SCHEMA", `${label} must be an object`);
  }
}

function assertExactKeys(value, keys, label) {
  assertPlainObject(value, label);
  const actual = Object.keys(value);
  const missing = [...keys].filter((key) => !actual.includes(key));
  const extra = actual.filter((key) => !keys.has(key));
  if (missing.length || extra.length) {
    throw new NovaError(
      "INVALID_SCHEMA",
      `${label} keys mismatch; missing=${missing.join(",") || "none"}; extra=${extra.join(",") || "none"}`,
    );
  }
}

function assertString(value, label, { nonEmpty = true, max = STRING_LIMIT } = {}) {
  if (typeof value !== "string" || (nonEmpty && value.length === 0)) {
    throw new NovaError("INVALID_SCHEMA", `${label} must be a${nonEmpty ? " non-empty" : ""} string`);
  }
  if (Buffer.byteLength(value, "utf8") > max) {
    throw new NovaError("STRING_LIMIT", `${label} exceeds ${max} UTF-8 bytes`);
  }
}

function assertArray(value, label) {
  if (!Array.isArray(value)) {
    throw new NovaError("INVALID_SCHEMA", `${label} must be an array`);
  }
  if (value.length > ARRAY_LIMIT) {
    throw new NovaError("ARRAY_LIMIT", `${label} exceeds ${ARRAY_LIMIT} items`);
  }
}

function validateAuthorityValue(value, label) {
  assertExactKeys(value, AUTHORITY_KEYS, label);
  assertString(value.value, `${label}.value`);
  assertString(value.source, `${label}.source`, { max: 1024 });
  if (!AUTHORITY_STATES.has(value.authorityState)) {
    throw new NovaError("INVALID_AUTHORITY", `${label}.authorityState is invalid`);
  }
}

function validateAuthorityArray(value, label) {
  assertArray(value, label);
  value.forEach((entry, index) => validateAuthorityValue(entry, `${label}[${index}]`));
}

function validateDepthAndStrings(value, label = "payload", depth = 0) {
  if (
    (Array.isArray(value) || (value !== null && typeof value === "object")) &&
    depth > NESTING_LIMIT
  ) {
    throw new NovaError("NESTING_LIMIT", `${label} exceeds nesting depth ${NESTING_LIMIT}`);
  }
  if (typeof value === "string") {
    assertString(value, label, { nonEmpty: false });
  } else if (Array.isArray(value)) {
    assertArray(value, label);
    value.forEach((entry, index) => validateDepthAndStrings(entry, `${label}[${index}]`, depth + 1));
  } else if (value !== null && typeof value === "object") {
    for (const [key, entry] of Object.entries(value)) {
      assertString(key, `${label} key`, { max: 256 });
      validateDepthAndStrings(entry, `${label}.${key}`, depth + 1);
    }
  }
}

function scanSecrets(value, pathName = "payload") {
  const forbiddenKey = /(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|private[_-]?key)/i;
  const forbiddenValue = /(?:\bBearer\s+[A-Za-z0-9._~+/=-]{12,}|\bsk-[A-Za-z0-9_-]{16,}|\bgh[opusr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/;
  if (typeof value === "string" && forbiddenValue.test(value)) {
    throw new NovaError("SECRET_DETECTED", `secret-like value rejected at ${pathName}`);
  }
  if (Array.isArray(value)) {
    value.forEach((entry, index) => scanSecrets(entry, `${pathName}[${index}]`));
    return;
  }
  if (value !== null && typeof value === "object") {
    for (const [key, entry] of Object.entries(value)) {
      if (forbiddenKey.test(key)) {
        throw new NovaError("SECRET_DETECTED", `forbidden sensitive field rejected at ${pathName}.${key}`);
      }
      scanSecrets(entry, `${pathName}.${key}`);
    }
  }
}

export function validateTaskCapsule(capsule) {
  assertExactKeys(capsule, CAPSULE_KEYS, "taskCapsule");
  validateAuthorityValue(capsule.objective, "taskCapsule.objective");
  validateAuthorityValue(capsule.stage, "taskCapsule.stage");
  validateAuthorityValue(capsule.nextAction, "taskCapsule.nextAction");
  for (const field of CAPSULE_ARRAY_FIELDS) {
    validateAuthorityArray(capsule[field], `taskCapsule.${field}`);
  }
  if (capsule.currentQuestion !== null) {
    validateAuthorityValue(capsule.currentQuestion, "taskCapsule.currentQuestion");
  }
  assertExactKeys(
    capsule.stageProjection,
    new Set(STAGE_PROJECTION_FIELDS),
    "taskCapsule.stageProjection",
  );
  for (const field of STAGE_PROJECTION_FIELDS) {
    validateAuthorityArray(
      capsule.stageProjection[field],
      `taskCapsule.stageProjection.${field}`,
    );
  }
}

export function validateControlDocuments(documents) {
  assertArray(documents, "controlDocuments");
  documents.forEach((document, index) => {
    const label = `controlDocuments[${index}]`;
    assertExactKeys(document, CONTROL_DOCUMENT_KEYS, label);
    assertString(document.path, `${label}.path`);
    if (!path.isAbsolute(document.path)) {
      throw new NovaError("INVALID_CONTROL_DOCUMENT", `${label}.path must be absolute`);
    }
    if (typeof document.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(document.sha256)) {
      throw new NovaError("INVALID_CONTROL_DOCUMENT", `${label}.sha256 must be lowercase SHA-256`);
    }
    if (!LOAD_STATES.has(document.loadState)) {
      throw new NovaError("INVALID_CONTROL_DOCUMENT", `${label}.loadState is invalid`);
    }
  });
}

export function validateSaveInput(input) {
  assertExactKeys(input, SAVE_KEYS, "checkpoint input");
  assertString(input.idempotencyKey, "idempotencyKey", { max: 256 });
  if (!/^[A-Za-z0-9._:-]+$/.test(input.idempotencyKey)) {
    throw new NovaError("INVALID_IDEMPOTENCY_KEY", "idempotencyKey contains unsupported characters");
  }
  if (!Number.isSafeInteger(input.coveredEventWatermark) || input.coveredEventWatermark < 0) {
    throw new NovaError("INVALID_WATERMARK", "coveredEventWatermark must be a non-negative safe integer");
  }
  validateTaskCapsule(input.taskCapsule);
  validateControlDocuments(input.controlDocuments);
  validateDepthAndStrings(input);
  scanSecrets(input);
  const normalized = canonicalClone(input);
  const bytes = Buffer.byteLength(stableStringify(normalized), "utf8");
  if (bytes > CHECKPOINT_PAYLOAD_LIMIT) {
    throw new NovaError(
      "PAYLOAD_LIMIT",
      `normalized checkpoint payload exceeds ${CHECKPOINT_PAYLOAD_LIMIT} bytes`,
    );
  }
  return normalized;
}
