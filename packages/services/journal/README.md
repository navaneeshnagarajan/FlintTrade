# flinttrade-journal

Trade journal service package for FlintTrade.

This package owns journal entries, trade logging, execution-quality analytics, and P&L tracking that were split out of `flinttrade-data` during the v0.6.0 restructure.

Run focused tests with:

```bash
python -m pytest packages/services/journal/tests -v --import-mode=importlib
```
