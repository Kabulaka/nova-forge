import fs from "node:fs";
import path from "node:path";
import { buildRecoveryContext } from "../core/capsule.mjs";
import { claimSession } from "../core/rendezvous.mjs";
import {
  assertCovered,
  completeCompaction,
  freezeCompaction,
  getCheckpoint,
  markEvent,
  recordInjectedCompaction,
  recordResumeInjection,
  startSession,
} from "../core/state-machine.mjs";
import { NovaError, cwdKey, readPluginVersion, redactError, scopeKey } from "../core/util.mjs";

export function detectHost(environment = process.env) {
  if (environment.NOVA_HOST === "codex" || environment.NOVA_HOST === "claude-code") {
    return environment.NOVA_HOST;
  }
  if (environment.PLUGIN_ROOT || environment.PLUGIN_DATA) return "codex";
  if (environment.CLAUDE_PLUGIN_ROOT || environment.CLAUDE_PLUGIN_DATA) return "claude-code";
  throw new NovaError("HOST_UNAVAILABLE", "trusted plugin host environment is unavailable");
}

export function resolvePluginPaths(environment = process.env) {
  const pluginRoot =
    environment.NOVA_PLUGIN_ROOT || environment.PLUGIN_ROOT || environment.CLAUDE_PLUGIN_ROOT;
  const dataRoot =
    environment.NOVA_PLUGIN_DATA || environment.PLUGIN_DATA || environment.CLAUDE_PLUGIN_DATA;
  if (!pluginRoot || !path.isAbsolute(pluginRoot)) {
    throw new NovaError("PLUGIN_ROOT_UNAVAILABLE", "absolute plugin root is unavailable");
  }
  if (!dataRoot || !path.isAbsolute(dataRoot)) {
    throw new NovaError("PLUGIN_DATA_UNAVAILABLE", "absolute writable plugin data root is unavailable");
  }
  return { pluginRoot, dataRoot };
}

function trustedBinding(host, input) {
  if (typeof input.session_id !== "string" || input.session_id.length === 0) {
    throw new NovaError("SESSION_ID_UNAVAILABLE", "trusted hook session_id is required");
  }
  if (typeof input.cwd !== "string" || !path.isAbsolute(input.cwd)) {
    throw new NovaError("CWD_UNAVAILABLE", "trusted absolute hook cwd is required");
  }
  return {
    host,
    sessionKey: scopeKey(host, input.session_id),
    cwdHash: cwdKey(input.cwd),
  };
}

function eventId(input) {
  const id = input.tool_use_id || input.turn_id;
  if (typeof id !== "string" || id.length === 0) {
    throw new NovaError("EVENT_ID_UNAVAILABLE", "trusted hook turn_id or tool_use_id is required");
  }
  return `${input.hook_event_name}:${id}`;
}

function contextOutput(event, context, systemMessage) {
  const output = {
    hookSpecificOutput: {
      hookEventName: event,
      additionalContext: context,
    },
  };
  if (systemMessage) output.systemMessage = systemMessage;
  return output;
}

function blockingOutput(host, event, reason) {
  if (event === "Stop") return { decision: "block", reason };
  if (
    host === "claude-code" &&
    (event === "PreCompact" || event === "UserPromptSubmit")
  ) {
    return { decision: "block", reason };
  }
  return { continue: false, stopReason: reason, systemMessage: reason };
}

function isOwnCheckpointTool(toolName) {
  return typeof toolName === "string" && /nova[_-]checkpoint_(?:get|save)$/i.test(toolName);
}

export function handleHook(input, environment = process.env, options = {}) {
  if (input === null || typeof input !== "object" || Array.isArray(input)) {
    throw new NovaError("INVALID_HOOK_INPUT", "hook input must be a JSON object");
  }
  const event = input.hook_event_name;
  const host = detectHost(environment);
  const { pluginRoot, dataRoot } = resolvePluginPaths(environment);
  const pluginVersion = readPluginVersion(pluginRoot);
  const binding = trustedBinding(host, input);
  const now = options.now ?? Date.now();

  try {
    if (event === "SessionStart") {
      const source = input.source;
      if (!["startup", "resume", "clear", "compact"].includes(source)) {
        throw new NovaError("UNSUPPORTED_SESSION_SOURCE", `unsupported SessionStart source ${source}`);
      }
      const rendezvous = claimSession(dataRoot, {
        host,
        cwd: input.cwd,
        sessionKey: binding.sessionKey,
        now,
      });
      startSession(dataRoot, binding, pluginVersion, source, { now });
      const rules = fs.readFileSync(path.join(pluginRoot, "codex", "AGENTS.global.md"), "utf8");
      let context;
      if (source === "resume" || source === "compact") {
        const loaded = getCheckpoint(dataRoot, binding, { now });
        assertCovered(loaded.envelope);
        context = buildRecoveryContext(rules, loaded.envelope);
        if (source === "compact") {
          recordInjectedCompaction(dataRoot, binding, pluginVersion, { now });
        } else {
          recordResumeInjection(dataRoot, binding, pluginVersion, { now });
        }
      } else {
        context = buildRecoveryContext(rules, { taskCapsule: null });
      }
      const warning =
        rendezvous.status === "ambiguous"
          ? "Nova checkpoint MCP binding is ambiguous and remains disabled for this session."
          : undefined;
      return contextOutput(event, context, warning);
    }

    if (event === "UserPromptSubmit") {
      markEvent(dataRoot, binding, pluginVersion, eventId(input), { now });
      return {};
    }
    if (event === "PostToolUse") {
      if (!isOwnCheckpointTool(input.tool_name)) {
        markEvent(dataRoot, binding, pluginVersion, eventId(input), { now });
      }
      return {};
    }
    if (event === "Stop") {
      const { envelope } = getCheckpoint(dataRoot, binding, { now });
      assertCovered(envelope);
      return {};
    }
    if (event === "PreCompact") {
      freezeCompaction(dataRoot, binding, pluginVersion, input.trigger, { now });
      return {};
    }
    if (event === "PostCompact") {
      completeCompaction(dataRoot, binding, pluginVersion, input.trigger, { now });
      return {};
    }
    throw new NovaError("UNSUPPORTED_HOOK_EVENT", `unsupported hook event ${event}`);
  } catch (error) {
    const reason = `Nova checkpoint safety gate: ${redactError(error)}`;
    if (event === "PostCompact" && host === "claude-code") return {};
    return blockingOutput(host, event, reason);
  }
}
