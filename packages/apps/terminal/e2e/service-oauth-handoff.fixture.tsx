import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import ServiceConnectionSetup from '../src/components/help/ServiceConnectionSetup';
import {readConnectionCollection, type ServiceConnectionCollection} from '../src/services/serviceConnectionControls';
import {useAuthStore} from '../src/stores/authStore';
useAuthStore.setState({status:'logged-in',token:'synthetic-session',username:'synthetic',sessionGeneration:1});
function Fixture({initial}:{initial:ServiceConnectionCollection}) {
 const [snapshot,setSnapshot]=useState(initial);const [blocked,setBlocked]=useState(false);
 return <ServiceConnectionSetup snapshot={snapshot} unavailable={false} blocked={blocked} onBlocked={setBlocked} onChanged={setSnapshot} onRefresh={async()=>{setSnapshot(await readConnectionCollection());setBlocked(false);}}/>;
}
void readConnectionCollection().then(initial=>createRoot(document.getElementById('root')!).render(<Fixture initial={initial}/>));
