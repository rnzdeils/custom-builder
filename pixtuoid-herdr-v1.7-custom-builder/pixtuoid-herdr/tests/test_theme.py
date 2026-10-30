import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from apply_soft_gray import transform, tone_channel

class GrayThemeTests(unittest.TestCase):
    def test_only_environment_colors(self):
        src='''pub static NORMAL: Theme = Theme {
    surface: SurfaceColors {
        tile: rgb(220, 170, 100),
        wall: Rgb::new(0xAA,0xBB,0xCC),
    },
    office: OfficeColors { desk: rgb(20, 90, 140), },
    furniture: FurnitureColors { sofa: rgb(70, 35, 15), },
    ui: UiColors { label_idle: rgb(0, 255, 20) },
    tool_glow: ToolGlowColors { edit: rgb(255, 20, 20) },
    source: SourceColors { claude: rgb(255, 90, 50) },
};\n'''
        new,n=transform(src)
        self.assertGreaterEqual(n,4)
        self.assertNotIn('tile: rgb(220, 170, 100)',new)
        self.assertIn('label_idle: rgb(0, 255, 20)',new)
        self.assertIn('edit: rgb(255, 20, 20)',new)
        self.assertIn('claude: rgb(255, 90, 50)',new)
    def test_chroma_reduction(self):
        values=tone_channel(200,100,20)
        self.assertLess(max(values)-min(values),80)
        self.assertNotEqual(values,(200,100,20))

if __name__=='__main__': unittest.main()
