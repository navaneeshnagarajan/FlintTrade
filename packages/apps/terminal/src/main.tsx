// Keep the existing motion dependency at the entry; no new animation is added.
import { MotionConfig } from "framer-motion";
import { initialisePublicPreview } from "./lib/publicPreview";
import { initialiseSchemaValidation } from "./lib/schemaValidation";

// Configure the supported no-eval validator before Application constructs schemas.
initialiseSchemaValidation();
// This must be an explicit call, not a side-effect-only import: package.json's
// sideEffects allowlist otherwise removes the public network/clock boundary.
initialisePublicPreview();
// Load data/store modules only AFTER the public snapshot is installed. Installed
// builds take the same path without modifying their clock or network transports.
void import("./Application").then(application => application.mountApplication(MotionConfig));
