#!/usr/bin/env node
import path from "node:path";
import { JSON_RPC_FRAME_LIMIT, MCP_PROTOCOL_VERSION } from "../core/constants.mjs";
import { consumeScopeProof } from "../core/scope-proof.mjs";
import {
  bootstrapStateRoot,
  legacyDataRoots,
  resolveNovaHome,
} from "../core/state-root.mjs";
import { getCheckpoint, saveCheckpoint } from "../core/state-machine.mjs";
import { isMainModule, NovaError, readPluginVersion, redactError } from "../core/util.mjs";

const SERVER_INSTRUCTIONS =
  "Before ending a turn, call nova_checkpoint_get; if dirty=true, call nova_checkpoint_save " +
  "with coveredEventWatermark copied from that get, then get again. In every taskCapsule, " +
  "objective, stage, and nextAction are {value, authorityState, source} objects, never strings. " +
  "Save top-level keys are exactly idempotencyKey, coveredEventWatermark, taskCapsule, and " +
  "controlDocuments; never eventWatermark. taskCapsule keys are exactly objective, stage, " +
  "confirmedDecisions, exclusions, delegatedScope, currentQuestion, unresolvedDeltas, " +
  "stageProjection, activeDeliveryScope, evidence, fileState, commitState, and nextAction. " +
  "currentQuestion is an authority object or null; all collection fields are arrays. " +
  "authorityState is one of user-confirmed, delegated-ai-candidate, verified-evidence, " +
  "explicitly-excluded, or pending. Projection item states are strict: inheritedContracts only " +
  "user-confirmed; stageEvidence only verified-evidence; stageDecisions only " +
  "delegated-ai-candidate; unresolvedDeltas only pending; resolutionBasis accepts only " +
  "user-confirmed, verified-evidence, delegated-ai-candidate, or explicitly-excluded; pending " +
  "is not allowed. stageProjection has exactly five array fields: " +
  "inheritedContracts, stageEvidence, stageDecisions, unresolvedDeltas, and resolutionBasis. " +
  "Do not invent authority, secrets, host, sessionId, or scopeProof.";

function parseHost(argv) {
  const index = argv.indexOf("--host");
  const host = index >= 0 ? argv[index + 1] : undefined;
  if (host !== "codex" && host !== "claude-code") {
    throw new NovaError("HOST_UNAVAILABLE", "--host must be codex or claude-code");
  }
  return host;
}

export function resolveMcpPluginRoot(
  host,
  environment = process.env,
  cwd = process.cwd(),
) {
  const configured =
    environment.NOVA_PLUGIN_ROOT ||
    (host === "codex" ? environment.PLUGIN_ROOT : environment.CLAUDE_PLUGIN_ROOT);
  const pluginRoot = configured || (host === "codex" ? cwd : undefined);
  if (!pluginRoot || !path.isAbsolute(pluginRoot)) {
    throw new NovaError("PLUGIN_ROOT_UNAVAILABLE", "absolute plugin root is unavailable");
  }
  return path.normalize(pluginRoot);
}

const AUTHORITY_VALUE_SCHEMA = {
  type: "object",
  description:
    "One explicit authority value. Pass this object shape for objective, stage, nextAction, and every array item; never pass a bare string.",
  additionalProperties: false,
  required: ["value", "authorityState", "source"],
  properties: {
    value: { type: "string", maxLength: 8192, description: "The current fact or action text." },
    authorityState: {
      type: "string",
      enum: [
        "user-confirmed",
        "delegated-ai-candidate",
        "verified-evidence",
        "explicitly-excluded",
        "pending",
      ],
      description: "The explicit authority category for this value.",
    },
    source: {
      type: "string",
      maxLength: 1024,
      description: "A concise provenance such as user request, verified workspace, or control document.",
    },
  },
};

const AUTHORITY_ARRAY_SCHEMA = {
  type: "array",
  description: "Always a JSON array of authority objects. Use [] when there are no entries.",
  maxItems: 128,
  items: AUTHORITY_VALUE_SCHEMA,
};

function authorityArraySchema(states) {
  return {
    ...AUTHORITY_ARRAY_SCHEMA,
    items: {
      ...AUTHORITY_VALUE_SCHEMA,
      properties: {
        ...AUTHORITY_VALUE_SCHEMA.properties,
        authorityState: {
          type: "string",
          enum: states,
          description: `This field accepts only: ${states.join(", ")}.`,
        },
      },
    },
  };
}

const TASK_CAPSULE_SCHEMA = {
  type: "object",
  description:
    "Complete recovery capsule. objective, stage, and nextAction are authority objects; collection fields are arrays of authority objects.",
  additionalProperties: false,
  required: [
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
  ],
  properties: {
    objective: {
      ...AUTHORITY_VALUE_SCHEMA,
      description: "Current objective as one authority object, never a string.",
    },
    stage: {
      ...AUTHORITY_VALUE_SCHEMA,
      description: "Current Nova or delivery stage as one authority object, never a string.",
    },
    confirmedDecisions: authorityArraySchema(["user-confirmed"]),
    exclusions: AUTHORITY_ARRAY_SCHEMA,
    delegatedScope: AUTHORITY_ARRAY_SCHEMA,
    currentQuestion: { anyOf: [AUTHORITY_VALUE_SCHEMA, { type: "null" }] },
    unresolvedDeltas: AUTHORITY_ARRAY_SCHEMA,
    stageProjection: {
      type: "object",
      description:
        "Exactly five array fields. resolutionBasis is an array even when it has zero or one entry.",
      additionalProperties: false,
      required: [
        "inheritedContracts",
        "stageEvidence",
        "stageDecisions",
        "unresolvedDeltas",
        "resolutionBasis",
      ],
      properties: {
        inheritedContracts: authorityArraySchema(["user-confirmed"]),
        stageEvidence: authorityArraySchema(["verified-evidence"]),
        stageDecisions: authorityArraySchema(["delegated-ai-candidate"]),
        unresolvedDeltas: authorityArraySchema(["pending"]),
        resolutionBasis: authorityArraySchema([
          "user-confirmed",
          "verified-evidence",
          "delegated-ai-candidate",
          "explicitly-excluded",
        ]),
      },
    },
    activeDeliveryScope: AUTHORITY_ARRAY_SCHEMA,
    evidence: AUTHORITY_ARRAY_SCHEMA,
    fileState: AUTHORITY_ARRAY_SCHEMA,
    commitState: AUTHORITY_ARRAY_SCHEMA,
    nextAction: {
      ...AUTHORITY_VALUE_SCHEMA,
      description: "Next executable action as one authority object, never a string.",
    },
  },
};

const SAVE_SCHEMA = {
  type: "object",
  description:
    "Exact top-level keys: idempotencyKey, coveredEventWatermark, taskCapsule, controlDocuments. Do not send eventWatermark or any internal proof field.",
  additionalProperties: false,
  required: ["idempotencyKey", "coveredEventWatermark", "taskCapsule", "controlDocuments"],
  properties: {
    idempotencyKey: {
      type: "string",
      maxLength: 256,
      description: "Caller-chosen unique string for this exact payload.",
    },
    coveredEventWatermark: {
      type: "integer",
      minimum: 0,
      description: "Copy the exact eventWatermark returned by the immediately preceding get.",
    },
    taskCapsule: TASK_CAPSULE_SCHEMA,
    controlDocuments: {
      type: "array",
      maxItems: 128,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["path", "sha256", "loadState"],
        properties: {
          path: { type: "string", maxLength: 8192 },
          sha256: { type: "string", pattern: "^[a-f0-9]{64}$" },
          loadState: { type: "string", enum: ["loaded", "needs-reload", "unavailable"] },
        },
      },
    },
  },
};

export class McpRuntime {
  constructor({
    dataRoot,
    pluginRoot,
    host,
    environment = process.env,
    legacyRoots = [],
  }) {
    if (!path.isAbsolute(dataRoot) || !path.isAbsolute(pluginRoot)) {
      throw new NovaError("INVALID_RUNTIME_PATH", "plugin root and data root must be absolute");
    }
    bootstrapStateRoot({ environment, host, dataRoot, legacyRoots });
    this.dataRoot = dataRoot;
    this.host = host;
    this.pluginVersion = readPluginVersion(pluginRoot);
  }

  listTools() {
    return [
      {
        name: "nova_checkpoint_get",
        description:
          "Read the latest validated checkpoint for the current trusted host session. Call this before save, copy its exact eventWatermark into coveredEventWatermark, and call it again after save to verify dirty=false.",
        inputSchema: { type: "object", additionalProperties: false, properties: {} },
      },
      {
        name: "nova_checkpoint_save",
        description:
          "Persist a complete structured Nova task checkpoint. Top-level keys are exactly idempotencyKey, coveredEventWatermark, taskCapsule, controlDocuments; never eventWatermark. taskCapsule keys are exactly objective, stage, confirmedDecisions, exclusions, delegatedScope, currentQuestion, unresolvedDeltas, stageProjection, activeDeliveryScope, evidence, fileState, commitState, nextAction. Do not use delegationScope, candidateIdentities, currentQuestions, files, or commits. objective, stage, nextAction, currentQuestion (unless null), and every array item are {value, authorityState, source}; authorityState is user-confirmed, delegated-ai-candidate, verified-evidence, explicitly-excluded, or pending, never confirmed. Projection item states are strict: inheritedContracts=user-confirmed; stageEvidence=verified-evidence; stageDecisions=delegated-ai-candidate; unresolvedDeltas=pending; resolutionBasis accepts only user-confirmed, verified-evidence, delegated-ai-candidate, or explicitly-excluded; pending is not allowed. Use [] when no correctly typed item exists. Every collection is an array. stageProjection has exactly inheritedContracts, stageEvidence, stageDecisions, unresolvedDeltas, resolutionBasis, all arrays.",
        inputSchema: SAVE_SCHEMA,
      },
    ];
  }

  callTool(name, args, options = {}) {
    if (name !== "nova_checkpoint_get" && name !== "nova_checkpoint_save") {
      throw new NovaError("UNKNOWN_TOOL", `unknown MCP tool ${name}`);
    }
    if (!isPlainObject(args)) {
      throw new NovaError("INVALID_SCHEMA", `${name} arguments must be a JSON object`);
    }
    const toolArgs = { ...args };
    const scopeProof = toolArgs.scopeProof;
    delete toolArgs.scopeProof;
    const binding = consumeScopeProof(
      this.dataRoot,
      { host: this.host, scopeProof, toolName: name },
      options,
    );
    if (name === "nova_checkpoint_get") {
      if (Object.keys(toolArgs).length > 0) {
        throw new NovaError("INVALID_SCHEMA", "nova_checkpoint_get accepts no arguments");
      }
      const { envelope, source } = getCheckpoint(this.dataRoot, binding, options);
      const value = {
        source,
        schemaVersion: envelope.schemaVersion,
        pluginVersion: envelope.pluginVersion,
        eventWatermark: envelope.eventWatermark,
        coveredEventWatermark: envelope.coveredEventWatermark,
        dirty: envelope.dirty,
        authorityGeneration: envelope.authorityGeneration,
        taskCapsule: envelope.taskCapsule,
        controlDocuments: envelope.controlDocuments,
      };
      return value;
    }
    if (name === "nova_checkpoint_save") {
      const outcome = saveCheckpoint(
        this.dataRoot,
        binding,
        this.pluginVersion,
        toolArgs,
        options,
      );
      return {
        saved: true,
        idempotent: outcome.result.idempotent,
        authorityGeneration: outcome.envelope.authorityGeneration,
        eventWatermark: outcome.envelope.eventWatermark,
        coveredEventWatermark: outcome.envelope.coveredEventWatermark,
        dirty: outcome.envelope.dirty,
      };
    }
  }
}

function success(id, result) {
  return { jsonrpc: "2.0", id, result };
}

function failure(id, code, message) {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validRequestId(id) {
  return id === null || typeof id === "string" || (typeof id === "number" && Number.isFinite(id));
}

export function handleRpc(runtime, request) {
  if (!isPlainObject(request) || request.jsonrpc !== "2.0") {
    return failure(request?.id ?? null, -32600, "Invalid Request");
  }
  const hasId = Object.hasOwn(request, "id");
  if (typeof request.method !== "string" || (hasId && !validRequestId(request.id))) {
    return failure(null, -32600, "Invalid Request");
  }
  if (!hasId) return null;
  if (request.method === "initialize") {
    if (request.params !== undefined && !isPlainObject(request.params)) {
      return failure(request.id, -32602, "Invalid params");
    }
    if (
      request.params?.protocolVersion !== undefined &&
      typeof request.params.protocolVersion !== "string"
    ) {
      return failure(request.id, -32602, "Invalid params");
    }
    return success(request.id, {
      protocolVersion: MCP_PROTOCOL_VERSION,
      capabilities: { tools: {} },
      serverInfo: { name: "nova-checkpoint", version: runtime.pluginVersion },
      instructions: SERVER_INSTRUCTIONS,
    });
  }
  if (request.method === "ping") {
    if (request.params !== undefined && !isPlainObject(request.params)) {
      return failure(request.id, -32602, "Invalid params");
    }
    return success(request.id, {});
  }
  if (request.method === "tools/list") {
    if (request.params !== undefined && !isPlainObject(request.params)) {
      return failure(request.id, -32602, "Invalid params");
    }
    return success(request.id, { tools: runtime.listTools() });
  }
  if (request.method === "tools/call") {
    if (
      !isPlainObject(request.params) ||
      typeof request.params.name !== "string" ||
      (request.params.arguments !== undefined && !isPlainObject(request.params.arguments))
    ) {
      return failure(request.id, -32602, "Invalid params");
    }
    try {
      const value = runtime.callTool(request.params.name, request.params.arguments ?? {});
      return success(request.id, {
        content: [{ type: "text", text: JSON.stringify(value) }],
        structuredContent: value,
        isError: false,
      });
    } catch (error) {
      const message = redactError(error);
      return success(request.id, {
        content: [{ type: "text", text: message }],
        structuredContent: { error: message },
        isError: true,
      });
    }
  }
  return failure(request.id ?? null, -32601, "Method not found");
}

async function main() {
  const host = parseHost(process.argv.slice(2));
  const pluginRoot = resolveMcpPluginRoot(host);
  const dataRoot = resolveNovaHome(process.env);
  const runtime = new McpRuntime({
    dataRoot,
    pluginRoot,
    host,
    legacyRoots: legacyDataRoots(process.env, host),
  });
  let buffer = Buffer.alloc(0);
  let discardingOversizedFrame = false;
  for await (const chunk of process.stdin) {
    buffer = Buffer.concat([buffer, chunk]);
    if (discardingOversizedFrame) {
      const newline = buffer.indexOf(10);
      if (newline < 0) {
        buffer = Buffer.alloc(0);
        continue;
      }
      buffer = buffer.subarray(newline + 1);
      discardingOversizedFrame = false;
    }
    if (buffer.length > JSON_RPC_FRAME_LIMIT && !buffer.includes(10)) {
      process.stdout.write(`${JSON.stringify(failure(null, -32700, "JSON-RPC frame exceeds limit"))}\n`);
      buffer = Buffer.alloc(0);
      discardingOversizedFrame = true;
      continue;
    }
    let newline;
    while ((newline = buffer.indexOf(10)) >= 0) {
      const frame = buffer.subarray(0, newline);
      buffer = buffer.subarray(newline + 1);
      if (frame.length === 0) continue;
      if (frame.length > JSON_RPC_FRAME_LIMIT) {
        process.stdout.write(`${JSON.stringify(failure(null, -32700, "JSON-RPC frame exceeds limit"))}\n`);
        continue;
      }
      let response;
      try {
        response = handleRpc(runtime, JSON.parse(frame.toString("utf8")));
      } catch {
        response = failure(null, -32700, "Parse error");
      }
      if (response) process.stdout.write(`${JSON.stringify(response)}\n`);
    }
  }
}

if (isMainModule(import.meta.url, process.argv[1])) {
  main().catch((error) => {
    process.stderr.write(`${redactError(error)}\n`);
    process.exitCode = 1;
  });
}
