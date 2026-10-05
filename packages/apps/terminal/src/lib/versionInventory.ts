export interface BuildVersionRow { name: string; installed: string | null; declared: string | null }
export interface BuildVersionInventory {
  commit: string | null;
  libraries: BuildVersionRow[];
  buildTools: BuildVersionRow[];
  pins: Array<{ name: string; version: string | null }>;
}
declare const __FLINTTRADE_VERSION_INVENTORY__: BuildVersionInventory;
export const BUILD_VERSIONS = typeof __FLINTTRADE_VERSION_INVENTORY__ === "undefined"
  ? { commit: null, libraries: [], buildTools: [], pins: [] }
  : __FLINTTRADE_VERSION_INVENTORY__;
