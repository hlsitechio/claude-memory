#!/usr/bin/env node
// ============================================================================
// MCI v2 SESSION STOP — state.md snapshot + session summary (Node.js)
// Ensures session ends with valid .mci (snapshots state.md if available)
// Generates session-summary.md with tool stats and file list
// ============================================================================

const fs = require('fs');
const path = require('path');

const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR || '.';
const MEMORY_BASE = path.join(PROJECT_DIR, '.claude-memory');
const TIMESTAMP = new Date().toTimeString().slice(0, 8);

function exists(p) { try { fs.accessSync(p); return true; } catch { return false; } }
function readFile(p) { try { return fs.readFileSync(p, 'utf8'); } catch { return ''; } }
function appendFile(p, text) { try { fs.appendFileSync(p, text); } catch {} }

function tailLines(filePath, n) {
  try {
    const lines = fs.readFileSync(filePath, 'utf8').split('\n');
    return lines.slice(-n);
  } catch { return []; }
}

// Extract section from state.md
function extractSection(content, sectionName, maxChars = 2000) {
  const regex = new RegExp(`^## ${sectionName}\\s*$`, 'm');
  const match = content.match(regex);
  if (!match) return '';
  const startIdx = match.index + match[0].length;
  const rest = content.slice(startIdx);
  const nextHeader = rest.match(/^## /m);
  const section = nextHeader ? rest.slice(0, nextHeader.index) : rest;
  return section.trim().slice(0, maxChars);
}

function readStdin() {
  return new Promise(resolve => {
    let data = '';
    const timer = setTimeout(() => resolve(data || '{}'), 1000);
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => { data += chunk; });
    process.stdin.on('end', () => { clearTimeout(timer); resolve(data || '{}'); });
    process.stdin.on('error', () => { clearTimeout(timer); resolve('{}'); });
    if (process.stdin.isTTY) { clearTimeout(timer); resolve('{}'); }
  });
}

async function main() {
  const input = await readStdin();
  let hookInput = {};
  try { hookInput = JSON.parse(input); } catch {}

  const transcriptPath = hookInput?.hookInput?.transcriptPath || hookInput?.transcriptPath || '';

  // Find current session
  let sessionPath = '';
  const csFile = path.join(MEMORY_BASE, 'current-session');
  if (exists(csFile)) sessionPath = readFile(csFile).trim();

  if (!sessionPath || !exists(sessionPath)) {
    const sessionDate = new Date().toISOString().slice(0, 10);
    const dateDir = path.join(MEMORY_BASE, 'sessions', sessionDate);
    try {
      const dirs = fs.readdirSync(dateDir).filter(d => d.startsWith('session-')).sort();
      if (dirs.length > 0) sessionPath = path.join(dateDir, dirs[dirs.length - 1]);
    } catch {}
  }

  if (!sessionPath) {
    process.stdout.write('{"suppressOutput": true}');
    process.exit(0);
  }

  const mciFile = path.join(sessionPath, 'memory.mci');
  const stateFile = path.join(sessionPath, 'state.md');

  // Find JSONL
  let jsonlFile = '';
  if (transcriptPath && exists(transcriptPath)) {
    jsonlFile = transcriptPath;
  } else {
    const claudeProjects = path.join(process.env.HOME || process.env.USERPROFILE || '', '.claude', 'projects');
    if (exists(claudeProjects)) {
      const findJsonl = (dir) => {
        const results = [];
        try {
          for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) results.push(...findJsonl(full));
            else if (entry.name.endsWith('.jsonl')) results.push(full);
          }
        } catch {}
        return results;
      };
      const jsonls = findJsonl(claudeProjects);
      if (jsonls.length > 0) jsonlFile = jsonls[0];
    }
  }

  // ============================================================================
  // STEP 1: SNAPSHOT state.md TO .mci (v2 — primary approach)
  // ============================================================================
  let mciWritten = false;

  if (exists(stateFile)) {
    const stateContent = readFile(stateFile);
    if (stateContent.length > 200) {
      const goal = extractSection(stateContent, 'Goal', 1500);
      const progress = extractSection(stateContent, 'Progress', 2000);
      const findings = extractSection(stateContent, 'Findings', 2000);

      appendFile(mciFile, `
--- [STOP] state.md Snapshot @ ${TIMESTAMP} ---
Memory: GOAL: ${goal || 'No goal set'}
Context: PROGRESS: ${progress || 'No progress tracked'}
Intent: FINDINGS: ${findings || 'No findings yet'}
`);
      mciWritten = true;
    }
  }

  // ============================================================================
  // STEP 2: FALLBACK — Auto-generate from JSONL if no state.md
  // ============================================================================
  if (!mciWritten && jsonlFile && exists(jsonlFile)) {
    const lines = fs.readFileSync(jsonlFile, 'utf8').split('\n');
    let toolCounts = {};
    let filesTouched = new Set();
    let lastUserMsgs = [];
    let markerMemory = '';
    let markerIntent = '';

    for (const line of lines) {
      try {
        const entry = JSON.parse(line);
        if (entry.type === 'assistant' && Array.isArray(entry.message?.content)) {
          for (const block of entry.message.content) {
            if (block.type === 'tool_use') {
              toolCounts[block.name] = (toolCounts[block.name] || 0) + 1;
              if ((block.name === 'Write' || block.name === 'Edit') && block.input?.file_path) {
                filesTouched.add(block.input.file_path);
              }
            }
            if (block.type === 'text' && block.text) {
              for (const tl of block.text.split('\n')) {
                if (/^\[!\]/.test(tl)) markerMemory = tl.replace(/^\[!\]\s*/, '');
                if (/^\[>\]/.test(tl)) markerIntent = tl.replace(/^\[>\]\s*/, '');
              }
            }
          }
        }
        if (entry.type === 'user') {
          const content = entry.message?.content;
          let text = '';
          if (typeof content === 'string') text = content;
          else if (Array.isArray(content)) text = content.filter(c => c.type === 'text').map(c => c.text || '').join(' ');
          if (text) lastUserMsgs.push(text.slice(0, 100));
        }
      } catch {}
    }

    const topTools = Object.entries(toolCounts).sort((a, b) => b[1] - a[1]).slice(0, 5)
      .map(([name, count]) => `${count} ${name}`).join(', ');
    const files = [...filesTouched].slice(0, 10).join(', ');

    const stopMemory = markerMemory || `[STOP] Session ended. Tools: ${topTools || 'none'}. Files: ${files || 'none'}`;
    const stopContext = `Session ended at ${TIMESTAMP}. Last user topic: ${lastUserMsgs.slice(-3).join(' | ').slice(0, 150)}`;
    const stopIntent = markerIntent || 'Continue from last topic next session.';

    appendFile(mciFile, `
--- [STOP] Auto-Generated @ ${TIMESTAMP} ---
Memory: ${stopMemory}
Context: ${stopContext}
Intent: ${stopIntent}
`);
  }

  // ============================================================================
  // STEP 3: GENERATE SESSION SUMMARY
  // ============================================================================
  if (jsonlFile && exists(jsonlFile)) {
    const allLines = fs.readFileSync(jsonlFile, 'utf8').split('\n');
    let userCount = 0;
    let toolStats = {};
    let allFiles = new Set();

    for (const line of allLines) {
      try {
        const entry = JSON.parse(line);
        if (entry.type === 'user') userCount++;
        if (entry.type === 'assistant' && Array.isArray(entry.message?.content)) {
          for (const block of entry.message.content) {
            if (block.type === 'tool_use') {
              toolStats[block.name] = (toolStats[block.name] || 0) + 1;
              if ((block.name === 'Write' || block.name === 'Edit') && block.input?.file_path) {
                allFiles.add(block.input.file_path);
              }
            }
          }
        }
      } catch {}
    }

    const toolCount = Object.values(toolStats).reduce((a, b) => a + b, 0);
    const toolLines = Object.entries(toolStats).sort((a, b) => b[1] - a[1]).slice(0, 15)
      .map(([name, count]) => `  ${String(count).padStart(6)} ${name}`).join('\n');
    const fileLines = [...allFiles].slice(0, 20).join('\n');
    const startTime = readFile(path.join(sessionPath, 'memory.md')).match(/\d{2}:\d{2}/)?.[0] || 'unknown';
    const mciEntries = (readFile(mciFile).match(/^Memory:/gm) || []).length;

    const summary = `# Session Summary - ${new Date().toISOString().slice(0, 10)} ${TIMESTAMP}

## Duration
- Started: ${startTime}
- Ended: ${TIMESTAMP}

## Memory Status
- state.md: ${exists(stateFile) ? `EXISTS (${readFile(stateFile).length} bytes)` : 'MISSING'}
- MCI saved by: ${mciWritten ? 'state.md snapshot' : 'auto-generated from JSONL'}
- MCI entries: ${mciEntries}

## Stats
- User messages: ~${userCount}
- Tool calls: ${toolCount}

## Tools Used
${toolLines}

## Files Modified
${fileLines}
`;

    try { fs.writeFileSync(path.join(sessionPath, 'session-summary.md'), summary.slice(0, 8000)); } catch {}
  }

  // Update session log
  appendFile(path.join(sessionPath, 'memory.md'),
    `\n## ${TIMESTAMP} - SESSION ENDED [state.md: ${exists(stateFile) ? 'EXISTS' : 'MISSING'}]\n`);

  process.stdout.write('{"suppressOutput": true}');
  process.exit(0);
}

main().catch(() => {
  process.stdout.write('{"suppressOutput": true}');
  process.exit(0);
});
