#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function repositorySlug(repository) {
  const value = typeof repository === "string" ? repository : repository?.url;
  const match = String(value ?? "").match(/github\.com[/:]([^/]+\/[^/#]+?)(?:\.git)?$/);
  return match?.[1] ?? null;
}

export function validateReleaseNotes({ root = scriptRoot, tag } = {}) {
  const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  const expectedTag = `v${packageJson.version}`;
  const releaseTag = tag ?? expectedTag;
  const notesPath = path.join(root, "docs", "release-notes", `${releaseTag}.md`);
  const errors = [];

  if (!/^v\d+\.\d+\.\d+$/.test(releaseTag)) {
    errors.push(`release tag must be SemVer with a v prefix: ${releaseTag}`);
  }
  if (releaseTag !== expectedTag) {
    errors.push(`release tag ${releaseTag} does not match package version ${expectedTag}`);
  }
  if (!fs.existsSync(notesPath)) {
    errors.push(`release notes are missing: ${path.relative(root, notesPath)}`);
    return { errors, notesPath, releaseTag };
  }

  const notes = fs.readFileSync(notesPath, "utf8");
  const slug = repositorySlug(packageJson.repository);
  const requiredHeadings = ["Overview", "Highlights", "Installation", "Requirements", "Upgrade Notes"];

  if (!notes.startsWith(`# Nova Forge ${releaseTag}\n`)) {
    errors.push(`release notes must start with \"# Nova Forge ${releaseTag}\"`);
  }
  for (const heading of requiredHeadings) {
    if (!new RegExp(`^## ${heading}$`, "m").test(notes)) {
      errors.push(`release notes are missing required heading: ${heading}`);
    }
  }
  if (!slug) {
    errors.push("package repository must be a GitHub repository");
  } else {
    const codexCommand = `codex plugin marketplace add ${slug} --ref ${releaseTag}`;
    if (!notes.includes(codexCommand)) {
      errors.push(`release notes are missing pinned Codex install command: ${codexCommand}`);
    }
    const changelogPrefix = `**Full Changelog**: https://github.com/${slug}/`;
    const escapedTag = releaseTag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const changelogPattern = new RegExp(
      `^${changelogPrefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?:commits/${escapedTag}|compare/[^\\s]+\\.\\.\\.${escapedTag})$`,
      "m",
    );
    if (!changelogPattern.test(notes)) {
      errors.push(`release notes need a baseline or comparison changelog ending at ${releaseTag}`);
    }
    for (const command of [`/plugin marketplace add ${slug}`, `/plugin install ${packageJson.name}@${packageJson.name}`]) {
      if (!notes.includes(command)) {
        errors.push(`release notes are missing Claude Code install command: ${command}`);
      }
    }
  }
  if (/(?:\bTODO\b|\bTBD\b|<CHANGE_ME>)/i.test(notes)) {
    errors.push("release notes contain an unresolved placeholder");
  }
  if (!notes.endsWith("\n")) {
    errors.push("release notes must end with a newline");
  }

  return { errors, notesPath, releaseTag };
}

function parseTag(argv) {
  if (argv.length === 0) return undefined;
  if (argv.length === 2 && argv[0] === "--tag") return argv[1];
  throw new Error("usage: validate-release-notes.mjs [--tag vX.Y.Z]");
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (isMain) {
  try {
    const result = validateReleaseNotes({ tag: parseTag(process.argv.slice(2)) });
    if (result.errors.length) {
      result.errors.forEach((error) => process.stderr.write(`ERROR: ${error}\n`));
      process.exitCode = 1;
    } else {
      process.stdout.write(`PASS: ${path.relative(scriptRoot, result.notesPath)} matches ${result.releaseTag}\n`);
    }
  } catch (error) {
    process.stderr.write(`ERROR: ${error.message}\n`);
    process.exitCode = 1;
  }
}
