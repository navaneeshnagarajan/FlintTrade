# Bug Tracking — single-writer-per-file

| File | Writer | Machine |
|---|---|---|
| live.md | Production server | your-production-server |
| in_progress.md | Build machine | your-dev-machine |
| in_testing.md | Test machine | your-test-machine |
| resolved.md | Production server | your-production-server |

Format: `### BUG-{number} | {severity} | {package} | {date}`
Lifecycle: live → in_progress → in_testing → resolved
