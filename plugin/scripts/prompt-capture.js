#!/usr/bin/env node
// ============================================================================
// claude-memory v2 PROMPT CAPTURE — state.md health + context estimation (Node.js)
// Fires on every UserPromptSubmit — must be FAST (<2s)
// Also captures legacy markers + auto-checkpoints (backward compat)
// ============================================================================

const fs = require('fs');
const path = require('path');

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

function tailLines(filePath, n) {
  try {
    const content = fs.readFileSync(filePath, 'utf8');
    return content.split('\n').slice(-n);
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

  const stateFile = path.join(sessionPath, 'state.md');
  let warnings = [];

  // ============================================================================
  // STEP 1: state.md HEALTH CHECK (v2 — primary concern)
  // ============================================================================
  if (!exists(stateFile)) {
    warnings.push(`[!] state.md MISSING at ${stateFile} — Create it with Goal/Progress/Findings sections using Edit tool.`);
  } else {
    const stateSize = readFile(stateFile).length;
    if (stateSize < 200) {
      warnings.push(`[i] state.md is still template (~${stateSize}b). Update Goal/Progress/Findings with your current work using Edit tool.`);
    }
  }

  // ============================================================================
  // STEP 2: LEGACY MARKER AUTO-CAPTURE (backward compat)
  // ============================================================================
  let jsonlFile = '';
  if (transcriptPath && exists(transcriptPath)) {
    jsonlFile = transcriptPath;
  } else {
    const claudeProjects = path.join(process.env.HOME || process.env.USERPROFILE || '', '.claude', 'projects');
    if (exists(claudeProjects)) {
      try {
        const memMd = path.join(sessionPath, 'memory.md');
        const memTime = exists(memMd) ? fs.statSync(memMd).mtimeMs : 0;
        const findJsonl = (dir) => {
          const results = [];
          try {
            for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
              const full = path.join(dir, entry.name);
              if (entry.isDirectory()) results.push(...findJsonl(full));
              else if (entry.name.endsWith('.jsonl')) {
                try { if (fs.statSync(full).mtimeMs > memTime) results.push(full); } catch {}
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
    const lines = tailLines(jsonlFile, 50);
    let lastResponse = '';

    for (let i = lines.length - 1; i >= 0; i--) {
      try {
        const entry = JSON.parse(lines[i]);
        if (entry.type === 'assistant' && entry.message?.content) {
          const content = entry.message.content;
          if (Array.isArray(content)) {
            lastResponse = content.filter(c => c.type === 'text' && c.text).map(c => c.text).join('\n');
          }
          break;
        }
      } catch {}
    }

    if (lastResponse) {
      const responseLines = lastResponse.split('\n');

      for (const line of responseLines.filter(l => /^\[!\]\s*/.test(l)).slice(0, 5)) {
        appendFile(path.join(sessionPath, 'facts.md'), `\n## ${TIMESTAMP} - ${line.replace(/^\[!\]\s*/, '')}\n`);
      }
      for (const line of responseLines.filter(l => /^\[\*\]\s*/.test(l)).slice(0, 5)) {
        appendFile(path.join(sessionPath, 'context.md'), `\n## ${TIMESTAMP} - ${line.replace(/^\[\*\]\s*/, '')}\n`);
      }
      for (const line of responseLines.filter(l => /^\[>\]\s*/.test(l)).slice(0, 5)) {
        appendFile(path.join(sessionPath, 'intent.md'), `\n## ${TIMESTAMP} - ${line.replace(/^\[>\]\s*/, '')}\n`);
      }
      for (const line of responseLines.filter(l => /^\[i\]\s*/.test(l)).slice(0, 5)) {
        appendFile(path.join(sessionPath, 'memory.md'), `\n## ${TIMESTAMP} - ${line.replace(/^\[i\]\s*/, '')}\n`);
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

      // v2: Try state.md first for auto-checkpoint
      let checkpointed = false;
      if (exists(stateFile)) {
        const stateContent = readFile(stateFile);
        if (stateContent.length > 200) {
          const extractSection = (content, name, max = 1000) => {
            const re = new RegExp(`^## ${name}\\s*$`, 'm');
            const m = content.match(re);
            if (!m) return '';
            const rest = content.slice(m.index + m[0].length);
            const next = rest.match(/^## /m);
            return (next ? rest.slice(0, next.index) : rest).trim().slice(0, max);
          };
          const goal = extractSection(stateContent, 'Goal');
          const progress = extractSection(stateContent, 'Progress');
          const findings = extractSection(stateContent, 'Findings');

          appendFile(mciFile, `
--- [AUTO] state.md Checkpoint @ ${TIMESTAMP} (prompt #${promptCount}) ---
Memory: GOAL: ${goal || 'No goal set'}
Context: PROGRESS: ${progress || 'No progress tracked'}
Intent: FINDINGS: ${findings || 'No findings yet'}
`);
          checkpointed = true;
        }
      }

      // Fallback: marker-based checkpoint
      if (!checkpointed) {
        const getLastEntry = (file) => {
          const content = readFile(file);
          const matches = content.match(/^## .+/gm);
          if (matches && matches.length > 0) return matches[matches.length - 1].replace(/^## [\d:]+ - /, '');
          return '';
        };

        const latestFact = getLastEntry(path.join(sessionPath, 'facts.md'));
        const latestContext = getLastEntry(path.join(sessionPath, 'context.md'));
        const latestIntent = getLastEntry(path.join(sessionPath, 'intent.md'));

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

        appendFile(mciFile, `
--- [AUTO] Checkpoint @ ${TIMESTAMP} (prompt #${promptCount}) ---
Memory: ${latestFact || jFact || `[AUTO] Checkpoint at prompt #${promptCount}`}
Context: ${latestContext || jContext || `Session in progress at ${TIMESTAMP}`}
Intent: ${latestIntent || jIntent || 'Continue current work.'}
`);
      }
    }

    // ===========================================================================
    // CONTEXT ESTIMATION
    // ===========================================================================
    try {
      const totalSize = fs.statSync(jsonlFile).size;
      let currentBytes = totalSize;

      const allLines = tailLines(jsonlFile, 2000);
      let summaryOffset = 0;
      for (let i = allLines.length - 1; i >= 0; i--) {
        try {
          const entry = JSON.parse(allLines[i]);
          if (entry.type === 'summary') {
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

      // state.md status for warnings
      let stateStatus = 'MISSING';
      if (exists(stateFile)) {
        stateStatus = readFile(stateFile).length > 200 ? 'ACTIVE' : 'TEMPLATE';
      }

      if (currentBytes >= EMERGENCY_BYTES) {
        warnings.push(`EMERGENCY: ~${remaining}% context remaining. Auto-compact IMMINENT. Update state.md NOW — it survives compact. state.md: ${stateStatus} (.mci entries: ${mciEntries})`);
      } else if (currentBytes >= CRITICAL_BYTES) {
        warnings.push(`WARNING: ~${remaining}% context remaining. Ensure state.md is current (Goal/Progress/Findings). state.md: ${stateStatus} (.mci entries: ${mciEntries})`);
      } else if (currentBytes >= WARN_BYTES) {
        warnings.push(`Context checkpoint: ~${remaining}% remaining. Good time to update state.md with current progress.`);
      }
    } catch {}

    if (warnings.length > 0) {
      process.stdout.write(JSON.stringify({
        hookSpecificOutput: { additionalContext: warnings.join('\n') }
      }));
    } else {
      process.stdout.write('{"suppressOutput": true}');
    }
  } else {
    // No JSONL — still output state.md warnings if any
    if (warnings.length > 0) {
      process.stdout.write(JSON.stringify({
        hookSpecificOutput: { additionalContext: warnings.join('\n') }
      }));
    } else {
      process.stdout.write('{"suppressOutput": true}');
    }
  }

  process.exit(0);
}

main().catch(() => {
  process.stdout.write('{"suppressOutput": true}');
  process.exit(0);
});
