import fs from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./observed-registry";
import { seedExploreDemoSession } from "./helpers";
import { registerExampleDeskReads } from "./visual/desk-mocks";
import { installDeterminism, settle } from "./visual/support";
import type { Locator, Page } from "@playwright/test";

test.use({ viewport: { width:1440, height:900 } });
test.beforeEach(async ({page,syntheticApi}) => {
  await installDeterminism(page); await seedExploreDemoSession(page); registerExampleDeskReads(syntheticApi);
  await page.goto('/home');
  await settle(page, async () => (await Promise.all([
    page.getByRole('tabpanel',{name:'Watchlist',exact:true}).getByRole('button',{name:'Add symbol',exact:true}).isVisible(),
    page.getByRole('tabpanel',{name:'Chart',exact:true}).getByRole('button',{name:'Open chart display settings',exact:true}).isVisible(),
    page.getByRole('region',{name:'Positions book',exact:true}).isVisible(),
  ])).every(Boolean));
});

async function painted(target:Locator) {
  return target.evaluate(el => {
    const r=el.getBoundingClientRect();
    return { box:{x:r.x,y:r.y,width:r.width,height:r.height}, viewport:r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
      hits:[r.x+1,r.x+r.width/2,r.right-1].map(x=>{const h=document.elementFromPoint(x,r.y+r.height/2);return h===el||el.contains(h);}) };
  });
}
async function moveSplitter(page:Page,x:number) {
  const boxes=await page.locator('.flexlayout__splitter').evaluateAll(els=>els.map(el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};}));
  const split=boxes.find(r=>r.w<15&&r.h>300); if(!split)throw Error('Missing vertical splitter');
  await page.mouse.move(split.x+split.w/2,split.y+split.h/2);await page.mouse.down();
  await page.mouse.move(x,split.y+split.h/2,{steps:20});await page.mouse.up();
}

test('watchlist context menu transfers focus navigates and returns on Escape',async({page},info)=>{
  const w=page.getByRole('tabpanel',{name:'Watchlist',exact:true}), tab=w.getByRole('tab',{name:'Watchlist 1',exact:true});
  await tab.focus();await page.keyboard.press('Shift+F10');
  const menu=w.getByRole('menu',{name:'Tab actions for Watchlist 1'});
  await expect(menu).toBeVisible();
  const open=await menu.getByRole('menuitem',{name:'Rename',exact:true}).evaluate(el=>document.activeElement===el);
  await page.keyboard.press('ArrowDown');
  const down=await menu.getByRole('menuitem',{name:'Duplicate',exact:true}).evaluate(el=>document.activeElement===el);
  await page.keyboard.press('Escape');
  fs.writeFileSync(info.outputPath('keyboard-menu.json'),JSON.stringify({open,down,closed:!await menu.isVisible()},null,2));
  expect.soft(open).toBe(true);expect.soft(down).toBe(true);await expect.soft(menu).toHaveCount(0);await expect.soft(tab).toBeFocused();
  if(!open)return;
  await page.keyboard.press('ContextMenu');await expect(menu.getByRole('menuitem',{name:'Rename',exact:true})).toBeFocused();
  await page.keyboard.press('End');await expect(menu.getByRole('menuitem',{name:'Duplicate',exact:true})).toBeFocused();
  await page.keyboard.press('Home');await page.keyboard.press('Enter');
  const editor=w.getByRole('textbox',{name:'Rename Watchlist 1'});await expect(editor).toBeFocused();
  await editor.fill('Research');await page.keyboard.press('Enter');await expect(w.getByRole('tab',{name:'Research',exact:true})).toBeFocused();
  await w.getByRole('tab',{name:'Research',exact:true}).click({button:'right'});
  await w.getByRole('menuitem',{name:'Duplicate',exact:true}).click();
  const copy=w.getByRole('tab',{name:'Research (copy)',exact:true});await expect(copy).toHaveAttribute('aria-selected','true');
  await copy.click({button:'right'});await w.getByRole('menuitem',{name:'Delete',exact:true}).click();
  await expect(copy).toHaveCount(0);await expect(w.getByRole('tab',{name:'Research',exact:true})).toHaveAttribute('aria-selected','true');
  await page.screenshot({path:info.outputPath('keyboard-menu.png')});
});

for (const key of ['Enter', 'Space']) {
  for (const action of ['Duplicate', 'Delete']) {
    test(`keyboard ${key} ${action} restores surviving watchlist focus`, async ({page}, info) => {
      const w = page.getByRole('tabpanel', {name: 'Watchlist', exact: true});
      const original = w.getByRole('tab', {name: 'Watchlist 1', exact: true});
      if (action === 'Delete') await w.getByRole('button', {name: 'Add watchlist tab'}).click();
      const invoker = action === 'Delete' ? w.getByRole('tab', {name: 'Watchlist 2', exact: true}) : original;
      await invoker.focus();
      await page.keyboard.press('ContextMenu');
      const menu = w.getByRole('menu');
      await expect(menu.getByRole('menuitem', {name: 'Rename', exact: true})).toBeFocused();
      // Up wraps from first to last, Down wraps back; then navigate to the action.
      await page.keyboard.press('ArrowUp');
      await expect(menu.getByRole('menuitem', {name: action === 'Delete' ? 'Delete' : 'Duplicate', exact: true})).toBeFocused();
      await page.keyboard.press('ArrowDown');
      await expect(menu.getByRole('menuitem', {name: 'Rename', exact: true})).toBeFocused();
      await page.keyboard.press(action === 'Delete' ? 'End' : 'ArrowDown');
      await expect(menu.getByRole('menuitem', {name: action, exact: true})).toBeFocused();
      await page.keyboard.press(key);
      const survivor = action === 'Duplicate' ? w.getByRole('tab', {name: 'Watchlist 1 (copy)', exact: true}) : original;
      await expect(menu).toHaveCount(0);
      await expect(survivor).toHaveAttribute('aria-selected', 'true');
      if (action === 'Delete') await expect(invoker).toHaveCount(0);
      await expect(survivor).toBeFocused();
      const paint = await painted(survivor);
      expect(paint.viewport && paint.hits.every(Boolean)).toBe(true);
      const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('flinttrade:watchlists') ?? 'null'));
      expect(stored.map((tab: {name: string}) => tab.name)).toEqual(action === 'Duplicate' ? ['Watchlist 1', 'Watchlist 1 (copy)'] : ['Watchlist 1']);
      if (action === 'Duplicate') expect(stored[1].symbols).toEqual(stored[0].symbols);
      fs.writeFileSync(info.outputPath('action-focus.json'), JSON.stringify({key, action, paint, stored}, null, 2));
      await page.screenshot({path: info.outputPath('action-focus.png')});
    });
  }
}

test('rename replaces its original slot and stays usable with overflowing tabs',async({page},info)=>{
  const w=page.getByRole('tabpanel',{name:'Watchlist',exact:true}), add=w.getByRole('button',{name:'Add watchlist tab'});
  await add.click();
  const first=w.getByRole('tab',{name:'Watchlist 1',exact:true});await first.click();
  const before=await first.boundingBox();if(!before)throw Error('Missing tab');
  await first.click({button:'right'});await w.getByRole('menuitem',{name:'Rename',exact:true}).click();
  const editor=w.getByRole('textbox',{name:'Rename Watchlist 1'});await expect(editor).toBeFocused();
  const value=await painted(editor);fs.writeFileSync(info.outputPath('editing.json'),JSON.stringify({before,value},null,2));
  expect(value.box).toEqual({x:before.x,y:before.y+(before.height-16)/2,width:96,height:16});
  expect(await editor.evaluate(el=>el.closest('[role="tablist"]'))).toBeNull();
  expect(value.viewport&&value.hits.every(Boolean)).toBe(true);
  await editor.fill('Cancelled');await page.keyboard.press('Escape');await expect(first).toBeFocused();await expect(first).toHaveText('Watchlist 1');
  for(let i=0;i<3;i++)await add.click();
  await page.clock.resume();await moveSplitter(page,250);
  const tabScroller=w.getByRole('tablist',{name:'Watchlist tabs'}).locator('..');
  expect(await tabScroller.evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(true);
  const last=w.getByRole('tab',{name:'Watchlist 5',exact:true});await last.focus();
  await page.keyboard.press('Shift+F10');await page.keyboard.press('Enter');
  const lastEditor=w.getByRole('textbox',{name:'Rename Watchlist 5'});await expect(lastEditor).toBeFocused();
  const overflow=await painted(lastEditor);expect(overflow.viewport&&overflow.hits.every(Boolean)).toBe(true);
  expect(await tabScroller.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
  await page.screenshot({path:info.outputPath('overflow-editor.png')});
  await lastEditor.fill('Last');await page.keyboard.press('Enter');await expect(w.getByRole('tab',{name:'Last',exact:true})).toBeFocused();
});

test('dock channel controls share strip clipping and reveal on sequential focus',async({page},info)=>{
  await page.clock.resume();
  const positions=page.getByRole('tab',{name:'Positions',exact:true});
  const outer=page.locator('.flexlayout__tabset_tabbar_outer').filter({has:positions});
  const controls=outer.getByRole('button',{name:/Link channel/});
  await moveSplitter(page,1270);
  const clip=await outer.locator('.flexlayout__tabset_tabbar_inner').boundingBox();if(!clip)throw Error('Missing strip');
  const beyond=await controls.first().evaluate((el,right)=>{const r=el.getBoundingClientRect();const x=Math.max(right+1,r.x+1),h=document.elementFromPoint(x,r.y+r.height/2);return {x,right:r.right,self:h===el||el.contains(h)};},clip.x+clip.width);
  await page.screenshot({path:info.outputPath('partial-overflow.png')});
  expect.soft(beyond.self,'Channel must not paint/hit beyond the actual native strip').toBe(false);
  await moveSplitter(page,1320);await positions.focus();
  const evidence=[];
  for(let i=0;i<4;i++){
    await page.keyboard.press('Tab');
    const active=page.locator(':focus');
    if((await active.getAttribute('aria-label'))?.startsWith('Link channel')){
      const p=await painted(active);
      const index=await controls.evaluateAll(els=>els.indexOf(document.activeElement as HTMLElement));
      const slot=await outer.getByRole('tab').nth(index).locator('span.inline-flex.h-4.w-4').boundingBox();
      const strip=await outer.locator('.flexlayout__tabset_tabbar_inner').boundingBox();
      evidence.push({p,slot,strip});expect.soft(p.viewport&&p.hits.every(Boolean),'Native Tab must reveal the channel control').toBe(true);
      expect.soft(p.box,'Focus must reveal the original strip slot, not scroll an independent overlay').toEqual(slot);
      await page.screenshot({path:info.outputPath(`focus-${i}.png`)});
    }
  }
  fs.writeFileSync(info.outputPath('overflow.json'),JSON.stringify({clip,beyond,evidence},null,2));
  expect(evidence).toHaveLength(2);await expect(positions).toHaveAttribute('aria-selected','true');
  await moveSplitter(page,1000);await positions.focus();
  await page.screenshot({path:info.outputPath('resize-return.png')});
});

test('a single watchlist remains structurally accessible while its tab is renamed',async({page},info)=>{
  const w=page.getByRole('tabpanel',{name:'Watchlist',exact:true});
  await w.getByRole('tab',{name:'Watchlist 1',exact:true}).focus();
  await page.keyboard.press('ContextMenu');
  const rename=w.getByRole('menuitem',{name:'Rename',exact:true});await expect(rename).toBeFocused();
  const menuPaint=await painted(rename);expect(menuPaint.viewport&&menuPaint.hits.every(Boolean)).toBe(true);
  await page.screenshot({path:info.outputPath('menu-focus.png')});
  await page.keyboard.press('Enter');
  const editor=w.getByRole('textbox',{name:'Rename Watchlist 1'});await expect(editor).toBeFocused();
  await page.clock.resume();
  const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze();
  fs.writeFileSync(info.outputPath('editing-axe.json'),JSON.stringify(axe,null,2));
  await page.screenshot({path:info.outputPath('single-editor.png')});
  expect(axe.violations).toEqual([]);
  await page.keyboard.press('Escape');await expect(w.getByRole('tab',{name:'Watchlist 1',exact:true})).toBeFocused();
});
