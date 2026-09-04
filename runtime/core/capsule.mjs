import { INJECTION_CHARACTER_LIMIT, STAGE_PROJECTION_FIELDS } from "./constants.mjs";
import { NovaError } from "./util.mjs";

function safeJson(value) {
  return JSON.stringify(value).replace(/[<>&]/g, (character) => {
    if (character === "<") return "\\u003c";
    if (character === ">") return "\\u003e";
    return "\\u0026";
  });
}

function authorityLine(label, item) {
  return `- ${label}: ${safeJson(item)}`;
}

function appendRequired(lines, line, limit) {
  const candidate = [...lines, line].join("\n");
  if (candidate.length > limit) {
    throw new NovaError("INJECTION_LIMIT", `required recovery field does not fit: ${line.slice(0, 80)}`);
  }
  lines.push(line);
}

function appendArray(lines, label, values, limit, omitted, required) {
  values.forEach((item, index) => {
    const line = authorityLine(`${label}[${index}]`, item);
    if ([...lines, line].join("\n").length <= limit) lines.push(line);
    else if (required) appendRequired(lines, line, limit);
    else omitted.push(`${label}[${index}]`);
  });
}

export function buildRecoveryContext(rules, envelope, limit = INJECTION_CHARACTER_LIMIT) {
  const lines = ["<nova-static-rules>", rules.trim(), "</nova-static-rules>"];
  if (envelope.taskCapsule === null) {
    const text = lines.join("\n");
    if (text.length > limit) throw new NovaError("INJECTION_LIMIT", "static rules exceed host injection limit");
    return text;
  }
  const capsule = envelope.taskCapsule;
  appendRequired(lines, "<nova-recovery-capsule>", limit);
  appendRequired(lines, `generation: ${envelope.authorityGeneration}`, limit);
  appendRequired(lines, authorityLine("objective", capsule.objective), limit);
  appendRequired(lines, authorityLine("stage", capsule.stage), limit);
  appendArray(lines, "confirmedDecisions", capsule.confirmedDecisions, limit, [], true);
  appendArray(lines, "exclusions", capsule.exclusions, limit, [], true);
  appendArray(lines, "delegatedScope", capsule.delegatedScope, limit, [], true);
  if (capsule.currentQuestion !== null) {
    appendRequired(lines, authorityLine("currentQuestion", capsule.currentQuestion), limit);
  }
  appendArray(lines, "unresolvedDeltas", capsule.unresolvedDeltas, limit, [], true);
  for (const field of STAGE_PROJECTION_FIELDS) {
    appendArray(lines, `stageProjection.${field}`, capsule.stageProjection[field], limit, [], true);
  }
  appendArray(lines, "activeDeliveryScope", capsule.activeDeliveryScope, limit, [], true);
  appendRequired(lines, authorityLine("nextAction", capsule.nextAction), limit);

  const omitted = [];
  appendArray(lines, "evidence", capsule.evidence, limit, omitted, false);
  appendArray(lines, "fileState", capsule.fileState, limit, omitted, false);
  appendArray(lines, "commitState", capsule.commitState, limit, omitted, false);
  envelope.controlDocuments.forEach((document, index) => {
    const line = `- controlDocuments[${index}]: ${safeJson(document)}`;
    if ([...lines, line].join("\n").length <= limit) lines.push(line);
    else omitted.push(`controlDocuments[${index}]`);
  });
  if (omitted.length) {
    const marker = `- omittedFields: ${omitted.join(", ")}`;
    appendRequired(lines, marker, limit);
  }
  appendRequired(lines, "</nova-recovery-capsule>", limit);
  return lines.join("\n");
}
