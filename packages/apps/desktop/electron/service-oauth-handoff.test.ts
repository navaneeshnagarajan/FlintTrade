import { expect, it, vi } from 'vitest';
import { hardenWebContents } from './hardening';
const origin = 'http://127.0.0.1:43127';
const launch = origin + '/v1/services/connections/oauth/launch?ticket=' + 'a'.repeat(43);
function opener(current = origin, selected: string|null = origin) {
 let open: (details:{url:string})=>{action:'deny'} = () => {throw new Error('not installed');};
 const external = vi.fn();
 hardenWebContents({closeDevTools(){},getURL:()=>current,on(){},setWindowOpenHandler(handler){open=handler;}}, {
  development:false,openExternal:external,originPolicy:{terminalOrigin:selected,splashUrl:'file:///splash'},
 });
 return {open,external};
}
it('launches the exact owned OAuth bootstrap only through the external browser',()=>{
 const {open,external}=opener();
 expect(open({url:launch})).toEqual({action:'deny'});
 expect(external).toHaveBeenCalledExactlyOnceWith(launch);
});
it.each([launch.replace(':43127',':43128'),launch.replace('127.0.0.1','localhost'),launch+'#x',launch+'&next=https://evil.invalid',launch.replace('/launch','/callback'),origin+'/settings'])('refuses an unscoped loopback popup %s',url=>{
 const {open,external}=opener();open({url});expect(external).not.toHaveBeenCalled();
});
it.each(['https://evil.invalid','file:///splash'])('refuses bootstrap from foreign renderer %s',current=>{
 const {open,external}=opener(current);open({url:launch});expect(external).not.toHaveBeenCalled();
});
it('retires the old port when the backend origin changes',()=>{
 const {open,external}=opener(origin,origin.replace(':43127',':43128'));open({url:launch});expect(external).not.toHaveBeenCalled();
});
