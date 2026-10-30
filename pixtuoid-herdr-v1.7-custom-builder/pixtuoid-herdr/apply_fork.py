#!/usr/bin/env python3
"""Apply narrowly-scoped Pixtuoid Herdr V1 changes to an upstream checkout.

No network operations, no post-install scripts, no changes to existing agent settings.
"""
from pathlib import Path
import argparse
import shutil
import sys


def replace_one(path: Path, before: str, after: str):
    text = path.read_text()
    if after in text:
        print(f"already applied: {path}")
        return
    count = text.count(before)
    if count != 1:
        raise ValueError(f"Expected one anchor ({count} found): {path}: {before[:100]!r}")
    path.write_text(text.replace(before, after, 1))
    print("modified:", path)


def main():
    parser = argparse.ArgumentParser(description="Apply the Herdr-only source to a Pixtuoid checkout")
    parser.add_argument("checkout", type=Path, help="the cloned upstream pixtuoid root")
    args = parser.parse_args()
    root = args.checkout.expanduser().resolve()
    lib = root / "crates/pixtuoid/src/lib.rs"
    pipe = root / "crates/pixtuoid/src/runtime/pipeline.rs"
    focus = root / "crates/pixtuoid/src/focus/mod.rs"
    window = root / "crates/pixtuoid/src/floating/window.rs"
    tooltip = root / "crates/pixtuoid-scene/src/tooltip.rs"
    badge = root / "crates/pixtuoid-scene/src/badge.rs"
    compose = root / "crates/pixtuoid-scene/src/display/compose.rs"
    if not all(f.is_file() for f in (lib, pipe, focus, window, tooltip, badge, compose)):
        sys.exit("Not a recognized Pixtuoid checkout; no changes made")

    # Validate every anchor before modifying *anything*.
    anchors = [
        (lib, 'pub(crate) mod graphics;', 'pub(crate) mod graphics;\n\npub(crate) mod herdr;'),
        (pipe, '    let sources = build_source_set(socket_path, Some(presence_tx));',
         '''    // Optional Herdr-only source. Ordinary Pixtuoid is unchanged when disabled.
    let herdr_only = crate::herdr::enabled();
    if herdr_only {
        for source in pixtuoid_core::source::registry::registered_source_names() {
            connected.set(source, true);
        }
    }
    let sources = if herdr_only { Vec::new() } else { build_source_set(socket_path, Some(presence_tx)) };'''),
        (pipe, '    manager.spawn_with_health(tx, health_tx);',
         '''    if herdr_only {
        crate::herdr::start(tx.clone());
        // Keep the health watch alive; this mode intentionally has no SourceManager members.
        let keep_health = health_tx.clone();
        tokio::spawn(async move {
            let _keep_health = keep_health;
            std::future::pending::<()>().await;
        });
    }
    manager.spawn_with_health(tx, health_tx);'''),
        (focus, '''pub(crate) fn focus_slot(slot: &AgentSlot) {
    focus_agent(slot, &FocusPaths::from_env(), &OsProcessTable, activate_os);
}''',
         '''pub(crate) fn focus_slot(slot: &AgentSlot) {
    // Click-to-focus a Herdr pane before trying the normal terminal PID route.
    if crate::herdr::focus_slot(slot.agent_id) { return; }
    focus_agent(slot, &FocusPaths::from_env(), &OsProcessTable, activate_os);
}'''),
        (tooltip, '''    pub fn label(text: &str) -> Self {''', '''    pub fn with_herdr_recap(mut self, note: &str) -> Self {
        let chars: Vec<char> = note.chars().filter(|c| !c.is_control()).take(240).collect();
        if !chars.is_empty() {
            self.rows.push(TipRow::Rule);
            for (i, part) in chars.chunks(60).enumerate() {
                let line: String = part.iter().copied().collect();
                let prefix = if i == 0 { "↪ " } else { "  " };
                self.rows.push(TipRow::Spans(vec![TipSpan::new(
                    format!("{prefix}{line}"), TipTone::Text,
                )]));
            }
        }
        self
    }

    pub fn label(text: &str) -> Self {'''),
        (window, '    cursor_in: bool,', '    cursor_in: bool,\n    /// Do not walk when the pointer is inside; sprite frames still animate.\n    herdr_hovered: bool,'),
        (window, '            cursor_in: false,', '            cursor_in: false,\n            herdr_hovered: false,'),
        (window, '        let floor_meta = FloorMeta::ground().with_motion(self.motion);',
         '        let floor_meta = FloorMeta::ground().with_motion(if self.herdr_hovered { pixtuoid_scene::anim::Motion::Still } else { self.motion });'),
        (window, '            WindowEvent::CursorMoved { position, .. } => {\n                self.cursor = position;',
         '            WindowEvent::CursorMoved { position, .. } => {\n                if crate::herdr::enabled() && !self.herdr_hovered {\n                    self.herdr_hovered = true;\n                    self.request_redraw();\n                }\n                self.cursor = position;'),
        (window, '            WindowEvent::CursorLeft { .. } => {\n                self.cursor_in = false;',
         '            WindowEvent::CursorLeft { .. } => {\n                self.herdr_hovered = false;\n                self.request_redraw();\n                self.cursor_in = false;'),
        (root / 'crates/pixtuoid-scene/src/display/compose.rs',
         '        let run = badge.run();\n        badges.push(badge);\n        order.push((\n            topmost_span(badge_plate(&run, pen), pen),\n            PieceKind::Text { run },\n        ));',
         '        let run = badge.run();\n        badges.push(badge);\n        if std::env::var("PIXTUOID_HERDR").as_deref() == Ok("1") {\n            // Wrap Herdr\'s complete job name above the character. Standard\n            // Pixtuoid preserves its original compact name badges.\n            let mut rows: Vec<String> = Vec::new();\n            let mut row = String::new();\n            for (cluster, width) in crate::display::text::clusters(&run.text()) {\n                if !row.is_empty() && crate::display::text::cells(&row).saturating_add(width) > 20 {\n                    rows.push(std::mem::take(&mut row));\n                }\n                row.push_str(cluster);\n            }\n            if !row.is_empty() { rows.push(row); }\n            for (idx, line) in rows.iter().enumerate() {\n                let mut wrapped = run.clone();\n                wrapped.spans = vec![crate::display::text::TextSpan::new(line, theme.ui.label_idle)];\n                // The ink of the original badge follows Herdr\'s activity state.\n                if let Some(span) = wrapped.spans.first_mut() {\n                    span.ink = run.spans[0].ink;\n                }\n                let lines_above = rows.len().saturating_sub(idx + 1);\n                let lift = u16::try_from(lines_above).unwrap_or(u16::MAX)\n                    .saturating_mul(crate::layout::CELL_ROWS);\n                wrapped.at.y = wrapped.at.y.saturating_sub(lift);\n                order.push((\n                    topmost_span(badge_plate(&wrapped, pen), pen),\n                    PieceKind::Text { run: wrapped },\n                ));\n            }\n        } else {\n            order.push((\n                topmost_span(badge_plate(&run, pen), pen),\n                PieceKind::Text { run },\n            ));\n        }'),
        (root / 'crates/pixtuoid-scene/src/badge.rs',
         '        truncate_label(&raw, BADGE_CELLS.saturating_sub(marker)).into_owned()',
         '''        if std::env::var("PIXTUOID_HERDR").as_deref() == Ok("1") {
            // Herdr jobs need the whole rename. The original desk-width cap
            // remains for standard Pixtuoid.
            raw.into_owned()
        } else {
            truncate_label(&raw, BADGE_CELLS.saturating_sub(marker)).into_owned()
        }'''),
        (window, '''                    pixtuoid_scene::tooltip::for_hit(hit, &shown)''', '''                    let recap = if let pixtuoid_scene::hit::SceneHit::Figure(
                        pixtuoid_scene::display::HoverTarget::Agent(id)
                    ) = &hit {
                        crate::herdr::note_for(*id)
                    } else {
                        None
                    };
                    pixtuoid_scene::tooltip::for_hit(hit, &shown).map(|tip| {
                        if let Some(note) = recap { tip.with_herdr_recap(&note) } else { tip }
                    })'''),
    ]
    for path, before, after in anchors:
        text = path.read_text()
        if text.count(before) != 1 and after not in text:
            sys.exit(f"Upstream mismatch in {path}; no files have been changed")
    dst = root / "crates/pixtuoid/src/herdr.rs"
    if dst.exists() and dst.read_bytes() != (Path(__file__).parent / "overlay/herdr.rs").read_bytes():
        sys.exit(f"Refusing to overwrite a modified {dst}")
    if not dst.exists():
        shutil.copyfile(Path(__file__).parent / "overlay/herdr.rs", dst)
        print("added:", dst)
    for path, before, after in anchors:
        replace_one(path, before, after)
    # Regression guard: do not remove any original renderer modules.
    lib_body = lib.read_text()
    for required in ("pub(crate) mod graphics;", "pub(crate) mod floating;", "pub(crate) mod tui;", "pub(crate) mod herdr;"):
        if required not in lib_body:
            sys.exit(f"Patch regression: missing module {required!r}")
    print("\nNext: cargo build --locked --release -p pixtuoid")


if __name__ == "__main__":
    main()
