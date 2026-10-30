//! Optional Herdr-only source for Pixtuoid. No agents are started, and only
//! read-only requests are sent except for an explicit user focus gesture.
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};
use pixtuoid_core::{AgentEvent, AgentId, Transport};
use pixtuoid_core::source::{Resolution, TaggedSender};
use serde_json::{Value, json};

const LIVE_TOOL_ID: &str = "herdr-running";
const WAIT_TOOL_ID: &str = "herdr-waiting";
const RECONNECT: Duration = Duration::from_secs(2);
// Snapshot refresh catches state changes even when pane.updated is not emitted.
// No per-pane agent_status_changed subscriptions: those require pane_id, and
// in current Herdr releases can add a non-trivial idle CPU cost per pane.
const REFRESH: Duration = Duration::from_secs(5);
const RECAP_REFRESH: Duration = Duration::from_secs(60);

#[derive(Clone, Debug, PartialEq, Eq)]
struct Resident {
    pane: String,
    id: AgentId,
    kind: String,
    session: String,
    native_session: String,
    cwd: PathBuf,
    name: String,
    status: String,
    metadata_summary: Option<String>,
}

#[derive(Clone)]
struct FocusTarget { pane: String, socket: PathBuf }
static FOCUS: OnceLock<Mutex<HashMap<AgentId, FocusTarget>>> = OnceLock::new();
// Short per-agent recap, shown only on hover. Never persist pane contents.
static NOTES: OnceLock<Mutex<HashMap<AgentId, String>>> = OnceLock::new();
fn notes() -> &'static Mutex<HashMap<AgentId, String>> {
    NOTES.get_or_init(|| Mutex::new(HashMap::new()))
}
pub(crate) fn note_for(id: AgentId) -> Option<String> {
    notes().lock().ok()?.get(&id).cloned()
}

fn focus_map() -> &'static Mutex<HashMap<AgentId, FocusTarget>> {
    FOCUS.get_or_init(|| Mutex::new(HashMap::new()))
}

/// The only write action: a deliberate click on a Herdr resident. All subprocess
/// arguments are literal argv elements, never interpreted by a shell.
pub(crate) fn focus_slot(id: AgentId) -> bool {
    let target = focus_map().lock().ok().and_then(|m| m.get(&id).cloned());
    let Some(target) = target else { return false; };
    // Setting HERDR_SOCKET_PATH also supports named sessions without a second flag.
    let result = std::process::Command::new("herdr")
        .env("HERDR_SOCKET_PATH", &target.socket)
        .args(["agent", "focus", &target.pane])
        .status();
    if let Err(error) = result {
        tracing::debug!(%error, "herdr focus failed");
    }
    true
}

pub(crate) fn enabled() -> bool {
    std::env::var("PIXTUOID_HERDR").is_ok_and(|v| v == "1")
}

pub(crate) fn start(tx: TaggedSender) {
    #[cfg(unix)]
    if let Err(error) = std::thread::Builder::new()
        .name("pixtuoid-herdr".into())
        .spawn(move || run_blocking(tx))
    {
        tracing::warn!(%error, "unable to start Herdr source thread");
    }
    #[cfg(not(unix))]
    { let _ = tx; tracing::warn!("Herdr source requires Unix sockets"); }
}

#[cfg(unix)]
fn socket_path() -> Option<PathBuf> {
    if let Some(path) = std::env::var_os("HERDR_SOCKET_PATH") {
        return Some(PathBuf::from(path));
    }
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?
        .join("herdr");
    if let Some(session) = std::env::var_os("HERDR_SESSION") {
        let name = PathBuf::from(session);
        if name.components().count() != 1 || name.as_os_str().is_empty() { return None; }
        return Some(base.join("sessions").join(name).join("herdr.sock"));
    }
    let default = base.join("herdr.sock");
    if default.exists() { return Some(default); }
    // If there is only one named local session, support it without extra env.
    // Never choose arbitrarily between two different sessions.
    let sessions = base.join("sessions");
    let mut named = Vec::new();
    if let Ok(dir) = std::fs::read_dir(sessions) {
        for entry in dir.flatten() {
            let path = entry.path().join("herdr.sock");
            if path.exists() { named.push(path); }
        }
    }
    if named.len() == 1 { return named.pop(); }
    Some(default)
}

#[cfg(unix)]
fn run_blocking(tx: TaggedSender) {
    let Some(socket) = socket_path() else {
        tracing::warn!("No Herdr socket path available");
        return;
    };
    let mut previous = HashMap::<String, Resident>::new();
    let mut previous_error = String::new();
    let mut last_warning = Instant::now() - Duration::from_secs(60);
    loop {
        match cycle(&socket, &tx, &mut previous) {
            Ok(()) => { previous_error.clear(); }
            Err(e) => {
                let detail = format!("{e} (socket: {})", socket.display());
                // An invalid subscription or wrong socket must not be invisible.
                // Rate-limit warnings while Herdr is stopped.
                if detail != previous_error || last_warning.elapsed() >= Duration::from_secs(30) {
                    tracing::warn!(%detail, "Herdr source disconnected; will retry");
                    last_warning = Instant::now();
                    previous_error = detail;
                }
            }
        }
        // Don't leave stale characters if the Herdr session exits.
        for old in previous.drain().map(|(_, a)| a) {
            emit(&tx, AgentEvent::SessionEnd { agent_id: old.id, as_child: false });
        }
        if let Ok(mut m) = focus_map().lock() { m.clear(); }
        if let Ok(mut m) = notes().lock() { m.clear(); }
        std::thread::sleep(RECONNECT);
    }
}

fn emit(tx: &TaggedSender, event: AgentEvent) {
    let _ = tx.blocking_send((Transport::Hook, event));
}

#[cfg(unix)]
fn request(socket: &Path, method: &str) -> std::io::Result<Value> {
    request_params(socket, method, json!({}))
}

#[cfg(unix)]
fn request_params(socket: &Path, method: &str, params: Value) -> std::io::Result<Value> {
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixStream;
    let mut conn = UnixStream::connect(socket)?;
    conn.set_read_timeout(Some(if method == "pane.read" {
        Duration::from_millis(500)
    } else { Duration::from_secs(3) }))?;
    let message = json!({"id":"pixtuoid-herdr","method":method,"params":params});
    writeln!(conn, "{message}")?;
    let mut line = String::new();
    BufReader::new(conn).read_line(&mut line)?;
    let parsed: Value = serde_json::from_str(&line).map_err(std::io::Error::other)?;
    if let Some(error) = parsed.get("error") {
        return Err(std::io::Error::other(format!("Herdr {method} rejected: {error}")));
    }
    Ok(parsed["result"].clone())
}

#[cfg(unix)]
fn cycle(socket: &Path, tx: &TaggedSender, previous: &mut HashMap<String, Resident>) -> std::io::Result<()> {
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixStream;
    // Subscribe *before* the initial snapshot to avoid a bootstrap gap.
    let mut stream = UnixStream::connect(socket)?;
    // IMPORTANT: pane.agent_status_changed is per-pane and requires a pane_id.
    // A global subscription silently prevented the initial snapshot from loading.
    let subscriptions = ["pane.created", "pane.closed", "pane.exited", "pane.agent_detected", "pane.updated"];
    let sub = json!({"id":"pixtuoid-sub", "method":"events.subscribe", "params":{
        "subscriptions": subscriptions.map(|s| json!({"type":s}))
    }});
    writeln!(stream, "{sub}")?;
    stream.set_read_timeout(Some(REFRESH))?;
    let mut reader = BufReader::new(stream);
    let mut ack = String::new();
    if reader.read_line(&mut ack)? == 0 { return Err(std::io::Error::other("subscription closed")); }
    let response: Value = serde_json::from_str(&ack).map_err(std::io::Error::other)?;
    if let Some(error) = response.get("error") {
        return Err(std::io::Error::other(format!("subscription rejected: {error}")));
    }
    reconcile(socket, tx, previous)?;
    refresh_notes(socket, previous);
    let mut last_recap = Instant::now();
    loop {
        let mut line = String::new();
        match reader.read_line(&mut line) {
            Ok(0) => return Err(std::io::Error::other("subscription ended")),
            Ok(_) => {},
            Err(e) if matches!(e.kind(), std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock) => {
                reconcile(socket, tx, previous)?;
                if last_recap.elapsed() >= RECAP_REFRESH {
                    refresh_notes(socket, previous);
                    last_recap = Instant::now();
                }
                continue;
            }
            Err(e) => return Err(e),
        }
        let event: Value = serde_json::from_str(&line).map_err(std::io::Error::other)?;
        if event.get("error").is_some() { return Err(std::io::Error::other("subscription events lost")); }
        // Events signal invalidation, not an ordered patch to a snapshot.
        reconcile(socket, tx, previous)?;
        if last_recap.elapsed() >= RECAP_REFRESH {
            refresh_notes(socket, previous);
            last_recap = Instant::now();
        }
    }
}

#[cfg(unix)]
fn reconcile(socket: &Path, tx: &TaggedSender, previous: &mut HashMap<String, Resident>) -> std::io::Result<()> {
    let value = request(socket, "session.snapshot")?;
    let current = residents(&value);
    for (pane, old) in previous.iter() {
        if current.get(pane).is_none_or(|fresh| fresh.id != old.id) {
            emit(tx, AgentEvent::SessionEnd { agent_id: old.id, as_child: false });
            if let Ok(mut m) = focus_map().lock() { m.remove(&old.id); }
            if let Ok(mut m) = notes().lock() { m.remove(&old.id); }
        }
    }
    for (pane, item) in &current {
        let old = previous.get(pane);
        if old.is_none_or(|x| x.id != item.id) {
            emit(tx, AgentEvent::SessionStart {
                agent_id: item.id, source: item.kind.clone(),
                session_id: item.session.clone(), cwd: item.cwd.clone(), parent_id: None,
            });
            emit(tx, AgentEvent::Rename { agent_id: item.id, label: item.name.clone() });
        } else if old.is_some_and(|x| x.name != item.name) {
            emit(tx, AgentEvent::Rename { agent_id: item.id, label: item.name.clone() });
        }
        let old_status = old.filter(|x| x.id == item.id).map(|x| x.status.as_str());
        if old_status != Some(item.status.as_str()) {
            transition(tx, item.id, old_status, &item.status);
            if item.status == "working" {
                if let Ok(mut m) = notes().lock() { m.remove(&item.id); }
            }
        }
        if let Ok(mut m) = focus_map().lock() {
            m.insert(item.id, FocusTarget { pane: pane.clone(), socket: socket.to_path_buf() });
        }
        if let Some(summary) = &item.metadata_summary {
            if let Ok(mut m) = notes().lock() { m.insert(item.id, summary.clone()); }
        }
        // Long-running, quiet agents must not be swept while Herdr still reports them.
        emit(tx, AgentEvent::ProofOfLife { agent_id: item.id });
    }
    *previous = current;
    Ok(())
}

// Optional, low-rate recap extraction. We only show explicit recap text or
// an explicitly reported `tokens.summary` metadata value. No LLM calls.
#[cfg(unix)]
fn refresh_notes(socket: &Path, current: &HashMap<String, Resident>) {
    // Bounded to avoid expensive scans on very large sessions.
    for item in current.values().filter(|v| v.status != "working").take(64) {
        // Claude transcript is structured; prefer its last user-facing text
        // over a fragile terminal-output heuristic. Only look for this session.
        if item.kind == "claude-code" {
            if let Some(reply) = last_claude_reply(&item.native_session) {
                if let Ok(mut m) = notes().lock() { m.insert(item.id, reply); }
                continue;
            }
        }
        if item.metadata_summary.is_some() { continue; }
        let result = request_params(socket, "pane.read", json!({
            "pane_id": item.pane,
            "source": "recent",
            "lines": 80,
            "format": "text",
            "strip_ansi": true
        }));
        if let Ok(result) = result {
            if let Some(recap) = find_recap(&result) {
                if let Ok(mut m) = notes().lock() { m.insert(item.id, recap); }
            }
        }
    }
}

/// Extract only the latest assistant *text* (not tool outputs or thinking)
/// from a bounded tail of the session's Claude Code JSONL. No LLM, subprocess,
/// network call or full-transcript scan. Files stay under ~/.claude/projects.
fn last_claude_reply(session: &str) -> Option<String> {
    use std::io::{Read, Seek, SeekFrom};
    if session.len() > 80 || session.is_empty() ||
        !session.chars().all(|c| c.is_ascii_hexdigit() || c == '-') {
        return None;
    }
    let home = std::env::var_os("HOME")?;
    let root = PathBuf::from(home).join(".claude/projects");
    let entries = std::fs::read_dir(root).ok()?;
    // Bounded directory enumeration; no recursive traversal or full transcript.
    for entry in entries.take(256).flatten() {
        if !entry.file_type().ok().is_some_and(|t| t.is_dir()) { continue; }
        let path = entry.path().join(format!("{session}.jsonl"));
        let Ok(mut file) = std::fs::File::open(path) else { continue; };
        let Ok(meta) = file.metadata() else { continue; };
        let start = meta.len().saturating_sub(256 * 1024);
        if file.seek(SeekFrom::Start(start)).is_err() { continue; }
        let mut bytes = Vec::new();
        if file.take(256 * 1024).read_to_end(&mut bytes).is_err() { continue; }
        let text = String::from_utf8_lossy(&bytes);
        for line in text.lines().rev() {
            let Ok(v) = serde_json::from_str::<Value>(line) else { continue; };
            if v.get("type").and_then(Value::as_str) != Some("assistant") ||
                v.get("isSidechain").and_then(Value::as_bool) == Some(true) { continue; }
            let Some(parts) = v.pointer("/message/content").and_then(Value::as_array) else { continue; };
            let combined = parts.iter().filter_map(|p| {
                if p.get("type").and_then(Value::as_str) == Some("text") {
                    p.get("text").and_then(Value::as_str)
                } else { None }
            }).collect::<Vec<_>>().join(" ");
            let trimmed = clean_line(&combined);
            if !trimmed.is_empty() {
                return Some(trimmed.chars().take(260).collect());
            }
        }
    }
    None
}

fn plain_lines(v: &Value, out: &mut Vec<String>) {
    match v {
        Value::String(s) => out.push(s.to_string()),
        Value::Array(items) => {
            for item in items.iter().take(150) { plain_lines(item, out); }
        }
        Value::Object(map) => {
            for key in ["text", "content", "output", "lines", "data", "rows", "value"] {
                if let Some(value) = map.get(key) { plain_lines(value, out); }
            }
        }
        _ => {}
    }
}

fn clean_line(raw: &str) -> String {
    // Minimal VT escape removal, plus control/bidi filtering. Never render terminal escapes.
    let mut result = String::new();
    let mut chars = raw.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\u{1b}' {
            if chars.next() == Some('[') {
                for a in chars.by_ref() { if ('@'..='~').contains(&a) { break; } }
            }
            continue;
        }
        if !c.is_control() && !matches!(c, '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}') {
            result.push(c);
        }
    }
    result.trim().to_owned()
}

fn find_recap(value: &Value) -> Option<String> {
    let mut blocks = Vec::new();
    plain_lines(value, &mut blocks);
    let lines: Vec<String> = blocks.iter().flat_map(|s| s.lines()).map(clean_line).collect();
    for (i, line) in lines.iter().enumerate().rev() {
        let lower = line.to_ascii_lowercase();
        if let Some(pos) = lower.find("recap:") {
            let rest = line.get(pos + 6..).unwrap_or("").trim();
            let text = if rest.is_empty() { lines.get(i + 1).map(String::as_str).unwrap_or("") } else { rest };
            let text = text.trim().trim_start_matches(&['-', ':', ' '][..]);
            if !text.is_empty() {
                let trimmed: String = text.chars().take(90).collect();
                return Some(if text.chars().count() > 90 { format!("{trimmed}…") } else { trimmed });
            }
        }
    }
    None
}

fn transition(tx: &TaggedSender, id: AgentId, before: Option<&str>, after: &str) {
    if before == Some("blocked") {
        emit(tx, AgentEvent::UserActionResolved { agent_id: id, by: Resolution::Call(WAIT_TOOL_ID.into()) });
    }
    if before == Some("working") {
        emit(tx, AgentEvent::ToolUseEnd { agent_id: id, tool_use_id: Some(LIVE_TOOL_ID.into()) });
    }
    match after {
        "working" => emit(tx, AgentEvent::ToolUseStart { agent_id: id, tool_use_id: Some(LIVE_TOOL_ID.into()), detail: None }),
        "blocked" => emit(tx, AgentEvent::UserActionRequest { agent_id: id, reason: Some("Herdr: intervención requerida".into()), tool_use_id: Some(WAIT_TOOL_ID.into()), tool_name: None, turn: None }),
        _ => {}, // idle/done/unknown both display as idle; no synthetic tokens.
    }
}

fn text_field<'a>(v: &'a Value, keys: &[&str]) -> Option<&'a str> {
    keys.iter().find_map(|key| v.get(*key).and_then(Value::as_str)).filter(|s| !s.is_empty())
}
fn safe_name(s: &str) -> String {
    s.chars().filter(|c| !c.is_control() && !matches!(*c, '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')).take(240).collect()
}
fn tool_source(s: &str) -> &'static str {
    match s.to_ascii_lowercase().as_str() {
        "claude" | "claude-code" => "claude-code",
        "codex" | "codex-cli" => "codex",
        "omp" | "pi" | "oh-my-pi" | "oh my pi" => "omp",
        "opencode" | "open-code" => "opencode",
        "cursor" => "cursor",
        "copilot" | "github-copilot" => "copilot",
        "hermes" => "hermes",
        "kimi" => "kimi",
        "grok" => "grok",
        _ => "opencode", // generic fallback only; label retains real agent name
    }
}
// The CLI /rename is not a Herdr API field by itself. Herdr exposes the
// resulting terminal title when the CLI publishes one; use that first.
fn job_label(item: &Value, pane: &Value, agent: &str, cwd: &Path) -> String {
    let title = text_field(item, &["terminal_title_stripped", "title", "display_agent"])
        .or_else(|| text_field(pane, &["terminal_title_stripped", "title", "display_agent"]))
        .unwrap_or("");
    let valid = !title.is_empty() && !title.eq_ignore_ascii_case(agent)
        && !title.trim().starts_with('/') && !title.contains('\n');
    if valid { return safe_name(title); }
    let fallback = cwd.file_name().and_then(|v| v.to_str()).unwrap_or(agent);
    safe_name(fallback)
}

fn residents(value: &Value) -> HashMap<String, Resident> {
    let snapshot = value.get("snapshot").unwrap_or(value);
    let workspaces = snapshot.get("workspaces").and_then(Value::as_array).cloned().unwrap_or_default();
    let mut roots = HashMap::new();
    for ws in workspaces {
        if let Some(id) = text_field(&ws, &["workspace_id", "id"]) {
            if let Some(path) = text_field(&ws, &["cwd", "path", "root"]) { roots.insert(id.to_owned(), PathBuf::from(path)); }
        }
    }
    let agents = snapshot.get("agents").and_then(Value::as_array).or_else(|| snapshot.get("panes").and_then(Value::as_array));
    let mut out = HashMap::new();
    let Some(agents) = agents else { return out; };
    for item in agents {
        let pane_info = item.get("pane").unwrap_or(item);
        let Some(pane) = text_field(pane_info, &["pane_id", "id"]).or_else(|| text_field(item, &["pane_id"])) else { continue; };
        let status = text_field(item, &["agent_status", "status", "state"])
            .or_else(|| text_field(pane_info, &["agent_status", "status"]))
            .unwrap_or("unknown");
        // A recognized agent can legitimately be in Herdr's `unknown` state.
        if !["working", "blocked", "done", "idle", "unknown"].contains(&status) { continue; }
        let Some(name) = text_field(item, &["agent", "agent_name", "name", "kind"])
            .or_else(|| item.get("agent_session").and_then(|v| text_field(v, &["agent"])))
            .or_else(|| text_field(item, &["display_agent"]))
            .or_else(|| text_field(pane_info, &["agent", "agent_name"])) else { continue; };
        let kind = tool_source(name).to_owned();
        let native_session = item.get("agent_session")
            .and_then(|a| text_field(a, &["value", "agent_session_id"]))
            .unwrap_or(pane);
        let session = format!("herdr:{pane}:{native_session}");
        let id = AgentId::from_parts(&kind, &session);
        let workspace_id = text_field(item, &["workspace_id"]).or_else(|| text_field(pane_info, &["workspace_id"]));
        let cwd = text_field(item, &["foreground_cwd", "cwd"])
            .or_else(|| text_field(pane_info, &["foreground_cwd", "cwd"]))
            .map(PathBuf::from)
            .or_else(|| workspace_id.and_then(|ws| roots.get(ws).cloned()))
            .unwrap_or_else(|| PathBuf::from("/"));
        let label = job_label(item, pane_info, name, &cwd);
        out.insert(pane.to_owned(), Resident {
            pane: pane.to_owned(), id, kind, session, native_session: native_session.to_owned(), cwd,
            name: label, status: status.to_ascii_lowercase(),
            metadata_summary: item.get("tokens").and_then(|v| text_field(v, &["summary", "recap"]))
                .or_else(|| pane_info.get("tokens").and_then(|v| text_field(v, &["summary", "recap"])))
                .map(safe_name),
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn normalizes_panes_without_duplicate_ids() {
        let data = json!({"panes":[
            {"pane_id":"w1:p1","agent":"omp","agent_status":"working","cwd":"/a"},
            {"pane_id":"w1:p2","agent":"omp","agent_status":"blocked","cwd":"/b"},
            {"pane_id":"w1:p3","agent_status":"unknown"}
        ]});
        let a = residents(&data);
        assert_eq!(a.len(), 2);
        assert_ne!(a["w1:p1"].id, a["w1:p2"].id);
        assert_eq!(a["w1:p1"].kind, "omp");
    }
    #[test]
    fn snapshot_from_real_agent_records() {
        let data = json!({"snapshot":{"agents":[
          {"pane_id":"w1:p1","workspace_id":"w1","agent":"pi","agent_status":"idle"},
          {"pane_id":"w1:p2","agent":"opencode","agent_status":"unknown"}
        ], "workspaces":[{"workspace_id":"w1","path":"/proj"}]}});
        let a = residents(&data);
        assert_eq!(a.len(), 2);
        assert_eq!(a["w1:p1"].cwd, PathBuf::from("/proj"));
        assert_eq!(a["w1:p2"].status, "unknown");
    }
    #[test]
    fn uses_title_as_job_label() {
        let data = json!({"panes":[{"pane_id":"w1:p1","agent":"claude",
            "agent_status":"idle","terminal_title_stripped":"Salesforce propuesta",
            "cwd":"/work/repo"}]});
        assert_eq!(residents(&data)["w1:p1"].name, "Salesforce propuesta");
    }
    #[test]
    fn recap_is_explicit_not_generated() {
        assert_eq!(find_recap(&json!({"text":"※ recap: Preparando propuesta Salesforce"})),
            Some("Preparando propuesta Salesforce".into()));
        assert_eq!(find_recap(&json!({"text":"Trabajando con ventas"})), None);
    }
    #[test]
    fn no_synthetic_agent_without_identity() {
        assert!(residents(&json!({"panes":[{"pane_id":"w1:p4","agent_status":"working"}]})).is_empty());
    }
}
