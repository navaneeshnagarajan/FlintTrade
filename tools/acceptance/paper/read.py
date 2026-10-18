"""Real disposable read authority with narrowly inert external SDK responses."""

import sys
from paths import artifacts
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import secrets
import threading
import time
from zoneinfo import ZoneInfo

class SDK:
    def __init__(self, bootstrap, role):
        self.bootstrap, self.role = bootstrap, role
        self.closed = False
        self.counts = {}

    def invoke(self, name, args, kwargs, response):
        self.counts[name] = self.counts.get(name, 0) + 1
        if self.closed or kwargs or self.counts[name] > 100:
            self.bootstrap.desk.failures.append(['sdk-shape-or-limit',self.role,name])
            raise RuntimeError('SDK fixture refused')
        self.bootstrap.rows.append({'role':self.role,'method':name,'args':args,'kwargs':kwargs,
                                    'response':response,'thread':threading.current_thread().name,
                                    'monotonic_ns':time.monotonic_ns(),
                                    'observed_at':datetime.now(timezone.utc).isoformat()})
        return response

    def quote_data(self, *args, **kwargs):
        if self.role != 'Quotes' or args != ({'NSE_EQ':[2885]},) or kwargs:
            return self.unexpected('quote_data', args, kwargs)
        price = self.bootstrap.price
        data = {'last_price':price, 'ohlc':{'open':122.0,'high':130.0,'low':115.0,'close':122.5},
                'volume':1000, 'depth':{'buy':[{'price':price-.1,'quantity':10,'orders':1}],
                                       'sell':[{'price':price+.1,'quantity':10,'orders':1}]}}
        if self.bootstrap.variant == 'bad-quote': data['last_price'] = -1
        if self.bootstrap.variant == 'bad-instrument':
            response={'status':'success','data':{'NSE_EQ':{'9999':data}}}
        else:
            response={'status':'success','data':{'NSE_EQ':{'2885':data}}}
        return self.invoke('quote_data', args, kwargs, response)

    def intraday_minute_data(self, *args, **kwargs):
        today=datetime.now(ZoneInfo('Asia/Kolkata')).date()
        expected=('2885','NSE_EQ','EQUITY',(today-timedelta(days=3)).isoformat(),today.isoformat(),5)
        if self.role != 'History' or args != expected or kwargs:
            return self.unexpected('intraday_minute_data',args,kwargs)
        end=int(time.time()//300)*300-300
        prices=[120.0+i*.05 for i in range(60)]
        times=[end-(59-i)*300 for i in range(60)]
        if self.bootstrap.variant == 'bad-history': times[-1] = int(time.time())+3600
        response={'status':'success','data':{'timestamp':times,'open':prices,
                 'high':[p+1 for p in prices],'low':[p-1 for p in prices],
                 'close':[p+.1 for p in prices],'volume':[100]*60}}
        return self.invoke('intraday_minute_data',args,kwargs,response)

    def get_fund_limits(self, *args, **kwargs):
        if self.role != 'Execution' or args or kwargs:
            return self.unexpected('get_fund_limits',args,kwargs)
        return self.invoke('get_fund_limits',args,kwargs,{'status':'success','data':{'availabelBalance':1000.0}})

    def unexpected(self, name, args, kwargs):
        self.bootstrap.desk.failures.append(['sdk-unregistered',self.role,name])
        raise RuntimeError('Unregistered SDK operation: '+name)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        def refused(*args, **kwargs):
            return self.unexpected(name,args,kwargs)
        return refused

    def close(self):
        self.closed=True

class Bootstrap:
    def __init__(self, desk, variant='positive'):
        from flinttrade_core.broker_identity import BrokerSelector
        from flinttrade_core.workspace_migrations import compare_and_swap_workspace, read_workspace_snapshot
        from flinttrade_gateway.credentials import CredentialStore
        from flinttrade_gateway.registry import create_owned_registry
        from flinttrade_gateway.brokers._base import Session
        from flinttrade_data.audit_logger import AuditLogger
        self.desk, self.variant = desk, variant
        self.price=123.5
        self.rows=[]
        self.published=[]
        self.selectors=[]
        self.clients=[]
        self.audit=AuditLogger()
        def update(config):
            block=config['brokers']
            block['registered']=['dhan:Quotes','dhan:History','dhan:Execution']
            block['account_acls']={'dhan':{role:['other-subject' if variant=='wrong-acl' else 'synthetic-operator'] for role in ('Quotes','History','Execution')}}
            block['execution']={'default':'dhan:Execution'}
            block['data'].update(quote='dhan:Quotes',ticks='dhan:Quotes',historical='dhan:History',option_chains='dhan:Quotes')
        current=read_workspace_snapshot(desk.workspace)
        compare_and_swap_workspace(desk.workspace,current.version,update)
        self.store=CredentialStore(desk.workspace/'r84-vault.db',secrets.token_urlsafe(40))
        self.registry,self.publication=create_owned_registry()
        for role in ('Quotes','History','Execution'):
            selector=BrokerSelector('dhan',role)
            self.selectors.append(selector)
            state=self.store.selector_state(selector)
            self.store.put_credentials(selector,'dhan','Synthetic '+role,{'client_id':secrets.token_hex(8),'access_token':secrets.token_urlsafe(32)},expected=state.version)
            sdk=SDK(self,role); self.clients.append(sdk)
            session=Session(secrets.token_urlsafe(32),time.time()+600,account_id=role,adapter_id='dhan',extra={'client':sdk})
            receipt=self.publication.prepare_session_candidate(selector,session,
                expected_registry=self.registry.snapshot_selector(selector),authority=self.authority(selector),
                broker='dhan',label='Synthetic '+role,client=sdk)
            result=self.publication.publish_prepared_candidate(receipt,current_authority=self.authority(selector))
            self.published.append(asdict(result))
        (artifacts() / 'read-publication.json').write_text(json.dumps({'variant':variant,'published':self.published},indent=2,default=str))

    def authority(self, selector):
        from flinttrade_core.workspace_migrations import broker_workspace_version,read_workspace_snapshot
        from flinttrade_gateway.registry import ManagedSessionAuthority
        state=self.store.selector_state(selector)
        workspace=read_workspace_snapshot(self.desk.workspace)
        return ManagedSessionAuthority(state.version,workspace.version,broker_workspace_version(workspace))

    def inputs(self):
        return {'registry':self.registry,'registry_publication_owner':self.publication,'credential_store':self.store,
                'audit':self.audit}

    def close(self):
        # Borrowed roots outlive the normal factory's request/read dependency drain.
        retired=[]
        for selector in self.selectors:
            version=self.registry.snapshot_selector(selector)
            if not version.present:
                continue
            result=self.publication.remove_session_for_exact(selector,expected_registry=version)
            if result.retired is not None:
                payload=self.publication.claim_retired_candidate(result.retired)
                payload.client.close()
                self.publication.release_retired_candidate(payload)
            retired.append(asdict(self.registry.snapshot_selector(selector)))
        self.store.close()
        self.audit.close()
        assert all(client.closed for client in self.clients)
        (artifacts() / 'sdk.json').write_text(json.dumps({'calls':self.rows,'retired':retired,
            'closed':[c.closed for c in self.clients]},indent=2,default=str))
