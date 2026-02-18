#!/usr/bin/env node
// ============================================================================
// PROMPT CAPTURE - UserPromptSubmit hook (Node.js - cross-platform)
// Captures markers from last response + estimates context usage
// Must be FAST (<2s) - fires on every prompt
// ============================================================================

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR || '.';
const MEMORY_BASE = path.join(PROJECT_DIR, '.claude-memory');
const TIMESTAMP = new Date().toTimeString().slice(0, 5);

// Context estimation thresholds
const CONTEXT_LIMIT = 1000000;
const WARN_BYTES = 700000;
const CRITICAL_BYTES = 850000;
const EMERGENCY_BYTES = 950000;

function exists(p) { try { fs.accessSync(p); return true; } catch { return false; } }
function readFile(p) { try { return fs.readFileSync(p, 'utf8'); } catch { return ''; } }
function appendFile(p, text) { try { fs.appendFileSync(p, text); } catch {} }

// Read stdin (hook input)
function readStdin() {
  return new Promise(resolve => {
    let data = '';
    const timer = setTimeout(() => resolve(data || '{}'), 1000);
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => { data += chunk; });
    process.stdin.on('end', () => { clearTimeout(timer); resolve(data || '{}'); });
    process.stdin.on('error', () => { clearTimeout(timer); resolve('{}'); });
    // If stdin is not a pipe, resolve immediately
    if (process.stdin.isTTY) { clearTimeout(timer); resolve('{}'); }
  });
}

// Read last N lines of a file efficiently
function tailLines(filePath, n) {
  try {
    const content = fs.readFileSync(filePath, 'utf8');
    const lines = content.split('\n');
    return lines.slice(-n);
  } catch { return []; }
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
      const dirs = fs.readdirSync(dateDir)
        .filter(d => d.startsWith('session-'))
        .sort((a, b) => parseInt(a.replace('session-', '')) - parseInt(b.replace('session-', '')));
      if (dirs.length > 0) sessionPath = path.join(dateDir, dirs[dirs.length - 1]);
    } catch {}
  }

  if (!sessionPath) {
    process.stdout.write('{"suppressOutput": true}');
    process.exit(0);
  }

  // ============================================================================
  // MARKER AUTO-CAPTURE from last assistant response
  // ============================================================================
  let jsonlFile = '';
  if (transcriptPath && exists(transcriptPath)) {
    jsonlFile = transcriptPath;
  } else {
    // Fallback: find latest JSONL
    const claudeProjects = path.join(process.env.HOME || process.env.USERPROFILE || '', '.claude', 'projects');
    if (exists(claudeProjects)) {
      try {
        const memMd = path.join(sessionPath, 'memory.md');
        const memTime = exists(memMd) ? fs.statSync(memMd).mtimeMs : 0;
        // Search for recent JSONL files
        const findJsonl = (dir) => {
          const results = [];
          try {
            for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
              const full = path.join(dir, entry.name);
              if (entry.isDirectory()) results.push(...findJsonl(full));
              else if (entry.name.endsWith('.jsonl')) {
                try {
                  if (fs.statSync(full).mtimeMs > memTime) results.push(full);
                } catch {}
              }
            }
          } catch {}
          return results;
        };
        const jsonls = findJsonl(claudeProjects);
        if (jsonls.length > 0) jsonlFile = jsonls[0];
      } catch {}
    }
  }

  if (jsonlFile && exists(jsonlFile)) {
    // Get last 50 lines, find last assistant response
    const lines = tailLines(jsonlFile, 50);
    let lastResponse = '';

    for (let i = lines.length - 1; i >= 0; i--) {
      try {
        const entry = JSON.parse(lines[i]);
        if (entry.type === 'assistant' && entry.message?.content) {
          const content = entry.message.content;
          if (Array.isArray(content)) {
            lastResponse = content
              .filter(c => c.type === 'text' && c.text)
              .map(c => c.text)
              .join('\n');
          }
          break;
        }
      } catch {}
    }

    if (lastResponse) {
      const responseLines = lastResponse.split('\n');

      // [!] -> facts.md
      const facts = responseLines.filter(l => /^\[!\]\s*/.test(l)).slice(0, 5);
      for (const line of facts) {
        const text = line.replace(/^\[!\]\s*/, '');
        appendFile(path.join(sessionPath, 'facts.md'), `\n## ${TIMESTAMP} - ${text}\n`);
      }

      // [*] -> context.md
      const contexts = responseLines.filter(l => /^\[\*\]\s*/.test(l)).slice(0, 5);
      for (const line of contexts) {
        const text = line.replace(/^\[\*\]\s*/, '');
        appendFile(path.join(sessionPath, 'context.md'), `\n## ${TIMESTAMP} - ${text}\n`);
      }

      // [>] -> intent.md
      const intents = responseLines.filter(l => /^\[>\]\s*/.test(l)).slice(0, 5);
      for (const line of intents) {
        const text = line.replace(/^\[>\]\s*/, '');
        appendFile(path.join(sessionPath, 'intent.md'), `\n## ${TIMESTAMP} - ${text}\n`);
      }

      // [i] -> memory.md
      const infos = responseLines.filter(l => /^\[i\]\s*/.test(l)).slice(0, 5);
      for (const line of infos) {
        const text = line.replace(/^\[i\]\s*/, '');
        appendFile(path.join(sessionPath, 'memory.md'), `\n## ${TIMESTAMP} - ${text}\n`);
      }
    }

    // ===========================================================================
    // AUTO-CHECKPOINT (every ~10 prompts — crash insurance)
    // ===========================================================================
    const counterFile = path.join(MEMORY_BASE, 'prompt-counter');
    let promptCount = 0;
    try { promptCount = parseInt(readFile(counterFile)) || 0; } catch {}
    promptCount++;
    try { fs.writeFileSync(counterFile, String(promptCount)); } catch {}

    const AUTO_CHECKPOINT_INTERVAL = 10;
    if (promptCount % AUTO_CHECKPOINT_INTERVAL === 0) {
      const mciFile = path.join(sessionPath, 'memory.mci');
      // Only auto-checkpoint if there are marker files with content
      const getLastEntry = (file) => {
        const content = readFile(file);
        const matches = content.match(/^## .+/gm);
        if (matches && matches.length > 0) return matches[matches.length - 1].replace(/^## [\d:]+ - /, '');
        return '';
      };

      const latestFact = getLastEntry(path.join(sessionPath, 'facts.md'));
      const latestContext = getLastEntry(path.join(sessionPath, 'context.md'));
      const latestIntent = getLastEntry(path.join(sessionPath, 'intent.md'));

      // Also extract from JSONL if markers are empty
      let jFact = '', jContext = '', jIntent = '';
      if (!latestFact && !latestContext && !latestIntent) {
        const recentLines = tailLines(jsonlFile, 200);
        let lastUserMsgs = [];
        let toolNames = {};
        for (const line of recentLines) {
          try {
            const entry = JSON.parse(line);
            if (entry.type === 'user') {
              const c = entry.message?.content;
              let text = typeof c === 'string' ? c : (Array.isArray(c) ? c.filter(b => b.type === 'text').map(b => b.text).join(' ') : '');
              if (text) lastUserMsgs.push(text.slice(0, 80));
            }
            if (entry.type === 'assistant' && Array.isArray(entry.message?.content)) {
              for (const block of entry.message.content) {
                if (block.type === 'tool_use') toolNames[block.name] = (toolNames[block.name] || 0) + 1;
              }
            }
          } catch {}
        }
        const topTools = Object.entries(toolNames).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([n]) => n).join(', ');
        jFact = `[AUTO] Prompt #${promptCount}. Tools: ${topTools || 'none'}`;
        jContext = `User topics: ${lastUserMsgs.slice(-3).join(' | ').slice(0, 150)}`;
        jIntent = 'Continue from last user message.';
      }

      const cpMemory = latestFact || jFact || `[AUTO] Checkpoint at prompt #${promptCount}`;
      const cpContext = latestContext || jContext || `Session in progress at ${TIMESTAMP}`;
      const cpIntent = latestIntent || jIntent || 'Continue current work.';

      appendFile(mciFile, `
--- [AUTO] Checkpoint @ ${TIMESTAMP} (prompt #${promptCount}) ---
Memory: ${cpMemory}
Context: ${cpContext}
Intent: ${cpIntent}
`);
    }

    // ===========================================================================
    // CONTEXT ESTIMATION
    // ===========================================================================
    let contextWarning = '';
    try {
      const totalSize = fs.statSync(jsonlFile).size;
      let currentBytes = totalSize;

      // Find last summary/compact marker
      const allLines = tailLines(jsonlFile, 2000);
      let summaryOffset = 0;
      for (let i = allLines.length - 1; i >= 0; i--) {
        try {
          const entry = JSON.parse(allLines[i]);
          if (entry.type === 'summary') {
            // Estimate offset
            summaryOffset = allLines.slice(0, i + 1).join('\n').length;
            break;
          }
        } catch {}
      }
      if (summaryOffset > 0) currentBytes = totalSize - summaryOffset;

      const estPercent = Math.min(100, Math.floor(currentBytes * 100 / CONTEXT_LIMIT));
      const remaining = 100 - estPercent;

      const mciFile = path.join(sessionPath, 'memory.mci');
      let mciEntries = 0;
      if (exists(mciFile)) {
        mciEntries = (readFile(mciFile).match(/^Memory:/gm) || []).length;
      }

      if (currentBytes >= EMERGENCY_BYTES) {
        contextWarning = `[PC] EMERGENCY: ~${remaining}% context remaining. Auto-compact IMMINENT. Write [PC] to ${mciFile} NOW. (.mci entries: ${mciEntries})`;
      } else if (currentBytes >= CRITICAL_BYTES) {
        contextWarning = `[PC] WARNING: ~${remaining}% context remaining. Save [PC] entry to ${mciFile} with Memory/Context/Intent. (.mci entries: ${mciEntries})`;
      } else if (currentBytes >= WARN_BYTES) {
        contextWarning = `[i] Context checkpoint: ~${remaining}% remaining. Consider saving progress to .mci.`;
      }
    } catch {}

    if (contextWarning) {
      process.stdout.write(JSON.stringify({
        hookSpecificOutput: { additionalContext: contextWarning }
      }));
    } else {
      process.stdout.write('{"suppressOutput": true}');
    }
  } else {
    process.stdout.write('{"suppressOutput": true}');
  }

  process.exit(0);
}

main().catch(() => {
  process.stdout.write('{"suppressOutput": true}');
  process.exit(0);
});
