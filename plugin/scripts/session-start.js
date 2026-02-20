#!/usr/bin/env node
// ============================================================================
// MCI v2 SESSION START — state.md based memory system (Node.js - cross-platform)
// Creates/resumes sessions, creates state.md template, loads .mci, injects v2 rules
// v2.0.0 — Living state.md replaces append-only marker files
// ============================================================================

const fs = require('fs');
const path = require('path');

const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR || '.';
const MEMORY_BASE = path.join(PROJECT_DIR, '.claude-memory');
const now = new Date();
const SESSION_DATE = now.toISOString().slice(0, 10);
const SESSION_TIME = now.toTimeString().slice(0, 5);
const SESSION_DIR = path.join(MEMORY_BASE, 'sessions', SESSION_DATE);
const RESUME_TIMEOUT = 14400; // 4 hours
const MCI_LOOKBACK_DAYS = 7;

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
      .sort((a, b) => parseInt(a.replace('session-', '')) - parseInt(b.replace('session-', '')))
      .map(d => path.join(dir, d));
  } catch { return []; }
}

function listDateDirs(sessionsRoot) {
  try {
    return fs.readdirSync(sessionsRoot)
      .filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d))
      .sort().reverse()
      .map(d => path.join(sessionsRoot, d));
  } catch { return []; }
}

function createSessionFiles(sessionPath, num) {
  mkdirp(sessionPath);
  fs.writeFileSync(path.join(sessionPath, 'memory.md'), `# Session ${num} - Started ${SESSION_TIME}\n---\n`);
  // state.md — the living state file (v2)
  fs.writeFileSync(path.join(sessionPath, 'state.md'), `# Session State
> Last updated: --:--

## Goal
(Set your mission here. What are you working on and why?)

## Progress
- [ ] Waiting for direction

## Findings
(none yet)
`);
  // Legacy marker files (backward compat)
  fs.writeFileSync(path.join(sessionPath, 'facts.md'), `# Facts - Session ${num}\n`);
  fs.writeFileSync(path.join(sessionPath, 'context.md'), `# Context - Session ${num}\n`);
  fs.writeFileSync(path.join(sessionPath, 'intent.md'), `# Intent - Session ${num}\n`);
}

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
let previousSessionPath = null;

if (lastSession && exists(path.join(lastSession, 'memory.md'))) {
  const lastMod = fileModTime(path.join(lastSession, 'memory.md'));
  const nowSec = Math.floor(Date.now() / 1000);
  const diff = nowSec - lastMod;

  const memContent = readFile(path.join(lastSession, 'memory.md'));
  const hasEndMarker = /SESSION ENDED/i.test(memContent);
  const hasSummary = exists(path.join(lastSession, 'session-summary.md'));

  if (diff < RESUME_TIMEOUT) {
    sessionPath = lastSession;
    sessionNum = parseInt(path.basename(lastSession).replace('session-', ''));
    sessionStatus = 'RESUMED';
    if (!hasEndMarker && !hasSummary && diff > 60) {
      crashDetected = true;
      sessionStatus = 'CRASH-RECOVERED';
    }
    // Ensure state.md exists on resume
    if (!exists(path.join(sessionPath, 'state.md'))) {
      fs.writeFileSync(path.join(sessionPath, 'state.md'), `# Session State
> Last updated: --:--

## Goal
(Resumed session — update with current mission)

## Progress
- [ ] (update with current tasks)

## Findings
(update with any findings)
`);
    }
    // Ensure legacy marker files exist
    for (const file of ['facts.md', 'context.md', 'intent.md']) {
      if (!exists(path.join(sessionPath, file))) {
        fs.writeFileSync(path.join(sessionPath, file), `# ${file.replace('.md', '')} - Session ${sessionNum}\n`);
      }
    }
  } else {
    previousSessionPath = lastSession;
    sessionNum = sessions.length + 1;
    sessionPath = path.join(SESSION_DIR, `session-${sessionNum}`);
    createSessionFiles(sessionPath, sessionNum);
    sessionStatus = 'NEW';
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
// LOAD IDENTITY FILES
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

const mciPath = path.join(sessionPath, 'memory.mci');
if (exists(mciPath)) {
  const content = readFile(mciPath);
  if (content.trim()) {
    mciLoaded = true;
    mciSource = 'current session';
    loadedContext += `\n\n=== Session .mci (${mciPath}) ===\n${content}`;
  }
}

if (!mciLoaded && previousSessionPath) {
  const prevMci = path.join(previousSessionPath, 'memory.mci');
  if (exists(prevMci)) {
    const content = readFile(prevMci);
    if (content.trim()) {
      mciLoaded = true;
      mciSource = 'previous session (timed out)';
      loadedContext += `\n\n=== Previous Session .mci (${prevMci}) ===\n${content}`;
    }
  }
}

if (!mciLoaded) {
  for (let i = sessions.length - 1; i >= 0; i--) {
    if (sessions[i] === sessionPath) continue;
    const mci = path.join(sessions[i], 'memory.mci');
    if (exists(mci)) {
      const content = readFile(mci);
      if (content.trim()) {
        mciLoaded = true;
        mciSource = `earlier today (${path.basename(sessions[i])})`;
        loadedContext += `\n\n=== Earlier Session .mci (${mci}) ===\n${content}`;
        break;
      }
    }
  }
}

if (!mciLoaded) {
  const sessionsRoot = path.join(MEMORY_BASE, 'sessions');
  const dateDirs = listDateDirs(sessionsRoot);
  for (const dateDir of dateDirs.slice(0, MCI_LOOKBACK_DAYS)) {
    if (dateDir === SESSION_DIR) continue;
    const daySessions = listDirs(dateDir);
    for (let i = daySessions.length - 1; i >= 0; i--) {
      const mci = path.join(daySessions[i], 'memory.mci');
      if (exists(mci)) {
        const content = readFile(mci);
        if (content.trim()) {
          mciLoaded = true;
          mciSource = `${path.basename(dateDir)} (${path.basename(daySessions[i])})`;
          loadedContext += `\n\n=== Previous .mci from ${path.basename(dateDir)} (${mci}) ===\n${content}`;
          break;
        }
      }
    }
    if (mciLoaded) break;
  }
}

// ============================================================================
// LOAD MARKER FILES FOR RICHER RECOVERY
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
// state.md STATUS
// ============================================================================
let stateStatus = 'EMPTY';
const stateFile = path.join(sessionPath, 'state.md');
if (exists(stateFile)) {
  const stateSize = readFile(stateFile).length;
  stateStatus = stateSize > 200 ? `ACTIVE (${stateSize} bytes)` : 'TEMPLATE';
}

// ============================================================================
// MCI v2 RULES (always injected)
// ============================================================================
const mciRules = `
=== MEMORY SYSTEM v2 — state.md ===

## state.md = Your External Brain
Path: ${sessionPath}/state.md
Status: ${stateStatus}

state.md is a LIVING document with 3 sections: Goal, Progress, Findings.
It survives compacts because it lives on disk. After compact, READ it for full recovery.

## How to Use
1. **Update Goal** when mission changes (use Edit tool)
2. **Update Progress** as you work — check off tasks, add new ones (use Edit tool)
3. **Update Findings** when you discover important data (use Edit tool)
4. **Append to memory.md** for session log entries ([i] marker)
5. **Every 3-5 tool calls** — quick state.md update to stay current

## Markers (display formatting + legacy capture)
| Marker | Meaning | state.md Action |
|--------|---------|----------------|
| [+] | Success | (display only) |
| [-] | Failed | (display only) |
| [!] | Critical find | → Edit Findings section |
| [>] | Next step | → Edit Progress section |
| [*] | Context shift | → Edit Goal section |
| [i] | Info note | → Append to memory.md |

Markers are OUTPUT FORMATTING. state.md is the REAL memory. Keep it current.

## Post-Compact Recovery
1. Read ${sessionPath}/state.md — your full state is there
2. Check Progress — see what's done, what's next
3. Resume from first unchecked item
4. DO NOT ask user what you were doing — state.md tells you

## .mci File
Path: ${sessionPath}/memory.mci
Auto-generated by hooks as safety net. Pre-compact snapshots state.md → .mci.`;

loadedContext += '\n' + mciRules;

// ============================================================================
// BUILD OUTPUT
// ============================================================================
let compactAlert = '';
if (isPostCompact) {
  compactAlert = `
=== POST-COMPACT RECOVERY ===
Auto-compact fired. Your state.md is intact on disk.
ACTION: Read ${sessionPath}/state.md for full recovery. Resume from Progress checklist.
Do NOT ask what you were doing. state.md TELLS you.
Compact info: ${compactInfo}`;
}

let crashAlert = '';
if (crashDetected && !isPostCompact) {
  crashAlert = `
=== CRASH RECOVERY ===
The previous session did NOT end cleanly (no Stop hook fired).
${previousSessionPath ? `Crashed session: ${previousSessionPath}` : 'Recovering in-place.'}
${mciLoaded ? 'M/C/I was recovered from: ' + mciSource : 'WARNING: No .mci found — check state.md and marker files for context.'}
ACTION: Read state.md first, then review loaded M/C/I. Resume where the user left off.`;
}

let onboardingGuide = '';
if (isFirstRun) {
  onboardingGuide = `
=== FIRST RUN — WELCOME TO M/C/I MEMORY v2 ===

You just got persistent memory powered by state.md. Here's what happened:

1. CREATED: .claude-memory/sessions/ directory (your memory vault)
2. CREATED: state.md — your living state file with Goal/Progress/Findings
3. CREATED: Legacy session files (facts.md, context.md, intent.md, memory.md)
4. COPIED: IDENTITY.md and PREFERENCES.md templates to project root

HOW THIS WORKS:
- state.md is your EXTERNAL BRAIN — it lives on disk, survives compacts
- 4 hooks run automatically (SessionStart, UserPromptSubmit, PreCompact, Stop)
- Pre-compact snapshots state.md into .mci as safety net
- After compact, READ state.md to recover your full state

WHAT YOU SHOULD DO RIGHT NOW:
1. Greet the user and explain you now have persistent memory
2. Offer to customize IDENTITY.md (who you are) and PREFERENCES.md (communication style)
3. Start updating state.md as you work — it's your primary memory
4. Use markers ([!] [*] [>] [i]) for display formatting

SKILLS AVAILABLE:
- /claude-memory:save — manually checkpoint your state
- /claude-memory:recall — load last saved state
- /claude-memory:status — show session dashboard`;
}

const context = `# M/C/I v2 Session - ${now.toISOString().slice(0, 10)} ${SESSION_TIME}

=== STATUS ===
[+] SESSION: #${sessionNum} (${sessionStatus})${isFirstRun ? ' (FIRST RUN)' : ''}
Path: ${sessionPath}
state.md: ${stateStatus}
MCI: ${mciLoaded ? 'LOADED from ' + mciSource : 'EMPTY - fresh session'}
Post-Compact: ${isPostCompact ? 'YES — READ state.md NOW' : 'No'}
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
