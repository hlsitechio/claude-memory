#!/usr/bin/env node
// ============================================================================
// SESSION START - M/C/I Memory System (Node.js - cross-platform)
// Creates/resumes sessions, loads last .mci state, injects M/C/I rules
// v1.3.0 — Extended recovery: 7-day cascade, crash detection, marker reload
// ============================================================================

const fs = require('fs');
const path = require('path');

const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR || '.';
const MEMORY_BASE = path.join(PROJECT_DIR, '.claude-memory');
const now = new Date();
const SESSION_DATE = now.toISOString().slice(0, 10); // YYYY-MM-DD
const SESSION_TIME = now.toTimeString().slice(0, 5);  // HH:MM
const SESSION_DIR = path.join(MEMORY_BASE, 'sessions', SESSION_DATE);
const RESUME_TIMEOUT = 14400; // 4 hours — generous for crashes/restarts
const MCI_LOOKBACK_DAYS = 7;  // Search up to 7 days back for .mci recovery

function mkdirp(dir) { fs.mkdirSync(dir, { recursive: true }); }
function exists(p) { try { fs.accessSync(p); return true; } catch { return false; } }
function readFile(p) { try { return fs.readFileSync(p, 'utf8'); } catch { return ''; } }

function fileModTime(p) {
  try { return Math.floor(fs.statSync(p).mtimeMs / 1000); } catch { return 0; }
}

function listDirs(dir) {
  try {
    return fs.readdirSync(dir)
      .filter(d => d.startsWith('session-'))
      .sort((a, b) => {
        const na = parseInt(a.replace('session-', ''));
        const nb = parseInt(b.replace('session-', ''));
        return na - nb;
      })
      .map(d => path.join(dir, d));
  } catch { return []; }
}

function listDateDirs(sessionsRoot) {
  try {
    return fs.readdirSync(sessionsRoot)
      .filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d))
      .sort()
      .reverse() // Most recent first
      .map(d => path.join(sessionsRoot, d));
  } catch { return []; }
}

function createSessionFiles(sessionPath, num) {
  mkdirp(sessionPath);
  fs.writeFileSync(path.join(sessionPath, 'memory.md'), `# Session ${num} - Started ${SESSION_TIME}\n---\n`);
  fs.writeFileSync(path.join(sessionPath, 'facts.md'), `# Facts - Session ${num}\n`);
  fs.writeFileSync(path.join(sessionPath, 'context.md'), `# Context - Session ${num}\n`);
  fs.writeFileSync(path.join(sessionPath, 'intent.md'), `# Intent - Session ${num}\n`);
}

// Extract meaningful entries from a marker file (skip header line)
function getMarkerEntries(filePath, maxEntries) {
  const content = readFile(filePath);
  if (!content) return [];
  const entries = content.match(/^## .+/gm) || [];
  return entries.slice(-maxEntries).map(e => e.replace(/^## /, ''));
}

// ============================================================================
// FIRST-RUN DETECTION & TEMPLATE SETUP
// ============================================================================
const isFirstRun = !exists(MEMORY_BASE) || !exists(path.join(MEMORY_BASE, 'sessions'));

if (isFirstRun) {
  mkdirp(MEMORY_BASE);
  const pluginRoot = path.resolve(__dirname, '..');
  const templatesDir = path.join(pluginRoot, 'templates');
  for (const file of ['IDENTITY.md', 'PREFERENCES.md']) {
    const src = path.join(templatesDir, file);
    const dest = path.join(PROJECT_DIR, file);
    if (exists(src) && !exists(dest)) {
      try { fs.copyFileSync(src, dest); } catch {}
    }
  }
}

// ============================================================================
// SESSION MANAGEMENT
// ============================================================================
mkdirp(SESSION_DIR);
const sessions = listDirs(SESSION_DIR);
const lastSession = sessions.length > 0 ? sessions[sessions.length - 1] : null;

let sessionPath, sessionNum, sessionStatus;
let crashDetected = false;
let previousSessionPath = null; // Track which session we're recovering from

if (lastSession && exists(path.join(lastSession, 'memory.md'))) {
  const lastMod = fileModTime(path.join(lastSession, 'memory.md'));
  const nowSec = Math.floor(Date.now() / 1000);
  const diff = nowSec - lastMod;

  // Check if last session ended cleanly
  const memContent = readFile(path.join(lastSession, 'memory.md'));
  const hasEndMarker = /SESSION ENDED/i.test(memContent);
  const hasSummary = exists(path.join(lastSession, 'session-summary.md'));

  if (diff < RESUME_TIMEOUT) {
    sessionPath = lastSession;
    sessionNum = parseInt(path.basename(lastSession).replace('session-', ''));
    sessionStatus = 'RESUMED';
    // Detect crash: session was active (recent activity) but never ended cleanly
    if (!hasEndMarker && !hasSummary && diff > 60) {
      crashDetected = true;
      sessionStatus = 'CRASH-RECOVERED';
    }
    // Ensure marker files exist
    for (const file of ['facts.md', 'context.md', 'intent.md']) {
      if (!exists(path.join(sessionPath, file))) {
        fs.writeFileSync(path.join(sessionPath, file), `# ${file.replace('.md', '')} - Session ${sessionNum}\n`);
      }
    }
  } else {
    // Session timed out — create new but track previous for recovery
    previousSessionPath = lastSession;
    sessionNum = sessions.length + 1;
    sessionPath = path.join(SESSION_DIR, `session-${sessionNum}`);
    createSessionFiles(sessionPath, sessionNum);
    sessionStatus = 'NEW';
    // If previous session never ended, it was a crash
    if (!hasEndMarker && !hasSummary) {
      crashDetected = true;
      sessionStatus = 'NEW (previous session crashed)';
    }
  }
} else {
  sessionNum = 1;
  sessionPath = path.join(SESSION_DIR, 'session-1');
  createSessionFiles(sessionPath, sessionNum);
  sessionStatus = 'NEW';
}

// Write current session path
mkdirp(MEMORY_BASE);
fs.writeFileSync(path.join(MEMORY_BASE, 'current-session'), sessionPath);

// ============================================================================
// POST-COMPACT DETECTION
// ============================================================================
const compactMarker = path.join(MEMORY_BASE, 'compact-pending');
let isPostCompact = false;
let compactInfo = '';

if (exists(compactMarker)) {
  isPostCompact = true;
  compactInfo = readFile(compactMarker);
  try { fs.unlinkSync(compactMarker); } catch {}
}

// ============================================================================
// LOAD IDENTITY FILES (optional)
// ============================================================================
let loadedContext = '';

if (exists(path.join(PROJECT_DIR, 'IDENTITY.md'))) {
  loadedContext += '\n\n=== Identity ===\n' + readFile(path.join(PROJECT_DIR, 'IDENTITY.md')).slice(0, 1000);
}
if (exists(path.join(PROJECT_DIR, 'PREFERENCES.md'))) {
  loadedContext += '\n\n=== Preferences ===\n' + readFile(path.join(PROJECT_DIR, 'PREFERENCES.md')).slice(0, 800);
}

// ============================================================================
// LOAD .MCI (cascade: current → previous today → last 7 days)
// ============================================================================
let mciLoaded = false;
let mciSource = '';

// Try current session
const mciPath = path.join(sessionPath, 'memory.mci');
if (exists(mciPath)) {
  const content = readFile(mciPath);
  if (content.trim()) {
    mciLoaded = true;
    mciSource = 'current session';
    loadedContext += `\n\n=== Session M/C/I (${mciPath}) ===\n${content}`;
  }
}

// Try previous session (if we tracked one from timeout)
if (!mciLoaded && previousSessionPath) {
  const prevMci = path.join(previousSessionPath, 'memory.mci');
  if (exists(prevMci)) {
    const content = readFile(prevMci);
    if (content.trim()) {
      mciLoaded = true;
      mciSource = 'previous session (timed out)';
      loadedContext += `\n\n=== Previous Session M/C/I (${prevMci}) ===\n${content}`;
    }
  }
}

// Fallback: scan other sessions today
if (!mciLoaded) {
  for (let i = sessions.length - 1; i >= 0; i--) {
    if (sessions[i] === sessionPath) continue;
    const mci = path.join(sessions[i], 'memory.mci');
    if (exists(mci)) {
      const content = readFile(mci);
      if (content.trim()) {
        mciLoaded = true;
        mciSource = `earlier today (${path.basename(sessions[i])})`;
        loadedContext += `\n\n=== Earlier Session M/C/I (${mci}) ===\n${content}`;
        break;
      }
    }
  }
}

// Fallback: scan last N days
if (!mciLoaded) {
  const sessionsRoot = path.join(MEMORY_BASE, 'sessions');
  const dateDirs = listDateDirs(sessionsRoot);

  for (const dateDir of dateDirs.slice(0, MCI_LOOKBACK_DAYS)) {
    if (dateDir === SESSION_DIR) continue; // Already searched today
    const daySessions = listDirs(dateDir);
    for (let i = daySessions.length - 1; i >= 0; i--) {
      const mci = path.join(daySessions[i], 'memory.mci');
      if (exists(mci)) {
        const content = readFile(mci);
        if (content.trim()) {
          mciLoaded = true;
          const dayName = path.basename(dateDir);
          mciSource = `${dayName} (${path.basename(daySessions[i])})`;
          loadedContext += `\n\n=== Previous M/C/I from ${dayName} (${mci}) ===\n${content}`;
          break;
        }
      }
    }
    if (mciLoaded) break;
  }
}

// ============================================================================
// LOAD MARKER FILES FOR RICHER RECOVERY (on crash/resume/new-from-crash)
// ============================================================================
let markerContext = '';
const recoverySource = crashDetected ? (previousSessionPath || sessionPath) : sessionPath;

if (crashDetected || isPostCompact || (sessionStatus === 'RESUMED' && mciLoaded)) {
  const factsEntries = getMarkerEntries(path.join(recoverySource, 'facts.md'), 5);
  const contextEntries = getMarkerEntries(path.join(recoverySource, 'context.md'), 3);
  const intentEntries = getMarkerEntries(path.join(recoverySource, 'intent.md'), 3);

  if (factsEntries.length || contextEntries.length || intentEntries.length) {
    markerContext += '\n\n=== Recent Marker Entries ===';
    if (factsEntries.length) markerContext += '\nFacts (last ' + factsEntries.length + '):\n' + factsEntries.map(e => '  - ' + e).join('\n');
    if (contextEntries.length) markerContext += '\nContext (last ' + contextEntries.length + '):\n' + contextEntries.map(e => '  - ' + e).join('\n');
    if (intentEntries.length) markerContext += '\nIntent (last ' + intentEntries.length + '):\n' + intentEntries.map(e => '  - ' + e).join('\n');
  }
}
loadedContext += markerContext;

// ============================================================================
// M/C/I RULES (always injected)
// ============================================================================
const mciRules = `
=== M/C/I MEMORY RULES ===

Markers are COMMANDS, not formatting. Type a marker = MUST write to its file in the SAME response.

| Marker | File | Action |
|--------|------|--------|
| [!] | facts.md | Append '## HH:MM - <fact>' to ${sessionPath}/facts.md |
| [*] | context.md | Append '## HH:MM - <context>' to ${sessionPath}/context.md |
| [>] | intent.md | Append '## HH:MM - <intent>' to ${sessionPath}/intent.md |
| [i] | memory.md | Append '## HH:MM - <info>' to ${sessionPath}/memory.md |
| [PC] | memory.mci | Write Memory/Context/Intent triplet to ${sessionPath}/memory.mci |
| [AC] | memory.mci | READ .mci, recover intent (post-compact recovery) |
| [+] | (none) | Display only: success |
| [-] | (none) | Display only: failed |

Rule: TYPE marker -> WRITE to file -> SAME RESPONSE -> CONTINUE.

.mci format:
--- <label> ---
Memory: <what happened>
Context: <why it matters>
Intent: <where we're going>

Auto-save: When the hook warns about context -> write [PC] immediately. The .mci is your lifeline.
Auto-checkpoint: The system auto-saves a checkpoint every ~10 prompts as crash insurance.`;

loadedContext += '\n' + mciRules;

// ============================================================================
// BUILD OUTPUT
// ============================================================================
let compactAlert = '';
if (isPostCompact) {
  compactAlert = `
=== POST-COMPACT RECOVERY ===
Auto-compact fired. Your .mci file is your lifeline.
Compact info: ${compactInfo}
ACTION: Read the M/C/I entries below. Recover your Intent. Continue work.
Do NOT ask what you were doing. The .mci TELLS you.`;
}

let crashAlert = '';
if (crashDetected && !isPostCompact) {
  crashAlert = `
=== CRASH RECOVERY ===
The previous session did NOT end cleanly (no Stop hook fired).
This means the terminal crashed, was killed, or was closed abruptly.
${previousSessionPath ? `Crashed session: ${previousSessionPath}` : 'Recovering in-place.'}
${mciLoaded ? 'M/C/I was recovered from: ' + mciSource : 'WARNING: No .mci found — check marker files below for context.'}
ACTION: Review the loaded M/C/I and marker entries. Resume where the user left off.
Do NOT ask what happened. Recover and continue.`;
}

// First-run onboarding guide
let onboardingGuide = '';
if (isFirstRun) {
  onboardingGuide = `
=== FIRST RUN — WELCOME TO M/C/I MEMORY ===

You just got persistent memory. Here's what happened:

1. CREATED: .claude-memory/sessions/ directory (your memory vault)
2. CREATED: Session files (facts.md, context.md, intent.md, memory.md)
3. COPIED: IDENTITY.md and PREFERENCES.md templates to project root (if they didn't exist)

HOW THIS WORKS:
- You now have 4 hooks running automatically:
  SessionStart: Loads your last saved state when you start
  UserPromptSubmit: Monitors context usage, captures markers, auto-checkpoints every ~10 prompts
  PreCompact: Saves your state BEFORE auto-compact wipes context
  Stop: Generates session summary when you exit

WHAT YOU SHOULD DO RIGHT NOW:
1. Greet the user and explain you now have persistent memory across sessions
2. Offer to customize IDENTITY.md (who you should be) and PREFERENCES.md (how to communicate)
3. Start using markers naturally — they auto-save to files:
   [!] for critical facts -> saves to facts.md
   [*] for context/significance -> saves to context.md
   [>] for next steps/goals -> saves to intent.md
   [i] for observations/notes -> saves to memory.md
4. Write a [PC] entry to memory.mci before any heavy operation (this is your lifeline across compacts)

EXAMPLE FIRST RESPONSE:
"Memory system initialized! I now have persistent memory across sessions.
Your session files are at: <session_path>

I've set up starter templates:
- IDENTITY.md — defines my personality and approach
- PREFERENCES.md — defines how I communicate with you

Want to customize these, or should we jump straight into work?

[i] First session initialized. M/C/I memory system active."
(Then you'd append that [i] entry to memory.md)

SKILLS AVAILABLE:
- /claude-memory:save — manually checkpoint your state
- /claude-memory:recall — load last saved M/C/I state
- /claude-memory:status — show session dashboard

The user installed this plugin to give you memory. Make them feel the difference from the first message.`;
}

const context = `# M/C/I Session - ${now.toISOString().slice(0, 10)} ${SESSION_TIME}

=== STATUS ===
[+] SESSION: #${sessionNum} (${sessionStatus})${isFirstRun ? ' (FIRST RUN)' : ''}
Path: ${sessionPath}
MCI: ${mciLoaded ? 'LOADED from ' + mciSource : 'EMPTY - fresh session'}
Post-Compact: ${isPostCompact ? 'YES - recovering' : 'No'}
Crash: ${crashDetected ? 'YES - previous session did not end cleanly' : 'No'}
${compactAlert}
${crashAlert}
${onboardingGuide}
${loadedContext}`;

const output = {
  hookSpecificOutput: {
    hookEventName: 'SessionStart',
    additionalContext: context
  }
};

process.stdout.write(JSON.stringify(output));
process.exit(0);
