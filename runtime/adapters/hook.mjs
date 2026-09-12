import fs from "node:fs";
import path from "node:path";
import { buildRecoveryContext } from "../core/capsule.mjs";
import { claimSession } from "../core/rendezvous.mjs";
import {
  bootstrapStateRoot,
  legacyDataRoots,
  resolveNovaHome,
} from "../core/state-root.mjs";
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
import { claimUncoveredStopNotice } from "../core/storage.mjs";
import {
  NovaError,
  cwdKey,
  randomId,
  readPluginVersion,
  redactError,
  scopeKey,
} from "../core/util.mjs";

const OWN_CHECKPOINT_TOOLS = {
  codex: new Set([
    "mcp__nova-checkpoint__nova_checkpoint_get",
    "mcp__nova-checkpoint__nova_checkpoint_save",
    "mcp__nova_checkpoint__nova_checkpoint_get",
    "mcp__nova_checkpoint__nova_checkpoint_save",
  ]),
  "claude-code": new Set([
    "mcp__plugin_nova-forge_nova-checkpoint__nova_checkpoint_get",
    "mcp__plugin_nova-forge_nova-checkpoint__nova_checkpoint_save",
  ]),
};

export function detectHost(environment = process.env) {
  if (environment.NOVA_HOST === "codex" || environment.NOVA_HOST === "claude-code") {
    return environment.NOVA_HOST;
  }
  if (environment.PLUGIN_ROOT || environment.PLUGIN_DATA) return "codex";
  if (environment.CLAUDE_PLUGIN_ROOT || environment.CLAUDE_PLUGIN_DATA) return "claude-code";
  throw new NovaError("HOST_UNAVAILABLE", "trusted plugin host environment is unavailable");
}

function resolvePluginRoot(environment = process.env) {
  const pluginRoot =
    environment.NOVA_PLUGIN_ROOT || environment.PLUGIN_ROOT || environment.CLAUDE_PLUGIN_ROOT;
  if (!pluginRoot || !path.isAbsolute(pluginRoot)) {
    throw new NovaError("PLUGIN_ROOT_UNAVAILABLE", "absolute plugin root is unavailable");
  }
  return pluginRoot;
}

export function resolvePluginPaths(environment = process.env, host = detectHost(environment)) {
  const pluginRoot = resolvePluginRoot(environment);
  return {
    pluginRoot,
    dataRoot: resolveNovaHome(environment),
    legacyRoots: legacyDataRoots(environment, host),
  };
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

function eventId(host, input) {
  const id = input.tool_use_id || input.turn_id;
  if (typeof id === "string" && id.length > 0) {
    return `${input.hook_event_name}:${id}`;
  }
  if (host === "claude-code" && input.hook_event_name === "UserPromptSubmit") {
    return `UserPromptSubmit:${randomId(16)}`;
  }
  {
    throw new NovaError("EVENT_ID_UNAVAILABLE", "trusted hook turn_id or tool_use_id is required");
  }
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

function uncoveredResumeContext(rules, envelope) {
  const recoveryState = JSON.stringify({
    eventWatermark: envelope.eventWatermark,
    coveredEventWatermark: envelope.coveredEventWatermark,
    dirty: envelope.dirty,
  });
  return (
    `${buildRecoveryContext(rules, { taskCapsule: null })}\n\n` +
    "<nova-checkpoint-recovery-required>\n" +
    `${recoveryState}\n` +
    "The resumed session has no checkpoint covering its current event watermark. " +
    "No prior taskCapsule was injected as authoritative state. Reconstruct only from the " +
    "visible conversation and verified workspace facts; preserve unknowns as pending. Before " +
    "ending, call nova_checkpoint_get, then nova_checkpoint_save for the latest eventWatermark, " +
    "and confirm dirty=false.\n" +
    "</nova-checkpoint-recovery-required>"
  );
}

function degradedOutput(event, reason, rules) {
  const warning =
    `${reason}. Nova checkpoint continuity is degraded, but the host operation was allowed ` +
    "to continue. No missing, stale, or invalid checkpoint was promoted to authoritative state.";
  if (event === "SessionStart" && typeof rules === "string") {
    const context =
      `${buildRecoveryContext(rules, { taskCapsule: null })}\n\n` +
      "<nova-checkpoint-degraded>\n" +
      `${warning}\n` +
      "Reconstruct only from visible conversation and verified workspace facts. Treat unknowns " +
      "as pending. If the Nova checkpoint MCP is available, a later turn may create a fresh " +
      "checkpoint; inability to do so must not block conversation or native compaction.\n" +
      "</nova-checkpoint-degraded>";
    return contextOutput(event, context, warning);
  }
  return { systemMessage: warning };
}

function isOwnCheckpointTool(host, toolName) {
  return typeof toolName === "string" && OWN_CHECKPOINT_TOOLS[host].has(toolName);
}

export function handleHook(input, environment = process.env, options = {}) {
  const event = input?.hook_event_name;
  let rules;
  try {
    if (input === null || typeof input !== "object" || Array.isArray(input)) {
      throw new NovaError("INVALID_HOOK_INPUT", "hook input must be a JSON object");
    }
    const host = detectHost(environment);
    const pluginRoot = resolvePluginRoot(environment);
    const pluginVersion = readPluginVersion(pluginRoot);
    rules = fs.readFileSync(path.join(pluginRoot, "codex", "AGENTS.global.md"), "utf8");
    const { dataRoot, legacyRoots } = resolvePluginPaths(environment, host);
    bootstrapStateRoot({ environment, host, dataRoot, legacyRoots, now: options.now ?? Date.now() });
    const binding = trustedBinding(host, input);
    const now = options.now ?? Date.now();
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
      let context;
      let recoveryWarning;
      if (source === "resume" || source === "compact") {
        const loaded = getCheckpoint(dataRoot, binding, { now });
        try {
          assertCovered(loaded.envelope);
          context = buildRecoveryContext(rules, loaded.envelope);
          if (source === "compact") {
            recordInjectedCompaction(dataRoot, binding, pluginVersion, { now });
          } else {
            recordResumeInjection(dataRoot, binding, pluginVersion, { now });
          }
        } catch (error) {
          if (source !== "resume" || error?.code !== "CHECKPOINT_NOT_COVERED") throw error;
          context = uncoveredResumeContext(rules, loaded.envelope);
          recoveryWarning =
            "Nova resumed without injecting an authoritative checkpoint because the saved " +
            "checkpoint does not cover the current event watermark. Repair it with the Nova " +
            "checkpoint MCP before ending this turn.";
        }
      } else {
        context = buildRecoveryContext(rules, { taskCapsule: null });
      }
      const warning = [
        recoveryWarning,
        rendezvous.status === "ambiguous"
          ? "Nova checkpoint MCP binding is ambiguous and remains disabled for this session."
          : undefined,
      ]
        .filter(Boolean)
        .join(" ");
      return contextOutput(event, context, warning);
    }

    if (event === "UserPromptSubmit") {
      markEvent(dataRoot, binding, pluginVersion, eventId(host, input), { now });
      return {};
    }
    if (event === "PostToolUse") {
      if (!isOwnCheckpointTool(host, input.tool_name)) {
        markEvent(dataRoot, binding, pluginVersion, eventId(host, input), { now });
      }
      return {};
    }
    if (event === "Stop") {
      const { envelope } = getCheckpoint(dataRoot, binding, { now });
      try {
        assertCovered(envelope);
      } catch (error) {
        if (error?.code !== "CHECKPOINT_NOT_COVERED") throw error;
        if (!claimUncoveredStopNotice(dataRoot, binding, envelope, now)) return {};
        throw error;
      }
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
    return degradedOutput(event, reason, rules);
  }
}
