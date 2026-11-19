/**
 * Netbuild Licensing - sheet API  (Google Apps Script)
 * Writes to the ONE licence sheet every Netbuild app reads: "Netbuild Licensing"
 * (BUA Workbook Builder, Revit Status, Revit MCP Router). Every reply carries sheet_id; the
 * developer tools refuse to write through a script that reports any other sheet.
 *
 * Set up (once), from inside the "Netbuild Licensing" sheet:
 *   Extensions > Apps Script > delete everything > paste this file > Save
 *   Deploy > New deployment > type: Web app > Execute as: Me > Who has access: Anyone > Deploy > authorise
 *   Copy the /exec URL into scripts\revitstatus_sheet_api.json and the KeyGen's sheet_api.json ("url").
 *   Project Settings (gear) > Script Properties > add (the secrets are NOT in this file -- it is public):
 *     TOKEN            the admin token (also "token" in sheet_api.json)
 *     LICENCE_SHEET_ID the "Netbuild Licensing" spreadsheet id (also "sheet_id" in sheet_api.json)
 *     SALT_BUA, SALT_RS, SALT_RMR   each app's password salt (pw_salt in netbuild_secrets.py)
 *   Without them every request is refused.
 * Every request must carry TOKEN; the script runs under the sheet owner's account, so the sheet
 * itself stays private (apps only read the tab published to the web as CSV).
 *
 * Columns: Key | Type | Status | Machine_ID | Note | Product
 * POST JSON body:
 *   {"token":"...","action":"list"}
 *   {"token":"...","action":"add","key":"<hash or key>","type":"password|key|kill","machine_id":"","note":"who","product":"..."}
 *   {"token":"...","action":"revoke","key":"<hash or key>"}
 *   {"token":"...","action":"activate","key":"<hash or key>"}
 *   {"token":"...","action":"set","key":"<hash or key>","machine_id":"XXXX-...","note":"...","status":"...","product":"..."}
 *   {"token":"...","action":"delete","key":"<hash or key>"}
 * GET  ?token=...&action=list   (same as list)
 * GET  ?action=kill&product=BUA  PUBLIC, no token: {"ok":true,"kill":"active|killed|missing"} for the
 *                                "<PRODUCT>-KILL-SWITCH" row ONLY, read live from the sheet (no publish
 *                                cache) - lets the apps see a kill / re-enable instantly. Nothing else is
 *                                readable without the token.
 * POST {"action":"claim","product":"BUA","password":"<plain>","machine_id":"XXXX-XXXX-XXXX-XXXX"}
 *                                PUBLIC, no token: locks a one-PC password to the first PC that activates
 *                                it. The script hashes the password itself (so only someone who KNOWS it can
 *                                claim), finds that product's active password row, writes the Machine_ID if
 *                                empty. -> {"ok":true,"claim":"claimed|mine|other|revoked|unknown"}
 * Updating the code later: Deploy > Manage deployments > pencil > Version: New version > Deploy (keeps the URL).
 */
var TOKEN = PropertiesService.getScriptProperties().getProperty("TOKEN");
var LICENCE_SHEET_ID = PropertiesService.getScriptProperties().getProperty("LICENCE_SHEET_ID");   // "Netbuild Licensing"
var LICENCE_TAB_GID = 1189617866;                                       // the tab published as CSV
var HEADER = ["Key", "Type", "Status", "Machine_ID", "Note", "Product"];

function _sheet() {
  var ss = SpreadsheetApp.openById(LICENCE_SHEET_ID);
  var sh = ss.getSheets().filter(function (s) { return s.getSheetId() === LICENCE_TAB_GID; })[0] || ss.getSheets()[0];
  if (sh.getLastRow() === 0) sh.appendRow(HEADER);
  return sh;
}
function _norm(k) { return String(k || "").replace(/-/g, "").trim().toLowerCase(); }
function _rows(sh) {
  var last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, HEADER.length).getValues();
}
function _find(sh, key) {
  var rows = _rows(sh), want = _norm(key);
  for (var i = 0; i < rows.length; i++) if (_norm(rows[i][0]) === want) return i + 2;   // sheet row number
  return -1;
}
function _out(obj) {
  obj.sheet_id = LICENCE_SHEET_ID;
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
function _list(sh) {
  return _rows(sh).filter(function (r) { return String(r[0]).trim() !== ""; }).map(function (r) {
    return { key: String(r[0]), type: String(r[1]), status: String(r[2]), machine_id: String(r[3]),
             note: String(r[4]), product: String(r[5]) };
  });
}
function _killState(product) {
  var code = String(product || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  if (!code) return "missing";
  var sh = _sheet(), row = _find(sh, code + "-KILL-SWITCH");
  if (row < 0) return "missing";
  var st = String(sh.getRange(row, 3).getValue()).trim().toLowerCase();
  return ["revoked", "killed", "disabled", "off"].indexOf(st) >= 0 ? "killed" : "active";
}
function _prop(name) { return PropertiesService.getScriptProperties().getProperty(name) || ""; }
// Products whose passwords lock to the first PC (salt = the app's password salt, name = Product column).
var CLAIM_PRODUCTS = {
  "BUA": { name: "BUA Workbook Builder", salt: _prop("SALT_BUA") },
  "RS":  { name: "Revit Status",         salt: _prop("SALT_RS") },
  "RMR": { name: "Revit MCP Router",     salt: _prop("SALT_RMR") }
};
function _hex(bytes) {
  return bytes.map(function (b) { var v = (b < 0 ? b + 256 : b).toString(16); return v.length === 1 ? "0" + v : v; }).join("");
}
function _claim(p) {
  var prod = CLAIM_PRODUCTS[String(p.product || "").toUpperCase()];
  if (!prod) return { ok: false, error: "unknown product" };
  if (!prod.salt) return { ok: false, error: "salt not set in Script Properties" };
  var pw = String(p.password || ""), mid = String(p.machine_id || "").trim().toUpperCase();
  if (!pw || mid.replace(/-/g, "").length !== 16) return { ok: false, error: "password and machine_id required" };
  var hash = _hex(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, prod.salt + "\u001f" + pw, Utilities.Charset.UTF_8));
  var sh = _sheet(), row = _find(sh, hash);
  if (row < 0) return { ok: true, claim: "unknown" };
  var v = sh.getRange(row, 1, 1, HEADER.length).getValues()[0];
  if (String(v[1]).trim().toLowerCase() !== "password" || String(v[5]).trim() !== prod.name) return { ok: true, claim: "unknown" };
  if (String(v[2]).trim().toLowerCase() !== "active") return { ok: true, claim: "revoked" };
  var owner = String(v[3]).trim().toUpperCase().replace(/-/g, "");
  if (!owner) { sh.getRange(row, 4).setValue(mid); return { ok: true, claim: "claimed" }; }
  return { ok: true, claim: owner === mid.replace(/-/g, "") ? "mine" : "other" };
}
function _handle(p) {
  if (p && String(p.action) === "kill") {          // public, read-only, kill switch row only
    return _out({ ok: true, product: String(p.product || ""), kill: _killState(p.product) });
  }
  if (p && String(p.action) === "claim") {         // public, but needs the plain password to do anything
    var lk = LockService.getScriptLock();
    lk.waitLock(10000);
    try { return _out(_claim(p)); } finally { lk.releaseLock(); }
  }
  if (!TOKEN || !p || p.token !== TOKEN) return _out({ ok: false, error: "bad token" });
  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var sh = _sheet();
    var action = String(p.action || "list");
    if (action === "list") return _out({ ok: true, rows: _list(sh) });
    var key = String(p.key || "").trim();
    if (!key) return _out({ ok: false, error: "key required" });
    var row = _find(sh, key);
    if (action === "add") {
      if (row > 0) return _out({ ok: false, error: "key already in sheet at row " + row });
      sh.appendRow([key, String(p.type || ""), String(p.status || "active"), String(p.machine_id || ""),
                    String(p.note || ""), String(p.product || "")]);
      return _out({ ok: true, row: sh.getLastRow(), rows: _list(sh) });
    }
    if (row < 0) return _out({ ok: false, error: "key not found" });
    if (action === "revoke")        { sh.getRange(row, 3).setValue("revoked"); }
    else if (action === "activate") { sh.getRange(row, 3).setValue("active"); }
    else if (action === "delete")   { sh.deleteRow(row); }
    else if (action === "set") {
      if (p.status !== undefined)     sh.getRange(row, 3).setValue(String(p.status));
      if (p.machine_id !== undefined) sh.getRange(row, 4).setValue(String(p.machine_id));
      if (p.note !== undefined)       sh.getRange(row, 5).setValue(String(p.note));
      if (p.product !== undefined)    sh.getRange(row, 6).setValue(String(p.product));
    }
    else return _out({ ok: false, error: "unknown action " + action });
    return _out({ ok: true, row: row, rows: _list(sh) });
  } finally {
    lock.releaseLock();
  }
}
function doPost(e) {
  var p = {};
  try { p = JSON.parse(e.postData.contents); } catch (err) { return _out({ ok: false, error: "body must be JSON" }); }
  return _handle(p);
}
function doGet(e) { return _handle(e.parameter); }
