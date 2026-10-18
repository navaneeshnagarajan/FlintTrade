// Private test compatibility overlay. Never changes application geometry or hides Reticle.
export async function ensureReticleChatMinimised(page:any,info:any,name:string){
 const collapsed=page.getByRole('button',{name:'Open agent chat',exact:true});
 if(!await collapsed.isVisible()){
  const expanded=page.getByRole('button',{name:'Minimise chat',exact:true});
  await expanded.waitFor({state:'visible'});
  await page.screenshot({path:info.outputPath(name+'.expanded-presenter.png')});
  await expanded.click();
  await collapsed.waitFor({state:'visible'});
 }
 const presenter=await collapsed.boundingBox();
 if(!presenter)throw Error('Reticle presenter target missing');
 return presenter;
}
