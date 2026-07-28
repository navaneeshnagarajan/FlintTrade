## Summary

<!-- 2-3 sentences describing what this PR does and why. -->

## Related issue

<!-- e.g., "Fixes #123" or "Refs #45". Skip if no linked issue. -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] Feature (non-breaking change that adds functionality)
- [ ] Documentation (no code changes)
- [ ] Refactor (no functional change)
- [ ] Test (adds or updates tests)
- [ ] Chore (build, CI, tooling)

## Persona affected

- [ ] Trader
- [ ] Investor
- [ ] Beginner
- [ ] Developer
- [ ] N/A (purely internal)

## Testing done

<!-- Commands you ran and their results. One per line — Windows PowerShell has
     no `&&`. e.g.: -->
```
python scripts/ft.py test                   # 9,089 passed
pnpm --filter @flinttrade/terminal test     # 2,973 passed
python scripts/ft.py lint                   # clean
```

## Screenshots

<!-- For UI changes — before/after. -->

## Checklist

- [ ] Tests added or updated (and they pass locally)
- [ ] Docs updated (`docs/`, README, or CHANGELOG entry)
- [ ] `ruff check` clean
- [ ] `tsc --noEmit` clean (if frontend code touched)
- [ ] Conventional commit title (`feat(pkg):`, `fix(pkg):`, `docs:`, etc.)
- [ ] No personal info in commit messages (no IPs, hostnames, broker accounts, fund amounts, order IDs)
- [ ] No new dependencies added without justification in the description
- [ ] British English in docstrings, comments, and user-visible strings
