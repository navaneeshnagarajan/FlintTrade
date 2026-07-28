import { installScriptRedirect } from '@/lib/install-script-routes';

export function GET(): Response {
  return installScriptRedirect('web-ps1');
}
