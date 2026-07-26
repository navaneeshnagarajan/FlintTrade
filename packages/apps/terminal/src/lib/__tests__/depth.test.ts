import { describe, it, expect } from "vitest";
import { normaliseDepth, bookImbalance } from "../depth";

describe("normaliseDepth", () => {
  it("reads the canonical field names", () => {
    const book = normaliseDepth({
      bids: [{ price: 100, quantity: 50, orders: 3 }],
      asks: [{ price: 101, quantity: 40, orders: 2 }],
    });
    expect(book.bids[0]).toEqual({ price: 100, qty: 50, orders: 3 });
    expect(book.asks[0]).toEqual({ price: 101, qty: 40, orders: 2 });
  });

  it("reads the short aliases some bridges emit", () => {
    // This is the shape the DOM Heatmap used to render as an empty book,
    // silently and with no error.
    const book = normaliseDepth({
      buy: [{ p: 100, q: 50, o: 3 }],
      sell: [{ p: 101, qty: 40, num_orders: 2 }],
    });
    expect(book.bids[0]).toEqual({ price: 100, qty: 50, orders: 3 });
    expect(book.asks[0]).toEqual({ price: 101, qty: 40, orders: 2 });
  });

  it("accepts buy/sell as side keys", () => {
    const book = normaliseDepth({ buy: [{ price: 1, quantity: 1 }], sell: [] });
    expect(book.bids).toHaveLength(1);
  });

  it("coerces string-typed wire numerics", () => {
    const book = normaliseDepth({ bids: [{ price: "100.5", quantity: "25" }], asks: [] });
    expect(book.bids[0].price).toBe(100.5);
    expect(book.bids[0].qty).toBe(25);
  });

  it("returns empty ladders for an absent or malformed payload", () => {
    expect(normaliseDepth(null)).toEqual({ bids: [], asks: [] });
    expect(normaliseDepth(undefined)).toEqual({ bids: [], asks: [] });
    expect(normaliseDepth({})).toEqual({ bids: [], asks: [] });
  });

  it("caps at five levels by default and honours an explicit cap", () => {
    const many = Array.from({ length: 20 }, (_, i) => ({ price: i + 1, quantity: 1 }));
    expect(normaliseDepth({ bids: many, asks: [] }).bids).toHaveLength(5);
    expect(normaliseDepth({ bids: many, asks: [] }, 20).bids).toHaveLength(20);
  });

  it("never emits NaN for a missing or garbage field", () => {
    const book = normaliseDepth({ bids: [{ price: 100 }], asks: [{ price: "abc" }] });
    expect(book.bids[0].qty).toBe(0);
    expect(book.asks[0].price).toBe(0);
  });
});

describe("bookImbalance", () => {
  it("is positive when the bid side is heavier", () => {
    expect(bookImbalance([{ price: 1, qty: 75, orders: 1 }], [{ price: 2, qty: 25, orders: 1 }]))
      .toBeCloseTo(0.5);
  });

  it("is negative when the ask side is heavier", () => {
    expect(bookImbalance([{ price: 1, qty: 25, orders: 1 }], [{ price: 2, qty: 75, orders: 1 }]))
      .toBeCloseTo(-0.5);
  });

  it("is zero for a balanced or empty book", () => {
    expect(bookImbalance([{ price: 1, qty: 10, orders: 1 }], [{ price: 2, qty: 10, orders: 1 }])).toBe(0);
    expect(bookImbalance([], [])).toBe(0);
  });
});
