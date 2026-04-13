#!/usr/bin/env python3
"""
MEMORY ENGINE VIEWER — Live web dashboard for the brain database.
Browse conversations, search history, view stats.
Runs on port 37888.
"""

import sqlite3
import json
import html
import os
import re
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH, VIEWER_PORT

PORT = VIEWER_PORT


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


IMAGES_DIR = Path(__file__).parent / "images"

def escape(text):
    return html.escape(str(text)) if text else ""


def render_content(text, max_len=1000):
    """Render entry content as formatted HTML. Handles tool calls, JSON results, and plain text."""
    import json as _json
    import re as _re

    # --- Type 1: MCP tool result JSON wrapper {"result":"..."} ---
    # Parse FULL text first (before truncation) so JSON stays valid
    if text.startswith('{"result":'):
        try:
            obj = _json.loads(text)
            inner = obj.get("result", text)
        except (_json.JSONDecodeError, ValueError):
            # DB stores literal \n (2 chars) instead of real newlines — fix before parse
            try:
                fixed = text.replace('\\n', '\n').replace('\\t', '\t')
                obj = _json.loads(fixed)
                inner = obj.get("result", text)
            except (_json.JSONDecodeError, ValueError):
                # Last resort: extract inner content between first ":" and last "}"
                inner = text[11:-2] if len(text) > 13 else text  # skip {"result":" and "}
                inner = inner.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
        if inner:
            if max_len and len(inner) > max_len * 2:
                inner = inner[:max_len * 2] + "\n…(truncated)"
            return _render_tool_result_block(inner)

    # --- Type 2: Tool call  [TOOL:Name] {json...} ---
    # Parse FULL text so JSON params stay valid
    tool_match = _re.match(r'^\[TOOL:(\w+)\]\s*(\{.*\})\s*$', text, _re.DOTALL)
    if tool_match:
        tool_name = tool_match.group(1)
        try:
            params = _json.loads(tool_match.group(2))
            return _render_tool_call_block(tool_name, params)
        except (_json.JSONDecodeError, ValueError):
            pass

    # --- Type 3: Plain text / markdown ---
    # Only truncate plain text (types 1 & 2 handle their own limits)
    text = text[:max_len] if max_len else text
    escaped = html.escape(text)

    # Replace [IMAGE:filename] with clickable thumbnail
    def img_replacer(m):
        fname = m.group(1)
        return f'<div style="margin:8px 0;"><a href="/img/{html.escape(fname)}" target="_blank"><img src="/img/{html.escape(fname)}" style="max-width:600px; max-height:400px; border-radius:6px; border:1px solid var(--border);" loading="lazy"></a></div>'
    escaped = _re.sub(r'\[IMAGE:([^\]]+)\]', img_replacer, escaped)

    # Inline formatting: **bold**, `code`, ```blocks```
    # Code blocks first (```...```)
    def code_block_replacer(m):
        lang = m.group(1) or ""
        code = m.group(2)
        label = f'<span style="color:var(--muted); font-size:10px;">{lang}</span>' if lang else ''
        return f'<div style="background:var(--bg); border:1px solid var(--border); border-radius:4px; padding:8px 10px; margin:6px 0; font-size:12px; overflow-x:auto;">{label}<pre style="margin:0; white-space:pre-wrap;">{code}</pre></div>'
    escaped = _re.sub(r'```(\w*)\n(.*?)```', code_block_replacer, escaped, flags=_re.DOTALL)

    # Inline code `...`
    escaped = _re.sub(r'`([^`]+)`', r'<code style="background:var(--bg); padding:1px 4px; border-radius:3px; font-size:12px;">\1</code>', escaped)

    # Bold **...**
    escaped = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)

    # Status markers [+] [-] [!] [*] [>] [i]
    escaped = _re.sub(r'\[\+\]', '<span style="color:var(--green); font-weight:bold;">[+]</span>', escaped)
    escaped = _re.sub(r'\[\-\]', '<span style="color:var(--red); font-weight:bold;">[-]</span>', escaped)
    escaped = _re.sub(r'\[!\]', '<span style="color:var(--red); font-weight:bold;">[!]</span>', escaped)
    escaped = _re.sub(r'\[\*\]', '<span style="color:var(--yellow); font-weight:bold;">[*]</span>', escaped)
    escaped = _re.sub(r'\[&gt;\]', '<span style="color:var(--accent); font-weight:bold;">[&gt;]</span>', escaped)
    escaped = _re.sub(r'\[i\]', '<span style="color:var(--purple); font-weight:bold;">[i]</span>', escaped)

    return escaped


def _render_tool_call_block(tool_name, params):
    """Render a [TOOL:X] {...} as a styled block."""
    # Color by tool type
    colors = {
        "Read": "var(--accent)", "Bash": "var(--green)", "Edit": "var(--yellow)",
        "Write": "var(--yellow)", "Grep": "var(--purple)", "Glob": "var(--purple)",
        "WebFetch": "#e67e22", "WebSearch": "#e67e22", "Task": "#1abc9c",
    }
    color = colors.get(tool_name, "var(--muted)")

    # Build concise param display
    parts = []
    if tool_name in ("Read", "Write", "Edit") and "file_path" in params:
        parts.append(f'<span style="color:var(--text);">{html.escape(params["file_path"])}</span>')
    elif tool_name == "Bash" and "command" in params:
        cmd = params["command"]
        if len(cmd) > 200:
            cmd = cmd[:200] + "…"
        parts.append(f'<code style="color:var(--text); background:var(--bg); padding:2px 6px; border-radius:3px; font-size:12px;">{html.escape(cmd)}</code>')
        if params.get("description"):
            parts.append(f'<span style="color:var(--muted); font-size:11px;">— {html.escape(params["description"])}</span>')
    elif tool_name in ("Grep", "Glob"):
        if "pattern" in params:
            parts.append(f'<code style="color:var(--text); background:var(--bg); padding:2px 6px; border-radius:3px;">/{html.escape(params["pattern"])}/</code>')
        if "path" in params:
            parts.append(f'<span style="color:var(--muted);">in {html.escape(params["path"])}</span>')
    elif tool_name == "WebFetch":
        if "url" in params:
            url = params["url"]
            if len(url) > 80:
                url = url[:80] + "…"
            parts.append(f'<span style="color:var(--accent);">{html.escape(url)}</span>')
    elif tool_name == "WebSearch":
        if "query" in params:
            parts.append(f'<span style="color:var(--text);">"{html.escape(params["query"])}"</span>')
    elif tool_name == "Edit":
        if "file_path" in params:
            parts.append(f'<span style="color:var(--text);">{html.escape(params["file_path"])}</span>')
        if "old_string" in params:
            old = params["old_string"]
            if len(old) > 60:
                old = old[:60] + "…"
            parts.append(f'<span style="color:var(--red); font-size:11px;">- {html.escape(old)}</span>')
    elif tool_name == "Task":
        if "description" in params:
            parts.append(f'<span style="color:var(--text);">{html.escape(params["description"])}</span>')
    else:
        # Generic: show first 2 params
        for k, v in list(params.items())[:2]:
            v_str = str(v)
            if len(v_str) > 80:
                v_str = v_str[:80] + "…"
            parts.append(f'<span style="color:var(--muted);">{html.escape(k)}=</span><span style="color:var(--text);">{html.escape(v_str)}</span>')

    param_html = " ".join(parts) if parts else '<span style="color:var(--muted);">no params</span>'

    return f'''<div style="display:flex; align-items:flex-start; gap:8px; padding:4px 0;">
        <span style="background:{color}22; color:{color}; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold; white-space:nowrap; border:1px solid {color}44;">{html.escape(tool_name)}</span>
        <div style="line-height:1.6; min-width:0;">{param_html}</div>
    </div>'''


def _render_tool_call_simple(tool_name, raw_params):
    """Fallback renderer when JSON parsing fails — still shows tool badge with truncated content."""
    colors = {
        "Read": "var(--accent)", "Bash": "var(--green)", "Edit": "var(--yellow)",
        "Write": "var(--yellow)", "Grep": "var(--purple)", "Glob": "var(--purple)",
        "WebFetch": "#e67e22", "WebSearch": "#e67e22", "Task": "#1abc9c",
    }
    color = colors.get(tool_name, "var(--muted)")
    # Extract key info heuristically
    import re as _re
    desc = ""
    cmd_match = _re.search(r'"command"\s*:\s*"([^"]{0,200})', raw_params)
    path_match = _re.search(r'"(?:file_)?path"\s*:\s*"([^"]+)"', raw_params)
    desc_match = _re.search(r'"description"\s*:\s*"([^"]+)"', raw_params)
    pattern_match = _re.search(r'"pattern"\s*:\s*"([^"]+)"', raw_params)
    query_match = _re.search(r'"query"\s*:\s*"([^"]+)"', raw_params)

    if cmd_match:
        cmd = cmd_match.group(1)
        if len(cmd) > 150:
            cmd = cmd[:150] + "…"
        desc = f'<code style="background:var(--bg); padding:2px 6px; border-radius:3px; font-size:12px;">{html.escape(cmd)}</code>'
        if desc_match:
            desc += f' <span style="color:var(--muted); font-size:11px;">— {html.escape(desc_match.group(1))}</span>'
    elif path_match:
        desc = f'<span style="color:var(--text);">{html.escape(path_match.group(1))}</span>'
    elif pattern_match:
        desc = f'<code style="background:var(--bg); padding:2px 6px; border-radius:3px;">/{html.escape(pattern_match.group(1))}/</code>'
    elif query_match:
        desc = f'<span style="color:var(--text);">"{html.escape(query_match.group(1))}"</span>'
    else:
        p = html.escape(raw_params[:150]) + ("…" if len(raw_params) > 150 else "")
        desc = f'<span style="color:var(--muted); font-size:11px;">{p}</span>'

    return f'''<div style="display:flex; align-items:flex-start; gap:8px; padding:4px 0;">
        <span style="background:{color}22; color:{color}; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold; white-space:nowrap; border:1px solid {color}44;">{html.escape(tool_name)}</span>
        <div style="line-height:1.6; min-width:0;">{desc}</div>
    </div>'''


def _render_tool_result_block(text):
    """Render a tool result string as formatted HTML. Parses RAW text, escapes selectively."""
    import re as _re
    import json as _json

    # Work with RAW text (not escaped) so JSON parsing works
    # Parse: "Found N results for: query\n\n---\n[role] Session: xxx | timestamp\n[TOOL:X] {...}\n---"
    found_match = _re.match(r'^Found (\d+) results? for: (.+?)(\n|$)', text)
    if found_match:
        count = found_match.group(1)
        query = html.escape(found_match.group(2))
        header = f'<div style="color:var(--accent); font-weight:bold; margin-bottom:8px;">Found {count} results for: <span style="color:var(--yellow);">{query}</span></div>'

        # Parse individual results separated by ---
        rest = text[found_match.end():]
        blocks = rest.split('---')

        results_html = ''
        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Parse: [role] Session: xxx... | timestamp\n[TOOL:Name] {json} or text
            entry_match = _re.match(r'\[(\w+)\]\s*Session:\s*(\S+)\s*\|\s*([^\n]+)\n(.*)', block, _re.DOTALL)
            if entry_match:
                role = html.escape(entry_match.group(1))
                session = html.escape(entry_match.group(2))
                ts = html.escape(entry_match.group(3).strip())
                content = entry_match.group(4).strip()

                role_color = "var(--accent)" if role == "assistant" else "var(--green)" if role == "user" else "var(--muted)"

                # Try to parse tool call from RAW content
                tool_m = _re.match(r'\[TOOL:(\w+)\]\s*(\{.*\})', content, _re.DOTALL)
                if tool_m:
                    tool_name = tool_m.group(1)
                    try:
                        raw_json = tool_m.group(2)
                        raw_json = raw_json.replace('\\"', '"')
                        # Sanitize: escape literal newlines/tabs inside JSON strings
                        raw_json = raw_json.replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r')
                        params = _json.loads(raw_json)
                        content_html = _render_tool_call_block(tool_name, params)
                    except Exception:
                        # JSON failed but we still know the tool name — render a simpler version
                        content_html = _render_tool_call_simple(tool_name, content[len(f'[TOOL:{tool_name}] '):])
                else:
                    c = html.escape(content)
                    if len(c) > 300:
                        c = c[:300] + '…'
                    content_html = f'<div style="color:var(--text); font-size:12px;">{c}</div>'

                results_html += f'''<div style="border-left:2px solid {role_color}; padding:4px 10px; margin:6px 0;">
                    <div style="font-size:10px; color:var(--muted); margin-bottom:2px;">
                        <span style="color:{role_color}; font-weight:bold;">{role}</span>
                        · {session} · {ts}
                    </div>
                    {content_html}
                </div>'''
            else:
                # Unparseable block — show as-is (escaped)
                b = html.escape(block)
                if len(b) > 300:
                    b = b[:300] + '…'
                results_html += f'<div style="color:var(--text); font-size:12px; padding:4px 0;">{b}</div>'

        return header + results_html

    # Generic result — escaped text with status markers
    escaped = html.escape(text)
    escaped = _re.sub(r'\[\+\]', '<span style="color:var(--green); font-weight:bold;">[+]</span>', escaped)
    escaped = _re.sub(r'\[\-\]', '<span style="color:var(--red); font-weight:bold;">[-]</span>', escaped)
    escaped = _re.sub(r'\[!\]', '<span style="color:var(--red); font-weight:bold;">[!]</span>', escaped)
    return escaped


CSS = """
:root {
    --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
    --border: #30363d; --text: #c9d1d9; --text2: #8b949e;
    --accent: #58a6ff; --green: #3fb950; --red: #f85149;
    --yellow: #d29922; --purple: #bc8cff;
    --sidebar-w: 220px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'JetBrains Mono', 'Fira Code', monospace; background: var(--bg); color: var(--text); font-size: 13px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Sidebar */
.sidebar { position:fixed; top:0; left:0; bottom:0; width:var(--sidebar-w); background:var(--bg2); border-right:1px solid var(--border); display:flex; flex-direction:column; z-index:100; overflow-y:auto; transition:transform 0.2s ease; }
.sidebar-brand { padding:16px 16px 12px; border-bottom:1px solid var(--border); display:flex; align-items:center; gap:10px; }
.sidebar-brand h1 { font-size:14px; color:var(--accent); margin:0; white-space:nowrap; }
.sidebar-section { padding:16px 16px 4px; font-size:10px; color:var(--text2); text-transform:uppercase; letter-spacing:1.2px; font-weight:bold; }
.sidebar-link { display:flex; align-items:center; gap:10px; padding:8px 16px; color:var(--text); font-size:12px; text-decoration:none; border-left:3px solid transparent; transition:background 0.15s, border-color 0.15s, color 0.15s; }
.sidebar-link:hover { background:var(--bg3); text-decoration:none; color:var(--text); }
.sidebar-link.active { border-left-color:var(--accent); background:var(--bg3); color:var(--accent); font-weight:bold; }
.sidebar-link svg { flex-shrink:0; opacity:0.6; }
.sidebar-link:hover svg, .sidebar-link.active svg { opacity:1; }
.sidebar-footer { margin-top:auto; padding:12px 16px; border-top:1px solid var(--border); font-size:11px; color:var(--text2); line-height:1.6; }

/* Main content */
.main-content { margin-left:var(--sidebar-w); min-height:100vh; }
.page-title { padding:12px 24px; border-bottom:1px solid var(--border); font-size:13px; color:var(--text2); background:var(--bg); display:flex; align-items:center; gap:8px; }
.page-title h2 { font-size:14px; color:var(--text); font-weight:600; }

/* Hamburger (mobile) */
.hamburger { display:none; position:fixed; top:10px; left:10px; z-index:200; background:var(--bg2); border:1px solid var(--border); border-radius:6px; color:var(--text); padding:6px 10px; cursor:pointer; font-size:18px; line-height:1; }
.sidebar-overlay { display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); z-index:99; }
@media (max-width:768px) {
    .sidebar { transform:translateX(-100%); }
    .sidebar.open { transform:translateX(0); }
    .sidebar-overlay.open { display:block; }
    .main-content { margin-left:0; }
    .hamburger { display:block; }
    .page-title { padding-left:48px; }
}

.container { max-width: 1200px; margin: 0 auto; padding: 20px; }

.search-box { width: 100%; padding: 10px 16px; background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-family: inherit; font-size: 14px; margin-bottom: 16px; }
.search-box:focus { outline: none; border-color: var(--accent); }

.filters { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.filters select, .filters input { padding: 6px 10px; background: var(--bg2); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-family: inherit; font-size: 12px; }

.entry { background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 8px; }
.entry:hover { border-color: var(--accent); }
.entry .meta { display: flex; gap: 12px; margin-bottom: 6px; font-size: 11px; color: var(--text2); }
.entry .role { font-weight: bold; padding: 2px 6px; border-radius: 4px; font-size: 10px; text-transform: uppercase; }
.entry .role.user { background: #1f3d2a; color: var(--green); }
.entry .role.assistant { background: #1c2d4f; color: var(--accent); }
.entry .role.system { background: #3d2a1f; color: var(--yellow); }
.entry .role.user_prompt { background: #2d1f3d; color: var(--purple); }
.entry .content { white-space: pre-wrap; word-break: break-word; line-height: 1.6; max-height: 400px; overflow-y: auto; }
.entry .content .highlight { background: #d2992244; padding: 1px 3px; border-radius: 2px; }
.entry .content pre { white-space: pre-wrap; }
.entry .content code { font-family: inherit; }

.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 24px; }
.stat-card { background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.stat-card .label { color: var(--text2); font-size: 11px; text-transform: uppercase; margin-bottom: 4px; }
.stat-card .value { font-size: 24px; font-weight: bold; color: var(--accent); }

.timeline-bar { display: flex; align-items: end; gap: 2px; height: 100px; margin-bottom: 24px; padding: 0 4px; }
.timeline-bar .bar { flex: 1; background: var(--accent); border-radius: 2px 2px 0 0; min-width: 4px; position: relative; cursor: pointer; }
.timeline-bar .bar:hover { background: var(--green); }
.timeline-bar .bar .tip { display: none; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); background: var(--bg3); border: 1px solid var(--border); padding: 4px 8px; border-radius: 4px; white-space: nowrap; font-size: 10px; z-index: 10; }
.timeline-bar .bar:hover .tip { display: block; }

.session-list { list-style: none; }
.session-item { background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center; }
.session-item:hover { border-color: var(--accent); }
.session-item .id { font-weight: bold; color: var(--accent); }
.session-item .info { color: var(--text2); font-size: 11px; }

.pagination { display: flex; gap: 8px; justify-content: center; margin-top: 16px; }
.pagination a { padding: 6px 12px; background: var(--bg2); border: 1px solid var(--border); border-radius: 6px; color: var(--text); }
.pagination a:hover { border-color: var(--accent); }
.pagination a.current { background: var(--accent); color: #000; }

.empty { text-align: center; padding: 40px; color: var(--text2); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 10px; }
.live-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--green); margin-right: 6px; animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.source-badge { display:inline-block; padding:2px 6px; border-radius:4px; font-size:9px; text-transform:uppercase; font-weight:bold; margin-left:4px; }
.source-badge.claude_code { background:#1c2d4f; color:var(--accent); }
.source-badge.copilot { background:#1f3d2a; color:var(--green); }
.source-badge.codex { background:#3d2a1f; color:var(--yellow); }
"""


NAV_ICONS = {
    "home": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 6l6-4.5L14 6v7.5a1 1 0 01-1 1H3a1 1 0 01-1-1V6z"/><path d="M6 14.5V8h4v6.5"/></svg>',
    "search": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="7" cy="7" r="4.5"/><path d="M14 14l-3.5-3.5"/></svg>',
    "semantic": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="4" r="2"/><circle cx="4" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><path d="M8 6v2M6.5 10.5L7 8M9.5 10.5L9 8"/></svg>',
    "timeline": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6.5"/><path d="M8 4v4l3 2"/></svg>',
    "sessions": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h12a1 1 0 011 1v7a1 1 0 01-1 1H2a1 1 0 01-1-1V4a1 1 0 011-1z"/><path d="M4 14h8M5 6h6M5 9h3"/></svg>',
    "topics": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 3h6M1 8h4M1 13h6M10 1v14M10 5l4-4M10 5l-3-3"/></svg>',
    "projects": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3.5A1.5 1.5 0 013.5 2h2.88a1.5 1.5 0 011.06.44L8.56 3.56A1.5 1.5 0 009.62 4H12.5A1.5 1.5 0 0114 5.5v7a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 12.5v-9z"/></svg>',
    "observations": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 14h6"/><path d="M6 11h4"/><path d="M4.5 7a3.5 3.5 0 117 0c0 1.5-1.2 2.2-1.7 3H6.2C5.7 9.2 4.5 8.5 4.5 7z"/></svg>',
    "live": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="2"/><path d="M5 5a4.5 4.5 0 000 6M11 5a4.5 4.5 0 010 6"/><path d="M3 3a7.5 7.5 0 000 10M13 3a7.5 7.5 0 010 10"/></svg>',
    "setup": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="2.5"/><path d="M12.9 10a1 1 0 00.2 1.1l.1.1a1.2 1.2 0 11-1.7 1.7l-.1-.1a1 1 0 00-1.1-.2 1 1 0 00-.6.9v.2a1.2 1.2 0 01-2.4 0v-.1a1 1 0 00-.7-.9 1 1 0 00-1.1.2l-.1.1a1.2 1.2 0 11-1.7-1.7l.1-.1a1 1 0 00.2-1.1 1 1 0 00-.9-.6H2.8a1.2 1.2 0 010-2.4h.1a1 1 0 00.9-.7 1 1 0 00-.2-1.1l-.1-.1a1.2 1.2 0 111.7-1.7l.1.1a1 1 0 001.1.2h0a1 1 0 00.6-.9V2.8a1.2 1.2 0 012.4 0v.1a1 1 0 00.6.9 1 1 0 001.1-.2l.1-.1a1.2 1.2 0 111.7 1.7l-.1.1a1 1 0 00-.2 1.1v0a1 1 0 00.9.6h.2a1.2 1.2 0 010 2.4h-.1a1 1 0 00-.9.6z"/></svg>',
}


SETUP_CSS = """
.wizard-progress { display:flex; gap:0; margin:24px auto 32px; max-width:500px; }
.wizard-dot { flex:1; height:4px; background:var(--bg3); transition:background 0.3s; border-radius:2px; margin:0 2px; }
.wizard-dot.done { background:var(--green); }
.wizard-dot.active { background:var(--accent); }

.wizard-panel { display:none; max-width:640px; margin:0 auto; }
.wizard-panel.active { display:block; animation:wizardFadeIn 0.3s ease; }
@keyframes wizardFadeIn { from{opacity:0;transform:translateY(12px)} to{opacity:1;transform:none} }

.wizard-hero { text-align:center; padding:48px 0 32px; }
.wizard-hero h1 { font-size:28px; color:var(--accent); margin-bottom:8px; }
.wizard-hero p { color:var(--text2); font-size:14px; line-height:1.7; }

.wizard-pills { display:flex; gap:10px; justify-content:center; margin:24px 0 32px; flex-wrap:wrap; }
.wizard-pill { padding:8px 16px; background:var(--bg2); border:1px solid var(--border); border-radius:20px; font-size:12px; color:var(--text); }

.tool-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(170px,1fr)); gap:12px; margin:24px 0; }
.tool-card { background:var(--bg2); border:2px solid var(--border); border-radius:12px; padding:20px 16px; cursor:pointer; text-align:center; transition:all 0.2s; }
.tool-card:hover { border-color:var(--accent); transform:translateY(-2px); }
.tool-card.selected { border-color:var(--green); background:rgba(63,185,80,0.07); }
.tool-card .icon { font-size:28px; margin-bottom:8px; display:block; }
.tool-card .name { font-size:13px; font-weight:bold; color:var(--text); display:block; }
.tool-card .desc { font-size:11px; color:var(--text2); margin-top:4px; display:block; }

.detect-row { display:flex; justify-content:space-between; align-items:center; padding:12px 16px; background:var(--bg2); border:1px solid var(--border); border-radius:8px; margin-bottom:8px; }
.detect-row .label { color:var(--text2); font-size:12px; min-width:120px; }
.detect-row .value { color:var(--green); font-family:'JetBrains Mono',monospace; font-size:11px; word-break:break-all; flex:1; margin:0 12px; }
.detect-row .value.missing { color:var(--red); }
.detect-row .status { font-size:14px; }
.detect-row input { background:var(--bg); border:1px solid var(--border); border-radius:4px; color:var(--text); padding:4px 8px; font-family:inherit; font-size:11px; flex:1; margin:0 12px; }

.config-block { background:var(--bg); border:1px solid var(--border); border-radius:8px; padding:16px; position:relative; margin:16px 0; overflow-x:auto; }
.config-block pre { margin:0; white-space:pre-wrap; color:var(--text); font-size:12px; line-height:1.6; }
.config-block .copy-btn { position:absolute; top:8px; right:8px; padding:4px 12px; background:var(--bg3); color:var(--accent); border:1px solid var(--border); border-radius:4px; cursor:pointer; font-size:11px; font-family:inherit; }
.config-block .copy-btn:hover { background:var(--accent); color:#000; }

.wizard-btn { display:inline-block; padding:12px 28px; background:var(--accent); color:#000; border:none; border-radius:8px; font-size:14px; font-weight:bold; cursor:pointer; font-family:inherit; transition:all 0.2s; }
.wizard-btn:hover { opacity:0.9; transform:translateY(-1px); }
.wizard-btn.green { background:var(--green); }
.wizard-btn.outline { background:transparent; border:1px solid var(--border); color:var(--text); font-weight:normal; }
.wizard-btn.outline:hover { border-color:var(--accent); color:var(--accent); }
.wizard-btn:disabled { opacity:0.4; cursor:not-allowed; }

.wizard-status { padding:12px 16px; border-radius:8px; margin:12px 0; font-size:13px; }
.wizard-status.ok { background:rgba(63,185,80,0.1); border:1px solid rgba(63,185,80,0.3); color:var(--green); }
.wizard-status.err { background:rgba(248,81,73,0.1); border:1px solid rgba(248,81,73,0.3); color:var(--red); }
.wizard-status.info { background:rgba(88,166,255,0.1); border:1px solid rgba(88,166,255,0.3); color:var(--accent); }

.spinner { display:inline-block; width:18px; height:18px; border:2px solid var(--bg3); border-top-color:var(--accent); border-radius:50%; animation:spin 0.8s linear infinite; vertical-align:middle; margin-right:8px; }
@keyframes spin { to{transform:rotate(360deg)} }

.wizard-done { text-align:center; padding:32px 0; }
.wizard-done .checkmark { display:inline-block; width:64px; height:64px; border-radius:50%; background:var(--green); position:relative; margin-bottom:16px; }
.wizard-done .checkmark::after { content:''; position:absolute; left:22px; top:14px; width:18px; height:32px; border:solid #000; border-width:0 4px 4px 0; transform:rotate(45deg); }

.tool-ref { text-align:left; margin:24px 0; }
.tool-ref summary { cursor:pointer; color:var(--accent); font-size:13px; padding:8px 0; }
.tool-ref table { width:100%; font-size:12px; margin-top:8px; }
.tool-ref td { padding:4px 8px; border-bottom:1px solid var(--border); }
.tool-ref td:first-child { color:var(--accent); font-family:'JetBrains Mono',monospace; white-space:nowrap; }

.config-path { padding:8px 12px; background:var(--bg2); border:1px solid var(--border); border-radius:6px; font-size:12px; color:var(--text2); margin-bottom:8px; font-family:'JetBrains Mono',monospace; }
"""


class ViewerHandler(BaseHTTPRequestHandler):
    _setup_done = None  # None = unchecked, True = setup complete, False = needs setup

    @classmethod
    def _is_first_run(cls):
        if cls._setup_done is True:
            return False
        if cls._setup_done is None:
            try:
                if not os.path.exists(DB_PATH):
                    cls._setup_done = False
                    return True
                conn = sqlite3.connect(DB_PATH)
                count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                conn.close()
                cls._setup_done = count > 0
                return count == 0
            except Exception:
                cls._setup_done = False
                return True
        return not cls._setup_done

    def log_message(self, format, *args):
        pass  # Suppress access logs

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # First-run redirect to setup wizard
        if self._is_first_run() and path not in ("/setup",) and not path.startswith("/api/setup"):
            self.send_response(302)
            self.send_header("Location", "/setup")
            self.end_headers()
            return

        # Enforce source isolation — no page renders without a source
        # (skip for setup, API, and static routes)
        if path not in ("/setup",) and not path.startswith("/api/") and not path.startswith("/img/"):
            source = params.get("source", [""])[0]
            if not source:
                # Default to claude_code
                self.send_response(302)
                sep = "&" if "?" in self.path else "?"
                self.send_header("Location", f"{self.path}{sep}source=claude_code")
                self.end_headers()
                return

        # Setup routes
        if path == "/setup":
            self.handle_setup(params)
            return
        elif path == "/api/setup/detect":
            self.handle_api_setup_detect()
            return
        elif path == "/api/setup/test":
            self.handle_api_setup_test(params)
            return
        elif path == "/api/setup/config":
            self.handle_api_setup_config(params)
            return

        if path == "/":
            self.handle_home(params)
        elif path == "/search":
            self.handle_search(params)
        elif path == "/timeline":
            self.handle_timeline(params)
        elif path == "/sessions":
            self.handle_sessions(params)
        elif path == "/session":
            self.handle_session_detail(params)
        elif path == "/topics":
            self.handle_topics(params)
        elif path == "/topic":
            self.handle_topic_detail(params)
        elif path == "/semantic":
            self.handle_semantic(params)
        elif path == "/projects":
            self.handle_projects(params)
        elif path == "/project":
            self.handle_project_detail(params)
        elif path == "/project/create":
            self.handle_project_create(params)
        elif path.startswith("/api/project/"):
            self.handle_api_project(path, params)
        elif path == "/observations":
            self.handle_observations(params)
        elif path == "/observation":
            self.handle_observation_detail(params)
        elif path == "/summary":
            self.handle_summary_detail(params)
        elif path == "/live":
            self.handle_live(params)
        elif path == "/api/semantic":
            self.handle_api_semantic(params)
        elif path == "/api/session_new":
            self.handle_api_session_new(params)
        elif path.startswith("/img/"):
            self.handle_image(path[5:])  # strip /img/ prefix
        elif path == "/api/stats":
            self.handle_api_stats(params)
        elif path == "/api/search":
            self.handle_api_search(params)
        elif path == "/api/latest":
            self.handle_api_latest(params)
        elif path == "/api/session":
            self.handle_api_session(params)
        elif path == "/api/sessions":
            self.handle_api_sessions(params)
        elif path == "/api/export":
            self.handle_api_export(params)
        elif path == "/api/session/digest":
            self.handle_api_session_digest(params)
        elif path == "/api/session/summary":
            self.handle_api_session_summary_get(params)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')

        # JSON endpoints
        if path == "/api/setup/install":
            self.handle_api_setup_install_post(post_data)
            return
        elif path == "/api/setup/ingest":
            self.handle_api_setup_ingest_post()
            return
        elif path == "/api/session/summary":
            self.handle_api_session_summary_post(post_data)
            return

        from urllib.parse import parse_qs as pqs
        form = pqs(post_data)

        if path == "/project/create":
            self.handle_project_create_post(form)
        elif path == "/project/update":
            self.handle_project_update_post(form)
        elif path == "/project/delete":
            self.handle_project_delete_post(form)
        else:
            self.send_error(404)

    def send_html(self, content, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode())

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def page_wrap(self, title, body, active="", source_filter=""):
        """Wrap page with sidebar. source_filter isolates to one tool's data."""
        conn = get_db()
        sf = source_filter  # shorthand

        # Stats scoped to active source
        if sf:
            total = conn.execute("SELECT COUNT(*) FROM entries WHERE source=?", (sf,)).fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='done' AND source=?", (sf,)).fetchone()[0]
        else:
            total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='done'").fetchone()[0]

        # Detect available sources with counts
        source_meta = {
            'claude_code': {'label': 'Claude Code', 'icon': '&#9672;', 'color': 'var(--accent)', 'count': 0},
            'copilot': {'label': 'Copilot CLI', 'icon': '&#9998;', 'color': 'var(--green)', 'count': 0},
            'codex': {'label': 'Codex CLI', 'icon': '&#9881;', 'color': 'var(--yellow)', 'count': 0},
        }
        try:
            rows = conn.execute("SELECT source, COUNT(*) as cnt FROM sessions WHERE status='done' GROUP BY source").fetchall()
            for r in rows:
                s = r['source'] or 'claude_code'
                if s in source_meta:
                    source_meta[s]['count'] = r['cnt']
        except Exception:
            pass
        conn.close()

        # Source is always set (enforced by do_GET redirect)
        qs = f"?source={sf}" if sf else "?source=claude_code"

        # Source label for title
        source_labels = {'claude_code': 'Claude Code', 'copilot': 'Copilot CLI', 'codex': 'Codex CLI'}
        title_suffix = f' — {source_labels.get(sf, sf)}' if sf else ''

        def nl(key, label, href):
            c = "active" if active == key else ""
            icon = NAV_ICONS.get(key, "")
            link = f'{href}{qs}'
            return f'<a href="{link}" class="sidebar-link {c}">{icon}<span>{label}</span></a>'

        # Build workspace switcher — no "All" option, each tool is isolated
        ws_pills = []
        for key, meta in source_meta.items():
            if meta['count'] == 0:
                continue
            is_active = sf == key
            pill_style = f'background:{meta["color"]}; color:#000; border-color:{meta["color"]};' if is_active else ''
            ws_pills.append(f'<a href="/?source={key}" style="padding:4px 10px; border-radius:12px; font-size:11px; text-decoration:none; border:1px solid var(--border); color:var(--text); {pill_style}">{meta["icon"]} {meta["label"]} <span style="opacity:0.7;">({meta["count"]})</span></a>')
        ws_html = '<div style="display:flex; flex-wrap:wrap; gap:6px; padding:12px 16px; border-bottom:1px solid var(--border);">' + ''.join(ws_pills) + '</div>'

        return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><title>{title}{title_suffix} — Memory Engine</title>
<style>{CSS}</style>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head><body>

<button class="hamburger" onclick="toggleSidebar()">&#9776;</button>
<div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>

<div class="sidebar" id="sidebar">
    <div class="sidebar-brand">
        <span class="live-dot"></span>
        <h1>Memory Engine</h1>
    </div>

    {ws_html}

    <div class="sidebar-section">Home</div>
    {nl("home", "Dashboard", "/")}

    <div class="sidebar-section">Search</div>
    {nl("search", "Search", "/search")}
    {nl("semantic", "Semantic", "/semantic")}

    <div class="sidebar-section">Browse</div>
    {nl("timeline", "Timeline", "/timeline")}
    {nl("sessions", "Sessions", "/sessions")}
    {nl("topics", "Topics", "/topics")}

    <div class="sidebar-section">Organize</div>
    {nl("projects", "Projects", "/projects")}
    {nl("observations", "Observations", "/observations")}

    <div class="sidebar-section">Live</div>
    {nl("live", "Live View", "/live")}

    <div class="sidebar-footer">
        {total:,} entries<br>{sessions} sessions
    </div>
</div>

<div class="main-content">
    <div class="page-title"><h2>{title}{title_suffix}</h2></div>
    <div class="container">{body}</div>
</div>

<script>
function toggleSidebar() {{
    document.getElementById('sidebar').classList.toggle('open');
    document.getElementById('sidebarOverlay').classList.toggle('open');
}}
</script>
</body></html>"""

    def handle_home(self, params):
        """Dashboard home page with overview stats."""
        sf = params.get("source", [""])[0]  # source filter
        conn = get_db()

        if sf:
            total_entries = conn.execute("SELECT COUNT(*) FROM entries WHERE source=?", (sf,)).fetchone()[0]
            total_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='done' AND source=?", (sf,)).fetchone()[0]
        else:
            total_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            total_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='done'").fetchone()[0]
        try:
            total_knowledge = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        except Exception:
            total_knowledge = 0
        try:
            total_observations = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        except Exception:
            total_observations = 0

        # Stats row
        body = '<div class="stats-grid">'
        body += f'<div class="stat-card"><div class="label">Entries</div><div class="value">{total_entries:,}</div></div>'
        body += f'<div class="stat-card"><div class="label">Sessions</div><div class="value">{total_sessions:,}</div></div>'
        body += f'<div class="stat-card"><div class="label">Knowledge</div><div class="value">{total_knowledge:,}</div></div>'
        body += f'<div class="stat-card"><div class="label">Observations</div><div class="value">{total_observations:,}</div></div>'
        body += '</div>'

        # Per-source breakdown
        try:
            source_rows = conn.execute("SELECT source, COUNT(*) as cnt FROM entries GROUP BY source ORDER BY cnt DESC").fetchall()
            if source_rows:
                source_colors = {'claude_code': 'var(--accent)', 'copilot': 'var(--green)', 'codex': 'var(--yellow)'}
                source_labels = {'claude_code': 'Claude Code', 'copilot': 'Copilot CLI', 'codex': 'Codex CLI'}
                body += '<div style="display:flex; gap:8px; margin-bottom:20px; flex-wrap:wrap;">'
                for sr in source_rows:
                    sname = sr['source'] or 'claude_code'
                    slabel = source_labels.get(sname, sname)
                    scolor = source_colors.get(sname, 'var(--text2)')
                    body += f'<div style="display:inline-flex; align-items:center; gap:6px; padding:6px 14px; background:var(--bg2); border:1px solid var(--border); border-radius:20px; font-size:12px;">'
                    body += f'<span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:{scolor};"></span>'
                    body += f'<span style="color:var(--text);">{escape(slabel)}</span>'
                    body += f'<span style="color:var(--text2); font-weight:bold;">{sr["cnt"]:,}</span>'
                    body += '</div>'
                body += '</div>'
        except Exception:
            pass

        # Two-column layout
        body += '<div style="display:grid; grid-template-columns:2fr 1fr; gap:20px; margin-top:8px;">'

        # Left column
        body += '<div>'

        # Quick search
        sf_hidden = f'<input type="hidden" name="source" value="{sf}">' if sf else ''
        body += f'''<div class="entry" style="margin-bottom:12px;">
            <div style="color:var(--text2); font-size:11px; text-transform:uppercase; margin-bottom:8px; letter-spacing:1px;">Quick Search</div>
            <form method="get" action="/search">
                {sf_hidden}
                <input class="search-box" type="text" name="q" placeholder="Search conversations..." style="margin-bottom:0;">
            </form>
        </div>'''

        # Recent sessions
        if sf:
            recent = conn.execute("""
                SELECT s.id, COUNT(e.id) as entry_count, MAX(e.timestamp) as last_ts
                FROM sessions s LEFT JOIN entries e ON e.session_id = s.id
                WHERE s.status = 'done' AND s.source = ?
                GROUP BY s.id ORDER BY s.last_processed_at DESC LIMIT 8
            """, (sf,)).fetchall()
        else:
            recent = conn.execute("""
                SELECT s.id, COUNT(e.id) as entry_count, MAX(e.timestamp) as last_ts
                FROM sessions s LEFT JOIN entries e ON e.session_id = s.id
                WHERE s.status = 'done'
                GROUP BY s.id ORDER BY s.last_processed_at DESC LIMIT 8
            """).fetchall()

        body += '<div class="entry"><div style="color:var(--text2); font-size:11px; text-transform:uppercase; margin-bottom:10px; letter-spacing:1px;">Recent Activity</div>'
        if recent:
            for r in recent:
                sid = r["id"][:8] if r["id"] else "?"
                ts = (r["last_ts"] or "?")[:16]
                ec = r["entry_count"] or 0
                body += f'<a href="/session?id={html.escape(r["id"])}" style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--border); text-decoration:none;">'
                body += f'<span style="color:var(--accent); font-size:12px;">{sid}...</span>'
                body += f'<span style="color:var(--text2); font-size:11px;">{ec} entries &middot; {ts}</span>'
                body += '</a>'
        else:
            body += '<div style="color:var(--text2); padding:12px 0;">No sessions yet. Run ingestion from <a href="/setup">Setup</a>.</div>'
        body += '</div>'
        body += '</div>'  # end left column

        # Right column
        body += '<div>'

        # Top topics
        body += '<div class="entry" style="margin-bottom:12px;"><div style="color:var(--text2); font-size:11px; text-transform:uppercase; margin-bottom:10px; letter-spacing:1px;">Top Topics</div>'
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from engine import MemoryEngine
            eng = MemoryEngine()
            raw = eng.topic_list_all(min_hits=10, limit=30)
            code_stops = {"the","and","this","that","for","with","not","from","but","are","was","were","been","have","has","had","will","would","could","should"}
            topics = [(w, c) for w, c in raw if w.lower() not in code_stops][:6]
            eng.conn.close()
            for word, count in topics:
                body += f'<a href="/topic?q={html.escape(word)}" style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid var(--border); text-decoration:none;">'
                body += f'<span style="font-size:12px;">{html.escape(word)}</span>'
                body += f'<span style="color:var(--text2); font-size:11px;">{count}</span></a>'
            if not topics:
                body += '<div style="color:var(--text2); font-size:12px;">No topic data yet.</div>'
        except Exception:
            body += '<div style="color:var(--text2); font-size:12px;">Run ingestion to see topics.</div>'
        body += '</div>'

        # System health
        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        try:
            fts_count = conn.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0]
            fts_html = f'<span style="color:var(--green);">Active ({fts_count:,})</span>'
        except Exception:
            fts_html = '<span style="color:var(--red);">Unavailable</span>'
        try:
            last_ingest = conn.execute("SELECT MAX(finished_at) FROM ingest_log WHERE status='done'").fetchone()[0]
            last_ingest = (last_ingest or "Never")[:19]
        except Exception:
            last_ingest = "Unknown"

        body += '<div class="entry"><div style="color:var(--text2); font-size:11px; text-transform:uppercase; margin-bottom:10px; letter-spacing:1px;">System</div>'
        body += f'<div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid var(--border); font-size:12px;"><span>DB Size</span><span style="color:var(--text2);">{db_size / 1024 / 1024:.1f} MB</span></div>'
        body += f'<div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid var(--border); font-size:12px;"><span>FTS Index</span>{fts_html}</div>'
        body += f'<div style="display:flex; justify-content:space-between; padding:5px 0; font-size:12px;"><span>Last Ingest</span><span style="color:var(--text2);">{last_ingest}</span></div>'
        body += '</div>'

        body += '</div>'  # end right column
        body += '</div>'  # end grid

        conn.close()
        self.send_html(self.page_wrap("Dashboard", body, active="home", source_filter=sf))

    def handle_search(self, params):
        query = params.get("q", [""])[0]
        role = params.get("role", [""])[0]
        days = int(params.get("days", ["0"])[0] or 0)
        source = params.get("source", [""])[0]
        page = int(params.get("page", ["1"])[0] or 1)
        per_page = 50
        offset = (page - 1) * per_page

        body = f"""
        <form method="get" action="/search">
            <input class="search-box" type="text" name="q" value="{escape(query)}"
                   placeholder="Search conversations... (FTS5: AND, OR, NOT, &quot;phrases&quot;)" autofocus>
            <div class="filters">
                <select name="role">
                    <option value="">All roles</option>
                    <option value="user" {'selected' if role=='user' else ''}>User</option>
                    <option value="assistant" {'selected' if role=='assistant' else ''}>Assistant</option>
                    <option value="system" {'selected' if role=='system' else ''}>System</option>
                </select>
                <select name="days">
                    <option value="0" {'selected' if days==0 else ''}>All time</option>
                    <option value="1" {'selected' if days==1 else ''}>Today</option>
                    <option value="7" {'selected' if days==7 else ''}>7 days</option>
                    <option value="30" {'selected' if days==30 else ''}>30 days</option>
                </select>
                <select name="source">
                    <option value="">All sources</option>
                    <option value="claude_code" {'selected' if source=='claude_code' else ''}>Claude Code</option>
                    <option value="copilot" {'selected' if source=='copilot' else ''}>Copilot CLI</option>
                    <option value="codex" {'selected' if source=='codex' else ''}>Codex CLI</option>
                </select>
                <input type="submit" value="Search" style="cursor:pointer; background:var(--accent); color:#000; border:none; padding:6px 16px; border-radius:6px; font-weight:bold;">
            </div>
        </form>"""

        conn = get_db()

        if query:
            # FTS search
            try:
                # Sanitize query
                safe_q = query
                if not any(op in query.upper() for op in [' AND ', ' OR ', ' NOT ', '"']):
                    tokens = query.split()
                    safe_tokens = []
                    for t in tokens:
                        if re.search(r'[-./:]', t):
                            safe_tokens.append(f'"{t}"')
                        else:
                            safe_tokens.append(t)
                    safe_q = ' '.join(safe_tokens)

                sql = """
                    SELECT e.id, e.content, e.role, e.session_id, e.timestamp, e.source
                    FROM entries_fts fts
                    JOIN entries e ON e.id = fts.rowid
                    WHERE entries_fts MATCH ?
                """
                sql_params = [safe_q]

                if role:
                    sql += " AND e.role = ?"
                    sql_params.append(role)
                if days:
                    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                    sql += " AND e.timestamp >= ?"
                    sql_params.append(cutoff)
                if source:
                    sql += " AND e.source = ?"
                    sql_params.append(source)

                # Count
                count_sql = f"SELECT COUNT(*) FROM ({sql})"
                total_results = conn.execute(count_sql, sql_params).fetchone()[0]

                sql += f" ORDER BY rank LIMIT ? OFFSET ?"
                sql_params.extend([per_page, offset])
                rows = conn.execute(sql, sql_params).fetchall()

                body += f'<p style="color:var(--text2); margin-bottom:12px;">Found {total_results:,} results for "{escape(query)}"</p>'

                for r in rows:
                    content = render_content(r["content"], max_len=1000)
                    # Highlight search terms
                    for term in query.split():
                        term_clean = term.strip('"')
                        if term_clean and term_clean.upper() not in ('AND', 'OR', 'NOT'):
                            pattern = re.compile(re.escape(term_clean), re.IGNORECASE)
                            content = pattern.sub(f'<span class="highlight">\\g<0></span>', content)

                    ts = r["timestamp"][:19] if r["timestamp"] else "?"
                    sid = r["session_id"][:8] if r["session_id"] else "?"
                    try:
                        source_name = r['source'] or 'claude_code'
                    except (KeyError, IndexError):
                        source_name = 'claude_code'
                    source_label = {'claude_code': 'Claude', 'copilot': 'Copilot', 'codex': 'Codex'}.get(source_name, source_name)
                    body += f"""
                    <div class="entry">
                        <div class="meta">
                            <span class="role {r['role']}">{r['role']}</span>
                            <span class="source-badge {source_name}">{source_label}</span>
                            <span>{ts}</span>
                            <a href="/session?id={escape(r['session_id'])}">{sid}…</a>
                        </div>
                        <div class="content">{content}</div>
                    </div>"""

                # Pagination
                total_pages = (total_results + per_page - 1) // per_page
                if total_pages > 1:
                    body += '<div class="pagination">'
                    for p in range(1, min(total_pages + 1, 20)):
                        cls = "current" if p == page else ""
                        body += f'<a href="/search?q={escape(query)}&role={role}&days={days}&source={source}&page={p}" class="{cls}">{p}</a>'
                    body += '</div>'

            except Exception as e:
                body += f'<div class="empty">Search error: {escape(str(e))}</div>'
        else:
            # Show recent entries
            sql = "SELECT * FROM entries"
            sql_params = []
            conditions = []

            if role:
                conditions.append("role = ?")
                sql_params.append(role)
            if days:
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                conditions.append("timestamp >= ?")
                sql_params.append(cutoff)
            if source:
                conditions.append("source = ?")
                sql_params.append(source)

            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

            sql += f" ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            sql_params.extend([per_page, offset])

            rows = conn.execute(sql, sql_params).fetchall()

            body += '<p style="color:var(--text2); margin-bottom:12px;">Recent entries (newest first)</p>'

            for r in rows:
                content = render_content(r["content"], max_len=1000)
                ts = r["timestamp"][:19] if r["timestamp"] else "?"
                sid = r["session_id"][:8] if r["session_id"] else "?"
                try:
                    source_name = r['source'] or 'claude_code'
                except (KeyError, IndexError):
                    source_name = 'claude_code'
                source_label = {'claude_code': 'Claude', 'copilot': 'Copilot', 'codex': 'Codex'}.get(source_name, source_name)
                body += f"""
                <div class="entry">
                    <div class="meta">
                        <span class="role {r['role']}">{r['role']}</span>
                        <span class="source-badge {source_name}">{source_label}</span>
                        <span>{ts}</span>
                        <a href="/session?id={escape(r['session_id'])}">{sid}…</a>
                    </div>
                    <div class="content">{content}</div>
                </div>"""

        conn.close()
        self.send_html(self.page_wrap("Search", body, active="search", source_filter=source))

    def handle_timeline(self, params):
        sf = params.get("source", [""])[0]
        conn = get_db()

        # Daily stats for last 30 days
        rows = conn.execute("""
            SELECT date(timestamp) as day, COUNT(*) as cnt,
                   SUM(CASE WHEN role='user' THEN 1 ELSE 0 END) as user_cnt,
                   SUM(CASE WHEN role='assistant' THEN 1 ELSE 0 END) as asst_cnt
            FROM entries
            WHERE timestamp >= date('now', '-30 days')
            GROUP BY day ORDER BY day
        """).fetchall()

        max_cnt = max((r["cnt"] for r in rows), default=1)

        bars = ""
        for r in rows:
            if r["day"]:
                h = max(int(r["cnt"] / max_cnt * 100), 2)
                bars += f"""<div class="bar" style="height:{h}px">
                    <div class="tip">{r['day']}<br>{r['cnt']:,} entries<br>U:{r['user_cnt']} A:{r['asst_cnt']}</div>
                </div>"""

        # Role breakdown
        role_stats = conn.execute("SELECT role, COUNT(*) as cnt FROM entries GROUP BY role ORDER BY cnt DESC").fetchall()
        total = sum(r["cnt"] for r in role_stats)

        stats_html = ""
        for r in role_stats:
            pct = (r["cnt"] / total * 100) if total else 0
            stats_html += f"""<div class="stat-card">
                <div class="label">{r['role']}</div>
                <div class="value">{r['cnt']:,}</div>
                <div style="color:var(--text2); font-size:11px;">{pct:.1f}%</div>
            </div>"""

        total_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        total_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='done'").fetchone()[0]
        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0

        body = f"""
        <div class="stats-grid">
            <div class="stat-card"><div class="label">Total Entries</div><div class="value">{total_entries:,}</div></div>
            <div class="stat-card"><div class="label">Sessions</div><div class="value">{total_sessions}</div></div>
            <div class="stat-card"><div class="label">DB Size</div><div class="value">{db_size / 1024 / 1024:.1f} MB</div></div>
            {stats_html}
        </div>
        <h3 style="margin-bottom:8px; color:var(--text2);">Last 30 Days</h3>
        <div class="timeline-bar">{bars}</div>
        """

        conn.close()
        self.send_html(self.page_wrap("Timeline", body, active="timeline", source_filter=sf))

    def handle_sessions(self, params):
        source = params.get("source", [""])[0]
        conn = get_db()

        body = f"""
        <form method="get" action="/sessions" style="margin-bottom:16px;">
            <div class="filters">
                <select name="source">
                    <option value="">All sources</option>
                    <option value="claude_code" {'selected' if source=='claude_code' else ''}>Claude Code</option>
                    <option value="copilot" {'selected' if source=='copilot' else ''}>Copilot CLI</option>
                    <option value="codex" {'selected' if source=='codex' else ''}>Codex CLI</option>
                </select>
                <input type="submit" value="Filter" style="cursor:pointer; background:var(--accent); color:#000; border:none; padding:6px 16px; border-radius:6px; font-weight:bold;">
            </div>
        </form>"""

        sessions_sql = """
            SELECT s.id, s.file_size, s.lines_processed, s.last_processed_at,
                   COUNT(e.id) as entry_count,
                   SUM(CASE WHEN e.role='user' THEN 1 ELSE 0 END) as user_cnt,
                   SUM(CASE WHEN e.role='assistant' THEN 1 ELSE 0 END) as asst_cnt,
                   MIN(e.timestamp) as first_ts
            FROM sessions s
            LEFT JOIN entries e ON e.session_id = s.id
            WHERE s.status = 'done'
        """
        sessions_params = []
        if source:
            sessions_sql += " AND s.source = ?"
            sessions_params.append(source)
        sessions_sql += """
            GROUP BY s.id
            ORDER BY s.last_processed_at DESC
            LIMIT 50
        """
        rows = conn.execute(sessions_sql, sessions_params).fetchall()

        body += '<ul class="session-list">'
        for r in rows:
            sid = r["id"][:8] if r["id"] else "?"
            first = r["first_ts"][:10] if r["first_ts"] else "?"
            size_kb = (r["file_size"] or 0) / 1024
            body += f"""
            <li class="session-item">
                <div>
                    <a href="/session?id={escape(r['id'])}" class="id">{sid}…</a>
                    <span class="info" style="margin-left:8px;">{first}</span>
                </div>
                <div class="info">
                    {r['entry_count']:,} entries · U:{r['user_cnt'] or 0} A:{r['asst_cnt'] or 0} · {size_kb:.0f} KB
                </div>
            </li>"""
        body += "</ul>"

        conn.close()
        self.send_html(self.page_wrap("Sessions", body, active="sessions", source_filter=source))

    def handle_session_detail(self, params):
        sf = params.get("source", [""])[0]
        session_id = params.get("id", [""])[0]
        page = int(params.get("page", ["1"])[0] or 1)
        per_page = 200
        offset = (page - 1) * per_page

        if not session_id:
            self.send_html(self.page_wrap("Session", '<div class="empty">No session ID</div>', source_filter=sf))
            return

        conn = get_db()
        total = conn.execute("SELECT COUNT(*) FROM entries WHERE session_id = ?", (session_id,)).fetchone()[0]
        rows = conn.execute("""
            SELECT * FROM entries WHERE session_id = ?
            ORDER BY source_line ASC LIMIT ? OFFSET ?
        """, (session_id, per_page, offset)).fetchall()

        sid_short = session_id[:8]

        # ── Build digest TOC for the full session ──
        all_rows = conn.execute("""
            SELECT id, content, role, timestamp, source_line
            FROM entries WHERE session_id = ? ORDER BY source_line ASC
        """, (session_id,)).fetchall()

        segments = []
        current_seg = None
        tool_count_total = 0
        for e in all_rows:
            c = e["content"] or ""
            is_tool = c.startswith("[TOOL:") or c.startswith('{"result":')
            is_user = e["role"] == "user" and not is_tool
            if is_tool:
                tool_count_total += 1
            if is_user:
                if current_seg:
                    segments.append(current_seg)
                title = c[:100].replace("\n", " ").strip()
                if len(c) > 100:
                    title += "…"
                current_seg = {
                    "title": title,
                    "line": e["source_line"],
                    "ts": (e["timestamp"] or "")[:16],
                    "entries": 1,
                    "tools": 0,
                }
            elif current_seg:
                current_seg["entries"] += 1
                if is_tool:
                    current_seg["tools"] += 1
            else:
                current_seg = {"title": "(session start)", "line": e["source_line"],
                               "ts": (e["timestamp"] or "")[:16], "entries": 1, "tools": 1 if is_tool else 0}
        if current_seg:
            segments.append(current_seg)

        # ── Header ──
        body = f'<h3 style="margin-bottom:4px;">Session {sid_short}… <span style="color:var(--text2); font-weight:normal;">({total:,} entries, {tool_count_total} tool calls, {len(segments)} turns)</span></h3>'

        # Show project badges
        try:
            from engine import MemoryEngine
            _eng = MemoryEngine()
            session_projects = _eng.get_session_projects(session_id)
            _eng.close()
            if session_projects:
                body += '<div style="display:flex; gap:6px; margin-bottom:12px; flex-wrap:wrap;">'
                import re as _re
                for sp in session_projects:
                    pc = sp.get("color") or "#58a6ff"
                    if not _re.match(r'^#[0-9a-fA-F]{3,8}$', pc):
                        pc = "#58a6ff"
                    body += f'<a href="/project?id={sp["id"]}" style="padding:3px 10px; border-radius:12px; background:{pc}22; color:{pc}; font-size:11px; text-decoration:none; border:1px solid {pc}44;">{escape(sp["name"])}</a>'
                body += '</div>'
        except Exception:
            pass

        # ── Summary Panel ──
        summary_row = conn.execute("SELECT summary FROM sessions WHERE id = ?", (session_id,)).fetchone()
        session_summary = summary_row["summary"] if summary_row and summary_row["summary"] else None
        if session_summary:
            body += f'''<div style="background: linear-gradient(135deg, rgba(88,166,255,0.08), rgba(124,58,237,0.08)); border:1px solid rgba(88,166,255,0.2); border-radius:10px; padding:16px 20px; margin-bottom:16px;">
                <div style="font-size:10px; font-weight:bold; text-transform:uppercase; letter-spacing:0.1em; color:var(--accent); margin-bottom:8px;">Session Summary</div>
                <div style="font-size:13px; line-height:1.6; color:var(--text1); white-space:pre-wrap;">{escape(session_summary)}</div>
            </div>'''
        else:
            body += f'''<div style="background:var(--bg2); border:1px dashed var(--border); border-radius:10px; padding:12px 20px; margin-bottom:16px; text-align:center;">
                <span style="font-size:12px; color:var(--text2);">No summary yet — run <code>/summarize {sid_short}</code> in Claude Code to generate one</span>
            </div>'''

        body += f'''<div style="display:flex; gap:12px; margin-bottom:16px; align-items:center;">
            <a href="/sessions" style="color:var(--text2);">← Back</a>
            <a href="/api/export?id={escape(session_id)}" style="color:var(--accent); font-size:12px;">⬇ Export JSON</a>
            <button onclick="document.getElementById('toc').style.display=document.getElementById('toc').style.display==='none'?'block':'none'" style="background:var(--bg2); border:1px solid var(--border); color:var(--text2); padding:3px 10px; border-radius:4px; cursor:pointer; font-size:12px;">📑 Table of Contents ({len(segments)} turns)</button>
            <button onclick="document.querySelectorAll('.tool-group').forEach(el=>el.open=!el.open)" style="background:var(--bg2); border:1px solid var(--border); color:var(--text2); padding:3px 10px; border-radius:4px; cursor:pointer; font-size:12px;">🔧 Toggle Tools</button>
        </div>'''

        # ── Table of Contents ──
        body += '<div id="toc" style="display:none; background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:16px; max-height:400px; overflow-y:auto;">'
        body += '<div style="font-size:11px; font-weight:bold; color:var(--text2); margin-bottom:8px;">CONVERSATION MAP</div>'
        for i, seg in enumerate(segments):
            tc_badge = f' <span style="color:var(--text2); opacity:0.5;">[{seg["tools"]} tools]</span>' if seg["tools"] else ""
            # Determine which page this segment's line falls on
            seg_page = (seg["line"] // per_page) + 1
            body += f'<a href="/session?id={escape(session_id)}&page={seg_page}&source={sf}#L{seg["line"]}" style="display:block; padding:3px 8px; margin-bottom:2px; border-radius:4px; font-size:11px; text-decoration:none; color:var(--text1); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" onmouseover="this.style.background=\'var(--bg3)\'" onmouseout="this.style.background=\'transparent\'">'
            body += f'<span style="color:var(--text2); width:35px; display:inline-block;">#{i+1}</span>'
            body += f'<span style="color:var(--accent); width:50px; display:inline-block;">L{seg["line"]}</span>'
            body += f'{escape(seg["title"][:80])}{tc_badge}</a>'
        body += '</div>'

        # ── Entries with tool collapsing ──
        tool_buffer = []

        def flush_tools():
            nonlocal tool_buffer
            if not tool_buffer:
                return ""
            n = len(tool_buffer)
            # Extract tool names
            names = []
            for tb in tool_buffer:
                c = tb["content"] or ""
                if c.startswith("[TOOL:"):
                    end = c.find("]")
                    if end > 0:
                        names.append(c[6:end])
                else:
                    names.append("result")
            unique_names = list(dict.fromkeys(names))
            label = ", ".join(unique_names[:5])
            if len(unique_names) > 5:
                label += f" +{len(unique_names)-5}"

            html_out = f'<details class="tool-group" style="margin:4px 0; border:1px solid var(--border); border-radius:6px; background:var(--bg2);">'
            html_out += f'<summary style="padding:6px 12px; cursor:pointer; font-size:11px; color:var(--text2);">🔧 {n} tool call{"s" if n>1 else ""}: {escape(label)}</summary>'
            html_out += '<div style="padding:4px 12px 8px;">'
            for tb in tool_buffer:
                content = render_content(tb["content"], max_len=500)
                ts = tb["timestamp"][:19] if tb["timestamp"] else "?"
                html_out += f'<div style="padding:4px 0; border-bottom:1px solid var(--border); font-size:11px;"><span style="color:var(--text2);">{ts} L{tb["source_line"]}</span><pre style="margin:2px 0; white-space:pre-wrap; font-size:11px; opacity:0.7;">{content}</pre></div>'
            html_out += '</div></details>'
            tool_buffer = []
            return html_out

        for r in rows:
            content_raw = r["content"] or ""
            is_tool = content_raw.startswith("[TOOL:") or content_raw.startswith('{"result":')

            if is_tool:
                tool_buffer.append(r)
                continue

            # Flush any pending tools before this non-tool entry
            body += flush_tools()

            content = render_content(content_raw, max_len=2000)
            ts = r["timestamp"][:19] if r["timestamp"] else "?"
            try:
                source_name = r['source'] or 'claude_code'
            except (KeyError, IndexError):
                source_name = 'claude_code'
            source_label = {'claude_code': 'Claude', 'copilot': 'Copilot', 'codex': 'Codex'}.get(source_name, source_name)
            body += f"""
            <div class="entry" id="L{r['source_line']}">
                <div class="meta">
                    <span class="role {r['role']}">{r['role']}</span>
                    <span class="source-badge {source_name}">{source_label}</span>
                    <span>{ts}</span>
                    <span>line {r['source_line']}</span>
                </div>
                <div class="content">{content}</div>
            </div>"""

        # Flush remaining tools
        body += flush_tools()

        # Pagination
        total_pages = (total + per_page - 1) // per_page
        if total_pages > 1:
            body += '<div class="pagination">'
            for p in range(1, min(total_pages + 1, 50)):
                cls = "current" if p == page else ""
                body += f'<a href="/session?id={escape(session_id)}&page={p}&source={sf}" class="{cls}">{p}</a>'
            if total_pages > 50:
                body += f'<span style="color:var(--text2);"> … {total_pages}</span>'
            body += '</div>'

        conn.close()
        self.send_html(self.page_wrap(f"Session {sid_short}", body, source_filter=sf))

    def handle_topics(self, params):
        sf = params.get("source", [""])[0]
        conn = get_db()

        # Import engine for topic analysis
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from engine import MemoryEngine
        eng = MemoryEngine()

        # Project-level topics (filter out generic code terms)
        code_stops = {
            'true', 'false', 'none', 'null', 'string', 'type', 'name', 'value',
            'const', 'function', 'return', 'import', 'export', 'default', 'class',
            'async', 'await', 'error', 'status', 'data', 'path', 'file', 'line',
            'test', 'echo', 'read', 'write', 'bash', 'command', 'output', 'result',
            'message', 'content', 'text', 'list', 'item', 'index', 'response',
            'config', 'settings', 'created', 'updated', 'check', 'home', 'user',
            'params', 'query', 'server', 'client', 'port', 'host', 'http',
            'https', 'json', 'html', 'title', 'description', 'args', 'options',
            'entries', 'count', 'total', 'successfully', 'running', 'process',
        }

        raw_topics = eng.topic_list_all(min_hits=10, limit=200)
        topics = [(w, c) for w, c in raw_topics if w not in code_stops][:60]
        max_count = topics[0][1] if topics else 1

        body = '<h3 style="margin-bottom:16px; color:var(--text2);">Discovered Topics (by mention frequency)</h3>'
        body += '<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:24px;">'
        for word, count in topics:
            # Size based on frequency
            size = max(12, min(28, int(12 + (count / max_count) * 16)))
            opacity = max(0.5, min(1.0, count / max_count))
            body += f'<a href="/topic?q={escape(word)}" style="font-size:{size}px; opacity:{opacity}; padding:4px 10px; background:var(--bg2); border:1px solid var(--border); border-radius:6px; display:inline-block;">{escape(word)} <span style="font-size:10px; color:var(--text2);">{count}</span></a>'
        body += '</div>'

        # Top topics as list
        body += '<div style="margin-top:24px;">'
        for i, (word, count) in enumerate(topics[:30], 1):
            bar_w = int(count / max_count * 300)
            body += f"""
            <div style="display:flex; align-items:center; gap:12px; margin-bottom:4px;">
                <span style="width:30px; text-align:right; color:var(--text2); font-size:11px;">{i}.</span>
                <a href="/topic?q={escape(word)}" style="width:150px;">{escape(word)}</a>
                <div style="background:var(--accent); height:16px; width:{bar_w}px; border-radius:3px; opacity:0.7;"></div>
                <span style="color:var(--text2); font-size:11px;">{count}</span>
            </div>"""
        body += '</div>'

        eng.close()
        conn.close()
        self.send_html(self.page_wrap("Topics", body, active="topics", source_filter=sf))

    def handle_topic_detail(self, params):
        sf = params.get("source", [""])[0]
        topic = params.get("q", [""])[0]
        if not topic:
            self.send_html(self.page_wrap("Topic", '<div class="empty">No topic specified</div>', source_filter=sf))
            return

        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from engine import MemoryEngine
        eng = MemoryEngine()

        data = eng.topic_deep_search(topic, limit=300)

        body = f'<h3 style="margin-bottom:4px;">Topic: {escape(topic)}</h3>'
        body += f'<p style="color:var(--text2); margin-bottom:16px;">{data["total_hits"]} mentions across {data["sessions_count"]} sessions · <a href="/topics">← All topics</a></p>'

        if not data["sessions"]:
            body += '<div class="empty">No data found for this topic.</div>'
        else:
            for s in data["sessions"]:
                date = s["first_ts"][:10] if s["first_ts"] else "?"
                sid = s["session_id"][:8] if s["session_id"] else "?"
                tools = ", ".join(s["tools_used"][:8]) if s["tools_used"] else ""

                body += f"""
                <div class="entry" style="margin-bottom:12px;">
                    <div class="meta">
                        <span style="color:var(--accent); font-weight:bold;">{date}</span>
                        <a href="/session?id={escape(s['session_id'])}">{sid}…</a>
                        <span>{s['hit_count']} hits</span>
                        {'<span style="color:var(--text2);">tools: ' + escape(tools) + '</span>' if tools else ''}
                    </div>
                    <div class="content" style="margin-top:8px;">"""

                for msg in s["user_msgs"][:3]:
                    short = escape(msg[:300])
                    body += f'<div style="margin-bottom:6px;"><span class="role user" style="margin-right:6px;">user</span>{short}</div>'

                for msg in s["assistant_msgs"][:3]:
                    short = escape(msg[:300])
                    body += f'<div style="margin-bottom:6px;"><span class="role assistant" style="margin-right:6px;">assistant</span>{short}</div>'

                body += '</div></div>'

        # Link to full search
        body += f'<p style="margin-top:16px;"><a href="/search?q={escape(topic)}">→ Full search results for "{escape(topic)}"</a></p>'

        eng.close()
        self.send_html(self.page_wrap(f"Topic: {topic}", body, active="topics", source_filter=sf))

    def _get_sem_engine(self):
        """Get a SemanticEngine instance (lazy import)."""
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from semantic import SemanticEngine
        return SemanticEngine()

    def _render_result_entry(self, r, i, show_context=False, show_similar_link=True):
        """Render a single semantic result as HTML."""
        sim = r.get("similarity", 0)
        hybrid = r.get("hybrid_score", sim)
        role_val = r.get("role", "?")
        ts = r.get("timestamp", "?")[:19] if r.get("timestamp") else "?"
        sid = r.get("session_id", "")[:8] if r.get("session_id") else "?"
        sqlite_id = r.get("sqlite_id", 0)
        content = render_content(r.get("content", ""), max_len=1500)

        # Score display
        sem_s = r.get("sem_score", sim)
        fts_s = r.get("fts_score", 0)
        score_label = f"{hybrid:.3f}"
        if fts_s > 0 and sem_s > 0:
            score_label += f" (sem:{sem_s:.2f} + kw:{fts_s:.2f})"

        # Color code
        if hybrid >= 0.6:
            sim_color = "var(--green)"
        elif hybrid >= 0.4:
            sim_color = "var(--yellow)"
        else:
            sim_color = "var(--red)"

        bar_w = int(hybrid * 250)

        links = f'<a href="/session?id={escape(r.get("session_id", ""))}">{sid}...</a>'
        if show_similar_link and sqlite_id:
            links += f' · <a href="/semantic?similar={sqlite_id}" style="color:var(--purple);">find similar</a>'
        if sqlite_id:
            links += f' · <a href="/semantic?context={sqlite_id}" style="color:var(--yellow);">context</a>'

        html_out = f"""
        <div class="entry" style="border-left: 3px solid {sim_color};">
            <div class="meta">
                <span style="color:{sim_color}; font-weight:bold; font-size:12px;">#{i} {score_label}</span>
                <div style="background:{sim_color}; height:4px; width:{bar_w}px; border-radius:2px; opacity:0.6;"></div>
                <span class="role {role_val}">{role_val}</span>
                <span>{ts}</span>
                {links}
            </div>
            <div class="content">{content}</div>
        </div>"""
        return html_out

    def handle_semantic(self, params):
        sf = params.get("source", [""])[0]
        query = params.get("q", [""])[0]
        role = params.get("role", [""])[0]
        n = int(params.get("n", ["20"])[0] or 20)
        mode = params.get("mode", ["hybrid"])[0]  # hybrid, semantic, keyword
        days = int(params.get("days", ["0"])[0] or 0)
        similar_id = int(params.get("similar", ["0"])[0] or 0)
        context_id = int(params.get("context", ["0"])[0] or 0)

        # Build form
        body = f"""
        <form method="get" action="/semantic">
            <input class="search-box" type="text" name="q" value="{escape(query)}"
                   placeholder="Search by meaning — hybrid combines semantic + keyword matching..." autofocus>
            <div class="filters">
                <select name="mode">
                    <option value="hybrid" {'selected' if mode=='hybrid' else ''}>Hybrid (semantic + keyword)</option>
                    <option value="semantic" {'selected' if mode=='semantic' else ''}>Semantic only</option>
                    <option value="keyword" {'selected' if mode=='keyword' else ''}>Keyword only (FTS)</option>
                </select>
                <select name="role">
                    <option value="">All roles</option>
                    <option value="user" {'selected' if role=='user' else ''}>User</option>
                    <option value="assistant" {'selected' if role=='assistant' else ''}>Assistant</option>
                </select>
                <select name="days">
                    <option value="0" {'selected' if days==0 else ''}>All time</option>
                    <option value="1" {'selected' if days==1 else ''}>Today</option>
                    <option value="7" {'selected' if days==7 else ''}>7 days</option>
                    <option value="30" {'selected' if days==30 else ''}>30 days</option>
                </select>
                <select name="n">
                    <option value="10" {'selected' if n==10 else ''}>10 results</option>
                    <option value="20" {'selected' if n==20 else ''}>20 results</option>
                    <option value="50" {'selected' if n==50 else ''}>50 results</option>
                </select>
                <input type="submit" value="Search" style="cursor:pointer; background:var(--purple); color:#000; border:none; padding:6px 16px; border-radius:6px; font-weight:bold;">
            </div>
        </form>"""

        try:
            sem = self._get_sem_engine()
            stats = sem.stats()

            # === FIND SIMILAR MODE ===
            if similar_id:
                body += f'<p style="color:var(--purple); margin-bottom:12px; font-weight:bold;">Entries similar to #{similar_id}</p>'
                results = sem.find_similar(similar_id, n_results=n)
                if results:
                    for i, r in enumerate(results, 1):
                        body += self._render_result_entry(r, i, show_similar_link=True)
                else:
                    body += '<div class="empty">No similar entries found.</div>'
                body += f'<p style="margin-top:12px;"><a href="/semantic">← Back to search</a></p>'
                sem.close()
                self.send_html(self.page_wrap("Similar Entries", body, active="semantic", source_filter=sf))
                return

            # === CONTEXT WINDOW MODE ===
            if context_id:
                body += f'<p style="color:var(--yellow); margin-bottom:12px; font-weight:bold;">Conversation context around entry #{context_id}</p>'
                context = sem.get_context_window(context_id, window=5)
                if context:
                    for r in context:
                        is_target = r["id"] == context_id
                        border = "border-left: 3px solid var(--yellow);" if is_target else ""
                        bg = "background: #d2992215;" if is_target else ""
                        content = render_content(r.get("content", ""), max_len=2000)
                        ts = r["timestamp"][:19] if r.get("timestamp") else "?"
                        body += f"""
                        <div class="entry" style="{border} {bg}">
                            <div class="meta">
                                <span class="role {r['role']}">{r['role']}</span>
                                <span>{ts}</span>
                                <span>line {r['source_line']}</span>
                                {'<span style="color:var(--yellow); font-weight:bold;">◀ TARGET</span>' if is_target else ''}
                                <a href="/semantic?similar={r['id']}" style="color:var(--purple);">find similar</a>
                            </div>
                            <div class="content">{content}</div>
                        </div>"""
                else:
                    body += '<div class="empty">Entry not found.</div>'
                body += f'<p style="margin-top:12px;"><a href="/semantic">← Back to search</a></p>'
                sem.close()
                self.send_html(self.page_wrap("Context Window", body, active="semantic", source_filter=sf))
                return

            # === SEARCH MODE ===
            if query:
                body += f'<p style="color:var(--text2); margin-bottom:4px;">Vector DB: {stats["chroma_docs"]:,} docs ({stats["coverage"]} coverage) · Mode: <strong>{mode}</strong></p>'

                if mode == "hybrid":
                    results = sem.hybrid_search(query, n_results=n, role=role or None, days=days or None)
                elif mode == "semantic":
                    results = sem.search(query, n_results=n, role=role or None)
                else:
                    # keyword-only — use FTS via hybrid but zero out semantic
                    results = sem.hybrid_search(query, n_results=n, role=role or None, days=days or None)
                    for r in results:
                        r["hybrid_score"] = r.get("fts_score", 0)
                    results.sort(key=lambda x: -x["hybrid_score"])

                if results:
                    # Related topics sidebar
                    related = sem.extract_related_topics(results, top_n=10)
                    if related:
                        body += '<div style="margin-bottom:16px;">'
                        body += '<span style="color:var(--text2); font-size:11px;">Related: </span>'
                        for word, count in related:
                            body += f'<a href="/semantic?q={escape(word)}&mode={mode}" style="font-size:11px; padding:2px 8px; margin:2px; background:var(--bg3); border:1px solid var(--border); border-radius:10px; display:inline-block;">{escape(word)} <span style="color:var(--text2);">{count}</span></a>'
                        body += '</div>'

                    body += f'<p style="color:var(--text2); margin-bottom:12px;">{len(results)} results</p>'

                    for i, r in enumerate(results, 1):
                        body += self._render_result_entry(r, i)
                else:
                    body += '<div class="empty">No results. Try different wording or switch search mode.</div>'

            else:
                # === LANDING PAGE ===
                body += f"""
                <div class="stats-grid" style="margin-top:20px;">
                    <div class="stat-card"><div class="label">Vector Docs</div><div class="value">{stats['chroma_docs']:,}</div></div>
                    <div class="stat-card"><div class="label">SQLite Eligible</div><div class="value">{stats['sqlite_eligible']:,}</div></div>
                    <div class="stat-card"><div class="label">Coverage</div><div class="value">{stats['coverage']}</div></div>
                </div>
                <div style="margin-top:20px; color:var(--text2);">
                    <p><strong>Hybrid search</strong> combines semantic (meaning) + keyword (FTS) for best results.</p>
                    <p style="margin-top:8px;">Try:</p>
                    <ul style="margin-top:4px; list-style:disc; padding-left:20px;">
                        <li><a href="/semantic?q=database+migration+strategy">database migration strategy</a></li>
                        <li><a href="/semantic?q=error+handling+patterns">error handling patterns</a></li>
                        <li><a href="/semantic?q=memory+system+setup+configuration">memory system setup</a></li>
                        <li><a href="/semantic?q=project+configuration+setup">project configuration</a></li>
                        <li><a href="/semantic?q=API+design+decisions">API design decisions</a></li>
                    </ul>
                    <p style="margin-top:12px; font-size:11px;">Each result has <span style="color:var(--purple);">find similar</span> and <span style="color:var(--yellow);">context</span> links to explore deeper.</p>
                </div>"""

            sem.close()

        except ImportError:
            body += '<div class="empty">chromadb not installed. Run: pip install chromadb</div>'
        except Exception as e:
            body += f'<div class="empty">Error: {escape(str(e))}</div>'

        self.send_html(self.page_wrap("Semantic Search", body, active="semantic", source_filter=sf))

    def handle_api_semantic(self, params):
        query = params.get("q", [""])[0]
        n = int(params.get("n", ["15"])[0])
        role = params.get("role", [""])[0]
        mode = params.get("mode", ["hybrid"])[0]
        similar_id = int(params.get("similar", ["0"])[0] or 0)
        context_id = int(params.get("context", ["0"])[0] or 0)

        try:
            sem = self._get_sem_engine()

            if similar_id:
                results = sem.find_similar(similar_id, n_results=n)
                sem.close()
                self.send_json({"results": results, "mode": "similar", "count": len(results)})
                return

            if context_id:
                context = sem.get_context_window(context_id, window=5)
                sem.close()
                self.send_json({"context": context, "mode": "context", "count": len(context)})
                return

            if not query:
                sem.close()
                self.send_json({"error": "query required"})
                return

            if mode == "hybrid":
                results = sem.hybrid_search(query, n_results=n, role=role or None)
            else:
                results = sem.search(query, n_results=n, role=role or None)

            related = sem.extract_related_topics(results)
            sem.close()
            self.send_json({
                "results": results,
                "related": [{"word": w, "count": c} for w, c in related],
                "mode": mode,
                "count": len(results),
            })
        except Exception as e:
            self.send_json({"error": str(e)})

    # ── Projects Pages ──────────────────────────────────────────────

    def handle_projects(self, params):
        """List all projects."""
        sf = params.get("source", [""])[0]
        status_filter = params.get("status", ["active"])[0]
        conn = get_db()

        from engine import MemoryEngine
        eng = MemoryEngine()
        projects = eng.list_projects(status=status_filter or None)
        eng.close()
        conn.close()

        body = '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">'
        body += '<h2>Projects</h2>'
        body += '<a href="/project/create" style="padding:8px 20px; background:var(--green); color:#000; border-radius:6px; font-weight:bold; font-size:13px;">+ New Project</a>'
        body += '</div>'

        # Filters
        body += '<div style="display:flex; gap:8px; margin-bottom:16px;">'
        for s in ["active", "archived", ""]:
            label = s if s else "all"
            active_style = "background:var(--accent); color:#000;" if status_filter == s else ""
            body += f'<a href="/projects?status={s}" style="padding:5px 14px; border-radius:20px; background:var(--bg3); color:var(--text); font-size:12px; text-decoration:none; {active_style}">{label}</a>'
        body += '</div>'

        if not projects:
            body += '<div class="entry" style="text-align:center; color:var(--muted); padding:40px;">No projects yet. Create your first one!</div>'
        else:
            body += '<div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(350px, 1fr)); gap:12px;">'
            import re as _re
            for p in projects:
                color = p.get("color") or "#58a6ff"
                if not _re.match(r'^#[0-9a-fA-F]{3,8}$', color):
                    color = "#58a6ff"
                tags_html = ""
                if p.get("tags"):
                    for tag in p["tags"].split(","):
                        tag = tag.strip()
                        if tag:
                            tags_html += f'<span style="padding:2px 8px; border-radius:10px; font-size:10px; background:var(--bg3); color:var(--muted);">{escape(tag)}</span>'

                desc = escape((p.get("description") or "")[:150])
                body += f'''<a href="/project?id={p["id"]}" style="text-decoration:none;">
                <div class="entry" style="border-left:4px solid {color}; cursor:pointer;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div style="font-weight:bold; font-size:15px; color:{color};">{escape(p["name"])}</div>
                        <span style="font-size:12px; color:var(--muted);">{p["session_count"]} sessions</span>
                    </div>
                    {f'<div style="color:var(--text2); font-size:12px; margin-top:4px;">{desc}</div>' if desc else ""}
                    <div style="display:flex; gap:4px; margin-top:8px; flex-wrap:wrap;">
                        {tags_html}
                        <span style="padding:2px 8px; border-radius:10px; font-size:10px; background:{"var(--bg3)" if p["status"] == "active" else "var(--red)22"}; color:{"var(--green)" if p["status"] == "active" else "var(--red)"};">{p["status"]}</span>
                    </div>
                </div></a>'''
            body += '</div>'

        self.send_html(self.page_wrap("Projects", body, active="projects", source_filter=sf))

    def handle_project_detail(self, params):
        """Project detail with tabs."""
        sf = params.get("source", [""])[0]
        project_id = params.get("id", [""])[0]
        if not project_id:
            self.send_error(400, "Missing id")
            return

        tab = params.get("tab", ["sessions"])[0]
        query = params.get("q", [""])[0]

        from engine import MemoryEngine
        eng = MemoryEngine()
        project = eng.get_project(int(project_id))
        if not project:
            eng.close()
            self.send_html(self.page_wrap("Project", '<p>Project not found</p>', active="projects", source_filter=sf))
            return

        stats = eng.project_stats(project["id"])
        pid = project["id"]
        import re as _re
        color = project.get("color") or "#58a6ff"
        if not _re.match(r'^#[0-9a-fA-F]{3,8}$', color):
            color = "#58a6ff"

        # Header
        body = f'''<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:20px;">
            <div>
                <h2 style="color:{color}; margin:0;">{escape(project["name"])}</h2>
                <div style="color:var(--muted); margin-top:4px;">{escape(project.get("description") or "")}</div>
            </div>
            <div style="display:flex; gap:8px;">
                <form method="POST" action="/project/delete" style="display:inline;">
                    <input type="hidden" name="id" value="{pid}">
                    <button type="submit" style="padding:6px 12px; background:var(--bg3); color:var(--red); border:1px solid var(--border); border-radius:6px; cursor:pointer; font-size:11px;" onclick="return confirm('Delete this project?')">Delete</button>
                </form>
            </div>
        </div>'''

        # Tags
        if project.get("tags"):
            body += '<div style="display:flex; gap:4px; margin-bottom:16px; flex-wrap:wrap;">'
            for tag in project["tags"].split(","):
                tag = tag.strip()
                if tag:
                    body += f'<span style="padding:3px 10px; border-radius:12px; font-size:11px; background:var(--bg3); color:var(--text2);">{escape(tag)}</span>'
            body += '</div>'

        # Stats
        body += '<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:10px; margin-bottom:20px;">'
        body += f'<div class="entry" style="text-align:center;"><div style="font-size:1.8em; color:{color};">{stats["sessions"]}</div><div style="font-size:11px; color:var(--muted);">Sessions</div></div>'
        body += f'<div class="entry" style="text-align:center;"><div style="font-size:1.8em; color:var(--green);">{stats["entries"]}</div><div style="font-size:11px; color:var(--muted);">Entries</div></div>'
        body += f'<div class="entry" style="text-align:center;"><div style="font-size:1.8em; color:var(--purple);">{stats["observations"]}</div><div style="font-size:11px; color:var(--muted);">Observations</div></div>'
        date_range = f'{(stats.get("first_ts") or "?")[:10]} → {(stats.get("last_ts") or "?")[:10]}'
        body += f'<div class="entry" style="text-align:center;"><div style="font-size:0.9em; color:var(--yellow); margin-top:8px;">{date_range}</div><div style="font-size:11px; color:var(--muted);">Date Range</div></div>'
        body += '</div>'

        # Search bar (project-scoped)
        body += f'''<form method="GET" action="/project" style="margin-bottom:16px;">
            <input type="hidden" name="id" value="{pid}">
            <input type="hidden" name="tab" value="entries">
            <input type="text" name="q" value="{escape(query)}" placeholder="Search within this project..." class="search-box">
        </form>'''

        # Tabs
        tabs = [("sessions", "Sessions"), ("entries", "Entries"), ("observations", "Observations")]
        body += '<div style="display:flex; gap:4px; margin-bottom:16px; border-bottom:1px solid var(--border); padding-bottom:8px;">'
        for t_id, t_label in tabs:
            active_style = "background:var(--bg2); color:var(--accent); border:1px solid var(--border); border-bottom:none;" if t_id == tab else "color:var(--muted);"
            body += f'<a href="/project?id={pid}&tab={t_id}" style="padding:8px 16px; border-radius:6px 6px 0 0; font-size:13px; text-decoration:none; {active_style}">{t_label}</a>'
        body += '</div>'

        # Tab content
        if tab == "sessions":
            body += self._render_project_sessions_tab(eng, pid, color)
        elif tab == "entries":
            body += self._render_project_entries_tab(eng, pid, query)
        elif tab == "observations":
            body += self._render_project_observations_tab(eng, pid)

        eng.close()
        self.send_html(self.page_wrap(project["name"], body, active="projects", source_filter=sf))

    def _render_project_sessions_tab(self, eng, pid, color):
        """Render the sessions tab of project detail."""
        sessions = eng.get_project_sessions(pid)
        body = ""

        # Assign form
        body += f'''<div class="entry" style="margin-bottom:16px; border-left:3px solid var(--green);">
            <div style="font-size:13px; font-weight:bold; margin-bottom:8px;">Assign Session</div>
            <div style="display:flex; gap:8px;">
                <input type="text" id="assign-sid" placeholder="Session UUID or prefix..." style="flex:1; padding:6px 10px; background:var(--bg); border:1px solid var(--border); border-radius:6px; color:var(--text); font-family:inherit; font-size:12px;">
                <button onclick="assignSession()" style="padding:6px 16px; background:var(--green); color:#000; border:none; border-radius:6px; cursor:pointer; font-size:12px;">Assign</button>
                <button onclick="suggestSessions()" style="padding:6px 16px; background:var(--purple); color:#000; border:none; border-radius:6px; cursor:pointer; font-size:12px;">Auto-Suggest</button>
            </div>
            <div id="assign-result" style="margin-top:8px; font-size:12px; color:var(--muted);"></div>
            <div id="suggestions" style="margin-top:8px;"></div>
        </div>'''

        # Session list
        if sessions:
            for s in sessions:
                sid = s["session_id"]
                sid_short = sid[:12]
                entries = s.get("entry_count", "?")
                first = (s.get("first_ts") or "?")[:16]
                last = (s.get("last_ts") or "?")[:16]
                notes = escape(s.get("notes") or "") if s.get("notes") else ""

                body += f'''<div class="entry" style="border-left:3px solid {color}; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <a href="/session?id={sid}" style="font-weight:bold; font-size:13px;">{sid_short}…</a>
                        <span style="color:var(--muted); font-size:11px; margin-left:8px;">{entries} entries | {first} → {last}</span>
                        {f'<div style="font-size:11px; color:var(--text2); margin-top:2px;">{notes}</div>' if notes else ""}
                    </div>
                    <button onclick="unassignSession('{sid}')" style="padding:4px 10px; background:var(--bg3); color:var(--red); border:1px solid var(--border); border-radius:4px; cursor:pointer; font-size:11px;">×</button>
                </div>'''
        else:
            body += '<div class="entry" style="text-align:center; color:var(--muted); padding:30px;">No sessions assigned yet. Use the form above or Auto-Suggest.</div>'

        # JavaScript for assign/unassign/suggest
        body += f'''<script>
const PID = {pid};

async function assignSession() {{
    const sid = document.getElementById('assign-sid').value.trim();
    if (!sid) return;
    const resp = await fetch('/api/project/assign?project_id=' + PID + '&session_id=' + encodeURIComponent(sid));
    const data = await resp.json();
    document.getElementById('assign-result').textContent = data.message || JSON.stringify(data);
    if (data.success) setTimeout(() => location.reload(), 500);
}}

async function unassignSession(sid) {{
    if (!confirm('Remove this session from project?')) return;
    const resp = await fetch('/api/project/unassign?project_id=' + PID + '&session_id=' + encodeURIComponent(sid));
    const data = await resp.json();
    if (data.success) location.reload();
}}

async function suggestSessions() {{
    const el = document.getElementById('suggestions');
    el.innerHTML = '<div style="color:var(--muted);">Searching...</div>';
    const resp = await fetch('/api/project/suggest?project_id=' + PID);
    const data = await resp.json();
    if (!data.suggestions || data.suggestions.length === 0) {{
        el.innerHTML = '<div style="color:var(--muted);">No matching sessions found.</div>';
        return;
    }}
    let html = '<div style="font-size:12px; color:var(--muted); margin-bottom:6px;">Suggested sessions:</div>';
    data.suggestions.forEach(s => {{
        const sid = s.session_id;
        const short = sid.substring(0, 12);
        html += '<div class="entry" style="padding:8px 12px; display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">';
        html += '<div><span style="font-weight:bold;">' + short + '…</span> <span style="color:var(--muted); font-size:11px;">' + s.match_count + ' matches | ' + (s.first_ts || '?').substring(0, 10) + '</span></div>';
        html += '<button onclick="quickAssign(\\'' + sid + '\\')" style="padding:4px 12px; background:var(--green); color:#000; border:none; border-radius:4px; cursor:pointer; font-size:11px;">+ Assign</button>';
        html += '</div>';
    }});
    el.innerHTML = html;
}}

async function quickAssign(sid) {{
    const resp = await fetch('/api/project/assign?project_id=' + PID + '&session_id=' + encodeURIComponent(sid));
    const data = await resp.json();
    if (data.success) location.reload();
}}
</script>'''

        return body

    def _render_project_entries_tab(self, eng, pid, query):
        """Render entries tab (project-scoped search or recent entries)."""
        body = ""
        if query:
            try:
                results = eng.project_search(pid, query, limit=30)
                body += f'<div style="margin-bottom:12px; color:var(--muted);">{len(results)} results for "{escape(query)}"</div>'
                for r in results:
                    role = r.get("role", "?")
                    ts = (r.get("timestamp") or "?")[:19]
                    sid = (r.get("session_id") or "?")[:8]
                    content = render_content(r["content"], max_len=800)
                    role_class = role
                    body += f'''<div class="entry">
                        <div class="meta">
                            <span class="role {role_class}">{role}</span>
                            <span>{ts}</span>
                            <a href="/session?id={r.get('session_id', '')}" style="color:var(--muted);">{sid}…</a>
                        </div>
                        <div class="content">{content}</div>
                    </div>'''
            except Exception as e:
                body += f'<div class="entry" style="color:var(--red);">Search error: {escape(str(e))}</div>'
        else:
            # Show recent entries from project sessions
            entries = eng.conn.execute("""
                SELECT e.id, e.content, e.role, e.session_id, e.timestamp
                FROM entries e
                WHERE e.session_id IN (SELECT session_id FROM project_sessions WHERE project_id = ?)
                AND e.role IN ('user', 'assistant')
                AND length(e.content) > 30
                AND e.content NOT LIKE '[TOOL:%'
                ORDER BY e.timestamp DESC
                LIMIT 50
            """, (pid,)).fetchall()

            body += f'<div style="margin-bottom:12px; color:var(--muted);">Recent {len(entries)} entries (use search for more)</div>'
            for e in entries:
                role = e["role"]
                ts = (e["timestamp"] or "?")[:19]
                sid = (e["session_id"] or "?")[:8]
                content = render_content(e["content"], max_len=500)
                body += f'''<div class="entry">
                    <div class="meta">
                        <span class="role {role}">{role}</span>
                        <span>{ts}</span>
                        <a href="/session?id={e['session_id']}" style="color:var(--muted);">{sid}…</a>
                    </div>
                    <div class="content">{content}</div>
                </div>'''
        return body

    def _render_project_observations_tab(self, eng, pid):
        """Render observations tab for project."""
        observations = eng.project_observations(pid, limit=50)
        type_colors = {
            "bugfix": "var(--red)", "discovery": "var(--green)", "change": "var(--blue)",
            "pattern": "var(--purple)", "decision": "var(--yellow)", "feature": "var(--accent)",
            "reference": "#e879f9",
        }

        body = f'<div style="margin-bottom:12px; color:var(--muted);">{len(observations)} observations in this project</div>'
        for obs in observations:
            color = type_colors.get(obs["type"], "var(--text)")
            concept_badge = f'<span style="background:var(--bg); padding:2px 8px; border-radius:10px; font-size:10px; color:var(--muted);">{obs["concept"]}</span>' if obs.get("concept") else ""
            content_text = escape(obs["content"][:400])
            sid = (obs.get("session_id") or "?")[:8]

            body += f'''<div class="entry" style="border-left:3px solid {color};">
                <div style="display:flex; gap:8px; align-items:center; margin-bottom:4px;">
                    <span style="color:{color}; font-weight:bold; text-transform:uppercase; font-size:12px;">{obs["type"]}</span>
                    {concept_badge}
                    <span style="color:var(--muted); font-size:11px;">conf:{obs["confidence"]:.2f}</span>
                    <a href="/session?id={obs.get("session_id", "")}" style="color:var(--muted); font-size:11px; margin-left:auto;">{sid}…</a>
                </div>
                <div style="margin-top:6px; white-space:pre-wrap; font-size:13px;">{content_text}</div>
            </div>'''

        if not observations:
            body += '<div class="entry" style="text-align:center; color:var(--muted); padding:30px;">No observations for this project yet.</div>'
        return body

    def handle_project_create(self, params):
        """Render project creation form."""
        sf = params.get("source", [""])[0]
        body = '<h2>Create Project</h2>'
        body += '''<form method="POST" action="/project/create">
            <div style="margin-bottom:16px;">
                <label style="display:block; font-size:12px; color:var(--muted); margin-bottom:4px;">Name *</label>
                <input type="text" name="name" required placeholder="e.g. Frontend Redesign, API v2, Research" class="search-box" style="margin-bottom:0;">
            </div>
            <div style="margin-bottom:16px;">
                <label style="display:block; font-size:12px; color:var(--muted); margin-bottom:4px;">Description</label>
                <textarea name="description" rows="3" placeholder="What is this project about?" style="width:100%; padding:10px 16px; background:var(--bg2); border:1px solid var(--border); border-radius:8px; color:var(--text); font-family:inherit; font-size:13px; resize:vertical;"></textarea>
            </div>
            <div style="margin-bottom:16px;">
                <label style="display:block; font-size:12px; color:var(--muted); margin-bottom:4px;">Tags (comma-separated)</label>
                <input type="text" name="tags" placeholder="e.g. react, typescript, api, frontend" class="search-box" style="margin-bottom:0;">
                <div style="font-size:11px; color:var(--muted); margin-top:4px;">Common: recon, appsec, mobile, api, web, infrastructure, iot, cloud</div>
            </div>
            <div style="margin-bottom:16px;">
                <label style="display:block; font-size:12px; color:var(--muted); margin-bottom:4px;">Color</label>
                <div style="display:flex; gap:8px; align-items:center;">
                    <input type="color" name="color" value="#58a6ff" style="width:50px; height:35px; border:none; background:none; cursor:pointer;">
                    <div style="display:flex; gap:4px;">'''

        preset_colors = [
            ("#58a6ff", "Blue"), ("#3fb950", "Green"), ("#f85149", "Red"),
            ("#d29922", "Yellow"), ("#bc8cff", "Purple"), ("#f778ba", "Pink"),
            ("#79c0ff", "Cyan"), ("#ff7b72", "Coral"),
        ]
        for hex_c, _ in preset_colors:
            body += f'<div onclick="document.querySelector(\'input[name=color]\').value=\'{hex_c}\'" style="width:24px; height:24px; border-radius:50%; background:{hex_c}; cursor:pointer; border:2px solid var(--bg);"></div>'

        body += '''</div></div>
            </div>
            <button type="submit" style="padding:10px 24px; background:var(--green); color:#000; border:none; border-radius:6px; cursor:pointer; font-weight:bold; font-size:14px;">Create Project</button>
            <a href="/projects" style="margin-left:12px; color:var(--muted);">Cancel</a>
        </form>'''

        self.send_html(self.page_wrap("New Project", body, active="projects", source_filter=sf))

    def handle_project_create_post(self, form):
        """Process project creation form."""
        name = form.get("name", [""])[0].strip()
        if not name:
            self.send_html(self.page_wrap("Error", '<p>Name is required</p>', active="projects", source_filter=""), status=400)
            return

        from engine import MemoryEngine
        eng = MemoryEngine()
        result = eng.create_project(
            name=name,
            description=form.get("description", [""])[0].strip() or None,
            tags=form.get("tags", [""])[0].strip() or None,
            color=form.get("color", ["#58a6ff"])[0].strip(),
        )
        eng.close()

        if result["action"] == "exists":
            self.send_html(self.page_wrap("Error", f'<p>Project "{escape(name)}" already exists</p>', active="projects", source_filter=""), status=400)
            return

        # Redirect to project detail
        self.send_response(302)
        self.send_header("Location", f"/project?id={result['id']}")
        self.end_headers()

    def handle_project_update_post(self, form):
        """Process project update."""
        pid = form.get("id", [""])[0]
        if not pid:
            self.send_error(400)
            return

        from engine import MemoryEngine
        eng = MemoryEngine()
        kwargs = {}
        for field in ["description", "tags", "status", "color"]:
            val = form.get(field, [""])[0].strip()
            if val:
                kwargs[field] = val
        eng.update_project(int(pid), **kwargs)
        eng.close()

        self.send_response(302)
        self.send_header("Location", f"/project?id={pid}")
        self.end_headers()

    def handle_project_delete_post(self, form):
        """Process project deletion."""
        pid = form.get("id", [""])[0]
        if not pid:
            self.send_error(400)
            return

        from engine import MemoryEngine
        eng = MemoryEngine()
        eng.delete_project(int(pid))
        eng.close()

        self.send_response(302)
        self.send_header("Location", "/projects")
        self.end_headers()

    def handle_api_project(self, path, params):
        """Handle project API endpoints."""
        from engine import MemoryEngine
        eng = MemoryEngine()

        try:
            if path == "/api/project/assign":
                pid = int(params.get("project_id", ["0"])[0])
                sid = params.get("session_id", [""])[0].strip()
                if not pid or not sid:
                    self.send_json({"success": False, "message": "Missing project_id or session_id"})
                    return

                # Support partial UUID
                if len(sid) < 36:
                    matches = eng.conn.execute(
                        "SELECT DISTINCT session_id FROM entries WHERE session_id LIKE ? LIMIT 5",
                        (sid + "%",)
                    ).fetchall()
                    if len(matches) == 1:
                        sid = matches[0]["session_id"]
                    elif len(matches) > 1:
                        self.send_json({"success": False, "message": f"Ambiguous: {', '.join(r['session_id'][:12] for r in matches)}"})
                        return
                    else:
                        self.send_json({"success": False, "message": f"No session: {sid}"})
                        return

                result = eng.assign_session(pid, sid)
                self.send_json({"success": True, "message": f"{result['action']}: {sid[:12]}…"})

            elif path == "/api/project/unassign":
                pid = int(params.get("project_id", ["0"])[0])
                sid = params.get("session_id", [""])[0]
                if not pid or not sid:
                    self.send_json({"success": False, "message": "Missing params"})
                    return
                eng.unassign_session(pid, sid)
                self.send_json({"success": True, "message": "Unassigned"})

            elif path == "/api/project/suggest":
                pid = int(params.get("project_id", ["0"])[0])
                limit = int(params.get("limit", ["20"])[0])
                suggestions = eng.suggest_project_sessions(pid, limit=limit)
                self.send_json({"suggestions": suggestions})

            else:
                self.send_json({"error": "Unknown endpoint"})
        except Exception as e:
            self.send_json({"success": False, "message": str(e)})
        finally:
            eng.close()

    # ── Observations Page ────────────────────────────────────────────

    def handle_observations(self, params):
        sf = params.get("source", [""])[0]
        obs_type = params.get("type", [""])[0]
        concept = params.get("concept", [""])[0]
        session_id = params.get("session", [""])[0]
        min_conf = float(params.get("conf", ["0.3"])[0] or "0.3")

        try:
            from observations import ObservationExtractor
            ext = ObservationExtractor()
            stats = ext.observation_stats()

            # Get observations
            observations = ext.get_observations(
                obs_type=obs_type or None,
                concept=concept or None,
                session_id=session_id or None,
                min_confidence=min_conf,
                limit=100
            )

            # Get recent summaries
            summaries = ext.get_recent_summaries(limit=10)
            ext.close()
        except Exception as e:
            self.send_html(self.page_wrap("Observations", f"<p>Error: {escape(str(e))}</p>", active="observations", source_filter=sf))
            return

        # Build page
        body = '<h2>Observations & Summaries</h2>'

        # Stats cards
        body += '<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin-bottom:20px;">'
        body += f'<div class="entry" style="text-align:center;"><div style="font-size:2em; color:var(--accent);">{stats["total_observations"]}</div><div>Observations</div></div>'
        body += f'<div class="entry" style="text-align:center;"><div style="font-size:2em; color:var(--green);">{stats["session_summaries"]}</div><div>Session Summaries</div></div>'
        body += f'<div class="entry" style="text-align:center;"><div style="font-size:2em; color:var(--purple);">{stats["avg_confidence"]:.2f}</div><div>Avg Confidence</div></div>'
        body += f'<div class="entry" style="text-align:center;"><div style="font-size:2em; color:var(--yellow);">{stats["total_sessions"]}</div><div>Total Sessions</div></div>'
        body += '</div>'

        # Type distribution
        body += '<div class="entry" style="margin-bottom:20px;"><h3>By Type</h3><div style="display:flex; gap:8px; flex-wrap:wrap;">'
        type_colors = {
            "bugfix": "var(--red)", "discovery": "var(--green)", "change": "var(--blue)",
            "pattern": "var(--purple)", "decision": "var(--yellow)", "feature": "var(--accent)",
            "reference": "#e879f9",
        }
        for t, c in stats.get("by_type", {}).items():
            color = type_colors.get(t, "var(--text)")
            is_active = "border:2px solid #fff;" if t == obs_type else ""
            body += f'<a href="/observations?type={t}" style="padding:6px 14px; border-radius:20px; background:var(--bg3); color:{color}; text-decoration:none; font-size:13px; {is_active}">{t} <b>{c}</b></a>'
        body += '</div>'

        # Concept distribution
        body += '<div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">'
        for t, c in stats.get("by_concept", {}).items():
            is_active = "border:2px solid #fff;" if t == concept else ""
            body += f'<a href="/observations?concept={t}" style="padding:4px 10px; border-radius:12px; background:var(--bg2); color:var(--muted); text-decoration:none; font-size:12px; {is_active}">{t} ({c})</a>'
        body += '</div></div>'

        # Filter display
        if obs_type or concept or session_id:
            filters = []
            if obs_type:
                filters.append(f'type={obs_type}')
            if concept:
                filters.append(f'concept={concept}')
            if session_id:
                filters.append(f'session={session_id[:8]}')
            body += f'<div style="margin-bottom:12px; color:var(--muted);">Filtering: {", ".join(filters)} | <a href="/observations" style="color:var(--accent);">Clear</a></div>'

        # Observations list
        body += f'<h3>Observations ({len(observations)})</h3>'
        for obs in observations:
            color = type_colors.get(obs["type"], "var(--text)")
            concept_badge = f'<span style="background:var(--bg2); padding:2px 8px; border-radius:10px; font-size:11px; color:var(--muted);">{obs["concept"]}</span>' if obs.get("concept") else ""
            conf_pct = int(obs["confidence"] * 100)
            conf_bar = f'<div style="width:{conf_pct}px; height:3px; background:{color}; border-radius:2px; margin-top:4px;"></div>'
            content_raw = obs["content"][:500]
            sid = (obs.get("session_id") or "?")[:8]

            # Make URLs clickable for reference type
            if obs["type"] == "reference":
                lines = content_raw.split("\n")
                url_line = lines[0] if lines else ""
                ctx_line = escape(lines[1]) if len(lines) > 1 else ""
                if url_line.startswith("http"):
                    content_html = f'<a href="{escape(url_line)}" target="_blank" style="color:var(--accent); word-break:break-all;">{escape(url_line)}</a>'
                    if ctx_line:
                        content_html += f'<div style="color:var(--muted); font-size:12px; margin-top:2px;">{ctx_line}</div>'
                else:
                    content_html = f'<span>{escape(content_raw)}</span>'
            else:
                content_html = escape(content_raw)

            body += f'''<div class="entry" style="border-left:3px solid {color};">
                <div style="display:flex; gap:8px; align-items:center; margin-bottom:6px;">
                    <span style="color:{color}; font-weight:bold; text-transform:uppercase; font-size:12px;">{obs["type"]}</span>
                    {concept_badge}
                    <span style="color:var(--muted); font-size:11px;">conf: {obs["confidence"]:.2f}</span>
                    <a href="/session?id={obs.get("session_id", "")}" style="color:var(--muted); font-size:11px; margin-left:auto;">{sid}</a>
                </div>
                {conf_bar}
                <div style="margin-top:8px; white-space:pre-wrap; font-size:13px;">{content_html}</div>
            </div>'''

        # Session Summaries section
        if summaries:
            body += '<h3 style="margin-top:30px;">Recent Session Summaries</h3>'
            for s in summaries:
                sid = s["session_id"][:8]
                req = escape((s.get("request") or "?")[:200])
                completed = escape((s.get("completed") or "?")[:200])
                dur = s.get("duration_minutes", "?")
                entries = s.get("entry_count", "?")
                tools = s.get("tools_used", "[]")

                body += f'''<div class="entry">
                    <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                        <a href="/summary?id={s["session_id"]}" style="color:var(--accent); font-weight:bold;">{sid}</a>
                        <span style="color:var(--muted); font-size:12px;">{entries} entries · {dur} min</span>
                    </div>
                    <div style="font-size:13px;"><b>Request:</b> {req}</div>
                    <div style="font-size:13px; color:var(--green); margin-top:4px;"><b>Completed:</b> {completed}</div>
                </div>'''

        self.send_html(self.page_wrap("Observations", body, active="observations", source_filter=sf))

    def handle_observation_detail(self, params):
        """Show observations for a specific session."""
        sf = params.get("source", [""])[0]
        session_id = params.get("session", [""])[0]
        if not session_id:
            self.send_error(400, "Missing session parameter")
            return

        try:
            from observations import ObservationExtractor
            ext = ObservationExtractor()
            observations = ext.get_observations(session_id=session_id, limit=200, min_confidence=0.0)
            summary = ext.get_session_summary(session_id)
            ext.close()
        except Exception as e:
            self.send_html(self.page_wrap("Observation Detail", f"<p>Error: {escape(str(e))}</p>", active="observations", source_filter=sf))
            return

        body = f'<h2>Session {escape(session_id[:12])}…</h2>'

        if summary:
            body += '<div class="entry" style="border-left:3px solid var(--accent);">'
            body += '<h3>Session Summary</h3>'
            for field in ["request", "investigated", "learned", "completed", "next_steps"]:
                val = escape((summary.get(field) or "N/A")[:500])
                body += f'<div style="margin:8px 0;"><b style="color:var(--accent); text-transform:uppercase;">{field.replace("_", " ")}:</b><div style="white-space:pre-wrap; font-size:13px; margin-top:4px;">{val}</div></div>'
            body += '</div>'

        body += f'<h3>Observations ({len(observations)})</h3>'
        type_colors = {"bugfix": "var(--red)", "discovery": "var(--green)", "change": "var(--blue)", "pattern": "var(--purple)", "decision": "var(--yellow)", "feature": "var(--accent)"}

        for obs in observations:
            color = type_colors.get(obs["type"], "var(--text)")
            concept_tag = f' [{obs["concept"]}]' if obs.get("concept") else ""
            content_text = escape(obs["content"][:600])
            body += f'''<div class="entry" style="border-left:3px solid {color};">
                <span style="color:{color}; font-weight:bold; font-size:12px;">{obs["type"]}{concept_tag}</span>
                <span style="color:var(--muted); font-size:11px; float:right;">conf: {obs["confidence"]:.2f}</span>
                <div style="white-space:pre-wrap; font-size:13px; margin-top:6px;">{content_text}</div>
            </div>'''

        self.send_html(self.page_wrap("Observations", body, active="observations", source_filter=sf))

    def handle_summary_detail(self, params):
        """Show full session summary."""
        sf = params.get("source", [""])[0]
        session_id = params.get("id", [""])[0]
        if not session_id:
            self.send_error(400, "Missing id parameter")
            return

        try:
            from observations import ObservationExtractor
            ext = ObservationExtractor()
            summary = ext.get_session_summary(session_id)
            if not summary:
                # Generate on the fly
                result = ext.summarize_session(session_id)
                summary = ext.get_session_summary(session_id)
            observations = ext.get_observations(session_id=session_id, limit=50, min_confidence=0.0)
            ext.close()
        except Exception as e:
            self.send_html(self.page_wrap("Summary", f"<p>Error: {escape(str(e))}</p>", active="observations", source_filter=sf))
            return

        if not summary:
            self.send_html(self.page_wrap("Summary", f"<p>No summary available for {escape(session_id[:12])}</p>", active="observations", source_filter=sf))
            return

        body = f'<h2>Session Summary: {escape(session_id[:12])}…</h2>'
        body += f'<div style="color:var(--muted); margin-bottom:16px;">{summary.get("entry_count", "?")} entries · {summary.get("duration_minutes", "?")} min · Tools: {escape(summary.get("tools_used", "[]"))}</div>'

        field_colors = {
            "request": "var(--yellow)", "investigated": "var(--blue)",
            "learned": "var(--green)", "completed": "var(--accent)", "next_steps": "var(--purple)"
        }

        for field in ["request", "investigated", "learned", "completed", "next_steps"]:
            color = field_colors.get(field, "var(--text)")
            val = escape((summary.get(field) or "N/A"))
            body += f'''<div class="entry" style="border-left:3px solid {color};">
                <h3 style="color:{color}; text-transform:uppercase; margin:0 0 8px 0; font-size:13px;">{field.replace("_", " ")}</h3>
                <div style="white-space:pre-wrap; font-size:13px;">{val}</div>
            </div>'''

        if observations:
            body += f'<h3 style="margin-top:24px;">Observations ({len(observations)})</h3>'
            type_colors = {"bugfix": "var(--red)", "discovery": "var(--green)", "change": "var(--blue)", "pattern": "var(--purple)", "decision": "var(--yellow)", "feature": "var(--accent)"}
            for obs in observations:
                color = type_colors.get(obs["type"], "var(--text)")
                concept_tag = f' [{obs["concept"]}]' if obs.get("concept") else ""
                content_text = escape(obs["content"][:400])
                body += f'<div class="entry" style="border-left:3px solid {color};"><span style="color:{color}; font-weight:bold; font-size:12px;">{obs["type"]}{concept_tag}</span> <span style="color:var(--muted); font-size:11px;">conf:{obs["confidence"]:.2f}</span><div style="white-space:pre-wrap; font-size:13px; margin-top:4px;">{content_text}</div></div>'

        body += f'<div style="margin-top:20px;"><a href="/session?id={escape(session_id)}" style="color:var(--accent);">View full session →</a></div>'

        self.send_html(self.page_wrap("Summary", body, active="observations", source_filter=sf))

    def handle_live(self, params):
        sf = params.get("source", [""])[0]
        session_id = params.get("id", [""])[0]
        conn = get_db()

        if not session_id:
            # Try to find an active session by checking for recently modified JSONL files
            import time as _time
            import re as _re
            now = _time.time()

            if sf == "copilot":
                from config import iter_copilot_files
                recent = iter_copilot_files()
                for f in recent[:5]:
                    if (now - f.stat().st_mtime) < 3600:  # Modified in last hour
                        # Session ID: parent dir name for events.jsonl, or stem for <uuid>.jsonl
                        sid = f.parent.name if f.stem == "events" else f.stem
                        try:
                            from engine import MemoryEngine as _ME
                            eng = _ME()
                            eng.ingest_copilot_jsonl(str(f))
                            eng.conn.close()
                        except Exception:
                            pass
                        session_id = sid
                        break

            elif sf == "codex":
                from config import CODEX_JSONL_DIR
                if CODEX_JSONL_DIR and CODEX_JSONL_DIR.exists():
                    recent = sorted(CODEX_JSONL_DIR.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
                    for f in recent[:3]:
                        if (now - f.stat().st_mtime) < 3600:
                            m = _re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$', f.stem)
                            if m:
                                session_id = m.group(1)
                                try:
                                    from engine import MemoryEngine as _ME
                                    eng = _ME()
                                    eng.ingest_codex_jsonl(str(f))
                                    eng.conn.close()
                                except Exception:
                                    pass
                            break

            elif sf == "claude_code":
                from config import JSONL_DIR
                if JSONL_DIR and Path(JSONL_DIR).exists():
                    recent = sorted(Path(JSONL_DIR).glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
                    for f in recent[:3]:
                        if (now - f.stat().st_mtime) < 3600:
                            session_id = f.stem
                            try:
                                from engine import MemoryEngine as _ME
                                eng = _ME()
                                eng.ingest_jsonl(str(f))
                                eng.conn.close()
                            except Exception:
                                pass
                            break

        # No fallback to old sessions — Live only shows actively running conversations
        if not session_id:
            source_labels = {'claude_code': 'Claude Code', 'copilot': 'Copilot CLI', 'codex': 'Codex CLI'}
            tool_name = source_labels.get(sf, sf)
            self.send_html(self.page_wrap("Live", f'<div class="empty">No active {escape(tool_name)} session detected.<br><br><span style="color:var(--text2); font-size:12px;">Start a conversation in {escape(tool_name)} and refresh this page.</span></div>', source_filter=sf))
            conn.close()
            return

        sid_short = session_id[:8]
        total = conn.execute("SELECT COUNT(*) FROM entries WHERE session_id = ?", (session_id,)).fetchone()[0]
        conn.close()

        # Load JS from external module
        live_js = ""
        try:
            from live_handler import LIVE_PAGE_JS
            live_js = LIVE_PAGE_JS.replace("SESSION_ID_PLACEHOLDER", json.dumps(session_id)[1:-1])
        except ImportError:
            pass

        body = f'''
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <h3><span class="live-dot"></span> Live — {escape(sid_short)}... ({total} entries)</h3>
            <div style="display:flex; gap:8px; align-items:center;">
                <label style="color:var(--text2); font-size:12px;">
                    <input type="checkbox" id="autoScroll" checked> Auto-scroll
                </label>
                <label style="color:var(--text2); font-size:12px;">
                    <input type="checkbox" id="showTools"> Show tool calls
                </label>
                <span id="status" style="font-size:11px; color:var(--green);">connected</span>
            </div>
        </div>
        <div id="entries" style="max-height:calc(100vh - 160px); overflow-y:auto; scroll-behavior:smooth;">
            <div class="empty" id="loading">Loading...</div>
        </div>
        {live_js}
        '''
        self.send_html(self.page_wrap(f"Live — {sid_short}", body, active="", source_filter=sf))

    _last_ingest_time = 0  # Class-level throttle

    def handle_api_session_new(self, params):
        session_id = params.get("id", [""])[0]
        after_line = int(params.get("after", ["0"])[0])
        limit = int(params.get("limit", ["200"])[0])

        if not session_id:
            self.send_json({"error": "session id required"})
            return

        # In-process ingest — throttled to once every 10 seconds (no fork bomb)
        import time as _time
        now = _time.time()
        if after_line > 0 and (now - ViewerHandler._last_ingest_time) > 10:
            ViewerHandler._last_ingest_time = now
            try:
                import sys as _sys
                _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from engine import MemoryEngine
                eng = MemoryEngine()
                # Detect source from session record
                src_row = eng.conn.execute("SELECT source FROM sessions WHERE id = ?", (session_id,)).fetchone()
                src = src_row["source"] if src_row else "claude_code"
                if src == "claude_code":
                    from config import JSONL_DIR
                    jsonl_file = JSONL_DIR / f"{session_id}.jsonl"
                    if jsonl_file.exists():
                        eng.ingest_jsonl(str(jsonl_file))
                elif src == "copilot":
                    from config import COPILOT_JSONL_DIR
                    if COPILOT_JSONL_DIR:
                        jsonl_file = COPILOT_JSONL_DIR / f"{session_id}.jsonl"
                        if jsonl_file.exists():
                            eng.ingest_copilot_jsonl(str(jsonl_file))
                elif src == "codex":
                    from config import CODEX_JSONL_DIR
                    if CODEX_JSONL_DIR:
                        # Find the rollout file containing this session UUID
                        for codex_f in sorted(CODEX_JSONL_DIR.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
                            if session_id in codex_f.stem:
                                eng.ingest_codex_jsonl(str(codex_f))
                                break
                eng.close()
            except Exception:
                pass  # Ingest failure shouldn't break the API

        conn = get_db()
        rows = conn.execute("""
            SELECT content, role, session_id, timestamp, source_line
            FROM entries WHERE session_id = ? AND source_line > ?
            ORDER BY source_line ASC LIMIT ?
        """, (session_id, after_line, limit)).fetchall()

        total = conn.execute("SELECT COUNT(*) FROM entries WHERE session_id = ?", (session_id,)).fetchone()[0]
        conn.close()

        self.send_json({
            "entries": [dict(r) for r in rows],
            "total": total,
            "session_id": session_id,
        })

    def handle_image(self, filename):
        """Serve an image file from the images directory."""
        # Sanitize — prevent path traversal
        filename = Path(filename).name
        filepath = IMAGES_DIR / filename

        if not filepath.exists() or not filepath.is_file():
            self.send_error(404, "Image not found")
            return

        # Determine content type
        ext = filepath.suffix.lower()
        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        ct = content_types.get(ext, "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def handle_api_stats(self, params):
        source = params.get("source", [""])[0]
        conn = get_db()
        if source:
            total = conn.execute("SELECT COUNT(*) FROM entries WHERE source = ?", (source,)).fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='done' AND source = ?", (source,)).fetchone()[0]
            roles = {r[0]: r[1] for r in conn.execute("SELECT role, COUNT(*) FROM entries WHERE source = ? GROUP BY role", (source,)).fetchall()}
        else:
            total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE status='done'").fetchone()[0]
            roles = {r[0]: r[1] for r in conn.execute("SELECT role, COUNT(*) FROM entries GROUP BY role").fetchall()}
        conn.close()
        self.send_json({"entries": total, "sessions": sessions, "by_role": roles})

    def handle_api_search(self, params):
        query = params.get("q", [""])[0]
        source = params.get("source", [""])[0]
        role = params.get("role", [""])[0]
        limit = min(int(params.get("limit", ["20"])[0]), 500)
        if not query:
            self.send_json([])
            return
        conn = get_db()
        try:
            sql = """
                SELECT e.content, e.role, e.session_id, e.timestamp, e.source
                FROM entries_fts fts JOIN entries e ON e.id = fts.rowid
                WHERE entries_fts MATCH ?
            """
            sql_params = [query]
            if source:
                sql += " AND e.source = ?"
                sql_params.append(source)
            if role:
                sql += " AND e.role = ?"
                sql_params.append(role)
            sql += " ORDER BY rank LIMIT ?"
            sql_params.append(limit)
            rows = conn.execute(sql, sql_params).fetchall()
            self.send_json([dict(r) for r in rows])
        except Exception as e:
            self.send_json({"error": str(e)})
        conn.close()

    def handle_api_latest(self, params):
        limit = min(int(params.get("limit", ["20"])[0]), 500)
        role = params.get("role", [""])[0]
        source = params.get("source", [""])[0]
        conn = get_db()
        sql = "SELECT content, role, session_id, timestamp, source FROM entries"
        conditions = []
        sql_params = []
        if role:
            conditions.append("role = ?")
            sql_params.append(role)
        if source:
            conditions.append("source = ?")
            sql_params.append(source)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        sql_params.append(limit)
        rows = conn.execute(sql, sql_params).fetchall()
        self.send_json([dict(r) for r in rows])
        conn.close()


    def handle_api_session(self, params):
        """GET /api/session?id=xxx&page=1&per_page=100 — JSON session detail"""
        session_id = params.get("id", [""])[0]
        if not session_id:
            self.send_json({"error": "id required"})
            return
        page = int(params.get("page", ["1"])[0] or 1)
        per_page = min(int(params.get("per_page", ["100"])[0] or 100), 500)
        offset = (page - 1) * per_page

        conn = get_db()
        total = conn.execute("SELECT COUNT(*) FROM entries WHERE session_id = ?", (session_id,)).fetchone()[0]
        rows = conn.execute("""
            SELECT content, role, timestamp, source_line FROM entries
            WHERE session_id = ? ORDER BY source_line ASC LIMIT ? OFFSET ?
        """, (session_id, per_page, offset)).fetchall()

        # Session metadata
        meta = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        conn.close()

        result = {
            "session_id": session_id,
            "total_entries": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }
        if meta:
            result["meta"] = {k: meta[k] for k in meta.keys()}
        result["entries"] = [dict(r) for r in rows]
        self.send_json(result)

    def handle_api_sessions(self, params):
        """GET /api/sessions?limit=20&source=X — JSON session list"""
        limit = min(int(params.get("limit", ["20"])[0] or 20), 100)
        off = int(params.get("offset", ["0"])[0] or 0)
        q = params.get("q", [""])[0]
        source = params.get("source", [""])[0]

        conn = get_db()
        conditions = []
        sql_params = []

        if source:
            conditions.append("s.source = ?")
            sql_params.append(source)

        if q:
            conditions.append("(s.id LIKE ? OR EXISTS (SELECT 1 FROM entries_fts fts JOIN entries e2 ON e2.id = fts.rowid WHERE e2.session_id = s.id AND entries_fts MATCH ?))")
            sql_params.extend([f"%{q}%", q])

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        rows = conn.execute(f"""
            SELECT s.id, s.status, s.last_processed_at, s.source, s.summary,
                   COUNT(e.id) as entry_count,
                   MIN(e.timestamp) as started_at,
                   MAX(e.timestamp) as ended_at
            FROM sessions s LEFT JOIN entries e ON e.session_id = s.id
            {where}
            GROUP BY s.id ORDER BY s.last_processed_at DESC LIMIT ? OFFSET ?
        """, sql_params + [limit, off]).fetchall()

        # Count total for this source
        if source:
            total = conn.execute("SELECT COUNT(*) FROM sessions WHERE source = ?", (source,)).fetchone()[0]
        else:
            total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()

        sessions = []
        for r in rows:
            s_obj = {
                "id": r["id"],
                "status": r["status"] or "done",
                "started_at": r["started_at"] or "",
                "ended_at": r["ended_at"] or "",
                "entries": r["entry_count"] or 0,
                "source": r["source"] or "claude_code",
            }
            if r["summary"]:
                s_obj["summary"] = r["summary"]
            sessions.append(s_obj)
        self.send_json({"total": total, "sessions": sessions})

    def handle_api_export(self, params):
        """GET /api/export?id=xxx[&dir=custom_path] — Export full session as JSON to disk.
        Saves to export/{YYYY-MM-DD}/{session_id}.json by default.
        Returns the file path and session data."""
        session_id = params.get("id", [""])[0]
        if not session_id:
            self.send_json({"error": "id required"}, 400)
            return

        custom_dir = params.get("dir", [""])[0]

        conn = get_db()

        # Get session metadata
        meta = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not meta:
            conn.close()
            self.send_json({"error": f"Session {session_id} not found"}, 404)
            return

        # Get ALL entries for this session (no pagination)
        rows = conn.execute("""
            SELECT id, content, role, session_id, timestamp, source_file,
                   source_line, content_hash, created_at
            FROM entries WHERE session_id = ? ORDER BY source_line ASC
        """, (session_id,)).fetchall()
        conn.close()

        # Build export object
        entries = [dict(r) for r in rows]
        meta_dict = {k: meta[k] for k in meta.keys()}

        # Derive date from first entry timestamp or today
        first_ts = entries[0]["timestamp"] if entries else None
        if first_ts:
            date_str = first_ts[:10]  # YYYY-MM-DD
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")

        export_data = {
            "session_id": session_id,
            "exported_at": datetime.now().isoformat(),
            "date": date_str,
            "meta": meta_dict,
            "total_entries": len(entries),
            "entries": entries,
        }

        # Determine export directory
        if custom_dir:
            export_base = Path(custom_dir)
        else:
            # Default: project_root/export/
            export_base = Path(__file__).parent.parent / "export"

        export_dir = export_base / date_str
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / f"{session_id}.json"

        # Write JSON
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)

        self.send_json({
            "ok": True,
            "path": str(export_path),
            "session_id": session_id,
            "date": date_str,
            "entries": len(entries),
        })

    def handle_api_session_digest(self, params):
        """GET /api/session/digest?id=xxx — Structured digest of a session.
        Breaks the session into navigable segments, groups tool calls,
        produces stats, and extracts key moments for quick navigation."""
        session_id = params.get("id", [""])[0]
        if not session_id:
            self.send_json({"error": "id required"}, 400)
            return

        conn = get_db()
        meta = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not meta:
            conn.close()
            self.send_json({"error": f"Session {session_id} not found"}, 404)
            return

        rows = conn.execute("""
            SELECT id, content, role, timestamp, source_line
            FROM entries WHERE session_id = ? ORDER BY source_line ASC
        """, (session_id,)).fetchall()
        conn.close()

        entries = [dict(r) for r in rows]
        if not entries:
            self.send_json({"session_id": session_id, "segments": [], "stats": {}})
            return

        # ── Stats ──
        role_counts = {}
        tool_calls = 0
        total_chars = 0
        for e in entries:
            role_counts[e["role"]] = role_counts.get(e["role"], 0) + 1
            total_chars += len(e["content"] or "")
            if (e["content"] or "").startswith("[TOOL:"):
                tool_calls += 1

        timestamps = [e["timestamp"] for e in entries if e["timestamp"]]
        time_start = timestamps[0] if timestamps else None
        time_end = timestamps[-1] if timestamps else None

        stats = {
            "total_entries": len(entries),
            "by_role": role_counts,
            "tool_calls": tool_calls,
            "total_chars": total_chars,
            "time_start": time_start,
            "time_end": time_end,
        }

        # ── Segment by user prompts ──
        # Each user message starts a new "turn". Consecutive tool calls get grouped.
        segments = []
        current_segment = None

        for e in entries:
            content = e["content"] or ""
            is_tool = content.startswith("[TOOL:") or content.startswith('{"result":')
            is_user = e["role"] == "user" and not is_tool

            if is_user:
                # Start a new segment on each user message
                if current_segment:
                    segments.append(current_segment)
                # Extract a short title from the user prompt
                title = content[:120].replace("\n", " ").strip()
                if len(content) > 120:
                    title += "..."
                current_segment = {
                    "index": len(segments),
                    "title": title,
                    "start_line": e["source_line"],
                    "start_entry_id": e["id"],
                    "timestamp": e["timestamp"],
                    "entries": 1,
                    "tool_calls": 0,
                    "assistant_chars": 0,
                    "messages": [{
                        "role": e["role"],
                        "preview": content[:300],
                        "source_line": e["source_line"],
                        "is_tool": False,
                        "full_length": len(content),
                    }],
                }
            elif current_segment:
                current_segment["entries"] += 1
                if is_tool:
                    current_segment["tool_calls"] += 1
                if e["role"] == "assistant" and not is_tool:
                    current_segment["assistant_chars"] += len(content)

                # For non-tool messages, add preview. For tools, add collapsed summary.
                if is_tool:
                    # Extract tool name
                    tool_name = ""
                    if content.startswith("[TOOL:"):
                        bracket_end = content.find("]")
                        if bracket_end > 0:
                            tool_name = content[6:bracket_end]
                    current_segment["messages"].append({
                        "role": e["role"],
                        "preview": f"[{tool_name}]" if tool_name else "[tool result]",
                        "source_line": e["source_line"],
                        "is_tool": True,
                        "full_length": len(content),
                    })
                else:
                    current_segment["messages"].append({
                        "role": e["role"],
                        "preview": content[:300],
                        "source_line": e["source_line"],
                        "is_tool": False,
                        "full_length": len(content),
                    })
            else:
                # Entries before first user message (system/assistant intro)
                if not current_segment:
                    current_segment = {
                        "index": 0,
                        "title": "(session start)",
                        "start_line": e["source_line"],
                        "start_entry_id": e["id"],
                        "timestamp": e["timestamp"],
                        "entries": 1,
                        "tool_calls": 1 if is_tool else 0,
                        "assistant_chars": len(content) if e["role"] == "assistant" and not is_tool else 0,
                        "messages": [{
                            "role": e["role"],
                            "preview": content[:300],
                            "source_line": e["source_line"],
                            "is_tool": is_tool,
                            "full_length": len(content),
                        }],
                    }
                else:
                    current_segment["entries"] += 1

        if current_segment:
            segments.append(current_segment)

        # ── Key moments (longest assistant responses = most substantive) ──
        assistant_entries = [
            e for e in entries
            if e["role"] == "assistant"
            and not (e["content"] or "").startswith("[TOOL:")
            and not (e["content"] or "").startswith('{"result":')
        ]
        assistant_entries.sort(key=lambda e: len(e["content"] or ""), reverse=True)
        key_moments = []
        for e in assistant_entries[:10]:
            content = e["content"] or ""
            key_moments.append({
                "source_line": e["source_line"],
                "preview": content[:200],
                "length": len(content),
                "timestamp": e["timestamp"],
            })

        self.send_json({
            "session_id": session_id,
            "stats": stats,
            "segments": segments,
            "segment_count": len(segments),
            "key_moments": key_moments,
        })

    def handle_api_session_summary_get(self, params):
        """GET /api/session/summary?id=xxx — Return session summary."""
        session_id = params.get("id", [""])[0]
        if not session_id:
            self.send_json({"error": "id required"}, 400)
            return
        conn = get_db()
        row = conn.execute("SELECT summary FROM sessions WHERE id = ?", (session_id,)).fetchone()
        conn.close()
        if not row:
            self.send_json({"error": "session not found"}, 404)
            return
        self.send_json({"session_id": session_id, "summary": row["summary"]})

    def handle_api_session_summary_post(self, post_data):
        """POST /api/session/summary — Save session summary.
        Body: {"session_id": "xxx", "summary": "..."}"""
        try:
            data = json.loads(post_data)
        except (json.JSONDecodeError, ValueError):
            self.send_json({"error": "invalid JSON"}, 400)
            return
        session_id = data.get("session_id", "")
        summary = data.get("summary", "")
        if not session_id or not summary:
            self.send_json({"error": "session_id and summary required"}, 400)
            return
        conn = get_db()
        exists = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not exists:
            conn.close()
            self.send_json({"error": "session not found"}, 404)
            return
        conn.execute("UPDATE sessions SET summary = ? WHERE id = ?", (summary, session_id))
        conn.commit()
        conn.close()
        self.send_json({"ok": True, "session_id": session_id})

    # ── Setup Wizard ─────────────────────────────────────────────────

    def setup_page_wrap(self, title, body):
        """Minimal page wrapper for setup wizard — no nav bar, no DB queries."""
        return f"""<!DOCTYPE html><html><head>
        <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{title} — Memory Engine</title>
        <style>{CSS}\n{SETUP_CSS}</style>
        </head><body>
        <div class="header">
            <h1 style="font-size:16px;">
                <span class="live-dot" style="background:var(--accent);"></span>
                Memory Engine
            </h1>
            <span class="stats" style="margin-left:auto;">Setup</span>
        </div>
        <div class="container">{body}</div>
        </body></html>"""

    def handle_api_setup_detect(self):
        """Auto-detect system configuration."""
        import shutil
        from config import DB_PATH as _db, JSONL_DIR as _jsonl, _get_engine_dir
        python_path = sys.executable
        mcp_server_path = str(Path(__file__).parent / "mcp_server.py")
        jsonl_dir = str(_jsonl)
        db_path = str(_db)
        jsonl_count = 0
        try:
            jdir = Path(jsonl_dir)
            if jdir.is_dir():
                jsonl_count = len(list(jdir.glob("*.jsonl")))
        except Exception:
            pass
        self.send_json({
            "python_path": python_path,
            "python_found": os.path.exists(python_path),
            "mcp_server_path": mcp_server_path,
            "mcp_server_found": os.path.exists(mcp_server_path),
            "jsonl_dir": jsonl_dir,
            "jsonl_dir_found": os.path.isdir(jsonl_dir),
            "jsonl_count": jsonl_count,
            "db_path": db_path,
            "db_exists": os.path.exists(db_path),
            "engine_dir": str(_get_engine_dir()),
        })

    def handle_api_setup_test(self, params):
        """Test database connection."""
        db = params.get("db", [DB_PATH])[0]
        try:
            conn = sqlite3.connect(db)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            entry_count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] if "entries" in tables else 0
            session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] if "sessions" in tables else 0
            conn.close()
            self.send_json({"ok": True, "tables": len(tables), "entries": entry_count, "sessions": session_count})
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)})

    def handle_api_setup_config(self, params):
        """Generate tool-specific MCP config JSON."""
        tool = params.get("tool", ["claude_code"])[0]
        python = params.get("python", [sys.executable])[0]
        mcp_server = params.get("mcp_server", [str(Path(__file__).parent / "mcp_server.py")])[0]
        db = params.get("db", [DB_PATH])[0]

        entry = {"command": python, "args": [mcp_server], "env": {"MEMORY_DB": db}}

        if tool == "vscode":
            cfg = {"servers": {"memory-engine": {"type": "stdio", **entry}}}
            config_path = str(Path.home() / ".vscode" / "mcp.json")
            display_path = "~/.vscode/mcp.json"
        elif tool == "cursor":
            cfg = {"mcpServers": {"memory-engine": entry}}
            config_path = str(Path.home() / ".cursor" / "mcp.json")
            display_path = "~/.cursor/mcp.json"
        elif tool == "claude_desktop":
            cfg = {"mcpServers": {"memory-engine": entry}}
            from config import get_claude_config_dir
            config_path = str(get_claude_config_dir() / "claude_desktop_config.json")
            display_path = config_path.replace(str(Path.home()), "~")
        else:  # claude_code + other
            cfg = {"mcpServers": {"memory-engine": entry}}
            from config import get_claude_config_dir
            config_path = str(get_claude_config_dir() / "settings.json")
            display_path = "~/.claude/settings.json"

        self.send_json({"config": cfg, "real_path": config_path, "display_path": display_path, "tool": tool})

    def handle_api_setup_install_post(self, post_data):
        """Write MCP config to the tool's config file (merge, don't overwrite)."""
        try:
            data = json.loads(post_data)
            target_path = Path(data["real_path"])
            new_config = data["config"]

            existing = {}
            if target_path.exists():
                try:
                    with open(target_path) as f:
                        existing = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass

            # Deep merge: only add/update the memory-engine key
            for top_key, top_val in new_config.items():
                if top_key not in existing:
                    existing[top_key] = {}
                if isinstance(top_val, dict):
                    for k, v in top_val.items():
                        existing[top_key][k] = v

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w") as f:
                json.dump(existing, f, indent=2)

            self.send_json({"ok": True, "path": str(target_path)})
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)})

    def handle_api_setup_ingest_post(self):
        """Trigger first JSONL ingestion."""
        try:
            from engine import MemoryEngine as _ME
            from config import JSONL_DIR as _jdir
            eng = _ME()

            jsonls = sorted(Path(_jdir).glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            archive_dir = Path(_jdir) / "archive"
            if archive_dir.exists():
                jsonls += sorted(archive_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

            done, skipped, entries_total = 0, 0, 0
            for f in jsonls:
                r = eng.ingest_jsonl(str(f))
                if r.get("status") == "already_done":
                    skipped += 1
                else:
                    done += 1
                    entries_total += r.get("entries", 0)

            eng.conn.close()
            ViewerHandler._setup_done = True

            self.send_json({
                "ok": True,
                "files_scanned": len(jsonls),
                "sessions_ingested": done,
                "sessions_skipped": skipped,
                "entries_indexed": entries_total,
            })
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)})

    def handle_setup(self, params):
        """Render the 6-step onboarding wizard."""
        body = """
        <div class="wizard-progress" id="progress">
            <div class="wizard-dot active"></div>
            <div class="wizard-dot"></div>
            <div class="wizard-dot"></div>
            <div class="wizard-dot"></div>
            <div class="wizard-dot"></div>
            <div class="wizard-dot"></div>
        </div>

        <!-- Step 1: Welcome -->
        <div class="wizard-panel active" id="step1">
            <div class="wizard-hero">
                <h1><span class="live-dot" style="background:var(--accent);"></span> Memory Engine</h1>
                <p>Persistent brain database for your AI coding tools.<br>
                Index all conversations into searchable SQLite with vector embeddings.</p>
            </div>
            <div class="wizard-pills">
                <span class="wizard-pill">Full-text search</span>
                <span class="wizard-pill">Semantic search</span>
                <span class="wizard-pill">Auto-extracted observations</span>
                <span class="wizard-pill">Session timeline</span>
                <span class="wizard-pill">Project organization</span>
            </div>
            <div style="text-align:center;">
                <button class="wizard-btn green" onclick="goToStep(2)">Get Started</button>
            </div>
        </div>

        <!-- Step 2: Select Tool -->
        <div class="wizard-panel" id="step2">
            <h2 style="text-align:center; margin-bottom:8px;">Select Your AI Tool</h2>
            <p style="text-align:center; color:var(--text2); margin-bottom:16px;">Which tool will connect to Memory Engine?</p>
            <div class="tool-grid">
                <div class="tool-card" onclick="selectTool('claude_code', this)">
                    <span class="icon">&#9672;</span>
                    <span class="name">Claude Code</span>
                    <span class="desc">CLI &amp; Desktop</span>
                </div>
                <div class="tool-card" onclick="selectTool('vscode', this)">
                    <span class="icon">&#9998;</span>
                    <span class="name">VS Code</span>
                    <span class="desc">Copilot / Extensions</span>
                </div>
                <div class="tool-card" onclick="selectTool('cursor', this)">
                    <span class="icon">&#9881;</span>
                    <span class="name">Cursor</span>
                    <span class="desc">AI Code Editor</span>
                </div>
                <div class="tool-card" onclick="selectTool('claude_desktop', this)">
                    <span class="icon">&#9635;</span>
                    <span class="name">Claude Desktop</span>
                    <span class="desc">Desktop App</span>
                </div>
                <div class="tool-card" onclick="selectTool('other', this)">
                    <span class="icon">&#8943;</span>
                    <span class="name">Other</span>
                    <span class="desc">Generic MCP</span>
                </div>
            </div>
        </div>

        <!-- Step 3: Auto-detect -->
        <div class="wizard-panel" id="step3">
            <h2 style="margin-bottom:8px;">Configuration</h2>
            <p style="color:var(--text2); margin-bottom:16px;">Auto-detected paths. Click a value to edit.</p>
            <div id="detect-rows">
                <div style="text-align:center; padding:24px;"><span class="spinner"></span> Detecting...</div>
            </div>
            <div id="test-status"></div>
            <div style="display:flex; gap:8px; margin-top:16px;">
                <button class="wizard-btn outline" onclick="goToStep(2)">Back</button>
                <button class="wizard-btn" onclick="testConnection()" id="test-btn">Test Connection</button>
                <button class="wizard-btn green" onclick="goToStep(4)" id="next3-btn" disabled>Next</button>
            </div>
        </div>

        <!-- Step 4: Config -->
        <div class="wizard-panel" id="step4">
            <h2 style="margin-bottom:8px;">Connect to <span id="tool-label">your tool</span></h2>
            <p style="color:var(--text2); margin-bottom:12px;">Add this to your config file:</p>
            <div class="config-path" id="config-path-display"></div>
            <div class="config-block">
                <button class="copy-btn" onclick="copyConfig()">Copy</button>
                <pre id="config-json"></pre>
            </div>
            <div id="install-status"></div>
            <div style="display:flex; gap:8px; margin-top:16px;">
                <button class="wizard-btn outline" onclick="goToStep(3)">Back</button>
                <button class="wizard-btn green" onclick="autoInstall()" id="install-btn">Auto-Install</button>
                <button class="wizard-btn outline" onclick="goToStep(5)">Skip — I'll do it manually</button>
            </div>
        </div>

        <!-- Step 5: Ingest -->
        <div class="wizard-panel" id="step5">
            <h2 style="margin-bottom:8px;">Index Your Conversations</h2>
            <p style="color:var(--text2); margin-bottom:16px;" id="ingest-desc">
                Scan your Claude Code conversation history and build the searchable database.
            </p>
            <div id="ingest-status"></div>
            <div style="display:flex; gap:8px; margin-top:16px;">
                <button class="wizard-btn outline" onclick="goToStep(4)">Back</button>
                <button class="wizard-btn green" onclick="runIngest()" id="ingest-btn">Start Indexing</button>
                <button class="wizard-btn outline" onclick="goToStep(6)" id="skip-ingest-btn">Skip for now</button>
            </div>
        </div>

        <!-- Step 6: Done -->
        <div class="wizard-panel" id="step6">
            <div class="wizard-done">
                <div class="checkmark"></div>
                <h2 style="color:var(--green); margin-bottom:8px;">You're all set!</h2>
                <p style="color:var(--text2); margin-bottom:24px;" id="done-summary">Memory Engine is ready.</p>
                <div class="stats-grid" id="done-stats" style="max-width:400px; margin:0 auto 24px;"></div>
                <a href="/" class="wizard-btn green" style="text-decoration:none;">Open Dashboard</a>
            </div>
            <details class="tool-ref">
                <summary>MCP Tool Quick Reference (27 tools)</summary>
                <table>
                    <tr><td>memory_search</td><td>Full-text keyword search</td></tr>
                    <tr><td>memory_semantic</td><td>Vector/hybrid search by meaning</td></tr>
                    <tr><td>memory_topic</td><td>Deep-dive into any topic</td></tr>
                    <tr><td>memory_topics</td><td>Discover frequent topics</td></tr>
                    <tr><td>memory_save</td><td>Save curated knowledge</td></tr>
                    <tr><td>memory_search_knowledge</td><td>Search knowledge base</td></tr>
                    <tr><td>memory_timeline</td><td>Browse by time range</td></tr>
                    <tr><td>memory_ingest</td><td>Ingest JSONL conversations</td></tr>
                    <tr><td>memory_stats</td><td>Database statistics</td></tr>
                    <tr><td>memory_observations</td><td>Auto-extracted patterns</td></tr>
                    <tr><td>memory_session_summary</td><td>Session summaries</td></tr>
                    <tr><td>memory_context</td><td>Conversation context around entry</td></tr>
                    <tr><td>memory_similar</td><td>Find similar entries</td></tr>
                    <tr><td>memory_delete</td><td>Delete specific entries</td></tr>
                    <tr><td>memory_forget</td><td>Bulk delete by session/date/pattern</td></tr>
                    <tr><td>memory_export</td><td>Export as JSON or CSV</td></tr>
                    <tr><td>memory_health</td><td>Database health check</td></tr>
                    <tr><td>memory_config</td><td>Show resolved configuration</td></tr>
                    <tr><td>project_create</td><td>Create project grouping</td></tr>
                    <tr><td>project_list</td><td>List all projects</td></tr>
                    <tr><td>project_search</td><td>Search within a project</td></tr>
                    <tr><td>project_delete</td><td>Delete a project</td></tr>
                </table>
            </details>
        </div>

        <script>
        let currentStep = 1;
        let selectedTool = '';
        let detectedConfig = {};
        let generatedConfig = {};

        function goToStep(n) {
            document.querySelectorAll('.wizard-panel').forEach(p => p.classList.remove('active'));
            document.getElementById('step' + n).classList.add('active');
            document.querySelectorAll('.wizard-dot').forEach((d, i) => {
                d.classList.remove('active', 'done');
                if (i < n - 1) d.classList.add('done');
                if (i === n - 1) d.classList.add('active');
            });
            currentStep = n;
            if (n === 3) runDetect();
            if (n === 4) loadConfig();
        }

        function selectTool(tool, el) {
            selectedTool = tool;
            document.querySelectorAll('.tool-card').forEach(c => c.classList.remove('selected'));
            el.classList.add('selected');
            const labels = {claude_code:'Claude Code', vscode:'VS Code', cursor:'Cursor', claude_desktop:'Claude Desktop', other:'Your Tool'};
            document.getElementById('tool-label').textContent = labels[tool] || tool;
            setTimeout(() => goToStep(3), 300);
        }

        async function runDetect() {
            const res = await fetch('/api/setup/detect');
            detectedConfig = await res.json();
            const c = detectedConfig;
            let html = '';
            html += detectRow('Python', 'python_path', c.python_path, c.python_found);
            html += detectRow('MCP Server', 'mcp_server_path', c.mcp_server_path, c.mcp_server_found);
            html += detectRow('JSONL Dir', 'jsonl_dir', c.jsonl_dir, c.jsonl_dir_found, c.jsonl_count + ' files');
            html += detectRow('Database', 'db_path', c.db_path, true);
            document.getElementById('detect-rows').innerHTML = html;
        }

        function detectRow(label, key, value, ok, extra) {
            const statusIcon = ok ? '<span style="color:var(--green);">&#10003;</span>' : '<span style="color:var(--red);">&#10007;</span>';
            const extraText = extra ? ' <span style="color:var(--text2);">(' + extra + ')</span>' : '';
            return '<div class="detect-row">' +
                '<span class="label">' + label + '</span>' +
                '<span class="value' + (ok ? '' : ' missing') + '" id="val-' + key + '" onclick="editField(this, \\'' + key + '\\')">' + value + extraText + '</span>' +
                '<span class="status">' + statusIcon + '</span></div>';
        }

        function editField(el, key) {
            const current = detectedConfig[key] || '';
            el.outerHTML = '<input class="value" id="val-' + key + '" value="' + current.replace(/"/g, '&quot;') + '" onblur="saveField(this, \\'' + key + '\\')" autofocus>';
            document.getElementById('val-' + key).focus();
        }

        function saveField(el, key) {
            detectedConfig[key] = el.value;
            el.outerHTML = '<span class="value" id="val-' + key + '" onclick="editField(this, \\'' + key + '\\')">' + el.value + '</span>';
        }

        async function testConnection() {
            document.getElementById('test-btn').disabled = true;
            document.getElementById('test-status').innerHTML = '<div class="wizard-status info"><span class="spinner"></span> Testing...</div>';
            try {
                const db = detectedConfig.db_path || '';
                const res = await fetch('/api/setup/test?db=' + encodeURIComponent(db));
                const data = await res.json();
                if (data.ok) {
                    document.getElementById('test-status').innerHTML = '<div class="wizard-status ok">Connected — ' + data.entries + ' entries, ' + data.sessions + ' sessions, ' + data.tables + ' tables</div>';
                    document.getElementById('next3-btn').disabled = false;
                } else {
                    document.getElementById('test-status').innerHTML = '<div class="wizard-status ok">Database will be created at: ' + (detectedConfig.db_path || 'default location') + '</div>';
                    document.getElementById('next3-btn').disabled = false;
                }
            } catch(e) {
                document.getElementById('test-status').innerHTML = '<div class="wizard-status err">Connection failed: ' + e.message + '</div>';
            }
            document.getElementById('test-btn').disabled = false;
        }

        async function loadConfig() {
            const p = detectedConfig;
            const url = '/api/setup/config?tool=' + encodeURIComponent(selectedTool)
                + '&python=' + encodeURIComponent(p.python_path || '')
                + '&mcp_server=' + encodeURIComponent(p.mcp_server_path || '')
                + '&db=' + encodeURIComponent(p.db_path || '');
            const res = await fetch(url);
            generatedConfig = await res.json();
            document.getElementById('config-path-display').textContent = generatedConfig.display_path || generatedConfig.real_path;
            document.getElementById('config-json').textContent = JSON.stringify(generatedConfig.config, null, 2);
        }

        function copyConfig() {
            const text = document.getElementById('config-json').textContent;
            navigator.clipboard.writeText(text).then(() => {
                const btn = document.querySelector('.copy-btn');
                btn.textContent = 'Copied!';
                setTimeout(() => btn.textContent = 'Copy', 2000);
            });
        }

        async function autoInstall() {
            document.getElementById('install-btn').disabled = true;
            document.getElementById('install-status').innerHTML = '<div class="wizard-status info"><span class="spinner"></span> Installing...</div>';
            try {
                const res = await fetch('/api/setup/install', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({config: generatedConfig.config, real_path: generatedConfig.real_path})
                });
                const data = await res.json();
                if (data.ok) {
                    document.getElementById('install-status').innerHTML = '<div class="wizard-status ok">Installed to ' + data.path + '</div>';
                    setTimeout(() => goToStep(5), 1000);
                } else {
                    document.getElementById('install-status').innerHTML = '<div class="wizard-status err">Error: ' + data.error + '</div>';
                }
            } catch(e) {
                document.getElementById('install-status').innerHTML = '<div class="wizard-status err">' + e.message + '</div>';
            }
            document.getElementById('install-btn').disabled = false;
        }

        async function runIngest() {
            document.getElementById('ingest-btn').disabled = true;
            document.getElementById('skip-ingest-btn').style.display = 'none';
            document.getElementById('ingest-status').innerHTML = '<div class="wizard-status info"><span class="spinner"></span> Indexing conversations... this may take a minute.</div>';
            try {
                const res = await fetch('/api/setup/ingest', {method: 'POST'});
                const data = await res.json();
                if (data.ok) {
                    document.getElementById('ingest-status').innerHTML =
                        '<div class="wizard-status ok">' + data.entries_indexed + ' entries indexed from ' + data.sessions_ingested + ' sessions (' + data.files_scanned + ' files scanned)</div>';
                    // Populate done page
                    document.getElementById('done-summary').textContent = 'Indexed ' + data.entries_indexed + ' entries from ' + data.sessions_ingested + ' sessions.';
                    document.getElementById('done-stats').innerHTML =
                        '<div class="stat-card"><div class="label">Entries</div><div class="value">' + data.entries_indexed + '</div></div>' +
                        '<div class="stat-card"><div class="label">Sessions</div><div class="value">' + data.sessions_ingested + '</div></div>' +
                        '<div class="stat-card"><div class="label">Files Scanned</div><div class="value">' + data.files_scanned + '</div></div>';
                    setTimeout(() => goToStep(6), 1500);
                } else {
                    document.getElementById('ingest-status').innerHTML = '<div class="wizard-status err">Error: ' + (data.error || 'Unknown') + '</div>';
                }
            } catch(e) {
                document.getElementById('ingest-status').innerHTML = '<div class="wizard-status err">' + e.message + '</div>';
            }
            document.getElementById('ingest-btn').disabled = false;
        }
        </script>
        """
        self.send_html(self.setup_page_wrap("Setup", body))


def main():
    HOST = os.environ.get("VIEWER_HOST", "127.0.0.1")
    server = HTTPServer((HOST, PORT), ViewerHandler)
    print(f"[+] Memory Engine Viewer running on http://{HOST}:{PORT}")
    print(f"[i] DB: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
