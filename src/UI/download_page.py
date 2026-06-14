import re
import os
import time
from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QListWidget, QListWidgetItem, QMessageBox,
    QScrollArea, QFrame, QComboBox
)
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtCore import pyqtSignal
from PyQt6 import QtCore, QtWidgets
from src.asmr_api.get_down_list import get_down_list
from src.download.download_thread import MultiFileDownloadManager
from src.download.download_utils import (
    format_bytes, calculate_actual_total_size, calculate_downloaded_size,
    build_file_tree_structure, check_all_files_skipped,
    set_initial_collapsed_folders, get_work_folder_name,
    format_file_size_for_filter_stats, format_rj_number,
    calculate_initial_progress, format_speed_display,
    build_file_filter_stats_text, validate_work_detail_for_download,
    create_download_item_data, calculate_global_speed
)
from src.download.download_threads import WorkDetailThread, DownloadListThread, ReviewThread
from src.download.download_manager_utils import (
    setup_download_manager, update_download_path_if_needed,
    get_ready_download_items,
    start_first_download_and_queue_others, stop_all_downloads,
    clear_download_items_from_layout,
    handle_error_types
)
from src.read_conf import ReadConf
from src.language.language_manager import language_manager


class FocusedScrollArea(QScrollArea):
    """带有焦点管理的滚动区域"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.WheelFocus)

    def enterEvent(self, event):
        """鼠标进入时获取焦点"""
        self.setFocus()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开时清除焦点"""
        self.clearFocus()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        """处理滚轮事件，只有在有焦点时才处理"""
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            # 如果没有焦点，将事件传递给父控件
            if self.parent():
                self.parent().wheelEvent(event)


class TriangleButton(QLabel):
    """可点击的三角形折叠按钮"""
    clicked = pyqtSignal(str)  # 传递folder_path参数

    def __init__(self, collapsed=True, folder_path=""):
        super().__init__()
        self.collapsed = collapsed
        self.folder_path = folder_path
        self.setFixedSize(12, 12)
        self.update_icon()

    def update_icon(self):
        """更新三角形图标"""
        if self.collapsed:
            self.setText("▶")  # 右指三角形
        else:
            self.setText("▼")  # 下指三角形
        self.setStyleSheet("color: #000; font-size: 10px; font-family: monospace;")

    def mousePressEvent(self, event):
        """处理点击事件"""
        try:
            from PyQt6.QtCore import Qt
            if event.button() == Qt.MouseButton.LeftButton:
                self.collapsed = not self.collapsed
                self.update_icon()
                self.clicked.emit(self.folder_path)
        except RuntimeError:
            # 忽略已删除对象的错误
            pass




class DownloadItemWidget(QWidget):
    detail_ready = pyqtSignal()

    def __init__(self, work_info, parent_page=None):
        super().__init__()
        self.work_info = work_info
        self.work_detail = None
        self.is_paused = False
        self.is_downloading = False
        self.download_speed = 0.0  # KB/s
        self.bytes_downloaded = 0
        self.total_bytes = 0
        self.last_update_time = time.time()
        self.last_downloaded = 0
        self.parent_page = parent_page
        self.setup_ui()
        self.load_work_detail()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)

        # 顶部信息行
        info_layout = QHBoxLayout()

        # 作品标题
        self.title_label = QLabel(self.work_info['title'])
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label, 1)

        # RJ号 - 直接使用接口返回的 source_id
        rj_text = self.work_info.get('source_id', f"RJ{self.work_info['id']:08d}")
        self.rj_label = QLabel(rj_text)
        self.rj_label.setStyleSheet("color: #666; font-size: 12px;")
        info_layout.addWidget(self.rj_label)

        layout.addLayout(info_layout)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # 底部信息和按钮
        bottom_layout = QHBoxLayout()

        # 状态标签
        self.status_label = QLabel(language_manager.get_text('waiting'))
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        bottom_layout.addWidget(self.status_label)

        # 下载速度标签
        self.speed_label = QLabel(f"0 {language_manager.get_text('kb_per_second')}")
        self.speed_label.setStyleSheet("color: #0066cc; font-size: 11px; font-weight: bold;")
        bottom_layout.addWidget(self.speed_label)

        # 文件大小标签
        self.size_label = QLabel(language_manager.get_text('loading'))
        self.size_label.setStyleSheet("color: #666; font-size: 11px;")
        bottom_layout.addWidget(self.size_label)

        bottom_layout.addStretch()

        layout.addLayout(bottom_layout)

        # 文件目录展示区域（初始隐藏）
        self.file_tree_scroll = FocusedScrollArea()
        self.file_tree_scroll.setVisible(False)
        self.file_tree_scroll.setMaximumHeight(250)
        self.file_tree_scroll.setWidgetResizable(True)
        self.file_tree_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.file_tree_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.file_tree_scroll.setStyleSheet("""
            QScrollArea {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 2px;
                margin: 2px 0px;
            }
            QScrollBar:vertical {
                background: #e8e8e8;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #888888;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #888888;
            }
            QScrollBar::handle:vertical:pressed {
                background: #888888;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                background: #e8e8e8;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: #888888;
                border-radius: 6px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #888888;
            }
            QScrollBar::handle:horizontal:pressed {
                background: #888888;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                border: none;
                background: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """)

        self.file_tree_widget = QWidget()
        self.file_tree_layout = QVBoxLayout()
        self.file_tree_layout.setContentsMargins(5, 5, 5, 5)
        self.file_tree_layout.setSpacing(1)
        self.file_tree_widget.setLayout(self.file_tree_layout)

        self.file_tree_scroll.setWidget(self.file_tree_widget)

        layout.addWidget(self.file_tree_scroll)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("color: #ddd;")
        layout.addWidget(line)

        # 添加点击事件处理
        self.is_expanded = False
        self.collapsed_folders = set()  # 存储被折叠的文件夹路径
        self.installEventFilter(self)

        self.setLayout(layout)

    def eventFilter(self, obj, event):
        """处理点击事件"""
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import Qt

        if obj == self and event.type() == QEvent.Type.MouseButtonPress:
            if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                # 检查点击位置是否在展开区域内
                click_pos = event.position().toPoint()

                # 如果展开区域可见，检查点击是否在其范围内
                if self.file_tree_scroll.isVisible():
                    scroll_geometry = self.file_tree_scroll.geometry()
                    if scroll_geometry.contains(click_pos):
                        # 点击在展开区域内，不处理
                        return False

                # 点击在主区域，处理展开/收起逻辑
                self.handle_item_click()
                return True
        return super().eventFilter(obj, event)

    def handle_item_click(self):
        """处理点击事件，包括收起其他展开项"""
        if not self.work_detail:
            return

        # 如果有父页面引用，先收起所有其他展开的项
        if self.parent_page:
            self.parent_page.collapse_all_except(self)

        # 切换当前项的展开状态
        self.toggle_file_tree()

    def toggle_file_tree(self):
        """切换文件目录显示状态"""
        if not self.work_detail:
            return

        self.is_expanded = not self.is_expanded

        if self.is_expanded:
            self.build_file_tree()
            self.file_tree_scroll.setVisible(True)
        else:
            self.file_tree_scroll.setVisible(False)

    def collapse_tree(self):
        """收起文件树"""
        self.is_expanded = False
        self.file_tree_scroll.setVisible(False)

    def build_file_tree(self):
        """构建文件目录树"""
        # 清除现有内容
        for i in reversed(range(self.file_tree_layout.count())):
            child = self.file_tree_layout.itemAt(i).widget()
            if child:
                child.setParent(None)

        if not self.work_detail or 'files' not in self.work_detail:
            return

        # 使用工具函数构建目录结构
        file_tree = build_file_tree_structure(self.work_detail)

        # 第一次构建时，将所有跳过的文件夹设为折叠状态
        if not hasattr(self, '_initial_collapsed_set'):
            self._set_initial_collapsed_folders(file_tree, "")
            self._initial_collapsed_set = True

        # 显示文件树
        self._display_tree(file_tree, 0)

    def _set_initial_collapsed_folders(self, tree_dict, folder_path):
        """初始化时将所有跳过的文件夹设为折叠状态"""
        set_initial_collapsed_folders(tree_dict, folder_path, self.collapsed_folders)

    def _display_tree(self, tree_dict, indent_level=0, prefix="", is_last=True, folder_path=""):
        """递归显示文件树，使用tree命令风格"""
        items = list(sorted(tree_dict.items()))

        for i, (name, item) in enumerate(items):
            is_current_last = (i == len(items) - 1)
            current_path = f"{folder_path}/{name}" if folder_path else name

            # 构建树形前缀
            if indent_level == 0:
                tree_prefix = ""
            else:
                tree_prefix = prefix + ("└── " if is_current_last else "├── ")

            if item['type'] == 'folder':
                # 检查文件夹内是否所有文件都被跳过
                all_files_skipped = check_all_files_skipped(item['children'])

                if all_files_skipped:
                    # 为跳过的文件夹创建带三角形的布局
                    folder_widget = QWidget()
                    folder_layout = QHBoxLayout()
                    folder_layout.setContentsMargins(0, 0, 0, 0)
                    folder_layout.setSpacing(2)

                    # 添加前缀空格
                    if tree_prefix:
                        prefix_label = QLabel(tree_prefix)
                        prefix_label.setStyleSheet("color: #000; font-size: 10px; font-family: 'Courier New', monospace;")
                        folder_layout.addWidget(prefix_label)

                    # 添加三角形按钮
                    is_collapsed = current_path in self.collapsed_folders
                    triangle = TriangleButton(collapsed=is_collapsed, folder_path=current_path)
                    triangle.clicked.connect(self._toggle_folder)
                    folder_layout.addWidget(triangle)

                    # 添加文件夹名称
                    folder_text = f"{name}/"
                    folder_label = QLabel(folder_text)
                    folder_label.setStyleSheet("""
                        color: #000;
                        font-weight: bold;
                        font-size: 10px;
                        font-family: 'Courier New', monospace;
                        text-decoration: line-through;
                    """)
                    folder_layout.addWidget(folder_label)
                    folder_layout.addStretch()

                    folder_widget.setLayout(folder_layout)
                    self.file_tree_layout.addWidget(folder_widget)

                    # 如果文件夹未被折叠，显示子项
                    if current_path not in self.collapsed_folders:
                        if indent_level == 0:
                            next_prefix = ""
                        else:
                            next_prefix = prefix + ("    " if is_current_last else "│   ")
                        self._display_tree(item['children'], indent_level + 1, next_prefix, is_current_last, current_path)
                else:
                    # 正常文件夹（有文件需要下载）
                    folder_text = f"{tree_prefix}{name}/"
                    folder_label = QLabel(folder_text)
                    folder_label.setStyleSheet("color: #666; font-weight: bold; font-size: 10px; font-family: 'Courier New', monospace;")
                    self.file_tree_layout.addWidget(folder_label)

                    # 递归显示子项
                    if indent_level == 0:
                        next_prefix = ""
                    else:
                        next_prefix = prefix + ("    " if is_current_last else "│   ")
                    self._display_tree(item['children'], indent_level + 1, next_prefix, is_current_last, current_path)
            else:
                # 文件
                file_size = format_bytes(item.get('size', 0))
                file_text = f"{tree_prefix}{name} ({file_size})"

                file_label = QLabel(file_text)

                if item.get('skipped', False):
                    # 不下载的文件使用黑色和删除线样式
                    file_label.setStyleSheet("""
                        color: #000;
                        font-size: 10px;
                        font-family: 'Courier New', monospace;
                        text-decoration: line-through;
                    """)
                else:
                    # 下载的文件使用灰色
                    file_label.setStyleSheet("color: #666; font-size: 10px; font-family: 'Courier New', monospace;")

                self.file_tree_layout.addWidget(file_label)


    def _toggle_folder(self, folder_path):
        """切换文件夹的折叠状态"""
        if folder_path in self.collapsed_folders:
            self.collapsed_folders.remove(folder_path)
        else:
            self.collapsed_folders.add(folder_path)

        # 重新构建文件树
        self.build_file_tree()

    def load_work_detail(self):
        """加载作品详细信息"""
        self.detail_thread = WorkDetailThread(self.work_info['id'])
        self.detail_thread.detail_loaded.connect(self.on_detail_loaded)
        self.detail_thread.error_occurred.connect(self.on_detail_error)
        self.detail_thread.start()

    def on_detail_loaded(self, work_detail):
        """作品详细信息加载完成"""
        self.work_detail = work_detail
        if work_detail:
            self.update_initial_progress()
            # 通知父窗口检查是否可以启用全局开始按钮
            self.detail_ready.emit()
        else:
            self.size_label.setText(language_manager.get_text('failed_to_get'))
            self.status_label.setText(language_manager.get_text('get_file_info_failed'))

    def update_initial_progress(self):
        """更新初始进度显示"""
        if not self.work_detail:
            return
            
        # 使用工具函数计算初始进度
        initial_progress, downloaded_size, actual_total_size = calculate_initial_progress(self.work_detail, self.work_info)
        self.progress_bar.setValue(initial_progress)

        # 格式化显示
        downloaded_formatted = format_bytes(downloaded_size)
        total_size_formatted = format_bytes(actual_total_size)
        self.size_label.setText(f"{downloaded_formatted}/{total_size_formatted}")
        
        if initial_progress == 100:
            self.status_label.setText(language_manager.get_text('completed'))
        elif downloaded_size > 0:
            self.status_label.setText(f"{language_manager.get_text('ready_to_download')} - 已下载 {initial_progress}%")
        else:
            self.status_label.setText(f"{language_manager.get_text('ready_to_download')} ({len(self.work_detail['files'])} {language_manager.get_text('files')})")

    def on_detail_error(self, error_msg):
        """作品详细信息加载错误"""
        self.size_label.setText(language_manager.get_text('failed_to_get'))
        self.status_label.setText(f"{language_manager.get_text('error')}: {error_msg}")

        # token 过期时引导用户重新登录；交由父窗口统一处理(去重，避免多个作品各弹一次)
        if error_msg == "TOKEN_EXPIRED" and self.parent_page:
            self.parent_page.handle_token_expired_from_detail()

    def start_download(self):
        """开始下载（由全局按钮调用）"""
        if not validate_work_detail_for_download(self.work_detail):
            return None, None

        self.is_downloading = True
        self.status_label.setText(language_manager.get_text('downloading'))
        # 重置进度条样式，清除之前的错误状态样式
        self.progress_bar.setStyleSheet("")
        return create_download_item_data(self.work_info['id'], self.work_detail)

    def pause_download(self):
        """暂停下载（由全局按钮调用）"""
        if not self.is_downloading:
            return
        self.is_paused = True
        self.status_label.setText(language_manager.get_text('paused'))
        self.speed_label.setText("0 KB/s")
        # 真正暂停底层下载线程，否则文件仍在全速下载、UI 却显示已暂停
        if self.parent_page and self.parent_page.download_manager:
            self.parent_page.download_manager.pause_download(str(self.work_info['id']))

    def resume_download(self):
        """继续下载（由全局按钮调用）"""
        if not self.is_downloading:
            return
        self.is_paused = False
        self.status_label.setText(language_manager.get_text('downloading'))
        # 恢复底层下载线程
        if self.parent_page and self.parent_page.download_manager:
            self.parent_page.download_manager.resume_download(str(self.work_info['id']))


    def update_progress(self, progress, downloaded_bytes=0, total_bytes=0, status="下载中..."):
        self.progress_bar.setValue(progress)

        # 更新下载量信息，使用实际下载总大小
        if downloaded_bytes >= 0 and self.work_detail:
            # 确保 downloaded_bytes 是数字类型，支持超大数值
            if isinstance(downloaded_bytes, str):
                try:
                    downloaded_bytes = int(downloaded_bytes)
                except ValueError:
                    downloaded_bytes = 0

            self.bytes_downloaded = downloaded_bytes

            # 使用传入的实际下载总大小，如果没有传入则使用API返回的原始大小
            if total_bytes > 0:
                self.total_bytes = total_bytes
                actual_total_size = total_bytes
            else:
                # 如果没有传入total_bytes，说明可能是初始化阶段，使用API原始大小
                actual_total_size = self.work_detail['total_size']
                self.total_bytes = actual_total_size

            # 使用实际下载总大小更新显示
            downloaded_formatted = format_bytes(downloaded_bytes)
            total_formatted = format_bytes(actual_total_size)
            self.size_label.setText(f"{downloaded_formatted}/{total_formatted}")

        if not self.is_paused:
            self.status_label.setText(status)

        if progress == 100:
            self.status_label.setText(language_manager.get_text('completed'))
            self.speed_label.setText("0 KB/s")
            self.is_downloading = False

    def mark_completed(self):
        """标记为下载完成：进度 100%、速度清零，且保持已下载量/总量显示正确
        (不要用 update_progress(100,0,0)，那会把已下载量显示重置为 0、总量回退成未过滤的 API 原始大小)"""
        self.progress_bar.setValue(100)
        self.status_label.setText(language_manager.get_text('completed'))
        self.speed_label.setText("0 KB/s")
        self.download_speed = 0.0
        self.is_downloading = False
        self.is_paused = False
        # 用下载过程中记录的实际总大小，显示为 总量/总量
        total = self.total_bytes if self.total_bytes > 0 else calculate_actual_total_size(self.work_detail)
        if total > 0:
            total_formatted = format_bytes(total)
            self.size_label.setText(f"{total_formatted}/{total_formatted}")

    def update_speed(self, speed_kbps):
        """更新下载速度显示"""
        self.download_speed = speed_kbps
        self.speed_label.setText(format_speed_display(speed_kbps))

    def set_downloading(self):
        self.status_label.setText(language_manager.get_text('downloading'))

    def set_error(self, error_msg):
        self.status_label.setText(f"{language_manager.get_text('error')}: {error_msg}")
        self.speed_label.setText("0 KB/s")
        self.is_downloading = False




    def update_language(self):
        """更新语言显示"""
        # 更新状态标签
        if not self.is_downloading:
            if self.work_detail:
                self.status_label.setText(f"{language_manager.get_text('ready_to_download')} ({len(self.work_detail['files'])} {language_manager.get_text('files')})")
            else:
                self.status_label.setText(language_manager.get_text('waiting'))
        elif self.is_paused:
            self.status_label.setText(language_manager.get_text('paused'))
        else:
            self.status_label.setText(language_manager.get_text('downloading'))

        # 更新速度标签
        if self.download_speed >= 1024:
            self.speed_label.setText(f"{self.download_speed/1024:.1f} {language_manager.get_text('mb_per_second')}")
        else:
            self.speed_label.setText(f"{self.download_speed:.1f} {language_manager.get_text('kb_per_second')}")

        # 更新加载状态(初始文案在不同语言下不同，不能只硬编码英文 "Loading..." 比较)
        if not self.work_detail and self.size_label.text() in ("Loading...", language_manager.get_text('loading')):
            self.size_label.setText(language_manager.get_text('loading'))




class DownloadPage(QWidget):
    def __init__(self):
        super().__init__()
        self.conf = ReadConf()
        self.download_items = {}
        self.download_manager = None
        self.is_downloading_active = False  # 跟踪是否有活动下载
        self.auto_refresh_enabled = True   # 是否启用自动刷新功能
        self._token_expired_dialog_shown = False  # 避免多个作品详情同时报 token 过期时重复弹窗
        self.review_threads = []  # 持有后台 review 线程引用，防止被 GC 提前回收
        self.work_fail_counts = {}  # work_id(str) -> 本会话下载失败次数
        self.MAX_WORK_RETRIES = 3  # 自动刷新循环中，单个作品达到此失败次数后不再自动重试，避免空转
        self.setup_ui()
        self.setup_download_manager()
        self.load_download_list()


    def setup_ui(self):
        self.setWindowTitle(language_manager.get_text('app_title'))
        self.setFixedSize(700, 500)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        # 顶部控制栏
        top_layout = QHBoxLayout()

        # 标题
        # title_label = QLabel("ASMR_download")
        # title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        # top_layout.addWidget(title_label)

        # 语言选择
        language_label = QLabel("Language:")
        top_layout.addWidget(language_label)

        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "zh")
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("日本語", "ja")

        # 设置当前语言
        current_lang = language_manager.current_language
        for i in range(self.language_combo.count()):
            if self.language_combo.itemData(i) == current_lang:
                self.language_combo.setCurrentIndex(i)
                break

        self.language_combo.currentIndexChanged.connect(self.on_language_changed)
        top_layout.addWidget(self.language_combo)

        top_layout.addStretch()

        # 全局速度显示
        self.global_speed_label = QLabel(f"{language_manager.get_text('total_speed')}: 0 {language_manager.get_text('kb_per_second')}")
        self.global_speed_label.setStyleSheet("color: #0066cc; font-weight: bold;")
        top_layout.addWidget(self.global_speed_label)

        # 开始/停止下载按钮
        self.start_all_button = QPushButton(language_manager.get_text('start_download'))
        self.start_all_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.start_all_button.clicked.connect(self.toggle_downloads)
        self.start_all_button.setEnabled(False)
        top_layout.addWidget(self.start_all_button)

        # 刷新按钮
        self.refresh_button = QPushButton(language_manager.get_text('refresh_list'))
        self.refresh_button.clicked.connect(self.load_download_list)
        top_layout.addWidget(self.refresh_button)

        # 设置按钮
        self.settings_button = QPushButton(language_manager.get_text('settings'))
        self.settings_button.clicked.connect(self.open_settings)
        top_layout.addWidget(self.settings_button)

        layout.addLayout(top_layout)

        # 滚动区域
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 下载列表容器
        self.download_container = QWidget()
        self.download_layout = QVBoxLayout(self.download_container)
        self.download_layout.setContentsMargins(0, 0, 0, 0)
        self.download_layout.addStretch()

        self.scroll.setWidget(self.download_container)
        layout.addWidget(self.scroll)

        # 底部状态栏
        status_layout = QHBoxLayout()
        self.status_label = QLabel(language_manager.get_text('waiting'))
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        self.count_label = QLabel(f"{language_manager.get_text('total_count')}: 0")
        self.count_label.setStyleSheet("color: #666; font-size: 11px;")
        status_layout.addWidget(self.count_label)

        layout.addLayout(status_layout)

        self.setLayout(layout)

    def setup_download_manager(self):
        """设置下载管理器"""
        self.download_manager = setup_download_manager()

        # 连接下载管理器信号
        self.download_manager.download_started.connect(self.on_download_started)
        self.download_manager.download_progress.connect(self.on_download_progress)
        self.download_manager.download_completed.connect(self.on_download_completed)
        self.download_manager.download_failed.connect(self.on_download_failed)
        self.download_manager.speed_updated.connect(self.on_speed_updated)
        self.download_manager.file_filter_stats.connect(self.on_file_filter_stats)

        # 不启动管理器的工作线程：下载由各 DownloadThread 负责，管理器槽函数
        # 在主线程事件循环中通过信号执行，避免对队列字典的跨线程竞态访问。

    def update_download_path(self):
        """动态更新下载路径，无需重启程序"""
        update_download_path_if_needed(self.download_manager)

    def load_download_list(self):
        self.status_label.setText(language_manager.get_text('loading'))
        self.refresh_button.setEnabled(False)
        # 新一轮刷新，允许再次提示 token 过期
        self._token_expired_dialog_shown = False
        # 用户主动刷新视为重新尝试，清空失败计数，给持续失败项一次重试机会
        self.work_fail_counts.clear()

        self.list_thread = DownloadListThread()
        self.list_thread.list_updated.connect(self.on_list_updated)
        self.list_thread.error_occurred.connect(self.on_list_error)
        self.list_thread.finished.connect(lambda: self.refresh_button.setEnabled(True))
        self.list_thread.start()

    def on_list_updated(self, works_list):
        # 清空现有列表（这已经重置了所有状态）
        self.clear_all_items()

        # 添加新的下载项
        for work in works_list:
            self.add_download_item(work)

        # 更新计数和状态
        self.count_label.setText(f"{language_manager.get_text('total_count')}: {len(works_list)}")
        
        # 根据列表是否为空设置不同的状态信息
        if works_list:
            self.status_label.setText(f"{language_manager.get_text('loaded_items')} {len(works_list)} {language_manager.get_text('download_items')}")
            self.start_all_button.setEnabled(True)
        else:
            # 对于空列表，保持清空状态并显示合适的提示
            self.status_label.setText(language_manager.get_text('empty_list'))
            # start_all_button已经在clear_all_items中被禁用了

    def on_list_error(self, error_msg):
        print(f"列表获取错误: {error_msg}")
        
        # 发生错误时也要清空UI中的现有数据
        self.clear_all_items()
        
        # 使用工具函数处理错误类型
        error_info = handle_error_types(error_msg)
        title = language_manager.get_text(error_info['title'])
        message = language_manager.get_text(error_info['message'])
        detail = error_info['detail']
        
        # 更新状态标签
        self.status_label.setText(f"{language_manager.get_text('error')}: {title}")
        
        # 弹出相应的错误对话框
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle(language_manager.get_text('error'))
        msg_box.setText(message)
        msg_box.setDetailedText(detail)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        result = msg_box.exec()

        # 如果是TOKEN_EXPIRED错误，点击OK后跳转到设置页面
        if error_msg == "TOKEN_EXPIRED" and result == QMessageBox.StandardButton.Ok:
            self.open_settings()

    def handle_token_expired_from_detail(self):
        """作品详情加载时检测到 token 过期：弹一次提示并跳转设置(去重)"""
        if self._token_expired_dialog_shown:
            return
        self._token_expired_dialog_shown = True

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle(language_manager.get_text('error'))
        msg_box.setText(language_manager.get_text('token_expired'))
        msg_box.setInformativeText(language_manager.get_text('relogin_required'))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        result = msg_box.exec()
        if result == QMessageBox.StandardButton.Ok:
            self.open_settings()

    def add_download_item(self, work_info):
        item_widget = DownloadItemWidget(work_info, parent_page=self)
        item_widget.detail_ready.connect(self.check_start_all_button)

        # 插入到倒数第二个位置（最后一个是stretch）
        self.download_layout.insertWidget(self.download_layout.count() - 1, item_widget)

        self.download_items[str(work_info['id'])] = item_widget

    def collapse_all_except(self, exception_widget):
        """收起所有展开的项，除了指定的项"""
        for item in self.download_items.values():
            if item != exception_widget and item.is_expanded:
                item.collapse_tree()

    def clear_all_items(self):
        """完全清空所有下载项和UI状态"""
        # 使用工具函数清空下载项
        clear_download_items_from_layout(self.download_layout, self.download_items)
        
        # 重置UI状态标签
        self.count_label.setText(f"{language_manager.get_text('total_count')}: 0")
        self.status_label.setText(language_manager.get_text('waiting'))
        
        # 禁用相关按钮
        self.start_all_button.setEnabled(False)
        if hasattr(self, 'stop_all_button'):
            self.stop_all_button.setEnabled(False)
        
        # 确保下载状态被重置
        self.is_downloading_active = False
        
        # 强制刷新布局，确保视觉上完全清空
        self.download_layout.update()
        self.download_container.update()
        self.update()
        
        # 重置滚动位置到顶部
        self.scroll.verticalScrollBar().setValue(0)
        self.scroll.horizontalScrollBar().setValue(0)
        
        # 强制处理所有待处理的Qt事件，确保UI立即更新
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def start_review_thread(self, work_id, progress=None):
        """在后台线程标记作品收听状态(review)。progress 指定时直接使用(如 'postponed' 搁置)"""
        thread = ReviewThread(work_id, progress=progress)
        self.review_threads.append(thread)
        # 完成后从列表移除并安全回收线程对象
        thread.review_done.connect(lambda wid, ok, t=thread: self._on_review_done(t, wid, ok))
        thread.start()

    def _on_review_done(self, thread, work_id, success):
        """review 后台线程完成的清理回调"""
        if not success:
            print(f"作品 {work_id} 状态标记失败(将于下次刷新重试)")
        thread.quit()
        thread.wait()
        if thread in self.review_threads:
            self.review_threads.remove(thread)

    def on_download_started(self, work_id):
        """下载开始"""
        print(f"开始下载: {work_id}")
        # 管理器从队列启动后续下载时，对应 widget 的 is_downloading 仍为 False，
        # 会导致 calculate_global_speed 把它过滤掉、总速度显示为 0。这里补上标记。
        if work_id in self.download_items:
            item = self.download_items[work_id]
            item.is_downloading = True
            item.is_paused = False

    def on_download_progress(self, work_id, progress, downloaded, total, status):
        """下载进度更新"""
        if work_id in self.download_items:
            self.download_items[work_id].update_progress(progress, downloaded, total, status)

    def on_download_completed(self, work_id):
        """下载完成"""
        # 在后台线程标记作品收听状态(review)，避免同步 HTTP 阻塞主线程/卡 UI
        self.start_review_thread(work_id)
        if work_id in self.download_items:
            self.download_items[work_id].mark_completed()
        self.update_global_speed()

        # 还有后续任务则继续，否则收尾(自动刷新或重置)
        if not self._finalize_batch_if_idle():
            rj_display = work_id
            if work_id in self.download_items:
                work_info = self.download_items[work_id].work_info
                rj_display = work_info.get('source_id', f"RJ{work_id}")
            self.status_label.setText(f"{language_manager.get_text('download_completed')}: {rj_display}, {language_manager.get_text('continue_next')}")

    def _finalize_batch_if_idle(self):
        """若下载队列与活动下载均已清空，则收尾(按需自动刷新或重置按钮)。

        返回 True 表示本批已收尾；返回 False 表示仍有任务在进行，调用方应显示"继续下一个"。
        """
        manager = self.download_manager
        busy = manager and (len(manager.download_queue) > 0 or len(manager.active_downloads) > 0)
        if busy:
            return False

        if self.auto_refresh_enabled and self.is_downloading_active:
            print("所有下载任务完成，开始自动刷新列表...")
            self.status_label.setText("所有下载完成，正在自动刷新列表...")
            # 延迟3秒后自动刷新，给用户一些时间看到完成状态
            QTimer.singleShot(3000, self.auto_refresh_and_continue)
        else:
            self.is_downloading_active = False
            self.start_all_button.setText(language_manager.get_text('start_download'))
            self.start_all_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
            self.status_label.setText(language_manager.get_text('all_downloads_completed'))
        return True

    def on_download_failed(self, work_id, error):
        """下载失败：标记该作品失败，但不停止整体下载——管理器会自动继续下一个作品"""
        if work_id in self.download_items:
            self.download_items[work_id].set_error(error)
        self.update_global_speed()

        # 记录失败次数，供自动刷新循环判断是否放弃该作品(避免对持续失败项无限重试)
        self.work_fail_counts[work_id] = self.work_fail_counts.get(work_id, 0) + 1

        # 达到最大重试次数即放弃：在服务器端把该作品标为"搁置(postponed)"，
        # 使其移出"想听"列表，不再于后续刷新中重复出现
        if self.work_fail_counts[work_id] >= self.MAX_WORK_RETRIES:
            print(f"作品 {work_id} 多次下载失败，标记为搁置(postponed)")
            self.start_review_thread(work_id, progress='postponed')

        # 用 RJ 号在状态栏提示失败(不再为每个失败弹模态框打断顺序下载)
        rj_display = work_id
        if work_id in self.download_items:
            rj_display = self.download_items[work_id].work_info.get('source_id', f"RJ{work_id}")

        # 还有后续任务则继续，否则收尾
        if not self._finalize_batch_if_idle():
            self.status_label.setText(
                f"{language_manager.get_text('error')}: {rj_display} {language_manager.get_text('download_failed')}, "
                f"{language_manager.get_text('continue_next')}")
        else:
            self.status_label.setText(
                f"{language_manager.get_text('error')}: {rj_display} {language_manager.get_text('download_failed')}")

    def on_speed_updated(self, work_id, speed_kbps):
        """速度更新"""
        if work_id in self.download_items:
            self.download_items[work_id].update_speed(speed_kbps)
        self.update_global_speed()

    def on_file_filter_stats(self, work_id, api_total, actual_total, skipped_total, total_files, skipped_files):
        """文件筛选统计信息"""
        # 获取 source_id 用于显示
        rj_display = work_id
        if work_id in self.download_items:
            work_info = self.download_items[work_id].work_info
            rj_display = work_info.get('source_id', f"RJ{work_id}")
        
        status_text = build_file_filter_stats_text(rj_display, total_files, skipped_files, skipped_total, actual_total)
        self.status_label.setText(status_text)

    def check_start_all_button(self):
        """检查是否应该启用开始全部下载按钮"""
        ready_count = 0
        for item in self.download_items.values():
            if item.work_detail and not item.is_downloading:
                ready_count += 1

        # 如果有准备好的下载项，启用按钮
        self.start_all_button.setEnabled(ready_count > 0)

    def toggle_downloads(self):
        """切换下载状态：开始下载或停止下载"""
        if not self.is_downloading_active:
            # 当前没有下载，开始下载
            self.start_downloads()
        else:
            # 当前有下载，停止下载
            self.stop_downloads()

    def start_downloads(self):
        """开始下载"""
        # 获取所有准备好的下载项
        ready_items = get_ready_download_items(self.download_layout, DownloadItemWidget)

        if ready_items:
            # 使用工具函数开始下载
            if start_first_download_and_queue_others(ready_items, self.download_manager):
                # 更新状态
                self.is_downloading_active = True
                self.start_all_button.setText(language_manager.get_text('stop_download'))
                self.start_all_button.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
                self.status_label.setText(f"{language_manager.get_text('start_sequential_download')} {len(ready_items)} {language_manager.get_text('tasks')}")
        else:
            self.status_label.setText(language_manager.get_text('no_downloadable_tasks'))

    def stop_downloads(self):
        """停止所有下载"""
        # 使用工具函数停止下载
        stop_all_downloads(self.download_manager, self.download_items)

        # 更新所有下载项状态
        for item in self.download_items.values():
            if item.is_downloading:
                item.is_downloading = False
                item.is_paused = False
                item.status_label.setText(language_manager.get_text('ready_to_download'))
                item.speed_label.setText("0 KB/s")

        # 更新按钮状态
        self.is_downloading_active = False
        self.start_all_button.setText(language_manager.get_text('start_download'))
        self.start_all_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.status_label.setText(language_manager.get_text('all_downloads_stopped'))


    def on_language_changed(self, index):
        """语言选择改变时的处理函数"""
        language_code = self.language_combo.itemData(index)
        if language_code:
            self.change_language(language_code)

    def change_language(self, language_code):
        """切换语言"""
        language_manager.set_language(language_code)
        self.update_ui_text()
        
        # 如果设置页面已经打开，通知它切换语言
        if hasattr(self, 'settings_page') and self.settings_page and self.settings_page.isVisible():
            self.settings_page.language_changed.emit(language_code)

    def update_ui_text(self):
        """更新界面文本"""
        # 更新窗口标题
        self.setWindowTitle(language_manager.get_text('app_title'))

        # 更新顶部按钮（根据当前状态显示相应文本）
        if self.is_downloading_active:
            self.start_all_button.setText(language_manager.get_text('stop_download'))
        else:
            self.start_all_button.setText(language_manager.get_text('start_download'))
        
        self.refresh_button.setText(language_manager.get_text('refresh_list'))
        self.settings_button.setText(language_manager.get_text('settings'))

        # 更新全局速度标签
        current_speed = self.global_speed_label.text().split(': ')[1] if ': ' in self.global_speed_label.text() else f"0 {language_manager.get_text('kb_per_second')}"
        self.global_speed_label.setText(f"{language_manager.get_text('total_speed')}: {current_speed}")

        # 更新底部状态
        current_count = self.count_label.text().split(': ')[1] if ': ' in self.count_label.text() else "0"
        self.count_label.setText(f"{language_manager.get_text('total_count')}: {current_count}")

        # 更新所有下载项目的语言显示
        for item in self.download_items.values():
            item.update_language()

    def open_settings(self):
        """打开设置页面"""
        from src.UI.set_config import SetConfig
        if not hasattr(self, 'settings_page') or not self.settings_page:
            self.settings_page = SetConfig()
            # 连接下载路径更改信号
            self.settings_page.download_path_changed.connect(self.update_download_path)
            # 初始语言同步已在SetConfig的__init__中完成
        self.settings_page.show()
        self.settings_page.raise_()
        self.settings_page.activateWindow()

    def update_global_speed(self):
        """更新全局下载速度"""
        total_speed = calculate_global_speed(self.download_items)
        speed_text = format_speed_display(total_speed)
        self.global_speed_label.setText(f"{language_manager.get_text('total_speed')}: {speed_text}")

    def show_download_error(self, work_id, error_msg):
        """显示下载错误对话框"""
        # 获取作品信息
        work_title = "未知作品"
        rj_display = work_id
        if work_id in self.download_items:
            work_info = self.download_items[work_id].work_info
            work_title = work_info.get('title', '未知作品')
            rj_display = work_info.get('source_id', f"RJ{work_id}")
        
        # 创建错误对话框
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle(language_manager.get_text('download_error'))
        msg_box.setText(f"{language_manager.get_text('download_failed')}")
        
        # 详细信息
        detail_text = f"作品: {rj_display} - {work_title}\n\n错误信息:\n{error_msg}\n\n下载队列已停止，请检查网络连接或稍后重试。"
        msg_box.setDetailedText(detail_text)
        
        # 设置按钮
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        
        # 更新状态标签
        self.status_label.setText(f"{language_manager.get_text('error')}: {rj_display} {language_manager.get_text('download_failed')}")
        
        # 显示对话框
        msg_box.exec()

    def auto_refresh_and_continue(self):
        """自动刷新列表并继续下载"""
        # 若用户在上一批完成后的延迟窗口内点了"停止"，则取消本次自动刷新，
        # 否则"刷新-下载"循环无法真正终止
        if not self.is_downloading_active or not self.auto_refresh_enabled:
            print("已停止下载，取消自动刷新")
            return

        print("开始执行自动刷新...")

        # 禁用刷新按钮，防止用户重复点击
        self.refresh_button.setEnabled(False)
        self.status_label.setText("正在获取新的下载列表...")
        
        # 创建新的下载列表线程
        self.auto_list_thread = DownloadListThread()
        self.auto_list_thread.list_updated.connect(self.on_auto_refresh_completed)
        self.auto_list_thread.error_occurred.connect(self.on_auto_refresh_failed)
        self.auto_list_thread.finished.connect(lambda: self.refresh_button.setEnabled(True))
        self.auto_list_thread.start()

    def on_auto_refresh_completed(self, works_list):
        """自动刷新完成，更新列表并自动开始下载"""
        print(f"自动刷新成功，获取到 {len(works_list)} 个新的下载项目")

        # 过滤掉本会话已多次失败的作品：它们不会被标记为已听，会在每次刷新时重复出现，
        # 若不剔除会对持续失败项(如已下架/404)形成无限重试循环
        pending = [w for w in works_list
                   if self.work_fail_counts.get(str(w['id']), 0) < self.MAX_WORK_RETRIES]
        exhausted_count = len(works_list) - len(pending)
        if exhausted_count:
            print(f"跳过 {exhausted_count} 个已达最大重试次数的失败作品")

        # 清空现有列表
        self.clear_all_items()

        # 添加可下载的新项
        for work in pending:
            self.add_download_item(work)

        self.count_label.setText(f"{language_manager.get_text('total_count')}: {len(pending)}")

        if pending:
            # 自动开始下载新列表
            print("自动开始下载新列表...")
            self.status_label.setText(f"已刷新列表，获取到 {len(pending)} 个新项目，正在自动开始下载...")

            # 等待所有详情加载完成后再开始下载
            QTimer.singleShot(2000, self.auto_start_downloads)
        else:
            # 没有可下载的新项(为空，或剩余项均已达最大重试次数)，停止自动循环
            print("没有可下载的新项目，停止自动下载")
            self.is_downloading_active = False
            self.start_all_button.setText(language_manager.get_text('start_download'))
            self.start_all_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
            if exhausted_count:
                self.status_label.setText(f"剩余 {exhausted_count} 个作品多次下载失败，已停止自动重试(可手动刷新重试)")
            else:
                self.status_label.setText("刷新完成，但没有新的下载项目")

    def on_auto_refresh_failed(self, error_msg):
        """自动刷新失败"""
        print(f"自动刷新失败: {error_msg}")
        
        # 停止自动下载
        self.is_downloading_active = False
        self.start_all_button.setText(language_manager.get_text('start_download'))
        self.start_all_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.status_label.setText(f"自动刷新失败: {error_msg}")

    def auto_start_downloads(self):
        """自动开始下载"""
        # 获取所有准备好的下载项
        ready_items = get_ready_download_items(self.download_layout, DownloadItemWidget)

        if ready_items:
            print(f"开始自动下载 {len(ready_items)} 个项目")
            
            # 使用工具函数开始下载
            if start_first_download_and_queue_others(ready_items, self.download_manager):
                # 保持下载状态
                self.status_label.setText(f"自动开始下载 {len(ready_items)} 个新项目")
        else:
            print("没有准备好的下载项目")
            # 等待一下再重试，可能详情还在加载中
            QTimer.singleShot(2000, self.check_and_retry_auto_start)

    def check_and_retry_auto_start(self):
        """检查并重试自动开始下载"""
        ready_items = get_ready_download_items(self.download_layout, DownloadItemWidget)

        if ready_items:
            self.auto_start_downloads()
        else:
            # 最终没有可下载的项目，停止自动下载
            print("重试后仍没有可下载的项目，停止自动下载")
            self.is_downloading_active = False
            self.start_all_button.setText(language_manager.get_text('start_download'))
            self.start_all_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
            self.status_label.setText("自动刷新完成，但没有可下载的项目")