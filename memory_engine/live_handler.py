"""
Live tail handler functions — injected into viewer.py
Contains handle_live, handle_api_session_new
"""

LIVE_PAGE_JS = r"""
<script>
const SESSION_ID = "SESSION_ID_PLACEHOLDER";
let lastLine = 0;
let pollInterval = 2000;
let autoScroll = true;
let showTools = false;

document.getElementById('autoScroll').addEventListener('change', (e) => {
    autoScroll = e.target.checked;
});
document.getElementById('showTools').addEventListener('change', (e) => {
    showTools = e.target.checked;
    document.querySelectorAll('.tool-entry').forEach(el => {
        el.style.display = showTools ? 'block' : 'none';
    });
});

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function createEntry(entry) {
    const div = document.createElement('div');
    const isTool = entry.content.startsWith('[TOOL:');
    div.className = 'entry' + (isTool ? ' tool-entry' : '');
    if (isTool && !showTools) div.style.display = 'none';

    const ts = entry.timestamp ? entry.timestamp.substring(11, 19) : '?';
    const content = escapeHtml(entry.content.substring(0, 2000));
    const roleClass = entry.role || 'system';

    const meta = document.createElement('div');
    meta.className = 'meta';

    const roleSpan = document.createElement('span');
    roleSpan.className = 'role ' + roleClass;
    roleSpan.textContent = entry.role;
    meta.appendChild(roleSpan);

    const tsSpan = document.createElement('span');
    tsSpan.textContent = ts;
    meta.appendChild(tsSpan);

    const lineSpan = document.createElement('span');
    lineSpan.textContent = 'line ' + entry.source_line;
    meta.appendChild(lineSpan);

    div.appendChild(meta);

    const contentDiv = document.createElement('div');
    contentDiv.className = 'content';

    const raw = entry.content.substring(0, 5000);
    const imgPattern = /\[IMAGE:([^\]]+)\]/g;
    let lastIdx = 0;
    let m;

    while ((m = imgPattern.exec(raw)) !== null) {
        if (m.index > lastIdx) {
            const textNode = document.createTextNode(raw.substring(lastIdx, m.index));
            contentDiv.appendChild(textNode);
        }

        const imgWrap = document.createElement('div');
        imgWrap.style.cssText = 'margin:8px 0;';

        const link = document.createElement('a');
        link.href = '/img/' + m[1];
        link.target = '_blank';

        const img = document.createElement('img');
        img.src = '/img/' + m[1];
        img.style.cssText = 'max-width:600px; max-height:400px; border-radius:6px; border:1px solid var(--border);';
        img.loading = 'lazy';

        link.appendChild(img);
        imgWrap.appendChild(link);
        contentDiv.appendChild(imgWrap);

        lastIdx = m.index + m[0].length;
    }

    if (lastIdx < raw.length) {
        contentDiv.appendChild(document.createTextNode(raw.substring(lastIdx)));
    }

    if (lastIdx === 0) {
        contentDiv.textContent = raw;
    }

    div.appendChild(contentDiv);

    div.style.borderColor = '#3fb950';
    setTimeout(() => { div.style.borderColor = ''; div.style.transition = 'border-color 1s'; }, 1500);

    return div;
}

async function fetchNew() {
    try {
        const resp = await fetch('/api/session_new?id=' + SESSION_ID + '&after=' + lastLine);
        const data = await resp.json();

        if (data.entries && data.entries.length > 0) {
            const container = document.getElementById('entries');
            const loading = document.getElementById('loading');
            if (loading) loading.remove();

            data.entries.forEach(entry => {
                container.appendChild(createEntry(entry));
                if (entry.source_line > lastLine) lastLine = entry.source_line;
            });

            const header = document.querySelector('h3');
            if (header) header.textContent = 'Live — ' + data.total + ' entries';

            if (autoScroll) {
                container.scrollTop = container.scrollHeight;
            }
        }

        const st = document.getElementById('status');
        if (st) { st.textContent = 'connected'; st.style.color = '#3fb950'; }
    } catch (e) {
        const st = document.getElementById('status');
        if (st) { st.textContent = 'disconnected'; st.style.color = '#f85149'; }
    }
}

async function initialLoad() {
    try {
        const resp = await fetch('/api/session_new?id=' + SESSION_ID + '&after=0&limit=5000');
        const data = await resp.json();

        const container = document.getElementById('entries');
        const loading = document.getElementById('loading');
        if (loading) loading.remove();

        if (data.entries) {
            data.entries.forEach(entry => {
                container.appendChild(createEntry(entry));
                if (entry.source_line > lastLine) lastLine = entry.source_line;
            });
        }

        if (autoScroll) {
            container.scrollTop = container.scrollHeight;
        }
    } catch (e) {
        console.error('Initial load failed:', e);
    }
}

initialLoad();
setInterval(fetchNew, pollInterval);
</script>
"""
