# Bug Tracking — single-writer-per-file

| File | Writer | Machine |
|---|---|---|
| live.md | Production server | ubuntu-i3-9350KF-RX6600XT |
| in_progress.md | Build machine | nitro-i5-13420H-RTX5050 |
| in_testing.md | Test machine | mac-m4-16gb |
| resolved.md | Production server | ubuntu-i3-9350KF-RX6600XT |

Format: `### BUG-{number} | {severity} | {package} | {date}`
Lifecycle: live → in_progress → in_testing → resolved
