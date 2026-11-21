import type { Metadata } from 'next';
import { permanentRedirect } from 'next/navigation';

export const metadata: Metadata = {
  title: 'Demo (example data)',
  description:
    'Open the FlintTrade terminal demo as a full-page app experience.',
};

export default function ExplorePage() {
  permanentRedirect('/demo-app/welcome');
}
