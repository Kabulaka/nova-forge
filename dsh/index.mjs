import * as SkillFilesystem from "@deepseek-ai/dsh-skill-filesystem";
import * as HooksClaudeCode from "@deepseek-ai/dsh-hooks-claude-code";
import { mountNova } from "./mount.mjs";

// Cordis loads this namespace; a default export would hide inject from its loader.
export const name = "nova-forge";
export const inject = ["skills", "shell", "sessionProjections", "workingDirectory"];

export async function apply(ctx) {
  await mountNova(ctx, SkillFilesystem, HooksClaudeCode);
}
