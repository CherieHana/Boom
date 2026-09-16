"""透明桌面覆盖层：加载假 DSH 页面，按挂件实际可见区域打遮罩实现鼠标穿透。

要点（都是阶段 0 验证出来的）：
  - QtWebEngine 回传 JS 对象不可靠，统一 `JSON.stringify` 成字符串再解析
  - 挂件用角色图 alpha 判定点击命中，透明处穿越；遮罩只圈"挂件本体 + 展开的面板"
  - 区域每 150ms 轮询一次，变化才 setMask（挂件拖动/弹面板都会跟着变）
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QRegion
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

from .config import webengine_dir


def _log_line(message: str) -> None:
    try:
        from .config import log_dir

        with (log_dir() / "whalepet.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{message}\n")
    except Exception:
        pass

# 只圈"挂件本体 + 真正可见且能点到的面板"
REGION_JS = r"""
(() => {
  const out = [];
  const vw = window.innerWidth, vh = window.innerHeight;
  const root = document.querySelector('.dshwv-root');
  if (!root) return '[]';
  const rr = root.getBoundingClientRect();
  if (rr.width >= 4 && rr.height >= 4) out.push([rr.left, rr.top, rr.right, rr.bottom]);

  const cand = [];
  const add = (el) => { if (el && cand.indexOf(el) < 0) cand.push(el); };
  for (const el of document.querySelectorAll('.dshwv-pop.dshwv-pop-open')) add(el);
  for (const el of document.querySelectorAll(
    '[class*="dshwv-mask"],[class*="dshwv-menu"],[class*="dshwv-panel"],' +
    '[class*="dshwv-dialog"],[class*="dshwv-usage"],[class*="dshwv-bubmask"],' +
    '[class*="dshwv-rolelist"],[class*="dshwv-audiolist"],[class*="dshwv-cropmask"],' +
    '[class*="dshwv-confirmmask"],[class*="dshwv-audiomask"],[class*="dshwv-snapmask"],' +
    '[class*="dshwv-resmask"],[class*="dshwv-qedit"],[class*="dshwv-custmenu"]'
  )) add(el);

  // 只保留最外层：真正带 padding/边框/圆角/投影的是外层盒子（如 .dshwv-menu），
  // 内层（如 .dshwv-menuview）只是内容区。用内层当遮罩会把边框和圆角裁掉
  // ——鲸鱼调小时鲸鱼自身的遮罩盖不住，就会看到"边框显示不全"。
  const outermost = cand.filter(
    (el) => !cand.some((other) => other !== el && other.contains(el))
  );
  const PAD = 10; // 给边框/圆角/投影留边，避免遮罩把面板边缘切平
  for (const el of outermost) {
    const b = el.getBoundingClientRect();
    if (b.width < 6 || b.height < 6) continue;
    const pts = [[0.5, 0.5], [0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]];
    let hit = false;
    for (const [fx, fy] of pts) {
      const x = b.left + b.width * fx, y = b.top + b.height * fy;
      if (x < 0 || y < 0 || x > vw || y > vh) continue;
      const t = document.elementFromPoint(x, y);
      if (t && (t === el || el.contains(t))) { hit = true; break; }
    }
    if (hit) out.push([b.left - PAD, b.top - PAD, b.right + PAD, b.bottom + PAD]);
  }
  return JSON.stringify(out.map((a) => a.map(Math.round)));
})()
"""


class Overlay(QWidget):
    """全屏透明置顶窗口；遮罩外的点击直接落到桌面。"""

    regions_changed = Signal(list)
    page_ready = Signal(bool)

    def __init__(self, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("WhalePet")

        self._profile = QWebEngineProfile("whalepet", self)
        self._profile.setPersistentStoragePath(str(webengine_dir() / "storage"))
        self._profile.setCachePath(str(webengine_dir() / "cache"))
        self._profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
        self._profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)

        self.view = QWebEngineView(self)
        self.view.setPage(self._make_page())
        self.view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.view.page().setBackgroundColor(Qt.transparent)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)

        self._regions: list[tuple[int, int, int, int]] = []
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll_regions)
        self.view.loadFinished.connect(self._on_loaded)
        self.view.loadProgress.connect(lambda p: _log_line(f"OVERLAY loadProgress={p}"))
        self.view.renderProcessTerminated.connect(
            lambda status, code: _log_line(f"OVERLAY renderProcessTerminated status={status} code={code}")
        )
        self.view.load(QUrl(url))

    def _make_page(self):
        from PySide6.QtWebEngineCore import QWebEnginePage

        profile = self._profile

        class _Page(QWebEnginePage):
            def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802, ANN001
                # 挂件自身会打一些无伤大雅的告警，这里只留痕不弹窗
                if "willReadFrequently" in message:
                    return
                _log_line(f"OVERLAY js[{level}] {str(message)[:200]}")

        return _Page(profile, self)

    # ------------------------------------------------------------------ 窗口
    def apply_screen(self, geometry) -> None:
        self.setGeometry(geometry)
        self.view.setGeometry(0, 0, geometry.width(), geometry.height())

    def _on_loaded(self, ok: bool) -> None:
        _log_line(f"OVERLAY loadFinished ok={ok} url={self.view.url().toString()}")
        self.page_ready.emit(bool(ok))
        if ok:
            self._timer.start()

    def _poll_regions(self) -> None:
        self.view.page().runJavaScript(REGION_JS, 0, self._apply_regions)

    def _apply_regions(self, raw: Any) -> None:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) and raw else []
        except Exception:
            parsed = []
        regions = [tuple(int(v) for v in r) for r in parsed if isinstance(r, list) and len(r) == 4]
        if regions == self._regions:
            return
        self._regions = regions
        mask = QRegion()
        for left, top, right, bottom in regions:
            mask = mask.united(QRegion(left, top, right - left, bottom - top))
        if mask.isEmpty():
            # 挂件还没渲染出来：先不遮，避免把整个窗口藏掉
            self.clearMask()
        else:
            self.setMask(mask)
        self.regions_changed.emit(list(regions))

    # ------------------------------------------------------------------ 其它
    def regions(self) -> list[tuple[int, int, int, int]]:
        return list(self._regions)

    def widget_ready(self) -> bool:
        return bool(self._regions)

    def stop(self) -> None:
        self._timer.stop()
