# @flinttrade/site

Next.js + Fumadocs site for FlintTrade documentation, contribution flows, and MCP reference pages.

Run focused checks with:

```bash
cd packages/apps/site
npm run typecheck
npm run test
npm run build
```

`npm run build` intentionally runs `next build --webpack` for now. Next 16's
default Turbopack production build currently hangs with the Fumadocs content
pipeline in this workspace, while the Webpack builder completes and matches the
Vercel-compatible output path.
