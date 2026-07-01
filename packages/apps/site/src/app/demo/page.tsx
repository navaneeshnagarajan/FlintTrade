import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

export const metadata: Metadata = {
  title: 'Sandbox Demo',
  description:
    'Open the FlintTrade terminal demo as a full-page app experience.',
};

export default function DemoPage() {
  redirect('/demo-app/welcome');
}
