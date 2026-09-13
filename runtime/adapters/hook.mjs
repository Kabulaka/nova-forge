import fs from "node:fs";
import path from "node:path";
import { buildRecoveryContext } from "../core/capsule.mjs";
import { INJECTION_CHARACTER_LIMIT } from "../core/constants.mjs";
import { issueScopeProof } from "../core/scope-proof.mjs";
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
  injectCompletedCompactionBeforePrompt,
  markEvent,
  recordInjectedCompaction,
  recordResumeInjection,
  startSession,
} from "../core/state-machine.mjs";
import {
  claimStopDiagnostic,
  claimUncoveredStopNotice,
  clearStopDiagnostics,
} from "../core/storage.mjs";
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

function checkpointTurnContext(host) {
  const toolNames =
    host === "codex"
      ? "mcp__nova_checkpoint__nova_checkpoint_get and mcp__nova_checkpoint__nova_checkpoint_save"
      : "the available plugin MCP tools whose full names end in __nova_checkpoint_get and __nova_checkpoint_save";
  return (
    "<nova-checkpoint-turn>\n" +
    "Mandatory before ending this user turn: first finish every non-checkpoint tool call, " +
    `including reading or hashing control documents, then call ${toolNames}. Use the complete ` +
    "host-exposed MCP name; a prefixed name is the checkpoint tool, not evidence that the tool is " +
    "unavailable. After the first get, use only the matching checkpoint save/get tools. If " +
    "dirty=true, save a complete recovery task capsule for its current eventWatermark. Every " +
    "authority value is exactly an object with value, authorityState, and source; objective, " +
    "stage, and nextAction are authority objects, never strings. Every collection field is a JSON " +
    "array (use [] only when it is truly empty). Save uses exactly the top-level keys " +
    "idempotencyKey, coveredEventWatermark, taskCapsule, and controlDocuments; never send " +
    "eventWatermark. taskCapsule uses exactly objective, stage, confirmedDecisions, exclusions, " +
    "delegatedScope, currentQuestion, unresolvedDeltas, stageProjection, activeDeliveryScope, " +
    "evidence, fileState, commitState, and nextAction. currentQuestion is one authority object or " +
    "null. Do not rename them to delegationScope, candidateIdentities, currentQuestions, files, or " +
    "commits. authorityState is exactly one of user-confirmed, delegated-ai-candidate, " +
    "verified-evidence, explicitly-excluded, or pending; never use confirmed. Projection item " +
    "states are strict: inheritedContracts=user-confirmed, stageEvidence=verified-evidence, " +
    "stageDecisions=delegated-ai-candidate, unresolvedDeltas=pending; resolutionBasis is one of " +
    "user-confirmed, verified-evidence, delegated-ai-candidate, or explicitly-excluded and never " +
    "pending; use [] when no correctly " +
    "typed item exists. stageProjection " +
    "contains exactly the five " +
    "array fields inheritedContracts, stageEvidence, stageDecisions, unresolvedDeltas, and " +
    "resolutionBasis. Then call checkpoint get again and verify dirty=false and " +
    "coveredEventWatermark equals eventWatermark. If the " +
    "checkpoint tools are unavailable or one repair attempt fails, continue the response with the " +
    "incomplete state visible; do not loop, fabricate coverage, or rely on the Stop hook to repair it.\n" +
    "</nova-checkpoint-turn>"
  );
}

function completedCompactionContext(
  rules,
  recoveryEnvelope,
  host,
  limit = INJECTION_CHARACTER_LIMIT,
) {
  const suffix = `\n\n${checkpointTurnContext(host)}`;
  const recoveryLimit = limit - suffix.length;
  if (recoveryLimit < 0) {
    throw new NovaError("INJECTION_LIMIT", "checkpoint turn instructions exceed host injection limit");
  }
  const context = `${buildRecoveryContext(rules, recoveryEnvelope, recoveryLimit)}${suffix}`;
  if (context.length > limit) {
    throw new NovaError("INJECTION_LIMIT", "completed compaction context exceeds host injection limit");
  }
  return context;
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

function checkpointToolName(host, toolName) {
  if (!isOwnCheckpointTool(host, toolName)) return null;
  return toolName.endsWith("_get") ? "nova_checkpoint_get" : "nova_checkpoint_save";
}

function proofOutput(input, scopeProof) {
  const toolInput = input.tool_input ?? {};
  if (toolInput === null || typeof toolInput !== "object" || Array.isArray(toolInput)) {
    throw new NovaError("INVALID_TOOL_INPUT", "checkpoint tool input must be a JSON object");
  }
  return {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "allow",
      updatedInput: {
        ...toolInput,
        scopeProof,
      },
    },
  };
}

function markLifecycleEvent(dataRoot, binding, eventIdentifier, host, environment, now) {
  try {
    markEvent(dataRoot, binding, undefined, eventIdentifier, { now });
    return null;
  } catch (error) {
    if (error?.code !== "CHECKPOINT_MISSING") throw error;
  }

  const { pluginRoot, legacyRoots } = resolvePluginPaths(environment, host);
  const pluginVersion = readPluginVersion(pluginRoot);
  bootstrapStateRoot({ environment, host, dataRoot, legacyRoots, now });
  startSession(dataRoot, binding, pluginVersion, "startup", { now });
  markEvent(dataRoot, binding, pluginVersion, eventIdentifier, { now });
  return pluginRoot;
}

export function handleHook(input, environment = process.env, options = {}) {
  const event = input?.hook_event_name;
  let rules;
  let dataRoot;
  let binding;
  let now;
  try {
    if (input === null || typeof input !== "object" || Array.isArray(input)) {
      throw new NovaError("INVALID_HOOK_INPUT", "hook input must be a JSON object");
    }
    const host = detectHost(environment);
    binding = trustedBinding(host, input);
    now = options.now ?? Date.now();
    dataRoot = resolveNovaHome(environment);
    if (event === "SessionStart") {
      const pluginRoot = resolvePluginRoot(environment);
      const pluginVersion = readPluginVersion(pluginRoot);
      rules = fs.readFileSync(path.join(pluginRoot, "codex", "AGENTS.global.md"), "utf8");
      const { legacyRoots } = resolvePluginPaths(environment, host);
      bootstrapStateRoot({ environment, host, dataRoot, legacyRoots, now });
      const source = input.source;
      if (!["startup", "resume", "clear", "compact"].includes(source)) {
        throw new NovaError("UNSUPPORTED_SESSION_SOURCE", `unsupported SessionStart source ${source}`);
      }
      startSession(dataRoot, binding, pluginVersion, source, { now });
      let context;
      let recoveryWarning;
      if (source === "resume" || source === "compact") {
        const loaded = getCheckpoint(dataRoot, binding, { now });
        try {
          assertCovered(loaded.envelope);
          const claudeCompactPending =
            source === "compact" &&
            host === "claude-code" &&
            loaded.envelope.compactionHandshake.status === "frozen";
          if (claudeCompactPending) {
            context = buildRecoveryContext(rules, { taskCapsule: null });
          } else {
            context = buildRecoveryContext(rules, loaded.envelope);
          }
          if (source === "compact" && !claudeCompactPending) {
            recordInjectedCompaction(dataRoot, binding, pluginVersion, { now });
          } else {
            if (source === "resume") {
              recordResumeInjection(dataRoot, binding, pluginVersion, { now });
            }
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
      return contextOutput(event, context, recoveryWarning);
    }

    if (event === "PreToolUse") {
      const toolName = checkpointToolName(host, input.tool_name);
      if (toolName === null) return {};
      const scopeProof = issueScopeProof(
        dataRoot,
        {
          ...binding,
          toolName,
          toolUseId: input.tool_use_id,
        },
        { now },
      );
      return proofOutput(input, scopeProof);
    }
    if (event === "UserPromptSubmit") {
      const promptEventId = eventId(host, input);
      if (host === "claude-code") {
        let loaded;
        try {
          loaded = getCheckpoint(dataRoot, binding, { now });
        } catch {
          loaded = null;
        }
        if (
          loaded?.currentValid !== false &&
          loaded?.envelope.compactionHandshake.status === "completed"
        ) {
          const pluginRoot = resolvePluginRoot(environment);
          rules = fs.readFileSync(path.join(pluginRoot, "codex", "AGENTS.global.md"), "utf8");
          const injected = injectCompletedCompactionBeforePrompt(
            dataRoot,
            binding,
            readPluginVersion(pluginRoot),
            promptEventId,
            {
              now,
              prepareInjection: (recoveryEnvelope) =>
                completedCompactionContext(
                  rules,
                  recoveryEnvelope,
                  host,
                  options.injectionLimit ?? INJECTION_CHARACTER_LIMIT,
                ),
            },
          );
          return contextOutput(event, injected.result.preparedContext);
        }
      }
      const latePluginRoot = markLifecycleEvent(
        dataRoot,
        binding,
        promptEventId,
        host,
        environment,
        now,
      );
      if (latePluginRoot !== null) {
        rules = fs.readFileSync(path.join(latePluginRoot, "codex", "AGENTS.global.md"), "utf8");
        return contextOutput(
          event,
          `${buildRecoveryContext(rules, { taskCapsule: null })}\n\n${checkpointTurnContext(host)}`,
        );
      }
      return contextOutput(event, checkpointTurnContext(host));
    }
    if (event === "PostToolUse") {
      if (!isOwnCheckpointTool(host, input.tool_name)) {
        markLifecycleEvent(
          dataRoot,
          binding,
          eventId(host, input),
          host,
          environment,
          now,
        );
      }
      return {};
    }
    if (event === "Stop") {
      const loaded = getCheckpoint(dataRoot, binding, { now });
      if (loaded.source === "backup" && loaded.currentValid === false) {
        throw new NovaError(
          "CHECKPOINT_RECOVERED_FROM_BACKUP",
          "current checkpoint is invalid; backup is preserved but is not current authority",
        );
      }
      const { envelope } = loaded;
      try {
        assertCovered(envelope);
      } catch (error) {
        if (error?.code !== "CHECKPOINT_NOT_COVERED") throw error;
        if (!claimUncoveredStopNotice(dataRoot, binding, envelope, now)) return {};
        throw error;
      }
      clearStopDiagnostics(dataRoot, binding);
      return {};
    }
    if (event === "PreCompact") {
      freezeCompaction(dataRoot, binding, undefined, input.trigger, { now });
      return {};
    }
    if (event === "PostCompact") {
      completeCompaction(dataRoot, binding, undefined, input.trigger, { now });
      return {};
    }
    throw new NovaError("UNSUPPORTED_HOOK_EVENT", `unsupported hook event ${event}`);
  } catch (error) {
    if (event === "Stop" && dataRoot && binding) {
      try {
        if (!claimStopDiagnostic(dataRoot, binding, error, now ?? Date.now())) return {};
      } catch {
        // A diagnostic write failure must not block the host or hide the original warning.
      }
    }
    const reason = `Nova checkpoint safety gate: ${redactError(error)}`;
    return degradedOutput(event, reason, rules);
  }
}
