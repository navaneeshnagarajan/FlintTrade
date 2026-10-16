import fs from "node:fs";
import { expect, type Page, type TestInfo, type Locator } from "@playwright/test";
import { settle } from "./visual/support";

async function paint(target: Locator) {
  await target.scrollIntoViewIfNeeded();
  const value = await target.evaluate(el => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return { name: el.getAttribute("aria-label") ?? el.textContent, box: { x:r.x, y:r.y, width:r.width, height:r.height }, viewport:r.left>=0 && r.top>=0 && r.right<=innerWidth && r.bottom<=innerHeight, hit:!!hit && (el===hit || el.contains(hit)) };
  });
  expect(value.viewport && value.hit, JSON.stringify(value)).toBe(true);
  return value;
}

export async function interactions(page: Page, info: TestInfo) {
  const evidence: Record<string, unknown> = {};
  const record = (key: string, value: unknown) => { evidence[key]=value; fs.writeFileSync(info.outputPath("interactions.json"),JSON.stringify(evidence,null,2)); };
  const watchlist = page.getByRole("tabpanel", { name:"Watchlist",exact:true });
  const list = watchlist.getByRole("list", { name:"Watchlist 1 symbols",exact:true });
  const tabs = watchlist.getByRole("tablist", { name:"Watchlist tabs",exact:true });
  const first = tabs.getByRole("tab", { name:"Watchlist 1",exact:true });
  const add = watchlist.getByRole("button", { name:"Add watchlist tab",exact:true });
  const dot = (name:string) => page.locator('.flexlayout__tabset_tabbar_outer').filter({has:page.getByRole("tab",{name,exact:true})}).getByRole("button",{name:/Link channel/});
  record("initialPaint", await Promise.all([paint(first),paint(add)]));
  expect(await add.evaluate(el=>el.closest('[role="tablist"]'))).toBeNull();
  await expect(watchlist.getByRole("group",{name:"Watchlist columns"})).toHaveText("SymbolSparklineLTP% change");
  await expect(list.getByRole("listitem")).toHaveCount(5);
  record("rowOrder",await list.getByRole("listitem").locator(':scope > button:first-child').evaluateAll(els=>els.map(el=>el.getAttribute('aria-label'))));
  expect(evidence["rowOrder"]).toEqual(["NIFTY","BANKNIFTY","SBIN","RELIANCE","HDFCBANK"]);
  await first.focus();await page.keyboard.press("Tab");await expect(add).toBeFocused();
  await page.keyboard.press("Shift+Tab");await expect(first).toBeFocused();
  await page.keyboard.press("Tab");await page.keyboard.press("Enter");
  const second=tabs.getByRole("tab",{name:"Watchlist 2",exact:true});
  await expect(second).toHaveAttribute("aria-selected","true");
  await first.focus();await page.keyboard.press("ArrowRight");await expect(second).toBeFocused();
  await page.keyboard.press("ArrowLeft");await expect(first).toBeFocused();
  await page.keyboard.press("Space");await expect(first).toHaveAttribute("aria-selected","true");
  await page.keyboard.press("Shift+F10");
  await expect(page.getByRole("menuitem",{name:"Rename",exact:true})).toBeFocused();
  await page.keyboard.press("Enter");
  const editor=watchlist.getByRole("textbox",{name:"Rename Watchlist 1",exact:true});
  await expect(editor).toBeFocused();
  expect(await editor.evaluate(el=>el.closest('[role="tablist"]'))).toBeNull();
  record("renamePaint",await paint(editor));
  await editor.fill("Cancelled");await page.keyboard.press("Escape");await expect(first).toBeFocused();await expect(first).toHaveText("Watchlist 1");
  await first.click({button:"right"});await page.getByRole("menuitem",{name:"Rename",exact:true}).click();
  await editor.fill("Research");await page.keyboard.press("Enter");
  const renamed=tabs.getByRole("tab",{name:"Research",exact:true});await expect(renamed).toBeFocused();
  await expect(watchlist.getByRole("tabpanel",{name:"Research",exact:true})).toBeVisible();
  record("watchlistKeyboard",{tab:true,shiftTab:true,arrowsFocusOnly:true,spaceSelection:true,enterAdd:true,renameCommitCancelAndFocus:true});

  const watchDot=dot("Watchlist"); const chartDot=dot("Chart");
  for(const control of [watchDot,chartDot]){
    expect(await control.evaluate(el=>el.closest('[role="tab"],[role="tablist"]'))).toBeNull();
    await control.focus();await page.keyboard.press("Shift+Tab");await page.keyboard.press("Tab");await expect(control).toBeFocused();
    await page.keyboard.press("Enter");await expect(control).toHaveAccessibleName("Link channel: Red — click to change");
    await page.keyboard.press("Space");await expect(control).toHaveAccessibleName("Link channel: Green — click to change");
    await page.keyboard.press("ArrowRight");await expect(control).toBeFocused();
  }
  await watchlist.getByRole("button",{name:"BANKNIFTY",exact:true}).focus();
  await page.keyboard.press("Enter");
  await settle(page,()=>page.getByRole("tabpanel",{name:"Chart",exact:true}).getByText("BANKNIFTY",{exact:true}).isVisible());
  record("channelPropagation",{chart:"BANKNIFTY",channel:"Green",nativeEnterAndSpace:true});
  const beforeDrag=await page.evaluate(()=>localStorage.getItem("flinttrade:app-layouts:v1:terminal"));
  const box=await watchDot.boundingBox();if(!box)throw new Error("Missing channel box");
  await page.mouse.move(box.x+8,box.y+8);await page.mouse.down();await page.mouse.move(box.x+80,box.y+50,{steps:8});await page.mouse.up();
  expect(await page.evaluate(()=>localStorage.getItem("flinttrade:app-layouts:v1:terminal"))).toBe(beforeDrag);
  // FlexLayout 0.11.1 exposes a context callback, not a built-in popup.
  // Exercise the application's real channel menu rather than inventing one.
  const links=page.getByTestId("instrument-links");
  await links.locator("summary").click();
  await links.getByRole("combobox",{name:"Instrument link channel"}).selectOption("fdc3.channel.green");
  record("channelMenu",await links.getByRole("combobox").locator("option").allTextContents());
  await links.locator("summary").click();

  const positions=page.getByRole("tab",{name:"Positions",exact:true});
  const orders=page.getByRole("tab",{name:"Orders",exact:true});
  await positions.focus();await page.keyboard.press("ArrowRight");await expect(orders).toBeFocused();
  await expect(positions).toHaveAttribute("aria-selected","true");await page.keyboard.press("Enter");await expect(orders).toHaveAttribute("aria-selected","true");
  await page.keyboard.press("ArrowLeft");await expect(positions).toBeFocused();await page.keyboard.press("Space");await expect(positions).toHaveAttribute("aria-selected","true");
  await page.clock.resume();
  await page.evaluate(() => {
    const events: unknown[]=[];
    Object.assign(window,{workspaceDragEvents:events});
    for(const kind of ["dragstart","dragenter","dragover","drop","dragend"])document.addEventListener(kind,e=>events.push({kind,target:(e.target as Element).outerHTML,prevented:e.defaultPrevented}),true);
  });
  const sourceBox=await orders.boundingBox(),targetBox=await positions.boundingBox();
  if(!sourceBox||!targetBox)throw new Error("Missing native drag targets");
  await page.mouse.move(sourceBox.x+20,sourceBox.y+15);await page.mouse.down();
  await page.mouse.move(sourceBox.x+25,sourceBox.y+15,{steps:5});
  await page.mouse.move(targetBox.x+20,targetBox.y+15,{steps:20});
  await page.mouse.move(targetBox.x+21,targetBox.y+15);
  await page.mouse.up();
  record("dragEvents",await page.evaluate(()=>Reflect.get(window,"workspaceDragEvents")));
  await expect(page.getByRole("tab",{name:"Orders",exact:true}).locator('..').getByRole("tab")).toHaveText(["Orders","Positions"]);
  await page.clock.pauseAt((await page.evaluate(()=>Date.now()))+50);
  record("reorder",["Orders","Positions"]);
  await orders.focus();await page.keyboard.press("Control+Delete");await expect(orders).toHaveCount(0);await expect(positions).toBeVisible();
  record("close",{shortcut:"Control+Delete",survivor:"Positions"});
  const paints=[];
  for(const control of [watchDot,chartDot,renamed,add,...await watchlist.getByRole("listitem").locator(':scope > button:first-child').all()])paints.push(await paint(control));
  record("finalPaint",paints);
  await renamed.focus();await page.screenshot({path:info.outputPath("interactions.png")});
  fs.writeFileSync(info.outputPath("interactions.ax.txt"),await page.locator("body").ariaSnapshot());
}
