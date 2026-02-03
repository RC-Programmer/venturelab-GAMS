import express from "express";

const app = express();
app.use(express.json({ limit: "1mb" }));

const PORT = process.env.PORT || 8080;
const MCP_URL = process.env.MCP_URL;
const API_TOKEN = process.env.API_TOKEN;

// VentureLab specific settings
const VENTURELAB_CUSTOMER_ID = "7725201935";
const MCC_LOGIN_CUSTOMER_ID = "5175250506";

if (!MCP_URL) throw new Error("Missing MCP_URL");
if (!API_TOKEN) throw new Error("Missing API_TOKEN");

function requireAuth(req, res, next) {
  const auth = String(req.headers.authorization || "").trim();
  const xApiKey = String(req.headers["x-api-key"] || "").trim();
  const apiKey = String(req.headers["api-key"] || "").trim();

  const ok =
    auth === `Bearer ${API_TOKEN}` ||
    auth === API_TOKEN ||
    xApiKey === API_TOKEN ||
    apiKey === API_TOKEN;

  if (!ok) return res.status(403).json({ error: "Forbidden" });
  next();
}

function safeJson(value) {
  const seen = new WeakSet();
  const normalize = (v) => {
    if (v == null) return v;
    const t = typeof v;
    if (t === "string" || t === "number" || t === "boolean") return v;
    if (t === "bigint") return v.toString();
    if (typeof Buffer !== "undefined" && Buffer.isBuffer(v)) return v.toString("base64");
    if (v instanceof Date) return v.toISOString();
    if (Array.isArray(v)) return v.map(normalize);
    if (typeof v === "object") {
      if (seen.has(v)) return "[Circular]";
      seen.add(v);
      if (typeof v.toJSON === "function") {
        try { return normalize(v.toJSON()); } catch {}
      }
      if (typeof v.toObject === "function") {
        try { return normalize(v.toObject()); } catch {}
      }
      try {
        if (typeof v[Symbol.iterator] === "function") {
          return Array.from(v, normalize);
        }
      } catch {}
      const out = {};
      for (const [k, val] of Object.entries(v)) {
        out[k] = normalize(val);
      }
      return out;
    }
    return String(v);
  };
  return normalize(value);
}

async function callMcpTool(toolName, args) {
  const body = {
    jsonrpc: "2.0",
    id: Date.now(),
    method: "tools/call",
    params: { name: toolName, arguments: args || {} }
  };

  const resp = await fetch(MCP_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json, text/event-stream"
    },
    body: JSON.stringify(body)
  });

  const text = await resp.text();
  
  let data;
  
  if (text.includes("event:") || text.startsWith("data:")) {
    const lines = text.split("\n");
    let lastData = null;
    for (const line of lines) {
      if (line.startsWith("data:")) {
        const jsonStr = line.slice(5).trim();
        if (jsonStr) {
          try {
            lastData = JSON.parse(jsonStr);
          } catch {}
        }
      }
    }
    if (!lastData) {
      throw new Error(`Failed to parse SSE response: ${text.slice(0, 500)}`);
    }
    data = lastData;
  } else {
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(`Invalid JSON response: ${text.slice(0, 500)}`);
    }
  }

  if (data?.error) {
    throw new Error(data.error?.message || JSON.stringify(data.error));
  }

  const result = data?.result;

  if (result?.isError === true) {
    const errContent = Array.isArray(result.content)
      ? result.content.find((c) => c?.type === "text")?.text
      : null;
    throw new Error(errContent || "Tool returned isError:true");
  }

  const toolResult = result?.structuredContent?.result ?? result?.content ?? result;
  return safeJson(toolResult);
}

function normalizeConditions(body) {
  if (Array.isArray(body?.conditions))
    return body.conditions.filter((x) => typeof x === "string" && x.trim());
  if (typeof body?.where === "string" && body.where.trim()) return [body.where.trim()];
  return [];
}

app.get("/healthz", (_req, res) => res.send("ok"));

// VentureLab info endpoint
app.get("/api/info", requireAuth, (_req, res) => {
  res.json({
    client: "VentureLab",
    customer_id: VENTURELAB_CUSTOMER_ID,
    mcc_id: MCC_LOGIN_CUSTOMER_ID
  });
});

app.post("/api/search", requireAuth, async (req, res) => {
  try {
    const body = req.body || {};
    const { resource, fields } = body;

    if (!resource || !Array.isArray(fields) || fields.length === 0) {
      return res.status(400).json({
        error: "Required: resource (string), fields (string[])"
      });
    }

    const conditions = normalizeConditions(body);
    const limit = typeof body.limit === "number" ? body.limit : undefined;

    // Normalize orderings to array format (Python MCP expects "orderings" as List[str])
    let orderings = [];
    if (Array.isArray(body.orderings)) {
      orderings = body.orderings.filter((x) => typeof x === "string" && x.trim());
    } else if (typeof body.orderings === "string" && body.orderings.trim()) {
      orderings = [body.orderings.trim()];
    } else if (typeof body.order_by === "string" && body.order_by.trim()) {
      // Support legacy "order_by" parameter name
      orderings = [body.order_by.trim()];
    }

    // Always use VentureLab's customer ID
    // Note: login_customer_id (MCC) is set via GOOGLE_ADS_LOGIN_CUSTOMER_ID env var on the MCP server
    const args = {
      customer_id: VENTURELAB_CUSTOMER_ID,
      resource,
      fields
    };

    if (conditions.length) args.conditions = conditions;
    if (orderings.length) args.orderings = orderings;
    if (typeof limit === "number") args.limit = limit;

    const result = await callMcpTool("search", args);
    res.json({ result });
  } catch (e) {
    console.error("search error:", e);
    res.status(500).json({ error: String(e?.message || e) });
  }
});

app.listen(PORT, () => console.log(`VentureLab GAMS wrapper listening on ${PORT}`));
