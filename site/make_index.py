"""Rewrites the live site's index.html so its words match what the directory measures (Oct 2026).

Reads site_backup_2026-10-08/index.html (the page as it was live) and writes site/index.html.
Every replacement must match exactly once, so a changed source fails loudly instead of half-applying."""
import io
import pathlib

HERE = pathlib.Path(__file__).parent
src = io.open(HERE.parent / "site_backup_2026-10-08" / "index.html", encoding="utf-8", errors="surrogateescape", newline="").read().replace("\r\n", "\n")

DESC_OLD = ("The machine-readable directory of autonomous AI agents. Every listing is crawled, probed for prompt "
            "injection resistance, and scored by an independent multi-family LLM judge panel.")
DESC_NEW = ("The machine-readable directory of AI agents another agent can call: remote MCP servers from the official "
            "registry, each tested over the protocol every day for availability, latency and tools.")

REPLACEMENTS = [
    (DESC_OLD, DESC_NEW, 3),
    ('<div><span id="auditedTodayCounter" class="text-sb-text font-bold">--</span> audited today</div>',
     '<div><span id="auditedTodayCounter" class="text-sb-text font-bold">--</span> working now</div>', 1),
    ("Our crawler hunts A2A files, MCP servers, and LLM interfaces autonomously across the web — then benchmarks each one.",
     "Every day we read the official MCP Registry, connect to each server over MCP, and record whether it answers, "
     "how fast, and which tools it offers.", 1),
    ("How the Oracle Benchmark Works", "How the Daily Protocol Check Works", 1),
    ('<h3 class="text-lg font-bold mb-2">1. Crawl</h3>', '<h3 class="text-lg font-bold mb-2">1. Discover</h3>', 1),
    ('<p class="text-sm text-sb-muted">Our distributed spiders actively hunt the web for <code class="text-xs bg-[#111] px-1 py-0.5 rounded">.well-known</code> directories, MCP definitions, and A2A-compatible endpoints.</p>',
     '<p class="text-sm text-sb-muted">We read the official MCP Registry and keep every active server that publishes a public HTTPS endpoint.</p>', 1),
    ('<p class="text-sm text-sb-muted">Each discovered agent is slammed with high-density deterministic latency tests and sophisticated Prompt Injection attempts.</p>',
     '<p class="text-sm text-sb-muted">Each endpoint gets a real MCP handshake: <code class="text-xs bg-[#111] px-1 py-0.5 rounded">initialize</code>, then <code class="text-xs bg-[#111] px-1 py-0.5 rounded">tools/list</code>. Read-only: no tool is ever called.</p>', 1),
    ('<h3 class="text-lg font-bold mb-2">3. Judge</h3>', '<h3 class="text-lg font-bold mb-2">3. Score</h3>', 1),
    ('<p class="text-sm text-sb-muted">A multi-family LLM panel (Meta, Mistral, Google) scores Security, Intelligence, and Performance. Same-family judges are recused to prevent bias.</p>',
     '<p class="text-sm text-sb-muted">Reachable 20 + answers MCP 40 + lists tools 20 + latency 20. Servers behind authentication are listed and tagged, without a score. It measures whether an agent can connect, not quality.</p>', 1),
    ('<th class="px-6 py-4 font-semibold">Security</th>', '<th class="px-6 py-4 font-semibold">Latency</th>', 1),
    ('<th class="px-6 py-4 font-semibold">Intelligence</th>', '<th class="px-6 py-4 font-semibold">Tools</th>', 1),
    ('<th class="px-6 py-4 font-semibold">Performance</th>', '<th class="px-6 py-4 font-semibold">Protocol</th>', 1),
    ("<p>Syncing with Oracle Database...</p>", "<p>Loading the directory...</p>", 1),
    ("To receive an official A2A Trust Score, verify ownership and request an Oracle Audit.",
     "To have it checked, verify ownership and queue a protocol check.", 1),
    ('<p class="text-sm font-bold text-sb-muted">Probe & Judge</p>', '<p class="text-sm font-bold text-sb-muted">Protocol check</p>', 1),
    ('<p class="text-xs text-sb-muted">LLM Panel evaluating security.</p>', '<p class="text-xs text-sb-muted">MCP handshake and tools/list.</p>', 1),
    ('"description": "The machine-readable directory of autonomous AI agents. Every listing is crawled, probed, and scored.",',
     '"description": "The machine-readable directory of AI agents another agent can call, each tested over MCP every day.",', 1),
    # leaderboard cells: latency, number of tools, protocol version from the probe
    ("""                const scores = agent.audit_log?.final_scores || {};
                const sec = scores.security_median ?? '-';
                const int = scores.intelligence_median ?? '-';
                const perf = scores.performance_score ?? '-';""",
     """                const probe = agent.raw_card?.probe || {};
                const sec = agent.response_time_ms ? `${agent.response_time_ms} ms` : '-';
                const int = Array.isArray(probe.tools) ? probe.tools.length : '-';
                const perf = probe.protocol_version || '-';""", 1),
    # counters: exact totals from /stats instead of the length of one 1000-row page
    ("""        function updateLiveCounters() {
            document.getElementById('totalAgentsCounter').innerText = allAgents.length;""",
     """        async function updateLiveCounters() {
            try {
                const s = await (await fetch(API_URL.replace(/\\/agents$/, '/stats'))).json();
                document.getElementById('totalAgentsCounter').innerText = (s.agents_with_endpoint ?? allAgents.length).toLocaleString('en');
                document.getElementById('auditedTodayCounter').innerText = (s.open_and_working ?? 0).toLocaleString('en');
                return;
            } catch (e) { /* fall back to the loaded page */ }
            document.getElementById('totalAgentsCounter').innerText = allAgents.length;""", 1),
    # servers behind authentication are not "pending": say what they are
    ("""                    } else {
                        tierBadge = `<div class="flex items-center gap-1.5 border border-sb-border bg-[#111] text-sb-muted text-[10px] uppercase font-bold tracking-wider px-2 py-1 rounded-md mb-3 w-max"><i class="ph-fill ph-hourglass-high"></i> Pending Audit</div>`;""",
     """                    } else if (tags.includes('auth-required')) {
                        tierBadge = `<div class="flex items-center gap-1.5 border border-sb-border bg-[#111] text-sb-muted text-[10px] uppercase font-bold tracking-wider px-2 py-1 rounded-md mb-3 w-max"><i class="ph-fill ph-lock-simple"></i> Auth required</div>`;
                    } else {
                        tierBadge = `<div class="flex items-center gap-1.5 border border-sb-border bg-[#111] text-sb-muted text-[10px] uppercase font-bold tracking-wider px-2 py-1 rounded-md mb-3 w-max"><i class="ph-fill ph-hourglass-high"></i> Pending Audit</div>`;""", 1),
]

out = src
for old, new, times in REPLACEMENTS:
    n = out.count(old)
    assert n == times, f"expected {times} match(es), found {n}: {old[:70]!r}"
    out = out.replace(old, new)
io.open(HERE / "index.html", "w", encoding="utf-8", errors="surrogateescape", newline="").write(out)
print("written", len(out), "chars")
