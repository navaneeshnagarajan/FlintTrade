/** Canonical Automation Hub wrapper for the functional React Flow editor. */

import FlowBuilderTool from "@/tools/FlowBuilder/FlowBuilderTool";

export default function FlowsSection() {
  return (
    <div
      className="h-full min-h-[36rem] overflow-hidden border border-border-default"
      data-tour-target="flow-builder"
    >
      <FlowBuilderTool />
    </div>
  );
}
