#!/usr/bin/env node
import path from "node:path";
import { JSON_RPC_FRAME_LIMIT, MCP_PROTOCOL_VERSION } from "../core/constants.mjs";
import { registerMcpInstance, waitForBinding } from "../core/rendezvous.mjs";
import { getCheckpoint, saveCheckpoint } from "../core/state-machine.mjs";
import { isMainModule, NovaError, readPluginVersion, redactError } from "../core/util.mjs";

function parseHost(argv) {
  const index = argv.indexOf("--host");
  const host = index >= 0 ? argv[index + 1] : undefined;
  if (host !== "codex" && host !== "claude-code") {
    throw new NovaError("HOST_UNAVAILABLE", "--host must be codex or claude-code");
  }
  return host;
}

const AUTHORITY_VALUE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["value", "authorityState", "source"],
  properties: {
    value: { type: "string", maxLength: 8192 },
    authorityState: {
      type: "string",
      enum: [
        "user-confirmed",
        "delegated-ai-candidate",
        "verified-evidence",
        "explicitly-excluded",
        "pending",
      ],
    },
    source: { type: "string", maxLength: 1024 },
  },
};

const AUTHORITY_ARRAY_SCHEMA = {
  type: "array",
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
        authorityState: { type: "string", enum: states },
      },
    },
  };
}

const TASK_CAPSULE_SCHEMA = {
  type: "object",
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
    objective: AUTHORITY_VALUE_SCHEMA,
    stage: AUTHORITY_VALUE_SCHEMA,
    confirmedDecisions: authorityArraySchema(["user-confirmed"]),
    exclusions: AUTHORITY_ARRAY_SCHEMA,
    delegatedScope: AUTHORITY_ARRAY_SCHEMA,
    currentQuestion: { anyOf: [AUTHORITY_VALUE_SCHEMA, { type: "null" }] },
    unresolvedDeltas: AUTHORITY_ARRAY_SCHEMA,
    stageProjection: {
      type: "object",
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
    nextAction: AUTHORITY_VALUE_SCHEMA,
  },
};

const SAVE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["idempotencyKey", "coveredEventWatermark", "taskCapsule", "controlDocuments"],
  properties: {
    idempotencyKey: { type: "string", maxLength: 256 },
    coveredEventWatermark: { type: "integer", minimum: 0 },
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
  constructor({ dataRoot, pluginRoot, host, cwd = process.cwd(), pid = process.pid }) {
    if (!path.isAbsolute(dataRoot) || !path.isAbsolute(pluginRoot)) {
      throw new NovaError("INVALID_RUNTIME_PATH", "plugin root and data root must be absolute");
    }
    this.dataRoot = dataRoot;
    this.pluginVersion = readPluginVersion(pluginRoot);
    this.registration = registerMcpInstance(dataRoot, { host, cwd, pid });
    this.binding = null;
  }

  currentBinding() {
    if (this.binding) return this.binding;
    this.binding = waitForBinding(this.dataRoot, this.registration);
    if (!this.binding) {
      throw new NovaError(
        "BINDING_UNAVAILABLE",
        "MCP instance is not uniquely bound to a trusted host session",
      );
    }
    return this.binding;
  }

  listTools() {
    return [
      {
        name: "nova_checkpoint_get",
        description: "Read the latest validated checkpoint for this bound host session.",
        inputSchema: { type: "object", additionalProperties: false, properties: {} },
      },
      {
        name: "nova_checkpoint_save",
        description:
          "Persist a complete structured Nova task checkpoint for the current trusted event watermark.",
        inputSchema: SAVE_SCHEMA,
      },
    ];
  }

  callTool(name, args) {
    const binding = this.currentBinding();
    if (name === "nova_checkpoint_get") {
      if (args && Object.keys(args).length > 0) {
        throw new NovaError("INVALID_SCHEMA", "nova_checkpoint_get accepts no arguments");
      }
      const { envelope, source } = getCheckpoint(this.dataRoot, binding);
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
      const outcome = saveCheckpoint(this.dataRoot, binding, this.pluginVersion, args);
      return {
        saved: true,
        idempotent: outcome.result.idempotent,
        authorityGeneration: outcome.envelope.authorityGeneration,
        eventWatermark: outcome.envelope.eventWatermark,
        coveredEventWatermark: outcome.envelope.coveredEventWatermark,
        dirty: outcome.envelope.dirty,
      };
    }
    throw new NovaError("UNKNOWN_TOOL", `unknown MCP tool ${name}`);
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
  const dataRoot = process.env.NOVA_PLUGIN_DATA;
  const pluginRoot = process.env.NOVA_PLUGIN_ROOT;
  if (!dataRoot || !pluginRoot) {
    throw new NovaError("PLUGIN_ENV_UNAVAILABLE", "NOVA_PLUGIN_DATA and NOVA_PLUGIN_ROOT are required");
  }
  const runtime = new McpRuntime({ dataRoot, pluginRoot, host });
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
