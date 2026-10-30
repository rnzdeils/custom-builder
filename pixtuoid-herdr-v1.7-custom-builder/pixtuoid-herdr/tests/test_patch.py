import tempfile, pathlib, unittest, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
class PatchTests(unittest.TestCase):
    def test_synthetic_upstream(self):
        with tempfile.TemporaryDirectory() as d:
            base=pathlib.Path(d)
            (base/'crates/pixtuoid/src/runtime').mkdir(parents=True)
            (base/'crates/pixtuoid/src/focus').mkdir()
            (base/'crates/pixtuoid/src/floating').mkdir()
            (base/'crates/pixtuoid-scene/src').mkdir(parents=True)
            (base/'crates/pixtuoid/src/lib.rs').write_text('pub(crate) mod floating;\npub(crate) mod graphics;\npub(crate) mod tui;\n')
            (base/'crates/pixtuoid/src/runtime/pipeline.rs').write_text('    let sources = build_source_set(socket_path, Some(presence_tx));\n    manager.spawn_with_health(tx, health_tx);')
            (base/'crates/pixtuoid/src/focus/mod.rs').write_text('pub(crate) fn focus_slot(slot: &AgentSlot) {\n    focus_agent(slot, &FocusPaths::from_env(), &OsProcessTable, activate_os);\n}')
            (base/'crates/pixtuoid/src/floating/window.rs').write_text('    cursor_in: bool,\n            cursor_in: false,\n        let floor_meta = FloorMeta::ground().with_motion(self.motion);\n        // ONE clock read, so the overlays below annotate the frame actually rendered.\n        let now = self.ui.now();\n            WindowEvent::CursorMoved { position, .. } => {\n                self.cursor = position;\n            WindowEvent::CursorLeft { .. } => {\n                self.cursor_in = false;\n                    pixtuoid_scene::tooltip::for_hit(hit, &shown)')
            (base/'crates/pixtuoid-scene/src/tooltip.rs').write_text('    pub fn label(text: &str) -> Self {')
            (base/'crates/pixtuoid-scene/src/badge.rs').write_text('        truncate_label(&raw, BADGE_CELLS.saturating_sub(marker)).into_owned()')
            (base/'crates/pixtuoid-scene/src/display').mkdir()
            (base/'crates/pixtuoid-scene/src/display/compose.rs').write_text('        let run = badge.run();\n        badges.push(badge);\n        order.push((\n            topmost_span(badge_plate(&run, pen), pen),\n            PieceKind::Text { run },\n        ));')
            for _ in range(2):
                cp=subprocess.run([sys.executable,str(ROOT/'apply_fork.py'),str(base)],capture_output=True,text=True)
                self.assertEqual(cp.returncode,0,cp.stderr+cp.stdout)
            lib_text = (base/'crates/pixtuoid/src/lib.rs').read_text()
            for required in ('pub(crate) mod graphics;', 'pub(crate) mod floating;', 'pub(crate) mod tui;', 'pub(crate) mod herdr;'):
                self.assertEqual(lib_text.count(required), 1, f"missing or duplicate: {required}")
            self.assertIn('crate::herdr::start', (base/'crates/pixtuoid/src/runtime/pipeline.rs').read_text())
            self.assertTrue((base/'crates/pixtuoid/src/herdr.rs').exists())
            self.assertIn('note_for', (base/'crates/pixtuoid/src/floating/window.rs').read_text())
            self.assertIn('with_herdr_recap', (base/'crates/pixtuoid-scene/src/tooltip.rs').read_text())
            self.assertIn('rows: Vec<String>', (base/'crates/pixtuoid-scene/src/display/compose.rs').read_text())
            window_body = (base/'crates/pixtuoid/src/floating/window.rs').read_text()
            self.assertIn('herdr_hovered', window_body)
            self.assertIn('pixtuoid_scene::anim::Motion::Still', window_body)
            self.assertIn('let now = self.ui.now();', window_body, 'The sprite animation clock must stay live')
            self.assertNotIn('herdr_hover_time', window_body)
    def test_old_regression_never_deletes_graphics(self):
        script = (ROOT / 'apply_fork.py').read_text()
        self.assertIn("'pub(crate) mod graphics;\\n\\npub(crate) mod herdr;'", script)
        self.assertNotIn("(lib, 'pub(crate) mod graphics;', 'pub(crate) mod herdr;')", script)
    def test_refuses_unknown_upstream(self):
        with tempfile.TemporaryDirectory() as d:
            base=pathlib.Path(d)
            for f in ['lib.rs','runtime/pipeline.rs','focus/mod.rs']:
                p=base/'crates/pixtuoid/src'/f
                p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text('unknown upstream')
            cp=subprocess.run([sys.executable,str(ROOT/'apply_fork.py'),str(base)],capture_output=True,text=True)
            self.assertNotEqual(cp.returncode,0)
            self.assertFalse((base/'crates/pixtuoid/src/herdr.rs').exists())
if __name__=='__main__': unittest.main()

class UXTests(unittest.TestCase):
    def test_floating_geometry_once_preserves_config(self):
        from tempfile import TemporaryDirectory
        sys.path.insert(0, str(ROOT))
        from configure_floating import configure
        with TemporaryDirectory() as td:
            root=pathlib.Path(td)
            cfg=root/'pixtuoid/config.toml'
            cfg.parent.mkdir()
            cfg.write_text('theme = "normal"\n[floating]\nwidth = 320\nheight = 300\n[sources]\nclaude = true\n')
            self.assertTrue(configure(root))
            data=cfg.read_text()
            self.assertIn('width = 1280',data)
            self.assertIn('height = 850',data)
            self.assertIn('zoom = 2',data)
            self.assertIn('[sources]\nclaude = true',data)
            self.assertFalse(configure(root))

    def test_claude_last_message_is_bounded(self):
        overlay=(ROOT/'overlay/herdr.rs').read_text()
        self.assertIn('fn last_claude_reply',overlay)
        self.assertIn('saturating_sub(256 * 1024)',overlay)
        self.assertIn('meta.len()',overlay)
        self.assertIn('"assistant"',overlay)
        self.assertIn('"working"',overlay)

    def test_recap_is_bounded_and_readonly(self):
        overlay=(ROOT/'overlay/herdr.rs').read_text()
        self.assertIn('"pane.read"', overlay)
        self.assertIn('"lines": 80', overlay)
        self.assertIn('Duration::from_secs(60)', overlay)
        self.assertIn('name: label', overlay)
        self.assertNotIn('"pane.send_text"', overlay)

class HoverAnimationTests(unittest.TestCase):
    def test_no_time_freezing_patch(self):
        script = (ROOT/'apply_fork.py').read_text()
        self.assertNotIn('unwrap_or_else(|| self.ui.now())', script)
        self.assertIn('Motion::Still', script)
        self.assertIn('herdr_hovered', script)
