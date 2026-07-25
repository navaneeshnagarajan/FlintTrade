/**
 * Squarified treemap layout for the Positions heat view.
 *
 * Packs weighted nodes into a rectangle as tiles kept as close to square as
 * possible (Bruls, Huizing & van Wijk, 2000): a strip runs along the shorter
 * edge of the free rectangle and keeps absorbing nodes while its worst aspect
 * ratio does not get worse, then the algorithm recurses on what is left.
 *
 * Ported from the retired Position Heat Map widget. It is generic over the node
 * type so the caller's own fields (symbol, sector, P&L…) travel through the
 * layout with their types intact.
 *
 * NOTE: `widgets/analysis/SectorMap/treemapLayout.ts` holds a second
 * implementation of the same published algorithm, differing only in that its
 * node type is an index-signature bag (`TreemapItem`), which erases the
 * caller's field types. The two should become one kernel; that consolidation
 * belongs with the SectorMap family rather than with this merge, because
 * adopting the untyped signature here would force casts back through every
 * heat cell.
 */

export interface TreemapNode {
  /** Non-negative weight driving the tile's area. */
  value: number;
}

export interface TreemapRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Lay `nodes` out inside the given rectangle.
 *
 * @param nodes - Weighted nodes; a non-positive total returns no tiles.
 * @param x - Left edge of the target rectangle.
 * @param y - Top edge of the target rectangle.
 * @param width - Target rectangle width in pixels.
 * @param height - Target rectangle height in pixels.
 * @returns Each input node with its tile geometry attached.
 */
export function squarifiedTreemap<T extends TreemapNode>(
  nodes: readonly T[],
  x: number,
  y: number,
  width: number,
  height: number,
): (T & TreemapRect)[] {
  type Out = T & TreemapRect;

  if (nodes.length === 0 || width <= 0 || height <= 0) return [];

  const total = nodes.reduce((sum, node) => sum + node.value, 0);
  if (total <= 0) return [];

  const result: Out[] = [];
  let remaining = [...nodes];
  let cx = x;
  let cy = y;
  let cw = width;
  let ch = height;
  let remainingTotal = total;

  while (remaining.length > 0) {
    const horizontal = cw >= ch;
    const mainSide = horizontal ? ch : cw;
    let row = [remaining[0]];
    let rowVal = remaining[0].value;
    let worstRatio = Infinity;

    for (let i = 1; i < remaining.length; i++) {
      const candidate = [...row, remaining[i]];
      const candidateVal = rowVal + remaining[i].value;
      const thickness = (candidateVal / remainingTotal) * (horizontal ? cw : ch);
      let worst = 0;
      candidate.forEach((node) => {
        const len = (node.value / candidateVal) * mainSide;
        worst = Math.max(worst, Math.max(thickness / len, len / thickness));
      });
      if (worst <= worstRatio) {
        row = candidate;
        rowVal = candidateVal;
        worstRatio = worst;
      } else {
        break;
      }
    }

    const rowFraction = rowVal / remainingTotal;
    const rowSize = horizontal ? rowFraction * cw : rowFraction * ch;
    let offset = 0;

    row.forEach((node) => {
      const itemFraction = node.value / rowVal;
      const itemSize = itemFraction * mainSide;
      if (horizontal) {
        result.push({ ...node, x: cx, y: cy + offset, width: rowSize, height: itemSize });
      } else {
        result.push({ ...node, x: cx + offset, y: cy, width: itemSize, height: rowSize });
      }
      offset += itemSize;
    });

    remainingTotal -= rowVal;
    remaining = remaining.slice(row.length);
    if (horizontal) {
      cx += rowSize;
      cw -= rowSize;
    } else {
      cy += rowSize;
      ch -= rowSize;
    }
  }

  return result;
}
