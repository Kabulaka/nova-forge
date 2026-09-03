import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { cwdKey, scopeKey } from "../runtime/core/util.mjs";

export const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export function temporaryDirectory(prefix = "nova-forge-") {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  return {
    directory,
    cleanup() {
      fs.rmSync(directory, { recursive: true, force: true });
    },
  };
}

export function binding(host = "codex", sessionId = "session-1", cwd = pluginRoot) {
  return { host, sessionKey: scopeKey(host, sessionId), cwdHash: cwdKey(cwd) };
}

export function authority(value, authorityState = "user-confirmed", source = "user") {
  return { value, authorityState, source };
}

export function capsule(overrides = {}) {
  return {
    objective: authority("Implement the Nova plugin"),
    stage: authority("implementation"),
    confirmedDecisions: [authority("Use structured checkpoints")],
    exclusions: [authority("Do not push", "explicitly-excluded")],
    delegatedScope: [authority("Internal module names", "delegated-ai-candidate", "confirmed design")],
    currentQuestion: null,
    unresolvedDeltas: [],
    stageProjection: {
      inheritedContracts: [authority("Same-session only")],
      stageEvidence: [authority("Tests are local", "verified-evidence", "test suite")],
      stageDecisions: [authority("Use Node.js standard library", "delegated-ai-candidate", "confirmed design")],
      unresolvedDeltas: [],
      resolutionBasis: [authority("Design confirmed", "verified-evidence", "conversation")],
    },
    activeDeliveryScope: [authority("Plugin runtime")],
    evidence: [],
    fileState: [],
    commitState: [],
    nextAction: authority("Run tests"),
    ...overrides,
  };
}

export function saveInput(watermark, overrides = {}) {
  return {
    idempotencyKey: `save-${watermark}`,
    coveredEventWatermark: watermark,
    taskCapsule: capsule(),
    controlDocuments: [
      {
        path: path.join(pluginRoot, "codex", "AGENTS.global.md"),
        sha256: "a".repeat(64),
        loadState: "loaded",
      },
    ],
    ...overrides,
  };
}
