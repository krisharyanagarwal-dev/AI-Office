import pathlib

p = pathlib.Path("scripts/check_llm_success_rate.py")
s = p.read_text(encoding="utf-8")

s = s.replace(
    'def scan(window_s, limit_bytes):\n    now = time.time()',
    'def scan(window_s, limit_bytes, pattern="/tmp/*_manager.log"):\n    now = time.time()',
    1,
)
s = s.replace(
    '    for path in glob.glob("/tmp/*_manager.log"):',
    '    for path in glob.glob(pattern):',
    1,
)
s = s.replace(
    '    ap.add_argument("--limit-bytes", type=int, default=25000,\n'
    '                    help="bytes of log tail read per agent")',
    '    ap.add_argument("--limit-bytes", type=int, default=25000,\n'
    '                    help="bytes of log tail read per agent")\n'
    '    ap.add_argument("--pattern", default="/tmp/*_manager.log",\n'
    '                    help="log glob; overridable so tests can drive it")',
    1,
)
s = s.replace(
    '    m = scan(args.window, args.limit_bytes)',
    '    m = scan(args.window, args.limit_bytes, args.pattern)',
    1,
)

p.write_text(s, encoding="utf-8")
print("  added --pattern seam for testability")
