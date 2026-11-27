import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { expect, it } from 'vitest';

function webpSize(buffer: Buffer): { width: number; height: number } {
  if (buffer.toString('ascii', 0, 4) !== 'RIFF' || buffer.toString('ascii', 8, 12) !== 'WEBP') {
    throw new Error('not a WebP file');
  }
  const chunk = buffer.toString('ascii', 12, 16);
  if (chunk === 'VP8X') {
    return {
      width: 1 + buffer.readUIntLE(24, 3),
      height: 1 + buffer.readUIntLE(27, 3),
    };
  }
  if (chunk === 'VP8 ') {
    return {
      width: buffer.readUInt16LE(26) & 0x3fff,
      height: buffer.readUInt16LE(28) & 0x3fff,
    };
  }
  if (chunk === 'VP8L') {
    const bits = buffer.readUInt32LE(21);
    return {
      width: 1 + (bits & 0x3fff),
      height: 1 + ((bits >> 14) & 0x3fff),
    };
  }
  throw new Error(`unsupported WebP chunk ${chunk}`);
}

function declaredSize(source: string, asset: string): { width: number; height: number } {
  const match = source.match(
    new RegExp(`src="/product/${asset}"[\\s\\S]*?width=\\{(\\d+)\\}[\\s\\S]*?height=\\{(\\d+)\\}`),
  );
  if (!match) throw new Error(`${asset} has no declared width and height`);
  return { width: Number(match[1]), height: Number(match[2]) };
}

it('stores each product screenshot at the 1600 by 900 size declared beside it', () => {
  const source = readFileSync(resolve(process.cwd(), 'src/components/product-overview.tsx'), 'utf8');
  for (const asset of ['trading.webp', 'studio.webp', 'review.webp']) {
    const file = webpSize(readFileSync(resolve(process.cwd(), 'public/product', asset)));
    const declared = declaredSize(source, asset);
    expect(file, asset).toEqual({ width: 1600, height: 900 });
    expect(declared, asset).toEqual(file);
  }
});
