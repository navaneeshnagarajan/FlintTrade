const rawVersion = import.meta.env.VITE_FLINTTRADE_VERSION || "v0.0.0-dev";

export const APP_VERSION_TAG = rawVersion.startsWith("v") ? rawVersion : `v${rawVersion}`;
export const APP_VERSION = APP_VERSION_TAG.replace(/^v/, "");
