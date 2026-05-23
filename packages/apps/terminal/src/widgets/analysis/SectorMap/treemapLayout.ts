/**
 * Treemap layout algorithm — squarified treemap.
 * Absorbed verbatim from openalgo-chart/src/components/SectorHeatmap/utils/treemapLayout.ts
 */

import type { TreemapItem, TreemapLayoutItem } from "./types";

export function calculateTreemapLayout(
  items: TreemapItem[],
  x: number,
  y: number,
  width: number,
  height: number,
): TreemapLayoutItem[] {
  if (items.length === 0 || width <= 0 || height <= 0) return [];
  const totalValue = items.reduce((sum, item) => sum + item.value, 0);
  if (totalValue <= 0) return [];

  const result: TreemapLayoutItem[] = [];
  let remaining = [...items];
  let currentX = x;
  let currentY = y;
  let currentWidth = width;
  let currentHeight = height;
  let remainingValue = totalValue;

  while (remaining.length > 0) {
    const isHorizontal = currentWidth >= currentHeight;
    const mainSide = isHorizontal ? currentHeight : currentWidth;
    let row = [remaining[0]];
    let rowValue = remaining[0].value;
    let worstRatio = Infinity;

    for (let i = 1; i < remaining.length; i++) {
      const testRow = [...row, remaining[i]];
      const testValue = rowValue + remaining[i].value;
      const rowThickness =
        (testValue / remainingValue) * (isHorizontal ? currentWidth : currentHeight);
      let testWorst = 0;
      testRow.forEach((item) => {
        const itemLength = (item.value / testValue) * mainSide;
        const ratio = Math.max(rowThickness / itemLength, itemLength / rowThickness);
        testWorst = Math.max(testWorst, ratio);
      });
      if (testWorst <= worstRatio) {
        row = testRow;
        rowValue = testValue;
        worstRatio = testWorst;
      } else {
        break;
      }
    }

    const rowFraction = rowValue / remainingValue;
    const rowSize = isHorizontal ? rowFraction * currentWidth : rowFraction * currentHeight;
    let offset = 0;

    row.forEach((item) => {
      const itemFraction = item.value / rowValue;
      const itemSize = itemFraction * mainSide;
      if (isHorizontal) {
        result.push({ ...item, x: currentX, y: currentY + offset, width: rowSize, height: itemSize });
      } else {
        result.push({ ...item, x: currentX + offset, y: currentY, width: itemSize, height: rowSize });
      }
      offset += itemSize;
    });

    remainingValue -= rowValue;
    remaining = remaining.slice(row.length);
    if (isHorizontal) {
      currentX += rowSize;
      currentWidth -= rowSize;
    } else {
      currentY += rowSize;
      currentHeight -= rowSize;
    }
  }

  return result;
}
