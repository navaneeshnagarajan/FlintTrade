import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { Github } from 'lucide-react';
import Image from 'next/image';

export function baseOptions(): BaseLayoutProps {
  return {
    githubUrl: 'https://github.com/navaneeshnagarajan/FlintTrade',
    nav: {
      title: (
        <span className="inline-flex items-center gap-2 font-semibold">
          <Image src="/flinttrade/logo.svg" alt="" width={24} height={24} />
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
      {
        type: 'icon',
        text: 'GitHub',
        label: 'GitHub repository',
        icon: <Github className="size-4" />,
        url: 'https://github.com/navaneeshnagarajan/FlintTrade',
        external: true,
      },
    ],
  };
}
