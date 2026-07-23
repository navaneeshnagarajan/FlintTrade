// Adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
import { contextBridge, ipcRenderer } from "electron";

import { createFlintDesktopApi } from "./bridge";

contextBridge.exposeInMainWorld("flintDesktop", createFlintDesktopApi(ipcRenderer));
