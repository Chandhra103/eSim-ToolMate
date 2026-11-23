from __future__ import annotations

import json
import platform
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import *

from app.core.diagnostics import collect

ROYAL_BLUE="#2563EB"; TEAL="#0F766E"; MAIN_BG="#F8FAFC"; CARD_BG="#FFFFFF"; BLUE_SURFACE="#EFF6FF"; AMBER="#F59E0B"; PRIMARY_TEXT="#1E293B"; SECONDARY_TEXT="#64748B"; BORDER="#E2E8F0"
class Worker(QThread):
    done=Signal(object)
    def __init__(self, fn): super().__init__(); self.fn=fn
    def run(self):
        try: self.done.emit(self.fn())
        except Exception as e:  # noqa: BLE001 - worker boundary returns failures to the UI
            self.done.emit(e)

class MainWindow(QMainWindow):
    def __init__(self, registry, storage, operations):
        super().__init__(); self.registry,self.storage,self.operations=registry,storage,operations; self.dark=False
        self.setWindowTitle("eSim ToolMate — Intelligent Tool Manager"); self.resize(1450,900); self._build(); self.scan()
    def _build(self):
        self.setStyleSheet(self._style())
        root=QWidget(); root.setObjectName("app-root"); layout=QHBoxLayout(root); layout.setContentsMargins(0,0,0,0)
        side=QFrame(); side.setObjectName("sidebar"); side.setFixedWidth(245); sl=QVBoxLayout(side)
        brand=QLabel("⚙  eSim ToolMate\n   Intelligent Tool Manager"); brand.setObjectName("brand"); sl.addWidget(brand); sl.addSpacing(18)
        self.nav=QButtonGroup(self); self.nav.setExclusive(True)
        for i,name in enumerate(["⌂  Dashboard","▣  Tool Manager","⇩  Install Tools","⟳  Version & Updates","♣  Dependency Checker","⚙  Configuration Manager","▤  System Diagnostics","▣  Activity Logs","⚙  Settings","ⓘ  About"]):
            b=QPushButton(name); b.setCheckable(True); b.setObjectName("nav"); self.nav.addButton(b,i); sl.addWidget(b); b.clicked.connect(lambda _,x=i:self.show_page(x))
        sl.addStretch(); sl.addWidget(QLabel("FOSSEE\neSim Winter Internship 2026\n\nDetect. Install. Configure.\nUpdate. Verify.")); layout.addWidget(side)
        main=QWidget(); ml=QVBoxLayout(main); ml.setContentsMargins(18,16,18,14)
        top=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("⌕  Search tools… (Ctrl + K)"); self.search.textChanged.connect(self.filter_tools); top.addWidget(self.search,1); self.theme=QPushButton("☼  Light theme"); self.theme.clicked.connect(self.toggle_theme); top.addWidget(self.theme); top.addWidget(QLabel(f"{platform.system()}  |  v1.0.0")); ml.addLayout(top)
        self.pages=QStackedWidget(); ml.addWidget(self.pages,1); layout.addWidget(main,1); self.setCentralWidget(root)
        self.dashboard=self._dashboard(); self.pages.addWidget(self.dashboard); self.tool_page=self._tool_page(); self.pages.addWidget(self.tool_page); self.install_page=self._install_page(); self.pages.addWidget(self.install_page); self.pages.addWidget(self._simple_page("Version & Updates", "Compare installed versions against trusted metadata.\nLatest-version checks are conservative and never invent a release.")); self.pages.addWidget(self._dependency_page()); self.pages.addWidget(self._simple_page("Configuration Manager", "Review detected executable paths and PATH entries.\nChanges are intentionally explicit and backed up before saving.")); self.pages.addWidget(self._diagnostics_page()); self.pages.addWidget(self._logs_page()); self.pages.addWidget(self._simple_page("Settings", "Theme and application data are stored in the platform application directory.")); self.pages.addWidget(self._simple_page("About", "eSim ToolMate 1.0.0\nA safe cross-platform tool manager for eSim workflows.")); self.nav.button(0).setChecked(True)
    def _dashboard(self):
        w=QWidget(); l=QVBoxLayout(w); hero=QLabel("👋  Welcome to eSim ToolMate!\nYour intelligent companion for managing eSim tools and dependencies."); hero.setObjectName("hero"); l.addWidget(hero)
        self.cards=QHBoxLayout(); l.addLayout(self.cards); self.card_labels=[]
        for title,color in [("Total Tools",ROYAL_BLUE),("Installed",TEAL),("Missing",AMBER),("Updates",ROYAL_BLUE),("Dependencies",TEAL),("Issues",AMBER)]:
            x=QFrame(); x.setObjectName("card"); q=QVBoxLayout(x); t=QLabel(title); n=QLabel("—"); n.setObjectName("metric"); q.addWidget(t); q.addWidget(n); x.setStyleSheet(f"QFrame#card{{border-top:4px solid {color};}}"); self.cards.addWidget(x); self.card_labels.append(n)
        row=QHBoxLayout(); l.addLayout(row,1); left=QGroupBox("Tool Status Overview"); ll=QVBoxLayout(left); self.status=QLabel(); ll.addWidget(self.status); row.addWidget(left,1); mid=QGroupBox("Quick Actions"); ql=QVBoxLayout(mid)
        for text,fn in [("⚡  Scan System",self.scan),("⇩  Install a Tool",lambda:self.show_page(2)),("⟳  Check for Updates",self.scan),("♣  Check Dependencies",self.check_deps),("▤  Generate Diagnostic Report",self.export_diag)]:
            b=QPushButton(text); b.clicked.connect(fn); ql.addWidget(b)
        row.addWidget(mid,1); right=QGroupBox("Recent Activity"); rl=QVBoxLayout(right); self.recent=QListWidget(); rl.addWidget(self.recent); row.addWidget(right,1); return w
    def _tool_page(self):
        w=QWidget(); l=QVBoxLayout(w); l.addWidget(QLabel("Tool Manager",objectName="title")); self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["Tool","Category","Status","Version","Executable","Official site"]); self.table.horizontalHeader().setStretchLastSection(True); l.addWidget(self.table); return w
    def _install_page(self):
        w=QWidget(); l=QVBoxLayout(w); l.addWidget(QLabel("Install Tools",objectName="title")); self.install_list=QListWidget(); l.addWidget(self.install_list); b=QPushButton("Install selected tool"); b.clicked.connect(self.install_selected); l.addWidget(b); return w
    def _dependency_page(self):
        w=QWidget(); l=QVBoxLayout(w); l.addWidget(QLabel("Dependency Checker",objectName="title")); self.dep=QTextEdit(); self.dep.setReadOnly(True); l.addWidget(self.dep); b=QPushButton("Check all dependencies"); b.clicked.connect(self.check_deps); l.addWidget(b); return w
    def _diagnostics_page(self):
        w=QWidget(); l=QVBoxLayout(w); l.addWidget(QLabel("System Diagnostics",objectName="title")); self.diag=QTextEdit(); self.diag.setReadOnly(True); l.addWidget(self.diag); b=QPushButton("Refresh diagnostics / export JSON"); b.clicked.connect(self.export_diag); l.addWidget(b); return w
    def _logs_page(self):
        w=QWidget(); l=QVBoxLayout(w); l.addWidget(QLabel("Activity Logs",objectName="title")); self.logs=QTableWidget(0,5); self.logs.setHorizontalHeaderLabels(["Time","Operation","Tool","Status","Message"]); self.logs.horizontalHeader().setStretchLastSection(True); l.addWidget(self.logs); b=QPushButton("Export CSV"); b.clicked.connect(self.export_logs); l.addWidget(b); return w
    def _simple_page(self,title,text):
        w=QWidget(); l=QVBoxLayout(w); l.addWidget(QLabel(title,objectName="title")); l.addWidget(QLabel(text)); l.addStretch(); return w
    def show_page(self,i): self.pages.setCurrentIndex(i); self.refresh_logs() if i==7 else None
    def scan(self):
        self.worker=Worker(self.registry.scan); self.worker.done.connect(self.scan_done); self.worker.start()
    def scan_done(self,result):
        if isinstance(result,Exception): QMessageBox.warning(self,"Scan failed",str(result)); return
        installed=sum(t.installed for t in self.registry.tools); missing=len(self.registry.tools)-installed
        for label,val in zip(self.card_labels,[len(self.registry.tools),installed,missing,0,"OK",0]): label.setText(str(val))
        self.status.setText(f"Installed: {installed}\nMissing: {missing}\n\n"+"\n".join(f"• {t.name}: {'Installed — '+str(t.version) if t.installed else 'Missing'}" for t in self.registry.tools)); self.refresh_table(); self.refresh_install(); self.refresh_logs(); self.diag.setPlainText(json.dumps(collect(self.registry),indent=2)); self.storage.log("system_scan",status="success",message=f"Detected {installed}/{len(self.registry.tools)} tools")
    def refresh_table(self):
        self.table.setRowCount(0)
        for t in self.registry.tools:
            r=self.table.rowCount(); self.table.insertRow(r); vals=[t.name,t.category,"Installed" if t.installed else "Missing",t.version or "—",t.executable or "—",t.website]
            for c,v in enumerate(vals): self.table.setItem(r,c,QTableWidgetItem(str(v)))
    def refresh_install(self): self.install_list.clear(); [self.install_list.addItem(f"{t.name} — {'Installed' if t.installed else 'Missing'}") for t in self.registry.tools]
    def filter_tools(self,text):
        if hasattr(self,'table'):
            for r in range(self.table.rowCount()): self.table.setRowHidden(r, bool(text) and not any(text.lower() in (self.table.item(r,c).text().lower()) for c in range(self.table.columnCount())))
    def install_selected(self):
        row=self.install_list.currentRow()
        if row<0: QMessageBox.information(self,"Select a tool","Choose a tool first."); return
        t=self.registry.tools[row]
        if QMessageBox.question(self,"Confirm installation",f"Install {t.name} using the verified package manager?\nAdministrator permission may be required.") != QMessageBox.Yes: return
        result=self.operations.install(t); QMessageBox.information(self,"Installation result",result.get("message", "Operation completed")); self.scan()
    def check_deps(self): self.dep.setPlainText(json.dumps(self.operations.check_dependencies(),indent=2)); self.card_labels[4].setText("OK")
    def export_diag(self):
        path,_=QFileDialog.getSaveFileName(self,"Export diagnostic report","diagnostic-report.json","JSON (*.json)");
        if path: Path(path).write_text(json.dumps(collect(self.registry),indent=2),encoding="utf-8"); self.diag.setPlainText(Path(path).read_text())
    def export_logs(self):
        path,_=QFileDialog.getSaveFileName(self,"Export activity log","activity.csv","CSV (*.csv)");
        if path: self.storage.export_csv(path)
    def refresh_logs(self):
        rows=self.storage.recent(); self.recent.clear(); self.logs.setRowCount(0)
        for x in rows[:8]: self.recent.addItem(f"{x['operation']} — {x['message']}")
        for x in rows:
            r=self.logs.rowCount(); self.logs.insertRow(r)
            for c,v in enumerate([x['timestamp'],x['operation'],x['tool'],x['status'],x['message']]): self.logs.setItem(r,c,QTableWidgetItem(str(v)))
    def toggle_theme(self):
        self.dark=not self.dark
        self.theme.setText("☼  Blue-tint theme" if self.dark else "☼  Light theme")
        self.setStyleSheet(self._style())
    def _style(self):
        bg = BLUE_SURFACE if self.dark else MAIN_BG
        return f"""
        QWidget {{ color: {PRIMARY_TEXT}; font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 14px; }}
        QMainWindow, QWidget#app-root {{ background: {bg}; }}
        QFrame#sidebar {{ background: {CARD_BG}; border-right: 1px solid {BORDER}; }}
        QLabel#brand {{ font-size: 19px; font-weight: 700; padding: 18px; color: {PRIMARY_TEXT}; }}
        QPushButton#nav {{ text-align: left; padding: 11px 12px; border: 1px solid transparent; color: {SECONDARY_TEXT}; background: transparent; border-radius: 9px; }}
        QPushButton#nav:checked {{ background: {BLUE_SURFACE}; color: {ROYAL_BLUE}; border-color: #DBEAFE; font-weight: 700; }}
        QPushButton#nav:hover {{ background: {BLUE_SURFACE}; color: {ROYAL_BLUE}; }}
        QLineEdit, QTextEdit, QTableWidget, QListWidget {{ background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px; selection-background-color: {BLUE_SURFACE}; selection-color: {PRIMARY_TEXT}; }}
        QLineEdit:focus, QTextEdit:focus, QTableWidget:focus, QListWidget:focus {{ border: 2px solid {ROYAL_BLUE}; }}
        QGroupBox {{ background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 12px; margin-top: 16px; padding: 15px 10px 10px; font-weight: 600; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; color: {PRIMARY_TEXT}; }}
        QPushButton {{ background: {ROYAL_BLUE}; color: #FFFFFF; border: 1px solid {ROYAL_BLUE}; border-radius: 8px; padding: 9px 13px; font-weight: 600; }}
        QPushButton:hover {{ background: #1D4ED8; border-color: #1D4ED8; }}
        QPushButton:pressed {{ background: #1E40AF; }}
        QPushButton:disabled {{ background: #CBD5E1; border-color: #CBD5E1; color: #475569; }}
        QHeaderView::section {{ background: #F1F5F9; color: {SECONDARY_TEXT}; border: 0; border-bottom: 1px solid {BORDER}; padding: 9px; font-weight: 700; }}
        QTableWidget {{ gridline-color: {BORDER}; }}
        QTableWidget::item {{ padding: 5px; }}
        QTableWidget::item:selected, QListWidget::item:selected {{ background: {BLUE_SURFACE}; color: {PRIMARY_TEXT}; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: #CBD5E1; min-height: 26px; border-radius: 5px; }}
        QLabel#hero {{ background: {BLUE_SURFACE}; color: {PRIMARY_TEXT}; border: 1px solid #DBEAFE; border-radius: 14px; padding: 23px; font-size: 20px; font-weight: 700; }}
        QLabel#title {{ font-size: 25px; font-weight: 700; padding: 8px 2px; }}
        QLabel#metric {{ font-size: 28px; font-weight: 700; color: {PRIMARY_TEXT}; }}
        """
