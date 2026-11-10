"""dev_host_ext.py - Playground only.  The test add-ons were written for the Playground's own window; this gives OpenPara's real program window
(core/gpd_app.py, unchanged) the few helpers they use, through the shell-mixin hook (ext.add_shell_mixin).  It lives in the Playground's addons/
folder and is never ported to the release."""


class DevHost:
    quiet = False
    threaded = True
    _restoring = False

    def build_menus(self):
        super().build_menus()
        fm = self.menuBar().actions()[0].menu()
        fm.addSeparator()
        if "voxel" in __import__("addons").tab_kinds():
            fm.addAction("Send this tab's mesh to a new Voxel FEA tab", lambda: self.send_current("voxel"))
        if "tet" in __import__("addons").tab_kinds():
            fm.addAction("Send this tab's mesh to a new Mesh FEA tab", lambda: self.send_current("tet"))

    def has_tab(self, w):
        try:
            return self.tabs.indexOf(w) >= 0
        except RuntimeError:                             # a tab that was closed: Qt has deleted it
            return False

    def title_of(self, w):
        i = self.tabs.indexOf(w) if self.has_tab(w) else -1
        t = self.tabs.tabText(i) if i >= 0 else "(closed)"
        return t[:-2] if t.endswith(" *") else t

    def sources_for(self, requester):
        """What `requester` may import: [(title, tab, 'mesh'|'voxels', info)]."""
        out = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if w is requester:
                continue
            title = self.tabs.tabText(i)
            m = w.provide_mesh() if hasattr(w, "provide_mesh") else None
            if m is not None:
                out.append((title, w, "mesh", f"mesh, {m.n_cells:,} triangles"))
            if getattr(requester, "KIND", "") == "voxel" and getattr(w, "KIND", "") == "voxel":
                v = w.provide_voxels()
                if v is not None:
                    out.append((title, w, "voxels", f"voxels, {v[0].shape[0]}x{v[0].shape[1]}x{v[0].shape[2]}, {v[1]:g} mm"))
        return out

    def send_current(self, kind):
        src = self.tabs.currentWidget()
        m = src.provide_mesh() if hasattr(src, "provide_mesh") else None
        if m is None:
            return None
        title = self.title_of(src)
        w = self.new_addon_tab(kind)
        if w is not None:
            w.set_source_mesh(m, f"tab '{title}' (mesh)", src)
        return w


def register(ext):
    ext.add_shell_mixin(DevHost)
