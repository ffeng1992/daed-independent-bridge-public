"""Compatibility alias for the verified payload-based management planner."""
def main(argv=None):
    from scripts.release_management_plan import main as entry
    return entry(argv)
if __name__ == '__main__':
    raise SystemExit(main())
