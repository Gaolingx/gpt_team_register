#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
子号批量加入母号 Workspace 工具
直接读取 OpenAI 子号 JSON（OAuth 格式），一键加入指定 Workspace
"""

import sys
import json
import time
import base64
import threading
from datetime import datetime

import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QPushButton, QTextEdit, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QLineEdit, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

# ================= 深色主题 =================
STYLE_DARK = """
QMainWindow { background-color: #1e1e2e; }
QGroupBox {
    color: #cdd6f4; font-weight: bold; border: 2px solid #45475a;
    border-radius: 8px; margin-top: 12px; padding-top: 10px; background-color: #1e1e2e;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #89b4fa;
}
QLabel { color: #cdd6f4; }
QLineEdit, QTextEdit {
    background-color: #11111b; color: #cdd6f4; border: 1px solid #45475a;
    border-radius: 4px; padding: 6px;
}
QPushButton {
    color: #1e1e2e; border: none; border-radius: 6px; padding: 8px 20px;
    font-weight: bold; font-size: 13px;
}
QPushButton:hover { opacity: 0.9; }
QPushButton:pressed { opacity: 0.7; }
QPushButton:disabled { background-color: #45475a; color: #6c7086; }
QProgressBar {
    border: 1px solid #45475a; border-radius: 4px; text-align: center;
    color: #cdd6f4; background-color: #313244;
}
QProgressBar::chunk { background-color: #89b4fa; border-radius: 3px; }
QTableWidget {
    background-color: #11111b; color: #cdd6f4; border: 1px solid #45475a;
    gridline-color: #313244; font-size: 12px;
}
QTableWidget::item:selected { background-color: #45475a; }
QHeaderView::section {
    background-color: #313244; color: #89b4fa; border: 1px solid #45475a;
    padding: 4px 8px; font-weight: bold;
}
QCheckBox { color: #cdd6f4; }
"""

# ================= 工具函数 =================
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

def decode_jwt_payload(token):
    """解析 JWT 获取 payload（不验证签名）"""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return {}
        payload = parts[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return {}

def is_token_expired(access_token):
    payload = decode_jwt_payload(access_token)
    exp = payload.get('exp', 0)
    return exp <= time.time() + 60  # 提前一分钟算过期

def refresh_access_token(refresh_token):
    """用 refresh_token 换取新 access_token"""
    url = "https://auth.openai.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    }
    try:
        r = requests.post(url, data=data, timeout=15)
        if r.status_code == 200:
            return r.json().get("access_token")
    except Exception as e:
        print(f"刷新 token 失败: {e}")
    return None

def send_invite(workspace_id, access_token, device_id, invite_type="request"):
    """
    发送加入请求
    invite_type: 'request' 或 'accept'
    """
    url = f"https://chatgpt.com/backend-api/accounts/{workspace_id}/invites/{invite_type}"
    headers = {
        "accept": "*/*",
        "authorization": f"Bearer {access_token}",
        "content-type": "application/json",
        "oai-device-id": device_id,
        "oai-language": "en-US",
    }
    try:
        resp = requests.post(url, headers=headers, timeout=20)
        if resp.status_code == 200:
            return True, resp.text
        else:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)

# ================= 工作线程 =================
class WorkerThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)  # current, total
    finished_signal = pyqtSignal()
    row_status_signal = pyqtSignal(int, str)  # row, status

    def __init__(self, accounts, mother_ids, invite_type):
        super().__init__()
        self.accounts = accounts
        self.mother_ids = [m.strip() for m in mother_ids if m.strip()]
        self.invite_type = invite_type
        self._is_canceled = False

    def cancel(self):
        self._is_canceled = True

    def run(self):
        total = len(self.accounts) * len(self.mother_ids)
        current = 0
        for row, acc in enumerate(self.accounts):
            if self._is_canceled:
                break
            email = acc.get("email", "unknown")
            at = acc.get("access_token", "")
            rt = acc.get("refresh_token", "")
            # 检查 AT 是否过期
            if is_token_expired(at):
                self.log_signal.emit(f"[{email}] AT 过期，尝试刷新...")
                new_at = refresh_access_token(rt)
                if new_at:
                    at = new_at
                    acc["access_token"] = new_at
                    self.log_signal.emit(f"[{email}] AT 刷新成功")
                else:
                    self.log_signal.emit(f"[{email}] AT 刷新失败，跳过")
                    self.row_status_signal.emit(row, "刷新失败")
                    current += len(self.mother_ids)
                    self.progress_signal.emit(current, total)
                    continue

            # 生成一个随机的 device_id，简单用 uuid4 代替
            import uuid
            device_id = str(uuid.uuid4())
            all_ok = True
            for ws_id in self.mother_ids:
                if self._is_canceled:
                    break
                self.log_signal.emit(f"[{email}] → {ws_id} ({self.invite_type})")
                ok, msg = send_invite(ws_id, at, device_id, self.invite_type)
                current += 1
                self.progress_signal.emit(current, total)
                if ok:
                    self.log_signal.emit(f"[{email}] ✓ {ws_id} 成功")
                else:
                    self.log_signal.emit(f"[{email}] ✗ {ws_id} 失败: {msg}")
                    all_ok = False
            status = "成功" if all_ok else "部分失败"
            self.row_status_signal.emit(row, status)
        self.finished_signal.emit()

# ================= 主窗口 =================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("子号加入母号 Workspace 工具")
        self.setMinimumSize(1000, 700)
        self.resize(1100, 750)

        self.accounts = []  # 原始账号列表
        self.worker = None

        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # ---- 母号配置 ----
        config_group = QGroupBox("母号 Workspace ID（一行一个或逗号分隔）")
        config_layout = QVBoxLayout(config_group)
        self.ws_input = QTextEdit()
        self.ws_input.setMaximumHeight(70)
        self.ws_input.setPlainText("b5ab60b4-2c65-42c9-a374-ee6345b945c9")  # 默认 k12 母号
        config_layout.addWidget(self.ws_input)
        main_layout.addWidget(config_group)

        # ---- 导入与子号列表 ----
        list_group = QGroupBox("子号列表")
        list_layout = QVBoxLayout(list_group)

        btn_row = QHBoxLayout()
        self.import_btn = QPushButton("导入 JSON")
        self.import_btn.setStyleSheet("background-color: #89b4fa;")
        self.import_btn.clicked.connect(self.import_json)
        btn_row.addWidget(self.import_btn)

        self.clear_btn = QPushButton("清空列表")
        self.clear_btn.setStyleSheet("background-color: #6c7086; color: #cdd6f4;")
        self.clear_btn.clicked.connect(self.clear_accounts)
        btn_row.addWidget(self.clear_btn)

        self.select_all_cb = QCheckBox("全选")
        self.select_all_cb.stateChanged.connect(self._on_select_all)
        btn_row.addWidget(self.select_all_cb)

        btn_row.addStretch()
        list_layout.addLayout(btn_row)

        self.acc_table = QTableWidget()
        self.acc_table.setColumnCount(5)
        self.acc_table.setHorizontalHeaderLabels(["选择", "邮箱", "Account ID", "AT 有效期", "状态"])
        self.acc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.acc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.acc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.acc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        list_layout.addWidget(self.acc_table)
        main_layout.addWidget(list_group)

        # ---- 操作按钮 ----
        action_group = QGroupBox("批量操作")
        action_layout = QHBoxLayout(action_group)

        self.req_all_btn = QPushButton("全部 Request")
        self.req_all_btn.setStyleSheet("background-color: #a6e3a1;")
        self.req_all_btn.clicked.connect(lambda: self._start_work("request", use_selected=False))
        action_layout.addWidget(self.req_all_btn)

        self.accept_all_btn = QPushButton("全部 Accept")
        self.accept_all_btn.setStyleSheet("background-color: #89b4fa;")
        self.accept_all_btn.clicked.connect(lambda: self._start_work("accept", use_selected=False))
        action_layout.addWidget(self.accept_all_btn)

        self.req_sel_btn = QPushButton("选中 Request")
        self.req_sel_btn.setStyleSheet("background-color: #fab387;")
        self.req_sel_btn.clicked.connect(lambda: self._start_work("request", use_selected=True))
        action_layout.addWidget(self.req_sel_btn)

        self.accept_sel_btn = QPushButton("选中 Accept")
        self.accept_sel_btn.setStyleSheet("background-color: #cba6f7;")
        self.accept_sel_btn.clicked.connect(lambda: self._start_work("accept", use_selected=True))
        action_layout.addWidget(self.accept_sel_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setStyleSheet("background-color: #f38ba8;")
        self.stop_btn.clicked.connect(self.stop_work)
        self.stop_btn.setEnabled(False)
        action_layout.addWidget(self.stop_btn)

        action_layout.addStretch()
        main_layout.addWidget(action_group)

        # ---- 进度条 ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat("就绪")
        main_layout.addWidget(self.progress_bar)

        # ---- 日志 ----
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        main_layout.addWidget(log_group)

    def import_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择子号 JSON", "", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法读取文件: {e}")
            return

        if isinstance(data, dict) and "accounts" in data:
            accounts = data["accounts"]
        elif isinstance(data, list):
            accounts = data
        else:
            QMessageBox.critical(self, "错误", "JSON 格式不正确，需要数组或包含 accounts 字段的对象")
            return

        self.accounts = []
        for acc in accounts:
            cred = acc.get("credentials", {})
            self.accounts.append({
                "email": cred.get("email", acc.get("name", "")),
                "access_token": cred.get("access_token", ""),
                "refresh_token": cred.get("refresh_token", ""),
                "account_id": cred.get("chatgpt_account_id", ""),
            })

        self._refresh_table()
        self.append_log(f"已导入 {len(self.accounts)} 个子号")

    def clear_accounts(self):
        self.accounts = []
        self._refresh_table()
        self.append_log("列表已清空")

    def _refresh_table(self):
        self.acc_table.setRowCount(0)
        self.acc_table.setRowCount(len(self.accounts))
        for i, acc in enumerate(self.accounts):
            # 选择框
            cb = QCheckBox()
            self.acc_table.setCellWidget(i, 0, cb)

            # 邮箱
            self.acc_table.setItem(i, 1, QTableWidgetItem(acc["email"]))

            # Account ID (简短)
            aid = acc.get("account_id", "")
            self.acc_table.setItem(i, 2, QTableWidgetItem(aid[:8] + "..." if aid else "-"))

            # AT 有效期
            at = acc.get("access_token", "")
            exp_str = "未知"
            if at:
                payload = decode_jwt_payload(at)
                exp = payload.get("exp", 0)
                if exp:
                    dt = datetime.fromtimestamp(exp)
                    now = datetime.now()
                    if exp > time.time():
                        remain = dt - now
                        hours, remainder = divmod(remain.seconds, 3600)
                        mins = remainder // 60
                        exp_str = f"{hours}小时{mins}分钟"
                    else:
                        exp_str = "已过期"
            self.acc_table.setItem(i, 3, QTableWidgetItem(exp_str))

            # 状态
            self.acc_table.setItem(i, 4, QTableWidgetItem("就绪"))

    def _on_select_all(self, state):
        check = state == Qt.CheckState.Checked.value
        for i in range(self.acc_table.rowCount()):
            widget = self.acc_table.cellWidget(i, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(check)

    def _get_mother_ids(self):
        text = self.ws_input.toPlainText()
        ids = []
        for part in text.replace(",", "\n").split("\n"):
            p = part.strip()
            if p:
                ids.append(p)
        return ids

    def _get_selected_accounts(self):
        selected = []
        for i in range(self.acc_table.rowCount()):
            cb = self.acc_table.cellWidget(i, 0)
            if isinstance(cb, QCheckBox) and cb.isChecked():
                selected.append(self.accounts[i])
        return selected

    def _start_work(self, invite_type, use_selected):
        mother_ids = self._get_mother_ids()
        if not mother_ids:
            QMessageBox.warning(self, "警告", "请先填写母号 Workspace ID")
            return

        if use_selected:
            accounts = self._get_selected_accounts()
            if not accounts:
                QMessageBox.warning(self, "警告", "请选择至少一个子号")
                return
        else:
            accounts = self.accounts[:]
            if not accounts:
                QMessageBox.warning(self, "警告", "子号列表为空")
                return

        # 禁用按钮
        self._set_buttons_enabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(accounts) * len(mother_ids))
        self.log_text.clear()

        self.worker = WorkerThread(accounts, mother_ids, invite_type)
        self.worker.log_signal.connect(self.append_log)
        self.worker.progress_signal.connect(self._update_progress)
        self.worker.row_status_signal.connect(self._update_row_status)
        self.worker.finished_signal.connect(self._work_finished)
        self.worker.start()

    def stop_work(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.append_log("[系统] 正在停止...")

    def _set_buttons_enabled(self, enabled):
        self.req_all_btn.setEnabled(enabled)
        self.accept_all_btn.setEnabled(enabled)
        self.req_sel_btn.setEnabled(enabled)
        self.accept_sel_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(not enabled)

    def _update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"{current}/{total}")

    def _update_row_status(self, row, status):
        if row < self.acc_table.rowCount():
            self.acc_table.setItem(row, 4, QTableWidgetItem(status))

    def _work_finished(self):
        self._set_buttons_enabled(True)
        self.append_log("[系统] 任务完成")
        # 更新所有AT有效期
        self._refresh_table()

    def append_log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {msg}")
        # 自动滚动到底部
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE_DARK)
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()