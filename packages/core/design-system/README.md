# @flinttrade/design-system

Shared FlintTrade design tokens and React primitives extracted from the terminal UI for v0.6.0.

Use it from app packages via the workspace alias:

```ts
import { Button, Card, cn } from "@flinttrade/design-system"
import "@flinttrade/design-system/tokens.css"
```

The package keeps CSS as side effects so Vite and Next.js preserve Tailwind v4 token and utility definitions.
