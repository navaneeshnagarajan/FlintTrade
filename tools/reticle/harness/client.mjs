import http from 'node:http';
import fs from 'node:fs/promises';

export async function connectReticle(artifact) {
  const pending = new Map(); let serial = 1; let endpoint; let stream; let resolveEndpoint;
  const ready = new Promise((resolve) => { resolveEndpoint = resolve; });
  const rows = [];
  const request = http.get({ host: '127.0.0.1', port: 4400, path: '/mcp/sse', agent: false }, (response) => {
    if (response.statusCode !== 200) throw new Error(`SSE status ${response.statusCode}`);
    stream = response; let buffer = ''; response.setEncoding('utf8');
    response.on('data', (chunk) => {
      buffer += chunk;
      const frames = buffer.split('\n\n'); buffer = frames.pop() ?? '';
      for (const frame of frames) {
        const event = /^event: (.*)$/m.exec(frame)?.[1] ?? 'message';
        const text = /^data: (.*)$/m.exec(frame)?.[1]; if (!text) continue;
        if (event === 'endpoint') { endpoint = text; resolveEndpoint(); continue; }
        const message = JSON.parse(text); const awaiting = pending.get(message.id);
        if (awaiting) { clearTimeout(awaiting.timer); pending.delete(message.id); awaiting.resolve(message); }
      }
    });
  });
  request.on('error', (error) => { for (const entry of pending.values()) entry.reject(error); });
  async function rpc(method, params, notification = false) {
    await ready; const id = serial++;
    const body = JSON.stringify({ jsonrpc: '2.0', ...(notification ? {} : { id }), method, params });
    const answer = notification ? Promise.resolve(null) : new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Reticle timeout: ${method}`)); }, 20000);
      pending.set(id, { resolve, reject, timer });
    });
    await new Promise((resolve, reject) => {
      const post = http.request({ host: '127.0.0.1', port: 4400, path: endpoint, method: 'POST', headers: { 'Content-Type': 'application/json' } }, (response) => {
        response.resume(); response.on('end', () => response.statusCode === 202 ? resolve() : reject(new Error(`MCP POST ${response.statusCode}`)));
      }); post.on('error', reject); post.end(body);
    });
    const response = await answer; rows.push({ request: JSON.parse(body), response });
    await fs.writeFile(artifact, JSON.stringify(rows, null, 2));
    if (response?.error) throw new Error(JSON.stringify(response.error));
    return response?.result;
  }
  await rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'foundation-truth', version: '1.0.0' } });
  await rpc('notifications/initialized', {}, true);
  await rpc('tools/list', {});
  return {
    async call(name, args) {
      const result = await rpc('tools/call', { name, arguments: args });
      if (result?.isError) throw new Error(JSON.stringify(result));
      if (result?.structuredContent) return result.structuredContent;
      const text = result?.content?.filter((row) => row.type === 'text').map((row) => row.text).join('\n');
      try { return JSON.parse(text); } catch { return { text }; }
    },
    close() { stream?.destroy(); request.destroy(); },
  };
}
