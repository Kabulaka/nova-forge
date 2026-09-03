export const SCHEMA_VERSION = 1;
export const CHECKPOINT_PAYLOAD_LIMIT = 256 * 1024;
export const JSON_RPC_FRAME_LIMIT = 320 * 1024;
export const STRING_LIMIT = 8 * 1024;
export const ARRAY_LIMIT = 128;
export const NESTING_LIMIT = 4;
export const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000;
export const HOST_QUOTA_BYTES = 512 * 1024 * 1024;
export const GLOBAL_QUOTA_BYTES = 1024 * 1024 * 1024;
export const HOST_SESSION_LIMIT = 2000;
export const RENDEZVOUS_TTL_MS = 30_000;
export const LOCK_TIMEOUT_MS = 2_000;
export const INJECTION_CHARACTER_LIMIT = 9_500;

export const AUTHORITY_STATES = new Set([
  "user-confirmed",
  "delegated-ai-candidate",
  "verified-evidence",
  "explicitly-excluded",
  "pending",
]);

export const CAPSULE_ARRAY_FIELDS = [
  "confirmedDecisions",
  "exclusions",
  "delegatedScope",
  "unresolvedDeltas",
  "activeDeliveryScope",
  "evidence",
  "fileState",
  "commitState",
];

export const STAGE_PROJECTION_FIELDS = [
  "inheritedContracts",
  "stageEvidence",
  "stageDecisions",
  "unresolvedDeltas",
  "resolutionBasis",
];
