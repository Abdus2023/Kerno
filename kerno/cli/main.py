"""
kerno command-line interface.
Entry point: kerno [command] [options]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        prog        = "kerno",
        description = "kerno: a kernel-native agent runtime",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Examples:\n"
            "  kerno run \"Analyze data.csv\"                  # Run with default LLM\n"
            "  kerno run \"Analyze data.csv\" --loop reflect   # Use ReflectReviseLoop\n"
            "  kerno session list                              # List past sessions\n"
            "  kerno memory list                              # Show stored memories\n"
            "  kerno config show                              # Show current config\n"
            "  kerno doctor                                   # Check environment\n"
        ),
    )

    parser.add_argument(
        "--config", "-c",
        metavar = "PATH",
        help    = "Path to config JSON file (default: .kerno/config.json)",
        default = None,
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ── run ───────────────────────────────────────────────────────────────────
    run_p = sub.add_parser("run", help="Run a task")
    run_p.add_argument("task",       help="Task description (natural language)")
    run_p.add_argument(
        "--loop", "-l",
        choices = ["reactive", "reflect", "plan", "hierarchical", "multi_agent"],
        default = "reactive",
        help    = "Execution loop strategy (default: reactive)",
    )
    run_p.add_argument(
        "--model", "-m",
        default = None,
        help    = "LLM model name (overrides config)",
    )
    run_p.add_argument(
        "--provider",
        choices = ["anthropic", "openai"],
        default = "anthropic",
        help    = "LLM provider (default: anthropic)",
    )
    run_p.add_argument(
        "--max-cells", "-n",
        type    = int,
        default = None,
        help    = "Maximum cells to execute",
    )
    run_p.add_argument(
        "--skills",
        metavar = "PATH",
        default = None,
        help    = "Path to skills file",
    )
    run_p.add_argument(
        "--save-notebook",
        action  = "store_true",
        default = False,
        help    = "Save session as a Jupyter notebook",
    )
    run_p.add_argument(
        "--notebook-dir",
        metavar = "DIR",
        default = "sessions",
        help    = "Directory for saved notebooks (default: sessions)",
    )
    run_p.add_argument(
        "--verbose", "-v",
        action  = "store_true",
        default = False,
        help    = "Print execution trace",
    )
    run_p.add_argument(
        "--memory",
        action  = "store_true",
        default = False,
        help    = "Enable cross-session memory",
    )
    run_p.add_argument(
        "--security",
        choices = ["none", "permissive", "data_analysis", "read_only"],
        default = "none",
        help    = "Security allowlist profile",
    )

    # ── session ───────────────────────────────────────────────────────────────
    sess_p = sub.add_parser("session", help="Inspect past sessions")
    sess_sub = sess_p.add_subparsers(dest="session_cmd")

    sess_list_p = sess_sub.add_parser("list", help="List saved sessions")
    sess_list_p.add_argument(
        "--dir", default="sessions", metavar="DIR",
        help="Sessions directory (default: sessions)"
    )
    sess_list_p.add_argument(
        "--limit", "-n", type=int, default=10,
        help="Maximum sessions to show (default: 10)"
    )

    sess_show_p = sess_sub.add_parser("show", help="Show a session notebook")
    sess_show_p.add_argument("path", help="Path to .ipynb file")

    # ── memory ────────────────────────────────────────────────────────────────
    mem_p   = sub.add_parser("memory", help="Manage the memory store")
    mem_sub = mem_p.add_subparsers(dest="memory_cmd")

    mem_list_p = mem_sub.add_parser("list", help="List stored memories")
    mem_list_p.add_argument(
        "--kind", choices=["result", "error", "insight", "skill"],
        default=None, help="Filter by kind"
    )
    mem_list_p.add_argument("--limit", "-n", type=int, default=20)
    mem_list_p.add_argument(
        "--path", default=".kerno/memory.json",
        help="Memory store path"
    )

    mem_search_p = mem_sub.add_parser("search", help="Search memories")
    mem_search_p.add_argument("query", help="Search query")
    mem_search_p.add_argument("--k", type=int, default=5)
    mem_search_p.add_argument("--path", default=".kerno/memory.json")

    mem_clear_p = mem_sub.add_parser("clear", help="Clear all memories")
    mem_clear_p.add_argument("--path", default=".kerno/memory.json")
    mem_clear_p.add_argument("--confirm", action="store_true")

    # ── config ────────────────────────────────────────────────────────────────
    cfg_p   = sub.add_parser("config", help="Manage configuration")
    cfg_sub = cfg_p.add_subparsers(dest="config_cmd")

    cfg_show_p = cfg_sub.add_parser("show", help="Show current configuration")
    cfg_show_p.add_argument(
        "--format", choices=["text", "json"],
        default="text"
    )

    cfg_init_p = cfg_sub.add_parser("init", help="Generate a config file")
    cfg_init_p.add_argument(
        "--profile",
        choices=["default", "development", "production"],
        default="default"
    )
    cfg_init_p.add_argument(
        "--output", "-o",
        default=".kerno/config.json",
        metavar="PATH"
    )

    # ── doctor ────────────────────────────────────────────────────────────────
    sub.add_parser("doctor", help="Diagnose the kerno environment")

    # ── metrics ───────────────────────────────────────────────────────────────
    sub.add_parser("metrics", help="Show current metrics snapshot")

    # ── repl ──────────────────────────────────────────────────────────────────
    repl_p = sub.add_parser("repl", help="Start the interactive kerno REPL")
    repl_p.add_argument(
        "--model", "-m",
        default = None,
        help    = "LLM model name (overrides config)",
    )
    repl_p.add_argument(
        "--provider",
        choices = ["anthropic", "openai"],
        default = "anthropic",
        help    = "LLM provider",
    )
    repl_p.add_argument(
        "--loop",
        choices = ["reactive", "reflect"],
        default = "reactive",
        help    = "Loop strategy for REPL tasks",
    )

    # ── serve ─────────────────────────────────────────────────────────────────
    serve_p = sub.add_parser("serve", help="Start the kerno HTTP server")
    serve_p.add_argument(
        "--host",
        default = "0.0.0.0",
        help    = "Server host (default: 0.0.0.0)",
    )
    serve_p.add_argument(
        "--port", "-p",
        type    = int,
        default = 8000,
        help    = "Server port (default: 8000)",
    )
    serve_p.add_argument(
        "--model", "-m",
        default = None,
        help    = "LLM model name",
    )
    serve_p.add_argument(
        "--provider",
        choices = ["anthropic", "openai"],
        default = "anthropic",
        help    = "LLM provider",
    )
    serve_p.add_argument(
        "--pool",
        type    = int,
        default = 3,
        help    = "Kernel pool size (default: 3)",
    )

    # ── bench ─────────────────────────────────────────────────────────────────
    bench_p = sub.add_parser("bench", help="Run the benchmark suite")
    bench_p.add_argument(
        "--suite",
        default = None,
        help    = "Path to benchmark suite JSON (default: standard suite)",
    )
    bench_p.add_argument(
        "--model", "-m",
        default = None,
        help    = "LLM model name",
    )
    bench_p.add_argument(
        "--provider",
        choices = ["anthropic", "openai"],
        default = "anthropic",
        help    = "LLM provider",
    )
    bench_p.add_argument(
        "--output", "-o",
        default = None,
        help    = "Save report to JSON file",
    )

    # ── Parse ─────────────────────────────────────────────────────────────────
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    # Load config
    config_path = args.config or ".kerno/config.json"
    config      = load_config(config_path)

    # Dispatch
    handlers = {
        "run":     cmd_run,
        "session": cmd_session,
        "memory":  cmd_memory,
        "config":  cmd_config,
        "doctor":  cmd_doctor,
        "metrics": cmd_metrics,
        "repl":    cmd_repl,
        "serve":   cmd_serve,
        "bench":   cmd_bench,
    }

    handler = handlers.get(args.command)
    if handler is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1

    return handler(args, config) or 0


# ── Command Handlers ──────────────────────────────────────────────────────────

def cmd_run(args, config) -> int:
    """Execute: kerno run <task>"""
    from kerno.config  import KernoConfig
    from kerno.runner  import run_with_config

    # Override config with CLI args
    if args.max_cells:
        config.kernel.max_cells = args.max_cells
    if args.verbose:
        config.output.verbose = True
    if args.save_notebook:
        config.output.save_notebook = True
    if args.notebook_dir:
        config.output.notebook_dir = args.notebook_dir
    if args.memory:
        config.memory.enabled = True
    if args.security != "none":
        config.security.profile = args.security

    # Build LLM
    llm = build_llm(
        provider = args.provider,
        model    = args.model or config.llm.model,
        config   = config,
    )

    if llm is None:
        print("❌ Could not build LLM. Check your API key.", file=sys.stderr)
        return 1

    print(f"kerno run — {args.loop} loop")
    print(f"Task: {args.task[:80]}")
    print("─" * 56)

    result = run_with_config(
        task        = args.task,
        llm         = llm,
        config      = config,
        loop        = args.loop,
        skills_path = args.skills,
    )

    # Summary output
    status_icons = {
        "COMPLETE":        "✅",
        "MAX_CELLS":       "⏱️",
        "INTERRUPTED":     "⛔",
        "KERNEL_DIED":     "💀",
        "ERROR_UNHANDLED": "❌",
    }
    icon = status_icons.get(result.status.name, "❓")

    print("\n" + "─" * 56)
    print(f"{icon} {result.status.name}")
    print(f"   Cells:     {result.cells_executed}")
    print(f"   Errors:    {result.error_count} ({result.recovery_count} recovered)")
    print(f"   Duration:  {result.duration:.1f}s")

    if result.summary:
        print(f"   Summary:   {result.summary[:200]}")

    return 0 if result.status.name == "COMPLETE" else 1


def cmd_session(args, config) -> int:
    """Execute: kerno session [list|show]"""
    cmd = getattr(args, "session_cmd", None)

    if cmd == "list" or cmd is None:
        return session_list(args)
    elif cmd == "show":
        return session_show(args)
    else:
        print("Usage: kerno session [list|show]")
        return 1


def session_list(args) -> int:
    sessions_dir = Path(getattr(args, "dir", "sessions"))
    limit        = getattr(args, "limit", 10)

    if not sessions_dir.exists():
        print(f"No sessions directory at: {sessions_dir}")
        return 0

    notebooks = sorted(
        sessions_dir.glob("*.ipynb"),
        key     = lambda p: p.stat().st_mtime,
        reverse = True,
    )[:limit]

    if not notebooks:
        print("No sessions found.")
        return 0

    print(f"Sessions in {sessions_dir}/  ({len(notebooks)} shown)")
    print("─" * 70)

    for nb_path in notebooks:
        try:
            import nbformat
            with open(nb_path) as f:
                nb = nbformat.read(f, as_version=4)

            meta     = nb.metadata.get("kerno", {})
            task     = meta.get("task", "unknown")[:50]
            started  = meta.get("started_at", "")[:16]
            n_cells  = len([c for c in nb.cells if c.cell_type == "code"])
            n_errors = sum(
                1 for c in nb.cells
                if c.cell_type == "code"
                and any(o.get("output_type") == "error" for o in c.get("outputs", []))
            )

            print(f"  {nb_path.name}")
            print(f"    Task:    {task}")
            print(f"    Started: {started}   Cells: {n_cells}   Errors: {n_errors}")
        except Exception:
            print(f"  {nb_path.name}  (could not parse)")

    return 0


def session_show(args) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    try:
        import nbformat
        with open(path) as f:
            nb = nbformat.read(f, as_version=4)

        meta = nb.metadata.get("kerno", {})
        print(f"Session: {path.name}")
        print(f"Task:    {meta.get('task', 'unknown')}")
        print(f"Started: {meta.get('started_at', 'unknown')}")
        print("─" * 56)

        for i, cell in enumerate(nb.cells):
            if cell.cell_type == "markdown":
                source = cell.source[:100].replace("\n", " ")
                print(f"  [md] {source}")
            elif cell.cell_type == "code":
                source  = cell.source[:80].replace("\n", " ")
                n_out   = len(cell.get("outputs", []))
                had_err = any(
                    o.get("output_type") == "error"
                    for o in cell.get("outputs", [])
                )
                icon = "✗" if had_err else "→"
                print(f"  [py] {icon} {source}  ({n_out} outputs)")

    except Exception as e:
        print(f"Error reading notebook: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_memory(args, config) -> int:
    """Execute: kerno memory [list|search|clear]"""
    cmd = getattr(args, "memory_cmd", None)

    if cmd == "list" or cmd is None:
        return memory_list(args)
    elif cmd == "search":
        return memory_search(args)
    elif cmd == "clear":
        return memory_clear(args)
    else:
        print("Usage: kerno memory [list|search|clear]")
        return 1


def memory_list(args) -> int:
    from kerno.memory.simple import SimpleMemoryStore

    path  = getattr(args, "path", ".kerno/memory.json")
    kind  = getattr(args, "kind", None)
    limit = getattr(args, "limit", 20)

    store   = SimpleMemoryStore(persist_path=path)
    entries = store.list(kind=kind, limit=limit)

    if not entries:
        print("No memories stored.")
        return 0

    print(f"Memory store: {path}  ({len(entries)} entries shown)")
    print("─" * 70)

    for entry in entries:
        import datetime
        ts      = datetime.datetime.fromtimestamp(entry.created_at).strftime("%Y-%m-%d %H:%M")
        preview = entry.content[:80].replace("\n", " ")
        print(f"  [{entry.kind:8s}] {ts}  {preview}")

    return 0


def memory_search(args) -> int:
    from kerno.memory.simple import SimpleMemoryStore

    store   = SimpleMemoryStore(persist_path=args.path)
    results = store.retrieve(args.query, k=args.k)

    if not results:
        print(f"No results for: {args.query}")
        return 0

    print(f"Search: '{args.query}'  ({len(results)} results)")
    print("─" * 70)

    for entry in results:
        print(f"  [{entry.kind}] score={entry.score:.3f}")
        print(f"    {entry.content[:120]}")
        print()

    return 0


def memory_clear(args) -> int:
    confirm = getattr(args, "confirm", False)
    path    = Path(getattr(args, "path", ".kerno/memory.json"))

    if not confirm:
        print(f"This will delete all memories at: {path}")
        print("Add --confirm to proceed.")
        return 0

    if path.exists():
        path.unlink()
        print(f"✓ Cleared memory store: {path}")
    else:
        print(f"Memory store not found: {path}")

    return 0


def cmd_config(args, config) -> int:
    """Execute: kerno config [show|init]"""
    cmd = getattr(args, "config_cmd", None)

    if cmd == "show" or cmd is None:
        fmt = getattr(args, "format", "text")
        if fmt == "json":
            print(json.dumps(config.to_dict(), indent=2))
        else:
            config.display()
        return 0

    elif cmd == "init":
        from kerno.config import KernoConfig

        profile = getattr(args, "profile", "default")
        factory = {
            "default":     KernoConfig.default,
            "development": KernoConfig.for_development,
            "production":  KernoConfig.for_production,
        }.get(profile, KernoConfig.default)

        cfg  = factory()
        path = getattr(args, "output", ".kerno/config.json")
        cfg.save(path)
        print(f"✓ Config written to: {path}  (profile: {profile})")
        return 0

    print("Usage: kerno config [show|init]")
    return 1


def cmd_doctor(args, config) -> int:
    """Execute: kerno doctor — environment diagnostic"""
    print("kerno doctor — environment check")
    print("─" * 56)

    checks = [
        ("Python version",       check_python_version),
        ("jupyter_client",       lambda: check_import("jupyter_client")),
        ("ipykernel",            lambda: check_import("ipykernel")),
        ("nbformat",             lambda: check_import("nbformat")),
        ("pandas",               lambda: check_import("pandas")),
        ("numpy",                lambda: check_import("numpy")),
        ("matplotlib",           lambda: check_import("matplotlib")),
        ("sklearn",              lambda: check_import("sklearn")),
        ("Kernel starts",        check_kernel_starts),
        ("API key (Anthropic)",  lambda: check_env("ANTHROPIC_API_KEY")),
        ("API key (OpenAI)",     lambda: check_env("OPENAI_API_KEY")),
        (".kerno/ directory",    lambda: check_dir(".kerno")),
    ]

    all_ok  = True
    for label, check_fn in checks:
        ok, detail = check_fn()
        icon       = "✓" if ok else "✗"
        line       = f"  {icon}  {label:<30}"
        if detail:
            line += f"  {detail}"
        print(line)
        if not ok and label not in ("API key (Anthropic)", "API key (OpenAI)"):
            all_ok = False

    print("─" * 56)
    if all_ok:
        print("✅ Environment looks good. Ready to run.")
    else:
        print("⚠️  Some checks failed. See above for details.")

    return 0 if all_ok else 1


def cmd_metrics(args, config) -> int:
    """Execute: kerno metrics — show current metrics"""
    metrics_path = Path(config.telemetry.metrics_path)

    if not metrics_path.exists():
        print("No metrics data found. Run some tasks first.")
        return 0

    # Read the last N lines and compute a summary
    lines = metrics_path.read_text().strip().split("\n")
    lines = [l for l in lines if l.strip()]

    if not lines:
        print("Metrics file is empty.")
        return 0

    # Count by metric name
    from collections import defaultdict, Counter
    counts:    Counter         = Counter()
    histos:    dict            = defaultdict(list)
    gauges:    dict            = {}

    for line in lines[-1000:]:   # Last 1000 records
        try:
            record = json.loads(line)
            name   = record.get("name", "")
            kind   = record.get("kind", "")
            value  = record.get("value", 0)

            if kind == "counter":
                counts[name] += value
            elif kind == "histogram":
                histos[name].append(value)
            elif kind == "gauge":
                gauges[name] = value
        except json.JSONDecodeError:
            pass

    print(f"Metrics summary  (last {min(len(lines), 1000)} records)")
    print("─" * 60)

    if counts:
        print("Counters:")
        for name, total in sorted(counts.items()):
            print(f"  {name:<40} {total:.0f}")

    if gauges:
        print("Gauges:")
        for name, value in sorted(gauges.items()):
            print(f"  {name:<40} {value:.2f}")

    if histos:
        print("Histograms (mean / p95):")
        for name, values in sorted(histos.items()):
            mean = sum(values) / len(values)
            p95  = sorted(values)[int(0.95 * len(values))]
            print(f"  {name:<40} mean={mean:.1f}  p95={p95:.1f}")

    return 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config(path: str):
    from kerno.config import KernoConfig
    p = Path(path)
    if p.exists():
        try:
            return KernoConfig.from_file(str(p))
        except Exception:
            pass
    return KernoConfig.from_env()


def build_llm(provider: str, model: str, config):
    """Build an LLM callable from provider + model."""
    if provider == "anthropic":
        try:
            import anthropic
            client = anthropic.Anthropic()
            from kerno.types import Message

            def llm(messages: list[Message]) -> str:
                response = client.messages.create(
                    model      = model,
                    max_tokens = config.llm.max_tokens,
                    system     = messages[0].content if messages else "",
                    messages   = [
                        {"role": m.role, "content": m.content}
                        for m in messages[1:]
                    ],
                )
                return response.content[0].text

            return llm
        except (ImportError, Exception):
            return None

    elif provider == "openai":
        try:
            import openai
            client = openai.OpenAI()
            from kerno.types import Message

            def llm(messages: list[Message]) -> str:
                response = client.chat.completions.create(
                    model    = model,
                    messages = [
                        {"role": m.role, "content": m.content}
                        for m in messages
                    ],
                )
                return response.choices[0].message.content

            return llm
        except (ImportError, Exception):
            return None

    return None


def check_python_version() -> tuple[bool, str]:
    import sys
    v   = sys.version_info
    ok  = v >= (3, 11)
    msg = f"Python {v.major}.{v.minor}.{v.micro}"
    return ok, msg


def check_import(module: str) -> tuple[bool, str]:
    try:
        import importlib
        m = importlib.import_module(module)
        v = getattr(m, "__version__", "")
        return True, v
    except ImportError:
        return False, "not installed  (pip install " + module + ")"


def check_kernel_starts() -> tuple[bool, str]:
    try:
        import jupyter_client
        km = jupyter_client.KernelManager(kernel_name="python3")
        km.start_kernel()
        km.shutdown_kernel(now=True)
        return True, "ok"
    except Exception as e:
        return False, str(e)[:60]


def check_env(key: str) -> tuple[bool, str]:
    import os
    val = os.environ.get(key, "")
    if val:
        return True, f"set ({key[:4]}...)"
    return False, "not set"


def check_dir(path: str) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        p.mkdir(parents=True)
        return True, "created"
    return True, "exists"


# ── New commands: repl, serve, bench ──────────────────────────────────────────

def cmd_repl(args, config) -> int:
    """Execute: kerno repl"""
    from kerno.dev.repl import KernoREPL

    llm = build_llm(
        provider = args.provider,
        model    = args.model or config.llm.model,
        config   = config,
    )
    if llm is None:
        print("❌ Could not build LLM. Check your API key.", file=sys.stderr)
        return 1

    repl = KernoREPL(llm=llm, loop=args.loop, verbose=True)
    repl.start()
    return 0


def cmd_serve(args, config) -> int:
    """Execute: kerno serve"""
    from kerno.server.cli import serve

    model    = args.model or config.llm.model
    provider = args.provider
    host     = args.host
    port     = args.port
    pool     = args.pool

    serve(
        host        = host,
        port        = port,
        model       = model,
        provider    = provider,
        pool_size   = pool,
        memory_path = config.memory.persist_path,
    )
    return 0


def cmd_bench(args, config) -> int:
    """Execute: kerno bench"""
    from kerno.benchmark import BenchmarkRunner, BenchmarkSuite
    from kerno.benchmark.suite import standard_suite

    llm = build_llm(
        provider = args.provider,
        model    = args.model or config.llm.model,
        config   = config,
    )
    if llm is None:
        print("❌ No LLM available.", file=sys.stderr)
        return 1

    suite_path = args.suite
    suite      = (
        BenchmarkSuite.load(suite_path)
        if suite_path
        else standard_suite()
    )

    runner = BenchmarkRunner(llm=llm, verbose=True)
    report = runner.run(suite)

    print("\n" + report.table())
    print("\n" + report.summary())

    output = args.output
    if output:
        report.save(output)
        print("\n✓ Report saved → {}".format(output))

    return 0 if report.pass_rate >= 0.8 else 1
