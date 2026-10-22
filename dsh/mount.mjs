import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const skillNames = [
  "nova-requirements", "nova-architecture", "nova-development", "nova-review", "nova-commit",
];

export async function mountNova(ctx, skillPlugin, hooksPlugin, root = packageRoot) {
  const pluginRoot = path.resolve(root);
  // The official bridge fails open on missing config. A broken installation must
  // instead fail visibly before contributing any partial Nova registration.
  for (const relative of [
    "hooks/run.mjs", "hooks/hooks.json", "codex/AGENTS.global.md",
    ...skillNames.map((name) => `skills/${name}/SKILL.md`),
    "skills/nova-requirements/assets/PRODUCT_REQUIREMENTS.template.md",
    "skills/nova-requirements/references/examples/AI_GATEWAY_REQUIREMENTS.md",
    "skills/nova-architecture/assets/PROJECT_BLUEPRINT.template.md",
    "skills/nova-development/assets/DESIGN.template.md",
    "skills/nova-development/references/conversation-sop.md",
    "skills/nova-development/references/reference-research-sop.md",
    "skills/nova-development/references/design-document-standard.md",
  ]) {
    try {
      if (!fs.statSync(path.join(pluginRoot, relative)).isFile()) throw new Error();
      fs.accessSync(path.join(pluginRoot, relative), fs.constants.R_OK);
    } catch {
      throw new Error(`Nova DSH installation is incomplete: ${relative}`);
    }
  }
  const hooksPath = path.join(pluginRoot, "hooks/hooks.json");
  const hooks = JSON.parse(fs.readFileSync(hooksPath, "utf8"));
  const groups = hooks?.hooks?.SessionStart;
  if (!Array.isArray(groups) || !groups.length) {
    throw new Error("Nova DSH installation has no SessionStart hook");
  }
  const uncovered = new Set(["startup", "resume", "clear", "compact"]);
  for (const group of groups) {
    if (!group || !Array.isArray(group.hooks) || !group.hooks.length ||
        group.hooks.some((hook) => !hook || hook.type !== "command" ||
          typeof hook.command !== "string" || !hook.command.trim()) ||
        (group.matcher !== undefined && typeof group.matcher !== "string")) {
      throw new Error("Nova DSH installation has an invalid SessionStart hook");
    }
    const matcher = group.matcher;
    const matchAll = matcher === undefined || matcher === "" || matcher === "*";
    // Match the official Claude bridge dialect: word/pipe patterns are exact
    // alternatives; other patterns are unanchored regular expressions.
    const literal = !matchAll && /^[A-Za-z0-9_|]+$/.test(matcher);
    let regex;
    if (!matchAll && !literal) {
      try { regex = new RegExp(matcher); }
      catch { throw new Error("Nova DSH installation has an invalid SessionStart matcher"); }
    }
    for (const source of uncovered) {
      if (matchAll || (literal ? matcher.split("|").includes(source) : regex.test(source))) {
        uncovered.delete(source);
      }
    }
  }
  if (uncovered.size) {
    throw new Error(`Nova DSH installation has uncovered SessionStart sources: ${[...uncovered].join(", ")}`);
  }

  const shell = ctx.shell;
  const hookScope = ctx.isolate("shell");
  // pluginRoot substitutes command text in the official bridge, but does not
  // export it. Scope this environment to bridge requests; never mutate process.env
  // or the host shell (which other plugins and profiles may share).
  await hookScope.plugin({
    name: "nova-hook-shell",
    apply(child) {
      child.provide("shell", {
        resolve(request) {
          return shell.resolve({
            ...request,
            env: { ...request.env, NOVA_PLUGIN_ROOT: pluginRoot, NOVA_DSH_ROOT: pluginRoot },
          });
        },
        execute(spec) { return shell.execute(spec); },
      });
    },
  });
  await hookScope.plugin(hooksPlugin, { configPath: hooksPath, pluginRoot });
  await ctx.plugin(skillPlugin, {
    providerName: "nova-forge",
    includeDefaultRoots: false,
    customSkillDirs: [path.join(pluginRoot, "skills")],
    watch: false,
  });
}
