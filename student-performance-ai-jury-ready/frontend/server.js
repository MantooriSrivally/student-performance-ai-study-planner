const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");
const { spawn } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const PUBLIC = path.join(__dirname, "public");
const BACKEND = path.join(ROOT, "backend");
const RUNNER = path.join(ROOT, "pipeline_runner.py");
const PORT = Number(process.env.PORT || 4173);
const PYTHON = process.env.PYTHON_BIN || (process.platform === "win32" ? "python" : "python3");
const MAX_BODY = 5 * 1024 * 1024;

const SOURCE_FILES = ["student.json","interview.json","assignment.json","assessment.json","attendance.json"];

function send(res, status, payload, headers={}) {
  const body = typeof payload === "string" ? payload : JSON.stringify(payload);
  res.writeHead(status, {"Content-Type": typeof payload === "string" ? "text/plain; charset=utf-8" : "application/json; charset=utf-8", ...headers});
  res.end(body);
}
function safeJson(res, req) {
  let body="";
  req.on("data", c => { body += c; if(body.length > MAX_BODY) req.destroy(); });
  req.on("end", () => {
    try { req.body = JSON.parse(body || "{}"); res._jsonReady = true; handleApi(res, req); }
    catch(e) { send(res,400,{error:"Invalid JSON payload",detail:e.message}); }
  });
}
function spawnPipeline(dataDir) {
  return new Promise((resolve) => {
    const started = Date.now();
    const env = { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" };
    const child = spawn(PYTHON, [RUNNER, dataDir], { cwd: ROOT, env });
    let out = "", err = "";
    child.stdout.on("data", c => out += c.toString("utf8"));
    child.stderr.on("data", c => err += c.toString("utf8"));
    child.on("error", e => resolve({ ok: false, error: `Could not start Python: ${e.message}`, stderr: err, timing_ms: Date.now() - started }));
    child.on("close", code => {
      const timing_ms = Date.now() - started;
      if (code !== 0) return resolve({ ok: false, error: "Pipeline failed", stderr: err, stdout: out, timing_ms });
      try { resolve({ ok: true, report: JSON.parse(out), stderr: err, timing_ms }); }
      catch (e) { resolve({ ok: false, error: "Pipeline returned invalid JSON", detail: e.message, stderr: err, stdout: out, timing_ms }); }
    });
  });
}
function validateBundle(bundle) {
  for (const f of SOURCE_FILES) {
    if(!bundle[f] || typeof bundle[f] !== "object" || Array.isArray(bundle[f])) return `Missing or invalid ${f}`;
  }
  return null;
}
async function handleApi(res, req) {
  if(req.url === "/api/run" && req.method === "POST") {
    const bundle = req.body.sources || req.body;
    const problem = validateBundle(bundle);
    if(problem) return send(res,400,{error:problem});
    const dir = await fs.promises.mkdtemp(path.join(os.tmpdir(),"student-pipeline-"));
    try {
      for(const f of SOURCE_FILES) await fs.promises.writeFile(path.join(dir,f), JSON.stringify(bundle[f],null,2), "utf8");
      const result = await spawnPipeline(dir);
      if(!result.ok) return send(res,422,result);
      return send(res,200,{
        report:result.report,
        pipeline:{engine:result.report.meta?.engine || "local", status:"completed", timing_ms:result.timing_ms,
          stages:["load","validate","kpi","report"]}
      });
    } finally {
      await fs.promises.rm(dir,{recursive:true,force:true}).catch(()=>{});
    }
  }
  if(req.url.startsWith("/api/demo") && req.method === "GET") {
    const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
    const profile = (url.searchParams.get("profile") || "strong").toLowerCase();
    // Prefer running the matching mock-data folder when present; fall back to writing a temp dir from bundle.
    let dir = path.join(BACKEND,"mock_data");
    let cleanup = null;
    if(profile === "at-risk" || profile === "atrisk" || profile === "weak") {
      const bundlePath = path.join(PUBLIC, "mock-bundle-at-risk.json");
      const bundle = JSON.parse(await fs.promises.readFile(bundlePath, "utf8"));
      dir = await fs.promises.mkdtemp(path.join(os.tmpdir(),"student-pipeline-"));
      cleanup = dir;
      for(const f of SOURCE_FILES) {
        const key = f;
        await fs.promises.writeFile(path.join(dir,f), JSON.stringify(bundle[key],null,2), "utf8");
      }
    }
    try {
      const result = await spawnPipeline(dir);
      if(!result.ok) return send(res,500,result);
      return send(res,200,{
        report:result.report,
        pipeline:{engine:result.report.meta?.engine || "local", status:"completed", demo:true,
          profile: profile === "at-risk" || profile === "atrisk" || profile === "weak" ? "at-risk" : "strong",
          timing_ms:result.timing_ms, stages:["load","validate","kpi","report"]}
      });
    } finally {
      if(cleanup) await fs.promises.rm(cleanup,{recursive:true,force:true}).catch(()=>{});
    }
  }
  send(res,404,{error:"Not found"});
}
function serveStatic(req,res) {
  let pathname = decodeURIComponent(req.url.split("?")[0]);
  if(pathname === "/") pathname="/index.html";
  const file = path.normalize(path.join(PUBLIC, pathname));
  if(!file.startsWith(PUBLIC)) return send(res,403,"Forbidden");
  fs.readFile(file,(err,data)=>{
    if(err) return send(res,404,"Not found");
    const ext=path.extname(file);
    const types={".html":"text/html; charset=utf-8",".css":"text/css; charset=utf-8",".js":"text/javascript; charset=utf-8",".svg":"image/svg+xml",".json":"application/json"};
    res.writeHead(200,{"Content-Type":types[ext]||"application/octet-stream","Cache-Control":"no-store"});
    res.end(data);
  });
}
const server=http.createServer((req,res)=>{
  if(req.url.startsWith("/api/")) {
    if(req.method==="POST") return safeJson(res,req);
    return handleApi(res,req);
  }
  serveStatic(req,res);
});
server.listen(PORT,()=>console.log(`Student Performance Command Center → http://localhost:${PORT}`));
