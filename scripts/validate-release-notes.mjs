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

function stripHtmlComments(text) {
  let result = "";
  let cursor = 0;
  while (cursor < text.length) {
    const start = text.indexOf("<!--", cursor);
    if (start === -1) return result + text.slice(cursor);
    result += text.slice(cursor, start);
    const end = text.indexOf("-->", start + 4);
    const commentEnd = end === -1 ? text.length : end + 3;
    result += text
      .slice(start, commentEnd)
      .replace(/[^\n]/g, " ");
    cursor = commentEnd;
  }
  return result;
}

function markdownStructure(text) {
  const lines = stripHtmlComments(text).split("\n");
  const headings = [];
  const visibleLines = [];
  let fence = null;

  lines.forEach((line, index) => {
    if (fence) {
      const closing = line.match(/^ {0,3}(`{3,}|~{3,})[ \t]*$/);
      const candidate = closing?.[1];
      if (candidate && candidate[0] === fence.character && candidate.length >= fence.length) {
        fence = null;
      }
      return;
    }

    const opening = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    const candidate = opening?.[1];
    const info = opening?.[2] ?? "";
    if (candidate && !(candidate[0] === "`" && info.includes("`"))) {
      fence = { character: candidate[0], length: candidate.length };
      return;
    }

    visibleLines.push(line);
    const heading = line.match(/^##\s+(.+?)\s*$/);
    if (heading) headings.push({ name: heading[1], line: index });
  });

  const sections = new Map();
  headings.forEach((heading, index) => {
    const end = headings[index + 1]?.line ?? lines.length;
    const values = sections.get(heading.name) ?? [];
    values.push(lines.slice(heading.line + 1, end).join("\n"));
    sections.set(heading.name, values);
  });
  return { sections, visibleLines };
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
  const structure = markdownStructure(notes);
  const requiredHeadings = ["Overview", "Highlights", "Installation", "Requirements", "Upgrade Notes"];

  const expectedTitle = `# Nova Forge ${releaseTag}`;
  if (!notes.startsWith(`${expectedTitle}\n`) && !notes.startsWith(`${expectedTitle}\r\n`)) {
    errors.push(`release notes must start with \"# Nova Forge ${releaseTag}\"`);
  }
  for (const heading of requiredHeadings) {
    const matches = structure.sections.get(heading) ?? [];
    if (matches.length === 0) {
      errors.push(`release notes are missing required heading: ${heading}`);
    } else if (matches.length > 1) {
      errors.push(`release notes contain duplicate required heading: ${heading}`);
    }
  }
  if (!slug) {
    errors.push("package repository must be a GitHub repository");
  } else {
    const codexCommand = `codex plugin marketplace add ${slug} --ref ${releaseTag}`;
    const installation = structure.sections.get("Installation")?.[0] ?? "";
    if (!installation.includes(codexCommand)) {
      errors.push(`release notes are missing pinned Codex install command: ${codexCommand}`);
    }
    const changelogPrefix = `**Full Changelog**: https://github.com/${slug}/`;
    const escapedTag = releaseTag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const changelogPattern = new RegExp(
      `^${changelogPrefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?:commits/${escapedTag}|compare/[^\\s]+\\.\\.\\.${escapedTag})$`,
      "m",
    );
    if (!structure.visibleLines.some((line) => changelogPattern.test(line))) {
      errors.push(`release notes need a baseline or comparison changelog ending at ${releaseTag}`);
    }
    for (const command of [`/plugin marketplace add ${slug}`, `/plugin install ${packageJson.name}@${packageJson.name}`]) {
      if (!installation.includes(command)) {
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
