import { LogoIcon } from '@flinttrade/design-system/brand';
import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';

export function baseOptions(): BaseLayoutProps {
  return {
    githubUrl: 'https://github.com/navaneeshnagarajan/FlintTrade',
    nav: {
      title: (
        <span className="inline-flex items-center gap-2 font-semibold">
          <LogoIcon size={20} aria-hidden="true" />
          FlintTrade
        </span>
      ),
      url: '/',
    },
    links: [
      { text: 'Docs', url: '/docs', active: 'nested-url' },
      { text: 'API', url: '/api-reference', active: 'url' },
      { text: 'MCP', url: '/mcp', active: 'url' },
      { text: 'Contribute', url: '/contribute', active: 'url' },
    ],
  };
}
