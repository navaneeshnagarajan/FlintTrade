import type { Metadata } from 'next';
import { permanentRedirect } from 'next/navigation';

export const metadata: Metadata = {
  title: 'Demo (example data)',
  description:
    'Open Demo (example data): the FlintTrade terminal with sample data.',
};

export default function ExplorePage() {
  permanentRedirect('/demo-app/welcome');
}
