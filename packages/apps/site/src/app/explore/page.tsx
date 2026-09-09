import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

export const metadata: Metadata = {
  title: 'Explore demo',
  description:
    'Open the FlintTrade terminal demo as a full-page app experience.',
};

export default function ExplorePage() {
  redirect('/demo-app/welcome');
}
