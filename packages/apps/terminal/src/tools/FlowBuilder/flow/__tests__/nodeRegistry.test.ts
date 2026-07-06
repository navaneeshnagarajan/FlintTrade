import { describe, expect, it } from "vitest";

import { NODE_DESCRIPTORS, NODE_CATEGORIES } from "../nodeRegistry";

function nodeDescription(type: string): string {
  for (const category of NODE_CATEGORIES) {
    const node = category.nodes.find((candidate) => candidate.type === type);
    if (node) return node.description;
  }
  throw new Error(`Missing node ${type}`);
}

describe("nodeRegistry broker data descriptions", () => {
  it("does not promise a fixed 50-level depth surface", () => {
    expect(nodeDescription("getDepth")).toBe("Broker depth snapshot");
    expect(nodeDescription("subscribeDepth")).toBe("Broker depth stream");

    const descriptions = [
      nodeDescription("getDepth"),
      nodeDescription("subscribeDepth"),
      ...Array.from(NODE_DESCRIPTORS.values()).map((descriptor) => descriptor.description),
    ];
    expect(descriptions.join("\n")).not.toContain("50-level");
  });
});
