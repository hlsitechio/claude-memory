#!/usr/bin/env node
// ============================================================================
// PRE-COMPACT - Safety net before auto-compact (Node.js - cross-platform)
// 3-tier fallback: .mci valid → assemble from markers → emergency from JSONL
// ============================================================================

const fs = require('fs');
const path = require('path');

const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR || '.';
const MEMORY_BASE = path.join(PROJECT_DIR, '.claude-memory');
const TIMESTAMP = new Date().toTimeString().slice(0, 8); // HH:MM:SS

function exists(p) { try { fs.accessSync(p); return true; } catch { return false; } }
function readFile(p) { try { return fs.readFileSync(p, 'utf8'); } catch { return ''; } }
function appendFile(p, text) { try { fs.appendFileSync(p, text); } catch {} }
function mkdirp(dir) { fs.mkdirSync(dir, { recursive: true }); }

function tailLines(filePath, n) {
  try {
    const lines = fs.readFileSync(filePath, 'utf8').split('\n');
    return lines.slice(-n);
  } catch { return []; }
}

// Read stdin
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
    sessionPath = path.join(MEMORY_BASE, 'sessions', new Date().toISOString().slice(0, 10), 'session-1');
    mkdirp(sessionPath);
  }

  const mciFile = path.join(sessionPath, 'memory.mci');
  const compactFile = path.join(sessionPath, `compact-${TIMESTAMP.replace(/:/g, '-')}.md`);

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
  // STEP 1: CHECK IF .MCI IS ALREADY VALID
  // ============================================================================
  let mciValid = false;
  if (exists(mciFile)) {
    const content = readFile(mciFile);
    const hasMemory = /^Memory:/m.test(content);
    const hasContext = /^Context:/m.test(content);
    const hasIntent = /^Intent:/m.test(content);
    mciValid = hasMemory && hasContext && hasIntent;
  }

  // ============================================================================
  // STEP 2: ASSEMBLE FROM MARKER FILES
  // ============================================================================
  let assembled = false;

  if (!mciValid) {
    const getLastEntry = (file) => {
      const content = readFile(file);
      const matches = content.match(/^## .+/gm);
      if (matches && matches.length > 0) {
        return matches[matches.length - 1].replace(/^## [\d:]+ - /, '');
      }
      return '';
    };

    const latestFact = getLastEntry(path.join(sessionPath, 'facts.md'));
    const latestContext = getLastEntry(path.join(sessionPath, 'context.md'));
    const latestIntent = getLastEntry(path.join(sessionPath, 'intent.md'));

    if (latestFact || latestContext || latestIntent) {
      assembled = true;
      appendFile(mciFile, `
--- [PC] Auto-Assembled from marker files @ ${TIMESTAMP} ---
Memory: ${latestFact || 'No [!] markers captured this session'}
Context: ${latestContext || 'No [*] markers captured this session'}
Intent: ${latestIntent || 'No [>] markers captured this session'}
`);
    }
  }

  // ============================================================================
  // STEP 3: EMERGENCY FALLBACK FROM JSONL
  // ============================================================================
  if (!mciValid && !assembled && jsonlFile && exists(jsonlFile)) {
    const lines = tailLines(jsonlFile, 500);
    let toolCounts = {};
    let filesTouched = new Set();
    let lastUserMsgs = [];
    let markerLines = [];

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
              const textLines = block.text.split('\n');
              for (const tl of textLines) {
                if (/^\[!\]|^\[\*\]|^\[>\]/.test(tl)) markerLines.push(tl);
              }
            }
          }
        }
        if (entry.type === 'user') {
          const content = entry.message?.content;
          let text = '';
          if (typeof content === 'string') text = content;
          else if (Array.isArray(content)) {
            text = content.filter(c => c.type === 'text').map(c => c.text || '').join(' ');
          }
          if (text) lastUserMsgs.push(text.slice(0, 100));
        }
      } catch {}
    }

    const topTools = Object.entries(toolCounts).sort((a, b) => b[1] - a[1]).slice(0, 5)
      .map(([name, count]) => `${count} ${name}`).join(', ');
    const files = [...filesTouched].slice(0, 10).join(', ');
    const userContext = lastUserMsgs.slice(-5).join(' | ').slice(0, 200);

    let eMemory = `[EMERGENCY] Tools: ${topTools || 'none'}. Files: ${files || 'none'}`;
    let eContext = `User discussing: ${userContext}`;
    let eIntent = `Session interrupted by compact. Review ${path.basename(compactFile)} for raw conversation.`;

    // Override with marker data if found
    const lastMarkers = markerLines.slice(-20);
    const mFact = lastMarkers.filter(l => /^\[!\]/.test(l)).pop()?.replace(/^\[!\]\s*/, '');
    const mCtx = lastMarkers.filter(l => /^\[\*\]/.test(l)).pop()?.replace(/^\[\*\]\s*/, '');
    const mInt = lastMarkers.filter(l => /^\[>\]/.test(l)).pop()?.replace(/^\[>\]\s*/, '');
    if (mFact) eMemory = mFact;
    if (mCtx) eContext = mCtx;
    if (mInt) eIntent = mInt;

    appendFile(mciFile, `
--- [PC] EMERGENCY from JSONL @ ${TIMESTAMP} ---
Memory: ${eMemory}
Context: ${eContext}
Intent: ${eIntent}
`);
  }

  // ============================================================================
  // STEP 4: CREATE COMPACT BACKUP
  // ============================================================================
  if (jsonlFile && exists(jsonlFile)) {
    const lines = tailLines(jsonlFile, 500);
    let convo = [];
    let msgCount = 0;

    for (const line of lines) {
      try {
        const entry = JSON.parse(line);
        if (entry.type === 'user') {
          msgCount++;
          const content = entry.message?.content;
          let text = '';
          if (typeof content === 'string') text = content;
          else if (Array.isArray(content)) text = content.filter(c => c.type === 'text').map(c => c.text || '').join('\n');
          if (text) convo.push(`## USER:\n${text.slice(0, 500)}`);
        }
        if (entry.type === 'assistant' && Array.isArray(entry.message?.content)) {
          const parts = entry.message.content.map(c => {
            if (c.type === 'text' && c.text) return c.text.slice(0, 500);
            if (c.type === 'tool_use') return `[tool: ${c.name}]`;
            return '';
          }).filter(Boolean);
          if (parts.length) convo.push(`## CLAUDE:\n${parts.join('\n')}`);
        }
      } catch {}
    }

    const backup = `# Pre-Compact Backup - ${TIMESTAMP}
## MCI Status: ${mciValid ? 'VALID' : 'AUTO-GENERATED'}
## Messages: ~${msgCount}

## Recent Conversation
${convo.slice(-20).join('\n\n').slice(0, 6000)}`;

    try { fs.writeFileSync(compactFile, backup); } catch {}
  }

  // ============================================================================
  // STEP 5: SET COMPACT-PENDING MARKER
  // ============================================================================
  try {
    fs.writeFileSync(
      path.join(MEMORY_BASE, 'compact-pending'),
      `${TIMESTAMP}|${mciFile}|${mciValid ? 'valid' : 'emergency'}`
    );
  } catch {}

  // Update session log
  appendFile(path.join(sessionPath, 'memory.md'),
    `\n## ${TIMESTAMP} - PRE-COMPACT [MCI: ${mciValid ? 'SAVED' : 'EMERGENCY'}]\n`);

  process.stdout.write(`Pre-compact: MCI=${mciValid ? 'valid' : 'emergency'}`);
  process.exit(0);
}

main().catch(() => { process.exit(0); });
