// Test source: GNU AGPL v3, as licensed in the repository LICENSE.
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SystemDiagnostics } from '../../src/chrome/SystemDiagnostics';
import { useAuthStore } from '../../src/stores/authStore';
import { useModeStore } from '../../src/stores/modeStore';
declare global { interface Window { incidentProbeKey: string; } }
useAuthStore.setState({status:'logged-in',token:window.incidentProbeKey});
useModeStore.setState({mode:'live'});
const query=new QueryClient({defaultOptions:{queries:{retry:false}}});
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={query}><SystemDiagnostics /></QueryClientProvider>);
